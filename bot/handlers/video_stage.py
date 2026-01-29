"""
Управление вторым этапом - сбор домашних видео.
Доступно главным админам и проверяющим.
"""
import logging
from datetime import datetime
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from db.session import async_session_maker
from db.models import Administrator, Faculty, User, UserProgress, StageType, SubmissionStatus

logger = logging.getLogger(__name__)

video_stage_router = Router()


async def get_admin(telegram_id: int) -> Optional[Administrator]:
    """Проверить, является ли пользователь админом (head_admin или reviewer)"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(Administrator).where(
                Administrator.telegram_id == telegram_id,
                Administrator.is_active == True
            )
        )
        return result.scalars().first()


async def get_head_admin(telegram_id: int) -> Optional[Administrator]:
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


class VideoChatStates(StatesGroup):
    waiting_chat_id = State()


class VideoRequestStates(StatesGroup):
    waiting_message_text = State()
    confirm_send = State()


# === Команда /get_chat_id ===

@video_stage_router.message(Command("get_chat_id"))
async def cmd_get_chat_id(message: Message):
    """Получить ID текущего чата"""
    chat_id = message.chat.id
    chat_type = message.chat.type
    
    text = f"📋 <b>Информация о чате</b>\n\n"
    text += f"Тип: <code>{chat_type}</code>\n"
    text += f"ID: <code>{chat_id}</code>\n"
    
    if message.chat.title:
        text += f"Название: {message.chat.title}\n"
    
    if message.chat.username:
        text += f"Username: @{message.chat.username}\n"
    
    await message.answer(text)


# === Настройка группового чата для видео ===

@video_stage_router.message(Command("video_chat"))
async def cmd_video_chat(message: Message, state: FSMContext):
    """Настроить групповой чат для видео"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer("❌ Эта команда доступна только главным админам.")
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
    
    if not faculty:
        await message.answer("❌ Факультет не найден.")
        return
    
    current_chat_id = faculty.video_chat_id
    
    text = f"🎬 <b>Настройка чата для видео</b>\n\n"
    text += f"Факультет: «{faculty.name}»\n\n"
    
    if current_chat_id:
        text += f"Текущий чат: <code>{current_chat_id}</code>\n\n"
    else:
        text += "Чат не настроен.\n\n"
    
    text += "Чтобы настроить чат:\n"
    text += "1. Добавьте бота в групповой чат\n"
    text += "2. Дайте боту права администратора (чтобы он мог отправлять сообщения)\n"
    text += "3. Отправьте команду /get_chat_id в этом чате\n"
    text += "4. Скопируйте ID и отправьте его мне\n\n"
    text += "<i>Или просто перешлите любое сообщение из нужного чата</i>"
    
    buttons = []
    if current_chat_id:
        buttons.append([InlineKeyboardButton(text="🗑 Удалить чат", callback_data="vc:remove")])
    
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="vc:cancel")])
    
    await state.update_data(faculty_id=faculty.id)
    await state.set_state(VideoChatStates.waiting_chat_id)
    
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    )


@video_stage_router.message(VideoChatStates.waiting_chat_id, F.forward_from_chat)
async def process_forwarded_chat(message: Message, state: FSMContext):
    """Обработать пересланное сообщение из чата"""
    chat_id = message.forward_from_chat.id
    chat_title = message.forward_from_chat.title or "Без названия"
    
    data = await state.get_data()
    faculty_id = data["faculty_id"]
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == faculty_id)
        )
        faculty = result.scalars().first()
        
        faculty.video_chat_id = chat_id
        await db.commit()
    
    await state.clear()
    
    await message.answer(
        f"✅ <b>Чат настроен!</b>\n\n"
        f"Чат: <b>{chat_title}</b>\n"
        f"ID: <code>{chat_id}</code>\n\n"
        f"Теперь видео будут отправляться в этот чат."
    )


