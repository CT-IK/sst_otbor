# Backend + Mini App Frontend
FROM python:3.12-slim-bookworm

WORKDIR /app

# Установка зависимостей системы (с retry для стабильности)
RUN apt-get update --fix-missing \
    && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Копируем requirements и устанавливаем зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Порт FastAPI
EXPOSE 8000

# Запуск с gunicorn + uvicorn workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

