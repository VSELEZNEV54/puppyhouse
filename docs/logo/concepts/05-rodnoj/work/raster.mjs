// Rasterize an SVG at an exact pixel size (Chromium, like a browser tab would), for favicon / small-size checks.
//   node raster.mjs in.svg out.png <px> [bg]
import { createRequire } from 'module';
import fs from 'fs';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const [inp, out, px, bg] = process.argv.slice(2);
const n = +px;
const uri = 'data:image/svg+xml;base64,' + Buffer.from(fs.readFileSync(inp)).toString('base64');
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: n, height: n }, deviceScaleFactor: 1 });
await p.setContent(`<!doctype html><style>html,body{margin:0;background:${bg || '#FFFFFF'}}img{display:block}</style><img src="${uri}" width=${n} height=${n}>`, { waitUntil: 'load' });
await p.screenshot({ path: out, clip: { x: 0, y: 0, width: n, height: n } });
await b.close();
