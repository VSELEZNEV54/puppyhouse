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
  const scrollBehavior = reduceMotion ? 'auto' : 'smooth';

  /* ---------- API: заявки, отзывы, анонимные события ----------
     Рабочий режим (LIVE) — только если <meta name="dsh-api"> (base.html.j2) задаёт адрес и сайт открыт с домена из
     data-origins, или в localStorage 'dsh:api' лежит абсолютный адрес API (разработка: http://127.0.0.1:8000/api/v1).
     Иначе — прототип (GitHub Pages): формы «отправляются» как раньше, без сервера, события не собираются, хранилище
     не трогаем. Общие функции — в window.DSH (trust.js, choice.js — отдельные IIFE). */
  const storage = (name) => {
    const s = () => { try { return window[name]; } catch (_) { return null; } };
    return {
      get(k) { try { const st = s(); return st ? st.getItem(k) : null; } catch (_) { return null; } },
      set(k, v) { try { const st = s(); if (st) st.setItem(k, v); } catch (_) { /* приватный режим, квота */ } },
      del(k) { try { const st = s(); if (st) st.removeItem(k); } catch (_) { /* приватный режим */ } }
    };
  };
  const local = storage('localStorage');
  const session = storage('sessionStorage');
  const readJSON = (st, k) => { try { const v = st.get(k); return v ? JSON.parse(v) : null; } catch (_) { return null; } };
  const writeJSON = (st, k, v) => { try { st.set(k, JSON.stringify(v)); } catch (_) { /* ничего */ } };

  function uuid() {
    const c = window.crypto;
    if (c && typeof c.randomUUID === 'function') { try { return c.randomUUID(); } catch (_) { /* не https */ } }
    const b = new Uint8Array(16);
    if (c && typeof c.getRandomValues === 'function') c.getRandomValues(b);
    else for (let i = 0; i < 16; i++) b[i] = Math.floor(Math.random() * 256);
    b[6] = (b[6] & 0x0f) | 0x40; // v4
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
    return h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' + h.slice(16, 20) + '-' + h.slice(20);
  }

  const apiMeta = $('meta[name="dsh-api"]');
  const API = (() => {
    const dev = local.get('dsh:api');
    if (dev && /^https?:\/\/\S+$/i.test(dev)) return dev.replace(/\/+$/, '');
    if (!apiMeta) return '';
    const url = (apiMeta.getAttribute('content') || '').trim();
    const origins = (apiMeta.dataset.origins || '').split(/\s+/).filter(Boolean);
    if (!url || !origins.includes(location.origin)) return '';
    try { return new URL(url, location.origin).href.replace(/\/+$/, ''); } catch (_) { return ''; }
  })();
  const LIVE = !!API;
  const CONSENT = {
    processing: (apiMeta && apiMeta.dataset.consent) || '',
    distribution: (apiMeta && apiMeta.dataset.consentPublish) || ''
  };

  /* идентификаторы браузера: посетитель (localStorage, навсегда), визит (sessionStorage, новый после 30 минут
     тишины: тогда же запоминаем страницу входа, внешний referrer и метки), первое касание (localStorage, один раз) */
  const SESSION_TTL = 30 * 60 * 1000;
  const UTM_KEYS = { utm_source: 'source', utm_medium: 'medium', utm_campaign: 'campaign', utm_content: 'content', utm_term: 'term', yclid: 'yclid', gclid: 'gclid' };
  function readUtm() {
    const out = {};
    try {
      const q = new URLSearchParams(location.search);
      Object.keys(UTM_KEYS).forEach((k) => { const v = q.get(k); if (v) out[UTM_KEYS[k]] = v.slice(0, 300); });
    } catch (_) { /* старый браузер */ }
    return out;
  }
  function externalReferrer() {
    const r = d.referrer || '';
    try { return r && new URL(r).origin !== location.origin ? r : ''; } catch (_) { return ''; }
  }
  let vid = '';
  function visitorId() {
    if (!vid) vid = local.get('dsh:vid') || '';
    if (!vid) { vid = uuid(); local.set('dsh:vid', vid); }
    return vid;
  }
  let mem = { id: '', ts: 0, info: null }; // если sessionStorage недоступен — визит живёт в памяти страницы
  function currentSession() {
    const now = Date.now();
    let id = session.get('dsh:sid') || mem.id;
    const ts = Number(session.get('dsh:sid-ts')) || mem.ts;
    let info = readJSON(session, 'dsh:sess') || mem.info;
    if (!id || !info || now - ts > SESSION_TTL) {
      id = uuid();
      info = { landing: location.pathname, referrer: externalReferrer(), utm: readUtm() };
      session.set('dsh:sid', id);
      writeJSON(session, 'dsh:sess', info);
    }
    session.set('dsh:sid-ts', String(now));
    mem = { id, ts: now, info };
    return mem;
  }
  function firstTouch(s) {
    let f = readJSON(local, 'dsh:first');
    if (!f || typeof f !== 'object') {
      f = { landing: s.info.landing, referrer: s.info.referrer, utm: s.info.utm };
      writeJSON(local, 'dsh:first', f);
    }
    return f;
  }
  function ymUid() {
    const m = /(?:^|;\s*)_ym_uid=(\d+)/.exec(d.cookie || '');
    return m ? m[1] : null;
  }
  const pageInfo = () => ({ path: location.pathname, title: d.title });
  // поля «кто и откуда» для заявки и пачки событий
  function context() {
    const s = currentSession();
    const f = firstTouch(s);
    return {
      visitor_id: visitorId(),
      session_id: s.id,
      landing: s.info.landing || location.pathname,
      referrer: s.info.referrer || null,
      utm: s.info.utm || {},
      first_landing: f.landing || s.info.landing || location.pathname,
      first_referrer: f.referrer || null,
      first_utm: f.utm || {},
      ym_uid: ymUid()
    };
  }

  /* POST JSON: keepalive, 12 с на попытку, повтор через 1 и 4 с при сетевой ошибке, 5xx, 408, 429 — с тем же
     телом (и тем же idempotency_key). Ответ: {ok, status, data}; status 0 — сеть или таймаут. */
  const RETRY_DELAYS = [1000, 4000];
  const retryable = (st) => st === 0 || st >= 500 || st === 408 || st === 429;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  async function postOnce(url, body) {
    const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = ctrl ? setTimeout(() => ctrl.abort(), 12000) : 0;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
        keepalive: true,
        credentials: 'same-origin',
        cache: 'no-store',
        signal: ctrl ? ctrl.signal : undefined
      });
      let data = null;
      try { data = await res.json(); } catch (_) { data = null; }
      return { ok: res.ok, status: res.status, data };
    } catch (_) {
      return { ok: false, status: 0, data: null };
    } finally {
      clearTimeout(timer);
    }
  }
  async function sendJSON(path, payload) {
    if (!LIVE) return { ok: false, status: 0, data: null };
    const body = JSON.stringify(payload);
    let res = await postOnce(API + path, body);
    for (let i = 0; i < RETRY_DELAYS.length && retryable(res.status); i++) {
      await sleep(RETRY_DELAYS[i]);
      res = await postOnce(API + path, body);
    }
    return res;
  }

  /* Очередь неотправленного в localStorage 'dsh:outbox': запись появляется ДО первой попытки, уходит после 2xx / 409 /
     422; остальное ждёт следующей страницы или события 'online' (старше 7 дней — выбрасываем). Ключ идемпотентности
     повторяется только для того же самого содержимого: та же заявка из очереди уходит ровно тем же телом. */
  const OUTBOX = 'dsh:outbox';
  const OUTBOX_TTL = 7 * 24 * 60 * 60 * 1000;
  const settled = (st) => (st >= 200 && st < 300) || st === 409 || st === 422;
  const inflight = new Set();
  function outboxRead() {
    const list = readJSON(local, OUTBOX);
    const now = Date.now();
    return Array.isArray(list)
      ? list.filter((e) => e && e.key && e.path && e.payload && typeof e.ts === 'number' && now - e.ts < OUTBOX_TTL)
      : [];
  }
  function outboxWrite(list) { if (list.length) writeJSON(local, OUTBOX, list); else local.del(OUTBOX); }
  function outboxPut(entry) { outboxWrite(outboxRead().filter((e) => e.key !== entry.key).concat([entry])); }
  function outboxDrop(key) { outboxWrite(outboxRead().filter((e) => e.key !== key)); }
  // отпечаток содержимого (без ключа и времени заполнения): та же заявка → та же запись очереди
  function fingerprint(path, payload) {
    const p = Object.assign({}, payload);
    delete p.idempotency_key;
    delete p.elapsed_ms;
    const str = path + JSON.stringify(p);
    let h1 = 0xdeadbeef;
    let h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
      const ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761);
      h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
  }
  async function sendEntry(entry) {
    inflight.add(entry.key);
    try { return await sendJSON(entry.path, entry.payload); } finally { inflight.delete(entry.key); }
  }
  // Отправка формы: state — объект формы ({key}); исправленная после ошибки заявка заменяет прежнюю в очереди.
  async function submit(path, data, state) {
    const fp = fingerprint(path, data);
    let entry = outboxRead().find((e) => e.path === path && e.fp === fp);
    if (!entry) {
      const key = uuid();
      entry = { key, path, fp, ts: Date.now(), payload: Object.assign({}, data, { idempotency_key: key }) };
      if (state && state.key && state.key !== key) outboxDrop(state.key);
      outboxPut(entry);
    }
    if (state) state.key = entry.key;
    let res = await sendEntry(entry);
    if (res.status === 409) { // ключ занят другим содержимым — новый ключ, ещё одна попытка
      outboxDrop(entry.key);
      const key = uuid();
      entry = { key, path, fp, ts: Date.now(), payload: Object.assign({}, entry.payload, { idempotency_key: key }) };
      outboxPut(entry);
      if (state) state.key = key;
      res = await sendEntry(entry);
    }
    if (settled(res.status)) {
      outboxDrop(entry.key);
      if (state) state.key = '';
    }
    return res;
  }
  let flushing = false;
  async function flushOutbox() {
    if (!LIVE || flushing) return;
    flushing = true;
    try {
      const list = outboxRead();
      outboxWrite(list); // заодно убираем просроченные
      for (const e of list) {
        if (inflight.has(e.key)) continue;
        const res = await sendEntry(e);
        if (settled(res.status)) outboxDrop(e.key);
        else break; // сервер всё ещё недоступен — дождёмся 'online' или следующей страницы
      }
    } finally {
      flushing = false;
    }
  }

  /* Анонимные события (только LIVE): page_view, form_open, contact_click, quiz_complete. Пачки до 20 штук уходят
     через sendBeacon (text/plain — без preflight), когда вкладка скрывается или закрывается; page_view — сразу. */
  const queue = [];
  function flushEvents() {
    if (!LIVE || !queue.length) return;
    const ctx = context();
    while (queue.length) {
      const json = JSON.stringify(Object.assign({}, ctx, { events: queue.splice(0, 20) }));
      let sent = false;
      try {
        sent = typeof navigator.sendBeacon === 'function' && navigator.sendBeacon(API + '/events', new Blob([json], { type: 'text/plain' }));
      } catch (_) { sent = false; }
      if (!sent) {
        try {
          fetch(API + '/events', { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: json, keepalive: true, credentials: 'same-origin' }).catch(() => {});
        } catch (_) { /* ничего */ }
      }
    }
  }
  function track(type, data) {
    if (!LIVE) return;
    queue.push({ type, path: location.pathname, ts: Date.now(), data: data || {} });
    if (queue.length >= 20) flushEvents();
  }
  // тест «Подбор породы» (choice.js): событие + результат для следующей заявки из этой вкладки
  function quizDone(winner, second, answers) {
    if (!LIVE || !winner) return;
    writeJSON(session, 'dsh:quiz', { winner, second: second || null });
    track('quiz_complete', { winner, second: second || null, answers: answers || {} });
  }

  const CHANNELS = [
    ['a[href^="tel:"]', 'phone'], ['a[href*="t.me/"]', 'telegram'], ['a[href*="wa.me/"]', 'whatsapp'],
    ['a[href*="max.ru"]', 'max'], ['a[href^="mailto:"]', 'email']
  ];
  const PLACES = [['#mega', 'mega'], ['#mmenu', 'mmenu'], ['.mbar', 'mbar'], ['.modal', 'modal'], ['.lead', 'lead'], ['.hdr', 'header'], ['.footer', 'footer']];
  if (LIVE) {
    d.addEventListener('click', (e) => {
      const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
      if (!a) return;
      const ch = CHANNELS.find(([sel]) => a.matches(sel));
      if (!ch) return;
      const place = PLACES.find(([sel]) => a.closest(sel));
      track('contact_click', { channel: ch[1], place: place ? place[1] : 'page' });
    }, true);
    d.addEventListener('visibilitychange', () => { if (d.visibilityState === 'hidden') flushEvents(); });
    window.addEventListener('pagehide', flushEvents);
    window.addEventListener('online', flushOutbox);
    track('page_view', { title: d.title });
    flushEvents();
    flushOutbox();
  }

  window.DSH = {
    live: LIVE, api: API, consent: CONSENT,
    uuid, context, page: pageInfo, sendJSON, submit, settled, flushOutbox, track, flushEvents, quizDone,
    session: { get: (k) => readJSON(session, k), del: (k) => session.del(k) }
  };

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
    // группа радиокнопок (contact, rating) — RadioNodeList: отмечаем каждую
    const el = form.elements[field];
    const targets = !el ? [] : (typeof el.setAttribute === 'function' ? [el] : Array.from(el));
    targets.forEach((t) => {
      if (msg) t.setAttribute('aria-invalid', 'true'); else t.removeAttribute('aria-invalid');
    });
  }
  // 422 от API: тексты сервера под полями (fields: {name, phone, contact, consent}); без них — тост с message
  function serverErrors(form, data, fields, set = setError) {
    const err = (data && data.error) || {};
    const map = err.fields || {};
    let first = null;
    fields.forEach((k) => {
      if (!map[k]) return;
      set(form, k, String(map[k]));
      if (!first) first = k;
    });
    if (first) {
      const el = form.elements[first];
      const target = el && typeof el.focus === 'function' ? el : (el && el[0]);
      if (target) target.focus();
    } else {
      showToast(err.message || 'Проверьте, пожалуйста, поля формы');
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
  const contactOf = (form) => {
    const c = form.querySelector('input[name="contact"]:checked');
    return c ? c.value : 'telegram';
  };

  /* Заявка в API (LIVE): тело по контракту POST /leads. extra — поля модалки (kind, puppy, colour, note, form_title);
     started — когда форму открыли (модалка) или начали заполнять (форма внизу) → elapsed_ms. */
  const LEAD_FIELDS = ['name', 'phone', 'contact', 'consent'];
  function leadPayload(form, extra, started) {
    const f = form.elements;
    const text = (n) => (f[n] && typeof f[n].value === 'string' ? f[n].value.trim() : '');
    const opt = (v) => (v ? String(v) : null);
    const quiz = readJSON(session, 'dsh:quiz');
    const ctx = context();
    return {
      kind: extra.kind || 'lead',
      name: text('name'),
      phone: text('phone'),
      contact: contactOf(form),
      consent: !!(f.consent && f.consent.checked),
      consent_version: CONSENT.processing,
      breed: f.breed ? f.breed.value : '',
      puppy: opt(extra.puppy),
      puppy_name: opt(extra.puppy_name),
      colour: opt(extra.colour),
      note: opt(extra.note),
      form_title: opt(extra.form_title),
      quiz: quiz && quiz.winner ? { winner: quiz.winner, second: quiz.second || null } : null,
      page: pageInfo(),
      visitor_id: ctx.visitor_id,
      session_id: ctx.session_id,
      landing: ctx.landing,
      referrer: ctx.referrer,
      utm: ctx.utm,
      first_landing: ctx.first_landing,
      first_referrer: ctx.first_referrer,
      first_utm: ctx.first_utm,
      ym_uid: ctx.ym_uid,
      hp_note: f.hp_note ? f.hp_note.value : '',
      elapsed_ms: started ? Math.max(0, Date.now() - started) : 0
    };
  }
  // отправка в API с кнопкой «Отправляем…»; isCurrent() = false — форму уже открыли заново, экран не трогаем
  async function liveLead(form, payload, state, { done, fail, isCurrent = () => true }) {
    const btn = $('[data-submit]', form);
    btn.disabled = true;
    btn.textContent = 'Отправляем…';
    let res;
    try { res = await submit('/leads', payload, state); } catch (_) { res = { ok: false, status: 0, data: null }; }
    if (res.ok) session.del('dsh:quiz'); // результат теста уходит только со следующей заявкой
    if (!isCurrent()) return;
    btn.disabled = false;
    btn.textContent = btn.dataset.label;
    if (res.ok) done();
    else if (res.status === 422) serverErrors(form, res.data, LEAD_FIELDS);
    else fail();
  }

  /* ---------- модалка «Узнать цену» ---------- */
  const modal = $('#price-modal');
  const pForm = $('#price-form');
  if (modal && pForm) {
    pForm.dataset.prefix = 'pm';
    bindLiveClear(pForm);
    const viewForm = $('[data-view="form"]', modal);
    const viewDone = $('[data-view="done"]', modal);
    const viewError = $('[data-view="error"]', modal);
    const errorTitle = $('#pm-error-title');
    const title = $('#pm-title');
    const sub = $('#pm-sub');
    const thumb = $('[data-pm-thumb]', modal);
    const thumbImg = $('img', thumb);
    const breedField = $('[data-pm-breed]', modal);
    const breedSelect = $('select', breedField);
    const doneTitle = $('#pm-done-title');
    const doneText = $('#pm-done-text');
    let returnTo = null;
    let openedAt = 0; // elapsed_ms заявки — от открытия окна
    let openSeq = 0; // номер открытия: ответ API от прошлого открытия не меняет экран нового
    const pState = { key: '' };
    const hidden = (name, value) => { if (pForm.elements[name]) pForm.elements[name].value = value || ''; };

    // порода в списке: по значению или по названию («Мальтипу»), без учёта регистра
    const selectBreed = (name) => {
      if (!breedSelect) return;
      const key = String(name).trim().toLowerCase();
      const opt = Array.from(breedSelect.options).find((o) => o.value.toLowerCase() === key || o.text.trim().toLowerCase() === key);
      if (opt) breedSelect.value = opt.value;
    };

    // ds — data-атрибуты кнопки: data-modal-title / -sub (заголовок и подпись окна),
    // data-modal-breed (порода в списке, если окно без щенка), data-modal-note (скрытая пометка заявки),
    // data-modal-kind (тип заявки для API; без него — puppy у карточки щенка, иначе price), data-modal-colour (окрас),
    // data-modal-submit (текст кнопки отправки), data-modal-done (текст после отправки).
    // Скрытые поля (kind, puppy, puppy_name, colour, note, form_title) задаём при КАЖДОМ открытии: form.reset() их не чистит.
    const pSubmit = $('[data-submit]', pForm);
    const SUBMIT_LABEL = pSubmit.dataset.label;
    let doneOverride = '';
    const openModal = (pup, opener, ds = {}) => {
      returnTo = opener;
      pSubmit.dataset.label = ds.modalSubmit || SUBMIT_LABEL;
      doneOverride = ds.modalDone || '';
      clearForm(pForm);
      openedAt = Date.now();
      openSeq++;
      pState.key = '';
      viewForm.hidden = false;
      viewDone.hidden = true;
      if (viewError) viewError.hidden = true;
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
        if (pup.breed) selectBreed(pup.breed); // порода щенка уходит в заявку, хотя список скрыт
      } else {
        title.textContent = 'Узнать цену щенка';
        sub.textContent = 'Пришлём щенков в наличии с ценами и видео';
        thumb.hidden = true;
        breedField.hidden = false;
      }
      if (ds.modalTitle) title.textContent = ds.modalTitle;
      if (ds.modalSub) sub.textContent = ds.modalSub;
      if (ds.modalBreed && !breedField.hidden) selectBreed(ds.modalBreed);
      const kind = ds.modalKind || (pup ? 'puppy' : 'price');
      hidden('kind', kind);
      hidden('puppy', pup ? pup.slug : '');
      hidden('puppy_name', pup ? pup.name : '');
      hidden('colour', ds.modalColour);
      hidden('note', ds.modalNote);
      hidden('form_title', title.textContent);
      // после всех обработчиков клика (puppy.js выбирает породу своей страницы) — порода уже в списке
      setTimeout(() => track('form_open', {
        kind,
        breed: (breedSelect && breedSelect.value) || null,
        puppy: (pup && pup.slug) || null,
        colour: ds.modalColour || null
      }), 0);
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
        slug: card.dataset.slug || '',
        breed: card.dataset.breed || '',
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
      const items = $$('a[href], button:not([disabled]), input:not([type="hidden"]):not([tabindex="-1"]), select, textarea, [tabindex]:not([tabindex="-1"])', modal)
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

    const showDone = () => {
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
    };
    // API недоступен после всех попыток: заявка ждёт в очереди браузера, форма остаётся заполненной
    const showError = () => {
      if (!viewError) return;
      viewForm.hidden = true;
      viewError.hidden = false;
      modal.setAttribute('aria-labelledby', 'pm-error-title');
      modal.setAttribute('aria-describedby', 'pm-error-text');
      errorTitle.focus();
    };
    const backBtn = $('[data-pm-back]', modal);
    if (backBtn) backBtn.addEventListener('click', () => {
      viewError.hidden = true;
      viewForm.hidden = false;
      modal.setAttribute('aria-labelledby', 'pm-title');
      modal.setAttribute('aria-describedby', 'pm-sub');
      pSubmit.focus();
    });

    pForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!validate(pForm)) return;
      if (!LIVE) { fakeSend(pForm, showDone); return; }
      const f = pForm.elements;
      const payload = leadPayload(pForm, {
        kind: f.kind.value,
        puppy: f.puppy.value,
        puppy_name: f.puppy_name.value,
        colour: f.colour.value,
        note: f.note.value,
        form_title: f.form_title.value
      }, openedAt);
      const seq = openSeq;
      liveLead(pForm, payload, pState, { done: showDone, fail: showError, isCurrent: () => seq === openSeq && modal.open });
    });
  }

  /* ---------- форма заявки внизу ---------- */
  const lForm = $('#lead-form');
  if (lForm) {
    lForm.dataset.prefix = 'lf';
    bindLiveClear(lForm);
    const done = $('[data-done]');
    const doneText = $('[data-done-text]');
    const fail = $('[data-fail]');
    const lState = { key: '' };
    let startedAt = 0; // elapsed_ms — от первого касания формы
    const start = () => {
      if (startedAt) return;
      startedAt = Date.now();
      track('form_open', { kind: 'lead', breed: (lForm.elements.breed && lForm.elements.breed.value) || null, puppy: null, colour: null });
    };
    lForm.addEventListener('focusin', start);
    lForm.addEventListener('input', start);
    const showDone = () => {
      const c = contactOf(lForm);
      doneText.textContent = c === 'call' ? 'Спасибо! Позвоним в течение рабочего дня' : 'Спасибо! Напишем в течение рабочего дня';
      if (fail) fail.hidden = true;
      lForm.hidden = true;
      done.hidden = false;
      done.focus();
    };
    lForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (!validate(lForm)) return;
      if (!LIVE) { fakeSend(lForm, showDone); return; }
      if (fail) fail.hidden = true;
      const title = $('#lead-title');
      const payload = leadPayload(lForm, { kind: 'lead', form_title: title ? title.textContent.trim() : '' }, startedAt);
      liveLead(lForm, payload, lState, { done: showDone, fail: () => { if (fail) fail.hidden = false; } });
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
