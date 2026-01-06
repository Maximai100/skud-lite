import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

# --- НАЧАЛО БЛОКА ДЛЯ RENDER ---
def run_web_server():
    # Создаем простейший веб-сервер, чтобы Render думал, что это сайт
    port = int(os.environ.get("PORT", 10000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    print(f"Запускаю фейковый веб-сервер на порту {port}")
    httpd.serve_forever()

# Запускаем веб-сервер в отдельном потоке
threading.Thread(target=run_web_server, daemon=True).start()
# --- КОНЕЦ БЛОКА ---

# Дальше идет твой обычный код...
"""
Telegram бот для дежурного (СКУД-лайт)
Команды: /start, /check, /absent, /reset, /delete
Функции: сводка, список отсутствующих с геолокацией, удаление пользователей
"""

import os
import logging
import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Загрузка переменных окружения
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("API_URL", "http://localhost:8000")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
WAITING_FOR_SEARCH = 1

# === Маппинг статусов ===
STATUS_LABELS = {
    "inside": "В здании",
    "work": "На работе",
    "day_off": "На сутки",
    "request": "По заявлению"
}


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    if not ADMIN_IDS:
        return True  # Если список пуст, разрешаем всем
    return user_id in ADMIN_IDS


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню с кнопками."""
    keyboard = [
        [InlineKeyboardButton("📊 Сводка", callback_data="check")],
        [InlineKeyboardButton("📋 Список отсутствующих", callback_data="absent")],
        [InlineKeyboardButton("📍 Местоположение", callback_data="locations")],
        [InlineKeyboardButton("🗑 Удалить пользователя", callback_data="delete_start")],
        [InlineKeyboardButton("🔄 Сбросить все статусы", callback_data="reset_confirm")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start — приветствие и проверка доступа."""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ Доступ запрещён.\n\n"
            f"Ваш ID: `{user_id}`\n"
            "Обратитесь к администратору для получения доступа.",
            parse_mode="Markdown"
        )
        return
    
    await update.message.reply_text(
        "👋 *Добро пожаловать в СКУД-лайт!*\n\n"
        "Я помогу вам отслеживать присутствие жильцов.\n\n"
        "📊 /check — сводка по личному составу\n"
        "📋 /absent — список отсутствующих\n"
        "📍 /locations — местоположение отсутствующих\n"
        "🗑 /delete — удалить пользователя\n"
        "🔄 /reset — сбросить все статусы\n\n"
        "Или используйте кнопки ниже:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )


async def check_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /check — показать сводку."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_URL}/api/stats")
            response.raise_for_status()
            stats = response.json()
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        text = "❌ Ошибка связи с сервером"
        if update.callback_query:
            await update.callback_query.answer(text, show_alert=True)
        else:
            await update.message.reply_text(text)
        return
    
    inside = stats.get("inside", 0)
    work = stats.get("work", 0)
    day_off = stats.get("day_off", 0)
    request = stats.get("request", 0)
    total = stats.get("total", 0)
    absent_total = work + day_off + request
    
    text = (
        "📊 *Сводка по личному составу:*\n\n"
        f"✅ *На месте:* {inside} чел.\n"
        f"❌ *Отсутствуют:* {absent_total} чел.\n"
        f"    — На работе: {work}\n"
        f"    — На сутки: {day_off}\n"
        f"    — По заявлению: {request}\n\n"
        f"👥 _Всего в базе: {total} чел._"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=get_main_keyboard()
        )


async def absent_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /absent — список отсутствующих."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_URL}/api/absent")
            response.raise_for_status()
            absent = response.json()
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        text = "❌ Ошибка связи с сервером"
        if update.callback_query:
            await update.callback_query.answer(text, show_alert=True)
        else:
            await update.message.reply_text(text)
        return
    
    if not absent:
        text = "✅ Все на месте! Отсутствующих нет."
    else:
        lines = ["📋 *Список отсутствующих:*\n"]
        for i, user in enumerate(absent, 1):
            status_label = user.get("status_label", user.get("status", ""))
            has_gps = "📍" if user.get("has_location") else ""
            lines.append(f"{i}. {user['full_name']} ({status_label}) {has_gps}")
        lines.append(f"\n_Всего: {len(absent)} чел._")
        lines.append("\n📍 = есть GPS, нажмите «Местоположение»")
        text = "\n".join(lines)
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=get_main_keyboard()
        )


async def show_locations(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /locations — показать местоположение отсутствующих."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_URL}/api/absent")
            response.raise_for_status()
            absent = response.json()
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        text = "❌ Ошибка связи с сервером"
        if update.callback_query:
            await update.callback_query.answer(text, show_alert=True)
        else:
            await update.message.reply_text(text)
        return
    
    # Фильтруем тех, у кого есть геолокация
    with_location = [u for u in absent if u.get("has_location")]
    
    if not with_location:
        text = "📍 Нет данных о местоположении.\n\nГеолокация сохраняется при смене статуса, если жилец разрешил доступ к GPS."
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text, reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(text, reply_markup=get_main_keyboard())
        return
    
    # Отправляем сообщение
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            f"📍 *Местоположение отсутствующих:*\n\n_{len(with_location)} чел. с GPS_",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
    
    # Отправляем каждую локацию отдельно
    chat_id = update.effective_chat.id
    for user in with_location:
        lat = user.get("latitude")
        lon = user.get("longitude")
        status_label = user.get("status_label", "")
        
        # Отправляем локацию
        await context.bot.send_location(
            chat_id=chat_id,
            latitude=lat,
            longitude=lon
        )
        # Подпись
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"👤 *{user['full_name']}*\n📌 {status_label}",
            parse_mode="Markdown"
        )


