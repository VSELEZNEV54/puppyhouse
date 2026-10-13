/* Puppy House — каталог /shchenki/: фильтры по породе, полу и статусу.
   Состояние в адресе: ?breed=maltipu&sex=female&status=available (значение «all» не пишется).
   Разметка: [data-catalog] → кнопки [data-cf-key][data-cf-value], карточки [data-cf-list] > li[data-breed][data-sex][data-status]. */
(() => {
  'use strict';

  const root = document.querySelector('[data-catalog]');
  if (!root) return;

  const $ = (sel, ctx = root) => ctx.querySelector(sel);
  const $$ = (sel, ctx = root) => Array.from(ctx.querySelectorAll(sel));

  const KEYS = ['breed', 'sex', 'status'];
  const filters = $('[data-cf]');
  const list = $('[data-cf-list]');
  const items = $$('[data-cf-list] > li[data-breed]');
  const more = $('[data-cf-more]');
  const empty = $('[data-cf-empty]');
  const count = $('[data-cf-count]');
  const status = $('[data-cf-status]');
  const badge = $('[data-cf-badge]');
  const toggle = $('[data-cf-toggle]');
  const resets = $$('[data-cf-reset]');
  const buttons = $$('[data-cf-key]');

  // допустимые значения — из самих кнопок
  const allowed = {};
  KEYS.forEach((k) => { allowed[k] = buttons.filter((b) => b.dataset.cfKey === k).map((b) => b.dataset.cfValue); });

  const plural = (n, one, few, many) => {
    const a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return many;
    if (b > 1 && b < 5) return few;
    if (b === 1) return one;
    return many;
  };

  const readUrl = () => {
    const q = new URLSearchParams(location.search);
    const st = {};
    KEYS.forEach((k) => {
      const v = q.get(k);
      st[k] = v && allowed[k].includes(v) ? v : 'all';
    });
    return st;
  };

  const writeUrl = (st) => {
    if (!history.replaceState) return;
    const q = new URLSearchParams(location.search);
    KEYS.forEach((k) => { if (st[k] === 'all') q.delete(k); else q.set(k, st[k]); });
    const qs = q.toString();
    history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
  };

  // «Ждёте другого щенка?» дополняет последний ряд сетки; если ряд полный — встаёт отдельной строкой
  const fitMore = (visible) => {
    if (!more) return;
    more.hidden = visible === 0;
    const cs = getComputedStyle(list);
    const cols = cs.display === 'grid' ? cs.gridTemplateColumns.split(' ').filter(Boolean).length || 1 : 1;
    const rest = visible % cols;
    more.style.gridColumn = 'span ' + (rest ? cols - rest : cols);
    more.classList.toggle('is-shared', rest > 0); // делит ряд с карточками → колонкой (pages.css)
  };

  let state = readUrl();
  let visible = items.length;

  const apply = (announce) => {
    visible = 0;
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(state[b.dataset.cfKey] === b.dataset.cfValue)));
    items.forEach((li) => {
      const show = KEYS.every((k) => state[k] === 'all' || li.dataset[k] === state[k]);
      li.hidden = !show;
      if (show) visible++;
    });
    list.hidden = visible === 0;
    if (empty) empty.hidden = visible > 0;
    fitMore(visible);

    const text = visible + ' ' + plural(visible, 'щенок', 'щенка', 'щенков');
    if (count) count.textContent = text;
    if (announce && status) status.textContent = visible ? 'Найдено: ' + text : 'Таких щенков сейчас нет';

    const active = KEYS.filter((k) => state[k] !== 'all').length;
    resets.forEach((r) => { if (r.closest('[data-cf]')) r.hidden = active === 0; });
    // на мобиле пол и статус спрятаны в панель — бейдж показывает, сколько там выбрано
    const inPanel = ['sex', 'status'].filter((k) => state[k] !== 'all').length;
    if (badge) { badge.hidden = inPanel === 0; badge.textContent = String(inPanel); }
    writeUrl(state);
  };

  buttons.forEach((b) => b.addEventListener('click', () => {
    state = { ...state, [b.dataset.cfKey]: b.dataset.cfValue };
    apply(true);
  }));

  resets.forEach((r) => r.addEventListener('click', () => {
    const fromEmpty = !r.closest('[data-cf]');
    state = { breed: 'all', sex: 'all', status: 'all' };
    apply(true);
    // кнопка сброса исчезла — фокус на первый фильтр, чтобы не потерялся
    const first = buttons[0];
    if (first && (fromEmpty || r.hidden)) first.focus({ preventScroll: !fromEmpty });
  }));

  if (toggle && filters) {
    toggle.addEventListener('click', () => {
      const open = toggle.getAttribute('aria-expanded') !== 'true';
      toggle.setAttribute('aria-expanded', String(open));
      filters.classList.toggle('is-open', open);
    });
  }

  let rt;
  window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => fitMore(visible), 120); });

  apply(false);
})();
