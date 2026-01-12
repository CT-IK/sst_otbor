#!/bin/bash
# Создание таблиц в БД

cd ~/ct/sst_otbor

echo "📊 Создаю таблицы в БД..."
docker-compose -f docker-compose.prod.yml exec -T backend python -c "
from db.models import Base
from db.engine import engine
import asyncio

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('✅ Таблицы созданы!')

asyncio.run(create_tables())
"
