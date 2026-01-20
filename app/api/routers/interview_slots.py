"""
API для управления слотами собеседований.

Эндпоинты:
- GET /interview-slots/{faculty_id} — список слотов (Head Admin / Reviewer)
- POST /interview-slots/{faculty_id} — создать слот (Head Admin)
- PUT /interview-slots/{slot_id} — обновить слот (Head Admin)
- DELETE /interview-slots/{slot_id} — удалить слот (Head Admin)
- GET /interview-slots/{faculty_id}/my-availability — моя доступность (Reviewer)
- POST /interview-slots/{slot_id}/availability — отметить доступность (Reviewer)
- DELETE /interview-slots/{slot_id}/availability — снять доступность (Reviewer)
"""
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import settings
from db.session import get_db
from db.models import (
    Faculty, Administrator, InterviewSlot, SlotAvailability,
    Interview
)
from app.api.schemas.interview_slots import (
    InterviewSlotCreate, InterviewSlotUpdate,
    InterviewSlotResponse, InterviewSlotsListResponse,
    AvailabilityResponse, AvailabilityListResponse
)

router = APIRouter(prefix="/interview-slots")


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


async def get_slot_with_permissions(
    slot_id: int,
    telegram_id: int,
    db: AsyncSession
) -> tuple[InterviewSlot, Administrator]:
    """Получить слот и проверить права доступа"""
    result = await db.execute(
        select(InterviewSlot).where(InterviewSlot.id == slot_id)
    )
    slot = result.scalars().first()
    
    if not slot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Слот не найден"
        )
    
    # Проверяем права
    admin = await verify_reviewer_or_head_admin(slot.faculty_id, telegram_id, db)
    
    return slot, admin


def slot_to_response(
    slot: InterviewSlot,
    current_participants: int,
    my_availability: Optional[bool] = None
) -> InterviewSlotResponse:
    """Конвертировать слот в ответ API"""
    available_places = max(0, slot.max_participants - current_participants)
    
    return InterviewSlotResponse(
        id=slot.id,
        faculty_id=slot.faculty_id,
        datetime_start=slot.datetime_start,
        datetime_end=slot.datetime_end,
        max_participants=slot.max_participants,
        current_participants=current_participants,
        available_places=available_places,
        location=slot.location,
        is_active=slot.is_active,
        created_by=slot.created_by,
        created_at=slot.created_at,
        my_availability=my_availability
    )


# === Эндпоинты для Head Admin ===

@router.get("/{faculty_id}", response_model=InterviewSlotsListResponse)
async def get_interview_slots(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список всех слотов собеседований факультета.
    Доступно для Head Admin и Reviewer.
    
    Для Reviewer показывается также их доступность в каждом слоте.
    """
    admin = await verify_reviewer_or_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Получаем слоты
    result = await db.execute(
        select(InterviewSlot)
        .where(InterviewSlot.faculty_id == faculty_id)
        .order_by(InterviewSlot.datetime_start)
    )
    slots = result.scalars().all()
    
    # Для каждого слота считаем количество записей
    slot_responses = []
    for slot in slots:
        # Считаем количество записей в слот
        result = await db.execute(
            select(func.count(Interview.id)).where(
                Interview.slot_id == slot.id,
                Interview.status != "cancelled"
            )
        )
        current_participants = result.scalar() or 0
        
        # Для Reviewer: проверяем его доступность
        my_availability = None
        if admin.role == "reviewer":
            result = await db.execute(
                select(SlotAvailability.available).where(
                    SlotAvailability.slot_id == slot.id,
                    SlotAvailability.interviewer_id == admin.id
                )
            )
            availability = result.scalar_one_or_none()
            if availability is not None:
                my_availability = availability
        
        slot_responses.append(
            slot_to_response(slot, current_participants, my_availability)
        )
    
    return InterviewSlotsListResponse(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        slots=slot_responses,
        total=len(slot_responses)
    )


@router.post("/{faculty_id}", response_model=InterviewSlotResponse, status_code=status.HTTP_201_CREATED)
async def create_interview_slot(
    faculty_id: int,
    data: InterviewSlotCreate,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Создать новый слот собеседования.
    Только для Head Admin.
    """
    admin = await verify_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Валидация времени
    if data.datetime_start >= data.datetime_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Время начала должно быть раньше времени окончания"
        )
    
    # Проверяем, что слот не в прошлом
    now = datetime.now(data.datetime_start.tzinfo) if data.datetime_start.tzinfo else datetime.utcnow()
    if data.datetime_start < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя создавать слоты в прошлом"
        )
    
    # Проверяем пересечения с существующими слотами (опционально)
    # Можно добавить проверку, если нужно запретить пересекающиеся слоты
    
    # Создаём слот
    slot = InterviewSlot(
        faculty_id=faculty_id,
        datetime_start=data.datetime_start,
        datetime_end=data.datetime_end,
        max_participants=data.max_participants,
        location=data.location,
        created_by=admin.id,
        is_active=True
    )
    db.add(slot)
    await db.flush()
    await db.refresh(slot)
    
    # Head Admin автоматически отмечает себя как доступного в созданном слоте
    availability = SlotAvailability(
        slot_id=slot.id,
        interviewer_id=admin.id,
        available=True
    )
    db.add(availability)
    await db.commit()
    await db.refresh(slot)
    
    return slot_to_response(slot, current_participants=0)


