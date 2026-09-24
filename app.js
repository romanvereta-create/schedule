const tg = window.Telegram.WebApp;
tg.expand();

// Keep dialogs inside the visible WebView, including when the keyboard reduces it.
function updateModalViewport() {
    const viewport = window.visualViewport;
    document.documentElement.style.setProperty('--modal-viewport-height', `${viewport ? viewport.height : window.innerHeight}px`);
    document.documentElement.style.setProperty('--modal-viewport-top', `${viewport ? viewport.offsetTop : 0}px`);
}
updateModalViewport();
window.addEventListener('resize', updateModalViewport);
window.visualViewport?.addEventListener('resize', updateModalViewport);
window.visualViewport?.addEventListener('scroll', updateModalViewport);

const DEFAULT_API_ORIGIN = 'https://bot-1787954043-4984-solo1986.bothost.tech';
const TEST_API_ORIGIN = 'https://bot-1789984567-3598-solo1986.bothost.tech';

const requestedApiOrigin = new URLSearchParams(window.location.search).get('api_origin');
const selfHostedBot3 = window.location.origin === TEST_API_ORIGIN
    && window.location.pathname.startsWith('/app/');
const API_ORIGIN = selfHostedBot3 || requestedApiOrigin === TEST_API_ORIGIN
    ? TEST_API_ORIGIN
    : DEFAULT_API_ORIGIN;
const API_URL = `${API_ORIGIN}/api`;
const SUPPORTS_BOOTSTRAP = API_ORIGIN === TEST_API_ORIGIN;
const START_HOUR = 0;
const END_HOUR = 23;
const MIN_HOUR_HEIGHT = 40;
const MAX_HOUR_HEIGHT = 160;
const DEFAULT_HOUR_HEIGHT = 80;
const ZOOM_STEP = 20;

let hourHeight = DEFAULT_HOUR_HEIGHT;
let weekTransitioning = false;
let autoFitWeekPending = true;
const WEEK_CACHE_TTL_MS = 60 * 1000;
const WEEK_CACHE_LIMIT = 3;
const weekScheduleCache = new Map();
const weekScheduleInflight = new Map();
let weekCacheGeneration = 0;
let adjacentWeekPrefetchTimer = null;
let calendarView = 'week';
try { calendarView = localStorage.getItem('temli-calendar-view') === 'day' ? 'day' : 'week'; } catch (_) {}
let calendarDay = new Date();
function visibleCalendarDates() {
    if (calendarView === 'day') return [new Date(calendarDay)];
    return Array.from({ length: 7 }, (_, i) => {
        const date = new Date(state.currentMonday);
        date.setDate(date.getDate() + i);
        return date;
    });
}

const state = {
    currentMonday: getMonday(new Date()),
    schedule: {},
    students: {},
    selectedLesson: null,
    isMoving: false,
    pendingMove: null,
    editingExisting: false,
    settings: { default_reminders_enabled: true, default_send_receipts: true, default_send_receipt_copy: true, zoom_link: '', work_start: '06:00', work_end: '00:00', days_off: [], language: 'ru', currency: 'RUB' },
    datePickerMonth: new Date(),
    workCenter: null,
    subscriptionStudentId: '',
    subscriptionPrice: 0,
    onboardingNeeded: false,
    pendingAddDate: '',
    pendingAddTime: ''
};

const MOVE_DRAG_THRESHOLD = 5;
const MOVE_LONG_PRESS_MS = 420;
let lessonDragSession = null;
let suppressLessonClickUntil = 0;
let lessonScrollFrame = 0;

function getMonday(date) {
    const d = new Date(date);
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    d.setDate(diff);
    d.setHours(0, 0, 0, 0);
    return d;
}

