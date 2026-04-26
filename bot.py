import os
import uuid
import requests
import logging
import time
import hashlib
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.utils.markdown import hcode, hbold, hlink
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
import asyncio

# --- НАСТРОЙКИ ---
API_TOKEN = os.getenv('BOT_TOKEN')
FK_SHOP_ID = os.getenv('FK_SHOP_ID')
FK_SECRET_1 = os.getenv('FK_SECRET_1')
# ID админов (тебе и другу)
ADMINS = [int(os.getenv('ADMIN_ID_1')), int(os.getenv('ADMIN_ID_2'))]

PANEL_URL = os.getenv('PANEL_URL')
SUB_PORT = os.getenv('SUB_PORT', '2096') 
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

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

# --- ФОРМИРОВАНИЕ ССЫЛКИ FREEKASSA ---
def generate_fk_link(amount, order_id):
    currency = "RUB"
    sign_str = f"{FK_SHOP_ID}:{amount}:{FK_SECRET_1}:{currency}:{order_id}"
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    return f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa={amount}&currency={currency}&o={order_id}&s={sign}"

# --- КЛАВИАТУРЫ ---
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")],
        [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/твой_логин")]
    ])

# --- ОБРАБОТЧИКИ ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(f"👋 Привет! Это <b>TrubaVPN</b>.", reply_markup=main_menu(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    amount = 250
    order_id = f"ID_{callback.from_user.id}"
    pay_url = generate_fk_link(amount, order_id)
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить 250₽", url=pay_url)],
        [InlineKeyboardButton(text="✅ Я оплатил!", callback_data=f"paid_{callback.from_user.id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("<b>Тариф «Блатной»</b>\n\nОплатите по ссылке и нажмите кнопку ниже.", reply_markup=markup, parse_mode="HTML")

# Когда юзер нажал "Я оплатил"
@router.callback_query(F.data.startswith("paid_"))
async def user_confirm_payment(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or "Нет юзернейма"
    
    # Уведомляем юзера
    await callback.message.answer("⏳ Запрос отправлен админам. Ожидайте подтверждения (обычно 2-5 мин).")
    await callback.answer()

    # Кнопки для админов
    admin_markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить и выдать", callback_data=f"admin_approve_{user_id}_{username}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_decline_{user_id}")]
    ])

    # Рассылка всем админам
    for admin in ADMINS:
        try:
            await bot.send_message(
                admin, 
                f"💰 <b>Новая оплата!</b>\n\nОт: @{username} (ID: {user_id})\nТариф: Блатной (250₽)",
                reply_markup=admin_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить админу {admin}: {e}")

# Когда админ нажал "Подтвердить"
@router.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve(callback: CallbackQuery):
    data = callback.data.split("_")
    user_id = int(data[2])
    username = data[3]

    await callback.message.edit_text(f"✅ Вы подтвердили оплату для @{username}. Генерирую ключ...")

    # Создаем ключ в панели
    link = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, user_id, username)

    if link:
        # Пишем юзеру
        try:
            await bot.send_message(
                user_id, 
                f"✅ <b>Оплата подтверждена!</b>\n\nТвой доступ готов:\n{hcode(link)}\n\nИнструкция в /start",
                parse_mode="HTML"
            )
            # Сообщаем остальным админам, что уже подтверждено
            for admin in ADMINS:
                if admin != callback.from_user.id:
                    await bot.send_message(admin, f"🤝 Админ @{callback.from_user.username} уже выдал ключ для @{username}")
        except Exception as e:
            await callback.message.answer(f"Ошибка при отправке юзеру: {e}")
    else:
        await callback.message.answer("❌ Ошибка панели при создании ключа!")

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
