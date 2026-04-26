import os
import uuid
import requests
import logging
import time
import hashlib
import sqlite3
import asyncio
import json
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.utils.markdown import hcode, hbold
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

# --- НАСТРОЙКИ ---
API_TOKEN = os.getenv('BOT_TOKEN')
FK_SHOP_ID = os.getenv('FK_SHOP_ID')
FK_SECRET_1 = os.getenv('FK_SECRET_1')
# ID админов из переменных Railway
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

# --- БАЗА ДАННЫХ (SQLite) ---
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, 
                       username TEXT,
                       referrer_id INTEGER, 
                       bought_friends INTEGER DEFAULT 0, 
                       reward_claimed INTEGER DEFAULT 0,
                       expiry_date TEXT,
                       is_active INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def register_user(user_id, username, referrer_id=None):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    username_low = username.lower() if username else None
    cursor.execute('''INSERT INTO users (user_id, username, referrer_id) 
                      VALUES (?, ?, ?) 
                      ON CONFLICT(user_id) DO UPDATE SET username = ?''', 
                   (user_id, username_low, referrer_id, username_low))
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
        response = session.get(f"{PANEL_URL}/panel/api/inbounds/get/{INBOUND_ID}", timeout=10)
        data = response.json()
        settings = json.loads(data['obj']['settings'])
        client_email = f"{username or 'user'}_{user_id}"
        
        stats = next((c for c in data['obj']['clientStats'] if c['email'] == client_email), None)
        sett = next((c for c in settings['clients'] if c['email'] == client_email), None)
        if stats and sett:
            return {"used": stats.get('up', 0) + stats.get('down', 0), "limit": sett.get('totalGB', 0)}
    except: pass
    return None

def get_vpn_link(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        client_uuid = str(uuid.uuid4())
        client_email = f"{username or 'user'}_{user_id}"
        limit_gb = 50 * 1024 * 1024 * 1024
        expiry_time = int((time.time() + (30 * 24 * 3600)) * 1000)

        payload = {
            "id": INBOUND_ID,
            "settings": json.dumps({"clients": [{"id": client_uuid, "alterId": 0, "email": client_email, "limitIp": 1, "totalGB": limit_gb, "expiryTime": expiry_time, "enable": True, "subId": client_uuid}]})
        }
        resp = session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload, timeout=10)
        if resp.json().get('success'):
            base_url = PANEL_URL.rsplit(':', 1)[0]
            return f"{base_url}:{SUB_PORT}/sub/{client_uuid}?remark=TrubaVPN"
    except: pass
    return None

# --- МЕНЮ ---
def main_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Партнерка", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")]
    ])

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    register_user(message.from_user.id, message.from_user.username, ref_id)
    await message.answer(f"👋 Привет, {hbold(message.from_user.full_name)}! Это <b>TrubaVPN</b>.", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    db_data = get_user_db_data(callback.from_user.id)
    if not db_data or not db_data[4]:
        await callback.message.edit_text("⚠️ <b>Нет активной подписки.</b>", reply_markup=main_markup(), parse_mode="HTML")
        return

    stats = get_user_stats(callback.from_user.id, callback.from_user.username)
    days_left = (int(db_data[3]) - time.time()) // (24 * 3600)
    
    u, l = (round(stats['used']/(1024**3), 2), round(stats['limit']/(1024**3), 2)) if stats else ("??", "50")
    text = (f"👤 <b>Личный кабинет</b>\n\n📋 <b>Тариф:</b> «Блатной»\n⏳ <b>Осталось дней:</b> {max(0, int(days_left))}\n"
            f"📊 <b>Трафик:</b> {u} ГБ из {l} ГБ")
    await callback.message.edit_text(text, reply_markup=main_markup(), parse_mode="HTML")

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
    await callback.message.edit_text("🚀 <b>Тариф «Блатной»</b>\n\n— 30 дней / 50 ГБ\n\nОплати и нажми кнопку подтверждения:", reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data.startswith("paid_"))
async def user_confirm_payment(callback: CallbackQuery):
    await callback.message.answer("⏳ Запрос отправлен админам.")
    user_id, user_name = callback.from_user.id, callback.from_user.username or "user"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать", callback_data=f"adm_ap_{user_id}_{user_name}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_delete_msg")]
    ])
    for adm in ADMINS:
        await bot.send_message(adm, f"💰 Оплата: @{user_name} (ID: {user_id})", reply_markup=markup)

@router.callback_query(F.data.startswith("adm_ap_"))
async def admin_approve(callback: CallbackQuery):
    _, _, u_id, u_name = callback.data.split("_")
    u_id = int(u_id)
    
    link = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, u_id, u_name)
    if link:
        activate_user_in_db(u_id)
        await bot.send_message(u_id, f"✅ Доступ готов:\n{hcode(link)}")
        
        # Рефералка
        u_data = get_user_db_data(u_id)
        if u_data and u_data[0]:
            ref_id = u_data[0]
            conn = sqlite3.connect('users.db'); conn.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,)); conn.commit(); conn.close()
    
    await callback.message.edit_text(f"✅ Выдано для @{u_name}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]]))

@router.message(Command("give"))
async def admin_give(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS or not command.args: return
    target = command.args.replace("@", "").lower().strip()
    
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    if target.isdigit(): cursor.execute('SELECT user_id, username FROM users WHERE user_id = ?', (int(target),))
    else: cursor.execute('SELECT user_id, username FROM users WHERE username = ?', (target,))
    row = cursor.fetchone(); conn.close()
    
    if row:
        link = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, row[0], row[1])
        if link:
            activate_user_in_db(row[0])
            await bot.send_message(row[0], f"🎁 Бонус:\n{hcode(link)}")
            await message.answer(f"✅ Выдано пользователю {row[1]}")
    else: await message.answer("❌ Юзер не найден в базе.")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    data = get_user_db_data(callback.from_user.id)
    bot_un = (await bot.get_me()).username
    text = (f"🤝 <b>Партнерка</b>\n\nПригласи 5 друзей и получи месяц бесплатно!\n\n"
            f"📈 Прогресс: <b>{data[1] if data else 0}/5</b>\n🔗 Ссылка:\n{hcode(f'https://t.me/{bot_un}?start={callback.from_user.id}')}")
    await callback.message.edit_text(text, reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 Инструкция: Скачай Happ и вставь ссылку из бота.", reply_markup=main_markup())

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text("Выбери действие:", reply_markup=main_markup())

@router.callback_query(F.data == "admin_delete_msg")
async def admin_del(callback: CallbackQuery):
    await callback.message.delete()

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
