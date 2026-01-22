"""
API для управления днями собеседований и временными слотами.

Эндпоинты:
- GET /interview-days/{faculty_id} — список дней (Head Admin / Reviewer)
- POST /interview-days/{faculty_id} — создать день (Head Admin)
- DELETE /interview-days/{day_id} — удалить день (Head Admin)
- GET /interview-days/{day_id}/time-slots — временные слоты дня
- PUT /time-slots/{time_slot_id} — установить количество мест (Head Admin)
- POST /time-slots/{time_slot_id}/availability — отметить доступность (Reviewer)
- DELETE /time-slots/{time_slot_id}/availability — снять доступность (Reviewer)
- GET /time-slots/{time_slot_id}/availability — список доступных проверяющих (Head Admin)
"""
from datetime import date, time, datetime
from typing import Annotated, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from db.session import get_db
from db.models import (
    Faculty, Administrator, InterviewDay, TimeSlot, TimeSlotAvailability,
    Interview
)
# Функции проверки прав (копируем из interview_slots)
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


async def verify_reviewer_or_head_admin(
    faculty_id: int,
    telegram_id: int,
    db: AsyncSession
) -> Administrator:
    """Проверить, что пользователь - Reviewer или Head Admin"""
    result = await db.execute(
        select(Administrator).where(
            Administrator.telegram_id == telegram_id,
            Administrator.faculty_id == faculty_id,
            Administrator.is_active == True
        )
    )
    admin = result.scalars().first()
    
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому факультету"
        )
    
    return admin


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
from app.api.schemas.interview_days import (
    InterviewDayCreate, InterviewDayResponse, InterviewDaysListResponse,
    TimeSlotResponse, TimeSlotUpdate, TimeSlotAvailabilityListResponse
)

router = APIRouter(prefix="/interview-days")

# Временные слоты: 10:00 - 22:00 (по часам)
TIME_SLOTS = [time(hour=h) for h in range(10, 23)]  # 10:00, 11:00, ..., 22:00


# === Эндпоинты для Head Admin ===

