"""
API для загрузки видео через Mini App.
Обходит ограничение Telegram Bot API в 50 МБ.
Поддерживает S3 хранилище (reg.ru Object Storage).
"""
import uuid
import logging
import httpx
from datetime import datetime
from typing import Optional
from pathlib import Path
from io import BytesIO

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from db.session import get_db
from db.models import (
    User, Faculty, UserProgress, HomeVideo,
    StageType, SubmissionStatus
)
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/video")

# Максимальный размер файла (500 МБ)
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB in bytes

# Разрешённые расширения
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# MIME types
CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}

# S3 клиент (ленивая инициализация)
_s3_client = None


def get_s3_client():
    """Получить S3 клиент (создаётся один раз)"""
    global _s3_client
    if _s3_client is None:
        try:
            import boto3
            _s3_client = boto3.client(
                's3',
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region
            )
            logger.info(f"S3 клиент инициализирован: {settings.s3_endpoint}")
        except Exception as e:
            logger.error(f"Ошибка инициализации S3 клиента: {e}")
            raise
    return _s3_client


def is_s3_configured() -> bool:
    """Проверить, настроен ли S3"""
    return bool(settings.s3_access_key and settings.s3_secret_key and settings.s3_bucket)


async def upload_to_s3(content: bytes, filename: str, content_type: str) -> str:
    """
    Загрузить файл в S3 и вернуть публичный URL.
    """
    s3 = get_s3_client()
    bucket = settings.s3_bucket
    
    # Загружаем файл
    s3.put_object(
        Bucket=bucket,
        Key=filename,
        Body=content,
        ContentType=content_type,
        ACL='public-read'  # Делаем файл публичным
    )
    
    # Формируем публичный URL
    # Для reg.ru формат: https://s3.regru.cloud/bucket/filename
    endpoint = settings.s3_endpoint.rstrip('/')
    public_url = f"{endpoint}/{bucket}/{filename}"
    
    logger.info(f"Файл загружен в S3: {public_url}")
    return public_url


class VideoUploadResponse(BaseModel):
    success: bool
    message: str
    video_id: Optional[int] = None
    video_url: Optional[str] = None


class VideoStatusResponse(BaseModel):
    can_upload: bool
    message: str
    faculty_name: Optional[str] = None
    faculty_id: Optional[int] = None
    already_submitted: bool = False


class TestUploadResponse(BaseModel):
    success: bool
    message: str
    filename: str
    size_mb: float
    url: str


async def get_user_video_faculty(telegram_id: int, db: AsyncSession):
    """
    Найти факультет, где пользователь может загрузить видео.
    Возвращает (user, faculty, questionnaire_progress) или (None, None, None)
    """
    # Получаем пользователя
    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalars().first()
    
    if not user:
        return None, None, None
    
    # Ищем факультет, где человек подал анкету И где сейчас этап HOME_VIDEO
    result = await db.execute(
        select(UserProgress, Faculty)
        .join(Faculty, UserProgress.faculty_id == Faculty.id)
        .where(
            UserProgress.user_id == user.id,
            UserProgress.stage_type == StageType.QUESTIONNAIRE,
            UserProgress.status == SubmissionStatus.SUBMITTED,
            Faculty.current_stage == StageType.HOME_VIDEO,
            Faculty.video_submission_open == True
        )
    )
    row = result.first()
    
    if not row:
        return user, None, None
    
    progress, faculty = row
    return user, faculty, progress