# === Удаление пользователей ===

async def delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало процесса удаления — запрос ФИО для поиска."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "🔍 *Удаление пользователя*\n\n"
            "Введите ФИО (или часть) для поиска:\n\n"
            "_Отправьте /cancel для отмены_",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🔍 *Удаление пользователя*\n\n"
            "Введите ФИО (или часть) для поиска:\n\n"
            "_Отправьте /cancel для отмены_",
            parse_mode="Markdown"
        )
    
    return WAITING_FOR_SEARCH


async def search_and_show_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Поиск пользователей и показ результатов."""
    query = update.message.text.strip()
    
    if len(query) < 2:
        await update.message.reply_text("❌ Введите минимум 2 символа для поиска")
        return WAITING_FOR_SEARCH
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_URL}/api/users/search", params={"q": query})
            response.raise_for_status()
            users = response.json()
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        await update.message.reply_text("❌ Ошибка связи с сервером")
        return ConversationHandler.END
    
    if not users:
        await update.message.reply_text(
            f"🔍 По запросу «{query}» ничего не найдено.\n\n"
            "Попробуйте другой запрос или /cancel для отмены."
        )
        return WAITING_FOR_SEARCH
    
    # Показываем результаты с кнопками
    keyboard = []
    for user in users:
        status_label = user.get("status_label", "")
        btn_text = f"🗑 {user['full_name']} ({status_label})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"del_{user['id']}")])
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="delete_cancel")])
    
    await update.message.reply_text(
        f"🔍 Найдено *{len(users)}* пользователей:\n\n"
        "Нажмите на пользователя для удаления:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return ConversationHandler.END


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение удаления конкретного пользователя."""
    query = update.callback_query
    user_id = int(query.data.replace("del_", ""))
    
    # Сохраняем ID для следующего шага
    context.user_data["delete_user_id"] = user_id
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_del_{user_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data="delete_cancel")
        ]
    ]
    
    await query.answer()
    await query.edit_message_text(
        "⚠️ *Вы уверены?*\n\n"
        "Пользователь будет удалён из системы.\n"
        "Это действие нельзя отменить!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def execute_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Выполнение удаления пользователя."""
    query = update.callback_query
    user_id = int(query.data.replace("confirm_del_", ""))
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(f"{API_URL}/api/users/{user_id}")
            response.raise_for_status()
            result = response.json()
    except Exception as e:
        logger.error(f"Ошибка удаления: {e}")
        await query.answer("❌ Ошибка удаления", show_alert=True)
        return
    
    await query.answer("✅ Пользователь удалён!")
    await query.edit_message_text(
        f"✅ *Готово!*\n\n{result.get('message', 'Пользователь удалён')}",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )


async def cancel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отмена удаления."""
    query = update.callback_query
    await query.answer("Отменено")
    await query.edit_message_text(
        "🔙 Удаление отменено",
        reply_markup=get_main_keyboard()
    )


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена разговора командой /cancel."""
    await update.message.reply_text(
        "🔙 Операция отменена",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END


# === Сброс статусов ===

async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Подтверждение сброса статусов."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, сбросить", callback_data="reset_yes"),
            InlineKeyboardButton("❌ Отмена", callback_data="reset_no")
        ]
    ]
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "⚠️ *Вы уверены?*\n\n"
        "Это сбросит статусы ВСЕХ пользователей на \"В здании\".",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /reset — сбросить все статусы."""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    
    # Если вызвано командой, а не кнопкой, показать подтверждение
    if update.message:
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сбросить", callback_data="reset_yes"),
                InlineKeyboardButton("❌ Отмена", callback_data="reset_no")
            ]
        ]
        await update.message.reply_text(
            "⚠️ *Вы уверены?*\n\n"
            "Это сбросит статусы ВСЕХ пользователей на \"В здании\".",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # Выполнение сброса
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{API_URL}/api/reset")
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Ошибка API: {e}")
        await update.callback_query.answer("❌ Ошибка сброса", show_alert=True)
        return
    
    await update.callback_query.answer("✅ Статусы сброшены!")
    await update.callback_query.edit_message_text(
        "✅ *Готово!*\n\nВсе статусы сброшены на \"В здании\".",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard()
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на inline-кнопки."""
    query = update.callback_query
    data = query.data
    
    if data == "check":
        await check_stats(update, context)
    elif data == "absent":
        await absent_list(update, context)
    elif data == "locations":
        await show_locations(update, context)
    elif data == "delete_start":
        await delete_start(update, context)
    elif data.startswith("del_"):
        await confirm_delete(update, context)
    elif data.startswith("confirm_del_"):
        await execute_delete(update, context)
    elif data == "delete_cancel":
        await cancel_delete(update, context)
    elif data == "reset_confirm":
        await reset_confirm(update, context)
    elif data == "reset_yes":
        await reset_all(update, context)
    elif data == "reset_no":
        await query.answer("Отменено")
        await query.edit_message_text(
            "🔙 Возврат в меню",
            reply_markup=get_main_keyboard()
        )


def main() -> None:
    """Запуск бота."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан! Создайте файл .env с BOT_TOKEN=ваш_токен")
        return
    
    # Создание приложения
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ConversationHandler для удаления пользователей
    delete_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_start)],
        states={
            WAITING_FOR_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_and_show_results)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    
    # Регистрация обработчиков
    app.add_handler(delete_conv_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_stats))
    app.add_handler(CommandHandler("absent", absent_list))
    app.add_handler(CommandHandler("locations", show_locations))
    app.add_handler(CommandHandler("reset", reset_all))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Запуск
    logger.info("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
