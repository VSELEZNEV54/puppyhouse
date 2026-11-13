#!/usr/bin/env node
/**
 * Мастер настройки доступов. Ведёт по шагам и всё записывает сам.
 *
 *     node seo/cli/setup.mjs
 *
 * Зачем он есть. Инструкция в SETUP.md требует открыть файл seo/.env
 * и вписать туда значения руками - для человека, который не работает
 * с кодом, это самый страшный шаг во всей настройке. Здесь его нет:
 * мастер печатает ссылку, ждёт, пока вы вставите скопированное,
 * и записывает сам.
 *
 * Мастер безопасно перезапускать: уже настроенные шаги он пропускает
 * и предлагает продолжить с того места, где остановились.
 *
 * Ничего не отправляет наружу, кроме официальных API Яндекса и Google.
 */

import { createInterface } from 'node:readline/promises';
import { stdin, stdout } from 'node:process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { get, has, setEnv, SEO_DIR, SITE_URL } from '../lib/env.mjs';
import { api } from '../lib/http.mjs';

/* ────────────────────────────  Оформление  ──────────────────────────────── */

const B = (s) => `\x1b[1m${s}\x1b[0m`;
const DIM = (s) => `\x1b[2m${s}\x1b[0m`;
const GREEN = (s) => `\x1b[32m${s}\x1b[0m`;
const RED = (s) => `\x1b[31m${s}\x1b[0m`;
const YELLOW = (s) => `\x1b[33m${s}\x1b[0m`;
const LINK = (s) => `\x1b[4;36m${s}\x1b[0m`;

const line = () => console.log(DIM('─'.repeat(64)));

function step(n, total, name) {
  console.log('');
  line();
  console.log(B(`  Шаг ${n} из ${total}. ${name}`));
  line();
  console.log('');
}

/** Крупно и отдельной строкой - чтобы ссылку было легко найти глазами. */
function url(u) {
  console.log('  Откройте в браузере:');
  console.log('');
  console.log('    ' + LINK(u));
  console.log('');
}

function say(...lines) {
  for (const l of lines) console.log('  ' + l);
  console.log('');
}

function ok(t) { console.log('  ' + GREEN('✓') + ' ' + t + '\n'); }
function bad(t) { console.log('  ' + RED('✗') + ' ' + t + '\n'); }
function warn(t) { console.log('  ' + YELLOW('!') + ' ' + t + '\n'); }

/* ──────────────────────────────  Ввод  ──────────────────────────────────── */

const rl = createInterface({ input: stdin, output: stdout });

const ask = async (q) => (await rl.question('  ' + q + ' ')).trim();

async function pause(text = 'Сделали — нажмите Enter, чтобы продолжить') {
  await rl.question(DIM('  ' + text + ' '));
  console.log('');
}

/** Спросить да/нет. Пустой ответ = да. */
async function yes(q) {
  const a = (await ask(q + ' ' + DIM('(Enter — да, «н» — нет)'))).toLowerCase();
  return a === '' || a === 'д' || a === 'да' || a === 'y' || a === 'yes';
}

/** Спросить значение, пока не введут непустое и подходящее. */
async function value(q, { check, hint, allowSkip = true } = {}) {
  for (;;) {
    const v = await ask(q);

    if (!v && allowSkip) {
      if (await yes('Пропустить этот шаг и вернуться к нему позже?')) return null;
      continue;
    }

    if (check && !check(v)) {
      bad(hint || 'Это не похоже на нужное значение. Попробуйте ещё раз.');
      continue;
    }

    return v;
  }
}

/* ───────────────────────────────  Шаги  ─────────────────────────────────── */

