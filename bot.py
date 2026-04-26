import os
import uuid
import requests
import logging
import time
import hashlib
import sqlite3
import asyncio
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.utils.markdown import hcode, hbold, hlink
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

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    # Таблица пользователей: id, кто пригласил, сколько друзей купили, статус реф-награды
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, referrer_id INTEGER, bought_friends INTEGER DEFAULT 0, reward_claimed INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def register_user(user_id, referrer_id=None):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, referrer_id) VALUES (?, ?)', (user_id, referrer_id))
    conn.commit()
    conn.close()

def get_user_data(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT referrer_id, bought_friends, reward_claimed FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def add_bought_friend(referrer_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (referrer_id,))
    conn.commit()
    conn.close()

# --- ЛОГИКА ПАНЕЛИ ---
def get_vpn_link(user_id, username):
    session = requests.Session()
    try:
        session.post(f"{PANEL_URL}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        client_uuid = str(uuid.uuid4())
        client_email = f"{username or 'user'}_{user_id}"
        limit_gb = 50 * 1024 * 1024 * 1024
        duration = 30 * 24 * 60 * 60 * 1000
        expiry_time = int((time.time() * 1000) + duration)

        add_url = f"{PANEL_URL}/panel/api/inbounds/addClient"
        payload = {
            "id": INBOUND_ID,
            "settings": "{\"clients\": [{\"id\": \"" + client_uuid + "\", \"alterId\": 0, \"email\": \"" + client_email + "\", \"limitIp\": 1, \"totalGB\": " + str(limit_gb) + ", \"expiryTime\": " + str(expiry_time) + ", \"enable\": true, \"subId\": \"" + client_uuid + "\"}]}"
        }
        response = session.post(add_url, json=payload, timeout=10)
        if response.json().get('success'):
            base_url = PANEL_URL.rsplit(':', 1)[0]
            return f"{base_url}:{SUB_PORT}/sub/{client_uuid}?remark=TrubaVPN"
        return None
    except Exception as e:
        logging.error(f"Error: {e}")
        return None

# --- МЕНЮ ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Партнерка", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")],
        [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/твой_логин")]
    ])

# --- ОБРАБОТЧИКИ ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    args = command.args
    referrer_id = int(args) if args and args.isdigit() else None
    
    # Регаем пользователя
    register_user(message.from_user.id, referrer_id)
    
    await message.answer(
        f"👋 Привет, {hbold(message.from_user.full_name)}!\n\n"
        f"Это <b>TrubaVPN</b>. Выбери действие:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    data = get_user_data(callback.from_user.id)
    # data = (referrer_id, bought_friends, reward_claimed)
    bought_count = data[1] if data else 0
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={callback.from_user.id}"
    
    text = (
        f"🤝 <b>Партнерская программа</b>\n\n"
        f"Пригласи 5 друзей, которые купят подписку, и получи <b>1 месяц бесплатно!</b>\n\n"
        f"📈 Твой прогресс: <b>{bought_count}/5</b> покупок\n\n"
        f"🔗 Твоя ссылка:\n{hcode(ref_link)}"
    )
    await callback.message.edit_text(text, reply_markup=main_menu(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    amount = 250
    order_id = f"ID_{callback.from_user.id}"
    # Формула FreeKassa
    sign = hashlib.md5(f"{FK_SHOP_ID}:{amount}:{FK_SECRET_1}:RUB:{order_id}".encode()).hexdigest()
    pay_url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa={amount}&currency=RUB&o={order_id}&s={sign}"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить 250₽", url=pay_url)],
        [InlineKeyboardButton(text="✅ Я оплатил!", callback_data=f"paid_{callback.from_user.id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    
    await callback.message.edit_text(
        "🚀 <b>Тариф «Блатной»</b>\n\n— 30 дней / 50 ГБ\n\nНажми подтверждение после оплаты:",
        reply_markup=markup, parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("paid_"))
async def user_confirm_payment(callback: CallbackQuery):
    await callback.message.answer("⏳ Запрос отправлен админам. Ожидайте.")
    user_id = callback.from_user.id
    username = callback.from_user.username or "user"
    
    admin_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплачено", callback_data=f"admin_approve_{user_id}_{username}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_decline_{user_id}")]
    ])

    for admin in ADMINS:
        await bot.send_message(admin, f"💰 Оплата: @{username} (ID: {user_id})", reply_markup=admin_markup)

@router.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve(callback: CallbackQuery):
    data = callback.data.split("_")
    user_id, username = int(data[2]), data[3]

    # ВЫДАЧА КЛЮЧА
    link = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, user_id, username)
    if link:
        await bot.send_message(user_id, f"✅ Доступ готов:\n{hcode(link)}")
        
        # ПРОЦЕСС РЕФЕРАЛКИ: Кто пригласил этого покупателя?
        user_info = get_user_data(user_id)
        if user_info and user_info[0]: # Если есть пригласитель
            referrer_id = user_info[0]
            add_bought_friend(referrer_id)
            
            # Проверяем, набралось ли 5 друзей у пригласителя
            ref_data = get_user_data(referrer_id)
            if ref_data and ref_data[1] >= 5 and ref_data[2] == 0:
                # Даем бонус пригласителю
                bonus_link = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, referrer_id, "ref_bonus")
                await bot.send_message(referrer_id, f"🎉 <b>Поздравляем!</b>\n\n5 твоих друзей купили подписку. Твой бонусный месяц:\n{hcode(bonus_link)}", parse_mode="HTML")
                
                # Помечаем, что награда выдана (чтобы не давать за каждого 6-го, 7-го и т.д. бесконечно, либо можно сбросить счетчик)
                conn = sqlite3.connect('users.db')
                conn.execute('UPDATE users SET reward_claimed = 1 WHERE user_id = ?', (referrer_id,))
                conn.commit()
                conn.close()

    await callback.message.edit_text(f"✅ Выдано для @{username}")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text("Выбери действие:", reply_markup=main_menu())

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    await callback.message.edit_text("📖 Инструкция: Скачай Happ и вставь ссылку.", reply_markup=main_menu())

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
