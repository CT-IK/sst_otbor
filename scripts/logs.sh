#!/bin/bash
# Просмотр логов

cd ~/ct/sst_otbor || cd "$(dirname "$0")/.."

if [ -z "$1" ]; then
    echo "Все логи (Ctrl+C для выхода):"
    docker-compose -f docker-compose.prod.yml logs -f backend bot redis pgadmin
else
    echo "Логи $1 (Ctrl+C для выхода):"
    docker-compose -f docker-compose.prod.yml logs -f "$1"
fi
