#!/usr/bin/env node
/**
 * Bing Webmaster Tools - и, главное, бесплатное исследование запросов.
 *
 *   node seo/cli/bing.mjs sites                 подтверждённые сайты
 *   node seo/cli/bing.mjs queries               запросы, по которым находят
 *   node seo/cli/bing.mjs pages                 страницы и их трафик
 *   node seo/cli/bing.mjs traffic               динамика показов и кликов
 *   node seo/cli/bing.mjs keyword <фраза>       частотность фразы по неделям
 *   node seo/cli/bing.mjs related <фраза>       связанные запросы - расширение семантики
 *   node seo/cli/bing.mjs links [url]           внешние ссылки
 *   node seo/cli/bing.mjs issues                технические проблемы, найденные Bing
 *
 * Зачем это сайту, который живёт с российского трафика. Ради двух методов:
 * GetKeywordStats и GetRelatedKeywords. Они дают историю показов по ЛЮБОЙ
 * фразе, не только по вашему сайту, - то есть то, за что обычно платят
 * в Ahrefs и Semrush. Бесплатно и без ограничений по чужим доменам.
 *
 * Важная оговорка. Данные - из индекса Bing, а его доля в России около
 * одного-двух процентов. Абсолютные числа поэтому занижены в разы.
 * Пользоваться этим стоит как компасом («какая формулировка спрашивается
 * чаще»), а не как измерителем спроса. Абсолютная частотность по России -
 * только Вордстат, и только руками: публичного бесплатного API у него нет.
 */

import { api, qs } from '../lib/http.mjs';
import { need, SITE_URL } from '../lib/env.mjs';
import { args, num, table, title, note, run, ok, warn, fail, pct, fmt } from '../lib/out.mjs';

/* JSON/REST. Старые SOAP и POX Microsoft отключает 31.08.2026,
   поэтому пути /soap и /pox не используем вовсе. */
const API = 'https://ssl.bing.com/webmaster/api.svc/json';

function key() {
  return need(
    'BING_API_KEY',
    'bing.com/webmasters → шестерёнка Settings → API Access → API Key → Generate. ' +
      'См. seo/SETUP.md, раздел 5',
  );
}

/**
 * Вызов метода Bing.
 * Ответ всегда завёрнут в поле d, а ошибки приходят с кодом 400
 * и телом {ErrorCode, Message} - HTTP-статус тут ничего не различает,
 * смотреть надо в Message.
 */
async function call(method, params = {}) {
  const url = `${API}/${method}` + qs({ apikey: key(), ...params });

  try {
    const res = await api(url, { service: `Bing · ${method}`, retries: 2 });
    return res?.d ?? res;
  } catch (e) {
    if (e.status === 400) {
      const msg = e.body?.Message ?? e.message;
      throw Object.assign(new Error(`Bing · ${method}: ${msg}`), {
        hint:
          /key/i.test(msg)
            ? 'Похоже на неверный ключ. Перевыпустите: Settings → API Access → Generate.'
            : 'Bing отвечает 400 и на плохой ключ, и на плохой параметр — смотрите текст выше.',
      });
    }
    throw e;
  }
}

