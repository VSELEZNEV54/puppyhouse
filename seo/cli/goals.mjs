#!/usr/bin/env node
/**
 * Цели в Яндекс.Метрике: создание пачкой.
 *
 *   node seo/cli/goals.mjs list      что заведено в счётчике сейчас
 *   node seo/cli/goals.mjs plan      что будет создано — ничего не меняет
 *   node seo/cli/goals.mjs create    создать недостающие
 *
 * Флаги: --counter 109…  --json
 *
 * Зачем. Код сайта отправляет 27 событий (src/scripts/analytics.ts), но
 * пока в кабинете нет цели с тем же именем, Метрика их просто не считает.
 * Завести 27 целей руками - это 27 одинаковых форм; здесь одна команда.
 *
 * Источник истины по именам - тип Goal в src/scripts/analytics.ts.
 * Если имя в Метрике не совпадёт с именем в коде хотя бы одним символом,
 * цель никогда не сработает, и заметить это будет нечем.
 *
 * Команда безопасна к повтору: перед созданием сверяется с тем, что уже
 * есть, и делает только недостающее. Ничего не удаляет.
 */

import { yandexApi } from '../lib/yandex.mjs';
import { need, get, PROJECT } from '../lib/env.mjs';
import { args, table, title, note, run, ok, warn, fail } from '../lib/out.mjs';

const MGMT = 'https://api-metrika.yandex.net/management/v1';

/* ─────────────────────────  Что должно быть заведено  ───────────────────── */

/**
 * Цели берутся из seo/project.json (ключ goals): у каждого проекта они свои,
 * а инструмент один на все проекты.
 *
 * ЗАПАСНОГО СПИСКА ЗДЕСЬ НЕТ — НАМЕРЕННО. В исходной версии инструмента он
 * был (цели того проекта, где инструмент родился), и это ровно та грабля,
 * на которую легко наступить: project.json нового проекта ещё без целей —
 * и команда молча заводит в свежем счётчике десятки чужих целей, которые
 * никогда не сработают, потому что код сайта их не отправляет. Удалять цели
 * из Метрики через API нельзя, чистить пришлось бы руками.
 *
 * Нет списка в project.json → команда останавливается и говорит, что делать.
 */
const GOALS = Array.isArray(PROJECT.goals) ? PROJECT.goals : [];

if (!GOALS.length) {
  fail(
    'В seo/project.json нет списка целей (ключ "goals").\n' +
    '  Возьмите за образец seo/project.example.json и перечислите цели\n' +
    '  СВОЕГО проекта: идентификатор цели должен посимвольно совпадать\n' +
    '  с тем, что отправляет код сайта (svpGoal(\'...\')).',
  );
  /* fail() только печатает — выходим сами, иначе команда пошла бы дальше
     с пустым списком и сказала бы «всё уже создано». */
  process.exit(2);
}

/* Составная цель-воронка и настройки счётчика - тоже свойства проекта.
   Нет в project.json - команда setup просто скажет, что настраивать нечего. */
const FUNNEL = PROJECT.funnel ?? null;
const ECOMMERCE_OBJECT = PROJECT.ecommerceObject ?? '';
const CUT_PARAMS = Array.isArray(PROJECT.cutParams) ? PROJECT.cutParams : [];

/* ─────────────────────────────  Тело запроса  ───────────────────────────── */

/**
 * Цель типа «Целевое событие»: срабатывает на ym(id, 'reachGoal', '<имя>').
 *
 * Формат проверен не по документации, а по живому образцу: в счётчике
 * карточки организации цели такого типа завёл сам Яндекс, и выглядят они
 * ровно так - type action, условие exact, имя события в поле url.
 *
 * Поля is_retargeting в запросе нет намеренно. Мы его пробовали: Метрика
 * принимает запрос и всё равно сохраняет 0, и на создании, и на PUT.
 * Причина - поле легаси, в схеме 2026 года его уже нет. Работе не мешает:
 * цель доступна Директу в любом случае, а аудитории для ретаргетинга
 * собираются сегментами, а не этим переключателем.
 *
 * Поле url в условии - это НЕ адрес страницы, а идентификатор события
 * из reachGoal. Название поля сбивает с толку, но так задумано.
 */
function goalBody(g) {
  return {
    goal: {
      name: g.name,
      type: 'action',
      conditions: [{ type: 'exact', url: g.id }],
    },
  };
}

/** Имя события, на которое настроена уже существующая цель. */
function eventOf(goal) {
  if (goal.type !== 'action') return null;
  return goal.conditions?.[0]?.url ?? null;
}

/* ──────────────────────────────  Счётчик  ───────────────────────────────── */

