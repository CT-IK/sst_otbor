"""
API для назначения проводящих на собеседования.

Эндпоинты:
- GET /interview-assignments/{faculty_id} — получить список записей на собеседования
- GET /interview-assignments/{interview_id} — получить детали записи
- GET /interview-assignments/{interview_id}/available-interviewers — получить доступных проводящих
- POST /interview-assignments/{interview_id}/assign — назначить проводящих
"""
from datetime import date, time, datetime
from typing import Annotated, List, Optional
import logging
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field

from config import settings
from db.session import get_db
from db.models import (
    Faculty, Administrator, Interview, InterviewTimeSlot, 
    InterviewerSchedule, User, InterviewInterviewer, InterviewStatus, Interviewer
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/interview-assignments")


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
    """Проверить, что пользователь является Head Admin факультета"""
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
            detail="Только главный администратор факультета может выполнить это действие"
        )
    return admin


# === Схемы ===

class InterviewerInfo(BaseModel):
    id: int
    name: str
    role: str

    class Config:
        from_attributes = True


class InterviewListItem(BaseModel):
    id: int
    user_fio: str
    user_username: Optional[str]
    date: date
    time: str
    status: str
    interviewers: List[InterviewerInfo] = []

    class Config:
        from_attributes = True


class InterviewDetailResponse(BaseModel):
    id: int
    user_fio: str
    user_username: Optional[str]
    user_telegram_id: Optional[int]
    date: date
    time: str
    status: str
    reschedule_count: int
    interviewers: List[InterviewerInfo] = []
    available_interviewers: List[InterviewerInfo] = []


class AssignInterviewersRequest(BaseModel):
    interviewer_ids: List[int] = Field(..., min_items=1, max_items=2, description="Список ID проводящих (1-2 человека)")


# === Эндпоинты ===

@router.get("/{faculty_id}", response_model=List[InterviewListItem])
async def get_interviews(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """Получить список записей на собеседования для факультета"""
    admin = await verify_head_admin(faculty_id, telegram_id, db)
    
    # Получаем все записи на собеседования
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.user), selectinload(Interview.interview_time_slot))
        .where(
            Interview.faculty_id == faculty_id,
            Interview.status == InterviewStatus.SCHEDULED
        )
        .order_by(Interview.created_at.desc())
    )
    interviews = result.scalars().all()
    
    # Получаем назначенных проводящих для всех записей
    interview_ids = [i.id for i in interviews]
    interviewers_map = {}
    if interview_ids:
        result = await db.execute(
            select(InterviewInterviewer)
            .options(selectinload(InterviewInterviewer.interviewer))
            .where(InterviewInterviewer.interview_id.in_(interview_ids))
        )
        interviewers = result.scalars().all()
        for ii in interviewers:
            if ii.interview_id not in interviewers_map:
                interviewers_map[ii.interview_id] = []
            interviewer = ii.interviewer
            name = interviewer.name or interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}"
            interviewers_map[ii.interview_id].append(
                InterviewerInfo(
                    id=interviewer.id,
                    name=name,
                    role="interviewer"  # У модели Interviewer нет поля role, используем константу
                )
            )
    
    # Формируем ответ
    response = []
    for interview in interviews:
        user = interview.user
        parts = []
        if user.first_name:
            parts.append(user.first_name)
        if user.second_name:
            parts.append(user.second_name)
        if user.surname:
            parts.append(user.surname)
        user_fio = " ".join(parts) if parts else f"ID {user.telegram_id}"
        
        slot = interview.interview_time_slot
        if not slot:
            continue
        
        assigned_interviewers = interviewers_map.get(interview.id, [])
        
        # У модели User нет поля username, используем None
        response.append(InterviewListItem(
            id=interview.id,
            user_fio=user_fio,
            user_username=None,  # User model не имеет поля username
            date=slot.date,
            time=slot.time.strftime("%H:%M"),
            status=interview.status.value,
            interviewers=assigned_interviewers
        ))
    
    return response


