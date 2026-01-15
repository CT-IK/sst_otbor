"""
Команды супер-администратора.
Создание факультетов, назначение админов.
"""
import logging
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from config import settings
from db.engine import async_session_maker
from db.models import Faculty, Administrator, StageType, StageStatus

logger = logging.getLogger(__name__)
superadmin_router = Router()


# === FSM States ===
class CreateFacultyStates(StatesGroup):
    """Состояния для создания факультета"""
    enter_name = State()
    enter_description = State()
    confirm = State()


class AddAdminStates(StatesGroup):
    """Состояния для добавления админа"""
    select_faculty = State()
    enter_telegram_id = State()
    confirm = State()


# === Helpers ===
def is_super_admin(telegram_id: int) -> bool:
    """Проверка супер-админа"""
    return settings.is_super_admin(telegram_id)


# === Команды ===

@superadmin_router.message(Command("superadmin"))
async def cmd_superadmin(message: Message):
    """Панель супер-админа"""
    if not is_super_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав супер-администратора")
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛 Факультеты", callback_data="sa:faculties")],
        [InlineKeyboardButton(text="👑 Админы", callback_data="sa:admins")],
        [InlineKeyboardButton(text="➕ Создать факультет", callback_data="sa:create_faculty")],
        [InlineKeyboardButton(text="👤 Добавить админа", callback_data="sa:add_admin")],
    ])
    
    await message.answer(
        "👑 <b>Панель супер-администратора</b>\n\n"
        "Здесь вы можете:\n"
        "• Создавать и управлять факультетами\n"
        "• Назначать и удалять администраторов факультетов",
        reply_markup=keyboard
    )


# === Список факультетов ===

