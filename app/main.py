from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from app.core.config import settings
from app.core.redis import redis_client
from app.api.routers import questionnaire, admin_stats, interview_slots, interview_days, google_sheets


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Startup
    await redis_client.connect()
    yield
    # Shutdown
    await redis_client.disconnect()


app = FastAPI(title="Backend for winter app", lifespan=lifespan)

# Путь к фронтенду
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры (API имеет приоритет над статикой)
app.include_router(questionnaire.router, prefix="/api/v1")
app.include_router(admin_stats.router, prefix="/api/v1")
app.include_router(interview_slots.router, prefix="/api/v1")
app.include_router(interview_days.router, prefix="/api/v1")
app.include_router(google_sheets.router, prefix="/api/v1")

# Раздаём статику (CSS, JS) - ДО HTML роутов
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# Раздаём HTML файлы (в конце, чтобы не перехватывать API и статику)
@app.get("/")
async def index():
    """Главная страница - Mini App для анкеты"""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Frontend not found", "path": str(FRONTEND_DIR)}


@app.get("/admin")
async def admin_page():
    """Админ-панель"""
    admin_file = FRONTEND_DIR / "admin.html"
    if admin_file.exists():
        return FileResponse(admin_file)
    return {"message": "Admin page not found"}


@app.get("/healthz")
async def health():
    return {"status": "ok"}
