from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine, AsyncSession
from config import settings



engine = create_async_engine(url=settings.database_url)
async_session_maker = async_sessionmaker(bind=engine, class_=AsyncSession)


class Base(DeclarativeBase):
    __abstract__ = True




