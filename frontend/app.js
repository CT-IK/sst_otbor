/**
 * Telegram Mini App - Анкета в Студсовет
 */

// === Конфигурация ===
const CONFIG = {
    // API URL бэкенда (определяется автоматически)
    // В проде: тот же домен, в dev: localhost
    API_URL: window.location.hostname === 'localhost' 
        ? 'http://localhost:8000/api/v1'
        : `${window.location.origin}/api/v1`,
    
    // Debounce для автосохранения (мс)
    SAVE_DEBOUNCE: 1000,
    
    // Dev режим (для тестирования без Telegram)
    // Автоматически определяется по наличию Telegram WebApp
    DEV_MODE: !window.Telegram?.WebApp?.initDataUnsafe?.user,
    DEV_TELEGRAM_ID: 123456789,
    DEV_FACULTY_ID: 1,
};

// === Глобальное состояние ===
const state = {
    telegramId: null,
    facultyId: null,
    templateId: null,
    questions: [],
    answers: {},
    canSubmit: false,
    saveTimeout: null,
    isSaving: false,
    adminRole: null, // head_admin | reviewer | null
};

// === Telegram Web App ===
const tg = window.Telegram?.WebApp;

// === DOM элементы ===
const elements = {
    loading: document.getElementById('loading'),
    error: document.getElementById('error'),
    errorMessage: document.getElementById('error-message'),
    stageClosed: document.getElementById('stage-closed'),
    alreadySubmitted: document.getElementById('already-submitted'),
    submissionDate: document.getElementById('submission-date'),
    questionnaire: document.getElementById('questionnaire'),
    facultyName: document.getElementById('faculty-name'),
    form: document.getElementById('questionnaire-form'),
    questionsContainer: document.getElementById('questions-container'),
    draftStatus: document.getElementById('draft-status'),
};

// === Инициализация ===
async function init() {
    try {
        console.log('Init started');
        console.log('Telegram WebApp:', tg);
        console.log('initData:', tg?.initData);
        console.log('initDataUnsafe:', tg?.initDataUnsafe);
        
        // Инициализация Telegram Web App
        if (tg) {
            tg.ready();
            tg.expand();
            
            // Применяем тему Telegram
            applyTelegramTheme();
            
            // Настраиваем MainButton
            tg.MainButton.setText('Отправить анкету');
            tg.MainButton.onClick(submitQuestionnaire);
            
            // Получаем данные из Telegram
            const initData = tg.initDataUnsafe;
            console.log('User from initData:', initData?.user);
            state.telegramId = initData?.user?.id;
            
            // faculty_id передаётся через start_param или query_id
            const startParam = initData?.start_param;
            if (startParam) {
                state.facultyId = parseInt(startParam, 10);
            }
        }
        
        // Также проверяем URL параметры (для WebApp кнопки)
        const urlParams = new URLSearchParams(window.location.search);
        const urlFacultyId = urlParams.get('faculty_id');
        if (urlFacultyId && !state.facultyId) {
            state.facultyId = parseInt(urlFacultyId, 10);
        }
        
        // Dev режим fallback
        if (CONFIG.DEV_MODE) {
            if (!state.telegramId) state.telegramId = CONFIG.DEV_TELEGRAM_ID;
            if (!state.facultyId) state.facultyId = CONFIG.DEV_FACULTY_ID;
        }
        
        if (!state.telegramId) {
            const debugInfo = `
DEBUG:
- tg: ${tg ? 'есть' : 'нет'}
- initData: ${tg?.initData ? 'есть' : 'пусто'}
- user: ${JSON.stringify(tg?.initDataUnsafe?.user || 'нет')}
- URL: ${window.location.href}
- faculty_id from URL: ${urlFacultyId || 'нет'}
            `;
            throw new Error('Не удалось получить данные пользователя.\n\n' + debugInfo);
        }
        
        if (!state.facultyId) {
            showNoFacultyError();
            return;
        }
        
        // Проверяем, является ли пользователь админом
        try {
            const adminCheck = await api(`/admin/check/${state.facultyId}`);
            
        if (adminCheck.is_admin) {
            // Сохраняем роль админа (head_admin или reviewer)
            state.adminRole = adminCheck.role || null;
            console.log('Admin role detected:', state.adminRole);
            // Админ — показываем статистику
            await loadAdminStats();
        } else {
                // Обычный пользователь — показываем анкету
                await loadQuestionnaire();
            }
        } catch (error) {
            // Если ошибка проверки админа, показываем анкету
            console.log('Admin check failed, showing questionnaire:', error);
            await loadQuestionnaire();
        }
        
    } catch (error) {
        console.error('Init error:', error);
        showError(error.message);
    }
}

