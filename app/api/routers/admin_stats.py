"""
API для статистики и просмотра ответов (для админов факультетов).

Эндпоинты:
- GET /admin/stats/{faculty_id} — статистика для Mini App
- GET /admin/responses/{faculty_id} — все ответы (для веб-таблицы)
- GET /admin/export/{faculty_id} — экспорт в CSV
"""
from datetime import datetime, timedelta
from typing import Annotated, Any
import hashlib
import secrets
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field

from config import settings
from db.session import get_db
from db.models import (
    User, Faculty, Administrator, Questionnaire, StageTemplate,
    UserProgress, StageType, StageStatus, SubmissionStatus
)

router = APIRouter(prefix="/admin")


# === Проверка прав админа ===

async def verify_faculty_admin(
    faculty_id: int,
    telegram_id: int,
    db: AsyncSession
) -> Administrator:
    """Проверить что пользователь - админ этого факультета или суперадмин"""
    
    # Суперадмин имеет доступ ко всем факультетам
    if settings.is_super_admin(telegram_id):
        # Создаём "виртуального" админа для суперадмина
        return Administrator(
            telegram_id=telegram_id,
            faculty_id=faculty_id,
            role="super_admin",
            is_active=True
        )
    
    # Проверяем обычного админа
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
    if telegram_id is not None:
        return telegram_id
    if settings.is_dev:
        return settings.dev_telegram_id
    raise HTTPException(status_code=400, detail="telegram_id обязателен")


TelegramId = Annotated[int, Depends(get_telegram_id)]


# === Схемы ответов ===


class AdminLoginRequest(BaseModel):
    """Запрос на вход"""
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    """Ответ на вход"""
    success: bool
    telegram_id: int | None = None
    faculty_id: int | None = None
    faculty_name: str | None = None
    error: str | None = None


class DailyStats(BaseModel):
    """Статистика за день"""
    date: str
    count: int


class FacultyStats(BaseModel):
    """Полная статистика факультета"""
    faculty_id: int
    faculty_name: str
    
    # Общие числа
    total_submissions: int = Field(description="Всего отправлено анкет")
    total_users: int = Field(description="Всего пользователей (включая не отправивших)")
    
    # По статусам
    pending_count: int = Field(description="Ожидают проверки")
    approved_count: int = Field(description="Одобрено")
    rejected_count: int = Field(description="Отклонено")
    
    # По датам (последние 14 дней)
    daily_submissions: list[DailyStats] = Field(description="Заявки по дням")
    
    # Статус этапа
    current_stage: str | None
    stage_status: str | None


class QuestionnaireResponse(BaseModel):
    """Ответ на анкету (для таблицы)"""
    id: int
    user_id: int
    telegram_id: int
    user_name: str
    answers: dict[str, Any]
    submitted_at: datetime
    status: str


class ResponsesListResponse(BaseModel):
    """Список ответов"""
    faculty_id: int
    faculty_name: str
    questions: list[dict] = Field(description="Список вопросов (для заголовков таблицы)")
    responses: list[QuestionnaireResponse]
    total: int


# === Эндпоинты ===

