from datetime import datetime

from sqlalchemy import (
    Integer,
    String,
    ForeignKey,
    Boolean,
    JSON,
    DateTime,
    Text,
    BigInteger,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.engine import Base


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


class Administrator(Base):
    """Администратор факультета для управления шаблонами и проверки ответов"""
    __tablename__ = "administrators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id", ondelete="RESTRICT"), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="faculty_admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    faculty = relationship("Faculty", back_populates="administrators", lazy="joined")


class Faculty(Base):
    """Факультет с собственными этапами отбора и администраторами"""
    __tablename__ = "faculty"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="faculty")
    administrators = relationship("Administrator", back_populates="faculty")
    stages = relationship("Stage", back_populates="faculty", cascade="all, delete-orphan")


class Stage(Base):
    """Этап отбора (анкета, видео, интервью и т.п.)"""
    __tablename__ = "stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    faculty = relationship("Faculty", back_populates="stages")
    templates = relationship("StageTemplate", back_populates="stage", cascade="all, delete-orphan")
    progress = relationship("UserProgress", back_populates="stage")
    approvals = relationship("ApprovalQueue", back_populates="stage")


class StageTemplate(Base):
    """Шаблон вопросов для этапа, созданный админом факультета"""
    __tablename__ = "stage_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    questions: Mapped[dict] = mapped_column(JSON)  # JSONB in Postgres
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stage = relationship("Stage", back_populates="templates")
    creator = relationship("Administrator", lazy="joined")


class Questionnaire(Base):
    """Анкета, заполненная пользователем (черновик или финальная)"""
    __tablename__ = "questionnaires"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("stage_templates.id", ondelete="SET NULL"), nullable=True)
    answers: Mapped[dict] = mapped_column(JSON, default={})
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(30), default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User", back_populates="questionnaires")
    template = relationship("StageTemplate")


class HomeVideo(Base):
    """Домашнее видео, загруженное пользователем"""
    __tablename__ = "home_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    video_url: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(30), default="in_progress")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="home_videos")


class Interview(Base):
    """Результаты собеседования"""
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="interviews")


class UserProgress(Base):
    """Прогресс пользователя по этапам отбора"""
    __tablename__ = "user_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    answers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="progress")
    stage = relationship("Stage", back_populates="progress")


class ApprovalQueue(Base):
    """Очередь ответов на проверку админом факультета"""
    __tablename__ = "approval_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id", ondelete="CASCADE"))
    answers: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("administrators.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user = relationship("User", back_populates="approvals")
    stage = relationship("Stage", back_populates="approvals")
    reviewer = relationship("Administrator", lazy="joined")






