import os
import uuid
import requests
import logging
import time
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.utils.markdown import hcode, hbold
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import asyncio

# --- НАСТРОЙКИ ИЗ VARIABLES ---
API_TOKEN = os.getenv('BOT_TOKEN')
PANEL_URL = os.getenv('PANEL_URL')
SUB_PORT = os.getenv('SUB_PORT', '2096') 
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

# Функция создания ключа с лимитами: 50ГБ и 30 дней
def get_vpn_link(user_id, username):
    session = requests.Session()
    try:
        session.post(f"{PANEL_URL}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        
        client_uuid = str(uuid.uuid4())
        # Привязываем юзернейм или ID, чтобы видеть в панели
        client_email = f"{username or 'user'}_{user_id}"
        
        # Настройки лимитов
        limit_gb = 50 * 1024 * 1024 * 1024  # 50 ГБ в байтах
        duration = 30 * 24 * 60 * 60 * 1000 # 30 дней в миллисекундах
        expiry_time = int((time.time() * 1000) + duration)

        add_url = f"{PANEL_URL}/panel/api/inbounds/addClient"
        payload = {
            "id": INBOUND_ID,
            "settings": "{\"clients\": [{\"id\": \"" + client_uuid + "\", \"alterId\": 0, \"email\": \"" + client_email + "\", \"limitIp\": 1, \"totalGB\": " + str(limit_gb) + ", \"expiryTime\": " + str(expiry_time) + ", \"enable\": true, \"subId\": \"" + client_uuid + "\"}]}"
        }
        
        response = session.post(add_url, json=payload, timeout=10)
        if response.json().get('success'):
            # Ссылка для Happ
            base_url = PANEL_URL.rsplit(':', 1)[0] # Отрезаем порт панели
            final_link = f"{base_url}:{SUB_PORT}/sub/{client_uuid}?remark=TrubaVPN"
            return final_link
        return None
    except Exception as e:
        logging.error(f"Error: {e}")
        return None

# --- КЛАВИАТУРЫ ---
def main_menu():
    buttons = [
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")],
        [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/artemrogatykh")] # ЗАМЕНИ НА СВОЙ
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def buy_menu():
    buttons = [[InlineKeyboardButton(text="⚡ Купить: 1 мес / 50 ГБ", callback_data="buy_standard")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ОБРАБОТЧИКИ ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"👋 Привет, {hbold(message.from_user.full_name)}!\n\n"
        "Добро пожаловать в **TrubaVPN**. Здесь ты можешь приобрести скоростной доступ и получить инструкции по настройке.",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: types.Callback_query):
    await callback.message.edit_text(
        "🚀 **Доступные тарифы:**\n\n"
        "• **Standard**\n"
        "  — Срок: 30 дней\n"
        "  — Трафик: 50 ГБ\n"
        "  — Скорость: Без ограничений\n\n"
        "Выбери тариф для оплаты:",
        reply_markup=buy_menu(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "guide")
async def show_guide(callback: types.Callback_query):
    guide_text = (
        "📖 **Инструкция для Happ (iOS/Android):**\n\n"
        "1. Скачай приложение **Happ** в AppStore или PlayMarket.\n"
        "2. Скопируй ссылку, которую выдаст бот после покупки.\n"
        "3. В Happ нажми кнопку **Settings** (Настройки).\n"
        "4. Выбери пункт **Subscription Group Settings**.\n"
        "5. Нажми на **«+»** и вставь скопированную ссылку.\n"
        "6. Вернись на главный экран, выбери сервер и нажми кнопку подключения."
    )
    await callback.message.edit_text(guide_text, reply_markup=main_menu(), parse_mode="HTML")

@router.callback_query(F.data == "buy_standard")
async def process_buy(callback: types.Callback_query):
    await callback.message.answer("⏳ Генерирую твой личный ключ...")
    
    # Создаем ключ
    link = await asyncio.get_event_loop().run_in_executor(
        None, get_vpn_link, callback.from_user.id, callback.from_user.username
    )
    
    if link:
        await callback.message.answer(
            f"✅ **Оплата прошла успешно!**\n\n"
            f"Твоя личная ссылка для Happ:\n{hcode(link)}\n\n"
            "⚠️ *Не делитесь ссылкой с другими! Она привязана к вашему аккаунту.*",
            parse_mode="HTML"
        )
    else:
        await callback.message.answer("❌ Ошибка при создании ключа. Обратитесь в поддержку.")

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
