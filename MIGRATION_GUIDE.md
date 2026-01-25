# Руководство по миграции на внешний PostgreSQL

## Что изменилось

1. ✅ Удалён сервис `postgres` из `docker-compose.prod.yml`
2. ✅ Удалён сервис `pgadmin` из `docker-compose.prod.yml`
3. ✅ Обновлены скрипты (убраны ссылки на postgres контейнер)
4. ✅ Обновлена документация

## Что нужно сделать на сервере

### 1. Обновить .env файл

Добавьте в `.env` на сервере:

```bash
# Подключение к внешнему PostgreSQL
DB_URL=postgresql+asyncpg://sst_user:your_password@your_postgres_host:5432/sst_db
```

Или используйте отдельные переменные:

```bash
POSTGRES_HOST=your_postgres_host
POSTGRES_PORT=5432
POSTGRES_USER=sst_user
POSTGRES_PASSWORD=your_password
POSTGRES_DB=sst_db
```

### 2. Остановить старые контейнеры

```bash
cd ~/ct/sst_otbor
docker compose -f docker-compose.prod.yml down
```

### 3. Удалить старые volumes (опционально, если не нужны данные)

```bash
docker volume rm sst_postgres_data sst_pgadmin_data
```

### 4. Запустить обновлённые сервисы

```bash
docker compose -f docker-compose.prod.yml up -d
```

### 5. Проверить работу

```bash
# Проверить логи
docker compose -f docker-compose.prod.yml logs -f backend bot redis

# Проверить подключение к БД
docker compose -f docker-compose.prod.yml exec backend python -c "
from db.engine import engine
import asyncio

async def test():
    async with engine.begin() as conn:
        result = await conn.execute('SELECT 1')
        print('✅ Подключение к БД работает!')

asyncio.run(test())
"
```

## Применение миграций через Alembic

Миграции применяются через Alembic (рекомендуемый способ):

```bash
# Перейти в директорию проекта
cd ~/ct/sst_otbor

# Убедиться, что .env файл настроен:
# DB_URL=postgresql+asyncpg://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db

# Применить все миграции до последней версии
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head

# Проверить текущую версию БД
docker compose -f docker-compose.prod.yml exec backend alembic current
```

Подробная инструкция в файле `ALEMBIC_SETUP.md`.

## Настройка nginx

Контейнер `sst_otbor` уже подключён к сети `infra_net` и имеет метку `nginx.proxy=true`.

Nginx должен проксировать запросы к контейнеру `sst_otbor:8000`.

Если nginx использует автоматическое обнаружение контейнеров, он должен автоматически подхватить `sst_otbor`.

Если нужно настроить вручную, добавьте в конфигурацию nginx:

```nginx
location / {
    proxy_pass http://sst_otbor:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Проверка сети

Убедитесь, что сеть `infra_net` существует:

```bash
docker network ls | grep infra_net
```

Если сети нет, создайте её:

```bash
docker network create infra_net
```

## Откат изменений (если что-то пошло не так)

Если нужно вернуться к старой конфигурации:

1. Восстановите старую версию `docker-compose.prod.yml` из git
2. Запустите: `docker compose -f docker-compose.prod.yml up -d`
