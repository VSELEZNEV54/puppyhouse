/**
 * Список адресов сайта - из его же карты сайта.
 *
 * Нужен почти всем инструментам: отправить страницы на переобход,
 * прогнать проверку скорости, сверить, что из индекса выпало.
 * Брать список из sitemap правильнее, чем хардкодить: карта генерируется
 * при сборке (@astrojs/sitemap), значит всегда актуальна.
 *
 * Разбор XML без библиотеки: карта сайта - предельно простой формат,
 * регулярного выражения по <loc> достаточно. Ставить парсер XML ради
 * одного тега - лишняя зависимость на пустом месте.
 */

import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { api } from './http.mjs';
import { BUILD_DIR, SITE_URL, SITEMAP_PATH } from './env.mjs';

const LOC = /<loc>\s*([^<\s]+)\s*<\/loc>/g;
const LASTMOD = /<lastmod>\s*([^<\s]+)\s*<\/lastmod>/;

function locations(xml) {
  const out = [];
  let m;
  LOC.lastIndex = 0;
  while ((m = LOC.exec(xml)) !== null) out.push(m[1]);
  return out;
}

/**
 * Все адреса страниц сайта.
 *
 * @param {object} opts
 * @param {boolean} [opts.local] - читать dist/ вместо боевого сайта.
 *   Полезно до деплоя: видно, что уедет в релиз.
 */
export async function siteUrls({ local = false } = {}) {
  if (local) {
    const dist = BUILD_DIR;
    const index = resolve(dist, SITEMAP_PATH.replace(/^\//, ''));
    if (!existsSync(index)) {
      throw new Error(
        `Карты сайта нет по пути ${index} — соберите сайт или поправьте ` +
          '«sitemap» в seo/project.json',
      );
    }
    const urls = [];
    for (const part of locations(readFileSync(index, 'utf8'))) {
      const file = resolve(dist, part.split('/').pop());
      if (existsSync(file)) urls.push(...locations(readFileSync(file, 'utf8')));
    }
    return [...new Set(urls)];
  }

  /* Боевой сайт: индекс карт -> каждая карта -> адреса. */
  const indexXml = await api(`${SITE_URL}${SITEMAP_PATH}`, {
    service: 'sitemap',
    raw: true,
  });

  /* Карта бывает двух видов: индекс со ссылками на другие карты и плоская
     со ссылками на страницы. Отличаем по тегу: у индекса это <sitemap>. */
  const isIndex = /<sitemapindex/i.test(indexXml);
  if (!isIndex) return [...new Set(locations(indexXml))];

  const urls = [];
  for (const part of locations(indexXml)) {
    const xml = await api(part, { service: 'sitemap', raw: true });
    urls.push(...locations(xml));
  }

  return [...new Set(urls)];
}

/** Адреса с датой изменения - чтобы отправлять на переобход только свежее. */
export async function siteUrlsWithDates() {
  const indexXml = await api(`${SITE_URL}${SITEMAP_PATH}`, { service: 'sitemap', raw: true });
  const out = [];

  for (const part of locations(indexXml)) {
    const xml = await api(part, { service: 'sitemap', raw: true });
    for (const block of xml.split('<url>').slice(1)) {
      const loc = /<loc>\s*([^<\s]+)\s*<\/loc>/.exec(block)?.[1];
      if (!loc) continue;
      out.push({ url: loc, lastmod: LASTMOD.exec(block)?.[1] || null });
    }
  }

  return out;
}

/**
 * Разделы сайта - по первому сегменту пути.
 * Нужно для отчетов: смотреть блог отдельно от услуг и кейсов.
 */
export function section(url) {
  try {
    const path = new URL(url).pathname;
    const seg = path.split('/').filter(Boolean)[0];
    if (!seg) return 'главная';
    if (['uslugi', 'portfolio', 'blog', 'kontakty', 'brief'].includes(seg)) return seg;
    return 'статья';
  } catch {
    return '—';
  }
}
