/**
 * Вывод в консоль и разбор аргументов.
 *
 * У всех инструментов один договор:
 *   - по умолчанию печатают таблицу, которую читает человек;
 *   - с флагом --json печатают сырые данные, которые читает агент
 *     или скрипт (jq, сводный отчет, cron).
 *
 * Таблица считает ширину по фактическому содержимому и умеет русский:
 * выравнивание по количеству символов, а не байт.
 */

/* ──────────────────────────────  Аргументы  ─────────────────────────────── */

/**
 * Разбор argv: команда + флаги.
 *   node seo/cli/gsc.mjs queries --days 28 --limit 50 --json
 *   -> { cmd: 'queries', days: '28', limit: '50', json: true, _: [] }
 */
/* Флаги без значения. Без этого списка `indexnow ping --json /uslugi/`
   разбирался бы как json='/uslugi/', адрес пропадал бы из списка, и команда
   падала бы с «не переданы адреса» - при том что адрес передан. */
const BOOLEAN_FLAGS = new Set([
  'json', 'clean', 'send', 'force', 'save', 'local', 'skipCheck', 'help',
]);

export function args(argv = process.argv.slice(2)) {
  const out = { cmd: argv[0] && !argv[0].startsWith('-') ? argv[0] : '', _: [] };
  const rest = out.cmd ? argv.slice(1) : argv;

  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = rest[i + 1];

      if (BOOLEAN_FLAGS.has(key)) {
        out[key] = true;
        continue;
      }

      if (next === undefined || next.startsWith('--')) {
        out[key] = true;
      } else {
        out[key] = next;
        i++;
      }
    } else {
      out._.push(a);
    }
  }
  return out;
}

/** Число из флага с запасным значением. */
export function num(v, fallback) {
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : fallback;
}

/* ─────────────────────────────────  Даты  ───────────────────────────────── */

/** YYYY-MM-DD. Все API в наборе понимают только этот формат. */
export function ymd(date) {
  return date.toISOString().slice(0, 10);
}

/**
 * Диапазон "последние N дней".
 * Вчерашний день - конец периода: сегодняшняя статистика везде неполная
 * и сравнивать ее с прошлыми днями некорректно.
 */
export function lastDays(n) {
  const end = new Date();
  end.setUTCDate(end.getUTCDate() - 1);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (n - 1));
  return { from: ymd(start), to: ymd(end) };
}

/** Предыдущий период такой же длины - для сравнения "стало / было". */
export function previousPeriod(from, to) {
  const start = new Date(from + 'T00:00:00Z');
  const end = new Date(to + 'T00:00:00Z');
  const days = Math.round((end - start) / 86_400_000) + 1;
  const prevEnd = new Date(start);
  prevEnd.setUTCDate(prevEnd.getUTCDate() - 1);
  const prevStart = new Date(prevEnd);
  prevStart.setUTCDate(prevStart.getUTCDate() - (days - 1));
  return { from: ymd(prevStart), to: ymd(prevEnd) };
}

/* ────────────────────────────────  Таблица  ─────────────────────────────── */

const width = (s) => [...String(s ?? '')].length;

function pad(s, w, align) {
  const str = String(s ?? '');
  const gap = Math.max(0, w - width(str));
  return align === 'right' ? ' '.repeat(gap) + str : str + ' '.repeat(gap);
}

/** Обрезка длинных значений, чтобы таблица не разъезжалась. */
function clip(s, max) {
  const str = String(s ?? '');
  return width(str) > max ? [...str].slice(0, max - 1).join('') + '…' : str;
}

/**
 * Таблица.
 * @param {Array<object>} rows
 * @param {Array<{key:string,title:string,align?:'right',max?:number}>} cols
 */
export function table(rows, cols) {
  if (!rows || rows.length === 0) {
    console.log('  (пусто — данных за период нет)');
    return;
  }

  const prepared = rows.map((r) =>
    Object.fromEntries(cols.map((c) => [c.key, clip(fmt(r[c.key]), c.max ?? 60)])),
  );

  const widths = cols.map((c) =>
    Math.max(width(c.title), ...prepared.map((r) => width(r[c.key]))),
  );

  const line = (cells) => '  ' + cells.join('  ');

  console.log(line(cols.map((c, i) => pad(c.title, widths[i], c.align))));
  console.log(line(widths.map((w) => '─'.repeat(w))));
  for (const r of prepared) {
    console.log(line(cols.map((c, i) => pad(r[c.key], widths[i], c.align))));
  }
}

/** Числа с разделителем разрядов, доли - с двумя знаками. */
export function fmt(v) {
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return '—';
    if (Number.isInteger(v)) return v.toLocaleString('ru-RU');
    return v.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
  }
  return v ?? '';
}

/** Процент с одним знаком. */
export function pct(v) {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
  return `${v.toFixed(1)}%`;
}

/** Дельта к прошлому периоду: +12,3% / −4,1% / без изменений. */
export function delta(now, before) {
  if (!before) return now ? 'новое' : '—';
  const d = ((now - before) / before) * 100;
  if (Math.abs(d) < 0.5) return '≈';
  return (d > 0 ? '+' : '−') + Math.abs(d).toFixed(1) + '%';
}

/* ────────────────────────────────  Заголовки  ───────────────────────────── */

export function title(text) {
  console.log('\n\x1b[1m' + text + '\x1b[0m');
}

export function note(text) {
  console.log('\x1b[2m' + text + '\x1b[0m');
}

export function ok(text) {
  console.log('\x1b[32m✓\x1b[0m ' + text);
}

export function warn(text) {
  console.log('\x1b[33m!\x1b[0m ' + text);
}

export function fail(text) {
  console.log('\x1b[31m✗\x1b[0m ' + text);
}

/**
 * Единая обертка запуска инструмента: ловит ApiError и печатает его
 * по-человечески, без стектрейса. Стектрейс нужен разработчику,
 * а инструментом пользуется владелец сайта.
 */
export async function run(main) {
  try {
    await main();
  } catch (e) {
    console.error('\n\x1b[31m✗ ' + (e.message || String(e)) + '\x1b[0m');
    if (e.hint) console.error('\n  ' + e.hint);
    if (process.env.SEO_DEBUG) console.error('\n', e);
    console.error('');
    process.exit(1);
  }
}
