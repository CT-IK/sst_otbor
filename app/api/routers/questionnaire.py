"""
API для работы с анкетами в Telegram Mini App.

Эндпоинты:
- GET /questionnaire/{faculty_id} — получить шаблон + черновик
- POST /questionnaire/{faculty_id}/draft — сохранить черновик
- DELETE /questionnaire/{faculty_id}/draft — удалить черновик
- POST /questionnaire/{faculty_id}/submit — отправить анкету
"""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import settings
from db.session import get_db
from db.models import (
    User, Faculty, StageTemplate, Questionnaire, 
    UserProgress, ApprovalQueue, StageType, StageStatus, 
    SubmissionStatus, ApprovalStatus
)
from app.core.redis import get_redis
from app.services.draft_service import DraftService
from app.services.notification_service import notification_service
from app.api.schemas.questionnaire import (
    TemplateResponse, Question, DraftSaveRequest, DraftResponse,
    DraftWithTemplateResponse, SubmitQuestionnaireRequest,
    SubmitQuestionnaireResponse, UserQuestionnaireStatus
)


router = APIRouter(prefix="/questionnaire")


def get_telegram_id(
    telegram_id: int | None = Query(default=None, description="Telegram ID пользователя")
) -> int:
    """
    Dependency для получения telegram_id.
    В dev режиме использует тестовое значение если не передано.
    """
    if telegram_id is not None:
        return telegram_id
    if settings.is_dev:
        return settings.dev_telegram_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="telegram_id обязателен"
    )


# Type alias для удобства
TelegramId = Annotated[int, Depends(get_telegram_id)]


async def get_or_create_user(
    telegram_id: int,
    faculty_id: int,
    db: AsyncSession
) -> User:
    """Получить пользователя по Telegram ID или создать нового"""
    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalars().first()
    
    if not user:
        # Автоматически создаём пользователя
        user = User(
            telegram_id=telegram_id,
            first_name="Участник",  # Будет обновлено при заполнении анкеты
            faculty_id=faculty_id,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
    
    return user


async def get_faculty_with_template(
    faculty_id: int,
    db: AsyncSession
) -> tuple[Faculty, StageTemplate]:
    """Получить факультет и активный шаблон анкеты"""
    # Факультет
    result = await db.execute(
        select(Faculty).where(Faculty.id == faculty_id)
    )
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Факультет не найден"
        )
    
    # Активный шаблон анкеты
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Шаблон анкеты не найден. Администратор ещё не создал вопросы."
        )
    
    return faculty, template


def template_to_response(faculty: Faculty, template: StageTemplate) -> TemplateResponse:
    """Конвертировать модель в ответ API"""
    questions = [
        Question(
            id=q["id"],
            text=q["text"],
            type=q.get("type", "text"),
            required=q.get("required", True),
            order=q.get("order", 0),
            options=q.get("options"),
            max_length=q.get("max_length"),
            min_value=q.get("min_value"),
            max_value=q.get("max_value"),
        )
        for q in template.questions
    ]
    return TemplateResponse(
        template_id=template.id,
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        stage_type=template.stage_type.value,
        questions=questions,
        version=template.version,
    )


# === Эндпоинты ===

