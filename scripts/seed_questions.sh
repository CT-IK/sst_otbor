#!/bin/bash
# Добавление дефолтных вопросов и открытие анкеты

cd ~/ct/sst_otbor

echo "📝 Добавление дефолтных вопросов..."
docker-compose -f docker-compose.prod.yml exec -T backend python -m scripts.seed_questions --open

echo ""
echo "✅ Готово! Теперь /questionnaire должен работать"
