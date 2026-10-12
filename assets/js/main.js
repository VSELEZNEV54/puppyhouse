/* Puppy House — главная. Ванильный JS, без библиотек. */
(() => {
  'use strict';

  const d = document;
  const root = d.documentElement;
  root.classList.add('js');

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canHover = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  const IMG_BASE = 'assets/img/';
  const TOAST_TEXT = 'Раздел появится на следующем этапе';
  const CONTACT_LABEL = { telegram: 'Telegram', whatsapp: 'WhatsApp', call: 'звонок' };
  const ERR = {
    name: 'Напишите, как к вам обращаться',
    phone: 'Проверьте номер: после +7 нужно 10 цифр',
    contact: 'Выберите, куда вам написать',
    consent: 'Без согласия на обработку данных мы не сможем отправить заявку'
  };

  const $ = (sel, ctx = d) => ctx.querySelector(sel);
  const $$ = (sel, ctx = d) => Array.from(ctx.querySelectorAll(sel));
  const scrollBehavior = reduceMotion ? 'auto' : 'smooth';

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
    // поверх открытой модалки тост должен быть в её верхнем слое
    const host = modal && modal.open ? modal : d.body;
    if (toast.parentElement !== host) host.appendChild(toast);
    toast.textContent = text;
    toast.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-on'), 2600);
  }

  // Несвёрстанные внутренние страницы → тост; якоря главной → плавная прокрутка
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
      if (href === '#top') window.scrollTo({ top: 0, behavior: scrollBehavior });
      else target.scrollIntoView({ behavior: scrollBehavior, block: 'start' });
      if (history.replaceState) history.replaceState(null, '', href);
      // фокус переезжает к цели — следующий Tab продолжается оттуда (ссылка «Перейти к содержанию», «Смотреть щенков»)
      if (href !== '#top') {
        if (!target.matches('a[href], button, input, select, textarea, [tabindex]')) {
          target.setAttribute('tabindex', '-1');
          target.setAttribute('data-anchor-focus', '');
        }
        target.focus({ preventScroll: true });
      }
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
  const ddIsOpen = () => !!ddBtn && ddBtn.getAttribute('aria-expanded') === 'true';
  if (ddBtn) {
    ddBtn.addEventListener('click', (e) => {
      // клик мышью на устройстве с ховером только открывает (ховер мог открыть раньше)
      if (canHover && e.detail > 0) { setDropdown(true); return; }
      setDropdown(!ddIsOpen());
    });
    ddBtn.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setDropdown(true);
        const first = $('a', ddPanel);
        first && first.focus();
      }
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
  const menuIsOpen = () => !!menu && !menu.hidden;

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
    $$('[data-menu-link]', menu).forEach((a) => a.addEventListener('click', () => closeMenu(false)));
    // ссылки на несвёрстанные страницы: тост поверх меню, меню остаётся открытым
    const acc = $('.mmenu__acc', menu);
    const sub = $('#mm-breeds');
    acc.addEventListener('click', () => {
      const open = acc.getAttribute('aria-expanded') !== 'true';
      acc.setAttribute('aria-expanded', String(open));
      sub.hidden = !open;
    });
    // ловушка фокуса
    menu.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const items = $$('a[href], button:not([disabled])', menu).filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && d.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    window.matchMedia('(min-width: 1100px)').addEventListener('change', (m) => { if (m.matches) closeMenu(false); });
  }

  /* ---------- Esc ---------- */
  d.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (modal && modal.open) return; // <dialog> закрывается сам
    if (menuIsOpen()) { closeMenu(); return; }
    if (ddIsOpen()) { setDropdown(false); ddBtn.focus(); }
  });

  /* ---------- маска телефона +7 (XXX) XXX-XX-XX ---------- */
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
      // префикс «+7» не стирается
      if (e.key === 'Backspace' && input.selectionStart <= 3 && input.selectionEnd <= 3) e.preventDefault();
    });
  });

  /* ---------- валидация ---------- */
  function setError(form, field, msg) {
    const errEl = $('#' + form.dataset.prefix + '-' + field + '-err');
    if (errEl) { errEl.textContent = msg || ''; errEl.hidden = !msg; }
    const targets = field === 'contact' ? $$('input[name="contact"]', form) : [form.elements[field]];
    targets.forEach((t) => {
      if (!t) return;
      if (msg) t.setAttribute('aria-invalid', 'true'); else t.removeAttribute('aria-invalid');
    });
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
  const contactOf = (form) => {
    const c = form.querySelector('input[name="contact"]:checked');
    return c ? c.value : 'telegram';
  };

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
    let returnTo = null;

    const openModal = (pup, opener) => {
      returnTo = opener;
      clearForm(pForm);
      viewForm.hidden = false;
      viewDone.hidden = true;
      modal.setAttribute('aria-labelledby', 'pm-title');
      modal.setAttribute('aria-describedby', 'pm-sub');
      if (pup) {
        title.textContent = 'Узнать цену: ' + pup.name;
        sub.textContent = pup.desc;
        thumbImg.src = IMG_BASE + pup.img;
        thumbImg.alt = '';
        thumb.style.setProperty('--tone', pup.tone || '');
        thumb.classList.toggle('is-studio', pup.img.startsWith('studio-'));
        thumb.hidden = false;
        breedField.hidden = true;
        pForm.elements.puppy.value = pup.name;
      } else {
        title.textContent = 'Узнать цену щенка';
        sub.textContent = 'Пришлём щенков в наличии с ценами и видео';
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
      // кнопка из бургер-меню исчезнет вместе с меню — фокус вернём на бургер
      let opener = trigger;
      if (menuIsOpen() && menu.contains(trigger)) { closeMenu(false); opener = burger; }
      const pup = card ? {
        name: card.dataset.name,
        desc: card.dataset.desc,
        img: card.dataset.img,
        tone: getComputedStyle(card).getPropertyValue('--tone').trim()
      } : null;
      openModal(pup, opener);
    });

    const closeModal = () => { if (modal.open) modal.close(); };
    modal.addEventListener('close', () => {
      lockScroll('modal', false);
      if (toast && toast.parentElement !== d.body) d.body.appendChild(toast);
      const target = returnTo;
      returnTo = null;
      if (target && target.isConnected && target.offsetParent !== null) target.focus();
    });
    $$('[data-close-modal]', modal).forEach((b) => b.addEventListener('click', closeModal));
    // ловушка фокуса: Tab по кругу внутри окна (браузер иначе уводит фокус в свою панель)
    modal.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const items = $$('a[href], button:not([disabled]), input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])', modal)
        .filter((el) => el.offsetParent !== null && !(el.type === 'radio' && !el.checked && $$('input[name="' + el.name + '"]:checked', modal).length));
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && (d.activeElement === first || !modal.contains(d.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    // клик по подложке (только если и нажали на подложке)
    let downOnBackdrop = false;
    modal.addEventListener('pointerdown', (e) => { downOnBackdrop = e.target === modal; });
    modal.addEventListener('click', (e) => { if (e.target === modal && downOnBackdrop) closeModal(); });

    pForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!validate(pForm)) return;
      fakeSend(pForm, () => {
        const name = pForm.elements.name.value.trim();
        const c = contactOf(pForm);
        doneTitle.textContent = 'Спасибо, ' + name;
        doneText.textContent = c === 'call'
          ? 'Куратор позвонит вам в течение 15 минут. Ночью — утром, после 9:00.'
          : 'Куратор пришлёт цену и видео в ' + CONTACT_LABEL[c] + ' в течение 15 минут. Ночью — утром, после 9:00.';
        viewForm.hidden = true;
        viewDone.hidden = false;
        modal.setAttribute('aria-labelledby', 'pm-done-title');
        modal.setAttribute('aria-describedby', 'pm-done-text');
        doneTitle.focus();
      });
    });
  }

  /* ---------- форма заявки внизу ---------- */
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
        const c = contactOf(lForm);
        doneText.textContent = c === 'call' ? 'Спасибо! Позвоним в течение 15 минут' : 'Спасибо! Напишем в течение 15 минут';
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
    const empty = $('[data-empty]');
    const status = $('[data-pups-status]');
    const more = $('[data-more]', grid);
    let visible = items.length;
    // плитка «Весь каталог» закрывает пустые ячейки последнего ряда; в ленте — всегда в конце
    const fitMore = () => {
      if (!more) return;
      const cs = getComputedStyle(grid);
      if (cs.display !== 'grid') { more.hidden = visible === 0; more.style.gridColumn = ''; return; }
      const cols = cs.gridTemplateColumns.split(' ').filter(Boolean).length || 1;
      const rest = visible % cols;
      more.hidden = visible === 0 || rest === 0;
      more.style.gridColumn = rest ? 'span ' + (cols - rest) : '';
    };
    let rt;
    window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(fitMore, 120); });
    const apply = (value) => {
      visible = 0;
      chips.forEach((c) => c.setAttribute('aria-pressed', String(c.dataset.filter === value)));
      items.forEach((li) => {
        const show = value === 'all' || li.dataset.breed === value;
        li.hidden = !show;
        if (show) visible++;
      });
      grid.hidden = visible === 0;
      if (empty) empty.hidden = visible > 0;
      if (status) status.textContent = 'Показано щенков: ' + visible;
      fitMore();
      grid.scrollLeft = 0;
    };
    chips.forEach((c) => c.addEventListener('click', () => apply(c.dataset.filter)));
    fitMore();
  }

  /* ---------- избранное ---------- */
  $$('.fav').forEach((btn) => {
    btn.addEventListener('click', () => {
      btn.setAttribute('aria-pressed', String(btn.getAttribute('aria-pressed') !== 'true'));
    });
  });

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
    const box = seoBtn.closest('.seo');
    const more = $('#' + seoBtn.getAttribute('aria-controls'));
    const label = $('[data-seo-label]', seoBtn);
    seoBtn.addEventListener('click', () => {
      const open = seoBtn.getAttribute('aria-expanded') !== 'true';
      seoBtn.setAttribute('aria-expanded', String(open));
      more.hidden = !open;
      box.classList.toggle('is-open', open);
      label.textContent = open ? 'Свернуть' : 'Читать полностью';
      if (!open && box.getBoundingClientRect().top < 0) box.scrollIntoView({ behavior: scrollBehavior, block: 'start' });
    });
  }

  /* ---------- липкая панель: после того как кнопки первого экрана ушли из вида ---------- */
  const mbar = $('[data-mbar]');
  const heroCtas = $('[data-hero-ctas]');
  const leadSection = $('#zayavka');
  if (mbar && heroCtas && 'IntersectionObserver' in window) {
    let ctasGone = false;
    let leadVisible = false;
    const sync = () => mbar.classList.toggle('is-on', ctasGone && !leadVisible);
    new IntersectionObserver(([entry]) => {
      ctasGone = !entry.isIntersecting && entry.boundingClientRect.top < 0;
      sync();
    }).observe(heroCtas);
    if (leadSection) {
      // над формой заявки панель не нужна — она закрывала бы кнопку отправки
      new IntersectionObserver(([entry]) => { leadVisible = entry.isIntersecting; sync(); }, { threshold: 0.15 }).observe(leadSection);
    }
  }

  /* ---------- ленты на мобиле: фото дальних карточек грузим, когда лента подъехала к экрану ----------
     (lazy-загрузка браузера не видит карточки далеко справа, и при свайпе они появлялись бы пустыми) */
  if ('IntersectionObserver' in window) {
    const stripIO = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const strip = entry.target;
        if (getComputedStyle(strip).overflowX === 'visible') return; // на десктопе это обычная сетка
        $$('img[loading="lazy"]', strip).forEach((img) => { img.loading = 'eager'; });
        stripIO.unobserve(strip);
      });
    }, { rootMargin: '600px 0px' });
    $$('.scroller').forEach((strip) => stripIO.observe(strip));
  }

  /* ---------- мягкое появление при скролле ---------- */
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const inScroller = (el) => {
      const p = el.parentElement;
      return p && getComputedStyle(p).overflowX !== 'visible';
    };
    const targets = $$([
      'main .section .sec-head',
      '.breeds > li', '.pups > li', '.help > li', '.steps > li', '.bento > li',
      '.ratings > li', '.reviews > li', '.faq__aside', '.faq__list', '.seo', '.lead', '.footer__tile'
    ].join(',')).filter((el) => !inScroller(el));

    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const siblings = el.parentElement ? Array.from(el.parentElement.children) : [];
        const idx = Math.max(0, siblings.indexOf(el));
        el.style.transitionDelay = Math.min(idx % 4, 3) * 70 + 'ms';
        el.classList.add('is-in');
        io.unobserve(el);
        // после анимации — вернуть элементу собственные переходы (ховер)
        setTimeout(() => { el.classList.remove('rv', 'is-in'); el.style.transitionDelay = ''; }, 900);
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.08 });

    targets.forEach((el) => {
      if (el.getBoundingClientRect().top < window.innerHeight * 0.9) return; // уже на экране
      el.classList.add('rv');
      io.observe(el);
    });
    window.addEventListener('beforeprint', () => {
      $$('.rv').forEach((el) => { el.classList.remove('rv', 'is-in'); io.unobserve(el); });
    });
  }
})();
