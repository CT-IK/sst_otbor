#!/bin/bash
# Скрипт для диагностики проблем с backend

cd ~/ct/sst_otbor || cd "$(dirname "$0")/.."

echo "=========================================="
echo "🔍 ДИАГНОСТИКА BACKEND"
echo "=========================================="

echo -e "\n📊 1. Статус контейнеров:"
docker compose -f docker-compose.prod.yml ps

echo -e "\n📋 2. Логи backend (последние 30 строк):"
docker compose -f docker-compose.prod.yml logs backend --tail=30

echo -e "\n📦 3. Проверка зависимостей Google Sheets:"
if docker compose -f docker-compose.prod.yml exec -T backend pip list 2>/dev/null | grep -E "gspread|google-auth" > /dev/null; then
    echo "✅ Зависимости установлены:"
    docker compose -f docker-compose.prod.yml exec -T backend pip list | grep -E "gspread|google-auth"
else
    echo "❌ Зависимости НЕ установлены!"
    echo "   Установите: pip install gspread google-auth google-auth-oauthlib google-auth-httplib2"
fi

echo -e "\n🏥 4. Проверка health endpoint:"
if docker compose -f docker-compose.prod.yml exec -T backend curl -s -f http://localhost:8000/healthz > /dev/null 2>&1; then
    echo "✅ Backend отвечает на /healthz"
    docker compose -f docker-compose.prod.yml exec -T backend curl -s http://localhost:8000/healthz
else
    echo "❌ Backend НЕ отвечает на /healthz"
fi

echo -e "\n🌐 5. Сетевая информация:"
if docker inspect sst_otbor > /dev/null 2>&1; then
    echo "IP адрес backend:"
    docker inspect sst_otbor 2>/dev/null | grep -A 5 "Networks" | grep IPAddress | head -1
    echo "Сети backend:"
    docker inspect sst_otbor 2>/dev/null | grep -A 10 "Networks" | grep -E "infra_net|internal" || echo "   (не найдено)"
else
    echo "❌ Контейнер sst_otbor не найден"
fi

echo -e "\n🔧 6. Проверка импорта модулей:"
if docker compose -f docker-compose.prod.yml exec -T backend python -c "from app.main import app; print('✅ Импорт успешен')" 2>&1; then
    echo ""
else
    echo "❌ Ошибка импорта модулей (см. выше)"
fi

echo -e "\n=========================================="
echo "✅ Диагностика завершена"
echo "=========================================="
