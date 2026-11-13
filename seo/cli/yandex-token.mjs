#!/usr/bin/env node
/**
 * Получение и продление OAuth-токена Яндекса.
 *
 *   node seo/cli/yandex-token.mjs             инструкция, что делать
 *   node seo/cli/yandex-token.mjs url         ссылка, которую открыть в браузере
 *   node seo/cli/yandex-token.mjs exchange 1234567    обмен кода на токен
 *   node seo/cli/yandex-token.mjs refresh     продлить токен (без человека)
 *   node seo/cli/yandex-token.mjs check       жив ли токен и что им можно
 *   node seo/cli/yandex-token.mjs revoke      отозвать токен
 *
 * Одним токеном закрываются и Метрика, и Вебмастер - это одно приложение
 * с четырьмя правами. Директ живёт отдельно и намеренно: изменение прав
 * у приложения отзывает ВСЕ выданные им токены, поэтому дописывать
 * direct:api в рабочее приложение нельзя - агент мгновенно ослепнет.
 *
 * Почему схема с кодом, а не «токен сразу в адресной строке». Быстрый
 * способ (response_type=token) не выдаёт refresh_token: через полгода
 * придётся всё повторять руками. Схема с кодом даёт пару токенов, и
 * дальше продление идёт само - `refresh` можно поставить в cron.
 *
 * Токен запрашивается с device_id. Это единственный способ сохранить
 * возможность отозвать его из скрипта: без device_id Яндекс отзывать
 * токен через API отказывается, остаётся только идти руками в id.yandex.ru.
 */

import { randomUUID } from 'node:crypto';
import { api } from '../lib/http.mjs';
import { get, setEnv, ENV_PATH, has } from '../lib/env.mjs';
import { yandexToken } from '../lib/yandex.mjs';
import { args, title, note, run, ok, warn, fail, table } from '../lib/out.mjs';

const OAUTH = 'https://oauth.yandex.ru';

/* Четыре права закрывают всё, что нужно агенту в Метрике и Вебмастере.
   Больше не берём: лишние права сокращают срок жизни токена (берётся
   наименьшее ограничение среди всех выбранных). */
const SCOPES = ['metrika:read', 'metrika:write', 'webmaster:hostinfo', 'webmaster:verify'];

function clientId() {
  const v = get('YANDEX_CLIENT_ID');
  if (v) return v;
  fail('Не задан YANDEX_CLIENT_ID.');
  note('  Приложение создаётся один раз на https://oauth.yandex.ru/client/new/');
  note('  Пошагово — seo/SETUP.md, раздел 1.');
  process.exit(2);
}

/** Стабильный идентификатор устройства: заводим один раз и запоминаем. */
function deviceId() {
  let v = get('YANDEX_DEVICE_ID');
  if (!v) {
    v = randomUUID();
    setEnv({ YANDEX_DEVICE_ID: v });
  }
  return v;
}

/** Обмен на пару токенов. Всё уходит в теле, urlencoded — иначе invalid_request. */
async function tokenRequest(params) {
  const id = clientId();
  const secret = get('YANDEX_CLIENT_SECRET');
  if (!secret) {
    fail('Не задан YANDEX_CLIENT_SECRET.');
    note('  Он на странице приложения в oauth.yandex.ru, рядом с ClientID.');
    process.exit(2);
  }

  const body = new URLSearchParams({
    ...params,
    device_id: deviceId(),
    device_name: 'seo-agent',
  });

  return api(`${OAUTH}/token`, {
    method: 'POST',
    service: 'Яндекс OAuth',
    retries: 1,
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      Authorization: 'Basic ' + Buffer.from(`${id}:${secret}`).toString('base64'),
    },
    json: body.toString(),
  });
}

/** Сохранить полученную пару и подписать срок. */
function store(res) {
  const expires = new Date(Date.now() + (res.expires_in ?? 0) * 1000);

  setEnv({
    YANDEX_OAUTH_TOKEN: res.access_token,
    YANDEX_OAUTH_REFRESH: res.refresh_token ?? get('YANDEX_OAUTH_REFRESH'),
    YANDEX_OAUTH_EXPIRES: expires.toISOString().slice(0, 10),
  });

  return expires;
}