// === Скрытие клавиатуры ===
function hideKeyboard() {
    if (document.activeElement && document.activeElement.blur) {
        document.activeElement.blur();
    }
    // Для iOS
    window.scrollTo(0, 0);
}

// Скрываем клавиатуру при клике на фон
document.addEventListener('click', (e) => {
    if (e.target.tagName !== 'INPUT' && 
        e.target.tagName !== 'TEXTAREA' && 
        e.target.tagName !== 'SELECT') {
        hideKeyboard();
    }
});

// === Применение темы Telegram ===
function applyTelegramTheme() {
    if (!tg?.themeParams) return;
    
    const root = document.documentElement;
    const params = tg.themeParams;
    
    if (params.bg_color) root.style.setProperty('--tg-theme-bg-color', params.bg_color);
    if (params.text_color) root.style.setProperty('--tg-theme-text-color', params.text_color);
    if (params.hint_color) root.style.setProperty('--tg-theme-hint-color', params.hint_color);
    if (params.link_color) root.style.setProperty('--tg-theme-link-color', params.link_color);
    if (params.button_color) root.style.setProperty('--tg-theme-button-color', params.button_color);
    if (params.button_text_color) root.style.setProperty('--tg-theme-button-text-color', params.button_text_color);
    if (params.secondary_bg_color) root.style.setProperty('--tg-theme-secondary-bg-color', params.secondary_bg_color);
}

// === API вызовы ===
async function api(endpoint, options = {}) {
    const url = new URL(`${CONFIG.API_URL}${endpoint}`);
    
    // Добавляем telegram_id как query параметр
    url.searchParams.set('telegram_id', state.telegramId);
    
    const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
        },
        ...options,
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `HTTP ${response.status}`);
    }
    
    // 204 No Content
    if (response.status === 204) return null;
    
    return response.json();
}

// === Загрузка анкеты ===
async function loadQuestionnaire() {
    try {
        const data = await api(`/questionnaire/${state.facultyId}`);
        
        // Проверяем, отправлял ли уже анкету
        if (data.already_submitted) {
            showAlreadySubmitted(data.submitted_at);
            return;
        }
        
        // Проверяем текущий этап
        if (data.current_stage === 'home_video') {
            showVideoStage();
            return;
        }
        
        // Проверяем статус этапа
        if (data.stage_status === 'not_started') {
            showStageClosed();
            return;
        }
        
        if (data.stage_status === 'closed' || data.stage_status === 'completed') {
            showStageClosed();
            return;
        }
        
        // Сохраняем данные
        state.templateId = data.template.template_id;
        state.questions = data.template.questions;
        state.canSubmit = data.can_submit;
        
        // Восстанавливаем черновик
        if (data.draft) {
            state.answers = data.draft.answers || {};
        }
        
        // Обновляем UI
        elements.facultyName.textContent = data.template.faculty_name;
        
        // Рендерим вопросы
        renderQuestions();
        
        // Показываем форму
        showScreen('questionnaire');
        
        // Показываем кнопку отправки
        if (tg && state.canSubmit) {
            tg.MainButton.show();
        }
        
    } catch (error) {
        console.error('Load error:', error);
        
        if (error.message.includes('уже отправили')) {
            showAlreadySubmitted();
        } else {
            throw error;
        }
    }
}

