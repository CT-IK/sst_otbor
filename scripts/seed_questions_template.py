#!/usr/bin/env python3
"""
Скрипт для массового добавления вопросов во все факультеты.

Использование:
    python scripts/seed_questions_template.py

Формат вопросов в questions.json:
[
    {
        "id": "q1",
        "text": "Почему хотите в студсовет?",
        "type": "text",
        "required": true,
        "order": 1,
        "max_length": 500
    },
    {
        "id": "q2",
        "text": "Какой у вас курс?",
        "type": "choice",
        "required": true,
        "order": 2,
        "options": [
            {"value": "1", "label": "1 курс"},
            {"value": "2", "label": "2 курс"},
            {"value": "3", "label": "3 курс"},
            {"value": "4", "label": "4 курс"}
        ]
    },
    {
        "id": "q3",
        "text": "Какие направления вас интересуют?",
        "type": "multiple_choice",
        "required": false,
        "order": 3,
        "options": [
            {"value": "opt_1", "label": "Организация мероприятий"},
            {"value": "opt_2", "label": "Работа со студентами"},
            {"value": "opt_3", "label": "Административная работа"}
        ]
    },
    {
        "id": "q4",
        "text": "Оцените свой опыт (1-10)",
        "type": "number",
        "required": true,
        "order": 4,
        "min_value": 1,
        "max_value": 10
    }
]
"""
import asyncio
import json
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import async_session_maker
from db.models import Faculty, StageTemplate, StageType


async def load_questions_from_file(file_path: str) -> list[dict]:
    """Загрузить вопросы из JSON файла"""
    with open(file_path, 'r', encoding='utf-8') as f:
        questions = json.load(f)
    
    # Валидация структуры
    for i, q in enumerate(questions):
        if not q.get('id'):
            raise ValueError(f"Вопрос #{i+1} не имеет 'id'")
        if not q.get('text'):
            raise ValueError(f"Вопрос #{i+1} (id={q['id']}) не имеет 'text'")
        if not q.get('type'):
            raise ValueError(f"Вопрос #{i+1} (id={q['id']}) не имеет 'type'")
        
        # Устанавливаем значения по умолчанию
        q.setdefault('required', True)
        q.setdefault('order', i + 1)
    
    return questions


async def seed_questions_to_all_faculties(
    questions: list[dict],
    stage_type: StageType = StageType.QUESTIONNAIRE,
    faculty_ids: list[int] | None = None
):
    """
    Добавить вопросы во все факультеты (или указанные).
    
    Args:
        questions: Список вопросов
        stage_type: Тип этапа (по умолчанию QUESTIONNAIRE)
        faculty_ids: Список ID факультетов (None = все факультеты)
    """
    async with async_session_maker() as db:
        # Получаем список факультетов
        if faculty_ids:
            query = select(Faculty).where(Faculty.id.in_(faculty_ids))
        else:
            query = select(Faculty)
        
        result = await db.execute(query)
        faculties = result.scalars().all()
        
        if not faculties:
            print("❌ Факультеты не найдены!")
            return
        
        print(f"📋 Найдено факультетов: {len(faculties)}")
        print(f"📝 Вопросов для добавления: {len(questions)}")
        print()
        
        created_count = 0
        updated_count = 0
        
        for faculty in faculties:
            # Проверяем, есть ли уже активный шаблон для этого этапа
            result = await db.execute(
                select(StageTemplate).where(
                    StageTemplate.faculty_id == faculty.id,
                    StageTemplate.stage_type == stage_type,
                    StageTemplate.is_active == True
                )
            )
            existing_template = result.scalars().first()
            
            if existing_template:
                # Деактивируем старый шаблон
                existing_template.is_active = False
                # Создаём новый с увеличенной версией
                new_version = existing_template.version + 1
                print(f"  🔄 Факультет '{faculty.name}': обновление шаблона (v{existing_template.version} -> v{new_version})")
            else:
                new_version = 1
                print(f"  ✨ Факультет '{faculty.name}': создание нового шаблона")
            
            # Создаём новый шаблон
            new_template = StageTemplate(
                faculty_id=faculty.id,
                stage_type=stage_type,
                version=new_version,
                questions=questions,
                is_active=True,
                created_by=None  # Системное добавление
            )
            db.add(new_template)
            
            if existing_template:
                updated_count += 1
            else:
                created_count += 1
        
        await db.commit()
        
        print()
        print(f"✅ Готово!")
        print(f"   Создано новых шаблонов: {created_count}")
        print(f"   Обновлено шаблонов: {updated_count}")
        print(f"   Всего обработано: {len(faculties)}")


async def main():
    """Главная функция"""
    # Путь к файлу с вопросами
    questions_file = Path(__file__).parent.parent / "questions.json"
    
    if not questions_file.exists():
        print(f"❌ Файл с вопросами не найден: {questions_file}")
        print()
        print("Создайте файл questions.json в корне проекта со структурой:")
        print(__doc__)
        sys.exit(1)
    
    # Загружаем вопросы
    print(f"📂 Загрузка вопросов из {questions_file}...")
    try:
        questions = await load_questions_from_file(str(questions_file))
    except Exception as e:
        print(f"❌ Ошибка при загрузке вопросов: {e}")
        sys.exit(1)
    
    print(f"✅ Загружено вопросов: {len(questions)}")
    print()
    
    # Показываем вопросы для подтверждения
    print("📋 Список вопросов:")
    for q in questions:
        print(f"  {q['order']}. [{q['id']}] {q['text']} ({q['type']})")
    print()
    
    # Подтверждение
    response = input("Добавить эти вопросы во ВСЕ факультеты? (yes/no): ")
    if response.lower() not in ['yes', 'y', 'да', 'д']:
        print("❌ Отменено")
        sys.exit(0)
    
    # Добавляем вопросы
    await seed_questions_to_all_faculties(questions)
    
    print()
    print("🎉 Вопросы успешно добавлены!")


if __name__ == "__main__":
    asyncio.run(main())
