"""
Команды администратора факультета.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from config import settings
from db.engine import async_session_maker
from db.models import (
    Faculty, StageType, StageStatus, User, Questionnaire,
    ApprovalQueue, ApprovalStatus, Administrator
)

admin_router = Router()


# === Проверка админа ===
async def get_admin(telegram_id: int) -> Optional[Administrator]:
    """Получить объект администратора по telegram_id"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.is_active == True
            )
        )
        return result.scalars().first()


async def is_admin(telegram_id: int) -> bool:
    """Проверить, является ли пользователь администратором"""
    # В dev режиме — все админы
    if settings.is_dev:
        return True
    
    admin = await get_admin(telegram_id)
    return admin is not None


async def get_admin_faculty_id(telegram_id: int) -> Optional[int]:
    """Получить ID факультета админа"""
    # В dev режиме - используем тестовый факультет
    if settings.is_dev:
        return settings.dev_faculty_id
    
    admin = await get_admin(telegram_id)
    return admin.faculty_id if admin else None


# === Команды ===

@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Панель администратора"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Вопросы", callback_data="admin:questions")],
        [InlineKeyboardButton(text="🎯 Этапы отбора", callback_data="admin:stages")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Заявки на проверку", callback_data="admin:approvals")],
    ])
    
    await message.answer(
        "🔧 <b>Панель администратора</b>\n\n"
        "Выберите раздел:",
        reply_markup=keyboard
    )


@admin_router.callback_query(F.data == "admin:stats")
async def callback_stats(callback: CallbackQuery):
    """Статистика"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        # Считаем статистику
        users_count = await db.scalar(select(func.count(User.id)))
        questionnaires_count = await db.scalar(select(func.count(Questionnaire.id)))
        pending_count = await db.scalar(
            select(func.count(ApprovalQueue.id)).where(
                ApprovalQueue.status == ApprovalStatus.PENDING
            )
        )
        
        # Факультеты
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
        
        faculty_stats = ""
        for f in faculties:
            stage_name = f.current_stage.value if f.current_stage else "не начат"
            status_name = f.stage_status.value if f.stage_status else "—"
            faculty_stats += f"\n  • {f.name}: {stage_name} ({status_name})"
    
    await callback.message.edit_text(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {users_count}\n"
        f"📝 Анкет отправлено: {questionnaires_count}\n"
        f"⏳ Ожидают проверки: {pending_count}\n\n"
        f"<b>Факультеты:</b>{faculty_stats or ' нет'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:stats")],
            [InlineKeyboardButton(text="« Назад", callback_data="admin:back")],
        ])
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin:stages")
async def callback_stages(callback: CallbackQuery):
    """Управление этапами — сразу переходим к факультету админа"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    faculty_id = await get_admin_faculty_id(callback.from_user.id)
    
    if not faculty_id:
        await callback.message.edit_text(
            "❌ Вы не привязаны к факультету.\n"
            "Обратитесь к супер-администратору.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="admin:back")],
            ])
        )
        await callback.answer()
        return
    
    # Сразу показываем этапы своего факультета
    await _show_faculty_stages(callback, faculty_id)