@router.get("/stats/{faculty_id}", response_model=FacultyStats)
async def get_faculty_stats(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить статистику факультета.
    Только для админов факультета или суперадминов.
    """
    admin = await verify_faculty_admin(faculty_id, telegram_id, db)
    
    # Получаем факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Всего анкет
    result = await db.execute(
        select(func.count(Questionnaire.id)).where(
            Questionnaire.faculty_id == faculty_id
        )
    )
    total_submissions = result.scalar() or 0
    
    # Всего пользователей
    result = await db.execute(
        select(func.count(User.id)).where(User.faculty_id == faculty_id)
    )
    total_users = result.scalar() or 0
    
    # По статусам (из UserProgress)
    result = await db.execute(
        select(UserProgress.status, func.count(UserProgress.id)).where(
            UserProgress.faculty_id == faculty_id,
            UserProgress.stage_type == StageType.QUESTIONNAIRE
        ).group_by(UserProgress.status)
    )
    status_counts = {row[0]: row[1] for row in result.all()}
    
    pending_count = status_counts.get(SubmissionStatus.SUBMITTED, 0)
    approved_count = status_counts.get(SubmissionStatus.APPROVED, 0)
    rejected_count = status_counts.get(SubmissionStatus.REJECTED, 0)
    
    # По датам (последние 14 дней)
    fourteen_days_ago = datetime.utcnow() - timedelta(days=14)
    result = await db.execute(
        select(
            func.date(Questionnaire.submitted_at).label('date'),
            func.count(Questionnaire.id).label('count')
        ).where(
            Questionnaire.faculty_id == faculty_id,
            Questionnaire.submitted_at >= fourteen_days_ago
        ).group_by(func.date(Questionnaire.submitted_at)).order_by('date')
    )
    daily_data = result.all()
    
    # Заполняем все дни (включая нулевые)
    daily_submissions = []
    for i in range(14):
        day = (datetime.utcnow() - timedelta(days=13-i)).date()
        count = next((row[1] for row in daily_data if row[0] == day), 0)
        daily_submissions.append(DailyStats(
            date=day.strftime('%d.%m'),
            count=count
        ))
    
    return FacultyStats(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        total_submissions=total_submissions,
        total_users=total_users,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        daily_submissions=daily_submissions,
        current_stage=faculty.current_stage.value if faculty.current_stage else None,
        stage_status=faculty.stage_status.value if faculty.stage_status else None,
    )


@router.get("/responses/{faculty_id}", response_model=ResponsesListResponse)
async def get_faculty_responses(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Получить все ответы на анкеты факультета.
    Для отображения в таблице.
    """
    admin = await verify_faculty_admin(faculty_id, telegram_id, db)
    
    # Факультет
    result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Шаблон вопросов (для заголовков)
    result = await db.execute(
        select(StageTemplate).where(
            StageTemplate.faculty_id == faculty_id,
            StageTemplate.stage_type == StageType.QUESTIONNAIRE,
            StageTemplate.is_active == True
        )
    )
    template = result.scalars().first()
    questions = template.questions if template else []
    
    # Все анкеты
    result = await db.execute(
        select(Questionnaire, User).join(
            User, Questionnaire.user_id == User.id
        ).where(
            Questionnaire.faculty_id == faculty_id
        ).order_by(Questionnaire.submitted_at.desc())
    )
    rows = result.all()
    
    # Получаем статусы
    user_ids = [row[1].id for row in rows]
    result = await db.execute(
        select(UserProgress).where(
            UserProgress.user_id.in_(user_ids),
            UserProgress.faculty_id == faculty_id,
            UserProgress.stage_type == StageType.QUESTIONNAIRE
        )
    )
    progress_map = {p.user_id: p for p in result.scalars().all()}
    
    responses = []
    for questionnaire, user in rows:
        progress = progress_map.get(user.id)
        status = progress.status.value if progress else "submitted"
        
        # Формируем имя пользователя
        user_name = f"{user.first_name or ''} {user.surname or ''}".strip()
        if not user_name:
            user_name = f"User {user.telegram_id}"
        
        responses.append(QuestionnaireResponse(
            id=questionnaire.id,
            user_id=user.id,
            telegram_id=user.telegram_id,
            user_name=user_name,
            answers=questionnaire.answers,
            submitted_at=questionnaire.submitted_at,
            status=status,
        ))
    
    return ResponsesListResponse(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        questions=questions,
        responses=responses,
        total=len(responses),
    )


@router.get("/export/{faculty_id}")
async def export_faculty_responses_csv(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Экспорт ответов в CSV.
    """
    admin = await verify_faculty_admin(faculty_id, telegram_id, db)
    
    # Получаем данные
    data = await get_faculty_responses(faculty_id, telegram_id, db)
    
    # Создаём CSV
    output = io.StringIO()
    
    # Заголовки: ID, Telegram ID, Имя, [вопросы...], Дата, Статус
    headers = ['ID', 'Telegram ID', 'Имя']
    question_ids = [q['id'] for q in data.questions]
    question_texts = [q['text'][:50] for q in data.questions]  # Обрезаем длинные
    headers.extend(question_texts)
    headers.extend(['Дата отправки', 'Статус'])
    
    writer = csv.writer(output)
    writer.writerow(headers)
    
    # Создаём map вопросов для быстрого доступа
    question_map = {q['id']: q for q in data.questions}
    
    # Данные
    for resp in data.responses:
        row = [
            resp.id,
            resp.telegram_id,
            resp.user_name,
        ]
        # Ответы на вопросы
        for qid in question_ids:
            question = question_map.get(qid, {})
            answer_value = resp.answers.get(qid, '')
            
            # Форматируем ответ для читаемости
            answer = format_answer_for_export(question, answer_value)
            row.append(answer)
        
        row.extend([
            resp.submitted_at.strftime('%d.%m.%Y %H:%M'),
            resp.status,
        ])
        writer.writerow(row)
    
    output.seek(0)
    
    # Возвращаем файл
    filename = f"responses_{data.faculty_name}_{datetime.now().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.get("/check/{faculty_id}")
async def check_admin_access(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
):
    """
    Проверить, является ли пользователь админом факультета.
    Используется Mini App для определения режима (user/admin).
    
    Примечание: Суперадмины НЕ получают автоматический доступ к админ-панели Mini App.
    Они должны быть добавлены в таблицу Administrator для доступа.
    """
    # Проверяем только реальных админов из таблицы (без автоматического доступа суперадминов)
    # Получаем только нужные поля напрямую, чтобы избежать проблем с lazy loading
    result = await db.execute(
        select(Administrator.role).where(
            Administrator.telegram_id == telegram_id,
            Administrator.faculty_id == faculty_id,
            Administrator.is_active == True
        )
    )
    role = result.scalar_one_or_none()
    
    if role:
        return {
            "is_admin": True,
            "role": role,
            "faculty_id": faculty_id,
        }
    else:
        return {
            "is_admin": False,
            "role": None,
            "faculty_id": faculty_id,
        }


def hash_password(password: str) -> str:
    """Хеширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Проверка пароля"""
    return hash_password(password) == password_hash


def generate_password(length: int = 12) -> str:
    """Генерация случайного пароля"""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def format_answer_for_export(question: dict, answer_value: Any) -> str:
    """Форматировать ответ для экспорта (читаемый формат)"""
    if answer_value is None or answer_value == '':
        return ''
    
    # Для вопросов с выбором (choice, multiple_choice)
    question_type = question.get('type', '')
    options = question.get('options', [])
    
    if question_type in ('choice', 'multiple_choice') and options:
        # Создаём map для быстрого поиска
        option_map = {opt.get('value'): opt.get('label', opt.get('value')) for opt in options}
        
        if isinstance(answer_value, list):
            # Множественный выбор
            labels = [option_map.get(val, val) for val in answer_value]
            return ', '.join(str(label) for label in labels)
        else:
            # Одиночный выбор
            return option_map.get(str(answer_value), str(answer_value))
    
    # Для остальных типов - просто строковое представление
    if isinstance(answer_value, (list, dict)):
        return str(answer_value)
    
    return str(answer_value)


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(
    data: AdminLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Вход админа по username и паролю.
    """
    username = data.username.lower().strip().lstrip('@')
    
    # Ищем админа по username
    result = await db.execute(
        select(Administrator).where(
            Administrator.username == username,
            Administrator.is_active == True
        )
    )
    admin = result.scalars().first()
    
    if not admin:
        return AdminLoginResponse(
            success=False,
            error="Пользователь не найден"
        )
    
    # Проверяем пароль
    if not admin.password_hash:
        return AdminLoginResponse(
            success=False,
            error="Пароль не установлен. Обратитесь к суперадмину."
        )
    
    if not verify_password(data.password, admin.password_hash):
        return AdminLoginResponse(
            success=False,
            error="Неверный пароль"
        )
    
    # Получаем факультет
    result = await db.execute(
        select(Faculty).where(Faculty.id == admin.faculty_id)
    )
    faculty = result.scalars().first()
    
    return AdminLoginResponse(
        success=True,
        telegram_id=admin.telegram_id,
        faculty_id=admin.faculty_id,
        faculty_name=faculty.name if faculty else None
    )
