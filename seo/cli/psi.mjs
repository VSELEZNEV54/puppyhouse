#!/usr/bin/env node
/**
 * Скорость и техническое качество страниц - PageSpeed Insights API.
 *
 *   node seo/cli/psi.mjs                        главная, мобайл
 *   node seo/cli/psi.mjs --url https://...      конкретная страница
 *   node seo/cli/psi.mjs --strategy desktop     десктоп
 *   node seo/cli/psi.mjs all --limit 15         обход сайта по карте
 *   node seo/cli/psi.mjs --json                 сырые данные
 *
 * Что показываем. Google дает две разные вещи, и путать их дорого:
 *
 *   Лаборатория (Lighthouse) - синтетический прогон в дата-центре.
 *   Есть всегда, даже у сайта без трафика. По ней чинят конкретные
 *   проблемы: тяжелые картинки, блокирующий JS.
 *
 *   Поле (CrUX) - реальные замеры у живых посетителей Chrome за 28 дней.
 *   Именно эти цифры Google использует как сигнал ранжирования. Но у сайта
 *   с небольшим трафиком их может не быть вовсе - это нормально
 *   и не является ошибкой.
 *
 * Мобильная стратегия по умолчанию: Google ранжирует по мобильной версии
 * (mobile-first indexing), десктоп - справочно.
 */

import { googleApiKey } from '../lib/google-auth.mjs';
import { api, qs, ApiError } from '../lib/http.mjs';
import { siteUrls } from '../lib/sitemap.mjs';
import { SITE_URL } from '../lib/env.mjs';
import { args, num, table, title, note, run, ok, warn, fail } from '../lib/out.mjs';

const ENDPOINT = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed';

/* Пороги Core Web Vitals - официальные значения Google.
   good / needs improvement / poor */
const THRESHOLDS = {
  LCP: [2500, 4000],   // мс, отрисовка главного элемента
  INP: [200, 500],     // мс, отклик на действие
  CLS: [0.1, 0.25],    // сдвиг макета
  FCP: [1800, 3000],   // мс, первая отрисовка
  TTFB: [800, 1800],   // мс, ответ сервера
};

function verdict(metric, value) {
  const t = THRESHOLDS[metric];
  if (!t || value == null) return '—';
  if (value <= t[0]) return 'хорошо';
  if (value <= t[1]) return 'средне';
  return 'плохо';
}

