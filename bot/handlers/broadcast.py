"""
Рассылка сообщений участникам факультета.
Доступна только главным админам.
"""
import logging
import asyncio
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from db.session import async_session_maker
from db.models import Administrator, Faculty, User, UserProgress

logger = logging.getLogger(__name__)

broadcast_router = Router()


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


class BroadcastStates(StatesGroup):
    waiting_message = State()
    confirm = State()


# === Команда /broadcast ===

@broadcast_router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Начать рассылку"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer(
            "❌ Эта команда доступна только главным админам факультетов.\n\n"
            "<i>Если вы проверяющий — обратитесь к главному админу.</i>"
        )
        return
    
    # Получаем статистику по пользователям
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        # Считаем пользователей с этим факультетом
        result = await db.execute(
            select(func.count(User.id)).where(User.faculty_id == admin.faculty_id)
        )
        user_count = result.scalar() or 0
        
        # Статистика по статусам
        result = await db.execute(
            select(UserProgress.status, func.count(UserProgress.id))
            .where(UserProgress.faculty_id == admin.faculty_id)
            .group_by(UserProgress.status)
        )
        status_counts = dict(result.fetchall())
    
    if user_count == 0:
        await message.answer(
            f"📭 <b>Нет пользователей для рассылки</b>\n\n"
            f"Факультет «{faculty.name}» пока не имеет участников."
        )
        return
    
    await state.update_data(
        faculty_id=admin.faculty_id,
        faculty_name=faculty.name
    )
    
    not_started = status_counts.get('not_started', 0)
    in_progress = status_counts.get('in_progress', 0)
    submitted = status_counts.get('submitted', 0)
    
    await message.answer(
        f"📢 <b>Рассылка по факультету «{faculty.name}»</b>\n\n"
        f"👥 Всего участников: <b>{user_count}</b>\n\n"
        f"<b>По статусу анкеты:</b>\n"
        f"• Не начали: {not_started}\n"
        f"• В процессе: {in_progress}\n"
        f"• Отправили: {submitted}\n\n"
        f"Выберите аудиторию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👥 Всем ({user_count})", callback_data="bcf:all")],
            [InlineKeyboardButton(text=f"📝 Не начали ({not_started})", callback_data="bcf:not_started")],
            [InlineKeyboardButton(text=f"✏️ В процессе ({in_progress})", callback_data="bcf:in_progress")],
            [InlineKeyboardButton(text=f"✅ Отправили ({submitted})", callback_data="bcf:submitted")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="bc:cancel")]
        ])
    )


