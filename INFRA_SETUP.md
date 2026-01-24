# Настройка инфраструктуры

## Изменения в инфраструктуре

Проект теперь использует:
- **Внешний PostgreSQL** (общий для нескольких проектов на сервере)
- **Внешний nginx** (общий для всех проектов)
- **Локальный Redis** (внутри docker-compose)

## Настройка .env файла

Создайте или обновите `.env` файл на сервере:

```bash
# Окружение
ENV=prod
DEBUG=false

# Подключение к внешнему PostgreSQL
# Вариант 1: Полный URL (рекомендуется)
DB_URL=postgresql+asyncpg://sst_user:your_password@your_postgres_host:5432/sst_db

# Вариант 2: Отдельные переменные (если не используете DB_URL)
# POSTGRES_HOST=your_postgres_host
# POSTGRES_PORT=5432
# POSTGRES_USER=sst_user
# POSTGRES_PASSWORD=your_password
# POSTGRES_DB=sst_db

# Redis (локальный контейнер)
REDIS_HOST=redis
REDIS_PORT=6379

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
SUPER_ADMIN_IDS=123456789,987654321

# pgAdmin (больше не используется, можно удалить)
# PGADMIN_EMAIL=admin@sst.local
# PGADMIN_PASSWORD=...
```

## Настройка nginx

Nginx уже настроен на сервере и ждёт название контейнера для проксирования.

Контейнер `sst_otbor` уже подключён к сети `infra_net` и имеет метку `nginx.proxy=true`.

Nginx должен проксировать запросы к контейнеру `sst_otbor` на порт `8000`.

Пример конфигурации nginx (если нужно настроить вручную):

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://sst_otbor:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Запуск сервисов

```bash
# Перейти в директорию проекта
cd ~/ct/sst_otbor

# Запустить сервисы
docker compose -f docker-compose.prod.yml up -d

# Проверить статус
docker compose -f docker-compose.prod.yml ps

# Просмотр логов
docker compose -f docker-compose.prod.yml logs -f backend bot redis
```

## Применение миграций БД

Теперь миграции применяются напрямую к внешнему PostgreSQL:

```bash
# Применить миграцию
psql -h YOUR_POSTGRES_HOST -p 5432 -U sst_user -d sst_db < migration/add_interview_days_structure.sql

# Или с паролем через переменную окружения
PGPASSWORD=your_password psql -h YOUR_POSTGRES_HOST -p 5432 -U sst_user -d sst_db < migration/add_interview_days_structure.sql
```

## Удалённые сервисы

Из `docker-compose.prod.yml` были удалены:
- `postgres` - теперь используется внешний PostgreSQL
- `pgadmin` - больше не нужен (используйте внешний инструмент для управления БД)

## Проверка подключения

```bash
# Проверить подключение к БД из контейнера backend
docker compose -f docker-compose.prod.yml exec backend python -c "
from db.engine import engine
import asyncio

async def test():
    async with engine.begin() as conn:
        result = await conn.execute('SELECT 1')
        print('✅ Подключение к БД работает!')

asyncio.run(test())
"

# Проверить подключение к Redis
docker compose -f docker-compose.prod.yml exec backend python -c "
from app.core.redis import redis_client
import asyncio

async def test():
    await redis_client.connect()
    await redis_client.client.ping()
    print('✅ Подключение к Redis работает!')
    await redis_client.disconnect()

asyncio.run(test())
"
```
