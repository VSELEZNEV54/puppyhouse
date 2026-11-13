/**
 * Секреты для SEO-инструментов.
 *
 * Все токены живут в одном файле seo/.env, который закрыт в .gitignore.
 * В репозиторий не уезжает ни один ключ - в git только seo/.env.example
 * с описанием, что куда вписать.
 *
 * Почему свой парсер, а не process.loadEnvFile(): инструменты должны
 * запускаться и локально на Mac (Node 24), и по cron на сервере, где
 * версия Node может быть старее. Двадцать строк надежнее, чем требование
 * к версии рантайма.
 *
 * Главный принцип файла: если ключа нет - не падать со стектрейсом,
 * а сказать человеческим языком, какой переменной не хватает и в каком
 * пункте seo/SETUP.md ее берут. Инструментом пользуется владелец сайта,
 * а не разработчик.
 */

import { readFileSync, writeFileSync, existsSync, renameSync, chmodSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const SEO_DIR = resolve(HERE, '..');
export const ROOT_DIR = resolve(SEO_DIR, '..');
const ENV_PATH = resolve(SEO_DIR, '.env');

/**
 * Общие ключи на все проекты.
 *
 * Токен Яндекса и ключ Google выданы АККАУНТУ, а не сайту: один и тот же
 * токен видит все счётчики Метрики и все сайты в Вебмастере, а сервисный
 * аккаунт Google - все ресурсы в Search Console. Держать их копии в каждом
 * проекте - значит при продлении токена вспоминать, где ещё лежит копия,
 * и однажды забыть. Поэтому ключи живут в одном месте на компьютере,
 * а в проекте остаётся только то, что у проектов действительно разное.
 *
 * Локальный seo/.env при этом продолжает работать и имеет приоритет:
 * так проект может переопределить что-то у себя, и так ничего не ломается
 * у того, кто общий файл ещё не заводил.
 */
export const SHARED_ENV_PATH = resolve(homedir(), '.seo-tools', '.env');

/** Разбор .env: KEY=value, кавычки снимаются, строки с # игнорируются. */
function parseEnv(text) {
  const out = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim();
    let val = line.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    if (key) out[key] = val;
  }
  return out;
}

/* Порядок приоритета, от низшего к высшему:
     общий файл ~/.seo-tools/.env  ->  локальный seo/.env  ->  окружение.
   Окружение сверху, чтобы можно было подменить значение на один запуск:
     YANDEX_OAUTH_TOKEN=... node seo/cli/webmaster.mjs queries */
const fromShared = existsSync(SHARED_ENV_PATH)
  ? parseEnv(readFileSync(SHARED_ENV_PATH, 'utf8'))
  : {};
const fromLocal = existsSync(ENV_PATH) ? parseEnv(readFileSync(ENV_PATH, 'utf8')) : {};
const fromFile = { ...fromShared, ...fromLocal };

export const envFileExists = existsSync(ENV_PATH) || existsSync(SHARED_ENV_PATH);
export const sharedEnvExists = existsSync(SHARED_ENV_PATH);

/* ─────────────────────────  Настройки проекта  ──────────────────────────── */

/**
 * seo/project.json - то, чем проекты отличаются друг от друга: домен,
 * номер счётчика, адрес ресурса в Search Console, где лежит собранный сайт.
 * Файл не секретный и лежит в git: он описывает проект, а не доступы.
 */
const PROJECT_PATH = resolve(SEO_DIR, 'project.json');

function readProject() {
  if (!existsSync(PROJECT_PATH)) return {};
  try {
    return JSON.parse(readFileSync(PROJECT_PATH, 'utf8'));
  } catch (e) {
    throw new Error(`seo/project.json не разбирается: ${e.message}`);
  }
}

export const PROJECT = readProject();
export const PROJECT_PATH_ABS = PROJECT_PATH;

/* Что берётся из project.json вместо переменной окружения. */
const FROM_PROJECT = {
  SEO_SITE_HOST: 'host',
  YANDEX_METRIKA_COUNTER: 'metrikaCounter',
  GSC_SITE_URL: 'gscSiteUrl',
  YANDEX_WEBMASTER_HOST_ID: 'webmasterHostId',
  INDEXNOW_KEY: 'indexnowKey',
};

