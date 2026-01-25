# Настройка pgAdmin

## Запуск pgAdmin

pgAdmin добавлен в `docker-compose.prod.yml` и будет доступен после запуска:

```bash
docker compose -f docker-compose.prod.yml up -d pgadmin
```

## Доступ к pgAdmin

1. **Локально (если на сервере):**
   - Откройте браузер: `http://localhost:5050`

2. **Через SSH туннель (если удаленно):**
   ```bash
   ssh -L 5050:localhost:5050 user@your-server
   ```
   Затем откройте: `http://localhost:5050`

3. **Через Nginx (рекомендуется для продакшена):**
   - Добавьте конфигурацию в nginx для доступа через домен
   - Уберите `ports` из docker-compose.prod.yml

## Первый вход

1. **Email:** Значение из `.env` переменной `PGADMIN_EMAIL` (по умолчанию: `admin@example.com`)
2. **Password:** Значение из `.env` переменной `PGADMIN_PASSWORD` (по умолчанию: `admin`)

⚠️ **ВАЖНО:** В продакшене обязательно измените пароль по умолчанию!

## Настройка подключения к PostgreSQL

После входа в pgAdmin:

1. **Правый клик на "Servers" → "Register" → "Server"**

2. **Вкладка "General":**
   - **Name:** `SST Otbor Database` (или любое удобное имя)

3. **Вкладка "Connection":**
   - **Host name/address:** 
     - Если PostgreSQL в той же сети `infra_net` - используйте имя контейнера/сервиса (например, `postgres` или `pgbouncer`)
     - Если внешний PostgreSQL - используйте IP или домен
   - **Port:** `5432` (прямое подключение) или `6432` (через pgbouncer)
   - **Maintenance database:** `postgres` (или ваша БД)
   - **Username:** Из `.env` (`POSTGRES_USER` или из `DB_URL`)
   - **Password:** Из `.env` (`POSTGRES_PASSWORD` или из `DB_URL`)
   - ✅ **Save password** (чтобы не вводить каждый раз)

4. **Вкладка "Advanced" (опционально):**
   - **DB restriction:** Укажите имя вашей БД (`sst_otbor_db`), чтобы видеть только её

5. Нажмите **"Save"**

## Определение параметров подключения

Если не знаете точные параметры, посмотрите в `.env`:

```bash
# Если используется DB_URL:
DB_URL=postgresql+asyncpg://user:password@host:port/database

# Или отдельные переменные:
POSTGRES_HOST=...
POSTGRES_PORT=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...
POSTGRES_DB=...
```

**Важно:** 
- pgAdmin подключается **напрямую к PostgreSQL**, а не через pgbouncer
- Если используете pgbouncer, нужно найти реальный хост PostgreSQL
- Обычно это либо имя контейнера в сети `infra_net`, либо IP адрес

## Проверка подключения

После настройки:
1. Разверните сервер в левой панели
2. Разверните "Databases"
3. Должна быть видна ваша база данных (`sst_otbor_db`)

## Безопасность

Для продакшена:

1. **Измените пароль pgAdmin:**
   ```bash
   # В .env добавьте:
   PGADMIN_EMAIL=your-email@example.com
   PGADMIN_PASSWORD=strong-password-here
   ```

2. **Ограничьте доступ через Nginx:**
   - Уберите `ports: - "5050:80"` из docker-compose.prod.yml
   - Добавьте конфигурацию в nginx с аутентификацией
   - Используйте HTTPS

3. **Ограничьте доступ по IP:**
   - Используйте firewall для ограничения доступа к порту 5050
   - Или используйте только SSH туннель

## Пример конфигурации Nginx

Если хотите доступ через домен:

```nginx
server {
    listen 80;
    server_name pgadmin.yourdomain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name pgadmin.yourdomain.com;
    
    ssl_certificate /etc/nginx/certs/yourdomain.com/fullchain.crt;
    ssl_certificate_key /etc/nginx/certs/yourdomain.com/privkey.key;
    
    # Базовая аутентификация (опционально)
    auth_basic "Restricted Access";
    auth_basic_user_file /etc/nginx/.htpasswd;
    
    location / {
        proxy_pass http://sst_pgadmin:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Устранение проблем

### pgAdmin не может подключиться к PostgreSQL

1. **Проверьте сеть:**
   ```bash
   docker exec sst_pgadmin ping -c 2 <postgres-host>
   ```

2. **Проверьте доступность порта:**
   ```bash
   docker exec sst_pgadmin nc -zv <postgres-host> 5432
   ```

3. **Проверьте логи:**
   ```bash
   docker compose -f docker-compose.prod.yml logs pgadmin
   ```

### Забыли пароль pgAdmin

1. Остановите контейнер:
   ```bash
   docker compose -f docker-compose.prod.yml stop pgadmin
   ```

2. Удалите volume (⚠️ потеряете все настройки):
   ```bash
   docker compose -f docker-compose.prod.yml rm -v pgadmin
   docker volume rm sst_big_otbor_pgadmin_data
   ```

3. Запустите заново с новыми параметрами в `.env`
