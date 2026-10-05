const path = require('path');
const { chromium } = require('playwright');

const origin = process.argv[2] || 'http://127.0.0.1:8765';
const outputDir = path.resolve(process.argv[3] || 'marketing/screenshots');
const executablePath = process.env.TEMLI_BROWSER_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 }, deviceScaleFactor: 1 });
  for (const view of ['calendar', 'students', 'payments']) {
    await page.goto(`${origin}/demo.html?view=${view}`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(outputDir, `temli-${view}.png`), fullPage: true });
  }
  await browser.close();
  console.log(`Captured calendar, students, and payments screenshots in ${outputDir}`);
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
