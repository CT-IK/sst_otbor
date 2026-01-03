from typing import AsyncGenerator

from fastapi import Depends

from db.session import get_db


async def get_async_db() -> AsyncGenerator:
    """Dependency wrapper for routes that need an async DB session."""
    async for session in get_db():
        yield session
