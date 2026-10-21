// Side-by-side comparison of every concept in ../concepts (one row each) -> ../compare.png
//   node compare.mjs [out.png]
// Row: lockup on the site page colour · inverse on deep navy · mark 96 / 32 / 16 px (+16 px ×4 pixelated) · header mock.
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '..');
const C = path.join(ROOT, 'concepts');
const out = process.argv[2] || path.join(ROOT, 'compare.png');
const read = (p) => (fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null);
const uri = (svg) => 'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64');
const GEIST = path.resolve(HERE, '../../../assets/fonts') + '/';
const f64 = (f) => 'data:font/woff2;base64,' + fs.readFileSync(GEIST + f).toString('base64');

const dirs = fs.readdirSync(C).filter((d) => fs.existsSync(path.join(C, d, 'lockup.svg')) && fs.existsSync(path.join(C, d, 'mark.svg'))).sort();
const rows = dirs.map((d) => {
  const L = read(path.join(C, d, 'lockup.svg')), M = read(path.join(C, d, 'mark.svg'));
  const LI = read(path.join(C, d, 'lockup-inverse.svg')) || L;
  return `<section><h2>${d}</h2><div class=r>
    <div class="c lk" style="background:#F3F2EF"><img src="${uri(L)}"></div>
    <div class="c lk" style="background:#10375C"><img src="${uri(LI)}"></div>
    <div class="c mk"><img src="${uri(M)}" width=96 height=96><img src="${uri(M)}" width=32 height=32><img src="${uri(M)}" width=16 height=16><canvas data-src="${uri(M)}" width=64 height=64></canvas></div>
    <div class="c hd"><div class=pill><img src="${uri(L)}"><span>Каталог щенков</span><span>Породы</span><span>Доставка</span></div></div>
  </div></section>`;
}).join('');
const html = `<!doctype html><meta charset=utf-8><style>
@font-face{font-family:Geist;font-weight:400 500;src:url('${f64('geist-cyrillic.woff2')}') format('woff2');unicode-range:U+0400-045F}
@font-face{font-family:Geist;font-weight:400 500;src:url('${f64('geist-latin.woff2')}') format('woff2');unicode-range:U+0000-00FF,U+2000-206F}
body{margin:0;padding:24px;background:#e9e7e2;font-family:Geist;color:#141414}
h2{font:500 16px Geist;margin:18px 0 8px}
.r{display:grid;grid-template-columns:1fr 1fr 300px 1fr;gap:14px}
.c{border-radius:18px;height:150px;display:flex;align-items:center;justify-content:center;padding:20px;box-sizing:border-box;overflow:hidden}
.lk img{max-width:100%;max-height:100px}
.mk{background:#F3F2EF;gap:14px;align-items:flex-end;justify-content:flex-start}
canvas{image-rendering:pixelated}
.hd{background:#F3F2EF;padding:14px}
.pill{background:#fff;border-radius:18px;height:64px;width:100%;display:flex;align-items:center;gap:16px;padding:0 14px;font:500 13px Geist;white-space:nowrap;overflow:hidden}
.pill img{height:40px;width:auto}
.pill span:nth-of-type(1){color:#FF6F4F}
</style>${rows}
<script>let n=0;const cs=document.querySelectorAll('canvas[data-src]');cs.forEach(c=>{const i=new Image();i.onload=()=>{const t=document.createElement('canvas');t.width=t.height=16;t.getContext('2d').drawImage(i,0,0,16,16);const y=c.getContext('2d');y.imageSmoothingEnabled=false;y.drawImage(t,0,0,16,16,0,0,64,64);if(++n===cs.length)document.body.dataset.done=1};i.src=c.dataset.src;});if(!cs.length)document.body.dataset.done=1;</script>`;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
await p.setContent(html, { waitUntil: 'load' });
await p.evaluate(() => document.fonts.ready);
await p.waitForFunction(() => document.body.dataset.done, null, { timeout: 8000 }).catch(() => {});
await p.screenshot({ path: out, fullPage: true });
await b.close();
console.log(out, dirs.length + ' concepts');
