#!/usr/bin/env node
/**
 * Яндекс.Директ - только то, что полезно для SEO.
 *
 *   node seo/cli/direct.mjs check                  жив ли доступ
 *   node seo/cli/direct.mjs has-volume фраза…      ищут ли такие запросы вообще
 *   node seo/cli/direct.mjs has-volume --file f.txt  список фраз из файла
 *   node seo/cli/direct.mjs dedupe фраза…          схлопнуть дубли фраз
 *   node seo/cli/direct.mjs queries                реальные запросы людей (нужна реклама)
 *
 * Честно о том, зачем этот файл вообще нужен, и о чём в нём НЕТ.
 *
 * Частотности запросов («сколько раз в месяц ищут») через API Директа v5
 * получить НЕЛЬЗЯ - такого метода в пятой версии не существует. Числа
 * Вордстата живут либо в устаревших методах Live 4, либо в платном
 * Wordstat API в Yandex Cloud. Все статьи, обещающие бесплатную выгрузку
 * частотности, описывают либо парсеры (нарушают правила Яндекса), либо
 * платные сервисы.
 *
 * Что здесь всё-таки есть и ради чего стоит держать доступ:
 *
 *   has-volume - проверка до 10 000 фраз одним запросом: есть у фразы
 *   показы или нет, и на каких устройствах. Числа не даёт, но отвечает
 *   на главный вопрос при написании статьи - «эту формулировку вообще
 *   кто-нибудь ищет?». Стоит один балл и работает без рекламного бюджета.
 *
 *   queries - реальные поисковые фразы, которые люди набирали перед
 *   показом объявления. Это не оценка, а факт, и лучший источник живых
 *   формулировок для заголовков. Но работает только там, где реклама
 *   действительно крутилась: без открутки отчёт будет пустым.
 *
 * Доступ требует созданной кампании в Директе и одобренной заявки
 * (до семи дней). Если платной рекламы нет - этот файл можно не трогать.
 */

import { readFileSync } from 'node:fs';
import { directApi, directLogin } from '../lib/yandex.mjs';
import { get } from '../lib/env.mjs';
import { args, num, table, title, note, run, ok, warn, fail } from '../lib/out.mjs';

const API = 'https://api.direct.yandex.com/json/v5';

/**
 * Вызов Директа.
 *
 * Отдельная функция, потому что Директ ведёт себя не как остальные:
 * при ошибке авторизации он отвечает HTTP 200 и кладёт беду в тело.
 * Код, который смотрит только на статус ответа, посчитает провал успехом.
 */
async function direct(service, method, params = {}) {
  const headers = {};
  const login = directLogin();
  if (login) headers['Client-Login'] = login;

  const res = await directApi(`${API}/${service}`, {
    method: 'POST',
    headers,
    json: { method, params },
  });

  if (res?.error) {
    const e = res.error;
    throw Object.assign(
      new Error(`Директ: ${e.error_string ?? 'ошибка'} — ${e.error_detail ?? ''} (код ${e.error_code})`),
      {
        hint:
          e.error_code === 53 || e.error_code === 8000
            ? 'Токен недействителен или заявка на доступ к API ещё не одобрена. См. seo/SETUP.md, раздел 6.'
            : e.error_code === 152
              ? 'Кончились баллы (units) на сутки. Лимит зависит от рекламной активности аккаунта.'
              : '',
      },
    );
  }

  return res?.result ?? res;
}

