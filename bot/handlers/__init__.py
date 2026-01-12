from bot.handlers.admin import admin_router
from bot.handlers.user import user_router
from bot.handlers.questions import questions_router
from bot.handlers.cleanup import cleanup_router
from bot.handlers.superadmin import superadmin_router

__all__ = ["admin_router", "user_router", "questions_router", "cleanup_router", "superadmin_router"]

