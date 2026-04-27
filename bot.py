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
# Обязательно пропиши эти переменные в окружении или замени на значения
API_TOKEN = os.getenv('BOT_TOKEN')
FK_SHOP_ID = os.getenv('FK_SHOP_ID')      # ID магазина FreeKassa
FK_SECRET_1 = os.getenv('FK_SECRET_1')    # Секретный ключ №1
ADMINS = [int(os.getenv('ADMIN_ID_1', 0))] # Список ID администраторов

PANEL_URL = os.getenv('PANEL_URL')        # URL панели (например, http://1.2.3.4:2053)
SUB_PORT = os.getenv('SUB_PORT', '2096')  # Порт подписки (обычно 2096 для HTTPS)
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1                            # ID входящего подключения в 3X-UI

SUPPORT_CONTACT = "@vvvvvpppnn"           # Твой контакт поддержки

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
    conn.commit()
    conn.close()

init_db()

def get_user_data(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT expiry_date, is_active, username, current_plan, referrer_id, bought_friends FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_user_id_by_username(identifier):
    if not identifier: return None
    clean_name = identifier.replace("@", "").lower()
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    if identifier.isdigit():
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (identifier,))
    else:
        cursor.execute('SELECT user_id FROM users WHERE username = ?', (clean_name,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

async def activate_user_in_db(user_id, plan='shnir', active=1, months=3):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    now = int(time.time())
    added_time = months * 30 * 24 * 60 * 60
    
    cursor.execute('SELECT expiry_date, referrer_id, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    # Если подписка активна — продлеваем, если нет — считаем от текущего момента
    expiry = (row[0] + added_time) if row and row[0] > now else (now + added_time)
    ref_id = row[1] if row else None
    already_active = row[2] if row else 0
    
    if active == 0: expiry = 0
    
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ?, current_plan = ? WHERE user_id = ?', 
                   (active, expiry, plan, user_id))
    
    # Реферальный бонус за 5 приглашенных
    if active == 1 and not already_active and ref_id:
        cursor.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,))
        cursor.execute('SELECT bought_friends, expiry_date FROM users WHERE user_id = ?', (ref_id,))
        ref_data = cursor.fetchone()
        
        if ref_data and ref_data[0] > 0 and ref_data[0] % 5 == 0:
            bonus_time = 30 * 24 * 60 * 60
            new_ref_expiry = (ref_data[1] + bonus_time) if ref_data[1] > now else (now + bonus_time)
            cursor.execute('UPDATE users SET expiry_date = ?, is_active = 1 WHERE user_id = ?', (new_ref_expiry, ref_id))
            try:
                await bot.send_message(ref_id, f"🎁 <b>Бонус за рефералов!</b>\n\nВы пригласили 5 друзей, ваша подписка продлена на 30 дней!", parse_mode="HTML")
            except: pass
        
    conn.commit()
    conn.close()
    return expiry

# --- API ПАНЕЛИ ---
def get_3xui_session():
    s = requests.Session()
    base_url = PANEL_URL.strip('/')
    try:
        r = s.post(f"{base_url}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return s if r.status_code == 200 else None
    except: return None

def get_vpn_link(user_id, username, expiry_ts, plan='shnir'):
    session = get_3xui_session()
    if not session: return "Error: Auth Failed"
    
    limits = {
        'shnir': {'gb': 30, 'ips': 1},
        'avtoritet': {'gb': 100, 'ips': 3},
        'smotritel': {'gb': 500, 'ips': 10}
    }
    config = limits.get(plan, limits['shnir'])
    base_url = PANEL_URL.strip('/')
    email = f"{plan}_{user_id}"
    
    # Стабильный UUID на основе ID пользователя
    u_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"truba_{user_id}"))
    limit_bytes = config['gb'] * 1024 * 1024 * 1024
    
    payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{
        "id": u_uuid, "email": email, "limitIp": config['ips'], 
        "totalGB": limit_bytes, "expiryTime": expiry_ts * 1000, 
        "enable": True, "subId": u_uuid
    }]})}
    
    try:
        session.post(f"{base_url}/panel/api/inbounds/addClient", json=payload, timeout=10)
        host = base_url.split('://')[-1].split(':')[0]
        protocol = base_url.split('://')[0]
        return f"{protocol}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN_{plan.capitalize()}"
    except: return "Error: Connection Failed"