@router.get("/status", response_model=VideoStatusResponse)
async def get_video_status(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """
    Проверить, может ли пользователь загрузить видео.
    """
    user, faculty, progress = await get_user_video_faculty(telegram_id, db)
    
    if not user:
        return VideoStatusResponse(
            can_upload=False,
            message="Вы не зарегистрированы в системе"
        )
    
    if not faculty:
        return VideoStatusResponse(
            can_upload=False,
            message="Нет факультетов с открытым приёмом видео"
        )
    
    # Проверяем, не отправлял ли уже видео
    result = await db.execute(
        select(UserProgress).where(
            UserProgress.user_id == user.id,
            UserProgress.faculty_id == faculty.id,
            UserProgress.stage_type == StageType.HOME_VIDEO
        )
    )
    video_progress = result.scalars().first()
    
    if video_progress and video_progress.status == SubmissionStatus.SUBMITTED:
        return VideoStatusResponse(
            can_upload=False,
            message="Вы уже отправили видео",
            faculty_name=faculty.name,
            faculty_id=faculty.id,
            already_submitted=True
        )
    
    return VideoStatusResponse(
        can_upload=True,
        message="Вы можете загрузить видео",
        faculty_name=faculty.name,
        faculty_id=faculty.id,
        already_submitted=False
    )


@router.post("/upload", response_model=VideoUploadResponse)
async def upload_video(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    file: UploadFile = File(..., description="Видео файл"),
    db: AsyncSession = Depends(get_db),
):
    """
    Загрузить видео.
    Максимальный размер: 500 МБ.
    """
    # Проверяем, настроен ли S3
    if not is_s3_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Хранилище видео не настроено"
        )
    
    # Проверяем пользователя и факультет
    user, faculty, progress = await get_user_video_faculty(telegram_id, db)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Вы не зарегистрированы в системе"
        )
    
    if not faculty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет факультетов с открытым приёмом видео"
        )
    
    # Сохраняем данные до работы с файлом
    user_id = user.id
    user_telegram_id = user.telegram_id
    user_first_name = user.first_name or ""
    user_surname = user.surname or ""
    faculty_id = faculty.id
    faculty_name = faculty.name
    video_chat_id = faculty.video_chat_id
    
    # Проверяем, не отправлял ли уже видео
    result = await db.execute(
        select(UserProgress).where(
            UserProgress.user_id == user_id,
            UserProgress.faculty_id == faculty_id,
            UserProgress.stage_type == StageType.HOME_VIDEO
        )
    )
    video_progress = result.scalars().first()
    
    if video_progress and video_progress.status == SubmissionStatus.SUBMITTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Вы уже отправили видео"
        )
    
    # Проверяем расширение файла
    file_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неподдерживаемый формат. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Читаем файл и проверяем размер
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой. Максимум: {MAX_FILE_SIZE // (1024*1024)} МБ"
        )
    
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл пустой"
        )
    
    # Генерируем уникальное имя файла
    unique_id = uuid.uuid4().hex[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"video_{faculty_id}_{user_telegram_id}_{timestamp}_{unique_id}{file_ext}"
    
    # Загружаем в S3
    try:
        content_type = CONTENT_TYPES.get(file_ext, "video/mp4")
        video_url = await upload_to_s3(content, filename, content_type)
        logger.info(f"Видео загружено в S3: {video_url}")
    except Exception as e:
        logger.error(f"Ошибка загрузки в S3: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка загрузки файла в хранилище"
        )
    
    # Создаём запись в БД
    home_video = HomeVideo(
        user_id=user_id,
        faculty_id=faculty_id,
        video_url=video_url,
        file_id=filename,
    )
    db.add(home_video)
    
    # Обновляем или создаём прогресс
    if video_progress:
        video_progress.status = SubmissionStatus.SUBMITTED
        video_progress.submitted_at = datetime.now()
    else:
        video_progress = UserProgress(
            user_id=user_id,
            faculty_id=faculty_id,
            stage_type=StageType.HOME_VIDEO,
            status=SubmissionStatus.SUBMITTED,
            submitted_at=datetime.now()
        )
        db.add(video_progress)
    
    await db.commit()
    await db.refresh(home_video)
    
    # Отправляем уведомление в Telegram чат факультета
    if video_chat_id:
        await send_telegram_notification(
            chat_id=video_chat_id,
            user_name=f"{user_first_name} {user_surname}".strip() or f"User {user_telegram_id}",
            user_telegram_id=user_telegram_id,
            faculty_name=faculty_name,
            video_url=video_url,
            file_size_mb=round(file_size / (1024 * 1024), 1)
        )
    
    return VideoUploadResponse(
        success=True,
        message="Видео успешно загружено!",
        video_id=home_video.id,
        video_url=video_url
    )


@router.post("/test-upload", response_model=TestUploadResponse)
async def test_upload_video(
    file: UploadFile = File(..., description="Видео файл"),
):
    """
    Тестовая загрузка видео в S3.
    Не требует авторизации, не пишет в БД, не отправляет уведомления.
    """
    # Проверяем, настроен ли S3
    if not is_s3_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 хранилище не настроено. Добавьте S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET в .env"
        )
    
    # Проверяем расширение файла
    file_ext = Path(file.filename).suffix.lower() if file.filename else ".mp4"
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неподдерживаемый формат. Разрешены: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Читаем файл
    content = await file.read()
    file_size = len(content)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой. Максимум: {MAX_FILE_SIZE // (1024*1024)} МБ"
        )
    
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл пустой"
        )
    
    # Генерируем уникальное имя файла
    unique_id = uuid.uuid4().hex[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"test_{timestamp}_{unique_id}{file_ext}"
    
    # Загружаем в S3
    try:
        content_type = CONTENT_TYPES.get(file_ext, "video/mp4")
        video_url = await upload_to_s3(content, filename, content_type)
        logger.info(f"Тестовое видео загружено в S3: {video_url}")
    except Exception as e:
        logger.error(f"Ошибка загрузки в S3: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки в S3: {str(e)}"
        )
    
    size_mb = round(file_size / (1024 * 1024), 2)
    
    return TestUploadResponse(
        success=True,
        message=f"Видео загружено в S3! Размер: {size_mb} МБ",
        filename=filename,
        size_mb=size_mb,
        url=video_url
    )


async def send_telegram_notification(
    chat_id: int,
    user_name: str,
    user_telegram_id: int,
    faculty_name: str,
    video_url: str,
    file_size_mb: float
):
    """
    Отправить уведомление в Telegram чат о новом видео.
    """
    try:
        bot_token = settings.telegram_bot_token
        if not bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN не настроен")
            return
        
        submission_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        text = (
            f"<b>Новое видео от кандидата</b>\n\n"
            f"<b>{user_name}</b>\n"
            f"ID: <code>{user_telegram_id}</code>\n"
            f"Факультет: {faculty_name}\n"
            f"Размер: {file_size_mb} МБ\n"
            f"Время: {submission_time}\n\n"
            f"<a href=\"{video_url}\">Смотреть видео</a>"
        )
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            })
            
            if response.status_code != 200:
                logger.error(f"Ошибка отправки в Telegram: {response.text}")
            else:
                logger.info(f"Уведомление отправлено в чат {chat_id}")
                
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления в Telegram: {e}")
