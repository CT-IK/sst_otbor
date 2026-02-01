"""
API для управления слотами собеседований с количеством мест.

Эндпоинты:
- GET /interview-slots-management/{faculty_id} — получить все слоты с проводящими
- PUT /interview-slots-management/{faculty_id}/slot — обновить количество мест для слота
"""
from datetime import date, time, datetime
from typing import Annotated, List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from config import settings
from db.session import get_db
from db.models import (
    Faculty, Administrator, InterviewerSchedule, InterviewTimeSlot
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/interview-slots-management")


# === Вспомогательные функции ===

def get_telegram_id(
    telegram_id: int | None = Query(default=None)
) -> int:
    """Получить telegram_id из query параметров"""
    if telegram_id is not None:
        return telegram_id
    if settings.is_dev:
        return settings.dev_telegram_id
    raise HTTPException(status_code=400, detail="telegram_id обязателен")


TelegramId = Annotated[int, Depends(get_telegram_id)]


async def verify_head_admin(
    faculty_id: int,
    telegram_id: int,
    db: AsyncSession
) -> Administrator:
    """Проверить, что пользователь - Head Admin факультета"""
    result = await db.execute(
        select(Administrator).where(
            Administrator.telegram_id == telegram_id,
            Administrator.faculty_id == faculty_id,
            Administrator.role == "head_admin",
            Administrator.is_active == True
        )
    )
    admin = result.scalars().first()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Эта функция доступна только главным администраторам факультета"
        )
    
    return admin


# === Схемы ===

class AvailableInterviewer(BaseModel):
    """Проводящий, который может в это время"""
    id: int
    name: str | None
    full_name: str | None
    username: str | None


class TimeSlotInfo(BaseModel):
    """Информация о временном слоте"""
    date: date
    time: str  # HH:MM
    max_participants: int  # Количество мест (0-10)
    available_interviewers: List[AvailableInterviewer]  # Список тех, кто может


class DateSlotsResponse(BaseModel):
    """Слоты для одной даты"""
    date: date
    slots: List[TimeSlotInfo]


class AllSlotsResponse(BaseModel):
    """Все слоты для факультета"""
    faculty_id: int
    faculty_name: str
    dates: List[DateSlotsResponse]


class UpdateSlotRequest(BaseModel):
    """Обновление количества мест"""
    date: date
    time: str  # HH:MM
    max_participants: int = Field(ge=0, le=10, description="Количество мест (0-10)")


# === Эндпоинты ===

