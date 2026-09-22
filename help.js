/* Teacher-facing help. No account data, remote content or hidden product promises. */
(() => {
    'use strict';
    const overlay = document.getElementById('help-overlay');
    if (!overlay) return;
    const body = overlay.querySelector('.help-body');
    overlay.setAttribute('data-i18n-ignore', '');
    const pick = pair => pair[window.TEMLI_I18N?.language() === 'en' ? 1 : 0];
    const steps = [
        [['Добавьте занятие', 'Add a lesson'], ['Нажмите свободное время или «Добавить занятие». Укажите ученика, время, длительность и цену; сохраните.', 'Tap a free time or “Add lesson”. Enter the student, time, duration and price; save.']],
        [['Работайте из календаря', 'Use the calendar'], ['Нажмите занятие: здесь оплата, перенос, связь и настройки урока. Ученики — слева вверху.', 'Tap a lesson for payment, rescheduling, contacts and lesson settings. Students are at the top left.']],
        [['Остальное — по необходимости', 'Set up the rest when needed'], ['Рабочие часы и «Мой бот» — в настройках справа вверху. Контакты можно добавить сразу при создании урока.', 'Working hours and “My bot” are in settings at the top right. You can add contacts while creating a lesson.']]
    ];
    const topics = [
        {id: 'calendar', title: ['Календарь и ближайшее занятие', 'Calendar and upcoming lesson'], items: [
            ['«Сегодня» возвращает к текущей дате; календарик выбирает дату. Стрелки листают дни в режиме «День» и недели в режиме «Неделя». Лупы меняют масштаб, а не длительность урока.', '“Today” returns to the current date; the date picker selects a date. Arrows switch days in Day view and weeks in Week view. Magnifiers change the scale, not lesson duration.'],
            ['Верхняя плашка показывает текущее или ближайшее занятие и его время. Раскройте верхнюю плашку для быстрых действий, связи, доски и видеовстречи, если ссылки заполнены.', 'The top bar shows the current or next lesson and its time. Expand it for quick actions, contacts, a board and a video call when links are set.'],
            ['Знак валюты отмечает оплату; у группы счётчик показывает оплативших участников. Отменённое занятие остаётся в истории с отдельной отметкой.', 'A currency symbol marks payment; a group counter shows paid participants. A cancelled lesson stays in history with its own mark.'],
            ['Выходной доступен для занятия: подтвердите шутливый вопрос. В свободные окна помощника такие дни не попадают. Кнопка разворота в шапке включает полноэкранный режим, если Telegram его поддерживает.', 'You can schedule on a day off by confirming the playful warning. The assistant excludes days off from free windows. The expand button uses fullscreen when supported by Telegram.']
        ]},
        {id: 'lessons', title: ['Занятия: создание, перенос, отмена', 'Lessons: create, move, cancel'], items: [
            ['При создании выберите ученика или группу с участниками. Для нового ученика введите имя. Проверьте дату, время, длительность, стоимость и повтор: разовый урок — «Без повтора», регулярный — с датой окончания.', 'Choose a student or a group with members. Enter a name for a new student. Check the date, time, duration, price and recurrence: no repeat for a one-off lesson, or an end date for regular lessons.'],
            ['Достаточно имени ученика; имя родителя и контакты необязательны. Без галочек приглашений никто не получит сообщений. Если хотите подключить ученика или родителя, отметьте нужные ссылки: после сохранения нажмите «Отправить». Участников группы подключайте через их карточки.', 'A student name is enough; the parent name and contacts are optional. Leave invitations unchecked to avoid messaging anyone. Select student or parent links if needed, then press Send after saving. Connect group members through their profiles.'],
            ['Нажмите урок → «Настройки занятия», чтобы изменить его. При изменении цены выберите область: этот урок или также будущие неоплаченные. Проверьте выбранную область перед сохранением.', 'Tap a lesson → Lesson settings to edit it. When changing the price, choose this lesson or also future unpaid lessons. Check the scope before saving.'],
            ['«Перенести»: короткий тап открывает меню. Движение карточки вбок или плавное движение вверх/вниз начинает перенос; быстрый вертикальный свайп прокручивает календарь даже поверх занятия. После отпускания выбран ровный час, а в следующем окне доступны :00, :15, :30, :45, шаг −5/+5 и ввод точного времени.', 'Reschedule: a short tap opens the menu. A sideways movement or a deliberate vertical movement starts dragging; a fast vertical swipe scrolls the calendar even over a lesson. On release, the exact hour is selected, and the next dialog offers :00, :15, :30, :45, −5/+5 and direct time entry.'],
            ['«Отменить» в меню урока сохраняет его как отменённый; «Вернуть занятие» восстанавливает. «Удалить» убирает уроки в выбранной области. Это разные действия — проверяйте подтверждение удаления.', 'Cancel in the lesson menu keeps the lesson as cancelled; Restore lesson brings it back. Delete removes lessons within the selected scope. These are different actions; check the deletion confirmation.'],
            ['После переноса, копирования или удаления на 20 секунд появляется «Отменить» — это отмена последнего действия, а не отмена урока. Она доступна, пока затронутые записи не изменились.', 'After a move, copy or deletion, Undo appears for 20 seconds. It reverses that action, not the lesson itself, provided the affected records have not changed.']
        ]},
        {id: 'personal', title: ['Личные дела', 'Personal events'], items: [
            ['Нажмите свободное время → «Личное дело». Укажите название, длительность и при необходимости заметку; сохраните. Для изменений нажмите событие в календаре.', 'Tap a free time → Personal event. Enter a title, duration and optional note; save. Tap the event in the calendar to change it.'],
            ['Личное дело занимает время и исключается из свободных окон, но не создаёт ученика, оплату или уведомление. Заметка не выводится на календарной карточке.', 'A personal event blocks time and is excluded from free windows, but creates no student, payment or notification. Its note is not displayed on the calendar card.']
        ]},
        {id: 'students', title: ['Ученики, группы и ссылки', 'Students, groups and links'], items: [
            ['Кнопка с двумя человечками слева вверху открывает список учеников. Выберите ученика: в карточке — контакты, заметка, история занятий и оплат. Редкие поля раскрываются отдельно.', 'The people button at the top left opens students. Choose a student for contacts, a note, lesson and payment history. Less-used fields expand separately.'],
            ['«Ссылка на доску» хранится в карточке ученика. Для видеовстречи используется личная ссылка, а если её нет — общая Zoom / Telemost из настроек. Вставляйте полную ссылку и сохраняйте.', 'The board link is in the student profile. Video calls use the student’s link, or the shared Zoom / Telemost link from settings if no personal link is set. Paste a full URL and save.'],
            ['«Пауза» и архив сохраняют профиль, но убирают ученика из выбора для новых уроков. Архив открывается флажком в списке учеников; оттуда ученика можно вернуть. Полное удаление — отдельное действие с подтверждением, не замена паузы.', 'Pause and archive retain the profile but remove the student from new-lesson choices. Show archived students using the checkbox in the list; you can restore them there. Permanent deletion is a separate confirmed action, not a substitute for pausing.'],
            ['У группы каждый участник имеет свою карточку, контакты и оплату. Нажмите имя участника в занятии для его действий. День рождения из карточки используется помощником.', 'Each group member has a separate profile, contacts and payment status. Tap their name in a lesson for individual actions. The assistant uses birthdays from profiles.']
        ]},
        {id: 'invites', title: ['Контакты и привязка к боту', 'Contacts and bot connections'], items: [
            ['Личный бот не обязателен: приглашения работают через общий TEMLI-бот. Если хотите своего бота, подключите его в «Настройки» → «Мой бот». Не используйте бота другого сервиса; токен никому не пересылайте. Уже подключённые получатели сохраняют прежний канал связи.', 'A personal bot is optional: invitations work through the shared TEMLI bot. Connect your own in Settings → My bot if desired. Do not use another service’s bot; keep the token private. Existing recipients retain their original messaging channel.'],
            ['Приглашения доступны при создании индивидуального урока и в карточке ученика → «Подключить ученика и родителя»: «Ссылка ученику» / «Ссылка родителю». Отправьте каждому его ссылку. Она одноразовая, действует 48 часов; новая заменяет прежнюю для этой роли.', 'Invitations are available when creating an individual lesson and in the student profile → Connect student and parent: Student link / Parent link. Send each person their own link. Links are single-use, expire in 48 hours and replace the previous link for that role.'],
            ['Получатель открывает ссылку и нажимает «Начать» / Start. Появится индикатор ожидающих привязок на кнопке учеников и отметка у нужного ученика. Откройте его карточку, проверьте аккаунт и подтвердите ученика или родителя. Если ждёте результат — «Обновить привязки».', 'The recipient opens the link and presses Start. A pending-connection indicator appears on the students button and beside the relevant student. Open their profile, check the account and confirm the student or parent. Use Refresh connections when waiting for a result.'],
            ['После подтверждения пустой Telegram-контакт соответствующей роли заполняется автоматически. Уже заполненный контакт не заменяется. Можно указать @username или цифровой ID вручную через «Добавить контакт»; затем «Сохранить».', 'After confirmation, an empty Telegram contact for that role is filled automatically. Existing contacts are preserved. You can also enter @username or a numeric ID manually via Add contact, then Save.'],
            ['Кнопка «Написать» сначала открывает Telegram. Если его нет — чат WhatsApp по номеру. Если указан только MAX, TEMLI копирует контакт: откройте MAX и вставьте его в поиск. Для ученика и родителя эта последовательность работает отдельно.', 'Write opens Telegram first. If it is missing, it opens a WhatsApp chat by phone number. If only MAX is available, TEMLI copies the contact: open MAX and paste it into search. This priority is applied separately to the student and parent.'],
            ['Контакт открывает вашу переписку; привязка разрешает боту отправлять сообщения. Это не одно и то же: одного контакта для автосообщений недостаточно. Ученик и родитель подтверждаются отдельно; неверную привязку можно отозвать в карточке.', 'A contact opens your chat; a connection lets the bot send messages. They are different: a contact alone is not enough for automatic messages. Student and parent connections are confirmed separately; revoke an incorrect connection in the profile.']
        ]},
        {id: 'messages', title: ['Напоминания, задержки и тексты', 'Reminders, delays and message texts'], items: [
            ['Сообщения отправляются через того бота, к которому подключился получатель: общего TEMLI-бота или личного бота преподавателя. Сначала подтвердите привязку. В карточке включите напоминания ученику и, при необходимости, сообщение родителю об окончании. В уроке задайте время напоминания.', 'Messages use the bot the recipient joined: the shared TEMLI bot or the teacher’s personal bot. Confirm the connection first. Enable student reminders and optional parent lesson-end messages in the profile. Set reminder timing in the lesson.'],
            ['Общие настройки уведомлений применяются к новым ученикам, а не переписывают настройки существующих. Для уже добавленного ученика меняйте его карточку.', 'Notification defaults apply to new students; they do not overwrite existing preferences. Change an existing student’s profile individually.'],
            ['«Я задержусь» в действиях занятия: выберите +5, +10 или +15 минут и подтвердите текст. «Ученик задерживается»: выберите, написать ученику или родителю. В группе сначала выберите участника. Эти сообщения сами не переносят занятие.', 'Use I’ll be late in lesson actions: choose +5, +10 or +15 minutes and confirm the text. Student is late lets you message the student or parent. Choose a member first for a group. These messages do not reschedule the lesson.'],
            ['Все семь шаблонов — «Настройки» → «Мой бот» → «Тексты сообщений»: приветствия ученику и родителю, напоминание, окончание занятия и три сообщения о задержке. Переменные указаны под полями; их значения подставятся при отправке.', 'All seven templates are in Settings → My bot → Message texts: student and parent welcomes, a reminder, a lesson-end message and three delay messages. Variables are listed below the fields and filled when sending.'],
            ['Пустое поле использует стандартный текст. «Вернуть стандартные тексты» очищает шаблоны; примените изменения кнопкой «Сохранить» в настройках. Перед ручной отправкой всегда проверьте показанный текст.', 'An empty field uses the default text. Restore default texts clears the templates; apply changes using Save in settings. Always check the preview before sending a manual message.']
        ]},
        {id: 'payments', title: ['Оплаты и абонементы', 'Payments and packages'], items: [
            ['Откройте занятие: «Оплачено» отмечает оплату, «Бесплатно» — бесплатный урок, «Абонемент» — оплату нескольких занятий. У группы статус и цена задаются по участникам; группа оплачена, когда оплачены все.', 'Open a lesson: Paid records payment, Free marks a free lesson, and Package pays for several lessons. Group members have separate prices and statuses; the group is paid when all members are paid.'],
            ['В карточке ученика «Распределить общую сумму» показывает расчёт перед подтверждением. И общая сумма, и абонемент начинают с самого раннего долга — индивидуальные и групповые уроки идут в одной очереди, затем будущие.', 'Allocate total amount in the student profile previews the calculation. Both total payments and packages start with the oldest debt: individual and group lessons share one queue, followed by future lessons.'],
            ['Если суммы не хватает на целый урок, остаток учитывается как частичная оплата; такой урок ещё не полностью оплачен. Проверяйте распределение, сумму и получателя чека до подтверждения.', 'If the amount does not cover a full lesson, it becomes a partial payment; that lesson is not fully paid yet. Check allocation, amount and receipt recipient before confirming.'],
            ['Разовую отметку оплаты можно снять через занятие. Общую оплату отменяют целиком в истории общих оплат; часть связанного платежа отдельно не снимается. Бесплатные и уже оплаченные уроки не оплачиваются повторно.', 'A direct payment mark can be removed from the lesson. Reverse an allocated payment as a whole in payment history, not one linked part. Free and already paid lessons are not paid again.']
        ]},
        {id: 'reports', title: ['Заметки к уроку, чеки и выгрузки', 'Lesson notes, receipts and exports'], items: [
            ['В действиях урока откройте отчёт/заметку о занятии, заполните и сохраните. История доступна в карточке ученика; это отдельно от общей заметки о нём.', 'Open the lesson report/note from lesson actions, enter it and save. History is available in the student profile, separate from the general student note.'],
            ['«Настройки» → «Данные для чека»: заполните реквизиты и оформление, сохраните. При оплате проверьте «Отправить чек родителю»; копией преподавателю управляет «Присылать копию чека мне».', 'Settings → Receipt details: enter details and appearance, then save. When paying, check Send receipt to parent; Send me a receipt copy controls the teacher’s copy.'],
            ['В настройках «Книга учёта» отправляет Excel в ваш Telegram, «Расписание недели» — PDF открытой недели. Если нужен другой период расписания, сначала выберите неделю в календаре.', 'In settings, Accounting book sends Excel to your Telegram; Weekly schedule sends a PDF of the open week. Select a different week in the calendar before exporting it.']
        ]},
        {id: 'assistant', title: ['Помощник: долги и свободные окна', 'Assistant: debts and free windows'], items: [
            ['Кнопка с листом рядом с настройками справа вверху открывает помощника: долги, свободные окна, сводку недели и ближайшие дни рождения. Нажмите запись, если у неё есть действие.', 'The document button beside settings at the top right opens the assistant: debts, free windows, weekly summary and upcoming birthdays. Tap an entry when it offers an action.'],
            ['Окна учитывают рабочие часы, выходные, занятия и личные дела. В разделе «Окна этой недели» кнопка копирования даёт текст, который можно отправить ученику или родителю.', 'Free windows account for working hours, days off, lessons and personal events. Copy in This week’s availability gives text you can send to a student or parent.']
        ]},
        {id: 'settings', title: ['Настройки и язык', 'Settings and language'], items: [
            ['Настройки находятся справа вверху. Рабочие часы задают видимую сетку и поиск свободных окон; выходные приглушаются, но уже созданные занятия не удаляются.', 'Settings are at the top right. Working hours define the visible grid and free-window search; days off are dimmed, but existing lessons are not deleted.'],
            ['Здесь же язык RU / EN, валюта, общая ссылка видеовстречи, значения уведомлений для новых учеников и данные для чеков. Смена валюты не конвертирует уже введённые суммы.', 'Here you can set RU / EN, currency, a shared meeting link, notification defaults for new students and receipt details. Changing currency does not convert existing amounts.'],
            ['После правок нажмите «Сохранить». Справка не сбрасывает введённые настройки: вернитесь стрелкой или кнопкой внизу и сохраните. Сама справка ничего не меняет.', 'Press Save after editing. Help preserves the settings you have entered: return with the back arrow or bottom button, then save. Help itself changes nothing.']
        ]},
        {id: 'saving', title: ['Сохранение, соединение и поддержка', 'Saving, connection and support'], items: [
            ['Кнопка с сообщением рядом с учениками слева вверху открывает поддержку TEMLI. Нажмите контакт, чтобы написать в Telegram; при ошибке укажите версию приложения из окна поддержки.', 'The message button beside Students at the top left opens TEMLI support. Tap the contact to write on Telegram; include the app version shown there when reporting an error.'],
            ['Дождитесь подтверждения сохранения. Черновики занятия, карточки ученика и отчёта удерживаются только в текущем открытом приложении и для той же записи. Закрытие или перезагрузка может их потерять; это не резервная копия.', 'Wait for confirmation when saving. Lesson, student profile and report drafts stay only in the current open app for the same record. Closing or reloading can lose them; they are not backups.'],
            ['При ошибке соединения прочитайте сообщение и обновите данные доступной кнопкой. Не повторяйте оплату или отправку вслепую: если результат неизвестен, сначала проверьте историю или доставку. Повторная загрузка данных сама не повторяет оплату.', 'On a connection error, read the message and reload data using the available button. Do not blindly repeat a payment or message: check history or delivery first if the outcome is uncertain. Reloading data does not repeat a payment.'],
            ['Если не удаётся открыть расписание, запустите Mini App из Telegram-бота и проверьте соединение. Версия приложения указана в настройках, а «Диагностика» доступна в сообщении об ошибке соединения. Не отправляйте вместе с ней токены и ключи.', 'If the schedule does not open, launch the Mini App from the Telegram bot and check your connection. The app version is in settings; Diagnostics is in the connection-error panel. Do not share tokens or keys with it.']
        ]}
    ];
    function element(tag, text, className) {
        const node = document.createElement(tag);
        if (text) node.textContent = text;
        if (className) node.className = className;
        return node;
    }
    function render() {
        const opened = body.querySelector('details[open]')?.dataset.helpTopic;
        const focused = body.contains(document.activeElement) ? document.activeElement.closest('details')?.dataset.helpTopic : null;
        const scroll = body.scrollTop;
        const fragment = document.createDocumentFragment();
        fragment.append(element('p', pick(['Начните с одного занятия. Всё остальное можно настроить позже.', 'Start with one lesson. Set up everything else later.']), 'help-lead'));
        const start = element('section', '', 'help-start');
        start.append(element('h3', pick(['Три шага для начала', 'Three steps to get started'])));
        const list = element('ol', '', 'help-step-list');
        for (const [title, text] of steps) {
            const item = element('li');
            item.append(element('strong', pick(title)), element('span', pick(text)));
            list.append(item);
        }
        start.append(list);
        fragment.append(start, element('h3', pick(['Подробнее — по теме', 'More help by topic']), 'help-topics-title'));
        const sections = element('div', '', 'help-section-list');
        for (const topic of topics) {
            const details = element('details', '', 'help-section');
            details.dataset.helpTopic = topic.id;
            details.name = 'temli-help';
            details.open = topic.id === opened;
            const contents = element('div', '', 'help-section-body');
            const items = element('ul');
            for (const pair of topic.items) items.append(element('li', pick(pair)));
            contents.append(items);
            details.append(element('summary', pick(topic.title)), contents);
            sections.append(details);
        }
        fragment.append(sections);
        body.replaceChildren(fragment);
        if (focused) body.querySelector(`[data-help-topic="${focused}"] summary`)?.focus({preventScroll: true});
        body.scrollTop = scroll;
        overlay.querySelector('h2').textContent = pick(['Как пользоваться TEMLI', 'How to use TEMLI']);
        document.getElementById('btn-close-help').setAttribute('aria-label', pick(['Закрыть', 'Close']));
        updateBack();
    }
    function updateBack() {
        const text = pick(overlay.dataset.returnTo === 'calendar' ? ['Назад в календарь', 'Back to calendar'] : ['Назад в настройки', 'Back to settings']);
        document.getElementById('btn-back-help').setAttribute('aria-label', text);
        document.getElementById('btn-help-back-bottom').textContent = text;
    }
    window.addEventListener('temli-help-open', updateBack);
    window.addEventListener('temli-language-change', render);
    render();
})();
