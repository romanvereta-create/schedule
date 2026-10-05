/* Public support contacts for all teachers. A bot username is enough; never add a bot token here. */
(() => {
    'use strict';
    const contacts = {telegramUsername: 'RomanVrt', botUsername: ''};
    // After the owner registers the support bot, put its @username in botUsername.
    const host = document.querySelector('.header-context-actions');
    if (!host || document.getElementById('btn-support')) return;
    const text = (ru, en) => window.TEMLI_I18N?.language() === 'en' ? en : ru;
    const make = (tag, className) => {
        const element = document.createElement(tag);
        if (className) element.className = className;
        return element;
    };
    const button = make('button', 'icon-btn');
    button.id = 'btn-support';
    button.type = 'button';
    button.setAttribute('data-i18n-ignore', '');
    button.setAttribute('aria-haspopup', 'dialog');
    button.setAttribute('aria-controls', 'support-overlay');
    button.innerHTML = '<svg class="thread-icon" aria-hidden="true"><use href="#ti-message"></use></svg>';
    host.append(button);

    const overlay = make('div', 'hidden');
    overlay.id = 'support-overlay';
    overlay.setAttribute('data-i18n-ignore', '');
    const box = make('div', 'modal-content support-modal');
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-labelledby', 'support-title');
    const header = make('header', 'modal-header');
    const title = make('h2');
    title.id = 'support-title';
    const close = make('button', 'close-modal');
    close.type = 'button';
    close.innerHTML = '<svg class="thread-icon" aria-hidden="true"><use href="#ti-close"></use></svg>';
    header.append(title, close);
    const body = make('div', 'modal-body support-body');
    const intro = make('p', 'field-hint');
    const contact = make('a', 'support-contact');
    const bot = make('a', 'support-contact');
    contact.id = 'support-contact-telegram';
    bot.id = 'support-contact-bot';
    function setLink(link, username) {
        const name = String(username || '').trim().replace(/^@/, '');
        const valid = /^[a-zA-Z][a-zA-Z0-9_]{4,31}$/.test(name);
        link.hidden = !valid;
        if (!valid) { link.removeAttribute('href'); return; }
        link.href = 'https://t.me/' + name;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.onclick = event => {
            const telegram = window.Telegram?.WebApp;
            if (typeof telegram?.openTelegramLink !== 'function') return;
            try { telegram.openTelegramLink(link.href); event.preventDefault(); }
            catch (_) { /* The ordinary link remains available. */ }
        };
    }
    setLink(contact, contacts.telegramUsername);
    setLink(bot, contacts.botUsername);
    const version = make('small', 'support-version');
    body.append(intro, contact, bot, version);
    const actions = make('div', 'modal-actions');
    const done = make('button', 'secondary-btn');
    done.type = 'button';
    actions.append(done);
    box.append(header, body, actions);
    overlay.append(box);
    document.body.append(overlay);
    const closeSupport = () => {
        overlay.classList.add('hidden');
        button.focus({preventScroll: true});
    };
    button.onclick = () => {
        document.getElementById('top-next-lesson-details')?.classList.add('hidden');
        document.getElementById('top-next-lesson')?.setAttribute('aria-expanded', 'false');
        overlay.classList.remove('hidden');
        body.scrollTop = 0;
        close.focus({preventScroll: true});
    };
    close.onclick = closeSupport;
    done.onclick = closeSupport;
    overlay.onclick = event => { if (event.target === overlay) closeSupport(); };
    overlay.onkeydown = event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeSupport(); }
        if (event.key !== 'Tab') return;
        const items = [...box.querySelectorAll('button, a[href]')].filter(item => !item.hidden);
        const first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    function render() {
        const label = text('Поддержка', 'Support');
        button.title = label;
        button.setAttribute('aria-label', label);
        title.textContent = text('Поддержка TEMLI', 'TEMLI support');
        intro.textContent = text('Расскажите, что случилось. Если возникла ошибка, приложите скриншот.', 'Tell us what happened. If you encountered an error, include a screenshot.');
        contact.textContent = text('Написать в Telegram', 'Message on Telegram') + ' · @' + contacts.telegramUsername.replace(/^@/, '');
        bot.textContent = text('Бот поддержки', 'Support bot') + ' · @' + contacts.botUsername.replace(/^@/, '');
        close.setAttribute('aria-label', text('Закрыть', 'Close'));
        done.textContent = text('Закрыть', 'Close');
        version.textContent = 'TEMLI ' + (window.TEMLI_I18N?.VERSION || '');
    }
    window.addEventListener('temli-language-change', render);
    render();
})();
