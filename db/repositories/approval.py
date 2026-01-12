from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import ApprovalQueue


class ApprovalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def get_by_id(self, approval_id: int) -> Optional[ApprovalQueue]:
        q = select(ApprovalQueue).where(ApprovalQueue.id == approval_id) 
        res = await self.db.execute(q)
        return res.scalars().first()
    

    async def list_pending_by_faculty(self, faculty_id: int, limit: int = 50, offset: int = 0) -> List[ApprovalQueue]:
        q = (select(ApprovalQueue)
        .join(ApprovalQueue.user)
        .where(ApprovalQueue.status == "pending", ApprovalQueue.user.has(faculty_id=faculty_id))
        .limit(limit).offset(offset)
        )
        res = await self.db.execute(q)
        return res.scalars().all()
    
   