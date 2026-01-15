"""
Управление проверяющими.
Только главный админ факультета может добавлять/удалять проверяющих.
"""
import logging
import secrets
import hashlib

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from db.session import async_session_maker
from db.models import Administrator, Faculty

logger = logging.getLogger(__name__)

reviewers_router = Router()


def generate_password(length: int = 10) -> str:
    """Генерация случайного пароля"""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def hash_password(password: str) -> str:
    """Хеширование пароля"""
    return hashlib.sha256(password.encode()).hexdigest()


async def get_head_admin(telegram_id: int):
    """Проверить, является ли пользователь главным админом"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.role == "head_admin",
                Administrator.is_active == True
            )
        )
        return result.scalars().first()


class AddReviewerStates(StatesGroup):
    waiting_telegram_id = State()
    confirm = State()


# === Команда /reviewers ===

@reviewers_router.message(Command("reviewers"))
async def cmd_reviewers(message: Message):
    """Список проверяющих и управление ими"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer("❌ Эта команда доступна только главным админам факультетов.")
        return
    
    async with async_session_maker() as db:
        # Получаем факультет
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        # Получаем проверяющих этого факультета
        result = await db.execute(
            select(Administrator).where(
                Administrator.faculty_id == admin.faculty_id,
                Administrator.role == "reviewer",
                Administrator.is_active == True
            )
        )
        reviewers = result.scalars().all()
    
    text = f"👥 <b>Проверяющие факультета «{faculty.name}»</b>\n\n"
    
    if reviewers:
        for i, r in enumerate(reviewers, 1):
            name = r.full_name or r.username or str(r.telegram_id)
            text += f"{i}. {name}"
            if r.username:
                text += f" (@{r.username})"
            text += f"\n   ID: <code>{r.telegram_id}</code>\n"
    else:
        text += "<i>Пока нет проверяющих</i>\n"
    
    text += "\n<i>Проверяющие могут смотреть ответы и статистику</i>"
    
    # Кнопки
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить проверяющего", callback_data="rev:add")],
    ]
    
    if reviewers:
        buttons.append([InlineKeyboardButton(text="➖ Удалить проверяющего", callback_data="rev:remove")])
    
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# === Добавление проверяющего ===

