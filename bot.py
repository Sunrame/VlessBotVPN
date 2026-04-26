import os
import uuid
import requests
import logging
import time
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.utils.markdown import hcode, hbold
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
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
        [InlineKeyboardButton(text="🆘 Поддержка", url="https://t.me/твой_логин")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def buy_menu():
    buttons = [
        [InlineKeyboardButton(text="⚡ Купить тариф «Блатной»", callback_data="buy_standard")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def back_only_menu():
    buttons = [[InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="to_main")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ОБРАБОТЧИКИ ---

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"👋 Привет, {hbold(message.from_user.full_name)}!\n\n"
        f"Добро пожаловать в <b>TrubaVPN</b>. Выберите нужное действие ниже:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        f"👋 Привет, {hbold(callback.from_user.full_name)}!\n\n"
        f"Добро пожаловать в <b>TrubaVPN</b>. Выберите нужное действие ниже:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    await callback.message.edit_text(
        "🚀 <b>Доступные тарифы:</b>\n\n"
        "• <b>Тариф «Блатной»</b>\n"
        "  — <b>Срок:</b> 30 дней\n"
        "  — <b>Трафик:</b> 50 ГБ\n"
        "  — <b>Скорость:</b> Без ограничений\n\n"
        "Нажми кнопку ниже для покупки:",
        reply_markup=buy_menu(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    guide_text = (
        "📖 <b>Инструкция для Happ (iOS/Android):</b>\n\n"
        "1. Скачай приложение <b>Happ</b>.\n"
        "2. Скопируй ссылку из бота.\n"
        "3. В Happ зайди в <b>Settings</b> -> <b>Subscription Group Settings</b>.\n"
        "4. Нажми <b>«+»</b>, вставь ссылку и сохрани.\n"
        "5. Выбери сервер на главном экране и подключайся!"
    )
    await callback.message.edit_text(guide_text, reply_markup=back_only_menu(), parse_mode="HTML")

@router.callback_query(F.data == "buy_standard")
async def process_buy(callback: CallbackQuery):
    await callback.answer("⏳ Генерирую доступ...")
    
    link = await asyncio.get_event_loop().run_in_executor(
        None, get_vpn_link, callback.from_user.id, callback.from_user.username
    )
    
    if link:
        await callback.message.answer(
            f"✅ <b>Тариф «Блатной» активирован!</b>\n\n"
            f"Твоя ссылка для Happ:\n{hcode(link)}\n\n"
            "⚠️ Инструкция по установке есть в главном меню.",
            reply_markup=back_only_menu(),
            parse_mode="HTML"
        )
    else:
        await callback.message.answer("❌ Ошибка панели. Напиши в поддержку.", reply_markup=back_only_menu())

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
