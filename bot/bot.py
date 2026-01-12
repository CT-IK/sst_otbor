"""
Telegram бот для системы отбора в студенческий совет.

Функционал:
- Админ панель для создания вопросов
- Управление этапами отбора
- Команды очистки тестовых данных
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from config import settings
from bot.handlers import admin_router, user_router, questions_router, cleanup_router, superadmin_router

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Роутеры
main_router = Router()


@main_router.message(CommandStart())
async def cmd_start(message: Message):
    """Команда /start"""
    await message.answer(
        "👋 <b>Добро пожаловать в систему отбора в Студенческий Совет!</b>\n\n"
        "Используйте кнопку ниже, чтобы открыть анкету:\n\n"
        "📝 /questionnaire — Заполнить анкету\n\n"
        "<i>Для администраторов:</i>\n"
        "/admin — Панель управления",
        parse_mode=ParseMode.HTML
    )


@main_router.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help"""
    help_text = """
<b>📚 Справка по командам</b>

<b>Для всех:</b>
/start — Начать работу с ботом
/questionnaire — Открыть анкету
/status — Проверить статус заявки

<b>Для администраторов факультета:</b>
/admin — Панель управления
/questions — Управление вопросами анкеты

<b>Для супер-администраторов:</b>
/superadmin — Создание факультетов и назначение админов

<b>Dev команды (только в dev режиме):</b>
/cleanup_redis — Очистить Redis
/cleanup_db — Очистить тестовые данные в БД
/seed — Создать тестовые данные
"""
    await message.answer(help_text, parse_mode=ParseMode.HTML)


@main_router.message(Command("questionnaire"))
async def cmd_questionnaire(message: Message, bot: Bot):
    """Открыть Mini App с анкетой"""
    # В проде здесь будет WebApp кнопка
    if settings.is_dev:
        await message.answer(
            "🔗 <b>Откройте анкету в браузере:</b>\n\n"
            f"http://localhost:8000/?faculty_id=1\n\n"
            "<i>В продакшене здесь будет кнопка Mini App</i>",
            parse_mode=ParseMode.HTML
        )
    else:
        # TODO: Добавить InlineKeyboardButton с WebApp
        await message.answer("Функция в разработке")


async def main():
    """Запуск бота"""
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не задан!")
        return
    
    # Создаём бота
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    # Диспетчер
    dp = Dispatcher()
    
    # Подключаем роутеры
    dp.include_router(main_router)
    dp.include_router(superadmin_router)  # Супер-админ первый (приоритет)
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(questions_router)
    dp.include_router(cleanup_router)
    
    # Запуск
    logger.info("Бот запускается...")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

