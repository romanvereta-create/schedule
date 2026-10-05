(() => {
    function show(view) {
        document.querySelectorAll('[data-panel]').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === view));
        document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === view));
        const url = new URL(window.location.href);
        url.searchParams.set('view', view);
        history.replaceState(null, '', url);
    }
    document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => show(button.dataset.view)));
    const requested = new URLSearchParams(location.search).get('view');
    show(['calendar', 'students', 'payments'].includes(requested) ? requested : 'calendar');
})();
