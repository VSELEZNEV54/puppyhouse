#!/usr/bin/env node
/**
 * Google Search Console - как сайт выглядит в поиске Google.
 *
 *   node seo/cli/gsc.mjs sites               какие ресурсы доступны
 *   node seo/cli/gsc.mjs summary             показы, клики, CTR, позиция
 *   node seo/cli/gsc.mjs queries             по каким запросам находят
 *   node seo/cli/gsc.mjs pages               какие страницы приносят клики
 *   node seo/cli/gsc.mjs opportunities       запросы на 2-3 странице выдачи
 *   node seo/cli/gsc.mjs zero-click          показы есть, кликов нет
 *   node seo/cli/gsc.mjs devices             устройства
 *   node seo/cli/gsc.mjs countries           страны
 *   node seo/cli/gsc.mjs dates               динамика по дням
 *   node seo/cli/gsc.mjs inspect <url>       что Google знает о странице
 *   node seo/cli/gsc.mjs sitemaps            карты сайта и их ошибки
 *   node seo/cli/gsc.mjs submit-sitemap      отдать карту сайта Google
 *
 * Флаги: --days 28 | --from … --to … | --limit 50 | --json
 *
 * Про задержку данных. Search Console показывает статистику с отставанием
 * в 2-3 дня, поэтому «вчера» здесь всегда пусто - это не поломка.
 * По умолчанию период сдвинут на три дня назад.
 */

import { google, serviceAccountEmail } from '../lib/google-auth.mjs';
import { qs } from '../lib/http.mjs';
import { get, SITE_URL } from '../lib/env.mjs';
import {
  args, num, table, title, note, run, ok, warn, fail, pct, ymd, previousPeriod, delta,
} from '../lib/out.mjs';

const API = 'https://searchconsole.googleapis.com/webmasters/v3';
const INSPECT = 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect';

const SCOPE_READ = 'https://www.googleapis.com/auth/webmasters.readonly';
const SCOPE_WRITE = 'https://www.googleapis.com/auth/webmasters';

/**
 * Адрес ресурса в том виде, в каком его завели в кабинете.
 * Два формата, и они не взаимозаменяемы:
 *   https://example.ru/   - ресурс с префиксом URL
 *   sc-domain:example.ru  - ресурс типа «Домен»
 * Ошибётесь форматом - API ответит 403, будто прав нет.
 */
function siteUrl() {
  return get('GSC_SITE_URL', SITE_URL.endsWith('/') ? SITE_URL : SITE_URL + '/');
}

const enc = (s) => encodeURIComponent(s);

/** Период с оглядкой на задержку данных Google. */
function period(a) {
  if (a.from && a.to) return { from: a.from, to: a.to };
  const days = num(a.days, 28);
  const end = new Date();
  end.setUTCDate(end.getUTCDate() - 3);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (days - 1));
  return { from: ymd(start), to: ymd(end) };
}

/** Запрос статистики. */
async function query({ from, to, dimensions = [], limit = 50, filters, type = 'web', startRow = 0 }) {
  const body = {
    startDate: from,
    endDate: to,
    dimensions,
    rowLimit: limit,
    startRow,
    type,
    /* Полные данные, а не свежие-но-неполные: цифры не будут меняться
       задним числом при повторном запросе. */
    dataState: 'final',
  };

  if (filters?.length) {
    body.dimensionFilterGroups = [{ groupType: 'and', filters }];
  }

  const res = await google(`${API}/sites/${enc(siteUrl())}/searchAnalytics/query`, {
    method: 'POST',
    scope: SCOPE_READ,
    service: 'Search Console',
    json: body,
  });

  return (res?.rows ?? []).map((r) => ({
    keys: r.keys ?? [],
    key: (r.keys ?? []).join(' / '),
    clicks: r.clicks ?? 0,
    impressions: r.impressions ?? 0,
    ctr: (r.ctr ?? 0) * 100,
    position: r.position ?? 0,
  }));
}

/**
 * Полная выборка постранично.
 *
 * Google сортирует строки по кликам и обрезает по rowLimit - то есть первым
 * отваливается хвост с нулевыми кликами. А именно он и нужен отчёту
 * «показы есть, кликов нет»: обрезав выдачу, мы отрежем ровно то, что ищем.
 * Потолок API - 25 000 строк за запрос и 50 000 в сутки на сайт.
 */
