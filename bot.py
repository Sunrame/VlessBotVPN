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
                       is_active INTEGER DEFAULT 0,
                       current_plan TEXT DEFAULT 'none')''')
    conn.commit(); conn.close()

init_db()

def get_user_data(user_id):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT expiry_date, is_active, username, current_plan FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone(); conn.close()
    return row

def activate_user_in_db(user_id, plan='shnir', active=1, months=3):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    now = int(time.time())
    added_time = months * 30 * 24 * 60 * 60
    
    cursor.execute('SELECT expiry_date FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    expiry = (row[0] + added_time) if row and row[0] > now else (now + added_time)
    
    if active == 0: expiry = 0
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ?, current_plan = ? WHERE user_id = ?', 
                   (active, expiry, plan, user_id))
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

def get_vpn_link(user_id, username, expiry_ts, plan='shnir'):
    session = get_3xui_session()
    if not session: return "Error: Auth Failed"
    
    # Настройки лимитов по тарифам
    limits = {
        'shnir': {'gb': 30, 'ips': 1},
        'avtoritet': {'gb': 100, 'ips': 3},
        'smotritel': {'gb': 500, 'ips': 10}
    }
    config = limits.get(plan, limits['shnir'])
    
    base_url = PANEL_URL.strip('/')
    email = f"{plan}_{user_id}"
    u_uuid = str(uuid.uuid4())
    limit_bytes = config['gb'] * 1024 * 1024 * 1024
    
    payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{
        "id": u_uuid, "email": email, "limitIp": config['ips'], 
        "totalGB": limit_bytes, "expiryTime": expiry_ts * 1000, 
        "enable": True, "subId": u_uuid
    }]})}
    
    try:
        r = session.post(f"{base_url}/panel/api/inbounds/addClient", json=payload, timeout=15)
        if r.json().get('success'):
            host = base_url.split('://')[-1].split(':')[0]
            protocol = base_url.split('://')[0]
            return f"{protocol}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN_{plan.capitalize()}"
        return f"Error: {r.json().get('msg')}"
    except: return "Error: Connection Failed"

# --- КЛАВИАТУРЫ ---
def main_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Выбрать тариф (на 3 месяца)", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Рефералы", callback_data="ref_program")],
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
    await message.answer(f"🚀 {hbold('TrubaVPN Panel')}\nДобро пожаловать в цифровой централ.", reply_markup=main_kb)
    await message.answer("Выбери масть (тариф) или зайди в кабинет:", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text(f"🚀 {hbold('TrubaVPN Panel')}\nГлавное меню:", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Шнырь (150₽ / 3 мес)", callback_data="buy_shnir")],
        [InlineKeyboardButton(text="⭐ Авторитет (350₽ / 3 мес)", callback_data="buy_avtoritet")],
        [InlineKeyboardButton(text="👑 Смотрящий (500₽ / 3 мес)", callback_data="buy_smotritel")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    text = (
        "💎 <b>Актуальные масти (на 90 дней):</b>\n\n"
        "🔹 <b>Шнырь</b> — 150₽\n(30 ГБ, 1 устройство)\n\n"
        "⭐ <b>Авторитет</b> — 350₽\n(100 ГБ, 3 устройства)\n\n"
        "👑 <b>Смотрящий</b> — 500₽\n(500 ГБ, 10 устройств, VIP приоритет)"
    )
    await callback.message.edit_text(text, reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    plan = callback.data.split("_")[1]
    prices = {"shnir": 150, "avtoritet": 350, "smotritel": 500}
    price = prices.get(plan, 150)
    
    sign = hashlib.md5(f"{FK_SHOP_ID}:{price}:{FK_SECRET_1}:RUB:ID_{callback.from_user.id}_{plan}".encode()).hexdigest()
    url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa={price}&currency=RUB&o=ID_{callback.from_user.id}_{plan}&s={sign}"
    
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {price}₽", url=url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"paid_{callback.from_user.id}_{plan}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tariffs")]
    ])
    await callback.message.edit_text(f"Вы выбрали тариф: <b>{plan.capitalize()}</b>\nСрок: 90 дней.\nК оплате: {price}₽", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    d = get_user_data(callback.from_user.id)
    if not d or d[1] == 0:
        return await callback.message.edit_text("👤 <b>Личный кабинет</b>\n\nСтатус: ❌ Пусто\nВозьми тариф, чтобы быть на связи.", reply_markup=back_btn(), parse_mode="HTML")
    
    await callback.answer("⏳ Соединяюсь с сервером...")
    expiry_ts, plan = d[0], d[3]
    days = (expiry_ts - int(time.time())) // 86400
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, callback.from_user.id, d[2], expiry_ts, plan)
    
    text = (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"Масть: <b>{plan.capitalize()}</b>\n"
        f"Действует до: {time.strftime('%d.%m.%Y', time.localtime(expiry_ts))} ({max(0, int(days))} дн.)\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n{hcode(lnk)}"
    )
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "about_menu")
async def about_menu(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Соглашение", callback_data="tos")],
        [InlineKeyboardButton(text="🔒 Приватность", callback_data="privacy")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT_CONTACT.replace('@','')}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("ℹ️ <b>TrubaVPN Info</b>\n\nРаботаем четко, логов не ведем, скорость держим.", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "tos")
async def show_tos(callback: CallbackQuery):
    await callback.message.edit_text("<b>Соглашение:</b>\n1. Не спамить.\n2. Не ломать.\n3. Деньги не возвращаем, если всё работает.", reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "privacy")
async def show_privacy(callback: CallbackQuery):
    await callback.message.edit_text("<b>Приватность:</b>\nМы не знаем, кто вы и куда заходите. Полная анонимность.", reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 <b>Инструкция:</b>\n1. Качай V2RayTun.\n2. Копируй ссылку из профиля.\n3. Вставляй и жми кнопку.", reply_markup=back_btn(), parse_mode="HTML")

# --- АДМИНКА ---
@router.message(Command("give"))
async def admin_give(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS: return
    args = command.args.split() if command.args else []
    if len(args) < 2: return await message.answer("Используй: /give @username shnir/avtoritet/smotritel")
    
    target, plan = args[0], args[1].lower()
    uid = get_user_id_by_username(target)
    if not uid: return await message.answer("Юзер не найден в БД.")
    
    new_exp = activate_user_in_db(uid, plan=plan, active=1, months=3)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, target, new_exp, plan)
    
    try:
        await bot.send_message(uid, f"🎁 Админ выдал тебе статус <b>{plan.capitalize()}</b>!\n\nСсылка:\n{hcode(lnk)}", parse_mode="HTML")
        await message.answer(f"✅ Выдано {target} (план {plan})")
    except: await message.answer(f"Ошибка отправки, но в базе обновлено. Ссылка: {hcode(lnk)}")

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    data = callback.data.split("_")
    uid, plan = data[1], data[2]
    await callback.answer("⏳ Запрос отправлен!", show_alert=True)
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_ap_{uid}_{plan}")]])
    for a in ADMINS:
        await bot.send_message(a, f"💰 Оплата за <b>{plan}</b> от @{callback.from_user.username}", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    d = callback.data.split("_")
    uid, plan = int(d[2]), d[3]
    new_exp = activate_user_in_db(uid, plan=plan, active=1, months=3)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, "user", new_exp, plan)
    await bot.send_message(uid, f"✅ Оплата принята! Твой статус: {plan}\nСсылка:\n{hcode(lnk)}", parse_mode="HTML")
    await callback.message.edit_text(f"✅ Активирован {plan}")

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
