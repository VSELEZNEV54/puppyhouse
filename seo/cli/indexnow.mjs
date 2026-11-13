#!/usr/bin/env node
/**
 * IndexNow - мгновенное уведомление поисковиков об изменившихся страницах.
 *
 *   node seo/cli/indexnow.mjs init            создать ключ и файл ключа
 *   node seo/cli/indexnow.mjs changed         только изменившиеся страницы
 *   node seo/cli/indexnow.mjs ping <url...>   конкретные адреса
 *   node seo/cli/indexnow.mjs since 7         изменённые за N дней по lastmod
 *   node seo/cli/indexnow.mjs all             весь сайт (первый запуск)
 *
 * Зачем это при живых Вебмастере и Search Console. Переобход в Вебмастере
 * ограничен примерно двумя десятками адресов в сутки и делается руками
 * в интерфейсе. IndexNow - открытый протокол: отправляем список адресов
 * одним запросом, без квоты такого порядка и без кабинета. Яндекс - один
 * из авторов протокола и поддерживает его напрямую, Bing тоже.
 * Google в IndexNow не участвует - для него остаётся Search Console.
 *
 * Как протокол подтверждает, что адреса шлёт владелец сайта: на сайте
 * лежит файл <ключ>.txt, внутри - тот же ключ. Поисковик его читает
 * и убеждается, что отправитель управляет доменом. Поэтому ключ
 * не секрет: он и так открыто лежит на сайте. Секретного здесь нет,
 * менять его при утечке не нужно.
 */