// === Загрузка статистики для админа ===
async function loadAdminStats() {
    try {
        const stats = await api(`/admin/stats/${state.facultyId}`);
        
        // Скрываем MainButton для админа
        if (tg) tg.MainButton.hide();
        
        // Показываем экран статистики
        renderAdminStats(stats);
        showScreen('admin-stats');
        
    } catch (error) {
        console.error('Admin stats error:', error);
        // Если ошибка — показываем обычную анкету
        await loadQuestionnaire();
    }
}

// === Рендер статистики админа ===
function renderAdminStats(stats) {
    const container = document.getElementById('admin-stats-content');
    if (!container) return;
    
    // График по дням
    const maxCount = Math.max(...stats.daily_submissions.map(d => d.count), 1);
    const chartBars = stats.daily_submissions.map(d => {
        const height = (d.count / maxCount) * 100;
        return `
            <div class="chart-bar-wrapper">
                <div class="chart-bar" style="height: ${height}%">
                    <span class="chart-value">${d.count || ''}</span>
                </div>
                <span class="chart-label">${d.date}</span>
            </div>
        `;
    }).join('');
    
    container.innerHTML = `
        <div class="stats-header">
            <h1>📊 ${stats.faculty_name}</h1>
            <p class="stats-subtitle">Статистика анкет</p>
        </div>
        
        <div class="stats-cards">
            <div class="stat-card primary">
                <div class="stat-value">${stats.total_submissions}</div>
                <div class="stat-label">Всего анкет</div>
            </div>
            <div class="stat-card success">
                <div class="stat-value">${stats.approved_count}</div>
                <div class="stat-label">Одобрено</div>
            </div>
            <div class="stat-card warning">
                <div class="stat-value">${stats.pending_count}</div>
                <div class="stat-label">На проверке</div>
            </div>
            <div class="stat-card danger">
                <div class="stat-value">${stats.rejected_count}</div>
                <div class="stat-label">Отклонено</div>
            </div>
        </div>
        
        <div class="stats-section">
            <h3>📈 Заявки за 14 дней</h3>
            <div class="chart">
                ${chartBars}
            </div>
        </div>
        
        <div class="stats-section">
            <h3>ℹ️ Информация</h3>
            <div class="info-row">
                <span>Этап:</span>
                <span>${stats.current_stage || 'не начат'}</span>
            </div>
            <div class="info-row">
                <span>Статус:</span>
                <span>${stats.stage_status || '—'}</span>
            </div>
            <div class="info-row">
                <span>Всего пользователей:</span>
                <span>${stats.total_users}</span>
            </div>
        </div>
        
        <div class="stats-actions">
            <a href="${window.location.origin}/admin?faculty_id=${state.facultyId}&telegram_id=${state.telegramId}" 
               target="_blank" class="btn-link">
                🔗 Открыть полную таблицу ответов
            </a>
            ${state.adminRole === 'head_admin' ? `
                <button class="btn btn-primary" style="margin-top: 12px; width: 100%;" onclick="window.loadInterviewSlots()">
                    📅 Слоты собеседований
                </button>
            ` : ''}
            ${state.adminRole === 'reviewer' ? `
                <button class="btn btn-primary" style="margin-top: 12px; width: 100%;" onclick="window.loadInterviewSlots()">
                    📅 Моя занятость
                </button>
            ` : ''}
        </div>
    `;
}

// === Слоты собеседований (для админов и проверяющих) ===
async function loadInterviewSlots() {
    try {
        const data = await api(`/interview-slots/${state.facultyId}`);
        // Скрываем MainButton для экранов слотов
        if (tg) tg.MainButton.hide();
        renderInterviewSlots(data);
        showScreen('interview-slots');
    } catch (error) {
        console.error('Interview slots error:', error);
        showError(error.message || 'Ошибка загрузки слотов собеседований');
    }
}

function formatDateTime(dateStr) {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return dateStr;
    return date.toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit'
    });
}