function dateKey(date) {
    const d = new Date(date);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function uiLocale() { return window.TEMLI_I18N?.locale() || 'ru-RU'; }
function currencySymbol() { return window.TEMLI_I18N?.currencySymbol() || '₽'; }
function localizeText(value) { return window.TEMLI_I18N?.translated(value) || value; }
function shortDateRu(value) {
    const source = String(value || '').trim();
    const date = new Date(`${source}T12:00:00`);
    if (!source || Number.isNaN(date.getTime())) return source || '—';
    return date.toLocaleDateString(uiLocale(), { day: 'numeric', month: 'short' }).replace(/\.$/, '');
}
function formatUiNumber(value, options = {}) {
    return window.TEMLI_I18N?.formatNumber(value, options) ?? Number(value || 0).toLocaleString(uiLocale(), options);
}

function formatWeekRange(monday) {
    const start = new Date(monday);
    const end = new Date(monday);
    end.setDate(end.getDate() + 6);
    const month = date => new Intl.DateTimeFormat(uiLocale(), { month: 'short' }).format(date).replace(/\.$/, '');
    if (start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear()) {
        return `${start.getDate()}–${end.getDate()} ${month(end)}`;
    }
    return `${start.getDate()} ${month(start)}–${end.getDate()} ${month(end)}`;
}

function haptic(type = 'light') {
    try { tg.HapticFeedback.impactOccurred(type); } catch (e) {}
}

function getStudentInfo(studentId) {
    const raw = state.students[studentId];
    return typeof raw === 'string' ? { name: raw } : (raw || {});
}

function teacherTelegramId() {
    return String(tg?.initDataUnsafe?.user?.id || '');
}

function visibleStudentEntries() {
    const teacherId = teacherTelegramId();
    return Object.entries(state.students)
        .filter(([id]) => String(id) !== teacherId)
        .sort((a, b) => {
            const aInfo = typeof a[1] === 'string' ? { name: a[1] } : (a[1] || {});
            const bInfo = typeof b[1] === 'string' ? { name: b[1] } : (b[1] || {});
            return String(aInfo.name || a[0]).localeCompare(String(bInfo.name || b[0]), uiLocale(), { sensitivity: 'base' });
        });
}

function lessonPriceValue(lesson, member = null) {
    const raw = member ? (member.price ?? lesson?.price) : lesson?.price;
    const value = Number(raw || 0);
    return Number.isFinite(value) && value > 0 ? value : 0;
}

function workingTimeMinutes(value, fallback, isEnd = false) {
    const match = /^(\d{2}):(\d{2})$/.exec(String(value || ''));
    if (!match) return fallback;
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    if (hour > 23 || minute > 59) return fallback;
    if (isEnd && hour === 0 && minute === 0) return 24 * 60;
    return hour * 60 + minute;
}

function workingTimeRangeIsValid(start, end) {
    return workingTimeMinutes(start, -1) >= 0
        && workingTimeMinutes(end, -1, true) > workingTimeMinutes(start, -1);
}

function configuredDaysOff() {
    return new Set((Array.isArray(state.settings.days_off) ? state.settings.days_off : [])
        .map(Number).filter(day => Number.isInteger(day) && day >= 0 && day <= 6));
}

function isDayOffDate(value) {
    const date = value instanceof Date ? value : new Date(`${value}T12:00:00`);
    return !Number.isNaN(date.getTime()) && configuredDaysOff().has((date.getDay() + 6) % 7);
}

function updateVisibleHoursFromSettingsAndLessons() {
    // The grid always contains a full day. Working hours only define the initial viewport,
    // so personal events can still be created before or after the teaching day.
    document.documentElement.style.setProperty('--visible-hour-count', '24');
}

function schoolYearEndFor(dateValue) {
    const d = dateValue ? new Date(`${dateValue}T12:00:00`) : new Date();
    const year = d.getFullYear();
    const month = d.getMonth() + 1;
    const targetYear = month <= 5 ? year : year + 1;
    return `${targetYear}-05-31`;
}

function getStudentColor(studentId, name) {
    const info = getStudentInfo(studentId);
    if (typeof info.color === 'string' && /^#[0-9a-fA-F]{6}$/.test(info.color)) return info.color;
    if (info.color !== undefined && info.color !== null) {
        const numericColor = Number(info.color);
        if (Number.isInteger(numericColor) && numericColor >= 0 && numericColor <= 7) return numericColor;
    }
    let hash = 0;
    for (const char of String(name || '')) hash = ((hash << 5) - hash) + char.charCodeAt(0);
    return Math.abs(hash) % 7;
}

function apiHeaders(extraHeaders = {}, body = null) {
    const initData = String(tg.initData || '');
    if (!initData) {
        throw new Error('Доступ к API невозможен без авторизации Telegram.');
    }
    const headers = {
        'X-Telegram-Init-Data': initData,
        ...extraHeaders
    };
    if (!(body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    return headers;
}

let initialDataReady = false;
let dataLoading = false;
let networkFailure = null;
const networkPanel = document.createElement('section');
networkPanel.id = 'network-status';
networkPanel.className = 'hidden';
networkPanel.setAttribute('data-i18n-ignore', '');
networkPanel.innerHTML = '<div class="network-card"><p role="status" aria-live="polite"></p><div class="network-actions"><button type="button" data-network-retry></button><button type="button" data-network-copy></button><button type="button" data-network-close></button></div><pre hidden></pre></div>';
document.body.appendChild(networkPanel);

function networkText(ru, en) { return uiLocale().startsWith('en') ? en : ru; }
function renderNetworkStatus(loading = false, show = true) {
    if (show) networkPanel.classList.remove('hidden');
    networkPanel.classList.toggle('network-blocking', !initialDataReady);
    const code = networkFailure?.code;
    let message = networkText('Загрузка расписания…', 'Loading schedule…');
    if (!loading) {
        if (code === 'auth') message = networkText('Сессия Telegram истекла. Закройте приложение и откройте его снова через бота.', 'Your Telegram session has expired. Close the app and reopen it through the bot.');
        else if (code === 'offline') message = networkText('Нет подключения к интернету. Восстановите соединение и повторите загрузку.', 'No internet connection. Reconnect and retry loading.');
        else if (code === 'http') message = networkText('Сервер временно недоступен. Повторите загрузку позже.', 'The server is temporarily unavailable. Retry loading later.');
        else if (code === 'invalid_response') message = networkText('Сервер вернул неполный или некорректный ответ. Повторите загрузку.', 'The server returned an incomplete or invalid response. Retry loading.');
        else message = networkText('Не удалось связаться с сервером. Проверьте сеть; если используете VPN, попробуйте другой сервер VPN.', 'Could not reach the server. Check your connection; if using a VPN, try another VPN server.');
        if (networkFailure?.uncertain) message += networkText(' Результат последнего действия неизвестен. Проверьте расписание или историю оплат перед повторением.', ' The last action’s result is unknown. Check the schedule or payment history before repeating it.');
    }
    networkPanel.querySelector('p').textContent = message;
    const retry = networkPanel.querySelector('[data-network-retry]');
    retry.textContent = networkText('Повторить загрузку', 'Retry loading');
    retry.disabled = loading;
    retry.hidden = code === 'auth';
    const copy = networkPanel.querySelector('[data-network-copy]');
    copy.textContent = networkText('Диагностика', 'Diagnostics');
    copy.hidden = loading;
    const close = networkPanel.querySelector('[data-network-close]');
    close.textContent = networkText('Закрыть', 'Close');
    close.hidden = !initialDataReady || loading;
}
function reportNetworkFailure(code, path, status = 0, uncertain = false) {
    // Only technical metadata: never record auth headers, query strings or request bodies.
    if (networkFailure?.uncertain && !uncertain && code !== 'auth') { renderNetworkStatus(); return; }
    networkFailure = {code, endpoint: path.split('?')[0], status, uncertain,
        version: window.TEMLI_I18N?.VERSION || '', time: new Date().toISOString()};
    renderNetworkStatus();
}
networkPanel.querySelector('[data-network-close]').onclick = () => networkPanel.classList.add('hidden');
networkPanel.querySelector('[data-network-retry]').onclick = () => fetchData();
networkPanel.querySelector('[data-network-copy]').onclick = async () => {
    const report = JSON.stringify(networkFailure, null, 2);
    const output = networkPanel.querySelector('pre');
    output.textContent = report;
    output.hidden = false;
    try { await navigator.clipboard.writeText(report); } catch (_) { /* Selectable text remains available. */ }
};
window.addEventListener('temli-language-change', () => {
    renderNetworkStatus(dataLoading, false);
    renderTopLesson();
});

async function apiFetch(path, options = {}) {
    const { quiet = false, ...fetchOptions } = options;
    const controller = new AbortController();
    const readOnly = (fetchOptions.method || 'GET').toUpperCase() === 'GET'
        || /^\/get_/.test(path) || path === '/bootstrap';
    const timer = setTimeout(() => controller.abort(), readOnly ? 15000 : 45000);
    let status = 0;
    try {
        const response = await fetch(API_URL + path, {
            ...fetchOptions,
            headers: apiHeaders(fetchOptions.headers || {}, fetchOptions.body || null),
            signal: controller.signal
        });
        status = response.status;
        if (status === 401 || status === 403) throw Object.assign(new Error(), { networkCode: 'auth' });
        if (status >= 500 || status === 429) throw Object.assign(new Error(), { networkCode: 'http' });
        // Read the entire response under the deadline, including a stalled response body.
        const body = await response.arrayBuffer();
        const buffered = new Response(body, {status, statusText: response.statusText, headers: response.headers});
        if (response.headers.get('content-type')?.includes('application/json')) {
            try { JSON.parse(new TextDecoder().decode(body)); }
            catch (_) { throw Object.assign(new Error(), { networkCode: 'invalid_response' }); }
        } else if (!path.startsWith('/download_') && !path.startsWith('/export_')) {
            throw Object.assign(new Error(), { networkCode: 'invalid_response' });
        }
        return buffered;
    } catch (error) {
        const code = error.networkCode || (navigator.onLine === false ? 'offline' : controller.signal.aborted ? 'timeout' : 'network');
        const uncertain = !readOnly && code !== 'auth';
        if (!quiet) reportNetworkFailure(code, path, status, uncertain);
        const message = code === 'auth'
            ? networkText('Откройте приложение заново через Telegram-бота.', 'Reopen the app through the Telegram bot.')
            : uncertain
                ? networkText('Ответ не получен. Перед повторением проверьте результат действия.', 'No response received. Check the action’s result before repeating it.')
                : networkText('Не удалось загрузить данные. Повторите загрузку.', 'Could not load data. Retry loading.');
        throw Object.assign(new Error(message), {networkCode: code});
    } finally { clearTimeout(timer); }
}

const PENDING_STUDENT_PAYMENT_KEY = 'temli.pending-student-payment.v1';

function newPaymentRequestId() {
    if (window.crypto?.randomUUID) return `payment-${window.crypto.randomUUID()}`;
    return `payment-${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function pendingStudentPayment(payload) {
    const fingerprint = JSON.stringify(payload);
    try {
        const saved = JSON.parse(sessionStorage.getItem(PENDING_STUDENT_PAYMENT_KEY) || 'null');
        if (saved?.fingerprint === fingerprint && typeof saved.requestId === 'string') return saved.requestId;
    } catch (error) {}
    const requestId = newPaymentRequestId();
    try { sessionStorage.setItem(PENDING_STUDENT_PAYMENT_KEY, JSON.stringify({ fingerprint, requestId })); } catch (error) {}
    return requestId;
}

function clearPendingStudentPayment(requestId) {
    try {
        const saved = JSON.parse(sessionStorage.getItem(PENDING_STUDENT_PAYMENT_KEY) || 'null');
        if (saved?.requestId === requestId) sessionStorage.removeItem(PENDING_STUDENT_PAYMENT_KEY);
    } catch (error) {}
}

function cachedWeekSchedule(weekKey) {
    const cached = weekScheduleCache.get(weekKey);
    if (!cached || Date.now() - cached.savedAt > WEEK_CACHE_TTL_MS) {
        weekScheduleCache.delete(weekKey);
        return null;
    }
    weekScheduleCache.delete(weekKey);
    weekScheduleCache.set(weekKey, cached);
    return { requestedWeek: weekKey, schedule: cached.schedule };
}

function storeWeekSchedule(weekKey, schedule) {
    weekScheduleCache.delete(weekKey);
    weekScheduleCache.set(weekKey, { schedule, savedAt: Date.now() });
    while (weekScheduleCache.size > WEEK_CACHE_LIMIT) {
        weekScheduleCache.delete(weekScheduleCache.keys().next().value);
    }
}

function clearWeekScheduleCache() {
    weekCacheGeneration += 1;
    weekScheduleCache.clear();
    window.clearTimeout(adjacentWeekPrefetchTimer);
}

function backgroundWeekPrefetchAllowed() {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    return !(connection?.saveData || ['slow-2g', '2g'].includes(connection?.effectiveType));
}

async function fetchWeekSchedule(monday, { allowCached = false } = {}) {
    const requestedWeek = dateKey(monday);
    if (allowCached) {
        const cached = cachedWeekSchedule(requestedWeek);
        if (cached) return cached;
    }
    const generation = weekCacheGeneration;
    const inflight = weekScheduleInflight.get(requestedWeek);
    if (inflight?.generation === generation) return inflight.promise;
    const promise = (async () => {
        const response = await apiFetch('/get_week_schedule', {
            method: 'POST',
            quiet: allowCached,
            body: JSON.stringify({ week_start: requestedWeek })
        });
        const data = await response.json();
        if (data.status !== 'ok') throw new Error(data.message || 'Ошибка расписания');
        const schedule = data.schedule || {};
        if (generation === weekCacheGeneration) storeWeekSchedule(requestedWeek, schedule);
        return { requestedWeek, schedule };
    })();
    weekScheduleInflight.set(requestedWeek, { generation, promise });
    try {
        return await promise;
    } finally {
        const current = weekScheduleInflight.get(requestedWeek);
        if (current?.promise === promise) weekScheduleInflight.delete(requestedWeek);
    }
}

function scheduleAdjacentWeekPrefetch(monday) {
    window.clearTimeout(adjacentWeekPrefetchTimer);
    // Cross-region storage is deliberately not prefetched: these reads used to
    // occupy the backend lock just as the user opened or saved a lesson.
}

async function loadSchedule() {
    const requestedMonday = new Date(state.currentMonday);
    const data = await fetchWeekSchedule(requestedMonday);

    // Если пользователь успел перелистнуть неделю, не затираем новый экран старым ответом.
    if (data.requestedWeek !== dateKey(state.currentMonday)) return false;
    state.schedule = data.schedule;
    renderCalendar();
    scheduleAdjacentWeekPrefetch(requestedMonday);
    return true;
}

async function loadStudents() {
    const response = await apiFetch('/get_students');
    const data = await response.json();
    if (!response.ok || data.status === 'error') throw new Error(data.message || 'Ошибка загрузки учеников');
    state.students = data.students || {};
    fillStudentsDropdown();
    return true;
}

async function loadSettings() {
    try {
        const response = await apiFetch('/get_settings');
        if (!response.ok) throw new Error('Settings unavailable');
        const data = await response.json();
        if (data.status === 'ok') {
            state.settings = data.settings || state.settings;
            await window.TEMLI_I18N?.setLanguage(state.settings.language || 'ru');
            window.TEMLI_I18N?.setCurrency(state.settings.currency || 'RUB');
            state.onboardingNeeded = data.onboarding_needed === true;
            updateVisibleHoursFromSettingsAndLessons();
            if (!initialDataReady) autoFitWeekPending = true;
        }
        if (data.status !== 'ok') throw new Error('Settings unavailable');
        return true;
    } catch (error) {
        console.warn('Настройки пока недоступны:', error);
        throw error;
    }
}

function scheduleWorkCenterRefresh(delay = 300) {
    window.clearTimeout(scheduleWorkCenterRefresh.timer);
    scheduleWorkCenterRefresh.timer = window.setTimeout(() => {
        refreshWorkCenterBadge();
    }, delay);
}

async function fetchData() {
    if (dataLoading) return;
    dataLoading = true;
    networkFailure = null;
    renderNetworkStatus(true);
    try {
        clearWeekScheduleCache();
        if (SUPPORTS_BOOTSTRAP) {
            await loadBootstrap();
        } else {
            const results = await Promise.allSettled([loadSchedule(), loadStudents(), loadSettings()]);
            const failure = results.find(result => result.status === 'rejected');
            if (failure) throw failure.reason;
        }
        renderCalendar();
        scheduleWorkCenterRefresh();
        refreshPendingBindingBadge();
        showOnboardingIfNeeded();
        initialDataReady = true;
        networkFailure = null;
        networkPanel.classList.add('hidden');
        networkPanel.querySelector('pre').hidden = true;
    } catch (error) {
        console.error('Ошибка загрузки:', error);
        if (!networkFailure) reportNetworkFailure(error.networkCode || 'invalid_response', '/initial_load');
        renderNetworkStatus();
    } finally { dataLoading = false; }
}

async function refreshScheduleOnly({ refreshHelper = true } = {}) {
    try {
        clearWeekScheduleCache();
        const applied = await loadSchedule();
        if (applied && refreshHelper) scheduleWorkCenterRefresh();
    } catch (error) {
        console.error('Ошибка загрузки расписания:', error);
    }
}

async function refreshScheduleAndStudents() {
    try {
        clearWeekScheduleCache();
        if (SUPPORTS_BOOTSTRAP) {
            await loadBootstrap({ applySettings: false });
        } else {
            await Promise.all([loadSchedule(), loadStudents()]);
        }
        renderCalendar();
        scheduleWorkCenterRefresh();
    } catch (error) {
        console.error('Ошибка обновления данных:', error);
    }
}

async function loadBootstrap({ applySettings = true } = {}) {
    const requestedWeek = dateKey(state.currentMonday);
    const response = await apiFetch('/bootstrap', {
        method: 'POST',
        body: JSON.stringify({ week_start: requestedWeek })
    });
    const data = await response.json();
    if (!response.ok || data.status !== 'ok') throw new Error(data.message || 'Ошибка загрузки данных');
    state.schedule = data.schedule || {};
    state.students = data.students || {};
    storeWeekSchedule(requestedWeek, state.schedule);
    fillStudentsDropdown();
    if (applySettings) {
        state.settings = data.settings || state.settings;
        await window.TEMLI_I18N?.setLanguage(state.settings.language || 'ru');
        window.TEMLI_I18N?.setCurrency(state.settings.currency || 'RUB');
        state.onboardingNeeded = data.onboarding_needed === true;
        updateVisibleHoursFromSettingsAndLessons();
        if (!initialDataReady) autoFitWeekPending = true;
    }
    return true;
}

async function refreshStudentsOnly() {
    try {
        await loadStudents();
        renderCalendar();
        scheduleWorkCenterRefresh();
    } catch (error) {
        console.error('Ошибка обновления учеников:', error);
    }
}

function fillStudentsDropdown() {
    const select = document.getElementById('student-select');
    if (!select) return;
    select.innerHTML = '<option value="">-- Выбрать ученика --</option><option value="manual">Вписать вручную...</option>';

    visibleStudentEntries().forEach(([id, raw]) => {
        const info = typeof raw === 'string' ? { name: raw } : (raw || {});
        if (info.status === 'paused' || info.archived) return;
        const option = document.createElement('option');
        option.value = id;
        option.textContent = info.name || id;
        option.setAttribute('data-i18n-ignore', '');
        option.dataset.name = info.name || id;
        select.appendChild(option);
    });
}

function groupMemberOptions(selectedId = '') {
    const options = ['<option value="">-- Выбрать ученика --</option>', '<option value="manual">Вписать вручную...</option>'];
    visibleStudentEntries().forEach(([id, raw]) => {
        const info = typeof raw === 'string' ? { name: raw } : (raw || {});
        if ((info.status === 'paused' || info.archived) && String(id) !== String(selectedId)) return;
        const selected = String(id) === String(selectedId) ? ' selected' : '';
        options.push(`<option value="${escapeHtml(String(id))}" data-name="${escapeHtml(info.name || String(id))}" data-i18n-ignore${selected}>${escapeHtml(info.name || String(id))}</option>`);
    });
    return options.join('');
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

function userContent(value) {
    return `<span data-i18n-ignore>${escapeHtml(value)}</span>`;
}

function uiText(value) {
    return window.TEMLI_I18N?.translated(value) ?? String(value ?? '');
}

function userContentOr(value, fallback) {
    return value ? userContent(value) : `<span>${escapeHtml(uiText(fallback))}</span>`;
}

function uiMessage(strings, ...values) {
    return strings.map((part, index) => uiText(part) + (index < values.length ? String(values[index] ?? '') : '')).join('');
}

function threadIcon(name, extraClass = '') {
    const className = ['thread-icon', extraClass].filter(Boolean).join(' ');
    return `<svg class="${className}" aria-hidden="true"><use href="#ti-${name}"></use></svg>`;
}

function setThreadButtonLabel(button, icon, label) {
    if (!button) return;
    button.innerHTML = `${threadIcon(icon)}${escapeHtml(label)}`;
}

function addGroupMemberRow(member = null) {
    const container = document.getElementById('group-members-container');
    const row = document.createElement('div');
    row.className = 'group-member-row';
    const memberId = member?.student_id || '';
    const known = memberId && state.students[memberId];
    const manual = member && !known;
    row.innerHTML = `
        <select class="group-member-select">${groupMemberOptions(manual ? 'manual' : memberId)}</select>
        <input type="text" class="group-member-manual ${manual ? '' : 'hidden'}" placeholder="Имя ученика" value="${escapeHtml(manual ? (member?.name || '') : '')}">
        <input type="number" class="group-member-price" min="0" step="1" inputmode="decimal" placeholder="Цена, ₽" value="${escapeHtml(member?.price ?? '')}">
        <button type="button" class="contact-remove-btn group-member-remove" title="Удалить" aria-label="Удалить">${threadIcon('close')}</button>
    `;
    const select = row.querySelector('.group-member-select');
    const input = row.querySelector('.group-member-manual');
    if (manual) select.value = 'manual';
    select.addEventListener('change', () => {
        const isManual = select.value === 'manual';
        input.classList.toggle('hidden', !isManual);
        if (isManual) input.focus();
    });
    row.querySelector('.group-member-remove').onclick = () => row.remove();
    container.appendChild(row);
}

function renderGroupMembers(members = []) {
    const container = document.getElementById('group-members-container');
    container.innerHTML = '';
    (members || []).forEach(member => addGroupMemberRow(member));
    if (!members || !members.length) addGroupMemberRow();
}

function collectGroupMembers() {
    const result = [];
    document.querySelectorAll('#group-members-container .group-member-row').forEach(row => {
        const select = row.querySelector('.group-member-select');
        const manualInput = row.querySelector('.group-member-manual');
        const priceInput = row.querySelector('.group-member-price');
        const price = Number(priceInput?.value || 0);
        if (!select?.value) return;
        if (select.value === 'manual') {
            const name = manualInput?.value.trim() || '';
            if (name) result.push({ student_id: 'manual', name, price: price > 0 ? price : '' });
        } else {
            const option = select.options[select.selectedIndex];
            result.push({ student_id: select.value, name: option?.dataset.name || option?.textContent || select.value, price: price > 0 ? price : '' });
        }
    });
    return result;
}

function updateLessonTypeUI() {
    const type = document.getElementById('lesson-type-select').value;
    const isGroup = type === 'group';
    const isPersonal = type === 'personal';
    document.getElementById('group-editor-group').classList.toggle('hidden', !isGroup);
    document.getElementById('personal-event-group').classList.toggle('hidden', !isPersonal);
    document.getElementById('student-select-group').classList.toggle('hidden', isGroup || isPersonal || state.editingExisting);
    document.getElementById('student-fixed-group').classList.toggle('hidden', isGroup || isPersonal || !state.editingExisting);
    document.getElementById('lesson-student-setup')?.classList.toggle('hidden', isGroup || isPersonal || state.editingExisting);
    document.getElementById('student-lesson-price-group')?.classList.toggle('hidden', isGroup || isPersonal);
    document.querySelector('.reminder-group')?.classList.toggle('hidden', isPersonal);
    if (!state.editingExisting) {
        document.getElementById('modal-title').textContent = isPersonal
            ? 'Добавить личное дело'
            : (isGroup ? 'Добавить групповое занятие' : 'Добавить занятие');
    }
}

function lessonBoundsForCurrentWeek() {
    let earliest = null;
    let latest = null;

    Object.values(state.schedule || {}).forEach(lessons => {
        (lessons || []).forEach(lesson => {
            const [hourRaw, minuteRaw] = String(lesson.time || '').split(':');
            const hour = Number(hourRaw);
            const minute = Number(minuteRaw);
            if (!Number.isFinite(hour) || !Number.isFinite(minute)) return;

            const start = hour * 60 + minute;
            if (start < START_HOUR * 60 || start > END_HOUR * 60 + 59) return;
            const duration = Math.max(1, Number(lesson.duration || 60));
            const end = Math.min((END_HOUR + 1) * 60, start + duration);

            earliest = earliest === null ? start : Math.min(earliest, start);
            latest = latest === null ? end : Math.max(latest, end);
        });
    });

    return earliest === null || latest === null ? null : { earliest, latest };
}

function autoFitCalendarToWeek() {
    if (!autoFitWeekPending) return;
    autoFitWeekPending = false;

    const container = document.getElementById('calendar-container');
    if (!container) return;

    let visibleStart = workingTimeMinutes(state.settings.work_start, 6 * 60);
    let visibleEnd = workingTimeMinutes(state.settings.work_end, 24 * 60, true);
    if (visibleEnd <= visibleStart) {
        visibleStart = 6 * 60;
        visibleEnd = 24 * 60;
    }
    const spanMinutes = Math.max(60, visibleEnd - visibleStart);
    const viewportHeight = Math.max(1, container.clientHeight - 12);

    // Fit the configured working day on first open, while keeping all 24 hours scrollable.
    const fitHeight = viewportHeight * 60 / spanMinutes;
    const targetHeight = Math.max(MIN_HOUR_HEIGHT, Math.min(MAX_HOUR_HEIGHT, fitHeight));
    applyHourHeightSmooth(targetHeight);
    container.scrollTop = Math.max(0, visibleStart * hourHeight / 60);
}

function scheduleCalendarAutoFit() {
    requestAnimationFrame(() => requestAnimationFrame(autoFitCalendarToWeek));
}

function moveTimeLabel(minutes) {
    const value = Math.max(0, Math.min(1439, Math.round(minutes)));
    return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
}

function isMoveTargetAvailable(date, startMinutes, lesson = state.selectedLesson) {
    const duration = Math.max(5, Number(lesson?.duration || 60));
    if (!lesson || startMinutes < 0 || startMinutes + duration > 24 * 60) return false;
    return !(state.schedule[date] || []).some(item => {
        if (item.cancelled || (date === lesson.date && item.id === lesson.id)) return false;
        const [hour, minute] = String(item.time || '00:00').split(':').map(Number);
        const itemStart = hour * 60 + minute;
        const itemEnd = itemStart + Math.max(5, Number(item.duration || 60));
        return startMinutes < itemEnd && startMinutes + duration > itemStart;
    });
}

function dragTargetFromPoint(clientX, clientY) {
    const grid = document.getElementById('week-grid');
    const dates = visibleCalendarDates();
    if (!grid || !dates.length) return null;
    const rect = grid.getBoundingClientRect();
    if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) return null;
    const dayIndex = Math.max(0, Math.min(dates.length - 1, Math.floor((clientX - rect.left) / (rect.width / dates.length))));
    const rawMinutes = START_HOUR * 60 + (clientY - rect.top) * 60 / hourHeight;
    const cellStart = Math.max(START_HOUR * 60, Math.min(END_HOUR * 60, Math.floor(rawMinutes / 60) * 60));
    const startMinutes = cellStart;
    const date = dateKey(dates[dayIndex]);
    return {date, dayIndex, cellStart, startMinutes, time:moveTimeLabel(startMinutes),
        available:isMoveTargetAvailable(date, startMinutes), dayOff:isDayOffDate(dates[dayIndex]), rect};
}

function clearLessonDragVisuals() {
    document.querySelector('.lesson-drag-ghost')?.remove();
    document.querySelector('.lesson-drop-preview')?.remove();
    document.body.classList.remove('calendar-dragging');
}

function renderLessonDropPreview(target) {
    let preview = document.querySelector('.lesson-drop-preview');
    if (!target) {
        preview?.remove();
        return;
    }
    const layer = document.getElementById('events-layer');
    if (!preview) {
        preview = document.createElement('div');
        preview.className = 'lesson-drop-preview';
        layer.appendChild(preview);
    }
    const dates = visibleCalendarDates();
    const colWidth = layer.clientWidth / dates.length;
    const duration = Math.max(5, Number(state.selectedLesson?.duration || 60));
    preview.className = `lesson-drop-preview ${target.available ? 'is-available' : 'is-unavailable'} ${target.dayOff ? 'is-day-off' : ''}`;
    preview.style.left = `${target.dayIndex * colWidth + 2}px`;
    preview.style.width = `${Math.max(20, colWidth - 4)}px`;
    preview.style.top = `${(target.startMinutes - START_HOUR * 60) * hourHeight / 60}px`;
    preview.style.height = `${Math.max(18, duration * hourHeight / 60 - 2)}px`;
    preview.textContent = target.time;
}

function updateLessonDrag(clientX, clientY) {
    const session = lessonDragSession;
    if (!session?.active) return;
    session.clientX = clientX;
    session.clientY = clientY;
    const container = document.getElementById('calendar-container');
    const viewport = container.getBoundingClientRect();
    if (clientY < viewport.top + 34) container.scrollTop = Math.max(0, container.scrollTop - 12);
    else if (clientY > viewport.bottom - 34) container.scrollTop += 12;
    const target = dragTargetFromPoint(clientX, clientY);
    session.target = target;
    renderLessonDropPreview(target);
    const ghost = document.querySelector('.lesson-drag-ghost');
    if (ghost) {
        ghost.style.left = `${Math.max(6, Math.min(window.innerWidth - ghost.offsetWidth - 6, clientX - ghost.offsetWidth / 2))}px`;
        const above = clientY - ghost.offsetHeight - 20;
        ghost.style.top = `${above >= 6 ? above : Math.min(window.innerHeight - ghost.offsetHeight - 6, clientY + 20)}px`;
    }
    const hint = document.getElementById('move-hint-text');
    hint.textContent = !target ? uiText('Перетащите в календарь') : target.time;
}

function beginLessonDrag(session, clientX, clientY) {
    if (session.active) return;
    session.active = true;
    suppressLessonClickUntil = Date.now() + 800;
    const ghost = session.clone;
    ghost.classList.add('lesson-drag-ghost');
    ghost.style.width = `${Math.min(110, Math.max(68, session.width))}px`;
    ghost.style.height = `${Math.min(38, Math.max(30, session.height))}px`;
    document.body.appendChild(ghost);
    document.body.classList.add('calendar-dragging');
    if (!state.isMoving) {
        state.selectedLesson = {date:session.date, ...session.lesson};
        state.isMoving = true;
        state.pendingMove = null;
    }
    updateLessonDrag(clientX, clientY);
    haptic('light');
}

function finishLessonDrag() {
    const session = lessonDragSession;
    if (!session) return;
    const target = session.target;
    clearLessonDragVisuals();
    lessonDragSession = null;
    if (!session.active) return;
    if (!target?.available) {
        uxMessage(uiText('Сюда поставить нельзя: время занято или занятие выйдет за пределы дня.', 'Cannot place here: the time is busy or the lesson would cross midnight.'));
        state.isMoving = false;
        state.selectedLesson = null;
        state.pendingMove = null;
        return;
    }
    const commit = () => confirmMoveTarget(target.date, target.time);
    if (target.dayOff) {
        document.getElementById('day-off-warning-title').textContent = uiText('Перенос в выходной');
        document.getElementById('day-off-warning-desc').textContent = uiText('Кажется, календарь рассчитывал отдохнуть 😄 Всё равно перенести занятие на выходной?');
        document.getElementById('btn-day-off-confirm').textContent = uiText('Всё равно перенести');
        document.getElementById('btn-day-off-cancel').textContent = uiText('Не сегодня');
        openDayOffWarning(commit);
    } else commit();
}

function resetLessonDragSession(resetMove = true) {
    const session = lessonDragSession;
    if (!session) return;
    session.cleanup?.();
    clearTimeout(session.watchdog);
    clearLessonDragVisuals();
    lessonDragSession = null;
    if (resetMove && session.active) {
        state.isMoving = false;
        state.selectedLesson = null;
        state.pendingMove = null;
    }
}

function updateLessonCardScroll(session, clientY) {
    const container = session.scrollContainer;
    const now = performance.now();
    const dt = Math.max(1, now - session.lastAt);
    session.scrollVelocity = -(clientY - session.lastY) / dt;
    session.lastY = clientY;
    session.lastAt = now;
    container.scrollTop = session.scrollStart - (clientY - session.startY);
}

function startLessonScrollMomentum(container, velocity) {
    cancelAnimationFrame(lessonScrollFrame);
    let speed = Math.max(-1.4, Math.min(1.4, Number(velocity) || 0));
    let last = performance.now();
    const step = now => {
        const dt = Math.min(32, now - last);
        last = now;
        const before = container.scrollTop;
        container.scrollTop += speed * dt;
        if (container.scrollTop === before || Math.abs(speed) < .025) return;
        speed *= Math.pow(.9, dt / 16);
        lessonScrollFrame = requestAnimationFrame(step);
    };
    if (Math.abs(speed) >= .08) lessonScrollFrame = requestAnimationFrame(step);
}

function attachLessonDrag(card, date, lesson) {
    card.addEventListener('pointerdown', event => {
        if (event.button !== 0 || lesson.cancelled) return;
        if (lessonDragSession) resetLessonDragSession(true);
        const invisibleMoveState = state.isMoving
            && document.getElementById('move-hint').classList.contains('hidden')
            && document.getElementById('move-modal-overlay').classList.contains('hidden')
            && document.getElementById('day-off-warning-overlay').classList.contains('hidden');
        if (invisibleMoveState) {
            state.isMoving = false;
            state.selectedLesson = null;
            state.pendingMove = null;
        }
        if (state.isMoving && state.selectedLesson?.id !== lesson.id) return;
        cancelAnimationFrame(lessonScrollFrame);
        const bounds = card.getBoundingClientRect();
        const container = document.getElementById('calendar-container');
        const session = {pointerId:event.pointerId, pointerType:event.pointerType, date, lesson,
            startX:event.clientX, startY:event.clientY, clientX:event.clientX, clientY:event.clientY,
            startedAt:Date.now(),
            width:bounds.width, height:bounds.height, clone:card.cloneNode(true), active:false,
            intent:'', target:null, scrollContainer:container, scrollStart:container.scrollTop,
            lastY:event.clientY, lastAt:performance.now(), scrollVelocity:0, cleanup:null, watchdog:null};
        lessonDragSession = session;
        const move = pointerEvent => {
            if (lessonDragSession !== session || pointerEvent.pointerId !== session.pointerId) return;
            session.clientX = pointerEvent.clientX;
            session.clientY = pointerEvent.clientY;
            const dx = pointerEvent.clientX - session.startX;
            const dy = pointerEvent.clientY - session.startY;
            const absX = Math.abs(dx);
            const absY = Math.abs(dy);
            const distance = Math.hypot(dx, dy);
            if (!session.active && session.pointerType === 'touch' && !session.intent) {
                const elapsed = Math.max(1, Date.now() - session.startedAt);
                const fastVertical = absY >= 8 && absY > absX * 1.6 && elapsed <= 140 && absY / elapsed >= .08;
                if (fastVertical) {
                    session.intent = 'scroll';
                    suppressLessonClickUntil = Date.now() + 700;
                    haptic('light');
                } else if (absX >= MOVE_DRAG_THRESHOLD || distance >= 7) {
                    session.intent = 'drag';
                    beginLessonDrag(session, pointerEvent.clientX, pointerEvent.clientY);
                }
            } else if (!session.active && session.pointerType !== 'touch' && distance >= MOVE_DRAG_THRESHOLD) {
                session.intent = 'drag';
                beginLessonDrag(session, pointerEvent.clientX, pointerEvent.clientY);
            }
            if (session.intent === 'scroll') {
                pointerEvent.preventDefault();
                updateLessonCardScroll(session, pointerEvent.clientY);
                return;
            }
            if (session.active) {
                pointerEvent.preventDefault();
                updateLessonDrag(pointerEvent.clientX, pointerEvent.clientY);
            }
        };
        const end = pointerEvent => {
            if (lessonDragSession !== session || pointerEvent.pointerId !== session.pointerId) return;
            cleanup();
            if (session.active) {
                pointerEvent.preventDefault();
                finishLessonDrag();
            } else if (session.intent === 'scroll') {
                pointerEvent.preventDefault();
                startLessonScrollMomentum(session.scrollContainer, session.scrollVelocity);
                suppressLessonClickUntil = Date.now() + 700;
                lessonDragSession = null;
            } else {
                if (Date.now() - session.startedAt >= MOVE_LONG_PRESS_MS) suppressLessonClickUntil = Date.now() + 700;
                lessonDragSession = null;
            }
        };
        const cancel = pointerEvent => {
            if (lessonDragSession !== session || pointerEvent.pointerId !== session.pointerId) return;
            cleanup();
            if (session.active) {
                clearLessonDragVisuals();
                lessonDragSession = null;
                state.isMoving = false;
                state.selectedLesson = null;
                state.pendingMove = null;
            } else {
                if (session.intent === 'scroll') suppressLessonClickUntil = Date.now() + 700;
                lessonDragSession = null;
            }
        };
        const cleanup = () => {
            clearTimeout(session.watchdog);
            document.removeEventListener('pointermove', move, true);
            document.removeEventListener('pointerup', end, true);
            document.removeEventListener('pointercancel', cancel, true);
        };
        session.cleanup = cleanup;
        session.watchdog = setTimeout(() => {
            if (lessonDragSession === session) resetLessonDragSession(true);
        }, 12000);
        document.addEventListener('pointermove', move, {capture:true, passive:false});
        document.addEventListener('pointerup', end, {capture:true, passive:false});
        document.addEventListener('pointercancel', cancel, true);
    });
}

function syncCalendarHeaderScrollbar() {
    const container = document.getElementById('calendar-container');
    if (!container) return;
    const scrollbarWidth = Math.max(0, container.offsetWidth - container.clientWidth);
    document.documentElement.style.setProperty('--calendar-scrollbar-width', `${scrollbarWidth}px`);
}

function renderCalendar() {
    updateVisibleHoursFromSettingsAndLessons();
    const labels = document.getElementById('time-labels');
    const grid = document.getElementById('week-grid');
    const layer = document.getElementById('events-layer');
    if (!labels || !grid || !layer) return;
    const scrollTop = document.getElementById('calendar-container').scrollTop;
    document.body.classList.toggle('calendar-day-view', calendarView === 'day');
    document.documentElement.style.setProperty('--calendar-columns', calendarView === 'day' ? '1' : '7');

    labels.innerHTML = '';
    grid.innerHTML = '';
    layer.innerHTML = '<div id="current-time-line" class="current-time-line hidden"><div class="time-line-dot"></div></div>';
    document.documentElement.style.setProperty('--hour-height', `${hourHeight}px`);
    document.documentElement.style.setProperty('--visible-hour-count', String(END_HOUR - START_HOUR + 1));

    document.getElementById('btn-date-picker').title = `${uiText('Выбрать дату')} · ${formatWeekRange(state.currentMonday)}`;

    const todayKey = dateKey(new Date());
    const header = document.getElementById('days-header');
    header.innerHTML = '';

    for (const dayDate of visibleCalendarDates()) {
        const cell = document.createElement('div');
        cell.className = `day-header-cell ${dateKey(dayDate) === todayKey ? 'today' : ''} ${isDayOffDate(dayDate) ? 'day-off' : ''}`;
        cell.innerHTML = `<div>${escapeHtml(dayDate.toLocaleDateString(uiLocale(), { weekday: calendarView === 'day' ? 'long' : 'short' }))}</div><div class="day-num">${dayDate.getDate()}</div>`;
        header.appendChild(cell);
    }

    for (let hour = START_HOUR; hour <= END_HOUR; hour++) {
        const label = document.createElement('div');
        label.className = 'time-label';
        label.textContent = `${String(hour).padStart(2, '0')}:00`;
        labels.appendChild(label);
    }
    const dayEndLabel = document.createElement('div');
    dayEndLabel.className = 'day-end-label';
    dayEndLabel.textContent = '00:00';
    labels.appendChild(dayEndLabel);

    for (const dayDate of visibleCalendarDates()) {
        const column = document.createElement('div');
        const key = dateKey(dayDate);
        column.className = `day-column ${dateKey(dayDate) === todayKey ? 'today' : ''} ${isDayOffDate(dayDate) ? 'day-off' : ''}`;

        for (let hour = START_HOUR; hour <= END_HOUR; hour++) {
            const slot = document.createElement('div');
            slot.className = 'time-slot';
            const time = `${String(hour).padStart(2, '0')}:00`;
            let moveTargetAvailable = true;
            let moveTargetDayOff = false;
            if (state.isMoving && state.selectedLesson) {
                const candidateStart = hour * 60;
                moveTargetAvailable = isMoveTargetAvailable(key, candidateStart);
                moveTargetDayOff = isDayOffDate(dayDate);
                slot.classList.add(moveTargetAvailable ? 'move-slot-available' : 'move-slot-unavailable');
                if (moveTargetAvailable && moveTargetDayOff) slot.classList.add('move-slot-day-off');
                slot.setAttribute('aria-disabled', String(!moveTargetAvailable));
                slot.title = !moveTargetAvailable
                    ? uiText('Время занято или недоступно')
                    : moveTargetDayOff ? uiText('Выходной: потребуется подтверждение') : uiText('Перенести сюда');
            }
            slot.addEventListener('click', () => {
                if (state.isMoving) {
                    if (!moveTargetAvailable) return;
                    if (moveTargetDayOff) {
                        document.getElementById('day-off-warning-title').textContent = 'Перенос в выходной';
                        document.getElementById('day-off-warning-desc').textContent = 'Кажется, календарь рассчитывал отдохнуть 😄 Всё равно перенести занятие на выходной?';
                        document.getElementById('btn-day-off-confirm').textContent = 'Всё равно перенести';
                        document.getElementById('btn-day-off-cancel').textContent = 'Не сегодня';
                        openDayOffWarning(() => confirmMoveTarget(key, time));
                    } else {
                        confirmMoveTarget(key, time);
                    }
                    return;
                }
                openAddTypeChooser(key, time);
            });
            column.appendChild(slot);
        }
        const dayEndSpacer = document.createElement('div');
        dayEndSpacer.className = 'day-end-spacer';
        column.appendChild(dayEndSpacer);
        grid.appendChild(column);
    }

    renderEvents();
    updateCurrentTimeLine();
    document.getElementById('calendar-container').scrollTop = scrollTop;
    window.dispatchEvent(new Event('temli-calendar-rendered'));
    requestAnimationFrame(syncCalendarHeaderScrollbar);
}

function renderEvents() {
    const layer = document.getElementById('events-layer');
    const dates = visibleCalendarDates();
    const colWidth = layer.clientWidth / dates.length;

    for (let dayIndex = 0; dayIndex < dates.length; dayIndex++) {
        const dayDate = dates[dayIndex];
        const key = dateKey(dayDate);
        const lessons = state.schedule[key] || [];

        lessons.forEach(lesson => {
            const [hour, minute] = String(lesson.time || '00:00').split(':').map(Number);
            if (hour < START_HOUR || hour > END_HOUR) return;

            const duration = Math.max(5, parseInt(lesson.duration || 60, 10));
            const card = document.createElement('div');
            const isActiveMove = state.isMoving && state.selectedLesson && state.selectedLesson.id === lesson.id;
            const isPersonal = lesson.entry_type === 'personal';
            const color = isPersonal ? null : getStudentColor(lesson.student_id, lesson.student);
            const colorClass = typeof color === 'number' ? `color-${color}` : '';
            const isGroup = !isPersonal && lesson.lesson_type === 'group';
            const groupMembers = Array.isArray(lesson.group_members) ? lesson.group_members : [];
            const groupPaidCount = groupMembers.filter(member => member.paid && !member.free).length;
            const fullyPaid = isPersonal ? false : isGroup
                ? groupMembers.length > 0 && groupMembers.every(member => member.paid && !member.free)
                : Boolean(lesson.paid && !lesson.free);
            const partiallyPaid = isGroup && groupPaidCount > 0 && groupPaidCount < groupMembers.length;
            card.className = `event-card ${colorClass} ${fullyPaid ? 'paid-status' : ''} ${partiallyPaid ? 'partial-paid-status' : ''} ${isGroup ? 'group-event' : ''} ${isPersonal ? 'personal-event' : ''} ${lesson.cancelled ? 'cancelled-event' : ''} ${isActiveMove ? 'moving-active' : ''}`;
            if (typeof color === 'string') card.style.backgroundColor = color;

            const top = ((hour - START_HOUR) * 60 + minute) * hourHeight / 60;
            const height = Math.max(18, duration * hourHeight / 60 - 2);
            card.style.top = `${top}px`;
            card.style.left = `${dayIndex * colWidth + 2}px`;
            card.style.width = `${Math.max(20, colWidth - 4)}px`;
            card.style.height = `${height}px`;
            card.dataset.startMinutes = String((hour - START_HOUR) * 60 + minute);
            card.dataset.durationMinutes = String(duration);

            const title = document.createElement('div');
            title.className = 'event-title';
            const studentInfo = isGroup ? {} : getStudentInfo(lesson.student_id);
            const calendarTitle = isPersonal ? lesson.title : isGroup
                ? (lesson.group_name || lesson.student)
                : (studentInfo.calendar_name || lesson.student || studentInfo.name);
            title.textContent = calendarTitle || uiText(isGroup ? 'Группа' : (isPersonal ? 'Личное дело' : 'Ученик'));
            title.toggleAttribute('data-i18n-ignore', Boolean(calendarTitle));
            const cardHeight = height;
            if (cardHeight < 34) card.classList.add('event-card-compact');
            else if (cardHeight < 54) card.classList.add('event-card-medium');
            else card.classList.add('event-card-tall');
            card.appendChild(title);
            const endMinutes = hour * 60 + minute + duration;
            const endTime = `${String(Math.floor(endMinutes / 60) % 24).padStart(2, '0')}:${String(endMinutes % 60).padStart(2, '0')}`;
            const eventMeta = document.createElement('div');
            eventMeta.className = 'event-day-meta';
            const eventStatus = lesson.cancelled ? uiText('Отменено') : isGroup ? uiText('Группа') : paymentStatusLabel(lesson);
            eventMeta.textContent = `${lesson.time}–${endTime}${isPersonal ? '' : ' · ' + eventStatus}`;
            card.appendChild(eventMeta);
            card.tabIndex = 0;
            card.setAttribute('role', 'button');
            card.setAttribute('aria-label', `${title.textContent}, ${eventMeta.textContent}`);
            card.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); card.click(); }
            });
            if (isGroup && groupMembers.length) {
                const meta = document.createElement('div');
                meta.className = 'event-group-meta';
                meta.textContent = `${currencySymbol()} ${groupPaidCount}/${groupMembers.length}`;
                card.appendChild(meta);
            }

            attachLessonDrag(card, key, lesson);
            card.addEventListener('contextmenu', event => {
                event.preventDefault();
                openActionMenu(key, lesson);
            });
            card.addEventListener('click', event => {
                event.stopPropagation();
                if (Date.now() < suppressLessonClickUntil || state.isMoving) return;
                openActionMenu(key, lesson);
            });
            layer.appendChild(card);
        });
    }

    if (autoFitWeekPending) scheduleCalendarAutoFit();
}

function updateCurrentTimeLine() {
    const line = document.getElementById('current-time-line');
    if (!line) return;
    const now = new Date();
    let todayColumn = -1;

    const dates = visibleCalendarDates();
    for (let i = 0; i < dates.length; i++) {
        const date = dates[i];
        if (dateKey(date) === dateKey(now)) todayColumn = i;
    }

    if (todayColumn < 0 || now.getHours() < START_HOUR || now.getHours() > END_HOUR) {
        line.classList.add('hidden');
        return;
    }

    const columnWidth = document.getElementById('events-layer').clientWidth / dates.length;
    const minutes = now.getHours() * 60 + Math.floor(now.getMinutes() / 5) * 5 - START_HOUR * 60;
    line.style.top = `${minutes * hourHeight / 60}px`;
    line.style.left = `${todayColumn * columnWidth}px`;
    line.style.width = `${columnWidth}px`;
    line.classList.remove('hidden');
}

setInterval(updateCurrentTimeLine, 5 * 60 * 1000);

function lessonHasStarted(date, lesson) {
    const start = new Date(`${date}T${lesson.time || '00:00'}:00`);
    return !Number.isNaN(start.getTime()) && start.getTime() <= Date.now();
}

function openActionMenu(date, lesson) {
    state.selectedLesson = { date, ...lesson };
    const isPersonal = lesson.entry_type === 'personal';
    const isGroup = !isPersonal && lesson.lesson_type === 'group';
    const cancelled = !!lesson.cancelled;
    document.getElementById('action-contact-label').textContent = isGroup ? 'Участники — нажмите имя для связи и оплаты' : 'Связь';
    const actionTitle = isPersonal ? lesson.title : (isGroup ? (lesson.group_name || lesson.student) : lesson.student);
    document.getElementById('action-menu-title').innerHTML = `${userContentOr(actionTitle, isGroup ? 'Группа' : (isPersonal ? 'Личное дело' : 'Ученик'))} · ${userContent(lesson.time || '--:--')}`;
    const personalNotes = document.getElementById('personal-event-notes-view');
    personalNotes.textContent = lesson.notes || 'Без заметок';
    personalNotes.classList.toggle('hidden', !isPersonal);

    const paidButton = document.getElementById('btn-action-paid');
    setThreadButtonLabel(paidButton, paymentActionIcon(lesson), paymentActionLabel(lesson));
    document.getElementById('individual-payment-label').classList.toggle('hidden', isGroup);
    paidButton.classList.toggle('hidden', cancelled || isGroup);

    document.getElementById('btn-action-student-card').classList.toggle('hidden', isGroup);
    document.getElementById('btn-action-chat-student').classList.toggle('hidden', isGroup);
    document.getElementById('btn-action-chat-parent').classList.toggle('hidden', isGroup);
    setThreadButtonLabel(document.getElementById('btn-action-chat-student'), 'message', 'Написать ученику');
    setThreadButtonLabel(document.getElementById('btn-action-chat-parent'), 'message', 'Написать родителю');
    document.getElementById('btn-action-subscription').classList.toggle('hidden', cancelled || isGroup);
    document.getElementById('btn-action-free').classList.toggle('hidden', cancelled || isGroup);
    setThreadButtonLabel(document.getElementById('btn-action-free'), lesson.free ? 'restore' : 'free', lesson.free ? 'Отменить бесплатно' : 'Бесплатно');
    setThreadButtonLabel(document.getElementById('btn-action-cancel-once'), cancelled ? 'restore' : 'cancel', cancelled ? 'Вернуть занятие' : 'Отменить');
    document.getElementById('btn-action-report').classList.toggle('hidden', cancelled || !lessonHasStarted(date, lesson));
    document.getElementById('btn-action-teacher-delay').classList.toggle('hidden', cancelled);
    document.getElementById('btn-action-student-delay').classList.toggle('hidden', cancelled);
    const settingsButton = document.getElementById('btn-action-settings');
    setThreadButtonLabel(settingsButton, isGroup ? 'edit' : 'settings', isGroup ? 'Редактировать группу' : 'Настройки занятия');

    const details = document.getElementById('group-action-details');
    details.innerHTML = '';
    details.classList.toggle('hidden', !isGroup);
    if (isGroup) {
        (lesson.group_members || []).forEach(member => {
            const row = document.createElement('div');
            row.className = 'group-action-member';
            const price = lessonPriceValue(lesson, member);
            const statusClass = member.free ? 'is-free' : (member.paid ? 'is-paid' : 'is-debt');
            const status = paymentStatusLabel(member);
            row.innerHTML = `
                <button type="button" class="group-action-member-head" aria-expanded="false">
                    <strong>${userContentOr(member.name, 'Ученик')}</strong>
                    <span class="group-member-summary">${price > 0 ? `${money(price)}` : 'цена —'} <i class="group-member-status ${statusClass}">${status}</i> ${threadIcon('chevron-right', 'row-chevron')}</span>
                </button>
                <div class="group-member-actions hidden">
                    <div class="action-section-label">Связь</div>
                    <button type="button" data-member-action="student-chat">${threadIcon('message')}Написать ученику</button>
                    <button type="button" data-member-action="parent-chat">${threadIcon('message')}Написать родителю</button>
                    <div class="action-section-label">Оплата</div>
                    <div class="group-member-payment-row">
                    <button type="button" data-member-action="paid">${threadIcon(paymentActionIcon(member))}${escapeHtml(paymentActionLabel(member))}</button>
                    <button type="button" data-member-action="subscription">${threadIcon('subscription')}Абонемент</button>
                    <button type="button" data-member-action="free">${threadIcon(member.free ? 'restore' : 'free')}${member.free ? 'Отменить бесплатно' : 'Бесплатно'}</button>
                    </div>
                    <div class="action-section-label">Ученик</div>
                    <button type="button" data-member-action="card">${threadIcon('profile')}Карточка ученика</button>
                </div>`;
            const head = row.querySelector('.group-action-member-head');
            const actions = row.querySelector('.group-member-actions');
            head.onclick = () => {
                const opening = actions.classList.contains('hidden');
                details.querySelectorAll('.group-member-actions').forEach(box => box.classList.add('hidden'));
                details.querySelectorAll('.group-action-member-head').forEach(button => button.setAttribute('aria-expanded', 'false'));
                if (opening) {
                    actions.classList.remove('hidden');
                    head.setAttribute('aria-expanded', 'true');
                }
            };
            row.querySelector('[data-member-action="card"]').onclick = () => { closeActionMenu(); openStudentCard(member.student_id); };
            row.querySelector('[data-member-action="subscription"]').onclick = () => openSubscriptionForStudent(lesson, member.student_id);
            row.querySelector('[data-member-action="free"]').onclick = () => setFreeStateForSelected(member.student_id, !member.free);
            row.querySelector('[data-member-action="student-chat"]').onclick = () => openStudentContactFor(member.student_id);
            row.querySelector('[data-member-action="parent-chat"]').onclick = () => openParentContactFor(member.student_id);
            row.querySelector('[data-member-action="paid"]').onclick = () => setGroupMemberPaidState(state.selectedLesson, member, !member.paid);
            if (cancelled) row.querySelectorAll('.group-member-actions button').forEach(button => { button.disabled = true; });
            details.appendChild(row);
        });
    }
    for (const id of ['action-contact-label', 'btn-action-chat-student', 'btn-action-chat-parent',
        'action-notification-label', 'action-notification-actions', 'individual-payment-label',
        'action-payment-actions', 'btn-action-student-card', 'btn-action-report',
        'action-color-label', 'action-color-palette']) {
        document.getElementById(id)?.classList.toggle('hidden', isPersonal);
    }
    document.getElementById('btn-action-cancel-once').classList.toggle('hidden', isPersonal);
    document.getElementById('action-event-label').textContent = isPersonal ? 'Личное дело' : 'Занятие';
    setThreadButtonLabel(settingsButton, 'settings', isPersonal ? 'Изменить' : (isGroup ? 'Редактировать группу' : 'Настройки занятия'));
    document.getElementById('action-menu-overlay').classList.remove('hidden');
}

async function setGroupMemberPaidState(lesson, member, makePaid) {
    if (!lesson || !member || member.free) return;
    if (hasAllocatedPayment(member)) return explainAllocatedPayment(member.student_id);
    if (member.paid_via_subscription) return alert('Занятие оплачено абонементом. Снятие оплаты одного занятия заблокировано.');
    const verb = uiText(makePaid ? 'Отметить оплату' : 'Снять оплату');
    if (!confirm(uiMessage`${verb}: ${member.name || uiText('ученик')}?`)) return;
    const response = await apiFetch('/mark_paid', {
        method: 'POST',
        body: JSON.stringify({
            date: lesson.date,
            id: lesson.id,
            paid: makePaid,
            send_receipt: makePaid && state.settings.default_send_receipts !== false,
            student_id: member.student_id
        })
    });
    const result = await response.json();
    if (result.status !== 'ok') return alert(result.message || 'Ошибка изменения оплаты');
    closeActionMenu();
    await refreshScheduleOnly();
}

function closeActionMenu() {
    document.getElementById('action-menu-overlay').classList.add('hidden');
}

function startMove(date, lesson) {
    state.selectedLesson = { date, ...lesson };
    state.isMoving = true;
    document.body.classList.add('calendar-move-mode');
    document.getElementById('move-hint').classList.remove('hidden');
    renderCalendar();
}

function moveTimeToMinutes(value) {
    const match = /^(\d{2}):(\d{2})$/.exec(String(value || ''));
    if (!match) return null;
    const hour = Number(match[1]);
    const minute = Number(match[2]);
    return hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59 ? hour * 60 + minute : null;
}

function setPendingMoveTime(value) {
    if (!state.pendingMove || !state.selectedLesson) return false;
    const minutes = moveTimeToMinutes(value);
    if (minutes === null) return false;
    const normalized = moveTimeLabel(Math.round(minutes / 5) * 5);
    const normalizedMinutes = moveTimeToMinutes(normalized);
    state.pendingMove.newTime = normalized;
    const input = document.getElementById('move-target-time');
    input.value = normalized;
    const personal = state.selectedLesson.entry_type === 'personal';
    const name = personal ? state.selectedLesson.title : state.selectedLesson.student;
    document.getElementById('move-modal-desc').textContent = `${name}: ${state.pendingMove.newDate}, ${normalized}`;
    document.querySelectorAll('[data-move-minute]').forEach(button => {
        button.classList.toggle('active', Number(button.dataset.moveMinute) === normalizedMinutes % 60);
    });
    const available = isMoveTargetAvailable(state.pendingMove.newDate, normalizedMinutes);
    const status = document.getElementById('move-time-status');
    status.textContent = available
        ? uiText('Свободно — можно продолжать', 'Available — ready to continue')
        : uiText('Это время занято или занятие выйдет за пределы дня', 'This time is busy or the lesson would cross midnight');
    status.classList.toggle('is-invalid', !available);
    for (const id of ['btn-action-copy', 'btn-action-move-once', 'btn-action-move-all']) {
        document.getElementById(id).disabled = !available;
    }
    return available;
}

function shiftPendingMoveTime(delta) {
    const current = moveTimeToMinutes(state.pendingMove?.newTime);
    if (current === null) return;
    setPendingMoveTime(moveTimeLabel(Math.max(0, Math.min(1435, current + delta))));
}

function confirmMoveTarget(newDate, newTime) {
    state.pendingMove = { newDate, newTime };
    const personal = state.selectedLesson.entry_type === 'personal';
    const name = personal ? state.selectedLesson.title : state.selectedLesson.student;
    document.getElementById('move-modal-title').textContent = personal ? 'Действие с личным делом' : 'Действие с занятием';
    document.getElementById('move-time-picker-label').textContent = uiText('Время начала', 'Start time');
    document.getElementById('btn-move-time-minus').setAttribute('aria-label', uiText('Уменьшить время на 5 минут', 'Move time back by 5 minutes'));
    document.getElementById('btn-move-time-plus').setAttribute('aria-label', uiText('Увеличить время на 5 минут', 'Move time forward by 5 minutes'));
    document.getElementById('move-target-time').setAttribute('aria-label', uiText('Новое время занятия', 'New lesson time'));
    setThreadButtonLabel(document.getElementById('btn-action-copy'), 'add', personal ? 'Добавить ещё одним личным делом' : 'Добавить ещё одним занятием');
    setPendingMoveTime(newTime);
    document.getElementById('move-modal-overlay').classList.remove('hidden');
}

async function executeMove(actionType) {
    if (!state.selectedLesson || !state.pendingMove) return;
    if (!setPendingMoveTime(state.pendingMove.newTime)) return;
    const payload = {
        old_date: state.selectedLesson.date,
        id: state.selectedLesson.id,
        new_date: state.pendingMove.newDate,
        new_time: state.pendingMove.newTime,
        action_type: actionType
    };
    const response = await apiFetch('/move_lesson', { method: 'POST', body: JSON.stringify(payload) });
    const result = await response.json();
    if (result.status !== 'ok') return alert(result.message || 'Ошибка переноса');
    window.dispatchEvent(new CustomEvent('temli-calendar-changed', { detail: { token: result.undo_token, action: actionType } }));
    cancelMove();
    refreshScheduleOnly();
}

function cancelMove() {
    clearLessonDragVisuals();
    lessonDragSession = null;
    state.isMoving = false;
    document.body.classList.remove('calendar-move-mode');
    state.selectedLesson = null;
    state.pendingMove = null;
    document.getElementById('move-hint').classList.add('hidden');
    document.getElementById('move-modal-overlay').classList.add('hidden');
    renderCalendar();
}

const CONTACT_TYPES = {
    tg: { label: 'Telegram', placeholder: '@username или ID' },
    wa: { label: 'WhatsApp', placeholder: 'WhatsApp номер' },
    phone: { label: 'Телефон', placeholder: 'Телефон' },
    max: { label: 'MAX', placeholder: 'MAX (номер или ник)' }
};
function contactTypeLabel(type) {
    if (type === 'phone') return uiLocale().startsWith('en') ? 'Phone' : 'Телефон';
    return CONTACT_TYPES[type]?.label || type;
}
function contactTypePlaceholder(type) {
    if (!uiLocale().startsWith('en')) return CONTACT_TYPES[type]?.placeholder || '';
    return {tg:'@username or ID', wa:'WhatsApp number', phone:'Phone', max:'MAX number or username'}[type] || '';
}

function contactIconSvg(type) {
    if (type === 'tg') return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#229ED9"/><path fill="#fff" d="M5.7 11.7 17.9 7c.56-.2 1.05.14.87.99l-2.08 9.8c-.16.7-.57.87-1.16.54l-3.17-2.34-1.53 1.47c-.17.17-.31.31-.64.31l.23-3.23 5.88-5.31c.26-.23-.06-.36-.4-.13l-7.26 4.57-3.13-.98c-.68-.21-.69-.68.14-1z"/></svg>';
    if (type === 'wa') return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#25D366"/><path fill="#fff" d="M17.1 14.6c-.28-.14-1.65-.81-1.9-.91-.26-.09-.44-.14-.63.14-.18.28-.72.91-.88 1.09-.16.19-.32.21-.6.07-1.62-.81-2.68-1.45-3.75-3.29-.28-.49.28-.46.81-1.52.09-.19.05-.35-.02-.49-.07-.14-.63-1.51-.86-2.07-.23-.55-.46-.47-.63-.48h-.54c-.19 0-.49.07-.74.35-.26.28-.98.96-.98 2.34s1 2.71 1.14 2.9c.14.18 1.97 3.01 4.77 4.22 1.77.76 2.46.83 3.34.7 1.07-.16 1.65-.67 1.88-1.32.23-.65.23-1.21.16-1.32-.07-.12-.25-.19-.53-.33z"/></svg>';
    if (type === 'phone') return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="12" fill="#5F6368"/><path fill="#fff" d="M7.2 5.8c.35-.35.91-.35 1.26 0l2 2c.3.3.35.76.12 1.12l-1.1 1.7a12.2 12.2 0 0 0 3.9 3.9l1.7-1.1c.36-.23.82-.18 1.12.12l2 2c.35.35.35.91 0 1.26l-1.3 1.3c-.72.72-1.8.98-2.77.64A15.3 15.3 0 0 1 5.26 9.87c-.34-.97-.08-2.05.64-2.77z"/></svg>';
    return '<span class="max-contact-mark" aria-hidden="true">MAX</span>';
}

function createContactRow(type = 'tg', value = '', removable = true) {
    const normalizedType = CONTACT_TYPES[type] ? type : 'tg';
    const row = document.createElement('div');
    row.className = 'contact-row';
    row.dataset.type = normalizedType;

    const picker = document.createElement('div');
    picker.className = 'contact-type-picker';
    const icon = document.createElement('span');
    icon.className = 'contact-brand-icon';
    icon.innerHTML = contactIconSvg(normalizedType);
    const select = document.createElement('select');
    select.className = 'contact-type-select';
    select.setAttribute('aria-label', uiLocale().startsWith('en') ? 'Messenger' : 'Мессенджер');
    Object.entries(CONTACT_TYPES).forEach(([key, meta]) => {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = contactTypeLabel(key);
        option.selected = key === normalizedType;
        select.appendChild(option);
    });

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'contact-input';
    input.dataset.field = normalizedType;
    input.placeholder = contactTypePlaceholder(normalizedType);
    input.value = value || '';

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'contact-remove-btn';
    remove.title = uiLocale().startsWith('en') ? 'Remove contact' : 'Удалить контакт';
    remove.innerHTML = threadIcon('close');
    remove.setAttribute('aria-label', remove.title);
    remove.style.visibility = removable ? 'visible' : 'hidden';

    select.addEventListener('change', () => {
        const nextType = select.value;
        row.dataset.type = nextType;
        input.dataset.field = nextType;
        input.placeholder = contactTypePlaceholder(nextType);
        icon.innerHTML = contactIconSvg(nextType);
    });
    remove.addEventListener('click', () => row.remove());

    picker.append(icon, select);
    row.append(picker, input, remove);
    return row;
}

function renderContacts(containerId, contacts = {}, defaultType = 'tg') {
    const container = document.getElementById(containerId);
    if (!container) return;
    const addButton = container.querySelector('.add-contact-btn');
    container.querySelectorAll('.contact-row').forEach(row => row.remove());

    const entries = Object.entries(contacts || {}).filter(([type, value]) => CONTACT_TYPES[type] && String(value || '').trim());
    if (entries.length === 0) entries.push([defaultType, '']);

    entries.forEach(([type, value], index) => {
        const row = createContactRow(type, value, index > 0);
        container.insertBefore(row, addButton);
    });
}

function addContactRow(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const used = new Set(Array.from(container.querySelectorAll('.contact-row')).map(row => row.dataset.type));
    const type = Object.keys(CONTACT_TYPES).find(key => !used.has(key));
    if (!type) return alert('Все типы контактов уже добавлены');
    const row = createContactRow(type, '', true);
    container.insertBefore(row, container.querySelector('.add-contact-btn'));
    row.querySelector('.contact-input').focus();
}

function getContacts(containerId) {
    const contacts = {};
    document.querySelectorAll(`#${containerId} .contact-row`).forEach(row => {
        const input = row.querySelector('.contact-input');
        const type = row.querySelector('.contact-type-select')?.value || row.dataset.type;
        const value = input?.value.trim() || '';
        if (value && CONTACT_TYPES[type]) contacts[type] = value;
    });
    return contacts;
}

let lessonInviteAvailabilityRequest = 0;
let lessonInviteAvailabilityTimer = 0;

function renderLessonStudentSetupLabels() {
    for (const id of ['lesson-parent-name', 'student-parent-name']) {
        const field = document.getElementById(id);
        field.placeholder = botText('Имя родителя (необязательно)', 'Parent name (optional)');
        field.setAttribute('aria-label', field.placeholder);
    }
    const setup = document.getElementById('lesson-student-setup');
    if (!setup) return;
    setup.querySelector('.lesson-student-setup-head strong').textContent = botText('Ученик и родитель', 'Student and parent');
    document.querySelector('#lesson-manual-contacts > summary').textContent = botText('Контакты вручную', 'Enter contacts manually');
    setup.querySelector('.lesson-student-setup-head small').textContent = botText('Необязательно: можно сохранить только имя, никому не отправляя сообщения', 'Optional: save just a name without messaging anyone');
    const labels = setup.querySelectorAll('.form-group > label');
    if (labels[0]) labels[0].textContent = botText('Контакт ученика', 'Student contact');
    if (labels[1]) labels[1].textContent = botText('Контакт родителя', 'Parent contact');
    setup.querySelectorAll('.add-contact-btn').forEach(button => { button.textContent = botText('＋ Добавить контакт', '＋ Add contact'); });
    document.querySelector('#lesson-bot-invite-options > strong').textContent = botText('Приглашения — по желанию', 'Invitations — optional');
    document.querySelector('#lesson-invite-student + span').textContent = botText('Создать ссылку ученику', 'Create student link');
    document.querySelector('#lesson-invite-parent + span').textContent = botText('Создать ссылку родителю', 'Create parent link');
    const contactLabels = {
        tg: {label:'Telegram', placeholder:botText('@username или ID', '@username or ID')},
        wa: {label:'WhatsApp', placeholder:botText('WhatsApp номер', 'WhatsApp number')},
        phone: {label:botText('Телефон', 'Phone'), placeholder:botText('Телефон', 'Phone')},
        max: {label:'MAX', placeholder:botText('MAX (ник)', 'MAX username')}
    };
    setup.querySelectorAll('.contact-row').forEach(row => {
        const select = row.querySelector('.contact-type-select');
        const input = row.querySelector('.contact-input');
        const remove = row.querySelector('.contact-remove-btn');
        select.setAttribute('aria-label', botText('Мессенджер', 'Messenger'));
        Array.from(select.options).forEach(option => { option.textContent = contactLabels[option.value]?.label || option.textContent; });
        input.placeholder = contactLabels[select.value]?.placeholder || '';
        remove.title = botText('Удалить контакт', 'Remove contact');
        remove.setAttribute('aria-label', remove.title);
    });
}

function syncLessonStudentSetup(studentId) {
    const info = studentId && studentId !== 'manual' ? getStudentInfo(studentId) : {};
    document.getElementById('lesson-parent-name').value = info.parent_name || '';
    document.getElementById('lesson-manual-contacts').open = Object.values(info.contacts || {}).some(Boolean) || Object.values(info.student_contacts || {}).some(Boolean);
    renderContacts('lesson-student-contacts', info.student_contacts || {});
    renderContacts('lesson-parent-contacts', info.contacts || {});
}

async function loadLessonInviteAvailability() {
    const requestId = ++lessonInviteAvailabilityRequest;
    const options = document.getElementById('lesson-bot-invite-options');
    const hint = document.getElementById('lesson-bot-invite-hint');
    options.hidden = true;
    renderLessonStudentSetupLabels();
    try {
        const response = await apiFetch('/personal_invites', {method:'POST', body:JSON.stringify({action:'availability'})});
        const result = await response.json();
        if (requestId !== lessonInviteAvailabilityRequest || !response.ok || result.status !== 'ok') return;
        if (!result.bot_username) return;
        hint.textContent = botText(
            `Через @${result.bot_username}. После сохранения отправьте ссылки ученику и родителю. Личный бот не обязателен.`,
            `Via @${result.bot_username}. Send the links after saving. A personal bot is optional.`
        );
        options.hidden = false;
    } catch (_) {
        options.hidden = true;
    }
}

function selectedLessonInviteRoles() {
    if (document.getElementById('lesson-bot-invite-options').hidden) return [];
    return ['student', 'parent'].filter(role => document.getElementById(`lesson-invite-${role}`).checked);
}

function showLessonInviteResults(studentName, links, failedRoles) {
    const overlay = document.getElementById('lesson-invite-result-overlay');
    const list = document.getElementById('lesson-invite-result-links');
    const status = document.getElementById('lesson-invite-result-status');
    document.getElementById('lesson-invite-result-title').textContent = botText('Занятие сохранено', 'Lesson saved');
    document.getElementById('lesson-invite-result-help').textContent = botText(
        `Приглашения для ${studentName || 'ученика'} готовы. Ссылки одноразовые и действуют 48 часов.`,
        `Invitations for ${studentName || 'the student'} are ready. Links are single-use and expire in 48 hours.`
    );
    document.getElementById('btn-done-lesson-invite-result').textContent = botText('Готово', 'Done');
    document.getElementById('btn-close-lesson-invite-result').setAttribute('aria-label', botText('Закрыть', 'Close'));
    list.replaceChildren();
    for (const item of links) {
        const row = document.createElement('div');
        row.className = 'lesson-created-invite-row';
        const label = document.createElement('strong');
        label.textContent = item.role === 'parent' ? botText('Ссылка родителю', 'Parent link') : botText('Ссылка ученику', 'Student link');
        const linkRow = document.createElement('div');
        linkRow.className = 'lesson-created-invite-link';
        const input = document.createElement('input');
        input.type = 'text';
        input.readOnly = true;
        input.value = item.url;
        input.setAttribute('aria-label', label.textContent);
        const copy = document.createElement('button');
        copy.type = 'button';
        copy.className = 'secondary-btn';
        copy.textContent = botText('Копировать', 'Copy');
        copy.onclick = async () => {
            try {
                await copyTextToClipboard(item.url);
                status.textContent = botText('Ссылка скопирована.', 'Link copied.');
            } catch (_) {
                input.focus();
                input.select();
                status.textContent = botText('Скопируйте выделенную ссылку вручную.', 'Copy the selected link manually.');
            }
        };
        linkRow.append(input, copy);
        const share = document.createElement('button');
        share.type = 'button';
        share.className = 'secondary-btn';
        share.textContent = botText('Отправить', 'Send');
        share.onclick = () => {
            const url = 'https://t.me/share/url?url=' + encodeURIComponent(item.url);
            if (typeof tg.openTelegramLink === 'function') tg.openTelegramLink(url);
            else window.open(url, '_blank', 'noopener,noreferrer');
        };
        row.append(label, linkRow);
        row.append(share);
        list.append(row);
    }
    status.textContent = failedRoles.length
        ? botText('Занятие сохранено, но часть ссылок создать не удалось. Их можно создать в карточке ученика.', 'The lesson was saved, but some links could not be created. Create them from the student profile.')
        : '';
    overlay.classList.remove('hidden');
}

async function createLessonInvitations(studentId, studentName, roles) {
    const settled = await Promise.allSettled(roles.map(async role => ({role, ...(await inviteApi({action:'create', student_id:studentId, role}))})));
    const links = settled.filter(item => item.status === 'fulfilled').map(item => item.value);
    const failedRoles = roles.filter((_, index) => settled[index].status === 'rejected');
    showLessonInviteResults(studentName, links, failedRoles);
}

document.getElementById('btn-close-lesson-invite-result').onclick = () => document.getElementById('lesson-invite-result-overlay').classList.add('hidden');
document.getElementById('btn-done-lesson-invite-result').onclick = () => document.getElementById('lesson-invite-result-overlay').classList.add('hidden');
function renderLessonInviteResultLabels() {
    document.getElementById('lesson-invite-result-title').textContent = botText('Занятие сохранено', 'Lesson saved');
    document.getElementById('btn-done-lesson-invite-result').textContent = botText('Готово', 'Done');
    document.getElementById('btn-close-lesson-invite-result').setAttribute('aria-label', botText('Закрыть', 'Close'));
}
window.addEventListener('temli-language-change', () => {
    renderLessonStudentSetupLabels();
    renderLessonInviteResultLabels();
});
function updateReminderControls() {
    const enabled = true;
    const input = document.getElementById('reminder-minutes');
    const wrap = document.getElementById('reminder-minutes-wrap');
    input.disabled = !enabled;
    wrap.classList.toggle('disabled', !enabled);
}

function resetAddForm(type = 'student') {
    document.getElementById('lesson-type-select').value = ['student', 'group', 'personal'].includes(type) ? type : 'student';
    document.getElementById('group-name').value = '';
    document.getElementById('personal-event-title').value = '';
    document.getElementById('personal-event-notes').value = '';
    renderGroupMembers([]);
    document.getElementById('student-select').value = '';
    document.getElementById('manual-student-name').value = '';
    document.getElementById('lesson-parent-name').value = '';
    document.getElementById('lesson-manual-contacts').open = false;
    document.getElementById('manual-student-name').classList.add('hidden');
    renderContacts('lesson-student-contacts', {});
    renderContacts('lesson-parent-contacts', {});
    document.getElementById('lesson-invite-student').checked = false;
    document.getElementById('lesson-invite-parent').checked = false;
    document.getElementById('lesson-bot-invite-options').hidden = true;
    document.getElementById('lesson-repeat').value = type === 'personal' ? 'no' : 'year';
    document.getElementById('lesson-price').value = '';
    const dateValue = document.getElementById('lesson-date')?.value || dateKey(new Date());
    const repeatUntil = document.getElementById('repeat-until');
    repeatUntil.min = dateValue;
    repeatUntil.max = dateKey(new Date(`${dateValue}T12:00:00`).getTime() + 370 * 24 * 60 * 60 * 1000);
    repeatUntil.value = schoolYearEndFor(dateValue);
    document.getElementById('repeat-until-wrap').classList.toggle('hidden', type === 'personal');
    document.getElementById('reminder-enabled').checked = state.settings.default_reminders_enabled === true;
    document.getElementById('reminder-minutes').value = '60';
    updateReminderControls();
    updateLessonTypeUI();
}

function formatAddTypeContext(date, time) {
    const value = new Date(`${date}T12:00:00`);
    const formattedDate = Number.isNaN(value.getTime())
        ? date
        : value.toLocaleDateString(uiLocale(), { weekday: 'short', day: 'numeric', month: 'long' }).replace(/\.$/, '');
    return `${formattedDate} · ${time}`;
}

function updateAddTypeContext() {
    const context = document.getElementById('add-type-context');
    if (context && state.pendingAddDate && state.pendingAddTime) {
        context.textContent = formatAddTypeContext(state.pendingAddDate, state.pendingAddTime);
    }
}

function openAddTypeChooser(date, time) {
    state.pendingAddDate = date;
    state.pendingAddTime = time;
    updateAddTypeContext();
    document.getElementById('add-type-overlay').classList.remove('hidden');
}

function chooseAddType(type) {
    const date = state.pendingAddDate;
    const time = state.pendingAddTime;
    document.getElementById('add-type-overlay').classList.add('hidden');
    if (date && time) openAddModal(date, time, type);
}

function openAddModal(date, time, type = 'student') {
    state.selectedLesson = null;
    state.editingExisting = false;
    document.getElementById('lesson-type-group').classList.add('hidden');
    document.getElementById('student-select-group').classList.remove('hidden');
    document.getElementById('student-fixed-group').classList.add('hidden');
    document.getElementById('time-duration-group').classList.remove('hidden');
    document.getElementById('repeat-group').classList.remove('hidden');
    document.getElementById('lesson-price-scope-group').classList.add('hidden');
    document.getElementById('lesson-date').value = date;
    resetAddForm(type);
    document.getElementById('lesson-time').value = time;
    document.getElementById('lesson-duration').value = '60';
    document.getElementById('modal-overlay').classList.remove('hidden');
    document.querySelectorAll('#modal-overlay .modal-body, #modal-overlay .modal-content').forEach(el => { el.scrollTop = 0; });
    // Invitation availability is secondary; let typing/selecting remain instant.
    window.clearTimeout(lessonInviteAvailabilityTimer);
    lessonInviteAvailabilityTimer = window.setTimeout(() => {
        if (!document.getElementById('modal-overlay').classList.contains('hidden')) {
            loadLessonInviteAvailability();
        }
    }, 4000);
}

function openEditModal(date, lesson) {
    state.selectedLesson = { date, ...lesson };
    state.editingExisting = true;
    const isPersonal = lesson.entry_type === 'personal';
    const isGroup = !isPersonal && lesson.lesson_type === 'group';
    document.getElementById('modal-title').textContent = isPersonal ? 'Личное дело' : (isGroup ? 'Настройки группы' : 'Настройки ученика');
    document.getElementById('lesson-type-select').value = isPersonal ? 'personal' : (isGroup ? 'group' : 'student');
    document.getElementById('lesson-type-group').classList.add('hidden');
    document.getElementById('group-name').value = lesson.group_name || lesson.student || '';
    renderGroupMembers(lesson.group_members || []);
    document.getElementById('fixed-student-name').value = lesson.student || '';
    document.getElementById('personal-event-title').value = lesson.title || '';
    document.getElementById('personal-event-notes').value = lesson.notes || '';
    updateLessonTypeUI();
    document.getElementById('time-duration-group').classList.toggle('hidden', !isPersonal);
    document.getElementById('repeat-group').classList.add('hidden');
    document.getElementById('lesson-date').value = date;
    document.getElementById('lesson-time').value = lesson.time || '10:00';
    document.getElementById('lesson-duration').value = lesson.duration || 60;
    document.getElementById('lesson-id').value = lesson.id || '';
    document.getElementById('lesson-price').value = lesson.price ?? '';
    document.querySelector('input[name="lesson-price-scope"][value="single"]').checked = true;
    document.getElementById('lesson-price-scope-group').classList.toggle('hidden', isPersonal);
    document.getElementById('reminder-enabled').checked = lesson.reminder_enabled !== false;
    document.getElementById('reminder-minutes').value = lesson.reminder_minutes ?? 60;

    updateReminderControls();
    document.getElementById('modal-overlay').classList.remove('hidden');
}

let pendingDayOffSave = null;

function openDayOffWarning(action) {
    pendingDayOffSave = action;
    document.getElementById('day-off-warning-overlay').classList.remove('hidden');
}

function closeDayOffWarning() {
    pendingDayOffSave = null;
    document.getElementById('day-off-warning-overlay').classList.add('hidden');
}

async function saveLesson(options = {}) {
    const skipDayOffWarning = options?.skipDayOffWarning === true;
    const date = document.getElementById('lesson-date').value;
    const time = document.getElementById('lesson-time').value;
    const duration = parseInt(document.getElementById('lesson-duration').value || 60, 10);
    const selectedType = document.getElementById('lesson-type-select').value;
    const isPersonal = selectedType === 'personal';
    const lessonType = selectedType === 'group' ? 'group' : 'student';
    const eventTitle = document.getElementById('personal-event-title').value.trim();
    const eventNotes = document.getElementById('personal-event-notes').value.trim();
    let student = '';
    let studentId = '';
    let groupName = '';
    let groupMembers = [];

    if (isPersonal) {
        if (!eventTitle) return alert('Укажите название личного дела');
    } else if (lessonType === 'group') {
        groupName = document.getElementById('group-name').value.trim();
        groupMembers = collectGroupMembers();
        if (!groupName) return alert('Укажите название группы');
        if (!groupMembers.length) return alert('Добавьте хотя бы одного ученика в группу');
    } else if (state.editingExisting) {
        student = state.selectedLesson.student;
        studentId = state.selectedLesson.student_id;
    } else {
        const select = document.getElementById('student-select');
        if (select.value === 'manual') student = document.getElementById('manual-student-name').value.trim();
        else if (select.value) {
            student = select.options[select.selectedIndex].dataset.name;
            studentId = select.value;
        }
    }

    if (!isPersonal && lessonType === 'student' && !student) return alert('Укажите ученика');
    if (!time) return alert('Укажите время');

    const repeat = state.editingExisting ? 'no' : document.getElementById('lesson-repeat').value;
    const repeatUntil = document.getElementById('repeat-until').value;
    if (!state.editingExisting && repeat === 'year') {
        if (!repeatUntil) return alert('Укажите дату окончания повторов');
        if (repeatUntil < date) return alert('Дата окончания повторов не может быть раньше первого занятия');
    }
    if (!Number.isInteger(duration) || duration < 15 || duration > 1440) {
        return alert('Длительность занятия должна быть от 15 до 1440 минут');
    }

    const priceValue = document.getElementById('lesson-price').value;
    const price = priceValue === '' ? 0 : Number(priceValue);
    if (!isPersonal && lessonType === 'student' && (!Number.isFinite(price) || price < 0)) {
        return alert('Стоимость занятия должна быть неотрицательным числом');
    }
    const reminderMinutes = Number(document.getElementById('reminder-minutes').value || 60);
    if (!isPersonal && (!Number.isInteger(reminderMinutes) || reminderMinutes < 0 || reminderMinutes > 10080)) {
        return alert('Напоминание должно быть в диапазоне от 0 до 10080 минут');
    }
    if (!state.editingExisting && !skipDayOffWarning && isDayOffDate(date)) {
        document.getElementById('day-off-warning-title').textContent = isPersonal ? 'Личное дело в выходной' : 'Занятие в выходной';
        document.getElementById('day-off-warning-desc').textContent = isPersonal
            ? 'Это ваш выходной день. Всё равно добавить личное дело?'
            : 'Вообще-то у вас выходной. Не советую 😄 Отдых тоже входит в расписание. Всё равно поставить занятие?';
        document.getElementById('btn-day-off-confirm').textContent = 'Всё равно поставить';
        document.getElementById('btn-day-off-cancel').textContent = 'Не сегодня';
        openDayOffWarning(() => saveLesson({ skipDayOffWarning: true }));
        return;
    }

    const isNewIndividual = !state.editingExisting && !isPersonal && lessonType === 'student';
    const inviteRoles = isNewIndividual ? selectedLessonInviteRoles() : [];
    const payload = {
        date, time, duration, entry_type: isPersonal ? 'personal' : 'lesson', lesson_type: lessonType,
        title: isPersonal ? eventTitle : '', notes: isPersonal ? eventNotes : '',
        student, student_id: studentId,
        group_name: groupName, group_members: groupMembers,
        price: !isPersonal && lessonType === 'student' ? price : '',
        reminder_enabled: document.getElementById('reminder-enabled').checked,
        reminder_minutes: reminderMinutes,
        repeat,
        repeat_until: repeatUntil,
        ...(isNewIndividual ? {
            student_contacts: getContacts('lesson-student-contacts'),
            parent_name: document.getElementById('lesson-parent-name').value.trim(),
            contacts: getContacts('lesson-parent-contacts')
        } : {})
    };
    if (state.editingExisting) {
        payload.price_scope = document.querySelector('input[name="lesson-price-scope"]:checked')?.value || 'single';
    }
    const endpoint = state.editingExisting ? '/update_lesson' : '/add_lesson';
    if (state.editingExisting) payload.id = state.selectedLesson.id;

    const saveButton = document.getElementById('btn-save');
    if (saveButton.disabled) return;
    saveButton.disabled = true;
    try {
        const response = await apiFetch(endpoint, { method: 'POST', body: JSON.stringify(payload) });
        const result = await response.json();
        if (result.status !== 'ok') return alert(result.message || 'Ошибка сохранения');
        window.dispatchEvent(new CustomEvent('temli-saved', { detail: { overlay: 'modal-overlay' } }));
        closeAllModals();
        await refreshScheduleAndStudents();
        if (inviteRoles.length && result.student_id) {
            await createLessonInvitations(result.student_id, student, inviteRoles);
        }
        if (Number(result.updated_prices || 0) > 1) {
            alert(uiMessage`Цена изменена в ${result.updated_prices} будущих занятиях.`);
        }
    } catch (error) {
        alert(error?.message || 'Не удалось сохранить занятие');
    } finally {
        saveButton.disabled = false;
    }
}

function closeAllModals() {
    ['modal-overlay', 'add-type-overlay', 'move-modal-overlay', 'action-menu-overlay', 'delete-modal-overlay', 'date-picker-overlay', 'app-settings-overlay', 'receipt-settings-overlay', 'help-overlay', 'student-card-overlay', 'work-center-overlay', 'paid-confirm-overlay', 'subscription-pay-overlay', 'lesson-report-overlay', 'students-overlay', 'student-payment-overlay', 'lesson-invite-result-overlay'].forEach(id => document.getElementById(id)?.classList.add('hidden'));
}

// Палитра цветов в меню действий
document.querySelectorAll('.color-swatch').forEach(el => {
    el.addEventListener('click', async () => {
        if (el.id === 'color-picker-open') {
            const input = document.createElement('input');
            input.type = 'color';
            input.value = '#5c6bc0';
            input.addEventListener('input', async (e) => {
                const color = e.target.value;
                const response = await apiFetch('/update_student_color', {
                    method: 'POST',
                    body: JSON.stringify({ student_id: state.selectedLesson?.student_id, color: color })
                });
                const result = await response.json();
                if (result.status !== 'ok') return alert(result.message || 'Ошибка изменения цвета');
                closeAllModals();
                refreshStudentsOnly();
            });
            input.click();
            return;
        }
        const color = el.dataset.color;
        const response = await apiFetch('/update_student_color', {
            method: 'POST',
            body: JSON.stringify({ student_id: state.selectedLesson?.student_id, color: color })
        });
        const result = await response.json();
        if (result.status !== 'ok') return alert(result.message || 'Ошибка изменения цвета');
        closeAllModals();
        refreshStudentsOnly();
    });
});

// Добавление контактов
 document.querySelectorAll('.add-contact-btn').forEach(button => {
    button.addEventListener('click', () => addContactRow(button.dataset.target));
});
document.getElementById('reminder-enabled').addEventListener('change', updateReminderControls);

document.getElementById('lesson-type-select').addEventListener('change', updateLessonTypeUI);
document.getElementById('btn-add-group-member').addEventListener('click', () => addGroupMemberRow());

// Переключатель ручного ввода
document.getElementById('student-select').addEventListener('change', event => {
    const input = document.getElementById('manual-student-name');
    const manual = event.target.value === 'manual';
    input.classList.toggle('hidden', !manual);
    syncLessonStudentSetup(event.target.value);
    if (manual) input.focus();
});

// Микроотчёт по проведённому занятию
function openLessonReport() {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    const title = lesson.lesson_type === 'group' ? (lesson.group_name || lesson.student) : lesson.student;
    document.getElementById('lesson-report-title').innerHTML = `<span>${uiText('Итог')}</span> · ${userContentOr(title, lesson.lesson_type === 'group' ? 'Группа' : 'Ученик')} · ${userContent(lesson.time || '')}`;
    document.getElementById('lesson-report-text').value = lesson.report || '';
    document.getElementById('lesson-report-overlay').classList.remove('hidden');
}

document.getElementById('btn-close-lesson-report').onclick = () => document.getElementById('lesson-report-overlay').classList.add('hidden');
document.getElementById('btn-cancel-lesson-report').onclick = () => document.getElementById('lesson-report-overlay').classList.add('hidden');
document.getElementById('btn-save-lesson-report').onclick = async () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    const button = document.getElementById('btn-save-lesson-report');
    button.disabled = true;
    try {
        const report = document.getElementById('lesson-report-text').value.trim();
        const response = await apiFetch('/update_lesson_report', {
            method: 'POST',
            body: JSON.stringify({ date: lesson.date, id: lesson.id, report })
        });
        const result = await response.json();
        if (result.status !== 'ok') return alert(result.message || 'Ошибка сохранения итога');
        state.selectedLesson.report = report;
        window.dispatchEvent(new CustomEvent('temli-saved', { detail: { overlay: 'lesson-report-overlay' } }));
        document.getElementById('lesson-report-overlay').classList.add('hidden');
        await refreshScheduleOnly();
    } catch (error) {
        alert(error.message || 'Ошибка сохранения итога');
    } finally {
        button.disabled = false;
    }
};

function openStudentContactFor(studentId) {
    const info = getStudentInfo(studentId);
    const contacts = info.student_contacts || {};
    if (contacts.tg) return openContact('tg', contacts.tg);
    if (info.username) return openContact('tg', info.username);
    for (const type of ['wa', 'max', 'phone']) if (contacts[type]) return openContact(type, contacts[type]);
    if (studentId && !String(studentId).startsWith('manual')) return tg.openTelegramLink(`tg://user?id=${studentId}`);
    alert(uiText('Контакт ученика не указан.', 'Student contact is missing.'));
}

function openParentContactFor(studentId) {
    const info = getStudentInfo(studentId);
    const contacts = info.contacts || {};
    for (const type of ['tg', 'wa', 'max', 'phone']) if (contacts[type]) return openContact(type, contacts[type]);
    alert(uiText('Контакт родителя не указан.', 'Parent contact is missing.'));
}

async function setFreeStateForSelected(studentId = '', makeFree = true) {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    const response = await apiFetch('/set_lesson_state', {
        method: 'POST',
        body: JSON.stringify({ date: lesson.date, id: lesson.id, action: makeFree ? 'free' : 'unfree', student_id: studentId })
    });
    const result = await response.json();
    if (result.status !== 'ok') return alert(result.message || 'Ошибка');
    closeActionMenu();
    await refreshScheduleOnly();
}

function openSubscriptionForStudent(lesson, studentId) {
    if (!lesson) return;
    const target = lesson.lesson_type === 'group'
        ? (lesson.group_members || []).find(m => String(m.student_id) === String(studentId)) : lesson;
    if (target && (target.paid || target.free || hasAllocatedPayment(target))) {
        return alert('Сначала отмените существующую оплату или бесплатный статус. Общая оплата отменяется в карточке ученика.');
    }
    let price = 0;
    let name = '';
    if (lesson.lesson_type === 'group') {
        const member = (lesson.group_members || []).find(m => String(m.student_id) === String(studentId));
        if (!member) return;
        price = lessonPriceValue(lesson, member);
        name = member.name || getStudentInfo(studentId).name || 'Ученик';
    } else {
        studentId = lesson.student_id;
        price = lessonPriceValue(lesson);
        name = getStudentInfo(studentId).calendar_name || lesson.student || getStudentInfo(studentId).name || 'Ученик';
    }
    if (!(price > 0)) {
        closeActionMenu();
        alert('Сначала укажите стоимость этого занятия.');
        return;
    }
    state.subscriptionStudentId = String(studentId || '');
    state.subscriptionPrice = price;
    document.getElementById('subscription-pay-title').innerHTML = `<span>${uiText('Абонемент')}</span> · ${userContent(name)}`;
    document.getElementById('subscription-pay-desc').textContent = `${uiText('Стоимость одного урока:')} ${money(price)}. ${uiText('Укажите общую сумму абонемента.')}`;
    const amountInput = document.getElementById('subscription-pay-amount');
    amountInput.value = String(price * 3);
    document.getElementById('subscription-custom-count').dataset.count = '3';
    document.getElementById('subscription-custom-count').textContent = '3 занятия';
    document.getElementById('subscription-send-receipt-checkbox').checked = state.settings.default_send_receipts !== false;
    updateSubscriptionPayHint();
    closeActionMenu();
    document.getElementById('subscription-pay-overlay').classList.remove('hidden');
    setTimeout(() => amountInput.focus(), 50);
}

// Меню действий
document.getElementById('btn-action-student-card').onclick = () => { closeActionMenu(); if (state.selectedLesson) openStudentCard(state.selectedLesson.student_id); };
document.getElementById('btn-action-report').onclick = () => { closeActionMenu(); openLessonReport(); };
document.getElementById('btn-action-settings').onclick = () => { closeActionMenu(); if (state.selectedLesson) openEditModal(state.selectedLesson.date, state.selectedLesson); };
function showDeferredNotificationNotice() {
    alert('Пока это макет. После регистрации учеников и родителей преподавательский бот будет автоматически отправлять готовое сообщение. Расписание не изменится.');
}
document.getElementById('btn-action-teacher-delay').onclick = () => openPersonalNotification(state.selectedLesson, true);
document.getElementById('btn-action-student-delay').onclick = () => openPersonalNotification(state.selectedLesson, false);
document.getElementById('btn-action-move-trigger').onclick = () => { closeActionMenu(); if (state.selectedLesson) startMove(state.selectedLesson.date, state.selectedLesson); };
document.getElementById('btn-action-free').onclick = () => {
    const lesson = state.selectedLesson;
    if (!lesson || lesson.lesson_type === 'group') return;
    setFreeStateForSelected('', !lesson.free);
};
document.getElementById('btn-action-cancel-once').onclick = async () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    const action = lesson.cancelled ? 'restore' : 'cancel';
    const response = await apiFetch('/set_lesson_state', { method: 'POST', body: JSON.stringify({ date: lesson.date, id: lesson.id, action }) });
    const result = await response.json();
    if (result.status !== 'ok') return alert(result.message || 'Ошибка');
    closeActionMenu();
    await refreshScheduleOnly();
};
document.getElementById('btn-action-paid').onclick = async () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    const isGroup = lesson.lesson_type === 'group';
    if (!isGroup && hasAllocatedPayment(lesson)) return explainAllocatedPayment(lesson.student_id);
    if (!isGroup && lesson.paid_via_subscription) return alert('Занятие оплачено абонементом. Снятие оплаты одного занятия заблокировано.');
    if (!isGroup && lesson.free) return alert('Сначала отмените бесплатный статус.');

    if (!isGroup && lesson.paid) {
        if (!confirm(uiMessage`Снять отметку об оплате у занятия ${lesson.student || ''} ${lesson.time || ''}?`)) return;
        const response = await apiFetch('/mark_paid', {
            method: 'POST',
            body: JSON.stringify({ date: lesson.date, id: lesson.id, paid: false, send_receipt: false })
        });
        const result = await response.json();
        if (result.status !== 'ok') return alert(result.message || 'Ошибка изменения оплаты');
        closeActionMenu();
        refreshScheduleOnly();
        return;
    }

    document.getElementById('paid-confirm-title').innerHTML = `${userContentOr(isGroup ? lesson.group_name : lesson.student, isGroup ? 'Группа' : 'Ученик')} · ${userContent(lesson.time || '--:--')}`;
    document.getElementById('paid-confirm-desc').textContent = isGroup
        ? 'Отметьте учеников, которые оплатили. Сумма берётся из стоимости каждого участника в этом занятии.'
        : (() => { const price = Number(lessonPriceValue(lesson)); return `Подтвердить оплату${price > 0 ? ` на ${money(price)}` : ''}?`; })();
    const membersBox = document.getElementById('group-paid-members');
    membersBox.innerHTML = '';
    membersBox.classList.toggle('hidden', !isGroup);
    if (isGroup) {
        (lesson.group_members || []).forEach(member => {
            const label = document.createElement('label');
            label.className = 'group-paid-member-row';
            const memberPrice = lessonPriceValue(lesson, member);
            label.innerHTML = `<input type="checkbox" value="${escapeHtml(member.student_id || '')}" ${member.paid ? 'checked' : ''}><span>${userContentOr(member.name, 'Ученик')}${memberPrice > 0 ? ` · ${money(memberPrice)}` : ` · ${uiText('Цена не указана')}`}</span>`;
            membersBox.appendChild(label);
        });
    }
    document.getElementById('send-receipt-checkbox').checked = state.settings.default_send_receipts !== false;
    closeActionMenu();
    document.getElementById('paid-confirm-overlay').classList.remove('hidden');
};

