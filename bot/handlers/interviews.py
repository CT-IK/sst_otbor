"""
Управление собеседованиями.
Head Admin: создание дней и слотов.
Reviewer: отметка доступности.
"""
import logging
from datetime import datetime, date, time, timedelta
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from db.session import async_session_maker
from db.models import (
    Administrator, Faculty, InterviewDay, TimeSlot, 
    TimeSlotAvailability, Interview
)

logger = logging.getLogger(__name__)

interviews_router = Router()

# Стандартные часы для слотов (10:00 - 22:00)
DEFAULT_HOURS = list(range(10, 23))  # 10, 11, 12, ..., 22


async def get_admin(telegram_id: int) -> Optional[Administrator]:
    """Получить админа (любую роль)"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.is_active == True
            )
        )
        return result.scalars().first()


async def get_head_admin(telegram_id: int) -> Optional[Administrator]:
    """Получить главного админа"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.role == "head_admin",
                Administrator.is_active == True
            )
        )
        return result.scalars().first()


# === FSM States ===

class CreateDayStates(StatesGroup):
    enter_date = State()
    enter_location = State()
    configure_slots = State()


class EditSlotsStates(StatesGroup):
    select_day = State()
    configure_slots = State()


# ============================================================
# HEAD ADMIN: Управление днями собеседований
# ============================================================

@interviews_router.message(Command("interview_days"))
async def cmd_interview_days(message: Message):
    """Список дней собеседований"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer("❌ Эта команда доступна только главным админам.")
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        result = await db.execute(
            select(InterviewDay)
            .options(selectinload(InterviewDay.time_slots))
            .where(
                InterviewDay.faculty_id == admin.faculty_id,
                InterviewDay.is_active == True
            )
            .order_by(InterviewDay.date)
        )
        days = result.scalars().all()
    
    text = f"📅 <b>Дни собеседований — {faculty.name}</b>\n\n"
    
    if days:
        for day in days:
            date_str = day.date.strftime("%d.%m.%Y (%a)")
            total_slots = sum(ts.max_participants for ts in day.time_slots)
            booked = sum(ts.current_participants for ts in day.time_slots)
            text += f"📆 <b>{date_str}</b>\n"
            if day.location:
                text += f"   📍 {day.location}\n"
            text += f"   Мест: {booked}/{total_slots}\n\n"
    else:
        text += "<i>Дни собеседований не созданы</i>\n"
    
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить день", callback_data="intd:add")],
    ]
    
    if days:
        buttons.append([InlineKeyboardButton(text="⚙️ Настроить слоты", callback_data="intd:edit_slots")])
        buttons.append([InlineKeyboardButton(text="🗑 Удалить день", callback_data="intd:delete")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@interviews_router.callback_query(F.data == "intd:add")
async def callback_add_day(callback: CallbackQuery, state: FSMContext):
    """Начать создание дня собеседований"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await state.update_data(faculty_id=admin.faculty_id, admin_id=admin.id)
    await state.set_state(CreateDayStates.enter_date)
    
    # Предлагаем ближайшие даты
    today = date.today()
    buttons = []
    for i in range(1, 15):  # Следующие 2 недели
        d = today + timedelta(days=i)
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]
        buttons.append([
            InlineKeyboardButton(
                text=f"{d.strftime('%d.%m')} ({day_name})",
                callback_data=f"intd:date:{d.isoformat()}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="intd:cancel")])
    
    await callback.message.edit_text(
        "📅 <b>Создание дня собеседований</b>\n\n"
        "Выберите дату или введите в формате ДД.ММ.ГГГГ:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@interviews_router.callback_query(F.data.startswith("intd:date:"), CreateDayStates.enter_date)
async def callback_select_date(callback: CallbackQuery, state: FSMContext):
    """Выбрана дата из кнопок"""
    date_str = callback.data.split(":")[2]
    selected_date = date.fromisoformat(date_str)
    
    await state.update_data(selected_date=selected_date)
    await state.set_state(CreateDayStates.enter_location)
    
    await callback.message.edit_text(
        f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\n"
        "📍 Введите место проведения (аудитория, ссылка и т.д.):\n\n"
        "<i>Или нажмите «Пропустить»</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="intd:skip_location")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="intd:cancel")]
        ])
    )
    await callback.answer()


@interviews_router.message(CreateDayStates.enter_date)
async def process_date_text(message: Message, state: FSMContext):
    """Ввод даты текстом"""
    try:
        selected_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
    except ValueError:
        await message.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ:")
        return
    
    if selected_date < date.today():
        await message.answer("❌ Дата не может быть в прошлом. Введите другую дату:")
        return
    
    await state.update_data(selected_date=selected_date)
    await state.set_state(CreateDayStates.enter_location)
    
    await message.answer(
        f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\n"
        "📍 Введите место проведения (аудитория, ссылка и т.д.):\n\n"
        "<i>Или нажмите «Пропустить»</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data="intd:skip_location")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="intd:cancel")]
        ])
    )


