# Реэкспорт из корневого config для обратной совместимости
from config import settings, Settings

__all__ = ["settings", "Settings"]