# --- КЛАВИАТУРЫ ---
def main_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Выбрать тариф (3 мес)", callback_data="tariffs")],
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
    r_id = int(command.args) if command.args and command.args.isdigit() and int(command.args) != message.from_user.id else None
    username = (message.from_user.username or "user").lower()
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username', (message.from_user.id, username, r_id))
    conn.commit()
    conn.close()
    await message.answer(f"🚀 {hbold('TrubaVPN Panel')}", reply_markup=main_kb)
    await message.answer("Главное меню:", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text(f"🚀 {hbold('TrubaVPN Panel')}\n\nГлавное меню:", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 Шнырь (150₽ / 3 мес)", callback_data="buy_shnir")],
        [InlineKeyboardButton(text="⭐ Авторитет (350₽ / 3 мес)", callback_data="buy_avtoritet")],
        [InlineKeyboardButton(text="👑 Смотрящий (500₽ / 3 мес)", callback_data="buy_smotritel")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    text = (
        "💎 <b>Доступные масти (подписка на 90 дней):</b>\n\n"
        "🔹 <b>Шнырь — 150₽</b>\n"
        "— Лимит трафика: 30 ГБ\n"
        "— Кол-во устройств: 1\n"
        "— Подходит для базового серфинга.\n\n"
        "⭐ <b>Авторитет — 350₽</b>\n"
        "— Лимит трафика: 100 ГБ\n"
        "— Кол-во устройств: 3\n"
        "— Оптимально для YouTube и соцсетей.\n\n"
        "👑 <b>Смотрящий — 500₽</b>\n"
        "— Лимит трафика: 500 ГБ\n"
        "— Кол-во устройств: 10\n"
        "— Максимальная скорость и жирный лимит."
    )
    await callback.message.edit_text(text, reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    plan = callback.data.split("_")[1]
    prices = {"shnir": 150, "avtoritet": 350, "smotritel": 500}
    price = prices.get(plan, 150)
    url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa={price}&currency=RUB&o=ID_{callback.from_user.id}_{plan}"
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {price}₽", url=url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"paid_{callback.from_user.id}_{plan}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tariffs")]
    ])
    await callback.message.edit_text(f"Вы выбрали тариф <b>{plan.capitalize()}</b>.\nСрок действия: 90 дней.", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    d = get_user_data(callback.from_user.id)
    now = int(time.time())
    if not d or d[1] == 0 or d[0] < now:
        return await callback.message.edit_text("👤 <b>Личный кабинет</b>\n\nСтатус: ❌ Подписка не активна.", reply_markup=back_btn(), parse_mode="HTML")
    
    await callback.answer("🔄 Синхронизация...")
    expiry_ts, plan = d[0], d[3]
    days = (expiry_ts - now) // 86400
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, callback.from_user.id, d[2], expiry_ts, plan)
    text = f"👤 <b>Личный кабинет</b>\n\nСтатус: ✅ Активен [{plan.capitalize()}]\nДо: {time.strftime('%d.%m.%Y', time.localtime(expiry_ts))} ({max(0, int(days))} дн.)\n\n🔗 <b>Ссылка:</b>\n{hcode(lnk)}"
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    d = get_user_data(callback.from_user.id)
    me = await bot.get_me()
    count = d[5] if d else 0
    link = f"https://t.me/{me.username}?start={callback.from_user.id}"
    text = (f"🤝 <b>Реферальная система</b>\n\n"
            f"За каждых <b>5 друзей</b>, купивших любую подписку, вы получаете <b>+1 месяц (30 дней)</b> бесплатного доступа!\n\n"
            f"Приглашено активных друзей: <b>{count}</b>\n"
            f"Прогресс до бонуса: <b>{count % 5}/5</b>\n\n"
            f"🔗 Твоя ссылка:\n{hcode(link)}")
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "about_menu")
async def about_menu(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Соглашение", callback_data="tos")],
        [InlineKeyboardButton(text="🔒 Приватность", callback_data="privacy")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT_CONTACT.replace('@','')}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("ℹ️ <b>О проекте TrubaVPN</b>", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "tos")
async def show_tos(callback: CallbackQuery):
    await callback.message.edit_text("<b>Условия использования:</b>\n1. Не спамить.\n2. Не перепродавать доступ.\n3. Не нарушать закон.", reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "privacy")
async def show_privacy(callback: CallbackQuery):
    await callback.message.edit_text("<b>Приватность:</b>\nМы не храним логи вашего трафика. Только ID Telegram для работы подписки.", reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 <b>Инструкция:</b>\n1. Качай V2RayTun (Android) или Streisand (iOS).\n2. Скопируй ссылку из профиля.\n3. Вставь ссылку в приложение и нажми Подключить.", reply_markup=back_btn(), parse_mode="HTML")

# --- АДМИНКА ---
@router.message(Command("give"))
async def admin_give(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS: return
    args = command.args.split() if command.args else []
    if len(args) < 2: return await message.answer("Ошибка! /give @username shnir/avtoritet/smotritel")
    target, plan = args[0], args[1].lower()
    uid = get_user_id_by_username(target)
    if not uid: return await message.answer("Юзер не найден.")
    new_exp = await activate_user_in_db(uid, plan=plan, active=1, months=3)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, target, new_exp, plan)
    await message.answer(f"✅ Выдано {target}")

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    d = callback.data.split("_")
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_ap_{d[1]}_{d[2]}")]])
    for a in ADMINS: 
        await bot.send_message(a, f"💰 Оплата {d[2]} от @{callback.from_user.username}", reply_markup=m)

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    d = callback.data.split("_")
    uid, plan = int(d[2]), d[3]
    new_exp = await activate_user_in_db(uid, plan=plan, active=1, months=3)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, "user", new_exp, plan)
    await bot.send_message(uid, f"✅ Оплата подтверждена!\n{hcode(lnk)}", parse_mode="HTML")
    await callback.message.edit_text(f"✅ Готово для {uid}")

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
