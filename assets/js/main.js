/* домщенков.рф — общий скрипт всех страниц. Ванильный JS, без библиотек.
   Страницы собирает tools/build.py: ссылки на собранные страницы — относительные,
   на ещё не собранные — от корня ("/maltipu/"), их клик показывает тост. */
(() => {
  'use strict';

  const d = document;
  const root = d.documentElement;
  root.classList.add('js');

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canHover = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  // папка фото относительно самого скрипта (assets/js/main.js → assets/img/): работает на любой глубине и под подпутём
  const IMG_BASE = d.currentScript && d.currentScript.src ? new URL('../img/', d.currentScript.src).href : 'assets/img/';
  const TOAST_TEXT = 'Раздел скоро откроется. Пока напишите нам — пришлём фото и видео щенков'; // ссылки на ещё не выложенные страницы (src/data/publish.json)
  const CONTACT_LABEL = { telegram: 'Telegram', whatsapp: 'WhatsApp', max: 'MAX', call: 'звонок' };
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

  // Несвёрстанные страницы (href от корня, сборщик оставил его как есть) → тост; якоря → плавная прокрутка
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

  /* ---------- выпадающие панели шапки: «Меню» (карта сайта) и «Породы» ----------
     Ховер с небольшой задержкой (намерение), клик / тап, клавиатура: Enter / Space — открыть-закрыть,
     ↓ — открыть и перейти к первой ссылке, ↑ / ↓ внутри — по ссылкам, Esc — закрыть и вернуть фокус на кнопку.
     Открытая кликом панель не закрывается, когда курсор уходит; открытая ховером — закрывается. */
  const drops = [];
  function dropdown(wrap, btn, panel, enterDelay) {
    let timer = 0;
    let pinned = false;
    let byHover = false;
    const api = {
      btn,
      isOpen: () => btn.getAttribute('aria-expanded') === 'true',
      set(open) {
        clearTimeout(timer);
        if (open) drops.forEach((o) => { if (o !== api && o.isOpen()) o.set(false); });
        btn.setAttribute('aria-expanded', String(open));
        panel.hidden = !open;
        wrap.classList.toggle('is-open', open);
        if (!open) { pinned = false; byHover = false; }
      }
    };
    const links = () => $$('a[href], button:not([disabled])', panel).filter((el) => el.offsetParent !== null);
    btn.addEventListener('click', (e) => {
      // мышью на устройстве с ховером: панель уже открыта наведением — клик её закрепляет, а не закрывает
      if (canHover && e.detail > 0 && api.isOpen() && byHover) { byHover = false; pinned = true; return; }
      const open = !api.isOpen();
      api.set(open);
      pinned = open;
    });
    btn.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowDown') return;
      e.preventDefault();
      api.set(true);
      pinned = true;
      const first = links()[0];
      first && first.focus();
    });
    panel.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const items = links();
      const i = items.indexOf(d.activeElement);
      if (i < 0) return;
      e.preventDefault();
      const next = e.key === 'ArrowDown' ? items[Math.min(i + 1, items.length - 1)] : items[i - 1];
      (next || btn).focus();
    });
    if (canHover) {
      wrap.addEventListener('mouseenter', () => {
        clearTimeout(timer);
        if (!api.isOpen()) timer = setTimeout(() => { api.set(true); byHover = true; }, enterDelay);
      });
      wrap.addEventListener('mouseleave', () => {
        clearTimeout(timer);
        if (api.isOpen() && !pinned) timer = setTimeout(() => api.set(false), 260);
      });
    }
    // фокус ушёл из панели (Tab дальше) — закрыть; клик по пустому месту панели фокус никуда не переводит
    wrap.addEventListener('focusout', (e) => {
      if (e.relatedTarget && !wrap.contains(e.relatedTarget)) api.set(false);
    });
    d.addEventListener('click', (e) => { if (api.isOpen() && !wrap.contains(e.target)) api.set(false); });
    drops.push(api);
    return api;
  }
  const ddWrap = $('[data-dd]');
  if (ddWrap) dropdown(ddWrap, $('.nav__dd-btn', ddWrap), $('#dd-breeds'), 60);
  const megaWrap = $('[data-mega]');
  const mega = megaWrap ? dropdown(megaWrap, $('[data-mega-btn]', megaWrap), $('#mega'), 140) : null;
  // мордочки пород в «Меню», «Породы ▾» и бургере — lazy и в скрытой панели не грузятся: подгружаем их, как только
  // указатель или фокус пришёл в шапку (панель открывается с задержкой — к открытию они уже на месте)
  if (hdr) {
    const warm = () => {
      ['#mega', '#dd-breeds', '#mmenu'].forEach((sel) => { const el = $(sel); if (el) $$('img[loading="lazy"]', el).forEach((img) => { img.loading = 'eager'; }); });
      ['pointerenter', 'focusin', 'touchstart'].forEach((ev) => hdr.removeEventListener(ev, warm));
    };
    ['pointerenter', 'focusin', 'touchstart'].forEach((ev) => hdr.addEventListener(ev, warm, { passive: true }));
  }
  // на планшете и телефоне вместо панелей — бургер
  window.matchMedia('(max-width: 1099px)').addEventListener('change', (m) => { if (m.matches) drops.forEach((o) => o.set(false)); });

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
    // группы разделов — аккордеоны: каждая кнопка открывает свой список (aria-controls)
    $$('.mmenu__acc', menu).forEach((acc) => {
      const sub = $('#' + acc.getAttribute('aria-controls'));
      if (!sub) return;
      acc.addEventListener('click', () => {
        const open = acc.getAttribute('aria-expanded') !== 'true';
        acc.setAttribute('aria-expanded', String(open));
        sub.hidden = !open;
      });
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
    if (d.querySelector('dialog[open]')) return; // модалка и лайтбокс (<dialog>) закрываются сами
    if (menuIsOpen()) { closeMenu(); return; }
    const open = drops.find((o) => o.isOpen());
    if (open) { open.set(false); open.btn.focus(); }
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
    const breedSelect = $('select', breedField);
    const doneTitle = $('#pm-done-title');
    const doneText = $('#pm-done-text');
    let returnTo = null;

    // порода в списке: по значению или по названию («Мальтипу»), без учёта регистра
    const selectBreed = (name) => {
      if (!breedSelect) return;
      const key = String(name).trim().toLowerCase();
      const opt = Array.from(breedSelect.options).find((o) => o.value.toLowerCase() === key || o.text.trim().toLowerCase() === key);
      if (opt) breedSelect.value = opt.value;
    };

    // ds — data-атрибуты кнопки: data-modal-title / -sub (заголовок и подпись окна),
    // data-modal-breed (порода в списке, если окно без щенка), data-modal-note (скрытая пометка заявки),
    // data-modal-submit (текст кнопки отправки), data-modal-done (текст после отправки)
    const pSubmit = $('[data-submit]', pForm);
    const SUBMIT_LABEL = pSubmit.dataset.label;
    let doneOverride = '';
    const openModal = (pup, opener, ds = {}) => {
      returnTo = opener;
      pSubmit.dataset.label = ds.modalSubmit || SUBMIT_LABEL;
      doneOverride = ds.modalDone || '';
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
      if (ds.modalTitle) title.textContent = ds.modalTitle;
      if (ds.modalSub) sub.textContent = ds.modalSub;
      if (ds.modalNote) pForm.elements.puppy.value = ds.modalNote;
      if (ds.modalBreed && !breedField.hidden) selectBreed(ds.modalBreed);
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
      // кнопка из панели «Меню» спрячется вместе с панелью — фокус вернём на «Меню»
      if (mega && megaWrap.contains(trigger)) { mega.set(false); opener = mega.btn; }
      const pup = card ? {
        name: card.dataset.name,
        desc: card.dataset.desc,
        img: card.dataset.img,
        tone: getComputedStyle(card).getPropertyValue('--tone').trim()
      } : null;
      openModal(pup, opener, trigger.dataset);
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
        doneText.textContent = doneOverride || (c === 'call'
          ? 'Куратор позвонит вам в течение рабочего дня по московскому времени.'
          : 'Куратор пришлёт цену и видео в ' + CONTACT_LABEL[c] + ' в течение рабочего дня по московскому времени.');
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
        doneText.textContent = c === 'call' ? 'Спасибо! Позвоним в течение рабочего дня' : 'Спасибо! Напишем в течение рабочего дня';
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

  /* ---------- SEO-текст (на странице их может быть несколько) ---------- */
  $$('[data-seo-toggle]').forEach((seoBtn) => {
    const box = seoBtn.closest('.seo');
    const more = $('#' + seoBtn.getAttribute('aria-controls'));
    const label = $('[data-seo-label]', seoBtn);
    if (!box || !more || !label) return;
    seoBtn.addEventListener('click', () => {
      const open = seoBtn.getAttribute('aria-expanded') !== 'true';
      seoBtn.setAttribute('aria-expanded', String(open));
      more.hidden = !open;
      box.classList.toggle('is-open', open);
      label.textContent = open ? 'Свернуть' : 'Читать полностью';
      if (!open && box.getBoundingClientRect().top < 0) box.scrollIntoView({ behavior: scrollBehavior, block: 'start' });
    });
  });

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

  /* ---------- карусели фото и видео [data-carousel] (macros/media.html.j2) ----------
     Нативная прокрутка с прилипанием (свайп на телефоне), стрелки, ← → на ленте или карточке,
     активная карточка — ближайшая к центру (у .media-carousel--reviews и data-align="start" — к левому краю).
     Фото карточек рядом с активной грузим заранее, когда карусель подъехала к экрану: lazy-загрузка браузера
     не видит карточки справа, и при свайпе они появлялись бы пустыми. Дальние — по мере листания
     (в ленте на главной ~40 кадров — все сразу не тянем). */
  const carouselIO = 'IntersectionObserver' in window ? new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      entry.target.dispatchEvent(new CustomEvent('carousel:near'));
      carouselIO.unobserve(entry.target);
    });
  }, { rootMargin: '600px 0px' }) : null;

  $$('[data-carousel]').forEach((root) => {
    const vp = $('[data-carousel-viewport]', root);
    const items = $$('.media-carousel__item', root);
    const prev = $('[data-carousel-prev]', root);
    const next = $('[data-carousel-next]', root);
    if (!vp || !items.length) return;
    if (carouselIO) carouselIO.observe(root);
    const fromStart = root.classList.contains('media-carousel--reviews') || root.dataset.align === 'start';
    let active = -1;
    let near = !carouselIO;
    const warm = (k) => {
      if (!near) return;
      items.slice(Math.max(0, k - 4), k + 7).forEach((li) => $$('img[loading="lazy"]', li).forEach((img) => { img.loading = 'eager'; }));
    };
    root.addEventListener('carousel:near', () => { near = true; warm(Math.max(active, 0)); });
    // точка, к которой прилипает карточка: центр ленты или её левый край (с учётом scroll-padding)
    const anchor = () => {
      const r = vp.getBoundingClientRect();
      return fromStart ? r.left + (parseFloat(getComputedStyle(vp).scrollPaddingLeft) || 0) : r.left + r.width / 2;
    };
    const pos = (li) => { const r = li.getBoundingClientRect(); return fromStart ? r.left : r.left + r.width / 2; };
    const setActive = (i) => {
      if (i === active) return;
      active = i;
      warm(i);
      items.forEach((li, k) => li.classList.toggle('is-active', k === i));
      if (prev) prev.disabled = i <= 0;
      if (next) next.disabled = i >= items.length - 1 || (fromStart && vp.scrollLeft + vp.clientWidth >= vp.scrollWidth - 2);
    };
    const nearest = () => {
      const a = anchor();
      let best = 0; let dist = Infinity;
      items.forEach((li, k) => { const dd = Math.abs(pos(li) - a); if (dd < dist) { dist = dd; best = k; } });
      return best;
    };
    // пока лента плавно едет к карточке после стрелки или клавиши, цель — эта карточка, а не «ближайшая к центру»:
    // иначе события scroll на полпути сбивают индекс, и быстрые нажатия подряд теряются
    let target = -1; let settle = 0;
    const release = (ms) => {
      clearTimeout(settle);
      settle = setTimeout(() => { target = -1; const k = nearest(); active = -1; setActive(k); }, ms);
    };
    const cur = () => (target >= 0 ? target : active);
    const go = (i, smooth = true) => {
      const k = Math.max(0, Math.min(items.length - 1, i));
      const animate = smooth && !reduceMotion;
      vp.scrollBy({ left: pos(items[k]) - anchor(), behavior: animate ? 'smooth' : 'auto' });
      setActive(k);
      if (animate) { target = k; release(400); }
      return k;
    };
    let raf = 0;
    vp.addEventListener('scroll', () => {
      if (target >= 0) { release(140); return; } // своя анимация: ждём, пока лента остановится
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { const k = nearest(); active = -1; setActive(k); });
    }, { passive: true });
    // палец или колесо на ленте — снова главный пользователь
    ['pointerdown', 'wheel'].forEach((ev) => vp.addEventListener(ev, () => { if (target >= 0) { target = -1; clearTimeout(settle); } }, { passive: true }));
    if (prev) prev.addEventListener('click', () => go(cur() - 1));
    if (next) next.addEventListener('click', () => go(cur() + 1));
    // клавиатура: на самой ленте или на карточке внутри — стрелки листают, фокус переходит на новую карточку
    vp.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      const k = go(cur() + (e.key === 'ArrowRight' ? 1 : -1));
      if (d.activeElement !== vp) {
        const btn = $('button', items[k]);
        btn && btn.focus({ preventScroll: true });
      }
    });
    // Tab по карточкам — карточка с фокусом выезжает к центру
    vp.addEventListener('focusin', (e) => {
      const li = e.target.closest('.media-carousel__item');
      if (li) go(items.indexOf(li));
    });
    // старт: средняя карточка (data-start), без анимации; после смены ширины — снова к активной
    const start = Math.min(items.length - 1, Math.max(0, Number(root.dataset.start) || 0));
    requestAnimationFrame(() => go(start, false));
    let rt;
    window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => go(Math.max(active, 0), false), 150); });
  });

  /* ---------- слайдер «О нашем питомнике» [data-hm-slider] (главная) ----------
     Фото — по PHOTO_MS, видео — до конца (не играет — ведёт себя как фото). Полоски сверху заполняются по ходу кадра,
     клик по полоске — к кадру, свайп — соседний кадр. Листается, только пока слайдер на экране и вкладка открыта;
     кнопка «Пауза» останавливает. При «уменьшить движение» не листается сам. Кадры открываем (и грузим) по одному вперёд. */
  const hs = $('[data-hm-slider]');
  if (hs) {
    const PHOTO_MS = 2600;
    const slides = $$('.hm-slider__slide', hs);
    const bars = $$('.hm-slider__bar', hs);
    const pauseBtn = $('[data-hm-pause]', hs);
    const n = slides.length;
    let cur = 0; let elapsed = 0; let last = 0; let raf = 0;
    let onScreen = false; let paused = reduceMotion; let prevTimer = 0;
    const media = (k) => slides[k].querySelector('img, video');
    const load = (k) => {
      const sl = slides[(k + n) % n];
      if (!sl.classList.contains('is-idle')) return;
      sl.classList.remove('is-idle');
      const m = media((k + n) % n);
      if (m && m.tagName === 'VIDEO') m.preload = 'auto';
    };
    const playable = (v) => v && v.tagName === 'VIDEO' && !v.dataset.failed;
    const running = () => onScreen && !paused && !d.hidden;
    const fill = (k, p) => bars[k].style.setProperty('--p', p);
    const startVideo = (v) => {
      v.muted = true;
      const p = v.play();
      if (p && p.catch) p.catch(() => { v.dataset.failed = '1'; });
    };
    const show = (k) => {
      const old = media(cur);
      if (old && old.tagName === 'VIDEO') old.pause();
      // прежний кадр остаётся под новым, пока тот проявляется, — без провала в фон посередине смены
      slides.forEach((sl) => sl.classList.remove('is-prev'));
      const was = slides[cur];
      if ((k + n) % n !== cur) {
        was.classList.add('is-prev');
        clearTimeout(prevTimer);
        prevTimer = setTimeout(() => was.classList.remove('is-prev'), 900);
      }
      was.classList.remove('is-on');
      was.setAttribute('aria-hidden', 'true');
      cur = (k + n) % n;
      slides[cur].classList.add('is-on');
      slides[cur].removeAttribute('aria-hidden');
      bars.forEach((b, j) => { fill(j, j < cur ? 1 : 0); if (j === cur) b.setAttribute('aria-current', 'true'); else b.removeAttribute('aria-current'); });
      load(cur); load(cur + 1);
      elapsed = 0; last = performance.now();
      const v = media(cur);
      if (playable(v)) { try { v.currentTime = 0; } catch (e) { /* ещё не загружено */ } if (running()) startVideo(v); }
    };
    const tick = (now) => {
      raf = 0;
      if (!running()) return;
      const v = media(cur);
      let p;
      elapsed += now - last;
      last = now;
      // видео, которое за 5 с так и не пошло (сеть, кодек), дальше ведёт себя как фото
      if (playable(v) && !v.currentTime && elapsed > 5000) v.dataset.failed = '1';
      if (playable(v)) p = v.duration ? v.currentTime / v.duration : 0;
      else p = elapsed / PHOTO_MS;
      if (p >= 1 && !playable(v)) { show(cur + 1); } else fill(cur, Math.min(p, 1));
      raf = requestAnimationFrame(tick);
    };
    const sync = () => {
      const v = media(cur);
      if (running()) {
        last = performance.now();
        if (playable(v)) startVideo(v);
        if (!raf) raf = requestAnimationFrame(tick);
      } else {
        if (v && v.tagName === 'VIDEO') v.pause();
        cancelAnimationFrame(raf); raf = 0;
      }
      pauseBtn.setAttribute('aria-pressed', paused ? 'true' : 'false');
      pauseBtn.setAttribute('aria-label', paused ? 'Смотреть дальше' : 'Пауза');
    };
    $$('video', hs).forEach((v) => {
      v.addEventListener('ended', () => { if (slides[cur].contains(v)) show(cur + 1); });
      v.addEventListener('error', () => { v.dataset.failed = '1'; });
    });
    bars.forEach((b, j) => b.addEventListener('click', () => { show(j); sync(); }));
    pauseBtn.addEventListener('click', () => { paused = !paused; sync(); });
    // свайп пальцем: влево — следующий кадр, вправо — предыдущий
    let x0 = null;
    hs.addEventListener('pointerdown', (e) => { if (e.pointerType !== 'mouse') x0 = e.clientX; }, { passive: true });
    hs.addEventListener('pointerup', (e) => {
      if (x0 === null) return;
      const dx = e.clientX - x0; x0 = null;
      if (Math.abs(dx) > 40) { show(cur + (dx < 0 ? 1 : -1)); sync(); }
    }, { passive: true });
    hs.addEventListener('pointercancel', () => { x0 = null; }, { passive: true });
    d.addEventListener('visibilitychange', sync);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(([entry]) => {
        if (entry.isIntersecting && !onScreen) load(cur + 1);
        onScreen = entry.isIntersecting; sync();
      }, { threshold: 0.35 }).observe(hs);
    } else { onScreen = true; load(cur + 1); }
    hs.classList.add('is-ready');
    sync();
  }

  /* ---------- отзывы с фото на главной (media.photo_review_card) ----------
     Длинный текст свёрнут до 8 строк: «Читать полностью» / «Свернуть» — только если текст правда не влез.
     На телефоне видно четыре отзыва, «Показать ещё отзывы» открывает следующие четыре. */
  const rvTexts = $$('[data-rvw-text]');
  const fold = (t) => {
    const btn = t.parentElement.querySelector('[data-rvw-toggle]');
    if (!btn || btn.getAttribute('aria-expanded') === 'true') return;
    t.classList.add('is-folded');
    const over = t.scrollHeight > t.clientHeight + 2;
    t.classList.toggle('is-folded', over);
    btn.hidden = !over;
  };
  if (rvTexts.length) {
    rvTexts.forEach((t) => {
      fold(t);
      const btn = t.parentElement.querySelector('[data-rvw-toggle]');
      btn && btn.addEventListener('click', () => {
        const open = btn.getAttribute('aria-expanded') !== 'true';
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        btn.textContent = open ? 'Свернуть' : 'Читать полностью';
        t.classList.toggle('is-folded', !open);
      });
    });
    let rvt;
    window.addEventListener('resize', () => { clearTimeout(rvt); rvt = setTimeout(() => rvTexts.forEach(fold), 200); });
    if (d.fonts && d.fonts.ready) d.fonts.ready.then(() => rvTexts.forEach(fold));
  }
  const rvws = $('.rvws');
  const rvMore = $('[data-rvw-more]');
  if (rvws && rvMore) {
    const STEP = 4;
    const rest = $$('.media-carousel__item', rvws).slice(STEP);
    const closed = () => rest.filter((li) => !li.classList.contains('is-open'));
    const upd = () => {
      const left = closed().length;
      rvMore.hidden = !left;
      rvws.classList.toggle('has-more', !!left);
      rvws.classList.toggle('is-all', !left);
    };
    rvMore.addEventListener('click', () => {
      const next = closed().slice(0, STEP);
      next.forEach((li) => li.classList.add('is-open'));
      next.forEach((li) => $$('[data-rvw-text]', li).forEach(fold));
      upd();
      if (rvMore.hidden && next[0]) { const b = $('button', next[0]); b && b.focus({ preventScroll: true }); }
    });
    upd();
  }

  /* ---------- лайтбокс #lightbox: [data-lightbox] открывает фото или видео ----------
     data-kind="photo" | "video"; data-src — файл видео (нет — постер и «Видео появится здесь»); data-caption — подпись.
     ← → — соседние карточки той же карусели, Esc / крестик / клик по фону — закрыть, фокус возвращается на карточку. */
  const lb = $('#lightbox');
  if (lb) {
    const stage = $('[data-lb-stage]', lb);
    const lbImg = $('[data-lb-img]', lb);
    const soon = $('[data-lb-soon]', lb);
    const cap = $('[data-lb-caption]', lb);
    const lbPrev = $('[data-lb-prev]', lb);
    const lbNext = $('[data-lb-next]', lb);
    let group = [];
    let idx = 0;
    let opener = null;
    let video = null;
    const stopVideo = () => { if (video) { video.pause(); video.remove(); video = null; } };
    const show = (i) => {
      idx = (i + group.length) % group.length;
      const b = group[idx];
      const pic = $('img', b);
      const isVideo = b.dataset.kind === 'video';
      stopVideo();
      lbImg.loading = 'eager';
      lbImg.src = pic ? (pic.currentSrc || pic.src) : '';
      lbImg.alt = pic ? pic.alt : '';
      lbImg.style.objectPosition = pic ? pic.style.objectPosition : '';
      if (pic && pic.naturalWidth) { lbImg.width = pic.naturalWidth; lbImg.height = pic.naturalHeight; }
      stage.classList.toggle('is-video', isVideo);
      const file = isVideo ? b.getAttribute('data-src') : '';
      soon.hidden = !isVideo || !!file;
      if (file) {
        video = d.createElement('video');
        video.src = file;
        video.controls = true;
        video.playsInline = true;
        video.poster = lbImg.src;
        stage.appendChild(video);
        video.play().catch(() => {});
      }
      cap.textContent = b.dataset.caption || lbImg.alt || (isVideo ? 'Видео' : 'Фото');
      lbPrev.hidden = lbNext.hidden = group.length < 2;
    };
    d.addEventListener('click', (e) => {
      const b = e.target.closest('[data-lightbox]');
      if (!b) return;
      e.preventDefault();
      opener = b;
      const scope = b.closest('[data-carousel]') || b.closest('section') || d.body;
      group = $$('[data-lightbox]', scope);
      show(Math.max(0, group.indexOf(b)));
      if (typeof lb.showModal === 'function') lb.showModal(); else lb.setAttribute('open', '');
      lockScroll('lightbox', true);
      $('[data-lb-close]', lb).focus();
    });
    lbPrev.addEventListener('click', () => show(idx - 1));
    lbNext.addEventListener('click', () => show(idx + 1));
    $('[data-lb-close]', lb).addEventListener('click', () => lb.close());
    lb.addEventListener('close', () => {
      stopVideo();
      lockScroll('lightbox', false);
      if (toast && toast.parentElement !== d.body) d.body.appendChild(toast);
      if (opener && opener.isConnected) opener.focus({ preventScroll: true });
      opener = null;
    });
    lb.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        if (group.length < 2 || (video && d.activeElement === video)) return;
        e.preventDefault();
        show(idx + (e.key === 'ArrowRight' ? 1 : -1));
        return;
      }
      if (e.key !== 'Tab') return;
      const els = $$('a[href], button:not([disabled]), video', lb).filter((el) => el.offsetParent !== null);
      if (!els.length) return;
      const first = els[0];
      const last = els[els.length - 1];
      if (e.shiftKey && (d.activeElement === first || !lb.contains(d.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
    });
    let downOnBackdrop = false;
    lb.addEventListener('pointerdown', (e) => { downOnBackdrop = e.target === lb; });
    lb.addEventListener('click', (e) => { if (e.target === lb && downOnBackdrop) lb.close(); });
  }

  /* ---------- мягкое появление при скролле ---------- */
  if (!reduceMotion && 'IntersectionObserver' in window) {
    const inScroller = (el) => {
      const p = el.parentElement;
      return p && getComputedStyle(p).overflowX !== 'visible';
    };
    const targets = $$([
      'main .section .sec-head',
      '.breeds > li', '.pups > li', '.help > li', '.steps > li', '.bento > li', '.advs > li', '.bteasers > li', '.lband',
      '.ratings > li', '.reviews > li', '.faq__aside', '.faq__list', '.seo', '.lead', '.footer__tile',
      // внутренние страницы: data-reveal — сам блок, data-reveal="items" — его дети по очереди
      '[data-reveal]:not([data-reveal="items"])', '[data-reveal="items"] > *'
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