run(async () => {
  const a = args();

  /* ── ссылка для браузера ───────────────────────────────────────────── */
  if (a.cmd === 'url') {
    const url =
      `${OAUTH}/authorize?response_type=code&client_id=${clientId()}` +
      `&scope=${encodeURIComponent(SCOPES.join(' '))}&force_confirm=yes`;

    title('Откройте это в браузере');
    console.log('\n  ' + url + '\n');
    note('  Важно: в браузере должен быть залогинен тот аккаунт Яндекса,');
    note('  на котором стоит счётчик Метрики и подтверждены права в Вебмастере.');
    note('  Токен получит тот, кто залогинен, а не владелец приложения —');
    note('  это самая частая причина «токен выдали, а доступа нет».');
    console.log('');
    note('  После кнопки «Разрешить» Яндекс покажет 7-значный код.');
    note('  Код живёт 10 минут. Дальше:');
    console.log('\n    node seo/cli/yandex-token.mjs exchange <код>\n');
    return;
  }

  /* ── обмен кода на токен ───────────────────────────────────────────── */
  if (a.cmd === 'exchange') {
    const code = (a._[0] ?? a.code ?? '').trim();

    /* Формат кода Яндекс не фиксирует - встречаются и цифры, и латинские
       буквы. Проверяем только на явные промахи: пробелы и вставленную
       целиком ссылку. */
    if (!/^[A-Za-z0-9_-]{4,100}$/.test(code)) {
      fail('Не похоже на код подтверждения.');
      note('  Нужен только сам код — без пробелов и без адреса страницы.');
      note('  Если скопировали всю ссылку, возьмите из неё часть после code=');
      note('  Ссылку для получения кода даёт: node seo/cli/yandex-token.mjs url');
      process.exit(2);
    }

    /* Готовый токен вместо кода - частый случай, если открылась ссылка
       вида response_type=token. Менять его не нужно, он уже рабочий. */
    if (/^y0_/.test(code) && code.length > 40) {
      setEnv({ YANDEX_OAUTH_TOKEN: code });
      ok('Это уже готовый доступ, а не код — записал его сразу.');
      warn('Обновлять такой доступ придётся вручную примерно раз в полгода.');
      note('  Чтобы обновление шло само, пройдите заново: node seo/cli/yandex-token.mjs url');
      return;
    }

    const res = await tokenRequest({ grant_type: 'authorization_code', code });
    const expires = store(res);

    title('Токен получен');
    console.log('');
    ok(`Записан в ${ENV_PATH}`);
    ok(`Права: ${res.scope ?? SCOPES.join(' ')}`);
    ok(`Действует примерно до ${expires.toISOString().slice(0, 10)}`);
    if (res.refresh_token) ok('Refresh-токен получен — дальше продление идёт без вас.');
    else warn('Refresh-токена нет. Проверьте, что использовали схему с кодом, а не implicit.');

    console.log('');
    note('  Проверить, что всё работает:  node seo/cli/doctor.mjs');
    return;
  }

  /* ── продление ─────────────────────────────────────────────────────── */
  if (a.cmd === 'refresh') {
    const refresh = get('YANDEX_OAUTH_REFRESH');
    if (!refresh) {
      fail('Refresh-токена нет — продлевать нечем.');
      note('  Пройдите заново: node seo/cli/yandex-token.mjs url');
      process.exit(2);
    }

    const res = await tokenRequest({ grant_type: 'refresh_token', refresh_token: refresh });
    const expires = store(res);

    ok(`Токен продлён до ${expires.toISOString().slice(0, 10)}`);
    note('  Новый refresh-токен тоже сохранён — старый больше не работает.');
    note('  Яндекс советует продлевать раз в три месяца; раз в месяц — с запасом.');
    return;
  }

  /* ── проверка ──────────────────────────────────────────────────────── */
  if (a.cmd === 'check') {
    const token = yandexToken();
    const rows = [];

    /* Проверяем каждый сервис отдельно: право может быть выдано
       на один и не выдано на другой, и это надо видеть раздельно. */
    try {
      const c = await api('https://api-metrika.yandex.net/management/v1/counters', {
        service: 'Метрика',
        headers: { Authorization: `OAuth ${token}` },
        retries: 1,
      });
      rows.push({
        s: 'Яндекс.Метрика',
        r: `доступно счётчиков: ${c?.counters?.length ?? 0}`,
      });
    } catch (e) {
      rows.push({ s: 'Яндекс.Метрика', r: `нет доступа — ${e.message.slice(0, 50)}` });
    }

    try {
      const u = await api('https://api.webmaster.yandex.net/v4/user/', {
        service: 'Вебмастер',
        headers: { Authorization: `OAuth ${token}` },
        retries: 1,
      });
      rows.push({ s: 'Яндекс.Вебмастер', r: `user_id: ${u?.user_id}` });
    } catch (e) {
      rows.push({ s: 'Яндекс.Вебмастер', r: `нет доступа — ${e.message.slice(0, 50)}` });
    }

    title('Что открыто этим токеном');
    table(rows, [
      { key: 's', title: 'Сервис', max: 24 },
      { key: 'r', title: 'Результат', max: 60 },
    ]);

    const expires = get('YANDEX_OAUTH_EXPIRES');
    if (expires) {
      const days = Math.round((new Date(expires) - Date.now()) / 86_400_000);
      if (days < 30) warn(`Токен истекает через ${days} дн. Продлите: node seo/cli/yandex-token.mjs refresh`);
      else note(`\n  Срок действия: ещё около ${days} дн. (до ${expires})`);
    }

    if (has('YANDEX_OAUTH_REFRESH')) {
      note('  Refresh-токен на месте — продление возможно без вашего участия.');
    } else {
      warn('Refresh-токена нет: когда токен истечёт, придётся получать заново руками.');
    }
    return;
  }

  /* ── отзыв ─────────────────────────────────────────────────────────── */
  if (a.cmd === 'revoke') {
    if (!a.force) {
      warn('Это отключит агента от Метрики и Вебмастера немедленно.');
      note('  Если уверены: node seo/cli/yandex-token.mjs revoke --force');
      return;
    }

    const id = clientId();
    const secret = get('YANDEX_CLIENT_SECRET');

    await api(`${OAUTH}/revoke_token`, {
      method: 'POST',
      service: 'Яндекс OAuth',
      retries: 0,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        Authorization: 'Basic ' + Buffer.from(`${id}:${secret}`).toString('base64'),
      },
      json: new URLSearchParams({ access_token: yandexToken() }).toString(),
    });

    setEnv({ YANDEX_OAUTH_TOKEN: '', YANDEX_OAUTH_REFRESH: '', YANDEX_OAUTH_EXPIRES: '' });
    ok('Токен отозван и стёрт из seo/.env');
    return;
  }

  /* ── инструкция по умолчанию ───────────────────────────────────────── */
  title('Токен Яндекса — четыре шага, делаются один раз');
  console.log(`
  1. Создать приложение: https://oauth.yandex.ru/client/new/
     Тип — «Для доступа к API или отладки» (поменять его потом нельзя).
     Права: ${SCOPES.join(', ')}
     Скопировать ClientID и Client secret.

  2. Вписать их в seo/.env:
       YANDEX_CLIENT_ID=…
       YANDEX_CLIENT_SECRET=…

  3. Получить ссылку и открыть её в браузере:
       node seo/cli/yandex-token.mjs url

  4. Обменять показанный 7-значный код на токен:
       node seo/cli/yandex-token.mjs exchange <код>

  Дальше всё само: node seo/cli/yandex-token.mjs refresh продлевает токен
  без вашего участия, эту команду можно поставить в расписание.

  Подробная инструкция с картой интерфейса — seo/SETUP.md, раздел 1.
`);

  if (has('YANDEX_OAUTH_TOKEN')) {
    ok('Токен уже есть. Проверить: node seo/cli/yandex-token.mjs check');
  }
});
