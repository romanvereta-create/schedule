/* Loaded after app.js; all recipients are resolved again on the server. */
function renderEndNotificationLabels() {
    document.getElementById('student-parent-end-label').textContent = botText('Родителю об окончании', 'Notify parent when lesson ends');
    document.getElementById('default-parent-end-label').textContent = botText('Родителю об окончании', 'Notify parent when lesson ends');
    for (const id of ['student-reminders-label', 'default-reminders-label'])
        document.getElementById(id).textContent = botText('Напоминать ученику о занятии', 'Remind student about lessons');
    document.getElementById('notification-defaults-hint').textContent = botText('Для новых учеников. Существующие настройки не меняются.', 'For new students. Existing preferences stay unchanged.');
    document.getElementById('lesson-reminder-label').textContent = botText('Напоминать за (если включено у ученика)', 'Reminder time (if enabled for student)');
}
window.addEventListener('temli-language-change', renderEndNotificationLabels);
renderEndNotificationLabels();
function openPersonalNotification(lesson, teacherDelay) {
    if (!lesson) return;
    document.getElementById('personal-notification-overlay')?.remove();
    const overlay = document.createElement('div');
    overlay.id = 'personal-notification-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:1500;background:#0007;display:flex;align-items:center;justify-content:center;padding:16px';
    overlay.setAttribute('data-i18n-ignore', '');
    const box = document.createElement('div');
    box.className = 'modal-content';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    const title = document.createElement('h2');
    title.style.cssText = 'font-size:17px;margin-bottom:12px';
    title.textContent = teacherDelay ? botText('Я задержусь', 'I’ll be late') : botText('Ученик задерживается', 'Student is late');
    box.append(title);
    const select = document.createElement('select');
    select.style.cssText = 'padding:10px;margin-bottom:10px;width:100%';
    const members = lesson.lesson_type === 'group' ? lesson.group_members || [] : [{student_id:lesson.student_id, name:lesson.student}];
    if (lesson.lesson_type === 'group') {
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = botText('Выберите ученика', 'Choose a student');
        placeholder.disabled = true;
        placeholder.selected = true;
        select.append(placeholder);
    }
    for (const member of members) {
        const option = document.createElement('option');
        option.value = member.student_id;
        option.textContent = member.name || getStudentInfo(member.student_id).name || botText('Ученик', 'Student');
        select.append(option);
    }
    select.setAttribute('aria-label', botText('Ученик', 'Student'));
    if (lesson.lesson_type === 'group') box.append(select);
    const actions = document.createElement('div');
    actions.style.cssText = 'display:grid;gap:8px';
    const status = document.createElement('p');
    status.setAttribute('role','status');
    status.style.cssText = 'font-size:13px;line-height:1.4;margin-top:10px';
    let busy = false;
    const choices = teacherDelay ? [5,10,15] : ['student','parent'];
    for (const choice of choices) {
        const button = document.createElement('button');
        button.className = 'secondary-btn';
        const role = teacherDelay ? 'student' : choice;
        const time = new Date(lesson.date + 'T' + lesson.time);
        if (teacherDelay) time.setMinutes(time.getMinutes() + choice);
        const hhmm = String(time.getHours()).padStart(2,'0') + ':' + String(time.getMinutes()).padStart(2,'0');
        const defaultPreview = teacherDelay
            ? botText('Немного задержусь. Начнём занятие в ', 'I’m running a little late. We’ll start at ') + hhmm + '.'
            : role === 'student' ? botText('Занятие уже началось. Сможешь подключиться?', 'The lesson has started. Can you join?')
            : botText('Занятие уже началось, но ребёнок пока не подключился. Подскажите, сможет присоединиться?', 'The lesson has started, but your child hasn’t joined yet. Will they be able to join?');
        const templateKey = teacherDelay ? 'teacher_delay_template' : role === 'student' ? 'student_delay_template' : 'parent_delay_template';
        const preview = String(state.settings[templateKey] || defaultPreview).replaceAll('{time}', hhmm);
        button.textContent = teacherDelay ? '+' + choice + ' → ' + hhmm : role === 'student' ? botText('Написать ученику', 'Message student') : botText('Написать родителю', 'Message parent');
        button.onclick = async () => {
            if (busy || !select.value) return;
            busy = true;
            actions.querySelectorAll('button').forEach(b => b.disabled = true);
            select.disabled = true;
            status.textContent = botText('Отправляем…', 'Sending…');
            try {
                const response = await apiFetch('/personal_notification', {method:'POST',body:JSON.stringify({
                    action:teacherDelay ? 'teacher_delay' : 'student_delay', role,
                    minutes:teacherDelay ? choice : null, date:lesson.date, lesson_id:lesson.id,
                    student_id:select.value, request_id:newPaymentRequestId()
                })});
                const result = await response.json();
                if (result.status !== 'ok') {
                    const messages = {
                        recipient_blocked:botText('Получатель заблокировал бота.', 'The recipient blocked the bot.'),
                        recipient_unavailable:botText('Чат получателя недоступен.', 'The recipient chat is unavailable.'),
                        bot_invalid:botText('Токен бота недействителен. Подключите бота заново.', 'Bot token is invalid. Reconnect the bot.'),
                        rate_limited:botText('Telegram ограничил отправку. Повторите позже.', 'Telegram rate limit reached. Try later.'),
                        recipient_missing:botText('Получатель не подключён. Подтвердите привязку в карточке ученика.', 'Recipient not connected. Confirm their connection in the student profile.'),
                        recipient_ambiguous:botText('Найдено несколько привязок. Оставьте нужную в карточке ученика.', 'Multiple connections found. Keep the intended connection in the student profile.'),
                        lesson_missing:botText('Занятие отменено или удалено.', 'The lesson was cancelled or removed.')
                    };
                    status.textContent = messages[result.code] || botMessage(result.code);
                    return;
                }
                status.textContent = result.delivery === 'sent' ? botText('Сообщение отправлено.', 'Message sent.')
                    : botText('Результат отправки неизвестен. Проверьте доставку перед повтором.', 'Delivery is uncertain. Check before sending again.');
            } catch {
                status.textContent = botText('Результат отправки неизвестен. Проверьте доставку перед повтором.', 'Delivery is uncertain. Check before sending again.');
            }
        };
        actions.append(button);
    }
    const close = document.createElement('button');
    close.className = 'secondary-btn';
    close.style.marginTop = '10px';
    close.textContent = botText('Закрыть', 'Close');
    close.onclick = () => overlay.remove();
    box.append(actions,status,close);
    overlay.append(box);
    document.body.append(overlay);
}