async function stepYandex() {
  step(1, 4, 'Яндекс: Метрика и Вебмастер');

  if (has('YANDEX_OAUTH_TOKEN')) {
    ok('Уже настроено — пропускаю.');
    return;
  }

  say(
    'Здесь мы создаём «приложение» — это просто способ Яндекса выдать',
    'доступ программе. Занимает минут десять.',
  );

  console.log(B('  А. Проверьте, под каким аккаунтом вы вошли'));
  console.log('');
  url('https://id.yandex.ru');
  say(
    'Вверху справа будет ваш логин.',
    '',
    'Это самый важный момент во всей настройке: доступ получит именно',
    'тот аккаунт, под которым вы сейчас в браузере. Нужен тот, где',
    'нужный счётчик Метрики и подтверждён ваш сайт в Вебмастере.',
    '',
    'Если логин не тот — выйдите и войдите под нужным.',
  );
  await pause();

  console.log(B('  Б. Создайте приложение'));
  console.log('');
  url('https://oauth.yandex.ru/client/new/');
  say(
    'Что нажимать:',
    '',
    '  1. В окошке выбора нажмите  «Для доступа к API или отладки»',
    '     ' + DIM('(не «Для авторизации пользователей» — потом не поменять)'),
    '',
    '  2. «Название вашего сервиса» — напишите:  SEO Agent',
    '',
    '  3. «Контактная почта» — ваша рабочая почта',
    '',
    '  4. Блок «Доступ к данным». Введите по одному и выбирайте',
    '     из выпадающей подсказки ровно четыре пункта:',
    '',
    '          metrika:read',
    '          metrika:write',
    '          webmaster:hostinfo',
    '          webmaster:verify',
    '',
    '     ' + DIM('Больше ничего не добавляйте: лишние права сокращают срок'),
    '     ' + DIM('жизни доступа.'),
    '',
    '  5. Нажмите  «Создать приложение»',
  );
  await pause();

  console.log(B('  В. Скопируйте два значения со страницы приложения'));
  console.log('');
  say(
    'На открывшейся странице будет  ClientID  — длинная строка из букв',
    'и цифр, рядом значок копирования. И  Client secret  — его, возможно,',
    'нужно будет открыть кнопкой «Показать».',
    '',
    'Копируете в браузере — вставляете ' + B('сюда, в это окно') + '.',
  );

  const id = await value(
    'Вставьте сюда ClientID и нажмите Enter:',
    {
      check: (v) => v.length >= 20 && !v.includes(' '),
      hint: 'ClientID — длинная строка без пробелов, обычно 32 символа.',
    },
  );
  if (!id) return;

  const secret = await value(
    'Теперь вставьте Client secret:',
    {
      check: (v) => v.length >= 20 && !v.includes(' '),
      hint: 'Client secret — тоже длинная строка без пробелов.',
    },
  );
  if (!secret) return;

  setEnv({ YANDEX_CLIENT_ID: id, YANDEX_CLIENT_SECRET: secret });
  ok('Записал. Файл с доступами закрыт от посторонних и не уезжает в репозиторий.');

  console.log(B('  Г. Разрешите доступ'));
  console.log('');

  const authUrl =
    `https://oauth.yandex.ru/authorize?response_type=code&client_id=${id}` +
    `&scope=${encodeURIComponent('metrika:read metrika:write webmaster:hostinfo webmaster:verify')}` +
    '&force_confirm=yes';

  url(authUrl);
  say(
    'Нажмите там  «Разрешить».',
    '',
    'Яндекс покажет  код подтверждения  — короткую строку.',
    'Она может быть из цифр, а может из букв и цифр — оба варианта нормальны.',
    '',
    'Скопируйте его, вернитесь ' + B('в это окно') + ' и вставьте в строку ниже.',
    'Код живёт 10 минут, поэтому не откладывайте.',
  );

  const code = await value(
    'Вставьте код подтверждения:',
    {
      /* Формат кода Яндекс не фиксирует: бывают и цифры, и латинские буквы.
         Проверять на «только цифры» нельзя - живой код с буквами такая
         проверка отвергнет, и человек упрётся на ровном месте.
         Ловим только явные промахи: пробелы внутри и вставленную целиком
         ссылку из адресной строки. */
      check: (v) => /^[A-Za-z0-9_-]{4,100}$/.test(v),
      hint:
        'Нужен только сам код — без пробелов и без адреса страницы. ' +
        'Если скопировали всю ссылку, возьмите из неё часть после code=',
    },
  );
  if (!code) return;

  /* Иногда в руках оказывается не код, а сразу готовый токен: так бывает,
     если открылась ссылка вида response_type=token. Токен узнаётся по
     началу y0_ и длине. Менять его на что-то не нужно - он уже готов. */
  if (/^y0_/.test(code) && code.length > 40) {
    setEnv({ YANDEX_OAUTH_TOKEN: code });
    ok('Это уже готовый доступ, а не код — записал его сразу.');
    warn('Только учтите: такой доступ придётся обновлять вручную примерно раз в полгода.');
    say('Чтобы обновление шло само, позже можно пройти шаг заново по ссылке из пункта Г.');
    return;
  }

  console.log('  Меняю код на доступ…\n');

  try {
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      device_id: get('YANDEX_DEVICE_ID') || (await import('node:crypto')).randomUUID(),
      device_name: 'seo-agent',
    });

    const res = await api('https://oauth.yandex.ru/token', {
      method: 'POST',
      service: 'Яндекс OAuth',
      retries: 1,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Authorization: 'Basic ' + Buffer.from(`${id}:${secret}`).toString('base64'),
      },
      json: body.toString(),
    });

    setEnv({
      YANDEX_OAUTH_TOKEN: res.access_token,
      YANDEX_OAUTH_REFRESH: res.refresh_token ?? '',
      YANDEX_OAUTH_EXPIRES: new Date(Date.now() + (res.expires_in ?? 0) * 1000)
        .toISOString()
        .slice(0, 10),
      YANDEX_DEVICE_ID: body.get('device_id'),
    });

    ok('Готово! Метрика и Вебмастер подключены.');
    say(DIM('Продлевать доступ вручную не придётся — это делается само.'));
  } catch (e) {
    bad('Не получилось: ' + e.message);
    say(
      'Частые причины:',
      '  · код просрочен (живёт 10 минут) — начните шаг Г заново',
      '  · код скопирован с лишним пробелом',
      '  · вставлен не тот ClientID',
      '',
      'Запустите мастер ещё раз: node seo/cli/setup.mjs',
    );
  }
}

