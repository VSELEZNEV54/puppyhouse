// node shot.mjs page.html out.png [width] [dark]
import { createRequire } from 'module'; import fs from 'fs';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const [file, out, w = '1280', dark] = process.argv.slice(2);
const body = fs.readFileSync(file, 'utf8');
const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>:root{color-scheme:light}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style></head><body>${body}</body></html>`;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: +w, height: 900 }, colorScheme: dark ? 'dark' : 'light' });
await p.setContent(html, { waitUntil: 'load' });
const sw = await p.evaluate(() => document.documentElement.scrollWidth);
await p.screenshot({ path: out, fullPage: true });
console.log(out, 'scrollWidth', sw, 'viewport', w);
await b.close();
