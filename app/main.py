from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.redis import redis_client
from app.api.routers import questionnaire
from config import settings

# Логирование
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: подключение/отключение Redis"""
    logger.info(f"Starting app in {settings.env} mode...")
    await redis_client.connect()
    logger.info("Redis connected")
    yield
    await redis_client.disconnect()
    logger.info("Redis disconnected")


app = FastAPI(
    title="SST Selection Backend",
    description="API для системы отбора в студенческий совет",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.is_dev else None,  # Swagger только в dev
    redoc_url="/api/redoc" if settings.is_dev else None,
)

# CORS для Mini App
# В проде Telegram Mini App работает с web.telegram.org
allowed_origins = ["*"] if settings.is_dev else [
    "https://web.telegram.org",
    "https://telegram.org",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роутеры
app.include_router(questionnaire.router, prefix="/api/v1", tags=["Questionnaire"])

# Раздача фронтенда
# В dev: напрямую из FastAPI
# В prod: обычно через nginx, но оставим fallback
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    # Статические файлы (CSS, JS)
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    
    @app.get("/")
    async def serve_frontend():
        """Главная страница — Mini App"""
        return FileResponse(frontend_path / "index.html")


@app.get("/healthz")
async def health():
    """Health check для мониторинга"""
    return {"status": "ok", "env": settings.env}
