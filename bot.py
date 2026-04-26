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

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = os.getenv('BOT_TOKEN')
FK_SHOP_ID = os.getenv('FK_SHOP_ID')
FK_SECRET_1 = os.getenv('FK_SECRET_1')
ADMINS = [int(os.getenv('ADMIN_ID_1', 0)), int(os.getenv('ADMIN_ID_2', 0))]

PANEL_URL = os.getenv('PANEL_URL')  # Напр: http://1.2.3.4:2053
SUB_PORT = os.getenv('SUB_PORT', '2096') 
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1  # УБЕДИСЬ, ЧТО ID В ПАНЕЛИ СОВПАДАЕТ

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
                       username TEXT,
                       referrer_id INTEGER, 
                       bought_friends INTEGER DEFAULT 0, 
                       expiry_date INTEGER DEFAULT 0,
                       is_active INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def get_user_db_data(user_id):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT referrer_id, bought_friends, expiry_date, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone(); conn.close()
    return row

def activate_user_in_db(user_id, active=1, custom_expiry=None, add_months=1):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT expiry_date FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    now = int(time.time())
    added_time = add_months * 30 * 24 * 60 * 60
    expiry = (row[0] + added_time) if row and row[0] > now else (now + added_time)
    if custom_expiry: expiry = custom_expiry
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ? WHERE user_id = ?', (active, expiry, user_id))
    conn.commit(); conn.close()
    return expiry

# --- API ПАНЕЛИ ---
def get_3xui_session():
    s = requests.Session()
    try:
        r = s.post(f"{PANEL_URL}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return s if r.status_code == 200 else None
    except: return None

def get_vpn_link(user_id, username, expiry_ts):
    session = get_3xui_session()
    if not session: return "Error: Ошибка входа в панель"
    
    email = f"{(username or 'user').lower()}_{user_id}"
    u_uuid = str(uuid.uuid4())
    limit = 50 * 1024 * 1024 * 1024
    exp_ms = expiry_ts * 1000 
    
    client_data = {"id": u_uuid, "alterId": 0, "email": email, "limitIp": 3, "totalGB": limit, "expiryTime": exp_ms, "enable": True, "subId": u_uuid}
    
    try:
        # Пробуем добавить
        payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [client_data]})}
        r = session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload, timeout=10)
        res = r.json()
        
        # Если клиент уже был (например, перепокупка), пробуем обновить существующего по email
        if not res.get('success') and "already exists" in res.get('msg', '').lower():
            # В данном API обновление часто идет через addClient (зависит от версии), 
            # но если не сработало, значит нужно сначала удалить старого.
            # Для надежности просто вернем ошибку админу, чтобы он удалил дубликат в панели.
            return f"Error: Клиент {email} уже есть в панели. Удали его вручную и нажми Выдать снова."

        if res.get('success'):
            host = PANEL_URL.split('://')[-1].split(':')[0]
            proto = PANEL_URL.split('://')[0]
            return f"{proto}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"
        else:
            return f"Panel Error: {res.get('msg')}"
    except Exception as e:
        return f"System Error: {str(e)}"

# --- МЕНЮ ---
def main_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Партнерка", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")],
        [InlineKeyboardButton(text="⚖️ Юр. информация", callback_data="rules_menu")]
    ])

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    r_id = int(command.args) if command.args and command.args.isdigit() else None
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username', (message.from_user.id, (message.from_user.username or "user").lower(), r_id))
    conn.commit(); conn.close()
    await message.answer(f"👋 Привет, {hbold(message.from_user.full_name)}!\n\nДобро пожаловать в <b>TrubaVPN</b>. Используя @trubavpnbot, вы принимаете условия соглашения.", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "rules_menu")
async def rules_menu(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Соглашение", callback_data="tos")],
        [InlineKeyboardButton(text="🔒 Приватность", callback_data="privacy")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("⚖️ <b>Юридическая информация</b>", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "tos")
async def show_tos(callback: CallbackQuery):
    text = (
        "📜 <b>ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ</b>\n\n"
        "1. <b>Общие правила:</b> Сервис предоставляется «как есть». Мы не несем ответственности за блокировки ресурсов.\n"
        "2. <b>Право на изменения:</b> Администрация @trubavpnbot вправе в любое время в одностороннем порядке менять стоимость, лимиты и условия предоставления услуг без уведомления.\n"
        "3. <b>Отказ в обслуживании:</b> Мы оставляем за собой право отозвать подписку без возврата средств при нарушении правил (спам, взломы, более 3-х устройств).\n"
        "4. <b>Возврат:</b> Цифровые услуги обмену и возврату не подлежат."
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="rules_menu")]]), parse_mode="HTML")

@router.callback_query(F.data == "privacy")
async def show_privacy(callback: CallbackQuery):
    text = (
        "🔒 <b>ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ</b>\n\n"
        "1. <b>Данные:</b> Мы храним только ваш Telegram ID для работы подписки.\n"
        "2. <b>No-Logs:</b> Мы принципиально не записываем историю ваших посещений и не храним данные о трафике.\n"
        "3. <b>Согласие:</b> Пользуясь ботом, вы соглашаетесь на обработку этих данных."
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="rules_menu")]]), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    d = get_user_db_data(callback.from_user.id)
    if not d or d[3] == 0:
        await callback.message.edit_text("⚠️ Активной подписки нет.", reply_markup=main_markup())
        return
    days = (d[2] - int(time.time())) // 86400
    await callback.message.edit_text(f"👤 <b>Кабинет</b>\n⏳ Дней: {max(0, int(days))}\n📱 Лимит: 3 устройства", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    await callback.message.answer("⏳ Заявка отправлена.")
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выдать", callback_data=f"adm_ap_{callback.from_user.id}_{callback.from_user.username or 'user'}")], [InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]])
    for a in ADMINS: 
        try: await bot.send_message(a, f"💰 Оплата: @{callback.from_user.username}", reply_markup=m)
        except: pass

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    _, _, uid, uname = callback.data.split("_"); uid = int(uid)
    new_expiry_ts = activate_user_in_db(uid, active=1, add_months=1)
    
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, uname, new_expiry_ts)
    
    if lnk.startswith("http"):
        await bot.send_message(uid, f"✅ Подписка активирована!\n\n{hcode(lnk)}", parse_mode="HTML")
        await callback.message.edit_text(f"✅ Успешно выдано: {uname}")
    else:
        # Если ошибка — бот напишет ее админу прямо в чат
        await callback.message.edit_text(f"❌ Ошибка: {lnk}")

@router.callback_query(F.data == "admin_delete_msg")
async def adm_del(callback: CallbackQuery): await callback.message.delete()

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery): await callback.message.edit_text("Меню:", reply_markup=main_markup())

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