@video_stage_router.message(VideoChatStates.waiting_chat_id, F.text)
async def process_chat_id_text(message: Message, state: FSMContext):
    """Обработать ID чата в виде текста"""
    try:
        chat_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числовой ID чата:")
        return
    
    data = await state.get_data()
    faculty_id = data["faculty_id"]
    
    # Проверяем, что бот может отправлять в этот чат
    # (попробуем отправить тестовое сообщение)
    try:
        test_msg = await message.bot.send_message(
            chat_id,
            "✅ Бот успешно подключён к этому чату!"
        )
        await message.bot.delete_message(chat_id, test_msg.message_id)
        chat_accessible = True
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
        await message.answer(
            f"⚠️ <b>Не удалось подключиться к чату</b>\n\n"
            f"Убедитесь, что:\n"
            f"• Бот добавлен в этот чат\n"
            f"• У бота есть права на отправку сообщений\n"
            f"• ID чата указан правильно\n\n"
            f"Попробуйте переслать сообщение из чата вместо ввода ID."
        )
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == faculty_id)
        )
        faculty = result.scalars().first()
        
        faculty.video_chat_id = chat_id
        await db.commit()
    
    await state.clear()
    
    await message.answer(
        f"✅ <b>Чат настроен!</b>\n\n"
        f"ID: <code>{chat_id}</code>\n\n"
        f"Теперь видео будут отправляться в этот чат."
    )


@video_stage_router.callback_query(F.data == "vc:remove")
async def callback_remove_chat(callback: CallbackQuery):
    """Удалить настройку чата"""
    admin = await get_head_admin(callback.from_user.id)
    if not admin:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        faculty.video_chat_id = None
        await db.commit()
    
    await callback.message.edit_text("✅ Настройка чата удалена.")
    await callback.answer()


@video_stage_router.callback_query(F.data == "vc:cancel")
async def callback_cancel_chat(callback: CallbackQuery, state: FSMContext):
    """Отменить настройку"""
    await state.clear()
    await callback.message.edit_text("❌ Отменено")
    await callback.answer()


# === Рассылка сообщения с кнопкой "Загрузить видео" ===

