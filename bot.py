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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton

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

SUPPORT_CONTACT = "@vvvvvpppnn"

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
    conn.commit(); conn.close()

init_db()

def get_user_id_by_username(identifier):
    if not identifier: return None
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
    base_url = PANEL_URL.strip('/')
    try:
        r = s.post(f"{base_url}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=15)
        return s if r.status_code == 200 else None
    except: return None

def get_vpn_link(user_id, username, expiry_ts):
    session = get_3xui_session()
    if not session: return "Error: Auth Failed"
    base_url = PANEL_URL.strip('/')
    email = f"{(username or 'user').lower()}_{user_id}"
    u_uuid = str(uuid.uuid4())
    limit_bytes = 50 * 1024 * 1024 * 1024
    payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{"id": u_uuid, "email": email, "limitIp": 3, "totalGB": limit_bytes, "expiryTime": expiry_ts * 1000, "enable": True, "subId": u_uuid}]})}
    try:
        r = session.post(f"{base_url}/panel/api/inbounds/addClient", json=payload, timeout=15)
        res = r.json()
        if res.get('success'):
            host = base_url.split('://')[-1].split(':')[0]
            protocol = base_url.split('://')[0]
            return f"{protocol}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"
        return f"Error: {res.get('msg')}"
    except: return "Error: Connection Failed"

# --- КЛАВИАТУРЫ ---
def main_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Купить VPN (Тарифы)", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Реферальная система", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Как подключить?", callback_data="guide")],
        [InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="about_menu")]
    ])

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])

main_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="/start")]], resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    r_id = int(command.args) if command.args and command.args.isdigit() else None
    username = (message.from_user.username or "user").lower()
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username', (message.from_user.id, username, r_id))
    conn.commit(); conn.close()
    
    await message.answer(f"🚀 {hbold('TrubaVPN Panel')}\n\nДобро пожаловать! Твой личный доступ к свободному интернету.", reply_markup=main_kb)
    await message.answer("Выбери нужный раздел:", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text(f"🚀 {hbold('TrubaVPN Panel')}\n\nГлавное меню:", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "about_menu")
async def about_menu(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", callback_data="tos")],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data="privacy")],
        [InlineKeyboardButton(text="🆘 Написать в поддержку", url=f"https://t.me/{SUPPORT_CONTACT.replace('@','')}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("ℹ️ <b>О сервисе TrubaVPN</b>\n\nМы обеспечиваем высокую скорость, шифрование трафика и доступ к любым ресурсам без ограничений.", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "tos")
async def show_tos(callback: CallbackQuery):
    text = (
        "<b>Пользовательское соглашение</b>\n\n"
        "1. Сервис предоставляет услуги VPN доступа.\n"
        "2. Мы не несем ответственности за действия пользователей.\n"
        "3. Возврат средств осуществляется только в случае технической неисправности сервиса.\n"
        "4. Запрещено использование сервиса для спама и хакерских атак."
    )
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "privacy")
async def show_privacy(callback: CallbackQuery):
    text = (
        "<b>Политика конфиденциальности</b>\n\n"
        "1. Мы придерживаемся политики No-Logs: мы не знаем, что вы делаете в сети.\n"
        "2. Для работы нужен только ваш ID Telegram.\n"
        "3. Мы не передаем данные третьим лицам, так как нам просто нечего передавать."
    )
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT expiry_date, is_active, username FROM users WHERE user_id = ?', (callback.from_user.id,))
    d = cursor.fetchone(); conn.close()
    
    if not d or d[1] == 0:
        return await callback.message.edit_text("👤 <b>Личный кабинет</b>\n\nПодписка: ❌ Не активна\nКупи VPN, чтобы быть в сети.", reply_markup=back_btn(), parse_mode="HTML")
    
    await callback.answer("⏳ Получаю ссылку...")
    expiry_ts, username = d[0], (d[2] or "user")
    days = (expiry_ts - int(time.time())) // 86400
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, callback.from_user.id, username, expiry_ts)
    
    link_display = f"🔗 <b>Твоя ссылка (VLESS):</b>\n{hcode(lnk)}" if lnk.startswith("http") else "⚠️ Ошибка API."
    text = f"👤 <b>Личный кабинет</b>\n\nСтатус: ✅ Активен\nДействует до: {time.strftime('%d.%m.%Y', time.localtime(expiry_ts))} ({max(0, int(days))} дн.)\n\n{link_display}"
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    sign = hashlib.md5(f"{FK_SHOP_ID}:250:{FK_SECRET_1}:RUB:ID_{callback.from_user.id}".encode()).hexdigest()
    url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa=250&currency=RUB&o=ID_{callback.from_user.id}&s={sign}"
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Купить за 250₽", url=url)], [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"paid_{callback.from_user.id}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])
    await callback.message.edit_text("💎 <b>VPN Тарифы</b>\n\n— 30 дней доступа\n— 50 ГБ трафика\n— Все локации\n— До 3-х устройств", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 <b>Как подключить VPN?</b>\n\n1. Скачай V2RayTun (Android) или Streisand (iOS).\n2. Скопируй ссылку из профиля.\n3. Вставь ссылку в приложение и нажми Подключить.", reply_markup=back_btn(), parse_mode="HTML")

# --- КОМАНДЫ ГИВ/ТЕЙК И ОСТАЛЬНОЕ (БЕЗ ИЗМЕНЕНИЙ) ---

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    await callback.answer("⏳ Запрос отправлен админу!", show_alert=True)
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выдать", callback_data=f"adm_ap_{callback.from_user.id}_{callback.from_user.username or 'user'}")], [InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]])
    for a in ADMINS: 
        try: await bot.send_message(a, f"💰 <b>Запрос оплаты</b>\nОт: @{callback.from_user.username}", reply_markup=m, parse_mode="HTML")
        except: pass

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    d = callback.data.split("_")
    uid, uname = int(d[2]), d[3]
    new_exp = activate_user_in_db(uid, active=1)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, uname, new_exp)
    if lnk.startswith("http"):
        await bot.send_message(uid, f"✅ Оплата подтверждена!\n\nТвоя ссылка:\n{hcode(lnk)}", parse_mode="HTML")
        await callback.message.edit_text(f"✅ Выдано для {uname}")
    else: await callback.message.edit_text(f"❌ Ошибка")

@router.callback_query(F.data == "admin_delete_msg")
async def adm_del(callback: CallbackQuery): await callback.message.delete()

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