async def _show_faculty_stages(callback: CallbackQuery, faculty_id: int):
    """Внутренняя функция для показа этапов факультета"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    # Проверяем, что админ имеет доступ к этому факультету
    admin_faculty_id = await get_admin_faculty_id(callback.from_user.id)
    if admin_faculty_id and admin_faculty_id != faculty_id:
        # Супер-админы (без привязки) или не в dev режиме
        if not settings.is_super_admin(callback.from_user.id):
            await callback.answer("Нет доступа к этому факультету", show_alert=True)
            return
    
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
    
    if not faculty:
        await callback.answer("Факультет не найден", show_alert=True)
        return
    
    current_stage = faculty.current_stage.value if faculty.current_stage else "не начат"
    current_status = faculty.stage_status.value if faculty.stage_status else "—"
    
    # Кнопки управления
    buttons = [
        [InlineKeyboardButton(
            text="📝 Открыть анкету",
            callback_data=f"stages:set:{faculty_id}:questionnaire:open"
        )],
        [InlineKeyboardButton(
            text="🔒 Закрыть анкету",
            callback_data=f"stages:set:{faculty_id}:questionnaire:closed"
        )],
        [InlineKeyboardButton(
            text="🎬 Открыть домашку",
            callback_data=f"stages:set:{faculty_id}:home_video:open"
        )],
        [InlineKeyboardButton(
            text="🎤 Открыть собесы",
            callback_data=f"stages:set:{faculty_id}:interview:open"
        )],
        [InlineKeyboardButton(text="« Назад", callback_data="admin:stages")],
    ]
    
    await callback.message.edit_text(
        f"🎯 <b>{faculty.name}</b>\n\n"
        f"Текущий этап: <b>{current_stage}</b>\n"
        f"Статус: <b>{current_status}</b>\n\n"
        f"Выберите действие:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("stages:faculty:"))
async def callback_faculty_stages(callback: CallbackQuery):
    """Управление этапами конкретного факультета"""
    faculty_id = int(callback.data.split(":")[2])
    await _show_faculty_stages(callback, faculty_id)


@admin_router.callback_query(F.data.startswith("stages:set:"))
async def callback_set_stage(callback: CallbackQuery):
    """Установить этап"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    parts = callback.data.split(":")
    faculty_id = int(parts[2])
    stage_type = parts[3]
    stage_status = parts[4]
    
    # Проверяем доступ
    admin_faculty_id = await get_admin_faculty_id(callback.from_user.id)
    if admin_faculty_id and admin_faculty_id != faculty_id:
        if not settings.is_super_admin(callback.from_user.id):
            await callback.answer("Нет доступа к этому факультету", show_alert=True)
            return
    
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
        
        if not faculty:
            await callback.answer("Факультет не найден", show_alert=True)
            return
        
        # Обновляем этап
        faculty.current_stage = StageType(stage_type)
        faculty.stage_status = StageStatus(stage_status)
        
        # При переходе на этап HOME_VIDEO автоматически открываем приём видео
        if StageType(stage_type) == StageType.HOME_VIDEO and StageStatus(stage_status) == StageStatus.OPEN:
            faculty.video_submission_open = True
        
        await db.commit()
    
    await callback.answer(f"✅ Этап изменён: {stage_type} ({stage_status})", show_alert=True)
    
    # Обновляем сообщение
    await _show_faculty_stages(callback, faculty_id)


@admin_router.callback_query(F.data == "admin:back")
async def callback_back(callback: CallbackQuery):
    """Вернуться в главное меню админа"""
    await cmd_admin(callback.message)
    await callback.answer()


@admin_router.callback_query(F.data == "admin:questions")
async def callback_questions(callback: CallbackQuery):
    """Переход к вопросам"""
    await callback.message.edit_text(
        "📝 <b>Управление вопросами</b>\n\n"
        "Используйте команду /questions для управления вопросами анкеты.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Назад", callback_data="admin:back")],
        ])
    )
    await callback.answer()


@admin_router.callback_query(F.data == "admin:approvals")
async def callback_approvals(callback: CallbackQuery):
    """Заявки на проверку"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(ApprovalQueue)
            .where(ApprovalQueue.status == ApprovalStatus.PENDING)
            .limit(10)
        )
        approvals = result.scalars().all()
    
    if not approvals:
        await callback.message.edit_text(
            "✅ Нет заявок на проверку",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:approvals")],
                [InlineKeyboardButton(text="« Назад", callback_data="admin:back")],
            ])
        )
        await callback.answer()
        return
    
    # Кнопки для заявок
    buttons = []
    for a in approvals:
        buttons.append([
            InlineKeyboardButton(
                text=f"#{a.id} — {a.stage_type.value}",
                callback_data=f"approval:view:{a.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data="admin:back")])
    
    await callback.message.edit_text(
        f"👥 <b>Заявки на проверку</b>\n\n"
        f"Найдено: {len(approvals)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

