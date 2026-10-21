// Render logo SVGs to PNG with Chromium, so you can LOOK at them (Read the PNG).
//
//   node proof.mjs <concept_dir>            -> <concept_dir>/proof.png  (full proof sheet)
//   node proof.mjs --one file.svg out.png [--w 1200] [--bg "#F3F2EF"]   -> a single SVG on a background
//
// The concept dir must hold: lockup.svg (light bg), mark.svg (square icon).
// Optional: lockup-inverse.svg (dark bg), stacked.svg, wordmark.svg, badge.svg, extra-*.svg (shown at the end).
// The sheet shows: the lockup big on the site page colour, on white, inverse on dark ink and on deep navy;
// the mark at 512 / 180 / 64 / 32 / 16 px (+ 16 and 32 px enlarged ×4 to judge pixel legibility);
// a website header mock (white pill, 40 px tall logo, nav links) at desktop and phone width;
// a social avatar circle crop; a black-and-white (single colour) test.
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const args = process.argv.slice(2);
const read = (p) => (fs.existsSync(p) ? fs.readFileSync(p, 'utf8') : null);
const uri = (svg) => 'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64');
const GEIST = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../assets/fonts') + '/';

async function shot(html, out, width, height = null) {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width, height: height || 800 }, deviceScaleFactor: 1 });
  await p.setContent(html, { waitUntil: 'load' });
  await p.evaluate(() => document.fonts.ready);
  await p.screenshot({ path: out, fullPage: !height });
  await b.close();
}

const f64 = (f) => 'data:font/woff2;base64,' + fs.readFileSync(GEIST + f).toString('base64');
const fontCss = `@font-face{font-family:Geist;font-weight:400 500;src:url('${f64('geist-cyrillic.woff2')}') format('woff2');unicode-range:U+0400-045F}
@font-face{font-family:Geist;font-weight:400 500;src:url('${f64('geist-latin.woff2')}') format('woff2');unicode-range:U+0000-00FF,U+2000-206F}
body{margin:0;font-family:Geist,system-ui,sans-serif;color:#141414;background:#e9e7e2}
.lbl{font:500 13px Geist;color:#6b6b6b;margin:0 0 8px}
.row{display:flex;gap:24px;align-items:stretch;margin:0 0 24px}
.card{border-radius:24px;padding:40px;display:grid;place-items:center;box-sizing:border-box}
.big img{max-width:100%;max-height:260px}
.wrap{padding:32px}
h1{font:500 22px Geist;margin:0 0 20px}
`;

