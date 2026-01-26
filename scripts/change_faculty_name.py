#!/usr/bin/env python3
"""
Скрипт для изменения названия факультета через Docker.
Использование:
  docker compose -f docker-compose.prod.yml exec backend python scripts/change_faculty_name.py list
  docker compose -f docker-compose.prod.yml exec backend python scripts/change_faculty_name.py <id> "Новое название"
"""
import sys
import os
import asyncio

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import async_session_maker
from db.models import Faculty
from sqlalchemy import select


async def list_faculties():
    """Показать список всех факультетов"""
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty).order_by(Faculty.id))
        faculties = result.scalars().all()
        
        if not faculties:
            print("Факультеты не найдены")
            return
        
        print("\n📋 Список факультетов:\n")
        print("ID | Название")
        print("---|" + "-" * 50)
        for f in faculties:
            print(f"{f.id:2} | {f.name}")
        print()


async def update_faculty(faculty_id: int, new_name: str):
    """Изменить название факультета"""
    async with async_session_maker() as db:
        # Получаем факультет
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
        
        if not faculty:
            print(f"❌ Факультет с ID={faculty_id} не найден!")
            return False
        
        old_name = faculty.name
        faculty.name = new_name
        await db.commit()
        
        print(f"✅ Название успешно изменено!")
        print(f"   ID: {faculty.id}")
        print(f"   Было: {old_name}")
        print(f"   Стало: {faculty.name}")
        return True


async def main():
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python scripts/change_faculty_name.py list")
        print("  python scripts/change_faculty_name.py <id> \"Новое название\"")
        print("\nПример:")
        print("  python scripts/change_faculty_name.py 1 \"Финансовый факультет\"")
        sys.exit(1)
    
    if sys.argv[1] == "list":
        await list_faculties()
    else:
        try:
            faculty_id = int(sys.argv[1])
            if len(sys.argv) < 3:
                print("❌ Укажите новое название факультета в кавычках")
                print("Пример: python scripts/change_faculty_name.py 1 \"Новое название\"")
                sys.exit(1)
            
            new_name = sys.argv[2]
            await update_faculty(faculty_id, new_name)
        except ValueError:
            print(f"❌ Неверный ID факультета: {sys.argv[1]}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
