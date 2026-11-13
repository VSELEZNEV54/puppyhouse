/**
 * Запросы к внешним API.
 *
 * Одна функция на весь инструментарий: таймаут, повтор при временных
 * сбоях, и - главное - расшифровка ошибок. У Яндекса и Google разные
 * форматы тела ошибки, и без разбора в консоль прилетает сырой JSON,
 * по которому непонятно, что делать. Здесь ошибка превращается
 * в предложение на русском: истек токен, нет прав, кончилась квота.
 *
 * Повторяем только то, что имеет смысл повторять: сетевые обрывы,
 * 429 (слишком часто) и 5xx. Ошибку прав повторять бессмысленно -
 * она не рассосется.
 */

const RETRY_STATUS = new Set([429, 500, 502, 503, 504]);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class ApiError extends Error {
  constructor(message, { status, service, body, hint } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.service = service;
    this.body = body;
    this.hint = hint;
  }
}

/**
 * Достать человеческое описание ошибки из тела ответа.
 * Форматы разные, поэтому перебираем известные поля по очереди.
 */
function explain(status, body, service) {
  let parsed = body;
  if (typeof body === 'string') {
    try {
      parsed = JSON.parse(body);
    } catch {
      /* тело не JSON - оставляем строкой */
    }
  }

  const message =
    parsed?.error?.message ||           // Google
    parsed?.message ||                  // Вебмастер, Метрика
    parsed?.error_message ||            // Метрика (старый формат)
    parsed?.error?.error_string ||      // Директ
    parsed?.error_description ||        // OAuth
    (typeof parsed === 'string' ? parsed.slice(0, 400) : '');

  const code =
    parsed?.error_type ||
    parsed?.error?.status ||
    parsed?.error_code ||
    parsed?.error?.error_code ||
    '';

  /* Подсказки: что делать владельцу сайта, а не что не так с запросом. */
  let hint = '';
  if (status === 401) {
    hint =
      'Токен недействителен или истек. Получите заново: node seo/cli/yandex-token.mjs ' +
      '(для Яндекса) или проверьте JSON-ключ сервисного аккаунта Google. См. seo/SETUP.md';
  } else if (status === 403) {
    hint =
      'Доступ запрещен. Обычно это одно из трех: у токена нет нужного права (scope), ' +
      'аккаунт не добавлен в ресурс, или не включен нужный API в Google Cloud. См. seo/SETUP.md';
  } else if (status === 429) {
    hint = 'Кончилась квота запросов. Подождите и повторите позже.';
  } else if (status === 404) {
    hint = 'Ресурс не найден. Проверьте идентификатор сайта или счетчика.';
  }

  return {
    text: [service, status, code, message].filter(Boolean).join(' · ') || `HTTP ${status}`,
    hint,
    parsed,
  };
}

/**
 * GET/POST к API с разбором JSON.
 *
 * @param {string} url
 * @param {object} opts
 * @param {string} [opts.method]  - GET по умолчанию
 * @param {object} [opts.headers]
 * @param {any}    [opts.json]    - тело запроса, будет сериализовано
 * @param {string} [opts.service] - имя сервиса для сообщений об ошибке
 * @param {number} [opts.timeout] - мс, по умолчанию 30000
 * @param {number} [opts.retries] - сколько раз повторить, по умолчанию 3
 * @param {boolean}[opts.raw]     - вернуть текст, а не разобранный JSON
 * @param {boolean}[opts.withResponse] - вернуть {status, headers, text},
 *        а не тело. Нужно там, где важен сам код ответа: отчёты Директа
 *        готовятся асинхронно и отвечают 201/202 с пустым телом, и отличить
 *        «ещё готовится» от «данных нет» можно только по статусу.
 */
export async function api(url, opts = {}) {
  const {
    method = 'GET',
    headers = {},
    json,
    service = 'API',
    timeout = 30_000,
    retries = 3,
    raw = false,
    withResponse = false,
  } = opts;

  const init = {
    method,
    headers: {
      Accept: 'application/json',
      'User-Agent': 'seo-tools/1.0',
      ...headers,
    },
  };

  if (json !== undefined) {
    init.body = typeof json === 'string' ? json : JSON.stringify(json);

    /* Content-Type ставим только если вызывающий не задал свой. Оба OAuth -
       и Яндекса, и Google - принимают ТОЛЬКО x-www-form-urlencoded; если
       перебить их заголовок на JSON, тело не разберётся и токен не выдадут.
       Сломано было бы разом всё: и Метрика с Вебмастером, и Search Console. */
    const hasContentType = Object.keys(init.headers).some(
      (h) => h.toLowerCase() === 'content-type',
    );
    if (!hasContentType) init.headers['Content-Type'] = 'application/json; charset=utf-8';
  }

  let lastError;

  for (let attempt = 0; attempt <= retries; attempt++) {
    if (attempt > 0) {
      /* Растущая пауза: 1с, 3с, 9с. Квоты Яндекса и Google
         восстанавливаются в пределах минуты. */
      await sleep(1000 * 3 ** (attempt - 1));
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);

    try {
      const res = await fetch(url, { ...init, signal: ctrl.signal });

      /* Таймер снимаем ПОСЛЕ чтения тела, а не сразу по заголовкам:
         сервер вполне может отдать 200 и подвиснуть на теле. Со снятым
         таймером такой запрос висел бы вечно - а прогон Lighthouse
         в PageSpeed ждёт до двух минут, там это особенно вероятно. */
      const text = await res.text();
      clearTimeout(timer);

      if (!res.ok) {
        const { text: msg, hint, parsed } = explain(res.status, text, service);
        const err = new ApiError(msg, { status: res.status, service, body: parsed, hint });
        if (RETRY_STATUS.has(res.status) && attempt < retries) {
          lastError = err;
          continue;
        }
        throw err;
      }

      if (withResponse) return { status: res.status, headers: res.headers, text };
      if (raw) return text;
      if (!text) return null;

      try {
        return JSON.parse(text);
      } catch {
        /* Пришёл 200, но тело не JSON: заглушка балансировщика, страница
           капчи, редирект. Вернуть это строкой - значит выдать отказ сервиса
           за успех: дальше по коду везде стоит `?? 0`, и отчёт покажет
           не ошибку, а честный на вид ноль. Лучше громко упасть. */
        throw new ApiError(
          `${service}: ответ не разбирается как JSON (HTTP ${res.status})`,
          {
            status: res.status,
            service,
            body: text.slice(0, 300),
            hint:
              'Обычно так отвечает не сам сервис, а что-то перед ним: ' +
              'прокси, капча или страница блокировки. Проверьте доступность вручную.',
          },
        );
      }
    } catch (e) {
      clearTimeout(timer);
      if (e instanceof ApiError) throw e;

      /* Сеть отвалилась или таймаут - имеет смысл повторить. */
      lastError = new ApiError(
        e.name === 'AbortError'
          ? `${service}: превышено время ожидания (${timeout / 1000} с)`
          : `${service}: сеть недоступна — ${e.message}`,
        { service },
      );
      if (attempt < retries) continue;
      throw lastError;
    }
  }

  throw lastError;
}

/** Собрать query-строку, пропуская пустые значения. Массивы через запятую. */
export function qs(params) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    sp.append(k, Array.isArray(v) ? v.join(',') : String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}
