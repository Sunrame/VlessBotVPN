import os
import uuid
import requests
import logging
import time
import hashlib
import sqlite3
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.utils.markdown import hcode, hbold
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

# --- НАСТРОЙКИ ---
API_TOKEN = os.getenv('BOT_TOKEN')
FK_SHOP_ID = os.getenv('FK_SHOP_ID')
FK_SECRET_1 = os.getenv('FK_SECRET_1')
ADMINS = [int(os.getenv('ADMIN_ID_1', 0)), int(os.getenv('ADMIN_ID_2', 0))]

PANEL_URL = os.getenv('PANEL_URL')
SUB_PORT = os.getenv('SUB_PORT', '2096') 
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, 
                       referrer_id INTEGER, 
                       bought_friends INTEGER DEFAULT 0, 
                       reward_claimed INTEGER DEFAULT 0,
                       expiry_date TEXT,
                       is_active INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

# --- Вспомогательные функции для БД ---
def register_user(user_id, referrer_id=None):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, referrer_id) VALUES (?, ?)', (user_id, referrer_id))
    conn.commit()
    conn.close()

def get_user_db_data(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT referrer_id, bought_friends, reward_claimed, expiry_date, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def activate_user_in_db(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    # Считаем 30 дней от текущего момента
    expiry = int(time.time() + (30 * 24 * 60 * 60))
    cursor.execute('UPDATE users SET is_active = 1, expiry_date = ? WHERE user_id = ?', (expiry, user_id))
    conn.commit()
    conn.close()

# --- ЛОГИКА ПАНЕЛИ 3X-UI ---

def get_3xui_session():
    session = requests.Session()
    try:
        session.post(f"{PANEL_URL}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return session
    except:
        return None

def get_user_stats(user_id, username):
    session = get_3xui_session()
    if not session: return None
    
    try:
        # Ищем нашего клиента в списке входящих подключений
        response = session.get(f"{PANEL_URL}/panel/api/inbounds/get/{INBOUND_ID}", timeout=10)
        data = response.json()
        if not data.get('success'): return None
        
        import json
        settings = json.loads(data['obj']['settings'])
        client_email = f"{username or 'user'}_{user_id}"
        
        # Ищем статистику трафика
        client_stats = next((c for c in data['obj']['clientStats'] if c['email'] == client_email), None)
        # Ищем настройки клиента (лимит трафика)
        client_setting = next((c for c in settings['clients'] if c['email'] == client_email), None)
        
        if client_stats and client_setting:
            up = client_stats.get('up', 0)
            down = client_stats.get('down', 0)
            total_used = up + down
            limit = client_setting.get('totalGB', 0)
            return {"used": total_used, "limit": limit}
    except Exception as e:
        logging.error(f"Stat error: {e}")
    return None

def get_vpn_link(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        client_uuid = str(uuid.uuid4())
        client_email = f"{username or 'user'}_{user_id}"
        limit_gb = 50 * 1024 * 1024 * 1024
        expiry_time = int((time.time() + (30 * 24 * 3600)) * 1000)

        add_url = f"{PANEL_URL}/panel/api/inbounds/addClient"
        payload = {
            "id": INBOUND_ID,
            "settings": "{\"clients\": [{\"id\": \"" + client_uuid + "\", \"alterId\": 0, \"email\": \"" + client_email + "\", \"limitIp\": 1, \"totalGB\": " + str(limit_gb) + ", \"expiryTime\": " + str(expiry_time) + ", \"enable\": true, \"subId\": \"" + client_uuid + "\"}]}"
        }
        resp = session.post(add_url, json=payload, timeout=10)
        if resp.json().get('success'):
            base_url = PANEL_URL.rsplit(':', 1)[0]
            return f"{base_url}:{SUB_PORT}/sub/{client_uuid}?remark=TrubaVPN"
    except: pass
    return None

# --- МЕНЮ ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Партнерка", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")]
    ])

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    register_user(message.from_user.id, int(command.args) if command.args and command.args.isdigit() else None)
    await message.answer(f"👋 Привет! Это <b>TrubaVPN</b>.", reply_markup=main_menu(), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    db_data = get_user_db_data(callback.from_user.id)
    # db_data = (referrer_id, bought_friends, reward_claimed, expiry_date, is_active)
    
    if not db_data or not db_data[4]: # is_active
        await callback.message.edit_text("⚠️ <b>У вас нет активной подписки.</b>\n\nКупите тариф «Блатной», чтобы пользоваться VPN.", reply_markup=main_menu(), parse_mode="HTML")
        return

    stats = get_user_stats(callback.from_user.id, callback.from_user.username)
    
    # Расчет времени
    expiry_ts = int(db_data[3])
    days_left = (expiry_ts - time.time()) // (24 * 3600)
    
    # Расчет гигабайт
    if stats:
        used_gb = round(stats['used'] / (1024**3), 2)
        limit_gb = round(stats['limit'] / (1024**3), 2)
        remain_gb = round(limit_gb - used_gb, 2)
    else:
        used_gb, limit_gb, remain_gb = "??", "50", "??"

    text = (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"📋 <b>Тариф:</b> «Блатной»\n"
        f"⏳ <b>Осталось дней:</b> {max(0, int(days_left))}\n"
        f"📊 <b>Трафик:</b> {used_gb} ГБ из {limit_gb} ГБ\n"
        f"🔋 <b>Доступно:</b> {remain_gb} ГБ\n\n"
        f"<i>Информация обновляется раз в несколько минут.</i>"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(), parse_mode="HTML")

@router.callback_query(F.data == "admin_approve_")
@router.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve(callback: CallbackQuery):
    data = callback.data.split("_")
    user_id, username = int(data[2]), data[3]
    
    link = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, user_id, username)
    if link:
        activate_user_in_db(user_id) # Записываем активацию в БД
        await bot.send_message(user_id, f"✅ Доступ готов:\n{hcode(link)}")
        
        # Рефералка (код из прошлого шага)
        user_info = get_user_db_data(user_id)
        if user_info and user_info[0]:
            ref_id = user_info[0]
            conn = sqlite3.connect('users.db'); conn.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,)); conn.commit(); conn.close()
    
    await callback.message.edit_text(f"✅ Выдано для @{username}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]]))

# Остальные обработчики (tariffs, guide, to_main) оставляем такими же...
@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text("Выбери действие:", reply_markup=main_menu())

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    amount = 250
    order_id = f"ID_{callback.from_user.id}"
    sign = hashlib.md5(f"{FK_SHOP_ID}:{amount}:{FK_SECRET_1}:RUB:{order_id}".encode()).hexdigest()
    pay_url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa={amount}&currency=RUB&o={order_id}&s={sign}"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить 250₽", url=pay_url)],
        [InlineKeyboardButton(text="✅ Я оплатил!", callback_data=f"paid_{callback.from_user.id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("🚀 <b>Тариф «Блатной»</b>\n\n— 30 дней / 50 ГБ", reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 Инструкция: Скачай Happ и вставь ссылку.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")

@router.callback_query(F.data == "admin_delete_msg")
async def admin_delete_msg(callback: CallbackQuery):
    await callback.message.delete()

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
