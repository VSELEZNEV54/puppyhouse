/* Puppy House — блог.
   /blog/: фильтр статей по теме. Состояние в адресе: ?tema=maltipu (значение «all» не пишется).
     Разметка: [data-blog] → кнопки [data-bf-value], список [data-bf-list] > li[data-topic],
     счётчик [data-bf-count], [data-bf-status].
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

  /* ---------- /blog/: фильтр по теме ---------- */
  const root = document.querySelector('[data-blog]');
  if (root) {
    const buttons = Array.from(root.querySelectorAll('[data-bf-value]'));
    const items = Array.from(root.querySelectorAll('[data-bf-list] > li[data-topic]'));
    const count = root.querySelector('[data-bf-count]');
    const status = root.querySelector('[data-bf-status]');
    const allowed = buttons.map((b) => b.dataset.bfValue);
    const KEY = 'tema';

    const read = () => {
      const v = new URLSearchParams(location.search).get(KEY);
      return v && allowed.includes(v) ? v : 'all';
    };
    const write = (v) => {
      if (!history.replaceState) return;
      const q = new URLSearchParams(location.search);
      if (v === 'all') q.delete(KEY); else q.set(KEY, v);
      const qs = q.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
    };

    const apply = (value, announce) => {
      let visible = 0;
      buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.bfValue === value)));
      items.forEach((li) => {
        const show = value === 'all' || li.dataset.topic === value;
        li.hidden = !show;
        if (show) visible++;
      });
      const text = visible + ' ' + plural(visible, 'статья', 'статьи', 'статей');
      if (count) count.textContent = text;
      if (status && announce) {
        const btn = buttons.find((b) => b.dataset.bfValue === value);
        status.textContent = 'Показано: ' + text + (value === 'all' || !btn ? '' : ' — ' + btn.textContent.trim());
      }
    };

    let state = read();
    apply(state, false);

    buttons.forEach((b) => b.addEventListener('click', () => {
      const v = b.dataset.bfValue;
      // повторный клик по выбранной теме возвращает все статьи
      state = v === state && v !== 'all' ? 'all' : v;
      apply(state, true);
      write(state);
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
