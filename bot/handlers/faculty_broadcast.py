"""
Универсальная рассылка для факультета.
Позволяет выбрать тип рассылки: обычное сообщение или приглашение на собеседование.
"""
import logging
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from db.session import async_session_maker
from db.models import Administrator, Faculty

logger = logging.getLogger(__name__)

faculty_broadcast_router = Router()


class InterviewInvitationStates(StatesGroup):
    """Состояния для настройки рассылки приглашений"""
    waiting_message = State()
    confirm = State()


async def get_head_admin(telegram_id: int) -> Optional[Administrator]:
    """Проверить, является ли пользователь главным админом"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.role == "head_admin",
                Administrator.is_active == True
            )
        )
        return result.scalars().first()


@faculty_broadcast_router.message(Command("faculty_broadcast"))
async def cmd_faculty_broadcast(message: Message):
    """Главное меню выбора типа рассылки"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer(
            "⛔ Эта команда доступна только главным администраторам факультета"
        )
        return
    
    if not admin.faculty_id:
        await message.answer("❌ Вы не привязаны к факультету")
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        if not faculty:
            await message.answer("❌ Факультет не найден")
            return
        
        faculty_name = faculty.name
    
    await message.answer(
        f"📢 <b>Рассылка по факультету «{faculty_name}»</b>\n\n"
        f"Выберите тип рассылки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Обычное сообщение",
                    callback_data="fbc:type:text"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Приглашение на собеседование",
                    callback_data="fbc:type:interview"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="fbc:cancel"
                )
            ]
        ]),
        parse_mode="HTML"
    )


@faculty_broadcast_router.callback_query(F.data == "fbc:cancel")
async def callback_cancel_faculty_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отменить выбор"""
    await state.clear()
    await callback.message.edit_text("❌ Отменено")
    await callback.answer()


@faculty_broadcast_router.callback_query(F.data == "fbc:type:text")
async def callback_select_text_broadcast(callback: CallbackQuery):
    """Выбрана рассылка обычного сообщения"""
    await callback.message.edit_text(
        "💬 <b>Рассылка обычного сообщения</b>\n\n"
        "Используйте команду <code>/broadcast</code> для рассылки обычных сообщений.\n\n"
        "Эта команда позволяет:\n"
        "• Отправить текст или фото\n"
        "• Выбрать аудиторию (всем, по статусу анкеты)\n"
        "• Предпросмотр перед отправкой",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Начать рассылку",
                    callback_data="fbc:start:text"
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="fbc:back"
                )
            ]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@faculty_broadcast_router.callback_query(F.data == "fbc:type:interview")
async def callback_select_interview_broadcast(callback: CallbackQuery, state: FSMContext):
    """Выбрана рассылка приглашений на собеседование"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin or not admin.faculty_id:
        await callback.answer("Ошибка доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        if not faculty:
            await callback.answer("Факультет не найден", show_alert=True)
            return
        
        faculty_name = faculty.name
    
    # Сохраняем данные в state
    await state.update_data(
        faculty_id=admin.faculty_id,
        faculty_name=faculty_name
    )
    
    await callback.message.edit_text(
        f"📅 <b>Рассылка приглашений на собеседование</b>\n\n"
        f"Факультет: <b>{faculty_name}</b>\n\n"
        f"Эта рассылка:\n"
        f"• Отправляется только пользователям с загруженным видео\n"
        f"• Отправляется только тем, кому ещё не отправляли приглашение\n"
        f"• Позволяет записаться на доступные слоты\n"
        f"• Учитывает ограничение 10 часов до начала\n\n"
        f"<b>Напишите сообщение для приглашения:</b>\n\n"
        f"<i>Вы можете использовать HTML-разметку. К кнопкам записи сообщение будет добавлено автоматически.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📝 Написать сообщение",
                    callback_data="fbc:write:message"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Использовать стандартное",
                    callback_data="fbc:start:interview:default"
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="fbc:back"
                )
            ]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@faculty_broadcast_router.callback_query(F.data == "fbc:back")
