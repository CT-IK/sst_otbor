"""
Схемы для управления слотами собеседований.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# === Создание/обновление слота ===

class InterviewSlotCreate(BaseModel):
    """Создание слота собеседования (Head Admin)"""
    datetime_start: datetime = Field(description="Дата и время начала слота")
    datetime_end: datetime = Field(description="Дата и время окончания слота")
    max_participants: int = Field(default=1, ge=1, description="Максимальное количество участников")
    location: Optional[str] = Field(default=None, max_length=255, description="Локация (аудитория/ссылка)")


class InterviewSlotUpdate(BaseModel):
    """Обновление слота собеседования (Head Admin)"""
    datetime_start: Optional[datetime] = None
    datetime_end: Optional[datetime] = None
    max_participants: Optional[int] = Field(default=None, ge=1)
    location: Optional[str] = Field(default=None, max_length=255)
    is_active: Optional[bool] = None


# === Ответы API ===

class InterviewSlotResponse(BaseModel):
    """Информация о слоте собеседования"""
    id: int
    faculty_id: int
    datetime_start: datetime
    datetime_end: datetime
    max_participants: int
    current_participants: int = Field(description="Текущее количество записей")
    available_places: int = Field(description="Свободных мест")
    location: Optional[str] = None
    is_active: bool
    created_by: Optional[int] = Field(description="ID администратора, который создал слот")
    created_at: datetime
    # Для Reviewer: доступен ли он в этот слот
    my_availability: Optional[bool] = Field(default=None, description="Моя доступность (null = не отмечал)")


class InterviewSlotsListResponse(BaseModel):
    """Список слотов факультета"""
    faculty_id: int
    faculty_name: str
    slots: list[InterviewSlotResponse]
    total: int


class AvailabilityResponse(BaseModel):
    """Информация о доступности"""
    slot_id: int
    available: bool
    interviewer_id: int
    updated_at: datetime


class AvailabilityListResponse(BaseModel):
    """Список моих доступностей"""
    faculty_id: int
    availabilities: list[AvailabilityResponse]
    total: int
