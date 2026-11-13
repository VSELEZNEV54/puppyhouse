#!/usr/bin/env node
/**
 * Прогон всех команд набора: что-нибудь сломалось?
 *
 *   node seo/cli/selftest.mjs                  всё, что доступно
 *   node seo/cli/selftest.mjs --counter 109…   ещё и по другому счётчику
 *
 * Зачем это появилось. 31.08.2026 при добавлении выбора счётчика я сделал
 * грубую замену по тексту, поймал только однострочные вызовы и проверил
 * одну команду из десяти. Восемь команд после этого падали с 403 - и на
 * втором счётчике, и на основном. Нашёл это не я, а заказчик.
 *
 * Урок дешевле повторить машиной, чем человеком: команд полтора десятка,
 * все читающие, прогон занимает минуту. Запускать после любой правки
 * в seo/ - и особенно после правок, сделанных заменой по тексту.
 *
 * Проверка честная: каждая команда действительно выполняется против API.
 * Ничего не меняется - только чтение. Команды записи (create, recrawl,
 * annotate, ping) намеренно не трогаем.
 */

import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { has, SEO_DIR, SITE_LABEL, PROJECT_NAME } from '../lib/env.mjs';
import { homedir } from 'node:os';
import { existsSync } from 'node:fs';
import { args, table, title, note, run, ok, warn, fail } from '../lib/out.mjs';

/* Только чтение. Ни одна из этих команд ничего не меняет. */
const CHECKS = [
  { file: 'doctor.mjs',    argv: [],                      need: null },

  { file: 'metrika.mjs',   argv: ['counters'],            need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['summary'],             need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['sources'],             need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['search'],              need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['phrases'],             need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['landings'],            need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['pages'],               need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['goals'],               need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['goals-list'],          need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['devices'],             need: 'yandex' },
  { file: 'metrika.mjs',   argv: ['regions'],             need: 'yandex' },

  { file: 'goals.mjs',     argv: ['list'],                need: 'yandex' },
  { file: 'goals.mjs',     argv: ['plan'],                need: 'yandex' },

  { file: 'webmaster.mjs', argv: ['hosts'],               need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['summary'],             need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['queries'],             need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['monitoring'],          need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['indexing'],            need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['dropped'],             need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['crawl'],               need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['problems'],            need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['broken'],              need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['links'],               need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['sitemaps'],            need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['sqi'],                 need: 'yandex' },
  { file: 'webmaster.mjs', argv: ['quota'],               need: 'yandex' },

  { file: 'gsc.mjs',       argv: ['sites'],               need: 'google' },
  { file: 'gsc.mjs',       argv: ['summary'],             need: 'google' },
  { file: 'gsc.mjs',       argv: ['queries'],             need: 'google' },
  { file: 'gsc.mjs',       argv: ['pages'],               need: 'google' },
  { file: 'gsc.mjs',       argv: ['devices'],             need: 'google' },
  { file: 'gsc.mjs',       argv: ['dates'],               need: 'google' },
  { file: 'gsc.mjs',       argv: ['sitemaps'],            need: 'google' },
  { file: 'gsc.mjs',       argv: ['opportunities'],       need: 'google' },
  { file: 'gsc.mjs',       argv: ['zero-click'],          need: 'google' },

  { file: 'psi.mjs',       argv: [],                      need: 'psi', slow: true },
  { file: 'bing.mjs',      argv: ['sites'],               need: 'bing' },
];

/** Что настроено — то и проверяем. */
function available() {
  return {
    yandex: has('YANDEX_OAUTH_TOKEN'),
    /* Ключ Google живёт либо в проекте, либо в общем месте на компьютере -
       проверять надо оба, иначе половина проверок молча пропускается. */
    google:
      has('GOOGLE_SERVICE_ACCOUNT_KEY') ||
      existsSync(resolve(SEO_DIR, 'keys', 'google-service-account.json')) ||
      existsSync(resolve(homedir(), '.seo-tools', 'google-service-account.json')),
    psi: has('GOOGLE_API_KEY'),
    bing: has('BING_API_KEY'),
  };
}

/** Выполнить команду и вернуть, чем закончилась. */
function runOne(file, argv) {
  return new Promise((done) => {
    const child = spawn(process.execPath, [resolve(SEO_DIR, 'cli', file), ...argv], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let out = '';
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', (d) => (out += d));

    child.on('close', (code) => {
      /* Убираем цветовые последовательности - иначе поиск по тексту
         спотыкается о невидимые символы. */
      const clean = out.replace(/\x1b\[[0-9;]*m/g, '');
      const marker = clean.split('\n').find((l) => l.trim().startsWith('✗'));
      done({ code, failed: code !== 0 || Boolean(marker), why: (marker ?? '').replace('✗', '').trim() });
    });
  });
}

run(async () => {
  const a = args();
  const have = available();
  const extra = a.counter && a.counter !== true ? String(a.counter) : null;

  title(`Прогон команд набора · ${PROJECT_NAME} · ${SITE_LABEL}`);
  note('  Только чтение: ничего не меняется и никуда не отправляется.');
  note(
    `  Доступно: ${Object.entries(have).filter(([, v]) => v).map(([k]) => k).join(', ') || 'ничего'}`,
  );
  console.log('');

  const rows = [];
  let failed = 0;
  let skipped = 0;

  const queue = [...CHECKS];

  /* Второй счётчик прогоняем теми же командами Метрики: ровно на этом
     месте прошлый раз и сломалось. */
  if (extra) {
    for (const c of CHECKS) {
      if (c.file === 'metrika.mjs' && c.argv[0] !== 'counters') {
        queue.push({ ...c, argv: [...c.argv, '--counter', extra], tag: `счётчик ${extra}` });
      }
    }
  }

  for (const c of queue) {
    /* В подпись берём только саму подкоманду: значения флагов туда попадать
       не должны, иначе номер счётчика печатается дважды. */
    const sub = c.argv[0] && !c.argv[0].startsWith('--') ? c.argv[0] : '';
    const label = `${c.file.replace('.mjs', '')} ${sub}`.trim();

    if (c.need && !have[c.need]) {
      skipped++;
      continue;
    }

    const r = await runOne(c.file, c.argv);
    if (r.failed) failed++;

    rows.push({
      n: label + (c.tag ? `  · ${c.tag}` : ''),
      s: r.failed ? 'СЛОМАНО' : 'ок',
      w: r.failed ? r.why.slice(0, 60) : '',
    });
  }

  table(rows, [
    { key: 'n', title: 'Команда', max: 40 },
    { key: 's', title: 'Итог' },
    { key: 'w', title: 'Что не так', max: 60 },
  ]);

  console.log('');
  if (failed) {
    fail(`Сломано команд: ${failed} из ${rows.length}`);
    process.exitCode = 1;
  } else {
    ok(`Все ${rows.length} команд отвечают.`);
  }
  if (skipped) note(`  Пропущено ${skipped} — для них нет доступа, это не ошибка.`);
});