document.getElementById('btn-action-subscription').onclick = () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    openSubscriptionForStudent(lesson, lesson.student_id);
};


function subscriptionCountWord(count) {
    if ((state.settings.language || 'ru') === 'en') return count === 1 ? 'lesson' : 'lessons';
    const mod100 = count % 100;
    const mod10 = count % 10;
    if (mod100 >= 11 && mod100 <= 14) return 'занятий';
    if (mod10 === 1) return 'занятие';
    if (mod10 >= 2 && mod10 <= 4) return 'занятия';
    return 'занятий';
}

function getSubscriptionLessonCount() {
    const el = document.getElementById('subscription-custom-count');
    return Math.max(2, Number(el?.dataset.count || 2));
}

function setSubscriptionLessonCount(count) {
    const el = document.getElementById('subscription-custom-count');
    if (!el) return;
    const safeCount = Math.max(2, Math.round(Number(count) || 2));
    el.dataset.count = String(safeCount);
    el.textContent = `${safeCount} ${subscriptionCountWord(safeCount)}`;
    updateSubscriptionPayHint();
}

function updateSubscriptionPayHint() {
    const lesson = state.selectedLesson;
    const hint = document.getElementById('subscription-pay-hint');
    if (!lesson || !hint) return;
    const price = Number(state.subscriptionPrice || lessonPriceValue(lesson));
    const amount = Number(document.getElementById('subscription-pay-amount').value || 0);
    const lessonCount = getSubscriptionLessonCount();
    if (!(price > 0) || !(amount > 0)) { hint.textContent = ''; return; }
    const effectivePrice = amount / lessonCount;
    const regularTotal = price * lessonCount;
    const discount = regularTotal > amount ? ((regularTotal - amount) / regularTotal) * 100 : 0;
    const discountText = discount > 0.01 ? ` · ${uiText('скидка')} ${formatUiNumber(discount, { maximumFractionDigits: 1 })}%` : '';
    hint.textContent = `${uiText('Будет оплачено:')} ${lessonCount} ${uiText(subscriptionCountWord(lessonCount))} · ${money(Number(effectivePrice.toFixed(2)))} ${uiText('/ занятие')}${discountText}.`;
}

