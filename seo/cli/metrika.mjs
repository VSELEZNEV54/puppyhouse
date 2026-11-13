#!/usr/bin/env node
/**
 * Яндекс.Метрика - что происходит с трафиком.
 *
 *   node seo/cli/metrika.mjs summary            сводка: было / стало
 *   node seo/cli/metrika.mjs sources            откуда приходят
 *   node seo/cli/metrika.mjs search             поисковые системы
 *   node seo/cli/metrika.mjs phrases            поисковые фразы
 *   node seo/cli/metrika.mjs landings           страницы входа из поиска
 *   node seo/cli/metrika.mjs pages              самые просматриваемые
 *   node seo/cli/metrika.mjs goals              достижения целей
 *   node seo/cli/metrika.mjs goals-list         какие цели заведены
 *   node seo/cli/metrika.mjs devices            устройства
 *   node seo/cli/metrika.mjs regions            города
 *
 * Общие флаги: --days 28  --from 2026-07-01 --to 2026-07-31  --limit 30  --json
 *
 * ВАЖНО про полноту данных. Счётчик на сайте поднимается только после
 * согласия на cookie (см. src/components/Analytics.astro). Люди, которые
 * баннер закрыли или проигнорировали, в Метрику не попадают вовсе.
 * Поэтому абсолютные числа Метрики ниже реальных, а вот доли и динамика
 * («стало больше / меньше») остаются достоверными. Для абсолютной
 * картины по поиску смотрите Вебмастер и Search Console — они считают
 * показы и клики на своей стороне и от согласия не зависят.
 */

import { yandexApi } from '../lib/yandex.mjs';
import { qs } from '../lib/http.mjs';
import { need, get } from '../lib/env.mjs';
import {
  args, num, table, title, note, run, ok, lastDays, previousPeriod, delta, pct, warn,
} from '../lib/out.mjs';

const STAT = 'https://api-metrika.yandex.net/stat/v1/data';
const MGMT = 'https://api-metrika.yandex.net/management/v1';

/**
 * Какой счётчик смотрим.
 *
 * По умолчанию - счётчик сайта из seo/.env. Флагом --counter можно взять
 * любой другой счётчик того же аккаунта: и по номеру, и по куску названия,
 * потому что помнить одиннадцать цифр никто не обязан.
 *
 *   node seo/cli/metrika.mjs summary --counter 12345678
 *   node seo/cli/metrika.mjs summary --counter "в порядке"
 *
 * Список всех доступных счётчиков: node seo/cli/metrika.mjs counters
 */
let resolvedCounter = null;

async function counterId(a) {
  if (resolvedCounter) return resolvedCounter;

  const asked = a?.counter;

  if (!asked || asked === true) {
    return (resolvedCounter = need(
      'YANDEX_METRIKA_COUNTER',
      'Номер счётчика виден в адресе кабинета metrika.yandex.ru/dashboard?id=… ' +
        'Номер виден в кабинете Метрики',
    ));
  }

  if (/^\d+$/.test(String(asked))) return (resolvedCounter = String(asked));

  /* Передали не номер, а часть названия - ищем среди своих счётчиков. */
  const list = await yandexApi(`${MGMT}/counters`, { service: 'Метрика (управление)' });
  const all = list?.counters ?? [];
  const needle = String(asked).toLowerCase();

  const hits = all.filter(
    (c) =>
      (c.name ?? '').toLowerCase().includes(needle) ||
      (c.site2?.site ?? c.site ?? '').toLowerCase().includes(needle),
  );

  if (!hits.length) {
    throw new Error(
      `Счётчик «${asked}» не найден.\n` +
        '  Доступные: ' + all.map((c) => `${c.id} ${c.name}`).join(', ') + '\n' +
        '  Полный список: node seo/cli/metrika.mjs counters',
    );
  }

  if (hits.length > 1) {
    throw new Error(
      `Под «${asked}» подходит несколько счётчиков — уточните номером:\n` +
        hits.map((c) => `    ${c.id}  ${c.name}  (${c.site2?.site ?? c.site ?? ''})`).join('\n'),
    );
  }

  note(`  Счётчик: ${hits[0].id} — ${hits[0].name}`);
  return (resolvedCounter = String(hits[0].id));
}

