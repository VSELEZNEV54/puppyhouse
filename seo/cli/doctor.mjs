#!/usr/bin/env node
/**
 * Карта доступов: что подключено, что нет, и что делать с недостающим.
 *
 *   node seo/cli/doctor.mjs           проверить всё
 *   node seo/cli/doctor.mjs --json    для машинной обработки
 *
 * Это первая команда, которую стоит запускать - и после настройки,
 * и когда что-то перестало работать. Она не просто говорит «нет доступа»,
 * а показывает, в каком пункте инструкции этот доступ берут.
 *
 * Проверка настоящая: каждый сервис реально дёргается самым дешёвым
 * запросом. Наличие переменной в файле ещё ничего не значит - токен
 * мог протухнуть, а права мог отозвать сам Яндекс при смене пароля.
 */

import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { homedir } from 'node:os';
import {
  get, has, envFileExists, SITE_URL, SITE_HOST, SEO_DIR,
  SHARED_ENV_PATH, sharedEnvExists, PROJECT_NAME, SITE_LABEL,
} from '../lib/env.mjs';
import { api } from '../lib/http.mjs';
import { serviceAccountEmail, google, googleApiKey } from '../lib/google-auth.mjs';
import { args, title, note, run, ok, warn, fail, table } from '../lib/out.mjs';

const CHECKS = [];

function check(name, need, fn, howto, hintFor) {
  CHECKS.push({ name, need, fn, howto, hintFor });
}

/* ─────────────────────────────  Яндекс  ─────────────────────────────────── */

check('Яндекс.Метрика', ['YANDEX_OAUTH_TOKEN', 'YANDEX_METRIKA_COUNTER'], async () => {
  const counter = get('YANDEX_METRIKA_COUNTER');
  const res = await api(
    `https://api-metrika.yandex.net/stat/v1/data?ids=${counter}&metrics=ym:s:visits&date1=7daysAgo&date2=yesterday`,
    { service: 'Метрика', retries: 1, headers: { Authorization: `OAuth ${get('YANDEX_OAUTH_TOKEN')}` } },
  );
  return `счётчик ${counter}, визитов за неделю: ${res?.totals?.[0] ?? 0}`;
}, 'seo/SETUP.md, раздел 1 — токен Яндекса');

check('Яндекс.Вебмастер', ['YANDEX_OAUTH_TOKEN'], async () => {
  const token = get('YANDEX_OAUTH_TOKEN');
  const me = await api('https://api.webmaster.yandex.net/v4/user/', {
    service: 'Вебмастер', retries: 1, headers: { Authorization: `OAuth ${token}` },
  });
  const hosts = await api(`https://api.webmaster.yandex.net/v4/user/${me.user_id}/hosts`, {
    service: 'Вебмастер', retries: 1, headers: { Authorization: `OAuth ${token}` },
  });
  const mine = (hosts?.hosts ?? []).find((h) => (h.ascii_host_url ?? '').includes(SITE_HOST));
  if (!mine) return `user_id ${me.user_id}, но сайта ${SITE_HOST} в кабинете нет`;
  return `${mine.verified ? 'права подтверждены' : 'ПРАВА НЕ ПОДТВЕРЖДЕНЫ'}, host_id ${mine.host_id}`;
}, 'seo/SETUP.md, раздел 1 — тот же токен Яндекса');

/* ─────────────────────────────  Google  ─────────────────────────────────── */

/* Ключ Google может лежать просто файлом в seo/keys/ без переменной -
   проверяем оба варианта, иначе doctor соврёт «не подключено». */
/* Те же два места, что и в google-auth.mjs: общее для всех проектов
   и локальное. Проверять только локальное - значит соврать «ключа нет»
   там, где он есть, просто лежит в общем месте. */
const LOCAL_KEY = resolve(SEO_DIR, 'keys', 'google-service-account.json');
const SHARED_KEY = resolve(homedir(), '.seo-tools', 'google-service-account.json');
const hasGoogleKey = () =>
  has('GOOGLE_SERVICE_ACCOUNT_KEY') || existsSync(LOCAL_KEY) || existsSync(SHARED_KEY);

