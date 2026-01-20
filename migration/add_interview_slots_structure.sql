-- Миграция для добавления структуры управления слотами собеседований
-- Этап 3: Запись на собеседования

-- 1. Добавляем поле is_active в interview_slots
ALTER TABLE interview_slots 
ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

-- 2. Добавляем поле interviewer_id в interviews (назначенный проверяющий)
ALTER TABLE interviews 
ADD COLUMN IF NOT EXISTS interviewer_id INTEGER REFERENCES administrators(id) ON DELETE SET NULL;

-- 3. Создаем таблицу slot_availability для связи слотов и проверяющих
CREATE TABLE IF NOT EXISTS slot_availability (
    id SERIAL PRIMARY KEY,
    slot_id INTEGER NOT NULL REFERENCES interview_slots(id) ON DELETE CASCADE,
    interviewer_id INTEGER NOT NULL REFERENCES administrators(id) ON DELETE CASCADE,
    available BOOLEAN NOT NULL DEFAULT true,  -- True = свободен, False = занят
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_slot_interviewer UNIQUE (slot_id, interviewer_id)
);

-- 4. Создаем индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_slot_availability_slot_id ON slot_availability(slot_id);
CREATE INDEX IF NOT EXISTS idx_slot_availability_interviewer_id ON slot_availability(interviewer_id);
CREATE INDEX IF NOT EXISTS idx_slot_availability_available ON slot_availability(available);

CREATE INDEX IF NOT EXISTS idx_interview_slots_faculty_id ON interview_slots(faculty_id);
CREATE INDEX IF NOT EXISTS idx_interview_slots_datetime_start ON interview_slots(datetime_start);
CREATE INDEX IF NOT EXISTS idx_interview_slots_is_active ON interview_slots(is_active);

CREATE INDEX IF NOT EXISTS idx_interviews_interviewer_id ON interviews(interviewer_id);
CREATE INDEX IF NOT EXISTS idx_interviews_slot_id ON interviews(slot_id);

-- 5. Комментарии к таблицам и полям
COMMENT ON TABLE slot_availability IS 'Доступность проверяющих для проведения собеседований в слотах';
COMMENT ON COLUMN slot_availability.available IS 'True = проверяющий свободен в этот слот, False = занят';
COMMENT ON COLUMN interview_slots.is_active IS 'Активен ли слот (можно деактивировать без удаления)';
COMMENT ON COLUMN interviews.interviewer_id IS 'Назначенный проверяющий для проведения собеседования';
