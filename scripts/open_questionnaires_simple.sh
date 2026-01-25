#!/bin/bash
# Простой скрипт для открытия анкет через docker exec

cd "$(dirname "$0")/.." || exit 1

echo "🔓 Открываю анкеты на всех факультетах..."

docker compose -f docker-compose.prod.yml exec backend python -c "
import asyncio
from db.engine import async_session_maker
from db.models import Faculty, StageType, StageStatus
from datetime import datetime
from sqlalchemy import select

async def open_questionnaires():
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
        
        if not faculties:
            print('❌ Факультеты не найдены!')
            return
        
        for faculty in faculties:
            faculty.current_stage = StageType.QUESTIONNAIRE
            faculty.stage_status = StageStatus.OPEN
            faculty.stage_opened_at = datetime.now()
            print(f'✅ Открыта анкета для: {faculty.name}')
        
        await db.commit()
        print(f'\n🎉 Всего открыто анкет: {len(faculties)}')

asyncio.run(open_questionnaires())
"

echo ""
echo "✅ Готово!"