@interviews_router.message(CreateDayStates.enter_location)
async def process_location(message: Message, state: FSMContext):
    """Ввод места проведения"""
    location = message.text.strip()[:255]
    await state.update_data(location=location)
    await create_day_and_show_slots(message, state)


@interviews_router.callback_query(F.data == "intd:skip_location", CreateDayStates.enter_location)
async def callback_skip_location(callback: CallbackQuery, state: FSMContext):
    """Пропустить место"""
    await state.update_data(location=None)
    await create_day_and_show_slots(callback.message, state, edit=True)
    await callback.answer()


async def create_day_and_show_slots(message: Message, state: FSMContext, edit: bool = False):
    """Создать день и показать настройку слотов"""
    data = await state.get_data()
    
    async with async_session_maker() as db:
        # Проверяем, не существует ли уже такой день
        result = await db.execute(
            select(InterviewDay).where(
                InterviewDay.faculty_id == data["faculty_id"],
                InterviewDay.date == data["selected_date"]
            )
        )
        existing = result.scalars().first()
        
        if existing:
            text = f"⚠️ День {data['selected_date'].strftime('%d.%m.%Y')} уже существует!"
            if edit:
                await message.edit_text(text)
            else:
                await message.answer(text)
            await state.clear()
            return
        
        # Создаём день
        interview_day = InterviewDay(
            faculty_id=data["faculty_id"],
            date=data["selected_date"],
            location=data.get("location"),
            created_by=data["admin_id"],
            is_active=True
        )
        db.add(interview_day)
        await db.commit()
        await db.refresh(interview_day)
        
        # Создаём слоты с 0 мест (админ потом настроит)
        for hour in DEFAULT_HOURS:
            slot = TimeSlot(
                day_id=interview_day.id,
                time=time(hour=hour, minute=0),
                max_participants=0,
                current_participants=0,
                is_active=True
            )
            db.add(slot)
        await db.commit()
        
        day_id = interview_day.id
    
    await state.update_data(day_id=day_id)
    await state.set_state(CreateDayStates.configure_slots)
    
    await show_slot_configuration(message, day_id, edit=edit)