/**
 * Запрос к отчётному API.
 * accuracy=full просит Метрику считать по всем визитам, а не по выборке:
 * на объёмах сайта студии это ничего не стоит, зато цифры точные.
 */
async function report({ counter, metrics, dimensions, from, to, filters, limit = 30, sort }) {
  const url =
    STAT +
    qs({
      ids: counter,
      metrics: Array.isArray(metrics) ? metrics.join(',') : metrics,
      dimensions: dimensions ? (Array.isArray(dimensions) ? dimensions.join(',') : dimensions) : undefined,
      date1: from,
      date2: to,
      filters,
      limit,
      sort,
      accuracy: 'full',
      lang: 'ru',
    });

  const res = await yandexApi(url, { service: 'Яндекс.Метрика' });

  /* Метрика молча урезает выборку и молча прячет редкие значения.
     И то и другое ломает именно SEO-отчёты - длинный хвост фраз
     и малопосещаемые страницы. Поэтому говорим об этом вслух. */
  if (res?.sampled && (res.sample_share ?? 1) < 1) {
    warn(
      `Данные посчитаны по выборке ${(res.sample_share * 100).toFixed(1)}% — ` +
        'цифрам по отдельным строкам верить нельзя, только порядку величин.',
    );
  }
  if (res?.contains_sensitive_data) {
    note('  Часть строк Метрика скрыла: по ним меньше 10 посетителей. Это не сбой.');
  }

  return res;
}

/**
 * Фильтр отчёта. Роботов по умолчанию НЕ отсекаем: так цифры совпадают
 * с тем, что владелец видит в интерфейсе Метрики. Флаг --clean включает
 * отсечение - тогда поведенческие показатели честнее, но с кабинетом
 * они уже не сойдутся.
 */
function withRobots(filters, clean) {
  if (!clean) return filters;
  return filters ? `(${filters}) AND ym:s:isRobot=='No'` : "ym:s:isRobot=='No'";
}

/**
 * Последовательный проход вместо Promise.all.
 * Метрика разрешает всего 3 параллельных запроса на пользователя;
 * наивный Promise.all по десятку отчётов упирается в 429.
 */
async function series(tasks) {
  const out = [];
  for (const t of tasks) out.push(await t());
  return out;
}

/** Строки отчёта -> плоские объекты. */
function rows(data) {
  return (data?.data ?? []).map((r) => ({
    name: r.dimensions.map((d) => d.name ?? d.id ?? '—').join(' / '),
    values: r.metrics,
  }));
}

/** Период из флагов: --from/--to важнее --days. */
function period(a) {
  if (a.from && a.to) return { from: a.from, to: a.to };
  return lastDays(num(a.days, 28));
}

const ORGANIC = "ym:s:lastTrafficSource=='organic'";