@router.get("/{interview_id}/detail", response_model=InterviewDetailResponse)
async def get_interview_detail(
    interview_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """Получить детали записи на собеседование"""
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.user), selectinload(Interview.interview_time_slot))
        .where(Interview.id == interview_id)
    )
    interview = result.scalars().first()
    
    if not interview:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    
    admin = await verify_head_admin(interview.faculty_id, telegram_id, db)
    
    user = interview.user
    parts = []
    if user.first_name:
        parts.append(user.first_name)
    if user.second_name:
        parts.append(user.second_name)
    if user.surname:
        parts.append(user.surname)
    user_fio = " ".join(parts) if parts else f"ID {user.telegram_id}"
    
    slot = interview.interview_time_slot
    if not slot:
        raise HTTPException(status_code=400, detail="Слот не найден")
    
    # Получаем назначенных проводящих
    result = await db.execute(
        select(InterviewInterviewer)
        .options(selectinload(InterviewInterviewer.interviewer))
        .where(InterviewInterviewer.interview_id == interview_id)
    )
    assigned_interviewers_list = result.scalars().all()
    assigned_interviewers = []
    for ii in assigned_interviewers_list:
        interviewer = ii.interviewer
        name = interviewer.name or interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}"
        assigned_interviewers.append(
            InterviewerInfo(
                id=interviewer.id,
                name=name,
                role="interviewer"  # У модели Interviewer нет поля role, используем константу
            )
        )
    
    # Получаем доступных проводящих для этого времени
    result = await db.execute(
        select(Interviewer).where(
            Interviewer.faculty_id == interview.faculty_id,
            Interviewer.is_active == True
        )
    )
    all_interviewers = result.scalars().all()
    
    # Проверяем доступность через InterviewerSchedule
    result = await db.execute(
        select(InterviewerSchedule).where(
            InterviewerSchedule.faculty_id == interview.faculty_id,
            InterviewerSchedule.date == slot.date,
            InterviewerSchedule.time_slot == slot.time,
            InterviewerSchedule.is_available == True
        )
    )
    available_schedules = result.scalars().all()
    available_interviewer_ids = {s.interviewer_id for s in available_schedules}
    
    available_interviewers = []
    for interviewer in all_interviewers:
        if interviewer.id in available_interviewer_ids:
            name = interviewer.name or interviewer.full_name or interviewer.username or f"ID {interviewer.telegram_id}"
            available_interviewers.append(
                InterviewerInfo(
                    id=interviewer.id,
                    name=name,
                    role="interviewer"
                )
            )
    
    # У модели User нет поля username, используем None
    return InterviewDetailResponse(
        id=interview.id,
        user_fio=user_fio,
        user_username=None,  # User model не имеет поля username
        user_telegram_id=user.telegram_id,
        date=slot.date,
        time=slot.time.strftime("%H:%M"),
        status=interview.status.value,
        reschedule_count=interview.reschedule_count,
        interviewers=assigned_interviewers,
        available_interviewers=available_interviewers
    )


@router.post("/{interview_id}/assign", status_code=status.HTTP_200_OK)
async def assign_interviewers(
    interview_id: int,
    data: AssignInterviewersRequest,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """Назначить проводящих на собеседование"""
    result = await db.execute(
        select(Interview)
        .options(selectinload(Interview.user), selectinload(Interview.interview_time_slot))
        .where(Interview.id == interview_id)
    )
    interview = result.scalars().first()
    
    if not interview:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    
    admin = await verify_head_admin(interview.faculty_id, telegram_id, db)
    
    if len(data.interviewer_ids) < 1 or len(data.interviewer_ids) > 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Необходимо назначить от 1 до 2 проводящих"
        )
    
    # Проверяем, что все проводящие существуют и активны
    result = await db.execute(
        select(Interviewer).where(
            Interviewer.id.in_(data.interviewer_ids),
            Interviewer.faculty_id == interview.faculty_id,
            Interviewer.is_active == True
        )
    )
    interviewers = result.scalars().all()
    
    if len(interviewers) != len(data.interviewer_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Один или несколько проводящих не найдены или неактивны"
        )
    
    # Сохраняем нужные значения до commit
    # interview уже загружен с selectinload на строке 299
    slot = interview.interview_time_slot
    user = interview.user
    
    if not slot:
        raise HTTPException(status_code=404, detail="Слот собеседования не найден")
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    # Сохраняем все значения в локальные переменные ДО commit()
    slot_date = slot.date
    slot_time = slot.time
    
    parts = []
    if user.first_name:
        parts.append(user.first_name)
    if user.second_name:
        parts.append(user.second_name)
    if user.surname:
        parts.append(user.surname)
    user_fio = " ".join(parts) if parts else f"ID {user.telegram_id}"
    # В модели User нет поля username, используем telegram_id для отображения
    username = f"{user.telegram_id}" if user.telegram_id else "не указан"
    
    # Сохраняем telegram_id проводящих ДО commit (важно: сохраняем в список)
    interviewer_telegram_ids = [int(i.telegram_id) for i in interviewers if i.telegram_id]
    
    # Удаляем старые назначения
    result = await db.execute(
        select(InterviewInterviewer).where(
            InterviewInterviewer.interview_id == interview_id
        )
    )
    old_assignments = result.scalars().all()
    for old in old_assignments:
        await db.delete(old)
    
    await db.flush()
    
    # Создаём новые назначения
    for interviewer_id in data.interviewer_ids:
        assignment = InterviewInterviewer(
            interview_id=interview_id,
            interviewer_id=interviewer_id,
            assigned_by=admin.id
        )
        db.add(assignment)
    
    await db.commit()
    
    # Отправляем уведомления проводящим
    bot_token = settings.telegram_bot_token
    if bot_token:
        for interviewer_telegram_id in interviewer_telegram_ids:
            try:
                notification_text = (
                    f"📅 <b>Вам назначено собеседование</b>\n\n"
                    f"👤 <b>Кандидат:</b> {user_fio}\n"
                    f"📱 Username: @{username}\n"
                    f"📅 <b>Дата:</b> {slot_date.strftime('%d.%m.%Y')}\n"
                    f"🕐 <b>Время:</b> {slot_time.strftime('%H:%M')}\n\n"
                    f"Пожалуйста, будьте готовы провести собеседование."
                )
                
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json={
                        "chat_id": interviewer_telegram_id,
                        "text": notification_text,
                        "parse_mode": "HTML"
                    })
                    response.raise_for_status()
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления проводящему {interviewer_telegram_id}: {e}")
    
    return {"success": True, "message": "Проводящие назначены"}
