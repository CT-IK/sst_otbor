"""
Сервис для работы с черновиками анкет в Redis.

Ключи в Redis:
- draft:questionnaire:{telegram_id}:{faculty_id} — черновик анкеты пользователя
"""
import json
from datetime import datetime

import redis.asyncio as redis

from config import settings


class DraftService:
    """Сервис для работы с черновиками в Redis"""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.ttl = settings.redis_draft_ttl

    def _make_key(self, telegram_id: int, faculty_id: int) -> str:
        """Формирует ключ для черновика"""
        return f"draft:questionnaire:{telegram_id}:{faculty_id}"

    async def save_draft(
        self,
        telegram_id: int,
        faculty_id: int,
        template_id: int,
        answers: dict,
    ) -> None:
        """
        Сохранить черновик анкеты.
        
        Args:
            telegram_id: Telegram ID пользователя
            faculty_id: ID факультета
            template_id: ID шаблона вопросов
            answers: Словарь с ответами {question_id: answer}
        """
        key = self._make_key(telegram_id, faculty_id)
        data = {
            "template_id": template_id,
            "answers": answers,
            "updated_at": datetime.utcnow().isoformat(),
        }
        await self.redis.set(key, json.dumps(data), ex=self.ttl)

    async def get_draft(
        self,
        telegram_id: int,
        faculty_id: int,
    ) -> dict | None:
        """
        Получить черновик анкеты.
        
        Returns:
            Словарь с template_id, answers, updated_at или None если нет черновика
        """
        key = self._make_key(telegram_id, faculty_id)
        data = await self.redis.get(key)
        if data:
            return json.loads(data)
        return None

    async def delete_draft(
        self,
        telegram_id: int,
        faculty_id: int,
    ) -> bool:
        """
        Удалить черновик (после успешной отправки анкеты).
        
        Returns:
            True если удалён, False если не существовал
        """
        key = self._make_key(telegram_id, faculty_id)
        result = await self.redis.delete(key)
        return result > 0

    async def get_draft_ttl(
        self,
        telegram_id: int,
        faculty_id: int,
    ) -> int:
        """
        Получить оставшееся время жизни черновика в секундах.
        
        Returns:
            Секунды до истечения или -2 если ключа нет
        """
        key = self._make_key(telegram_id, faculty_id)
        return await self.redis.ttl(key)

