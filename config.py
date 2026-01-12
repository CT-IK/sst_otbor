from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"  # Игнорировать лишние переменные из .env
    )

    env: Literal["prod", "dev", "test"] = "dev"
    debug: bool = True

    # PostgreSQL (можно задать напрямую через DB_URL или через отдельные переменные)
    db_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_db: str = "postgres"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_draft_ttl: int = 60 * 60 * 24 * 7  # 7 дней TTL для черновиков

    # Telegram
    telegram_bot_token: str = ""
    
    # Супер-админы (могут создавать факультеты и назначать админов)
    # Список Telegram ID через запятую: "123456789,987654321"
    super_admin_ids: str = ""

    # === Тестовые данные для разработки (без Telegram) ===
    dev_telegram_id: int = 123456789  # Тестовый Telegram ID
    dev_faculty_id: int = 1           # Тестовый факультет
    dev_user_id: int = 1              # Тестовый пользователь

    @property
    def database_url(self) -> str:
        """Возвращает URL для подключения к БД"""
        if self.db_url:
            return self.db_url
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"
    
    @property
    def super_admins(self) -> list[int]:
        """Список Telegram ID супер-админов"""
        if not self.super_admin_ids:
            return []
        return [int(x.strip()) for x in self.super_admin_ids.split(",") if x.strip()]
    
    def is_super_admin(self, telegram_id: int) -> bool:
        """Проверка, является ли пользователь супер-админом"""
        if self.is_dev:
            return True
        return telegram_id in self.super_admins


settings = Settings()
