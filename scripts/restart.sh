#!/bin/bash
# Быстрый перезапуск без пересборки

cd ~/ct/sst_otbor

echo "🔄 Перезапуск контейнеров..."
docker-compose -f docker-compose.prod.yml restart

echo "📋 Статус:"
docker-compose -f docker-compose.prod.yml ps
