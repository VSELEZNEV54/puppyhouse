/* домщенков.рф — блог.
   /blog/: два фильтра — тема и порода; выбраны оба — статьи, подходящие под оба. На кнопке — сколько статей
     останется, если нажать (0 — кнопка неактивна). Состояние в адресе: ?tema=uhod&poroda=maltipu
     (старые ссылки ?tema=<порода> со страниц пород тоже работают).
     Разметка: [data-blog] → кнопки [data-bf-group="tag|breed"][data-bf-value], число [data-bf-n] внутри кнопки,
     список [data-bf-list] > li[data-tag][data-breed], [data-bf-count], [data-bf-reset], [data-bf-empty], [data-bf-status].
   Статья: оглавление .toc подсвечивает текущий раздел (aria-current="true"). */
(() => {
  'use strict';

  const plural = (n, one, few, many) => {
    const a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return many;
    if (b > 1 && b < 5) return few;
    if (b === 1) return one;
    return many;
  };

  /* ---------- /blog/: фильтр по теме и породе ---------- */
  const root = document.querySelector('[data-blog]');
  if (root) {
    const buttons = Array.from(root.querySelectorAll('[data-bf-value]'));
    const items = Array.from(root.querySelectorAll('[data-bf-list] > li'));
    const count = root.querySelector('[data-bf-count]');
    const status = root.querySelector('[data-bf-status]');
    const empty = root.querySelector('[data-bf-empty]');
    const list = root.querySelector('[data-bf-list]');
    const resets = Array.from(root.querySelectorAll('[data-bf-reset]'));
    const PARAM = { tag: 'tema', breed: 'poroda' };
    const values = (g) => buttons.filter((b) => b.dataset.bfGroup === g).map((b) => b.dataset.bfValue);

    const fits = (li, st) => (st.tag === 'all' || li.dataset.tag === st.tag) && (st.breed === 'all' || li.dataset.breed === st.breed);
    const read = () => {
      const q = new URLSearchParams(location.search);
      const st = { tag: q.get(PARAM.tag) || 'all', breed: q.get(PARAM.breed) || 'all' };
      if (values('breed').includes(st.tag) && st.breed === 'all') { st.breed = st.tag; st.tag = 'all'; } // ?tema=maltipu
      if (!values('tag').includes(st.tag)) st.tag = 'all';
      if (!values('breed').includes(st.breed)) st.breed = 'all';
      return st;
    };
    const write = (st) => {
      if (!history.replaceState) return;
      const q = new URLSearchParams(location.search);
      Object.keys(PARAM).forEach((g) => { if (st[g] === 'all') q.delete(PARAM[g]); else q.set(PARAM[g], st[g]); });
      const qs = q.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
    };

    const apply = (st, announce) => {
      let visible = 0;
      items.forEach((li) => {
        const show = fits(li, st);
        li.hidden = !show;
        if (show) visible++;
      });
      // кнопки: выбранная — нажата; на остальных — сколько статей будет, если выбрать её (при второй группе как есть)
      buttons.forEach((b) => {
        const g = b.dataset.bfGroup, v = b.dataset.bfValue;
        const on = st[g] === v;
        b.setAttribute('aria-pressed', String(on));
        const n = items.filter((li) => fits(li, Object.assign({}, st, { [g]: v }))).length;
        const badge = b.querySelector('[data-bf-n]');
        if (badge) badge.textContent = n;
        b.disabled = !on && n === 0;
      });
      const text = visible + ' ' + plural(visible, 'статья', 'статьи', 'статей');
      if (count) count.textContent = text;
      if (list) list.hidden = visible === 0;
      if (empty) empty.hidden = visible > 0;
      const filtered = st.tag !== 'all' || st.breed !== 'all';
      resets.forEach((r) => { if (r.closest('.blg-filters')) r.hidden = !filtered; });
      if (status && announce) status.textContent = 'Показано: ' + text;
    };

    let state = read();
    apply(state, false);

    buttons.forEach((b) => b.addEventListener('click', () => {
      const g = b.dataset.bfGroup, v = b.dataset.bfValue;
      // повторный клик по выбранной кнопке снимает выбор в этой группе
      state = Object.assign({}, state, { [g]: v === state[g] && v !== 'all' ? 'all' : v });
      apply(state, true);
      write(state);
    }));
    resets.forEach((r) => r.addEventListener('click', () => {
      state = { tag: 'all', breed: 'all' };
      apply(state, true);
      write(state);
      const first = buttons[0];
      if (first) first.focus();
    }));

    window.addEventListener('popstate', () => { state = read(); apply(state, false); });
  }

  /* ---------- статья: текущий раздел в оглавлении ---------- */
  const toc = document.querySelector('.blg-post .toc');
  if (toc) {
    const links = Array.from(toc.querySelectorAll('a[href^="#"]'));
    const list = toc.querySelector('.toc__list');
    const pairs = links
      .map((a) => ({ a, h: document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1))) }))
      .filter((p) => p.h);
    let current = null;
    let ticking = false;

    const reveal = (a) => {
      // лента оглавления на мобиле: подвинуть пилюлю в видимую часть, не трогая вертикальный скролл страницы
      if (!list || getComputedStyle(list).overflowX === 'visible') return;
      const lr = list.getBoundingClientRect(), ar = a.getBoundingClientRect();
      const l = ar.left - lr.left + list.scrollLeft, r = l + ar.width;
      if (l < list.scrollLeft || r > list.scrollLeft + list.clientWidth) {
        list.scrollTo({ left: Math.max(0, l - 24), behavior: 'smooth' });
      }
    };

    const update = () => {
      ticking = false;
      const line = window.innerHeight * 0.3;
      let active = null;
      pairs.forEach((p) => { if (p.h.getBoundingClientRect().top <= line) active = p; });
      if (active === current) return;
      if (current) current.a.removeAttribute('aria-current');
      current = active;
      if (current) {
        current.a.setAttribute('aria-current', 'true');
        reveal(current.a);
      }
    };
    const onScroll = () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } };

    if (pairs.length) {
      window.addEventListener('scroll', onScroll, { passive: true });
      window.addEventListener('resize', onScroll);
      update();
    }
  }
})();