/** Прогон одной страницы. */
async function measure(url, strategy) {
  const key = googleApiKey();

  const query = qs({
    url,
    strategy,
    key: key || undefined,
    /* Категории запрашиваем все полезные: производительность,
       доступность, лучшие практики и SEO-чеклист Lighthouse. */
    category: undefined,
  });

  /* category повторяется несколько раз - URLSearchParams в qs() так
     не умеет, добавляем руками. */
  const cats = ['performance', 'accessibility', 'best-practices', 'seo']
    .map((c) => `&category=${c}`)
    .join('');

  const data = await api(ENDPOINT + query + cats, {
    service: 'PageSpeed Insights',
    timeout: 120_000,       // полный прогон Lighthouse - до минуты
    retries: 2,
  });

  /* PageSpeed отвечает 200 и когда прогон провалился: страница не
     загрузилась, не дождались отрисовки. Ошибка лежит в runtimeError,
     а метрики приходят пустыми. Не проверить - значит показать LCP 0 мс
     и вывести сломанную страницу наверх сортировки как самую быструю. */
  const runtimeError = data?.lighthouseResult?.runtimeError;
  if (runtimeError?.code) {
    throw new ApiError(`PageSpeed не смог измерить ${url}: ${runtimeError.message ?? runtimeError.code}`, {
      service: 'PageSpeed Insights',
      hint: 'Проверьте, что адрес открывается и отдаёт 200 без редиректа.',
    });
  }

  const lh = data?.lighthouseResult ?? {};
  const cats2 = lh.categories ?? {};
  const audits = lh.audits ?? {};

  /* Полевые данные. loadingExperience - по URL, originLoadingExperience -
     по всему домену (бывает, что по конкретному URL данных мало,
     а по домену есть). */
  const fieldSrc = data?.loadingExperience?.metrics
    ? data.loadingExperience
    : data?.originLoadingExperience;

  const f = fieldSrc?.metrics ?? {};
  const field = {
    scope: data?.loadingExperience?.metrics ? 'страница' : 'весь домен',
    LCP: f.LARGEST_CONTENTFUL_PAINT_MS?.percentile ?? null,
    INP: f.INTERACTION_TO_NEXT_PAINT?.percentile ?? null,
    CLS: f.CUMULATIVE_LAYOUT_SHIFT_SCORE?.percentile != null
      ? f.CUMULATIVE_LAYOUT_SHIFT_SCORE.percentile / 100
      : null,
    FCP: f.FIRST_CONTENTFUL_PAINT_MS?.percentile ?? null,
    TTFB: f.EXPERIMENTAL_TIME_TO_FIRST_BYTE?.percentile ?? null,
    verdict: fieldSrc?.overall_category ?? null,
  };

  const score = (name) =>
    cats2[name]?.score != null ? Math.round(cats2[name].score * 100) : null;

  return {
    url,
    strategy,
    scores: {
      performance: score('performance'),
      accessibility: score('accessibility'),
      bestPractices: score('best-practices'),
      seo: score('seo'),
    },
    lab: {
      LCP: audits['largest-contentful-paint']?.numericValue ?? null,
      CLS: audits['cumulative-layout-shift']?.numericValue ?? null,
      FCP: audits['first-contentful-paint']?.numericValue ?? null,
      TBT: audits['total-blocking-time']?.numericValue ?? null,
      TTFB: audits['server-response-time']?.numericValue ?? null,
      speedIndex: audits['speed-index']?.numericValue ?? null,
    },
    field,
    /* Что чинить: проваленные проверки с оценкой веса. */
    opportunities: Object.values(audits)
      .filter(
        (a) =>
          a && a.score !== null && a.score < 0.9 &&
          (a.details?.type === 'opportunity' || a.numericValue > 0) &&
          a.title,
      )
      .map((a) => ({
        title: a.title,
        score: a.score,
        saving: a.details?.overallSavingsMs ?? a.numericValue ?? null,
        display: a.displayValue ?? '',
      }))
      .sort((a, b) => (b.saving ?? 0) - (a.saving ?? 0))
      .slice(0, 12),
    failedSeo: Object.entries(audits)
      .filter(([, a]) => a?.score === 0 && lh.categories?.seo?.auditRefs?.some((r) => r.id === a.id))
      .map(([, a]) => a.title),
  };
}

