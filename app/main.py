from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routers import questionnaire, admin_stats

app = FastAPI(title="Backend for winter app")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем роутеры
app.include_router(questionnaire.router)
app.include_router(admin_stats.router)


@app.get("/")
async def root():
    return {
        "message": "SST Selection Backend API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/healthz",
            "questionnaire": "/questionnaire/{faculty_id}",
            "admin": "/admin/stats/{faculty_id}",
            "docs": "/docs"
        }
    }


@app.get("/healthz")
async def health():
    return {"status": "ok"}
