#!/usr/bin/env node
/**
 * Яндекс.Вебмастер - главный кабинет для российского трафика.
 *
 *   node seo/cli/webmaster.mjs hosts            сайты в кабинете, user_id и host_id
 *   node seo/cli/webmaster.mjs summary          ИКС, страницы в поиске, счётчик проблем
 *   node seo/cli/webmaster.mjs queries          поисковые запросы: показы, клики, позиции
 *   node seo/cli/webmaster.mjs monitoring       связка «запрос → страница» за 2 недели
 *   node seo/cli/webmaster.mjs indexing         сколько страниц в поиске и куда движется
 *   node seo/cli/webmaster.mjs dropped          что выпало из поиска и почему
 *   node seo/cli/webmaster.mjs crawl            как робот обходит сайт, коды ответов
 *   node seo/cli/webmaster.mjs problems         диагностика: что Яндекс считает бедой
 *   node seo/cli/webmaster.mjs broken           битые внутренние ссылки
 *   node seo/cli/webmaster.mjs links            внешние ссылки на сайт
 *   node seo/cli/webmaster.mjs sitemaps         карты сайта и ошибки в них
 *   node seo/cli/webmaster.mjs sqi              история индекса качества сайта
 *   node seo/cli/webmaster.mjs quota            остаток суточной квоты переобхода
 *   node seo/cli/webmaster.mjs recrawl <url>    отправить страницу на переобход
 *   node seo/cli/webmaster.mjs recrawl-changed  переобход изменившихся страниц
 *   node seo/cli/webmaster.mjs sitemap-recrawl  весь sitemap на приоритетный переобход
 *
 * Флаги: --days 28 | --from … --to … | --limit 50 | --json
 *
 * Почему этот кабинет важнее Search Console для этого сайта: студия
 * работает на российский рынок, а там основная доля поиска у Яндекса.
 * Search Console показывает вторую половину картины, но не первую.
 *
 * О чём стоит помнить, глядя на любые цифры отсюда: робот приходит на
 * отправленную страницу до трёх суток, а выдача обновляется до двух
 * недель после обхода. Мерить эффект правки на следующий день бессмысленно.
 */

import { yandexApi } from '../lib/yandex.mjs';
import { qs } from '../lib/http.mjs';
import { get, SITE_HOST, SITE_URL } from '../lib/env.mjs';
import { siteUrls } from '../lib/sitemap.mjs';
import { changedPages } from '../lib/dist-hash.mjs';
import {
  args, num, table, title, note, run, ok, warn, fail, pct, lastDays, fmt,
} from '../lib/out.mjs';

const API = 'https://api.webmaster.yandex.net/v4';
/* Приоритетный переобход карты сайта живёт только в версии 4.1 -
   на /v4/ этого метода просто нет. */
const API41 = 'https://api.webmaster.yandex.net/v4.1';

/* ─────────────────────────  Кто мы и какой сайт  ────────────────────────── */

let cachedUserId = null;

/** user_id выдаёт сам API по токену - в кабинете его нигде не видно. */
async function userId() {
  if (cachedUserId) return cachedUserId;
  const fromEnv = get('YANDEX_WEBMASTER_USER_ID');
  if (fromEnv) return (cachedUserId = fromEnv);

  const me = await yandexApi(`${API}/user/`, { service: 'Яндекс.Вебмастер' });
  cachedUserId = String(me?.user_id ?? '');
  if (!cachedUserId) throw new Error('Вебмастер не вернул user_id — проверьте права токена.');
  return cachedUserId;
}

/**
 * host_id - опознаватель сайта. Формат нестандартный: https:example.ru:443
 * Собирать его вручную не стоит: легко промахнуться мимо http/https или
 * мимо главного зеркала, и тогда половина отчётов молча придёт пустой.
 * Поэтому берём из списка хостов и предпочитаем главное зеркало.
 */
async function hostId() {
  const fromEnv = get('YANDEX_WEBMASTER_HOST_ID');
  if (fromEnv) return fromEnv;

  const uid = await userId();
  const list = await yandexApi(`${API}/user/${uid}/hosts`, { service: 'Яндекс.Вебмастер' });
  const hosts = list?.hosts ?? [];

  const mine = hosts.filter((h) => (h.ascii_host_url ?? h.unicode_host_url ?? '').includes(SITE_HOST));
  if (!mine.length) {
    throw new Error(
      `Сайт ${SITE_HOST} не найден в кабинете Вебмастера.\n` +
        `  Доступные: ${hosts.map((h) => h.ascii_host_url).join(', ') || '(ни одного)'}\n` +
        '  Добавьте сайт на webmaster.yandex.ru и подтвердите права.',
    );
  }

  /* main_mirror - это объект с адресом главного зеркала, а не флаг «я зеркало»:
     у самого главного зеркала он указывает сам на себя. Работать не с главным
     зеркалом нельзя - половина отчётов придёт пустой, и понять почему тяжело. */
  const first = mine[0];
  return first.main_mirror?.host_id ?? first.host_id;
}