async function stepGoogleConsole() {
  step(2, 4, 'Google Search Console');

  const keyPath = resolve(SEO_DIR, 'keys', 'google-service-account.json');
  if (existsSync(keyPath)) {
    ok('Ключ на месте — пропускаю.');
    return;
  }

  say(
    'Здесь мы заводим отдельную «служебную учётку» Google. Она нужна,',
    'чтобы доступ не приходилось подтверждать заново каждую неделю.',
    '',
    'Банковская карта НЕ нужна. Если Google предложит пробный период —',
    'просто закройте это предложение.',
    '',
    YELLOW('Возможна помеха:') + ' Google Cloud из России открывается не всегда.',
    'Если страница не грузится — включите VPN. Зайти туда нужно один раз.',
  );
  await pause('Понятно — нажмите Enter');

  console.log(B('  А. Создайте проект'));
  console.log('');
  url('https://console.cloud.google.com/projectcreate');
  say(
    '  1. «Название проекта» — напишите:  seo-tools',
    '  2. Остальное не трогайте',
    '  3. Нажмите  «Создать»  и подождите секунд двадцать',
  );
  await pause();

  console.log(B('  Б. Включите нужную функцию'));
  console.log('');
  url('https://console.cloud.google.com/apis/library/searchconsole.googleapis.com');
  say(
    'Нажмите синюю кнопку  «Включить».',
    'Когда надпись сменится на «Управление» — готово.',
    '',
    DIM('Если вверху страницы выбран другой проект — переключите на seo-tools.'),
  );
  await pause();

  console.log(B('  В. Создайте служебную учётку'));
  console.log('');
  url('https://console.cloud.google.com/iam-admin/serviceaccounts');
  say(
    '  1. Нажмите  «+ Создать сервисный аккаунт»',
    '',
    '  2. «Название» — напишите:  seo-agent',
    '',
    '  3. ' + B('Под полем появится ПОЧТА') + ' вида',
    '     seo-agent@seo-tools-12345.iam.gserviceaccount.com',
    '     ' + B('Скопируйте её — она понадобится через минуту.'),
    '',
    '  4. Нажмите  «Создать и продолжить»',
    '',
    '  5. Дальше два шага про доступ и пользователей —',
    '     ' + B('ничего не выбирайте'),
    '     Нажмите  «Продолжить», потом  «Готово»',
  );

  const email = await value(
    'Вставьте сюда скопированную почту служебной учётки:',
    {
      check: (v) => v.includes('@') && v.includes('gserviceaccount.com'),
      hint: 'Почта должна заканчиваться на @…iam.gserviceaccount.com',
    },
  );

  console.log('');
  console.log(B('  Г. Скачайте файл-ключ'));
  console.log('');
  say(
    'На той же странице:',
    '',
    '  1. Нажмите на созданную учётку (на саму почту)',
    '  2. Перейдите на вкладку  «Ключи»',
    '  3. «Добавить ключ»  →  «Создать новый ключ»',
    '  4. Тип  «JSON»  →  «Создать»',
    '',
    'Браузер скачает файл в «Загрузки».',
    '',
    B('  5. Переименуйте его ровно в:'),
    '',
    '        google-service-account.json',
    '',
    B('  6. И положите сюда:'),
    '',
    '        ' + resolve(SEO_DIR, 'keys'),
    '',
    DIM('Файл скачивается один раз — потеряете, придётся делать новый ключ.'),
    DIM('Никому его не пересылайте.'),
  );
  await pause('Положили файл — нажмите Enter');

  if (!existsSync(keyPath)) {
    warn('Файла по этому пути пока не вижу.');
    say(
      'Проверьте:',
      '  · имя ровно  google-service-account.json  (без «(1)» на конце)',
      '  · папка  ' + resolve(SEO_DIR, 'keys'),
      '',
      'Ничего страшного — положите и запустите мастер заново.',
    );
  } else {
    ok('Файл на месте.');
  }

  console.log(B('  Д. Самое главное: дайте учётке доступ в кабинет'));
  console.log('');
  say(
    YELLOW('Этот шаг пропускают чаще всего.') + ' Без него ключ будет рабочим,',
    'а сайтов Google не покажет.',
  );
  url('https://search.google.com/search-console/users');
  say(
    '  1. Вверху слева выберите свой сайт',
    '  2. Нажмите  «Добавить пользователя»',
    '  3. В поле почты вставьте:',
    '',
    '        ' + (email || 'ту самую почту @…iam.gserviceaccount.com'),
    '',
    '  4. В списке «Разрешение» выберите  «Владелец»',
    '     ' + DIM('(если недоступно — «Полный». «Ограниченный» не подойдёт)'),
    '  5. Нажмите  «Добавить»',
  );
  await pause();

  if (existsSync(keyPath)) {
    console.log('  Проверяю доступ…\n');
    try {
      const { google } = await import('../lib/google-auth.mjs');
      const res = await google('https://searchconsole.googleapis.com/webmasters/v3/sites', {
        scope: 'https://www.googleapis.com/auth/webmasters.readonly',
        service: 'Search Console',
        retries: 1,
      });
      const sites = res?.siteEntry ?? [];
      if (sites.length) {
        ok(`Работает. Google показывает сайтов: ${sites.length}`);
      } else {
        warn('Ключ рабочий, но сайтов не видно.');
        say(
          'Скорее всего, не выполнен шаг Д, либо права ещё расходятся —',
          'это занимает до пяти минут. Проверьте позже:',
          '',
          '    node seo/cli/doctor.mjs',
        );
      }
    } catch (e) {
      warn('Пока не отвечает: ' + e.message);
      say('Права расходятся до пяти минут. Проверьте позже: node seo/cli/doctor.mjs');
    }
  }
}