document.getElementById('subscription-pay-amount').addEventListener('input', () => {
    const lesson = state.selectedLesson;
    const price = Number(state.subscriptionPrice || lessonPriceValue(lesson));
    const amount = Number(document.getElementById('subscription-pay-amount').value || 0);
    if (price > 0 && amount > 0) setSubscriptionLessonCount(Math.max(2, Math.round(amount / price)));
    else updateSubscriptionPayHint();
});
document.getElementById('subscription-count-minus').onclick = () => setSubscriptionLessonCount(getSubscriptionLessonCount() - 1);
document.getElementById('subscription-count-plus').onclick = () => setSubscriptionLessonCount(getSubscriptionLessonCount() + 1);
document.getElementById('btn-subscription-pay-cancel').onclick = () => document.getElementById('subscription-pay-overlay').classList.add('hidden');
document.getElementById('btn-subscription-pay-apply').onclick = async () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    const amount = Number(document.getElementById('subscription-pay-amount').value || 0);
    const lessonCount = getSubscriptionLessonCount();
    const sendReceipt = document.getElementById('subscription-send-receipt-checkbox').checked;
    const button = document.getElementById('btn-subscription-pay-apply');
    button.disabled = true;
    try {
        const response = await apiFetch('/pay_subscription', {
            method: 'POST',
            body: JSON.stringify({ date: lesson.date, id: lesson.id, student_id: state.subscriptionStudentId, amount, lesson_count: lessonCount, send_receipt: sendReceipt })
        });
        const result = await response.json();
        if (result.status !== 'ok') return alert(result.message || 'Ошибка оплаты абонемента');
        document.getElementById('subscription-pay-overlay').classList.add('hidden');
        await Promise.all([refreshScheduleOnly(), refreshStudentsOnly()]);
        await refreshOpenPaymentCard();
        alert(uiMessage`Абонемент оплачен: ${result.lessons_paid} занятий. Чек № ${result.receipt_number || '—'}. ${result.receipt_message || ''}`);
    } finally {
        button.disabled = false;
    }
};

