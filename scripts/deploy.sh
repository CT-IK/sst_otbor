#!/bin/bash
# Скрипт для деплоя/перезапуска проекта

set -e

echo "🚀 Деплой SST Big Otbor"
echo "========================"

cd ~/ct/sst_otbor

echo "📦 Останавливаю контейнеры..."
docker-compose -f docker-compose.prod.yml down

echo "🔨 Собираю образы..."
docker-compose -f docker-compose.prod.yml build

echo "🚀 Запускаю контейнеры..."
docker-compose -f docker-compose.prod.yml up -d

echo "⏳ Жду запуска БД..."
sleep 5

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

echo ""
echo "📋 Статус контейнеров:"
docker-compose -f docker-compose.prod.yml ps

echo ""
echo "✅ Готово! Проверь:"
echo "   - Сайт: https://putevod-ik.ru"
echo "   - Бот: напиши /start"
echo ""
echo "📝 Логи: docker-compose -f docker-compose.prod.yml logs -f"
