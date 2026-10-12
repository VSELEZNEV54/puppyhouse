/* Puppy House — Вариант B «Ярко и по-доброму». Vanilla JS, no dependencies. */
(() => {
  'use strict';

  const doc = document;
  const html = doc.documentElement;
  const $ = (s, c = doc) => c.querySelector(s);
  const $$ = (s, c = doc) => Array.from(c.querySelectorAll(s));
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* ---------------------------------------------------------
     Toast
     --------------------------------------------------------- */
  const toast = $('#toast');
  let toastTimer = 0;
  function showToast(message) {
    if (!toast) return;
    // A modal <dialog> lives in the top layer: host the toast inside it so it stays visible.
    const host = doc.querySelector('dialog[open]') || doc.body;
    if (toast.parentElement !== host) host.appendChild(toast);
    toast.querySelector('span').textContent = message;
    toast.classList.remove('is-show');
    void toast.offsetWidth; // restart transition
    toast.classList.add('is-show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-show'), 2800);
  }

  /* Internal pages are not built yet: intercept a[href^="/"] (anchors "#…" work as usual). */
  doc.addEventListener('click', (e) => {
    const a = e.target.closest('a[href]');
    if (!a) return;
    const href = a.getAttribute('href');
    if (!href || href.charAt(0) !== '/' || href.charAt(1) === '/') return;
    e.preventDefault();
    showToast('Раздел появится на следующем этапе');
  });

  /* In-page anchors: smooth scroll via JS (keeps programmatic scrolling instant) */
  doc.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (!a || e.defaultPrevented) return;
    const id = decodeURIComponent(a.getAttribute('href').slice(1));
    const target = id ? doc.getElementById(id) : null;
    if (!target) return;
    e.preventDefault();
    const behavior = reduceMotion.matches ? 'auto' : 'smooth';
    if (id === 'top') window.scrollTo({ top: 0, behavior });
    else target.scrollIntoView({ behavior, block: 'start' });
    if (history.pushState) history.pushState(null, '', '#' + id);
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  });

  /* ---------------------------------------------------------
     Header: shadow on scroll
     --------------------------------------------------------- */
  const header = $('#header');
  const onScroll = () => header && header.classList.toggle('is-scrolled', window.scrollY > 4);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* ---------------------------------------------------------
     Desktop dropdown «Породы»
     --------------------------------------------------------- */
  const dd = $('[data-dd]');
  const ddBtn = dd && $('.nav__dd-btn', dd);
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  let ddTimer = 0;
  let ddByHover = false;
  const ddIsOpen = () => !!dd && dd.classList.contains('is-open');
  function setDD(open) {
    if (!dd) return;
    dd.classList.toggle('is-open', open);
    ddBtn.setAttribute('aria-expanded', String(open));
    if (!open) ddByHover = false;
  }
  if (dd) {
    ddBtn.addEventListener('click', () => {
      if (ddByHover && ddIsOpen()) { ddByHover = false; return; } // opened by hover → click keeps it open
      setDD(!ddIsOpen());
    });
    dd.addEventListener('mouseenter', () => {
      if (!finePointer.matches) return;
      clearTimeout(ddTimer);
      if (!ddIsOpen()) { ddByHover = true; setDD(true); }
    });
    dd.addEventListener('mouseleave', () => {
      if (!finePointer.matches) return;
      ddTimer = setTimeout(() => setDD(false), 180);
    });
    dd.addEventListener('focusout', (e) => { if (!dd.contains(e.relatedTarget)) setDD(false); });
    doc.addEventListener('click', (e) => { if (ddIsOpen() && !dd.contains(e.target)) setDD(false); });
  }

  /* ---------------------------------------------------------
     Mobile menu
     --------------------------------------------------------- */
  const burger = $('.burger');
  const menu = $('#mmenu');
  let menuReturnFocus = null;
  function openMenu() {
    if (!menu) return;
    menuReturnFocus = doc.activeElement;
    menu.hidden = false;
    burger.setAttribute('aria-expanded', 'true');
    html.classList.add('is-locked');
    $('.mmenu__close', menu).focus();
  }
  function closeMenu(returnFocus) {
    if (!menu || menu.hidden) return;
    menu.hidden = true;
    burger.setAttribute('aria-expanded', 'false');
    if (!($('#price-modal') || {}).open) html.classList.remove('is-locked');
    if (returnFocus && menuReturnFocus && menuReturnFocus.focus) menuReturnFocus.focus();
  }
  if (burger && menu) {
    burger.addEventListener('click', openMenu);
    $$('[data-close-menu]', menu).forEach((el) => {
      el.addEventListener('click', () => closeMenu(el.classList.contains('mmenu__close')));
    });
    $$('.mmenu__group-btn', menu).forEach((btn) => {
      btn.addEventListener('click', () => {
        const sub = doc.getElementById(btn.getAttribute('aria-controls'));
        const open = btn.getAttribute('aria-expanded') !== 'true';
        btn.setAttribute('aria-expanded', String(open));
        if (sub) sub.hidden = !open;
      });
    });
    // Simple focus trap
    menu.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const items = $$('a[href], button:not([disabled])', menu).filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && doc.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && doc.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    window.matchMedia('(min-width: 1280px)').addEventListener('change', (e) => { if (e.matches) closeMenu(false); });
  }

  /* ---------------------------------------------------------
     Tooltip on the РКФ trust chip
     --------------------------------------------------------- */
  const tipBtn = $('.trust__info');
  const tipChip = tipBtn && tipBtn.closest('.trust__chip');
  function setTip(open) {
    if (!tipChip) return;
    tipChip.classList.toggle('is-open', open);
    tipBtn.setAttribute('aria-expanded', String(open));
  }
  if (tipBtn) {
    tipBtn.addEventListener('click', (e) => { e.stopPropagation(); setTip(!tipChip.classList.contains('is-open')); });
    doc.addEventListener('click', (e) => { if (!tipChip.contains(e.target)) setTip(false); });
  }

  /* ---------------------------------------------------------
     Puppies filter
     --------------------------------------------------------- */
  const chips = $$('.chip[data-filter]');
  const pupGrid = $('#pups');
  const pups = $$('.pup', pupGrid || doc);
  const pupsEmpty = $('#pups-empty');
  const pupsStatus = $('#pups-status');
  chips.forEach((chip) => {
    chip.addEventListener('click', () => {
      const f = chip.dataset.filter;
      chips.forEach((c) => {
        const on = c === chip;
        c.classList.toggle('is-active', on);
        c.setAttribute('aria-pressed', String(on));
      });
      let shown = 0;
      pups.forEach((p) => {
        const show = f === 'all' || p.dataset.breed === f;
        p.hidden = !show;
        p.classList.remove('reveal', 'is-in');
        if (show) {
          shown += 1;
          if (!reduceMotion.matches) {
            p.classList.remove('is-entering');
            void p.offsetWidth;
            p.style.animationDelay = (shown - 1) * 50 + 'ms';
            p.classList.add('is-entering');
          }
        }
      });
      if (pupGrid) { pupGrid.hidden = shown === 0; pupGrid.scrollLeft = 0; }
      if (pupsEmpty) pupsEmpty.hidden = shown > 0;
      if (pupsStatus) {
        pupsStatus.textContent = shown
          ? 'Показано щенков: ' + shown
          : 'Сейчас щенков этой породы нет в наличии. Оставьте заявку — напишем, когда появится новый помёт.';
      }
    });
  });
  pups.forEach((p) => p.addEventListener('animationend', () => { p.classList.remove('is-entering'); p.style.animationDelay = ''; }));

  /* ---------------------------------------------------------
     FAQ accordion
     --------------------------------------------------------- */
  $$('.faq__q').forEach((q) => {
    q.addEventListener('click', () => {
      const open = q.getAttribute('aria-expanded') !== 'true';
      q.setAttribute('aria-expanded', String(open));
      q.closest('.faq__item').classList.toggle('is-open', open);
    });
  });

  /* ---------------------------------------------------------
     SEO text: read more
     --------------------------------------------------------- */
  const seoBtn = $('.seo__toggle');
  const seoMore = $('#seo-more');
  if (seoBtn && seoMore) {
    seoBtn.addEventListener('click', () => {
      const open = seoMore.hidden;
      seoMore.hidden = !open;
      seoBtn.setAttribute('aria-expanded', String(open));
      seoBtn.querySelector('span').textContent = open ? seoBtn.dataset.less : seoBtn.dataset.more;
      if (!open) {
        const sec = $('#o-pitomnike');
        if (sec && sec.getBoundingClientRect().top < 0) {
          sec.scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
        }
      }
    });
  }

  /* ---------------------------------------------------------
     Phone mask  +7 (XXX) XXX-XX-XX
     --------------------------------------------------------- */
  const PREFIX = '+7 (';
  function formatPhone(d) {
    if (!d) return '';
    let s = PREFIX + d.slice(0, 3);
    if (d.length > 3) s += ') ' + d.slice(3, 6);
    if (d.length > 6) s += '-' + d.slice(6, 8);
    if (d.length > 8) s += '-' + d.slice(8, 10);
    return s;
  }
  function phoneDigits(raw, prev) {
    let d = raw.replace(/\D/g, '');
    if (/^\s*\+\s*7/.test(raw)) d = d.slice(1);
    else if (d.length === 11 && /^[78]/.test(d)) d = d.slice(1);
    if (d.length > 10) {
      if (/^[78]/.test(d) && (!prev || prev.length === 0)) d = d.slice(1);
      d = d.slice(0, 10);
    }
    return d;
  }
  function digitsBefore(raw, pos) {
    let n = 0;
    for (let i = 0; i < pos && i < raw.length; i += 1) if (/\d/.test(raw[i])) n += 1;
    const seven = raw.search(/7/);
    if (/^\s*\+\s*7/.test(raw) && pos > seven) n -= 1;
    return Math.max(0, n);
  }
  function caretAfter(formatted, n) {
    if (!formatted) return 0;
    if (n <= 0) return Math.min(PREFIX.length, formatted.length);
    let c = 0;
    for (let i = PREFIX.length; i < formatted.length; i += 1) {
      if (/\d/.test(formatted[i])) { c += 1; if (c === n) return i + 1; }
    }
    return formatted.length;
  }
  function applyPhone(el, raw, caretDigits) {
    const d = phoneDigits(raw, el.dataset.d || '');
    const f = formatPhone(d);
    el.value = f || (doc.activeElement === el ? PREFIX : '');
    el.dataset.d = d;
    if (doc.activeElement === el) {
      const pos = caretDigits == null ? el.value.length : caretAfter(el.value, Math.min(caretDigits, d.length));
      try { el.setSelectionRange(pos, pos); } catch (err) { /* noop */ }
    }
  }
  $$('input[data-phone]').forEach((el) => {
    el.addEventListener('focus', () => {
      if (!el.value) { el.value = PREFIX; el.dataset.d = ''; }
      requestAnimationFrame(() => { try { el.setSelectionRange(el.value.length, el.value.length); } catch (err) { /* noop */ } });
    });
    el.addEventListener('blur', () => { if (!(el.dataset.d || '').length) el.value = ''; });
    el.addEventListener('keydown', (e) => {
      if (e.key !== 'Backspace' || el.selectionStart !== el.selectionEnd) return;
      const pos = el.selectionStart;
      const v = el.value;
      if (pos <= PREFIX.length) { e.preventDefault(); return; }
      if (/\d/.test(v[pos - 1])) return; // native deletion of a digit is fine
      // caret stands after a formatting char: delete the previous digit instead
      let j = pos - 1;
      while (j >= PREFIX.length && !/\d/.test(v[j])) j -= 1;
      e.preventDefault();
      if (j < PREFIX.length) return;
      const raw = v.slice(0, j) + v.slice(j + 1);
      applyPhone(el, raw, digitsBefore(v, j));
    });
    el.addEventListener('input', () => {
      const raw = el.value;
      const pos = el.selectionStart == null ? raw.length : el.selectionStart;
      applyPhone(el, raw, digitsBefore(raw, pos));
    });
  });

  /* ---------------------------------------------------------
     Forms: validation + success (no network)
     --------------------------------------------------------- */
  function setFieldError(field, on) {
    if (!field) return;
    const err = $('.field__err', field);
    field.classList.toggle('is-invalid', on);
    if (err) err.textContent = on ? err.dataset.err : '';
    $$('input, select, textarea', field).forEach((inp) => {
      if (inp.type === 'radio') return;
      if (on) inp.setAttribute('aria-invalid', 'true'); else inp.removeAttribute('aria-invalid');
    });
  }
  function checkForm(form) {
    const name = form.elements.name;
    const phone = form.elements.phone;
    const consent = form.elements.consent;
    const method = form.querySelector('input[name="method"]:checked');
    const checks = [
      [name, name.value.trim().length > 0],
      [phone, (phone.dataset.d || '').length === 10],
      [form.querySelector('input[name="method"]'), !!method],
      [consent, consent.checked],
    ];
    let firstBad = null;
    checks.forEach(([el, ok]) => {
      setFieldError(el.closest('.field'), !ok);
      if (!ok && !firstBad) firstBad = el;
    });
    return { ok: !firstBad, firstBad, name: name.value.trim(), method: method ? method.value : '' };
  }
  function liveRevalidate(form) {
    form.addEventListener('input', (e) => {
      const field = e.target.closest('.field');
      if (field && field.classList.contains('is-invalid')) checkFieldQuiet(form, field);
    });
    form.addEventListener('change', (e) => {
      const field = e.target.closest('.field');
      if (field && field.classList.contains('is-invalid')) checkFieldQuiet(form, field);
      if (e.target.tagName === 'SELECT') e.target.classList.toggle('is-empty', !e.target.value);
    });
  }
  function checkFieldQuiet(form, field) {
    const name = form.elements.name;
    const phone = form.elements.phone;
    let ok = true;
    if (field.contains(name)) ok = name.value.trim().length > 0;
    else if (field.contains(phone)) ok = (phone.dataset.d || '').length === 10;
    else if (field.querySelector('input[name="method"]')) ok = !!form.querySelector('input[name="method"]:checked');
    else if (field.contains(form.elements.consent)) ok = form.elements.consent.checked;
    if (ok) setFieldError(field, false);
  }
  function resetForm(form) {
    form.reset();
    $$('.field', form).forEach((f) => setFieldError(f, false));
    $$('input[data-phone]', form).forEach((p) => { p.dataset.d = ''; });
    $$('select', form).forEach((s) => s.classList.add('is-empty'));
    const btn = $('.form__submit', form);
    if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label; }
  }
  function submitWith(form, done) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const res = checkForm(form);
      if (!res.ok) {
        res.firstBad.focus();
        return;
      }
      const btn = $('.form__submit', form);
      btn.disabled = true;
      btn.textContent = btn.dataset.busy;
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = btn.dataset.label;
        done(res);
      }, 900);
    });
    liveRevalidate(form);
  }
  $$('select').forEach((s) => s.classList.toggle('is-empty', !s.value));

  // Final form
  const leadForm = $('#lead-form');
  const leadSuccess = $('#final-success');
  if (leadForm && leadSuccess) {
    submitWith(leadForm, ({ name, method }) => {
      const tail = 'в течение 15 минут, а если сейчас поздний вечер — утром. Пока ждёте, почитайте, что говорят владельцы наших щенков.';
      $('[data-success-text]', leadSuccess).textContent = method === 'call'
        ? 'Спасибо, ' + name + '. Куратор позвонит вам ' + tail
        : 'Спасибо, ' + name + '. Куратор напишет вам в ' + method + ' ' + tail;
      leadForm.hidden = true;
      leadSuccess.hidden = false;
      leadSuccess.focus();
    });
  }

  /* ---------------------------------------------------------
     «Узнать цену» modal
     --------------------------------------------------------- */
  const modal = $('#price-modal');
  if (modal && typeof modal.showModal === 'function') {
    const form = $('#price-form', modal);
    const formView = $('.modal__form-view', modal);
    const success = $('[data-pm-success]', modal);
    const title = $('#pm-title', modal);
    const sub = $('#pm-sub', modal);
    const pic = $('[data-pm-pic]', modal);
    const breedField = $('[data-breed-field]', modal);
    const DEFAULT_TITLE = title.textContent;
    const DEFAULT_SUB = sub.textContent;

    function openPrice(data) {
      resetForm(form);
      formView.hidden = false;
      success.hidden = true;
      if (data.name) {
        title.textContent = 'Узнать цену: ' + data.name;
        sub.textContent = (data.meta ? data.meta + '. ' : '') + 'Пришлём цену, видео и условия брони в удобный мессенджер. Это ни к чему не обязывает.';
        form.elements.puppy.value = data.name + (data.meta ? ' (' + data.meta + ')' : '');
        breedField.hidden = true;
        pic.style.backgroundImage = data.img ? 'url("' + data.img + '")' : '';
        pic.style.backgroundColor = data.tone || '';
        pic.classList.toggle('has-img', !!data.img);
      } else {
        title.textContent = DEFAULT_TITLE;
        sub.textContent = DEFAULT_SUB;
        form.elements.puppy.value = '';
        breedField.hidden = false;
        pic.style.backgroundImage = '';
        pic.style.backgroundColor = '';
        pic.classList.remove('has-img');
      }
      modal.showModal();
      html.classList.add('is-locked');
      const first = form.elements.name;
      requestAnimationFrame(() => first.focus());
    }

    doc.addEventListener('click', (e) => {
      const trigger = e.target.closest('[data-open-price]');
      if (!trigger) return;
      e.preventDefault();
      openPrice({
        name: trigger.dataset.name || '',
        meta: trigger.dataset.meta || '',
        img: trigger.dataset.img || '',
        tone: trigger.dataset.tone || '',
      });
    });

    $$('[data-close-modal]', modal).forEach((b) => b.addEventListener('click', () => modal.close()));
    // Backdrop click (only when the press started on the backdrop too)
    let downOnBackdrop = false;
    modal.addEventListener('pointerdown', (e) => { downOnBackdrop = e.target === modal; });
    modal.addEventListener('click', (e) => { if (e.target === modal && downOnBackdrop) modal.close(); });
    modal.addEventListener('close', () => {
      if (!menu || menu.hidden) html.classList.remove('is-locked');
      if (toast && toast.parentElement !== doc.body) doc.body.appendChild(toast);
    });

    submitWith(form, ({ name, method }) => {
      $('[data-pm-success-title]', success).textContent = 'Спасибо, ' + name;
      $('[data-pm-success-text]', success).textContent = method === 'call'
        ? 'Куратор позвонит вам в течение 15 минут. Ночью — утром, после 9:00.'
        : 'Куратор пришлёт цену и видео в ' + method + ' в течение 15 минут. Ночью — утром, после 9:00.';
      formView.hidden = true;
      success.hidden = false;
      success.focus();
    });
  }

  /* ---------------------------------------------------------
     Escape closes overlays (the <dialog> handles its own Esc)
     --------------------------------------------------------- */
  doc.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (modal && modal.open) return;
    if (menu && !menu.hidden) { closeMenu(true); return; }
    if (ddIsOpen()) { setDD(false); ddBtn.focus(); return; }
    if (tipChip && tipChip.classList.contains('is-open')) { setTip(false); tipBtn.focus(); }
  });

  /* ---------------------------------------------------------
     Gentle reveal on scroll (skipped for reduced motion)
     --------------------------------------------------------- */
  if ('IntersectionObserver' in window && !reduceMotion.matches) {
    const wide = window.innerWidth >= 640;
    const selectors = [
      '.sec-head', '.stats > li', '.step', '.parents > *', '.podbor > *', '.delivery > *',
      '.duo > *', '.rev-top > *', '.post', '.faq__item', '.seo', '.final',
    ];
    if (wide) selectors.push('.breed', '.pup', '.benefit', '.review');
    const targets = $$(selectors.join(','));
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const el = entry.target;
        if (entry.isIntersecting || entry.boundingClientRect.bottom < 0) {
          el.classList.add('is-in');
          io.unobserve(el);
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -6% 0px' });
    targets.forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) return; // already on screen: leave as is
      const siblings = el.parentElement ? Array.from(el.parentElement.children) : [];
      const idx = siblings.indexOf(el);
      el.style.transitionDelay = (idx > 0 ? (idx % 4) * 70 : 0) + 'ms';
      el.classList.add('reveal');
      el.addEventListener('transitionend', function done(ev) {
        if (ev.target !== el || ev.propertyName !== 'opacity') return;
        el.classList.remove('reveal', 'is-in');
        el.style.transitionDelay = '';
        el.removeEventListener('transitionend', done);
      });
      io.observe(el);
    });
    html.classList.add('reveal-ready');
  }
})();
