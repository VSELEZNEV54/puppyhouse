#!/usr/bin/env node
/**
 * Разослать инструменты по остальным проектам.
 *
 *   node seo/cli/sync.mjs            показать, что и куда уедет
 *   node seo/cli/sync.mjs --apply    скопировать
 *   node seo/cli/sync.mjs add <путь> подключить ещё один проект
 *   node seo/cli/sync.mjs list       какие проекты подключены
 *
 * Зачем. Инструменты живут копией в каждом проекте - так их видно там же,
 * где работаешь, и не нужно помнить путь к общей папке. Плата за это одна:
 * копии разъезжаются. Починил в одном месте, забыл про второе, через месяц
 * в одном проекте баг исправлен, в другом нет.
 *
 * Эта команда закрывает ровно эту дыру: копирует lib/ и cli/ отсюда во все
 * подключённые проекты. Настройки проекта (project.json) и его данные
 * не трогаются никогда - у каждого сайта они свои.
 *
 * Список проектов лежит в ~/.seo-tools/projects.json рядом с общими ключами.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync, cpSync, statSync } from 'node:fs';
import { resolve, basename } from 'node:path';
import { homedir } from 'node:os';
import { SEO_DIR, ROOT_DIR, PROJECT_NAME } from '../lib/env.mjs';
import { args, table, title, note, run, ok, warn, fail } from '../lib/out.mjs';

const REGISTRY = resolve(homedir(), '.seo-tools', 'projects.json');

/* Копируем только код. Настройки, ключи и накопленные данные - у каждого свои. */
const SHARED = ['lib', 'cli'];

function readRegistry() {
  if (!existsSync(REGISTRY)) return [];
  try {
    const v = JSON.parse(readFileSync(REGISTRY, 'utf8'));
    return Array.isArray(v) ? v : (v.projects ?? []);
  } catch {
    return [];
  }
}

function writeRegistry(list) {
  mkdirSync(resolve(homedir(), '.seo-tools'), { recursive: true });
  writeFileSync(REGISTRY, JSON.stringify({ projects: list }, null, 2), 'utf8');
}

/** Название проекта из его же настроек — чтобы в списке были имена, а не пути. */
function nameOf(dir) {
  const cfg = resolve(dir, 'seo', 'project.json');
  if (existsSync(cfg)) {
    try {
      return JSON.parse(readFileSync(cfg, 'utf8')).name || basename(dir);
    } catch {
      /* повреждённый файл — не повод падать, просто покажем путь */
    }
  }
  return basename(dir);
}

run(async () => {
  const a = args();
  const list = readRegistry();

  /* ── подключить проект ──────────────────────────────────────────────── */
  if (a.cmd === 'add') {
    const dir = a._[0];
    if (!dir) {
      fail('Укажите путь к проекту.');
      note('  node seo/cli/sync.mjs add "/Users/…/Другой проект"');
      process.exit(2);
    }

    const abs = resolve(dir);
    if (!existsSync(abs) || !statSync(abs).isDirectory()) {
      fail(`Папки нет: ${abs}`);
      process.exit(1);
    }

    if (list.includes(abs)) {
      warn('Этот проект уже подключён.');
      return;
    }

    list.push(abs);
    writeRegistry(list);
    ok(`Подключён: ${nameOf(abs)}`);
    note(`  ${abs}`);
    note('\n  Разослать инструменты: node seo/cli/sync.mjs --apply');
    note('  Не забудьте завести там seo/project.json — без него проект');
    note('  будет считать себя сайтом по умолчанию.');
    return;
  }

  /* ── список ─────────────────────────────────────────────────────────── */
  if (a.cmd === 'list') {
    title(`Подключённые проекты — ${list.length}`);
    if (!list.length) {
      note('  Пока ни одного. Подключить: node seo/cli/sync.mjs add <путь>');
      return;
    }
    table(
      list.map((d) => ({
        n: nameOf(d),
        p: d.replace(homedir(), '~'),
        s: existsSync(resolve(d, 'seo')) ? 'есть' : 'НЕТ ПАПКИ seo',
      })),
      [
        { key: 'n', title: 'Проект', max: 24 },
        { key: 'p', title: 'Путь', max: 46 },
        { key: 's', title: 'Инструменты' },
      ],
    );
    return;
  }

  /* ── рассылка ───────────────────────────────────────────────────────── */
  const targets = list.filter((d) => resolve(d) !== resolve(ROOT_DIR));

  title(`Рассылка инструментов из «${PROJECT_NAME}»`);

  if (!targets.length) {
    note('  Некуда рассылать: других проектов не подключено.');
    note('  Подключить: node seo/cli/sync.mjs add <путь>');
    return;
  }

  const rows = [];

  for (const dir of targets) {
    const dst = resolve(dir, 'seo');
    if (!existsSync(dir)) {
      rows.push({ n: nameOf(dir), r: 'папки проекта нет — пропускаю' });
      continue;
    }

    if (!a.apply) {
      rows.push({ n: nameOf(dir), r: `получит: ${SHARED.join(', ')}` });
      continue;
    }

    try {
      mkdirSync(dst, { recursive: true });
      for (const part of SHARED) {
        cpSync(resolve(SEO_DIR, part), resolve(dst, part), { recursive: true, force: true });
      }
      rows.push({ n: nameOf(dir), r: 'обновлено' });
    } catch (e) {
      rows.push({ n: nameOf(dir), r: `ошибка: ${e.message.slice(0, 50)}` });
    }
  }

  table(rows, [
    { key: 'n', title: 'Проект', max: 26 },
    { key: 'r', title: 'Что сделано', max: 46 },
  ]);

  if (!a.apply) {
    note('\n  Это был показ. Чтобы скопировать: node seo/cli/sync.mjs --apply');
  } else {
    ok('Готово.');
    note('  Настройки проектов и их данные не тронуты — только код инструментов.');
    note('  Проверить, что нигде не сломалось: node seo/cli/selftest.mjs в каждом.');
  }
});