function renderInterviewSlots(data) {
    const container = document.getElementById('interview-slots-content');
    if (!container) return;

    const roleLabel = state.adminRole === 'head_admin'
        ? 'Главный администратор'
        : (state.adminRole === 'reviewer' ? 'Проверяющий' : 'Администратор');

    const slots = data.slots || [];

    const slotsHtml = slots.length === 0
        ? '<p class="hint-text">Слотов собеседований пока нет. Создайте первый слот.</p>'
        : slots.map(slot => {
            const statusText = slot.is_active ? 'Активен' : 'Неактивен';
            const capacityText = `${slot.current_participants} / ${slot.max_participants}`;
            const freeText = `${slot.available_places}`;
            const locationText = slot.location ? slot.location : 'Не указана';

            let availabilityBlock = '';
            // Показываем блок доступности для всех админов и проверяющих
            if (state.adminRole === 'head_admin' || state.adminRole === 'reviewer') {
                let label;
                if (slot.my_availability === true) {
                    label = '✅ Я свободен в это время';
                } else if (slot.my_availability === false) {
                    label = '⛔ Я занят в это время';
                } else {
                    label = '🤔 Не отмечено';
                }

                const nextAvailable = !(slot.my_availability === true);
                const buttonText = nextAvailable ? 'Отметить как свободен' : 'Отметить как занят';

                availabilityBlock = `
                    <div class="slot-availability">
                        <span class="slot-availability-label">${label}</span>
                        <button class="btn btn-primary" onclick="window.toggleSlotAvailability(${slot.id}, ${nextAvailable})">
                            ${buttonText}
                        </button>
                    </div>
                `;
            }

            return `
                <div class="slot-card">
                    <div class="slot-header">
                        <div class="slot-time">${formatDateTime(slot.datetime_start)} – ${formatDateTime(slot.datetime_end)}</div>
                        <div class="slot-status ${slot.is_active ? 'active' : 'inactive'}">${statusText}</div>
                    </div>
                    <div class="slot-body">
                        <div class="slot-row">
                            <span>Мест занято / всего:</span>
                            <span>${capacityText}</span>
                        </div>
                        <div class="slot-row">
                            <span>Свободных мест:</span>
                            <span>${freeText}</span>
                        </div>
                        <div class="slot-row">
                            <span>Локация:</span>
                            <span>${locationText}</span>
                        </div>
                    </div>
                    ${availabilityBlock}
                </div>
            `;
        }).join('');

    const createButtonHtml = state.adminRole === 'head_admin'
        ? `
            <button class="btn btn-primary" style="width: 100%; margin-bottom: 12px;" onclick="window.openCreateSlotPrompt()">
                ➕ Создать слот
            </button>
        `
        : '';

    container.innerHTML = `
        <div class="stats-header">
            <h1>📅 Слоты собеседований</h1>
            <p class="stats-subtitle">${data.faculty_name} — ${roleLabel}</p>
        </div>
        <div class="stats-actions">
            ${createButtonHtml}
            <button class="btn" style="width: 100%;" onclick="window.loadAdminStats()">⬅️ Назад к статистике</button>
        </div>
        <div class="slots-list">
            ${slotsHtml}
        </div>
    `;
}

async function openCreateSlotPrompt() {
    const date = prompt('Дата (в формате ГГГГ-ММ-ДД, например 2026-02-01):');
    if (!date) return;
    const startTime = prompt('Время начала (часы:минуты, например 18:00):');
    if (!startTime) return;
    const endTime = prompt('Время окончания (часы:минуты, например 18:30):');
    if (!endTime) return;
    const maxParticipantsStr = prompt('Максимальное количество участников (по умолчанию 1):', '1');
    if (!maxParticipantsStr) return;
    const maxParticipants = parseInt(maxParticipantsStr, 10) || 1;
    const location = prompt('Локация (аудитория/ссылка, опционально):') || null;

    const toIso = (d, t) => {
        const iso = `${d}T${t}`;
        const dateObj = new Date(iso);
        if (isNaN(dateObj.getTime())) {
            throw new Error('Неверный формат даты/времени');
        }
        return dateObj.toISOString();
    };

    try {
        const datetime_start = toIso(date, startTime);
        const datetime_end = toIso(date, endTime);

        await api(`/interview-slots/${state.facultyId}`, {
            method: 'POST',
            body: JSON.stringify({
                datetime_start,
                datetime_end,
                max_participants: maxParticipants,
                location,
            }),
        });

        await loadInterviewSlots();
    } catch (error) {
        console.error('Create slot error:', error);
        showError(error.message || 'Ошибка создания слота');
    }
}

