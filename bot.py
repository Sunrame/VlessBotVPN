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
    cursor.execute('SELECT expiry_date, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    now = int(time.time())
    added_time = add_months * 30 * 24 * 60 * 60
    
    if custom_expiry:
        expiry = custom_expiry
    else:
        if row and row[3] == 1 and row[2] > now:
            expiry = row[2] + added_time
        else:
            expiry = now + added_time
            
    if active == 0: expiry = 0
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ? WHERE user_id = ?', (active, expiry, user_id))
    conn.commit(); conn.close()

# --- API ПАНЕЛИ ---
def get_3xui_session():
    s = requests.Session()
    try:
        r = s.post(f"{PANEL_URL}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return s if r.status_code == 200 else None
    except: return None

def sync_with_panel(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        resp = session.get(f"{PANEL_URL}/panel/api/inbounds/get/{INBOUND_ID}", timeout=10)
        email = f"{(username or 'user').lower()}_{user_id}"
        obj = resp.json()['obj']
        clients = json.loads(obj['settings'])['clients']
        c_set = next((c for c in clients if c['email'] == email), None)
        if c_set and c_set.get('enable'):
            exp = c_set.get('expiryTime', 0) // 1000
            if exp > time.time() or exp == 0:
                activate_user_in_db(user_id, active=1, custom_expiry=exp)
                return True
        activate_user_in_db(user_id, active=0)
    except: pass
    return False

def get_vpn_link(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        u_uuid = str(uuid.uuid4())
        email = f"{(username or 'user').lower()}_{user_id}"
        limit = 50 * 1024 * 1024 * 1024
        exp = int((time.time() + (30 * 24 * 3600)) * 1000)
        payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{"id": u_uuid, "alterId": 0, "email": email, "limitIp": 3, "totalGB": limit, "expiryTime": exp, "enable": True, "subId": u_uuid}]})}
        r = session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload, timeout=10)
        if r.json().get('success'):
            host = PANEL_URL.rsplit(':', 1)[0]
            return f"{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"
    except: pass
    return None

# --- КНОПКИ ---
def main_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Партнерка", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")],
        [InlineKeyboardButton(text="⚖️ Пользовательское соглашение", callback_data="rules")]
    ])

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    r_id = int(command.args) if command.args and command.args.isdigit() else None
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username', (message.from_user.id, (message.from_user.username or "user").lower(), r_id))
    conn.commit(); conn.close()
    await asyncio.get_event_loop().run_in_executor(None, sync_with_panel, message.from_user.id, message.from_user.username)
    await message.answer(f"👋 Привет, {hbold(message.from_user.full_name)}!\n\nИспользуя бота, вы соглашаетесь с правилами сервиса.", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "rules")
async def show_rules(callback: CallbackQuery):
    rules_text = (
        "⚖️ <b>Пользовательское соглашение</b>\n\n"
        "1. Сервис предоставляет услуги доступа к частной сети (VPN) в ознакомительных целях.\n"
        "2. Персональные данные: Бот сохраняет ваш Telegram ID и Username для идентификации доступа. Данные не передаются третьим лицам.\n"
        "3. Ответственность: Пользователь несет полную ответственность за свои действия в сети Интернет при использовании сервиса. Запрещено использование сервиса для совершения противоправных действий согласно законодательству РФ.\n"
        "4. Возврат: Цифровые товары (подписки) возврату не подлежат после активации доступа.\n"
        "5. Ограничения: 1 аккаунт = до 3 устройств одновременно."
    )
    await callback.message.edit_text(rules_text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    await asyncio.get_event_loop().run_in_executor(None, sync_with_panel, callback.from_user.id, callback.from_user.username)
    d = get_user_db_data(callback.from_user.id)
    if not d or d[3] == 0:
        await callback.message.edit_text("⚠️ <b>Нет активной подписки.</b>", reply_markup=main_markup(), parse_mode="HTML")
        return
    days = (d[2] - int(time.time())) // 86400
    await callback.message.edit_text(f"👤 <b>Личный кабинет</b>\n\n⏳ Осталось: <b>{max(0, int(days))} дн.</b>\n📱 Лимит: 3 устройства", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    d = get_user_db_data(callback.from_user.id); me = await bot.get_me()
    count = d[1] if d else 0
    text = (f"🤝 <b>Партнерка</b>\n\nПригласи 5 друзей и получи <b>+1 месяц</b>!\n📈 Прогресс: <b>{count}/5</b>\n🔗 Ссылка: {hcode(f'https://t.me/{me.username}?start={callback.from_user.id}')}\n\n<i>После 5 приглашений счетчик обнуляется.</i>")
    markup = []
    if count >= 5: markup.append([InlineKeyboardButton(text="🎁 Забрать бонус", callback_data="claim_reward")])
    markup.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=markup), parse_mode="HTML")

@router.callback_query(F.data == "claim_reward")
async def claim_reward(callback: CallbackQuery):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT bought_friends FROM users WHERE user_id = ?', (callback.from_user.id,))
    if cursor.fetchone()[0] >= 5:
        cursor.execute('UPDATE users SET bought_friends = bought_friends - 5 WHERE user_id = ?', (callback.from_user.id,))
        conn.commit(); conn.close()
        activate_user_in_db(callback.from_user.id, active=1, add_months=1)
        await callback.answer("✅ Бонус начислен!", show_alert=True)
        await show_ref(callback)
    else: conn.close()

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    sign = hashlib.md5(f"{FK_SHOP_ID}:250:{FK_SECRET_1}:RUB:ID_{callback.from_user.id}".encode()).hexdigest()
    url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa=250&currency=RUB&o=ID_{callback.from_user.id}&s={sign}"
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить 250₽", url=url)], [InlineKeyboardButton(text="✅ Я оплатил!", callback_data=f"paid_{callback.from_user.id}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])
    await callback.message.edit_text("🚀 <b>Тариф «Блатной»</b>\n30 дней / 50 ГБ / 3 устройства", reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 <b>Инструкция Happ:</b>\n1. Скачай Happ.\n2. Копируй ссылку.\n3. Импортируй.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery): await callback.message.edit_text("Меню:", reply_markup=main_markup())

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
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, uname)
    if lnk:
        conn = sqlite3.connect('users.db'); cursor = conn.cursor()
        cursor.execute('SELECT referrer_id FROM users WHERE user_id = ?', (uid,))
        ref_id = cursor.fetchone()[0]
        if ref_id:
            cursor.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,))
            conn.commit()
        conn.close()
        activate_user_in_db(uid, active=1, add_months=1)
        await bot.send_message(uid, f"✅ Доступ активирован!\n\n{hcode(lnk)}", parse_mode="HTML")
    await callback.message.edit_text(f"✅ Выдано {uname}")

@router.callback_query(F.data == "admin_delete_msg")
async def adm_del(callback: CallbackQuery): await callback.message.delete()

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
