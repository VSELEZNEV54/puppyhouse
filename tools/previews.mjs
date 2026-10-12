// Снимает первый экран каждого варианта для карточек на корневой странице.
// Запуск: node tools/previews.mjs [baseUrl=http://127.0.0.1:8765]
// Нужен playwright-core (PLAYWRIGHT_CORE=путь к модулю, если не установлен локально).
import { mkdirSync } from 'node:fs';
const mod = process.env.PLAYWRIGHT_CORE || 'playwright-core';
const { chromium } = await import(mod);
const base = process.argv[2] || 'http://127.0.0.1:8765';
const args = process.env.HTTPS_PROXY ? [`--proxy-server=${process.env.HTTPS_PROXY}`, '--proxy-bypass-list=127.0.0.1;localhost'] : [];
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args });
mkdirSync('assets/previews', { recursive: true });
for (const v of ['variant-a', 'variant-b', 'variant-c']) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(`${base}/${v}/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  await page.screenshot({ path: `assets/previews/${v}.jpg`, type: 'jpeg', quality: 78 });
  await page.close();
  console.log(`assets/previews/${v}.jpg`);
}
await browser.close();