async function queryAll(opts) {
  const PAGE = 25_000;
  const all = [];

  for (let startRow = 0; startRow < 50_000; startRow += PAGE) {
    const rows = await query({ ...opts, limit: PAGE, startRow });
    all.push(...rows);
    if (rows.length < PAGE) break;
  }

  return all;
}

const STAT_COLS = [
  { key: 'clicks', title: 'Клики', align: 'right' },
  { key: 'impressions', title: 'Показы', align: 'right' },
  { key: 'ctrText', title: 'CTR', align: 'right' },
  { key: 'posText', title: 'Позиция', align: 'right' },
];

const decorate = (rows) =>
  rows.map((r) => ({ ...r, ctrText: pct(r.ctr), posText: r.position.toFixed(1) }));

run(async () => {
  const a = args();
  const { from, to } = period(a);
  const limit = num(a.limit, 50);
  const out = (o) => console.log(JSON.stringify(o, null, 2));

  /* ────────────────────── СПИСОК РЕСУРСОВ ──────────────────────────── */
  if (a.cmd === 'sites') {
    const res = await google(`${API}/sites`, { scope: SCOPE_READ, service: 'Search Console' });
    if (a.json) return out(res);

    const sites = res?.siteEntry ?? [];
    title(`Доступно ресурсов: ${sites.length}`);
    note(`  Сервисный аккаунт: ${serviceAccountEmail()}`);

    if (!sites.length) {
      warn('Ресурсов нет.');
      note('  Сервисный аккаунт нужно добавить в кабинет как пользователя:');
      note('  search.google.com/search-console → Настройки → Пользователи и разрешения');
      note(`  → Добавить пользователя → ${serviceAccountEmail()} → права «Полный доступ»`);
      return;
    }

    table(
      sites.map((s) => ({ u: s.siteUrl, p: s.permissionLevel })),
      [
        { key: 'u', title: 'Ресурс', max: 60 },
        { key: 'p', title: 'Права' },
      ],
    );
    note(`\n  Сейчас инструменты работают с: ${siteUrl()}`);
    note('  Другой ресурс — впишите GSC_SITE_URL в seo/.env');
    return;
  }

  /* ──────────────────────────── СВОДКА ─────────────────────────────── */
  if (!a.cmd || a.cmd === 'summary') {
    const prev = previousPeriod(from, to);
    const [now, before] = await Promise.all([
      query({ from, to, dimensions: [], limit: 1 }),
      query({ from: prev.from, to: prev.to, dimensions: [], limit: 1 }),
    ]);

    const n = now[0] ?? { clicks: 0, impressions: 0, ctr: 0, position: 0 };
    const b = before[0] ?? { clicks: 0, impressions: 0, ctr: 0, position: 0 };

    if (a.json) return out({ period: { from, to }, current: n, previous: b });

    title(`Google Search Console · ${from} — ${to}`);
    note(`  Ресурс: ${siteUrl()}`);
    note(`  Сравнение с ${prev.from} — ${prev.to}`);

    table(
      [
        { m: 'Клики', v: n.clicks, d: delta(n.clicks, b.clicks) },
        { m: 'Показы', v: n.impressions, d: delta(n.impressions, b.impressions) },
        { m: 'CTR', v: pct(n.ctr), d: delta(n.ctr, b.ctr) },
        { m: 'Средняя позиция', v: n.position.toFixed(1), d: delta(b.position, n.position) },
      ],
      [
        { key: 'm', title: 'Показатель' },
        { key: 'v', title: 'Сейчас', align: 'right' },
        { key: 'd', title: 'К прошлому', align: 'right' },
      ],
    );
    note('\n  По позиции рост показан как улучшение: 12,4 → 8,1 это «+».');
    return;
  }

  /* ───────────────────────── РАЗРЕЗЫ ───────────────────────────────── */
  const SIMPLE = {
    queries: { dim: 'query', title: 'Поисковые запросы', col: 'Запрос', max: 60 },
    pages: { dim: 'page', title: 'Страницы', col: 'Страница', max: 60 },
    devices: { dim: 'device', title: 'Устройства', col: 'Устройство', max: 20 },
    countries: { dim: 'country', title: 'Страны', col: 'Страна', max: 20 },
    dates: { dim: 'date', title: 'По дням', col: 'Дата', max: 12 },
  };

  if (SIMPLE[a.cmd]) {
    const cfg = SIMPLE[a.cmd];
    /* Для динамики по дням число строк задаёт длина периода, а не размер
       таблицы: с limit 50 отчёт за квартал молча обрезался бы. */
    const rowLimit =
      a.cmd === 'dates'
        ? Math.max(limit, Math.round((new Date(to) - new Date(from)) / 86_400_000) + 2)
        : limit;
    let rows = await query({ from, to, dimensions: [cfg.dim], limit: rowLimit });
    if (a.json) return out(rows);

    if (a.cmd === 'dates') rows = rows.sort((x, y) => x.key.localeCompare(y.key));
    if (a.cmd === 'pages') rows = rows.map((r) => ({ ...r, key: r.key.replace(/^https?:\/\/[^/]+/, '') }));

    title(`${cfg.title} · ${from} — ${to}`);
    table(decorate(rows), [{ key: 'key', title: cfg.col, max: cfg.max }, ...STAT_COLS]);
    if (!rows.length) {
      note('  Данных нет. Обычные причины: ресурс подтверждён недавно,');
      note('  либо период попал в трёхдневную задержку статистики Google.');
    }
    return;
  }

  /* ──────────────────── ТОЧКИ РОСТА: 2-3 СТРАНИЦА ──────────────────── */
  if (a.cmd === 'opportunities') {
    const rows = await queryAll({ from, to, dimensions: ['query', 'page'] });

    /* Запросы на позициях 8-25: до первой страницы рукой подать.
       Показы уже есть - значит, спрос реальный, а не выдуманный. */
    const near = rows
      .filter((r) => r.position >= 8 && r.position <= 25 && r.impressions >= 10)
      .sort((x, y) => y.impressions - x.impressions)
      .slice(0, limit);

    if (a.json) return out(near);

    title(`Почти на первой странице · ${from} — ${to}`);
    note('  Позиции 8–25 при заметных показах. Дешевле дотянуть это,');
    note('  чем продвигать запрос с нуля.');

    table(
      decorate(near).map((r) => ({
        q: r.keys[0],
        p: (r.keys[1] ?? '').replace(/^https?:\/\/[^/]+/, ''),
        ...r,
      })),
      [
        { key: 'q', title: 'Запрос', max: 42 },
        { key: 'p', title: 'Страница', max: 34 },
        { key: 'impressions', title: 'Показы', align: 'right' },
        { key: 'clicks', title: 'Клики', align: 'right' },
        { key: 'posText', title: 'Позиция', align: 'right' },
      ],
    );
    return;
  }

  /* ───────────────── ПОКАЗЫ БЕЗ КЛИКОВ ─────────────────────────────── */
  if (a.cmd === 'zero-click') {
    const rows = await queryAll({ from, to, dimensions: ['query'] });

    /* Показов много, кликов нет: сниппет не цепляет. Лечится
       заголовком и описанием, а не ссылками. */
    const bad = rows
      .filter((r) => r.impressions >= 20 && r.ctr < 1 && r.position <= 20)
      .sort((x, y) => y.impressions - x.impressions)
      .slice(0, limit);

    if (a.json) return out(bad);

    title(`Показы есть, кликов нет · ${from} — ${to}`);
    note('  Сайт в выдаче виден, но по нему не кликают. Обычно дело');
    note('  в заголовке title и описании description — их и переписывают.');
    table(decorate(bad), [{ key: 'key', title: 'Запрос', max: 60 }, ...STAT_COLS]);
    return;
  }

  /* ─────────────────── ПРОВЕРКА КОНКРЕТНОГО URL ────────────────────── */
  if (a.cmd === 'inspect') {
    const target = a._[0] || a.url;
    if (!target) {
      fail('Укажите адрес: node seo/cli/gsc.mjs inspect https://example.ru/uslugi/');
      process.exit(2);
    }
    const url = target.startsWith('http') ? target : `${SITE_URL}${target.startsWith('/') ? '' : '/'}${target}`;

    const res = await google(INSPECT, {
      method: 'POST',
      scope: SCOPE_READ,
      service: 'Search Console (проверка URL)',
      json: { inspectionUrl: url, siteUrl: siteUrl(), languageCode: 'ru' },
    });

    if (a.json) return out(res);

    const r = res?.inspectionResult ?? {};
    const idx = r.indexStatusResult ?? {};

    title(`Проверка страницы\n  ${url}`);
    table(
      [
        { k: 'В индексе Google', v: idx.coverageState ?? '—' },
        { k: 'Вердикт', v: r.indexStatusResult?.verdict ?? '—' },
        { k: 'Обнаружена через', v: idx.robotsTxtState === 'ALLOWED' ? 'robots.txt разрешает' : idx.robotsTxtState ?? '—' },
        { k: 'Последний обход', v: idx.lastCrawlTime ?? 'ещё не обходили' },
        { k: 'Индексирование разрешено', v: idx.indexingState ?? '—' },
        { k: 'Канонический (наш)', v: idx.userCanonical ?? '—' },
        { k: 'Канонический (Google)', v: idx.googleCanonical ?? '—' },
        { k: 'Микроразметка', v: r.richResultsResult?.verdict ?? 'разметки не найдено' },
      ],
      [
        { key: 'k', title: 'Параметр', max: 30 },
        { key: 'v', title: 'Значение', max: 60 },
      ],
    );

    if (idx.googleCanonical && idx.userCanonical && idx.googleCanonical !== idx.userCanonical) {
      warn('Google выбрал другой канонический адрес, чем указан на странице.');
      note('  Значит, он считает эту страницу дублем другой. Это частая причина');
      note('  «страница не в индексе, хотя всё правильно».');
    }
    return;
  }

  /* ────────────────────────── КАРТЫ САЙТА ──────────────────────────── */
  if (a.cmd === 'sitemaps') {
    const res = await google(`${API}/sites/${enc(siteUrl())}/sitemaps`, {
      scope: SCOPE_READ,
      service: 'Search Console',
    });
    if (a.json) return out(res);

    const maps = res?.sitemap ?? [];
    title(`Карты сайта — ${maps.length}`);

    if (!maps.length) {
      warn('Google не знает ни одной карты сайта.');
      note('  Отдать: node seo/cli/gsc.mjs submit-sitemap');
      return;
    }

    table(
      maps.map((m) => ({
        p: m.path,
        sub: (m.lastSubmitted ?? '').slice(0, 10),
        d: (m.lastDownloaded ?? '').slice(0, 10),
        n: (m.contents ?? []).reduce((s, c) => s + Number(c.submitted ?? 0), 0),
        e: m.errors ?? 0,
        w: m.warnings ?? 0,
      })),
      [
        { key: 'p', title: 'Карта', max: 50 },
        { key: 'sub', title: 'Отдана' },
        { key: 'd', title: 'Скачана' },
        { key: 'n', title: 'Адресов', align: 'right' },
        { key: 'e', title: 'Ошибки', align: 'right' },
        { key: 'w', title: 'Предупр.', align: 'right' },
      ],
    );
    return;
  }

  if (a.cmd === 'submit-sitemap') {
    const map = a.url || `${SITE_URL}/sitemap-index.xml`;
    await google(`${API}/sites/${enc(siteUrl())}/sitemaps/${enc(map)}`, {
      method: 'PUT',
      scope: SCOPE_WRITE,
      service: 'Search Console',
    });
    ok(`Карта сайта отдана Google: ${map}`);
    note('  Проверить обработку: node seo/cli/gsc.mjs sitemaps (через несколько часов)');
    return;
  }

  console.log(`
  Google Search Console — ресурс ${siteUrl()}

    sites            какие ресурсы видит сервисный аккаунт
    summary          клики, показы, CTR, средняя позиция
    queries          по каким запросам находят
    pages            какие страницы приносят клики
    opportunities    запросы на позициях 8–25 — ближайший рост
    zero-click       показы есть, кликов нет — переписать сниппет
    devices          устройства
    countries        страны
    dates            динамика по дням
    inspect <url>    что Google знает о конкретной странице
    sitemaps         карты сайта и ошибки в них
    submit-sitemap   отдать карту сайта

  Флаги: --days 28 | --from … --to … | --limit 50 | --json
`);
});
