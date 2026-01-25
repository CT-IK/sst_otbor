"""
Сервис для отправки уведомлений в Telegram.
"""
import aiohttp
import logging
from config import settings

logger = logging.getLogger(__name__)


class NotificationService:
    """Отправка уведомлений через Telegram Bot API"""
    
    def __init__(self):
        self.bot_token = settings.telegram_bot_token
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
    
    async def send_message(self, chat_id: int, text: str, parse_mode: str = "HTML") -> bool:
        """Отправить сообщение пользователю"""
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN не настроен")
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                    }
                ) as response:
                    if response.status == 200:
                        logger.info(f"Уведомление отправлено: chat_id={chat_id}")
                        return True
                    else:
                        error = await response.text()
                        logger.error(f"Ошибка отправки уведомления: {error}")
                        return False
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")
            return False
    
    async def notify_questionnaire_submitted(self, telegram_id: int, faculty_name: str) -> bool:
        """Уведомление об успешной подаче анкеты"""
        text = (
            "Спасибо за заполнение анкеты! Первый этап отбора пройден.\n\n"
            "Следи за новыми публикациями в группе отбора и приходящими сообщениями от данного бота — "
            "там будет дальнейшая информация по отбору. После заполнения анкеты появится информация "
            "о следующем этапе. Если ты не получишь сообщение, напиши об этом в личные сообщения группы.\n\n"
            "Удачи!"
        )
        return await self.send_message(telegram_id, text)
    
    async def notify_questionnaire_approved(self, telegram_id: int, faculty_name: str) -> bool:
        """Уведомление об одобрении анкеты"""
        text = (
            "🎉 <b>Поздравляем!</b>\n\n"
            f"Твоя анкета на {faculty_name} одобрена!\n\n"
            "Следующий этап — домашнее задание.\n"
            "Следи за обновлениями!"
        )
        return await self.send_message(telegram_id, text)
    
    async def notify_questionnaire_rejected(self, telegram_id: int, faculty_name: str, reason: str = None) -> bool:
        """Уведомление об отклонении анкеты"""
        text = (
            "😔 <b>К сожалению, твоя анкета отклонена</b>\n\n"
            f"Факультет: {faculty_name}\n"
        )
        if reason:
            text += f"\nПричина: {reason}\n"
        text += "\nНе расстраивайся! Попробуй в следующем году."
        return await self.send_message(telegram_id, text)


# Singleton
notification_service = NotificationService()
