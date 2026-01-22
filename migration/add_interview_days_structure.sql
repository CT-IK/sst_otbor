-- Миграция для новой структуры дней собеседований и временных слотов
-- Этап 3: Запись на собеседования (новая версия)

-- 1. Создаем таблицу interview_days (дни собеседований)
CREATE TABLE IF NOT EXISTS interview_days (
    id SERIAL PRIMARY KEY,
    faculty_id INTEGER NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    location VARCHAR(255),
    created_by INTEGER REFERENCES administrators(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_faculty_date UNIQUE (faculty_id, date)
);

-- 2. Создаем таблицу time_slots (временные слоты 10:00-22:00)
CREATE TABLE IF NOT EXISTS time_slots (
    id SERIAL PRIMARY KEY,
    day_id INTEGER NOT NULL REFERENCES interview_days(id) ON DELETE CASCADE,
    time TIME NOT NULL,  -- Время начала слота (10:00, 11:00, ..., 22:00)
    max_participants INTEGER NOT NULL DEFAULT 0,  -- Количество мест (0-10)
    current_participants INTEGER NOT NULL DEFAULT 0,  -- Текущее количество записей
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_day_time UNIQUE (day_id, time)
);

-- 3. Создаем таблицу time_slot_availability (доступность проверяющих)
CREATE TABLE IF NOT EXISTS time_slot_availability (
    id SERIAL PRIMARY KEY,
    time_slot_id INTEGER NOT NULL REFERENCES time_slots(id) ON DELETE CASCADE,
    interviewer_id INTEGER NOT NULL REFERENCES administrators(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_time_slot_interviewer UNIQUE (time_slot_id, interviewer_id)
);

-- 4. Добавляем поле time_slot_id в interviews (для связи с новыми временными слотами)
ALTER TABLE interviews 
ADD COLUMN IF NOT EXISTS time_slot_id INTEGER REFERENCES time_slots(id) ON DELETE SET NULL;

-- 5. Создаем индексы
CREATE INDEX IF NOT EXISTS idx_interview_days_faculty_id ON interview_days(faculty_id);
CREATE INDEX IF NOT EXISTS idx_interview_days_date ON interview_days(date);
CREATE INDEX IF NOT EXISTS idx_interview_days_is_active ON interview_days(is_active);

CREATE INDEX IF NOT EXISTS idx_time_slots_day_id ON time_slots(day_id);
CREATE INDEX IF NOT EXISTS idx_time_slots_time ON time_slots(time);
CREATE INDEX IF NOT EXISTS idx_time_slots_is_active ON time_slots(is_active);

CREATE INDEX IF NOT EXISTS idx_time_slot_availability_time_slot_id ON time_slot_availability(time_slot_id);
CREATE INDEX IF NOT EXISTS idx_time_slot_availability_interviewer_id ON time_slot_availability(interviewer_id);

CREATE INDEX IF NOT EXISTS idx_interviews_time_slot_id ON interviews(time_slot_id);

-- 6. Комментарии
COMMENT ON TABLE interview_days IS 'Дни, когда проводятся собеседования. Head Admin создает дни.';
COMMENT ON TABLE time_slots IS 'Временные слоты в день (10:00-22:00). Head Admin устанавливает количество мест.';
COMMENT ON TABLE time_slot_availability IS 'Доступность проверяющих в временных слотах. Reviewer отмечает галочками.';
COMMENT ON COLUMN time_slots.max_participants IS 'Количество доступных мест (0-10), устанавливает Head Admin';
COMMENT ON COLUMN time_slots.current_participants IS 'Текущее количество записей пользователей';
