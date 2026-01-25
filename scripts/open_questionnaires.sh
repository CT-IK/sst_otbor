#!/bin/bash
# Скрипт для открытия анкет на всех факультетах

set -e

cd "$(dirname "$0")/.." || exit 1

echo "🔓 Открываю анкеты на всех факультетах..."

# Получаем параметры подключения из .env
if [ -f .env ]; then
    source .env
else
    echo "❌ Файл .env не найден!"
    exit 1
fi

# Парсим DB_URL для получения параметров подключения
# Формат: postgresql+asyncpg://user:password@host:port/dbname
if [[ $DB_URL =~ postgresql.*://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+) ]]; then
    DB_USER="${BASH_REMATCH[1]}"
    DB_PASS="${BASH_REMATCH[2]}"
    DB_HOST="${BASH_REMATCH[3]}"
    DB_PORT="${BASH_REMATCH[4]}"
    DB_NAME="${BASH_REMATCH[5]}"
else
    echo "❌ Не удалось распарсить DB_URL из .env"
    echo "   Используйте формат: postgresql+asyncpg://user:password@host:port/dbname"
    exit 1
fi

# SQL запрос для открытия анкет
SQL="
UPDATE faculty 
SET 
    current_stage = 'questionnaire',
    stage_status = 'open',
    stage_opened_at = NOW()
WHERE id IN (SELECT id FROM faculty);
"

# Выполняем через psql в контейнере backend (если pgbouncer доступен)
# Или напрямую через psql на хосте
if command -v psql &> /dev/null; then
    # Используем psql напрямую
    echo "📊 Подключение к БД: $DB_HOST:$DB_PORT/$DB_NAME"
    PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "$SQL"
elif docker compose -f docker-compose.prod.yml ps backend | grep -q "Up"; then
    # Используем psql через docker exec (если psql установлен в контейнере)
    echo "📊 Подключение через docker контейнер..."
    docker compose -f docker-compose.prod.yml exec -T backend python -c "
import asyncio
from db.engine import async_session_maker
from db.models import Faculty, StageType, StageStatus
from datetime import datetime
from sqlalchemy import select

async def open_questionnaires():
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
        
        for faculty in faculties:
            faculty.current_stage = StageType.QUESTIONNAIRE
            faculty.stage_status = StageStatus.OPEN
            faculty.stage_opened_at = datetime.now()
            print(f'✅ Открыта анкета для: {faculty.name}')
        
        await db.commit()
        print(f'\n🎉 Всего открыто анкет: {len(faculties)}')

asyncio.run(open_questionnaires())
"
else
    echo "❌ Не найден psql и контейнер backend не запущен"
    exit 1
fi

echo ""
echo "✅ Готово! Анкеты открыты на всех факультетах."
