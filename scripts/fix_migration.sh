#!/bin/bash
# Скрипт для безопасного отката и повторного применения миграции

set -e

echo "🔍 Проверка текущего статуса миграции..."
docker exec -it sst_otbor alembic current
echo ""

echo "⚠️  ВНИМАНИЕ: Следующие шаги могут удалить временные данные миграции!"
echo "   Это безопасно, так как данные будут восстановлены из administrators"
echo ""
read -p "Продолжить? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Отменено"
    exit 1
fi

echo ""
echo "📋 Шаг 1: Откат последней миграции..."
docker exec -it sst_otbor alembic downgrade -1 || {
    echo "⚠️  Откат не удался. Возможно, миграция не была применена полностью."
    echo "   Продолжаем с ручной очисткой..."
    
    echo ""
    echo "📋 Шаг 2: Ручная очистка частично созданных объектов..."
    
    # Подключаемся к БД через контейнер
    # Копируем скрипт в контейнер и выполняем
    docker cp scripts/cleanup_migration.py sst_otbor:/tmp/cleanup_migration.py
    docker exec sst_otbor python3 /tmp/cleanup_migration.py
    docker exec sst_otbor rm /tmp/cleanup_migration.py
}

echo ""
echo "📋 Шаг 3: Применение исправленной миграции..."
docker exec -it sst_otbor alembic upgrade head

echo ""
echo "✅ Готово! Проверьте статус:"
docker exec -it sst_otbor alembic current