async function toggleSlotAvailability(slotId, available) {
    try {
        await api(`/interview-slots/${slotId}/availability?available=${available}`, {
            method: 'POST',
        });
        await loadInterviewSlots();
    } catch (error) {
        console.error('Toggle availability error:', error);
        showError(error.message || 'Ошибка изменения доступности');
    }
}

// === Рендер вопросов ===
function renderQuestions() {
    elements.questionsContainer.innerHTML = '';
    
    // Сортируем по order
    const sortedQuestions = [...state.questions].sort((a, b) => a.order - b.order);
    
    sortedQuestions.forEach((question, index) => {
        const card = createQuestionCard(question, index);
        elements.questionsContainer.appendChild(card);
    });
}

function createQuestionCard(question, index) {
    const card = document.createElement('div');
    card.className = 'question-card';
    card.dataset.questionId = question.id;
    card.style.animationDelay = `${index * 0.05}s`;
    
    // Label
    const label = document.createElement('label');
    label.className = 'question-label';
    label.innerHTML = question.text;
    if (question.required) {
        label.innerHTML += '<span class="required">*</span>';
    }
    card.appendChild(label);
    
    // Input based on type
    let input;
    switch (question.type) {
        case 'text':
            input = createTextInput(question);
            break;
        case 'choice':
            input = createChoiceInput(question);
            break;
        case 'multiple_choice':
            input = createMultipleChoiceInput(question);
            break;
        case 'number':
            input = createNumberInput(question);
            break;
        default:
            input = createTextInput(question);
    }
    card.appendChild(input);
    
    // Validation error
    const errorEl = document.createElement('div');
    errorEl.className = 'validation-error';
    errorEl.textContent = 'Это поле обязательно для заполнения';
    card.appendChild(errorEl);
    
    return card;
}

function createTextInput(question) {
    const wrapper = document.createElement('div');
    
    const textarea = document.createElement('textarea');
    textarea.className = 'textarea-input';
    textarea.placeholder = 'Введите ответ...';
    textarea.value = state.answers[question.id] || '';
    if (question.max_length) {
        textarea.maxLength = question.max_length;
    }
    
    textarea.addEventListener('input', (e) => {
        updateAnswer(question.id, e.target.value);
        updateCharCounter(counter, e.target.value.length, question.max_length);
    });
    
    wrapper.appendChild(textarea);
    
    // Character counter
    if (question.max_length) {
        const counter = document.createElement('div');
        counter.className = 'char-counter';
        updateCharCounter(counter, textarea.value.length, question.max_length);
        wrapper.appendChild(counter);
    }
    
    return wrapper;
}

function createChoiceInput(question) {
    const wrapper = document.createElement('div');
    wrapper.className = 'options-list';
    
    question.options?.forEach(option => {
        const item = document.createElement('label');
        item.className = 'option-item';
        if (state.answers[question.id] === option.value) {
            item.classList.add('selected');
        }
        
        const input = document.createElement('input');
        input.type = 'radio';
        input.name = `question_${question.id}`;
        input.value = option.value;
        input.checked = state.answers[question.id] === option.value;
        
        input.addEventListener('change', () => {
            // Убираем selected у всех
            wrapper.querySelectorAll('.option-item').forEach(el => el.classList.remove('selected'));
            item.classList.add('selected');
            updateAnswer(question.id, option.value);
        });
        
        const radio = document.createElement('span');
        radio.className = 'option-radio';
        
        const label = document.createElement('span');
        label.className = 'option-label';
        label.textContent = option.label;
        
        item.appendChild(input);
        item.appendChild(radio);
        item.appendChild(label);
        wrapper.appendChild(item);
    });
    
    return wrapper;
}

