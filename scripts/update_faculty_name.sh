#!/bin/bash
# Скрипт для изменения названия факультета через Docker

cd ~/ct/sst_otbor || cd "$(dirname "$0")/.."

if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Использование: $0 <faculty_id> <новое_название>"
    echo ""
    echo "Пример:"
    echo "  $0 1 'Финансовый факультет'"
    echo ""
    echo "Сначала посмотрите список факультетов:"
    echo "  $0 list"
    exit 1
fi

if [ "$1" = "list" ]; then
    echo "Список факультетов:"
    docker compose -f docker-compose.prod.yml exec -T backend python -c "
import asyncio
from db.session import async_session_maker
from db.models import Faculty
from sqlalchemy import select

async def list_faculties():
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
        print('ID | Название')
        print('---|' + '-' * 50)
        for f in faculties:
            print(f'{f.id:2} | {f.name}')

asyncio.run(list_faculties())
"
    exit 0
fi

FACULTY_ID=$1
NEW_NAME=$2

echo "Изменение названия факультета ID=$FACULTY_ID на '$NEW_NAME'..."

docker compose -f docker-compose.prod.yml exec -T backend python -c "
import asyncio
from db.session import async_session_maker
from db.models import Faculty
from sqlalchemy import select

async def update_faculty():
    async with async_session_maker() as db:
        # Получаем факультет
        result = await db.execute(select(Faculty).where(Faculty.id == $FACULTY_ID))
        faculty = result.scalars().first()
        
        if not faculty:
            print(f'❌ Факультет с ID=$FACULTY_ID не найден!')
            return
        
        old_name = faculty.name
        faculty.name = '$NEW_NAME'
        await db.commit()
        
        print(f'✅ Название изменено:')
        print(f'   Было: {old_name}')
        print(f'   Стало: {faculty.name}')

asyncio.run(update_faculty())
"
