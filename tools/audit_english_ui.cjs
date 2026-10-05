const { chromium } = require('playwright');

const origin = process.argv[2] || 'http://127.0.0.1:8765';
const output = process.argv[3] || '';

function isoDate(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  return value.toISOString().slice(0, 10);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.TEMLI_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  });
  const context = await browser.newContext({ viewport: { width: 430, height: 920 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => {
    localStorage.clear();
    window.Telegram = { WebApp: {
      initData: 'query_id=test&user=%7B%22id%22%3A1001%2C%22language_code%22%3A%22en%22%7D&auth_date=1&hash=test',
      initDataUnsafe: { user: { id: 1001, first_name: 'Alex', language_code: 'en' } },
      expand() {}, ready() {}, close() {}, openLink() {}, openTelegramLink() {},
      HapticFeedback: { impactOccurred() {}, notificationOccurred() {}, selectionChanged() {} },
      BackButton: { show() {}, hide() {}, onClick() {}, offClick() {} },
      MainButton: { show() {}, hide() {}, onClick() {}, offClick() {}, setText() {}, enable() {}, disable() {} },
      themeParams: {}, colorScheme: 'light', viewportHeight: 920, viewportStableHeight: 920,
    }};
  });
  const page = await context.newPage();
  await page.route('https://bot-1789984567-3598-solo1986.bothost.tech/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let payload = { status: 'ok' };
    if (path.endsWith('/eligibility/status')) payload = { status: 'ok', ready: true };
    else if (path.endsWith('/bootstrap')) payload = {
      status: 'ok', onboarding_needed: false,
      settings: {
        language: 'en', currency: 'USD', work_start: '08:00', work_end: '21:00', days_off: [],
        onboarding_completed: true, default_student_reminders: false, parent_lesson_end: false,
        teacher_block_reminders: true, default_send_receipts: true, default_send_receipt_copy: true,
      },
      students: {
        s1: { name: 'Emma Carter', color: 1, price: 42 },
        s2: { name: 'Noah Williams', color: 4, price: 55 },
      },
      schedule: {
        [isoDate(1)]: [{ id: 'l1', student_id: 's1', student_name: 'Emma Carter', time: '10:00', duration: 60, price: 42, paid: true }],
        [isoDate(2)]: [{ id: 'l2', student_id: 's2', student_name: 'Noah Williams', time: '15:30', duration: 90, price: 55, paid: false }],
      },
    };
    else if (path.endsWith('/personal_bot')) payload = { status: 'ok', enabled: true, bot: null };
    else if (path.endsWith('/work_center')) payload = { status: 'ok', debts: [], free_slots: [], birthdays: [], weekly: {} };
    else if (path.endsWith('/pending_bindings')) payload = { status: 'ok', bindings: [] };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) });
  });

  await page.goto(`${origin}/index.html?api_origin=https://bot-1789984567-3598-solo1986.bothost.tech`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.documentElement.lang === 'en' && !document.getElementById('startup-status'));
  const cyrillicLines = [];
  const attributeLeaks = [];
  async function scan(label) {
    const visible = await page.locator('body').innerText();
    for (const line of visible.split(/\r?\n/).map(x => x.trim())) {
      if (/[А-Яа-яЁё]/.test(line) && line !== 'Русский') cyrillicLines.push(`${label}: ${line}`);
    }
    const leaks = await page.evaluate(() => {
    const leaks = [];
    for (const element of document.querySelectorAll('[placeholder], [title], [aria-label]')) {
      if (getComputedStyle(element).display === 'none') continue;
      for (const name of ['placeholder', 'title', 'aria-label']) {
        const value = element.getAttribute(name) || '';
        if (/[А-Яа-яЁё]/.test(value) && value !== 'Русский') leaks.push(`${name}: ${value}`);
      }
    }
    return [...new Set(leaks)];
    });
    attributeLeaks.push(...leaks.map(value => `${label}: ${value}`));
  }

  await scan('calendar');
  await page.click('#btn-app-settings');
  await page.waitForTimeout(250);
  await scan('settings');
  await page.click('#btn-open-receipt-settings');
  await page.waitForTimeout(100);
  await scan('receipt-settings');
  await page.click('#btn-back-receipt-settings');
  await page.click('#btn-open-help');
  await page.waitForTimeout(100);
  await scan('help');
  await page.click('#btn-back-help');
  await page.click('#btn-close-app-settings');
  await page.click('#btn-students');
  await page.waitForTimeout(250);
  await scan('students');
  await page.click('#btn-close-students');
  await page.click('#btn-work-center');
  await page.waitForTimeout(250);
  await scan('assistant');
  await page.click('#btn-close-work-center');
  const uniqueCyrillicLines = [...new Set(cyrillicLines)];
  const uniqueAttributeLeaks = [...new Set(attributeLeaks)];
  if (output) await page.screenshot({ path: output, fullPage: true });
  console.log(JSON.stringify({ cyrillicLines: uniqueCyrillicLines, attributeLeaks: uniqueAttributeLeaks }, null, 2));
  await browser.close();
  if (uniqueCyrillicLines.length || uniqueAttributeLeaks.length) process.exitCode = 2;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
