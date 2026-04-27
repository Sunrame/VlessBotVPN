import os
import uuid
import requests
import logging
import time
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
ADMINS = [int(os.getenv('ADMIN_ID_1', 0))]

PANEL_URL = os.getenv('PANEL_URL') 
SUB_PORT = os.getenv('SUB_PORT', '2096') 
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1 

SUPPORT_CONTACT = "@RSConnectHelp_bot"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

# --- БЛОК БАЗЫ ДАННЫХ (ВЕЧНАЯ ПАМЯТЬ) ---
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

async def activate_user_in_db(user_id, plan='standart', active=1, months=1):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    now = int(time.time())
    added_time = months * 30 * 24 * 60 * 60
    cursor.execute('SELECT expiry_date, referrer_id, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    expiry = (row[0] + added_time) if row and row[0] > now else (now + added_time)
    ref_id = row[1] if row else None
    already_active = row[2] if row else 0
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ?, current_plan = ? WHERE user_id = ?', (active, expiry, plan, user_id))
    
    if active == 1 and not already_active and ref_id:
        cursor.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,))
        cursor.execute('SELECT bought_friends, expiry_date FROM users WHERE user_id = ?', (ref_id,))
        ref_data = cursor.fetchone()
        if ref_data and ref_data[0] > 0 and ref_data[0] % 5 == 0:
            bonus = 30 * 24 * 60 * 60
            new_ref_expiry = (ref_data[1] + bonus) if ref_data[1] > now else (now + bonus)
            cursor.execute('UPDATE users SET expiry_date = ?, is_active = 1 WHERE user_id = ?', (new_ref_expiry, ref_id))
            try: await bot.send_message(ref_id, "🎁 Бонус за рефералов! +30 дней подписки начислено.")
            except: pass
    conn.commit()
    conn.close()
    return expiry

# --- API ПАНЕЛИ ---
def get_3xui_session():
    s = requests.Session()
    try:
        r = s.post(f"{PANEL_URL.strip('/')}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return s if r.status_code == 200 else None
    except: return None

def get_vpn_link(user_id, expiry_ts, plan='standart'):
    session = get_3xui_session()
    if not session: return "Ошибка связи"
    limits = {
        'standart': {'gb': 50, 'ips': 1}, 
        'premium': {'gb': 0, 'ips': 1}, 
        'premium_plus': {'gb': 0, 'ips': 3}
    }
    config = limits.get(plan, limits['standart'])
    u_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"truba_v2_{user_id}"))
    limit_bytes = config['gb'] * 1024 * 1024 * 1024 if config['gb'] > 0 else 0
    
    payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{"id": u_uuid, "email": f"{plan}_{user_id}", "limitIp": config['ips'], "totalGB": limit_bytes, "expiryTime": expiry_ts * 1000, "enable": True, "subId": u_uuid}]})}
    try:
        session.post(f"{PANEL_URL.strip('/')}/panel/api/inbounds/addClient", json=payload, timeout=10)
        host = PANEL_URL.split('://')[-1].split(':')[0]
        return f"{PANEL_URL.split('://')[0]}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=Truba_{plan.capitalize()}"
    except: return "Ошибка VPN"