@router.get("/{faculty_id}", response_model=AllSlotsResponse)
async def get_all_slots(
    faculty_id: int,
    start_date: date = Query(description="Начальная дата (например, 2026-02-02)"),
    end_date: date = Query(description="Конечная дата (например, 2026-02-07)"),
    telegram_id: TelegramId = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить все слоты с проводящими и количеством мест.
    Только для Head Admin.
    """
    if telegram_id:
        admin = await verify_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Получаем все слоты для факультета
    result = await db.execute(
        select(InterviewTimeSlot).where(
            InterviewTimeSlot.faculty_id == faculty_id,
            InterviewTimeSlot.date >= start_date,
            InterviewTimeSlot.date <= end_date
        ).order_by(InterviewTimeSlot.date, InterviewTimeSlot.time)
    )
    slots = result.scalars().all()
    
    # Создаём карту слотов
    slots_map = {}
    for slot in slots:
        key = f"{slot.date}_{slot.time.strftime('%H:%M')}"
        slots_map[key] = slot
    
    # Получаем всех проводящих, которые могут в эти времена
    result = await db.execute(
        select(InterviewerSchedule).where(
            InterviewerSchedule.faculty_id == faculty_id,
            InterviewerSchedule.date >= start_date,
            InterviewerSchedule.date <= end_date,
            InterviewerSchedule.is_available == True
        ).order_by(InterviewerSchedule.date, InterviewerSchedule.time_slot)
    )
    schedules = result.scalars().all()
    
    # Получаем информацию о проводящих
    interviewer_ids = {s.interviewer_id for s in schedules}
    interviewers_map = {}
    if interviewer_ids:
        result = await db.execute(
            select(Administrator).where(
                Administrator.id.in_(interviewer_ids),
                Administrator.is_active == True
            )
        )
        for interviewer in result.scalars().all():
            interviewers_map[interviewer.id] = interviewer
    
    # Группируем по датам
    dates_map = {}
    for schedule in schedules:
        date_key = schedule.date
        time_str = schedule.time_slot.strftime('%H:%M')
        slot_key = f"{date_key}_{time_str}"
        
        if date_key not in dates_map:
            dates_map[date_key] = {}
        
        if time_str not in dates_map[date_key]:
            slot = slots_map.get(slot_key)
            dates_map[date_key][time_str] = {
                'max_participants': slot.max_participants if slot else 0,
                'interviewers': []
            }
        
        interviewer = interviewers_map.get(schedule.interviewer_id)
        if interviewer:
            dates_map[date_key][time_str]['interviewers'].append(
                AvailableInterviewer(
                    id=interviewer.id,
                    name=interviewer.name,
                    full_name=interviewer.full_name,
                    username=interviewer.username
                )
            )
    
    # Формируем ответ
    dates_list = []
    current_date = start_date
    while current_date <= end_date:
        slots_list = []
        # Время от 10:00 до 21:00
        for hour in range(10, 22):
            time_str = f"{hour:02d}:00"
            slot_key = f"{current_date}_{time_str}"
            
            # Получаем количество мест
            slot = slots_map.get(slot_key)
            max_participants = slot.max_participants if slot else 0
            
            # Получаем проводящих
            interviewers = dates_map.get(current_date, {}).get(time_str, {}).get('interviewers', [])
            
            slots_list.append(TimeSlotInfo(
                date=current_date,
                time=time_str,
                max_participants=max_participants,
                available_interviewers=interviewers
            ))
        
        dates_list.append(DateSlotsResponse(
            date=current_date,
            slots=slots_list
        ))
        
        # Следующий день
        from datetime import timedelta
        current_date += timedelta(days=1)
    
    return AllSlotsResponse(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        dates=dates_list
    )


@router.put("/{faculty_id}/slot", response_model=TimeSlotInfo)
async def update_slot(
    faculty_id: int,
    data: UpdateSlotRequest,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить количество мест для слота.
    Только для Head Admin.
    """
    admin = await verify_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Ищем существующий слот
    time_obj = datetime.strptime(data.time, "%H:%M").time()
    result = await db.execute(
        select(InterviewTimeSlot).where(
            InterviewTimeSlot.faculty_id == faculty_id,
            InterviewTimeSlot.date == data.date,
            InterviewTimeSlot.time == time_obj
        )
    )
    slot = result.scalars().first()
    
    if slot:
        # Обновляем
        slot.max_participants = data.max_participants
    else:
        # Создаём новый
        slot = InterviewTimeSlot(
            faculty_id=faculty_id,
            date=data.date,
            time=time_obj,
            max_participants=data.max_participants
        )
        db.add(slot)
    
    await db.commit()
    await db.refresh(slot)
    
    # Получаем проводящих для этого слота
    result = await db.execute(
        select(InterviewerSchedule).where(
            InterviewerSchedule.faculty_id == faculty_id,
            InterviewerSchedule.date == data.date,
            InterviewerSchedule.time_slot == time_obj,
            InterviewerSchedule.is_available == True
        )
    )
    schedules = result.scalars().all()
    
    interviewer_ids = {s.interviewer_id for s in schedules}
    interviewers_list = []
    if interviewer_ids:
        result = await db.execute(
            select(Administrator).where(
                Administrator.id.in_(interviewer_ids),
                Administrator.is_active == True
            )
        )
        for interviewer in result.scalars().all():
            interviewers_list.append(
                AvailableInterviewer(
                    id=interviewer.id,
                    name=interviewer.name,
                    full_name=interviewer.full_name,
                    username=interviewer.username
                )
            )
    
    return TimeSlotInfo(
        date=slot.date,
        time=slot.time.strftime('%H:%M'),
        max_participants=slot.max_participants,
        available_interviewers=interviewers_list
    )
