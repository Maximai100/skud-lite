/**
 * СКУД-лайт Frontend
 * Простое SPA для отметки присутствия жильцов
 */

// === Конфигурация ===
// API на том же сервере (FastAPI раздаёт frontend)
const API_URL = window.location.origin;
const STORAGE_KEY = 'skud_user_id';

// === DOM элементы ===
const screens = {
    register: document.getElementById('register-screen'),
    main: document.getElementById('main-screen'),
    confirm: document.getElementById('confirm-screen')
};

const elements = {
    registerForm: document.getElementById('register-form'),
    fullNameInput: document.getElementById('full-name'),
    userName: document.getElementById('user-name'),
    currentStatus: document.getElementById('current-status'),
    statusCard: document.getElementById('status-card'),
    leavingButtons: document.getElementById('leaving-buttons'),
    returnButton: document.getElementById('return-button'),
    confirmIcon: document.getElementById('confirm-icon'),
    confirmText: document.getElementById('confirm-text'),
    backBtn: document.getElementById('back-btn'),
    loading: document.getElementById('loading'),
    errorToast: document.getElementById('error-toast')
};

// === Маппинг статусов ===
const STATUS_LABELS = {
    inside: 'В здании',
    work: 'На работе',
    day_off: 'На сутки',
    request: 'По заявлению'
};

const CONFIRM_MESSAGES = {
    work: { icon: '👋', text: 'Хорошего рабочего дня!' },
    day_off: { icon: '🌙', text: 'Хорошего отдыха!' },
    request: { icon: '📋', text: 'Хорошего дня!' },
    inside: { icon: '🏠', text: 'С возвращением!' }
};

// === Утилиты ===

function showLoading() {
    elements.loading.classList.remove('hidden');
}

function hideLoading() {
    elements.loading.classList.add('hidden');
}

function showError(message) {
    elements.errorToast.textContent = message;
    elements.errorToast.classList.remove('hidden');
    setTimeout(() => {
        elements.errorToast.classList.add('hidden');
    }, 3000);
}

function showScreen(screenName) {
    Object.values(screens).forEach(screen => screen.classList.add('hidden'));
    screens[screenName].classList.remove('hidden');
}

function getUserId() {
    return localStorage.getItem(STORAGE_KEY);
}

function setUserId(userId) {
    localStorage.setItem(STORAGE_KEY, userId);
}

// === Геолокация ===

function getCurrentPosition() {
    return new Promise((resolve) => {
        if (!navigator.geolocation) {
            resolve(null);
            return;
        }
        
        navigator.geolocation.getCurrentPosition(
            (position) => {
                resolve({
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude
                });
            },
            (error) => {
                console.log('Геолокация недоступна:', error.message);
                resolve(null);
            },
            {
                enableHighAccuracy: true,
                timeout: 5000,
                maximumAge: 60000
            }
        );
    });
}

// === API запросы ===

async function apiRequest(endpoint, options = {}) {
    try {
        const response = await fetch(`${API_URL}${endpoint}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Ошибка сервера' }));
            throw new Error(error.detail || 'Ошибка запроса');
        }

        return await response.json();
    } catch (error) {
        if (error.message === 'Failed to fetch') {
            throw new Error('Нет связи с сервером');
        }
        throw error;
    }
}

async function register(fullName) {
    return await apiRequest('/api/register', {
        method: 'POST',
        body: JSON.stringify({ full_name: fullName })
    });
}

async function getStatus(userId) {
    return await apiRequest(`/api/status/${userId}`);
}

async function updateStatus(userId, status, location = null) {
    const body = { status };
    if (location) {
        body.latitude = location.latitude;
        body.longitude = location.longitude;
    }
    return await apiRequest(`/api/status/${userId}`, {
        method: 'POST',
        body: JSON.stringify(body)
    });
}

// === UI обновление ===

function updateMainScreen(data) {
    elements.userName.textContent = data.full_name;
    
    const isInside = data.status === 'inside';
    elements.currentStatus.textContent = STATUS_LABELS[data.status] || data.status;
    elements.currentStatus.className = 'status-value ' + (isInside ? 'inside' : 'outside');
    
    if (isInside) {
        elements.leavingButtons.classList.remove('hidden');
        elements.returnButton.classList.add('hidden');
    } else {
        elements.leavingButtons.classList.add('hidden');
        elements.returnButton.classList.remove('hidden');
    }
}

function showConfirmation(status) {
    const msg = CONFIRM_MESSAGES[status] || { icon: '✅', text: 'Готово!' };
    elements.confirmIcon.textContent = msg.icon;
    elements.confirmText.textContent = msg.text;
    showScreen('confirm');
}

// === Обработчики событий ===

async function handleRegister(event) {
    event.preventDefault();
    
    const fullName = elements.fullNameInput.value.trim();
    if (!fullName || fullName.length < 2) {
        showError('Введите корректное ФИО');
        return;
    }

    showLoading();
    try {
        const data = await register(fullName);
        setUserId(data.user_id);
        updateMainScreen(data);
        showScreen('main');
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

async function handleStatusChange(event) {
    const btn = event.target.closest('.btn-status');
    if (!btn) return;

    const newStatus = btn.dataset.status;
    const userId = getUserId();

    showLoading();
    try {
        // Получаем геолокацию параллельно (не блокируем, если недоступна)
        const location = await getCurrentPosition();
        await updateStatus(userId, newStatus, location);
        showConfirmation(newStatus);
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

async function handleBack() {
    const userId = getUserId();
    
    showLoading();
    try {
        const data = await getStatus(userId);
        updateMainScreen(data);
        showScreen('main');
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

// === Инициализация ===

async function init() {
    const userId = getUserId();

    if (!userId) {
        // Первое посещение — показать форму регистрации
        showScreen('register');
        return;
    }

    // Повторное посещение — загрузить статус
    showLoading();
    try {
        const data = await getStatus(userId);
        updateMainScreen(data);
        showScreen('main');
    } catch (error) {
        // Если пользователь не найден — сбросить и показать регистрацию
        if (error.message.includes('не найден')) {
            localStorage.removeItem(STORAGE_KEY);
            showScreen('register');
        } else {
            showError(error.message);
            showScreen('register');
        }
    } finally {
        hideLoading();
    }
}

// === Привязка событий ===
elements.registerForm.addEventListener('submit', handleRegister);
elements.leavingButtons.addEventListener('click', handleStatusChange);
elements.returnButton.addEventListener('click', handleStatusChange);
elements.backBtn.addEventListener('click', handleBack);

// Запуск приложения
init();
