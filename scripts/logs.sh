#!/bin/bash
# Просмотр логов

cd ~/ct/sst_otbor || cd "$(dirname "$0")/.."

if [ -z "$1" ]; then
    echo "Все логи (без pgAdmin) (Ctrl+C для выхода):"
    # Показываем все сервисы кроме pgAdmin
    docker-compose -f docker-compose.prod.yml logs -f backend bot postgres redis 2>/dev/null || \
    docker-compose -f docker-compose.prod.yml logs -f --no-log-prefix | grep -v "sst_pgadmin"
else
    if [ "$1" == "pgadmin" ]; then
        echo "Логи pgAdmin (Ctrl+C для выхода):"
        docker-compose -f docker-compose.prod.yml logs -f pgadmin
    else
        echo "Логи $1 (Ctrl+C для выхода):"
        docker-compose -f docker-compose.prod.yml logs -f "$1"
    fi
fi