@router.get("/{faculty_id}", response_model=InterviewDaysListResponse)
async def get_interview_days(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список всех дней собеседований факультета.
    Доступно для Head Admin и Reviewer.
    """
    admin = await verify_reviewer_or_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Получаем дни
    result = await db.execute(
        select(InterviewDay)
        .where(InterviewDay.faculty_id == faculty_id)
        .order_by(InterviewDay.date)
    )
    days = result.scalars().all()
    
    # Для каждого дня получаем временные слоты
    day_responses = []
    for day in days:
        # Получаем временные слоты дня
        result = await db.execute(
            select(TimeSlot)
            .where(TimeSlot.day_id == day.id)
            .order_by(TimeSlot.time)
        )
        time_slots = result.scalars().all()
        
        # Если слотов нет, создаем их автоматически (10:00-22:00)
        if not time_slots:
            for slot_time in TIME_SLOTS:
                time_slot = TimeSlot(
                    day_id=day.id,
                    time=slot_time,
                    max_participants=0,
                    current_participants=0,
                    is_active=True
                )
                db.add(time_slot)
            await db.commit()
            await db.refresh(day)
            # Перезагружаем слоты
            result = await db.execute(
                select(TimeSlot)
                .where(TimeSlot.day_id == day.id)
                .order_by(TimeSlot.time)
            )
            time_slots = result.scalars().all()
        
        # Формируем ответ для временных слотов
        time_slot_responses = []
        for ts in time_slots:
            available_places = max(0, ts.max_participants - ts.current_participants)
            
            # Для Head Admin: список доступных проверяющих
            available_interviewers = []
            if admin.role == "head_admin":
                result = await db.execute(
                    select(TimeSlotAvailability, Administrator)
                    .join(Administrator, TimeSlotAvailability.interviewer_id == Administrator.id)
                    .where(TimeSlotAvailability.time_slot_id == ts.id)
                )
                for av, interviewer in result.all():
                    available_interviewers.append({
                        "id": interviewer.id,
                        "name": interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}",
                        "telegram_id": interviewer.telegram_id
                    })
            
            # Для Reviewer: моя доступность
            my_availability = None
            if admin.role == "reviewer":
                result = await db.execute(
                    select(TimeSlotAvailability).where(
                        TimeSlotAvailability.time_slot_id == ts.id,
                        TimeSlotAvailability.interviewer_id == admin.id
                    )
                )
                if result.scalar_one_or_none():
                    my_availability = True
            
            time_slot_responses.append(TimeSlotResponse(
                id=ts.id,
                time=ts.time.strftime("%H:%M"),
                max_participants=ts.max_participants,
                current_participants=ts.current_participants,
                available_places=available_places,
                is_active=ts.is_active,
                available_interviewers=available_interviewers,
                my_availability=my_availability
            ))
        
        day_responses.append(InterviewDayResponse(
            id=day.id,
            date=day.date,
            location=day.location,
            is_active=day.is_active,
            time_slots=time_slot_responses
        ))
    
    return InterviewDaysListResponse(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        days=day_responses,
        total=len(day_responses)
    )


@router.post("/{faculty_id}", response_model=InterviewDayResponse, status_code=status.HTTP_201_CREATED)
async def create_interview_day(
    faculty_id: int,
    data: InterviewDayCreate,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Создать новый день собеседований.
    Только для Head Admin.
    Автоматически создаются временные слоты 10:00-22:00.
    """
    admin = await verify_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Проверяем, что дата не в прошлом
    if data.date < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя создавать дни собеседований в прошлом"
        )
    
    # Проверяем, не существует ли уже день с этой датой
    result = await db.execute(
        select(InterviewDay).where(
            InterviewDay.faculty_id == faculty_id,
            InterviewDay.date == data.date
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="День собеседований с этой датой уже существует"
        )
    
    # Создаём день
    interview_day = InterviewDay(
        faculty_id=faculty_id,
        date=data.date,
        location=data.location,
        created_by=admin.id,
        is_active=True
    )
    db.add(interview_day)
    await db.flush()
    await db.refresh(interview_day)
    
    # Создаём временные слоты (10:00-22:00)
    for slot_time in TIME_SLOTS:
        time_slot = TimeSlot(
            day_id=interview_day.id,
            time=slot_time,
            max_participants=0,  # По умолчанию 0, Head Admin установит
            current_participants=0,
            is_active=True
        )
        db.add(time_slot)
    
    await db.commit()
    await db.refresh(interview_day)
    
    # Получаем созданные слоты для ответа
    result = await db.execute(
        select(TimeSlot)
        .where(TimeSlot.day_id == interview_day.id)
        .order_by(TimeSlot.time)
    )
    time_slots = result.scalars().all()
    
    time_slot_responses = [
        TimeSlotResponse(
            id=ts.id,
            time=ts.time.strftime("%H:%M"),
            max_participants=ts.max_participants,
            current_participants=ts.current_participants,
            available_places=max(0, ts.max_participants - ts.current_participants),
            is_active=ts.is_active,
            available_interviewers=[],
            my_availability=None
        )
        for ts in time_slots
    ]
    
    return InterviewDayResponse(
        id=interview_day.id,
        date=interview_day.date,
        location=interview_day.location,
        is_active=interview_day.is_active,
        time_slots=time_slot_responses
    )


@router.delete("/{day_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview_day(
    day_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Удалить день собеседований.
    Только для Head Admin.
    """
    result = await db.execute(select(InterviewDay).where(InterviewDay.id == day_id))
    day = result.scalars().first()
    
    if not day:
        raise HTTPException(status_code=404, detail="День не найден")
    
    admin = await verify_head_admin(day.faculty_id, telegram_id, db)
    
    # Проверяем, есть ли записи
    result = await db.execute(
        select(func.count(Interview.id)).where(
            Interview.time_slot_id.in_(
                select(TimeSlot.id).where(TimeSlot.day_id == day_id)
            )
        )
    )
    current_participants = result.scalar() or 0
    
    if current_participants > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Нельзя удалить день, на который уже записались {current_participants} человек."
        )
    
    await db.delete(day)
    await db.commit()


# === Эндпоинты для временных слотов ===

@router.put("/time-slots/{time_slot_id}", response_model=TimeSlotResponse)
async def update_time_slot(
    time_slot_id: int,
    data: TimeSlotUpdate,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Установить количество мест для временного слота.
    Только для Head Admin.
    """
    result = await db.execute(select(TimeSlot).where(TimeSlot.id == time_slot_id))
    time_slot = result.scalars().first()
    
    if not time_slot:
        raise HTTPException(status_code=404, detail="Временной слот не найден")
    
    # Получаем день для проверки прав
    result = await db.execute(select(InterviewDay).where(InterviewDay.id == time_slot.day_id))
    day = result.scalars().first()
    
    admin = await verify_head_admin(day.faculty_id, telegram_id, db)
    
    # Проверяем, что новое количество мест не меньше текущих записей
    if data.max_participants < time_slot.current_participants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Нельзя установить количество мест меньше текущих записей ({time_slot.current_participants})"
        )
    
    time_slot.max_participants = data.max_participants
    await db.commit()
    await db.refresh(time_slot)
    
    available_places = max(0, time_slot.max_participants - time_slot.current_participants)
    
    # Получаем список доступных проверяющих
    result = await db.execute(
        select(TimeSlotAvailability, Administrator)
        .join(Administrator, TimeSlotAvailability.interviewer_id == Administrator.id)
        .where(TimeSlotAvailability.time_slot_id == time_slot.id)
    )
    available_interviewers = [
        {
            "id": interviewer.id,
            "name": interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}",
            "telegram_id": interviewer.telegram_id
        }
        for _, interviewer in result.all()
    ]
    
    return TimeSlotResponse(
        id=time_slot.id,
        time=time_slot.time.strftime("%H:%M"),
        max_participants=time_slot.max_participants,
        current_participants=time_slot.current_participants,
        available_places=available_places,
        is_active=time_slot.is_active,
        available_interviewers=available_interviewers,
        my_availability=None
    )


