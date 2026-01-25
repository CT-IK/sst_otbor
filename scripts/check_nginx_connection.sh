#!/bin/bash
# Проверка подключения Nginx к backend

echo "=========================================="
echo "🔍 ПРОВЕРКА ПОДКЛЮЧЕНИЯ NGINX -> BACKEND"
echo "=========================================="

echo -e "\n1. IP адрес backend контейнера:"
BACKEND_IP=$(docker inspect sst_otbor 2>/dev/null | grep -A 5 "Networks" | grep IPAddress | head -1 | awk '{print $2}' | tr -d '",')
if [ -z "$BACKEND_IP" ]; then
    echo "❌ Не удалось получить IP адрес контейнера sst_otbor"
    echo "   Проверьте, что контейнер запущен: docker ps | grep sst_otbor"
    exit 1
fi
echo "   IP: $BACKEND_IP"

echo -e "\n2. Сети backend контейнера:"
docker inspect sst_otbor 2>/dev/null | grep -A 10 "Networks" | grep -E "infra_net|internal" || echo "   ⚠️  Сети не найдены"

echo -e "\n3. Проверка доступности backend изнутри контейнера:"
if docker compose -f docker-compose.prod.yml exec -T backend curl -s -f http://localhost:8000/healthz > /dev/null 2>&1; then
    echo "   ✅ Backend отвечает на localhost:8000"
    docker compose -f docker-compose.prod.yml exec -T backend curl -s http://localhost:8000/healthz
else
    echo "   ❌ Backend НЕ отвечает на localhost:8000"
fi

echo -e "\n4. Проверка доступности по имени контейнера (из другого контейнера):"
# Попробуем из redis контейнера (он в той же сети)
if docker compose -f docker-compose.prod.yml exec -T redis ping -c 2 sst_otbor > /dev/null 2>&1; then
    echo "   ✅ Контейнер sst_otbor доступен по имени в сети"
    docker compose -f docker-compose.prod.yml exec -T redis ping -c 2 sst_otbor
else
    echo "   ❌ Контейнер sst_otbor НЕ доступен по имени"
fi

echo -e "\n5. Проверка подключения к порту 8000 по имени контейнера:"
if docker compose -f docker-compose.prod.yml exec -T redis nc -zv sst_otbor 8000 2>&1 | grep -q "succeeded"; then
    echo "   ✅ Порт 8000 доступен на sst_otbor"
else
    echo "   ❌ Порт 8000 НЕ доступен на sst_otbor"
    docker compose -f docker-compose.prod.yml exec -T redis nc -zv sst_otbor 8000 2>&1
fi

echo -e "\n6. Информация о сети infra_net:"
if docker network inspect infra_net > /dev/null 2>&1; then
    echo "   ✅ Сеть infra_net существует"
    echo "   Контейнеры в сети infra_net:"
    docker network inspect infra_net 2>/dev/null | grep -A 5 "Containers" | grep "Name" | head -5
    echo "   Backend в сети:"
    docker network inspect infra_net 2>/dev/null | grep -A 10 "sst_otbor" || echo "   ❌ sst_otbor НЕ в сети infra_net!"
else
    echo "   ❌ Сеть infra_net НЕ существует!"
    echo "   Создайте её: docker network create infra_net"
fi

echo -e "\n7. Рекомендации:"
echo "   - Если backend не в сети infra_net, перезапустите:"
echo "     docker compose -f docker-compose.prod.yml down"
echo "     docker compose -f docker-compose.prod.yml up -d"
echo ""
echo "   - Если Nginx не может подключиться, проверьте конфигурацию Nginx:"
echo "     proxy_pass должен указывать на: http://sst_otbor:8000"
echo ""
echo "   - Перезагрузите Nginx после изменений:"
echo "     docker exec <nginx_container> nginx -s reload"

echo -e "\n=========================================="