/** Даты Bing приходят в формате /Date(1316645995221-0700)/ */
function bingDate(v) {
  if (typeof v !== 'string') return '';
  const m = /\/Date\((-?\d+)/.exec(v);
  return m ? new Date(Number(m[1])).toISOString().slice(0, 10) : '';
}

const site = () => SITE_URL;

/**
 * Свернуть поднедельные строки в одну на ключ.
 * Показы и клики складываем, позицию усредняем по весу показов -
 * простое среднее по неделям завысило бы вклад недель с одним показом.
 */
function collapse(rows, keyField) {
  const acc = new Map();

  for (const r of rows) {
    const key = r[keyField] ?? '';
    if (!key) continue;
    const cur = acc.get(key) ?? { key, imp: 0, cl: 0, posWeighted: 0 };
    const imp = r.Impressions ?? 0;
    cur.imp += imp;
    cur.cl += r.Clicks ?? 0;
    cur.posWeighted += (r.AvgImpressionPosition ?? 0) * imp;
    acc.set(key, cur);
  }

  return [...acc.values()]
    .map((r) => ({ ...r, pos: r.imp ? r.posWeighted / r.imp : 0 }))
    .sort((x, y) => y.imp - x.imp);
}

run(async () => {
  const a = args();
  const limit = num(a.limit, 30);
  const out = (o) => console.log(JSON.stringify(o, null, 2));

  if (a.cmd === 'sites') {
    const res = await call('GetUserSites');
    if (a.json) return out(res);
    const sites = Array.isArray(res) ? res : [];
    title(`Сайты в Bing Webmaster Tools — ${sites.length}`);
    if (!sites.length) {
      warn('Ни одного сайта. Добавьте свой сайт на bing.com/webmasters —');
      note('  быстрее всего кнопкой «Import from Google Search Console».');
      return;
    }
    table(
      sites.map((s) => ({ u: s.Url, v: s.IsVerified ? 'да' : 'НЕТ' })),
      [{ key: 'u', title: 'Сайт', max: 50 }, { key: 'v', title: 'Права' }],
    );
    return;
  }

  if (a.cmd === 'queries') {
    const res = await call('GetQueryStats', { siteUrl: site() });
    if (a.json) return out(res);

    /* Bing отдаёт строку на каждую пару «запрос × неделя» за всю историю,
       без сортировки. Взять первые N - значит показать один и тот же запрос
       много раз подряд, да ещё и за самые старые недели. Сворачиваем. */
    const rows = collapse(Array.isArray(res) ? res : [], 'Query').slice(0, limit);

    title(`Запросы в Bing · ${site()}`);
    table(
      rows.map((r) => ({
        q: r.key,
        imp: r.imp,
        cl: r.cl,
        ctr: pct(r.imp ? (r.cl / r.imp) * 100 : 0),
        pos: r.pos.toFixed(1),
      })),
      [
        { key: 'q', title: 'Запрос', max: 55 },
        { key: 'imp', title: 'Показы', align: 'right' },
        { key: 'cl', title: 'Клики', align: 'right' },
        { key: 'ctr', title: 'CTR', align: 'right' },
        { key: 'pos', title: 'Позиция', align: 'right' },
      ],
    );
    return;
  }

  if (a.cmd === 'pages') {
    const res = await call('GetPageStats', { siteUrl: site() });
    if (a.json) return out(res);

    const rows = collapse(Array.isArray(res) ? res : [], 'Query').slice(0, limit);

    title(`Страницы в Bing · ${site()}`);
    table(
      rows.map((r) => ({
        u: r.key.replace(/^https?:\/\/[^/]+/, ''),
        imp: r.imp,
        cl: r.cl,
      })),
      [
        { key: 'u', title: 'Страница', max: 60 },
        { key: 'imp', title: 'Показы', align: 'right' },
        { key: 'cl', title: 'Клики', align: 'right' },
      ],
    );
    return;
  }

  if (a.cmd === 'traffic') {
    const res = await call('GetRankAndTrafficStats', { siteUrl: site() });
    if (a.json) return out(res);
    const rows = (Array.isArray(res) ? res : []).slice(-30);
    title(`Динамика в Bing · ${site()}`);
    table(
      rows.map((r) => ({ d: bingDate(r.Date), imp: r.Impressions, cl: r.Clicks })),
      [
        { key: 'd', title: 'Дата' },
        { key: 'imp', title: 'Показы', align: 'right' },
        { key: 'cl', title: 'Клики', align: 'right' },
      ],
    );
    return;
  }

  /* ── Исследование запросов: то, ради чего всё и затевалось ──────────── */
  if (a.cmd === 'keyword' || a.cmd === 'related') {
    const phrase = a._.join(' ').trim() || a.q;
    if (!phrase) {
      fail(`Укажите фразу: node seo/cli/bing.mjs ${a.cmd} "разработка сайта"`);
      process.exit(2);
    }

    const country = a.country ?? 'ru';
    const language = a.language ?? 'ru-RU';

    if (a.cmd === 'keyword') {
      const res = await call('GetKeywordStats', { q: phrase, country, language });
      if (a.json) return out(res);

      const rows = Array.isArray(res) ? res : [];
      title(`Частотность фразы «${phrase}» · ${country}/${language}`);

      if (!rows.length) {
        warn('Данных нет. Обычно это значит, что в индексе Bing по этой фразе');
        note('  слишком мало запросов — для русского рынка это частая история.');
        return;
      }

      table(
        rows.slice(-16).map((r) => ({
          d: bingDate(r.Date),
          e: r.Impressions,
          b: r.BroadImpressions,
        })),
        [
          { key: 'd', title: 'Неделя' },
          { key: 'e', title: 'Точное вхождение', align: 'right' },
          { key: 'b', title: 'Широкое', align: 'right' },
        ],
      );
      note('\n  Цифры — из индекса Bing. В России это единицы процентов рынка,');
      note('  поэтому сравнивайте фразы между собой, а не с реальным спросом.');
      return;
    }

    /* startDate и endDate у этого метода обязательны. Пример curl
       в документации Microsoft скопирован от другого метода и дат не
       содержит - по нему запрос всегда возвращает 400. */
    const end = new Date();
    const start = new Date(end);
    start.setUTCMonth(start.getUTCMonth() - 6);

    const res = await call('GetRelatedKeywords', {
      q: phrase,
      country,
      language,
      startDate: start.toISOString().slice(0, 10),
      endDate: end.toISOString().slice(0, 10),
    });
    if (a.json) return out(res);

    const rows = (Array.isArray(res) ? res : []).slice(0, limit);
    title(`Связанные запросы к «${phrase}»`);

    if (!rows.length) {
      warn('Связанных запросов Bing не нашёл.');
      return;
    }

    table(
      rows.map((r) => ({ q: r.Query ?? r.Keyword, imp: r.Impressions ?? r.BroadImpressions })),
      [
        { key: 'q', title: 'Запрос', max: 60 },
        { key: 'imp', title: 'Показы', align: 'right' },
      ],
    );
    note('\n  Это готовые кандидаты в заголовки статей и в подзаголовки страниц услуг.');
    return;
  }

  if (a.cmd === 'links') {
    const target = a._[0] || site();
    const res = await call('GetUrlLinks', { siteUrl: site(), link: target, page: 0 });
    if (a.json) return out(res);

    /* Ответ - объект с массивом Details, а не массив и не поле Links.
       Прочитать не то поле здесь особенно обидно: таблица выйдет пустой,
       и это прочитается как «ссылок на сайт нет». */
    const links = res?.Details ?? [];
    title(`Внешние ссылки на ${target}${res?.TotalPages > 1 ? ` · страница 1 из ${res.TotalPages}` : ''}`);
    table(
      links.slice(0, limit).map((l) => ({ u: l.Url ?? '', t: l.AnchorText ?? '' })),
      [
        { key: 'u', title: 'Откуда', max: 60 },
        { key: 't', title: 'Текст ссылки', max: 30 },
      ],
    );
    return;
  }

  if (a.cmd === 'issues') {
    const res = await call('GetCrawlIssues', { siteUrl: site() });
    if (a.json) return out(res);

    const rows = Array.isArray(res) ? res : [];
    title(`Проблемы обхода, найденные Bing — ${rows.length}`);
    if (!rows.length) return ok('Проблем не найдено.');

    /* В JSON поле Issues приходит числом - это битовая маска, а не текст.
       Напечатать её как есть - показать человеку «32» вместо «вредоносный код». */
    const ISSUE_BITS = [
      [1, 'не в индексе'],
      [2, 'закрыта в robots.txt'],
      [4, 'нет заголовка title'],
      [8, 'нет описания'],
      [16, 'заголовок слишком длинный'],
      [32, 'вредоносный код'],
      [64, 'ошибка ответа сервера'],
      [128, 'страница не найдена'],
      [256, 'перенаправление'],
      [512, 'слишком мало текста'],
    ];

    const describeIssues = (v) => {
      if (typeof v === 'string') return v;
      if (typeof v !== 'number' || !v) return '';
      const found = ISSUE_BITS.filter(([bit]) => v & bit).map(([, name]) => name);
      return found.length ? found.join(', ') : `код ${v}`;
    };

    table(
      rows.slice(0, limit).map((r) => ({
        u: (r.Url ?? '').replace(/^https?:\/\/[^/]+/, ''),
        c: r.HttpCode ?? '',
        i: describeIssues(r.Issues),
      })),
      [
        { key: 'u', title: 'Адрес', max: 50 },
        { key: 'c', title: 'Код', align: 'right' },
        { key: 'i', title: 'Что не так', max: 40 },
      ],
    );
    return;
  }

  console.log(`
  Bing Webmaster Tools — ${SITE_URL}

    sites                подтверждённые сайты (проверка ключа)
    queries              запросы, по которым находят сайт
    pages                страницы и их трафик
    traffic              динамика показов и кликов
    keyword <фраза>      частотность фразы по неделям
    related <фраза>      связанные запросы — расширение семантики
    links [url]          внешние ссылки
    issues               технические проблемы, найденные роботом

  Флаги: --country ru --language ru-RU --limit 30 --json

  Главная ценность здесь — keyword и related: бесплатная замена платным
  сервисам подбора запросов. Данные из индекса Bing, годятся как компас.
`);
});
