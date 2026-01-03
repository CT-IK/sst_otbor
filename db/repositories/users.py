from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> Optional[User]:
        q = select(User).where(User.id == user_id)
        res = await self.db.execute(q)
        return res.scalars().first()

    async def get_by_telegram(self, telegram_id: int) -> Optional[User]:
        q = select(User).where(User.telegram_id == telegram_id)
        res = await self.db.execute(q)
        return res.scalars().first()

    async def create(self, **kwargs) -> User:
        user = User(**kwargs)
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def update(self, user: User, **kwargs) -> User:
        for k, v in kwargs.items():
            setattr(user, k, v)
        await self.db.commit()
        await self.db.refresh(user)
        return user