@router.put("/{slot_id}", response_model=InterviewSlotResponse)
async def update_interview_slot(
    slot_id: int,
    data: InterviewSlotUpdate,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить слот собеседования.
    Только для Head Admin.
    """
    slot, admin = await get_slot_with_permissions(slot_id, telegram_id, db)
    
    if admin.role != "head_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только главный администратор может редактировать слоты"
        )
    
    # Проверяем, есть ли уже записи в слот
    result = await db.execute(
        select(func.count(Interview.id)).where(
            Interview.slot_id == slot.id,
            Interview.status != "cancelled"
        )
    )
    current_participants = result.scalar() or 0
    
    # Обновляем поля
    if data.datetime_start is not None:
        slot.datetime_start = data.datetime_start
    if data.datetime_end is not None:
        slot.datetime_end = data.datetime_end
    if data.max_participants is not None:
        if data.max_participants < current_participants:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Нельзя уменьшить количество мест до {data.max_participants}, уже записано {current_participants} человек"
            )
        slot.max_participants = data.max_participants
    if data.location is not None:
        slot.location = data.location
    if data.is_active is not None:
        slot.is_active = data.is_active
    
    # Валидация времени
    if slot.datetime_start >= slot.datetime_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Время начала должно быть раньше времени окончания"
        )
    
    await db.commit()
    await db.refresh(slot)
    
    return slot_to_response(slot, current_participants)


@router.delete("/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interview_slot(
    slot_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Удалить слот собеседования.
    Только для Head Admin.
    
    Внимание: Если на слот уже записались пользователи, удаление не допускается.
    Вместо этого нужно деактивировать слот (is_active=false).
    """
    slot, admin = await get_slot_with_permissions(slot_id, telegram_id, db)
    
    if admin.role != "head_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только главный администратор может удалять слоты"
        )
    
    # Проверяем, есть ли записи
    result = await db.execute(
        select(func.count(Interview.id)).where(
            Interview.slot_id == slot.id,
            Interview.status != "cancelled"
        )
    )
    current_participants = result.scalar() or 0
    
    if current_participants > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Нельзя удалить слот, на который уже записались {current_participants} человек. Используйте деактивацию (is_active=false)."
        )
    
    await db.delete(slot)
    await db.commit()


# === Эндпоинты для Reviewer ===

@router.get("/{faculty_id}/my-availability", response_model=AvailabilityListResponse)
async def get_my_availability(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список моих доступностей в слотах.
    Только для Reviewer и Head Admin.
    """
    admin = await verify_reviewer_or_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Получаем мои доступности
    result = await db.execute(
        select(SlotAvailability)
        .join(InterviewSlot, SlotAvailability.slot_id == InterviewSlot.id)
        .where(
            SlotAvailability.interviewer_id == admin.id,
            InterviewSlot.faculty_id == faculty_id
        )
        .order_by(InterviewSlot.datetime_start)
    )
    availabilities = result.scalars().all()
    
    availability_responses = [
        AvailabilityResponse(
            slot_id=av.slot_id,
            available=av.available,
            interviewer_id=av.interviewer_id,
            updated_at=av.updated_at
        )
        for av in availabilities
    ]
    
    return AvailabilityListResponse(
        faculty_id=faculty_id,
        availabilities=availability_responses,
        total=len(availability_responses)
    )


@router.post("/{slot_id}/availability", response_model=AvailabilityResponse, status_code=status.HTTP_201_CREATED)
async def set_availability(
    slot_id: int,
    available: bool = Query(description="true = свободен, false = занят"),
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Отметить свою доступность в слоте.
    Для Reviewer и Head Admin.
    """
    slot, admin = await get_slot_with_permissions(slot_id, telegram_id, db)
    
    # Проверяем, не прошел ли уже слот
    now = datetime.now(slot.datetime_start.tzinfo) if slot.datetime_start.tzinfo else datetime.utcnow()
    if slot.datetime_start < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя изменять доступность для прошедших слотов"
        )
    
    # Проверяем, существует ли уже запись о доступности
    result = await db.execute(
        select(SlotAvailability).where(
            SlotAvailability.slot_id == slot_id,
            SlotAvailability.interviewer_id == admin.id
        )
    )
    existing = result.scalars().first()
    
    if existing:
        # Обновляем существующую запись
        existing.available = available
        existing.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(existing)
        
        return AvailabilityResponse(
            slot_id=existing.slot_id,
            available=existing.available,
            interviewer_id=existing.interviewer_id,
            updated_at=existing.updated_at
        )
    else:
        # Создаём новую запись
        availability = SlotAvailability(
            slot_id=slot_id,
            interviewer_id=admin.id,
            available=available
        )
        db.add(availability)
        await db.commit()
        await db.refresh(availability)
        
        return AvailabilityResponse(
            slot_id=availability.slot_id,
            available=availability.available,
            interviewer_id=availability.interviewer_id,
            updated_at=availability.updated_at
        )


@router.delete("/{slot_id}/availability", status_code=status.HTTP_204_NO_CONTENT)
async def remove_availability(
    slot_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Снять отметку доступности в слоте.
    Для Reviewer и Head Admin.
    """
    slot, admin = await get_slot_with_permissions(slot_id, telegram_id, db)
    
    # Находим запись о доступности
    result = await db.execute(
        select(SlotAvailability).where(
            SlotAvailability.slot_id == slot_id,
            SlotAvailability.interviewer_id == admin.id
        )
    )
    availability = result.scalars().first()
    
    if not availability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Запись о доступности не найдена"
        )
    
    await db.delete(availability)
    await db.commit()