function createMultipleChoiceInput(question) {
    const wrapper = document.createElement('div');
    wrapper.className = 'options-list';
    
    const currentValue = state.answers[question.id] || [];
    
    question.options?.forEach(option => {
        const item = document.createElement('label');
        item.className = 'option-item';
        if (currentValue.includes(option.value)) {
            item.classList.add('selected');
        }
        
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.value = option.value;
        input.checked = currentValue.includes(option.value);
        
        input.addEventListener('change', () => {
            item.classList.toggle('selected', input.checked);
            
            // Собираем все выбранные
            const selected = [];
            wrapper.querySelectorAll('input:checked').forEach(el => {
                selected.push(el.value);
            });
            updateAnswer(question.id, selected);
        });
        
        const checkbox = document.createElement('span');
        checkbox.className = 'option-checkbox';
        
        const label = document.createElement('span');
        label.className = 'option-label';
        label.textContent = option.label;
        
        item.appendChild(input);
        item.appendChild(checkbox);
        item.appendChild(label);
        wrapper.appendChild(item);
    });
    
    return wrapper;
}

function createNumberInput(question) {
    const input = document.createElement('input');
    input.type = 'number';
    input.className = 'number-input';
    input.placeholder = 'Введите число...';
    input.value = state.answers[question.id] || '';
    
    if (question.min_value !== undefined) input.min = question.min_value;
    if (question.max_value !== undefined) input.max = question.max_value;
    
    input.addEventListener('input', (e) => {
        updateAnswer(question.id, e.target.value ? Number(e.target.value) : null);
    });
    
    return input;
}

function updateCharCounter(counter, current, max) {
    if (!counter) return;
    
    counter.textContent = `${current}/${max}`;
    counter.classList.remove('warning', 'error');
    
    const percent = current / max;
    if (percent >= 1) {
        counter.classList.add('error');
    } else if (percent >= 0.9) {
        counter.classList.add('warning');
    }
}

// === Обновление ответа ===
function updateAnswer(questionId, value) {
    state.answers[questionId] = value;
    
    // Убираем ошибку валидации
    const card = document.querySelector(`[data-question-id="${questionId}"]`);
    if (card) card.classList.remove('invalid');
    
    // Debounced save
    scheduleSave();
}

// === Автосохранение ===
function scheduleSave() {
    if (state.saveTimeout) {
        clearTimeout(state.saveTimeout);
    }
    
    state.saveTimeout = setTimeout(() => {
        saveDraft();
    }, CONFIG.SAVE_DEBOUNCE);
}

async function saveDraft() {
    if (state.isSaving) return;
    
    state.isSaving = true;
    setDraftStatus('saving');
    
    try {
        await api(`/questionnaire/${state.facultyId}/draft`, {
            method: 'POST',
            body: JSON.stringify({
                template_id: state.templateId,
                answers: state.answers,
            }),
        });
        
        setDraftStatus('saved');
        
        // Скрываем через 2 сек
        setTimeout(() => {
            setDraftStatus('hidden');
        }, 2000);
        
    } catch (error) {
        console.error('Save draft error:', error);
        setDraftStatus('hidden');
    } finally {
        state.isSaving = false;
    }
}

function setDraftStatus(status) {
    elements.draftStatus.classList.remove('saving', 'saved');
    
    if (status === 'saving') {
        elements.draftStatus.classList.add('saving');
        elements.draftStatus.querySelector('.status-text').textContent = 'Сохранение...';
    } else if (status === 'saved') {
        elements.draftStatus.classList.add('saved');
        elements.draftStatus.querySelector('.status-text').textContent = 'Сохранено';
    }
}

// === Отправка анкеты ===
async function submitQuestionnaire() {
    // Валидация
    if (!validateForm()) {
        if (tg) tg.HapticFeedback.notificationOccurred('error');
        return;
    }
    
    // Подтверждение
    if (tg) {
        tg.showConfirm('Вы уверены, что хотите отправить анкету? После отправки изменить ответы будет невозможно.', async (confirmed) => {
            if (confirmed) {
                await doSubmit();
            }
        });
    } else {
        if (confirm('Вы уверены, что хотите отправить анкету?')) {
            await doSubmit();
        }
    }
}