# --- КЛАВИАТУРЫ ---
def main_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Выбрать тариф", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Рефералы", callback_data="ref_program")],
        [InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="about_menu")]
    ])

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    r_id = int(command.args) if command.args and command.args.isdigit() and int(command.args) != message.from_user.id else None
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username', (message.from_user.id, message.from_user.username, r_id))
    conn.commit()
    conn.close()
    await message.answer(f"🚀 {hbold('TrubaVPN')} готов к работе!", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text(f"🚀 {hbold('TrubaVPN')} Главное меню:", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    text = (
        "💎 <b>Актуальные тарифы:</b>\n\n"
        "🔹 <b>Стандарт — 100₽ / мес</b>\n"
        "— Лимит трафика: 50 ГБ\n"
        "— Устройств: 1\n\n"
        "⭐ <b>Премиум — 150₽ / мес</b>\n"
        "— Лимит трафика: БЕЗЛИМИТ\n"
        "— Устройств: 1\n\n"
        "👑 <b>Премиум Plus — 300₽ / мес</b>\n"
        "— Лимит трафика: БЕЗЛИМИТ\n"
        "— Устройств: 3"
    )
    btns = [
        [InlineKeyboardButton(text="Стандарт (100₽)", callback_data="buy_standart")],
        [InlineKeyboardButton(text="Премиум (150₽)", callback_data="buy_premium")],
        [InlineKeyboardButton(text="Премиум Plus (300₽)", callback_data="buy_premium_plus")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    plan = callback.data.split("_")[1]
    if "plus" in callback.data: plan = "premium_plus"
    prices = {"standart": 100, "premium": 150, "premium_plus": 300}
    price = prices.get(plan, 100)
    url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa={price}&currency=RUB&o=ID_{callback.from_user.id}_{plan}"
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {price}₽", url=url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"paid_{callback.from_user.id}_{plan}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tariffs")]
    ])
    await callback.message.edit_text(f"Вы выбрали тариф <b>{plan.replace('_', ' ').capitalize()}</b>.", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    d = get_user_data(callback.from_user.id)
    now = int(time.time())
    if not d or d[1] == 0 or d[0] < now:
        return await callback.message.edit_text("👤 <b>Личный кабинет</b>\n\nПодписка: ❌ Не активна.", reply_markup=back_btn(), parse_mode="HTML")
    
    await callback.answer("🔄 Загрузка...")
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, callback.from_user.id, d[0], d[3])
    text = f"👤 <b>Личный кабинет</b>\nТариф: {d[3].replace('_', ' ').capitalize()}\nДо: {time.strftime('%d.%m.%Y', time.localtime(d[0]))}\n\n🔗 <b>Ссылка:</b>\n{hcode(lnk)}"
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "about_menu")
async def about_menu(callback: CallbackQuery):
    text = (
        "📖 <b>О сервисе TrubaVPN</b>\n\n"
        "Мы предоставляем быстрый и анонимный доступ в интернет. "
        "Для нас важна ваша безопасность и прозрачность отношений.\n\n"
        "Ознакомьтесь с официальными документами сервиса по ссылкам ниже:"
    )
    btns = [
        [InlineKeyboardButton(text="📜 Пользовательское соглашение", url="https://telegra.ph/Soglashenie-ob-ispolzovanii-materialov-i-servisov-internet-sajta-04-27")],
        [InlineKeyboardButton(text="🛡 Политика конфиденциальности", url="https://telegra.ph/Politika-obrabotki-personalnyh-dannyh-servisa-TrubaVPN-04-27")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT_CONTACT.replace('@','')}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    d = get_user_data(callback.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={callback.from_user.id}"
    text = f"🤝 <b>Рефералы</b>\nПригласи 5 друзей — получи +30 дней!\n\nПриглашено: {d[5]}\nСсылка: {hcode(link)}"
    await callback.message.edit_text(text, reply_markup=back_btn(), parse_mode="HTML")

# --- АДМИНКА ---
@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    d = callback.data.split("_")
    plan = "_".join(d[2:])
    m = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_ap_{d[1]}_{plan}")]])
    for a in ADMINS:
        await bot.send_message(a, f"💰 Заявка на <b>{plan}</b> от @{callback.from_user.username}", reply_markup=m, parse_mode="HTML")
    await callback.answer("⏳ Ожидайте подтверждения администратором", show_alert=True)

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    d = callback.data.split("_")
    uid, plan = int(d[2]), "_".join(d[3:])
    new_exp = await activate_user_in_db(uid, plan=plan)
    await bot.send_message(uid, f"✅ Оплата принята! Тариф <b>{plan.capitalize()}</b> активирован.", parse_mode="HTML")
    await callback.message.edit_text(f"✅ Готово для {uid}")

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
