#!/usr/bin/env node
/**
 * Сводка по сайту: всё, что видно из подключённых сервисов, одной командой.
 *
 *   node seo/cli/report.mjs               за 28 дней
 *   node seo/cli/report.mjs --days 7      за неделю
 *   node seo/cli/report.mjs --save        плюс снимок в seo/data/ для истории
 *   node seo/cli/report.mjs --json
 *
 * Что делает и чего не делает. Отчёт СОБИРАЕТ факты и показывает, куда
 * смотреть; выводы и правки - отдельная работа. Каждый блок независим:
 * не подключён сервис или отвалился токен - остальные всё равно соберутся,
 * а про пропуск будет сказано прямо.
 *
 * Про --save. У данных короткая память: связка «запрос → страница»
 * в Вебмастере хранится две недели, история Search Console - шестнадцать
 * месяцев скользящим окном. Через год сравнить будет не с чем, если не
 * складывать выгрузки самому. Снимки ложатся в seo/data/ (папка вне git,
 * там данные, а не код) - раз в неделю этого достаточно.
 */

import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { has, get, SEO_DIR, SITE_HOST, SITE_URL } from '../lib/env.mjs';
import { api, qs } from '../lib/http.mjs';
import { yandexApi } from '../lib/yandex.mjs';
import { google } from '../lib/google-auth.mjs';
import {
  args, num, table, title, note, run, ok, warn, fail, pct, lastDays, previousPeriod, delta, fmt,
} from '../lib/out.mjs';

const GSC = 'https://searchconsole.googleapis.com/webmasters/v3';
const WM = 'https://api.webmaster.yandex.net/v4';
const SCOPE = 'https://www.googleapis.com/auth/webmasters.readonly';

/** Блок отчёта: если сервиса нет - молча пропускаем, но говорим об этом. */
async function block(name, ready, fn) {
  if (!ready) return { name, skipped: 'не подключено' };
  try {
    return { name, data: await fn() };
  } catch (e) {
    return { name, error: e.message };
  }
}

