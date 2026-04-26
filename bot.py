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

# --- НАСТРОЙКИ (БЕРУТСЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ) ---
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
    cursor.execute('''CREATE TABLE IF NOT EXISTS users 
                      (user_id INTEGER PRIMARY KEY, 
                       username TEXT,
                       referrer_id INTEGER, 
                       bought_friends INTEGER DEFAULT 0, 
                       reward_claimed INTEGER DEFAULT 0,
                       expiry_date INTEGER DEFAULT 0,
                       is_active INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def register_user(user_id, username, referrer_id=None):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    un_low = (username or "user").lower()
    cursor.execute('''INSERT INTO users (user_id, username, referrer_id) 
                      VALUES (?, ?, ?) 
                      ON CONFLICT(user_id) DO UPDATE SET username = EXCLUDED.username''', 
                   (user_id, un_low, referrer_id))
    conn.commit()
    conn.close()

def get_user_db_data(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT referrer_id, bought_friends, reward_claimed, expiry_date, is_active FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def activate_user_in_db(user_id, active=1, custom_expiry=None):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    # 30 дней по умолчанию
    expiry = custom_expiry if custom_expiry else int(time.time() + (30 * 24 * 60 * 60))
    if active == 0:
        expiry = 0
    cursor.execute('UPDATE users SET is_active = ?, expiry_date = ? WHERE user_id = ?', (active, expiry, user_id))
    conn.commit()
    conn.close()

# --- ВЗАИМОДЕЙСТВИЕ С ПАНЕЛЬЮ 3X-UI ---
def get_3xui_session():
    s = requests.Session()
    try:
        s.post(f"{PANEL_URL}/login", data={'username': LOGIN, 'password': PASSWORD}, timeout=10)
        return s
    except Exception as e:
        logging.error(f"Ошибка авторизации в панели: {e}")
        return None

def get_user_stats(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        resp = session.get(f"{PANEL_URL}/panel/api/inbounds/get/{INBOUND_ID}", timeout=10)
        data = resp.json()
        email = f"{(username or 'user').lower()}_{user_id}"
        
        # Получаем онлайн устройства
        onlines_resp = session.post(f"{PANEL_URL}/panel/api/inbounds/onlines", timeout=10)
        onlines = onlines_resp.json().get('obj', [])
        active_ips = onlines.count(email)

        stats = next((c for c in data['obj']['clientStats'] if c['email'] == email), None)
        sett = next((c for c in json.loads(data['obj']['settings'])['clients'] if c['email'] == email), None)
        
        if stats and sett:
            return {
                "used": stats.get('up', 0) + stats.get('down', 0), 
                "limit": sett.get('totalGB', 0),
                "online": active_ips,
                "expiry": sett.get('expiryTime', 0)
            }
    except Exception as e:
        logging.error(f"Ошибка получения статистики: {e}")
    return None

def get_vpn_link(user_id, username):
    session = get_3xui_session()
    if not session: return None
    try:
        u_uuid = str(uuid.uuid4())
        email = f"{(username or 'user').lower()}_{user_id}"
        limit_traffic = 50 * 1024 * 1024 * 1024 # 50 ГБ
        exp_time = int((time.time() + (30 * 24 * 3600)) * 1000) # 30 дней в мс
        
        payload = {
            "id": INBOUND_ID, 
            "settings": json.dumps({
                "clients": [{
                    "id": u_uuid, "alterId": 0, "email": email, "limitIp": 3, 
                    "totalGB": limit_traffic, "expiryTime": exp_time, "enable": True, "subId": u_uuid
                }]
            })
        }
        r = session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload, timeout=10)
        if r.json().get('success'):
            host = PANEL_URL.rsplit(':', 1)[0]
            return f"{host}:{SUB_PORT}/sub/{u_uuid}?remark=TrubaVPN"
    except Exception as e:
        logging.error(f"Ошибка создания клиента: {e}")
    return None

def delete_vpn_client(user_id, username):
    session = get_3xui_session()
    if not session: return False
    try:
        email = f"{(username or 'user').lower()}_{user_id}"
        resp = session.post(f"{PANEL_URL}/panel/api/inbounds/delClient/{INBOUND_ID}", data={"email": email}, timeout=10)
        return resp.json().get('success')
    except:
        return False

# --- КЛАВИАТУРЫ ---
def main_markup():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile")],
        [InlineKeyboardButton(text="💎 Тарифы", callback_data="tariffs")],
        [InlineKeyboardButton(text="🤝 Партнерка", callback_data="ref_program")],
        [InlineKeyboardButton(text="📖 Инструкция", callback_data="guide")]
    ])

def back_markup():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]])

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ И КНОПОК ---

@router.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject):
    ref_id = int(command.args) if command.args and command.args.isdigit() else None
    register_user(message.from_user.id, message.from_user.username, ref_id)
    await message.answer(f"👋 Привет, {hbold(message.from_user.full_name)}!\nДобро пожаловать в сервис TrubaVPN.", reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    # Синхронизация с панелью
    st = get_user_stats(callback.from_user.id, callback.from_user.username)
    if st:
        # Если в панели есть клиент, обновляем статус в БД
        exp_sec = st['expiry'] // 1000 if st['expiry'] > 0 else int(time.time() + 86400)
        activate_user_in_db(callback.from_user.id, active=1, custom_expiry=exp_sec)
    
    d = get_user_db_data(callback.from_user.id)
    if not d or str(d[4]) not in ["1", "True"]:
        await callback.message.edit_text("⚠️ <b>У вас нет активной подписки.</b>\nПерейдите в раздел Тарифы, чтобы подключиться.", reply_markup=main_markup(), parse_mode="HTML")
        return

    now = int(time.time())
    days_left = (int(d[3]) - now) // 86400
    
    # Авто-деактивация если срок истек
    if days_left < 0:
        activate_user_in_db(callback.from_user.id, active=0)
        await callback.message.edit_text("⚠️ <b>Ваша подписка истекла.</b>", reply_markup=main_markup(), parse_mode="HTML")
        return

    u, l = (round(st['used']/(1024**3), 2), round(st['limit']/(1024**3), 2)) if st else ("??", "50")
    online = st['online'] if st else 0
    
    text = (f"👤 <b>Личный кабинет</b>\n\n"
            f"⏳ Осталось дней: <b>{max(0, int(days_left))}</b>\n"
            f"📊 Трафик: <b>{u} / {l} ГБ</b>\n"
            f"📱 Устройств онлайн: <b>{online} / 3</b>")
    
    await callback.message.edit_text(text, reply_markup=main_markup(), parse_mode="HTML")

@router.callback_query(F.data == "tariffs")
async def show_tariffs(callback: CallbackQuery):
    d = get_user_db_data(callback.from_user.id)
    # Проверка: если подписка уже есть, не даем покупать
    if d and str(d[4]) in ["1", "True"]:
        await callback.message.edit_text("✅ <b>У вас уже есть активная подписка!</b>\nНовый тариф можно будет купить после окончания текущего.", reply_markup=main_markup(), parse_mode="HTML")
        return

    sign = hashlib.md5(f"{FK_SHOP_ID}:250:{FK_SECRET_1}:RUB:ID_{callback.from_user.id}".encode()).hexdigest()
    pay_url = f"https://pay.freekassa.ru/?m={FK_SHOP_ID}&oa=250&currency=RUB&o=ID_{callback.from_user.id}&s={sign}"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить 250₽", url=pay_url)],
        [InlineKeyboardButton(text="✅ Я оплатил!", callback_data=f"paid_{callback.from_user.id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]
    ])
    await callback.message.edit_text("🚀 <b>Тариф «Блатной»</b>\n\n✅ Срок: 30 дней\n✅ Лимит: 50 ГБ\n✅ Устройства: до 3-х одновременно\n💰 Цена: 250 руб.", reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "ref_program")
async def show_ref(callback: CallbackQuery):
    d = get_user_db_data(callback.from_user.id)
    if not d: register_user(callback.from_user.id, callback.from_user.username); d = get_user_db_data(callback.from_user.id)
    me = await bot.get_me()
    text = (f"🤝 <b>Партнерская программа</b>\n\n"
            f"Приглашай друзей по своей ссылке. За каждого 5-го друга, купившего подписку, ты получишь 1 месяц бесплатно!\n\n"
            f"📈 Твой прогресс: <b>{d[1]}/5</b> друзей\n"
            f"🔗 Твоя ссылка: {hcode(f'https://t.me/{me.username}?start={callback.from_user.id}')}")
    await callback.message.edit_text(text, reply_markup=back_markup(), parse_mode="HTML")

@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery):
    text = ("📖 <b>Как подключиться?</b>\n\n"
            "1. Скачайте приложение <b>Hiddify</b> (Android/iOS/PC).\n"
            "2. Скопируйте ссылку на подключение из бота.\n"
            "3. В приложении нажмите <b>'Новый профиль'</b> -> <b>'Добавить из буфера'</b>.\n"
            "4. Нажмите кнопку подключения (центр экрана).")
    await callback.message.edit_text(text, reply_markup=back_markup(), parse_mode="HTML")

@router.callback_query(F.data == "to_main")
async def to_main(callback: CallbackQuery):
    await callback.message.edit_text("Выбери интересующий раздел:", reply_markup=main_markup())

@router.callback_query(F.data.startswith("paid_"))
async def user_paid(callback: CallbackQuery):
    await callback.message.answer("⏳ Запрос отправлен. Ожидайте подтверждения от администратора.")
    m = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать доступ", callback_data=f"adm_ap_{callback.from_user.id}_{callback.from_user.username or 'user'}")],
        [InlineKeyboardButton(text="🗑 Удалить сообщение", callback_data="admin_delete_msg")]
    ])
    for a in ADMINS: 
        try: await bot.send_message(a, f"💰 <b>Новая заявка на оплату!</b>\nЮзер: @{callback.from_user.username} (ID: {callback.from_user.id})", reply_markup=m, parse_mode="HTML")
        except: pass

@router.callback_query(F.data.startswith("adm_ap_"))
async def adm_ap(callback: CallbackQuery):
    _, _, uid, uname = callback.data.split("_")
    uid = int(uid)
    lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, uid, uname)
    if lnk:
        activate_user_in_db(uid, active=1)
        await bot.send_message(uid, f"🥳 <b>Оплата подтверждена!</b>\n\nТвоя ссылка для подключения:\n{hcode(lnk)}\n\nИспользуй её в приложении согласно инструкции.", parse_mode="HTML")
        
        # Логика рефералов
        u_data = get_user_db_data(uid)
        if u_data and u_data[0]:
            ref_owner = u_data[0]
            conn = sqlite3.connect('users.db')
            conn.execute('UPDATE users SET bought_friends = bought_friends + 1 WHERE user_id = ?', (ref_owner,))
            conn.commit()
            conn.close()
    
    await callback.message.edit_text(f"✅ Доступ успешно выдан для @{uname}")

# --- АДМИН-КОМАНДЫ ---

@router.message(Command("give"))
async def admin_give(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS or not command.args: return
    target = command.args.replace("@", "").lower().strip()
    conn = sqlite3.connect('users.db'); c = conn.cursor()
    if target.isdigit(): c.execute('SELECT user_id, username FROM users WHERE user_id = ?', (int(target),))
    else: c.execute('SELECT user_id, username FROM users WHERE username = ?', (target,))
    res = c.fetchone(); conn.close()
    
    if res:
        lnk = await asyncio.get_event_loop().run_in_executor(None, get_vpn_link, res[0], res[1])
        if lnk:
            activate_user_in_db(res[0], active=1)
            await bot.send_message(res[0], f"🎁 <b>Вам выдан бонусный доступ!</b>\n\n{hcode(lnk)}", parse_mode="HTML")
            await message.answer(f"✅ Успешно выдано пользователю {res[1]}")
    else: await message.answer("❌ Пользователь не найден в базе данных.")

@router.message(Command("take"))
async def admin_take(message: types.Message, command: CommandObject):
    if message.from_user.id not in ADMINS or not command.args: return
    target = command.args.replace("@", "").lower().strip()
    conn = sqlite3.connect('users.db'); c = conn.cursor()
    if target.isdigit(): c.execute('SELECT user_id, username FROM users WHERE user_id = ?', (int(target),))
    else: c.execute('SELECT user_id, username FROM users WHERE username = ?', (target,))
    res = c.fetchone(); conn.close()
    
    if res:
        await asyncio.get_event_loop().run_in_executor(None, delete_vpn_client, res[0], res[1])
        activate_user_in_db(res[0], active=0)
        await bot.send_message(res[0], "⚠️ Ваша подписка была аннулирована администратором.")
        await message.answer(f"🚫 Доступ у {res[1]} отозван.")

@router.callback_query(F.data == "admin_delete_msg")
async def adm_del(callback: CallbackQuery):
    await callback.message.delete()

# --- ЗАПУСК ---
async def main():
    dp.include_router(router)
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен.")
