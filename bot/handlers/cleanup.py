"""
Команды очистки тестовых данных.
Только для dev режима!
"""
import redis.asyncio as redis
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import text, delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.engine import async_session_maker
from db.models import (
    User, Faculty, StageTemplate, Questionnaire, HomeVideo,
    Interview, InterviewSlot, UserProgress, ApprovalQueue, AdminActionLog
)

cleanup_router = Router()


def is_dev_mode() -> bool:
    """Проверка dev режима"""
    return settings.is_dev


@cleanup_router.message(Command("cleanup_redis"))
async def cmd_cleanup_redis(message: Message):
    """Очистить все данные в Redis"""
    if not is_dev_mode():
        await message.answer("⛔ Команда доступна только в dev режиме")
        return
    
    try:
        redis_client = redis.from_url(settings.redis_url)
        
        # Получаем все ключи с черновиками
        keys = await redis_client.keys("draft:*")
        
        if keys:
            deleted = await redis_client.delete(*keys)
            await message.answer(
                f"✅ <b>Redis очищен</b>\n\n"
                f"Удалено ключей: {deleted}",
            )
        else:
            await message.answer("ℹ️ Redis пуст, нечего удалять")
        
        await redis_client.close()
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@cleanup_router.message(Command("cleanup_db"))
async def cmd_cleanup_db(message: Message):
    """Очистить тестовые данные в PostgreSQL"""
    if not is_dev_mode():
        await message.answer("⛔ Команда доступна только в dev режиме")
        return
    
    try:
        async with async_session_maker() as db:
            # Удаляем в правильном порядке (учитываем FK)
            counts = {}
            
            # 1. Удаляем логи
            result = await db.execute(delete(AdminActionLog))
            counts["admin_action_logs"] = result.rowcount
            
            # 2. Удаляем очередь проверки
            result = await db.execute(delete(ApprovalQueue))
            counts["approval_queue"] = result.rowcount
            
            # 3. Удаляем прогресс
            result = await db.execute(delete(UserProgress))
            counts["user_progress"] = result.rowcount
            
            # 4. Удаляем анкеты
            result = await db.execute(delete(Questionnaire))
            counts["questionnaires"] = result.rowcount
            
            # 5. Удаляем видео
            result = await db.execute(delete(HomeVideo))
            counts["home_videos"] = result.rowcount
            
            # 6. Удаляем интервью
            result = await db.execute(delete(Interview))
            counts["interviews"] = result.rowcount
            
            # 7. Удаляем слоты
            result = await db.execute(delete(InterviewSlot))
            counts["interview_slots"] = result.rowcount
            
            # 8. Удаляем шаблоны
            result = await db.execute(delete(StageTemplate))
            counts["stage_templates"] = result.rowcount
            
            # 9. Удаляем пользователей
            result = await db.execute(delete(User))
            counts["users"] = result.rowcount
            
            # 10. Удаляем факультеты
            result = await db.execute(delete(Faculty))
            counts["faculty"] = result.rowcount
            
            await db.commit()
            
            # Формируем отчёт
            total = sum(counts.values())
            report = "\n".join([f"  • {k}: {v}" for k, v in counts.items() if v > 0])
            
            if total > 0:
                await message.answer(
                    f"✅ <b>База данных очищена</b>\n\n"
                    f"Удалено записей:\n{report}\n\n"
                    f"<b>Всего: {total}</b>"
                )
            else:
                await message.answer("ℹ️ База данных пуста, нечего удалять")
                
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@cleanup_router.message(Command("cleanup_all"))
async def cmd_cleanup_all(message: Message):
    """Очистить всё (Redis + PostgreSQL)"""
    if not is_dev_mode():
        await message.answer("⛔ Команда доступна только в dev режиме")
        return
    
    await message.answer("🧹 Начинаю полную очистку...")
    
    # Очищаем Redis
    await cmd_cleanup_redis(message)
    
    # Очищаем БД
    await cmd_cleanup_db(message)
    
    await message.answer("✅ <b>Полная очистка завершена!</b>")


@cleanup_router.message(Command("seed"))
async def cmd_seed(message: Message):
    """Создать тестовые данные"""
    if not is_dev_mode():
        await message.answer("⛔ Команда доступна только в dev режиме")
        return
    
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.post("http://localhost:8000/api/v1/questionnaire/dev/seed") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    await message.answer(
                        f"✅ <b>Тестовые данные созданы</b>\n\n"
                        f"• Faculty ID: {data['faculty_id']}\n"
                        f"• Telegram ID: {data['user_telegram_id']}\n"
                        f"• Template ID: {data['template_id']}"
                    )
                else:
                    error = await resp.text()
                    await message.answer(f"❌ Ошибка: {error}")
                    
    except aiohttp.ClientError as e:
        await message.answer(
            f"❌ Не удалось подключиться к API\n\n"
            f"Убедитесь что бэкенд запущен:\n"
            f"<code>uvicorn app.main:app --reload</code>"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