@video_stage_router.message(Command("send_video_request"))
async def cmd_send_video_request(message: Message, state: FSMContext):
    """Разослать сообщение с кнопкой загрузки видео"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer("❌ Эта команда доступна только главным админам.")
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
        
        if not faculty:
            await message.answer("❌ Факультет не найден.")
            return
        
        if faculty.current_stage != StageType.HOME_VIDEO:
            await message.answer(
                f"❌ Сейчас активен этап: {faculty.current_stage.value if faculty.current_stage else 'не начат'}\n\n"
                f"Сначала переведите факультет на этап «Домашнее видео»."
            )
            return
        
        if not faculty.video_chat_id:
            await message.answer(
                "❌ Групповой чат для видео не настроен.\n\n"
                "Используйте /video_chat чтобы настроить чат."
            )
            return
        
        # Получаем пользователей, которые отправили анкету НА ЭТОТ ФАКУЛЬТЕТ
        result = await db.execute(
            select(User.telegram_id, User.first_name, User.surname)
            .join(UserProgress, User.id == UserProgress.user_id)
            .where(
                UserProgress.faculty_id == admin.faculty_id,  # Важно: по faculty_id в UserProgress!
                UserProgress.stage_type == StageType.QUESTIONNAIRE,
                UserProgress.status == SubmissionStatus.SUBMITTED
            )
        )
        users = result.fetchall()
        
        if not users:
            await message.answer("❌ Нет пользователей, которые отправили анкету.")
            return
        
        faculty_name = faculty.name
        user_count = len(users)
    
    # Сохраняем данные в состояние
    await state.update_data(
        faculty_id=admin.faculty_id,
        faculty_name=faculty_name,
        user_count=user_count
    )
    
    # Шаблон сообщения по умолчанию
    default_template = (
        "🎬 <b>Второй этап отбора</b>\n\n"
        "Поздравляем! Вы прошли первый этап отбора.\n\n"
        "Теперь вам нужно загрузить <b>домашнее видео</b>.\n\n"
        "<b>Требования к видео:</b>\n"
        "• Длительность: до 1 минуты\n"
        "• Расскажите о себе и почему хотите в Студсовет\n\n"
        "<b>Как отправить видео:</b>\n"
        "1. Нажмите кнопку «📹 Загрузить видео» ниже\n"
        "2. Отправьте ваше видео в этот чат\n"
        "3. Видео будет автоматически передано на проверку"
    )
    
    await state.set_state(VideoRequestStates.waiting_message_text)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Использовать шаблон", callback_data="vr:use_template")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="vr:cancel")]
    ])
    
    await message.answer(
        f"📢 <b>Рассылка уведомления о видео-этапе</b>\n\n"
        f"Факультет: «{faculty_name}»\n"
        f"Получателей: <b>{user_count}</b> чел.\n\n"
        f"Напишите текст сообщения, который получат кандидаты.\n\n"
        f"<i>💡 Совет: используйте HTML-разметку для форматирования:</i>\n"
        f"<code>&lt;b&gt;жирный&lt;/b&gt;</code> → <b>жирный</b>\n"
        f"<code>&lt;i&gt;курсив&lt;/i&gt;</code> → <i>курсив</i>\n\n"
        f"Или нажмите «📝 Использовать шаблон» для стандартного текста.",
        reply_markup=keyboard
    )


@video_stage_router.callback_query(F.data == "vr:use_template", VideoRequestStates.waiting_message_text)
async def callback_use_template(callback: CallbackQuery, state: FSMContext):
    """Использовать шаблон сообщения"""
    default_template = (
        "🎬 <b>Второй этап отбора</b>\n\n"
        "Поздравляем! Вы прошли первый этап отбора.\n\n"
        "Теперь вам нужно загрузить <b>домашнее видео</b>.\n\n"
        "<b>Требования к видео:</b>\n"
        "• Длительность: до 1 минуты\n"
        "• Расскажите о себе и почему хотите в Студсовет\n\n"
        "<b>Как отправить видео:</b>\n"
        "1. Нажмите кнопку «📹 Загрузить видео» ниже\n"
        "2. Отправьте ваше видео в этот чат\n"
        "3. Видео будет автоматически передано на проверку"
    )
    
    await state.update_data(broadcast_text=default_template)
    await show_preview(callback.message, state)
    await callback.answer()


@video_stage_router.message(VideoRequestStates.waiting_message_text, F.text)
async def process_custom_message(message: Message, state: FSMContext):
    """Получен кастомный текст сообщения"""
    custom_text = message.text.strip()
    
    if len(custom_text) < 10:
        await message.answer("❌ Сообщение слишком короткое. Напишите хотя бы 10 символов.")
        return
    
    if len(custom_text) > 4000:
        await message.answer("❌ Сообщение слишком длинное (максимум 4000 символов).")
        return
    
    await state.update_data(broadcast_text=custom_text)
    await show_preview(message, state)


async def show_preview(message: Message, state: FSMContext):
    """Показать превью сообщения"""
    data = await state.get_data()
    broadcast_text = data["broadcast_text"]
    faculty_name = data["faculty_name"]
    user_count = data["user_count"]
    
    await state.set_state(VideoRequestStates.confirm_send)
    
    # Кнопка для загрузки видео (как будет у пользователей)
    preview_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📹 Загрузить видео", callback_data="video:upload")]
    ])
    
    # Показываем превью
    await message.answer(
        f"👁 <b>Превью сообщения</b>\n\n"
        f"Так увидят кандидаты:\n"
        f"{'─' * 30}"
    )
    
    await message.answer(
        broadcast_text,
        reply_markup=preview_keyboard
    )
    
    # Кнопки подтверждения
    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="vr:confirm"),
            InlineKeyboardButton(text="✏️ Изменить", callback_data="vr:edit")
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="vr:cancel")]
    ])
    
    await message.answer(
        f"{'─' * 30}\n\n"
        f"📤 Отправить <b>{user_count}</b> кандидатам факультета «{faculty_name}»?",
        reply_markup=confirm_keyboard
    )


@video_stage_router.callback_query(F.data == "vr:confirm", VideoRequestStates.confirm_send)
async def callback_confirm_send(callback: CallbackQuery, state: FSMContext):
    """Подтвердить отправку"""
    data = await state.get_data()
    broadcast_text = data["broadcast_text"]
    faculty_id = data["faculty_id"]
    
    await callback.message.edit_text("⏳ Отправка сообщений...")
    
    # Получаем пользователей заново
    async with async_session_maker() as db:
        result = await db.execute(
            select(User.telegram_id, User.first_name, User.surname)
            .join(UserProgress, User.id == UserProgress.user_id)
            .where(
                UserProgress.faculty_id == faculty_id,  # Важно: по faculty_id в UserProgress!
                UserProgress.stage_type == StageType.QUESTIONNAIRE,
                UserProgress.status == SubmissionStatus.SUBMITTED
            )
        )
        users = result.fetchall()
    
    # Кнопка для загрузки видео
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📹 Загрузить видео", callback_data="video:upload")]
    ])
    
    # Отправляем сообщения
    success = 0
    failed = 0
    
    for user_id, first_name, surname in users:
        try:
            await callback.bot.send_message(
                user_id,
                broadcast_text,
                reply_markup=keyboard
            )
            success += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить сообщение {user_id}: {e}")
            failed += 1
    
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"✉️ Доставлено: <b>{success}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>"
    )


@video_stage_router.callback_query(F.data == "vr:edit", VideoRequestStates.confirm_send)
async def callback_edit_message(callback: CallbackQuery, state: FSMContext):
    """Изменить текст сообщения"""
    await state.set_state(VideoRequestStates.waiting_message_text)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Использовать шаблон", callback_data="vr:use_template")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="vr:cancel")]
    ])
    
    await callback.message.edit_text(
        "✏️ <b>Редактирование</b>\n\n"
        "Напишите новый текст сообщения:",
        reply_markup=keyboard
    )
    await callback.answer()


@video_stage_router.callback_query(F.data == "vr:cancel")
async def callback_cancel_video_request(callback: CallbackQuery, state: FSMContext):
    """Отменить рассылку"""
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена")
    await callback.answer()


# === Обработка загрузки видео ===

@video_stage_router.callback_query(F.data == "video:upload")
async def callback_video_upload(callback: CallbackQuery):
    """Пользователь нажал кнопку загрузки видео"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await callback.answer("Вы не зарегистрированы", show_alert=True)
            return
        
        # Ищем факультет, где человек подал анкету И где сейчас этап HOME_VIDEO
        result = await db.execute(
            select(UserProgress, Faculty)
            .join(Faculty, UserProgress.faculty_id == Faculty.id)
            .where(
                UserProgress.user_id == user.id,
                UserProgress.stage_type == StageType.QUESTIONNAIRE,
                UserProgress.status == SubmissionStatus.SUBMITTED,
                Faculty.current_stage == StageType.HOME_VIDEO,  # Только где этап видео!
                Faculty.video_submission_open == True  # И приём открыт
            )
        )
        row = result.first()
        
        if not row:
            await callback.answer("Нет факультетов с открытым приёмом видео", show_alert=True)
            return
        
        progress, faculty = row
    
    await callback.message.answer(
        f"📹 <b>Отправь видео в этот чат</b>\n\n"
        f"Факультет: <b>{faculty.name}</b>\n\n"
        "Просто запиши и отправь видео сюда — оно автоматически уйдёт на проверку.\n\n"
        "<i>Максимальный размер: 50 МБ</i>"
    )
    await callback.answer()


