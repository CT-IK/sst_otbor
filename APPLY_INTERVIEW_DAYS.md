# Применение изменений для дней собеседований

## Шаги для применения:

### 1. Создать миграцию для interview_days (если ещё не создана)

Если миграция для interview_days ещё не создана через Alembic:

```bash
# Перейти в директорию проекта
cd ~/ct/sst_otbor

# Создать миграцию автоматически на основе моделей
docker compose -f docker-compose.prod.yml exec backend alembic revision --autogenerate -m "add interview days and time slots"

# Проверить созданную миграцию в migration/versions/
```

### 2. Применить миграцию БД через Alembic

```bash
# Убедиться, что .env файл настроен:
# DB_URL=postgresql+asyncpg://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db

# Применить все миграции до последней версии
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head

# Проверить текущую версию БД
docker compose -f docker-compose.prod.yml exec backend alembic current
```

### 3. Пересобрать и перезапустить backend

```bash
# Пересобрать backend контейнер
docker compose -f docker-compose.prod.yml build --no-cache backend

# Перезапустить backend
docker compose -f docker-compose.prod.yml up -d backend
```

Или использовать скрипт:

```bash
./scripts/rebuild_backend.sh
```

### 4. Проверить, что всё работает

```bash
# Проверить логи backend
docker compose -f docker-compose.prod.yml logs -f backend --tail=50

# Проверить, что API доступен
curl http://localhost:8000/api/v1/interview-days/1?telegram_id=YOUR_TELEGRAM_ID
```

### 5. Проверить структуру БД

```bash
# Подключиться к PostgreSQL через pgbouncer
psql "postgresql://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db"

# Проверить таблицы
\dt interview_days
\dt time_slots
\dt time_slot_availability

# Проверить структуру таблицы
\d interview_days

# Выйти
\q
```

## Что было добавлено:

1. **Новые таблицы:**
   - `interview_days` - дни собеседований
   - `time_slots` - временные слоты (10:00-22:00)
   - `time_slot_availability` - доступность проверяющих

2. **Новое поле в `interviews`:**
   - `time_slot_id` - связь с временным слотом

3. **Новые API эндпоинты:**
   - `GET /api/v1/interview-days/{faculty_id}` - список дней
   - `POST /api/v1/interview-days/{faculty_id}` - создать день
   - `PUT /api/v1/interview-days/time-slots/{time_slot_id}` - установить количество мест
   - `POST /api/v1/interview-days/time-slots/{time_slot_id}/availability` - отметить доступность
   - `GET /api/v1/interview-days/time-slots/{time_slot_id}/availability` - список доступных проверяющих

## Если что-то пошло не так:

1. Проверьте логи backend:
   ```bash
   docker compose -f docker-compose.prod.yml logs backend --tail=100
   ```

2. Проверьте, что миграция применилась:
   ```bash
   # Через pgbouncer
   psql "postgresql://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db" -c "\d interview_days"
   
   # Или через Alembic
   docker compose -f docker-compose.prod.yml exec backend alembic current
   ```

3. Если нужно откатить миграцию (осторожно!):
   ```sql
   DROP TABLE IF EXISTS time_slot_availability CASCADE;
   DROP TABLE IF EXISTS time_slots CASCADE;
   DROP TABLE IF EXISTS interview_days CASCADE;
   ALTER TABLE interviews DROP COLUMN IF EXISTS time_slot_id;
   ```
