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
        if row and row[2] > now:
            expiry = row[2] + added_time
        else:
            expiry = now + added_time
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
    if not session: return None
    email = f"{(username or 'user').lower()}_{user_id}"
    u_uuid = str(uuid.uuid4())
    limit = 50 * 1024 * 1024 * 1024
    exp_ms = expiry_ts * 1000 
    
    client_settings = {"id": u_uuid, "alterId": 0, "email": email, "limitIp": 3, "totalGB": limit, "expiryTime": exp_ms, "enable": True, "subId": u_uuid}
    
    try:
        payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [client_settings]})}
        r = session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload, timeout=10)
        res = r.json()
        
        if not res.get('success') and "already exists" in res.get('msg', '').lower():
            session.post(f"{PANEL_URL}/panel/api/inbounds/updateClient/{u_uuid}", json=payload, timeout=10)
            return f"{PANEL_URL.rsplit(':', 1)[0]}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"

        if res.get('success'):
            return f"{PANEL_URL.rsplit(':', 1)[0]}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"
    except: pass
    return None

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
    await message.answer(f"👋 Привет, {hbold(message.from_user.full_name)}!\n\nДобро пожаловать в <b>TrubaVPN</b>. Используя @trubavpnbot, вы автоматически принимаете условия соглашения.", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "rules_menu")
async def rules_menu(callback: CallbackQuery):
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Пользовательское соглашение", callback_data="tos")],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data="privacy")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("⚖️ <b>Юридический отдел TrubaVPN</b>\n\nВыберите документ:", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "tos")
async def show_tos(callback: CallbackQuery):
    text = (
        "📜 <b>ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ</b>\n\n"
        "1. <b>Общие положения:</b> Настоящее Соглашение является публичной офертой. Используя @trubavpnbot, вы принимаете условия в полном объеме.\n\n"
        "2. <b>Права Исполнителя:</b> Мы оставляем за собой право в одностороннем порядке:\n"
        "— Изменять стоимость подписки и параметры тарифов;\n"
        "— Приостанавливать доступ при обнаружении вредоносной активности;\n"
        "— Редактировать текст Соглашения без предварительного уведомления.\n\n"
        "3. <b>Ограничения:</b> Запрещено использование для DDoS, спама и взломов. Лимит — 3 устройства.\n\n"
        "4. <b>Отказ от ответственности:</b> Сервис предоставляется «КАК ЕСТЬ». Мы не гарантируем доступность ресурсов, заблокированных РКН.\n\n"
        "5. <b>Возврат:</b> Цифровой контент возврату не подлежит после активации.\n\n"
        "🆘 Поддержка: @hhhhaahahaha"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="rules_menu")]]), parse_mode="HTML")

@router.callback_query(F.data == "privacy")
async def show_privacy(callback: CallbackQuery):
    text = (
        "🔒 <b>ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ</b>\n\n"
        "1. <b>Сбор данных:</b> Мы храним только ваш Telegram ID и сроки подписки для обеспечения работы сервиса.\n\n"
        "2. <b>No-Logs Policy:</b> TrubaVPN <b>НЕ</b> собирает и <b>НЕ</b> хранит:\n"
        "— Историю посещенных сайтов;\n"
        "— Содержимое трафика и DNS-запросы;\n"
        "— IP-адреса ресурсов.\n\n"
        "3. <b>Безопасность:</b> Мы не передаем ваши данные третьим лицам.\n\n"
        "4. <b>Изменения:</b> Продолжение использования бота после обновления Политики означает ваше автоматическое согласие.\n\n"
        "🆘 Поддержка: @hhhhaahahaha"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="rules_menu")]]), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    d = get_user_db_data(callback.from_user.id)
    if not d or d[3] == 0:
        await callback.message.edit_text("⚠️ <b>Нет активной подписки.</b>", reply_markup=main_markup(), parse_mode="HTML")
        return
    days = (d[2] - int(time.time())) // 86400
    await callback.message.edit_text(f"👤 <b>Личный кабинет</b>\n\n⏳ Осталось: <b>{max(0, int(days))} дн.</b>\n📱 Лимит: 3 устройства", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    sign = hashlib.md5(f"{FK_SHOP_ID}:250:{FK_SECRET_1}:RUB:ID_{callback.from_user.id}".encode()).hexdigest()
    url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa=250&currency=RUB&o=ID_{callback.from_user.id}&s={sign}"
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Купить (250₽)", url=url)], [InlineKeyboardButton(text="✅ Оплачено", callback_data=f"paid_{callback.from_user.id}")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])
    await callback.message.edit_text("🚀 <b>Тариф «Блатной»</b>\n30 дней / 50 ГБ / 3 устройства", reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery): await callback.message.edit_text("Выберите действие:", reply_markup=main_markup())

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    await callback.message.answer("⏳ Заявка на проверку отправлена админам.")
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Выдать", callback_data=f"adm_ap_{callback.from_user.id}_{callback.from_user.username or 'user'}")], [InlineKeyboardButton(text="🗑 Удалить", callback_data="admin_delete_msg")]])
    for a in ADMINS: 
        try: await bot.send_message(a, f"💰 Оплата: @{callback.from_user.username}", reply_markup=m)
        except: pass

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    _, _, uid, uname = callback.data.split("_"); uid = int(uid)
    new_expiry_ts = activate_user_in_db(uid, active=1, add_months=1)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, uname, new_expiry_ts)
    if lnk:
        await bot.send_message(uid, f"✅ Подписка активирована!\n\nТвоя ссылка:\n{hcode(lnk)}", parse_mode="HTML")
        await callback.message.edit_text(f"✅ Выдано для {uname}")
    else:
        await callback.answer("Ошибка панели!", show_alert=True)

@router.callback_query(F.data == "admin_delete_msg")
async def adm_del(callback: CallbackQuery): await callback.message.delete()

async def main():
    dp.include_router(router); await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
