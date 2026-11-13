/**
 * Авторизация в Google API через сервисный аккаунт.
 *
 * Почему сервисный аккаунт, а не обычный OAuth. Обычный OAuth требует
 * живого человека у браузера: раз в какое-то время токен протухает и надо
 * заново нажимать "разрешить". Автономный агент так работать не может.
 * Сервисный аккаунт - это отдельная "машинная учетка": один раз скачали
 * JSON-ключ, один раз добавили ее почту в Search Console - и дальше
 * доступ работает сам, пока ключ не отозвали.
 *
 * Как это устроено внутри. Библиотек не ставим: весь протокол - это
 * подписать JWT ключом из файла и обменять его на access-token. Node это
 * умеет из коробки (node:crypto), пакет googleapis тянет 20+ зависимостей
 * ради того же самого.
 *
 * Токен живет час; держим его в памяти процесса и переполучаем,
 * когда до истечения осталось меньше минуты.
 */

import { createSign } from 'node:crypto';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, isAbsolute } from 'node:path';
import { homedir } from 'node:os';
import { get, need, SEO_DIR } from './env.mjs';
import { api } from './http.mjs';

const TOKEN_URL = 'https://oauth2.googleapis.com/token';

/** base64url без паддинга - того требует формат JWT. */
const b64url = (buf) =>
  Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

let keyCache = null;

/** Прочитать JSON-ключ сервисного аккаунта. */
export function serviceAccountKey() {
  if (keyCache) return keyCache;

  /* Ключ ищем в двух местах. Сначала общее для всех проектов - сервисный
     аккаунт выдан аккаунту Google и видит все ресурсы Search Console сразу,
     так что копия в каждом проекте только плодит рассинхрон. Потомлокальное
     seo/keys/ - на случай, если проекту нужен именно свой ключ. */
  const SHARED_KEY = resolve(homedir(), '.seo-tools', 'google-service-account.json');
  const LOCAL_KEY = resolve(SEO_DIR, 'keys', 'google-service-account.json');

  let raw = get('GOOGLE_SERVICE_ACCOUNT_KEY');
  if (!raw && existsSync(LOCAL_KEY)) raw = LOCAL_KEY;
  if (!raw && existsSync(SHARED_KEY)) raw = SHARED_KEY;

  if (!raw) {
    raw = need(
      'GOOGLE_SERVICE_ACCOUNT_KEY',
      'Google Cloud Console → Сервисные аккаунты → Ключи → скачать JSON, ' +
        'файл положить в seo/keys/google-service-account.json (см. seo/SETUP.md, раздел 2)',
    );
  }

  /* Допускаем два формата: путь к файлу и сам JSON строкой.
     Путь удобнее локально, строка - когда ключ передают через
     переменную окружения на сервере. */
  let text = raw;
  if (!raw.trim().startsWith('{')) {
    const path = isAbsolute(raw) ? raw : resolve(SEO_DIR, raw);
    if (!existsSync(path)) {
      throw new Error(
        `Файл ключа Google не найден: ${path}\n` +
          '  Проверьте GOOGLE_SERVICE_ACCOUNT_KEY в seo/.env — там должен быть путь к скачанному JSON.',
      );
    }
    text = readFileSync(path, 'utf8');
  }

  let key;
  try {
    key = JSON.parse(text);
  } catch {
    throw new Error('Ключ Google не разбирается как JSON. Скачайте файл заново.');
  }

  if (!key.client_email || !key.private_key) {
    throw new Error(
      'В ключе Google нет client_email или private_key. ' +
        'Похоже, скачан не тот файл: нужен ключ сервисного аккаунта, а не OAuth-клиента.',
    );
  }

  keyCache = key;
  return key;
}

/** Почта сервисного аккаунта - ее добавляют в доступы Search Console. */
export function serviceAccountEmail() {
  return serviceAccountKey().client_email;
}

const tokens = new Map(); // scope -> { token, expires }

/**
 * Access-token для набора прав.
 * @param {string|string[]} scope
 */
export async function googleToken(scope) {
  const scopes = Array.isArray(scope) ? scope.join(' ') : scope;
  const cached = tokens.get(scopes);
  if (cached && cached.expires > Date.now() + 60_000) return cached.token;

  const key = serviceAccountKey();
  const now = Math.floor(Date.now() / 1000);

  const header = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const claims = b64url(
    JSON.stringify({
      iss: key.client_email,
      scope: scopes,
      aud: key.token_uri || TOKEN_URL,
      exp: now + 3600,
      iat: now,
    }),
  );

  const signer = createSign('RSA-SHA256');
  signer.update(`${header}.${claims}`);
  const signature = b64url(signer.sign(key.private_key.replace(/\\n/g, '\n')));
  const assertion = `${header}.${claims}.${signature}`;

  const res = await api(key.token_uri || TOKEN_URL, {
    method: 'POST',
    service: 'Google OAuth',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    json: new URLSearchParams({
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer',
      assertion,
    }).toString(),
  });

  if (!res?.access_token) {
    throw new Error('Google не выдал access-token. Проверьте, что ключ не отозван.');
  }

  tokens.set(scopes, {
    token: res.access_token,
    expires: Date.now() + (res.expires_in ?? 3600) * 1000,
  });

  return res.access_token;
}

/** Запрос к Google API с уже подставленным токеном. */
export async function google(url, { scope, ...opts } = {}) {
  const token = await googleToken(scope);
  return api(url, {
    ...opts,
    service: opts.service || 'Google API',
    headers: { Authorization: `Bearer ${token}`, ...(opts.headers || {}) },
  });
}

/** Ключ для простых API, которым хватает ?key= (PageSpeed, CrUX). */
export function googleApiKey() {
  return get('GOOGLE_API_KEY');
}
