"""
Управление вопросами анкеты через FSM.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from config import settings
from db.engine import async_session_maker
from db.models import Faculty, StageTemplate, StageType

logger = logging.getLogger(__name__)
questions_router = Router()


# === FSM States ===
class AddQuestionStates(StatesGroup):
    """Состояния для добавления вопроса"""
    select_faculty = State()
    select_action = State()
    enter_question_id = State()
    enter_question_text = State()
    enter_question_type = State()
    enter_options = State()
    enter_max_length = State()
    confirm = State()


# === Helpers ===
async def is_admin(telegram_id: int) -> bool:
    """Проверка админа"""
    if settings.is_dev:
        return True
    
    async with async_session_maker() as db:
        from db.models import Administrator
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.is_active == True
            )
        )
        return result.scalars().first() is not None


async def get_admin_faculty_id(telegram_id: int) -> int | None:
    """Получить ID факультета админа"""
    if settings.is_dev:
        return settings.dev_faculty_id
    
    async with async_session_maker() as db:
        from db.models import Administrator
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.is_active == True
            )
        )
        admin = result.scalars().first()
        return admin.faculty_id if admin else None


def get_question_types_keyboard():
    """Клавиатура выбора типа вопроса"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Текст", callback_data="qtype:text")],
        [InlineKeyboardButton(text="🔘 Один вариант", callback_data="qtype:choice")],
        [InlineKeyboardButton(text="☑️ Несколько вариантов", callback_data="qtype:multiple_choice")],
        [InlineKeyboardButton(text="🔢 Число", callback_data="qtype:number")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="qtype:cancel")],
    ])


# === Команды ===