async def show_slot_configuration(message: Message, day_id: int, edit: bool = False):
    """Показать интерфейс настройки слотов"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(InterviewDay)
            .options(selectinload(InterviewDay.time_slots))
            .where(InterviewDay.id == day_id)
        )
        day = result.scalars().first()
    
    if not day:
        return
    
    date_str = day.date.strftime("%d.%m.%Y")
    
    text = f"⚙️ <b>Настройка слотов на {date_str}</b>\n\n"
    text += "Нажмите на время, чтобы изменить количество мест:\n\n"
    
    # Сортируем слоты по времени
    slots = sorted(day.time_slots, key=lambda s: s.time)
    
    buttons = []
    row = []
    for slot in slots:
        hour = slot.time.hour
        count = slot.max_participants
        emoji = "🟢" if count > 0 else "⚪"
        
        row.append(InlineKeyboardButton(
            text=f"{emoji} {hour}:00 ({count})",
            callback_data=f"intd:slot:{slot.id}"
        ))
        
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Быстрые действия
    buttons.append([
        InlineKeyboardButton(text="📊 Все по 3", callback_data=f"intd:setall:{day_id}:3"),
        InlineKeyboardButton(text="📊 Все по 5", callback_data=f"intd:setall:{day_id}:5"),
    ])
    buttons.append([
        InlineKeyboardButton(text="✅ Готово", callback_data="intd:done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="intd:cancel")
    ])
    
    if edit:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@interviews_router.callback_query(F.data.startswith("intd:slot:"))
async def callback_edit_slot(callback: CallbackQuery, state: FSMContext):
    """Изменить количество мест в слоте"""
    slot_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        result = await db.execute(select(TimeSlot).where(TimeSlot.id == slot_id))
        slot = result.scalars().first()
        
        if not slot:
            await callback.answer("Слот не найден", show_alert=True)
            return
        
        day_id = slot.day_id
        current = slot.max_participants
        hour = slot.time.hour
    
    # Кнопки для выбора количества мест
    buttons = []
    row = []
    for i in range(11):  # 0-10
        emoji = "✅" if i == current else ""
        row.append(InlineKeyboardButton(
            text=f"{emoji}{i}",
            callback_data=f"intd:setslot:{slot_id}:{i}"
        ))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"intd:backslots:{day_id}")])
    
    await callback.message.edit_text(
        f"⚙️ <b>Слот {hour}:00</b>\n\n"
        f"Текущее количество мест: <b>{current}</b>\n\n"
        "Выберите новое количество:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@interviews_router.callback_query(F.data.startswith("intd:setslot:"))
async def callback_set_slot(callback: CallbackQuery, state: FSMContext):
    """Установить количество мест в слоте"""
    parts = callback.data.split(":")
    slot_id = int(parts[2])
    count = int(parts[3])
    
    async with async_session_maker() as db:
        result = await db.execute(select(TimeSlot).where(TimeSlot.id == slot_id))
        slot = result.scalars().first()
        
        if slot:
            slot.max_participants = count
            day_id = slot.day_id
            await db.commit()
    
    await show_slot_configuration(callback.message, day_id, edit=True)
    await callback.answer(f"Установлено: {count}")


@interviews_router.callback_query(F.data.startswith("intd:setall:"))
async def callback_set_all_slots(callback: CallbackQuery, state: FSMContext):
    """Установить одинаковое количество мест во все слоты"""
    parts = callback.data.split(":")
    day_id = int(parts[2])
    count = int(parts[3])
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(TimeSlot).where(TimeSlot.day_id == day_id)
        )
        slots = result.scalars().all()
        
        for slot in slots:
            slot.max_participants = count
        await db.commit()
    
    await show_slot_configuration(callback.message, day_id, edit=True)
    await callback.answer(f"Все слоты: {count} мест")


@interviews_router.callback_query(F.data.startswith("intd:backslots:"))
async def callback_back_to_slots(callback: CallbackQuery, state: FSMContext):
    """Вернуться к списку слотов"""
    day_id = int(callback.data.split(":")[2])
    await show_slot_configuration(callback.message, day_id, edit=True)
    await callback.answer()


@interviews_router.callback_query(F.data == "intd:done")
async def callback_slots_done(callback: CallbackQuery, state: FSMContext):
    """Завершить настройку слотов"""
    await state.clear()
    await callback.message.edit_text(
        "✅ <b>День собеседований создан!</b>\n\n"
        "Теперь проверяющие могут отмечать свою доступность командой /my_schedule"
    )
    await callback.answer("Готово!")


@interviews_router.callback_query(F.data == "intd:edit_slots")
async def callback_edit_slots_menu(callback: CallbackQuery, state: FSMContext):
    """Выбор дня для редактирования слотов"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(InterviewDay)
            .where(
                InterviewDay.faculty_id == admin.faculty_id,
                InterviewDay.is_active == True
            )
            .order_by(InterviewDay.date)
        )
        days = result.scalars().all()
    
    buttons = []
    for day in days:
        buttons.append([
            InlineKeyboardButton(
                text=f"📆 {day.date.strftime('%d.%m.%Y')}",
                callback_data=f"intd:editday:{day.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="intd:back")])
    
    await callback.message.edit_text(
        "⚙️ <b>Редактирование слотов</b>\n\n"
        "Выберите день:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@interviews_router.callback_query(F.data.startswith("intd:editday:"))
async def callback_edit_day_slots(callback: CallbackQuery, state: FSMContext):
    """Редактирование слотов выбранного дня"""
    day_id = int(callback.data.split(":")[2])
    await state.set_state(CreateDayStates.configure_slots)
    await state.update_data(day_id=day_id)
    await show_slot_configuration(callback.message, day_id, edit=True)
    await callback.answer()


@interviews_router.callback_query(F.data == "intd:delete")
async def callback_delete_day_menu(callback: CallbackQuery):
    """Выбор дня для удаления"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(InterviewDay)
            .where(
                InterviewDay.faculty_id == admin.faculty_id,
                InterviewDay.is_active == True
            )
            .order_by(InterviewDay.date)
        )
        days = result.scalars().all()
    
    buttons = []
    for day in days:
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑 {day.date.strftime('%d.%m.%Y')}",
                callback_data=f"intd:delday:{day.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="intd:back")])
    
    await callback.message.edit_text(
        "🗑 <b>Удаление дня собеседований</b>\n\n"
        "Выберите день для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@interviews_router.callback_query(F.data.startswith("intd:delday:"))
async def callback_confirm_delete_day(callback: CallbackQuery):
    """Подтверждение удаления дня"""
    day_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        result = await db.execute(select(InterviewDay).where(InterviewDay.id == day_id))
        day = result.scalars().first()
        
        if day:
            day.is_active = False
            await db.commit()
            date_str = day.date.strftime('%d.%m.%Y')
    
    await callback.message.edit_text(
        f"✅ День <b>{date_str}</b> удалён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="intd:back")]
        ])
    )
    await callback.answer("Удалено!")


@interviews_router.callback_query(F.data == "intd:cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена"""
    await state.clear()
    await callback.message.edit_text("❌ Отменено")
    await callback.answer()


@interviews_router.callback_query(F.data == "intd:back")
async def callback_back_to_days(callback: CallbackQuery, state: FSMContext):
    """Назад к списку дней"""
    await state.clear()
    await cmd_interview_days(callback.message)
    await callback.answer()


# ============================================================
# REVIEWER: Отметка доступности
# ============================================================

@interviews_router.message(Command("my_schedule"))
async def cmd_my_schedule(message: Message):
    """Моя доступность для собеседований (для reviewer)"""
    admin = await get_admin(message.from_user.id)
    
    if not admin:
        await message.answer("❌ Эта команда доступна только админам и проверяющим.")
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        # Получаем все активные дни
        result = await db.execute(
            select(InterviewDay)
            .options(selectinload(InterviewDay.time_slots))
            .where(
                InterviewDay.faculty_id == admin.faculty_id,
                InterviewDay.is_active == True,
                InterviewDay.date >= date.today()  # Только будущие
            )
            .order_by(InterviewDay.date)
        )
        days = result.scalars().all()
    
    if not days:
        await message.answer(
            f"📅 <b>Расписание собеседований — {faculty.name}</b>\n\n"
            "<i>Пока нет запланированных дней собеседований.</i>"
        )
        return
    
    text = f"📅 <b>Моё расписание — {faculty.name}</b>\n\n"
    text += "Выберите день, чтобы отметить свою доступность:\n"
    
    buttons = []
    for day in days:
        date_str = day.date.strftime("%d.%m (%a)")
        buttons.append([
            InlineKeyboardButton(
                text=f"📆 {date_str}",
                callback_data=f"avail:day:{day.id}"
            )
        ])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@interviews_router.callback_query(F.data.startswith("avail:day:"))
async def callback_show_day_availability(callback: CallbackQuery):
    """Показать слоты дня для отметки доступности"""
    admin = await get_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    day_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(InterviewDay)
            .options(selectinload(InterviewDay.time_slots))
            .where(InterviewDay.id == day_id)
        )
        day = result.scalars().first()
        
        if not day:
            await callback.answer("День не найден", show_alert=True)
            return
        
        # Получаем текущую доступность этого админа
        result = await db.execute(
            select(TimeSlotAvailability.time_slot_id)
            .where(TimeSlotAvailability.interviewer_id == admin.id)
        )
        my_slots = set(row[0] for row in result.fetchall())
    
    date_str = day.date.strftime("%d.%m.%Y (%a)")
    
    text = f"📅 <b>{date_str}</b>\n"
    if day.location:
        text += f"📍 {day.location}\n"
    text += "\nОтметьте слоты, когда вы <b>можете</b> проводить собес:\n"
    text += "<i>✅ — вы доступны, ⬜ — не отмечено</i>\n"
    
    # Сортируем слоты по времени
    slots = sorted(day.time_slots, key=lambda s: s.time)
    
    buttons = []
    row = []
    for slot in slots:
        if slot.max_participants == 0:
            continue  # Пропускаем слоты с 0 мест
        
        hour = slot.time.hour
        is_available = slot.id in my_slots
        emoji = "✅" if is_available else "⬜"
        
        row.append(InlineKeyboardButton(
            text=f"{emoji} {hour}:00",
            callback_data=f"avail:toggle:{slot.id}"
        ))
        
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    if not buttons:
        text += "\n<i>На этот день пока нет открытых слотов.</i>"
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="avail:back")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@interviews_router.callback_query(F.data.startswith("avail:toggle:"))
async def callback_toggle_availability(callback: CallbackQuery):
    """Переключить доступность на слот"""
    admin = await get_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    slot_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        # Проверяем, есть ли уже отметка
        result = await db.execute(
            select(TimeSlotAvailability).where(
                TimeSlotAvailability.time_slot_id == slot_id,
                TimeSlotAvailability.interviewer_id == admin.id
            )
        )
        existing = result.scalars().first()
        
        if existing:
            # Удаляем
            await db.delete(existing)
            action = "снята"
        else:
            # Добавляем
            availability = TimeSlotAvailability(
                time_slot_id=slot_id,
                interviewer_id=admin.id
            )
            db.add(availability)
            action = "добавлена"
        
        await db.commit()
        
        # Получаем day_id для обновления интерфейса
        result = await db.execute(select(TimeSlot).where(TimeSlot.id == slot_id))
        slot = result.scalars().first()
        day_id = slot.day_id if slot else None
    
    await callback.answer(f"Доступность {action}")
    
    # Обновляем интерфейс
    if day_id:
        callback.data = f"avail:day:{day_id}"
        await callback_show_day_availability(callback)


@interviews_router.callback_query(F.data == "avail:back")
async def callback_back_to_schedule(callback: CallbackQuery):
    """Назад к списку дней"""
    await cmd_my_schedule(callback.message)
    await callback.answer()


# ============================================================
# HEAD ADMIN: Просмотр доступности проверяющих
# ============================================================

@interviews_router.message(Command("view_availability"))
async def cmd_view_availability(message: Message):
    """Просмотр доступности всех проверяющих (для head_admin)"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer("❌ Эта команда доступна только главным админам.")
        return
    
    async with async_session_maker() as db:
        # Получаем все дни с доступностью
        result = await db.execute(
            select(InterviewDay)
            .options(
                selectinload(InterviewDay.time_slots)
                .selectinload(TimeSlot.availabilities)
                .selectinload(TimeSlotAvailability.interviewer)
            )
            .where(
                InterviewDay.faculty_id == admin.faculty_id,
                InterviewDay.is_active == True,
                InterviewDay.date >= date.today()
            )
            .order_by(InterviewDay.date)
        )
        days = result.scalars().all()
    
    if not days:
        await message.answer("📅 Нет запланированных дней собеседований.")
        return
    
    text = "👥 <b>Доступность проверяющих</b>\n\n"
    
    for day in days:
        date_str = day.date.strftime("%d.%m.%Y (%a)")
        text += f"<b>📆 {date_str}</b>\n"
        
        slots = sorted(day.time_slots, key=lambda s: s.time)
        
        for slot in slots:
            if slot.max_participants == 0:
                continue
            
            hour = slot.time.hour
            interviewers = [a.interviewer for a in slot.availabilities if a.interviewer]
            
            if interviewers:
                names = ", ".join([
                    i.full_name or i.username or str(i.telegram_id)
                    for i in interviewers
                ])
                text += f"  {hour}:00 — {names}\n"
            else:
                text += f"  {hour}:00 — <i>никто</i>\n"
        
        text += "\n"
    
    # Ограничиваем длину сообщения
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>... (сообщение обрезано)</i>"
    
    await message.answer(text)
