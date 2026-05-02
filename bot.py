import os
import uuid
import requests
import logging
import time
import sqlite3
import asyncio
import json
from aiogram import Bot, Dispatcher, types, Router, F, BaseMiddleware
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.utils.markdown import hcode, hbold
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = os.getenv('BOT_TOKEN')
ADMINS = [int(os.getenv('ADMIN_ID_1', 0)), int(os.getenv('ADMIN_ID_2', 0))]

LINKS = {
    "standart": {
        "1": "https://app.lava.top/products/851dc5e2-5f49-43f7-82c6-0dbd466974b7",
        "3": "https://app.lava.top/products/71ee86dc-3764-4612-82c7-80085ef07183",
        "6": "https://app.lava.top/products/2ef5af01-730a-4a25-81be-c222483cc33d",
        "12": "https://app.lava.top/products/c5a053d5-aa8a-4c3f-a1b8-b57bf88a3ea6"
    },
    "standart_plus": {
        "1": "https://app.lava.top/products/0351edae-7cec-45dc-bc71-52d437661ad5",
        "3": "https://app.lava.top/products/b07fce1c-8a3e-4628-86aa-ef81f9dcd034",
        "6": "https://app.lava.top/products/53a834d5-010d-4b1e-813f-703bc4b0a074",
        "12": "https://app.lava.top/products/29ebbe84-9794-4908-967d-f526bd1866cd"
    },
    "premium": {
        "1": "https://app.lava.top/products/f2e69243-0890-4546-83dc-7aa16a2bf068",
        "3": "https://app.lava.top/products/b65ad027-6705-4faa-aca7-cec8e213fc4c",
        "6": "https://app.lava.top/products/e8c3b88d-90c2-4c06-b10e-d3609a83fba3",
        "12": "https://app.lava.top/products/140a5da6-2941-4e6a-8753-c706517371a0"
    }
}

PANEL_URL = os.getenv('PANEL_URL') 
SUB_PORT = os.getenv('SUB_PORT', '2096') 
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1 

SUPPORT_CONTACT = "@vvvvvpppnn"
CHANNEL_ID = "@Truba_VPN"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

# Хранилище для лимитов нажатий
payment_attempts = {}

# --- MIDDLEWARE ---
class JoinCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        if user_id in ADMINS:
            return await handler(event, data)
        try:
            member = await data['bot'].get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
            if member.status in ["left", "kicked"]:
                raise Exception()
        except Exception:
            text = f"❌ <b>Доступ ограничен!</b>\n\nДля использования бота необходимо подписаться на наш канал: {CHANNEL_ID}"
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_ID.replace('@','')}")],
                [InlineKeyboardButton(text="🔄 Я подписался", callback_data="to_main")]
            ])
            if isinstance(event, types.Message):
                await event.answer(text, reply_markup=markup, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer("Сначала подпишитесь на канал!", show_alert=True)
                await event.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return
        return await handler(event, data)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def check_payment_limit(user_id):
    now = time.time()
    if user_id not in payment_attempts:
        payment_attempts[user_id] = []
    payment_attempts[user_id] = [t for t in payment_attempts[user_id] if now - t < 3600]
    if len(payment_attempts[user_id]) >= 3:
        return int(3600 - (now - payment_attempts[user_id][0]))
    payment_attempts[user_id].append(now)
    return 0

def main_panel():
    btns = [
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs"), InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="🤝 Реф. программа", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 О сервисе", callback_data="about_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=btns)

# --- БАЗЫ ДАННЫХ ---
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
                       current_plan TEXT DEFAULT 'none',
                       last_notified INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT expiry_date, is_active, username, current_plan, referrer_id, bought_friends FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

async def activate_user_in_db(user_id, plan='Стандарт', active=1, months=1):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    now = int(time.time())
    added_time = int(months) * 30 * 24 * 60 * 60
    cursor.execute('SELECT expiry_date, referrer_id, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    expiry = (row[0] + added_time) if row and row[0] > now else (now + added_time)
    ref_id = row[1] if row else None
    already_active = row[2] if row else 0
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ?, current_plan = ? WHERE user_id = ?', (active, expiry, plan, user_id))
    if active == 1 and not already_active and ref_id:
        cursor.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,))
        cursor.execute('SELECT bought_friends FROM users WHERE user_id = ?', (ref_id,))
        ref_data = cursor.fetchone()
        if ref_data and ref_data[0] >= 5:
            forever_expiry = now + (100 * 365 * 24 * 60 * 60)
            cursor.execute('UPDATE users SET expiry_date = ?, is_active = 1, current_plan = "Премиум" WHERE user_id = ?', (forever_expiry, ref_id))
            try: await bot.send_message(ref_id, "🔥 <b>ЛЕГЕНДА!</b>\nВы пригласили 5 друзей. Вам начислена <b>БЕСКОНЕЧНАЯ</b> подписка!")
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

def check_client_in_panel(user_id):
    session = get_3xui_session()
    if not session: return None
    try:
        r = session.get(f"{PANEL_URL.strip('/')}/panel/api/inbounds/get/{INBOUND_ID}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            settings = json.loads(data['obj']['settings'])
            for client in settings['clients']:
                if client['email'].split('_')[0] == str(user_id):
                    return client
    except: pass
    return None

def get_vpn_link(user_id, username, expiry_ts, plan='Стандарт'):
    session = get_3xui_session()
    if not session: return "Ошибка связи"
    limits = {
        'Стандарт': {'gb': 50, 'ips': 1}, 
        'Стандарт +': {'gb': 0, 'ips': 1}, 
        'Премиум': {'gb': 0, 'ips': 3}
    }
    clean_plan = plan.split(' (')[0]
    config = limits.get(clean_plan, limits['Стандарт'])
    u_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"truba_v2_{user_id}"))
    limit_bytes = config['gb'] * 1024 * 1024 * 1024 if config['gb'] > 0 else 0
    display_name = f"{user_id}_{username}" if username else str(user_id)
    payload = {
        "id": INBOUND_ID, 
        "settings": json.dumps({
            "clients": [{
                "id": u_uuid, "email": display_name, "limitIp": config['ips'], 
                "totalGB": limit_bytes, "expiryTime": expiry_ts * 1000, 
                "enable": True, "subId": u_uuid
            }]
        })
    }
    try:
        session.post(f"{PANEL_URL.strip('/')}/panel/api/inbounds/addClient", json=payload, timeout=10)
        host = PANEL_URL.split('://')[-1].split(':')[0]
        return f"{PANEL_URL.split('://')[0]}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=Truba_{plan.replace(' ', '_')}"
    except: return "Ошибка VPN"

