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
    # Добавляем колонку username если её нет, и создаем таблицу
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, 
                       username TEXT,
                       referrer_id INTEGER, 
                       bought_friends INTEGER DEFAULT 0, 
                       expiry_date INTEGER DEFAULT 0,
                       is_active INTEGER DEFAULT 0)''')
    conn.commit(); conn.close()

init_db()

def get_user_id_by_username(identifier):
    # Очищаем юзернейм от @
    clean_name = identifier.replace("@", "").lower()
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    
    if identifier.isdigit():
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (identifier,))
    else:
        cursor.execute('SELECT user_id FROM users WHERE username = ?', (clean_name,))
    
    row = cursor.fetchone(); conn.close()
    return row[0] if row else None

def activate_user_in_db(user_id, active=1, add_months=1):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT expiry_date FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    now = int(time.time())
    added_time = add_months * 30 * 24 * 60 * 60
    expiry = (row[0] + added_time) if row and row[0] > now else (now + added_time)
    if active == 0: expiry = 0
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
    if not session: return "Error: API Session Failed"
    email = f"{(username or 'user').lower()}_{user_id}"
    u_uuid = str(uuid.uuid4())
    payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{"id": u_uuid, "email": email, "limitIp": 3, "totalGB": 53687091200, "expiryTime": expiry_ts * 1000, "enable": True, "subId": u_uuid}]})}
    try:
        r = session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload, timeout=10)
        if r.json().get('success'):
            host = PANEL_URL.split('://')[-1].split(':')[0]
            return f"{PANEL_URL.split('://')[0]}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"
    except: pass
    return "Error: Connection Failed"

# --- МЕНЮ ---
def main_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Партнерка", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")],
        [InlineKeyboardButton(text="⚖️ Юр. информация", callback_data="rules_menu")]
    ])

# --- КОМАНДЫ АДМИНА (/give и /take по юзернейму или ID) ---

@router.message(Command("give"))
async def admin_give(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS: return
    if not command.args: return await message.answer("Используй: `/give @username` или `/give ID`")
    
    uid = get_user_id_by_username(command.args)
    if not uid: return await message.answer("❌ Пользователь не найден в базе бота.")
    
    new_expiry = activate_user_in_db(uid, active=1, add_months=1)
    await message.answer(f"✅ Пользователю {command.args} (ID: {uid}) выдано 30 дней.")
    try: await bot.send_message(uid, "🎁 Администратор выдал вам 30 дней подписки!")
    except: pass

@router.message(Command("take"))
async def admin_take(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS: return
    if not command.args: return await message.answer("Используй: `/take @username` или `/take ID`")
    
    uid = get_user_id_by_username(command.args)
    if not uid: return await message.answer("❌ Пользователь не найден в базе.")
    
    activate_user_in_db(uid, active=0, add_months=0)
    await message.answer(f"🚫 Подписка пользователя {command.args} аннулирована.")
    try: await bot.send_message(uid, "🔴 Ваша подписка была аннулирована администратором.")
    except: pass

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    r_id = int(command.args) if command.args and command.args.isdigit() else None
    username = (message.from_user.username or "user").lower()
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('''INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?) 
                      ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username''', 
                   (message.from_user.id, username, r_id))
    conn.commit(); conn.close()
    await message.answer(f"👋 Привет, {hbold(message.from_user.full_name)}!\n\nДобро пожаловать в <b>TrubaVPN</b>.", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    sign = hashlib.md5(f"{FK_SHOP_ID}:250:{FK_SECRET_1}:RUB:ID_{callback.from_user.id}".encode()).hexdigest()
    url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa=250&currency=RUB&o=ID_{callback.from_user.id}&s={sign}"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить (250₽)", url=url)],
        [InlineKeyboardButton(text="✅ Оплачено", callback_data=f"paid_{callback.from_user.id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("🚀 <b>Тариф «Блатной»</b>\n30 дней / 50 ГБ / 3 устройства", reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT bought_friends FROM users WHERE user_id = ?', (callback.from_user.id,))
    row = cursor.fetchone(); conn.close()
    me = await bot.get_me()
    text = f"🤝 <b>Рефералка</b>\n\nПригласи 5 друзей и получи месяц!\n📈 Прогресс: {row[0] if row else 0}/5\n🔗 {hcode(f'https://t.me/{me.username}?start={callback.from_user.id}')}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 <b>Инструкция:</b>\n1. Скачай V2RayTun\n2. Вставь ссылку из ЛК.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT expiry_date, is_active FROM users WHERE user_id = ?', (callback.from_user.id,))
    d = cursor.fetchone(); conn.close()
    if not d or d[1] == 0: return await callback.message.edit_text("⚠️ Нет подписки.", reply_markup=main_markup())
    days = (d[0] - int(time.time())) // 86400
    await callback.message.edit_text(f"👤 <b>ЛК</b>\n⏳ Осталось: {max(0, int(days))} дн.", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery): await callback.message.edit_text("Меню:", reply_markup=main_markup())

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    await callback.answer("⏳ Ожидайте проверки...")
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выдать", callback_data=f"adm_ap_{callback.from_user.id}_{callback.from_user.username or 'user'}")], [InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]])
    for a in ADMINS: 
        try: await bot.send_message(a, f"💰 Оплата: @{callback.from_user.username} (ID: {callback.from_user.id})", reply_markup=m)
        except: pass

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    data = callback.data.split("_")
    uid, uname = int(data[2]), data[3]
    new_exp = activate_user_in_db(uid, active=1)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, uname, new_exp)
    if lnk.startswith("http"):
        await bot.send_message(uid, f"✅ Готово!\n{hcode(lnk)}", parse_mode="HTML")
        await callback.message.edit_text(f"✅ Выдано для {uname}")
    else: await callback.message.edit_text(f"❌ Ошибка: {lnk}")

@router.callback_query(F.data == "admin_delete_msg")
async def adm_del(callback: CallbackQuery): await callback.message.delete()

@router.callback_query(F.data == "rules_menu")
async def rules_menu(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📜 Соглашение", callback_data="tos")], [InlineKeyboardButton(text="🔒 Приватность", callback_data="privacy")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])
    await callback.message.edit_text("⚖️ Юр. данные", reply_markup=m)

@router.callback_query(F.data == "tos")
async def show_tos(callback: CallbackQuery):
    await callback.message.edit_text("📜 Мы вправе менять условия и отключать доступ за нарушения. Мы не несём ответственность за ваши действия в интернете. Пользуясь сервисом, вы соглашаетесь с данным положением", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="rules_menu")]]))

@router.callback_query(F.data == "privacy")
async def show_privacy(callback: CallbackQuery):
    await callback.message.edit_text("🔒 No-Logs policy. Только ID для работы.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="rules_menu")]]))

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
