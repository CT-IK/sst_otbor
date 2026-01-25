# Первоначальная настройка БД на сервере

## Быстрый старт

После создания новой базы данных `sst_otbor_db` нужно применить все миграции через Alembic.

### 1. Настроить .env файл

На сервере в `~/ct/sst_otbor/.env`:

```bash
ENV=prod
DEBUG=false

# Подключение через pgbouncer
DB_URL=postgresql+asyncpg://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db

REDIS_HOST=redis
REDIS_PORT=6379

TELEGRAM_BOT_TOKEN=your_bot_token
SUPER_ADMIN_IDS=123456789,987654321
```

### 2. Создать миграцию для interview_days (если ещё не создана)

```bash
cd ~/ct/sst_otbor

# Создать миграцию автоматически на основе моделей
docker compose -f docker-compose.prod.yml exec backend alembic revision --autogenerate -m "add interview days and time slots"
```

### 3. Применить все миграции

```bash
# Применить все миграции до последней версии
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 4. Проверить результат

```bash
# Проверить текущую версию БД
docker compose -f docker-compose.prod.yml exec backend alembic current

# Проверить таблицы в БД
psql "postgresql://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db" -c "\dt"

# Должны быть таблицы:
# - faculty
# - administrators
# - users
# - questionnaires
# - interview_days (новая)
# - time_slots (новая)
# - time_slot_availability (новая)
# - и другие...
```

## Если что-то пошло не так

### Ошибка подключения к БД

Проверьте:
- Правильность строки подключения в `.env`
- Доступность pgbouncer на порту 6432
- Правильность имени БД и учётных данных

### Миграция не создаётся

Если `alembic revision --autogenerate` не видит изменений:

1. Убедитесь, что модели в `db/models.py` содержат `InterviewDay`, `TimeSlot`, `TimeSlotAvailability`
2. Проверьте, что все импорты корректны
3. Попробуйте создать миграцию вручную (см. `ALEMBIC_SETUP.md`)

### Откат миграций

Если нужно откатить:

```bash
# Откатить одну миграцию
docker compose -f docker-compose.prod.yml exec backend alembic downgrade -1

# Откатить все
docker compose -f docker-compose.prod.yml exec backend alembic downgrade base
```

## Дополнительная информация

- Подробная инструкция по Alembic: `ALEMBIC_SETUP.md`
- Настройка инфраструктуры: `INFRA_SETUP.md`
- Применение изменений для interview_days: `APPLY_INTERVIEW_DAYS.md`