async function sheet(dir) {
  const L = read(path.join(dir, 'lockup.svg'));
  const M = read(path.join(dir, 'mark.svg'));
  if (!L || !M) { console.error('need lockup.svg and mark.svg in ' + dir); process.exit(2); }
  const LI = read(path.join(dir, 'lockup-inverse.svg')) || L;
  const ST = read(path.join(dir, 'stacked.svg'));
  const LM = read(path.join(dir, 'lockup-mono.svg'));
  const MM = read(path.join(dir, 'mark-mono.svg'));
  const extras = fs.readdirSync(dir).filter((f) => /^(wordmark|badge|extra-.*)\.svg$/.test(f));
  const sizes = [400, 180, 64, 32, 16];
  const html = `<!doctype html><meta charset=utf-8><style>${fontCss}
  .hdr{background:#F3F2EF;padding:22px;border-radius:24px}
  .pill{background:#fff;border-radius:22px;height:68px;display:flex;align-items:center;gap:28px;padding:0 18px;box-shadow:0 14px 40px -24px rgba(20,20,20,.35)}
  .pill img{height:40px;width:auto;display:block}
  .nav{display:flex;gap:22px;font:500 15px Geist;color:#141414;flex:1}
  .nav span:first-child{color:#FF6F4F}
  .btn{background:#FF967C;border-radius:999px;padding:12px 20px;font:500 15px Geist}
  .phone{width:390px}
  .phone .pill{height:60px;gap:12px}
  .phone .pill img{height:34px}
  .burger{margin-left:auto;width:44px;height:44px;border-radius:50%;background:#F3F2EF}
  .marks{display:flex;flex-wrap:wrap;gap:28px;align-items:flex-end;background:#F3F2EF;border-radius:24px;padding:32px}
  .marks figure{margin:0;text-align:center;font:400 12px Geist;color:#6b6b6b}
  .px{image-rendering:pixelated}
  .tab{white-space:nowrap;display:inline-flex;align-items:center;gap:8px;background:#fff;border-radius:10px 10px 0 0;padding:8px 14px;font:400 13px Geist}
  .avatar{width:180px;height:180px;border-radius:50%;overflow:hidden;background:#fff;display:grid;place-items:center}
  .avatar img{width:100%;height:100%;object-fit:cover}
  </style><div class=wrap>
  <h1>${path.basename(dir)} — proof</h1>
  <p class=lbl>1 · lockup on site page colour #F3F2EF / on white</p>
  <div class=row><div class="card big" style="flex:1;background:#F3F2EF"><img src="${uri(L)}"></div><div class="card big" style="flex:1;background:#fff"><img src="${uri(L)}"></div></div>
  <p class=lbl>2 · inverse on ink #141414 / on deep navy #10375C / on coral #FF967C</p>
  <div class=row><div class="card big" style="flex:1;background:#141414"><img src="${uri(LI)}"></div><div class="card big" style="flex:1;background:#10375C"><img src="${uri(LI)}"></div><div class="card big" style="flex:1;background:#FF967C"><img src="${uri(L)}"></div></div>
  <p class=lbl>3 · website header (logo 40 px tall) — desktop and phone</p>
  <div class=row><div class=hdr style="flex:1"><div class=pill><img src="${uri(L)}"><div class=nav><span>Каталог щенков</span><span>Породы</span><span>Доставка</span><span>Отзывы</span></div><span class=btn>Оставить заявку</span></div></div>
  <div class="hdr phone"><div class=pill><img src="${uri(L)}"><span class=burger></span></div></div></div>
  <p class=lbl>4 · mark: 400 · 180 · 64 · 32 · 16 px, then 32 and 16 px enlarged ×4 (pixel legibility), browser tab, social avatar</p>
  <div class=marks>${sizes.map((s) => `<figure><img src="${uri(M)}" width=${s} height=${s}><figcaption>${s}</figcaption></figure>`).join('')}
    <figure><canvas class=px data-s=32 width=128 height=128></canvas><figcaption>32 ×4</figcaption></figure>
    <figure><canvas class=px data-s=16 width=64 height=64></canvas><figcaption>16 ×4</figcaption></figure>
    <figure><span class=tab><img src="${uri(M)}" width=16 height=16>Щенки мальтипу | домщенков.рф</span><figcaption>tab</figcaption></figure>
    <figure><div class=avatar><img src="${uri(M)}"></div><figcaption>avatar</figcaption></figure>
  </div>
  <p class=lbl style="margin-top:24px">5 · ${LM || MM ? 'single-colour versions (lockup-mono.svg / mark-mono.svg)' : 'NO lockup-mono.svg / mark-mono.svg — showing greyscale of the colour files (value-contrast test only)'}</p>
  <div class=row><div class="card big" style="flex:2;background:#fff"><img src="${uri(LM || L)}" style="${LM ? '' : 'filter:grayscale(1)'}"></div><div class="card big" style="flex:1;background:#fff"><img src="${uri(MM || M)}" width=160 style="${MM ? '' : 'filter:grayscale(1)'}"></div></div>
  ${ST ? `<p class=lbl>6 · stacked</p><div class=row><div class="card big" style="flex:1;background:#F3F2EF"><img src="${uri(ST)}"></div><div class="card big" style="flex:1;background:#141414"><img src="${uri(ST)}"></div></div>` : ''}
  ${extras.map((f) => `<p class=lbl>${f}</p><div class=row><div class="card big" style="flex:1;background:#F3F2EF"><img src="${uri(read(path.join(dir, f)))}"></div></div>`).join('')}
  </div>
  <script>
  const src=${JSON.stringify(uri(M))};
  document.querySelectorAll('canvas[data-s]').forEach(c=>{const s=+c.dataset.s;const i=new Image();i.onload=()=>{const t=document.createElement('canvas');t.width=t.height=s;const x=t.getContext('2d');x.drawImage(i,0,0,s,s);const y=c.getContext('2d');y.imageSmoothingEnabled=false;y.drawImage(t,0,0,s,s,0,0,c.width,c.height);document.body.dataset.done=(+(document.body.dataset.done||0)+1)};i.src=src;});
  </script>`;
  const out = path.join(dir, 'proof.png');
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
  await p.setContent(html, { waitUntil: 'load' });
  await p.evaluate(() => document.fonts.ready);
  await p.waitForFunction(() => +(document.body.dataset.done || 0) >= 2, null, { timeout: 5000 }).catch(() => {});
  await p.screenshot({ path: out, fullPage: true });
  await b.close();
  console.log(out);
}

if (args[0] === '--one') {
  const [, file, out] = args;
  const w = +(args[args.indexOf('--w') + 1] || 0) || 1200;
  const bg = args.includes('--bg') ? args[args.indexOf('--bg') + 1] : '#F3F2EF';
  const svg = read(file);
  await shot(`<!doctype html><style>body{margin:0;background:${bg}}div{padding:40px;display:grid;place-items:center}img{width:${w - 80}px;height:auto}</style><div><img src="${uri(svg)}"></div>`, out, w);
  console.log(out);
} else if (args[0]) {
  await sheet(args[0]);
} else {
  console.error('usage: node proof.mjs <concept_dir> | --one file.svg out.png [--w 1200] [--bg #hex]');
  process.exit(2);
}
