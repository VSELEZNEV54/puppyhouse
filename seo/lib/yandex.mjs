/**
 * Общий слой для сервисов Яндекса: Метрика, Вебмастер, Директ.
 *
 * У всех трех один OAuth-токен (одно приложение может нести права сразу
 * на все три сервиса), но заголовок авторизации у них исторически разный:
 * Метрика и Вебмастер ждут "OAuth <токен>", Директ - "Bearer <токен>".
 * Из-за этого их и разводят по трем функциям, а не по одной.
 *
 * Токен получают один раз руками: node seo/cli/yandex-token.mjs
 * Он живет год, дата истечения пишется рядом в seo/.env, и doctor.mjs
 * предупредит за месяц.
 */

import { need, get } from './env.mjs';
import { api } from './http.mjs';

const TOKEN_HINT =
  'Получить: node seo/cli/yandex-token.mjs — команда проведет по шагам. ' +
  'Вручную: seo/SETUP.md, раздел 1';

export function yandexToken() {
  return need('YANDEX_OAUTH_TOKEN', TOKEN_HINT);
}

/** Метрика и Вебмастер: заголовок "OAuth <токен>". */
export async function yandexApi(url, opts = {}) {
  return api(url, {
    ...opts,
    headers: { Authorization: `OAuth ${yandexToken()}`, ...(opts.headers || {}) },
  });
}

/**
 * Директ: заголовок "Bearer <токен>" плюс язык ответа.
 *
 * И токен у него СВОЙ. Директ живёт отдельным приложением намеренно:
 * дописать direct:api в рабочее приложение нельзя - изменение прав
 * отзывает все выданные им токены, и агент разом теряет Метрику
 * с Вебмастером. Значит и переменная окружения здесь другая.
 */
export function directToken() {
  return need(
    'YANDEX_DIRECT_TOKEN',
    'Отдельное приложение с правом direct:api и одобренная заявка. ' +
      'См. seo/SETUP.md, раздел 6',
  );
}

export async function directApi(url, opts = {}) {
  return api(url, {
    ...opts,
    service: opts.service || 'Яндекс.Директ',
    headers: {
      Authorization: `Bearer ${directToken()}`,
      'Accept-Language': 'ru',
      ...(opts.headers || {}),
    },
  });
}

/** Логин в Директе (нужен агентствам; для своего аккаунта не обязателен). */
export function directLogin() {
  return get('YANDEX_DIRECT_LOGIN');
}

/**
 * Дата истечения токена в seo/.env - чисто для напоминания.
 * Само API про срок не сообщает, пока токен не перестанет работать.
 */
export function tokenExpiresAt() {
  const v = get('YANDEX_OAUTH_EXPIRES');
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}
