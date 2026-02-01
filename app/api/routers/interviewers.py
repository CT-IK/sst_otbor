"""
API для управления проводящими собеседования и их расписанием.

Эндпоинты:
- POST /interviewers/{faculty_id} — добавить проводящего (Head Admin)
- GET /interviewers/{faculty_id} — список проводящих (Head Admin)
- DELETE /interviewers/{interviewer_id} — удалить проводящего (Head Admin)
- GET /interviewers/{interviewer_id}/schedule — получить расписание (Head Admin)
- PUT /interviewers/{interviewer_id}/schedule — обновить расписание (Head Admin)
- PUT /interviewers/{interviewer_id}/name — обновить имя проводящего (Head Admin)
"""
from datetime import date, time, datetime
from typing import Annotated, List, Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from config import settings
from db.session import get_db
from db.models import (
    Faculty, Administrator, InterviewerSchedule, Interviewer
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/interviewers")


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

class AddInterviewerRequest(BaseModel):
    """Добавление проводящего собесы"""
    telegram_id: int = Field(description="Telegram ID проводящего")


class InterviewerResponse(BaseModel):
    """Информация о проводящем"""
    id: int
    telegram_id: int | None
    username: str | None
    full_name: str | None
    name: str | None  # Отображаемое имя
    faculty_id: int
    role: str  # head_admin или reviewer
    created_at: str


class InterviewersListResponse(BaseModel):
    """Список проводящих"""
    faculty_id: int
    faculty_name: str
    interviewers: List[InterviewerResponse]
    total: int


class ScheduleSlot(BaseModel):
    """Один слот расписания"""
    date: date
    time: str  # HH:MM
    is_available: bool
    is_after_interview: bool


class ScheduleUpdateRequest(BaseModel):
    """Обновление расписания"""
    slots: List[ScheduleSlot]


class ScheduleResponse(BaseModel):
    """Расписание проводящего"""
    interviewer_id: int
    interviewer_name: str
    slots: List[ScheduleSlot]
    total: int


class UpdateInterviewerNameRequest(BaseModel):
    """Обновление имени проводящего"""
    name: str | None = Field(None, description="Имя проводящего (nullable)")


# === Эндпоинты ===

@router.post("/{faculty_id}", response_model=InterviewerResponse, status_code=status.HTTP_201_CREATED)
async def add_interviewer(
    faculty_id: int,
    data: AddInterviewerRequest,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Добавить проводящего собесы.
    Только для Head Admin.
    Отправляет уведомление в бот.
    """
    admin = await verify_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Проверяем, не добавлен ли уже проводящий для этого факультета
    result = await db.execute(
        select(Interviewer).where(
            Interviewer.telegram_id == data.telegram_id,
            Interviewer.faculty_id == faculty_id
        )
    )
    existing_interviewer = result.scalars().first()
    
    is_new_interviewer = True
    
    if existing_interviewer:
        if existing_interviewer.is_active:
            # Уже является проводящим этого факультета
            interviewer = existing_interviewer
            is_new_interviewer = False
        else:
            # Активируем существующего неактивного проводящего
            existing_interviewer.is_active = True
            interviewer = existing_interviewer
            await db.commit()
            await db.refresh(interviewer)
    else:
        # Создаём нового проводящего
        # Пытаемся получить информацию о пользователе из Telegram
        username = None
        full_name = None
        try:
            import httpx
            bot_token = settings.telegram_bot_token
            if bot_token:
                url = f"https://api.telegram.org/bot{bot_token}/getChat"
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json={"chat_id": data.telegram_id})
                    if response.status_code == 200:
                        chat_data = response.json()
                        if chat_data.get("ok"):
                            user_data = chat_data.get("result", {})
                            username = user_data.get("username")
                            first_name = user_data.get("first_name", "")
                            last_name = user_data.get("last_name", "")
                            full_name = f"{first_name} {last_name}".strip() if last_name else first_name
        except Exception as e:
            logger.warning(f"Не удалось получить информацию о пользователе {data.telegram_id}: {e}")
        
        interviewer = Interviewer(
            telegram_id=data.telegram_id,
            faculty_id=faculty_id,
            username=username,
            full_name=full_name,
            is_active=True,
            added_by=admin.id
        )
        db.add(interviewer)
        await db.commit()
        await db.refresh(interviewer)
    
    # Отправляем уведомление в бот (только если это новый проводящий)
    if is_new_interviewer:
        try:
            import httpx
            bot_token = settings.telegram_bot_token
            if bot_token:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                async with httpx.AsyncClient() as client:
                    await client.post(url, json={
                        "chat_id": data.telegram_id,
                        "text": (
                            f"👋 <b>Вы добавлены как проводящий собеседования!</b>\n\n"
                            f"Факультет: <b>{faculty.name}</b>\n\n"
                            f"Теперь вы можете проводить собеседования для этого факультета."
                        ),
                        "parse_mode": "HTML"
                    })
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление проводящему {data.telegram_id}: {e}")
    
    # Формируем имя для ответа
    display_name = interviewer.name or interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}"
    
    return InterviewerResponse(
        id=interviewer.id,
        telegram_id=interviewer.telegram_id,
        username=interviewer.username,
        full_name=interviewer.full_name,
        name=interviewer.name,
        faculty_id=interviewer.faculty_id,
        role="interviewer",  # Все проводящие имеют роль "interviewer"
        created_at=interviewer.created_at.isoformat()
    )


@router.get("/{faculty_id}", response_model=InterviewersListResponse)
async def get_interviewers(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить список всех проводящих собесы факультета.
    Только для Head Admin.
    """
    admin = await verify_head_admin(faculty_id, telegram_id, db)
    
    # Проверяем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Получаем всех активных проводящих факультета
    result = await db.execute(
        select(Interviewer).where(
            Interviewer.faculty_id == faculty_id,
            Interviewer.is_active == True
        ).order_by(Interviewer.created_at)
    )
    interviewers_list = result.scalars().all()
    
    interviewer_responses = [
        InterviewerResponse(
            id=i.id,
            telegram_id=i.telegram_id,
            username=i.username,
            full_name=i.full_name,
            name=i.name,
            faculty_id=i.faculty_id,
            role="interviewer",
            created_at=i.created_at.isoformat()
        )
        for i in interviewers_list
    ]
    
    return InterviewersListResponse(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        interviewers=interviewer_responses,
        total=len(interviewer_responses)
    )


@router.delete("/{interviewer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_interviewer(
    interviewer_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Удалить проводящего.
    Только для Head Admin.
    """
    result = await db.execute(
        select(Interviewer).where(Interviewer.id == interviewer_id)
    )
    interviewer = result.scalars().first()
    
    if not interviewer:
        raise HTTPException(status_code=404, detail="Проводящий не найден")
    
    admin = await verify_head_admin(interviewer.faculty_id, telegram_id, db)
    
    # Деактивируем вместо удаления
    interviewer.is_active = False
    await db.commit()


@router.get("/{interviewer_id}/schedule", response_model=ScheduleResponse)
async def get_interviewer_schedule(
    interviewer_id: int,
    start_date: date = Query(description="Начальная дата (например, 2026-02-02)"),
    end_date: date = Query(description="Конечная дата (например, 2026-02-07)"),
    telegram_id: TelegramId = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить расписание проводящего.
    Доступно для Head Admin.
    """
    result = await db.execute(
        select(Interviewer).where(Interviewer.id == interviewer_id)
    )
    interviewer = result.scalars().first()
    
    if not interviewer:
        raise HTTPException(status_code=404, detail="Проводящий не найден")
    
    if telegram_id:
        admin = await verify_head_admin(interviewer.faculty_id, telegram_id, db)
    
    # Получаем расписание
    result = await db.execute(
        select(InterviewerSchedule).where(
            InterviewerSchedule.interviewer_id == interviewer_id,
            InterviewerSchedule.date >= start_date,
            InterviewerSchedule.date <= end_date
        ).order_by(InterviewerSchedule.date, InterviewerSchedule.time_slot)
    )
    schedules = result.scalars().all()
    
    slots = [
        ScheduleSlot(
            date=s.date,
            time=s.time_slot.strftime("%H:%M"),
            is_available=s.is_available,
            is_after_interview=s.is_after_interview
        )
        for s in schedules
    ]
    
    interviewer_name = interviewer.name or interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}"
    
    return ScheduleResponse(
        interviewer_id=interviewer.id,
        interviewer_name=interviewer_name,
        slots=slots,
        total=len(slots)
    )


@router.put("/{interviewer_id}/schedule", response_model=ScheduleResponse)
async def update_interviewer_schedule(
    interviewer_id: int,
    data: ScheduleUpdateRequest,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить расписание проводящего.
    Только для Head Admin.
    """
    result = await db.execute(
        select(Interviewer).where(Interviewer.id == interviewer_id)
    )
    interviewer = result.scalars().first()
    
    if not interviewer:
        raise HTTPException(status_code=404, detail="Проводящий не найден")
    
    admin = await verify_head_admin(interviewer.faculty_id, telegram_id, db)
    
    # Сохраняем все нужные значения до commit (чтобы избежать expired объекта)
    current_interviewer_id = interviewer.id
    current_faculty_id = interviewer.faculty_id
    interviewer_name = interviewer.name or interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}"
    
    # Удаляем старое расписание для этих дат
    if data.slots:
        dates = {slot.date for slot in data.slots}
        # Получаем все времена из слотов
        times = {datetime.strptime(slot.time, "%H:%M").time() for slot in data.slots}
        
        # Удаляем старые записи
        result = await db.execute(
            select(InterviewerSchedule).where(
                InterviewerSchedule.interviewer_id == current_interviewer_id,
                InterviewerSchedule.date.in_(dates),
                InterviewerSchedule.time_slot.in_(times)
            )
        )
        old_schedules = result.scalars().all()
        for old_schedule in old_schedules:
            await db.delete(old_schedule)
        
        await db.flush()  # Применяем удаление перед добавлением новых
    
    # Создаём новое расписание
    for slot in data.slots:
        schedule = InterviewerSchedule(
            interviewer_id=current_interviewer_id,
            faculty_id=current_faculty_id,
            date=slot.date,
            time_slot=datetime.strptime(slot.time, "%H:%M").time(),
            is_available=slot.is_available,
            is_after_interview=slot.is_after_interview
        )
        db.add(schedule)
    
    await db.commit()
    
    # Возвращаем обновлённое расписание
    if data.slots:
        dates = {slot.date for slot in data.slots}
        result = await db.execute(
            select(InterviewerSchedule).where(
                InterviewerSchedule.interviewer_id == interviewer_id,
                InterviewerSchedule.date.in_(dates)
            ).order_by(InterviewerSchedule.date, InterviewerSchedule.time_slot)
        )
        schedules = result.scalars().all()
        
        slots = [
            ScheduleSlot(
                date=s.date,
                time=s.time_slot.strftime("%H:%M"),
                is_available=s.is_available,
                is_after_interview=s.is_after_interview
            )
            for s in schedules
        ]
    else:
        slots = []
    
    # Используем сохранённые значения (не обращаемся к expired объекту)
    return ScheduleResponse(
        interviewer_id=current_interviewer_id,
        interviewer_name=interviewer_name,
        slots=slots,
        total=len(slots)
    )


@router.put("/{interviewer_id}/name", response_model=InterviewerResponse)
async def update_interviewer_name(
    interviewer_id: int,
    data: UpdateInterviewerNameRequest,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Обновить имя проводящего.
    Только для Head Admin.
    """
    result = await db.execute(
        select(Interviewer).where(Interviewer.id == interviewer_id)
    )
    interviewer = result.scalars().first()
    
    if not interviewer:
        raise HTTPException(status_code=404, detail="Проводящий не найден")
    
    admin = await verify_head_admin(interviewer.faculty_id, telegram_id, db)
    
    # Обновляем имя
    interviewer.name = data.name if data.name else None
    await db.commit()
    await db.refresh(interviewer)
    
    return InterviewerResponse(
        id=interviewer.id,
        telegram_id=interviewer.telegram_id,
        username=interviewer.username,
        full_name=interviewer.full_name,
        name=interviewer.name,
        faculty_id=interviewer.faculty_id,
        role="interviewer",
        created_at=interviewer.created_at.isoformat()
    )
