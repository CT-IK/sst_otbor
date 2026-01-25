"""
Схемы для управления днями собеседований и временными слотами.
"""
from datetime import date as date_type, time
from typing import Optional, List

from pydantic import BaseModel, Field


# === Создание дня собеседований ===

class InterviewDayCreate(BaseModel):
    """Создание дня собеседований (Head Admin)"""
    date: date_type = Field(description="Дата собеседований")
    location: Optional[str] = Field(default=None, max_length=255, description="Локация (аудитория/ссылка)")


# === Временные слоты ===

class TimeSlotResponse(BaseModel):
    """Информация о временном слоте"""
    id: int
    time: str = Field(description="Время в формате HH:MM")
    max_participants: int = Field(ge=0, le=10, description="Количество мест (0-10)")
    current_participants: int = Field(description="Текущее количество записей")
    available_places: int = Field(description="Свободных мест")
    is_active: bool
    # Для Head Admin: список доступных проверяющих
    available_interviewers: List[dict] = Field(default_factory=list, description="Список доступных проверяющих")
    # Для Reviewer: доступен ли я в этот слот
    my_availability: Optional[bool] = Field(default=None, description="Моя доступность (null = не отмечал)")


class TimeSlotUpdate(BaseModel):
    """Обновление временного слота (установка количества мест)"""
    max_participants: int = Field(ge=0, le=10, description="Количество мест (0-10)")


# === День собеседований ===

class InterviewDayResponse(BaseModel):
    """Информация о дне собеседований"""
    id: int
    date: date_type
    location: Optional[str] = None
    is_active: bool
    time_slots: List[TimeSlotResponse] = Field(default_factory=list)


class InterviewDaysListResponse(BaseModel):
    """Список дней собеседований"""
    faculty_id: int
    faculty_name: str
    days: List[InterviewDayResponse]
    total: int


# === Доступность ===

class TimeSlotAvailabilityResponse(BaseModel):
    """Информация о доступности проверяющего"""
    time_slot_id: int
    interviewer_id: int
    interviewer_name: str
    created_at: str


class TimeSlotAvailabilityListResponse(BaseModel):
    """Список доступностей для временного слота"""
    time_slot_id: int
    time: str
    date: date_type
    availabilities: List[TimeSlotAvailabilityResponse]
    total: int