run(async () => {
  const a = args();
  const { from, to } = a.from && a.to ? { from: a.from, to: a.to } : lastDays(num(a.days, 28));
  const prev = previousPeriod(from, to);

  const yandexReady = has('YANDEX_OAUTH_TOKEN');
  const googleReady = has('GOOGLE_SERVICE_ACCOUNT_KEY') ||
    existsSync(resolve(SEO_DIR, 'keys', 'google-service-account.json'));

  /* ── Метрика: что с трафиком в целом ───────────────────────────────── */
  const metrika = await block('Метрика', yandexReady && has('YANDEX_METRIKA_COUNTER'), async () => {
    const counter = get('YANDEX_METRIKA_COUNTER');
    const metrics = 'ym:s:visits,ym:s:users,ym:s:bounceRate,ym:s:anyGoalReaches';

    const ask = (d1, d2, filters) =>
      yandexApi(
        'https://api-metrika.yandex.net/stat/v1/data' +
          qs({ ids: counter, metrics, date1: d1, date2: d2, filters, accuracy: 'full' }),
        { service: 'Метрика' },
      );

    /* Последовательно: Метрика разрешает всего три параллельных запроса. */
    const now = await ask(from, to);
    const before = await ask(prev.from, prev.to);
    const organic = await ask(from, to, "ym:s:lastTrafficSource=='organic'");
    const organicBefore = await ask(prev.from, prev.to, "ym:s:lastTrafficSource=='organic'");

    return {
      visits: now.totals?.[0] ?? 0,
      visitsPrev: before.totals?.[0] ?? 0,
      users: now.totals?.[1] ?? 0,
      bounce: now.totals?.[2] ?? 0,
      goals: now.totals?.[3] ?? 0,
      goalsPrev: before.totals?.[3] ?? 0,
      organic: organic.totals?.[0] ?? 0,
      organicPrev: organicBefore.totals?.[0] ?? 0,
    };
  });

  /* ── Вебмастер: как дела в Яндексе ─────────────────────────────────── */
  const webmaster = await block('Вебмастер', yandexReady, async () => {
    const me = await yandexApi(`${WM}/user/`, { service: 'Вебмастер' });
    const hosts = await yandexApi(`${WM}/user/${me.user_id}/hosts`, { service: 'Вебмастер' });
    const host = (hosts?.hosts ?? []).find((h) => (h.ascii_host_url ?? '').includes(SITE_HOST));
    if (!host) throw new Error(`сайта ${SITE_HOST} нет в кабинете`);

    const base = `${WM}/user/${me.user_id}/hosts/${host.host_id}`;

    /* Подзапросы не глушим в null: 403 без нужного права, 401 с протухшим
       токеном и 429 при исчерпанной квоте выглядели бы в отчёте как честные
       нули - «битых ссылок 0, из поиска не выпало ничего». Отказ надо
       показывать отказом, а не спокойной цифрой. */
    const failures = [];
    const soft = async (name, p) => {
      try {
        return await p;
      } catch (e) {
        failures.push(`${name}: ${e.message}`);
        return null;
      }
    };

    const summary = await yandexApi(`${base}/summary`, { service: 'Вебмастер' });

    const queries = await soft(
      'популярные запросы',
      yandexApi(
        `${base}/search-queries/popular` +
        qs({ order_by: 'TOTAL_SHOWS', date_from: from, date_to: to, limit: 25 }) +
        '&query_indicator=TOTAL_SHOWS&query_indicator=TOTAL_CLICKS&query_indicator=AVG_SHOW_POSITION',
        { service: 'Вебмастер' },
      ),
    );

    const events = await soft(
      'события в поиске',
      yandexApi(`${base}/search-urls/events/samples` + qs({ limit: 100 }), { service: 'Вебмастер' }),
    );

    const broken = await soft(
      'битые ссылки',
      yandexApi(`${base}/links/internal/broken/samples` + qs({ limit: 20 }), { service: 'Вебмастер' }),
    );

    const quota = await soft(
      'квота переобхода',
      yandexApi(`${base}/recrawl/quota`, { service: 'Вебмастер' }),
    );

    return {
      sqi: summary?.sqi,
      inSearch: summary?.searchable_pages_count,
      excluded: summary?.excluded_pages_count,
      problems: summary?.site_problems ?? {},
      queries: (queries?.queries ?? []).map((q) => ({
        q: q.query_text,
        shows: q.indicators?.TOTAL_SHOWS ?? 0,
        clicks: q.indicators?.TOTAL_CLICKS ?? 0,
        pos: q.indicators?.AVG_SHOW_POSITION ?? 0,
      })),
      /* Значение именно REMOVED_FROM_SEARCH: по несуществующему имени фильтр
         всегда давал бы ноль, и отчёт спокойно сообщал бы «ничего не выпало». */
      dropped: (events?.samples ?? []).filter((e) => e.event === 'REMOVED_FROM_SEARCH').length,
      droppedUnknown: events === null,
      broken: broken?.count ?? (broken?.links ?? []).length,
      quotaLeft: quota?.quota_remainder,
      brokenUnknown: broken === null,
      failures,
    };
  });

  /* ── Search Console: как дела в Google ─────────────────────────────── */
  const gsc = await block('Search Console', googleReady, async () => {
    const site = get('GSC_SITE_URL', SITE_URL + '/');
    const url = `${GSC}/sites/${encodeURIComponent(site)}/searchAnalytics/query`;

    /* Google отдаёт данные с задержкой в 2–3 дня — сдвигаем окно,
       иначе последние дни придут пустыми и отчёт покажет ложный обвал. */
    const shift = (d, n) => {
      const x = new Date(d + 'T00:00:00Z');
      x.setUTCDate(x.getUTCDate() - n);
      return x.toISOString().slice(0, 10);
    };
    const gFrom = shift(from, 3);
    const gTo = shift(to, 3);

    const ask = (body) =>
      google(url, { method: 'POST', scope: SCOPE, service: 'Search Console', json: body });

    const totals = await ask({ startDate: gFrom, endDate: gTo, dimensions: [], rowLimit: 1, dataState: 'final' });
    const before = await ask({
      startDate: shift(prev.from, 3), endDate: shift(prev.to, 3), dimensions: [], rowLimit: 1, dataState: 'final',
    });
    const queries = await ask({
      startDate: gFrom, endDate: gTo, dimensions: ['query'], rowLimit: 1000, dataState: 'final',
    });

    const rows = (queries?.rows ?? []).map((r) => ({
      q: r.keys[0], clicks: r.clicks, impressions: r.impressions, ctr: r.ctr * 100, position: r.position,
    }));

    return {
      period: { from: gFrom, to: gTo },
      clicks: totals?.rows?.[0]?.clicks ?? 0,
      clicksPrev: before?.rows?.[0]?.clicks ?? 0,
      impressions: totals?.rows?.[0]?.impressions ?? 0,
      position: totals?.rows?.[0]?.position ?? 0,
      /* Позиции 8–25 при живых показах: до первой страницы недалеко,
         и спрос уже подтверждён показами. Самая дешёвая точка роста. */
      almost: rows
        .filter((r) => r.position >= 8 && r.position <= 25 && r.impressions >= 10)
        .sort((x, y) => y.impressions - x.impressions)
        .slice(0, 15),
      /* Показы есть, кликов нет — вопрос к заголовку и описанию. */
      weakSnippets: rows
        .filter((r) => r.impressions >= 20 && r.ctr < 1 && r.position <= 20)
        .sort((x, y) => y.impressions - x.impressions)
        .slice(0, 10),
    };
  });

  const all = { period: { from, to }, previous: prev, metrika, webmaster, gsc };

  if (a.json) return console.log(JSON.stringify(all, null, 2));

  /* ────────────────────────────  Вывод  ───────────────────────────────── */

  title(`Сводка по сайту ${SITE_HOST} · ${from} — ${to}`);
  note(`  Сравнение с предыдущим периодом: ${prev.from} — ${prev.to}`);

  for (const b of [metrika, webmaster, gsc]) {
    if (b.skipped) note(`  ${b.name}: пропущен — ${b.skipped}`);
    if (b.error) fail(`${b.name}: ${b.error}`);
  }

  /* Трафик */
  if (metrika.data) {
    const m = metrika.data;
    title('Трафик — Метрика');
    table(
      [
        { k: 'Визиты', v: m.visits, d: delta(m.visits, m.visitsPrev) },
        { k: 'Из них из поиска', v: m.organic, d: delta(m.organic, m.organicPrev) },
        { k: 'Посетители', v: m.users, d: '' },
        { k: 'Отказы', v: pct(m.bounce), d: '' },
        { k: 'Достижения целей', v: m.goals, d: delta(m.goals, m.goalsPrev) },
      ],
      [
        { key: 'k', title: 'Показатель', max: 26 },
        { key: 'v', title: 'Сейчас', align: 'right' },
        { key: 'd', title: 'К прошлому', align: 'right' },
      ],
    );
    if (!m.goals) {
      warn('Достижений целей ноль — вероятно, цели не заведены в кабинете.');
      note('  Инструкция: документация/метрика-цели.md');
    }
  }

  /* Яндекс */
  if (webmaster.data) {
    const w = webmaster.data;
    title('Яндекс — Вебмастер');
    table(
      [
        { k: 'Страниц в поиске', v: fmt(w.inSearch ?? '—') },
        { k: 'Страниц исключено', v: fmt(w.excluded ?? '—') },
        { k: 'ИКС', v: fmt(w.sqi ?? '—') },
        { k: 'Фатальных проблем', v: fmt(w.problems.FATAL ?? 0) },
        { k: 'Критичных проблем', v: fmt(w.problems.CRITICAL ?? 0) },
        { k: 'Битых внутренних ссылок', v: w.brokenUnknown ? '—' : fmt(w.broken ?? 0) },
        { k: 'Выпало из поиска (в выборке)', v: w.droppedUnknown ? '—' : fmt(w.dropped ?? 0) },
        { k: 'Осталось квоты переобхода', v: fmt(w.quotaLeft ?? '—') },
      ],
      [
        { key: 'k', title: 'Показатель', max: 32 },
        { key: 'v', title: 'Значение', align: 'right' },
      ],
    );

    if (w.failures?.length) {
      for (const f of w.failures) warn(`Вебмастер, не удалось получить — ${f}`);
      note('  В строках выше вместо этих данных стоит прочерк, а не ноль.');
    }

    if (w.queries.length) {
      title('Запросы в Яндексе — верх списка');
      table(
        w.queries.slice(0, 15).map((q) => ({
          q: q.q,
          s: q.shows,
          c: q.clicks,
          p: q.pos.toFixed(1),
        })),
        [
          { key: 'q', title: 'Запрос', max: 50 },
          { key: 's', title: 'Показы', align: 'right' },
          { key: 'c', title: 'Клики', align: 'right' },
          { key: 'p', title: 'Позиция', align: 'right' },
        ],
      );
    }
  }

  /* Google */
  if (gsc.data) {
    const g = gsc.data;
    title(`Google — Search Console · ${g.period.from} — ${g.period.to}`);
    note('  Период сдвинут на три дня: у Google такая задержка данных.');
    table(
      [
        { k: 'Клики', v: fmt(g.clicks), d: delta(g.clicks, g.clicksPrev) },
        { k: 'Показы', v: fmt(g.impressions), d: '' },
        { k: 'Средняя позиция', v: g.position.toFixed(1), d: '' },
      ],
      [
        { key: 'k', title: 'Показатель', max: 26 },
        { key: 'v', title: 'Значение', align: 'right' },
        { key: 'd', title: 'К прошлому', align: 'right' },
      ],
    );

    if (g.almost.length) {
      title('Почти на первой странице — сюда стоит вложиться в первую очередь');
      table(
        g.almost.map((r) => ({ q: r.q, i: r.impressions, c: r.clicks, p: r.position.toFixed(1) })),
        [
          { key: 'q', title: 'Запрос', max: 50 },
          { key: 'i', title: 'Показы', align: 'right' },
          { key: 'c', title: 'Клики', align: 'right' },
          { key: 'p', title: 'Позиция', align: 'right' },
        ],
      );
    }

    if (g.weakSnippets.length) {
      title('Показы есть, кликов нет — переписать заголовок и описание');
      table(
        g.weakSnippets.map((r) => ({ q: r.q, i: r.impressions, ctr: pct(r.ctr), p: r.position.toFixed(1) })),
        [
          { key: 'q', title: 'Запрос', max: 50 },
          { key: 'i', title: 'Показы', align: 'right' },
          { key: 'ctr', title: 'CTR', align: 'right' },
          { key: 'p', title: 'Позиция', align: 'right' },
        ],
      );
    }
  }

  /* Снимок для истории */
  if (a.save) {
    const dir = resolve(SEO_DIR, 'data', 'snapshots');
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
    const path = resolve(dir, `${to}.json`);
    writeFileSync(path, JSON.stringify(all, null, 2), 'utf8');
    console.log('');
    ok(`Снимок сохранён: ${path.replace(process.cwd() + '/', '')}`);
    note('  Через полгода это будет единственный способ сравнить «стало» с «было»:');
    note('  сами сервисы историю дольше пары недель — года не держат.');
  }

  console.log('');
});