@superadmin_router.callback_query(F.data == "sa:faculties")
async def callback_faculties(callback: CallbackQuery):
    """Список всех факультетов"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
    
    if not faculties:
        text = "🏛 <b>Факультеты</b>\n\n<i>Факультетов пока нет</i>"
    else:
        text = "🏛 <b>Факультеты</b>\n\n"
        for f in faculties:
            stage = f.current_stage.value if f.current_stage else "не начат"
            status = f.stage_status.value if f.stage_status else "—"
            text += f"<b>{f.id}.</b> {f.name}\n"
            text += f"   📍 Этап: {stage} ({status})\n\n"
    
    buttons = [
        [InlineKeyboardButton(text="➕ Создать", callback_data="sa:create_faculty")],
        [InlineKeyboardButton(text="« Назад", callback_data="sa:back")],
    ]
    
    # Добавляем кнопки для каждого факультета
    for f in faculties:
        buttons.insert(-1, [
            InlineKeyboardButton(text=f"⚙️ {f.name}", callback_data=f"sa:faculty:{f.id}")
        ])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@superadmin_router.callback_query(F.data.startswith("sa:faculty:"))
async def callback_faculty_details(callback: CallbackQuery):
    """Детали факультета"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    faculty_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == faculty_id)
        )
        faculty = result.scalars().first()
        
        if not faculty:
            await callback.answer("Факультет не найден", show_alert=True)
            return
        
        # Получаем админов факультета
        result = await db.execute(
            select(Administrator).where(
                Administrator.faculty_id == faculty_id,
                Administrator.is_active == True
            )
        )
        admins = result.scalars().all()
    
    stage = faculty.current_stage.value if faculty.current_stage else "не начат"
    status = faculty.stage_status.value if faculty.stage_status else "—"
    
    admins_text = ""
    if admins:
        for a in admins:
            admins_text += f"\n  • {a.full_name or 'Без имени'}"
            if a.username:
                admins_text += f" (@{a.username})"
            admins_text += f" [ID: {a.telegram_id}]"
    else:
        admins_text = "\n  <i>Нет админов</i>"
    
    buttons = [
        [InlineKeyboardButton(
            text="👤 Добавить админа", 
            callback_data=f"sa:add_admin_to:{faculty_id}"
        )],
        [InlineKeyboardButton(
            text="🗑 Удалить факультет", 
            callback_data=f"sa:delete_faculty:{faculty_id}"
        )],
        [InlineKeyboardButton(text="« Назад", callback_data="sa:faculties")],
    ]
    
    await callback.message.edit_text(
        f"🏛 <b>{faculty.name}</b>\n\n"
        f"📝 {faculty.description or 'Без описания'}\n\n"
        f"📍 Этап: <b>{stage}</b> ({status})\n\n"
        f"👑 <b>Администраторы:</b>{admins_text}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


# === Создание факультета ===

@superadmin_router.callback_query(F.data == "sa:create_faculty")
async def callback_create_faculty(callback: CallbackQuery, state: FSMContext):
    """Начать создание факультета"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await state.set_state(CreateFacultyStates.enter_name)
    
    await callback.message.edit_text(
        "🏛 <b>Создание факультета</b>\n\n"
        "Введите <b>название</b> факультета:\n\n"
        "<i>Например: ФИТ, ИИПС, ФМА</i>\n\n"
        "Отмена: /cancel"
    )
    await callback.answer()


@superadmin_router.message(CreateFacultyStates.enter_name)
async def process_faculty_name(message: Message, state: FSMContext):
    """Обработка названия факультета"""
    if not is_super_admin(message.from_user.id):
        return
    
    name = message.text.strip()
    
    if len(name) < 2 or len(name) > 100:
        await message.answer("❌ Название должно быть от 2 до 100 символов")
        return
    
    # Проверяем уникальность
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.name == name)
        )
        if result.scalars().first():
            await message.answer("❌ Факультет с таким названием уже существует")
            return
    
    await state.update_data(faculty_name=name)
    await state.set_state(CreateFacultyStates.enter_description)
    
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "Введите <b>описание</b> факультета (или отправьте '-' чтобы пропустить):"
    )


@superadmin_router.message(CreateFacultyStates.enter_description)
async def process_faculty_description(message: Message, state: FSMContext):
    """Обработка описания факультета"""
    if not is_super_admin(message.from_user.id):
        return
    
    description = message.text.strip()
    if description == "-":
        description = None
    
    await state.update_data(faculty_description=description)
    await state.set_state(CreateFacultyStates.confirm)
    
    data = await state.get_data()
    
    buttons = [
        [
            InlineKeyboardButton(text="✅ Создать", callback_data="sa:confirm_faculty"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="sa:cancel_faculty"),
        ]
    ]
    
    await message.answer(
        f"📋 <b>Проверьте данные:</b>\n\n"
        f"Название: <b>{data['faculty_name']}</b>\n"
        f"Описание: {description or '—'}\n\n"
        f"Создать факультет?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@superadmin_router.callback_query(F.data == "sa:confirm_faculty", CreateFacultyStates.confirm)
async def confirm_create_faculty(callback: CallbackQuery, state: FSMContext):
    """Подтвердить создание факультета"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    data = await state.get_data()
    
    async with async_session_maker() as db:
        faculty = Faculty(
            name=data["faculty_name"],
            description=data.get("faculty_description"),
            current_stage=None,
            stage_status=StageStatus.NOT_STARTED,
        )
        db.add(faculty)
        await db.commit()
        await db.refresh(faculty)
        faculty_id = faculty.id
    
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ <b>Факультет создан!</b>\n\n"
        f"ID: {faculty_id}\n"
        f"Название: <b>{data['faculty_name']}</b>\n\n"
        f"Теперь назначьте администратора факультета."
    )
    await callback.answer("Создано!")


@superadmin_router.callback_query(F.data == "sa:cancel_faculty")
async def cancel_create_faculty(callback: CallbackQuery, state: FSMContext):
    """Отменить создание факультета"""
    await state.clear()
    await callback.message.edit_text("❌ Создание отменено")
    await callback.answer()


# === Удаление факультета ===