# --- ОБРАБОТЧИКИ ---

@router.message(Command("check"))
async def cmd_check_user(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS: return
    if not command.args: return await message.answer("⚠️ Введите ID: <code>/check 12345</code>", parse_mode="HTML")
    target_id = int(command.args) if command.args.isdigit() else 0
    user_data = get_user_data(target_id)
    if not user_data: return await message.answer("❌ Пользователь не найден в БД.")
    db_username = f"@{user_data[2]}" if user_data[2] else "Не установлен"
    plan_info = user_data[3] if user_data[3] != 'none' else "Нет"
    now = int(time.time())
    expiry_text = "Истекла" if user_data[0] <= now else (
        "Бессрочно ∞" if (user_data[0] - now) > (10 * 365 * 24 * 60 * 60) 
        else time.strftime('%d.%m.%Y', time.localtime(user_data[0]))
    )
    text = (f"🔍 <b>Информация:</b>\n\n🆔 ID: <code>{target_id}</code>\n👤 Юзер: {db_username}\n💎 Тариф: <b>{plan_info}</b>\n📅 До: <b>{expiry_text}</b>")
    await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    text = "💎 <b>Выберите тип тарифа:</b>\n\nВсе тарифы обеспечивают высокую скорость и обход блокировок."
    btns = [
        [InlineKeyboardButton(text="🔹 Стандарт (от 70₽)", callback_data="type_standart")],
        [InlineKeyboardButton(text="⭐ Стандарт + (от 105₽)", callback_data="type_standart_plus")],
        [InlineKeyboardButton(text="👑 Премиум (от 210₽)", callback_data="type_premium")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ]
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

@router.callback_query(F.data.startswith("type_"))
async def choose_duration(callback: CallbackQuery):
    t_type = callback.data.replace("type_", "")
    data = {
        "standart": {
            "name": "Стандарт", 
            "p": [100, 270, 480, 840], 
            "desc": "— Трафик: <b>50 ГБ</b>\n— Устройств: <b>1</b>\n— Локация: DE"
        },
        "standart_plus": {
            "name": "Стандарт +", 
            "p": [150, 405, 720, 1260], 
            "desc": "— Трафик: <b>БЕЗЛИМИТ</b>\n— Устройств: <b>1</b>\n— Локация: DE"
        },
        "premium": {
            "name": "Премиум", 
            "p": [300, 810, 1440, 2520], 
            "desc": "— Трафик: <b>БЕЗЛИМИТ</b>\n— Устройств: <b>до 3-х</b>\n— Приоритетная поддержка"
        }
    }
    info = data[t_type]
    months_list = [1, 3, 6, 12]
    
    text = (
        f"💳 <b>Тариф: {info['name']}</b>\n\n"
        f"{info['desc']}\n\n"
        f"—————\n"
        f"⏳ <b>Выберите срок подписки:</b>\n"
        f"<i>Чем дольше срок, тем больше выгода!</i>\n\n"
        f"🤝 <b>АКЦИЯ:</b> Пригласи 5 друзей и получи тариф <b>БЕСПЛАТНО НАВСЕГДА!</b>"
    )
    
    btns = []
    for idx, m in enumerate(months_list):
        total_price = info['p'][idx]
        price_per_month = total_price // m  # Расчет стоимости в месяц
        
        # Формируем текст кнопки: Срок — Общая цена (Цена в месяц/мес)
        btn_text = f"{m} мес. — {total_price}₽ ({price_per_month}₽/мес)"
        btns.append([InlineKeyboardButton(text=btn_text, callback_data=f"buy_{t_type}_{m}")])
    
    btns.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="tariffs")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    parts = callback.data.split("_")
    t_type, months = ("_".join(parts[1:-1]), parts[-1])
    plan_names = {"standart": "Стандарт", "standart_plus": "Стандарт +", "premium": "Премиум"}
    plan_display = f"{plan_names[t_type]} ({months} мес.)"
    url = LINKS[t_type][months]
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {plan_display}", url=url)],
        [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"paid_{callback.from_user.id}_{t_type}_{months}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"type_{t_type}")]
    ])
    await callback.message.edit_text(f"Вы выбрали <b>{plan_display}</b>.\n\nПосле оплаты нажмите кнопку проверки. Ключ нужно будет вставить в <b>HAPP</b>.", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    user_id = callback.from_user.id
    wait_time = check_payment_limit(user_id)
    if wait_time > 0:
        return await callback.answer(f"⚠️ Подождите {wait_time // 60} мин. до следующей попытки.", show_alert=True)

    d = callback.data.split("_")
    uid, months, t_type = d[1], d[-1], "_".join(d[2:-1])
    plan_names = {"standart": "Стандарт", "standart_plus": "Стандарт +", "premium": "Премиум"}
    p_name = f"{plan_names[t_type]} ({months} мес.)"
    
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_ap_{uid}_{t_type}_{months}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_dec_{uid}")]
    ])
    for a in ADMINS:
        if a != 0:
            try: await bot.send_message(a, f"💰 Заявка: <b>{p_name}</b> от @{callback.from_user.username}", reply_markup=m, parse_mode="HTML")
            except: pass
    await callback.answer("⏳ Заявка отправлена. Ожидайте подтверждения.", show_alert=True)

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    d = callback.data.split("_")
    uid, months = int(d[2]), d[-1]
    t_type = "_".join(d[3:-1])
    user_info = get_user_data(uid)
    plan_names = {"standart": "Стандарт", "standart_plus": "Стандарт +", "premium": "Премиум"}
    p_full_name = f"{plan_names[t_type]} ({months} мес.)"
    expiry_ts = await activate_user_in_db(uid, plan=p_full_name, months=months)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, user_info[2] if user_info else None, expiry_ts, p_full_name)
    try: await bot.send_message(uid, f"✅ <b>Оплата принята!</b>\n\nТариф: <b>{p_full_name}</b>\n🔗 <b>Ваш ключ:</b>\n{hcode(lnk)}", parse_mode="HTML")
    except: pass
    await callback.message.edit_text(f"✅ Выдано для {uid}")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    d = get_user_data(user_id)
    if not d: return await callback.answer("Нажмите /start", show_alert=True)
    now = int(time.time())
    panel_client = await asyncio.get_event_loop().run_in_executor(None, check_client_in_panel, user_id)
    if (d[1] == 0 or d[0] < now) and not panel_client:
        return await callback.message.edit_text("👤 <b>Личный кабинет</b>\n\nПодписка: ❌ Не активна.", 
                                               reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")
    await callback.answer("🔄 Загрузка...")
    expiry_date = d[0] if d[0] > now else (panel_client['expiryTime'] // 1000 if panel_client else now)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, user_id, d[2], expiry_date, d[3])
    expiry_text = "Бессрочно ∞" if (expiry_date - now) > (10 * 365 * 24 * 60 * 60) else time.strftime('%d.%m.%Y', time.localtime(expiry_date))
    text = f"👤 <b>Личный кабинет</b>\nТариф: {d[3]}\nДо: {expiry_text}\n\n🔗 <b>Ключ:</b>\n{hcode(lnk)}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")

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

@router.callback_query(F.data == "about_menu")
async def about_menu(callback: CallbackQuery):
    btns = [[InlineKeyboardButton(text="📜 Пользовательское Соглашение", url="https://telegra.ph/Soglashenie-ob-ispolzovanii-materialov-i-servisov-internet-sajta-04-27")],
            [InlineKeyboardButton(text="🛡 Политика Конфиденциальности ", url="https://telegra.ph/Politika-obrabotki-personalnyh-dannyh-servisa-TrubaVPN-04-27")],
            [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT_CONTACT.replace('@','')}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]
    await callback.message.edit_text("📖 <b>Информация:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns), parse_mode="HTML")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    d = get_user_data(callback.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={callback.from_user.id}"
    text = f"🤝 <b>Реферальная программа</b>\n\nПригласи 5 друзей и получи <b>ВЕЧНЫЙ ПРЕМИУМ</b>!\n\n👥 Приглашено: {d[5] if d else 0} / 5\n🔗 Ссылка:\n{hcode(link)}"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="HTML")

@router.callback_query(F.data.startswith("adm_dec_"))
async def adm_dec(callback: CallbackQuery):
    uid = int(callback.data.split("_")[2])
    try: await bot.send_message(uid, "❌ Администратор не подтвердил ваш платеж.")
    except: pass
    await callback.message.edit_text(f"❌ Отклонено для {uid}")

async def main():
    init_db()
    router.message.middleware(JoinCheckMiddleware())
    router.callback_query.middleware(JoinCheckMiddleware())
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    try: asyncio.run(main())
    except: pass