@router.get("/{faculty_id}", response_model=DraftWithTemplateResponse)
async def get_questionnaire_form(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """
    Получить форму анкеты: шаблон вопросов + черновик (если есть).
    
    Вызывается при открытии Mini App.
    """
    faculty, template = await get_faculty_with_template(faculty_id, db)
    user = await get_or_create_user(telegram_id, faculty_id, db)
    
    # Проверяем, отправлял ли уже анкету
    result = await db.execute(
        select(Questionnaire).where(
            Questionnaire.user_id == user.id,
            Questionnaire.faculty_id == faculty_id,
        )
    )
    existing_questionnaire = result.scalars().first()
    already_submitted = existing_questionnaire is not None
    submitted_at = existing_questionnaire.submitted_at if existing_questionnaire else None
    
    # Проверяем текущий этап факультета
    current_stage = faculty.current_stage
    
    # Если этап HOME_VIDEO, возвращаем специальный ответ
    if current_stage == StageType.HOME_VIDEO:
        return DraftWithTemplateResponse(
            template=template_to_response(faculty, template),
            draft=None,
            stage_status=faculty.stage_status.value if faculty.stage_status else "not_started",
            can_submit=False,
            already_submitted=already_submitted,
            submitted_at=submitted_at,
            current_stage="home_video",  # Указываем, что нужно показать сообщение о видео
        )
    
    # Проверяем статус этапа для анкеты
    can_submit = (
        current_stage == StageType.QUESTIONNAIRE and
        faculty.stage_status == StageStatus.OPEN and
        not already_submitted  # Нельзя отправить повторно!
    )
    
    # Получаем черновик из Redis (только если ещё не отправил)
    draft_response = None
    if not already_submitted:
        draft_service = DraftService(redis_client)
        draft_data = await draft_service.get_draft(telegram_id, faculty_id)
        
        if draft_data:
            ttl = await draft_service.get_draft_ttl(telegram_id, faculty_id)
            draft_response = DraftResponse(
                template_id=draft_data["template_id"],
                answers=draft_data["answers"],
                updated_at=datetime.fromisoformat(draft_data["updated_at"]),
                ttl_seconds=max(ttl, 0),
            )
    
    return DraftWithTemplateResponse(
        template=template_to_response(faculty, template),
        draft=draft_response,
        stage_status=faculty.stage_status.value if faculty.stage_status else "not_started",
        can_submit=can_submit,
        already_submitted=already_submitted,
        submitted_at=submitted_at,
        current_stage=current_stage.value if current_stage else "not_started",
    )


@router.post("/{faculty_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def save_draft(
    faculty_id: int,
    telegram_id: TelegramId,
    data: DraftSaveRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """
    Сохранить черновик анкеты в Redis.
    
    Вызывается при каждом изменении ответов (с debounce на фронте).
    """
    user = await get_or_create_user(telegram_id, faculty_id, db)
    
    # Проверяем что шаблон существует
    result = await db.execute(
        select(StageTemplate).where(StageTemplate.id == data.template_id)
    )
    template = result.scalars().first()
    if not template or template.faculty_id != faculty_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный template_id"
        )
    
    draft_service = DraftService(redis_client)
    await draft_service.save_draft(
        telegram_id=telegram_id,
        faculty_id=faculty_id,
        template_id=data.template_id,
        answers=data.answers,
    )


@router.delete("/{faculty_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """Удалить черновик анкеты."""
    user = await get_or_create_user(telegram_id, faculty_id, db)
    
    draft_service = DraftService(redis_client)
    await draft_service.delete_draft(telegram_id, faculty_id)


@router.post("/{faculty_id}/submit", response_model=SubmitQuestionnaireResponse)
async def submit_questionnaire(
    faculty_id: int,
    telegram_id: TelegramId,
    data: SubmitQuestionnaireRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """
    Отправить анкету на проверку.
    
    1. Проверяем что этап открыт
    2. Валидируем ответы
    3. Сохраняем в PostgreSQL (Questionnaire + ApprovalQueue + UserProgress)
    4. Удаляем черновик из Redis
    """
    faculty, template = await get_faculty_with_template(faculty_id, db)
    user = await get_or_create_user(telegram_id, faculty_id, db)
    
    # Проверяем что этап открыт
    if faculty.current_stage != StageType.QUESTIONNAIRE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этап анкеты ещё не начался или уже завершён"
        )
    if faculty.stage_status != StageStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Приём анкет закрыт"
        )
    
    # Проверяем template_id
    if data.template_id != template.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Шаблон устарел. Обновите страницу."
        )
    
    # Проверяем что ещё не отправлял
    result = await db.execute(
        select(Questionnaire).where(
            Questionnaire.user_id == user.id,
            Questionnaire.faculty_id == faculty_id,
        )
    )
    existing = result.scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Вы уже отправили анкету"
        )
    
    # Валидация обязательных полей
    required_questions = [q["id"] for q in template.questions if q.get("required", True)]
    missing = [qid for qid in required_questions if qid not in data.answers or not data.answers[qid]]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Не заполнены обязательные поля: {missing}"
        )
    
    # Создаём анкету
    questionnaire = Questionnaire(
        user_id=user.id,
        faculty_id=faculty_id,
        template_id=template.id,
        answers=data.answers,
    )
    db.add(questionnaire)
    
    # Добавляем в очередь на проверку
    approval = ApprovalQueue(
        user_id=user.id,
        faculty_id=faculty_id,
        stage_type=StageType.QUESTIONNAIRE,
        answers=data.answers,
        status=ApprovalStatus.PENDING,
    )
    db.add(approval)
    
    # Обновляем прогресс пользователя
    result = await db.execute(
        select(UserProgress).where(
            UserProgress.user_id == user.id,
            UserProgress.faculty_id == faculty_id,
            UserProgress.stage_type == StageType.QUESTIONNAIRE,
        )
    )
    progress = result.scalars().first()
    if progress:
        progress.status = SubmissionStatus.SUBMITTED
        progress.submitted_at = datetime.utcnow()
    else:
        progress = UserProgress(
            user_id=user.id,
            faculty_id=faculty_id,
            stage_type=StageType.QUESTIONNAIRE,
            status=SubmissionStatus.SUBMITTED,
            submitted_at=datetime.utcnow(),
        )
        db.add(progress)
    
    # Сохраняем имя факультета до commit (чтобы избежать lazy loading после commit)
    faculty_name = faculty.name
    
    await db.commit()
    await db.refresh(questionnaire)
    
    # Удаляем черновик из Redis
    draft_service = DraftService(redis_client)
    await draft_service.delete_draft(telegram_id, faculty_id)
    
    # Отправляем уведомление в Telegram
    await notification_service.notify_questionnaire_submitted(
        telegram_id=telegram_id,
        faculty_name=faculty_name
    )
    
    return SubmitQuestionnaireResponse(
        success=True,
        questionnaire_id=questionnaire.id,
        message="Анкета успешно отправлена на проверку",
    )


@router.get("/{faculty_id}/status", response_model=UserQuestionnaireStatus)
async def get_questionnaire_status(
    faculty_id: int,
    telegram_id: TelegramId,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """Получить статус анкеты пользователя."""
    user = await get_or_create_user(telegram_id, faculty_id, db)
    
    # Факультет
    result = await db.execute(
        select(Faculty).where(Faculty.id == faculty_id)
    )
    faculty = result.scalars().first()
    if not faculty:
        raise HTTPException(status_code=404, detail="Факультет не найден")
    
    # Прогресс пользователя
    result = await db.execute(
        select(UserProgress).where(
            UserProgress.user_id == user.id,
            UserProgress.faculty_id == faculty_id,
            UserProgress.stage_type == StageType.QUESTIONNAIRE,
        )
    )
    progress = result.scalars().first()
    
    user_status = progress.status.value if progress else "not_started"
    submitted_at = progress.submitted_at if progress else None
    
    # Проверяем черновик
    draft_service = DraftService(redis_client)
    has_draft = await draft_service.get_draft(telegram_id, faculty_id) is not None
    
    # Можно ли отправить
    can_submit = (
        faculty.current_stage == StageType.QUESTIONNAIRE and
        faculty.stage_status == StageStatus.OPEN and
        user_status not in ["submitted", "approved"]
    )
    
    return UserQuestionnaireStatus(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        stage_status=faculty.stage_status.value if faculty.stage_status else "not_started",
        user_status=user_status,
        submitted_at=submitted_at,
        can_edit=has_draft or user_status == "not_started",
        can_submit=can_submit,
    )


# === Dev эндпоинты ===

@router.post("/dev/seed", include_in_schema=False)
async def seed_dev_data(
    db: AsyncSession = Depends(get_db),
):
    """
    Создать тестовые данные для разработки.
    Только в dev режиме!
    """
    if not settings.is_dev:
        raise HTTPException(status_code=403, detail="Только для dev режима")
    
    faculty_id = settings.dev_faculty_id
    telegram_id = settings.dev_telegram_id
    template_id = None
    
    # Проверяем, есть ли уже тестовый факультет
    result = await db.execute(
        select(Faculty).where(Faculty.id == faculty_id)
    )
    faculty = result.scalars().first()
    
    if not faculty:
        # Создаём тестовый факультет
        faculty = Faculty(
            name="Тестовый факультет",
            description="Факультет для разработки",
            current_stage=StageType.QUESTIONNAIRE,
            stage_status=StageStatus.OPEN,
        )
        db.add(faculty)
        await db.flush()
        await db.refresh(faculty)
        faculty_id = faculty.id
    
    # Проверяем тестового пользователя
    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalars().first()
    
    if not user:
        user = User(
            telegram_id=telegram_id,
            first_name="Тест",
            second_name="Тестович",
            surname="Тестов",
            faculty_id=faculty_id,
            course_of_study=2,
            group="ТЕС-21",
        )
        db.add(user)
        await db.flush()
    
    # Проверяем шаблон анкеты
    result = await db.execute(
        select(StageTemplate).where(
            StageTemplate.faculty_id == faculty_id,
            StageTemplate.stage_type == StageType.QUESTIONNAIRE,
            StageTemplate.is_active == True,
        )
    )
    template = result.scalars().first()
    
    if not template:
        template = StageTemplate(
            faculty_id=faculty_id,
            stage_type=StageType.QUESTIONNAIRE,
            version=1,
            is_active=True,
            questions=[
                {
                    "id": "motivation",
                    "text": "Почему вы хотите вступить в студенческий совет?",
                    "type": "text",
                    "required": True,
                    "order": 1,
                    "max_length": 1000,
                },
                {
                    "id": "experience",
                    "text": "Расскажите о вашем опыте организаторской деятельности",
                    "type": "text",
                    "required": True,
                    "order": 2,
                    "max_length": 1000,
                },
                {
                    "id": "skills",
                    "text": "Какими навыками вы обладаете?",
                    "type": "multiple_choice",
                    "required": True,
                    "order": 3,
                    "options": [
                        {"value": "design", "label": "Дизайн"},
                        {"value": "smm", "label": "SMM"},
                        {"value": "video", "label": "Видеомонтаж"},
                        {"value": "photo", "label": "Фотография"},
                        {"value": "events", "label": "Организация мероприятий"},
                        {"value": "other", "label": "Другое"},
                    ],
                },
                {
                    "id": "time",
                    "text": "Сколько часов в неделю готовы уделять студсовету?",
                    "type": "choice",
                    "required": True,
                    "order": 4,
                    "options": [
                        {"value": "5", "label": "До 5 часов"},
                        {"value": "10", "label": "5-10 часов"},
                        {"value": "15", "label": "10-15 часов"},
                        {"value": "more", "label": "Более 15 часов"},
                    ],
                },
                {
                    "id": "additional",
                    "text": "Что ещё хотите добавить? (необязательно)",
                    "type": "text",
                    "required": False,
                    "order": 5,
                    "max_length": 500,
                },
            ],
        )
        db.add(template)
        await db.flush()
        await db.refresh(template)
    
    template_id = template.id
    
    await db.commit()
    
    return {
        "message": "Тестовые данные созданы",
        "faculty_id": faculty_id,
        "user_telegram_id": telegram_id,
        "template_id": template_id,
    }

