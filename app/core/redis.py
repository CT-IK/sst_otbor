import redis.asyncio as redis
from typing import AsyncGenerator

from config import settings


class RedisClient:
    """Асинхронный клиент Redis"""
    
    def __init__(self):
        self._pool: redis.ConnectionPool | None = None
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Создать пул соединений"""
        self._pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
        )
        self._client = redis.Redis(connection_pool=self._pool)

    async def disconnect(self) -> None:
        """Закрыть соединения"""
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()

    @property
    def client(self) -> redis.Redis:
        if not self._client:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client


# Глобальный экземпляр
redis_client = RedisClient()


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """Dependency для получения Redis клиента в роутах"""
    yield redis_client.client