/**
 * Даты в ответах приходят как 2026-08-24T00:00:00,000+0300 -
 * с ЗАПЯТОЙ перед миллисекундами. new Date() такое не разбирает.
 */
function wmDate(v) {
  if (typeof v !== 'string') return '';
  return v.replace(',', '.').slice(0, 10);
}

function period(a) {
  if (a.from && a.to) return { from: a.from, to: a.to };
  return lastDays(num(a.days, 28));
}

/* ───────────────────────────────  Команды  ──────────────────────────────── */

run(async () => {
  const a = args();
  const limit = num(a.limit, 50);
  const out = (o) => console.log(JSON.stringify(o, null, 2));

  const KNOWN = [
    'hosts', 'summary', 'queries', 'monitoring', 'indexing', 'dropped', 'crawl',
    'problems', 'broken', 'links', 'sitemaps', 'sqi', 'quota',
    'recrawl', 'recrawl-changed', 'sitemap-recrawl',
  ];

  /* Справку показываем до обращения к API: команда `help` не должна
     требовать токен - иначе человек не может даже узнать, что тут есть. */
  if (a.cmd && !KNOWN.includes(a.cmd)) {
  console.log(`
  Яндекс.Вебмастер — ${SITE_HOST}

    hosts             сайты в кабинете, user_id и host_id
    summary           ИКС, страницы в поиске, счётчик проблем
    queries           поисковые запросы: показы, клики, позиции
    monitoring        связка «запрос → страница», последние 2 недели
    indexing          сколько страниц в поиске и куда движется
    dropped           что выпало из поиска и почему
    crawl             как робот обходит сайт, коды ответов
    problems          диагностика: что Яндекс считает проблемой
    broken            битые внутренние ссылки
    links             внешние ссылки на сайт
    sitemaps          карты сайта и ошибки в них
    sqi               история индекса качества сайта
    quota             остаток суточной квоты переобхода
    recrawl <url>     отправить страницу на переобход
    recrawl-changed   переобход изменившихся страниц (по снимку сборки)
    sitemap-recrawl   вся карта сайта на приоритетный переобход (10 раз в месяц)

  Флаги: --days 28 | --from … --to … | --limit 50 | --json
`);
    return;
  }


  /* ── список сайтов ─────────────────────────────────────────────────── */
  if (a.cmd === 'hosts') {
    const uid = await userId();
    const list = await yandexApi(`${API}/user/${uid}/hosts`, { service: 'Яндекс.Вебмастер' });
    if (a.json) return out({ user_id: uid, ...list });

    const hosts = list?.hosts ?? [];
    title(`Сайты в кабинете — ${hosts.length}`);
    note(`  user_id: ${uid}`);

    table(
      hosts.map((h) => ({
        u: h.unicode_host_url ?? h.ascii_host_url,
        id: h.host_id,
        v: h.verified ? 'да' : 'НЕТ',
        m: h.main_mirror && h.main_mirror.host_id !== h.host_id ? 'зеркало' : 'главный',
      })),
      [
        { key: 'u', title: 'Сайт', max: 34 },
        { key: 'id', title: 'host_id', max: 34 },
        { key: 'v', title: 'Права' },
        { key: 'm', title: 'Роль' },
      ],
    );

    const main = hosts.find((h) => !h.main_mirror || h.main_mirror.host_id === h.host_id);
    note('\n  Закрепите значения в seo/.env — тогда каждый запуск не будет');
    note('  тратить два лишних запроса на их выяснение:');
    note(`    YANDEX_WEBMASTER_USER_ID=${uid}`);
    if (main) note(`    YANDEX_WEBMASTER_HOST_ID=${main.host_id}`);
    return;
  }

  const uid = await userId();
  const host = await hostId();
  const base = `${API}/user/${uid}/hosts/${host}`;
  const base41 = `${API41}/user/${uid}/hosts/${host}`;

  /* ── сводка ────────────────────────────────────────────────────────── */
  if (!a.cmd || a.cmd === 'summary') {
    const s = await yandexApi(`${base}/summary`, { service: 'Яндекс.Вебмастер' });
    if (a.json) return out(s);

    const p = s?.site_problems ?? {};

    title(`Вебмастер · ${SITE_HOST}`);
    table(
      [
        { k: 'Индекс качества сайта (ИКС)', v: fmt(s?.sqi ?? '—') },
        { k: 'Страниц в поиске', v: fmt(s?.searchable_pages_count ?? '—') },
        { k: 'Страниц исключено', v: fmt(s?.excluded_pages_count ?? '—') },
        { k: 'Фатальных проблем', v: fmt(p.FATAL ?? 0) },
        { k: 'Критичных проблем', v: fmt(p.CRITICAL ?? 0) },
        { k: 'Возможных проблем', v: fmt(p.POSSIBLE_PROBLEM ?? 0) },
        { k: 'Рекомендаций', v: fmt(p.RECOMMENDATION ?? 0) },
      ],
      [
        { key: 'k', title: 'Показатель', max: 34 },
        { key: 'v', title: 'Значение', align: 'right' },
      ],
    );

    if ((p.FATAL ?? 0) || (p.CRITICAL ?? 0)) {
      warn(`Есть серьёзные проблемы: ${p.FATAL ?? 0} фатальных, ${p.CRITICAL ?? 0} критичных.`);
      note('  Разбор: node seo/cli/webmaster.mjs problems');
    } else {
      ok('Фатальных и критичных проблем нет.');
    }
    return;
  }

  /* ── поисковые запросы ─────────────────────────────────────────────── */
  if (a.cmd === 'queries') {
    const { from, to } = period(a);

    /* Индикаторы перечисляются повторяющимся параметром - URLSearchParams
       так не умеет, дописываем строкой. Потолок выдачи - ТОП-3000,
       за страницу не больше 500. */
    const url =
      `${base}/search-queries/popular` +
      qs({ order_by: 'TOTAL_SHOWS', date_from: from, date_to: to, limit: Math.min(limit, 500) }) +
      '&query_indicator=TOTAL_SHOWS&query_indicator=TOTAL_CLICKS' +
      '&query_indicator=AVG_SHOW_POSITION&query_indicator=AVG_CLICK_POSITION';

    const res = await yandexApi(url, { service: 'Яндекс.Вебмастер' });
    if (a.json) return out(res);

    const rows = (res?.queries ?? []).map((q) => {
      const i = q.indicators ?? {};
      const shows = i.TOTAL_SHOWS ?? 0;
      const clicks = i.TOTAL_CLICKS ?? 0;
      return {
        q: q.query_text,
        shows,
        clicks,
        ctr: pct(shows ? (clicks / shows) * 100 : 0),
        pos: (i.AVG_SHOW_POSITION ?? 0).toFixed(1),
      };
    });

    title(`Поисковые запросы Яндекса · ${from} — ${to}`);
    table(rows, [
      { key: 'q', title: 'Запрос', max: 55 },
      { key: 'shows', title: 'Показы', align: 'right' },
      { key: 'clicks', title: 'Клики', align: 'right' },
      { key: 'ctr', title: 'CTR', align: 'right' },
      { key: 'pos', title: 'Позиция', align: 'right' },
    ]);

    if (!rows.length) {
      note('  Пусто. Вебмастер начинает копить статистику запросов не сразу');
      note('  после подтверждения прав — на новом сайте это нормально.');
    } else {
      const weak = rows.filter((r) => r.shows >= 20 && parseFloat(r.ctr) < 2);
      if (weak.length) {
        note(`\n  ${weak.length} запр. с показами, но почти без кликов — кандидаты`);
        note('  на переписывание title и description соответствующих страниц.');
      }
    }
    return;
  }

  /* ── связка «запрос → страница» ────────────────────────────────────── */
  if (a.cmd === 'monitoring') {
    /* Самый полезный бесплатный отчёт Вебмастера: видно, КАКАЯ СТРАНИЦА
       показывается по какому запросу. Так находят каннибализацию -
       когда по одному запросу конкурируют две свои же страницы.
       История здесь всего две недели, глубже данных нет вообще. */
    const res = await yandexApi(`${base}/query-analytics/list`, {
      method: 'POST',
      service: 'Яндекс.Вебмастер',
      json: {
        offset: 0,
        limit: Math.min(limit, 500),
        device_type_indicator: 'ALL',
        text_indicator: 'QUERY',
      },
    });

    if (a.json) return out(res);

    /* statistics - поденные записи вида {date, field, value}: на каждый день
       своя строка по каждому показателю. Их надо складывать, а не брать
       последнюю. Позицию складывать бессмысленно - по ней среднее.
       Имена показателей здесь свои, не такие, как в популярных запросах. */
    const rows = (res?.text_indicator_to_statistics ?? []).map((r) => {
      const sum = {};
      const count = {};
      for (const st of r.statistics ?? []) {
        sum[st.field] = (sum[st.field] ?? 0) + (st.value ?? 0);
        count[st.field] = (count[st.field] ?? 0) + 1;
      }

      return {
        q: r.text_indicator?.value ?? '',
        /* Самая частая страница по этому запросу - ровно то, ради чего
           команда и нужна. */
        url: (r.popular_complementary_indicator?.value ?? '').replace(/^https?:\/\/[^/]+/, ''),
        shows: sum.IMPRESSIONS ?? 0,
        clicks: sum.CLICKS ?? 0,
        pos: (count.POSITION ? sum.POSITION / count.POSITION : 0).toFixed(1),
      };
    });

    /* Сортируем у себя: сортировать по показам сервер не умеет. */
    rows.sort((x, y) => y.shows - x.shows);

    title('Мониторинг запросов · последние 2 недели');
    note('  Глубже двух недель этих данных не существует. Если нужна история —');
    note('  запускайте команду регулярно и складывайте выгрузки: --json > файл');

    table(rows, [
      { key: 'q', title: 'Запрос', max: 40 },
      { key: 'url', title: 'Страница', max: 32 },
      { key: 'shows', title: 'Показы', align: 'right' },
      { key: 'clicks', title: 'Клики', align: 'right' },
      { key: 'pos', title: 'Позиция', align: 'right' },
    ]);

    /* Один запрос, ведущий на разные страницы, - это каннибализация:
       свои же страницы конкурируют между собой и обе проигрывают. */
    const byQuery = new Map();
    for (const r of rows) {
      if (!r.url) continue;
      const set = byQuery.get(r.q) ?? new Set();
      set.add(r.url);
      byQuery.set(r.q, set);
    }
    const cannibal = [...byQuery.entries()].filter(([, urls]) => urls.size > 1);
    if (cannibal.length) {
      warn(`По ${cannibal.length} запр. показываются разные страницы сайта —`);
      note('  они конкурируют между собой. Стоит выбрать одну и увести на неё ссылки.');
    }
    return;
  }

  /* ── индексирование ────────────────────────────────────────────────── */
  if (a.cmd === 'indexing') {
    const { from, to } = period(a);

    const history = await yandexApi(
      `${base}/search-urls/in-search/history` + qs({ date_from: from, date_to: to }),
      { service: 'Яндекс.Вебмастер' },
    ).catch(() => null);

    const samples = await yandexApi(
      `${base}/search-urls/in-search/samples` + qs({ limit: Math.min(limit, 100) }),
      { service: 'Яндекс.Вебмастер' },
    ).catch(() => null);

    if (a.json) return out({ history, samples });

    title(`Страницы в поиске Яндекса · ${from} — ${to}`);

    const points = history?.history ?? history?.indicators?.SEARCHABLE ?? [];
    if (points.length) {
      table(
        points.slice(-14).map((p) => ({ d: wmDate(p.date), v: p.value })),
        [
          { key: 'd', title: 'Дата' },
          { key: 'v', title: 'Страниц в поиске', align: 'right' },
        ],
      );

      const first = points[0]?.value ?? 0;
      const last = points[points.length - 1]?.value ?? 0;
      if (last < first) {
        warn(`Страниц в поиске стало меньше: ${first} → ${last}.`);
        note('  Это главный тревожный признак. Смотрите, что именно выпало:');
        note('    node seo/cli/webmaster.mjs dropped');
      } else if (last > first) {
        ok(`Страниц в поиске стало больше: ${first} → ${last}.`);
      } else {
        note(`  Без изменений: ${last}.`);
      }
    } else {
      note('  История пока пустая.');
    }

    const list = samples?.samples ?? [];
    if (list.length) {
      title(`Примеры страниц в поиске (${list.length})`);
      table(
        list.slice(0, 20).map((s) => ({
          u: (s.url ?? '').replace(/^https?:\/\/[^/]+/, ''),
          t: (s.title ?? '').slice(0, 50),
        })),
        [
          { key: 'u', title: 'Адрес', max: 45 },
          { key: 't', title: 'Заголовок', max: 50 },
        ],
      );
    }
    return;
  }

  /* ── что выпало из поиска ──────────────────────────────────────────── */
  if (a.cmd === 'dropped') {
    const res = await yandexApi(
      `${base}/search-urls/events/samples` + qs({ limit: Math.min(limit, 100) }),
      { service: 'Яндекс.Вебмастер' },
    );
    if (a.json) return out(res);

    /* Значений события ровно два, и написаны они именно так. Ошибиться здесь
       дороже всего: фильтр по несуществующему значению даёт пустой список,
       и команда бодро отвечает «всё хорошо» ровно тогда, когда половина
       сайта вылетела из выдачи. */
    const events = res?.samples ?? [];
    const removed = events.filter((e) => e.event === 'REMOVED_FROM_SEARCH');
    const appeared = events.filter((e) => e.event === 'APPEARED_IN_SEARCH');

    /* Причину исключения Яндекс кладёт в excluded_url_status. */
    const WHY = {
      NOTHING_FOUND: 'страница не найдена',
      HTTP_ERROR: 'ошибка ответа сервера',
      NOT_CANONICAL: 'не канонический адрес',
      DUPLICATE: 'дубль другой страницы',
      LOW_QUALITY: 'сочтена малополезной',
      NO_INDEX: 'запрещена к индексированию',
      ROBOTS_URL_ERROR: 'закрыта в robots.txt',
      NOT_MAIN_MIRROR: 'адрес не главного зеркала',
      PARSER_ERROR: 'страницу не удалось разобрать',
      REDIRECT: 'перенаправляет на другой адрес',
    };

    title(`Изменения в поиске — событий ${events.length}`);

    if (removed.length) {
      title(`Выпало из поиска: ${removed.length}`);
      table(
        removed.slice(0, 30).map((e) => ({
          u: (e.url ?? '').replace(/^https?:\/\/[^/]+/, ''),
          r: WHY[e.excluded_url_status] ?? e.excluded_url_status ?? '',
          d: wmDate(e.event_date ?? e.last_access ?? ''),
        })),
        [
          { key: 'u', title: 'Адрес', max: 45 },
          { key: 'r', title: 'Причина', max: 34 },
          { key: 'd', title: 'Когда' },
        ],
      );
      warn('Каждая выпавшая страница — потерянный трафик. Разберитесь с причиной,');
      note('  почините и отправьте на переобход: node seo/cli/webmaster.mjs recrawl <url>');
    } else {
      ok('Выпавших из поиска страниц в выборке нет.');
    }

    if (appeared.length) {
      title(`Появилось в поиске: ${appeared.length}`);
      table(
        appeared.slice(0, 20).map((e) => ({
          u: (e.url ?? '').replace(/^https?:\/\/[^/]+/, ''),
          d: wmDate(e.event_date ?? ''),
        })),
        [
          { key: 'u', title: 'Адрес', max: 55 },
          { key: 'd', title: 'Когда' },
        ],
      );
    }
    return;
  }

  /* ── как робот обходит сайт ────────────────────────────────────────── */
  if (a.cmd === 'crawl') {
    const { from, to } = period(a);

    const history = await yandexApi(
      `${base}/indexing/history` + qs({ date_from: from, date_to: to }),
      { service: 'Яндекс.Вебмастер' },
    ).catch(() => null);

    const samples = await yandexApi(
      `${base}/indexing/samples` + qs({ limit: Math.min(limit, 100) }),
      { service: 'Яндекс.Вебмастер' },
    ).catch(() => null);

    if (a.json) return out({ history, samples });

    title(`Обход роботом · ${from} — ${to}`);

    const ind = history?.indicators ?? {};
    const keys = Object.keys(ind);
    if (keys.length) {
      /* Коды ответов: рост 4xx или 5xx после деплоя - сразу видно. */
      table(
        keys.map((k) => {
          const arr = ind[k] ?? [];
          return { k, last: arr[arr.length - 1]?.value ?? 0 };
        }),
        [
          { key: 'k', title: 'Что считаем' },
          { key: 'last', title: 'Последнее значение', align: 'right' },
        ],
      );
    } else {
      note('  Данных пока нет.');
    }

    const bad = (samples?.samples ?? []).filter((s) => s.http_code && s.http_code >= 400);
    if (bad.length) {
      title(`Страницы с ошибками — ${bad.length}`);
      table(
        bad.slice(0, 30).map((s) => ({
          u: (s.url ?? '').replace(/^https?:\/\/[^/]+/, ''),
          c: s.http_code,
          d: wmDate(s.access_date ?? ''),
        })),
        [
          { key: 'u', title: 'Адрес', max: 50 },
          { key: 'c', title: 'Код', align: 'right' },
          { key: 'd', title: 'Обход' },
        ],
      );
      warn('Робот получает ошибки на этих адресах — их надо чинить или закрывать редиректом.');
    } else {
      ok('Ошибок обхода в примерах нет.');
    }
    return;
  }

  /* ── диагностика ───────────────────────────────────────────────────── */
  if (a.cmd === 'problems') {
    const res = await yandexApi(`${base}/diagnostics`, { service: 'Яндекс.Вебмастер' });
    if (a.json) return out(res);

    /* В ответе problems - словарь «тип проблемы -> подробности», а не список.
       И описаний API не отдаёт вовсе: тип приходит ключом, а что он значит -
       надо знать самому. Отсюда словарь WHAT: без него колонка была бы пустой. */
    const WHAT = {
      DISALLOWED_IN_ROBOTS: 'Робот не может обойти сайт: закрыт в robots.txt',
      CONNECT_FAILED: 'Сервер не отвечает роботу',
      DNS_ERROR: 'Домен не разрешается в адрес',
      MAIN_PAGE_ERROR: 'Главная страница отдаёт ошибку',
      NO_ROBOTS_TXT: 'Нет файла robots.txt',
      NO_SITEMAPS: 'Не указана карта сайта',
      SITEMAP_ERROR: 'Карта сайта содержит ошибки',
      ERRORS_IN_ROBOTS: 'Ошибки в robots.txt',
      SLOW_AVG_RESPONSE_TIME: 'Сайт отвечает медленно',
      DOCS_4XX: 'Много страниц отдают 4xx',
      DOCS_5XX: 'Много страниц отдают 5xx',
      NO_METRIKA_COUNTER: 'Не найден счётчик Метрики',
      NO_METRIKA_COUNTER_BINDING: 'Счётчик Метрики не привязан к сайту в Вебмастере',
      NO_METRIKA_COUNTER_CRAWL_ENABLED: 'Не включён обход страниц по данным Метрики',
      THREATS: 'Найдены угрозы безопасности',
      NO_MOBILE_VERSION: 'Нет мобильной версии',
      BAD_TITLES: 'Проблемы с заголовками title',
      BAD_DESCRIPTIONS: 'Проблемы с описаниями description',
      DUPLICATE_TITLES: 'Одинаковые заголовки на разных страницах',
      DUPLICATE_DESCRIPTIONS: 'Одинаковые описания на разных страницах',
      NO_FAVICON: 'Не найден значок сайта',
      REDIRECT_MAIN_PAGE: 'Главная страница перенаправляет',
      SITE_NOT_INDEXED: 'Сайт не индексируется',
      NO_SITEMAP_MODIFICATIONS: 'Карта сайта давно не менялась',
    };

    const SEV = {
      FATAL: 'ФАТАЛЬНО',
      CRITICAL: 'критично',
      POSSIBLE_PROBLEM: 'возможно',
      RECOMMENDATION: 'совет',
    };
    const order = ['FATAL', 'CRITICAL', 'POSSIBLE_PROBLEM', 'RECOMMENDATION'];

    const active = Object.entries(res?.problems ?? {})
      .map(([type, p]) => ({ type, ...p }))
      .filter((p) => p.state === 'PRESENT' || p.state === undefined)
      .sort((x, y) => order.indexOf(x.severity) - order.indexOf(y.severity));

    title(`Диагностика сайта — активных записей ${active.length}`);

    if (!active.length) {
      ok('Активных проблем Яндекс не видит.');
      return;
    }

    table(
      active.map((p) => ({
        s: SEV[p.severity] ?? p.severity,
        n: p.type,
        d: WHAT[p.type] ?? '(описание Яндекс не отдаёт — смотрите в кабинете)',
        u: wmDate(p.last_state_update ?? ''),
      })),
      [
        { key: 's', title: 'Важность' },
        { key: 'n', title: 'Тип', max: 32 },
        { key: 'd', title: 'Что это', max: 50 },
        { key: 'u', title: 'Обновлено' },
      ],
    );

    /* Отдельно ловим связку с Метрикой: обход по счётчику - бесплатный
       канал ускорения индексации, который не тратит квоту переобхода. */
    if (active.some((p) => p.type.includes('METRIKA'))) {
      warn('Вебмастер не видит связки со счётчиком Метрики.');
      note('  Связать стоит: тогда включится «обход по счётчику» — робот узнаёт');
      note('  о новых страницах из данных Метрики, и это не тратит квоту переобхода.');
      note('  Кабинет Вебмастера → Настройки → Привязка счётчика Метрики.');
    }
    return;
  }

  /* ── битые внутренние ссылки ───────────────────────────────────────── */
  if (a.cmd === 'broken') {
    const res = await yandexApi(
      `${base}/links/internal/broken/samples` + qs({ limit: Math.min(limit, 100), offset: 0 }),
      { service: 'Яндекс.Вебмастер' },
    );
    if (a.json) return out(res);

    const links = res?.links ?? [];
    title(`Битые внутренние ссылки — показано ${links.length} из ${fmt(res?.count ?? links.length)}`);

    if (!links.length) {
      ok('Битых внутренних ссылок не найдено.');
      return;
    }

    table(
      links.map((l) => ({
        from: (l.source_url ?? '').replace(/^https?:\/\/[^/]+/, ''),
        to: (l.destination_url ?? '').replace(/^https?:\/\/[^/]+/, ''),
        /* Кода ответа в этом ответе нет - только даты. Показываем, когда
           ссылка замечена: свежая важнее давно висящей. */
        d: wmDate(l.discovery_date ?? ''),
      })),
      [
        { key: 'from', title: 'Со страницы', max: 38 },
        { key: 'to', title: 'На адрес', max: 38 },
        { key: 'd', title: 'Найдена' },
      ],
    );
    note('\n  Это чинится прямо в исходниках: найти href и поправить.');
    note('  Битые ссылки внутри сайта — из немногих ошибок, которые видны роботу сразу.');
    return;
  }

  /* ── внешние ссылки ────────────────────────────────────────────────── */
  if (a.cmd === 'links') {
    const res = await yandexApi(
      `${base}/links/external/samples` + qs({ limit: Math.min(limit, 100), offset: 0 }),
      { service: 'Яндекс.Вебмастер' },
    );
    if (a.json) return out(res);

    const links = res?.links ?? [];
    title(`Внешние ссылки — показано ${links.length} из ${fmt(res?.count ?? links.length)}`);

    table(
      links.map((l) => ({
        from: (l.source_url ?? '').slice(0, 60),
        to: (l.destination_url ?? '').replace(/^https?:\/\/[^/]+/, ''),
        d: wmDate(l.discovery_date ?? ''),
      })),
      [
        { key: 'from', title: 'Откуда', max: 55 },
        { key: 'to', title: 'Куда', max: 30 },
        { key: 'd', title: 'Найдена' },
      ],
    );
    return;
  }

  /* ── карты сайта ───────────────────────────────────────────────────── */
  if (a.cmd === 'sitemaps') {
    /* Без limit сервер отдаёт всего 10 карт - вывод молча обрежется. */
    const res = await yandexApi(`${base}/sitemaps` + qs({ limit: Math.min(limit, 100) }), {
      service: 'Яндекс.Вебмастер',
    });
    if (a.json) return out(res);

    const maps = res?.sitemaps ?? [];
    title(`Карты сайта — ${maps.length}`);

    if (!maps.length) {
      warn('Яндекс не знает ни одной карты сайта.');
      note(`  Добавьте: Индексирование → Файлы Sitemap → ${SITE_URL}/sitemap-index.xml`);
      return;
    }

    table(
      maps.map((m) => ({
        u: (m.sitemap_url ?? '').replace(/^https?:\/\/[^/]+/, ''),
        id: (m.sitemap_id ?? '').slice(0, 14),
        t: wmDate(m.last_access_date ?? ''),
        n: m.urls_count ?? 0,
        c: m.children_count ?? 0,
        e: m.errors_count ?? 0,
      })),
      [
        { key: 'u', title: 'Карта', max: 32 },
        { key: 'id', title: 'sitemap_id', max: 14 },
        { key: 't', title: 'Прочитана' },
        { key: 'n', title: 'Адресов', align: 'right' },
        { key: 'c', title: 'Вложенных', align: 'right' },
        { key: 'e', title: 'Ошибки', align: 'right' },
      ],
    );
    return;
  }

  /* ── ИКС ───────────────────────────────────────────────────────────── */
  if (a.cmd === 'sqi') {
    const res = await yandexApi(`${base}/sqi-history`, { service: 'Яндекс.Вебмастер' });
    if (a.json) return out(res);

    const points = res?.points ?? [];
    title('История индекса качества сайта (ИКС)');
    table(
      points.slice(-16).map((p) => ({ d: wmDate(p.date), v: p.value })),
      [
        { key: 'd', title: 'Дата' },
        { key: 'v', title: 'ИКС', align: 'right' },
      ],
    );
    note('\n  ИКС — интегральная и медленная метрика. По ней смотрят тренд за месяцы,');
    note('  а не результат конкретной правки.');
    return;
  }

  /* ── квота переобхода ──────────────────────────────────────────────── */
  if (a.cmd === 'quota') {
    const res = await yandexApi(`${base}/recrawl/quota`, { service: 'Яндекс.Вебмастер' });
    if (a.json) return out(res);

    title('Квота переобхода страниц');
    table(
      [
        { k: 'Всего в сутки', v: fmt(res?.daily_quota ?? '—') },
        { k: 'Осталось', v: fmt(res?.quota_remainder ?? '—') },
      ],
      [
        { key: 'k', title: 'Показатель' },
        { key: 'v', title: 'Значение', align: 'right' },
      ],
    );

    note('\n  Квота считается индивидуально для домена и не публикуется —');
    note('  единственный достоверный источник этих чисел вот этот запрос.');
    note('  Тратить её стоит на изменившиеся страницы. Массовое уведомление');
    note('  без квоты — IndexNow: node seo/cli/indexnow.mjs changed');
    return;
  }

  /* ── переобход ─────────────────────────────────────────────────────── */
  if (a.cmd === 'recrawl' || a.cmd === 'recrawl-changed') {
    let urls = [];

    if (a.cmd === 'recrawl') {
      urls = a._.filter(Boolean).map((u) =>
        u.startsWith('http') ? u : `${SITE_URL}${u.startsWith('/') ? '' : '/'}${u}`,
      );
      if (!urls.length) {
        fail('Укажите адрес: node seo/cli/webmaster.mjs recrawl /uslugi/');
        process.exit(2);
      }
    } else {
      const diff = changedPages();
      if (diff.first) {
        warn('Снимка прошлой сборки нет — не с чем сравнивать.');
        note('  Сначала выполните: node seo/cli/indexnow.mjs changed');
        return;
      }
      urls = [...diff.added, ...diff.changed];
      if (!urls.length) {
        ok('Изменившихся страниц нет — квоту тратить не на что.');
        return;
      }
      note(`  Изменилось страниц: ${urls.length}`);
    }

    const quota = await yandexApi(`${base}/recrawl/quota`, { service: 'Яндекс.Вебмастер' }).catch(() => null);
    let left = quota?.quota_remainder ?? null;

    if (left !== null && urls.length > left) {
      warn(`Квоты хватит на ${left} адр., а в списке ${urls.length}.`);
      if (left === 0) {
        note('  На сегодня квота исчерпана. Изменившиеся страницы всё равно можно');
        note('  анонсировать через IndexNow — там такой квоты нет.');
        return;
      }
      note(`  Отправим первые ${left}, остальные — завтра.`);
      urls = urls.slice(0, left);
    }

    title(`Переобход: отправляем ${urls.length} адр.`);

    const results = [];
    for (const url of urls) {
      try {
        /* Пакетной отправки у Вебмастера нет - один адрес за запрос,
           каждый съедает единицу суточной квоты. */
        const res = await yandexApi(`${base}/recrawl/queue`, {
          method: 'POST',
          service: 'Яндекс.Вебмастер',
          json: { url },
        });
        if (typeof res?.quota_remainder === 'number') left = res.quota_remainder;
        results.push({ url: url.replace(/^https?:\/\/[^/]+/, ''), r: 'в очереди' });
      } catch (e) {
        const exhausted = e.status === 429;
        results.push({
          url: url.replace(/^https?:\/\/[^/]+/, ''),
          r: exhausted ? 'квота исчерпана' : `ошибка: ${e.message.slice(0, 50)}`,
        });
        if (exhausted) break;
      }
    }

    if (a.json) return out(results);

    table(results, [
      { key: 'url', title: 'Адрес', max: 50 },
      { key: 'r', title: 'Результат', max: 55 },
    ]);
    if (left !== null) note(`\n  Осталось квоты: ${left}`);
    note('  Робот придёт в течение трёх суток, выдача обновится в течение двух недель.');
    return;
  }

  /* ── приоритетный переобход карты сайта ────────────────────────────── */
  if (a.cmd === 'sitemap-recrawl') {
    /* Когда изменилось много страниц сразу, дешевле отправить на переобход
       всю карту сайта, чем тратить суточную квоту постранично.
       Лимит - 10 раз в месяц, и метод живёт только в версии 4.1. */
    const res = await yandexApi(`${base41}/sitemaps/recrawl`, { service: 'Яндекс.Вебмастер' });

    /* Лимиты лежат вложенными, а не на верхнем уровне. Прочитать не там -
       значит показать таблицу из прочерков и не заметить, что лимит выбран. */
    const lim = res?.host_sitemaps_recrawl_limit_info ?? {};
    const used = lim.requests_count ?? 0;
    const cap = lim.monthly_limit_requests ?? 0;

    title('Приоритетный переобход карты сайта');
    table(
      [
        { k: 'Лимит в месяц', v: fmt(cap || '—') },
        { k: 'Использовано', v: fmt(used) },
        { k: 'Ближайший доступный день', v: wmDate(lim.nearest_allowed_day ?? '') || 'сегодня' },
      ],
      [
        { key: 'k', title: 'Показатель', max: 30 },
        { key: 'v', title: 'Значение', align: 'right' },
      ],
    );

    if (!a.send) {
      note('\n  Это была проверка лимита. Чтобы действительно отправить:');
      note('    node seo/cli/webmaster.mjs sitemap-recrawl --send');
      return;
    }

    if (cap && used >= cap) {
      fail(`Месячный лимит выбран: ${used} из ${cap}.`);
      note(`  Следующая возможность: ${wmDate(lim.nearest_allowed_day ?? '') || 'позже'}`);
      note('  Пока можно уведомлять через IndexNow — там такого лимита нет.');
      return;
    }

    const maps = await yandexApi(`${base}/sitemaps` + qs({ limit: 100 }), {
      service: 'Яндекс.Вебмастер',
    });
    const list = maps?.sitemaps ?? [];
    if (!list.length) {
      fail('Карт сайта в кабинете нет — отправлять нечего.');
      return;
    }

    /* Отправляем одну - индексную: она тянет за собой вложенные. Слать все
       подряд нельзя: каждая отправка съедает единицу из десяти в месяц,
       а после первой сервер отвечает «переобход уже идёт». */
    const target = list.find((m) => m.sitemap_type === 'INDEX_SITEMAP') ?? list[0];

    try {
      const done = await yandexApi(`${base41}/sitemaps/${target.sitemap_id}/recrawl`, {
        method: 'POST',
        service: 'Яндекс.Вебмастер',
      });
      ok(`Отправлена: ${target.sitemap_url}`);
      const left = done?.host_sitemaps_recrawl_limit_info;
      if (left) {
        note(`  Использовано за месяц: ${left.requests_count ?? '—'} из ${left.monthly_limit_requests ?? '—'}`);
      }
    } catch (e) {
      if (e.status === 409) {
        warn('Переобход карты сайта уже выполняется — повторная отправка не нужна.');
      } else {
        fail(`${target.sitemap_url} — ${e.message}`);
      }
    }
    return;
  }

});