async function stepPageSpeed() {
  step(3, 4, 'Проверка скорости сайта');

  if (has('GOOGLE_API_KEY')) {
    ok('Уже настроено — пропускаю.');
    return;
  }

  say(
    'Короткий шаг. Нужен «ключ» — строка, которая начинается на AIza.',
    'Без него эта проверка не работает совсем.',
  );

  console.log(B('  А. Включите функцию'));
  console.log('');
  url('https://console.cloud.google.com/apis/library/pagespeedonline.googleapis.com');
  say('Нажмите  «Включить».');
  await pause();

  console.log(B('  Б. Создайте ключ'));
  console.log('');
  url('https://console.cloud.google.com/apis/credentials');
  say(
    '  1. Нажмите  «+ Создать учётные данные»',
    '  2. Выберите  «Ключ API»',
    '  3. Появится окно с ключом — нажмите значок копирования',
  );

  const key = await value(
    'Вставьте ключ (начинается на AIza):',
    {
      check: (v) => v.startsWith('AIza') && v.length > 30,
      hint: 'Ключ начинается на AIza и довольно длинный.',
    },
  );
  if (!key) return;

  setEnv({ GOOGLE_API_KEY: key });
  ok('Записал.');

  console.log('  Проверяю…\n');
  try {
    const res = await api(
      `https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=${encodeURIComponent(SITE_URL)}` +
        `&strategy=mobile&category=performance&key=${key}`,
      { service: 'PageSpeed', retries: 0, timeout: 120_000 },
    );
    const score = res?.lighthouseResult?.categories?.performance?.score;
    ok(`Работает. Скорость главной страницы: ${score != null ? Math.round(score * 100) : '—'} из 100`);
  } catch (e) {
    warn('Пока не отвечает: ' + e.message);
    say('Иногда ключ начинает работать через пару минут. Проверьте: node seo/cli/psi.mjs');
  }
}