@router.post("/time-slots/{time_slot_id}/availability", status_code=status.HTTP_201_CREATED)
async def set_time_slot_availability(
    time_slot_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Отметить свою доступность во временном слоте.
    Для Reviewer и Head Admin.
    """
    result = await db.execute(select(TimeSlot).where(TimeSlot.id == time_slot_id))
    time_slot = result.scalars().first()
    
    if not time_slot:
        raise HTTPException(status_code=404, detail="Временной слот не найден")
    
    # Получаем день для проверки прав
    result = await db.execute(select(InterviewDay).where(InterviewDay.id == time_slot.day_id))
    day = result.scalars().first()
    
    admin = await verify_reviewer_or_head_admin(day.faculty_id, telegram_id, db)
    
    # Проверяем, не прошел ли уже день
    if day.date < date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя изменять доступность для прошедших дней"
        )
    
    # Проверяем, существует ли уже запись
    result = await db.execute(
        select(TimeSlotAvailability).where(
            TimeSlotAvailability.time_slot_id == time_slot_id,
            TimeSlotAvailability.interviewer_id == admin.id
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Уже отмечено
        return {"message": "Доступность уже отмечена"}
    
    # Создаём запись
    availability = TimeSlotAvailability(
        time_slot_id=time_slot_id,
        interviewer_id=admin.id
    )
    db.add(availability)
    await db.commit()
    
    return {"message": "Доступность отмечена"}


@router.delete("/time-slots/{time_slot_id}/availability", status_code=status.HTTP_204_NO_CONTENT)
async def remove_time_slot_availability(
    time_slot_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Снять отметку доступности во временном слоте.
    Для Reviewer и Head Admin.
    """
    result = await db.execute(select(TimeSlot).where(TimeSlot.id == time_slot_id))
    time_slot = result.scalars().first()
    
    if not time_slot:
        raise HTTPException(status_code=404, detail="Временной слот не найден")
    
    # Получаем день для проверки прав
    result = await db.execute(select(InterviewDay).where(InterviewDay.id == time_slot.day_id))
    day = result.scalars().first()
    
    admin = await verify_reviewer_or_head_admin(day.faculty_id, telegram_id, db)
    
    # Находим запись
    result = await db.execute(
        select(TimeSlotAvailability).where(
            TimeSlotAvailability.time_slot_id == time_slot_id,
            TimeSlotAvailability.interviewer_id == admin.id
        )
    )
    availability = result.scalar_one_or_none()
    
    if not availability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись о доступности не найдена"
        )
    
    await db.delete(availability)
    await db.commit()


@router.get("/time-slots/{time_slot_id}/availability", response_model=TimeSlotAvailabilityListResponse)
async def get_time_slot_availability(
    time_slot_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список доступных проверяющих для временного слота.
    Только для Head Admin.
    """
    result = await db.execute(select(TimeSlot).where(TimeSlot.id == time_slot_id))
    time_slot = result.scalars().first()
    
    if not time_slot:
        raise HTTPException(status_code=404, detail="Временной слот не найден")
    
    # Получаем день для проверки прав
    result = await db.execute(select(InterviewDay).where(InterviewDay.id == time_slot.day_id))
    day = result.scalars().first()
    
    admin = await verify_head_admin(day.faculty_id, telegram_id, db)
    
    # Получаем доступности
    result = await db.execute(
        select(TimeSlotAvailability, Administrator)
        .join(Administrator, TimeSlotAvailability.interviewer_id == Administrator.id)
        .where(TimeSlotAvailability.time_slot_id == time_slot_id)
    )
    
    from app.api.schemas.interview_days import TimeSlotAvailabilityResponse
    
    availabilities = [
        TimeSlotAvailabilityResponse(
            time_slot_id=av.time_slot_id,
            interviewer_id=interviewer.id,
            interviewer_name=interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}",
            created_at=av.created_at.isoformat()
        )
        for av, interviewer in result.all()
    ]
    
    return TimeSlotAvailabilityListResponse(
        time_slot_id=time_slot.id,
        time=time_slot.time.strftime("%H:%M"),
        date=day.date,
        availabilities=availabilities,
        total=len(availabilities)
    )
