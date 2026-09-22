/* TEMLI daily workflow. Drafts remain in memory and are never sent or persisted automatically. */
function uxText(ru, en) { return uiLocale().startsWith('en') ? en : ru; }
function uxButton(ru, en, action, className = 'secondary-btn') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.dataset.uxRu = ru;
    button.dataset.uxEn = en;
    button.textContent = uxText(ru, en);
    button.onclick = action;
    return button;
}
function uxMessage(message) {
    if (document.getElementById('ux-undo')?.hidden === false) return;
    const box = document.getElementById('ux-feedback');
    box.textContent = message;
    box.hidden = false;
    clearTimeout(uxMessage.timer);
    uxMessage.timer = setTimeout(() => { box.hidden = true; }, 4500);
}
async function shiftCalendarDay(direction) {
    if (weekTransitioning) return;
    weekTransitioning = true;
    const next = new Date(calendarDay);
    next.setDate(next.getDate() + direction);
    const monday = getMonday(next);
    const originalDay = dateKey(calendarDay);
    try {
        const data = await fetchWeekSchedule(monday, { allowCached: true });
        if (dateKey(calendarDay) !== originalDay) return;
        calendarDay = next;
        state.currentMonday = monday;
        state.schedule = data.schedule;
        autoFitWeekPending = false;
        clearWeekDragStyles();
        renderCalendar();
        scheduleWorkCenterRefresh();
    } catch (_) { animateBackFromWeekDrag(); }
    finally { weekTransitioning = false; }
}
function setCalendarView(view) {
    if (weekTransitioning || !['day', 'week'].includes(view)) return;
    calendarView = view;
    if (dateKey(getMonday(calendarDay)) !== dateKey(state.currentMonday)) calendarDay = new Date(state.currentMonday);
    try { localStorage.setItem('temli-calendar-view', view); } catch (_) {}
    renderCalendar();
}
async function revealCalendarLesson(lesson) {
    if (!lesson?.date || weekTransitioning) return;
    weekTransitioning = true;
    try {
        const date = new Date(`${lesson.date}T12:00:00`);
        const monday = getMonday(date);
        const data = await fetchWeekSchedule(monday,{allowCached:true});
        calendarDay = date;
        state.currentMonday = monday;
        state.schedule = data.schedule;
        autoFitWeekPending = false;
        document.getElementById('top-next-lesson-details').classList.add('hidden');
        renderCalendar();
        document.getElementById('calendar-container').scrollTop = Math.max(0,workingTimeMinutes(lesson.time,0)*hourHeight/60 - 36);
    } catch (_) { /* The network panel provides retry without losing the current view. */ }
    finally { weekTransitioning = false; }
}
function uxSection(labelRu, labelEn, nodes, before) {
    const section = document.createElement('details');
    section.className = 'ux-section';
    const summary = document.createElement('summary');
    summary.dataset.uxRu = labelRu;
    summary.dataset.uxEn = labelEn;
    summary.textContent = uxText(labelRu, labelEn);
    section.append(summary);
    before.before(section);
    nodes.filter(Boolean).forEach(node => section.append(node));
    return section;
}
function uxEndTime(time, duration) {
    const minutes = workingTimeMinutes(time, 0) + Number(duration || 60);
    return `${String(Math.floor(minutes / 60) % 24).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
}
(() => {
    const byId = id => document.getElementById(id);
    const feedback = document.createElement('div');
    feedback.id = 'ux-feedback';
    feedback.hidden = true;
    feedback.setAttribute('role', 'status');
    feedback.setAttribute('data-i18n-ignore', '');
    document.body.append(feedback);
    const undo = document.createElement('div');
    undo.id = 'ux-undo';
    undo.hidden = true;
    undo.setAttribute('data-i18n-ignore','');
    const undoLabel = document.createElement('span');
    undoLabel.setAttribute('role','status');
    const undoButton = uxButton('Отменить','Undo',null,'ux-text-button');
    undo.append(undoLabel,undoButton);
    document.body.append(undo);
    let undoTimer;
    window.addEventListener('temli-calendar-changed', event => {
        const {token,action} = event.detail;
        if (!token) return;
        clearTimeout(undoTimer);
        feedback.hidden = true;
        undo.hidden = false;
        undoButton.disabled = false;
        undoLabel.dataset.uxRu = action === 'delete' ? 'Удалено' : action === 'copy' ? 'Копия добавлена' : 'Перенесено';
        undoLabel.dataset.uxEn = action === 'delete' ? 'Deleted' : action === 'copy' ? 'Copy added' : 'Rescheduled';
        undoLabel.textContent = uxText(undoLabel.dataset.uxRu,undoLabel.dataset.uxEn);
        undoButton.onclick = async () => {
            if (undoButton.disabled) return;
            undoButton.disabled = true;
            clearTimeout(undoTimer);
            try {
                const response = await apiFetch('/undo_calendar_action',{method:'POST',body:JSON.stringify({undo_token:token})});
                const result = await response.json();
                undo.hidden = true;
                if (!response.ok || result.status !== 'ok') {
                    uxMessage(uxText('Отмена недоступна: время истекло или расписание изменилось.', 'Undo is unavailable: time expired or the schedule changed.'));
                } else {
                    uxMessage(uxText('Действие отменено','Action undone'));
                    await refreshScheduleOnly();
                }
            } catch (_) {
                undo.hidden = true;
                uxMessage(uxText('Не удалось подтвердить отмену. Обновите расписание и проверьте результат.', 'Could not confirm undo. Reload the schedule and check the result.'));
            }
        };
        undoTimer = setTimeout(() => undo.hidden = true,20000);
    });

    const toolbar = document.createElement('div');
    toolbar.className = 'calendar-view-toolbar';
    const primaryCalendarActions = document.createElement('div');
    primaryCalendarActions.className = 'calendar-primary-actions';
    const stepNavigation = document.createElement('div');
    stepNavigation.className = 'calendar-step-navigation';
    stepNavigation.setAttribute('role', 'group');
    const modes = document.createElement('div');
    modes.className = 'calendar-view-switch';
    modes.setAttribute('role', 'group');
    const day = uxButton('День', 'Day', () => setCalendarView('day'), '');
    const week = uxButton('Неделя', 'Week', () => setCalendarView('week'), '');
    day.id = 'btn-view-day'; week.id = 'btn-view-week';
    modes.append(day, week);
    const todayButton = byId('btn-today');
    const datePickerButton = byId('btn-date-picker');
    const previousButton = byId('btn-prev-week');
    const nextButton = byId('btn-next-week');
    const headerTop = document.querySelector('.header-top');
    const headerContextActions = document.createElement('div');
    headerContextActions.className = 'header-context-actions';
    headerContextActions.append(byId('btn-students'));
    headerTop.prepend(headerContextActions);
    byId('btn-app-settings').before(byId('btn-work-center'));
    // Keep the date actions in one uninterrupted sequence: previous, Today,
    // date picker, next. This makes the paging target clear and prevents the
    // view switch from leaving a misleading empty gap on narrow screens.
    primaryCalendarActions.append(todayButton, datePickerButton);
    stepNavigation.append(previousButton, primaryCalendarActions, nextButton);
    toolbar.append(modes, stepNavigation);
    document.querySelector('.week-days-container').before(toolbar);
    toolbar.after(byId('move-hint'));

    const intro = document.createElement('div');
    intro.id = 'calendar-first-step';
    intro.hidden = true;
    intro.setAttribute('data-i18n-ignore', '');
    const introText = document.createElement('p');
    const addFirst = uxButton('Добавить занятие', 'Add lesson', () => {
        const date = onboardingSuggestedLesson();
        openAddModal(dateKey(date), `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`);
        byId('lesson-repeat').value = 'no';
        byId('repeat-until-wrap').classList.add('hidden');
        if (!visibleStudentEntries().length) {
            byId('student-select').value = 'manual';
            byId('student-select').dispatchEvent(new Event('change', {bubbles: true}));
        }
    }, 'primary-btn');
    addFirst.id = 'btn-first-lesson';
    const firstHelp = uxButton('Краткая справка', 'Quick help', () => openHelp(false), 'ux-text-button');
    firstHelp.id = 'btn-first-help';
    intro.append(introText, addFirst, firstHelp);
    toolbar.after(intro);

    function sizeCalendar() {
        const header = document.querySelector('.main-header');
        byId('calendar-container').style.height = `calc(100dvh - ${Math.ceil(header.getBoundingClientRect().bottom)}px)`;
    }
    function layoutDayCards() {
        if (calendarView !== 'day') return;
        // Overlapping events share lanes, so none silently covers another.
        const cards = [...document.querySelectorAll('#events-layer .event-card')].sort((a,b) => +a.dataset.startMinutes - +b.dataset.startMinutes);
        let cluster = [], end = -1;
        const draw = () => {
            const lanes = [];
            for (const card of cluster) {
                const start = +card.dataset.startMinutes;
                let lane = lanes.findIndex(value => value <= start);
                if (lane < 0) lane = lanes.length;
                lanes[lane] = start + +card.dataset.durationMinutes;
                card.dataset.lane = lane;
            }
            const width = byId('events-layer').clientWidth / Math.max(1, lanes.length);
            for (const card of cluster) {
                card.style.left = `${+card.dataset.lane * width + 3}px`;
                card.style.width = `${Math.max(16, width - 6)}px`;
            }
        };
        for (const card of cards) {
            const start = +card.dataset.startMinutes;
            if (start >= end && cluster.length) { draw(); cluster = []; end = -1; }
            cluster.push(card);
            end = Math.max(end, start + +card.dataset.durationMinutes);
        }
        draw();
    }
    function updateCalendarChrome() {
        day.setAttribute('aria-pressed', String(calendarView === 'day'));
        week.setAttribute('aria-pressed', String(calendarView === 'week'));
        modes.setAttribute('aria-label', uxText('Вид календаря', 'Calendar view'));
        stepNavigation.setAttribute('aria-label', calendarView === 'day' ? uxText('Навигация по дням','Day navigation') : uxText('Навигация по неделям','Week navigation'));
        byId('btn-prev-week').setAttribute('aria-label', calendarView === 'day' ? uxText('Предыдущий день','Previous day') : uxText('Предыдущая неделя','Previous week'));
        byId('btn-next-week').setAttribute('aria-label', calendarView === 'day' ? uxText('Следующий день','Next day') : uxText('Следующая неделя','Next week'));
        ['btn-prev-week','btn-next-week'].forEach(id => byId(id).title = byId(id).getAttribute('aria-label'));
        byId('top-next-lesson-details').style.top = `${Math.ceil(document.querySelector('.header-top').getBoundingClientRect().bottom) + 4}px`;
        intro.hidden = !state.onboardingNeeded || visibleStudentEntries().length > 0 || Object.values(state.schedule).some(items => items.length);
        introText.textContent = uxText('Добавьте первое занятие. Можно нажать на свободное время в календаре.', 'Add your first lesson, or tap an empty time in the calendar.');
        sizeCalendar();
        layoutDayCards();
    }
    window.addEventListener('temli-calendar-rendered', updateCalendarChrome);
    new MutationObserver(() => byId('top-next-lesson').setAttribute('aria-expanded', String(!byId('top-next-lesson-details').classList.contains('hidden'))))
        .observe(byId('top-next-lesson-details'), {attributes:true,attributeFilter:['class']});
    window.addEventListener('temli-onboarding-needed', updateCalendarChrome);
    const resizeObserver = new ResizeObserver(() => {
        sizeCalendar();
        // Width changes require new event coordinates; zoom and scroll remain unchanged.
        const width = byId('events-layer').clientWidth;
        if (width !== resizeObserver.lastWidth) { resizeObserver.lastWidth = width; renderCalendar(); }
    });
    resizeObserver.observe(document.querySelector('.main-header'));
    resizeObserver.observe(byId('calendar-container'));

    const actions = document.querySelector('#action-menu-overlay .modal-actions-column');
    const more = uxSection('Ещё', 'More', [
        byId('btn-action-report'),
        byId('action-color-label'), byId('action-color-palette')
    ], byId('btn-action-close'));
    more.id = 'action-more';
    const contacts = document.createElement('div');
    contacts.className = 'payment-actions-row';
    byId('btn-action-chat-student').before(contacts);
    contacts.append(byId('btn-action-chat-student'), byId('btn-action-chat-parent'));
    const actionContext = document.createElement('p');
    actionContext.id = 'action-context';
    actionContext.setAttribute('data-i18n-ignore', '');
    byId('action-menu-title').after(actionContext);
    function updateActionContext() {
        more.open = false;
        const lesson = state.selectedLesson;
        if (!lesson) { actionContext.textContent = ''; return; }
        actionContext.textContent = `${shortDateRu(lesson.date)} · ${lesson.time}–${uxEndTime(lesson.time,lesson.duration)}`;
        if (lesson.entry_type !== 'personal' && lesson.lesson_type !== 'group') {
            actionContext.textContent += ' · ' + uiText(lesson.cancelled ? 'Отменено' : paymentStatusLabel(lesson));
        }
        contacts.classList.toggle('hidden', lesson.entry_type === 'personal' || lesson.lesson_type === 'group');
    }
    new MutationObserver(updateActionContext).observe(byId('action-menu-overlay'), {attributes:true,attributeFilter:['class']});

    const studentBody = document.querySelector('#student-card-overlay .modal-body');
    const groupFor = id => byId(id).closest('.form-group');
    const profileNodes = ['student-calendar-name','student-birthday','student-status-active'].map(groupFor);
    uxSection('Профиль ученика', 'Student profile', profileNodes, profileNodes[0]);
    const linkNodes = ['student-board-link','student-zoom-link','student-card-student-contacts','student-card-parent-contacts'].map(groupFor);
    uxSection('Контакты и ссылки', 'Contacts and links', linkNodes, linkNodes[0]);
    const notificationOptions = document.querySelector('.student-notification-options');
    uxSection('Уведомления', 'Notifications', [notificationOptions,byId('student-bot-invites')], notificationOptions);
    const history = document.querySelector('.student-history-section');
    uxSection('История занятий', 'Lesson history', [history], history);
    studentBody.querySelectorAll('.ux-section').forEach(section => section.setAttribute('data-ux-student-section',''));
    new MutationObserver(() => {
        if (!byId('student-card-overlay').classList.contains('hidden')) studentBody.querySelectorAll('[data-ux-student-section]').forEach(section => section.open = false);
    }).observe(byId('student-card-overlay'), {attributes:true,attributeFilter:['class']});

    // Offer sending the invitation through the device's share sheet when available.
    const inviteRow = document.querySelector('.student-bot-invite-link-row');
    if (navigator.share) {
        const share = uxButton('Поделиться', 'Share', async () => {
            const url = byId('student-bot-invite-url').value;
            if (!url) return;
            try { await navigator.share({url}); }
            catch (error) { if (error.name !== 'AbortError') uxMessage(uxText('Не удалось открыть отправку. Скопируйте ссылку.', 'Could not share. Copy the link instead.')); }
        });
        share.id = 'student-bot-invite-share';
        inviteRow.append(share);
    }
    byId('student-bot-invite-url').classList.add('ux-invite-url');
    const showLink = uxButton('Показать ссылку', 'Show link', () => {
        const input = byId('student-bot-invite-url');
        input.classList.toggle('ux-show-url');
        showLink.setAttribute('aria-expanded',String(input.classList.contains('ux-show-url')));
    }, 'ux-text-button');
    byId('student-bot-invite-result').append(showLink);
    const originalCopy = byId('student-bot-invite-copy').onclick;
    byId('student-bot-invite-copy').onclick = async () => {
        try {
            await copyTextToClipboard(byId('student-bot-invite-url').value);
            uxMessage(uxText('Ссылка скопирована', 'Link copied'));
        } catch (_) {
            byId('student-bot-invite-url').classList.add('ux-show-url');
            await originalCopy();
        }
    };

    // Drafts are scoped to the exact form/record. No personal information in localStorage.
    const drafts = new Map();
    const formIds = ['modal-overlay','student-card-overlay','lesson-report-overlay'];
    function draftKey(id) {
        if (id === 'student-card-overlay') return id + ':' + byId(id).dataset.studentId;
        if (id === 'lesson-report-overlay') return id + ':' + state.selectedLesson?.id;
        return state.editingExisting ? id + ':edit:' + state.selectedLesson?.id
            : id + ':new:' + byId('lesson-type-select').value + ':' + byId('lesson-date').value + ':' + byId('lesson-time').value;
    }
    for (const id of formIds) {
        const overlay = byId(id);
        let activeKey = '', wasOpen = false, restoring = false;
        let draftCaptureHandle = null;
        let draftCaptureUsesIdleCallback = false;
        let skipCaptureOnClose = false;
        const notice = document.createElement('div');
        notice.className = 'ux-draft-notice';
        notice.hidden = true;
        notice.setAttribute('data-i18n-ignore','');
        const label = document.createElement('span');
        const discard = uxButton('Сбросить', 'Discard', () => {
            drafts.delete(activeKey);
            notice.hidden = true;
            if (id === 'student-card-overlay') openStudentCard(overlay.dataset.studentId);
            else if (id === 'lesson-report-overlay') openLessonReport();
            else if (state.editingExisting) openEditModal(state.selectedLesson.date,state.selectedLesson);
            else openAddModal(byId('lesson-date').value,byId('lesson-time').value,byId('lesson-type-select').value);
        },'ux-text-button');
        notice.append(label,discard);
        (overlay.querySelector('.modal-body') || overlay.querySelector('.modal-content')).prepend(notice);
        function capture() {
            if (restoring || !wasOpen) return;
            const fields = [...overlay.querySelectorAll('input[id],textarea[id],select[id]')]
                .filter(field => field.type !== 'password' && !field.readOnly)
                .map(field => ({id:field.id,value:field.value,checked:field.checked}));
            const draft = {fields};
            if (id === 'modal-overlay' && byId('lesson-type-select').value === 'group') draft.members = collectGroupMembers();
            if (id === 'modal-overlay' && byId('lesson-type-select').value === 'student') {
                draft.lessonContacts = getContacts('lesson-parent-contacts');
                draft.lessonStudentContacts = getContacts('lesson-student-contacts');
            }
            if (id === 'student-card-overlay') {
                draft.contacts = getContacts('student-card-parent-contacts');
                draft.studentContacts = getContacts('student-card-student-contacts');
                draft.status = overlay.dataset.studentStatus;
            }
            drafts.set(activeKey,draft);
            label.textContent = uxText('Есть несохранённые изменения', 'Unsaved changes');
            label.dataset.uxRu = 'Есть несохранённые изменения';
            label.dataset.uxEn = 'Unsaved changes';
            notice.hidden = false;
        }
        function cancelScheduledCapture() {
            if (draftCaptureHandle === null) return;
            if (draftCaptureUsesIdleCallback && typeof window.cancelIdleCallback === 'function') {
                window.cancelIdleCallback(draftCaptureHandle);
            } else {
                window.clearTimeout(draftCaptureHandle);
            }
            draftCaptureHandle = null;
        }
        function flushScheduledCapture() {
            cancelScheduledCapture();
            capture();
        }
        function scheduleCapture() {
            cancelScheduledCapture();
            // Reading every field and contact row is intentionally kept out of the
            // input event. This lets the browser paint the typed digit/selection
            // before maintaining the in-memory draft on slower Telegram WebViews.
            if (typeof window.requestIdleCallback === 'function') {
                draftCaptureUsesIdleCallback = true;
                draftCaptureHandle = window.requestIdleCallback(() => {
                    draftCaptureHandle = null;
                    capture();
                }, {timeout: 250});
            } else {
                draftCaptureUsesIdleCallback = false;
                draftCaptureHandle = window.setTimeout(() => {
                    draftCaptureHandle = null;
                    capture();
                }, 120);
            }
        }
        overlay.addEventListener('input',scheduleCapture);
        overlay.addEventListener('change',scheduleCapture);
        overlay.addEventListener('click', event => {
            if (event.target.closest('.contact-remove-btn,.add-contact-btn,.student-status-btn')) queueMicrotask(scheduleCapture);
        });
        new MutationObserver(() => {
            const open = !overlay.classList.contains('hidden');
            if (open && (!wasOpen || activeKey !== draftKey(id))) {
                skipCaptureOnClose = false;
                wasOpen = true;
                activeKey = draftKey(id);
                const draft = drafts.get(activeKey);
                notice.hidden = !draft;
                if (draft) {
                    restoring = true;
                    if (draft.members) renderGroupMembers(draft.members);
                    for (const field of draft.fields) {
                        const target = byId(field.id);
                        if (!target) continue;
                        target.value = field.value;
                        if (target.type === 'checkbox' || target.type === 'radio') target.checked = field.checked;
                    }
                    if (id === 'modal-overlay') {
                        updateLessonTypeUI(); updateReminderControls();
                        byId('manual-student-name').classList.toggle('hidden',byId('student-select').value !== 'manual');
                        byId('repeat-until-wrap').classList.toggle('hidden',byId('lesson-repeat').value !== 'year');
                        if (draft.lessonContacts) {
                            renderContacts('lesson-parent-contacts',draft.lessonContacts);
                            renderContacts('lesson-student-contacts',draft.lessonStudentContacts);
                        }
                    }
                    if (draft.contacts) {
                        renderContacts('student-card-parent-contacts',draft.contacts);
                        renderContacts('student-card-student-contacts',draft.studentContacts);
                        setStudentStatus(draft.status);
                    }
                    label.textContent = uxText('Черновик восстановлен', 'Draft restored');
                    label.dataset.uxRu = 'Черновик восстановлен';
                    label.dataset.uxEn = 'Draft restored';
                    restoring = false;
                }
            } else if (!open) {
                // Preserve the last keystroke even when the form is closed before
                // the idle callback gets a chance to run.
                if (skipCaptureOnClose) cancelScheduledCapture();
                else flushScheduledCapture();
                skipCaptureOnClose = false;
                wasOpen = false;
            }
        }).observe(overlay,{attributes:true,attributeFilter:['class']});
        window.addEventListener('temli-saved', event => {
            if (event.detail.overlay === id) {
                cancelScheduledCapture();
                skipCaptureOnClose = true;
                drafts.delete(activeKey);
                notice.hidden = true;
            }
        });
    }
    window.addEventListener('temli-saved', async event => {
        const firstLesson = event.detail.overlay === 'modal-overlay' && state.onboardingNeeded && byId('lesson-type-select').value !== 'personal';
        uxMessage(firstLesson
            ? uxText('Первое занятие готово. Нажмите его для оплаты, переноса и связи.', 'Your first lesson is ready. Tap it for payment, rescheduling and contacts.')
            : uxText('Сохранено', 'Saved'));
        if (firstLesson) {
            try { await markOnboardingCompleted(); } catch (_) { /* The lesson has already been saved. */ }
        }
        updateCalendarChrome();
    });

    // Infer duration from existing lessons only when creating an individual lesson.
    byId('student-select').addEventListener('change', () => {
        if (state.editingExisting) return;
        const id = byId('student-select').value;
        if (!id || id === 'manual') return;
        const lessons = Object.values(state.schedule).flat().filter(lesson => String(lesson.student_id) === id && lesson.entry_type !== 'personal' && lesson.lesson_type !== 'group');
        const counts = new Map();
        lessons.forEach(lesson => {
            const duration = Number(lesson.duration || 60);
            if (duration >= 15 && duration <= 1440) counts.set(duration,(counts.get(duration) || 0) + 1);
        });
        if (counts.size) byId('lesson-duration').value = [...counts].sort((a,b) => b[1]-a[1])[0][0];
        byId('reminder-enabled').checked = getStudentInfo(id).student_reminders === true;
        updateReminderControls();
    });

    const originalExecuteMove = executeMove;
    executeMove = async function(action) {
        const buttons = [...document.querySelectorAll('#move-modal-overlay button')];
        if (executeMove.busy) return;
        executeMove.busy = true;
        buttons.forEach(button => button.disabled = true);
        const target = state.pendingMove && {...state.pendingMove};
        try {
            await originalExecuteMove(action);
            if (!state.isMoving && target) uxMessage(uxText('Готово: ', 'Done: ') + formatAddTypeContext(target.newDate,target.newTime));
        } catch (_) { /* Network panel retains the failed operation and destination. */ }
        finally { executeMove.busy = false; buttons.forEach(button => button.disabled = false); }
    };

    const profileSave = byId('btn-save-student-card');
    const saveProfile = profileSave.onclick;
    profileSave.onclick = async () => {
        if (profileSave.disabled) return;
        profileSave.disabled = true;
        try { await saveProfile(); }
        catch (_) { uxMessage(uxText('Не сохранено. Изменения остались в карточке.', 'Not saved. Your changes remain in the profile.')); }
        finally { profileSave.disabled = false; }
    };
    for (const id of ['btn-delete-once','btn-delete-all']) {
        const button = byId(id), handler = button.onclick;
        button.onclick = async () => {
            if (byId('btn-delete-once').disabled || byId('btn-delete-all').disabled) return;
            byId('btn-delete-once').disabled = byId('btn-delete-all').disabled = true;
            try { await handler(); }
            catch (_) { /* Keep the confirmation visible for network recovery. */ }
            finally { byId('btn-delete-once').disabled = byId('btn-delete-all').disabled = false; }
        };
    }

    // Advisory conflict preview. The final write still uses the existing server workflow.
    function attachConflictPreview(overlayId, values, watchIds) {
        const overlay = byId(overlayId);
        const notice = document.createElement('p');
        notice.className = 'ux-conflict-notice';
        notice.hidden = true;
        notice.setAttribute('role','status');
        notice.setAttribute('data-i18n-ignore','');
        (overlay.querySelector('.modal-actions') || overlay.querySelector('.modal-actions-column')).before(notice);
        let sequence = 0, timer;
        function check() {
            const seq = ++sequence;
            if (overlay.classList.contains('hidden')) { notice.hidden = true; notice.textContent = ''; return; }
            const {date,time,duration,exclude} = values();
            const start = new Date(`${date}T${time}:00`);
            if (!date || !time || Number.isNaN(start.getTime()) || !(duration > 0)) { notice.hidden = true; return; }
            const end = new Date(start.getTime() + duration * 60000);
            const previous = new Date(start); previous.setDate(previous.getDate()-1);
            const weeks = [...new Set([dateKey(getMonday(previous)),dateKey(getMonday(start)),dateKey(getMonday(end))])];
            try {
                // Conflict preview is advisory. Never let it compete with the save
                // request for cross-region storage: inspect the displayed week and
                // already-cached adjacent weeks only. The server remains the final
                // authority when the form is saved.
                const currentWeek = dateKey(state.currentMonday);
                const results = weeks.map(key => key === currentWeek
                    ? {requestedWeek:key, schedule:state.schedule}
                    : cachedWeekSchedule(key)).filter(Boolean);
                if (seq !== sequence || overlay.classList.contains('hidden')) return;
                const conflicts = [];
                for (const result of results) for (const [key,items] of Object.entries(result.schedule || {})) for (const item of items) {
                    if (item.cancelled || (exclude && String(item.id) === String(exclude))) continue;
                    const otherStart = new Date(`${key}T${item.time}:00`);
                    const otherEnd = new Date(otherStart.getTime()+Number(item.duration||60)*60000);
                    if (start < otherEnd && end > otherStart) conflicts.push(item);
                }
                notice.hidden = !conflicts.length;
                notice.textContent = conflicts.length ? uxText('Пересекается: ', 'Overlaps: ') + conflicts.slice(0,3).map(item =>
                    `${item.entry_type === 'personal' ? uxText('личное дело','personal event') : item.group_name || item.student || uxText('занятие','lesson')} ${item.time}–${uxEndTime(item.time,item.duration)}`).join('; ') : '';
            } catch (_) {
                if (seq === sequence) notice.textContent = uxText('Не удалось проверить пересечения. Проверьте время в календаре.', 'Could not check overlaps. Check the time in the calendar.');
            }
        }
        const schedule = () => { clearTimeout(timer); sequence++; timer = setTimeout(check,250); };
        watchIds.forEach(id => byId(id).addEventListener('input',schedule));
        new MutationObserver(schedule).observe(overlay,{attributes:true,attributeFilter:['class']});
        window.addEventListener('temli-language-change',schedule);
    }
    attachConflictPreview('modal-overlay', () => ({date:byId('lesson-date').value,time:byId('lesson-time').value,
        duration:Number(byId('lesson-duration').value),exclude:state.editingExisting ? state.selectedLesson?.id : null}),['lesson-date','lesson-time','lesson-duration']);
    attachConflictPreview('move-modal-overlay', () => ({date:state.pendingMove?.newDate,time:state.pendingMove?.newTime,
        duration:Number(state.selectedLesson?.duration || 60),exclude:state.selectedLesson?.id}),[]);

    // The single-event action is the primary choice; copying is secondary.
    const moveOnce = byId('btn-action-move-once');
    byId('btn-action-copy').before(moveOnce);
    moveOnce.className = 'primary-btn';
    byId('btn-action-copy').className = 'secondary-btn';

    function localizeUx() {
        document.querySelectorAll('[data-ux-ru]').forEach(node => node.textContent = uxText(node.dataset.uxRu,node.dataset.uxEn));
        feedback.hidden = true;
        feedback.textContent = '';
        byId('move-hint-text').textContent = uxText('Выберите новое время', 'Choose a new time');
        updateActionContext();
        renderCalendar();
        updateCalendarChrome();
    }
    window.addEventListener('temli-language-change',localizeUx);
    localizeUx();
})();
