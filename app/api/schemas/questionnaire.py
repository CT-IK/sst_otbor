from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# === Вопросы в шаблоне ===

class QuestionOption(BaseModel):
    """Вариант ответа для вопросов с выбором"""
    value: str
    label: str


class Question(BaseModel):
    """Вопрос из шаблона"""
    id: str
    text: str
    type: str = Field(description="text | choice | multiple_choice | number")
    required: bool = True
    order: int
    options: list[QuestionOption] | None = None
    max_length: int | None = None
    min_value: int | None = None
    max_value: int | None = None


# === Шаблон ===

class TemplateResponse(BaseModel):
    """Ответ с шаблоном вопросов"""
    template_id: int
    faculty_id: int
    faculty_name: str
    stage_type: str
    questions: list[Question]
    version: int


# === Черновик ===

class DraftSaveRequest(BaseModel):
    """Запрос на сохранение черновика"""
    template_id: int
    answers: dict[str, Any] = Field(
        description="Ответы в формате {question_id: answer_value}"
    )


class DraftResponse(BaseModel):
    """Ответ с черновиком"""
    template_id: int
    answers: dict[str, Any]
    updated_at: datetime
    ttl_seconds: int = Field(description="Оставшееся время жизни черновика")


class DraftWithTemplateResponse(BaseModel):
    """Черновик вместе с шаблоном (для загрузки формы)"""
    template: TemplateResponse
    draft: DraftResponse | None = None
    stage_status: str = Field(description="Статус этапа факультета")
    can_submit: bool = Field(description="Можно ли отправить анкету")
    already_submitted: bool = Field(default=False, description="Уже отправлял анкету")
    submitted_at: datetime | None = Field(default=None, description="Когда отправил")
    current_stage: str | None = Field(default=None, description="Текущий этап факультета (questionnaire | home_video | interview)")


# === Отправка анкеты ===

class SubmitQuestionnaireRequest(BaseModel):
    """Запрос на отправку анкеты"""
    template_id: int
    answers: dict[str, Any]


class SubmitQuestionnaireResponse(BaseModel):
    """Ответ после отправки анкеты"""
    success: bool
    questionnaire_id: int
    message: str = "Анкета успешно отправлена"


# === Статус пользователя ===

class UserQuestionnaireStatus(BaseModel):
    """Статус анкеты пользователя"""
    faculty_id: int
    faculty_name: str
    stage_status: str  # not_started | open | closed | completed
    user_status: str  # not_started | in_progress | submitted | approved | rejected
    submitted_at: datetime | None = None
    can_edit: bool = Field(description="Может ли редактировать (есть черновик)")
    can_submit: bool = Field(description="Может ли отправить")