async function doSubmit() {
    if (tg) {
        tg.MainButton.showProgress();
    }
    
    try {
        const result = await api(`/questionnaire/${state.facultyId}/submit`, {
            method: 'POST',
            body: JSON.stringify({
                template_id: state.templateId,
                answers: state.answers,
            }),
        });
        
        if (tg) {
            tg.HapticFeedback.notificationOccurred('success');
            tg.MainButton.hideProgress();
            tg.MainButton.hide();
        }
        
        // Показываем успех
        showAlreadySubmitted(new Date().toISOString());
        
    } catch (error) {
        console.error('Submit error:', error);
        
        if (tg) {
            tg.HapticFeedback.notificationOccurred('error');
            tg.MainButton.hideProgress();
            tg.showAlert(error.message || 'Ошибка отправки');
        } else {
            alert(error.message || 'Ошибка отправки');
        }
    }
}

// === Валидация ===
function validateForm() {
    let isValid = true;
    
    state.questions.forEach(question => {
        if (!question.required) return;
        
        const value = state.answers[question.id];
        const card = document.querySelector(`[data-question-id="${question.id}"]`);
        
        let isEmpty = false;
        
        if (value === undefined || value === null || value === '') {
            isEmpty = true;
        } else if (Array.isArray(value) && value.length === 0) {
            isEmpty = true;
        }
        
        if (isEmpty) {
            isValid = false;
            if (card) {
                card.classList.add('invalid');
                // Скролл к первой ошибке
                if (isValid === false) {
                    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        } else {
            if (card) card.classList.remove('invalid');
        }
    });
    
    return isValid;
}

// === UI хелперы ===
function showScreen(screenId) {
    // Скрываем все экраны
    const allScreens = ['loading', 'error', 'stage-closed', 'already-submitted', 'questionnaire', 'video-stage', 'admin-stats', 'interview-slots', 'no-faculty'];
    allScreens.forEach(id => {
        const screen = document.getElementById(id);
        if (screen) screen.classList.add('hidden');
    });
    
    // Показываем нужный
    const screen = document.getElementById(screenId);
    if (screen) screen.classList.remove('hidden');
}

function showError(message) {
    elements.errorMessage.textContent = message;
    showScreen('error');
    
    if (tg) tg.MainButton.hide();
}

function showNoFacultyError() {
    showScreen('no-faculty');
    if (tg) tg.MainButton.hide();
}

function showStageClosed() {
    showScreen('stage-closed');
    if (tg) tg.MainButton.hide();
}

function showVideoStage() {
    showScreen('video-stage');
    if (tg) tg.MainButton.hide();
}

function showAlreadySubmitted(submittedAtOrMessage) {
    showScreen('already-submitted');
    if (tg) tg.MainButton.hide();
    
    // Показываем дату отправки или сообщение
    if (submittedAtOrMessage && elements.submissionDate) {
        // Если это дата (ISO формат)
        if (submittedAtOrMessage.includes('T') || submittedAtOrMessage.includes('-')) {
            const date = new Date(submittedAtOrMessage);
            if (!isNaN(date.getTime())) {
                const formatted = date.toLocaleDateString('ru-RU', {
                    day: 'numeric',
                    month: 'long',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                });
                elements.submissionDate.textContent = `Отправлено: ${formatted}`;
                return;
            }
        }
        // Иначе это сообщение
        elements.submissionDate.textContent = submittedAtOrMessage;
    }
}

// === Экспорт функций в window для использования в onclick ===
window.loadInterviewSlots = loadInterviewSlots;
window.loadAdminStats = loadAdminStats;
window.openCreateSlotPrompt = openCreateSlotPrompt;
window.toggleSlotAvailability = toggleSlotAvailability;

// === Запуск ===
document.addEventListener('DOMContentLoaded', init);

