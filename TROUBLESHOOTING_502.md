# Диагностика и исправление 502 Bad Gateway

## Пошаговая инструкция

### Шаг 1: Проверка статуса контейнеров

```bash
cd ~/ct/sst_otbor
docker compose -f docker-compose.prod.yml ps
```

**Ожидаемый результат:**
- `sst_otbor` (backend) - Status: Up
- `sst_bot` - Status: Up
- `sst_redis` - Status: Up (healthy)
- `sst_pgadmin` - Status: Up

**Если контейнер не запущен:**
- Запишите имя контейнера и переходите к шагу 2

### Шаг 2: Проверка логов backend

```bash
docker compose -f docker-compose.prod.yml logs backend --tail=100
```

**Что искать:**
- `ERROR` - ошибки при запуске
- `ImportError` - проблемы с импортом модулей
- `ModuleNotFoundError` - отсутствующие зависимости
- `Connection refused` - проблемы с подключением к БД/Redis
- `Application startup complete` - успешный запуск

**Если видите ошибки:**
- Запишите текст ошибки
- Переходите к соответствующему шагу исправления

### Шаг 3: Проверка зависимостей

```bash
docker compose -f docker-compose.prod.yml exec backend pip list | grep -E "gspread|google-auth"
```

**Ожидаемый результат:**
```
gspread                   5.x.x
google-auth               2.x.x
google-auth-httplib2      0.x.x
google-auth-oauthlib      1.x.x
```

**Если зависимости отсутствуют:**
```bash
docker compose -f docker-compose.prod.yml exec backend pip install gspread google-auth google-auth-oauthlib google-auth-httplib2
```

### Шаг 4: Проверка доступности backend изнутри контейнера

```bash
docker compose -f docker-compose.prod.yml exec backend curl -I http://localhost:8000/healthz
```

**Ожидаемый результат:**
```
HTTP/1.1 200 OK
...
{"status":"ok"}
```

**Если не отвечает:**
- Backend не запустился или упал
- Смотрите логи (шаг 2)

### Шаг 5: Проверка сетевого подключения от Nginx

```bash
# Узнайте IP контейнера backend
docker inspect sst_otbor | grep -A 20 "Networks" | grep IPAddress

# Проверьте доступность из контейнера Nginx (если есть доступ)
docker exec <nginx_container> ping -c 2 sst_otbor
docker exec <nginx_container> curl -I http://sst_otbor:8000/healthz
```

**Ожидаемый результат:**
- Ping успешен
- HTTP запрос возвращает 200 OK

### Шаг 6: Полная перезагрузка (если нужно)

```bash
cd ~/ct/sst_otbor

# Остановить все контейнеры
docker compose -f docker-compose.prod.yml down

# Пересобрать образы (если были изменения в коде)
docker compose -f docker-compose.prod.yml build --no-cache backend bot

# Запустить контейнеры
docker compose -f docker-compose.prod.yml up -d

# Подождать 10-15 секунд для запуска
sleep 15

# Проверить статус
docker compose -f docker-compose.prod.yml ps

# Проверить логи
docker compose -f docker-compose.prod.yml logs backend --tail=50
```

### Шаг 7: Проверка работы после перезапуска

```bash
# Проверка health endpoint
docker compose -f docker-compose.prod.yml exec backend curl http://localhost:8000/healthz

# Проверка через браузер или curl
curl -I https://your-domain.com/healthz
```

## Частые проблемы и решения

### Проблема 1: Backend не запускается из-за отсутствия зависимостей

**Симптомы:**
```
ModuleNotFoundError: No module named 'gspread'
```

**Решение:**
```bash
# Установить зависимости
docker compose -f docker-compose.prod.yml exec backend pip install -r requirements.txt

# Перезапустить
docker compose -f docker-compose.prod.yml restart backend
```

### Проблема 2: Backend падает при импорте модулей

**Симптомы:**
```
ImportError: cannot import name 'google_sheets' from 'app.api.routers'
```

**Решение:**
```bash
# Проверить, что файл существует
docker compose -f docker-compose.prod.yml exec backend ls -la /app/app/api/routers/google_sheets.py

# Пересобрать образ
docker compose -f docker-compose.prod.yml build --no-cache backend
docker compose -f docker-compose.prod.yml up -d backend
```

### Проблема 3: Backend не может подключиться к БД

**Симптомы:**
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Решение:**
```bash
# Проверить переменные окружения
docker compose -f docker-compose.prod.yml exec backend env | grep DB_URL

# Проверить доступность БД
docker compose -f docker-compose.prod.yml exec backend ping -c 2 pgbouncer
```

### Проблема 4: Nginx не может найти контейнер backend

**Симптомы:**
```
connect() failed (111: Connection refused) while connecting to upstream
```

**Решение:**
```bash
# Проверить, что контейнер в правильной сети
docker inspect sst_otbor | grep -A 10 "Networks"

# Должна быть сеть infra_net
# Если нет - перезапустить с правильной конфигурацией

# Перезагрузить Nginx (если есть доступ)
docker exec <nginx_container> nginx -s reload
```

### Проблема 5: Backend запускается, но сразу падает

**Симптомы:**
- Контейнер постоянно перезапускается
- В логах ошибка приложения

**Решение:**
```bash
# Посмотреть последние логи перед падением
docker compose -f docker-compose.prod.yml logs backend --tail=200

# Проверить конфигурацию
docker compose -f docker-compose.prod.yml exec backend python -c "from app.main import app; print('OK')"
```

## Быстрая диагностика (все команды сразу)

```bash
cd ~/ct/sst_otbor

echo "=== Статус контейнеров ==="
docker compose -f docker-compose.prod.yml ps

echo -e "\n=== Логи backend (последние 50 строк) ==="
docker compose -f docker-compose.prod.yml logs backend --tail=50

echo -e "\n=== Проверка зависимостей ==="
docker compose -f docker-compose.prod.yml exec backend pip list | grep -E "gspread|google-auth" || echo "Зависимости не установлены!"

echo -e "\n=== Проверка health endpoint ==="
docker compose -f docker-compose.prod.yml exec backend curl -s http://localhost:8000/healthz || echo "Backend не отвечает!"

echo -e "\n=== IP адрес backend ==="
docker inspect sst_otbor | grep -A 5 "Networks" | grep IPAddress
```

## После исправления

1. Проверьте работу сайта в браузере
2. Проверьте работу API: `curl https://your-domain.com/api/v1/admin/check/1?telegram_id=YOUR_ID`
3. Проверьте логи на наличие ошибок: `docker compose -f docker-compose.prod.yml logs -f backend`
