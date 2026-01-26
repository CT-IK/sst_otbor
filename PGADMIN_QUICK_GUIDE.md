# Быстрый гайд по pgAdmin

## Доступ к pgAdmin

### Вариант 1: Локально (если на сервере)

```bash
# Откройте в браузере
http://localhost:5050
```

### Вариант 2: Через SSH туннель (если удалённо)

```bash
# На вашем локальном компьютере выполните:
ssh -L 5050:localhost:5050 user@your-server

# Затем откройте в браузере:
http://localhost:5050
```

## Вход в pgAdmin

1. **Email:** Значение из `.env` переменной `PGADMIN_EMAIL` (по умолчанию: `admin@example.com`)
2. **Password:** Значение из `.env` переменной `PGADMIN_PASSWORD` (по умолчанию: `admin`)

## Настройка подключения к PostgreSQL

1. **Правый клик на "Servers" → "Register" → "Server"**

2. **Вкладка "General":**
   - **Name:** `SST Otbor Database` (или любое удобное имя)

3. **Вкладка "Connection":**
   - **Host name/address:** 
     - Если PostgreSQL в сети `infra_net` - используйте имя контейнера (например, `postgres` или `pgbouncer`)
     - Если внешний PostgreSQL - используйте IP или домен
   - **Port:** `5432` (прямое подключение) или `6432` (через pgbouncer)
   - **Maintenance database:** `postgres` (или ваша БД)
   - **Username:** Из `.env` (`POSTGRES_USER` или из `DB_URL`)
   - **Password:** Из `.env` (`POSTGRES_PASSWORD` или из `DB_URL`)
   - ✅ **Save password**

4. Нажмите **"Save"**

## Изменение названия факультета

1. **Разверните сервер** в левой панели
2. **Разверните "Databases"**
3. **Разверните вашу базу данных** (например, `sst_otbor_db`)
4. **Разверните "Schemas" → "public" → "Tables"**
5. **Найдите таблицу `faculty`**
6. **Правый клик на `faculty` → "View/Edit Data" → "All Rows"**
7. **Найдите нужный факультет** (по `id` или текущему `name`)
8. **Дважды кликните на ячейку `name`** и введите новое название
9. **Нажмите Enter** или кликните вне ячейки
10. **Нажмите кнопку "Save"** (дискета) в верхней панели

## Альтернативный способ (через SQL)

1. **Правый клик на таблице `faculty` → "Query Tool"**
2. **Выполните SQL запрос:**

```sql
-- Посмотреть все факультеты
SELECT id, name FROM faculty;

-- Изменить название факультета (замените ID и новое название)
UPDATE faculty 
SET name = 'Новое название' 
WHERE id = 1;

-- Проверить результат
SELECT id, name FROM faculty WHERE id = 1;
```

3. **Нажмите F5** или кнопку "Execute" (▶️) для выполнения запроса

## Проверка параметров подключения

Если не знаете параметры подключения, проверьте `.env`:

```bash
cat .env | grep -E "POSTGRES|DB_URL"
```

Или посмотрите в контейнере:

```bash
docker compose -f docker-compose.prod.yml exec backend env | grep -E "POSTGRES|DB_URL"
```

## Устранение проблем

### pgAdmin не открывается

```bash
# Проверьте статус контейнера
docker compose -f docker-compose.prod.yml ps pgadmin

# Проверьте логи
docker compose -f docker-compose.prod.yml logs pgadmin --tail=50

# Перезапустите
docker compose -f docker-compose.prod.yml restart pgadmin
```

### Не могу подключиться к PostgreSQL

1. Проверьте, что PostgreSQL доступен из контейнера pgAdmin:
   ```bash
   docker compose -f docker-compose.prod.yml exec pgadmin ping -c 2 <postgres-host>
   ```

2. Проверьте порт:
   ```bash
   docker compose -f docker-compose.prod.yml exec pgadmin nc -zv <postgres-host> 5432
   ```

3. Убедитесь, что pgAdmin в правильной сети:
   ```bash
   docker network inspect infra_net | grep pgadmin
   ```
