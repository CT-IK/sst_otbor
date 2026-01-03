from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Questionnaire


class QuestionnaireRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, questionnaire_id: int) -> Optional[Questionnaire]:
        q = select(Questionnaire).where(Questionnaire.id == questionnaire_id)
        res = await self.db.execute(q)
        return res.scalars().first()

    async def create(self, **kwargs) -> Questionnaire:
        qobj = Questionnaire(**kwargs)
        self.db.add(qobj)
        await self.db.commit()
        await self.db.refresh(qobj)
        return qobj

    async def update(self, questionnaire: Questionnaire, **kwargs) -> Questionnaire:
        for k, v in kwargs.items():
            setattr(questionnaire, k, v)
        await self.db.commit()
        await self.db.refresh(questionnaire)
        return questionnaire
