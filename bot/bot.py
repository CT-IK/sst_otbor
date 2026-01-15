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

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config import settings
from bot.handlers import admin_router, user_router, questions_router, cleanup_router, superadmin_router, reviewers_router, broadcast_router, video_stage_router

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
    """Открыть Mini App с анкетой - выбор факультета"""
    from sqlalchemy import select
    from db.engine import async_session_maker
    from db.models import Faculty, StageType, StageStatus
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    
    async with async_session_maker() as db:
        # Получаем факультеты с открытой анкетой
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
    
    if not faculties:
        await message.answer(
            "ℹ️ Факультеты ещё не созданы.\n"
            "Обратитесь к администратору.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Фильтруем факультеты с открытой анкетой
    open_faculties = [
        f for f in faculties 
        if f.current_stage == StageType.QUESTIONNAIRE and f.stage_status == StageStatus.OPEN
    ]
    
    if not open_faculties:
        # Показываем все факультеты, но с информацией о статусе
        buttons = []
        for f in faculties:
            if f.current_stage == StageType.QUESTIONNAIRE and f.stage_status == StageStatus.OPEN:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"✅ {f.name}",
                        callback_data=f"quest:faculty:{f.id}"
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔒 {f.name} (закрыто)",
                        callback_data=f"quest:closed:{f.id}"
                    )
                ])
        
        await message.answer(
            "📝 <b>Анкета в Студсовет</b>\n\n"
            "⚠️ Анкета пока не открыта ни для одного факультета.\n\n"
            "Выберите факультет для проверки статуса:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )
    else:
        # Есть открытые факультеты
        buttons = []
        for f in faculties:
            if f.current_stage == StageType.QUESTIONNAIRE and f.stage_status == StageStatus.OPEN:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"✅ {f.name}",
                        callback_data=f"quest:faculty:{f.id}"
                    )
                ])
            else:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"🔒 {f.name}",
                        callback_data=f"quest:closed:{f.id}"
                    )
                ])
        
        await message.answer(
            "📝 <b>Анкета в Студсовет</b>\n\n"
            "Выберите ваш факультет:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode=ParseMode.HTML
        )


@main_router.callback_query(F.data.startswith("quest:faculty:"))
async def callback_quest_faculty(callback: CallbackQuery):
    """Факультет выбран - показываем кнопку Mini App"""
    faculty_id = int(callback.data.split(":")[2])
    
    from sqlalchemy import select
    from db.engine import async_session_maker
    from db.models import Faculty, StageType, StageStatus
    
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
    
    if not faculty:
        await callback.answer("Факультет не найден", show_alert=True)
        return
    
    # Проверяем открыта ли анкета
    if faculty.current_stage != StageType.QUESTIONNAIRE or faculty.stage_status != StageStatus.OPEN:
        await callback.answer("Анкета для этого факультета закрыта", show_alert=True)
        return
    
    # URL Mini App
    if settings.is_dev:
        webapp_url = f"http://localhost:8000/?faculty_id={faculty_id}"
        await callback.message.edit_text(
            f"🏛 <b>{faculty.name}</b>\n\n"
            f"🔗 Откройте анкету в браузере:\n{webapp_url}",
            parse_mode=ParseMode.HTML
        )
    else:
        webapp_url = f"https://putevod-ik.ru/?faculty_id={faculty_id}"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Заполнить анкету",
                web_app=WebAppInfo(url=webapp_url)
            )],
            [InlineKeyboardButton(text="« Назад", callback_data="quest:back")]
        ])
        
        await callback.message.edit_text(
            f"🏛 <b>{faculty.name}</b>\n\n"
            "Нажмите кнопку ниже, чтобы открыть анкету:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )
    
    await callback.answer()


@main_router.callback_query(F.data.startswith("quest:closed:"))
async def callback_quest_closed(callback: CallbackQuery):
    """Факультет с закрытой анкетой"""
    faculty_id = int(callback.data.split(":")[2])
    
    from sqlalchemy import select
    from db.engine import async_session_maker
    from db.models import Faculty
    
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
    
    if not faculty:
        await callback.answer("Факультет не найден", show_alert=True)
        return
    
    stage = faculty.current_stage.value if faculty.current_stage else "не начат"
    status = faculty.stage_status.value if faculty.stage_status else "—"
    
    await callback.answer(
        f"🔒 Анкета закрыта\nЭтап: {stage} ({status})",
        show_alert=True
    )


@main_router.callback_query(F.data == "quest:back")
async def callback_quest_back(callback: CallbackQuery):
    """Назад к выбору факультета"""
    from sqlalchemy import select
    from db.engine import async_session_maker
    from db.models import Faculty, StageType, StageStatus
    
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
    
    buttons = []
    for f in faculties:
        if f.current_stage == StageType.QUESTIONNAIRE and f.stage_status == StageStatus.OPEN:
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ {f.name}",
                    callback_data=f"quest:faculty:{f.id}"
                )
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text=f"🔒 {f.name}",
                    callback_data=f"quest:closed:{f.id}"
                )
            ])
    
    await callback.message.edit_text(
        "📝 <b>Анкета в Студсовет</b>\n\n"
        "Выберите ваш факультет:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


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
    dp.include_router(reviewers_router)   # Управление проверяющими
    dp.include_router(broadcast_router)   # Рассылки (только для head_admin)
    dp.include_router(video_stage_router)  # Второй этап - сбор видео
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