@superadmin_router.callback_query(F.data.startswith("sa:delete_faculty:"))
async def callback_delete_faculty(callback: CallbackQuery):
    """Запросить подтверждение удаления факультета"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    faculty_id = int(callback.data.split(":")[2])
    
    buttons = [
        [
            InlineKeyboardButton(
                text="🗑 Да, удалить", 
                callback_data=f"sa:confirm_delete_faculty:{faculty_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отмена", 
                callback_data=f"sa:faculty:{faculty_id}"
            ),
        ]
    ]
    
    await callback.message.edit_text(
        "⚠️ <b>Внимание!</b>\n\n"
        "Вы уверены, что хотите удалить этот факультет?\n"
        "Все связанные данные (шаблоны, анкеты) будут удалены!\n\n"
        "Это действие нельзя отменить!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@superadmin_router.callback_query(F.data.startswith("sa:confirm_delete_faculty:"))
async def confirm_delete_faculty(callback: CallbackQuery):
    """Подтвердить удаление факультета"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    faculty_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == faculty_id)
        )
        faculty = result.scalars().first()
        
        if faculty:
            await db.delete(faculty)
            await db.commit()
    
    await callback.message.edit_text("✅ Факультет удалён")
    await callback.answer("Удалено!")


# === Список админов ===

