"""
API для работы с Google Sheets (экспорт анкет).
"""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from db.session import get_db
from db.models import Faculty, Administrator, Questionnaire, User, StageTemplate, StageType
from app.api.routers.admin_stats import verify_faculty_admin, get_telegram_id, TelegramId
from app.services.google_sheets_service import google_sheets_service

router = APIRouter(prefix="/admin/google-sheets")


# === Схемы ===

class SetSheetUrlRequest(BaseModel):
    """Запрос на установку ссылки на Google таблицу"""
    sheet_url: str = Field(..., description="URL Google таблицы")


class SetSheetUrlResponse(BaseModel):
    """Ответ на установку ссылки"""
    success: bool
    message: str
    sheet_url: str | None = None


class ExportQuestionnairesRequest(BaseModel):
    """Запрос на экспорт анкет"""
    force_export_all: bool = Field(
        default=False,
        description="Принудительно экспортировать все анкеты (включая уже выгруженные)"
    )


class ExportQuestionnairesResponse(BaseModel):
    """Ответ на экспорт"""
    success: bool
    exported_count: int
    skipped_count: int
    total_in_sheet: int
    message: str
    error: str | None = None


# === Эндпоинты ===

@router.put("/{faculty_id}/sheet-url", response_model=SetSheetUrlResponse)
async def set_sheet_url(
    faculty_id: int,
    telegram_id: TelegramId,
    data: SetSheetUrlRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Установить ссылку на Google таблицу для факультета.
    Только для head_admin факультета.
    """
    admin = await verify_faculty_admin(faculty_id, telegram_id, db)
    
    # Проверяем, что это head_admin
    if admin.role != "head_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только главный администратор может настраивать Google таблицу"
        )
    
    # Получаем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Валидируем URL (базовая проверка)
    if not data.sheet_url.startswith(('http://', 'https://')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный URL таблицы"
        )
    
    # Сохраняем ссылку
    faculty.google_sheet_url = data.sheet_url
    await db.commit()
    
    return SetSheetUrlResponse(
        success=True,
        message="Ссылка на Google таблицу успешно сохранена",
        # После commit() объект может быть "expired", и доступ к атрибутам
        # вызовет ленивую подзагрузку (в async это может упасть MissingGreenlet).
        sheet_url=data.sheet_url
    )


@router.get("/{faculty_id}/sheet-url", response_model=SetSheetUrlResponse)
async def get_sheet_url(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить ссылку на Google таблицу для факультета.
    """
    admin = await verify_faculty_admin(faculty_id, telegram_id, db)
    
    # Получаем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    if not faculty.google_sheet_url:
        return SetSheetUrlResponse(
            success=False,
            message="Ссылка на Google таблицу не настроена",
            sheet_url=None
        )
    
    return SetSheetUrlResponse(
        success=True,
        message="Ссылка на Google таблицу найдена",
        sheet_url=faculty.google_sheet_url
    )


@router.post("/{faculty_id}/export", response_model=ExportQuestionnairesResponse)
async def export_questionnaires(
    faculty_id: int,
    telegram_id: TelegramId,
    data: ExportQuestionnairesRequest = ExportQuestionnairesRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    Экспортировать анкеты факультета в Google таблицу.
    Только для head_admin факультета.
    """
    admin = await verify_faculty_admin(faculty_id, telegram_id, db)
    
    # Проверяем, что это head_admin
    if admin.role != "head_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только главный администратор может экспортировать данные"
        )
    
    # Получаем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Проверяем, что ссылка настроена
    if not faculty.google_sheet_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ссылка на Google таблицу не настроена. Сначала установите ссылку."
        )
    
    # Получаем шаблон вопросов
    result = await db.execute(
        select(StageTemplate).where(
            StageTemplate.faculty_id == faculty_id,
            StageTemplate.stage_type == StageType.QUESTIONNAIRE,
            StageTemplate.is_active == True
        )
    )
    template = result.scalars().first()
    if not template:
        raise HTTPException(
            status_code=404,
            detail="Шаблон анкеты не найден"
        )
    
    questions = template.questions or []
    
    # Получаем все анкеты факультета
    result = await db.execute(
        select(Questionnaire, User).join(
            User, Questionnaire.user_id == User.id
        ).where(
            Questionnaire.faculty_id == faculty_id
        ).order_by(Questionnaire.submitted_at.desc())
    )
    rows = result.all()
    
    # Формируем данные для экспорта
    questionnaires_data = []
    for questionnaire, user in rows:
        # Формируем ФИО пользователя:
        # 1) сначала пробуем взять из ответов анкеты (questions.json: surname, first_name, middle_name)
        # 2) если там пусто — используем поля User из БД
        answers = questionnaire.answers or {}
        first_name = (
            answers.get("first_name")
            or user.first_name
            or ""
        )
        middle_name = (
            answers.get("middle_name")
            or getattr(user, "second_name", None)
            or ""
        )
        surname = (
            answers.get("surname")
            or user.surname
            or ""
        )
        # Собираем "Имя Отчество Фамилия" (без лишних пробелов)
        user_name = " ".join(part for part in [first_name, middle_name, surname] if part).strip()
        if not user_name:
            user_name = f"User {user.telegram_id}"
        
        questionnaires_data.append({
            'user_id': user.id,
            'telegram_id': user.telegram_id,
            'user_name': user_name,
            'submitted_at': questionnaire.submitted_at,
            'answers': questionnaire.answers,
        })
    
    # Экспортируем
    export_result = google_sheets_service.export_questionnaires(
        sheet_url=faculty.google_sheet_url,
        questionnaires=questionnaires_data,
        questions=questions,
        faculty_name=faculty.name,
        force_export_all=data.force_export_all
    )
    
    if export_result['success']:
        message = (
            f"Экспорт завершён успешно. "
            f"Выгружено новых анкет: {export_result['exported_count']}, "
            f"пропущено (уже выгружено): {export_result['skipped_count']}, "
            f"всего в таблице: {export_result['total_in_sheet']}"
        )
    else:
        message = f"Ошибка при экспорте: {export_result['error']}"
    
    return ExportQuestionnairesResponse(
        success=export_result['success'],
        exported_count=export_result['exported_count'],
        skipped_count=export_result['skipped_count'],
        total_in_sheet=export_result['total_in_sheet'],
        message=message,
        error=export_result['error']
    )