@video_stage_router.message(F.video)
async def handle_video_submission(message: Message, bot: Bot):
    """Обработать отправленное видео"""
    async with async_session_maker() as db:
        result = await db.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalars().first()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
        
        # Ищем факультет, где человек подал анкету И где сейчас этап HOME_VIDEO
        result = await db.execute(
            select(UserProgress, Faculty)
            .join(Faculty, UserProgress.faculty_id == Faculty.id)
            .where(
                UserProgress.user_id == user.id,
                UserProgress.stage_type == StageType.QUESTIONNAIRE,
                UserProgress.status == SubmissionStatus.SUBMITTED,
                Faculty.current_stage == StageType.HOME_VIDEO,  # Только где этап видео!
                Faculty.video_submission_open == True  # И приём открыт
            )
        )
        row = result.first()
        
        if not row:
            await message.answer(
                "❌ Нет факультетов с открытым приёмом видео.\n\n"
                "Возможно, этап ещё не начался или приём уже закрыт."
            )
            return
        
        questionnaire_progress, faculty = row
        
        # Сохраняем нужные данные ДО выхода из сессии (чтобы избежать MissingGreenlet)
        faculty_id = faculty.id
        video_chat_id = faculty.video_chat_id
        user_id = user.id
        user_telegram_id = user.telegram_id
        user_name = f"{user.first_name or ''} {user.surname or ''}".strip()
        if not user_name:
            user_name = f"User {user_telegram_id}"
        
        # Проверяем, не отправлял ли уже видео
        result = await db.execute(
            select(UserProgress).where(
                UserProgress.user_id == user_id,
                UserProgress.faculty_id == faculty_id,
                UserProgress.stage_type == StageType.HOME_VIDEO
            )
        )
        existing_progress = result.scalars().first()
        
        if existing_progress and existing_progress.status == SubmissionStatus.SUBMITTED:
            await message.answer("⚠️ Вы уже отправили видео. Повторная отправка невозможна.")
            return
        
        # Обновляем или создаём прогресс
        if existing_progress:
            progress = existing_progress
        else:
            progress = UserProgress(
                user_id=user_id,
                faculty_id=faculty_id,
                stage_type=StageType.HOME_VIDEO,
                status=SubmissionStatus.SUBMITTED,
                submitted_at=datetime.now()
            )
            db.add(progress)
        
        progress.status = SubmissionStatus.SUBMITTED
        progress.submitted_at = datetime.now()
        await db.commit()
    
    # Отправляем видео в групповой чат (уже вне сессии БД)
    if video_chat_id:
        try:
            submission_time = datetime.now().strftime("%d.%m.%Y %H:%M")
            
            caption = (
                f"📹 <b>Видео от кандидата</b>\n\n"
                f"👤 <b>{user_name}</b>\n"
                f"🆔 ID: <code>{user_telegram_id}</code>\n"
                f"⏰ Время отправки: {submission_time}"
            )
            
            if message.caption:
                caption += f"\n\n💬 <i>Комментарий кандидата:</i>\n{message.caption}"
            
            await bot.send_video(
                video_chat_id,
                message.video.file_id,
                caption=caption,
                parse_mode="HTML"
            )
            
            await message.answer(
                "✅ <b>Видео успешно отправлено!</b>\n\n"
                "Ваше видео получено и отправлено на проверку."
            )
        except Exception as e:
            logger.error(f"Не удалось отправить видео в чат {video_chat_id}: {e}")
            await message.answer(
                "✅ Видео получено, но произошла ошибка при отправке в группу.\n"
                "Обратитесь к администратору."
            )
    else:
        await message.answer(
            "✅ Видео получено, но чат для видео не настроен.\n"
            "Обратитесь к администратору."
        )