@questions_router.message(Command("questions"))
async def cmd_questions(message: Message, state: FSMContext):
    """Управление вопросами"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора")
        return
    
    # Сбрасываем состояние
    await state.clear()
    
    # Получаем факультет админа
    admin_faculty_id = await get_admin_faculty_id(message.from_user.id)
    
    if admin_faculty_id:
        # Сразу показываем вопросы своего факультета
        async with async_session_maker() as db:
            result = await db.execute(select(Faculty).where(Faculty.id == admin_faculty_id))
            faculty = result.scalars().first()
            
            if not faculty:
                await message.answer("❌ Ваш факультет не найден")
                return
            
            # Получаем шаблон
            result = await db.execute(
                select(StageTemplate).where(
                    StageTemplate.faculty_id == admin_faculty_id,
                    StageTemplate.stage_type == StageType.QUESTIONNAIRE,
                    StageTemplate.is_active == True
                )
            )
            template = result.scalars().first()
        
        if template:
            questions = template.questions or []
            questions_text = ""
            for i, q in enumerate(questions, 1):
                req = "🔴" if q.get("required") else "⚪"
                questions_text += f"\n{i}. {req} [{q.get('type', 'text')}] {q.get('text', '')[:50]}..."
            
            await state.update_data(template_id=template.id, faculty_id=admin_faculty_id)
        else:
            questions_text = "\n<i>Вопросов пока нет</i>"
            await state.update_data(template_id=None, faculty_id=admin_faculty_id)
        
        buttons = [
            [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="q:add")],
            [InlineKeyboardButton(text="📋 Показать все", callback_data="q:list")],
            [InlineKeyboardButton(text="🗑 Удалить вопрос", callback_data="q:delete")],
            [InlineKeyboardButton(text="🔄 Сбросить все", callback_data="q:reset")],
        ]
        
        await message.answer(
            f"📝 <b>{faculty.name}</b>\n\n"
            f"<b>Текущие вопросы:</b>{questions_text}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    else:
        # Супер-админ или нет привязки — показываем выбор
        async with async_session_maker() as db:
            result = await db.execute(select(Faculty))
            faculties = result.scalars().all()
        
        if not faculties:
            await message.answer(
                "ℹ️ Нет факультетов.\n"
                "Создайте факультет: /superadmin"
            )
            return
        
        buttons = []
        for f in faculties:
            buttons.append([
                InlineKeyboardButton(
                    text=f.name,
                    callback_data=f"q:faculty:{f.id}"
                )
            ])
        
        await message.answer(
            "📝 <b>Управление вопросами</b>\n\n"
            "Выберите факультет:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )


@questions_router.callback_query(F.data.startswith("q:faculty:"))
async def callback_select_faculty(callback: CallbackQuery, state: FSMContext):
    """Выбор факультета"""
    faculty_id = int(callback.data.split(":")[2])
    
    await state.update_data(faculty_id=faculty_id)
    
    async with async_session_maker() as db:
        # Получаем факультет
        result = await db.execute(select(Faculty).where(Faculty.id == faculty_id))
        faculty = result.scalars().first()
        
        # Получаем текущий шаблон
        result = await db.execute(
            select(StageTemplate).where(
                StageTemplate.faculty_id == faculty_id,
                StageTemplate.stage_type == StageType.QUESTIONNAIRE,
                StageTemplate.is_active == True
            )
        )
        template = result.scalars().first()
    
    if template:
        questions = template.questions or []
        questions_text = ""
        for i, q in enumerate(questions, 1):
            req = "🔴" if q.get("required") else "⚪"
            questions_text += f"\n{i}. {req} [{q.get('type', 'text')}] {q.get('text', '')[:50]}..."
        
        await state.update_data(template_id=template.id)
    else:
        questions_text = "\n<i>Вопросов пока нет</i>"
        await state.update_data(template_id=None)
    
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="q:add")],
        [InlineKeyboardButton(text="📋 Показать все", callback_data="q:list")],
        [InlineKeyboardButton(text="🗑 Удалить вопрос", callback_data="q:delete")],
        [InlineKeyboardButton(text="🔄 Сбросить все", callback_data="q:reset")],
        [InlineKeyboardButton(text="« Назад", callback_data="q:back")],
    ]
    
    await callback.message.edit_text(
        f"📝 <b>{faculty.name}</b>\n\n"
        f"<b>Текущие вопросы:</b>{questions_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@questions_router.callback_query(F.data == "q:add")
async def callback_add_question(callback: CallbackQuery, state: FSMContext):
    """Начать добавление вопроса"""
    await state.set_state(AddQuestionStates.enter_question_id)
    
    await callback.message.edit_text(
        "➕ <b>Добавление вопроса</b>\n\n"
        "Введите <b>ID вопроса</b> (латиницей, без пробелов):\n"
        "<i>Например: motivation, experience, skills</i>\n\n"
        "Отмена: /cancel"
    )
    await callback.answer()


@questions_router.message(AddQuestionStates.enter_question_id)
async def process_question_id(message: Message, state: FSMContext):
    """Обработка ID вопроса"""
    question_id = message.text.strip().lower()
    
    # Валидация
    if not question_id.isidentifier():
        await message.answer(
            "❌ Неверный формат ID.\n"
            "Используйте только латинские буквы, цифры и _\n\n"
            "Попробуйте ещё раз:"
        )
        return
    
    await state.update_data(question_id=question_id)
    await state.set_state(AddQuestionStates.enter_question_text)
    
    await message.answer(
        f"✅ ID: <code>{question_id}</code>\n\n"
        "Теперь введите <b>текст вопроса</b>:"
    )


@questions_router.message(AddQuestionStates.enter_question_text)
async def process_question_text(message: Message, state: FSMContext):
    """Обработка текста вопроса"""
    question_text = message.text.strip()
    
    if len(question_text) < 5:
        await message.answer("❌ Вопрос слишком короткий. Минимум 5 символов.")
        return
    
    await state.update_data(question_text=question_text)
    await state.set_state(AddQuestionStates.enter_question_type)
    
    await message.answer(
        f"✅ Текст: {question_text[:100]}...\n\n"
        "Выберите <b>тип вопроса</b>:",
        reply_markup=get_question_types_keyboard()
    )


@questions_router.callback_query(F.data.startswith("qtype:"), AddQuestionStates.enter_question_type)
async def process_question_type(callback: CallbackQuery, state: FSMContext):
    """Обработка типа вопроса"""
    qtype = callback.data.split(":")[1]
    
    if qtype == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Добавление отменено")
        await callback.answer()
        return
    
    await state.update_data(question_type=qtype)
    
    if qtype in ["choice", "multiple_choice"]:
        await state.set_state(AddQuestionStates.enter_options)
        await callback.message.edit_text(
            "Введите <b>варианты ответов</b>, каждый с новой строки:\n\n"
            "<i>Пример:\n"
            "Дизайн\n"
            "SMM\n"
            "Видеомонтаж</i>"
        )
    elif qtype == "text":
        await state.set_state(AddQuestionStates.enter_max_length)
        await callback.message.edit_text(
            "Введите <b>максимальную длину</b> ответа (число):\n\n"
            "<i>Рекомендуется: 500-1000 символов</i>"
        )
    else:
        # number - сразу к подтверждению
        await show_confirmation(callback.message, state)
    
    await callback.answer()


@questions_router.message(AddQuestionStates.enter_options)
async def process_options(message: Message, state: FSMContext):
    """Обработка вариантов ответа"""
    lines = [line.strip() for line in message.text.strip().split("\n") if line.strip()]
    
    if len(lines) < 2:
        await message.answer("❌ Нужно минимум 2 варианта ответа")
        return
    
    options = [{"value": f"opt_{i}", "label": opt} for i, opt in enumerate(lines, 1)]
    await state.update_data(options=options)
    
    await show_confirmation(message, state)


@questions_router.message(AddQuestionStates.enter_max_length)
async def process_max_length(message: Message, state: FSMContext):
    """Обработка максимальной длины"""
    try:
        max_length = int(message.text.strip())
        if max_length < 10 or max_length > 5000:
            raise ValueError()
    except ValueError:
        await message.answer("❌ Введите число от 10 до 5000")
        return
    
    await state.update_data(max_length=max_length)
    await show_confirmation(message, state)


async def show_confirmation(message: Message, state: FSMContext):
    """Показать подтверждение"""
    data = await state.get_data()
    
    options_text = ""
    if data.get("options"):
        options_text = "\nВарианты:\n" + "\n".join([f"  • {o['label']}" for o in data["options"]])
    
    await state.set_state(AddQuestionStates.confirm)
    
    buttons = [
        [
            InlineKeyboardButton(text="✅ Сохранить", callback_data="q:save"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="q:cancel_add"),
        ],
        [InlineKeyboardButton(text="🔴 Обязательный", callback_data="q:toggle_required")],
    ]
    
    required = data.get("required", True)
    req_text = "🔴 Да" if required else "⚪ Нет"
    
    await message.answer(
        f"📝 <b>Проверьте вопрос:</b>\n\n"
        f"ID: <code>{data.get('question_id')}</code>\n"
        f"Текст: {data.get('question_text')}\n"
        f"Тип: {data.get('question_type')}\n"
        f"Обязательный: {req_text}\n"
        f"Макс. длина: {data.get('max_length', '—')}"
        f"{options_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@questions_router.callback_query(F.data == "q:toggle_required", AddQuestionStates.confirm)
async def toggle_required(callback: CallbackQuery, state: FSMContext):
    """Переключить обязательность"""
    data = await state.get_data()
    required = not data.get("required", True)
    await state.update_data(required=required)
    
    await show_confirmation(callback.message, state)
    await callback.answer()


@questions_router.callback_query(F.data == "q:save", AddQuestionStates.confirm)
async def save_question(callback: CallbackQuery, state: FSMContext):
    """Сохранить вопрос"""
    data = await state.get_data()
    logger.info(f"Saving question with data: {data}")
    
    # Формируем вопрос
    question = {
        "id": data["question_id"],
        "text": data["question_text"],
        "type": data["question_type"],
        "required": data.get("required", True),
        "order": 999,  # Будет в конце
    }
    
    if data.get("options"):
        question["options"] = data["options"]
    if data.get("max_length"):
        question["max_length"] = data["max_length"]
    
    logger.info(f"Question to save: {question}")
    
    async with async_session_maker() as db:
        template_id = data.get("template_id")
        faculty_id = data["faculty_id"]
        logger.info(f"template_id={template_id}, faculty_id={faculty_id}")
        
        if template_id:
            # Обновляем существующий шаблон
            result = await db.execute(
                select(StageTemplate).where(StageTemplate.id == template_id)
            )
            template = result.scalars().first()
            logger.info(f"Found template: {template}, questions before: {template.questions if template else None}")
            
            questions = list(template.questions or [])  # Создаём новый список
            question["order"] = len(questions) + 1
            questions.append(question)
            template.questions = questions
            flag_modified(template, "questions")  # Явно указываем SQLAlchemy об изменении
            logger.info(f"Questions after: {template.questions}")
        else:
            # Создаём новый шаблон
            logger.info("Creating new template")
            template = StageTemplate(
                faculty_id=faculty_id,
                stage_type=StageType.QUESTIONNAIRE,
                version=1,
                is_active=True,
                questions=[question],
            )
            db.add(template)
        
        await db.commit()
        logger.info("Committed to database successfully")
    
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ <b>Вопрос добавлен!</b>\n\n"
        f"ID: <code>{question['id']}</code>\n\n"
        f"Используйте /questions для продолжения"
    )
    await callback.answer("Сохранено!")


@questions_router.callback_query(F.data == "q:cancel_add")
async def cancel_add(callback: CallbackQuery, state: FSMContext):
    """Отменить добавление"""
    await state.clear()
    await callback.message.edit_text("❌ Добавление отменено")
    await callback.answer()


@questions_router.callback_query(F.data == "q:list")
async def callback_list_questions(callback: CallbackQuery, state: FSMContext):
    """Показать все вопросы"""
    data = await state.get_data()
    faculty_id = data.get("faculty_id")
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(StageTemplate).where(
                StageTemplate.faculty_id == faculty_id,
                StageTemplate.stage_type == StageType.QUESTIONNAIRE,
                StageTemplate.is_active == True
            )
        )
        template = result.scalars().first()
    
    if not template or not template.questions:
        await callback.answer("Вопросов нет", show_alert=True)
        return
    
    text = "📋 <b>Все вопросы:</b>\n\n"
    for i, q in enumerate(template.questions, 1):
        req = "🔴" if q.get("required") else "⚪"
        text += f"{i}. {req} <b>[{q.get('type')}]</b>\n"
        text += f"   ID: <code>{q.get('id')}</code>\n"
        text += f"   {q.get('text')}\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Назад", callback_data=f"q:faculty:{faculty_id}")],
        ])
    )
    await callback.answer()


@questions_router.callback_query(F.data == "q:back")
async def callback_back(callback: CallbackQuery, state: FSMContext):
    """Назад к списку факультетов"""
    await state.clear()
    await callback.message.delete()
    # Симулируем вызов команды
    await callback.message.answer("Используйте /questions")
    await callback.answer()


@questions_router.callback_query(F.data == "q:delete")
async def callback_delete_question(callback: CallbackQuery, state: FSMContext):
    """Удалить вопрос - показать список для удаления"""
    data = await state.get_data()
    faculty_id = data.get("faculty_id")
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(StageTemplate).where(
                StageTemplate.faculty_id == faculty_id,
                StageTemplate.stage_type == StageType.QUESTIONNAIRE,
                StageTemplate.is_active == True
            )
        )
        template = result.scalars().first()
    
    if not template or not template.questions:
        await callback.answer("Вопросов нет", show_alert=True)
        return
    
    # Кнопки для каждого вопроса
    buttons = []
    for i, q in enumerate(template.questions):
        buttons.append([
            InlineKeyboardButton(
                text=f"🗑 {i+1}. {q.get('text', '')[:30]}...",
                callback_data=f"q:del:{q.get('id')}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="« Назад", callback_data=f"q:faculty:{faculty_id}")])
    
    await callback.message.edit_text(
        "🗑 <b>Удаление вопроса</b>\n\n"
        "Выберите вопрос для удаления:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@questions_router.callback_query(F.data.startswith("q:del:"))
async def callback_confirm_delete(callback: CallbackQuery, state: FSMContext):
    """Подтвердить удаление вопроса"""
    question_id = callback.data.split(":")[2]
    data = await state.get_data()
    faculty_id = data.get("faculty_id")
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(StageTemplate).where(
                StageTemplate.faculty_id == faculty_id,
                StageTemplate.stage_type == StageType.QUESTIONNAIRE,
                StageTemplate.is_active == True
            )
        )
        template = result.scalars().first()
        
        if template and template.questions:
            # Удаляем вопрос из списка
            new_questions = [q for q in template.questions if q.get("id") != question_id]
            
            # Обновляем порядок
            for i, q in enumerate(new_questions, 1):
                q["order"] = i
            
            template.questions = new_questions
            flag_modified(template, "questions")
            await db.commit()
    
    await callback.answer("✅ Вопрос удалён!", show_alert=True)
    
    # Возвращаемся к факультету
    callback.data = f"q:faculty:{faculty_id}"
    await callback_select_faculty(callback, state)


@questions_router.callback_query(F.data == "q:reset")
async def callback_reset_questions(callback: CallbackQuery, state: FSMContext):
    """Сбросить все вопросы"""
    data = await state.get_data()
    faculty_id = data.get("faculty_id")
    
    buttons = [
        [
            InlineKeyboardButton(text="✅ Да, удалить все", callback_data="q:reset:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"q:faculty:{faculty_id}"),
        ]
    ]
    
    await callback.message.edit_text(
        "⚠️ <b>Внимание!</b>\n\n"
        "Вы уверены, что хотите удалить ВСЕ вопросы?\n"
        "Это действие нельзя отменить!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@questions_router.callback_query(F.data == "q:reset:confirm")
async def callback_reset_confirm(callback: CallbackQuery, state: FSMContext):
    """Подтвердить сброс всех вопросов"""
    data = await state.get_data()
    faculty_id = data.get("faculty_id")
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(StageTemplate).where(
                StageTemplate.faculty_id == faculty_id,
                StageTemplate.stage_type == StageType.QUESTIONNAIRE,
                StageTemplate.is_active == True
            )
        )
        template = result.scalars().first()
        
        if template:
            template.questions = []
            flag_modified(template, "questions")
            await db.commit()
    
    await callback.answer("✅ Все вопросы удалены!", show_alert=True)
    
    # Возвращаемся к факультету
    callback.data = f"q:faculty:{faculty_id}"
    await callback_select_faculty(callback, state)


@questions_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    await state.clear()
    await message.answer("❌ Действие отменено")