async def callback_back_to_menu(callback: CallbackQuery):
    """Вернуться в главное меню"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin or not admin.faculty_id:
        await callback.answer("Ошибка доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        if not faculty:
            await callback.answer("Факультет не найден", show_alert=True)
            return
        
        faculty_name = faculty.name
    
    await callback.message.edit_text(
        f"📢 <b>Рассылка по факультету «{faculty_name}»</b>\n\n"
        f"Выберите тип рассылки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Обычное сообщение",
                    callback_data="fbc:type:text"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📅 Приглашение на собеседование",
                    callback_data="fbc:type:interview"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="fbc:cancel"
                )
            ]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@faculty_broadcast_router.callback_query(F.data == "fbc:start:text")
async def callback_start_text_broadcast(callback: CallbackQuery, bot: Bot):
    """Запустить рассылку обычного сообщения"""
    await callback.message.edit_text(
        "💬 <b>Рассылка обычного сообщения</b>\n\n"
        "Используйте команду:\n"
        "<code>/broadcast</code>\n\n"
        "Эта команда откроет меню выбора аудитории и позволит отправить сообщение.\n\n"
        "Или нажмите кнопку ниже для быстрого запуска:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Начать рассылку",
                    callback_data="fbc:run:broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="fbc:back"
                )
            ]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@faculty_broadcast_router.callback_query(F.data == "fbc:run:broadcast")
async def callback_run_broadcast(callback: CallbackQuery):
    """Инструкция по использованию /broadcast"""
    await callback.message.edit_text(
        "💬 <b>Рассылка обычного сообщения</b>\n\n"
        "Для рассылки обычного сообщения используйте команду:\n"
        "<code>/broadcast</code>\n\n"
        "Эта команда позволит:\n"
        "• Выбрать аудиторию (всем, по статусу анкеты)\n"
        "• Отправить текст или фото\n"
        "• Предпросмотр перед отправкой\n\n"
        "<i>Просто введите /broadcast в чат</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="fbc:back"
                )
            ]
        ]),
        parse_mode="HTML"
    )
    await callback.answer("Используйте команду /broadcast")


@faculty_broadcast_router.callback_query(F.data == "fbc:write:message")
async def callback_write_message(callback: CallbackQuery, state: FSMContext):
    """Начать ввод сообщения для приглашения"""
    await state.set_state(InterviewInvitationStates.waiting_message)
    
    await callback.message.edit_text(
        "✏️ <b>Напишите сообщение для приглашения</b>\n\n"
        "Вы можете использовать HTML-разметку:\n"
        "• <b>жирный</b> — <code>&lt;b&gt;текст&lt;/b&gt;</code>\n"
        "• <i>курсив</i> — <code>&lt;i&gt;текст&lt;/i&gt;</code>\n"
        "• <code>моноширинный</code> — <code>&lt;code&gt;текст&lt;/code&gt;</code>\n\n"
        "К вашему сообщению автоматически будут добавлены:\n"
        "• Информация о перезаписи (максимум 2 раза)\n"
        "• Ограничение 10 часов до начала\n"
        "• Контакт для технических вопросов (@yanejettt)\n"
        "• Кнопки для записи\n\n"
        "<i>Для отмены: /cancel</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="fbc:cancel")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@faculty_broadcast_router.message(Command("cancel"), InterviewInvitationStates.waiting_message)
@faculty_broadcast_router.message(Command("cancel"), InterviewInvitationStates.confirm)
async def cmd_cancel_interview_invitation(message: Message, state: FSMContext):
    """Отменить рассылку приглашений"""
    await state.clear()
    await message.answer("❌ Рассылка приглашений отменена.")


@faculty_broadcast_router.message(InterviewInvitationStates.waiting_message, F.text)
async def process_invitation_message(message: Message, state: FSMContext):
    """Обработать введенное сообщение для приглашения"""
    data = await state.get_data()
    
    await state.update_data(
        custom_message=message.text,
        message_entities=message.entities
    )
    await state.set_state(InterviewInvitationStates.confirm)
    
    await message.answer(
        f"📋 <b>Предпросмотр сообщения</b>\n\n"
        f"Факультет: <b>{data.get('faculty_name', 'Неизвестно')}</b>\n\n"
        f"─────────────────\n\n"
        f"{message.text}\n\n"
        f"─────────────────\n\n"
        f"<i>К этому сообщению будут добавлены:\n"
        f"• Информация о перезаписи (максимум 2 раза)\n"
        f"• Ограничение 10 часов до начала\n"
        f"• Контакт @yanejettt\n"
        f"• Кнопки для записи</i>\n\n"
        f"Отправить рассылку?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="fbc:send:interview"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="fbc:cancel")
            ],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="fbc:edit:message")]
        ]),
        parse_mode="HTML"
    )


@faculty_broadcast_router.callback_query(F.data == "fbc:edit:message", InterviewInvitationStates.confirm)
async def callback_edit_message(callback: CallbackQuery, state: FSMContext):
    """Изменить сообщение"""
    await state.set_state(InterviewInvitationStates.waiting_message)
    
    await callback.message.edit_text(
        "✏️ <b>Напишите сообщение для приглашения</b>\n\n"
        "Вы можете использовать HTML-разметку:\n"
        "• <b>жирный</b> — <code>&lt;b&gt;текст&lt;/b&gt;</code>\n"
        "• <i>курсив</i> — <code>&lt;i&gt;текст&lt;/i&gt;</code>\n"
        "• <code>моноширинный</code> — <code>&lt;code&gt;текст&lt;/code&gt;</code>\n\n"
        "К вашему сообщению автоматически будут добавлены:\n"
        "• Информация о перезаписи (максимум 2 раза)\n"
        "• Ограничение 10 часов до начала\n"
        "• Контакт для технических вопросов (@yanejettt)\n"
        "• Кнопки для записи\n\n"
        "<i>Для отмены: /cancel</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="fbc:cancel")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@faculty_broadcast_router.callback_query(F.data == "fbc:start:interview:default")
async def callback_start_interview_default(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Запустить рассылку с стандартным сообщением"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin or not admin.faculty_id:
        await callback.answer("Ошибка доступа", show_alert=True)
        await state.clear()
        return
    
    # Обновляем сообщение
    await callback.message.edit_text(
        "⏳ <b>Запуск рассылки приглашений...</b>",
        parse_mode="HTML"
    )
    await callback.answer()
    
    # Импортируем функцию рассылки приглашений
    from bot.handlers.interview_invitations import send_invitations_with_custom_message
    
    # Вызываем функцию рассылки со стандартным сообщением
    await send_invitations_with_custom_message(
        faculty_id=admin.faculty_id,
        admin_telegram_id=callback.from_user.id,
        custom_message=None,
        message_entities=None,
        bot=bot,
        update_message=callback.message
    )
    
    await state.clear()


@faculty_broadcast_router.callback_query(F.data == "fbc:send:interview", InterviewInvitationStates.confirm)
async def callback_start_interview_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Запустить рассылку приглашений на собеседование"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin or not admin.faculty_id:
        await callback.answer("Ошибка доступа", show_alert=True)
        await state.clear()
        return
    
    data = await state.get_data()
    
    # Проверяем, что админ отправляет только своему факультету
    if data.get('faculty_id') != admin.faculty_id:
        await callback.answer("Ошибка: попытка отправить рассылку другому факультету", show_alert=True)
        await state.clear()
        return
    
    custom_message = data.get('custom_message')
    message_entities = data.get('message_entities')
    
    # Обновляем сообщение
    await callback.message.edit_text(
        "⏳ <b>Запуск рассылки приглашений...</b>",
        parse_mode="HTML"
    )
    await callback.answer()
    
    # Импортируем функцию рассылки приглашений
    from bot.handlers.interview_invitations import send_invitations_with_custom_message
    
    # Вызываем функцию рассылки с кастомным сообщением
    await send_invitations_with_custom_message(
        faculty_id=admin.faculty_id,
        admin_telegram_id=callback.from_user.id,
        custom_message=custom_message,
        message_entities=message_entities,
        bot=bot,
        update_message=callback.message
    )
    
    await state.clear()