document.getElementById('btn-paid-confirm-cancel').onclick = () => document.getElementById('paid-confirm-overlay').classList.add('hidden');
document.getElementById('btn-paid-confirm-apply').onclick = async () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    const isGroup = lesson.lesson_type === 'group';
    const sendReceipt = document.getElementById('send-receipt-checkbox').checked;
    const button = document.getElementById('btn-paid-confirm-apply');
    const paidStudentIds = isGroup
        ? Array.from(document.querySelectorAll('#group-paid-members input[type="checkbox"]:checked')).map(input => input.value)
        : [];
    button.disabled = true;
    try {
        const response = await apiFetch('/mark_paid', {
            method: 'POST',
            body: JSON.stringify({ date: lesson.date, id: lesson.id, paid: true, send_receipt: sendReceipt, paid_student_ids: paidStudentIds })
        });
        const result = await response.json();
        if (result.status !== 'ok') return alert(result.message || 'Ошибка изменения оплаты');
        document.getElementById('paid-confirm-overlay').classList.add('hidden');
        await refreshScheduleOnly();
        if (isGroup) alert(uiMessage`Оплаты группы сохранены. ${result.receipt_message || ''}`);
        else alert(uiMessage`Оплата отмечена. Чек № ${result.receipt_number || '—'}. ${result.receipt_message || ''}`);
    } finally {
        button.disabled = false;
    }
};
document.getElementById('btn-action-delete').onclick = () => {
    const personal = state.selectedLesson?.entry_type === 'personal';
    document.getElementById('delete-modal-title').textContent = personal ? 'Удаление личного дела' : 'Удаление занятия';
    document.getElementById('delete-modal-desc').textContent = personal ? 'Как удалить личное дело?' : 'Как удалить это занятие?';
    document.getElementById('btn-delete-once').textContent = personal ? 'Удалить только это личное дело' : 'Удалить только это занятие';
    document.getElementById('btn-delete-all').textContent = personal ? 'Удалить все будущие повторы' : 'Удалить все будущие (навсегда)';
    closeActionMenu();
    document.getElementById('delete-modal-overlay').classList.remove('hidden');
};
document.getElementById('btn-action-close').onclick = closeActionMenu;

// Написать ученику
document.getElementById('btn-action-chat-student').onclick = () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    if (lesson.lesson_type === 'group') {
        const members = lesson.group_members || [];
        if (!members.length) return alert('В группе нет учеников.');
        const choice = prompt(uiText('Кому написать?\n') + members.map((m, i) => `${i + 1}. ${m.name || uiText('Ученик')}`).join('\n') + uiText('\n\nВведите номер:'));
        const idx = parseInt(choice, 10) - 1;
        if (idx >= 0 && idx < members.length) openStudentContactFor(members[idx].student_id);
    } else {
        openStudentContactFor(lesson.student_id);
    }
    closeActionMenu();
};

// Написать родителю (выбор мессенджера)
document.getElementById('btn-action-chat-parent').onclick = () => {
    const lesson = state.selectedLesson;
    if (!lesson) return;
    if (lesson.lesson_type === 'group') {
        const members = lesson.group_members || [];
        if (!members.length) return alert('В группе нет учеников.');
        const choice = prompt(uiText('Родителю какого ученика написать?\n') + members.map((m, i) => `${i + 1}. ${m.name || uiText('Ученик')}`).join('\n') + uiText('\n\nВведите номер:'));
        const idx = parseInt(choice, 10) - 1;
        if (idx >= 0 && idx < members.length) openParentContactFor(members[idx].student_id);
    } else {
        openParentContactFor(lesson.student_id);
    }
    closeActionMenu();
};

function openExternalContactUrl(url) {
    try {
        if (typeof tg.openLink === 'function') return tg.openLink(url);
    } catch (_) { /* Browser fallback below. */ }
    return window.open(url, '_blank', 'noopener,noreferrer');
}

function normalizedWhatsAppNumber(value) {
    let digits = String(value || '').replace(/[^0-9]/g, '');
    if (/^8\d{10}$/.test(digits)) digits = '7' + digits.slice(1);
    return /^[1-9]\d{7,14}$/.test(digits) ? digits : '';
}

async function openContact(type, value) {
    switch(type) {
        case 'tg': {
            const clean = String(value).trim().replace('@', '');
            if (/^\d+$/.test(clean)) window.location.href = `tg://user?id=${clean}`;
            else tg.openTelegramLink(`https://t.me/${clean}`);
            break;
        }
        case 'wa': {
            const number = normalizedWhatsAppNumber(value);
            if (!number) return alert(uiText('Укажите номер WhatsApp в международном формате.', 'Enter the WhatsApp number in international format.'));
            openExternalContactUrl(`https://wa.me/${number}`);
            break;
        }
        case 'phone':
            openExternalContactUrl(`tel:${String(value).replace(/[^0-9+]/g, '')}`);
            break;
        case 'max': {
            const contact = String(value || '').trim();
            if (!contact) return alert(uiText('Контакт MAX не указан.', 'MAX contact is missing.'));
            try {
                await copyTextToClipboard(contact);
                if (typeof uxMessage === 'function') uxMessage(uiText('Контакт MAX скопирован. Откройте MAX и вставьте его в поиск.', 'MAX contact copied. Open MAX and paste it into search.'));
            } catch (_) {
                alert(uiText(`Не удалось скопировать автоматически. Контакт MAX: ${contact}`, `Could not copy automatically. MAX contact: ${contact}`));
            }
            break;
        }
        default:
            alert(uiMessage`Контакт: ${value}`);
    }
}

// Удаление
document.getElementById('btn-delete-once').onclick = async () => {
    const l = state.selectedLesson;
    const response = await apiFetch('/delete_lesson', { method: 'POST', body: JSON.stringify({ date: l.date, id: l.id, delete_all: false }) });
    const result = await response.json();
    if (result.status !== 'ok') return alert(result.message || 'Ошибка удаления');
    window.dispatchEvent(new CustomEvent('temli-calendar-changed', { detail: { token: result.undo_token, action: 'delete' } }));
    closeAllModals();
    refreshScheduleOnly();
};
document.getElementById('btn-delete-all').onclick = async () => {
    const l = state.selectedLesson;
    const response = await apiFetch('/delete_lesson', { method: 'POST', body: JSON.stringify({ date: l.date, id: l.id, delete_all: true }) });
    const result = await response.json();
    if (result.status !== 'ok') return alert(result.message || 'Ошибка удаления');
    window.dispatchEvent(new CustomEvent('temli-calendar-changed', { detail: { token: result.undo_token, action: 'delete' } }));
    closeAllModals();
    refreshScheduleOnly();
};
document.getElementById('btn-delete-cancel').onclick = closeAllModals;

// Перенос
document.querySelectorAll('[data-move-minute]').forEach(button => {
    button.onclick = () => {
        const current = moveTimeToMinutes(state.pendingMove?.newTime);
        if (current === null) return;
        setPendingMoveTime(moveTimeLabel(Math.floor(current / 60) * 60 + Number(button.dataset.moveMinute)));
    };
});
document.getElementById('btn-move-time-minus').onclick = () => shiftPendingMoveTime(-5);
document.getElementById('btn-move-time-plus').onclick = () => shiftPendingMoveTime(5);
document.getElementById('move-target-time').onchange = event => setPendingMoveTime(event.target.value);
document.getElementById('btn-action-copy').onclick = () => executeMove('copy');
document.getElementById('btn-action-move-once').onclick = () => executeMove('move_once');
document.getElementById('btn-action-move-all').onclick = () => executeMove('move_all');
document.getElementById('btn-action-move-cancel').onclick = cancelMove;
document.getElementById('btn-cancel-move').onclick = cancelMove;

// Кнопки сохранения и закрытия
document.getElementById('btn-save').onclick = saveLesson;
document.getElementById('btn-cancel-modal').onclick = closeAllModals;
document.getElementById('btn-close-modal').onclick = closeAllModals;
document.getElementById('btn-close-add-type').onclick = closeAllModals;
document.getElementById('btn-add-type-student').onclick = () => chooseAddType('student');
document.getElementById('btn-add-type-group').onclick = () => chooseAddType('group');
document.getElementById('btn-add-type-personal').onclick = () => chooseAddType('personal');
document.getElementById('btn-day-off-confirm').onclick = () => {
    const action = pendingDayOffSave;
    closeDayOffWarning();
    if (action) action();
};
document.getElementById('btn-day-off-cancel').onclick = closeDayOffWarning;
document.getElementById('day-off-warning-overlay').addEventListener('click', event => {
    if (event.target.id === 'day-off-warning-overlay') closeDayOffWarning();
});
['modal-overlay', 'add-type-overlay', 'move-modal-overlay', 'action-menu-overlay', 'delete-modal-overlay', 'date-picker-overlay', 'app-settings-overlay', 'receipt-settings-overlay', 'help-overlay', 'student-card-overlay', 'work-center-overlay', 'paid-confirm-overlay', 'subscription-pay-overlay', 'lesson-report-overlay', 'students-overlay', 'student-payment-overlay'].forEach(id => {
    document.getElementById(id).addEventListener('click', event => { if (event.target.id === id) closeAllModals(); });
});

// Дата и навигация
function stripCloneIds(root) {
    if (root.id) root.removeAttribute('id');
    root.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
}

function clearWeekDragStyles() {
    const grid = document.querySelector('#calendar-container > .calendar-grid');
    const header = document.getElementById('days-header');
    if (grid) {
        grid.style.transition = '';
        grid.style.transform = '';
        grid.style.willChange = '';
    }
    if (header) {
        header.style.transition = '';
        header.style.transform = '';
        header.style.willChange = '';
    }
    weekDragOffset = 0;
}

function setWeekDragOffset(dx) {
    const grid = document.querySelector('#calendar-container > .calendar-grid');
    const header = document.getElementById('days-header');
    const limit = Math.max(100, calendarContainer.clientWidth * 0.72);
    const offset = Math.max(-limit, Math.min(limit, dx * 0.82));
    weekDragOffset = offset;
    const transform = `translate3d(${offset}px, 0, 0)`;
    if (grid) {
        grid.style.willChange = 'transform';
        grid.style.transform = transform;
    }
    if (header) {
        header.style.willChange = 'transform';
        header.style.transform = transform;
    }
}

function animateBackFromWeekDrag() {
    const grid = document.querySelector('#calendar-container > .calendar-grid');
    const header = document.getElementById('days-header');
    [grid, header].forEach(el => {
        if (!el) return;
        el.style.transition = 'transform 180ms cubic-bezier(.22,.61,.36,1)';
        el.style.transform = 'translate3d(0,0,0)';
    });
    window.setTimeout(clearWeekDragStyles, 200);
}

async function shiftWeek(days, { fromSwipe = false } = {}) {
    if (calendarView === 'day') return shiftCalendarDay(Math.sign(days));
    if (weekTransitioning || !days) return;
    weekTransitioning = true;

    const direction = days > 0 ? -1 : 1;
    const container = document.getElementById('calendar-container');
    const targetMonday = new Date(state.currentMonday);
    targetMonday.setDate(targetMonday.getDate() + days);
    const targetWeekKey = dateKey(targetMonday);
    const readyFromCache = Boolean(cachedWeekSchedule(targetWeekKey));
    const dataPromise = fetchWeekSchedule(targetMonday, { allowCached: true });
    let releasePromise = Promise.resolve();
    let gridSnapshot = null;
    let headerSnapshot = null;

    try {
        if (fromSwipe && !readyFromCache) {
            animateBackFromWeekDrag();
            releasePromise = new Promise(resolve => window.setTimeout(resolve, 210));
        }
        // Подписываемся на сетевой запрос сразу, чтобы ранняя ошибка не стала
        // необработанным отклонением во время возвратной анимации.
        const [data] = await Promise.all([dataPromise, releasePromise]);
        const currentGrid = container.querySelector(':scope > .calendar-grid');
        const header = document.getElementById('days-header');
        const headerParent = header?.parentElement;
        const releaseOffset = readyFromCache && fromSwipe ? weekDragOffset : 0;

        gridSnapshot = currentGrid?.cloneNode(true) || null;
        headerSnapshot = header?.cloneNode(true) || null;
        if (gridSnapshot) {
            stripCloneIds(gridSnapshot);
            gridSnapshot.classList.add('week-slide-snapshot');
            gridSnapshot.style.transform = `translate3d(${releaseOffset}px,0,0)`;
            container.appendChild(gridSnapshot);
        }
        if (headerSnapshot && headerParent) {
            stripCloneIds(headerSnapshot);
            headerSnapshot.classList.add('week-header-snapshot');
            headerSnapshot.style.transform = `translate3d(${releaseOffset}px,0,0)`;
            headerParent.appendChild(headerSnapshot);
        }

        state.currentMonday = targetMonday;
        calendarDay = new Date(targetMonday);
        state.schedule = data.schedule;
        // Во время анимации сохраняем геометрию старой недели; автоподбор запускаем после слайда.
        autoFitWeekPending = false;
        clearWeekDragStyles();
        renderCalendar();

        const newGrid = container.querySelector(':scope > .calendar-grid');
        const newHeader = document.getElementById('days-header');
        [newGrid, newHeader].forEach(el => {
            if (!el) return;
            const startX = -direction * el.clientWidth + releaseOffset;
            el.style.transition = 'none';
            el.style.willChange = 'transform';
            el.style.transform = `translate3d(${startX}px,0,0)`;
        });

        // Два кадра гарантируют, что браузер увидит начальную позицию новой недели.
        requestAnimationFrame(() => requestAnimationFrame(() => {
            [newGrid, newHeader].forEach(el => {
                if (!el) return;
                el.style.transition = 'transform 230ms cubic-bezier(.22,.61,.36,1)';
                el.style.transform = 'translate3d(0,0,0)';
            });
            [gridSnapshot, headerSnapshot].forEach(el => {
                if (!el) return;
                const exitX = direction * el.clientWidth;
                el.style.transition = 'transform 230ms cubic-bezier(.22,.61,.36,1)';
                el.style.transform = `translate3d(${exitX}px,0,0)`;
            });
        }));

        window.setTimeout(() => {
            gridSnapshot?.remove();
            headerSnapshot?.remove();
            clearWeekDragStyles();
            weekTransitioning = false;
            // Preserve time and zoom when paging through the calendar.
            scheduleAdjacentWeekPrefetch(targetMonday);
        }, 270);
        scheduleWorkCenterRefresh();
    } catch (error) {
        console.error('Ошибка загрузки расписания:', error);
        gridSnapshot?.remove();
        headerSnapshot?.remove();
        animateBackFromWeekDrag();
        weekTransitioning = false;
    }
}

function openDatePicker() {
    const middle = new Date(state.currentMonday);
    middle.setDate(middle.getDate() + 3);
    state.datePickerMonth = new Date(middle.getFullYear(), middle.getMonth(), 1);
    renderDatePicker();
    document.getElementById('date-picker-overlay').classList.remove('hidden');
}

function renderDatePicker() {
    const base = new Date(state.datePickerMonth);
    const year = base.getFullYear();
    const month = base.getMonth();
    document.getElementById('date-picker-title').textContent = base.toLocaleDateString(uiLocale(), { month: 'long', year: 'numeric' });
    const grid = document.getElementById('date-picker-grid');
    grid.innerHTML = '';

    const first = new Date(year, month, 1);
    const mondayOffset = (first.getDay() + 6) % 7;
    const start = new Date(year, month, 1 - mondayOffset);
    const today = dateKey(new Date());

    for (let i = 0; i < 42; i++) {
        const date = new Date(start);
        date.setDate(start.getDate() + i);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'date-picker-day';
        if (date.getMonth() !== month) button.classList.add('other-month');
        if (dateKey(date) === today) button.classList.add('today');
        if (date >= state.currentMonday && date < new Date(state.currentMonday.getFullYear(), state.currentMonday.getMonth(), state.currentMonday.getDate() + 7)) button.classList.add('selected');
        button.textContent = date.getDate();
        button.onclick = () => {
            calendarDay = new Date(date);
            state.currentMonday = getMonday(date);
            autoFitWeekPending = true;
            document.getElementById('date-picker-overlay').classList.add('hidden');
            refreshScheduleOnly();
        };
        grid.appendChild(button);
    }
}

document.getElementById('btn-date-picker').onclick = openDatePicker;
document.getElementById('date-picker-prev').onclick = () => { state.datePickerMonth.setMonth(state.datePickerMonth.getMonth() - 1); renderDatePicker(); };
document.getElementById('date-picker-next').onclick = () => { state.datePickerMonth.setMonth(state.datePickerMonth.getMonth() + 1); renderDatePicker(); };
document.getElementById('date-picker-today').onclick = () => {
    const today = new Date();
    state.currentMonday = getMonday(today);
    calendarDay = new Date(today);
    autoFitWeekPending = true;
    document.getElementById('date-picker-overlay').classList.add('hidden');
    refreshScheduleOnly();
};
document.getElementById('date-picker-close').onclick = () => document.getElementById('date-picker-overlay').classList.add('hidden');

document.getElementById('btn-today').onclick = () => { calendarDay = new Date(); state.currentMonday = getMonday(calendarDay); autoFitWeekPending = true; refreshScheduleOnly(); };
document.getElementById('btn-prev-week').onclick = () => shiftWeek(-7);
document.getElementById('btn-next-week').onclick = () => shiftWeek(7);
document.getElementById('btn-zoom-in').onclick = () => applyHourHeightSmooth(Math.min(MAX_HOUR_HEIGHT, hourHeight + ZOOM_STEP));
document.getElementById('btn-zoom-out').onclick = () => applyHourHeightSmooth(Math.max(MIN_HOUR_HEIGHT, hourHeight - ZOOM_STEP));

