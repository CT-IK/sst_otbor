"""
Команды для обычных пользователей.
"""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import select

from config import settings
from db.engine import async_session_maker
from db.models import User, Faculty, UserProgress, StageType, SubmissionStatus

user_router = Router()


@user_router.message(Command("status"))
async def cmd_status(message: Message):
    """Проверить статус заявки"""
    async with async_session_maker() as db:
        # Ищем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await message.answer(
                "❓ Вы ещё не зарегистрированы.\n\n"
                "Используйте /questionnaire чтобы заполнить анкету."
            )
            return
        
        # Получаем прогресс
        result = await db.execute(
            select(UserProgress).where(UserProgress.user_id == user.id)
        )
        progress_list = result.scalars().all()
        
        # Получаем факультет
        result = await db.execute(
            select(Faculty).where(Faculty.id == user.faculty_id)
        )
        faculty = result.scalars().first()
    
    # Формируем статус
    status_text = f"👤 <b>{user.first_name} {user.surname or ''}</b>\n"
    
    if faculty:
        status_text += f"🏫 Факультет: {faculty.name}\n\n"
    
    if progress_list:
        status_text += "<b>Прогресс по этапам:</b>\n\n"
        
        stage_names = {
            StageType.QUESTIONNAIRE: "📝 Анкета",
            StageType.HOME_VIDEO: "🎬 Домашнее видео",
            StageType.INTERVIEW: "🎤 Собеседование",
        }
        
        status_icons = {
            SubmissionStatus.NOT_STARTED: "⚪",
            SubmissionStatus.IN_PROGRESS: "🟡",
            SubmissionStatus.SUBMITTED: "🔵",
            SubmissionStatus.APPROVED: "🟢",
            SubmissionStatus.REJECTED: "🔴",
        }
        
        for p in progress_list:
            stage_name = stage_names.get(p.stage_type, p.stage_type.value)
            icon = status_icons.get(p.status, "⚪")
            status_text += f"{icon} {stage_name}: {p.status.value}\n"
            
            if p.submitted_at:
                status_text += f"   <i>Отправлено: {p.submitted_at.strftime('%d.%m.%Y %H:%M')}</i>\n"
            if p.rejection_reason:
                status_text += f"   <i>Причина: {p.rejection_reason}</i>\n"
    else:
        status_text += "<i>Вы ещё не начали заполнять анкету</i>"
    
    await message.answer(status_text)


@user_router.message(Command("register"))
async def cmd_register(message: Message):
    """Регистрация пользователя"""
    async with async_session_maker() as db:
        # Проверяем существует ли
        result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalars().first()
        
        if user:
            await message.answer(
                f"✅ Вы уже зарегистрированы как {user.first_name}.\n\n"
                f"Используйте /status для проверки статуса."
            )
            return
        
        # Получаем список факультетов
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
    
    if not faculties:
        await message.answer(
            "ℹ️ Регистрация временно недоступна.\n"
            "Попробуйте позже."
        )
        return
    
    # Кнопки факультетов
    buttons = []
    for f in faculties:
        buttons.append([
            InlineKeyboardButton(
                text=f.name,
                callback_data=f"register:faculty:{f.id}"
            )
        ])
    
    await message.answer(
        "📝 <b>Регистрация</b>\n\n"
        "Выберите ваш факультет:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@user_router.message(Command("webapp"))
async def cmd_webapp(message: Message):
    """Открыть Mini App напрямую"""
    # В продакшене здесь будет реальный URL
    if settings.is_dev:
        await message.answer(
            "🔗 <b>Mini App (Dev режим)</b>\n\n"
            "Откройте в браузере:\n"
            "http://localhost:8000/\n\n"
            "<i>В продакшене будет кнопка WebApp</i>"
        )
    else:
        # WebApp кнопка
        webapp_url = "https://your-domain.com/"  # TODO: настроить
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Открыть анкету",
                web_app=WebAppInfo(url=webapp_url)
            )]
        ])
        
        await message.answer(
            "📝 <b>Анкета в Студсовет</b>\n\n"
            "Нажмите кнопку ниже, чтобы открыть анкету:",
            reply_markup=keyboard
        )