/** Значение переменной или пустая строка. */
export function get(name, fallback = '') {
  const fromProcess = process.env[name];
  if (typeof fromProcess === 'string' && fromProcess.trim() !== '') return fromProcess.trim();

  /* Локальный .env сильнее project.json: даёт возможность переопределить
     настройку проекта, не трогая файл, который лежит в git. */
  const local = fromLocal[name];
  if (typeof local === 'string' && local.trim() !== '') return local.trim();

  const key = FROM_PROJECT[name];
  if (key && PROJECT[key]) return String(PROJECT[key]).trim();

  const v = fromFile[name];
  return typeof v === 'string' && v.trim() !== '' ? v.trim() : fallback;
}

/** Есть ли переменная. Нужен doctor.mjs, чтобы показать карту доступов. */
export function has(name) {
  return get(name) !== '';
}

/**
 * Обязательная переменная. Нет - понятная остановка с указанием,
 * где взять значение.
 */
export function need(name, where) {
  const v = get(name);
  if (v) return v;

  const lines = [
    '',
    `  Не задана переменная ${name}`,
    '',
    `  Где взять: ${where}`,
    '',
    envFileExists
      ? `  Куда вписать: ${ENV_PATH}`
      : `  Файла seo/.env еще нет. Создайте его:\n      cp seo/.env.example seo/.env`,
    '',
    '  Полная инструкция по всем доступам: seo/SETUP.md',
    '',
  ];
  process.stderr.write(lines.join('\n') + '\n');
  process.exit(2);
}

/** Домен сайта без схемы и без слеша на конце. Для доменов на кириллице
    здесь всегда punycode: именно его ждут и API, и заголовки запросов. */
export const SITE_HOST = get('SEO_SITE_HOST', 'example.ru');

/** Как домен показывать человеку. Для латиницы совпадает с SITE_HOST. */
export const SITE_LABEL = PROJECT.displayHost || SITE_HOST;

/** Название проекта - чтобы в отчётах было видно, о каком сайте речь. */
export const PROJECT_NAME = PROJECT.name || SITE_LABEL;

/** Полный адрес сайта - в таком виде его ждут Search Console и IndexNow. */
export const SITE_URL = `https://${SITE_HOST}`;

/** Где лежит собранный сайт: у Астро это dist, у статики может быть иначе. */
export const BUILD_DIR = resolve(ROOT_DIR, PROJECT.buildDir || 'dist');

/** Куда класть файлы, которые должны попасть на сайт как есть. */
export const PUBLIC_DIR = resolve(ROOT_DIR, PROJECT.publicDir || 'public');

/** Адрес карты сайта относительно домена. */
export const SITEMAP_PATH = PROJECT.sitemap || '/sitemap-index.xml';

/**
 * Записать значение в seo/.env, сохранив остальные строки и комментарии.
 *
 * Нужно помощнику получения токена: он сам кладёт полученный токен
 * в файл, чтобы владельцу не пришлось копировать длинные строки руками
 * и заодно не пришлось показывать токен в переписке.
 */
export function setEnv(updates) {
  const lines = existsSync(ENV_PATH) ? readFileSync(ENV_PATH, 'utf8').split('\n') : [];
  const done = new Set();

  const next = lines.map((line) => {
    const m = /^\s*([A-Z0-9_]+)\s*=/.exec(line);
    if (!m || !(m[1] in updates)) return line;
    done.add(m[1]);
    return `${m[1]}=${updates[m[1]]}`;
  });

  for (const [k, v] of Object.entries(updates)) {
    if (!done.has(k)) next.push(`${k}=${v}`);
  }

  const body = next.join('\n').replace(/\n{3,}/g, '\n\n');

  /* Пишем через временный файл и переименование. Прямая перезапись сначала
     обнуляет файл: падение между усечением и записью оставило бы пустой
     seo/.env - а это единственное место, где лежат все токены. Refresh-токен
     Яндекса при этом теряется безвозвратно, и получать доступ пришлось бы
     заново руками. Переименование в пределах одной папки атомарно. */
  const tmp = ENV_PATH + '.tmp';
  writeFileSync(tmp, body, { encoding: 'utf8', mode: 0o600 });
  renameSync(tmp, ENV_PATH);

  /* mode в writeFileSync действует только при создании файла. Файл обычно
     уже существует - скопирован из .env.example и получил права 644,
     то есть читается любым пользователем машины. Выставляем явно. */
  chmodSync(ENV_PATH, 0o600);

  return ENV_PATH;
}

export { ENV_PATH };