async function stepDeploy() {
  step(4, 4, 'Выложить сайт');

  say(
    'Последнее. На сайт уже положен файл, который разрешает мне',
    'сообщать Яндексу и Bing об изменениях — но он заработает только',
    'после того, как сайт будет выложен заново.',
    '',
    'Команда:',
    '',
    '    ' + B('npm run build && npm run deploy'),
    '',
    'Её можно выполнить и позже, вместе с ближайшими правками.',
  );

  await pause('Прочитал — нажмите Enter');
}

/* ──────────────────────────────  Запуск  ────────────────────────────────── */

async function main() {
  /* Мастер спрашивает и ждёт ответа. Без живого терминала он молча
     оборвался бы на первом же вопросе - лучше сказать об этом прямо. */
  if (!stdin.isTTY) {
    console.error('');
    console.error('  Этот мастер нужно запускать в терминале — он задаёт вопросы.');
    console.error('');
    console.error('  Откройте Терминал, перейдите в папку проекта и выполните:');
    console.error('');
    console.error('      node seo/cli/setup.mjs');
    console.error('');
    console.error('  Если нужна инструкция текстом — она в seo/SETUP.md');
    console.error('');
    process.exit(1);
  }

  console.clear();
  console.log('');
  console.log(B('  Настройка доступов'));
  console.log('');
  say(
    'Я буду показывать ссылки и говорить, что нажимать.',
    '',
    'Работа выглядит так: открываете ссылку в браузере, копируете оттуда',
    'что попрошу, возвращаетесь ' + B('в это окно') + ', вставляете и жмёте Enter.',
    'Записывать что-то в файлы не нужно — это я сделаю сам.',
    '',
    'Всё бесплатно, карта нигде не потребуется.',
    'Займёт около получаса. Прерваться можно в любой момент:',
    'запустите мастер снова, и он продолжит с того же места.',
  );

  await pause('Начинаем — нажмите Enter');

  await stepYandex();
  await stepGoogleConsole();
  await stepPageSpeed();
  await stepDeploy();

  console.log('');
  line();
  console.log(B('  Готово. Проверяю, что получилось…'));
  line();
  console.log('');

  rl.close();

  /* Финальную сводку рисует doctor - незачем дублировать её логику. */
  const { spawn } = await import('node:child_process');
  spawn(process.execPath, [resolve(SEO_DIR, 'cli', 'doctor.mjs')], { stdio: 'inherit' });
}

main().catch((e) => {
  console.error('\n' + RED('  Что-то пошло не так: ' + (e.message || e)));
  console.error(DIM('  Запустите мастер заново: node seo/cli/setup.mjs\n'));
  rl.close();
  process.exit(1);
});
