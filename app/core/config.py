from pydantic import BaseSettings


class Settings(BaseSettings):
    app_name: str = "selection_app"
    debug: bool = False
    db_url: str | None = None
    redis_url: str | None = None
    telegram_bot_token: str | None = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
