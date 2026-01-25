# Настройка и применение миграций через Alembic

## Первоначальная настройка БД

После создания новой базы данных нужно применить все миграции:

```bash
# Перейти в директорию проекта
cd ~/ct/sst_otbor

# Убедиться, что .env файл настроен с правильной строкой подключения
# DB_URL=postgresql+asyncpg://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db

# Применить все миграции
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

## Строка подключения

Проект использует **pgbouncer** на порту **6432** для подключения к PostgreSQL.

Формат строки подключения:
```
postgresql+asyncpg://sst_user:cheburashaka_blya@127.0.0.1:6432/sst_otbor_db
```

Где:
- `sst_user` - пользователь БД
- `cheburashaka_blya` - пароль
- `127.0.0.1:6432` - адрес pgbouncer (localhost, порт 6432)
- `sst_otbor_db` - название базы данных

## Основные команды Alembic

### Применение миграций

```bash
# Применить все миграции до последней версии
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head

# Применить одну миграцию
docker compose -f docker-compose.prod.yml exec backend alembic upgrade +1

# Применить до конкретной версии
docker compose -f docker-compose.prod.yml exec backend alembic upgrade <revision_id>
```

### Проверка состояния

```bash
# Текущая версия БД
docker compose -f docker-compose.prod.yml exec backend alembic current

# История миграций
docker compose -f docker-compose.prod.yml exec backend alembic history

# История с подробностями
docker compose -f docker-compose.prod.yml exec backend alembic history --verbose
```

### Откат миграций

```bash
# Откатить одну миграцию
docker compose -f docker-compose.prod.yml exec backend alembic downgrade -1

# Откатить до конкретной версии
docker compose -f docker-compose.prod.yml exec backend alembic downgrade <revision_id>

# Откатить все миграции
docker compose -f docker-compose.prod.yml exec backend alembic downgrade base
```

### Создание новых миграций

```bash
# Автоматически создать миграцию на основе изменений в моделях
docker compose -f docker-compose.prod.yml exec backend alembic revision --autogenerate -m "описание изменений"

# Создать пустую миграцию (для ручных изменений)
docker compose -f docker-compose.prod.yml exec backend alembic revision -m "описание изменений"
```

## Работа локально (без Docker)

Если у вас настроен локальный Python и .env файл:

```bash
# Активировать виртуальное окружение
source venv/bin/activate  # или venv\Scripts\activate на Windows

# Применить миграции
alembic upgrade head

# Проверить текущую версию
alembic current

# Создать новую миграцию
alembic revision --autogenerate -m "описание изменений"
```

## Существующие миграции

В проекте уже есть следующие миграции:

1. **8adb9fe323f1** - `initial` - начальная схема БД (таблицы: faculty, administrators, users, questionnaires, и т.д.)
2. **add_video_stage_fields** - добавление полей для этапа видео
3. **dffec56257a2** - сделать поля админа опциональными

## Важные замечания

1. **Всегда делайте бэкап БД** перед применением миграций в продакшене
2. **Проверяйте миграции** перед применением (особенно autogenerate)
3. **Не редактируйте применённые миграции** - создавайте новые
4. **Используйте транзакции** для критичных миграций

## Устранение проблем

### Ошибка подключения к БД

Проверьте:
- Правильность строки подключения в `.env`
- Доступность pgbouncer на порту 6432
- Правильность имени БД и учётных данных

### Конфликт версий миграций

Если миграции не применяются из-за конфликта:

```bash
# Проверить текущую версию
docker compose -f docker-compose.prod.yml exec backend alembic current

# Посмотреть историю
docker compose -f docker-compose.prod.yml exec backend alembic history

# Если нужно, откатить и применить заново
docker compose -f docker-compose.prod.yml exec backend alembic downgrade -1
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### Проблемы с asyncpg и pgbouncer

Если возникают проблемы с подключением через pgbouncer:

1. Убедитесь, что используется `postgresql+asyncpg://` в строке подключения
2. Проверьте, что pgbouncer настроен на правильный pool_mode (обычно `transaction`)
3. При необходимости можно подключиться напрямую к PostgreSQL (минуя pgbouncer) для миграций