@reviewers_router.callback_query(F.data == "rev:add")
async def callback_add_reviewer(callback: CallbackQuery, state: FSMContext):
    """Начать добавление проверяющего"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await state.update_data(faculty_id=admin.faculty_id)
    await state.set_state(AddReviewerStates.waiting_telegram_id)
    
    await callback.message.edit_text(
        "👤 <b>Добавление проверяющего</b>\n\n"
        "Отправьте Telegram ID пользователя, которого хотите добавить.\n\n"
        "<i>ID можно узнать у бота @userinfobot</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="rev:cancel")]
        ])
    )
    await callback.answer()


@reviewers_router.message(AddReviewerStates.waiting_telegram_id)
async def process_reviewer_telegram_id(message: Message, state: FSMContext, bot: Bot):
    """Получить telegram_id проверяющего"""
    try:
        telegram_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID:")
        return
    
    data = await state.get_data()
    faculty_id = data["faculty_id"]
    
    # Проверяем, не добавлен ли уже
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.faculty_id == faculty_id,
                Administrator.is_active == True
            )
        )
        existing = result.scalars().first()
        
        if existing:
            await message.answer(
                f"⚠️ Этот пользователь уже является {'главным админом' if existing.role == 'head_admin' else 'проверяющим'} этого факультета.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="rev:back")]
                ])
            )
            await state.clear()
            return
    
    # Пробуем получить информацию о пользователе
    try:
        chat = await bot.get_chat(telegram_id)
        full_name = chat.full_name
        username = chat.username
    except Exception:
        full_name = None
        username = None
    
    await state.update_data(
        reviewer_telegram_id=telegram_id,
        reviewer_full_name=full_name,
        reviewer_username=username
    )
    await state.set_state(AddReviewerStates.confirm)
    
    # Подтверждение
    text = f"👤 <b>Добавить проверяющего?</b>\n\n"
    text += f"Telegram ID: <code>{telegram_id}</code>\n"
    if full_name:
        text += f"Имя: {full_name}\n"
    if username:
        text += f"Username: @{username}\n"
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Добавить", callback_data="rev:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="rev:cancel")
            ]
        ])
    )


@reviewers_router.callback_query(F.data == "rev:confirm", AddReviewerStates.confirm)
async def confirm_add_reviewer(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтвердить добавление проверяющего"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    data = await state.get_data()
    
    # Генерируем пароль
    password = generate_password()
    password_hash = hash_password(password)
    
    reviewer_telegram_id = data["reviewer_telegram_id"]
    reviewer_username = data.get("reviewer_username")
    
    async with async_session_maker() as db:
        # Получаем название факультета
        result = await db.execute(
            select(Faculty).where(Faculty.id == data["faculty_id"])
        )
        faculty = result.scalars().first()
        faculty_name = faculty.name if faculty else "—"
        
        # Создаём проверяющего
        reviewer = Administrator(
            telegram_id=reviewer_telegram_id,
            full_name=data.get("reviewer_full_name"),
            username=reviewer_username,
            faculty_id=data["faculty_id"],
            role="reviewer",
            is_active=True,
            password_hash=password_hash,
            added_by=callback.from_user.id
        )
        db.add(reviewer)
        await db.commit()
    
    await state.clear()
    
    # Отправляем пароль проверяющему
    try:
        await bot.send_message(
            reviewer_telegram_id,
            f"👋 <b>Вы добавлены как проверяющий!</b>\n\n"
            f"Факультет: <b>{faculty_name}</b>\n\n"
            f"📊 <b>Данные для входа в админ-панель:</b>\n"
            f"Логин: <code>{reviewer_username or reviewer_telegram_id}</code>\n"
            f"Пароль: <code>{password}</code>\n\n"
            f"🔗 Админ-панель: https://putevod-ik.ru/admin\n\n"
            f"<i>Сохраните пароль!</i>\n\n"
            f"<b>Ваши возможности:</b>\n"
            f"• Просмотр ответов на анкеты\n"
            f"• Просмотр статистики\n"
            f"• Проведение собеседований"
        )
        password_sent = True
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение проверяющему: {e}")
        password_sent = False
    
    msg = f"✅ <b>Проверяющий добавлен!</b>\n\n"
    msg += f"Telegram ID: <code>{reviewer_telegram_id}</code>\n"
    if reviewer_username:
        msg += f"Username: @{reviewer_username}\n"
    msg += f"\n"
    
    if password_sent:
        msg += "✅ Данные для входа отправлены в личные сообщения"
    else:
        msg += f"⚠️ Не удалось отправить сообщение.\n"
        msg += f"Передайте данные вручную:\n"
        msg += f"Логин: <code>{reviewer_username or reviewer_telegram_id}</code>\n"
        msg += f"Пароль: <code>{password}</code>"
    
    await callback.message.edit_text(
        msg,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К списку", callback_data="rev:back")]
        ])
    )
    await callback.answer("Добавлено!")


# === Удаление проверяющего ===

@reviewers_router.callback_query(F.data == "rev:remove")
async def callback_remove_reviewer(callback: CallbackQuery):
    """Показать список проверяющих для удаления"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.faculty_id == admin.faculty_id,
                Administrator.role == "reviewer",
                Administrator.is_active == True
            )
        )
        reviewers = result.scalars().all()
    
    if not reviewers:
        await callback.answer("Нет проверяющих для удаления", show_alert=True)
        return
    
    buttons = []
    for r in reviewers:
        name = r.full_name or r.username or str(r.telegram_id)
        buttons.append([
            InlineKeyboardButton(text=f"❌ {name}", callback_data=f"rev:del:{r.id}")
        ])
    
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="rev:back")])
    
    await callback.message.edit_text(
        "🗑 <b>Удаление проверяющего</b>\n\n"
        "Выберите кого удалить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


@reviewers_router.callback_query(F.data.startswith("rev:del:"))
async def confirm_remove_reviewer(callback: CallbackQuery):
    """Подтвердить удаление проверяющего"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    reviewer_id = int(callback.data.split(":")[2])
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(Administrator.id == reviewer_id)
        )
        reviewer = result.scalars().first()
        
        if not reviewer or reviewer.faculty_id != admin.faculty_id:
            await callback.answer("Проверяющий не найден", show_alert=True)
            return
        
        reviewer.is_active = False
        await db.commit()
        
        name = reviewer.full_name or reviewer.username or str(reviewer.telegram_id)
    
    await callback.message.edit_text(
        f"✅ Проверяющий <b>{name}</b> удалён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К списку", callback_data="rev:back")]
        ])
    )
    await callback.answer("Удалено!")


# === Вспомогательные ===

@reviewers_router.callback_query(F.data == "rev:cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Отменить действие"""
    await state.clear()
    await callback.message.edit_text("❌ Отменено")
    await callback.answer()


@reviewers_router.callback_query(F.data == "rev:back")
async def callback_back(callback: CallbackQuery, state: FSMContext):
    """Вернуться к списку проверяющих"""
    await state.clear()
    # Имитируем вызов /reviewers
    await cmd_reviewers(callback.message)
    await callback.answer()
