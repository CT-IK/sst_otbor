# Backend + Mini App Frontend
FROM python:3.12-slim

WORKDIR /app

# Копируем requirements и устанавливаем зависимости Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Порт FastAPI
EXPOSE 8000

# Запуск
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