@superadmin_router.callback_query(F.data == "sa:admins")
async def callback_admins(callback: CallbackQuery):
    """Список всех админов"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(Administrator.is_active == True)
        )
        admins = result.scalars().all()
    
    if not admins:
        text = "👑 <b>Администраторы</b>\n\n<i>Админов пока нет</i>"
    else:
        text = "👑 <b>Администраторы</b>\n\n"
        for a in admins:
            text += f"<b>{a.id}.</b> {a.full_name or 'Без имени'}"
            if a.username:
                text += f" (@{a.username})"
            text += f"\n   📍 {a.faculty.name if a.faculty else 'Без факультета'}"
            text += f"\n   🆔 {a.telegram_id}\n\n"
    
    buttons = [
        [InlineKeyboardButton(text="👤 Добавить админа", callback_data="sa:add_admin")],
        [InlineKeyboardButton(text="« Назад", callback_data="sa:back")],
    ]
    
    # Кнопки для удаления каждого админа
    for a in admins:
        buttons.insert(-1, [
            InlineKeyboardButton(
                text=f"🗑 {a.full_name or a.telegram_id}", 
                callback_data=f"sa:remove_admin:{a.id}"
            )
        ])
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


# === Добавление админа ===

@superadmin_router.callback_query(F.data == "sa:add_admin")
async def callback_add_admin(callback: CallbackQuery, state: FSMContext):
    """Начать добавление админа - выбор факультета"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(select(Faculty))
        faculties = result.scalars().all()
    
    if not faculties:
        await callback.message.edit_text(
            "❌ Сначала создайте факультет!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="« Назад", callback_data="sa:back")],
            ])
        )
        await callback.answer()
        return
    
    buttons = []
    for f in faculties:
        buttons.append([
            InlineKeyboardButton(
                text=f.name,
                callback_data=f"sa:add_admin_to:{f.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="« Отмена", callback_data="sa:back")])
    
    await callback.message.edit_text(
        "👤 <b>Добавление администратора</b>\n\n"
        "Выберите факультет:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@superadmin_router.callback_query(F.data.startswith("sa:add_admin_to:"))
async def callback_add_admin_to_faculty(callback: CallbackQuery, state: FSMContext):
    """Выбран факультет, запросить Telegram ID"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    faculty_id = int(callback.data.split(":")[2])
    await state.update_data(admin_faculty_id=faculty_id)
    await state.set_state(AddAdminStates.enter_telegram_id)
    
    await callback.message.edit_text(
        "👤 <b>Добавление администратора</b>\n\n"
        "Новый админ должен отправить боту любое сообщение.\n"
        "После этого перешлите мне это сообщение, и я получу его Telegram ID.\n\n"
        "Или введите Telegram ID вручную:\n\n"
        "Отмена: /cancel"
    )
    await callback.answer()


@superadmin_router.message(AddAdminStates.enter_telegram_id)
async def process_admin_telegram_id(message: Message, state: FSMContext):
    """Обработка Telegram ID нового админа"""
    if not is_super_admin(message.from_user.id):
        return
    
    # Проверяем, это пересланное сообщение или ID
    if message.forward_from:
        telegram_id = message.forward_from.id
        full_name = message.forward_from.full_name
        username = message.forward_from.username
    elif message.text and message.text.isdigit():
        telegram_id = int(message.text)
        full_name = None
        username = None
    else:
        await message.answer(
            "❌ Неверный формат.\n"
            "Перешлите сообщение от нового админа или введите его Telegram ID (число)"
        )
        return
    
    # Проверяем, есть ли уже такой админ
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(Administrator.telegram_id == telegram_id)
        )
        existing = result.scalars().first()
        
        if existing:
            if existing.is_active:
                await message.answer(
                    f"❌ Этот пользователь уже админ факультета: "
                    f"{existing.faculty.name if existing.faculty else 'без факультета'}"
                )
                return
            else:
                # Реактивируем
                await state.update_data(
                    admin_telegram_id=telegram_id,
                    admin_full_name=existing.full_name,
                    admin_username=existing.username,
                    admin_existing_id=existing.id
                )
        else:
            await state.update_data(
                admin_telegram_id=telegram_id,
                admin_full_name=full_name,
                admin_username=username,
                admin_existing_id=None
            )
    
    await state.set_state(AddAdminStates.confirm)
    
    data = await state.get_data()
    
    # Получаем название факультета
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == data["admin_faculty_id"])
        )
        faculty = result.scalars().first()
    
    buttons = [
        [
            InlineKeyboardButton(text="✅ Добавить", callback_data="sa:confirm_admin"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="sa:cancel_admin"),
        ]
    ]
    
    await message.answer(
        f"📋 <b>Проверьте данные:</b>\n\n"
        f"Telegram ID: <code>{telegram_id}</code>\n"
        f"Имя: {full_name or '—'}\n"
        f"Username: @{username or '—'}\n"
        f"Факультет: <b>{faculty.name if faculty else '—'}</b>\n\n"
        f"Добавить как администратора?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


def generate_password(length: int = 10) -> str:
    """Генерация случайного пароля"""
    import secrets
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def hash_password(password: str) -> str:
    """Хеширование пароля"""
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


@superadmin_router.callback_query(F.data == "sa:confirm_admin", AddAdminStates.confirm)
async def confirm_add_admin(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтвердить добавление админа"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    data = await state.get_data()
    
    # Генерируем пароль для админки
    password = generate_password()
    password_hash = hash_password(password)
    
    admin_telegram_id = data["admin_telegram_id"]
    admin_username = data.get("admin_username")
    
    async with async_session_maker() as db:
        # Получаем название факультета
        result = await db.execute(
            select(Faculty).where(Faculty.id == data["admin_faculty_id"])
        )
        faculty = result.scalars().first()
        faculty_name = faculty.name if faculty else "—"
        
        if data.get("admin_existing_id"):
            # Реактивируем существующего
            result = await db.execute(
                select(Administrator).where(Administrator.id == data["admin_existing_id"])
            )
            admin = result.scalars().first()
            admin.is_active = True
            admin.faculty_id = data["admin_faculty_id"]
            admin.role = "head_admin"  # Суперадмин назначает главных админов
            admin.password_hash = password_hash  # Обновляем пароль
        else:
            # Создаём нового
            admin = Administrator(
                telegram_id=admin_telegram_id,
                full_name=data.get("admin_full_name"),
                username=admin_username,
                faculty_id=data["admin_faculty_id"],
                role="head_admin",  # Суперадмин назначает главных админов
                is_active=True,
                password_hash=password_hash,
            )
            db.add(admin)
        
        await db.commit()
    
    await state.clear()
    
    # Отправляем пароль новому админу
    try:
        await bot.send_message(
            admin_telegram_id,
            f"🎉 <b>Вы назначены ГЛАВНЫМ администратором!</b>\n\n"
            f"Факультет: <b>{faculty_name}</b>\n\n"
            f"📊 <b>Данные для входа в админ-панель:</b>\n"
            f"Логин: <code>{admin_username or admin_telegram_id}</code>\n"
            f"Пароль: <code>{password}</code>\n\n"
            f"🔗 Админ-панель: https://putevod-ik.ru/admin\n\n"
            f"<i>Сохраните пароль! Он больше не будет показан.</i>\n\n"
            f"<b>Ваши возможности:</b>\n"
            f"• /admin — управление факультетом\n"
            f"• /questions — редактор вопросов\n"
            f"• /reviewers — управление проверяющими\n"
            f"• /broadcast — рассылка участникам"
        )
        password_sent = True
    except Exception as e:
        logger.error(f"Не удалось отправить пароль админу: {e}")
        password_sent = False
    
    # Сообщение суперадмину
    msg = f"✅ <b>Администратор добавлен!</b>\n\n"
    msg += f"Telegram ID: <code>{admin_telegram_id}</code>\n"
    if admin_username:
        msg += f"Username: @{admin_username}\n"
    msg += f"Факультет: {faculty_name}\n\n"
    
    if password_sent:
        msg += "✅ Пароль отправлен админу в личные сообщения"
    else:
        msg += f"⚠️ Не удалось отправить пароль.\n"
        msg += f"Передайте вручную:\n"
        msg += f"Логин: <code>{admin_username or admin_telegram_id}</code>\n"
        msg += f"Пароль: <code>{password}</code>"
    
    await callback.message.edit_text(msg)
    await callback.answer("Добавлено!")


@superadmin_router.callback_query(F.data == "sa:cancel_admin")
async def cancel_add_admin(callback: CallbackQuery, state: FSMContext):
    """Отменить добавление админа"""
    await state.clear()
    await callback.message.edit_text("❌ Добавление отменено")
    await callback.answer()


# === Удаление админа ===

@superadmin_router.callback_query(F.data.startswith("sa:remove_admin:"))
async def callback_remove_admin(callback: CallbackQuery):
    """Удалить админа"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    admin_id = int(callback.data.split(":")[2])
    
    buttons = [
        [
            InlineKeyboardButton(
                text="🗑 Да, удалить", 
                callback_data=f"sa:confirm_remove_admin:{admin_id}"
            ),
            InlineKeyboardButton(text="❌ Отмена", callback_data="sa:admins"),
        ]
    ]
    
    await callback.message.edit_text(
        "⚠️ Удалить этого администратора?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@superadmin_router.callback_query(F.data.startswith("sa:confirm_remove_admin:"))
async def confirm_remove_admin(callback: CallbackQuery):
    """Подтвердить удаление админа"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    admin_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(Administrator.id == admin_id)
        )
        admin = result.scalars().first()
        
        if admin:
            admin.is_active = False  # Мягкое удаление
            await db.commit()
    
    await callback.message.edit_text("✅ Администратор удалён")
    await callback.answer("Удалено!")


# === Навигация ===

@superadmin_router.callback_query(F.data == "sa:back")
async def callback_back(callback: CallbackQuery, state: FSMContext):
    """Назад в главное меню супер-админа"""
    await state.clear()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛 Факультеты", callback_data="sa:faculties")],
        [InlineKeyboardButton(text="👑 Админы", callback_data="sa:admins")],
        [InlineKeyboardButton(text="➕ Создать факультет", callback_data="sa:create_faculty")],
        [InlineKeyboardButton(text="👤 Добавить админа", callback_data="sa:add_admin")],
    ])
    
    await callback.message.edit_text(
        "👑 <b>Панель супер-администратора</b>\n\n"
        "Здесь вы можете:\n"
        "• Создавать и управлять факультетами\n"
        "• Назначать и удалять администраторов факультетов",
        reply_markup=keyboard
    )
    await callback.answer()

