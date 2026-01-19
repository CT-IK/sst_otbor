#!/bin/bash
# Пересборка bot с применением изменений в коде

set -e

echo "🔨 Пересборка bot..."

cd ~/ct/sst_otbor || cd "$(dirname "$0")/.."

echo "📦 Останавливаю bot..."
docker-compose -f docker-compose.prod.yml stop bot

echo "🔨 Собираю новый образ bot..."
docker-compose -f docker-compose.prod.yml build --no-cache bot

echo "🚀 Запускаю bot..."
docker-compose -f docker-compose.prod.yml up -d bot

echo "📋 Статус:"
docker-compose -f docker-compose.prod.yml ps bot

echo ""
echo "✅ Bot пересобран и запущен!"
echo "📝 Логи: docker-compose -f docker-compose.prod.yml logs -f bot"
