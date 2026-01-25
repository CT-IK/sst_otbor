#!/bin/bash
# Полная перезагрузка с пересборкой

cd ~/ct/sst_otbor || cd "$(dirname "$0")/.."

echo "🛑 Остановка контейнеров..."
docker compose -f docker-compose.prod.yml down

echo -e "\n🔨 Пересборка образов..."
docker compose -f docker-compose.prod.yml build --no-cache backend bot

echo -e "\n🚀 Запуск контейнеров..."
docker compose -f docker-compose.prod.yml up -d

echo -e "\n⏳ Ожидание запуска (15 секунд)..."
sleep 15

echo -e "\n📊 Статус контейнеров:"
docker compose -f docker-compose.prod.yml ps

echo -e "\n📋 Логи backend (последние 20 строк):"
docker compose -f docker-compose.prod.yml logs backend --tail=20

echo -e "\n✅ Перезагрузка завершена!"
echo "Для диагностики запустите: ./scripts/diagnose.sh"
