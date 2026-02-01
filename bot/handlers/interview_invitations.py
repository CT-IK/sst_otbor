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
from config import settings

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


def is_slot_available_min_10_hours(slot_date: date, slot_time: time, now: datetime) -> bool:
    """
    Проверяет, что до слота осталось не менее 10 часов.
    Возвращает True, если можно записаться, False - если слишком поздно.
    """
    slot_datetime = datetime.combine(slot_date, slot_time)
    time_diff = slot_datetime - now
    
    # Проверяем, что разница не менее 10 часов (36000 секунд)
    return time_diff.total_seconds() >= 10 * 3600


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
        
        # Фильтруем слоты с учётом занятых мест и ограничения 10 часов
        available_slots = []
        for slot in all_slots:
            # Проверяем ограничение 10 часов
            if not is_slot_available_min_10_hours(slot.date, slot.time, now):
                continue
            
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
        
        # Отправляем приглашения с стандартным сообщением
        await send_invitations_with_custom_message(
            faculty_id=faculty_id,
            admin_telegram_id=message.from_user.id,
            custom_message=None,
            message_entities=None,
            bot=bot,
            update_message=message
        )


async def send_invitations_with_custom_message(
    faculty_id: int,
    admin_telegram_id: int,
    custom_message: str | None,
    message_entities: list | None,
    bot: Bot,
    update_message: Message | None = None
):
    """
    Рассылка приглашений на собеседования с возможностью кастомного сообщения.
    
    Args:
        faculty_id: ID факультета
        admin_telegram_id: Telegram ID администратора
        custom_message: Кастомное сообщение (если None, используется стандартное)
        message_entities: HTML entities из оригинального сообщения
        bot: Экземпляр бота
        update_message: Сообщение для обновления статуса (опционально)
    """
    async with async_session_maker() as db:
        # Получаем факультет
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
        
        if not faculty:
            if update_message:
                await update_message.edit_text("❌ Факультет не найден")
            return
        
        faculty_name = faculty.name
        
        # Получаем всех пользователей с видео для этого факультета
        result = await db.execute(
            select(User).join(HomeVideo).where(
                HomeVideo.faculty_id == faculty_id
            ).distinct()
        )
        users_with_videos = result.scalars().all()
        
        if not users_with_videos:
            if update_message:
                await update_message.edit_text("❌ Нет пользователей с загруженными видео")
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
            if update_message:
                await update_message.edit_text("✅ Все пользователи с видео уже получили приглашения")
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
        
        # Фильтруем слоты с учётом занятых мест и ограничения 10 часов
        available_slots = []
        for slot in all_slots:
            # Проверяем ограничение 10 часов
            if not is_slot_available_min_10_hours(slot.date, slot.time, now):
                continue
            
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
            if update_message:
                await update_message.edit_text("❌ Нет доступных слотов для записи (все слоты заполнены или прошли)")
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
        
        # Получаем администратора для записи в БД
        result = await db.execute(
            select(Administrator).where(Administrator.telegram_id == admin_telegram_id)
        )
        admin = result.scalars().first()
        admin_id = admin.id if admin else None
        
        # Отправляем приглашения
        sent_count = 0
        failed_count = 0
        
        for user in users_to_invite:
            try:
                # Формируем сообщение
                if custom_message:
                    # Используем кастомное сообщение
                    text = (
                        f"{custom_message}\n\n"
                        f"─────────────────\n\n"
                        f"⚠️ <b>Важно:</b> Вы можете перезаписаться максимум <b>2 раза</b>.\n\n"
                        f"⚠️ <b>Ограничение:</b> Запись доступна не менее чем за <b>10 часов</b> до начала собеседования.\n\n"
                        f"❓ В случае технических неполадок обращайтесь к @yanejettt\n\n"
                        f"Выберите дату:"
                    )
                else:
                    # Стандартное сообщение
                    text = (
                        f"🎯 <b>Приглашение на собеседование!</b>\n\n"
                        f"Факультет: <b>{faculty_name}</b>\n\n"
                        f"Выберите удобную дату и время для записи на собеседование.\n\n"
                        f"⚠️ <b>Важно:</b> Вы можете перезаписаться максимум <b>2 раза</b>.\n\n"
                        f"⚠️ <b>Ограничение:</b> Запись доступна не менее чем за <b>10 часов</b> до начала собеседования.\n\n"
                        f"❓ В случае технических неполадок обращайтесь к @yanejettt\n\n"
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
        
        result_text = (
            f"✅ <b>Рассылка завершена</b>\n\n"
            f"Отправлено: {sent_count}\n"
            f"Ошибок: {failed_count}\n\n"
            f"Приглашения отправлены только тем, кому ещё не приходило."
        )
        
        if update_message:
            try:
                await update_message.edit_text(result_text, parse_mode="HTML")
            except Exception:
                await bot.send_message(admin_telegram_id, result_text, parse_mode="HTML")


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
        
        # Проверяем текущие записи для подсчёта занятых мест и ограничение 10 часов
        slot_info = []
        for slot in slots:
            # Проверяем ограничение 10 часов
            if not is_slot_available_min_10_hours(slot.date, slot.time, now):
                continue
            
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
            await callback.answer("Все слоты на эту дату заняты или недоступны (менее 10 часов до начала)", show_alert=True)
            return
        
        # Формируем клавиатуру с временами
        keyboard_buttons = []
        for slot, available in slot_info:
            time_str = slot.time.strftime("%H:%M")
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"🕐 {time_str}",
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
            f"⚠️ <b>Напоминание:</b> Вы можете перезаписаться максимум <b>2 раза</b>.\n\n"
            f"⚠️ <b>Ограничение:</b> Запись доступна не менее чем за <b>10 часов</b> до начала.\n\n"
            f"❓ В случае технических неполадок обращайтесь к @yanejettt",
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
        
        # Проверяем существующие записи - ищем активную запись (SCHEDULED)
        # Важно: ищем только активные записи, не отмененные
        result = await db.execute(
            select(Interview).where(
                Interview.user_id == user.id,
                Interview.faculty_id == slot.faculty_id,
                Interview.status == InterviewStatus.SCHEDULED
            ).order_by(Interview.id.desc())
        )
        existing_interview = result.scalars().first()
        
        # Дополнительно: проверяем все записи пользователя для отладки
        result_all = await db.execute(
            select(Interview).where(
                Interview.user_id == user.id,
                Interview.faculty_id == slot.faculty_id
            ).order_by(Interview.id.desc())
        )
        all_interviews = result_all.scalars().all()
        logger.info(f"[callback_select_time] Все записи для user_id={user.id}, faculty_id={slot.faculty_id}: {[(i.id, i.status, i.reschedule_count) for i in all_interviews]}")
        
        # Проверяем лимит перезаписей
        # Если есть активная запись, проверяем её reschedule_count
        if existing_interview:
            # Сохраняем reschedule_count в локальную переменную
            current_reschedule_count = existing_interview.reschedule_count
            logger.info(f"[callback_select_time] Найдена существующая активная запись для user_id={user.id}, interview_id={existing_interview.id}, reschedule_count={current_reschedule_count}, status={existing_interview.status}")
            
            # Предупреждаем о лимите перезаписей, но не блокируем
            # reschedule_count = 0 означает первую запись (можно перезаписаться 2 раза)
            # reschedule_count = 1 означает первую перезапись (можно перезаписаться еще 1 раз)
            # reschedule_count = 2 и более: превышен лимит, но разрешаем запись
            if current_reschedule_count >= 2:
                logger.info(f"[callback_select_time] Перезапись превышает лимит для user_id={user.id}, reschedule_count={current_reschedule_count}, но разрешаем")
            
            # Это перезапись - показываем информацию о перезаписи
            reschedule_count = current_reschedule_count + 1
            remaining = max(0, 2 - reschedule_count)  # Не показываем отрицательные значения
            
            if reschedule_count > 2:
                reschedule_warning = f"\n\n⚠️ <b>Внимание:</b> Вы превысили рекомендуемый лимит перезаписей (рекомендуется максимум 2 раза)."
            elif reschedule_count == 2:
                reschedule_warning = f"\n\n⚠️ <b>Внимание:</b> Это ваша последняя рекомендуемая перезапись (максимум 2 раза)."
            else:
                reschedule_warning = f"\n\n⚠️ <b>Напоминание:</b> Вы можете перезаписаться максимум <b>2 раза</b>. Осталось перезаписей: <b>{remaining}</b>"
            
            confirm_text = (
                f"⚠️ <b>Перезапись на собеседование</b>\n\n"
                f"📅 Дата: {format_date(slot.date)}\n"
                f"🕐 Время: {slot.time.strftime('%H:%M')}\n\n"
                f"Это будет ваша <b>{reschedule_count + 1}-я</b> запись.{reschedule_warning}\n\n"
                f"❓ В случае технических неполадок обращайтесь к @yanejettt\n\n"
                f"Подтвердите запись:"
            )
        else:
            # Новая запись (первая запись, не перезапись)
            logger.info(f"[callback_select_time] Новая запись (не перезапись) для user_id={user.id}, активных записей не найдено")
            confirm_text = (
                f"📅 <b>Подтверждение записи</b>\n\n"
                f"Дата: {format_date(slot.date)}\n"
                f"Время: {slot.time.strftime('%H:%M')}\n\n"
                f"⚠️ <b>Напоминание:</b> Вы можете перезаписаться максимум <b>2 раза</b>.\n\n"
                f"❓ В случае технических неполадок обращайтесь к @yanejettt\n\n"
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
        
        # Проверяем ограничение 10 часов
        now = datetime.now()
        if not is_slot_available_min_10_hours(slot.date, slot.time, now):
            await callback.answer(
                "❌ Нельзя записаться менее чем за 10 часов до собеседования",
                show_alert=True
            )
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
        
        # Получаем username из Telegram объекта
        telegram_username = callback.from_user.username if callback.from_user.username else None
        
        # Проверяем существующие записи - ищем активную запись (SCHEDULED)
        result = await db.execute(
            select(Interview).where(
                Interview.user_id == user.id,
                Interview.faculty_id == slot.faculty_id,
                Interview.status == InterviewStatus.SCHEDULED
            ).order_by(Interview.id.desc())
        )
        existing_interview = result.scalars().first()
        
        # Дополнительно: проверяем все записи пользователя для отладки
        result_all = await db.execute(
            select(Interview).where(
                Interview.user_id == user.id,
                Interview.faculty_id == slot.faculty_id
            ).order_by(Interview.id.desc())
        )
        all_interviews = result_all.scalars().all()
        logger.info(f"[callback_confirm_booking] Все записи для user_id={user.id}, faculty_id={slot.faculty_id}: {[(i.id, i.status, i.reschedule_count) for i in all_interviews]}")
        
        # Сохраняем нужные значения из slot ДО commit()
        slot_date = slot.date
        slot_time = slot.time
        faculty_id_for_notification = slot.faculty_id
        
        # Сохраняем данные пользователя ДО commit()
        user_fio = ""
        username = telegram_username if telegram_username else "не указан"
        parts = []
        if user.first_name:
            parts.append(user.first_name)
        if user.second_name:
            parts.append(user.second_name)
        if user.surname:
            parts.append(user.surname)
        user_fio = " ".join(parts) if parts else f"ID {user.telegram_id}"
        
        if existing_interview:
            # Перезапись
            # Сохраняем reschedule_count ДО изменения
            old_reschedule_count = existing_interview.reschedule_count
            logger.info(f"[callback_confirm_booking] Перезапись для user_id={user.id}, interview_id={existing_interview.id}, текущий reschedule_count={old_reschedule_count}, status={existing_interview.status}")
            
            # Предупреждаем о лимите перезаписей, но не блокируем
            # reschedule_count = 0: первая запись, можно перезаписаться 2 раза
            # reschedule_count = 1: первая перезапись, можно перезаписаться еще 1 раз
            # reschedule_count = 2 и более: превышен лимит, но разрешаем запись
            if old_reschedule_count >= 2:
                logger.info(f"[callback_confirm_booking] Перезапись превышает лимит для user_id={user.id}, reschedule_count={old_reschedule_count}, но разрешаем")
            
            # Отменяем старую запись
            existing_interview.status = InterviewStatus.CANCELLED
            
            # Создаём новую запись с увеличенным счетчиком
            new_reschedule_count = old_reschedule_count + 1
            new_interview = Interview(
                user_id=user.id,
                faculty_id=faculty_id_for_notification,
                interview_time_slot_id=slot_id,
                reschedule_count=new_reschedule_count,
                status=InterviewStatus.SCHEDULED
            )
            db.add(new_interview)
            reschedule_count = new_reschedule_count
        else:
            # Новая запись (первая запись, не перезапись)
            logger.info(f"Новая запись (не перезапись) для user_id={user.id}")
            new_interview = Interview(
                user_id=user.id,
                faculty_id=faculty_id_for_notification,
                interview_time_slot_id=slot_id,
                reschedule_count=0,
                status=InterviewStatus.SCHEDULED
            )
            db.add(new_interview)
            reschedule_count = 0
        
        # Получаем ID интервью ДО commit() (чтобы избежать MissingGreenlet)
        interview_id = new_interview.id
        
        await db.commit()
        
        # Получаем факультет для уведомления в новой сессии
        video_chat_id = None
        async with async_session_maker() as db_notif:
            result = await db_notif.execute(
                select(Faculty).where(Faculty.id == faculty_id_for_notification)
            )
            faculty = result.scalars().first()
            # Сохраняем video_chat_id ДО закрытия сессии
            if faculty:
                video_chat_id = faculty.video_chat_id
        
        reschedule_info = ""
        # Показываем информацию о перезаписях только если это действительно перезапись
        if existing_interview and reschedule_count > 0:
            remaining = max(0, 2 - reschedule_count)  # Не показываем отрицательные значения
            if reschedule_count > 2:
                reschedule_info = f"\n\n⚠️ <b>Внимание:</b> Вы превысили рекомендуемый лимит перезаписей (рекомендуется максимум 2 раза)."
            elif reschedule_count == 2:
                reschedule_info = f"\n\n⚠️ <b>Внимание:</b> Вы использовали рекомендуемый лимит перезаписей (максимум 2 раза)."
            else:
                reschedule_info = f"\n\n⚠️ Осталось перезаписей: <b>{remaining}</b>"
        
        await callback.message.edit_text(
            f"✅ <b>Запись подтверждена!</b>\n\n"
            f"📅 Дата: {format_date(slot_date)}\n"
            f"🕐 Время: {slot_time.strftime('%H:%M')}\n\n"
            f"Мы ждём вас на собеседовании!{reschedule_info}",
            parse_mode="HTML"
        )
        
        # Отправляем уведомление в чат факультета
        if video_chat_id:
            try:
                import httpx
                bot_token = settings.telegram_bot_token
                if bot_token:
                    notification_text = (
                        f"📝 <b>Новая запись на собеседование</b>\n\n"
                        f"👤 <b>Кандидат:</b> {user_fio}\n"
                        f"📱 Username: @{username}\n"
                        f"📅 <b>Дата:</b> {format_date(slot_date)}\n"
                        f"🕐 <b>Время:</b> {slot_time.strftime('%H:%M')}\n\n"
                        f"ID записи: {interview_id}"
                    )
                    
                    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    async with httpx.AsyncClient() as client:
                        response = await client.post(url, json={
                            "chat_id": video_chat_id,
                            "text": notification_text,
                            "parse_mode": "HTML"
                        })
                        response.raise_for_status()
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления в чат {video_chat_id}: {e}")
        
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
        
        # Получаем доступные даты с учётом ограничения 10 часов
        now = datetime.now()
        result = await db.execute(
            select(InterviewTimeSlot).where(
                InterviewTimeSlot.faculty_id == video.faculty_id,
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
        
        # Фильтруем по ограничению 10 часов и проверяем доступность мест
        available_dates = set()
        for slot in all_slots:
            if is_slot_available_min_10_hours(slot.date, slot.time, now):
                # Проверяем доступность мест
                result = await db.execute(
                    select(func.count(Interview.id)).where(
                        Interview.interview_time_slot_id == slot.id,
                        Interview.status != InterviewStatus.CANCELLED
                    )
                )
                booked_count = result.scalar() or 0
                available = slot.max_participants - booked_count
                if available > 0:
                    available_dates.add(slot.date)
        
        dates = sorted(list(available_dates))
        
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
            f"⚠️ <b>Важно:</b> Вы можете перезаписаться максимум <b>2 раза</b>.\n\n"
            f"⚠️ <b>Ограничение:</b> Запись доступна не менее чем за <b>10 часов</b> до начала.\n\n"
            f"❓ В случае технических неполадок обращайтесь к @yanejettt",
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
        
        # Проверяем текущие записи для подсчёта занятых мест и ограничение 10 часов
        slot_info = []
        for slot in slots:
            # Проверяем ограничение 10 часов
            if not is_slot_available_min_10_hours(slot.date, slot.time, now):
                continue
            
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
            await callback.answer("Все слоты на эту дату заняты или недоступны (менее 10 часов до начала)", show_alert=True)
            return
        
        # Формируем клавиатуру с временами
        keyboard_buttons = []
        for slot, available in slot_info:
            time_str = slot.time.strftime("%H:%M")
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"🕐 {time_str}",
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
            f"⚠️ <b>Напоминание:</b> Вы можете перезаписаться максимум <b>2 раза</b>.\n\n"
            f"⚠️ <b>Ограничение:</b> Запись доступна не менее чем за <b>10 часов</b> до начала.\n\n"
            f"❓ В случае технических неполадок обращайтесь к @yanejettt",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
        await state.update_data(selected_date=date_str, faculty_id=video.faculty_id)
        await state.set_state(InterviewBookingStates.select_time)
