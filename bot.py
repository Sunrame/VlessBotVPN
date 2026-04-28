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

# --- ТВОИ ССЫЛКИ НА ТОВАРЫ LAVA.TOP ---
LINKS = {
    "standart": "https://app.lava.top/products/851dc5e2-5f49-43f7-82c6-0dbd466974b7",
    "standart_plus": "https://app.lava.top/products/0351edae-7cec-45dc-bc71-52d437661ad5",
    "premium": "https://app.lava.top/products/f2e69243-0890-4546-83dc-7aa16a2bf068"
}

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = os.getenv('BOT_TOKEN')
ADMINS = [int(os.getenv('ADMIN_ID_1', 0))] # Твой Telegram ID должен быть тут

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

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, username TEXT, referrer_id INTEGER, 
                       bought_friends INTEGER DEFAULT 0, expiry_date INTEGER DEFAULT 0,
                       is_active INTEGER DEFAULT 0, current_plan TEXT DEFAULT 'none')''')
    conn.commit()
    conn.close()

init_db()

# --- ФУНКЦИИ АКТИВАЦИИ И VPN ---
async def activate_user_in_db(user_id, plan='Стандарт'):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    now = int(time.time())
    added_time = 30 * 24 * 60 * 60
    
    cursor.execute('SELECT expiry_date, referrer_id, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    expiry = (row[0] + added_time) if row and row[0] > now else (now + added_time)
    ref_id = row[1] if row else None
    already_active = row[2] if row else 0
    
    cursor.execute('UPDATE users SET is_active = 1, expiry_date = ?, current_plan = ? WHERE user_id = ?', (active, expiry, plan, user_id))
    
    if not already_active and ref_id:
        cursor.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_id,))
        cursor.execute('SELECT bought_friends FROM users WHERE user_id = ?', (ref_id,))
        ref_data = cursor.fetchone()
        if ref_data and ref_data[0] >= 5:
            forever = now + (100 * 365 * 24 * 60 * 60)
            cursor.execute('UPDATE users SET expiry_date = ?, is_active = 1, current_plan = "Премиум" WHERE user_id = ?', (forever, ref_id))
            try: await bot.send_message(ref_id, "🔥 Активен вечный Премиум за 5 друзей!")
            except: pass
    conn.commit()
    conn.close()

def get_3xui_session():
    s = requests.Session()
    try:
        r = s.post(f"{PANEL_URL.strip('/')}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return s if r.status_code == 200 else None
    except: return None

def get_vpn_link(user_id, expiry_ts, plan='Стандарт'):
    session = get_3xui_session()
    if not session: return "Ошибка связи"
    limits = {'Стандарт': {'gb': 50, 'ips': 1}, 'Стандарт +': {'gb': 0, 'ips': 1}, 'Премиум': {'gb': 0, 'ips': 3}}
    config = limits.get(plan, limits['Стандарт'])
    u_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"truba_v2_{user_id}"))
    limit_bytes = config['gb'] * 1024 * 1024 * 1024 if config['gb'] > 0 else 0
    payload = {"id": INBOUND_ID, "settings": json.dumps({"clients": [{"id": u_uuid, "email": str(user_id), "limitIp": config['ips'], "totalGB": limit_bytes, "expiryTime": expiry_ts * 1000, "enable": True, "subId": u_uuid}]})}
    try:
        session.post(f"{PANEL_URL.strip('/')}/panel/api/inbounds/addClient", json=payload, timeout=10)
        host = PANEL_URL.split('://')[-1].split(':')[0]
        return f"{PANEL_URL.split('://')[0]}://{host}:{SUB_PORT}/sub/{u_uuid}?remark=Truba_{plan.replace(' ', '_')}"
    except: return "Ошибка VPN"

# --- ОБРАБОТЧИКИ ---
@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    r_id = int(command.args) if command.args and command.args.isdigit() and int(command.args) != message.from_user.id else None
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username', (message.from_user.id, message.from_user.username, r_id))
    conn.commit()
    conn.close()
    await message.answer(f"🚀 {hbold('TrubaVPN')} на связи!", reply_markup=main_panel(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    btns = [
        [InlineKeyboardButton(text="Стандарт (100₽)", callback_data="buy_standart")],
        [InlineKeyboardButton(text="Стандарт + (150₽)", callback_data="buy_standart_plus")],
        [InlineKeyboardButton(text="Премиум (300₽)", callback_data="buy_premium")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ]
    await callback.message.edit_text("💎 Выберите тариф для покупки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@router.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: CallbackQuery):
    plan_key = callback.data.replace("buy_", "")
    pay_url = LINKS[plan_key]
    
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить на Lava.top", url=pay_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{callback.from_user.id}_{plan_key}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tariffs")]
    ])
    await callback.message.edit_text(f"Тариф: <b>{plan_key.upper()}</b>\n\nОплатите товар по ссылке, затем нажмите кнопку «Я оплатил».", reply_markup=m, parse_mode="HTML")

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    d = callback.data.split("_")
    uid, p_key = d[1], "_".join(d[2:])
    
    # Кнопка для админа
    adm_m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"adm_ap_{uid}_{p_key}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_dec_{uid}")]
    ])
    
    for a in ADMINS:
        await bot.send_message(a, f"💰 @{callback.from_user.username} заявляет об оплате <b>{p_key}</b>", reply_markup=adm_m, parse_mode="HTML")
    
    await callback.answer("⏳ Запрос отправлен админу. Ожидайте подтверждения!", show_alert=True)

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_approve(callback: CallbackQuery):
    plan_map = {"standart": "Стандарт", "standart_plus": "Стандарт +", "premium": "Премиум"}
    d = callback.data.split("_")
    uid, p_key = int(d[2]), "_".join(d[3:])
    
    await activate_user_in_db(uid, plan=plan_map.get(p_key, "Стандарт"))
    try:
        await bot.send_message(uid, f"✅ <b>Оплата подтверждена!</b>\nТариф {plan_map.get(p_key, 'Стандарт')} активирован. Зайдите в личный кабинет.", parse_mode="HTML")
    except: pass
    await callback.message.edit_text(f"✅ Активировано для {uid}")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT expiry_date, is_active, current_plan FROM users WHERE user_id = ?', (callback.from_user.id,))
    d = cursor.fetchone()
    conn.close()
    
    now = int(time.time())
    if not d or d[1] == 0 or d[0] < now:
        return await callback.message.edit_text("👤 Подписка не активна.", reply_markup=back_btn())
    
    await callback.answer("⏳ Генерирую ключ...")
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, callback.from_user.id, d[0], d[2])
    exp = "∞" if (d[0]-now) > 10**8 else time.strftime('%d.%m.%Y', time.localtime(d[0]))
    await callback.message.edit_text(f"👤 Кабинет\nТариф: {d[2]}\nДо: {exp}\n\nКлюч:\n{hcode(lnk)}", reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text("🚀 Меню:", reply_markup=main_panel())

def main_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Рефералы", callback_data="ref_program")],
        [InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="about_menu")]
    ])

def back_btn():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT bought_friends FROM users WHERE user_id = ?', (callback.from_user.id,))
    res = cursor.fetchone()
    conn.close()
    cnt = res[0] if res else 0
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={callback.from_user.id}"
    await callback.message.edit_text(f"🤝 Рефералы: {cnt}/5\n\nСсылка:\n{hcode(link)}", reply_markup=back_btn(), parse_mode="HTML")

@router.callback_query(F.data == "about_menu")
async def about_menu(callback: CallbackQuery):
    btns = [[InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT_CONTACT.replace('@','')}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]
    await callback.message.edit_text("📖 Сервис TrubaVPN\nБезопасный и быстрый доступ.", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