async function downloadApiFile(path, options, fallbackFilename) {
    const response = await apiFetch(path, options || {});
    if (!response.ok) {
        let message = 'Не удалось скачать файл';
        try {
            const data = await response.json();
            message = data.message || message;
        } catch (_) {}
        throw new Error(message);
    }

    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
    let filename = fallbackFilename;
    if (match && match[1]) {
        try { filename = decodeURIComponent(match[1].replace(/\"/g, '').trim()); } catch (_) {}
    }

    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1500);
}

async function runExportButton(button, workingText, action) {
    const original = button.innerHTML;
    button.disabled = true;
    button.classList.add('is-loading');
    button.innerHTML = `<span class="settings-link-main"><strong>${workingText}</strong><small>Подождите немного…</small></span><span>…</span>`;
    try {
        await action();
    } catch (error) {
        alert(error.message || 'Ошибка экспорта');
    } finally {
        button.disabled = false;
        button.classList.remove('is-loading');
        button.innerHTML = original;
    }
}

async function sendExportToTelegram(path, options = {}) {
    const response = await apiFetch(path, options);
    let result = {};
    try { result = await response.json(); } catch (_) {}
    if (!response.ok || result.status !== 'ok') {
        throw new Error(result.message || 'Не удалось отправить файл в Telegram');
    }
    alert(result.message || 'Файл отправлен в Telegram.');
}

const btnDownloadBook = document.getElementById('btn-download-book');
btnDownloadBook.onclick = () => runExportButton(btnDownloadBook, 'Отправляю книгу учёта', async () => {
    await sendExportToTelegram('/download_book', { method: 'GET' });
});

const btnExportWeekPdf = document.getElementById('btn-export-week-pdf');
btnExportWeekPdf.onclick = () => runExportButton(btnExportWeekPdf, 'Отправляю PDF недели', async () => {
    const start = dateKey(state.currentMonday);
    await sendExportToTelegram('/export_week_pdf', {
        method: 'POST',
        body: JSON.stringify({ week_start: start })
    });
});

// Общие настройки и данные для чека
const receiptSettingFields = [
    'company_name', 'inn', 'ogrnip', 'address', 'phone', 'service_name', 'tax_system',
    'email_sender', 'thanks_text', 'website', 'bank_name', 'bik', 'account_number',
    'corr_account', 'recipient', 'payment_comment'
];

function syncLanguageSegment(language = document.getElementById('interface-language').value) {
    const segment = document.getElementById('interface-language-segment');
    if (!segment) return;
    segment.dataset.active = language;
    segment.querySelectorAll('[data-language]').forEach(button => {
        const active = button.dataset.language === language;
        button.classList.toggle('active', active);
        button.setAttribute('aria-checked', String(active));
    });
}

function fillAppSettingsForm() {
    document.getElementById('interface-language').value = state.settings.language || 'ru';
    syncLanguageSegment(state.settings.language || 'ru');
    document.getElementById('interface-currency').value = state.settings.currency || 'RUB';
    document.getElementById('default-reminders-enabled').checked = state.settings.default_student_reminders === true;
    document.getElementById('default-parent-end').checked = state.settings.parent_lesson_end === true;
    document.getElementById('default-zoom-link').value = state.settings.zoom_link || '';
    document.getElementById('work-start').value = state.settings.work_start || '06:00';
    document.getElementById('work-end').value = state.settings.work_end || '00:00';
    const daysOff = configuredDaysOff();
    document.querySelectorAll('#days-off-options input').forEach(input => {
        input.checked = daysOff.has(Number(input.value));
    });
    document.getElementById('default-send-receipts').checked = state.settings.default_send_receipts !== false;
    document.getElementById('default-send-receipt-copy').checked = state.settings.default_send_receipt_copy !== false;
    document.getElementById('student-binding-template').value = state.settings.student_binding_template || '';
    document.getElementById('parent-binding-template').value = state.settings.parent_binding_template || '';
    document.getElementById('student-reminder-template').value = state.settings.student_reminder_template || '';
    document.getElementById('parent-end-template').value = state.settings.parent_lesson_end_template || '';
    document.getElementById('teacher-delay-template').value = state.settings.teacher_delay_template || '';
    document.getElementById('student-delay-template').value = state.settings.student_delay_template || '';
    document.getElementById('parent-delay-template').value = state.settings.parent_delay_template || '';
    document.getElementById('notification-templates-status').textContent = '';
}

function fillReceiptSettingsForm() {
    receiptSettingFields.forEach(key => {
        const el = document.getElementById(`settings-${key}`);
        if (el) el.value = state.settings[key] || '';
    });
    document.getElementById('current-logo-name').textContent = state.settings.receipt_logo || 'не загружена';
    document.getElementById('current-signature-name').textContent = state.settings.receipt_signature || 'не загружена';
    document.getElementById('current-qrcode-name').textContent = state.settings.receipt_qrcode || 'не загружен';
}

function onboardingSuggestedLesson() {
    const now = new Date();
    const suggested = new Date(now);
    suggested.setMinutes(0, 0, 0);
    suggested.setHours(suggested.getHours() + 1);
    const workStart = String(state.settings.work_start || '06:00');
    const startMinutes = workingTimeMinutes(workStart, 6 * 60);
    const endMinutes = workingTimeMinutes(state.settings.work_end || '00:00', 24 * 60, true);
    const suggestedMinutes = suggested.getHours() * 60 + suggested.getMinutes();
    if (suggestedMinutes < startMinutes) {
        suggested.setHours(Math.floor(startMinutes / 60), startMinutes % 60, 0, 0);
    } else if (suggestedMinutes >= endMinutes) {
        suggested.setDate(suggested.getDate() + 1);
        suggested.setHours(Math.floor(startMinutes / 60), startMinutes % 60, 0, 0);
    }
    return suggested;
}

function showOnboardingStep(step) {
    ['settings', 'lesson', 'done'].forEach(name => {
        document.getElementById(`onboarding-step-${name}`).classList.toggle('hidden', name !== step);
    });
}

function showOnboardingIfNeeded() {
    if (!state.onboardingNeeded) return;
    window.dispatchEvent(new Event('temli-onboarding-needed'));
}

async function markOnboardingCompleted() {
    const response = await apiFetch('/update_settings', {
        method: 'POST', body: JSON.stringify({ onboarding_completed: true })
    });
    const result = await response.json();
    if (result.status !== 'ok') throw new Error(result.message || 'Не удалось завершить настройку');
    state.settings = result.settings || { ...state.settings, onboarding_completed: true };
    state.onboardingNeeded = false;
}

document.getElementById('btn-onboarding-next').onclick = () => {
    const start = document.getElementById('onboarding-work-start').value;
    const end = document.getElementById('onboarding-work-end').value;
    if (!workingTimeRangeIsValid(start, end)) return alert('Проверьте рабочие часы: время окончания должно быть позже начала.');
    showOnboardingStep('lesson');
    document.getElementById('onboarding-student-name').focus();
};
document.getElementById('btn-onboarding-back').onclick = () => showOnboardingStep('settings');
document.querySelectorAll('.btn-onboarding-skip').forEach(button => {
    button.onclick = async () => {
        button.disabled = true;
        try {
            await markOnboardingCompleted();
            document.getElementById('onboarding-overlay').classList.add('hidden');
        } catch (error) {
            alert(error.message || 'Не удалось пропустить настройку');
        } finally { button.disabled = false; }
    };
});
document.getElementById('btn-onboarding-create').onclick = async () => {
    const button = document.getElementById('btn-onboarding-create');
    if (button.disabled) return;
    const student = document.getElementById('onboarding-student-name').value.trim();
    const date = document.getElementById('onboarding-lesson-date').value;
    const time = document.getElementById('onboarding-lesson-time').value;
    const duration = Number(document.getElementById('onboarding-duration').value || 60);
    const priceRaw = document.getElementById('onboarding-price').value;
    const price = priceRaw === '' ? 0 : Number(priceRaw);
    const workStart = document.getElementById('onboarding-work-start').value;
    const workEnd = document.getElementById('onboarding-work-end').value;
    if (!student) return alert('Укажите имя ученика.');
    if (!date || !time) return alert('Укажите дату и время занятия.');
    if (!Number.isInteger(duration) || duration < 15 || duration > 1440) return alert('Длительность занятия должна быть от 15 до 1440 минут.');
    if (!Number.isFinite(price) || price < 0) return alert('Стоимость занятия должна быть неотрицательным числом.');
    button.disabled = true;
    try {
        const settingsResponse = await apiFetch('/update_settings', {
            method: 'POST', body: JSON.stringify({ work_start: workStart, work_end: workEnd })
        });
        const settingsResult = await settingsResponse.json();
        if (settingsResult.status !== 'ok') throw new Error(settingsResult.message || 'Не удалось сохранить рабочие часы');
        state.settings = settingsResult.settings || { ...state.settings, work_start: workStart, work_end: workEnd };
        autoFitWeekPending = true;

        const lessonResponse = await apiFetch('/add_lesson', {
            method: 'POST',
            body: JSON.stringify({
                date, time, duration, lesson_type: 'student', student, student_id: '', price,
                reminder_enabled: state.settings.default_reminders_enabled !== false,
                reminder_minutes: 60, repeat: 'no', repeat_until: ''
            })
        });
        const lessonResult = await lessonResponse.json();
        if (lessonResult.status !== 'ok') throw new Error(lessonResult.message || 'Не удалось создать занятие');
        try { await markOnboardingCompleted(); } catch (error) { console.warn(error); }
        await refreshScheduleAndStudents();
        updateVisibleHoursFromSettingsAndLessons();
        showOnboardingStep('done');
    } catch (error) {
        alert(error.message || 'Не удалось создать первое занятие');
    } finally { button.disabled = false; }
};
document.getElementById('btn-onboarding-finish').onclick = () => document.getElementById('onboarding-overlay').classList.add('hidden');
document.getElementById('btn-onboarding-receipts').onclick = () => {
    document.getElementById('onboarding-overlay').classList.add('hidden');
    fillReceiptSettingsForm();
    document.getElementById('receipt-settings-overlay').classList.remove('hidden');
};

async function uploadReceiptAsset(assetType, inputId) {
    const input = document.getElementById(inputId);
    if (!input || !input.files || !input.files[0]) return null;
    const formData = new FormData();
    formData.append('asset_type', assetType);
    formData.append('file', input.files[0]);
    const response = await apiFetch('/upload_receipt_asset', { method: 'POST', body: formData });
    const result = await response.json();
    if (result.status !== 'ok') throw new Error(result.message || 'Ошибка загрузки файла');
    return result.settings || null;
}

let personalBotCurrent = null;
let personalBotBusy = false;
let personalBotView = null;
function botText(ru, en) { return uiLocale().startsWith('en') ? en : ru; }
function botMessage(code) {
    const messages = {
        unavailable: ['Подключение пока не включено на сервере.', 'Bot connections are not enabled on the server yet.'],
        invalid_token: ['Проверьте токен BotFather.', 'Check your BotFather token.'],
        telegram_unavailable: ['Telegram не подтвердил токен. Проверьте его или повторите позже.', 'Telegram could not verify the token. Check it or try later.'],
        central_bot: ['Главный бот TEMLI подключать нельзя.', 'The central TEMLI bot cannot be connected.'],
        existing_webhook: ['Бот уже подключён к другому сервису. Используйте отдельного бота.', 'This bot has a webhook. Use a dedicated bot.'],
        already_connected: ['Бот уже подключён к другому аккаунту.', 'This bot is already connected to another account.'],
        disconnect_first: ['Сначала отключите текущего бота.', 'Disconnect the current bot first.'],
        expired_preview: ['Проверка истекла. Проверьте токен заново.', 'Verification expired. Check the token again.'],
        key_mismatch: ['Не удалось открыть сохранённое подключение. Обратитесь к администратору.', 'The saved connection cannot be read. Contact the administrator.'],
        changed: ['Подключение изменилось. Откройте настройки заново.', 'The connection changed. Reopen settings.']
        ,bot_required: ['Бот для приглашений пока недоступен.', 'The invitation bot is currently unavailable.']
        ,bot_unavailable: ['TEMLI-бот ещё запускается. Попробуйте чуть позже.', 'The TEMLI bot is starting. Try again shortly.']
        ,student_missing: ['Карточка ученика не найдена.', 'Student profile not found.']
        ,binding_missing: ['Привязка изменилась. Обновите список.', 'The connection changed. Refresh the list.']
        ,public_url: ['Не настроен адрес приёма сообщений. Обратитесь к администратору TEMLI.', 'The message endpoint is not configured. Contact TEMLI support.']
    };
    const pair = messages[code] || ['Не удалось выполнить действие. Повторите позже.', 'Unable to complete the action. Try later.'];
    return botText(...pair);
}
function renderPersonalBot(result) {
    personalBotView = result;
    renderPersonalBotLabels();
    personalBotCurrent = result.bot || null;
    const connected = Boolean(personalBotCurrent);
    document.getElementById('personal-bot-status').textContent = !result.enabled ? botMessage('unavailable')
        : connected ? botText('Подключён: ', 'Connected: ') + personalBotCurrent.name + ' · @' + personalBotCurrent.username
        : botText('Личный бот не подключён. Приглашения работают через TEMLI.', 'No personal bot connected. Invitations work through TEMLI.');
    document.getElementById('personal-bot-help').hidden = connected;
    document.getElementById('personal-bot-label').hidden = connected;
    document.getElementById('personal-bot-token').hidden = connected;
    document.getElementById('personal-bot-check').hidden = connected;
    document.getElementById('personal-bot-check').disabled = !result.enabled;
    document.getElementById('personal-bot-token').disabled = !result.enabled;
    document.getElementById('personal-bot-disconnect').hidden = !connected;
}
function renderPersonalBotLabels() {
    const text = (id, ru, en) => { document.getElementById(id).textContent = botText(ru, en); };
    text('personal-bot-title', 'Мой бот', 'My bot');
    text('personal-bot-label', 'Токен BotFather', 'BotFather token');
    text('personal-bot-check', 'Проверить и подключить', 'Verify and connect');
    text('personal-bot-disconnect', 'Отключить', 'Disconnect');
    text('personal-bot-help', 'Личный бот — по желанию: создайте его через /newbot в @BotFather и вставьте токен. Без него приглашения и сообщения работают через общий TEMLI-бот. Не подключайте бота другого сервиса.',
        'A personal bot is optional: create one using /newbot in @BotFather and paste its token. Without one, invitations and messages use the shared TEMLI bot. Do not connect another service’s bot.');
    text('teacher-delay-template-label', 'Я задержусь — ученику', 'My delay — to student');
    text('student-delay-template-label', 'Ученик задерживается — ученику', 'Student delay — to student');
    text('parent-delay-template-label', 'Ученик задерживается — родителю', 'Student delay — to parent');
    text('delay-template-hint', '{time} — время начала с учётом задержки.', '{time} — start time including the delay.');
    text('notification-templates-title', 'Тексты сообщений', 'Message texts');
    text('notification-templates-help', 'Редкая настройка. Пустое поле использует стандартный текст.', 'Rare setting. Leave a field empty to use the default text.');
    text('student-binding-template-label', 'После подключения ученика', 'After a student connects');
    text('parent-binding-template-label', 'После подключения родителя', 'After a parent connects');
    text('student-reminder-template-label', 'Напоминание ученику', 'Student reminder');
    text('parent-end-template-label', 'Родителю после занятия', 'Parent after the lesson');
    text('student-binding-template-hint', 'Можно использовать {name}.', 'Available variable: {name}.');
    text('parent-binding-template-hint', 'Можно использовать {name}.', 'Available variable: {name}.');
    text('student-reminder-template-hint', 'Переменные: {time}, {link}.', 'Variables: {time}, {link}.');
    text('parent-end-template-hint', 'Переменные: {start}, {end}.', 'Variables: {start}, {end}.');
    text('btn-reset-notification-templates', 'Вернуть стандартные тексты', 'Restore default texts');
    document.getElementById('student-binding-template').placeholder = botText('Привет! Мы на связи 😊 Скоро я всё подтвержу, и сюда будут приходить мои напоминания о занятиях.', 'Hi! We’re connected 😊 I’ll confirm everything soon, and my lesson reminders will arrive here.');
    document.getElementById('parent-binding-template').placeholder = botText('Здравствуйте! Спасибо, что подключились 😊 Скоро я всё подтвержу, и сюда будут приходить мои сообщения о занятиях.', 'Hello! Thank you for connecting 😊 I’ll confirm everything soon, and my lesson updates will arrive here.');
    document.getElementById('student-reminder-template').placeholder = botText('Напоминание: занятие в {time}.', 'Reminder: lesson at {time}.');
    document.getElementById('parent-end-template').placeholder = botText('Приветствую! Сегодня было проведено занятие с {start} до {end}.', 'Hello! Today’s lesson was held from {start} to {end}.');
}
window.addEventListener('temli-language-change', () => {
    updateAddTypeContext();
    renderPersonalBotLabels();
    if (personalBotView) renderPersonalBot(personalBotView);
    renderInviteLabels();
    renderPendingBindingBadge();
});
async function loadPersonalBot() {
    if (personalBotBusy) return;
    personalBotView = null;
    renderPersonalBotLabels();
    document.getElementById('personal-bot-token').value = '';
    document.getElementById('personal-bot-check').disabled = true;
    document.getElementById('personal-bot-disconnect').hidden = true;
    document.getElementById('personal-bot-status').textContent = botText('Загрузка…', 'Loading…');
    try {
        const response = await apiFetch('/personal_bot');
        const result = await response.json();
        if (!response.ok || result.status !== 'ok') throw new Error(result.code || '');
        renderPersonalBot(result);
    } catch (error) {
        document.getElementById('personal-bot-status').textContent = botMessage(error.message);
    }
}
async function personalBotAction(payload) {
    const response = await apiFetch('/personal_bot', {method: 'POST', body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok || result.status !== 'ok') throw new Error(result.code || '');
    return result;
}
async function runPersonalBotAction(action) {
    if (personalBotBusy) return;
    personalBotBusy = true;
    const check = document.getElementById('personal-bot-check');
    const disconnect = document.getElementById('personal-bot-disconnect');
    check.disabled = disconnect.disabled = true;
    try { await action(); }
    catch (error) { document.getElementById('personal-bot-status').textContent = botMessage(error.message); }
    finally { personalBotBusy = false; check.disabled = disconnect.disabled = false; }
}
document.getElementById('personal-bot-check').onclick = () => runPersonalBotAction(async () => {
    const input = document.getElementById('personal-bot-token');
    const token = input.value.trim();
    input.value = '';
    const preview = await personalBotAction({action: 'preview', token});
    if (!confirm(botText('Подключить ', 'Connect ') + preview.bot.name + ' · @' + preview.bot.username + '?')) return;
    renderPersonalBot(await personalBotAction({action: 'connect', ticket: preview.ticket}));
});
document.getElementById('personal-bot-disconnect').onclick = () => runPersonalBotAction(async () => {
    if (!personalBotCurrent || !confirm(botText('Отключить личного бота от TEMLI?', 'Disconnect your personal bot from TEMLI?'))) return;
    renderPersonalBot(await personalBotAction({action: 'disconnect', bot_id: personalBotCurrent.bot_id}));
});

document.getElementById('btn-reset-notification-templates').onclick = () => {
    for (const id of ['student-binding-template','parent-binding-template','student-reminder-template','parent-end-template','teacher-delay-template','student-delay-template','parent-delay-template'])
        document.getElementById(id).value = '';
    document.getElementById('notification-templates-status').textContent = botText('Стандартные тексты будут восстановлены после сохранения.', 'Default texts will be restored after saving.');
};

document.getElementById('btn-app-settings').onclick = () => {
    document.getElementById('settings-build-version').textContent = `TEMLI ${window.TEMLI_I18N?.VERSION || '—'}`;
    document.getElementById('notification-templates-panel').open = false;
    fillAppSettingsForm();
    loadPersonalBot();
    document.getElementById('app-settings-overlay').classList.remove('hidden');
};
async function closeAppSettings() {
    document.getElementById('personal-bot-token').value = '';
    await window.TEMLI_I18N?.setLanguage(state.settings.language || 'ru', { persist: false });
    window.TEMLI_I18N?.setCurrency(state.settings.currency || 'RUB', { persist: false });
    document.getElementById('app-settings-overlay').classList.add('hidden');
}
document.getElementById('btn-close-app-settings').onclick = closeAppSettings;
document.getElementById('btn-cancel-app-settings').onclick = closeAppSettings;
document.getElementById('interface-currency').onchange = event => {
    window.TEMLI_I18N?.setCurrency(event.target.value, { persist: false });
};
document.querySelectorAll('#interface-language-segment [data-language]').forEach(button => {
    button.onclick = () => {
        const select = document.getElementById('interface-language');
        select.value = button.dataset.language;
        select.dispatchEvent(new Event('change', { bubbles: true }));
    };
});
document.getElementById('interface-language').onchange = async event => {
    const language = event.target.value;
    syncLanguageSegment(language);
    try {
        await window.TEMLI_I18N?.setLanguage(language, { persist: false });
        renderPersonalBotLabels();
    } catch (error) {
        alert('Не удалось загрузить выбранный язык.');
    }
};
document.getElementById('btn-save-app-settings').onclick = async () => {
    const button = document.getElementById('btn-save-app-settings');
    const workStart = document.getElementById('work-start').value || '06:00';
    const workEnd = document.getElementById('work-end').value || '00:00';
    if (!workingTimeRangeIsValid(workStart, workEnd)) return alert('Проверьте рабочие часы: время окончания должно быть позже начала.');
    button.disabled = true;
    try {
        const settings = {
            language: document.getElementById('interface-language').value || 'ru',
            currency: document.getElementById('interface-currency').value || 'RUB',
            default_student_reminders: document.getElementById('default-reminders-enabled').checked,
            parent_lesson_end: document.getElementById('default-parent-end').checked,
            zoom_link: normalizeExternalUrl(document.getElementById('default-zoom-link').value),
            work_start: workStart,
            work_end: workEnd,
            days_off: Array.from(document.querySelectorAll('#days-off-options input:checked'), input => Number(input.value)),
            default_send_receipts: document.getElementById('default-send-receipts').checked,
            default_send_receipt_copy: document.getElementById('default-send-receipt-copy').checked,
            student_binding_template: document.getElementById('student-binding-template').value.trim(),
            parent_binding_template: document.getElementById('parent-binding-template').value.trim(),
            student_reminder_template: document.getElementById('student-reminder-template').value.trim(),
            parent_lesson_end_template: document.getElementById('parent-end-template').value.trim(),
            teacher_delay_template: document.getElementById('teacher-delay-template').value.trim(),
            student_delay_template: document.getElementById('student-delay-template').value.trim(),
            parent_delay_template: document.getElementById('parent-delay-template').value.trim()
        };
        const response = await apiFetch('/update_settings', { method: 'POST', body: JSON.stringify(settings) });
        const result = await response.json();
        if (result.status !== 'ok') return alert(result.message || 'Ошибка сохранения настроек');
        state.settings = result.settings || { ...state.settings, ...settings };
        window.dispatchEvent(new CustomEvent('temli-saved', { detail: { overlay: 'app-settings-overlay' } }));
        await window.TEMLI_I18N?.setLanguage(state.settings.language || 'ru');
        window.TEMLI_I18N?.setCurrency(state.settings.currency || 'RUB');
        updateVisibleHoursFromSettingsAndLessons();
        autoFitWeekPending = true;
        renderCalendar();
        scheduleWorkCenterRefresh();
        document.getElementById('app-settings-overlay').classList.add('hidden');
    } catch (error) {
        alert(error.message || 'Ошибка сохранения настроек');
    } finally {
        button.disabled = false;
    }
};

document.getElementById('btn-open-receipt-settings').onclick = () => {
    fillReceiptSettingsForm();
    document.getElementById('app-settings-overlay').classList.add('hidden');
    document.getElementById('receipt-settings-overlay').classList.remove('hidden');
};
function openHelp(fromSettings = true) {
    document.getElementById('app-settings-overlay').classList.add('hidden');
    const helpOverlay = document.getElementById('help-overlay');
    helpOverlay.dataset.returnTo = fromSettings ? 'settings' : 'calendar';
    helpOverlay.classList.remove('hidden');
    const helpBody = helpOverlay.querySelector('.modal-body');
    if (helpBody) helpBody.scrollTop = 0;
    window.dispatchEvent(new CustomEvent('temli-help-open'));
    document.getElementById('btn-back-help').focus({preventScroll: true});
}
document.getElementById('btn-open-help').onclick = () => openHelp(true);
function closeHelp(openMain = true) {
    const helpOverlay = document.getElementById('help-overlay');
    helpOverlay.classList.add('hidden');
    const toSettings = openMain && helpOverlay.dataset.returnTo !== 'calendar';
    if (toSettings) document.getElementById('app-settings-overlay').classList.remove('hidden');
    const target = toSettings ? 'btn-open-help' : document.getElementById('calendar-first-step')?.hidden === false ? 'btn-first-help' : 'btn-app-settings';
    document.getElementById(target)?.focus({preventScroll: true});
}
document.getElementById('btn-back-help').onclick = () => closeHelp(true);
document.getElementById('btn-help-back-bottom').onclick = () => closeHelp(true);
document.getElementById('btn-close-help').onclick = () => closeHelp(false);
function closeReceiptSettings(openMain = true) {
    document.getElementById('receipt-settings-overlay').classList.add('hidden');
    if (openMain) document.getElementById('app-settings-overlay').classList.remove('hidden');
}
document.getElementById('btn-back-receipt-settings').onclick = () => closeReceiptSettings(true);
document.getElementById('btn-cancel-receipt-settings').onclick = () => closeReceiptSettings(true);
document.getElementById('btn-close-receipt-settings').onclick = () => closeReceiptSettings(false);
document.getElementById('btn-save-receipt-settings').onclick = async () => {
    const button = document.getElementById('btn-save-receipt-settings');
    button.disabled = true;
    try {
        const settings = {};
        receiptSettingFields.forEach(key => {
            const el = document.getElementById(`settings-${key}`);
            settings[key] = el ? el.value.trim() : '';
        });
        const response = await apiFetch('/update_settings', { method: 'POST', body: JSON.stringify(settings) });
        const result = await response.json();
        if (result.status !== 'ok') throw new Error(result.message || 'Ошибка сохранения данных для чека');
        state.settings = result.settings || { ...state.settings, ...settings };
        for (const [type, inputId] of [['logo', 'settings-logo-file'], ['signature', 'settings-signature-file'], ['qrcode', 'settings-qrcode-file']]) {
            const updated = await uploadReceiptAsset(type, inputId);
            if (updated) state.settings = updated;
        }
        ['settings-logo-file', 'settings-signature-file', 'settings-qrcode-file'].forEach(id => {
            const input = document.getElementById(id);
            if (input) input.value = '';
        });
        fillReceiptSettingsForm();
        alert('Данные для чека сохранены');
    } catch (error) {
        alert(error.message || 'Ошибка сохранения данных для чека');
    } finally {
        button.disabled = false;
    }
};

// Карточка ученика: имя, стоимость, контакты и статистика оплат
async function loadStudentLessonStats(studentId) {
    const ratio = document.getElementById('student-lessons-ratio');
    const historyList = document.getElementById('student-history-list');
    const historySummary = document.getElementById('student-history-summary');
    ratio.textContent = '… / …';
    if (historyList) historyList.innerHTML = '<div class="student-history-empty">Загрузка…</div>';
    if (historySummary) historySummary.textContent = '';
    try {
        const response = await apiFetch('/get_student_stats', { method: 'POST', body: JSON.stringify({ student_id: studentId }) });
        const result = await response.json();
        if (result.status !== 'ok') throw new Error(result.message || 'Ошибка статистики');
        ratio.textContent = `${result.paid_lessons || 0} / ${result.conducted_lessons || 0}`;
        if (historySummary) historySummary.textContent = `${result.total_lessons || 0} ${uiText('всего')}`;
        if (historyList) {
            const history = Array.isArray(result.history) ? result.history : [];
            historyList.innerHTML = history.length ? history.map(item => {
                const dateLabel = shortDateRu(item.date);
                const paidLabel = item.paid ? 'оплачено' : 'не оплачено';
                const report = String(item.report || '').trim();
                return `<div class="student-history-row student-history-row-report"><div class="student-history-main"><span>${escapeHtml(dateLabel)} · ${escapeHtml(item.time || '')}</span><span class="student-history-paid ${item.paid ? 'is-paid' : ''}">${paidLabel}</span></div>${report ? `<div class="student-history-report" data-i18n-ignore>${escapeHtml(report)}</div>` : ''}</div>`;
            }).join('') : '<div class="student-history-empty">Занятий пока нет</div>';
        }
    } catch (error) {
        ratio.textContent = '— / —';
        if (historyList) historyList.innerHTML = '<div class="student-history-empty">Не удалось загрузить историю</div>';
    }
}

function setStudentStatus(status) {
    const normalized = status === 'paused' ? 'paused' : 'active';
    document.getElementById('student-card-overlay').dataset.studentStatus = normalized;
    document.getElementById('student-status-active').classList.toggle('active', normalized === 'active');
    document.getElementById('student-status-paused').classList.toggle('active', normalized === 'paused');
}

document.getElementById('student-status-active').onclick = () => setStudentStatus('active');
document.getElementById('student-status-paused').onclick = () => setStudentStatus('paused');

function hasAllocatedPayment(target) {
    return Number(target.paid_amount || 0) > 0 || (target.allocation_ids || []).length > 0;
}

function paymentStatusLabel(target) {
    if (target.free) return 'Бесплатно';
    if (hasAllocatedPayment(target)) return target.paid ? 'Оплачено общей суммой' : 'Частично общей суммой';
    if (target.paid_via_subscription) return 'Абонемент';
    return target.paid ? 'Оплачено' : 'Не оплачено';
}

function paymentActionLabel(target) {
    if (hasAllocatedPayment(target)) return 'Оплачено общей суммой';
    if (target.paid_via_subscription) return 'Оплачено абонементом';
    return target.paid && !target.free ? 'Снять оплату' : 'Оплачено';
}

function paymentActionIcon(target) {
    if (target.paid_via_subscription) return 'subscription';
    return target.paid && !target.free ? 'restore' : 'paid';
}

function explainAllocatedPayment(studentId) {
    alert('На занятие распределена общая сумма, возможно частично. Полностью отменить платёж можно в истории общих оплат карточки ученика. Старые распределения без истории автоматически не отменяются.');
    closeActionMenu();
    openStudentCard(studentId);
    document.getElementById('student-finances').open = true;
    document.querySelector('.student-payment-history').open = true;
}

async function refreshOpenPaymentCard() {
    const card = document.getElementById('student-card-overlay');
    if (!card.classList.contains('hidden') && card.dataset.studentId) {
        await Promise.all([loadStudentPayments(card.dataset.studentId), loadStudentLessonStats(card.dataset.studentId)]);
    }
}

let studentPaymentsRequest = 0;
async function loadStudentPayments(studentId) {
    const requestId = ++studentPaymentsRequest;
    const list = document.getElementById('student-payment-lessons');
    const transactions = document.getElementById('student-payment-transactions');
    list.textContent = 'Загрузка оплат…';
    transactions.textContent = '';
    try {
        const response = await apiFetch('/get_student_payments', { method: 'POST', body: JSON.stringify({ student_id: studentId }) });
        const result = await response.json();
        if (requestId !== studentPaymentsRequest || document.getElementById('student-card-overlay').dataset.studentId !== String(studentId)) return;
        if (result.status !== 'ok') throw new Error(result.message || 'Не удалось загрузить оплаты');
        const lessons = result.lessons || [];
        list.innerHTML = '';
        if (!lessons.length) list.textContent = 'Занятий пока нет.';
        lessons.forEach(item => {
            const row = document.createElement('article');
            row.className = 'student-finance-row';
            const price = item.price == null ? 'Цена не указана' : money(item.price);
            const allocated = hasAllocatedPayment(item);
            const actions = item.source === 'unpaid'
                ? `<button type="button" data-finance-action="direct">${threadIcon('paid')}Оплачено</button><button type="button" data-finance-action="subscription">${threadIcon('subscription')}Абонемент</button><button type="button" data-finance-action="free">${threadIcon('free')}Бесплатно</button>`
                : item.source === 'direct' ? `<button type="button" data-finance-action="reverse">${threadIcon('restore')}Снять оплату</button>`
                : item.source === 'free' ? `<button type="button" data-finance-action="unfree">${threadIcon('restore')}Отменить бесплатно</button>` : '';
            let note = '';
            if (allocated) {
                note = (item.allocation_ids || []).length
                    ? 'Отмена всего платежа — в истории общих оплат ниже. Если платежи пересекаются, сначала отмените более поздний.'
                    : 'Старое распределение без истории: автоматическая отмена недоступна.';
            } else if (item.source === 'subscription') {
                note = 'Оплачено абонементом. Снятие оплаты одного занятия заблокировано, чтобы сохранить учёт абонемента.';
            }
            row.innerHTML = `<strong>${escapeHtml(item.date)} · ${escapeHtml(item.time || '')}</strong>
                <div>${item.lesson_type === 'group' ? `<span>${uiText('Группа')}</span> · ${userContent(item.group_name || '')}` : `<span>${uiText('Индивидуальное')}</span>`} · ${escapeHtml(price)}</div>
                <div class="student-finance-status">${escapeHtml(uiText(paymentStatusLabel(item)))}${allocated ? ` · ${escapeHtml(money(item.paid_amount))} ${uiText('из')} ${escapeHtml(price)}` : ''}${item.cancelled ? ` · ${uiText('Занятие отменено')}` : ''}</div>
                ${note ? `<p class="field-hint">${escapeHtml(uiText(note))}</p>` : ''}
                <div class="student-finance-actions">${item.cancelled && item.source === 'unpaid' ? '' : actions}</div>`;
            row.querySelectorAll('[data-finance-action]').forEach(button => {
                button.onclick = () => changeStudentLessonPayment(studentId, item, button.dataset.financeAction, row);
            });
            list.appendChild(row);
        });
        transactions.innerHTML = '';
        if (!(result.transactions || []).length) transactions.textContent = 'Сохранённых общих оплат пока нет.';
        (result.transactions || []).forEach(tx => {
            const row = document.createElement('article');
            row.className = 'student-finance-row';
            const allocations = (tx.allocations || []).map(a => `<li>${escapeHtml(a.date)} · ${escapeHtml(a.time || '')} · ${uiText(a.is_group ? 'Групповое' : 'Индивидуальное')} · ${escapeHtml(money(a.amount))}</li>`).join('');
            row.innerHTML = `<strong>${escapeHtml(money(tx.amount))} · ${uiText(tx.reversed_at ? 'Отменена' : 'Общая оплата')}</strong>
                <div>${escapeHtml(new Date(tx.created_at).toLocaleString(uiLocale()))} · № ${escapeHtml(tx.receipt_number || '')}</div>
                <ul>${allocations}</ul>
                ${tx.reversed_at ? `<small>${uiText('Отменена')} ${escapeHtml(new Date(tx.reversed_at).toLocaleString(uiLocale()))}</small>` : `<button type="button" class="secondary-btn">${threadIcon('restore')}Отменить весь платёж</button>`}`;
            const button = row.querySelector('button');
            if (button) button.onclick = async () => {
                if (!confirm(uiMessage`Отменить всю общую оплату ${money(tx.amount)}? Будут восстановлены ${tx.allocations.length} занятий и добавлена отрицательная запись в книгу.`)) return;
                button.disabled = true;
                try {
                    const response = await apiFetch('/reverse_student_payment', { method: 'POST', body: JSON.stringify({ student_id: studentId, transaction_id: tx.id }) });
                    const result = await response.json();
                    if (result.status !== 'ok') throw new Error(result.message || 'Не удалось отменить оплату');
                    await Promise.all([refreshScheduleOnly(), refreshOpenPaymentCard()]);
                } catch (error) {
                    alert(error.message || 'Ошибка отмены оплаты');
                } finally {
                    button.disabled = false;
                }
            };
            transactions.appendChild(row);
        });
    } catch (error) {
        if (requestId === studentPaymentsRequest) list.textContent = error.message || 'Не удалось загрузить оплаты.';
    }
}

async function changeStudentLessonPayment(studentId, item, action, row) {
    if (action === 'subscription') {
        const lesson = { ...item };
        if (item.lesson_type === 'group') lesson.group_members = [{ ...item, name: item.student }];
        state.selectedLesson = lesson;
        openSubscriptionForStudent(lesson, studentId);
        return;
    }
    const descriptions = { direct: 'Отметить занятие оплаченным', reverse: 'Снять оплату', free: 'Сделать занятие бесплатным', unfree: 'Отменить бесплатный статус' };
    if (!confirm(uiMessage`${uiText(descriptions[action])}: ${item.date} ${item.time || ''}?`)) return;
    row.querySelectorAll('button').forEach(button => { button.disabled = true; });
    try {
        const isState = action === 'free' || action === 'unfree';
        const response = await apiFetch(isState ? '/set_lesson_state' : '/mark_paid', {
            method: 'POST',
            body: JSON.stringify({ date: item.date, id: item.id, student_id: studentId,
                ...(isState ? { action } : { paid: action === 'direct', send_receipt: action === 'direct' && state.settings.default_send_receipts !== false }) })
        });
        const result = await response.json();
        if (result.status !== 'ok') throw new Error(result.message || 'Не удалось изменить оплату');
        await Promise.all([refreshScheduleOnly(), refreshOpenPaymentCard()]);
    } catch (error) {
        alert(error.message || 'Ошибка изменения оплаты');
    } finally {
        row.querySelectorAll('button').forEach(button => { button.disabled = false; });
    }
}

let inviteView = null;
let inviteRequest = 0;
let inviteBusy = false;
let pendingBindingRoles = new Map();
function pendingBindingLabel(roles = []) {
    const student = roles.includes('student');
    const parent = roles.includes('parent');
    if (student && parent) return botText('Подтвердить ученика и родителя', 'Confirm student and parent');
    return parent ? botText('Подтвердить родителя', 'Confirm parent') : botText('Подтвердить ученика', 'Confirm student');
}
function renderPendingBindingBadge() {
    const badge = document.getElementById('student-binding-alert');
    const count = [...pendingBindingRoles.values()].reduce((sum, roles) => sum + roles.length, 0);
    badge.classList.toggle('hidden', count === 0);
    const title = count ? botText('Есть новые привязки', 'New connections are waiting') : botText('Ученики', 'Students');
    document.getElementById('btn-students').title = title;
    document.getElementById('btn-students').setAttribute('aria-label', title);
    if (!document.getElementById('students-overlay').classList.contains('hidden'))
        renderStudentsList(document.getElementById('students-search').value);
}
async function refreshPendingBindingBadge() {
    try {
        const result = await inviteApi({action:'pending_summary'});
        pendingBindingRoles = new Map((result.pending || []).map(item => [String(item.student_id), item.roles || []]));
        if (result.contacts_updated) {
            const openStudentId = document.getElementById('student-card-overlay').classList.contains('hidden') ? '' : inviteStudentId();
            await loadStudents();
            if (openStudentId && state.students[openStudentId]) applyBoundTelegramContacts(openStudentId, state.students[openStudentId]);
        }
        renderPendingBindingBadge();
    } catch (_) {
        // A badge is advisory; normal calendar work must not fail with the personal bot.
    }
}
function inviteStudentId() {
    return document.getElementById('student-card-overlay').dataset.studentId;
}
function renderInviteLabels() {
    const labels = [
        ['student-bot-invites-title', 'Подключить ученика и родителя', 'Connect student and parent'],
        ['student-bot-invites-help', 'Одноразовая ссылка действует 48 часов. После запуска бота обновите привязки и подтвердите человека.',
            'The one-time link expires in 48 hours. After they start the bot, refresh connections and confirm their identity.'],
        ['student-bot-invite-student', 'Ссылка ученику', 'Student invitation'],
        ['student-bot-invite-parent', 'Ссылка родителю', 'Parent invitation'],
        ['student-bot-invite-copy-label', 'Копировать', 'Copy'],
        ['student-bot-invites-refresh', 'Обновить привязки', 'Refresh connections']
    ];
    for (const [id, ru, en] of labels) document.getElementById(id).textContent = botText(ru, en);
    const result = document.getElementById('student-bot-invite-result');
    const role = result.dataset.role;
    document.getElementById('student-bot-invite-result-label').textContent = role === 'parent'
        ? botText('Ссылка родителю готова', 'Parent link is ready')
        : role === 'student' ? botText('Ссылка ученику готова', 'Student link is ready')
            : botText('Готовая ссылка', 'Invitation link');
    document.getElementById('student-bot-invite-url').setAttribute('aria-label', botText('Ссылка-приглашение', 'Invitation link'));
    if (inviteView) renderInviteBindings();
}
function renderInviteBindings() {
    const list = document.getElementById('student-bot-bindings');
    list.replaceChildren();
    const view = inviteView;
    if (!view || view.studentId !== inviteStudentId()) return;
    document.getElementById('student-bot-invites-status').textContent = view.bot_username
        ? botText('Через ', 'Via ') + '@' + view.bot_username : botMessage('bot_required');
    for (const binding of view.bindings || []) {
        const row = document.createElement('div');
        row.className = 'student-bot-binding-card';
        const label = document.createElement('p');
        label.textContent = (binding.role === 'parent' ? botText('Родитель', 'Parent') : botText('Ученик', 'Student'))
            + ' · ' + binding.name + (binding.username ? ' · @' + binding.username : '')
            + ' · ID ' + binding.telegram_id + ' · '
            + (binding.state === 'active' ? botText('Подтверждён', 'Confirmed') : botText('Ожидает подтверждения', 'Awaiting confirmation'));
        row.append(label);
        for (const action of binding.state === 'active' ? ['revoke'] : ['approve', 'revoke']) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'secondary-btn';
            button.disabled = inviteBusy;
            button.textContent = action === 'approve' ? botText('Подтвердить', 'Confirm') : botText('Удалить привязку', 'Remove connection');
            button.onclick = () => runInviteAction(async studentId => {
                if (!confirm(action === 'approve'
                    ? (binding.role === 'student' ? botText('Подтвердить аккаунт ученика? Предыдущая привязка ученика будет заменена.', 'Confirm this student account? The previous student connection will be replaced.') : botText('Вы проверили, что это нужный человек?', 'Have you verified this is the intended person?'))
                    : botText('Удалить эту привязку? Карточка ученика сохранится.', 'Remove this connection? The student profile will be kept.'))) return;
                await inviteApi({action, student_id: studentId, binding_id: binding.id});
                await loadStudentBotBindings(studentId);
            });
            row.append(button);
        }
        list.append(row);
    }
    for (const id of ['student-bot-invite-student','student-bot-invite-parent']) {
        document.getElementById(id).disabled = inviteBusy || !view.bot_username;
    }
}
async function inviteApi(payload) {
    const response = await apiFetch('/personal_invites', {method:'POST', body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok || result.status !== 'ok') throw new Error(result.code || '');
    return result;
}
function applyBoundTelegramContacts(studentId, student) {
    if (!student || typeof student !== 'object') return;
    state.students[studentId] = student;
    if (inviteStudentId() !== String(studentId)) return;
    for (const [containerId, field] of [
        ['student-card-student-contacts','student_contacts'],
        ['student-card-parent-contacts','contacts']
    ]) {
        const current = getContacts(containerId);
        const telegram = String(student[field]?.tg || '').trim();
        if (!current.tg && telegram) renderContacts(containerId, {...current, tg:telegram});
    }
}
async function loadStudentBotBindings(studentId = inviteStudentId()) {
    const sequence = ++inviteRequest;
    inviteView = null;
    renderInviteLabels();
    document.getElementById('student-bot-bindings').replaceChildren();
    for (const id of ['student-bot-invite-student','student-bot-invite-parent']) document.getElementById(id).disabled = true;
    document.getElementById('student-bot-invites-status').textContent = botText('Загрузка…', 'Loading…');
    try {
        const result = await inviteApi({action:'list', student_id:studentId});
        if (sequence !== inviteRequest || studentId !== inviteStudentId()) return;
        inviteView = {...result, studentId};
        applyBoundTelegramContacts(studentId, result.student);
        renderInviteBindings();
        await refreshPendingBindingBadge();
    } catch (error) {
        if (sequence === inviteRequest && studentId === inviteStudentId())
            document.getElementById('student-bot-invites-status').textContent = botMessage(error.message);
    }
}
async function runInviteAction(action) {
    if (inviteBusy) return;
    const studentId = inviteStudentId();
    inviteBusy = true;
    document.querySelectorAll('#student-bot-invites button').forEach(b => { b.disabled = true; });
    try { await action(studentId); }
    catch (error) {
        if (studentId === inviteStudentId()) document.getElementById('student-bot-invites-status').textContent = botMessage(error.message);
    } finally {
        inviteBusy = false;
        document.querySelectorAll('#student-bot-invites button').forEach(b => { b.disabled = false; });
        if (!inviteView?.bot_username) {
            document.getElementById('student-bot-invite-student').disabled = true;
            document.getElementById('student-bot-invite-parent').disabled = true;
        }
    }
}
for (const role of ['student','parent']) {
    document.getElementById('student-bot-invite-' + role).onclick = () => runInviteAction(async studentId => {
        const result = await inviteApi({action:'create', student_id:studentId, role});
        if (studentId !== inviteStudentId()) return;
        document.getElementById('student-bot-invite-url').value = result.url;
        const resultCard = document.getElementById('student-bot-invite-result');
        resultCard.dataset.role = role;
        resultCard.hidden = false;
        renderInviteLabels();
    });
}
document.getElementById('student-bot-invites-refresh').onclick = () => loadStudentBotBindings();
document.getElementById('student-bot-invite-copy').onclick = async () => {
    const input = document.getElementById('student-bot-invite-url');
    try {
        await navigator.clipboard.writeText(input.value);
        document.getElementById('student-bot-invites-status').textContent = botText('Ссылка скопирована.', 'Link copied.');
    } catch {
        input.focus(); input.select();
        document.getElementById('student-bot-invites-status').textContent = botText('Скопируйте выделенную ссылку вручную.', 'Copy the selected link manually.');
    }
};

function openStudentCard(studentId) {
    if (!studentId || !state.students[studentId]) return alert('Карточка доступна после сохранения ученика.');
    document.getElementById('student-finances').open = false;
    document.querySelector('.student-payment-history').open = false;
    document.querySelector('#student-card-overlay .modal-body').scrollTop = 0;
    const info = getStudentInfo(studentId);
    document.getElementById('student-card-overlay').dataset.studentId = studentId;
    document.getElementById('btn-archive-student').textContent = info.archived ? 'Вернуть ученика из архива' : 'Убрать ученика в архив';
    const studentCardTitle = document.getElementById('student-card-title');
    studentCardTitle.textContent = info.name || uiText('Ученик');
    studentCardTitle.toggleAttribute('data-i18n-ignore', Boolean(info.name));
    document.getElementById('student-calendar-name').value = info.calendar_name || '';
    const endToggle = document.getElementById('student-parent-end');
    endToggle.checked = info.parent_lesson_end === true;
    document.getElementById('student-reminders').checked = info.student_reminders === true;
    endToggle.dataset.changed = '';
    endToggle.onchange = () => endToggle.dataset.changed = 'yes';
    document.getElementById('student-birthday').value = info.birthday || '';
    document.getElementById('student-note').value = info.note || '';
    document.getElementById('student-board-link').value = info.board_link || '';
    document.getElementById('student-zoom-link').value = info.zoom_link || '';
    setStudentStatus(info.status || 'active');
    renderContacts('student-card-student-contacts', info.student_contacts || {});
    document.getElementById('student-parent-name').value = info.parent_name || '';
    renderContacts('student-card-parent-contacts', info.contacts || {});
    document.getElementById('student-card-overlay').classList.remove('hidden');
    loadStudentLessonStats(studentId);
    loadStudentPayments(studentId);
    const studentBotInvites = document.getElementById('student-bot-invites');
    const hasPendingBinding = pendingBindingRoles.has(String(studentId));
    studentBotInvites.open = hasPendingBinding;
    studentBotInvites.closest('.ux-section')?.toggleAttribute('open', hasPendingBinding);
    if (hasPendingBinding) requestAnimationFrame(() => {
        if (inviteStudentId() !== String(studentId)) return;
        studentBotInvites.open = true;
        studentBotInvites.closest('.ux-section')?.setAttribute('open', '');
    });
    document.getElementById('student-bot-invite-result').hidden = true;
    delete document.getElementById('student-bot-invite-result').dataset.role;
    document.getElementById('student-bot-invite-url').value = '';
    loadStudentBotBindings(studentId);
}

document.getElementById('btn-close-student-card').onclick = () => document.getElementById('student-card-overlay').classList.add('hidden');
document.getElementById('btn-cancel-student-card').onclick = () => document.getElementById('student-card-overlay').classList.add('hidden');
document.getElementById('btn-save-student-card').onclick = async () => {
    const studentId = document.getElementById('student-card-overlay').dataset.studentId;
    const payload = {
        student_id: studentId,
        calendar_name: document.getElementById('student-calendar-name').value.trim(),
        parent_lesson_end: document.getElementById('student-parent-end').checked,
        student_reminders: document.getElementById('student-reminders').checked,
        birthday: document.getElementById('student-birthday').value,
        status: document.getElementById('student-card-overlay').dataset.studentStatus || 'active',
        note: document.getElementById('student-note').value.trim(),
        board_link: normalizeExternalUrl(document.getElementById('student-board-link').value),
        zoom_link: normalizeExternalUrl(document.getElementById('student-zoom-link').value),
        student_contacts: getContacts('student-card-student-contacts'),
        parent_name: document.getElementById('student-parent-name').value.trim(),
        contacts: getContacts('student-card-parent-contacts')
    };
    const response = await apiFetch('/update_student_profile', { method: 'POST', body: JSON.stringify(payload) });
    const result = await response.json();
    if (result.status !== 'ok') return alert(result.message || 'Ошибка сохранения ученика');
    state.students[studentId] = result.student;
    window.dispatchEvent(new CustomEvent('temli-saved', { detail: { overlay: 'student-card-overlay' } }));
    document.getElementById('student-card-overlay').classList.add('hidden');
    fillStudentsDropdown();
    renderCalendar();
    refreshWorkCenterBadge();
};

// Рабочий центр: внимание, окна, сводка и дни рождения
function shortWeekdayRu(dateString) {
    const d = new Date(`${dateString}T12:00:00`);
    const value = d.toLocaleDateString(uiLocale(), { weekday: 'short' }).replace(/\.$/, '');
    return value.charAt(0).toUpperCase() + value.slice(1);
}

function groupedWorkCenterWindows(windows) {
    const byDate = new Map();
    (windows || []).forEach(item => {
        if (!item?.date || !item?.from || !item?.to) return;
        if (!byDate.has(item.date)) byDate.set(item.date, []);
        byDate.get(item.date).push(`${item.from}–${item.to}`);
    });
    return Array.from(byDate, ([date, intervals]) => ({
        day: shortWeekdayRu(date),
        intervals
    }));
}
function workCenterWindowsCopyText(windows) {
    const grouped = groupedWorkCenterWindows(windows);
    if (!grouped.length) return '';
    return [localizeText('Свободные окна на этой неделе:'), ...grouped.map(item => `${item.day}: ${item.intervals.join('; ')}`)].join('\n');
}

async function copyTextToClipboard(text) {
    if (navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch (_error) { /* Старые WebView могут запрещать Clipboard API. */ }
    }
    const field = document.createElement('textarea');
    field.value = text;
    field.setAttribute('readonly', '');
    field.style.position = 'fixed';
    field.style.opacity = '0';
    field.style.pointerEvents = 'none';
    document.body.appendChild(field);
    field.select();
    field.setSelectionRange(0, field.value.length);
    const copied = document.execCommand('copy');
    field.remove();
    if (!copied) throw new Error('Не удалось скопировать текст');
}

let weekWindowsCopyTimer = null;
async function copyWeekWindows() {
    const button = document.getElementById('btn-copy-week-windows');
    const text = workCenterWindowsCopyText(state.workCenter?.windows);
    if (!button || !text) return;
    try {
        await copyTextToClipboard(text);
        setThreadButtonLabel(button, 'check', '');
        button.classList.add('is-copied');
        button.setAttribute('aria-label', 'Скопировано');
        button.title = 'Скопировано';
        tg.HapticFeedback?.impactOccurred('light');
        clearTimeout(weekWindowsCopyTimer);
        weekWindowsCopyTimer = setTimeout(() => {
            setThreadButtonLabel(button, 'copy', '');
            button.classList.remove('is-copied');
            button.setAttribute('aria-label', 'Скопировать окна недели');
            button.title = 'Скопировать окна недели';
        }, 1500);
    } catch (error) {
        alert(error.message || 'Не удалось скопировать текст');
    }
}
function money(value) {
    const formatted = window.TEMLI_I18N?.formatNumber(value) ?? Number(value || 0).toLocaleString(uiLocale());
    const symbol = window.TEMLI_I18N?.currencySymbol() || '₽';
    return `${formatted} ${symbol}`;
}
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
}

async function loadWorkCenter() {
    const response = await apiFetch('/get_work_center', {
        method: 'POST',
        body: JSON.stringify({ week_start: dateKey(state.currentMonday) })
    });
    const result = await response.json();
    if (result.status !== 'ok') throw new Error(result.message || 'Не удалось загрузить помощник');
    state.workCenter = result;
    renderWorkCenter();
    return result;
}

function normalizeExternalUrl(url) {
    const value = String(url || '').trim();
    if (!value) return '';
    if (/^https?:\/\//i.test(value)) return value;
    return `https://${value}`;
}

function openExternalLink(url) {
    const value = normalizeExternalUrl(url);
    if (!value) return alert('Ссылка не указана');
    try { tg.openLink(value); } catch (e) { window.open(value, '_blank', 'noopener,noreferrer'); }
}

function isDesktopApp() {
    return ['tdesktop', 'macos', 'unigram'].includes(tg.platform) ||
        ((!tg.platform || tg.platform === 'unknown' || tg.platform.startsWith('web')) &&
         !/Android|iPhone|iPad|iPod/i.test(navigator.userAgent) && navigator.maxTouchPoints < 2);
}

const fullscreenButton = document.getElementById('btn-fullscreen');
const telegramFullscreen = isDesktopApp() && typeof tg.requestFullscreen === 'function' &&
    typeof tg.exitFullscreen === 'function' && tg.isVersionAtLeast?.('8.0');
function updateFullscreenButton() {
    fullscreenButton.classList.toggle('hidden', !isDesktopApp() || !(telegramFullscreen || document.fullscreenEnabled));
    const active = telegramFullscreen ? tg.isFullscreen : !!document.fullscreenElement;
    fullscreenButton.title = active ? 'Выйти из полного экрана' : 'На весь экран';
    fullscreenButton.setAttribute('aria-label', fullscreenButton.title);
    fullscreenButton.setAttribute('aria-pressed', String(!!active));
}
fullscreenButton.onclick = async () => {
    try {
        if (telegramFullscreen) {
            if (tg.isFullscreen) tg.exitFullscreen(); else tg.requestFullscreen();
        } else if (document.fullscreenElement) await document.exitFullscreen();
        else await document.documentElement.requestFullscreen();
    } catch (error) { alert('Этот клиент не разрешил полный экран.'); }
    updateFullscreenButton();
};
function handleFullscreenLayoutChange() {
    updateFullscreenButton();
    requestAnimationFrame(syncCalendarHeaderScrollbar);
}
document.addEventListener('fullscreenchange', handleFullscreenLayoutChange);
tg.onEvent?.('fullscreenChanged', handleFullscreenLayoutChange);
tg.onEvent?.('fullscreenFailed', () => alert('Полный экран недоступен в этом клиенте Telegram.'));
updateFullscreenButton();

function renderTopLesson() {
    const data = state.workCenter || {};
    const current = data.current_lesson || null;
    const next = data.next_lesson || null;
    const summary = document.getElementById('top-next-lesson-summary');
    const details = document.getElementById('top-next-lesson-details');
    const notificationPreview = document.getElementById('top-notification-preview');
    if (!summary || !details) return;

    const topButton = document.getElementById('top-next-lesson');
    const active = current || next;
    topButton.dataset.lessonStatus = current ? 'current' : next ? 'next' : 'empty';
    // The compact pill shows one person; the expanded panel keeps both lessons.
    if (current) {
        summary.innerHTML = `<span class="top-live-node" aria-hidden="true"></span><span class="top-summary-text">${userContentOr(current.student, 'Ученик')}</span><span class="top-summary-time">${userContent(current.time || '')}</span>`;
    } else if (next) {
        summary.innerHTML = `<span class="top-upcoming-node" aria-hidden="true">»</span><span class="top-summary-text">${userContentOr(next.student, 'Ученик')}</span><span class="top-summary-time">${userContent(next.time || '')}</span>`;
    } else {
        summary.textContent = uiText('Ближайших занятий нет');
    }
    const accessibleSummary = active
        ? `${uiText(current ? 'Сейчас' : 'Следующее занятие')}: ${active.student || uiText('Ученик')} ${active.time || ''}`
        : uiText('Ближайших занятий нет');
    topButton.setAttribute('aria-label', accessibleSummary);
    topButton.title = accessibleSummary;
    topButton.setAttribute('aria-expanded', String(!details.classList.contains('hidden')));
    notificationPreview.classList.toggle('hidden', !(current || next));

    const items = [];
    if (current) items.push({ label: 'Сейчас', item: current });
    if (next) items.push({ label: 'Следующее занятие', item: next });
    details.innerHTML = items.map(({label, item}, i) => {
        const buttons = [
            item.board_link ? `<button type="button" class="next-link-btn top-board-btn" data-top-link="${i}-board">${threadIcon('board')}Доска</button>` : '',
            `<button type="button" class="next-link-btn future-notification-btn" data-top-teacher-delay="${i}">${threadIcon('delay-teacher')}Я задержусь</button>`,
            `<button type="button" class="next-link-btn future-notification-btn" data-top-student-delay="${i}">${threadIcon('delay-student')}Ученик задерживается</button>`
        ].filter(Boolean).join('');
        return `<div class="top-next-detail-row"><div class="top-next-detail-copy"><small>${label}</small><strong>${userContentOr(item.student, 'Ученик')}</strong><span>${userContent(item.time || '')}</span></div>${buttons ? `<div class="next-lesson-actions">${buttons}</div>` : ''}</div>`;
    }).join('') || '<div class="hub-empty">Ближайших занятий нет.</div>';
    items.forEach(({item}, i) => {
        details.querySelector(`[data-top-link="${i}-board"]`)?.addEventListener('click', e => { e.stopPropagation(); openExternalLink(item.board_link); });
        details.querySelector(`[data-top-teacher-delay="${i}"]`)?.addEventListener('click', () => openPersonalNotification(item, true));
        details.querySelector(`[data-top-student-delay="${i}"]`)?.addEventListener('click', () => openPersonalNotification(item, false));
    });
}
document.getElementById('btn-top-teacher-delay').onclick = () => openPersonalNotification(state.workCenter?.current_lesson || state.workCenter?.next_lesson, true);
document.getElementById('btn-top-student-delay').onclick = () => openPersonalNotification(state.workCenter?.current_lesson || state.workCenter?.next_lesson, false);
setInterval(() => { if (!document.hidden) { refreshWorkCenterBadge(); refreshPendingBindingBadge(); } }, 60000);

function renderWorkCenter() {
    const data = state.workCenter || { debts: [], windows: [], birthdays: [], summary: {} };
    renderTopLesson();
    const debts = Array.isArray(data.debts) ? data.debts : [];
    const debtAlert = document.getElementById('work-center-debt-alert');
    if (debtAlert) {
        debtAlert.classList.toggle('hidden', debts.length === 0);
        debtAlert.setAttribute('aria-hidden', debts.length === 0 ? 'true' : 'false');
    }
    document.getElementById('hub-debts-count').textContent = debts.length;
    document.getElementById('hub-debts').innerHTML = debts.length
        ? `<div class="hub-debt-total"><span>Всего к оплате</span><strong>${money(data.debt_total || 0)}</strong></div>` + debts.map(item => `<div class="hub-item"><strong>${userContentOr(item.name, 'Ученик')}</strong><span>${item.unpaid_count || 0} ${uiText('зан.')} · ${money(item.amount || 0)}</span></div>`).join('')
        : '<div class="hub-empty">Просроченных неоплаченных занятий нет.</div>';

    const groupedWindows = groupedWorkCenterWindows(data.windows);
    document.getElementById('hub-windows-list').innerHTML = groupedWindows.length
        ? groupedWindows.map(item => `<div class="hub-item"><strong>${escapeHtml(item.day)}</strong><span>${item.intervals.map(escapeHtml).join('; ')}</span></div>`).join('')
        : '<div class="hub-empty">Свободных окон от 60 минут нет.</div>';
    document.getElementById('hub-windows-copy-toolbar').classList.toggle('hidden', groupedWindows.length === 0);

    const summaryData = data.summary || {};
    document.getElementById('hub-summary').innerHTML = `
        <div class="summary-grid">
            <div><small>Занятий</small><strong>${summaryData.lessons || 0}</strong></div>
            <div><small>Оплачено</small><strong>${summaryData.paid || 0}</strong></div>
            <div><small>План</small><strong>${money(summaryData.planned_sum)}</strong></div>
            <div><small>Получено</small><strong>${money(summaryData.paid_sum)}</strong></div>
        </div>`;

    document.getElementById('hub-birthdays').innerHTML = (data.birthdays || []).length
        ? data.birthdays.map(item => `<div class="hub-item"><strong>${userContent(item.name)}</strong><span>${item.days === 0 ? uiText('сегодня') : `${shortDateRu(item.date)} · ${uiText('через')} ${item.days} ${uiText('дн.')}`}</span></div>`).join('')
        : `<div class="hub-empty">${uiText('В ближайшие 30 дней дней рождения нет.')}</div>`;
}

async function refreshWorkCenterBadge() {
    try { await loadWorkCenter(); } catch (e) { console.warn('Помощник недоступен:', e); }
}

document.getElementById('btn-work-center').onclick = async () => {
    document.getElementById('work-center-overlay').classList.remove('hidden');
    document.querySelectorAll('.hub-panel').forEach(el => el.classList.add('hidden'));
    try { await loadWorkCenter(); } catch (e) { alert(e.message); }
};
document.getElementById('btn-close-work-center').onclick = () => document.getElementById('work-center-overlay').classList.add('hidden');
document.getElementById('btn-close-work-center-bottom').onclick = () => document.getElementById('work-center-overlay').classList.add('hidden');
document.getElementById('btn-copy-week-windows').onclick = copyWeekWindows;
document.querySelectorAll('.hub-row').forEach(row => {
    row.onclick = () => {
        const target = document.getElementById(`hub-${row.dataset.hubSection}`);
        const wasHidden = target.classList.contains('hidden');
        document.querySelectorAll('.hub-panel').forEach(panel => panel.classList.add('hidden'));
        if (wasHidden) target.classList.remove('hidden');
    };
});

// Плавный pinch-зум + живое перелистывание недель одним пальцем
let pinchStartDistance = null;
let pinchStartHeight = hourHeight;
let pinchAnchorHours = null;
let pinchAnchorLocalY = null;
let pendingPinchHeight = null;
let pinchFrame = null;
let swipeStartX = null;
let swipeStartY = null;
let swipeStartAt = 0;
let swipeTracking = false;
let swipeHorizontal = false;
let weekDragOffset = 0;
const calendarContainer = document.getElementById('calendar-container');

function applyHourHeightSmooth(nextHeight) {
    hourHeight = Math.max(MIN_HOUR_HEIGHT, Math.min(MAX_HOUR_HEIGHT, nextHeight));
    document.documentElement.style.setProperty('--hour-height', `${hourHeight}px`);

    document.querySelectorAll('#events-layer .event-card').forEach(card => {
        const startMinutes = Number(card.dataset.startMinutes || 0);
        const duration = Number(card.dataset.durationMinutes || 60);
        const cardHeight = Math.max(18, duration * hourHeight / 60 - 2);
        card.style.top = `${startMinutes * hourHeight / 60}px`;
        card.style.height = `${cardHeight}px`;
        card.classList.remove('event-card-compact', 'event-card-medium', 'event-card-tall');
        if (cardHeight < 34) card.classList.add('event-card-compact');
        else if (cardHeight < 54) card.classList.add('event-card-medium');
        else card.classList.add('event-card-tall');
    });

    if (pinchAnchorHours !== null && pinchAnchorLocalY !== null) {
        calendarContainer.scrollTop = Math.max(0, pinchAnchorHours * hourHeight - pinchAnchorLocalY);
    }
    updateCurrentTimeLine();
}

function schedulePinchHeight(nextHeight) {
    pendingPinchHeight = nextHeight;
    if (pinchFrame !== null) return;
    pinchFrame = requestAnimationFrame(() => {
        pinchFrame = null;
        if (pendingPinchHeight !== null) applyHourHeightSmooth(pendingPinchHeight);
        pendingPinchHeight = null;
    });
}

function finishPinch() {
    if (pinchFrame !== null) {
        cancelAnimationFrame(pinchFrame);
        pinchFrame = null;
    }
    if (pendingPinchHeight !== null) {
        applyHourHeightSmooth(pendingPinchHeight);
        pendingPinchHeight = null;
    }
    pinchStartDistance = null;
    pinchAnchorHours = null;
    pinchAnchorLocalY = null;
}

calendarContainer.addEventListener('touchstart', event => {
    if (event.touches.length === 2) {
        swipeTracking = false;
        swipeHorizontal = false;
        swipeStartX = null;
        const a = event.touches[0];
        const b = event.touches[1];
        const dx = a.clientX - b.clientX;
        const dy = a.clientY - b.clientY;
        pinchStartDistance = Math.hypot(dx, dy);
        pinchStartHeight = hourHeight;
        const rect = calendarContainer.getBoundingClientRect();
        const midpointY = (a.clientY + b.clientY) / 2;
        pinchAnchorLocalY = midpointY - rect.top;
        pinchAnchorHours = (calendarContainer.scrollTop + pinchAnchorLocalY) / pinchStartHeight;
        return;
    }
    if (event.touches.length === 1 && !state.isMoving && !weekTransitioning && !event.target.closest('.event-card')) {
        finishPinch();
        swipeStartX = event.touches[0].clientX;
        swipeStartY = event.touches[0].clientY;
        swipeStartAt = performance.now();
        swipeTracking = true;
        swipeHorizontal = false;
    }
}, { passive: true });

calendarContainer.addEventListener('touchmove', event => {
    if (event.touches.length === 2 && pinchStartDistance !== null) {
        event.preventDefault();
        const a = event.touches[0];
        const b = event.touches[1];
        const distance = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
        const ratio = distance / Math.max(1, pinchStartDistance);
        // Нелинейная чувствительность: небольшое движение пальцев уже заметно, но без скачков.
        const nextHeight = pinchStartHeight * Math.pow(ratio, 0.88);
        schedulePinchHeight(nextHeight);
        return;
    }
    if (event.touches.length === 1 && swipeTracking && swipeStartX !== null) {
        const dx = event.touches[0].clientX - swipeStartX;
        const dy = event.touches[0].clientY - swipeStartY;
        if (!swipeHorizontal && Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy) * 1.15) swipeHorizontal = true;
        if (swipeHorizontal) {
            event.preventDefault();
            setWeekDragOffset(dx);
        }
    }
}, { passive: false });

calendarContainer.addEventListener('touchend', event => {
    if (event.touches.length < 2 && pinchStartDistance !== null) finishPinch();
    if (!swipeTracking || swipeStartX === null || !event.changedTouches.length) return;
    const dx = event.changedTouches[0].clientX - swipeStartX;
    const dy = event.changedTouches[0].clientY - swipeStartY;
    const elapsed = Math.max(1, performance.now() - swipeStartAt);
    swipeTracking = false;
    swipeStartX = null;
    swipeStartY = null;
    const fastSwipe = Math.abs(dx) >= 30 && Math.abs(dx) / elapsed >= 0.45;
    const shouldShift = swipeHorizontal && (Math.abs(dx) >= 58 || fastSwipe) && Math.abs(dx) > Math.abs(dy) * 1.18;
    swipeHorizontal = false;
    if (shouldShift) {
        haptic('light');
        shiftWeek(dx < 0 ? 7 : -7, { fromSwipe: true });
    } else {
        animateBackFromWeekDrag();
    }
});

calendarContainer.addEventListener('touchcancel', () => {
    finishPinch();
    swipeTracking = false;
    swipeHorizontal = false;
    swipeStartX = null;
    swipeStartY = null;
    swipeStartAt = 0;
    animateBackFromWeekDrag();
});

window.addEventListener('resize', () => requestAnimationFrame(() => renderCalendar()));
if (window.ResizeObserver) {
    const calendarHeaderObserver = new ResizeObserver(syncCalendarHeaderScrollbar);
    calendarHeaderObserver.observe(calendarContainer);
    const calendarGrid = calendarContainer.querySelector(':scope > .calendar-grid');
    if (calendarGrid) calendarHeaderObserver.observe(calendarGrid);
}
requestAnimationFrame(syncCalendarHeaderScrollbar);
fetchData();

// v30.7: единый раздел учеников и оплата произвольной суммой
function renderStudentsList(filter = '') {
    const box = document.getElementById('students-list');
    if (!box) return;
    const q = String(filter || '').trim().toLocaleLowerCase('ru');
    const rows = visibleStudentEntries().filter(([id, raw]) => {
        const info = typeof raw === 'string' ? { name: raw } : (raw || {});
        return !!info.archived === document.getElementById('students-show-archived').checked
            && (!q || String(info.name || id).toLocaleLowerCase('ru').includes(q));
    });
    box.innerHTML = '';
    if (!rows.length) {
        box.innerHTML = '<div class="hub-empty">Ученики не найдены.</div>';
        return;
    }
    rows.forEach(([id, raw]) => {
        const info = typeof raw === 'string' ? { name: raw } : (raw || {});
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'student-list-row';
        const pendingRoles = pendingBindingRoles.get(String(id)) || [];
        const pending = pendingRoles.length
            ? `<small class="student-binding-pending">${threadIcon('message')}${escapeHtml(pendingBindingLabel(pendingRoles))}</small>` : '';
        btn.innerHTML = `<span class="student-list-main"><strong>${userContent(info.name || id)}</strong>${pending}</span>${threadIcon('chevron-right', 'row-chevron')}`;
        btn.onclick = () => {
            document.getElementById('students-overlay').classList.add('hidden');
            openStudentCard(id);
        };
        box.appendChild(btn);
    });
}

document.getElementById('btn-students').onclick = () => {
    document.getElementById('students-show-archived').checked = false;
    document.getElementById('students-search').value = '';
    renderStudentsList('');
    document.getElementById('students-overlay').classList.remove('hidden');
    refreshPendingBindingBadge();
};
document.getElementById('students-search').addEventListener('input', e => renderStudentsList(e.target.value));
document.getElementById('students-show-archived').onchange = () => renderStudentsList(document.getElementById('students-search').value);
document.getElementById('btn-archive-student').onclick = async () => {
    const studentId = document.getElementById('student-card-overlay').dataset.studentId;
    const archived = !getStudentInfo(studentId).archived;
    if (!confirm(archived ? 'Убрать ученика из общего списка? История, оплаты и уже созданные занятия сохранятся. Ученика можно вернуть из архива.' : 'Вернуть ученика в общий список?')) return;
    const button = document.getElementById('btn-archive-student');
    button.disabled = true;
    try {
        const response = await apiFetch('/set_student_archived', { method: 'POST', body: JSON.stringify({ student_id: studentId, archived }) });
        const result = await response.json();
        if (result.status !== 'ok') throw new Error(result.message || 'Не удалось изменить архив');
        state.students[studentId] = result.student;
        fillStudentsDropdown();
        document.getElementById('student-card-overlay').classList.add('hidden');
        document.getElementById('btn-students').click();
    } catch (error) {
        alert(error.message || 'Не удалось изменить архив');
    } finally { button.disabled = false; }
};
document.getElementById('btn-delete-student').onclick = async () => {
    const studentId = document.getElementById('student-card-overlay').dataset.studentId;
    const studentName = String(getStudentInfo(studentId).name || '').trim();
    const typedName = prompt(uiMessage`Удалить ученика «${studentName}»? Профиль и все будущие занятия будут удалены без возможности восстановления. Прошедшие занятия, оплаты, чеки и книга учёта сохранятся.\n\nДля подтверждения введите имя ученика:`);
    if (typedName === null) return;
    if (typedName.trim() !== studentName) return alert('Имя не совпало. Удаление отменено.');
    const button = document.getElementById('btn-delete-student');
    button.disabled = true;
    try {
        const response = await apiFetch('/delete_student', { method: 'POST', body: JSON.stringify({ student_id: studentId, confirm_name: typedName.trim() }) });
        const result = await response.json();
        if (result.status !== 'ok') throw new Error(result.message || 'Не удалось удалить ученика');
        delete state.students[studentId];
        fillStudentsDropdown();
        document.getElementById('student-card-overlay').classList.add('hidden');
        await refreshScheduleOnly();
        document.getElementById('btn-students').click();
        alert('Ученик и будущие занятия удалены. Книга учёта и финансовая история сохранены.');
    } catch (error) {
        alert(error.message || 'Не удалось удалить ученика');
    } finally { button.disabled = false; }
};
document.getElementById('btn-close-students').onclick = () => document.getElementById('students-overlay').classList.add('hidden');
document.getElementById('btn-close-students-bottom').onclick = () => document.getElementById('students-overlay').classList.add('hidden');

let selectedPaymentQuote = null;
let paymentOptionsRequest = 0;
document.getElementById('btn-student-payment').onclick = async () => {
    const studentId = document.getElementById('student-card-overlay').dataset.studentId;
    if (!studentId) return;
    const info = getStudentInfo(studentId);
    document.getElementById('student-payment-overlay').dataset.studentId = studentId;
    document.getElementById('student-payment-title').innerHTML = `<span>${uiText('Оплата')}</span> · ${userContentOr(info.name, 'Ученик')}`;
    document.getElementById('student-payment-amount').value = '';
    document.getElementById('student-payment-send-receipt').checked = state.settings.default_send_receipts !== false;
    document.getElementById('student-payment-overlay').classList.remove('hidden');
    selectedPaymentQuote = null;
    const requestId = ++paymentOptionsRequest;
    const options = document.getElementById('student-payment-options');
    const explanation = document.getElementById('student-payment-explanation');
    const amountInput = document.getElementById('student-payment-amount');
    const applyButton = document.getElementById('btn-apply-student-payment');
    amountInput.closest('.form-group').classList.add('hidden');
    applyButton.classList.add('hidden');
    options.textContent = 'Рассчитываем варианты…';
    explanation.textContent = uiText('Сначала старые долги, затем будущие занятия. Учитываются индивидуальные и групповые занятия по их стоимости.');
    try {
        const response = await apiFetch('/get_student_payment_options', { method: 'POST', body: JSON.stringify({ student_id: studentId }) });
        const result = await response.json();
        if (requestId !== paymentOptionsRequest) return;
        if (result.status !== 'ok') throw new Error(result.message);
        options.innerHTML = '';
        (result.options || []).forEach(quote => {
            const block = document.createElement('div');
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'primary-btn';
            button.textContent = `${quote.count} ${uiText(quote.count === 4 ? 'занятия' : 'занятий')} — ${money(quote.amount)}`;
            button.onclick = () => {
                if (applyButton.disabled) return;
                selectedPaymentQuote = quote;
                amountInput.value = String(quote.amount);
                document.getElementById('btn-apply-student-payment').click();
            };
            const details = document.createElement('details');
            details.innerHTML = '<summary>Какие занятия</summary><ul>' + (quote.lessons || []).map(lesson =>
                `<li>${escapeHtml(lesson.date)} · ${escapeHtml(lesson.time)} · ${uiText(lesson.is_group ? 'Группа' : 'Индивидуальное')} · ${escapeHtml(money(lesson.amount))}</li>`).join('') + '</ul>';
            block.append(button, details);
            options.appendChild(block);
        });
        if (!(result.options || []).length) explanation.textContent = uiText('Пока нет четырёх неоплаченных занятий с указанной ценой. Можно внести другую сумму — начиная со старых долгов.');
    } catch (error) {
        if (requestId !== paymentOptionsRequest) return;
        options.innerHTML = '';
        explanation.textContent = 'Варианты сейчас недоступны. Можно внести другую сумму.';
    }
    const custom = document.createElement('button');
    custom.type = 'button';
    custom.className = 'secondary-btn';
    custom.textContent = 'Другая сумма';
    custom.onclick = () => {
        selectedPaymentQuote = null;
        amountInput.value = '';
        amountInput.closest('.form-group').classList.remove('hidden');
        applyButton.classList.remove('hidden');
        explanation.textContent = uiText('Сначала старые долги, затем будущие занятия. Учитываются индивидуальные и групповые занятия по их стоимости.');
        amountInput.focus();
    };
    options.appendChild(custom);
};
document.getElementById('btn-close-student-payment').onclick =
document.getElementById('btn-cancel-student-payment').onclick = () => document.getElementById('student-payment-overlay').classList.add('hidden');
document.getElementById('btn-apply-student-payment').onclick = async () => {
    const overlay = document.getElementById('student-payment-overlay');
    const studentId = overlay.dataset.studentId;
    const amount = Number(document.getElementById('student-payment-amount').value || 0);
    if (!(amount > 0)) return alert('Укажите сумму оплаты.');
    const button = document.getElementById('btn-apply-student-payment');
    if (button.disabled) return;
    const quote = selectedPaymentQuote;
    const paymentPayload = {
        student_id: studentId,
        amount,
        ...(quote ? { quick_count: quote.count, preview_token: quote.preview_token } : {}),
        send_receipt: document.getElementById('student-payment-send-receipt').checked
    };
    const requestId = pendingStudentPayment(paymentPayload);
    button.disabled = true;
    document.querySelectorAll('#student-payment-options button').forEach(item => { item.disabled = true; });
    try {
        const response = await apiFetch('/apply_student_payment', {
            method: 'POST',
            body: JSON.stringify({ ...paymentPayload, request_id: requestId })
        });
        const result = await response.json();
        if (result.status !== 'ok') {
            clearPendingStudentPayment(requestId);
            return alert(result.message || 'Ошибка оплаты');
        }
        clearPendingStudentPayment(requestId);
        overlay.classList.add('hidden');
        await Promise.all([refreshScheduleOnly(), loadStudentLessonStats(studentId)]);
        await loadStudentPayments(studentId);
        const restText = Number(result.unallocated || 0) > 0 ? uiMessage` Не распределено: ${money(result.unallocated)}.` : '';
        alert(uiMessage`Оплата распределена.${restText} ${result.receipt_message || ''}`.trim());
    } catch (error) {
        alert('Не удалось получить результат оплаты. Перед повторной оплатой проверьте историю ученика.');
    } finally {
        button.disabled = false;
        document.querySelectorAll('#student-payment-options button').forEach(item => { item.disabled = false; });
    }
};

document.getElementById('lesson-repeat').addEventListener('change', e => {
    const year = e.target.value === 'year';
    document.getElementById('repeat-until-wrap').classList.toggle('hidden', !year);
    const repeatUntil = document.getElementById('repeat-until');
    const lessonDate = document.getElementById('lesson-date').value;
    if (year) {
        repeatUntil.min = lessonDate;
        repeatUntil.max = dateKey(new Date(`${lessonDate}T12:00:00`).getTime() + 370 * 24 * 60 * 60 * 1000);
        if (!repeatUntil.value) repeatUntil.value = schoolYearEndFor(lessonDate);
    }
});

document.getElementById('top-next-lesson').onclick = () => {
    const hidden = document.getElementById('top-next-lesson-details').classList.toggle('hidden');
    document.getElementById('top-next-lesson').setAttribute('aria-expanded', String(!hidden));
};