async function counterId(a) {
  const asked = a?.counter;
  if (!asked || asked === true) {
    return need('YANDEX_METRIKA_COUNTER', 'Номер счётчика — см. seo/.env');
  }
  if (/^\d+$/.test(String(asked))) return String(asked);

  const list = await yandexApi(`${MGMT}/counters`, { service: 'Метрика (управление)' });
  const needle = String(asked).toLowerCase();
  const hits = (list?.counters ?? []).filter((c) =>
    (c.name ?? '').toLowerCase().includes(needle),
  );
  if (hits.length !== 1) {
    throw new Error(`По «${asked}» подходит ${hits.length} счётчиков — укажите номером.`);
  }
  note(`  Счётчик: ${hits[0].id} — ${hits[0].name}`);
  return String(hits[0].id);
}

/* ───────────────────────────────  Команды  ──────────────────────────────── */

run(async () => {
  const a = args();
  const counter = await counterId(a);
  const out = (o) => console.log(JSON.stringify(o, null, 2));

  const existing = await yandexApi(`${MGMT}/counter/${counter}/goals?useDeleted=false`, {
    service: 'Метрика (управление)',
  });
  const have = existing?.goals ?? [];

  /* Сверяемся по имени события, а не по названию цели: название человек
     может переименовать в кабинете, а событие - это то, что реально
     связывает цель с кодом сайта.

     Эта сверка обязательна, а не «на всякий случай»: сама Метрика дубли
     не проверяет вообще. Повторный POST с тем же именем и тем же условием
     создаст вторую цель с новым номером и ответит 200 OK. Запусти команду
     дважды без сверки - получишь 54 цели вместо 27. */
  const haveEvents = new Set(have.map(eventOf).filter(Boolean));
  const missing = GOALS.filter((g) => !haveEvents.has(g.id));
  const auto = have.filter((g) => g.type !== 'action');

  /* ── что есть сейчас ────────────────────────────────────────────────── */
  if (a.cmd === 'list') {
    if (a.json) return out(have);

    title(`Цели счётчика ${counter} — заведено ${have.length}`);

    if (!have.length) {
      warn('Целей нет ни одной. События из кода уходят в никуда.');
      note('  Посмотреть, что будет создано: node seo/cli/goals.mjs plan');
      return;
    }

    table(
      have.map((g) => ({
        id: String(g.id),
        n: g.name,
        e: eventOf(g) ?? `(автоцель, тип ${g.type})`,
      })),
      [
        { key: 'id', title: 'Номер', align: 'right' },
        { key: 'n', title: 'Название', max: 40 },
        { key: 'e', title: 'Событие', max: 30 },
      ],
    );
    return;
  }

  /* ── что будет создано ──────────────────────────────────────────────── */
  if (!a.cmd || a.cmd === 'plan') {
    if (a.json) return out({ counter, missing, existing: have.length });

    title(`Счётчик ${counter}`);
    note(`  Заведено сейчас: ${have.length}. Из них по событиям кода: ${haveEvents.size}.`);

    if (!missing.length) {
      ok(`Все ${GOALS.length} целей на месте — создавать нечего.`);
    } else {
      title(`Будет создано целей: ${missing.length}`);
      table(
        missing.map((g) => ({ s: g.star ? '★' : '', e: g.id, n: g.name })),
        [
          { key: 's', title: '' },
          { key: 'e', title: 'Событие', max: 22 },
          { key: 'n', title: 'Название цели', max: 44 },
        ],
      );
      note('\n  ★ — то, без чего не видно денег: воронка оплаты и заявки.');
      note('\n  Ничего пока не создано. Чтобы создать:');
      note('    node seo/cli/goals.mjs create');
    }

    if (auto.length) {
      console.log('');
      warn(`В счётчике ${auto.length} автоцелей Метрики:`);
      for (const g of auto) note(`    ${g.name}  (тип ${g.type})`);
      note('');
      note('  Часть из них ловит то же, что и события кода — например, отправку');
      note('  формы и клик по почте. Тогда одна заявка считается дважды, и в');
      note('  Директе реклама оптимизируется по завышенной цифре.');
      note('  Удалять автоматически не буду: решение ваше. Скажете — уберу.');
    }
    return;
  }

  /* ── создание ───────────────────────────────────────────────────────── */
  if (a.cmd === 'create') {
    if (!missing.length) {
      ok('Все цели уже на месте — создавать нечего.');
      return;
    }

    title(`Создаю ${missing.length} целей в счётчике ${counter}`);

    const done = [];
    const failed = [];

    for (const g of missing) {
      try {
        const res = await yandexApi(`${MGMT}/counter/${counter}/goals`, {
          method: 'POST',
          service: 'Метрика (управление)',
          json: goalBody(g),
          retries: 1,
        });
        done.push({ e: g.id, n: g.name, id: String(res?.goal?.id ?? '') });
      } catch (e) {
        failed.push({ e: g.id, n: g.name, why: e.message.slice(0, 70) });
        /* Первая же ошибка обычно означает, что неверен формат запроса,
           а не что не повезло с одной целью. Останавливаемся, чтобы
           не наплодить два десятка одинаковых отказов. */
        if (failed.length >= 3) {
          fail('Три ошибки подряд — останавливаюсь, чтобы не сломать счётчик.');
          break;
        }
      }
    }

    if (done.length) {
      console.log('');
      table(done, [
        { key: 'id', title: 'Номер', align: 'right' },
        { key: 'e', title: 'Событие', max: 22 },
        { key: 'n', title: 'Название', max: 44 },
      ]);
      ok(`Создано целей: ${done.length}`);
    }

    if (failed.length) {
      console.log('');
      table(failed, [
        { key: 'e', title: 'Событие', max: 20 },
        { key: 'why', title: 'Что ответила Метрика', max: 60 },
      ]);
      fail(`Не создано: ${failed.length}`);
    }

    if (done.length) {
      note('\n  Данные по целям появятся не сразу — Метрике нужно несколько минут,');
      note('  а чтобы цель сработала, посетитель должен принять cookie на сайте.');
      note('\n  Проверить: node seo/cli/metrika.mjs goals --days 28');
    }
    return;
  }

  /* ── воронка, e-commerce, обрезка GET-параметров ────────────────────── */
  if (a.cmd === 'setup') {
    title(`Настройка счётчика ${counter}`);

    /* 1. Составная цель: показывает, на каком шаге отваливаются люди.
          Сверяемся по названию - у составной цели нет события, по которому
          её можно было бы опознать так же надёжно, как обычную. */
    if (!FUNNEL) {
      note('  Воронка в project.json не описана — пропускаю.');
    } else if (have.some((g) => g.name === FUNNEL.name)) {
      note(`  Воронка «${FUNNEL.name}» уже есть.`);
    } else {
      await yandexApi(`${MGMT}/counter/${counter}/goals`, {
        method: 'POST',
        service: 'Метрика (управление)',
        json: {
          goal: {
            name: FUNNEL.name,
            type: 'step',
            steps: FUNNEL.steps.map((st) => ({
              name: st.name,
              type: 'action',
              conditions: [{ type: 'exact', url: st.id }],
            })),
          },
        },
      });
      ok(`Воронка «${FUNNEL.name}» — создана, шагов: ${FUNNEL.steps.length}`);
    }

    /* 2. Электронная коммерция. Читаем счётчик целиком и дописываем два поля
          в code_options: там же лежат вебвизор, информер и прочее, и PUT
          только с одним полем может обнулить соседние. */
    if (!ECOMMERCE_OBJECT) {
      note('  Контейнер электронной коммерции в project.json не задан — пропускаю.');
    } else {
      const info = await yandexApi(`${MGMT}/counter/${counter}`, { service: 'Метрика (управление)' });
      const opts = info?.counter?.code_options ?? {};
      if (opts.ecommerce) {
        note(`  Электронная коммерция уже включена (контейнер ${opts.ecommerce_object || ECOMMERCE_OBJECT}).`);
      } else {
        await yandexApi(`${MGMT}/counter/${counter}`, {
          method: 'PUT',
          service: 'Метрика (управление)',
          json: { counter: { code_options: { ...opts, ecommerce: true, ecommerce_object: ECOMMERCE_OBJECT } } },
        });
        ok(`Электронная коммерция включена, контейнер ${ECOMMERCE_OBJECT}`);
      }
    }

    /* 3. Обрезка GET-параметров: без неё отчёт «Страницы» разваливается на
          тысячи адресов вида /result?id=<uuid> и читать его невозможно. */
    if (!CUT_PARAMS.length) {
      note('  GET-параметры для обрезки в project.json не заданы — пропускаю.');
    } else {
      const list = await yandexApi(`${MGMT}/counter/${counter}/operations`, {
        service: 'Метрика (управление)',
      });
      const already = new Set(
        (list?.operations ?? [])
          .filter((o) => o.action === 'cut_parameter')
          .map((o) => o.value),
      );
      const add = CUT_PARAMS.filter((v) => !already.has(v));
      for (const value of add) {
        await yandexApi(`${MGMT}/counter/${counter}/operations`, {
          method: 'POST',
          service: 'Метрика (управление)',
          json: { operation: { action: 'cut_parameter', attr: 'url', value, status: 'active' } },
        });
      }
      if (add.length) ok(`GET-параметры обрезаются: добавлено ${add.length} — ${add.join(', ')}`);
      else note(`  Все ${CUT_PARAMS.length} GET-параметров уже в списке обрезки.`);
    }

    note('\n  Проверить: node seo/cli/metrika.mjs goals --days 28');
    return;
  }

  console.log(`
  Цели Яндекс.Метрики — счётчик ${get('YANDEX_METRIKA_COUNTER') || '(не задан)'}

    list      что заведено в счётчике сейчас
    plan      что будет создано — ничего не меняет
    create    создать недостающие
    setup     воронка, электронная коммерция, обрезка GET-параметров

  Флаги: --counter 109… | --json

  Имена целей берутся из seo/project.json (ключ goals) — это то, что
  реально отправляет сайт. Расхождение хотя бы в одном символе означает,
  что цель не сработает никогда.
`);
});
