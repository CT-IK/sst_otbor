#!/bin/bash
# Прямое выполнение очистки через Python в контейнере

echo "🧹 Очистка частично примененной миграции..."

docker exec sst_otbor python3 -c "
import asyncio
from sqlalchemy import text
from db.engine import engine

async def cleanup():
    async with engine.begin() as conn:
        # Удаляем таблицу interviewers если существует
        try:
            await conn.execute(text('DROP TABLE IF EXISTS interviewers CASCADE'))
            print('✅ Таблица interviewers удалена (если существовала)')
        except Exception as e:
            print(f'⚠️  Ошибка при удалении interviewers: {e}')
        
        # Удаляем временные колонки если существуют
        try:
            await conn.execute(text('ALTER TABLE interviewer_schedule DROP COLUMN IF EXISTS old_interviewer_id'))
            print('✅ Временная колонка old_interviewer_id удалена из interviewer_schedule')
        except Exception as e:
            print(f'⚠️  Ошибка при удалении колонки из interviewer_schedule: {e}')
        
        try:
            await conn.execute(text('ALTER TABLE interview_interviewers DROP COLUMN IF EXISTS old_interviewer_id'))
            print('✅ Временная колонка old_interviewer_id удалена из interview_interviewers')
        except Exception as e:
            print(f'⚠️  Ошибка при удалении колонки из interview_interviewers: {e}')
        
        # Удаляем запись о миграции из alembic_version если нужно
        try:
            result = await conn.execute(text(\"DELETE FROM alembic_version WHERE version_num = 'bdb260946a10'\"))
            if result.rowcount > 0:
                print('✅ Запись о миграции bdb260946a10 удалена из alembic_version')
            else:
                print('ℹ️  Запись о миграции bdb260946a10 не найдена в alembic_version')
        except Exception as e:
            print(f'⚠️  Ошибка при удалении записи миграции: {e}')
        
        print('\n✅ Очистка завершена!')

asyncio.run(cleanup())
"

echo ""
echo "📋 Теперь применяем миграцию заново..."
docker exec sst_otbor alembic upgrade head

echo ""
echo "✅ Готово! Проверьте статус:"
docker exec sst_otbor alembic current
