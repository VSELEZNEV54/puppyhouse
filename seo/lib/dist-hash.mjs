/**
 * Какие страницы реально изменились после сборки.
 *
 * Зачем. IndexNow и переобход в Вебмастере просят слать ТОЛЬКО изменённые
 * адреса. Отправлять весь сайт при каждом деплое - и бесполезно (робот
 * увидит те же страницы), и вредно: Яндекс прямо называет это поведением
 * спамера, а квота переобхода тратится впустую.
 *
 * Как считаем. После сборки берём каждый HTML в dist/, считаем sha1 от
 * содержимого и сравниваем со снимком прошлой сборки в seo/data/.
 * Что не совпало или чего раньше не было - то и изменилось.
 *
 * Список страниц берём не из файлов, а из карты сайта. Разница
 * принципиальная: в dist/ помимо 82 страниц лежат ещё 68 заглушек
 * редиректов со старых адресов Tilda - они помечены noindex и ведут
 * на настоящую статью. Отправить такую заглушку в поисковик - значит
 * попросить проиндексировать пустышку. Карта сайта - единственный
 * авторитетный список того, что вообще должно быть в индексе.
 *
 * Из содержимого перед хешированием вырезаем то, что меняется само по себе
 * при каждой сборке (даты сборки, хеши в именах ассетов не трогаем -
 * они меняются только при реальном изменении ассета). Иначе после любой
 * пересборки "изменившимися" оказались бы все 82 страницы сразу.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { resolve, join, relative } from 'node:path';
import { createHash } from 'node:crypto';
import { BUILD_DIR, SEO_DIR, SITE_URL, SITEMAP_PATH } from './env.mjs';

const DIST = BUILD_DIR;
const DATA = resolve(SEO_DIR, 'data');
const SNAPSHOT = resolve(DATA, 'dist-hashes.json');

/** Все .html внутри dist, рекурсивно. */
function htmlFiles(dir, acc = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    const st = statSync(path);
    if (st.isDirectory()) htmlFiles(path, acc);
    else if (name.endsWith('.html')) acc.push(path);
  }
  return acc;
}

/** Хеш содержимого без шумовых различий между сборками. */
function hashOf(path) {
  let html = readFileSync(path, 'utf8');

  /* Даты генерации и служебные метки Astro меняются при каждой сборке
     и к содержанию страницы отношения не имеют. */
  html = html
    .replace(/<meta name="generator"[^>]*>/g, '')
    .replace(/"dateModified"\s*:\s*"[^"]*"/g, '')
    .replace(/data-astro-[a-z-]+="[^"]*"/g, '');

  return createHash('sha1').update(html).digest('hex');
}

/** Путь файла в dist -> адрес страницы на сайте. */
export function fileToUrl(path) {
  let rel = relative(DIST, path).replace(/\\/g, '/');
  /* Только целый сегмент: без якоря на границу «blog/pageindex.html»
     превратился бы в «/blog/page» - адрес, которого на сайте нет. */
  rel = rel.replace(/(^|\/)index\.html$/, '$1');
  if (rel && !rel.endsWith('/')) rel = rel.replace(/\.html$/, '/');
  return `${SITE_URL}/${rel}`.replace(/\/+$/, '/').replace(`${SITE_URL}//`, `${SITE_URL}/`);
}


/**
 * Адреса из собранной карты сайта - список того, что должно быть в индексе.
 * Читаем локальный dist, а не боевой сайт: сравниваем именно то, что
 * собрано сейчас, ещё до деплоя.
 */
function sitemapUrls() {
  const index = resolve(DIST, SITEMAP_PATH.replace(/^\//, ''));
  if (!existsSync(index)) {
    throw new Error(
      `Карты сайта нет по пути ${index} — сборка неполная либо в ` +
        'seo/project.json неверно указан «sitemap».',
    );
  }

  const urls = new Set();
  const LOC_ONE = /<loc>\s*([^<\s]+)\s*<\/loc>/g;

  const locs = (xml) => {
    const out = [];
    let m;
    LOC_ONE.lastIndex = 0;
    while ((m = LOC_ONE.exec(xml)) !== null) out.push(m[1]);
    return out;
  };

  const xml = readFileSync(index, 'utf8');

  /* Плоская карта - адреса лежат прямо в ней, вложенных файлов нет. */
  if (!/<sitemapindex/i.test(xml)) {
    for (const u of locs(xml)) urls.add(u);
    return urls;
  }

  for (const part of locs(xml)) {
    const file = resolve(DIST, part.split('/').pop());
    if (existsSync(file)) for (const u of locs(readFileSync(file, 'utf8'))) urls.add(u);
  }

  return urls;
}

/** Снимок прошлой сборки. */
function readSnapshot() {
  if (!existsSync(SNAPSHOT)) return null;
  try {
    return JSON.parse(readFileSync(SNAPSHOT, 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Что изменилось с прошлого снимка.
 * @returns {{first:boolean, changed:string[], added:string[], removed:string[], total:number}}
 */
export function changedPages() {
  if (!existsSync(DIST)) {
    throw new Error(`Папки со сборкой нет: ${DIST}`);
  }

  const indexable = sitemapUrls();

  const now = {};
  for (const file of htmlFiles(DIST)) {
    const url = fileToUrl(file);
    /* Всё, чего нет в карте сайта: заглушки редиректов, 404-я,
       файлы подтверждения прав. В индекс им не надо. */
    if (!indexable.has(url)) continue;
    now[url] = hashOf(file);
  }

  const before = readSnapshot();
  const total = Object.keys(now).length;

  if (!before) {
    return { first: true, changed: [], added: Object.keys(now), removed: [], total, snapshot: now };
  }

  const changed = [];
  const added = [];
  for (const [url, h] of Object.entries(now)) {
    if (!(url in before.pages)) added.push(url);
    else if (before.pages[url] !== h) changed.push(url);
  }
  const removed = Object.keys(before.pages).filter((u) => !(u in now));

  return { first: false, changed, added, removed, total, snapshot: now };
}

/** Запомнить текущее состояние как эталон. */
export function saveSnapshot(pages) {
  if (!existsSync(DATA)) mkdirSync(DATA, { recursive: true });
  writeFileSync(
    SNAPSHOT,
    JSON.stringify({ at: new Date().toISOString(), pages }, null, 2),
    'utf8',
  );
}

export const SNAPSHOT_PATH = SNAPSHOT;
