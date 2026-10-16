/* домщенков.рф — /otzyvy/: фильтр отзывов по породе и модалка «Оставить отзыв».
   Фильтр: [data-rf] → кнопки [data-rf-value], список [data-rf-list] > li[data-breed]. Состояние в адресе: ?breed=maltipu.
   Модалка: любая кнопка [data-rv-open] открывает #review-modal. Форма #review-form: два отдельных согласия (обработка
   данных и публикация, 152-ФЗ); в рабочем режиме (window.DSH.live, main.js) — POST {api}/reviews через общую очередь
   и повторы main.js, в прототипе — «отправка» без сервера, как раньше. */
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
  const doneText = $('#rm-done-text');
  const doneDefault = doneText ? doneText.textContent : '';
  const submit = $('[data-rv-submit]', form);
  const failBox = $('[data-rv-fail]', form);
  const TEXT_MAX = 4000; // как в API (ReviewIn.text) и maxlength у #rm-text
  const ERR = {
    name: 'Напишите, как вас подписать',
    phone: 'Проверьте номер: после +7 нужно 10 цифр',
    text: 'Расскажите хотя бы пару предложений',
    text_long: 'Отзыв слишком длинный: до 4000 знаков. Сократите его, пожалуйста',
    consent: 'Без согласия на обработку данных мы не сможем отправить отзыв',
    consent_publish: 'Без согласия мы не сможем опубликовать отзыв'
  };
  const FIELDS = ['name', 'phone', 'text', 'rating', 'consent', 'consent_publish']; // поля, о которых может сказать API (422)
  const tenDigits = (v) => { // как phoneDigits() в main.js: 10 цифр после +7 / 8
    let s = String(v || '').trim();
    let dg = s.startsWith('+7') ? s.slice(2).replace(/\D/g, '') : s.replace(/\D/g, '');
    if (!s.startsWith('+7') && dg.length === 11 && (dg[0] === '7' || dg[0] === '8')) dg = dg.slice(1);
    return dg;
  };
  let returnTo = null;
  let openedAt = 0; // elapsed_ms — от открытия окна
  let openSeq = 0; // ответ API от прошлого открытия не меняет экран нового
  const rvState = { key: '' };

  const setError = (field, msg) => {
    const el = $('#rm-' + field + '-err');
    if (el) { el.textContent = msg || ''; el.hidden = !msg; }
    const input = form.elements[field];
    // оценка — группа радиокнопок (RadioNodeList): отмечаем каждую
    const targets = !input ? [] : (typeof input.setAttribute === 'function' ? [input] : Array.from(input));
    targets.forEach((t) => { if (msg) t.setAttribute('aria-invalid', 'true'); else t.removeAttribute('aria-invalid'); });
  };
  const textLen = () => form.elements.text.value.trim().length;
  const validate = () => {
    const f = form.elements;
    const len = textLen();
    const checks = [
      ['name', !f.name.value.trim()],
      ['phone', tenDigits(f.phone.value).length !== 10],
      ['text', len < 10 || len > TEXT_MAX, len > TEXT_MAX ? ERR.text_long : ERR.text],
      ['consent', !f.consent.checked],
      ['consent_publish', !f.consent_publish.checked]
    ];
    let first = null;
    checks.forEach(([k, bad, msg]) => {
      setError(k, bad ? (msg || ERR[k]) : '');
      if (bad && !first) first = f[k];
    });
    if (first) first.focus();
    return !first;
  };
  const reset = () => {
    form.reset();
    FIELDS.forEach((k) => setError(k, ''));
    if (failBox) failBox.hidden = true;
    submit.disabled = false;
    submit.textContent = submit.dataset.label;
  };

  const lock = (on) => d.documentElement.classList.toggle('is-locked', on);

  const open = (opener) => {
    returnTo = opener;
    reset();
    openedAt = Date.now();
    openSeq++;
    rvState.key = '';
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
    const els = $$('a[href], button:not([disabled]), input:not([type="hidden"]):not([tabindex="-1"]), select, textarea, [tabindex]:not([tabindex="-1"])', modal)
      .filter((el) => el.offsetParent !== null && !(el.type === 'radio' && !el.checked && $$('input[name="' + el.name + '"]:checked', modal).length));
    if (!els.length) return;
    const first = els[0], last = els[els.length - 1];
    if (e.shiftKey && (d.activeElement === first || !modal.contains(d.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  form.addEventListener('input', (e) => {
    const n = e.target.name;
    if (n === 'name' && e.target.value.trim()) setError('name', '');
    if (n === 'phone' && tenDigits(e.target.value).length === 10) setError('phone', '');
    if (n === 'text' && textLen() >= 10 && textLen() <= TEXT_MAX) setError('text', '');
  });
  form.addEventListener('change', (e) => {
    const n = e.target.name;
    if ((n === 'consent' || n === 'consent_publish') && e.target.checked) setError(n, '');
    if (n === 'rating') setError('rating', '');
  });

  const showDone = (text) => {
    const name = form.elements.name.value.trim();
    doneTitle.textContent = 'Спасибо, ' + name;
    if (doneText) doneText.textContent = text || doneDefault;
    viewForm.hidden = true;
    viewDone.hidden = false;
    modal.setAttribute('aria-labelledby', 'rm-done-title');
    modal.setAttribute('aria-describedby', 'rm-done-text');
    doneTitle.focus();
  };

  // тело по контракту POST /reviews
  const reviewPayload = (api) => {
    const f = form.elements;
    const rating = form.querySelector('input[name="rating"]:checked');
    const ctx = api.context();
    return {
      name: f.name.value.trim(),
      phone: f.phone.value.trim(),
      city: f.city.value.trim() || null,
      breed: f.breed.value || null,
      rating: rating ? Number(rating.value) : null,
      text: f.text.value.trim(),
      consent: f.consent.checked,
      consent_version: api.consent.review || api.consent.processing,
      consent_publish: f.consent_publish.checked,
      consent_publish_version: api.consent.distribution,
      page: api.page(),
      visitor_id: ctx.visitor_id,
      session_id: ctx.session_id,
      hp_note: f.hp_note ? f.hp_note.value : '',
      elapsed_ms: openedAt ? Math.max(0, Date.now() - openedAt) : 0
    };
  };

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!validate()) return;
    submit.disabled = true;
    submit.textContent = 'Отправляем…';
    const api = window.DSH;
    if (!api || !api.live) { // прототип: без сервера, как раньше
      setTimeout(() => showDone(), reduceMotion ? 300 : 900);
      return;
    }
    if (failBox) failBox.hidden = true;
    const seq = openSeq;
    api.submit('/reviews', reviewPayload(api), rvState)
      .catch(() => ({ ok: false, status: 0, data: null }))
      .then((res) => {
        if (seq !== openSeq || !modal.hasAttribute('open')) return;
        submit.disabled = false;
        submit.textContent = submit.dataset.label;
        if (res.ok) { showDone('Отзыв появится на сайте после проверки.'); return; }
        if (res.status === 422) {
          const map = (res.data && res.data.error && res.data.error.fields) || {};
          const bad = FIELDS.filter((k) => map[k]);
          bad.forEach((k) => setError(k, String(map[k])));
          if (!bad.length) bad.push('text');
          if (!map[bad[0]]) setError('text', (res.data && res.data.error && res.data.error.message) || 'Проверьте, пожалуйста, текст отзыва');
          const el = form.elements[bad[0]];
          const target = el && typeof el.focus === 'function' ? el : (el && el[0]);
          if (target) target.focus();
          return;
        }
        if (res.status === 413) { // тело больше лимита API: такой отзыв не примут никогда, в очереди его нет
          setError('text', ERR.text_long);
          form.elements.text.focus();
          return;
        }
        // сервер недоступен после всех попыток (или ответил непонятно): отзыв ждёт в очереди, форма заполнена;
        // 400 / 415 — не сохранён (api.permanent), остаются только контакты
        if (failBox) {
          if (typeof api.failMode === 'function') api.failMode(failBox, !(api.permanent && api.permanent(res.status)));
          failBox.hidden = false;
        }
      });
  });
})();