run(async () => {
  const a = args();
  const { from, to } = period(a);
  const limit = num(a.limit, 30);
  const out = (obj) => console.log(JSON.stringify(obj, null, 2));

  /* Список счётчиков не требует выбранного счётчика - обрабатываем раньше. */
  if (a.cmd === 'counters') {
    const list = await yandexApi(`${MGMT}/counters`, { service: 'Метрика (управление)' });
    const all = list?.counters ?? [];
    if (a.json) return out(all);

    title(`Счётчики на аккаунте — ${all.length}`);
    table(
      all.map((c) => ({
        /* Строкой, а не числом: fmt() иначе разобьёт номер пробелами
           по разрядам, и его нельзя будет скопировать. */
        id: String(c.id),
        n: c.name ?? '',
        s: c.site2?.site ?? c.site ?? '',
        st: c.status === 'Active' ? 'работает' : c.status,
      })),
      [
        { key: 'id', title: 'Номер', align: 'right' },
        { key: 'n', title: 'Название', max: 30 },
        { key: 's', title: 'Сайт', max: 28 },
        { key: 'st', title: 'Статус' },
      ],
    );
    note(`\n  Сейчас по умолчанию берётся ${get('YANDEX_METRIKA_COUNTER') || '(не задан)'}.`);
    note('  Любую команду можно выполнить по другому счётчику:');
    note('    node seo/cli/metrika.mjs summary --counter 12345678');
    note('    node seo/cli/metrika.mjs summary --counter "в порядке"');
    return;
  }

  const counter = await counterId(a);

  /* ─────────────────────────── СВОДКА ──────────────────────────────── */
  if (!a.cmd || a.cmd === 'summary') {
    const prev = previousPeriod(from, to);

    const metrics = [
      'ym:s:visits',
      'ym:s:users',
      'ym:s:bounceRate',
      'ym:s:pageDepth',
      'ym:s:avgVisitDurationSeconds',
      'ym:s:anyGoalReaches',
    ];

    const [now, before, organicNow, organicBefore] = await series([
      () => report({ counter, metrics, from, to, filters: withRobots('', a.clean) }),
      () => report({ counter, metrics, from: prev.from, to: prev.to, filters: withRobots('', a.clean) }),
      () => report({ counter, metrics: ['ym:s:visits', 'ym:s:users'], from, to, filters: withRobots(ORGANIC, a.clean) }),
      () => report({ counter, metrics: ['ym:s:visits', 'ym:s:users'], from: prev.from, to: prev.to, filters: withRobots(ORGANIC, a.clean) }),
    ]);

    const n = now.totals ?? [];
    const b = before.totals ?? [];
    const on = organicNow.totals ?? [];
    const ob = organicBefore.totals ?? [];

    if (a.json) {
      return out({ period: { from, to }, previous: prev, totals: n, previousTotals: b, organic: on, organicPrevious: ob });
    }

    title(`Метрика · ${from} — ${to}`);
    note(`  Сравнение с предыдущим периодом: ${prev.from} — ${prev.to}`);

    table(
      [
        { m: 'Визиты', v: n[0], d: delta(n[0], b[0]) },
        { m: 'Посетители', v: n[1], d: delta(n[1], b[1]) },
        { m: 'Визиты из поиска', v: on[0], d: delta(on[0], ob[0]) },
        { m: 'Посетители из поиска', v: on[1], d: delta(on[1], ob[1]) },
        { m: 'Отказы', v: pct(n[2]), d: delta(n[2], b[2]) },
        { m: 'Глубина просмотра', v: n[3]?.toFixed(2), d: delta(n[3], b[3]) },
        { m: 'Время на сайте, сек', v: Math.round(n[4] ?? 0), d: delta(n[4], b[4]) },
        { m: 'Достижения целей', v: n[5], d: delta(n[5], b[5]) },
      ],
      [
        { key: 'm', title: 'Показатель' },
        { key: 'v', title: 'Сейчас', align: 'right' },
        { key: 'd', title: 'К прошлому', align: 'right' },
      ],
    );

    if (!n[5]) {
      warn('Достижений целей ноль. Возможно, цели ещё не заведены в кабинете —');
      note('  проверьте: node seo/cli/metrika.mjs goals-list');
    }

    note('\n  Счётчик стартует только после согласия на cookie, поэтому абсолютные');
    note('  цифры занижены. Динамика и доли — достоверны.');
    return;
  }

  /* ────────────────────────── ИСТОЧНИКИ ────────────────────────────── */
  if (a.cmd === 'sources') {
    const data = await report({
      counter,
      metrics: ['ym:s:visits', 'ym:s:users', 'ym:s:bounceRate', 'ym:s:anyGoalReaches'],
      dimensions: 'ym:s:lastTrafficSource',
      from, to, limit,
      filters: withRobots('', a.clean),
      sort: '-ym:s:visits',
    });
    if (a.json) return out(data);

    title(`Источники трафика · ${from} — ${to}`);
    const total = data.totals?.[0] || 1;
    table(
      rows(data).map((r) => ({
        n: r.name,
        v: r.values[0],
        share: pct((r.values[0] / total) * 100),
        u: r.values[1],
        b: pct(r.values[2]),
        g: r.values[3],
      })),
      [
        { key: 'n', title: 'Источник', max: 34 },
        { key: 'v', title: 'Визиты', align: 'right' },
        { key: 'share', title: 'Доля', align: 'right' },
        { key: 'u', title: 'Люди', align: 'right' },
        { key: 'b', title: 'Отказы', align: 'right' },
        { key: 'g', title: 'Цели', align: 'right' },
      ],
    );
    return;
  }

  /* ───────────────────── ПОИСКОВЫЕ СИСТЕМЫ ─────────────────────────── */
  if (a.cmd === 'search') {
    const data = await report({
      counter,
      metrics: ['ym:s:visits', 'ym:s:users', 'ym:s:bounceRate', 'ym:s:anyGoalReaches'],
      dimensions: 'ym:s:lastSearchEngineRoot',
      from, to, limit,
      filters: withRobots(ORGANIC, a.clean),
      sort: '-ym:s:visits',
    });
    if (a.json) return out(data);

    title(`Поисковые системы · ${from} — ${to}`);
    table(
      rows(data).map((r) => ({ n: r.name, v: r.values[0], u: r.values[1], b: pct(r.values[2]), g: r.values[3] })),
      [
        { key: 'n', title: 'Поисковик', max: 30 },
        { key: 'v', title: 'Визиты', align: 'right' },
        { key: 'u', title: 'Люди', align: 'right' },
        { key: 'b', title: 'Отказы', align: 'right' },
        { key: 'g', title: 'Цели', align: 'right' },
      ],
    );
    return;
  }

  /* ────────────────────── ПОИСКОВЫЕ ФРАЗЫ ──────────────────────────── */
  if (a.cmd === 'phrases') {
    const data = await report({
      counter,
      metrics: ['ym:s:visits', 'ym:s:users', 'ym:s:bounceRate'],
      dimensions: 'ym:s:lastSearchPhrase',
      from, to, limit,
      filters: withRobots(ORGANIC, a.clean),
      sort: '-ym:s:visits',
    });
    if (a.json) return out(data);

    title(`Поисковые фразы · ${from} — ${to}`);
    table(
      rows(data).map((r) => ({ n: r.name, v: r.values[0], b: pct(r.values[2]) })),
      [
        { key: 'n', title: 'Фраза', max: 70 },
        { key: 'v', title: 'Визиты', align: 'right' },
        { key: 'b', title: 'Отказы', align: 'right' },
      ],
    );
    note('\n  Метрика скрывает большую часть фраз («не определено») — так работают');
    note('  поисковики. Полную картину по запросам дают Вебмастер и Search Console:');
    note('    node seo/cli/webmaster.mjs queries');
    note('    node seo/cli/gsc.mjs queries');
    return;
  }

  /* ─────────────────── СТРАНИЦЫ ВХОДА ИЗ ПОИСКА ────────────────────── */
  if (a.cmd === 'landings') {
    const data = await report({
      counter,
      metrics: ['ym:s:visits', 'ym:s:users', 'ym:s:bounceRate', 'ym:s:avgVisitDurationSeconds', 'ym:s:anyGoalReaches'],
      dimensions: 'ym:s:startURL',
      from, to, limit,
      filters: withRobots(ORGANIC, a.clean),
      sort: '-ym:s:visits',
    });
    if (a.json) return out(data);

    title(`Страницы входа из поиска · ${from} — ${to}`);
    table(
      rows(data).map((r) => ({
        n: r.name.replace(/^https?:\/\/[^/]+/, ''),
        v: r.values[0],
        b: pct(r.values[2]),
        t: Math.round(r.values[3] ?? 0),
        g: r.values[4],
      })),
      [
        { key: 'n', title: 'Страница', max: 60 },
        { key: 'v', title: 'Визиты', align: 'right' },
        { key: 'b', title: 'Отказы', align: 'right' },
        { key: 't', title: 'Сек.', align: 'right' },
        { key: 'g', title: 'Цели', align: 'right' },
      ],
    );
    note('\n  Высокие отказы при заметном трафике — страница не отвечает на запрос,');
    note('  с которого пришли. Это самая дешёвая точка роста.');
    return;
  }

  /* ───────────────────────── ПРОСМОТРЫ ─────────────────────────────── */
  if (a.cmd === 'pages') {
    const data = await report({
      counter,
      metrics: ['ym:pv:pageviews', 'ym:pv:users'],
      dimensions: 'ym:pv:URL',
      from, to, limit,
      sort: '-ym:pv:pageviews',
    });
    if (a.json) return out(data);

    title(`Самые просматриваемые страницы · ${from} — ${to}`);
    table(
      rows(data).map((r) => ({ n: r.name.replace(/^https?:\/\/[^/]+/, ''), v: r.values[0], u: r.values[1] })),
      [
        { key: 'n', title: 'Страница', max: 62 },
        { key: 'v', title: 'Просмотры', align: 'right' },
        { key: 'u', title: 'Люди', align: 'right' },
      ],
    );
    return;
  }

  /* ─────────────────────────── ЦЕЛИ ────────────────────────────────── */
  if (a.cmd === 'goals-list') {
    const data = await yandexApi(`${MGMT}/counter/${counter}/goals?useDeleted=false`, {
      service: 'Метрика (управление)',
    });
    if (a.json) return out(data);

    const goals = data?.goals ?? [];
    title(`Цели счётчика ${counter} — заведено ${goals.length}`);

    if (!goals.length) {
      warn('Целей нет ни одной.');
      note('  Код на сайте события отправляет, но пока цели не созданы в кабинете,');
      note('  Метрика их не считает. Инструкция: документация/метрика-цели.md');
      return;
    }

    table(
      goals.map((g) => ({
        id: String(g.id),
        name: g.name,
        type: g.type,
        cond: (g.conditions ?? []).map((c) => `${c.type} ${c.url ?? ''}`).join('; '),
      })),
      [
        { key: 'id', title: 'ID', align: 'right' },
        { key: 'name', title: 'Название', max: 40 },
        { key: 'type', title: 'Тип' },
        { key: 'cond', title: 'Условие', max: 40 },
      ],
    );
    return;
  }

  if (a.cmd === 'goals') {
    const list = await yandexApi(`${MGMT}/counter/${counter}/goals?useDeleted=false`, {
      service: 'Метрика (управление)',
    });
    const goals = list?.goals ?? [];

    if (!goals.length) {
      warn('Целей в счётчике нет — считать нечего.');
      note('  Инструкция по созданию: документация/метрика-цели.md');
      return;
    }

    /* Метрика умеет отдавать разом достижения по всем целям:
       по метрике на цель. Больше 20 метрик в один запрос не берём. */
    const chunks = [];
    for (let i = 0; i < goals.length; i += 20) chunks.push(goals.slice(i, i + 20));

    const result = [];
    for (const chunk of chunks) {
      const data = await report({
        counter,
        metrics: chunk.map((g) => `ym:s:goal${g.id}reaches`),
        from, to,
      });
      chunk.forEach((g, i) => result.push({ id: String(g.id), name: g.name, reaches: data.totals?.[i] ?? 0 }));
    }

    if (a.json) return out({ period: { from, to }, goals: result });

    title(`Достижения целей · ${from} — ${to}`);
    table(
      result.sort((x, y) => y.reaches - x.reaches),
      [
        { key: 'name', title: 'Цель', max: 50 },
        { key: 'id', title: 'ID', align: 'right' },
        { key: 'reaches', title: 'Достижений', align: 'right' },
      ],
    );
    return;
  }

  /* ───────────────────── УСТРОЙСТВА И ГОРОДА ───────────────────────── */
  if (a.cmd === 'devices') {
    const data = await report({
      counter,
      metrics: ['ym:s:visits', 'ym:s:bounceRate', 'ym:s:anyGoalReaches'],
      dimensions: 'ym:s:deviceCategory',
      from, to, limit,
      filters: withRobots('', a.clean),
      sort: '-ym:s:visits',
    });
    if (a.json) return out(data);
    title(`Устройства · ${from} — ${to}`);
    table(
      rows(data).map((r) => ({ n: r.name, v: r.values[0], b: pct(r.values[1]), g: r.values[2] })),
      [
        { key: 'n', title: 'Тип' },
        { key: 'v', title: 'Визиты', align: 'right' },
        { key: 'b', title: 'Отказы', align: 'right' },
        { key: 'g', title: 'Цели', align: 'right' },
      ],
    );
    return;
  }

  if (a.cmd === 'regions') {
    const data = await report({
      counter,
      metrics: ['ym:s:visits', 'ym:s:bounceRate', 'ym:s:anyGoalReaches'],
      dimensions: 'ym:s:regionCity',
      from, to, limit,
      filters: withRobots('', a.clean),
      sort: '-ym:s:visits',
    });
    if (a.json) return out(data);
    title(`Города · ${from} — ${to}`);
    table(
      rows(data).map((r) => ({ n: r.name, v: r.values[0], b: pct(r.values[1]), g: r.values[2] })),
      [
        { key: 'n', title: 'Город', max: 40 },
        { key: 'v', title: 'Визиты', align: 'right' },
        { key: 'b', title: 'Отказы', align: 'right' },
        { key: 'g', title: 'Цели', align: 'right' },
      ],
    );
    return;
  }

  /* ───────────────── ОТМЕТКИ НА ГРАФИКАХ ──────────────────────────── */
  if (a.cmd === 'annotate') {
    /* Зачем это в наборе SEO-инструментов. Через месяц никто не вспомнит,
       что именно менялось на сайте 24 августа, а на графике будет виден
       перелом. Отметка ставится в момент правки и подписывает причину -
       дальше причина и следствие видны рядом. Требует права metrika:write. */
    const text = a._.join(' ').trim() || a.text;
    if (!text) {
      warn('Укажите, что произошло:');
      note('  node seo/cli/metrika.mjs annotate "Переписал title на 12 страницах блога"');
      process.exit(2);
    }

    /* Флаг без значения парсер превращает в true. Улетев в тело запроса,
       такое булево даёт 400 вместо понятного объяснения. */
    const date =
      typeof a.date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(a.date)
        ? a.date
        : new Date().toISOString().slice(0, 10);

    const res = await yandexApi(`${MGMT}/counter/${counter}/chart_annotations`, {
      method: 'POST',
      service: 'Метрика (управление)',
      json: {
        /* Ключ именно chart_annotation: с «annotation» приходит 400,
           и примечание не создаётся никогда. */
        chart_annotation: {
          date,
          title: text.slice(0, 255),
          message: typeof a.message === 'string' ? a.message.slice(0, 1023) : '',
          group: 'A',
        },
      },
    });

    if (a.json) return out(res);
    ok(`Отметка поставлена на ${date}: «${text}»`);
    note('  Видна на всех графиках Метрики — теперь понятно, откуда взялся перелом.');
    return;
  }

  console.log(`
  Яндекс.Метрика — счётчик ${get('YANDEX_METRIKA_COUNTER') || '(не задан)'}

    summary      сводка с динамикой к прошлому периоду
    sources      источники трафика
    search       поисковые системы
    phrases      поисковые фразы
    landings     страницы входа из поиска
    pages        самые просматриваемые страницы
    goals        достижения целей
    goals-list   какие цели заведены в кабинете
    devices      устройства
    regions      города
    annotate "…" поставить отметку на графике: что и когда меняли
    counters     все счётчики аккаунта

  Флаги: --days 28 | --from 2026-07-01 --to 2026-07-31 | --limit 30 | --json
         --clean          отсечь роботов (честнее поведенческие, но не
                          совпадёт с тем, что показывает кабинет)
         --counter 109…   другой счётчик: номером или куском названия
`);
});
