from bot.handlers.admin import admin_router
from bot.handlers.user import user_router
from bot.handlers.questions import questions_router
from bot.handlers.cleanup import cleanup_router
from bot.handlers.superadmin import superadmin_router
from bot.handlers.reviewers import reviewers_router
from bot.handlers.broadcast import broadcast_router
from bot.handlers.video_stage import video_stage_router
from bot.handlers.surveys import surveys_router
from bot.handlers.interviews import interviews_router

__all__ = ["admin_router", "user_router", "questions_router", "cleanup_router", "superadmin_router", "reviewers_router", "broadcast_router", "video_stage_router", "surveys_router", "interviews_router"]

