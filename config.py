from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    env: Literal["prod", "test"] = "prod"

    db_url = ...
    # общие настройки


settings = Settings()