#!/bin/bash
# Пересборка backend с применением изменений в коде

set -e

echo "🔨 Пересборка backend..."

cd ~/ct/sst_otbor || cd "$(dirname "$0")/.."

echo "📦 Останавливаю backend..."
docker-compose -f docker-compose.prod.yml stop backend

echo "🔨 Собираю новый образ backend..."
docker-compose -f docker-compose.prod.yml build --no-cache backend

echo "🚀 Запускаю backend..."
docker-compose -f docker-compose.prod.yml up -d backend

echo "📋 Статус:"
docker-compose -f docker-compose.prod.yml ps backend

echo ""
echo "✅ Backend пересобран и запущен!"
echo "📝 Логи: docker-compose -f docker-compose.prod.yml logs -f backend"