check('Google Search Console', [], async () => {
  if (!hasGoogleKey()) throw Object.assign(new Error('ключ сервисного аккаунта не найден'), { missing: true });
  const res = await google('https://searchconsole.googleapis.com/webmasters/v3/sites', {
    scope: 'https://www.googleapis.com/auth/webmasters.readonly',
    service: 'Search Console',
    retries: 1,
  });
  const sites = res?.siteEntry ?? [];
  if (!sites.length) {
    return `ключ рабочий, но ресурсов нет — добавьте ${serviceAccountEmail()} в кабинет`;
  }
  return `ресурсов: ${sites.length} (${sites.map((s) => s.siteUrl).join(', ').slice(0, 60)})`;
}, 'seo/SETUP.md, раздел 2 — сервисный аккаунт Google');

check('PageSpeed Insights', ['GOOGLE_API_KEY'], async () => {
  /* 403 с текстом «Requests to this API ... are blocked» означает не
     отсутствие прав, а ограничения самого ключа: в Cloud Console у него
     список разрешённых API, и PageSpeed в него не попал. Общая подсказка
     про scope и добавление аккаунта в ресурс тут уводит не туда. */
  const res = await api(
    `https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=${encodeURIComponent(SITE_URL)}` +
      `&strategy=mobile&category=performance&key=${googleApiKey()}`,
    { service: 'PageSpeed', retries: 0, timeout: 120_000 },
  );
  const score = res?.lighthouseResult?.categories?.performance?.score;
  return `ключ рабочий, скорость главной: ${score != null ? Math.round(score * 100) : '—'}/100`;
}, null, (e) => {
  /* У PageSpeed 403 значит не «нет прав», а «ключу не разрешён этот API».
     Общая подсказка про scope и добавление аккаунта в ресурс тут врёт. */
  if (e.status === 403) {
    return 'У ключа стоят ограничения по API. console.cloud.google.com/apis/credentials → ' +
      'ваш ключ → «Ограничения API» → добавить PageSpeed Insights API.';
  }
  return null;
}, 'Если 403 «are blocked» — у ключа стоят ограничения по API: ' +
   'console.cloud.google.com/apis/credentials → ключ → «Ограничения API» → ' +
   'добавить PageSpeed Insights API. См. seo/SETUP.md, раздел 3');

/* ─────────────────────────────  Прочее  ─────────────────────────────────── */

check('IndexNow', ['INDEXNOW_KEY'], async () => {
  const key = get('INDEXNOW_KEY');
  let body;
  try {
    body = await api(`${SITE_URL}/${key}.txt`, { service: 'IndexNow', raw: true, retries: 1 });
  } catch (e) {
    /* 404 здесь означает ровно одно: ключ создан, но сайт после этого
       не выкладывали. Общая подсказка про «проверьте идентификатор»
       тут только сбивает с толку. */
    if (e.status === 404) {
      throw Object.assign(new Error('файла ключа нет на сайте — он ещё не выложен'), {
        hint: 'Выполните: npm run build && npm run deploy — и проверьте снова.',
      });
    }
    throw e;
  }
  if (body.trim() !== key) throw new Error(`файл ${key}.txt на сайте содержит другой ключ`);
  return 'ключ подтверждён — файл на сайте отдаёт 200 и совпадает';
}, 'node seo/cli/indexnow.mjs init, затем npm run build && npm run deploy');

check('Bing Webmaster', ['BING_API_KEY'], async () => {
  const res = await api(
    `https://ssl.bing.com/webmaster/api.svc/json/GetUserSites?apikey=${get('BING_API_KEY')}`,
    { service: 'Bing', retries: 1 },
  );
  const sites = res?.d ?? [];
  return `сайтов: ${Array.isArray(sites) ? sites.length : 0}`;
}, 'seo/SETUP.md, раздел 5 — не обязателен, но даёт бесплатный подбор запросов');

