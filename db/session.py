from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import async_session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Yields an async DB session and ensures it's closed."""
    async with async_session_maker() as session:
        yield session
