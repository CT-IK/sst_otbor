"""
Система опросов для суперадминов.
Рассылка опросов всем пользователям бота с сохранением ответов в JSON.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from config import settings
from db.engine import async_session_maker
from db.models import User

logger = logging.getLogger(__name__)
surveys_router = Router()

# Путь к файлу с опросами
DATA_DIR = Path(__file__).parent.parent.parent / "data"
SURVEYS_FILE = DATA_DIR / "surveys.json"


# === FSM States ===
class CreateSurveyStates(StatesGroup):
    """Состояния для создания опроса"""
    enter_message = State()
    enter_options = State()
    confirm = State()


# === Helpers ===
def is_super_admin(telegram_id: int) -> bool:
    """Проверка супер-админа"""
    return settings.is_super_admin(telegram_id)


def ensure_data_dir():
    """Создать папку data если её нет"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_surveys() -> dict:
    """Загрузить все опросы из файла"""
    ensure_data_dir()
    if not SURVEYS_FILE.exists():
        return {}
    try:
        with open(SURVEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_surveys(surveys: dict):
    """Сохранить опросы в файл"""
    ensure_data_dir()
    with open(SURVEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(surveys, f, ensure_ascii=False, indent=2)


def get_survey(survey_id: str) -> Optional[dict]:
    """Получить опрос по ID"""
    surveys = load_surveys()
    return surveys.get(survey_id)


def save_survey(survey_id: str, survey_data: dict):
    """Сохранить один опрос"""
    surveys = load_surveys()
    surveys[survey_id] = survey_data
    save_surveys(surveys)


def add_response(survey_id: str, telegram_id: int, username: Optional[str], answer: str) -> bool:
    """
    Добавить ответ в опрос.
    Возвращает True если ответ новый, False если уже отвечал.
    """
    surveys = load_surveys()
    survey = surveys.get(survey_id)
    
    if not survey:
        return False
    
    # Проверяем, не отвечал ли уже
    for response in survey.get("responses", []):
        if response.get("telegram_id") == telegram_id:
            return False  # Уже отвечал
    
    # Добавляем ответ
    if "responses" not in survey:
        survey["responses"] = []
    
    survey["responses"].append({
        "telegram_id": telegram_id,
        "username": username,
        "answer": answer,
        "answered_at": datetime.now().isoformat()
    })
    
    surveys[survey_id] = survey
    save_surveys(surveys)
    return True


# === Команды ===

@surveys_router.message(Command("survey"))
async def cmd_survey(message: Message, state: FSMContext):
    """Начать создание опроса"""
    if not is_super_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав супер-администратора")
        return
    
    await state.set_state(CreateSurveyStates.enter_message)
    
    await message.answer(
        "📊 <b>Создание опроса</b>\n\n"
        "Этот опрос будет отправлен <b>всем пользователям</b>, "
        "которые хоть раз писали боту.\n\n"
        "Введите <b>текст сообщения</b> для рассылки:\n\n"
        "<i>Пример: Придёте ли вы на общее собрание 15 февраля?</i>\n\n"
        "Отмена: /cancel"
    )


@surveys_router.message(CreateSurveyStates.enter_message)
async def process_survey_message(message: Message, state: FSMContext):
    """Обработка текста опроса"""
    if not is_super_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    
    if len(text) < 5:
        await message.answer("❌ Сообщение слишком короткое (минимум 5 символов)")
        return
    
    if len(text) > 2000:
        await message.answer("❌ Сообщение слишком длинное (максимум 2000 символов)")
        return
    
    await state.update_data(survey_message=text)
    await state.set_state(CreateSurveyStates.enter_options)
    
    await message.answer(
        "✅ Текст сохранён!\n\n"
        "Теперь введите <b>варианты ответов</b>, каждый с новой строки:\n\n"
        "<i>Пример:\n"
        "Да, приду\n"
        "Нет, не смогу\n"
        "Пока не знаю</i>\n\n"
        "Отмена: /cancel"
    )


@surveys_router.message(CreateSurveyStates.enter_options)
async def process_survey_options(message: Message, state: FSMContext):
    """Обработка вариантов ответов"""
    if not is_super_admin(message.from_user.id):
        return
    
    text = message.text.strip()
    
    # Разбиваем по строкам
    options = [opt.strip() for opt in text.split("\n") if opt.strip()]
    
    if len(options) < 2:
        await message.answer(
            "❌ Нужно минимум 2 варианта ответа.\n"
            "Введите каждый вариант с новой строки."
        )
        return
    
    if len(options) > 10:
        await message.answer("❌ Максимум 10 вариантов ответа")
        return
    
    # Проверяем длину каждого варианта
    for opt in options:
        if len(opt) > 64:
            await message.answer(
                f"❌ Вариант слишком длинный (макс 64 символа):\n"
                f"<code>{opt[:50]}...</code>"
            )
            return
    
    await state.update_data(survey_options=options)
    await state.set_state(CreateSurveyStates.confirm)
    
    # Получаем количество пользователей
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.telegram_id.isnot(None)))
        users = result.scalars().all()
        user_count = len(users)
    
    data = await state.get_data()
    
    # Формируем превью
    options_text = "\n".join([f"  • {opt}" for opt in options])
    
    buttons = [
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="survey:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="survey:cancel"),
        ]
    ]
    
    await message.answer(
        f"📋 <b>Проверьте опрос:</b>\n\n"
        f"📝 <b>Сообщение:</b>\n{data['survey_message']}\n\n"
        f"🔘 <b>Варианты ответов:</b>\n{options_text}\n\n"
        f"👥 <b>Получателей:</b> {user_count} пользователей\n\n"
        f"Отправить опрос?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@surveys_router.callback_query(F.data == "survey:confirm", CreateSurveyStates.confirm)
async def confirm_survey(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Подтвердить и отправить опрос"""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    data = await state.get_data()
    survey_message = data["survey_message"]
    options = data["survey_options"]
    
    # Создаём уникальный ID опроса
    survey_id = f"survey_{int(datetime.now().timestamp())}"
    
    # Сохраняем опрос
    survey_data = {
        "message": survey_message,
        "options": options,
        "created_at": datetime.now().isoformat(),
        "created_by": callback.from_user.id,
        "responses": []
    }
    save_survey(survey_id, survey_data)
    
    await state.clear()
    
    # Обновляем сообщение
    await callback.message.edit_text(
        "⏳ <b>Рассылка начата...</b>\n\n"
        f"ID опроса: <code>{survey_id}</code>"
    )
    
    # Получаем всех пользователей
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.telegram_id.isnot(None)))
        users = result.scalars().all()
    
    # Формируем кнопки ответов
    buttons = []
    for i, option in enumerate(options):
        buttons.append([
            InlineKeyboardButton(
                text=option,
                callback_data=f"sv:{survey_id}:{i}"
            )
        ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # Рассылаем
    sent = 0
    failed = 0
    
    for user in users:
        if not user.telegram_id:
            continue
        try:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=f"📢 {survey_message}",
                reply_markup=keyboard
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить опрос пользователю {user.telegram_id}: {e}")
            failed += 1
    
    # Итоговое сообщение
    await callback.message.edit_text(
        f"✅ <b>Опрос отправлен!</b>\n\n"
        f"📊 ID опроса: <code>{survey_id}</code>\n\n"
        f"📨 Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}\n\n"
        f"Для просмотра результатов:\n"
        f"<code>/survey_results {survey_id}</code>"
    )
    await callback.answer("Рассылка завершена!")


@surveys_router.callback_query(F.data == "survey:cancel")
async def cancel_survey(callback: CallbackQuery, state: FSMContext):
    """Отменить создание опроса"""
    await state.clear()
    await callback.message.edit_text("❌ Создание опроса отменено")
    await callback.answer()


# === Обработка ответов на опросы ===

@surveys_router.callback_query(F.data.startswith("sv:"))
async def handle_survey_response(callback: CallbackQuery):
    """Обработка ответа на опрос"""
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Ошибка формата", show_alert=True)
        return
    
    _, survey_id, option_idx_str = parts
    
    try:
        option_idx = int(option_idx_str)
    except ValueError:
        await callback.answer("Ошибка формата", show_alert=True)
        return
    
    # Получаем опрос
    survey = get_survey(survey_id)
    if not survey:
        await callback.answer("Опрос не найден", show_alert=True)
        return
    
    options = survey.get("options", [])
    if option_idx < 0 or option_idx >= len(options):
        await callback.answer("Неверный вариант ответа", show_alert=True)
        return
    
    answer = options[option_idx]
    
    # Сохраняем ответ
    is_new = add_response(
        survey_id=survey_id,
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        answer=answer
    )
    
    if not is_new:
        await callback.answer("Вы уже отвечали на этот опрос!", show_alert=True)
        return
    
    # Редактируем сообщение
    await callback.message.edit_text(
        f"📢 {survey['message']}\n\n"
        f"✅ <b>Спасибо за ответ!</b>\n"
        f"Ваш выбор: <i>{answer}</i>"
    )
    await callback.answer("Ответ сохранён!")


# === Просмотр результатов ===

@surveys_router.message(Command("survey_results"))
async def cmd_survey_results(message: Message):
    """Показать результаты опроса"""
    if not is_super_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав супер-администратора")
        return
    
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        # Показываем список всех опросов
        surveys = load_surveys()
        
        if not surveys:
            await message.answer(
                "📊 <b>Опросы</b>\n\n"
                "Опросов пока нет.\n"
                "Создать: /survey"
            )
            return
        
        text = "📊 <b>Все опросы:</b>\n\n"
        for survey_id, survey in sorted(surveys.items(), key=lambda x: x[1].get("created_at", ""), reverse=True):
            responses_count = len(survey.get("responses", []))
            created = survey.get("created_at", "")[:10]
            msg_preview = survey.get("message", "")[:50]
            if len(survey.get("message", "")) > 50:
                msg_preview += "..."
            
            text += f"🔹 <code>{survey_id}</code>\n"
            text += f"   📝 {msg_preview}\n"
            text += f"   📅 {created} | 👥 {responses_count} ответов\n\n"
        
        text += "\nДля деталей: <code>/survey_results ID_опроса</code>"
        
        await message.answer(text)
        return
    
    survey_id = args[1].strip()
    survey = get_survey(survey_id)
    
    if not survey:
        await message.answer(f"❌ Опрос <code>{survey_id}</code> не найден")
        return
    
    # Считаем статистику
    options = survey.get("options", [])
    responses = survey.get("responses", [])
    
    # Подсчёт по вариантам
    stats = {opt: 0 for opt in options}
    for response in responses:
        answer = response.get("answer")
        if answer in stats:
            stats[answer] += 1
    
    total = len(responses)
    
    # Формируем текст
    text = f"📊 <b>Результаты опроса</b>\n\n"
    text += f"📝 {survey.get('message')}\n\n"
    text += f"👥 <b>Всего ответов:</b> {total}\n\n"
    text += "<b>Распределение:</b>\n"
    
    for option in options:
        count = stats[option]
        percent = (count / total * 100) if total > 0 else 0
        bar = "█" * int(percent / 10) + "░" * (10 - int(percent / 10))
        text += f"  {bar} {count} ({percent:.1f}%)\n"
        text += f"  <i>{option}</i>\n\n"
    
    # Последние 10 ответов
    if responses:
        text += "\n<b>Последние ответы:</b>\n"
        for response in responses[-10:]:
            username = response.get("username") or str(response.get("telegram_id"))
            answer = response.get("answer")
            text += f"  • @{username}: {answer}\n"
    
    await message.answer(text)


# === Список опросов ===

@surveys_router.message(Command("surveys"))
async def cmd_surveys(message: Message):
    """Показать список всех опросов"""
    if not is_super_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав супер-администратора")
        return
    
    # Перенаправляем на survey_results без аргументов
    message.text = "/survey_results"
    await cmd_survey_results(message)