check('Яндекс.Директ', ['YANDEX_DIRECT_TOKEN'], async () => {
  const res = await api('https://api.direct.yandex.com/json/v5/campaigns', {
    method: 'POST',
    service: 'Директ',
    retries: 1,
    headers: {
      Authorization: `Bearer ${get('YANDEX_DIRECT_TOKEN')}`,
      'Accept-Language': 'ru',
    },
    json: { method: 'get', params: { SelectionCriteria: {}, FieldNames: ['Id', 'Name'] } },
  });
  /* Директ отвечает 200 даже на неверный токен — смотреть надо в тело. */
  if (res?.error) throw new Error(res.error.error_string ?? res.error.error_detail ?? 'отказ');
  return `кампаний: ${res?.result?.Campaigns?.length ?? 0}`;
}, 'seo/SETUP.md, раздел 6 — нужен только при платной рекламе, требует одобрения заявки');

/* ────────────────────────────────  Запуск  ──────────────────────────────── */

run(async () => {
  const a = args();

  title(`Доступы к сервисам · ${SITE_LABEL}`);

  if (!envFileExists) {
    fail('Ключей доступа не найдено.');
    note('  Ключи доступа лежат в ~/.seo-tools/.env — общие для всех проектов.');
    note('  Если их ещё нет, пройдите настройку: node seo/cli/setup.mjs');
    console.log('');
  } else {
    /* Источников два, и путать их дорого: при «доступ пропал» первый
       вопрос - какой именно файл смотрели. */
    if (sharedEnvExists) note(`  Ключи: ${SHARED_ENV_PATH}  (общие для всех проектов)`);
    note(`  Проект: ${PROJECT_NAME} · ${SITE_LABEL}`);
  }

  const results = [];

  for (const c of CHECKS) {
    const missing = c.need.filter((n) => !has(n));

    if (missing.length) {
      results.push({
        service: c.name,
        state: 'не подключено',
        detail: `не заданы: ${missing.join(', ')}`,
        howto: c.howto,
      });
      continue;
    }

    try {
      const detail = await c.fn();
      results.push({ service: c.name, state: 'работает', detail, howto: '' });
    } catch (e) {
      results.push({
        service: c.name,
        state: e.missing ? 'не подключено' : 'ошибка',
        detail: (e.message ?? String(e)).slice(0, 80),
        /* Своя подсказка проверки сильнее общей из ApiError: она знает
           про конкретный сервис, а общая - только про класс ошибки. */
        howto: c.hintFor?.(e) ?? e.hint ?? c.howto,
      });
    }
  }

  if (a.json) return console.log(JSON.stringify(results, null, 2));

  console.log('');
  for (const r of results) {
    if (r.state === 'работает') ok(`${r.service} — ${r.detail}`);
    else if (r.state === 'не подключено') warn(`${r.service} — ${r.detail}`);
    else fail(`${r.service} — ${r.detail}`);
    if (r.howto) note(`      ${r.howto}`);
  }

  const live = results.filter((r) => r.state === 'работает').length;
  const broken = results.filter((r) => r.state === 'ошибка').length;

  console.log('');
  title(`Итог: работает ${live} из ${results.length}`);

  if (broken) {
    warn(`${broken} доступ(ов) с ошибкой — это важнее, чем неподключённые:`);
    note('  значит, настройка была, но перестала работать. Частая причина —');
    note('  смена пароля Яндекс-аккаунта: она отзывает все токены разом.');
  }

  const critical = results.filter(
    (r) => ['Яндекс.Вебмастер', 'Яндекс.Метрика', 'Google Search Console'].includes(r.service) && r.state !== 'работает',
  );
  if (critical.length) {
    console.log('');
    note('  Без этих трёх автономная работа по сайту невозможна:');
    for (const c of critical) note(`    · ${c.service}`);
  } else {
    console.log('');
    ok('Основа на месте: видно и Яндекс, и Google. Можно работать.');
  }
});
