# 🚀 Деплой с Traefik (рекомендуемый способ)

**Преимущества:**
- ✅ Автоматические SSL сертификаты
- ✅ Не нужно писать nginx конфиги
- ✅ Добавление нового проекта = 4 строки labels
- ✅ Dashboard для мониторинга

---

## 1. Первоначальная настройка Traefik

```bash
# На сервере
mkdir -p ~/infra
cd ~/infra

# Создай docker-compose.yml (скопируй из infra-example/)
nano docker-compose.yml
```

**Содержимое `~/infra/docker-compose.yml`:**
```yaml
services:
  traefik:
    image: traefik:v3.0
    container_name: traefik
    restart: always
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--providers.docker.network=web"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--certificatesresolvers.letsencrypt.acme.tlschallenge=true"
      - "--certificatesresolvers.letsencrypt.acme.email=твой@email.ru"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik_letsencrypt:/letsencrypt
    networks:
      - web

volumes:
  traefik_letsencrypt:

networks:
  web:
    name: web
```

```bash
# Запуск Traefik
docker-compose up -d
```

---

## 2. Деплой SST проекта

```bash
cd ~
git clone <URL> sst_big_otbor
cd sst_big_otbor

# Создай .env
cat > .env << 'EOF'
ENV=prod
DEBUG=false
POSTGRES_USER=sst_user
POSTGRES_PASSWORD=SuperSecretPassword123!
POSTGRES_DB=sst_db
TELEGRAM_BOT_TOKEN=твой_токен
SUPER_ADMIN_IDS=твой_telegram_id
EOF

# Запуск с Traefik
docker-compose -f docker-compose.traefik.yml up -d --build

# Миграции
docker-compose -f docker-compose.traefik.yml exec backend alembic upgrade head
```

**Готово!** Через ~30 секунд:
- https://putevod-ik.ru — работает с SSL
- Бот отвечает на `/start`

---

## 3. Добавление нового проекта

Просто добавь labels в любой сервис:

```yaml
services:
  myapp:
    image: myapp:latest
    networks:
      - web
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.myapp.rule=Host(`my-domain.ru`)"
      - "traefik.http.routers.myapp.entrypoints=websecure"
      - "traefik.http.routers.myapp.tls.certresolver=letsencrypt"

networks:
  web:
    external: true
```

SSL получится автоматически!

---

## Полезные команды

```bash
# Логи Traefik
docker logs -f traefik

# Логи SST
cd ~/sst_big_otbor
docker-compose -f docker-compose.traefik.yml logs -f

# Обновление проекта
git pull
docker-compose -f docker-compose.traefik.yml up -d --build

# Список запущенных контейнеров
docker ps

# Проверить сертификаты
curl -I https://putevod-ik.ru
```

---

## Сравнение с nginx

| | Nginx | Traefik |
|---|---|---|
| Новый домен | Писать конфиг, reload | 4 строки labels |
| SSL | certbot вручную | Автоматически |
| Конфиг | Файлы | Docker labels |
| Обновление | reload | Автоматически |