/** Фразы из аргументов или из файла — списком по строке на фразу. */
function phrases(a) {
  if (a.file) {
    return readFileSync(a.file, 'utf8')
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return a._.filter(Boolean);
}

run(async () => {
  const a = args();
  const out = (o) => console.log(JSON.stringify(o, null, 2));

  if (a.cmd === 'check') {
    const res = await direct('campaigns', 'get', {
      SelectionCriteria: {},
      FieldNames: ['Id', 'Name', 'Status', 'State'],
    });
    const list = res?.Campaigns ?? [];

    title('Доступ к API Директа');
    ok(`Работает. Кампаний в аккаунте: ${list.length}`);

    if (list.length) {
      table(
        list.slice(0, 20).map((c) => ({ id: c.Id, n: c.Name, s: c.Status, st: c.State })),
        [
          { key: 'id', title: 'ID', align: 'right' },
          { key: 'n', title: 'Кампания', max: 40 },
          { key: 's', title: 'Статус' },
          { key: 'st', title: 'Состояние' },
        ],
      );
    } else {
      note('  Кампаний нет — отчёт по реальным запросам будет пустым.');
      note('  Полезным останется только has-volume.');
    }
    return;
  }

  /* ── есть ли у фразы показы вообще ─────────────────────────────────── */
  if (a.cmd === 'has-volume') {
    const list = phrases(a);
    if (!list.length) {
      fail('Укажите фразы или файл со списком.');
      note('  node seo/cli/direct.mjs has-volume "дизайн сайта новосибирск" "заказать лендинг"');
      note('  node seo/cli/direct.mjs has-volume --file семантика.txt');
      process.exit(2);
    }

    /* За один вызов допускается до 10 000 фраз, и стоит он один балл.
       Дробим на всякий случай, чтобы не упереться в размер тела. */
    const CHUNK = 1000;
    const results = [];

    for (let i = 0; i < list.length; i += CHUNK) {
      const chunk = list.slice(i, i + CHUNK);
      /* Имена полей здесь свои: AllDevices, Desktops, MobilePhones, Tablets.
         Придуманные «HasSearchVolume» API отвергает как недопустимое
         значение перечисления. */
      const res = await direct('keywordsresearch', 'hasSearchVolume', {
        SelectionCriteria: { Keywords: chunk, RegionIds: [num(a.region, 225)] },
        FieldNames: ['Keyword', 'AllDevices', 'Desktops', 'MobilePhones', 'Tablets'],
      });
      results.push(...(res?.HasSearchVolumeResults ?? []));
    }

    if (a.json) return out(results);

    const alive = results.filter((r) => r.AllDevices === 'YES');
    const dead = results.filter((r) => r.AllDevices !== 'YES');

    title(`Проверено фраз: ${results.length} · регион ${num(a.region, 225)} (225 — Россия)`);

    if (alive.length) {
      title(`Ищут — ${alive.length}`);
      table(
        alive.map((r) => ({
          k: r.Keyword,
          d: r.Desktops === 'YES' ? 'да' : '—',
          m: r.MobilePhones === 'YES' ? 'да' : '—',
          t: r.Tablets === 'YES' ? 'да' : '—',
        })),
        [
          { key: 'k', title: 'Фраза', max: 55 },
          { key: 'd', title: 'Десктоп' },
          { key: 'm', title: 'Мобильные' },
          { key: 't', title: 'Планшеты' },
        ],
      );
    }

    if (dead.length) {
      title(`Не ищут — ${dead.length}`);
      for (const r of dead) note('  · ' + r.Keyword);
      note('\n  Эти формулировки в заголовки брать не стоит: спроса на них нет.');
    }

    if (alive.length && !dead.length) ok('Все проверенные фразы живые.');
    return;
  }

  /* ── дедупликация ядра ─────────────────────────────────────────────── */
  if (a.cmd === 'dedupe') {
    const list = phrases(a);
    if (!list.length) {
      fail('Укажите фразы или --file со списком.');
      process.exit(2);
    }

    /* У этого метода нет ни SelectionCriteria, ни FieldNames: параметры -
       это массив объектов Keywords. Операцию не задаём: без неё выполняются
       обе - схлопывание дублей и устранение пересечений. */
    const res = await direct('keywordsresearch', 'deduplicate', {
      Keywords: list.map((k, i) => ({ Id: i + 1, Keyword: k })),
    });

    if (a.json) return out(res);

    /* Ответ разложен по действиям, а не по фразам: Add - что добавить,
       Update - что переписать, Delete - что убрать как дубль. */
    const add = (res?.Add ?? []).map((x) => x.Keyword);
    const update = (res?.Update ?? []).map((x) => x.Keyword);
    const deleted = res?.Delete?.Ids?.length ?? 0;
    const failed = res?.Failure ?? [];

    const kept = [...add, ...update];

    title(`Ядро после схлопывания: ${kept.length} фраз из ${list.length}`);

    if (deleted) {
      note(`  Убрано как дубли: ${deleted}`);
    } else {
      note('  Дублей не нашлось — ядро уже чистое.');
    }

    if (kept.length) {
      table(
        kept.map((k) => ({ k })),
        [{ key: 'k', title: 'Фраза', max: 70 }],
      );
    }

    if (failed.length) {
      warn(`Не разобрано фраз: ${failed.length}`);
      for (const f of failed.slice(0, 10)) {
        note(`  · позиция ${f.Position}: ${(f.Errors ?? []).map((e) => e.Message).join('; ')}`);
      }
    }

    note('\n  Дубли в ядре — прямой путь к каннибализации: две страницы под один');
    note('  запрос конкурируют между собой и обе проигрывают.');
    return;
  }

  /* ── реальные запросы людей ────────────────────────────────────────── */
  if (a.cmd === 'queries') {
    warn('Этот отчёт заполнен только там, где реально крутилась реклама.');
    note('  Без открученного бюджета он будет пустым — это не ошибка.');
    note('  Отчёты Директа выгружаются асинхронно; при первом запуске');
    note('  сервис может ответить «отчёт формируется» — повторите позже.\n');

    const days = num(a.days, 30);
    const to = new Date();
    to.setUTCDate(to.getUTCDate() - 1);
    const from = new Date(to);
    from.setUTCDate(from.getUTCDate() - (days - 1));
    const ymd = (d) => d.toISOString().slice(0, 10);

    const body = {
      params: {
        SelectionCriteria: { DateFrom: ymd(from), DateTo: ymd(to) },
        FieldNames: ['Query', 'Impressions', 'Clicks', 'Ctr'],
        ReportName: `seo-queries-${ymd(from)}-${ymd(to)}`,
        ReportType: 'SEARCH_QUERY_PERFORMANCE_REPORT',
        DateRangeType: 'CUSTOM_DATE',
        Format: 'TSV',
        IncludeVAT: 'NO',
      },
    };

    const headers = {
      processingMode: 'auto',
      returnMoneyInMicros: 'false',
      skipReportHeader: 'true',
      skipReportSummary: 'true',
    };
    const login = directLogin();
    if (login) headers['Client-Login'] = login;

    /* Отчёты этого типа формируются только офлайн: первый запрос отвечает
       201 с пустым телом, следующие - 202, пока отчёт не готов, и лишь потом
       200 с данными. Разобрать 201 как готовый TSV - значит увидеть пустую
       строку и сказать «реклама не показывалась», хотя отчёт просто ещё
       считается. Поэтому смотрим на статус, а не только на тело.
       Повторять надо С ТЕМИ ЖЕ параметрами, включая имя отчёта. */
    let tsv = '';

    for (let attempt = 0; attempt < 12; attempt++) {
      const res = await directApi(`${API}/reports`, {
        method: 'POST',
        service: 'Директ (отчёты)',
        headers,
        json: body,
        withResponse: true,
        retries: 1,
      });

      if (res.status === 200) {
        tsv = res.text;
        break;
      }

      if (res.status === 201 || res.status === 202) {
        /* Сколько ждать, Директ говорит сам в заголовке retryIn. */
        const wait = Number(res.headers.get('retryIn')) || 20;
        if (attempt === 0) {
          note(`  Отчёт ставится в очередь. Директ просит подождать ${wait} с.`);
        }
        await new Promise((r) => setTimeout(r, wait * 1000));
        continue;
      }

      fail(`Директ ответил ${res.status}: ${String(res.text).slice(0, 200)}`);
      return;
    }

    if (!tsv) {
      warn('Отчёт так и не подготовился за отведённое время.');
      note('  Это нормально для больших периодов — повторите команду позже,');
      note('  Директ отдаст уже готовый отчёт.');
      return;
    }

    if (a.json) return console.log(tsv);

    /* Заголовок и итоговую строку мы попросили не присылать (skipReportHeader
       и skipReportSummary), но первая строка - это имена колонок. */
    const lines = String(tsv).trim().split('\n').filter(Boolean);
    if (lines.length < 2) {
      note('  Отчёт пустой — за период реклама не показывалась.');
      note('  Это ожидаемо, если контекстной рекламы нет: метод берёт данные');
      note('  из показов объявлений, а не из поиска вообще.');
      return;
    }

    const rows = lines.slice(1).map((l) => {
      const [q, imp, cl, ctr] = l.split('\t');
      return { q, imp: Number(imp) || 0, cl: Number(cl) || 0, ctr };
    });

    title(`Реальные запросы людей · ${ymd(from)} — ${ymd(to)}`);
    table(
      rows.sort((x, y) => y.imp - x.imp).slice(0, num(a.limit, 50)),
      [
        { key: 'q', title: 'Что набрали в поиске', max: 60 },
        { key: 'imp', title: 'Показы', align: 'right' },
        { key: 'cl', title: 'Клики', align: 'right' },
      ],
    );
    note('\n  Это живые формулировки, а не догадки. Лучший материал для H1,');
    note('  title и подзаголовков страниц услуг.');
    return;
  }

  console.log(`
  Яндекс.Директ — только SEO-полезное

    check                  жив ли доступ, есть ли кампании
    has-volume фраза…      ищут ли такие запросы (YES/NO, без цифр)
    dedupe фраза…          схлопнуть дубли в ядре
    queries                реальные запросы людей (нужна открученная реклама)

  Флаги: --file список.txt | --region 225 | --days 30 | --limit 50 | --json

  Частотности («сколько раз в месяц ищут») в API Директа v5 НЕТ — ни одного
  метода с этим числом не существует. Ближайшая бесплатная замена для
  сравнения формулировок между собой: node seo/cli/bing.mjs keyword «фраза»
`);
});
