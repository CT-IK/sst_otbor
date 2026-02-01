#!/usr/bin/env python3
"""Скрипт для проверки корректности миграции interviewers"""
import asyncio
from sqlalchemy import text, select, func
from db.engine import engine
from db.models import Interviewer, Administrator, InterviewerSchedule, InterviewInterviewer

async def verify_migration():
    """Проверка корректности миграции"""
    print("🔍 Проверка миграции interviewers...\n")
    
    async with engine.begin() as conn:
        # 1. Проверка существования таблицы interviewers
        print("1️⃣  Проверка таблицы interviewers...")
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'interviewers'
            )
        """))
        if result.scalar():
            print("   ✅ Таблица interviewers существует")
        else:
            print("   ❌ Таблица interviewers не найдена!")
            return
        
        # 2. Проверка количества записей в interviewers
        print("\n2️⃣  Проверка данных в interviewers...")
        result = await conn.execute(text("SELECT COUNT(*) FROM interviewers"))
        interviewers_count = result.scalar()
        print(f"   📊 Всего проводящих: {interviewers_count}")
        
        result = await conn.execute(text("SELECT COUNT(*) FROM interviewers WHERE is_active = true"))
        active_count = result.scalar()
        print(f"   📊 Активных проводящих: {active_count}")
        
        # 3. Проверка миграции из administrators
        print("\n3️⃣  Проверка миграции из administrators...")
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM administrators 
            WHERE is_active = true AND (role = 'reviewer' OR role = 'head_admin')
        """))
        admins_count = result.scalar()
        print(f"   📊 Администраторов (reviewer + head_admin): {admins_count}")
        
        if interviewers_count >= admins_count:
            print("   ✅ Данные мигрированы корректно")
        else:
            print(f"   ⚠️  Возможно, не все данные мигрированы (ожидалось {admins_count}, получено {interviewers_count})")
        
        # 4. Проверка связей в interviewer_schedule
        print("\n4️⃣  Проверка связей в interviewer_schedule...")
        result = await conn.execute(text("""
            SELECT COUNT(*) FROM interviewer_schedule 
            WHERE interviewer_id IS NOT NULL
        """))
        schedule_count = result.scalar()
        print(f"   📊 Записей в расписании: {schedule_count}")
        
        # Проверка на дубликаты
        result = await conn.execute(text("""
            SELECT interviewer_id, date, time_slot, COUNT(*) as cnt
            FROM interviewer_schedule
            WHERE interviewer_id IS NOT NULL
            GROUP BY interviewer_id, date, time_slot
            HAVING COUNT(*) > 1
        """))
        duplicates = result.fetchall()
        if duplicates:
            print(f"   ❌ Найдено дубликатов: {len(duplicates)}")
            for dup in duplicates[:5]:  # Показываем первые 5
                print(f"      - interviewer_id={dup[0]}, date={dup[1]}, time={dup[2]}, count={dup[3]}")
        else:
            print("   ✅ Дубликатов не найдено")
        
        # 5. Проверка связей в interview_interviewers
        print("\n5️⃣  Проверка связей в interview_interviewers...")
        result = await conn.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'interview_interviewers'
            )
        """))
        if result.scalar():
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM interview_interviewers 
                WHERE interviewer_id IS NOT NULL
            """))
            assignments_count = result.scalar()
            print(f"   📊 Назначений проводящих: {assignments_count}")
            
            # Проверка на дубликаты
            result = await conn.execute(text("""
                SELECT interview_id, interviewer_id, COUNT(*) as cnt
                FROM interview_interviewers
                GROUP BY interview_id, interviewer_id
                HAVING COUNT(*) > 1
            """))
            duplicates = result.fetchall()
            if duplicates:
                print(f"   ❌ Найдено дубликатов: {len(duplicates)}")
            else:
                print("   ✅ Дубликатов не найдено")
        else:
            print("   ℹ️  Таблица interview_interviewers не существует (это нормально, если нет назначений)")
        
        # 6. Проверка foreign key constraints
        print("\n6️⃣  Проверка foreign key constraints...")
        result = await conn.execute(text("""
            SELECT constraint_name 
            FROM information_schema.table_constraints 
            WHERE table_name = 'interviewer_schedule' 
            AND constraint_type = 'FOREIGN KEY'
            AND constraint_name LIKE '%interviewer%'
        """))
        fk_schedule = result.fetchall()
        if fk_schedule:
            print(f"   ✅ Foreign key для interviewer_schedule: {fk_schedule[0][0]}")
        else:
            print("   ⚠️  Foreign key для interviewer_schedule не найден")
        
        result = await conn.execute(text("""
            SELECT constraint_name 
            FROM information_schema.table_constraints 
            WHERE table_name = 'interview_interviewers' 
            AND constraint_type = 'FOREIGN KEY'
            AND constraint_name LIKE '%interviewer%'
        """))
        fk_assignments = result.fetchall()
        if fk_assignments:
            print(f"   ✅ Foreign key для interview_interviewers: {fk_assignments[0][0]}")
        else:
            print("   ℹ️  Foreign key для interview_interviewers не найден (возможно, таблица не существует)")
        
        # 7. Примеры данных
        print("\n7️⃣  Примеры данных...")
        result = await conn.execute(text("""
            SELECT i.id, i.telegram_id, i.name, i.username, f.name as faculty_name
            FROM interviewers i
            JOIN faculty f ON f.id = i.faculty_id
            WHERE i.is_active = true
            LIMIT 5
        """))
        examples = result.fetchall()
        if examples:
            print("   Примеры проводящих:")
            for ex in examples:
                name = ex[2] or ex[3] or f"ID {ex[1]}"
                print(f"      - {name} (ID: {ex[0]}, Факультет: {ex[4]})")
        else:
            print("   ℹ️  Нет активных проводящих")
        
        print("\n✅ Проверка завершена!")

if __name__ == "__main__":
    asyncio.run(verify_migration())
