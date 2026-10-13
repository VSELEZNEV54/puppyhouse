/* домщенков.рф — /otzyvy/: фильтр отзывов по породе и модалка «Оставить отзыв».
   Фильтр: [data-rf] → кнопки [data-rf-value], список [data-rf-list] > li[data-breed]. Состояние в адресе: ?breed=maltipu.
   Модалка: любая кнопка [data-rv-open] открывает #review-modal; форма #review-form «отправляется» без сервера. */
(() => {
  'use strict';

  const d = document;
  const $ = (sel, ctx = d) => ctx.querySelector(sel);
  const $$ = (sel, ctx = d) => Array.from(ctx.querySelectorAll(sel));
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const plural = (n, one, few, many) => {
    const a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return many;
    if (b > 1 && b < 5) return few;
    if (b === 1) return one;
    return many;
  };

  /* ---------- фильтр отзывов ---------- */
  const root = $('[data-rf]');
  if (root) {
    const buttons = $$('[data-rf-value]', root);
    const list = $('[data-rf-list]', root);
    const items = $$('[data-rf-list] > li[data-breed]', root);
    const count = $('[data-rf-count]', root);
    const status = $('[data-rf-status]', root);
    const empty = $('[data-rf-empty]', root);
    const allowed = buttons.map((b) => b.dataset.rfValue);

    const readUrl = () => {
      const v = new URLSearchParams(location.search).get('breed');
      return v && allowed.includes(v) ? v : 'all';
    };
    const writeUrl = (v) => {
      if (!history.replaceState) return;
      const q = new URLSearchParams(location.search);
      if (v === 'all') q.delete('breed'); else q.set('breed', v);
      const qs = q.toString();
      history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash);
    };

    const apply = (value, announce) => {
      let visible = 0;
      buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.rfValue === value)));
      items.forEach((li) => {
        const show = value === 'all' || li.dataset.breed === value;
        li.hidden = !show;
        if (show) visible++;
      });
      list.hidden = visible === 0;
      if (empty) empty.hidden = visible > 0;
      const text = visible + ' ' + plural(visible, 'отзыв', 'отзыва', 'отзывов');
      if (count) count.textContent = text;
      if (announce && status) status.textContent = visible ? 'Показано: ' + text : 'Отзывов о такой породе пока нет';
      writeUrl(value);
    };

    buttons.forEach((b) => b.addEventListener('click', () => apply(b.dataset.rfValue, true)));
    $$('[data-rf-reset]', root).forEach((r) => r.addEventListener('click', () => {
      apply('all', true);
      if (buttons[0]) buttons[0].focus();
    }));
    apply(readUrl(), false);
  }

  /* ---------- модалка «Оставить отзыв» ---------- */
  const modal = $('#review-modal');
  const form = $('#review-form');
  if (!modal || !form) return;

  const viewForm = $('[data-rv-view="form"]', modal);
  const viewDone = $('[data-rv-view="done"]', modal);
  const doneTitle = $('#rm-done-title');
  const submit = $('[data-rv-submit]', form);
  const ERR = {
    name: 'Напишите, как вас подписать',
    text: 'Расскажите хотя бы пару предложений',
    consent: 'Без согласия мы не сможем опубликовать отзыв'
  };
  let returnTo = null;

  const setError = (field, msg) => {
    const el = $('#rm-' + field + '-err');
    if (el) { el.textContent = msg || ''; el.hidden = !msg; }
    const input = form.elements[field];
    if (input) { if (msg) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid'); }
  };
  const validate = () => {
    const f = form.elements;
    const checks = [
      ['name', !f.name.value.trim()],
      ['text', f.text.value.trim().length < 10],
      ['consent', !f.consent.checked]
    ];
    let first = null;
    checks.forEach(([k, bad]) => {
      setError(k, bad ? ERR[k] : '');
      if (bad && !first) first = f[k];
    });
    if (first) first.focus();
    return !first;
  };
  const reset = () => {
    form.reset();
    ['name', 'text', 'consent'].forEach((k) => setError(k, ''));
    submit.disabled = false;
    submit.textContent = submit.dataset.label;
  };

  const lock = (on) => d.documentElement.classList.toggle('is-locked', on);

  const open = (opener) => {
    returnTo = opener;
    reset();
    viewForm.hidden = false;
    viewDone.hidden = true;
    modal.setAttribute('aria-labelledby', 'rm-title');
    modal.setAttribute('aria-describedby', 'rm-sub');
    if (typeof modal.showModal === 'function') modal.showModal(); else modal.setAttribute('open', '');
    lock(true);
    setTimeout(() => form.elements.name.focus(), 30);
  };
  const close = () => {
    if (modal.open && typeof modal.close === 'function') modal.close();
    else if (modal.hasAttribute('open')) { modal.removeAttribute('open'); modal.dispatchEvent(new Event('close')); }
  };

  d.addEventListener('click', (e) => {
    const t = e.target.closest('[data-rv-open]');
    if (!t) return;
    e.preventDefault();
    open(t);
  });
  $$('[data-rv-close]', modal).forEach((b) => b.addEventListener('click', close));
  modal.addEventListener('close', () => {
    lock(false);
    const t = returnTo;
    returnTo = null;
    if (t && t.isConnected && t.offsetParent !== null) t.focus();
  });
  // клик по подложке закрывает окно (только если и нажали на подложке)
  let downOnBackdrop = false;
  modal.addEventListener('pointerdown', (e) => { downOnBackdrop = e.target === modal; });
  modal.addEventListener('click', (e) => { if (e.target === modal && downOnBackdrop) close(); });
  // ловушка фокуса: Tab по кругу внутри окна
  modal.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const els = $$('a[href], button:not([disabled]), input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])', modal)
      .filter((el) => el.offsetParent !== null && !(el.type === 'radio' && !el.checked && $$('input[name="' + el.name + '"]:checked', modal).length));
    if (!els.length) return;
    const first = els[0], last = els[els.length - 1];
    if (e.shiftKey && (d.activeElement === first || !modal.contains(d.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  form.addEventListener('input', (e) => {
    const n = e.target.name;
    if (n === 'name' && e.target.value.trim()) setError('name', '');
    if (n === 'text' && e.target.value.trim().length >= 10) setError('text', '');
  });
  form.addEventListener('change', (e) => {
    if (e.target.name === 'consent' && e.target.checked) setError('consent', '');
  });
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!validate()) return;
    submit.disabled = true;
    submit.textContent = 'Отправляем…';
    setTimeout(() => {
      const name = form.elements.name.value.trim();
      doneTitle.textContent = 'Спасибо, ' + name;
      viewForm.hidden = true;
      viewDone.hidden = false;
      modal.setAttribute('aria-labelledby', 'rm-done-title');
      modal.setAttribute('aria-describedby', 'rm-done-text');
      doneTitle.focus();
    }, reduceMotion ? 300 : 900);
  });
})();