# === Управление приёмом видео ===

@video_stage_router.message(Command("video_toggle"))
async def cmd_video_toggle(message: Message):
    """Открыть/закрыть приём видео"""
    admin = await get_head_admin(message.from_user.id)
    
    if not admin:
        await message.answer("❌ Эта команда доступна только главным админам.")
        return
    
    async with async_session_maker() as db:
        result = await db.execute(
            select(Faculty).where(Faculty.id == admin.faculty_id)
        )
        faculty = result.scalars().first()
    
    if not faculty:
        await message.answer("❌ Факультет не найден.")
        return
    
    if faculty.current_stage != StageType.HOME_VIDEO:
        await message.answer(
            f"❌ Сейчас активен этап: {faculty.current_stage.value if faculty.current_stage else 'не начат'}\n\n"
            f"Сначала переведите факультет на этап «Домашнее видео»."
        )
        return
    
    # Переключаем статус
    faculty.video_submission_open = not faculty.video_submission_open
    await db.commit()
    
    status = "открыт" if faculty.video_submission_open else "закрыт"
    emoji = "✅" if faculty.video_submission_open else "❌"
    
    await message.answer(
        f"{emoji} <b>Приём видео {status}</b>\n\n"
        f"Факультет: «{faculty.name}»\n\n"
        f"Статус: <b>{status.upper()}</b>"
    )
