"""
Обработка приглашений на собеседования и записи пользователей.

Команды:
- /send_interview_invitations - рассылка приглашений (Head Admin)
- Обработка записи на собеседование через callback
"""
import logging
from datetime import date, time, datetime, timedelta
from typing import Optional
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from db.engine import async_session_maker
from db.models import (
    Administrator, Faculty, HomeVideo, User, InterviewTimeSlot, 
    Interview, InterviewInvitation, InterviewStatus
)

logger = logging.getLogger(__name__)
invitations_router = Router()


# === FSM States ===
class InterviewBookingStates(StatesGroup):
    """Состояния для записи на собеседование"""
    select_date = State()
    select_time = State()
    confirm_booking = State()


# === Helpers ===
async def get_head_admin(telegram_id: int) -> Optional[Administrator]:
    """Получить Head Admin по telegram_id"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.role == "head_admin",
                Administrator.is_active == True
            )
        )
        return result.scalars().first()


def format_date(d: date) -> str:
    """Форматирование даты"""
    days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    return f"{d.day}.{d.month} ({days[d.weekday()]})"


# === Команда для рассылки приглашений ===
@invitations_router.message(Command("send_interview_invitations"))
async def cmd_send_invitations(message: Message, bot: Bot):
    """Рассылка приглашений на собеседования (Head Admin)"""
    admin = await get_head_admin(message.from_user.id)
    if not admin:
        await message.answer("⛔ Эта команда доступна только главным администраторам факультета")
        return
    
    # Сохраняем нужные значения до использования в новой сессии
    faculty_id = admin.faculty_id
    admin_id = admin.id
    
    if not faculty_id:
        await message.answer("❌ Вы не привязаны к факультету")
        return
    
    async with async_session_maker() as db:
        # Получаем факультет
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
        
        if not faculty:
            await message.answer("❌ Факультет не найден")
            return
        
        # Сохраняем название факультета до использования вне сессии
        faculty_name = faculty.name
        
        # Получаем всех пользователей с видео для этого факультета
        result = await db.execute(
            select(User).join(HomeVideo).where(
                HomeVideo.faculty_id == faculty_id
            ).distinct()
        )
        users_with_videos = result.scalars().all()
        
        if not users_with_videos:
            await message.answer("❌ Нет пользователей с загруженными видео")
            return
        
        # Получаем список тех, кому уже отправляли приглашения
        result = await db.execute(
            select(InterviewInvitation.user_id).where(
                InterviewInvitation.faculty_id == faculty_id
            )
        )
        already_invited = {row[0] for row in result.all()}
        
        # Фильтруем: отправляем только тем, кому ещё не отправляли
        users_to_invite = [u for u in users_with_videos if u.id not in already_invited]
        
        if not users_to_invite:
            await message.answer("✅ Все пользователи с видео уже получили приглашения")
            return
        
        # Получаем доступные слоты (только с местами > 0 и будущие)
        now = datetime.now()
        result = await db.execute(
            select(InterviewTimeSlot).where(
                InterviewTimeSlot.faculty_id == faculty_id,
                InterviewTimeSlot.max_participants > 0,
                or_(
                    InterviewTimeSlot.date > now.date(),
                    and_(
                        InterviewTimeSlot.date == now.date(),
                        InterviewTimeSlot.time >= now.time()
                    )
                )
            ).order_by(InterviewTimeSlot.date, InterviewTimeSlot.time)
        )
        all_slots = result.scalars().all()
        
        # Фильтруем слоты с учётом занятых мест
        available_slots = []
        for slot in all_slots:
            # Подсчитываем количество записей на этот слот
            result = await db.execute(
                select(func.count(Interview.id)).where(
                    Interview.interview_time_slot_id == slot.id,
                    Interview.status != InterviewStatus.CANCELLED
                )
            )
            booked_count = result.scalar() or 0
            available = slot.max_participants - booked_count
            
            if available > 0:
                available_slots.append(slot)
        
        if not available_slots:
            await message.answer("❌ Нет доступных слотов для записи (все слоты заполнены или прошли)")
            return
        
        # Группируем слоты по датам
        slots_by_date = {}
        for slot in available_slots:
            if slot.date not in slots_by_date:
                slots_by_date[slot.date] = []
            slots_by_date[slot.date].append(slot)
        
        # Формируем клавиатуру с датами
        keyboard_buttons = []
        for slot_date in sorted(slots_by_date.keys()):
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"📅 {format_date(slot_date)}",
                    callback_data=f"inv:date:{slot_date.isoformat()}"
                )
            ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Отправляем приглашения
        sent_count = 0
        failed_count = 0
        
        for user in users_to_invite:
            try:
                # Формируем сообщение
                text = (
                    f"🎯 <b>Приглашение на собеседование!</b>\n\n"
                    f"Факультет: <b>{faculty_name}</b>\n\n"
                    f"Выберите удобную дату и время для записи на собеседование.\n\n"
                    f"⚠️ <b>Важно:</b> Вы можете перезаписаться максимум <b>2 раза</b>.\n\n"
                    f"Выберите дату:"
                )
                
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                
                # Сохраняем информацию об отправке
                invitation = InterviewInvitation(
                    user_id=user.id,
                    faculty_id=faculty_id,
                    sent_by=admin_id
                )
                db.add(invitation)
                sent_count += 1
                
            except Exception as e:
                logger.error(f"Ошибка отправки приглашения пользователю {user.telegram_id}: {e}")
                failed_count += 1
        
        await db.commit()
        
        await message.answer(
            f"✅ <b>Рассылка завершена</b>\n\n"
            f"Отправлено: {sent_count}\n"
            f"Ошибок: {failed_count}\n\n"
            f"Приглашения отправлены только тем, кому ещё не приходило.",
            parse_mode="HTML"
        )


# === Обработка выбора даты ===
@invitations_router.callback_query(F.data.startswith("inv:date:"))
async def callback_select_date(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обработка выбора даты"""
    date_str = callback.data.split(":")[-1]
    selected_date = date.fromisoformat(date_str)
    
    async with async_session_maker() as db:
        # Получаем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем факультет пользователя (из последнего видео)
        result = await db.execute(
            select(HomeVideo).where(
                HomeVideo.user_id == user.id
            ).order_by(HomeVideo.submitted_at.desc()).limit(1)
        )
        video = result.scalars().first()
        
        if not video:
            await callback.answer("Видео не найдено", show_alert=True)
            return
        
        # Получаем доступные времена для этой даты
        now = datetime.now()
        result = await db.execute(
            select(InterviewTimeSlot).where(
                InterviewTimeSlot.faculty_id == video.faculty_id,
                InterviewTimeSlot.date == selected_date,
                InterviewTimeSlot.max_participants > 0,
                or_(
                    InterviewTimeSlot.date > now.date(),
                    and_(
                        InterviewTimeSlot.date == now.date(),
                        InterviewTimeSlot.time >= now.time()
                    )
                )
            ).order_by(InterviewTimeSlot.time)
        )
        slots = result.scalars().all()
        
        if not slots:
            await callback.answer("Нет доступных слотов на эту дату", show_alert=True)
            return
        
        # Проверяем текущие записи для подсчёта занятых мест
        slot_info = []
        for slot in slots:
            # Подсчитываем количество записей на этот слот
            result = await db.execute(
                select(func.count(Interview.id)).where(
                    Interview.interview_time_slot_id == slot.id,
                    Interview.status != InterviewStatus.CANCELLED
                )
            )
            booked_count = result.scalar() or 0
            available = slot.max_participants - booked_count
            
            if available > 0:
                slot_info.append((slot, available))
        
        if not slot_info:
            await callback.answer("Все слоты на эту дату заняты", show_alert=True)
            return
        
        # Формируем клавиатуру с временами
        keyboard_buttons = []
        for slot, available in slot_info:
            time_str = slot.time.strftime("%H:%M")
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"🕐 {time_str} (мест: {available})",
                    callback_data=f"inv:time:{slot.id}"
                )
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="« Назад к датам", callback_data="inv:back:dates")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(
            f"📅 <b>Выбрана дата: {format_date(selected_date)}</b>\n\n"
            f"Выберите удобное время:\n\n"
            f"⚠️ <b>Напоминание:</b> Вы можете перезаписаться максимум <b>2 раза</b>.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.update_data(selected_date=date_str, faculty_id=video.faculty_id)
        await state.set_state(InterviewBookingStates.select_time)


# === Обработка выбора времени ===
@invitations_router.callback_query(F.data.startswith("inv:time:"))
async def callback_select_time(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обработка выбора времени"""
    slot_id = int(callback.data.split(":")[-1])
    
    async with async_session_maker() as db:
        # Получаем слот
        result = await db.execute(
            select(InterviewTimeSlot).where(InterviewTimeSlot.id == slot_id)
        )
        slot = result.scalars().first()
        
        if not slot:
            await callback.answer("Слот не найден", show_alert=True)
            return
        
        # Проверяем доступность
        result = await db.execute(
            select(func.count(Interview.id)).where(
                Interview.interview_time_slot_id == slot.id,
                Interview.status != InterviewStatus.CANCELLED
            )
        )
        booked_count = result.scalar() or 0
        available = slot.max_participants - booked_count
        
        if available <= 0:
            await callback.answer("Этот слот уже занят", show_alert=True)
            return
        
        # Получаем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Проверяем существующие записи
        result = await db.execute(
            select(Interview).where(
                Interview.user_id == user.id,
                Interview.faculty_id == slot.faculty_id,
                Interview.status != InterviewStatus.CANCELLED
            )
        )
        existing_interview = result.scalars().first()
        
        # Проверяем лимит перезаписей
        if existing_interview:
            if existing_interview.reschedule_count >= 2:
                await callback.answer(
                    "❌ Вы уже использовали все возможности перезаписи (максимум 2 раза)",
                    show_alert=True
                )
                return
            
            reschedule_count = existing_interview.reschedule_count + 1
            remaining = 2 - reschedule_count
            confirm_text = (
                f"⚠️ <b>Перезапись на собеседование</b>\n\n"
                f"📅 Дата: {format_date(slot.date)}\n"
                f"🕐 Время: {slot.time.strftime('%H:%M')}\n\n"
                f"Это будет ваша <b>{reschedule_count + 1}-я</b> запись.\n"
                f"Осталось перезаписей: <b>{remaining}</b>\n\n"
                f"Подтвердите запись:"
            )
        else:
            confirm_text = (
                f"📅 <b>Подтверждение записи</b>\n\n"
                f"Дата: {format_date(slot.date)}\n"
                f"Время: {slot.time.strftime('%H:%M')}\n\n"
                f"Подтвердите запись:"
            )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"inv:confirm:{slot_id}")],
            [InlineKeyboardButton(text="« Назад", callback_data=f"inv:back:time:{slot.date.isoformat()}")]
        ])
        
        await callback.message.edit_text(
            confirm_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.update_data(slot_id=slot_id)
        await state.set_state(InterviewBookingStates.confirm_booking)


# === Обработка подтверждения записи ===
@invitations_router.callback_query(F.data.startswith("inv:confirm:"))
async def callback_confirm_booking(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтверждение и сохранение записи"""
    slot_id = int(callback.data.split(":")[-1])
    
    async with async_session_maker() as db:
        # Получаем слот
        result = await db.execute(
            select(InterviewTimeSlot).where(InterviewTimeSlot.id == slot_id)
        )
        slot = result.scalars().first()
        
        if not slot:
            await callback.answer("Слот не найден", show_alert=True)
            return
        
        # Проверяем доступность ещё раз
        result = await db.execute(
            select(func.count(Interview.id)).where(
                Interview.interview_time_slot_id == slot.id,
                Interview.status != InterviewStatus.CANCELLED
            )
        )
        booked_count = result.scalar() or 0
        available = slot.max_participants - booked_count
        
        if available <= 0:
            await callback.answer("Этот слот уже занят", show_alert=True)
            return
        
        # Получаем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Проверяем существующие записи
        result = await db.execute(
            select(Interview).where(
                Interview.user_id == user.id,
                Interview.faculty_id == slot.faculty_id,
                Interview.status != InterviewStatus.CANCELLED
            )
        )
        existing_interview = result.scalars().first()
        
        if existing_interview:
            # Перезапись
            if existing_interview.reschedule_count >= 2:
                await callback.answer(
                    "❌ Вы уже использовали все возможности перезаписи",
                    show_alert=True
                )
                return
            
            # Отменяем старую запись
            existing_interview.status = InterviewStatus.CANCELLED
            
            # Создаём новую запись
            new_interview = Interview(
                user_id=user.id,
                faculty_id=slot.faculty_id,
                interview_time_slot_id=slot_id,
                reschedule_count=existing_interview.reschedule_count + 1,
                status=InterviewStatus.SCHEDULED
            )
            db.add(new_interview)
        else:
            # Новая запись
            new_interview = Interview(
                user_id=user.id,
                faculty_id=slot.faculty_id,
                interview_time_slot_id=slot_id,
                reschedule_count=0,
                status=InterviewStatus.SCHEDULED
            )
            db.add(new_interview)
        
        await db.commit()
        
        # Сохраняем нужные значения до закрытия сессии
        slot_date = slot.date
        slot_time = slot.time
        reschedule_count = new_interview.reschedule_count
        
        reschedule_info = ""
        if existing_interview:
            remaining = 2 - reschedule_count
            reschedule_info = f"\n\n⚠️ Осталось перезаписей: <b>{remaining}</b>"
        
        await callback.message.edit_text(
            f"✅ <b>Запись подтверждена!</b>\n\n"
            f"📅 Дата: {format_date(slot_date)}\n"
            f"🕐 Время: {slot_time.strftime('%H:%M')}\n\n"
            f"Мы ждём вас на собеседовании!{reschedule_info}",
            parse_mode="HTML"
        )
        
        await state.clear()


# === Обработка кнопки "Назад" ===
@invitations_router.callback_query(F.data == "inv:back:dates")
async def callback_back_to_dates(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Возврат к выбору дат"""
    async with async_session_maker() as db:
        # Получаем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем факультет
        result = await db.execute(
            select(HomeVideo).where(
                HomeVideo.user_id == user.id
            ).order_by(HomeVideo.submitted_at.desc()).limit(1)
        )
        video = result.scalars().first()
        
        if not video:
            await callback.answer("Видео не найдено", show_alert=True)
            return
        
        # Получаем доступные даты
        now = datetime.now().date()
        result = await db.execute(
            select(InterviewTimeSlot.date).where(
                InterviewTimeSlot.faculty_id == video.faculty_id,
                InterviewTimeSlot.max_participants > 0,
                or_(
                    InterviewTimeSlot.date > now,
                    and_(
                        InterviewTimeSlot.date == now,
                        InterviewTimeSlot.time >= datetime.now().time()
                    )
                )
            ).distinct().order_by(InterviewTimeSlot.date)
        )
        dates = [row[0] for row in result.all()]
        
        if not dates:
            await callback.answer("Нет доступных дат", show_alert=True)
            return
        
        # Формируем клавиатуру
        keyboard_buttons = []
        for slot_date in dates:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"📅 {format_date(slot_date)}",
                    callback_data=f"inv:date:{slot_date.isoformat()}"
                )
            ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        # Получаем факультет
        result = await db.execute(
            select(Faculty).where(Faculty.id == video.faculty_id)
        )
        faculty = result.scalars().first()
        faculty_name = faculty.name if faculty else "Неизвестно"
        
        await callback.message.edit_text(
            f"🎯 <b>Выберите дату для записи на собеседование</b>\n\n"
            f"Факультет: <b>{faculty_name}</b>\n\n"
            f"⚠️ <b>Важно:</b> Вы можете перезаписаться максимум <b>2 раза</b>.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.set_state(InterviewBookingStates.select_date)


@invitations_router.callback_query(F.data.startswith("inv:back:time:"))
async def callback_back_to_time(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Возврат к выбору времени"""
    date_str = callback.data.split(":")[-1]
    selected_date = date.fromisoformat(date_str)
    
    async with async_session_maker() as db:
        # Получаем пользователя
        result = await db.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Получаем факультет пользователя (из последнего видео)
        result = await db.execute(
            select(HomeVideo).where(
                HomeVideo.user_id == user.id
            ).order_by(HomeVideo.submitted_at.desc()).limit(1)
        )
        video = result.scalars().first()
        
        if not video:
            await callback.answer("Видео не найдено", show_alert=True)
            return
        
        # Получаем доступные времена для этой даты
        now = datetime.now()
        result = await db.execute(
            select(InterviewTimeSlot).where(
                InterviewTimeSlot.faculty_id == video.faculty_id,
                InterviewTimeSlot.date == selected_date,
                InterviewTimeSlot.max_participants > 0,
                or_(
                    InterviewTimeSlot.date > now.date(),
                    and_(
                        InterviewTimeSlot.date == now.date(),
                        InterviewTimeSlot.time >= now.time()
                    )
                )
            ).order_by(InterviewTimeSlot.time)
        )
        slots = result.scalars().all()
        
        if not slots:
            await callback.answer("Нет доступных слотов на эту дату", show_alert=True)
            return
        
        # Проверяем текущие записи для подсчёта занятых мест
        slot_info = []
        for slot in slots:
            # Подсчитываем количество записей на этот слот
            result = await db.execute(
                select(func.count(Interview.id)).where(
                    Interview.interview_time_slot_id == slot.id,
                    Interview.status != InterviewStatus.CANCELLED
                )
            )
            booked_count = result.scalar() or 0
            available = slot.max_participants - booked_count
            
            if available > 0:
                slot_info.append((slot, available))
        
        if not slot_info:
            await callback.answer("Все слоты на эту дату заняты", show_alert=True)
            return
        
        # Формируем клавиатуру с временами
        keyboard_buttons = []
        for slot, available in slot_info:
            time_str = slot.time.strftime("%H:%M")
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"🕐 {time_str} (мест: {available})",
                    callback_data=f"inv:time:{slot.id}"
                )
            ])
        
        keyboard_buttons.append([
            InlineKeyboardButton(text="« Назад к датам", callback_data="inv:back:dates")
        ])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        
        await callback.message.edit_text(
            f"📅 <b>Выбрана дата: {format_date(selected_date)}</b>\n\n"
            f"Выберите удобное время:\n\n"
            f"⚠️ <b>Напоминание:</b> Вы можете перезаписаться максимум <b>2 раза</b>.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.update_data(selected_date=date_str, faculty_id=video.faculty_id)
        await state.set_state(InterviewBookingStates.select_time)
