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


@app.get("/healthz")
async def health():
    return {"status": "ok"}
