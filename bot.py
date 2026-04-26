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
                       username TEXT,
                       referrer_id INTEGER, 
                       bought_friends INTEGER DEFAULT 0, 
                       reward_claimed INTEGER DEFAULT 0,
                       expiry_date INTEGER DEFAULT 0,
                       is_active INTEGER DEFAULT 0)''')
    try: cursor.execute('ALTER TABLE users ADD COLUMN username TEXT')
    except: pass
    conn.commit(); conn.close()

init_db()

def register_user(user_id, username, referrer_id=None):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    un_low = username.lower() if username else None
    cursor.execute('''INSERT INTO users (user_id, username, referrer_id) 
                      VALUES (?, ?, ?) 
                      ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username''', 
                   (user_id, un_low, referrer_id))
    conn.commit(); conn.close()

def get_user_db_data(user_id):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT referrer_id, bought_friends, reward_claimed, expiry_date, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone(); conn.close()
    return row

def activate_user_in_db(user_id, active=1):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    # Сохраняем дату как число (timestamp)
    expiry = int(time.time() + (30 * 24 * 60 * 60)) if active == 1 else 0
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ? WHERE user_id = ?', (active, expiry, user_id))
    conn.commit(); conn.close()

# --- ЛОГИКА ПАНЕЛИ ---
def get_3xui_session():
    s = requests.Session()
    try:
        s.post(f"{PANEL_URL}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return s
    except: return None

def delete_vpn_client(user_id, username):
    session = get_3xui_session()
    if not session: return False
    try:
        email = f"{username or 'user'}_{user_id}"
        resp = session.post(f"{PANEL_URL}/panel/api/inbounds/delClient/{INBOUND_ID}", data={"email": email}, timeout=10)
        return resp.json().get('success')
    except: return False

def get_user_stats(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        resp = session.get(f"{PANEL_URL}/panel/api/inbounds/get/{INBOUND_ID}", timeout=10)
        data = resp.json()
        settings = json.loads(data['obj']['settings'])
        email = f"{username or 'user'}_{user_id}"
        stats = next((c for c in data['obj']['clientStats'] if c['email'] == email), None)
        sett = next((c for c in settings['clients'] if c['email'] == email), None)
        if stats and sett:
            return {"used": stats.get('up', 0) + stats.get('down', 0), "limit": sett.get('totalGB', 0)}
    except: pass
    return None

def get_vpn_link(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        u_uuid = str(uuid.uuid4())
        email = f"{username or 'user'}_{user_id}"
        limit = 50 * 1024 * 1024 * 1024
        exp = int((time.time() + (30 * 24 * 3600)) * 1000)
        payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{"id": u_uuid, "alterId": 0, "email": email, "limitIp": 1, "totalGB": limit, "expiryTime": exp, "enable": True, "subId": u_uuid}]})}
        r = session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload, timeout=10)
        if r.json().get('success'):
            host = PANEL_URL.rsplit(':', 1)[0]
            return f"{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"
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
    r_id = int(command.args) if command.args and command.args.isdigit() else None
    register_user(message.from_user.id, message.from_user.username, r_id)
    await message.answer(f"👋 Привет, {hbold(message.from_user.full_name)}!", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    d = get_user_db_data(callback.from_user.id)
    # d = (referrer_id, bought_friends, reward_claimed, expiry_date, is_active)
    
    # ПРОВЕРКА: Если в базе флаг is_active не равен 1
    if not d or int(d[4]) != 1:
        await callback.message.edit_text("⚠️ <b>Нет активной подписки.</b>\n\nКупите тариф, чтобы пользоваться VPN.", reply_markup=main_markup(), parse_mode="HTML")
        return
    
    st = get_user_stats(callback.from_user.id, callback.from_user.username)
    
    # Считаем разницу между сохраненным timestamp и текущим
    now = int(time.time())
    expiry_ts = int(d[3]) if d[3] else 0
    days = (expiry_ts - now) // 86400
    
    u, l = (round(st['used']/(1024**3), 2), round(st['limit']/(1024**3), 2)) if st else ("??", "50")
    
    text = (f"👤 <b>Личный кабинет</b>\n\n"
            f"📋 Тариф: «Блатной»\n"
            f"⏳ Осталось дней: {max(0, int(days))}\n"
            f"📊 Трафик: {u} / {l} ГБ")
    
    await callback.message.edit_text(text, reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    sign = hashlib.md5(f"{FK_SHOP_ID}:250:{FK_SECRET_1}:RUB:ID_{callback.from_user.id}".encode()).hexdigest()
    pay_url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa=250&currency=RUB&o=ID_{callback.from_user.id}&s={sign}"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить 250₽", url=pay_url)],
        [InlineKeyboardButton(text="✅ Я оплатил!", callback_data=f"paid_{callback.from_user.id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("🚀 <b>Тариф «Блатной»</b>\n30 дней / 50 ГБ", reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    await callback.message.answer("⏳ Запрос отправлен админам. Ожидайте подтверждения.")
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выдать", callback_data=f"adm_ap_{callback.from_user.id}_{callback.from_user.username or 'user'}")], [InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]])
    for a in ADMINS: 
        try: await bot.send_message(a, f"💰 Оплата: @{callback.from_user.username} (ID: {callback.from_user.id})", reply_markup=m)
        except: pass

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    _, _, uid, uname = callback.data.split("_")
    uid = int(uid)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, uname)
    if lnk:
        activate_user_in_db(uid, active=1) # ОБЯЗАТЕЛЬНО АКТИВИРУЕМ В БД
        await bot.send_message(uid, f"✅ Доступ готов:\n{hcode(lnk)}")
        
        # Рефералка
        u_data = get_user_db_data(uid)
        if u_data and u_data[0]:
            ref_id = u_data[0]
            conn = sqlite3.connect('users.db'); conn.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,)); conn.commit(); conn.close()

    await callback.message.edit_text(f"✅ Выдано для @{uname}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]]))

@router.message(Command("give"))
async def admin_give(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS or not command.args: return
    t = command.args.replace("@", "").lower().strip()
    conn = sqlite3.connect('users.db'); c = conn.cursor()
    if t.isdigit(): c.execute('SELECT user_id, username FROM users WHERE user_id = ?', (int(t),))
    else: c.execute('SELECT user_id, username FROM users WHERE username = ?', (t,))
    r = c.fetchone(); conn.close()
    if r:
        lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, r[0], r[1])
        if lnk:
            activate_user_in_db(r[0], active=1)
            await bot.send_message(r[0], f"🎁 Доступ выдан!\n{hcode(lnk)}")
            await message.answer(f"✅ Успешно выдано {r[1]}")
    else: await message.answer("❌ Юзер не найден.")

@router.message(Command("take"))
async def admin_take(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS or not command.args: return
    t = command.args.replace("@", "").lower().strip()
    conn = sqlite3.connect('users.db'); c = conn.cursor()
    if t.isdigit(): c.execute('SELECT user_id, username FROM users WHERE user_id = ?', (int(t),))
    else: c.execute('SELECT user_id, username FROM users WHERE username = ?', (t,))
    r = c.fetchone(); conn.close()
    if r:
        deleted = await asyncio.get_event_loop().run_in_executor(None, delete_vpn_client, r[0], r[1])
        activate_user_in_db(r[0], active=0) # ДЕАКТИВИРУЕМ
        await bot.send_message(r[0], "⚠️ Ваша подписка была аннулирована.")
        await message.answer(f"🚫 Подписка у @{r[1]} отобрана.")
    else: await message.answer("❌ Юзер не найден.")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    d = get_user_db_data(callback.from_user.id)
    me = await bot.get_me()
    await callback.message.edit_text(f"🤝 <b>Партнерка</b>\n📈 Прогресс: {d[1] if d else 0}/5\n🔗 Ссылка:\n{hcode(f'https://t.me/{me.username}?start={callback.from_user.id}')}", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery): await callback.message.edit_text("Меню:", reply_markup=main_markup())

@router.callback_query(F.data == "admin_delete_msg")
async def adm_del(callback: CallbackQuery): await callback.message.delete()

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
