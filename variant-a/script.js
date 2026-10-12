/* Puppy House — Вариант A «Бенто чистый». Ванильный JS, без библиотек. */
(() => {
  'use strict';

  const d = document;
  const root = d.documentElement;
  root.classList.add('js');

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canHover = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  const IMG_BASE = '../assets/img/';
  const TOAST_TEXT = 'Раздел появится на следующем этапе';
  const CONTACT_LABEL = { telegram: 'Telegram', whatsapp: 'WhatsApp', max: 'MAX', call: 'звонок' };
  const ERR = {
    name: 'Напишите, как к вам обращаться',
    phone: 'Проверьте номер: после +7 нужно 10 цифр',
    contact: 'Выберите, куда вам написать',
    consent: 'Без согласия на обработку данных мы не сможем отправить заявку'
  };

  const $ = (sel, ctx = d) => ctx.querySelector(sel);
  const $$ = (sel, ctx = d) => Array.from(ctx.querySelectorAll(sel));

  /* ---------- блокировка прокрутки ---------- */
  const locks = new Set();
  function lockScroll(key, on) {
    if (on) locks.add(key); else locks.delete(key);
    root.classList.toggle('is-locked', locks.size > 0);
  }

  /* ---------- тост ---------- */
  const toast = $('[data-toast]');
  let toastTimer;
  function showToast(text = TOAST_TEXT) {
    if (!toast) return;
    toast.textContent = text;
    toast.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-on'), 2600);
  }

  // Внутренние ссылки на ещё не свёрстанные страницы и ссылки-заглушки;
  // якоря внутри главной — плавная прокрутка (без CSS scroll-behavior, чтобы не мешать программной прокрутке)
  d.addEventListener('click', (e) => {
    const a = e.target.closest('a');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    const isInternalPage = href.startsWith('/') && !href.startsWith('//');
    if (a.hasAttribute('data-soon') || isInternalPage) {
      e.preventDefault();
      showToast();
      return;
    }
    if (href.length > 1 && href.startsWith('#')) {
      const target = d.getElementById(decodeURIComponent(href.slice(1)));
      if (!target) return;
      e.preventDefault();
      if (href === '#top') window.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' });
      else target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      if (history.replaceState) history.replaceState(null, '', href);
    }
  });

  /* ---------- шапка: тень при прокрутке ---------- */
  const hdr = $('[data-hdr]');
  const onScroll = () => hdr && hdr.classList.toggle('is-scrolled', window.scrollY > 8);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  /* ---------- выпадающее меню «Породы» ---------- */
  const ddWrap = $('[data-dd]');
  const ddBtn = ddWrap && $('.nav__dd-btn', ddWrap);
  const ddPanel = ddWrap && $('#dd-breeds');
  let ddTimer;
  function setDropdown(open) {
    if (!ddBtn) return;
    ddBtn.setAttribute('aria-expanded', String(open));
    ddPanel.hidden = !open;
  }
  const ddIsOpen = () => ddBtn && ddBtn.getAttribute('aria-expanded') === 'true';
  if (ddBtn) {
    ddBtn.addEventListener('click', (e) => {
      // клик мышью на устройстве с ховером — только открывает (ховер уже мог открыть)
      if (canHover && e.detail > 0) { setDropdown(true); return; }
      setDropdown(!ddIsOpen());
    });
    if (canHover) {
      ddWrap.addEventListener('mouseenter', () => { clearTimeout(ddTimer); setDropdown(true); });
      ddWrap.addEventListener('mouseleave', () => { ddTimer = setTimeout(() => setDropdown(false), 200); });
    }
    ddWrap.addEventListener('focusout', (e) => {
      if (!ddWrap.contains(e.relatedTarget)) setDropdown(false);
    });
    d.addEventListener('click', (e) => { if (ddIsOpen() && !ddWrap.contains(e.target)) setDropdown(false); });
  }

  /* ---------- мобильное меню ---------- */
  const burger = $('[data-burger]');
  const menu = $('#mmenu');
  const menuIsOpen = () => menu && !menu.hidden;

  function openMenu() {
    if (!menu) return;
    menu.hidden = false;
    burger.setAttribute('aria-expanded', 'true');
    lockScroll('menu', true);
    requestAnimationFrame(() => menu.classList.add('is-open'));
    const closeBtn = $('[data-menu-close]', menu);
    closeBtn && closeBtn.focus();
  }
  function closeMenu(returnFocus = true) {
    if (!menuIsOpen()) return;
    menu.classList.remove('is-open');
    burger.setAttribute('aria-expanded', 'false');
    lockScroll('menu', false);
    const finish = () => { menu.hidden = true; };
    if (reduceMotion) finish(); else setTimeout(finish, 260);
    if (returnFocus) burger.focus();
  }
  if (burger && menu) {
    burger.addEventListener('click', openMenu);
    $('[data-menu-close]', menu).addEventListener('click', () => closeMenu());
    // Логотип в меню ведёт на #top — закрываем меню
    $$('[data-menu-link]', menu).forEach((a) => a.addEventListener('click', () => closeMenu(false)));
    // Аккордеон «Породы»
    const acc = $('.mmenu__acc', menu);
    const sub = $('#mm-breeds');
    acc.addEventListener('click', () => {
      const open = acc.getAttribute('aria-expanded') !== 'true';
      acc.setAttribute('aria-expanded', String(open));
      sub.hidden = !open;
    });
    // Ловушка фокуса
    menu.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const items = $$('a[href], button:not([disabled])', menu).filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && d.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    // При переходе на десктоп — закрыть
    window.matchMedia('(min-width: 1100px)').addEventListener('change', (m) => { if (m.matches) closeMenu(false); });
  }

  /* ---------- подсказка у чипа ---------- */
  $$('.tip').forEach((tip) => {
    const btn = $('.tip__btn', tip);
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = !tip.classList.contains('is-open');
      tip.classList.toggle('is-open', open);
      btn.setAttribute('aria-expanded', String(open));
    });
    d.addEventListener('click', (e) => {
      if (!tip.contains(e.target)) { tip.classList.remove('is-open'); btn.setAttribute('aria-expanded', 'false'); }
    });
  });

  /* ---------- Esc ---------- */
  d.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (modal && modal.open) return; // диалог закрывается сам (событие cancel)
    if (menuIsOpen()) { closeMenu(); return; }
    if (ddIsOpen()) { setDropdown(false); ddBtn.focus(); return; }
    $$('.tip.is-open').forEach((t) => { t.classList.remove('is-open'); $('.tip__btn', t).setAttribute('aria-expanded', 'false'); });
  });

  /* ---------- маска телефона +7 ---------- */
  function phoneDigits(value) {
    const s = String(value || '').trim();
    let digits;
    if (s.startsWith('+7')) {
      digits = s.slice(2).replace(/\D/g, '');
    } else {
      digits = s.replace(/\D/g, '');
      if (digits[0] === '7' || digits[0] === '8') digits = digits.slice(1);
    }
    if (digits.length > 10 && (digits[0] === '7' || digits[0] === '8')) digits = digits.slice(1);
    return digits.slice(0, 10);
  }
  function formatPhone(digits) {
    if (!digits) return '+7 ';
    let out = '+7 (' + digits.slice(0, 3);
    if (digits.length > 3) out += ') ' + digits.slice(3, 6);
    if (digits.length > 6) out += '-' + digits.slice(6, 8);
    if (digits.length > 8) out += '-' + digits.slice(8, 10);
    return out;
  }
  $$('[data-phone]').forEach((input) => {
    input.addEventListener('focus', () => { if (!input.value) input.value = '+7 '; });
    input.addEventListener('blur', () => { if (!phoneDigits(input.value)) input.value = ''; });
    input.addEventListener('input', () => {
      input.value = formatPhone(phoneDigits(input.value));
      const end = input.value.length;
      try { input.setSelectionRange(end, end); } catch (_) { /* старые браузеры */ }
    });
    input.addEventListener('keydown', (e) => {
      // не даём стереть префикс «+7»
      if ((e.key === 'Backspace') && input.selectionStart <= 3 && input.selectionEnd <= 3) e.preventDefault();
    });
  });

  /* ---------- валидация форм ---------- */
  function setError(form, field, msg) {
    const errEl = $('#' + form.dataset.prefix + '-' + field + '-err');
    const target = field === 'contact' ? $('.seg', form) : form.elements[field];
    if (errEl) { errEl.textContent = msg || ''; errEl.hidden = !msg; }
    if (target) {
      if (msg) target.setAttribute('aria-invalid', 'true'); else target.removeAttribute('aria-invalid');
    }
  }
  function validate(form) {
    const f = form.elements;
    const checks = [
      ['name', !f.name.value.trim(), f.name],
      ['phone', phoneDigits(f.phone.value).length !== 10, f.phone],
      ['contact', !form.querySelector('input[name="contact"]:checked'), form.querySelector('input[name="contact"]')],
      ['consent', !f.consent.checked, f.consent]
    ];
    let firstBad = null;
    checks.forEach(([key, bad, el]) => {
      setError(form, key, bad ? ERR[key] : '');
      if (bad && !firstBad) firstBad = el;
    });
    if (firstBad) firstBad.focus();
    return !firstBad;
  }
  function clearForm(form) {
    form.reset();
    ['name', 'phone', 'contact', 'consent'].forEach((k) => setError(form, k, ''));
    const btn = $('[data-submit]', form);
    btn.disabled = false;
    btn.textContent = btn.dataset.label;
  }
  function bindLiveClear(form) {
    form.addEventListener('input', (e) => {
      const n = e.target.name;
      if (n === 'name' && e.target.value.trim()) setError(form, 'name', '');
      if (n === 'phone' && phoneDigits(e.target.value).length === 10) setError(form, 'phone', '');
    });
    form.addEventListener('change', (e) => {
      const n = e.target.name;
      if (n === 'contact') setError(form, 'contact', '');
      if (n === 'consent' && e.target.checked) setError(form, 'consent', '');
    });
  }
  function fakeSend(form, done) {
    const btn = $('[data-submit]', form);
    btn.disabled = true;
    btn.textContent = 'Отправляем…';
    setTimeout(() => { btn.disabled = false; btn.textContent = btn.dataset.label; done(); }, reduceMotion ? 300 : 900);
  }
  function contactOf(form) {
    const c = form.querySelector('input[name="contact"]:checked');
    return c ? c.value : 'telegram';
  }

  /* ---------- модалка «Узнать цену» ---------- */
  const modal = $('#price-modal');
  const pForm = $('#price-form');
  if (modal && pForm) {
    pForm.dataset.prefix = 'pm';
    bindLiveClear(pForm);
    const viewForm = $('[data-view="form"]', modal);
    const viewDone = $('[data-view="done"]', modal);
    const title = $('#pm-title');
    const sub = $('#pm-sub');
    const thumb = $('[data-pm-thumb]', modal);
    const thumbImg = $('img', thumb);
    const breedField = $('[data-pm-breed]', modal);
    const doneTitle = $('#pm-done-title');
    const doneText = $('#pm-done-text');

    const openModal = (pup) => {
      clearForm(pForm);
      viewForm.hidden = false;
      viewDone.hidden = true;
      modal.setAttribute('aria-labelledby', 'pm-title');
      modal.setAttribute('aria-describedby', 'pm-sub');
      if (pup) {
        title.textContent = 'Узнать цену: ' + pup.name;
        sub.textContent = pup.desc + '. Пришлём цену, видео и условия брони в удобный мессенджер. Это ни к чему не обязывает.';
        thumbImg.src = IMG_BASE + pup.img;
        thumbImg.alt = 'Щенок ' + pup.name;
        thumb.hidden = false;
        breedField.hidden = true;
        pForm.elements.puppy.value = pup.name;
      } else {
        title.textContent = 'Узнать цену щенка';
        sub.textContent = 'Расскажите, какая порода интересует, — пришлём щенков в наличии с ценами и видео.';
        thumb.hidden = true;
        breedField.hidden = false;
        pForm.elements.puppy.value = '';
      }
      if (typeof modal.showModal === 'function') modal.showModal(); else modal.setAttribute('open', '');
      lockScroll('modal', true);
      setTimeout(() => pForm.elements.name.focus(), 30);
    };

    d.addEventListener('click', (e) => {
      const trigger = e.target.closest('[data-open-modal]');
      if (!trigger) return;
      e.preventDefault();
      const card = trigger.closest('[data-pup]');
      if (menuIsOpen()) closeMenu(false);
      openModal(card ? { name: card.dataset.name, desc: card.dataset.desc, img: card.dataset.img } : null);
    });

    const closeModal = () => { if (modal.open) modal.close(); };
    modal.addEventListener('close', () => lockScroll('modal', false));
    $$('[data-close-modal]', modal).forEach((b) => b.addEventListener('click', closeModal));
    // клик по подложке
    modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

    pForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!validate(pForm)) return;
      fakeSend(pForm, () => {
        const name = pForm.elements.name.value.trim();
        const c = contactOf(pForm);
        doneTitle.textContent = 'Спасибо, ' + name;
        doneText.textContent = c === 'call'
          ? 'Куратор позвонит вам и расскажет о цене и условиях брони в течение 15 минут. Ночью — утром, после 9:00.'
          : 'Куратор пришлёт цену и видео в ' + CONTACT_LABEL[c] + ' в течение 15 минут. Ночью — утром, после 9:00.';
        viewForm.hidden = true;
        viewDone.hidden = false;
        modal.setAttribute('aria-labelledby', 'pm-done-title');
        modal.setAttribute('aria-describedby', 'pm-done-text');
        doneTitle.focus();
      });
    });
  }

  /* ---------- финальная форма ---------- */
  const lForm = $('#lead-form');
  if (lForm) {
    lForm.dataset.prefix = 'lf';
    bindLiveClear(lForm);
    const done = $('[data-done]');
    const doneText = $('[data-done-text]');
    lForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!validate(lForm)) return;
      fakeSend(lForm, () => {
        const name = lForm.elements.name.value.trim();
        const c = contactOf(lForm);
        const how = c === 'call' ? 'позвонит вам' : 'напишет вам в ' + CONTACT_LABEL[c];
        doneText.textContent = 'Спасибо, ' + name + '. Куратор ' + how + ' в течение 15 минут, а если сейчас поздний вечер — утром. Пока ждёте, почитайте, что говорят владельцы наших щенков.';
        lForm.hidden = true;
        done.hidden = false;
        done.focus();
      });
    });
  }

  /* ---------- фильтр щенков ---------- */
  const grid = $('[data-pups]');
  if (grid) {
    const chips = $$('[data-filter]');
    const items = $$('.pups__item', grid);
    const more = $('[data-more]', grid);
    const empty = $('[data-empty]');
    let visible = items.length;

    // Плитка «Весь каталог» закрывает пустые ячейки последнего ряда; в карусели — всегда в конце
    const fitMore = () => {
      const cs = getComputedStyle(grid);
      if (cs.display !== 'grid') { more.hidden = visible === 0; more.style.gridColumn = ''; return; }
      const cols = cs.gridTemplateColumns.split(' ').filter(Boolean).length || 1;
      const rest = visible % cols;
      more.hidden = visible === 0 || rest === 0;
      more.style.gridColumn = rest ? 'span ' + (cols - rest) : '';
    };

    const apply = (value) => {
      visible = 0;
      chips.forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.filter === value)));
      items.forEach((li) => {
        const show = value === 'all' || li.dataset.breed === value;
        li.hidden = !show;
        if (show) visible++;
      });
      empty.hidden = visible > 0;
      fitMore();
      grid.scrollLeft = 0;
    };
    chips.forEach((c) => c.addEventListener('click', () => apply(c.dataset.filter)));
    let rt;
    window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(fitMore, 120); });
    fitMore();
  }

  /* ---------- FAQ ---------- */
  $$('.faq__btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.faq__item');
      const open = btn.getAttribute('aria-expanded') !== 'true';
      btn.setAttribute('aria-expanded', String(open));
      item.classList.toggle('is-open', open);
    });
  });

  /* ---------- SEO-текст ---------- */
  const seoBtn = $('[data-seo-toggle]');
  if (seoBtn) {
    const more = $('#' + seoBtn.getAttribute('aria-controls'));
    const label = $('[data-seo-label]', seoBtn);
    seoBtn.addEventListener('click', () => {
      const open = seoBtn.getAttribute('aria-expanded') !== 'true';
      seoBtn.setAttribute('aria-expanded', String(open));
      more.hidden = !open;
      label.textContent = open ? 'Свернуть' : 'Читать полностью';
      if (!open) {
        const sec = seoBtn.closest('.section');
        if (sec && sec.getBoundingClientRect().top < 0) sec.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      }
    });
  }

  /* ---------- появление при скролле ---------- */
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const isScroller = (el) => {
      const p = el.parentElement && el.parentElement.closest('.pups, .reviews, .posts');
      return p && getComputedStyle(p).overflowX !== 'visible';
    };
    const targets = $$([
      'main .section .sec-head',
      '.breeds > li',
      '.pups > li',
      '.ben > .tile',
      '.steps > .tile',
      '.par > .tile', '.par__facts > .tile',
      '.pick > .tile',
      '.dost > .tile',
      '.duo > .tile',
      '.rev-top > .tile', '.ratings > .tile',
      '.reviews > li',
      '.posts > li',
      '.faq__aside', '.faq__list',
      '.seo', '.lead-form > .tile',
      '.footer__tile'
    ].join(',')).filter((el) => !isScroller(el));

    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const siblings = el.parentElement ? Array.from(el.parentElement.children) : [];
        const idx = Math.max(0, siblings.indexOf(el));
        el.style.transitionDelay = Math.min(idx % 4, 3) * 70 + 'ms';
        el.classList.add('is-in');
        io.unobserve(el);
        // после анимации возвращаем элементу собственные переходы (ховер и т. п.)
        setTimeout(() => { el.classList.remove('rv', 'is-in'); el.style.transitionDelay = ''; }, 900);
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.08 });

    targets.forEach((el) => {
      // элементы уже на экране — без анимации
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight * 0.9) return;
      el.classList.add('rv');
      io.observe(el);
    });

    // печать и сохранение страницы — показать всё сразу
    window.addEventListener('beforeprint', () => {
      $$('.rv').forEach((el) => { el.classList.remove('rv', 'is-in'); io.unobserve(el); });
    });
  }
})();
