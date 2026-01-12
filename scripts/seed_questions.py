"""
Скрипт для добавления дефолтных вопросов анкеты.
Запуск: python -m scripts.seed_questions
"""
import asyncio
import sys
sys.path.insert(0, '.')

from sqlalchemy import select
from db.engine import async_session_maker
from db.models import Faculty, StageTemplate, StageType, StageStatus


# Дефолтные вопросы анкеты
DEFAULT_QUESTIONS = [
    {
        "id": "full_name",
        "text": "Фамилия, Имя, Отчество",
        "type": "text",
        "required": True,
        "max_length": 200,
        "placeholder": "Иванов Иван Иванович"
    },
    {
        "id": "group",
        "text": "Группа",
        "type": "text",
        "required": True,
        "max_length": 20,
        "placeholder": "ИВТ-101"
    },
    {
        "id": "phone",
        "text": "Номер телефона",
        "type": "text",
        "required": True,
        "max_length": 20,
        "placeholder": "+7 (999) 123-45-67"
    },
    {
        "id": "email",
        "text": "Email",
        "type": "text",
        "required": True,
        "max_length": 100,
        "placeholder": "example@mail.ru"
    },
    {
        "id": "why_studsovet",
        "text": "Почему ты хочешь вступить в Студенческий Совет?",
        "type": "textarea",
        "required": True,
        "max_length": 2000,
        "placeholder": "Расскажи о своей мотивации..."
    },
    {
        "id": "experience",
        "text": "Есть ли у тебя опыт организаторской или общественной деятельности?",
        "type": "textarea",
        "required": True,
        "max_length": 2000,
        "placeholder": "Опиши свой опыт..."
    },
    {
        "id": "skills",
        "text": "Какие навыки ты можешь применить в Студсовете?",
        "type": "textarea",
        "required": True,
        "max_length": 2000,
        "placeholder": "Например: дизайн, SMM, организация мероприятий..."
    },
    {
        "id": "department",
        "text": "В каком департаменте ты хотел бы работать?",
        "type": "select",
        "required": True,
        "options": [
            "Организационный",
            "Медиа и PR",
            "Культурно-массовый",
            "Спортивный",
            "Научный",
            "Социальный",
            "Пока не определился"
        ]
    },
    {
        "id": "time_commitment",
        "text": "Сколько времени в неделю ты готов уделять работе в Студсовете?",
        "type": "select",
        "required": True,
        "options": [
            "5-10 часов",
            "10-15 часов",
            "15-20 часов",
            "Больше 20 часов"
        ]
    },
    {
        "id": "about_yourself",
        "text": "Расскажи немного о себе",
        "type": "textarea",
        "required": False,
        "max_length": 3000,
        "placeholder": "Хобби, интересы, что тебя вдохновляет..."
    }
]


async def seed_questions():
    """Добавить дефолтные вопросы для всех факультетов"""
    async with async_session_maker() as db:
        # Получаем все факультеты
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
        
        if not faculties:
            print("❌ Нет факультетов! Сначала создайте факультет через /superadmin")
            return
        
        for faculty in faculties:
            print(f"\n📍 Факультет: {faculty.name}")
            
            # Проверяем есть ли уже шаблон
            result = await db.execute(
                select(StageTemplate).where(
                    StageTemplate.faculty_id == faculty.id,
                    StageTemplate.stage_type == StageType.QUESTIONNAIRE
                )
            )
            template = result.scalars().first()
            
            if template:
                if template.questions:
                    print(f"   ⚠️ Уже есть {len(template.questions)} вопросов, пропускаем")
                    continue
                else:
                    # Обновляем существующий шаблон
                    template.questions = DEFAULT_QUESTIONS
                    print(f"   ✅ Добавлено {len(DEFAULT_QUESTIONS)} вопросов в существующий шаблон")
            else:
                # Создаём новый шаблон
                template = StageTemplate(
                    faculty_id=faculty.id,
                    stage_type=StageType.QUESTIONNAIRE,
                    questions=DEFAULT_QUESTIONS,
                    is_active=True
                )
                db.add(template)
                print(f"   ✅ Создан шаблон с {len(DEFAULT_QUESTIONS)} вопросами")
        
        await db.commit()
        print("\n✅ Готово!")


async def open_questionnaire_stage():
    """Открыть этап анкеты для всех факультетов"""
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
        
        for faculty in faculties:
            faculty.current_stage = StageType.QUESTIONNAIRE
            faculty.stage_status = StageStatus.OPEN
            print(f"✅ Анкета открыта для: {faculty.name}")
        
        await db.commit()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Seed questions for questionnaire")
    parser.add_argument("--open", action="store_true", help="Also open questionnaire stage")
    args = parser.parse_args()
    
    print("🚀 Добавление дефолтных вопросов...")
    asyncio.run(seed_questions())
    
    if args.open:
        print("\n🔓 Открытие этапа анкеты...")
        asyncio.run(open_questionnaire_stage())
