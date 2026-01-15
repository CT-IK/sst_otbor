-- Миграция: добавление полей для второго этапа (видео)
-- Выполнить вручную, если alembic недоступен

-- Добавляем поле added_by в administrators
ALTER TABLE administrators ADD COLUMN IF NOT EXISTS added_by BIGINT;

-- Добавляем поля для этапа видео в faculty
ALTER TABLE faculty ADD COLUMN IF NOT EXISTS video_chat_id BIGINT;
ALTER TABLE faculty ADD COLUMN IF NOT EXISTS video_submission_open BOOLEAN NOT NULL DEFAULT false;
