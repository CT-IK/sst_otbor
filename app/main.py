from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(title="Backend for winter app")


@app.get("/healthz")
async def health():
    return {"status": "ok"}
