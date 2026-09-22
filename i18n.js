(() => {
    const VERSION = '1.0.0';
    const LANGUAGES = {
        ru: { label: 'Русский', locale: 'ru-RU', currency: 'RUB' },
        en: { label: 'English', locale: 'en-US', currency: 'USD' },
    };
    const CURRENCIES = {
        RUB: { symbol: '₽', label: 'RUB — ₽' },
        USD: { symbol: '$', label: 'USD — $' },
        EUR: { symbol: '€', label: 'EUR — €' },
        CNY: { symbol: '¥', label: 'CNY — ¥' },
        TRY: { symbol: '₺', label: 'TRY — ₺' }
    };
    const dictionaries = { ru: {} };
    const supplementalDictionaries = { en: {
        'Занятия и оплаты': 'Lessons and payments',
        'Оплачено / проведено': 'Paid / completed',
        'Распределить общую сумму': 'Allocate payment',
        'Отменено': 'Cancelled',
        'В календаре': 'Show in calendar',
        'Следующее занятие': 'Next lesson',
        'Сначала старые долги, затем будущие занятия. Учитываются индивидуальные и групповые занятия по их стоимости.': 'Oldest unpaid lessons first, then future lessons. Both individual and group lessons are included at their own prices.',
        'Пока нет четырёх неоплаченных занятий с указанной ценой. Можно внести другую сумму — начиная со старых долгов.': 'Fewer than four unpaid lessons have a price. You can enter another amount, starting with the oldest debt.',
        'Что добавить?': 'What would you like to add?',
        'Занятие с учеником': 'Individual lesson',
        'Групповое занятие': 'Group lesson',
        'Добавить групповое занятие': 'Add group lesson',
        'Личное дело': 'Personal event',
        'Добавить личное дело': 'Add personal event',
        'Название': 'Title',
        'Заметки': 'Notes',
        'Необязательно': 'Optional',
        'Например: врач, встреча, дорога': 'For example: appointment, meeting, travel',
        'Заметки видны только владельцу расписания.': 'Notes are visible only to the schedule owner.',
        'Без заметок': 'No notes',
        'Изменить': 'Edit',
        'Личное дело в выходной': 'Personal event on a day off',
        'Это ваш выходной день. Всё равно добавить личное дело?': 'This is your day off. Add the personal event anyway?',
        'Перенос в выходной': 'Move to a day off',
        'Кажется, календарь рассчитывал отдохнуть 😄 Всё равно перенести занятие на выходной?': 'Looks like the calendar was planning to rest 😄 Move the lesson to a day off anyway?',
        'Всё равно перенести': 'Move anyway',
        'Выходной: потребуется подтверждение': 'Day off: confirmation required',
        'Время занято или недоступно': 'This time is occupied or unavailable',
        'Время начала': 'Start time',
        'Быстрый выбор минут': 'Quick minute selection',
        'Уменьшить время на 5 минут': 'Move time back by 5 minutes',
        'Увеличить время на 5 минут': 'Move time forward by 5 minutes',
        'Новое время занятия': 'New lesson time',
        'Перенести сюда': 'Move here',
        'Действие с личным делом': 'Personal event action',
        'Добавить ещё одним личным делом': 'Add another personal event',
        'Удаление личного дела': 'Delete personal event',
        'Как удалить личное дело?': 'How should this personal event be deleted?',
        'Удалить только это личное дело': 'Delete only this personal event',
        'Удалить все будущие повторы': 'Delete all future occurrences'
        ,'Личные дела': 'Personal events'
        ,'Нажмите свободный слот и выберите «Личное дело». Укажите название, время, длительность и при необходимости заметки.': 'Tap an empty slot and choose “Personal event”. Enter a title, time, duration, and optional notes.'
        ,'Нажмите свободный слот и выберите': 'Tap an empty slot and choose'
        ,'«Личное дело»': '“Personal event”'
        ,'. Укажите название, время, длительность и при необходимости заметки.': '. Enter a title, time, duration, and optional notes.'
        ,'Личное дело занимает время и исключается из свободных окон, но не связано с учениками, оплатами и уведомлениями.': 'A personal event blocks its time in available windows but is not connected to students, payments, or notifications.'
        ,'Заметки видны только владельцу расписания и не показываются прямо на календарной карточке.': 'Notes are visible only to the schedule owner and are not shown directly on the calendar card.'
        ,'Личный бот и уведомления': 'Personal bot and notifications'
        ,'Сообщения ученикам и родителям отправляются через личного бота преподавателя. Подключите его в настройках, а получателей подтвердите в карточке ученика.': 'Messages to students and parents are sent through the teacher’s personal bot. Connect it in settings and confirm recipients in the student profile.'
        ,'Контакты и привязка к боту': 'Contacts and bot connection'
        ,'Добавить контакт.': 'Add a contact.'
        ,'Добавить контакт': 'Add a contact'
        ,'Нажмите кнопку с двумя человечками в верхней строке, выберите ученика и откройте его карточку. В блоке «Контакт ученика» нажмите «Добавить контакт», выберите Telegram и укажите': 'Tap the two-person button in the top bar, select a student, and open the student profile. Under “Student contact”, tap “Add contact”, choose Telegram, and enter'
        ,'или цифровой Telegram ID. Для родителя используйте соседний блок «Контакт родителя». Затем нажмите «Сохранить».': 'or a numeric Telegram ID. Use the adjacent “Parent contact” section for a parent. Then tap “Save”.'
        ,'Подключить личного бота.': 'Connect your personal bot.'
        ,'Сначала откройте «Настройки» → «Мой бот» и убедитесь, что бот подключён.': 'First open “Settings” → “My bot” and make sure the bot is connected.'
        ,'Создать приглашение.': 'Create an invitation.'
        ,'Вернитесь в карточку ученика, раскройте «Пригласить в моего бота» и нажмите «Ссылка ученику» либо «Ссылка родителю».': 'Return to the student profile, expand “Invite to my bot”, and tap “Student invitation” or “Parent invitation”.'
        ,'Завершить привязку.': 'Complete the connection.'
        ,'Скопируйте ссылку и отправьте её нужному человеку. Он должен открыть её и нажать': 'Copy the link and send it to the intended person. They must open it and tap'
        ,'в Telegram.': 'in Telegram.'
        ,'Подтвердить получателя.': 'Confirm the recipient.'
        ,'В карточке ученика нажмите «Обновить привязки» и подтвердите появившийся аккаунт. Только подтверждённая привязка получает уведомления.': 'In the student profile, tap “Refresh connections” and confirm the account that appears. Only a confirmed connection receives notifications.'
        ,'Контакт и привязка — разные вещи: контакт нужен для быстрого перехода к переписке, а подтверждённая привязка позволяет личному боту отправлять уведомления.': 'A contact and a bot connection are different: a contact opens the chat quickly, while a confirmed connection lets the personal bot send notifications.'
        ,'Строка над календарём собрана по одной логике:': 'The row above the calendar contains:'
        ,'выбор даты, стрелки назад/вперёд и режимы «День» / «Неделя». В режиме дня стрелки листают дни, в режиме недели — недели.': 'date picker, previous/next buttons, and Day / Week modes. In Day mode the arrows move by day; in Week mode they move by week.'
        ,', выбор даты, стрелки назад/вперёд и режимы «День» / «Неделя». В режиме дня стрелки листают дни, в режиме недели — недели.': ', date picker, previous/next buttons, and Day / Week modes. In Day mode the arrows move by day; in Week mode they move by week.'
        ,'сначала закрывает самые старые неоплаченные занятия, включая участие в группах, и только затем будущие.': 'covers the oldest unpaid lessons first, including group participation, and only then future lessons.'
    } };
    const dictionaryEntries = { ru: [] };
    const loading = {};
    const textState = new WeakMap();
    const attrState = new WeakMap();
    let language = localStorage.getItem('temli-language') || 'ru';
    let currency = localStorage.getItem('temli-currency') || 'RUB';
    if (!LANGUAGES[language]) language = 'ru';
    if (!CURRENCIES[currency]) currency = 'RUB';

    function currencySymbol() {
        return CURRENCIES[currency]?.symbol || '₽';
    }

    function replaceCurrency(value) {
        return String(value ?? '')
            .replaceAll('₽', currencySymbol())
            .replace(/\bруб\.?\b/giu, currencySymbol());
    }

    function translated(value, { fragments = true } = {}) {
        const source = String(value ?? '');
        if (!source || language === 'ru') return replaceCurrency(source);
        const dictionary = dictionaries[language] || {};
        const leading = source.match(/^\s*/)?.[0] || '';
        const trailing = source.match(/\s*$/)?.[0] || '';
        const core = source.slice(leading.length, source.length - trailing.length);
        let result = dictionary[core];
        if (result == null) {
            result = core;
            if (fragments) {
                for (const [from, to] of (dictionaryEntries[language] || [])) {
                    if (result.includes(from)) result = result.split(from).join(to);
                }
            }
        }
        return leading + replaceCurrency(result) + trailing;
    }

    function shouldSkip(node) {
        const parent = node.parentElement;
        return !parent || Boolean(parent.closest('script, style, svg, [data-i18n-ignore]'));
    }

    function translateTextNode(node) {
        if (shouldSkip(node) || !node.nodeValue?.trim()) return;
        let record = textState.get(node);
        if (!record) record = { source: node.nodeValue, last: node.nodeValue };
        else if (node.nodeValue !== record.last) record.source = node.nodeValue;
        const next = translated(record.source);
        record.last = next;
        textState.set(node, record);
        if (node.nodeValue !== next) node.nodeValue = next;
    }

    function translateAttributes(element) {
        if (!(element instanceof Element) || element.closest('script, style, svg, [data-i18n-ignore]')) return;
        let records = attrState.get(element);
        if (!records) records = {};
        for (const name of ['placeholder', 'title', 'aria-label']) {
            if (!element.hasAttribute(name)) continue;
            const current = element.getAttribute(name) || '';
            let record = records[name];
            if (!record) record = { source: current, last: current };
            else if (current !== record.last) record.source = current;
            const next = translated(record.source);
            record.last = next;
            records[name] = record;
            if (current !== next) element.setAttribute(name, next);
        }
        attrState.set(element, records);
    }

    function apply(root = document.body) {
        if (!root) return;
        if (root.nodeType === Node.TEXT_NODE) {
            translateTextNode(root);
            return;
        }
        if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
        if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
            if (walker.currentNode.nodeType === Node.TEXT_NODE) translateTextNode(walker.currentNode);
            else translateAttributes(walker.currentNode);
        }
        document.documentElement.lang = language;
        const dateInputLanguage = language === 'en' ? 'en-US' : 'ru-RU';
        document.querySelectorAll('input[type="date"]').forEach(input => { input.lang = dateInputLanguage; });
        document.title = translated('TEMLI — расписание');
    }

    function register(code, dictionary) {
        if (LANGUAGES[code] && dictionary && typeof dictionary === 'object') {
            dictionaries[code] = { ...(supplementalDictionaries[code] || {}), ...dictionary };
            dictionaryEntries[code] = Object.entries(dictionary)
                .filter(([from]) => from.length >= 3)
                .sort((a, b) => b[0].length - a[0].length);
        }
    }

    function ensureLanguage(code) {
        if (code === 'ru' || dictionaries[code]) return Promise.resolve();
        if (loading[code]) return loading[code];
        loading[code] = new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = `locales/${code}.js?v=${VERSION}`;
            const timer = setTimeout(() => finish(new Error(`Locale ${code} timed out`)), 15000);
            function finish(error) {
                clearTimeout(timer);
                script.onload = script.onerror = null;
                if (error) { script.remove(); delete loading[code]; reject(error); }
                else resolve();
            }
            script.onload = () => finish(dictionaries[code] ? null : new Error(`Locale ${code} is invalid`));
            script.onerror = () => finish(new Error(`Locale ${code} could not be loaded`));
            document.head.appendChild(script);
        });
        return loading[code];
    }

    async function setLanguage(code, { persist = true } = {}) {
        const safeCode = LANGUAGES[code] ? code : 'ru';
        await ensureLanguage(safeCode);
        language = safeCode;
        if (persist) localStorage.setItem('temli-language', safeCode);
        apply();
        window.dispatchEvent(new CustomEvent('temli-language-change', { detail: { language } }));
        return language;
    }

    function setCurrency(code, { persist = true } = {}) {
        currency = CURRENCIES[code] ? code : 'RUB';
        if (persist) localStorage.setItem('temli-currency', currency);
        document.documentElement.style.setProperty('--currency-symbol', `"${currencySymbol()}"`);
        apply();
        return currency;
    }

    function formatNumber(value, options = {}) {
        return Number(value || 0).toLocaleString(LANGUAGES[language]?.locale || 'ru-RU', options);
    }

    const nativeAlert = window.alert.bind(window);
    const nativeConfirm = window.confirm.bind(window);
    window.alert = message => nativeAlert(translated(message, { fragments: false }));
    window.confirm = message => nativeConfirm(translated(message, { fragments: false }));

    const observer = new MutationObserver(mutations => {
        for (const mutation of mutations) {
            if (mutation.type === 'characterData') translateTextNode(mutation.target);
            else {
                for (const node of mutation.addedNodes) apply(node);
                if (mutation.type === 'attributes') translateAttributes(mutation.target);
            }
        }
    });
    let initialized = false;
    function initialize() {
        if (initialized) return;
        initialized = true;
        document.documentElement.style.setProperty('--currency-symbol', `"${currencySymbol()}"`);
        apply();
        observer.observe(document.body, {
            subtree: true,
            childList: true,
            characterData: true,
            attributes: true,
            attributeFilter: ['placeholder', 'title', 'aria-label']
        });
        setLanguage(language).catch(error => console.warn('TEMLI locale:', error));
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }

    window.TEMLI_I18N = {
        VERSION, LANGUAGES, CURRENCIES, register, apply, translated,
        setLanguage, setCurrency, language: () => language,
        currency: () => currency, currencySymbol,
        locale: () => LANGUAGES[language]?.locale || 'ru-RU',
        recommendedCurrency: code => LANGUAGES[code]?.currency || 'RUB',
        formatNumber
    };
})();