import { writeFileSync, existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { randomBytes } from 'node:crypto';
import { api } from '../lib/http.mjs';
import { get, PUBLIC_DIR, SITE_HOST, SITE_URL } from '../lib/env.mjs';
import { siteUrls, siteUrlsWithDates } from '../lib/sitemap.mjs';
import { changedPages, saveSnapshot, SNAPSHOT_PATH } from '../lib/dist-hash.mjs';
import { args, num, title, note, run, ok, warn, fail, table } from '../lib/out.mjs';

/* Основной приёмник один. api.indexnow.org сам раздаёт заявку всем
   участникам протокола - слать тот же список ещё и напрямую в Яндекс
   с Bing означает тройную нагрузку ради нулевого выигрыша и лишний риск
   упереться в 429. Прямые адреса держим только как запасной путь,
   на случай недоступности общего шлюза. */
const PRIMARY = { name: 'IndexNow (общий шлюз)', url: 'https://api.indexnow.org/indexnow' };
const FALLBACKS = [
  { name: 'Яндекс напрямую', url: 'https://yandex.com/indexnow' },
  { name: 'Bing напрямую', url: 'https://www.bing.com/indexnow' },
];

const MAX_PER_REQUEST = 10_000;

function keyFilePath(key) {
  return resolve(PUBLIC_DIR, `${key}.txt`);
}

function currentKey() {
  const fromEnv = get('INDEXNOW_KEY');
  if (fromEnv) return fromEnv;

  /* Ключ мог быть создан раньше и лежать в public/ - подхватим его,
     чтобы не плодить новые при каждой пересборке окружения. */
  return '';
}

async function send(key, urls) {
  const body = {
    host: SITE_HOST,
    key,
    keyLocation: `${SITE_URL}/${key}.txt`,
    urlList: urls,
  };

  const attempt = async (ep) => {
    /* 200 и 202 - оба успех. 202 означает «ключ принят, идёт проверка»
       и на первой отправке встречается штатно; считать его ошибкой
       и повторять запрос не нужно. */
    await api(ep.url, { method: 'POST', service: ep.name, retries: 1, json: body });
    return { ep: ep.name, status: 'принято' };
  };

  const why = (e) =>
    e.status === 403
      ? `ключ не подтверждён — ${SITE_URL}/${key}.txt должен отдавать 200`
      : e.status === 422
        ? 'адреса не с этого домена либо ключ не совпадает с файлом'
        : e.message;

  try {
    return [await attempt(PRIMARY)];
  } catch (e) {
    const results = [{ ep: PRIMARY.name, status: `ошибка: ${why(e)}` }];

    /* Общий шлюз не ответил - пробуем достучаться напрямую. */
    for (const ep of FALLBACKS) {
      try {
        results.push(await attempt(ep));
      } catch (e2) {
        results.push({ ep: ep.name, status: `ошибка: ${why(e2)}` });
      }
    }
    return results;
  }
}

run(async () => {
  const a = args();

  /* ── init: создать ключ и положить файл в public/ ─────────────────── */
  if (a.cmd === 'init') {
    const existing = currentKey();
    if (existing && !a.force) {
      warn(`Ключ уже задан: ${existing}`);
      note(`  Файл: ${keyFilePath(existing)}`);
      note('  Пересоздать: node seo/cli/indexnow.mjs init --force');
      return;
    }

    const key = randomBytes(16).toString('hex'); // 32 символа, разрешено 8–128
    const path = keyFilePath(key);
    writeFileSync(path, key, 'utf8');

    title('Ключ IndexNow создан');
    console.log(`\n  Ключ:  ${key}`);
    console.log(`  Файл:  public/${key}.txt`);
    console.log(`  Адрес: ${SITE_URL}/${key}.txt  (появится после деплоя)\n`);

    note('  Осталось два шага:');
    console.log(`    1. Впишите в seo/.env:  INDEXNOW_KEY=${key}`);
    console.log('    2. Соберите и выложите сайт:  npm run build && npm run deploy');
    console.log('');
    note('  Файл public/<ключ>.txt удалять нельзя — на нём держится подтверждение прав.');
    return;
  }

  const KNOWN = ['init', 'changed', 'ping', 'all', 'since'];
  /* Справка не должна упираться в проверку ключа: человек может открыть
     её раньше, чем что-либо настроит. */
  if (!a.cmd || !KNOWN.includes(a.cmd)) {
    console.log(`
  IndexNow — мгновенное уведомление Яндекса и Bing об изменениях.

    node seo/cli/indexnow.mjs init             создать ключ (один раз)
    node seo/cli/indexnow.mjs changed          ТОЛЬКО изменившиеся страницы — так правильно
    node seo/cli/indexnow.mjs ping /uslugi/    конкретные адреса
    node seo/cli/indexnow.mjs since 7          изменённые за N дней по lastmod
    node seo/cli/indexnow.mjs all              весь сайт (только при первом запуске)

  Яндекс просит присылать лишь изменившиеся адреса: массовая переотправка
  одного и того же ничего не ускоряет и выглядит как спам.
`);
    return;
  }

  const key = currentKey();
  if (!key) {
    fail('Ключ IndexNow не создан.');
    note('  Создайте: node seo/cli/indexnow.mjs init');
    process.exit(2);
  }

  /* Перед отправкой убеждаемся, что файл ключа доступен снаружи.
     Иначе поисковик молча проигнорирует весь список. */
  if (!a.skipCheck) {
    try {
      const body = await api(`${SITE_URL}/${key}.txt`, { service: 'файл ключа', raw: true, retries: 1 });
      if (body.trim() !== key) {
        fail(`Файл ${SITE_URL}/${key}.txt содержит не тот ключ.`);
        note('  Внутри файла должен лежать ровно ключ, без пробелов и переводов строки.');
        process.exit(1);
      }
    } catch {
      fail(`Файл ключа недоступен: ${SITE_URL}/${key}.txt`);
      note('  Похоже, сайт ещё не пересобран после init. Выполните: npm run build && npm run deploy');
      process.exit(1);
    }
  }

  /* ── какие адреса отправляем ──────────────────────────────────────── */
  let urls = [];

  if (a.cmd === 'ping') {
    urls = a._.filter(Boolean).map((u) => (u.startsWith('http') ? u : `${SITE_URL}${u.startsWith('/') ? '' : '/'}${u}`));
    if (!urls.length) {
      fail('Не переданы адреса. Пример: node seo/cli/indexnow.mjs ping /uslugi/ /blog/');
      process.exit(2);
    }
  } else if (a.cmd === 'changed') {
    /* Главный режим для деплоя: шлём только то, что реально изменилось
       в собранном сайте с прошлого раза. Именно об этом просит Яндекс. */
    const diff = changedPages();

    if (diff.first) {
      warn('Снимка прошлой сборки нет — это первый запуск.');
      note(`  Запоминаю текущее состояние (${diff.total} стр.) как эталон.`);
      note('  Отправлять весь сайт не буду: в следующий раз уйдут только изменения.');
      note('  Если нужно всё сразу — node seo/cli/indexnow.mjs all');
      saveSnapshot(diff.snapshot);
      return;
    }

    urls = [...diff.added, ...diff.changed];

    if (diff.removed.length) {
      warn(`Со сборки исчезло страниц: ${diff.removed.length}. IndexNow про удаление не сообщает —`);
      note('  проверьте, что на их адресах стоит 301 или 410, иначе останутся битые ссылки в выдаче.');
      for (const u of diff.removed.slice(0, 10)) note('    ' + u);
    }

    if (!urls.length) {
      ok('Изменившихся страниц нет — отправлять нечего.');
      return;
    }

    note(`  Новых: ${diff.added.length}, изменённых: ${diff.changed.length}, всего в сборке: ${diff.total}`);
    /* Снимок обновляем только после успешной отправки — иначе при сбое
       изменения потеряются и во второй раз уже не уйдут. */
    a.__snapshot = diff.snapshot;
  } else if (a.cmd === 'all') {
    urls = await siteUrls();
  } else if (a.cmd === 'since') {
    const days = num(a._[0] ?? a.days, 7);
    const edge = Date.now() - days * 86_400_000;
    const withDates = await siteUrlsWithDates();
    urls = withDates
      .filter((u) => u.lastmod && new Date(u.lastmod).getTime() >= edge)
      .map((u) => u.url);

    if (!urls.length) {
      warn(`За последние ${days} дн. в карте сайта нет изменённых страниц.`);
      note('  Если правки были — проверьте lastmod в sitemap: он может стоять один на весь сайт.');
      return;
    }
  }

  if (urls.length > MAX_PER_REQUEST) {
    warn(`Адресов ${urls.length}, за один раз шлём не больше ${MAX_PER_REQUEST}. Отправим первые.`);
    urls = urls.slice(0, MAX_PER_REQUEST);
  }

  title(`Отправка ${urls.length} адр. в IndexNow`);
  for (const u of urls.slice(0, 15)) note('  ' + u);
  if (urls.length > 15) note(`  … и ещё ${urls.length - 15}`);

  const results = await send(key, urls);

  console.log('');
  table(results, [
    { key: 'ep', title: 'Приёмник' },
    { key: 'status', title: 'Результат', max: 80 },
  ]);

  const good = results.filter((r) => r.status === 'принято').length;
  console.log('');
  if (good) {
    ok(`Принято приёмниками: ${good} из ${results.length}`);
    if (a.__snapshot) {
      saveSnapshot(a.__snapshot);
      note(`  Снимок сборки обновлён: ${SNAPSHOT_PATH.replace(process.cwd() + '/', '')}`);
    }
  } else {
    fail('Ни один приёмник не принял список — см. причины выше.');
    if (a.__snapshot) note('  Снимок НЕ обновлён: при следующем запуске эти же адреса уйдут снова.');
  }

  note('\n  «Принято» означает, что список получен, а не что страницы уже в индексе.');
  note('  Скорость обхода поисковик решает сам.');
});
