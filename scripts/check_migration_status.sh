#!/bin/bash
# Скрипт для проверки статуса миграции и безопасной очистки

set -e

echo "🔍 Проверка параметров подключения к БД..."

# Загружаем переменные из .env
if [ -f .env ]; then
    source .env
else
    echo "❌ Файл .env не найден!"
    exit 1
fi

# Парсим DB_URL или используем отдельные переменные
if [ -n "$DB_URL" ]; then
    # Формат: postgresql+asyncpg://user:password@host:port/dbname
    if [[ $DB_URL =~ postgresql.*://([^:]+):([^@]+)@([^:]+):([^/]+)/(.+) ]]; then
        DB_USER="${BASH_REMATCH[1]}"
        DB_PASS="${BASH_REMATCH[2]}"
        DB_HOST="${BASH_REMATCH[3]}"
        DB_PORT="${BASH_REMATCH[4]}"
        DB_NAME="${BASH_REMATCH[5]}"
    else
        echo "❌ Не удалось распарсить DB_URL"
        exit 1
    fi
else
    DB_USER="${POSTGRES_USER:-postgres}"
    DB_PASS="${POSTGRES_PASSWORD:-}"
    DB_HOST="${POSTGRES_HOST:-localhost}"
    DB_PORT="${POSTGRES_PORT:-5432}"
    DB_NAME="${POSTGRES_DB:-postgres}"
fi

echo "📊 Параметры подключения:"
echo "   Host: $DB_HOST"
echo "   Port: $DB_PORT"
echo "   User: $DB_USER"
echo "   Database: $DB_NAME"
echo ""

# Проверяем статус миграции
echo "🔍 Проверка статуса миграции..."
docker exec -it sst_otbor alembic current || echo "⚠️  Не удалось получить текущую версию миграции"
echo ""

# Проверяем, существует ли таблица interviewers
echo "🔍 Проверка существующих таблиц..."
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'interviewers') 
        THEN '✅ Таблица interviewers существует'
        ELSE '❌ Таблица interviewers не существует'
    END as status;
" 2>/dev/null || echo "⚠️  Не удалось подключиться к БД"
echo ""

# Проверяем временные колонки
echo "🔍 Проверка временных колонок..."
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT 
    CASE 
        WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'interviewer_schedule' AND column_name = 'old_interviewer_id') 
        THEN '⚠️  Временная колонка old_interviewer_id существует в interviewer_schedule'
        ELSE '✅ Временная колонка old_interviewer_id отсутствует в interviewer_schedule'
    END as status;
" 2>/dev/null || echo "⚠️  Не удалось проверить колонки"
echo ""

# Показываем, что будет удалено
echo "📋 Что будет удалено при очистке:"
echo ""
echo "1. Таблица 'interviewers' (если существует)"
echo "   ⚠️  ВНИМАНИЕ: Это удалит всех проводящих собеседования!"
echo "   ⚠️  Но данные будут восстановлены при повторной миграции из administrators"
echo ""
echo "2. Временная колонка 'old_interviewer_id' из 'interviewer_schedule'"
echo "   ✅ Безопасно - это временная колонка для миграции"
echo ""
echo "3. Временная колонка 'old_interviewer_id' из 'interview_interviewers'"
echo "   ✅ Безопасно - это временная колонка для миграции"
echo ""
echo "💡 Рекомендация:"
echo "   Если миграция частично выполнилась, лучше откатить её:"
echo "   docker exec -it sst_otbor alembic downgrade -1"
echo ""
echo "   Затем применить заново:"
echo "   docker exec -it sst_otbor alembic upgrade head"
echo ""
