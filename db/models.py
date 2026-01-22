from datetime import datetime, date, time
from enum import Enum

from sqlalchemy import (
    Integer,
    String,
    ForeignKey,
    Boolean,
    JSON,
    DateTime,
    Date,
    Time,
    Text,
    BigInteger,
    Enum as SQLEnum,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.engine import Base


class StageType(str, Enum):
    """Типы этапов отбора (фиксированные для всех факультетов)"""
    QUESTIONNAIRE = "questionnaire"  # Анкета
    HOME_VIDEO = "home_video"        # Домашнее видео
    INTERVIEW = "interview"          # Собеседование


class StageStatus(str, Enum):
    """Статусы этапа"""
    NOT_STARTED = "not_started"  # Ещё не начался
    OPEN = "open"                # Открыт для подачи
    CLOSED = "closed"            # Приём закрыт, идёт проверка
    COMPLETED = "completed"      # Этап завершён


class User(Base):
    """Пользователь системы отбора (студент)"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    first_name: Mapped[str] = mapped_column(String(50))
    second_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    surname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    course_of_study: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id", ondelete="RESTRICT"), nullable=True)
    is_student: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # relations
    faculty = relationship("Faculty", back_populates="users", lazy="joined")
    questionnaires = relationship("Questionnaire", back_populates="user", cascade="all, delete-orphan")
    home_videos = relationship("HomeVideo", back_populates="user", cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="user", cascade="all, delete-orphan")
    progress = relationship("UserProgress", back_populates="user", cascade="all, delete-orphan")
    approvals = relationship("ApprovalQueue", back_populates="user", cascade="all, delete-orphan")


class AdminRole(str, Enum):
    """Роли администраторов"""
    HEAD_ADMIN = "head_admin"      # Главный админ факультета (назначает суперадмин)
    REVIEWER = "reviewer"          # Проверяющий (назначает главный админ)


class Administrator(Base):
    """
    Администратор факультета.
    
    Роли:
    - head_admin: Главный админ факультета (назначается суперадмином)
      Может: добавлять проверяющих, делать рассылки, редактировать вопросы, всё остальное
    - reviewer: Проверяющий (назначается главным админом)
      Может: смотреть ответы, статистику, проводить собесы
    """
    __tablename__ = "administrators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)  # @username в Telegram
    full_name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # Имя из Telegram
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)  # Для веб-интерфейса
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Для веб-интерфейса
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id", ondelete="RESTRICT"), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="reviewer")  # head_admin, reviewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # Кто добавил (telegram_id)

    faculty = relationship("Faculty", back_populates="administrators", lazy="joined")
    slot_availability = relationship("SlotAvailability", back_populates="interviewer", cascade="all, delete-orphan")


class Faculty(Base):
    """Факультет с собственными этапами отбора и администраторами"""
    __tablename__ = "faculty"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Управление текущим этапом отбора
    current_stage: Mapped[StageType | None] = mapped_column(
        SQLEnum(StageType), 
        default=None, 
        nullable=True
    )  # None = отбор не начался
    stage_status: Mapped[StageStatus] = mapped_column(
        SQLEnum(StageStatus), 
        default=StageStatus.NOT_STARTED
    )
    stage_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Настройки для этапа домашнего видео
    video_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # ID группового чата для видео
    video_submission_open: Mapped[bool] = mapped_column(Boolean, default=False)  # Открыт ли приём видео
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="faculty")
    administrators = relationship("Administrator", back_populates="faculty")
    templates = relationship("StageTemplate", back_populates="faculty", cascade="all, delete-orphan")


class StageTemplate(Base):
    """
    Шаблон вопросов для этапа, созданный админом факультета.
    
    Структура questions (JSON):
    [
        {
            "id": "q1",
            "text": "Почему хотите в студсовет?",
            "type": "text",  # text | choice | multiple_choice | number
            "required": true,
            "order": 1,
            "options": null,  # для choice/multiple_choice: ["вариант1", "вариант2"]
            "max_length": 500  # для text
        },
        ...
    ]
    """
    __tablename__ = "stage_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    stage_type: Mapped[StageType] = mapped_column(SQLEnum(StageType))  # К какому этапу относится
    version: Mapped[int] = mapped_column(Integer, default=1)
    questions: Mapped[dict] = mapped_column(JSON)  # JSONB in Postgres
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    faculty = relationship("Faculty", back_populates="templates")
    creator = relationship("Administrator", lazy="joined")


class Questionnaire(Base):
    """
    Финальная анкета, отправленная пользователем.
    Черновики хранятся в Redis, здесь только отправленные.
    """
    __tablename__ = "questionnaires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("stage_templates.id", ondelete="SET NULL"), nullable=True)
    answers: Mapped[dict] = mapped_column(JSON)  # Финальные ответы
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="questionnaires")
    faculty = relationship("Faculty")
    template = relationship("StageTemplate")


class HomeVideo(Base):
    """Домашнее видео, загруженное пользователем"""
    __tablename__ = "home_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    video_url: Mapped[str] = mapped_column(String(512))
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Telegram file_id
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="home_videos")
    faculty = relationship("Faculty")


class InterviewSlot(Base):
    """Слоты для записи на собеседование"""
    __tablename__ = "interview_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    datetime_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    datetime_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_participants: Mapped[int] = mapped_column(Integer, default=1)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Аудитория/ссылка
    created_by: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # Активен ли слот (можно деактивировать)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    faculty = relationship("Faculty")
    creator = relationship("Administrator")
    interviews = relationship("Interview", back_populates="slot")
    available_interviewers = relationship("SlotAvailability", back_populates="slot", cascade="all, delete-orphan")


class InterviewStatus(str, Enum):
    """Статусы собеседования"""
    SCHEDULED = "scheduled"      # Назначено
    COMPLETED = "completed"      # Проведено
    NO_SHOW = "no_show"          # Не пришёл
    CANCELLED = "cancelled"      # Отменено


class Interview(Base):
    """Запись на собеседование и результаты"""
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    slot_id: Mapped[int | None] = mapped_column(ForeignKey("interview_slots.id", ondelete="SET NULL"), nullable=True)
    interviewer_id: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"), nullable=True)  # Назначенный проверяющий
    status: Mapped[InterviewStatus] = mapped_column(
        SQLEnum(InterviewStatus), 
        default=InterviewStatus.SCHEDULED
    )
    interviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Оценка 1-10
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="interviews")
    faculty = relationship("Faculty")
    slot = relationship("InterviewSlot", back_populates="interviews")
    time_slot_id: Mapped[int | None] = mapped_column(ForeignKey("time_slots.id", ondelete="SET NULL"), nullable=True)  # Новый временной слот
    time_slot = relationship("TimeSlot", back_populates="interviews", foreign_keys=[time_slot_id])
    interviewer = relationship("Administrator", foreign_keys=[interviewer_id])


class SlotAvailability(Base):
    """
    Доступность проверяющих для проведения собеседований в слотах.
    Связь многие-ко-многим между InterviewSlot и Administrator.
    
    Reviewer'ы отмечают, в каких слотах они готовы проводить собеседования.
    Head Admin создает слоты, Reviewer'ы отмечают свою доступность.
    """
    __tablename__ = "slot_availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_id: Mapped[int] = mapped_column(ForeignKey("interview_slots.id", ondelete="CASCADE"))
    interviewer_id: Mapped[int] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    available: Mapped[bool] = mapped_column(Boolean, default=True)  # True = свободен, False = занят
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    slot = relationship("InterviewSlot", back_populates="available_interviewers")
    interviewer = relationship("Administrator", back_populates="slot_availability")

    __table_args__ = (
        UniqueConstraint('slot_id', 'interviewer_id', name='uq_slot_interviewer'),
    )


class InterviewDay(Base):
    """
    Дни, когда проводятся собеседования.
    Head Admin создает дни собеседований.
    """
    __tablename__ = "interview_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)  # Дата собеседований
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Общая локация для дня
    created_by: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    faculty = relationship("Faculty")
    creator = relationship("Administrator")
    time_slots = relationship("TimeSlot", back_populates="day", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('faculty_id', 'date', name='uq_faculty_date'),
    )


class TimeSlot(Base):
    """
    Временные слоты в день собеседований (10:00, 11:00, ..., 22:00).
    Head Admin устанавливает количество доступных мест для каждого временного слота.
    """
    __tablename__ = "time_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_id: Mapped[int] = mapped_column(ForeignKey("interview_days.id", ondelete="CASCADE"))
    time: Mapped[Time] = mapped_column(Time)  # Время начала слота (10:00, 11:00, и т.д.)
    max_participants: Mapped[int] = mapped_column(Integer, default=0)  # Количество мест (0-10, устанавливает Head Admin)
    current_participants: Mapped[int] = mapped_column(Integer, default=0)  # Текущее количество записей
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    day = relationship("InterviewDay", back_populates="time_slots")
    availabilities = relationship("TimeSlotAvailability", back_populates="time_slot", cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="time_slot")

    __table_args__ = (
        UniqueConstraint('day_id', 'time', name='uq_day_time'),
    )


class TimeSlotAvailability(Base):
    """
    Доступность проверяющих в временных слотах.
    Reviewer'ы отмечают галочками, в какие временные слоты они могут проводить собеседования.
    """
    __tablename__ = "time_slot_availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time_slot_id: Mapped[int] = mapped_column(ForeignKey("time_slots.id", ondelete="CASCADE"))
    interviewer_id: Mapped[int] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    time_slot = relationship("TimeSlot", back_populates="availabilities")
    interviewer = relationship("Administrator", back_populates="time_slot_availability")

    __table_args__ = (
        UniqueConstraint('time_slot_id', 'interviewer_id', name='uq_time_slot_interviewer'),
    )


class SubmissionStatus(str, Enum):
    """Статусы заявки пользователя"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"  # Начал заполнять
    SUBMITTED = "submitted"      # Отправил на проверку
    APPROVED = "approved"        # Одобрено
    REJECTED = "rejected"        # Отклонено


class UserProgress(Base):
    """Прогресс пользователя по этапам отбора"""
    __tablename__ = "user_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    stage_type: Mapped[StageType] = mapped_column(SQLEnum(StageType))
    status: Mapped[SubmissionStatus] = mapped_column(
        SQLEnum(SubmissionStatus), 
        default=SubmissionStatus.NOT_STARTED
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", back_populates="progress")
    faculty = relationship("Faculty")


class ApprovalStatus(str, Enum):
    """Статусы проверки"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalQueue(Base):
    """Очередь ответов на проверку админом факультета"""
    __tablename__ = "approval_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    stage_type: Mapped[StageType] = mapped_column(SQLEnum(StageType))
    answers: Mapped[dict] = mapped_column(JSON)  # Ответы на момент отправки
    status: Mapped[ApprovalStatus] = mapped_column(
        SQLEnum(ApprovalStatus), 
        default=ApprovalStatus.PENDING
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"), nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # Комментарий проверяющего

    user = relationship("User", back_populates="approvals")
    faculty = relationship("Faculty")
    reviewer = relationship("Administrator", lazy="joined")


class AdminActionLog(Base):
    """
    Лог действий администраторов для аналитики.
    Записываем все важные действия: смена этапа, одобрение/отклонение заявок и т.д.
    """
    __tablename__ = "admin_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(50))  # stage_opened, stage_closed, submission_approved, etc.
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # user, stage, template
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Дополнительные данные
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    admin = relationship("Administrator", lazy="joined")
    faculty = relationship("Faculty")


