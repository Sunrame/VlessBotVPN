import os
import uuid
import requests
import logging
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.utils.markdown import hcode
import asyncio

# Данные берутся из вкладки Variables на Railway
API_TOKEN = os.getenv('BOT_TOKEN')
PANEL_URL = os.getenv('PANEL_URL')     # Например: http://31.44.9.47:2053
SUB_PORT = os.getenv('SUB_PORT', '2096') 
LOGIN = os.getenv('PANEL_LOGIN')
PASSWORD = os.getenv('PANEL_PASSWORD')
INBOUND_ID = 1  # ID твоей «Германии»

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

def get_vpn_link(user_id):
    session = requests.Session()
    login_url = f"{PANEL_URL}/login"
    try:
        session.post(login_url, data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        client_uuid = str(uuid.uuid4())
        client_email = f"tg_{user_id}"
        
        add_url = f"{PANEL_URL}/panel/api/inbounds/addClient"
        payload = {
            "id": INBOUND_ID,
            "settings": "{\"clients\": [{\"id\": \"" + client_uuid + "\", \"alterId\": 0, \"email\": \"" + client_email + "\", \"limitIp\": 1, \"totalGB\": 0, \"expiryTime\": 0, \"enable\": true, \"subId\": \"" + client_uuid + "\"}]}"
        }
        
        response = session.post(add_url, json=payload, timeout=10)
        if response.json().get('success'):
            # Ссылка с категорией TrubaVPN
            final_link = f"{PANEL_URL.split(':')[0]}:{PANEL_URL.split(':')[1]}:{SUB_PORT}/sub/{client_uuid}?remark=TrubaVPN"
            return final_link
        return None
    except Exception as e:
        logging.error(f"Error: {e}")
        return None

@router.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! Нажми /new_vpn для получения доступа.")

@router.message(Command("new_vpn"))
async def create_key(message: types.Message):
    await message.answer("⏳ Создаю твой личный профиль...")
    loop = asyncio.get_event_loop()
    link = await loop.run_in_executor(None, get_vpn_link, message.from_user.id)
    if link:
        await message.answer(f"✅ Готово!\n\nДобавь ссылку в Happ:\n\n{hcode(link)}", parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка панели. Проверь Variables в Railway.")

async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