@broadcast_router.message(Command("cancel"), BroadcastStates.waiting_message)
@broadcast_router.message(Command("cancel"), BroadcastStates.confirm)
async def cmd_cancel_broadcast(message: Message, state: FSMContext):
    """Отменить рассылку"""
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@broadcast_router.callback_query(F.data == "bc:cancel")
async def callback_cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отменить рассылку"""
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.answer()


@broadcast_router.message(BroadcastStates.waiting_message, F.text)
async def process_broadcast_text(message: Message, state: FSMContext):
    """Получить текст для рассылки"""
    await state.update_data(
        broadcast_type="text",
        broadcast_text=message.text,
        broadcast_entities=message.entities
    )
    await state.set_state(BroadcastStates.confirm)
    
    data = await state.get_data()
    
    await message.answer(
        f"📋 <b>Предпросмотр рассылки</b>\n\n"
        f"Факультет: «{data['faculty_name']}»\n"
        f"Получателей: {data['user_count']}\n\n"
        f"─────────────────\n\n"
        f"{message.text}\n\n"
        f"─────────────────\n\n"
        f"Отправить рассылку?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="bc:send"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="bc:cancel")
            ],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="bc:edit")]
        ])
    )


@broadcast_router.message(BroadcastStates.waiting_message, F.photo)
async def process_broadcast_photo(message: Message, state: FSMContext):
    """Получить фото для рассылки"""
    await state.update_data(
        broadcast_type="photo",
        broadcast_photo_id=message.photo[-1].file_id,  # Самое большое фото
        broadcast_caption=message.caption,
        broadcast_entities=message.caption_entities
    )
    await state.set_state(BroadcastStates.confirm)
    
    data = await state.get_data()
    
    caption_preview = message.caption[:100] + "..." if message.caption and len(message.caption) > 100 else (message.caption or "<без подписи>")
    
    await message.answer(
        f"📋 <b>Предпросмотр рассылки</b>\n\n"
        f"Факультет: «{data['faculty_name']}»\n"
        f"Получателей: {data['user_count']}\n"
        f"Тип: 📷 Фото\n"
        f"Подпись: {caption_preview}\n\n"
        f"Отправить рассылку?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="bc:send"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="bc:cancel")
            ],
            [InlineKeyboardButton(text="✏️ Изменить", callback_data="bc:edit")]
        ])
    )


@broadcast_router.callback_query(F.data == "bc:edit")
async def callback_edit_broadcast(callback: CallbackQuery, state: FSMContext):
    """Изменить сообщение"""
    await state.set_state(BroadcastStates.waiting_message)
    await callback.message.edit_text(
        "✏️ Отправьте новое сообщение для рассылки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="bc:cancel")]
        ])
    )
    await callback.answer()


@broadcast_router.callback_query(F.data == "bc:send", BroadcastStates.confirm)
async def callback_send_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Отправить рассылку"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    data = await state.get_data()
    await state.clear()
    
    filter_info = ""
    if data.get('filter_name'):
        filter_info = f"Фильтр: {data['filter_name']}\n"
    
    # Обновляем сообщение
    await callback.message.edit_text(
        f"⏳ <b>Рассылка началась...</b>\n\n"
        f"Факультет: «{data['faculty_name']}»\n"
        f"{filter_info}"
        f"Получателей: {data['user_count']}"
    )
    await callback.answer("Рассылка запущена!")
    
    # Получаем пользователей (с учётом фильтра)
    async with async_session_maker() as db:
        filter_type = data.get('filter_type')
        
        if filter_type and filter_type != 'all':
            # Фильтрованная рассылка - берём из UserProgress
            result = await db.execute(
                select(User.telegram_id)
                .join(UserProgress, User.id == UserProgress.user_id)
                .where(
                    UserProgress.faculty_id == data['faculty_id'],
                    UserProgress.status == filter_type
                )
            )
        else:
            # Все пользователи факультета
            result = await db.execute(
                select(User.telegram_id).where(User.faculty_id == data['faculty_id'])
            )
        
        user_ids = [row[0] for row in result.fetchall()]
    
    # Отправляем сообщения
    success_count = 0
    fail_count = 0
    blocked_count = 0
    
    for user_id in user_ids:
        try:
            if data['broadcast_type'] == 'text':
                await bot.send_message(
                    user_id,
                    data['broadcast_text'],
                    entities=data.get('broadcast_entities')
                )
            elif data['broadcast_type'] == 'photo':
                await bot.send_photo(
                    user_id,
                    data['broadcast_photo_id'],
                    caption=data.get('broadcast_caption'),
                    caption_entities=data.get('broadcast_entities')
                )
            success_count += 1
        except Exception as e:
            error_msg = str(e).lower()
            if "blocked" in error_msg or "deactivated" in error_msg or "chat not found" in error_msg:
                blocked_count += 1
            else:
                fail_count += 1
                logger.warning(f"Не удалось отправить сообщение {user_id}: {e}")
        
        # Небольшая задержка чтобы не превысить лимиты
        await asyncio.sleep(0.05)
    
    # Итоговое сообщение
    result_text = f"✅ <b>Рассылка завершена!</b>\n\n"
    result_text += f"Факультет: «{data['faculty_name']}»\n"
    
    if data.get('filter_name'):
        result_text += f"Аудитория: {data['filter_name']}\n"
    
    result_text += f"\n📊 <b>Статистика:</b>\n"
    result_text += f"• Доставлено: {success_count}\n"
    
    if blocked_count > 0:
        result_text += f"• Заблокировали бота: {blocked_count}\n"
    
    if fail_count > 0:
        result_text += f"• Ошибки доставки: {fail_count}\n"
    
    result_text += f"\n<i>Всего в списке было: {len(user_ids)}</i>"
    
    await callback.message.edit_text(result_text)


@broadcast_router.callback_query(F.data.startswith("bcf:"))
async def callback_broadcast_filter_select(callback: CallbackQuery, state: FSMContext):
    """Выбрать фильтр аудитории"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    filter_type = callback.data.split(":")[1]
    
    # Получаем количество пользователей по фильтру
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        if filter_type == "all":
            result = await db.execute(
                select(func.count(User.id)).where(User.faculty_id == admin.faculty_id)
            )
            user_count = result.scalar() or 0
            filter_name = "Все участники"
        else:
            result = await db.execute(
                select(func.count(UserProgress.id)).where(
                    UserProgress.faculty_id == admin.faculty_id,
                    UserProgress.status == filter_type
                )
            )
            user_count = result.scalar() or 0
            filter_names = {
                "not_started": "Не начали анкету",
                "in_progress": "Начали, не закончили",
                "submitted": "Отправили анкету"
            }
            filter_name = filter_names.get(filter_type, filter_type)
    
    if user_count == 0:
        await callback.answer("Нет пользователей с таким статусом", show_alert=True)
        return
    
    await state.update_data(
        faculty_id=admin.faculty_id,
        faculty_name=faculty.name,
        user_count=user_count,
        filter_type=filter_type,
        filter_name=filter_name
    )
    await state.set_state(BroadcastStates.waiting_message)
    
    await callback.message.edit_text(
        f"📢 <b>Рассылка по факультету «{faculty.name}»</b>\n\n"
        f"Фильтр: <b>{filter_name}</b>\n"
        f"Получателей: <b>{user_count}</b> человек\n\n"
        f"Отправьте сообщение для рассылки.\n\n"
        f"<i>Для отмены: /cancel</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="bc:cancel")]
        ])
    )
    await callback.answer()