function printOne(r) {
  const s = r.scores;
  title(`${r.url}  ·  ${r.strategy === 'mobile' ? 'мобильные' : 'десктоп'}`);

  table(
    [
      { m: 'Производительность', v: s.performance },
      { m: 'Доступность', v: s.accessibility },
      { m: 'Лучшие практики', v: s.bestPractices },
      { m: 'SEO-чеклист', v: s.seo },
    ],
    [
      { key: 'm', title: 'Оценка Lighthouse (0–100)' },
      { key: 'v', title: 'Балл', align: 'right' },
    ],
  );

  title('Лаборатория — синтетический прогон');
  table(
    [
      { m: 'LCP — главный элемент', v: Math.round(r.lab.LCP ?? 0) + ' мс', z: verdict('LCP', r.lab.LCP) },
      { m: 'CLS — сдвиг макета', v: (r.lab.CLS ?? 0).toFixed(3), z: verdict('CLS', r.lab.CLS) },
      { m: 'FCP — первая отрисовка', v: Math.round(r.lab.FCP ?? 0) + ' мс', z: verdict('FCP', r.lab.FCP) },
      { m: 'TBT — блокировка потока', v: Math.round(r.lab.TBT ?? 0) + ' мс', z: '' },
      { m: 'Ответ сервера', v: Math.round(r.lab.TTFB ?? 0) + ' мс', z: verdict('TTFB', r.lab.TTFB) },
    ],
    [
      { key: 'm', title: 'Метрика' },
      { key: 'v', title: 'Значение', align: 'right' },
      { key: 'z', title: 'Оценка' },
    ],
  );

  if (r.field.LCP != null || r.field.CLS != null) {
    title(`Поле — реальные посетители Chrome за 28 дней (${r.field.scope})`);
    note('  Именно эти цифры Google учитывает при ранжировании.');
    table(
      [
        { m: 'LCP', v: r.field.LCP != null ? r.field.LCP + ' мс' : '—', z: verdict('LCP', r.field.LCP) },
        { m: 'INP', v: r.field.INP != null ? r.field.INP + ' мс' : '—', z: verdict('INP', r.field.INP) },
        { m: 'CLS', v: r.field.CLS != null ? r.field.CLS.toFixed(3) : '—', z: verdict('CLS', r.field.CLS) },
        { m: 'TTFB', v: r.field.TTFB != null ? r.field.TTFB + ' мс' : '—', z: verdict('TTFB', r.field.TTFB) },
      ],
      [
        { key: 'm', title: 'Метрика' },
        { key: 'v', title: 'Значение', align: 'right' },
        { key: 'z', title: 'Оценка' },
      ],
    );
  } else {
    title('Поле — реальные посетители');
    note('  Данных нет: у сайта пока мало трафика для статистики CrUX.');
    note('  Это не ошибка. Ориентируйтесь на лабораторные цифры.');
  }

  if (r.failedSeo.length) {
    title('Проваленные SEO-проверки Lighthouse');
    for (const t of r.failedSeo) fail(t);
  }

  if (r.opportunities.length) {
    title('Что чинить — по убыванию выигрыша');
    table(
      r.opportunities.map((o) => ({
        t: o.title,
        s: o.saving ? Math.round(o.saving) + ' мс' : o.display || '',
      })),
      [
        { key: 't', title: 'Проблема', max: 70 },
        { key: 's', title: 'Выигрыш', align: 'right' },
      ],
    );
  }
}

run(async () => {
  const a = args();
  const strategy = a.strategy === 'desktop' ? 'desktop' : 'mobile';

  if (!googleApiKey()) {
    warn(
      'GOOGLE_API_KEY не задан. Без ключа API сейчас не работает вовсе: общая ' +
        'анонимная квота Google исчерпана, приходит отказ. Документация Google ' +
        'до сих пор пишет «работает и без ключа» — это устарело. ' +
        'Ключ бесплатный и делается за пять минут: seo/SETUP.md, раздел 3.',
    );
  }

  if (a.cmd === 'all') {
    const limit = num(a.limit, 10);
    const urls = (await siteUrls()).slice(0, limit);
    const results = [];

    for (const [i, url] of urls.entries()) {
      note(`  [${i + 1}/${urls.length}] ${url}`);
      try {
        results.push(await measure(url, strategy));
      } catch (e) {
        fail(`${url} — ${e.message}`);
      }
      /* PageSpeed без ключа выдерживает считаные запросы в минуту,
         с ключом - 240 в минуту. Пауза страхует в обоих случаях. */
      if (i < urls.length - 1) await new Promise((r) => setTimeout(r, googleApiKey() ? 500 : 8000));
    }

    if (a.json) return console.log(JSON.stringify(results, null, 2));

    title(`Скорость страниц · ${strategy === 'mobile' ? 'мобильные' : 'десктоп'}`);
    table(
      results
        .map((r) => ({
          url: new URL(r.url).pathname,
          perf: r.scores.performance,
          seo: r.scores.seo,
          lcp: Math.round(r.lab.LCP ?? 0),
          cls: (r.lab.CLS ?? 0).toFixed(3),
        }))
        .sort((x, y) => (x.perf ?? 100) - (y.perf ?? 100)),
      [
        { key: 'url', title: 'Страница', max: 55 },
        { key: 'perf', title: 'Скорость', align: 'right' },
        { key: 'seo', title: 'SEO', align: 'right' },
        { key: 'lcp', title: 'LCP, мс', align: 'right' },
        { key: 'cls', title: 'CLS', align: 'right' },
      ],
    );
    note('\n  Сортировка от худших. Ниже 50 по скорости — разбираться в первую очередь.');
    return;
  }

  const url = a.url || SITE_URL;
  const r = await measure(url, strategy);

  if (a.json) return console.log(JSON.stringify(r, null, 2));
  printOne(r);
  ok('готово');
});
