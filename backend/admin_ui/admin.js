/* Админ-панель домщенков.рф: резервная копия всех заявок с сайта, по базам пород.
   Работает поверх /api/v1/admin (тот же сервер, тот же домен). Ванильный JS без сборки.
   Безопасность: данные заявок вставляются только как текст (textContent), никогда как HTML; токен входа живёт
   в sessionStorage (закрыли вкладку — вышли) и отправляется только в заголовке Authorization. */
(() => {
  'use strict';

  const API = '/api/v1/admin';
  const TOKEN_KEY = 'dsh:admin-token';
  const POLL_MS = 60_000;
  const app = document.getElementById('app');
  const S = { meta: null, me: null, breeds: [], lastNew: null, timer: null, main: null, drawer: null };
  let TZ = 'Europe/Moscow';

  /* ---------- хранилище токена ---------- */
  const token = {
    get() { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (_) { return ''; } },
    set(v) { try { if (v) sessionStorage.setItem(TOKEN_KEY, v); else sessionStorage.removeItem(TOKEN_KEY); } catch (_) { /* приватный режим */ } }
  };

  /* ---------- DOM: только текст ---------- */
  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'text') el.textContent = v;
        else if (k === 'vars') for (const [n, val] of Object.entries(v)) el.style.setProperty(n, val);
        else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
        else if (k === 'value') el.value = v;
        else if (['checked', 'disabled', 'selected', 'required', 'hidden'].includes(k)) el[k] = !!v;
        else el.setAttribute(k, v === true ? '' : String(v));
      }
    }
    append(el, kids);
    return el;
  }
  function append(el, kids) {
    for (const k of kids.flat(Infinity)) {
      if (k == null || k === false || k === '') continue;
      el.append(k instanceof Node ? k : document.createTextNode(String(k)));
    }
    return el;
  }
  const field = (label, control) => h('label', { class: 'field' }, h('span', { text: label }), control);
  const option = (value, text, selected) => h('option', { value, text, selected: selected || false });
  // только безопасные ссылки: tel:, https:, относительные пути сайта
  const safeHref = (u) => (typeof u === 'string' && /^(tel:\+?\d+|https:\/\/|\/(?!\/))/.test(u) ? u : null);

  /* ---------- API ---------- */
  async function api(path, { method = 'GET', body, version, raw } = {}) {
    const headers = { Authorization: 'Bearer ' + token.get() };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (version != null) headers['If-Match'] = String(version);
    let r;
    try {
      r = await fetch(API + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined,
                                    cache: 'no-store', credentials: 'omit' });
    } catch (_) {
      throw Object.assign(new Error('Нет связи с сервером. Проверьте интернет и попробуйте ещё раз'), { status: 0 });
    }
    if (r.status === 401) {
      token.set('');
      viewLogin('Сессия закончилась — войдите снова');
      throw Object.assign(new Error('unauthorized'), { status: 401, silent: true });
    }
    if (raw) return r;
    const data = r.status === 204 ? null : await r.json().catch(() => null);
    if (!r.ok) {
      const err = (data && data.error) || {};
      const fields = Object.values(err.fields || {});
      throw Object.assign(new Error([err.message || 'Ошибка ' + r.status, ...fields].join('. ')),
                          { status: r.status, code: err.code, data: err });
    }
    return data;
  }

  /* ---------- форматы ---------- */
  const fmtDate = (iso, time = true) => {
    if (!iso) return '—';
    const o = { timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric' };
    if (time) Object.assign(o, { hour: '2-digit', minute: '2-digit' });
    return new Intl.DateTimeFormat('ru-RU', o).format(new Date(iso));
  };
  const listOf = (name) => (S.meta && S.meta[name]) || [];
  const labelOf = (name, value) => { const it = listOf(name).find((x) => x.value === value); return it ? it.label : (value || '—'); };
  const statusMeta = (v) => listOf('statuses').find((x) => x.value === v) || { label: v, color: '#999', is_closed: false };
  const chip = (status) => { const m = statusMeta(status); return h('span', { class: 'chip', vars: { '--c': m.color }, text: m.label }); };
  const OPEN = () => listOf('statuses').filter((s) => !s.is_closed).map((s) => s.value);
  const isLate = (l) => OPEN().includes(l.status) && !l.parent_id &&
    ((l.next_contact_at && new Date(l.next_contact_at) < new Date()) ||
     (l.status === 'new' && Date.now() - new Date(l.created_at).getTime() > 15 * 60 * 1000));
  // +79161234567 → +7 (916) 123-45-67; другие страны — как есть
  const fmtPhone = (e164) => {
    const m = /^\+7(\d{3})(\d{3})(\d{2})(\d{2})$/.exec(e164 || '');
    return m ? '+7 (' + m[1] + ') ' + m[2] + '-' + m[3] + '-' + m[4] : (e164 || '');
  };
  // (direct) / (none) — так аналитика называет заход без рекламной метки и без сайта-источника
  const sourceLabel = (src, medium) => src === '(direct)' ? 'прямой заход' : [src, medium].filter(Boolean).join(' / ');
  const duration = (min) => {
    if (min == null) return '—';
    if (min < 60) return Math.round(min) + ' мин';
    if (min < 48 * 60) return Math.round(min / 60) + ' ч';
    return Math.round(min / 1440) + ' дн';
  };
  const plural = (n, one, few, many) => { const a = Math.abs(n) % 100, b = a % 10;
    return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many; };

  /* ---------- уведомления ---------- */
  let toastTimer;
  function toast(text) {
    let t = document.querySelector('.toast');
    if (!t) { t = h('div', { class: 'toast', role: 'status' }); document.body.append(t); }
    t.textContent = text;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3500);
  }
  const notice = (text, err) => h('p', { class: 'notice' + (err ? ' notice--err' : ''), role: err ? 'alert' : 'status', text });

  /* ---------- маршруты: #/leads?base=…, #/reviews, #/stats ---------- */
  function route() {
    const [path, qs] = (location.hash.slice(1) || '/leads').split('?');
    return { path: path || '/leads', q: new URLSearchParams(qs || '') };
  }
  function go(path, params = {}, replace = false) {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null && v !== false)).toString();
    const hash = '#' + path + (qs ? '?' + qs : '');
    if (replace) history.replaceState(null, '', hash); else location.hash = hash;
    if (replace) render();
  }
  window.addEventListener('hashchange', () => render());

  /* ---------- вход ---------- */
  function viewLogin(message) {
    stopPolling();
    closeDrawer(true);
    const err = h('p', { class: 'login__err', role: 'alert', text: message || '' });
    const login = h('input', { class: 'input', name: 'login', autocomplete: 'username', required: true });
    const pass = h('input', { class: 'input', type: 'password', name: 'password', autocomplete: 'current-password', required: true });
    const btn = h('button', { class: 'btn btn--ink', type: 'submit', text: 'Войти' });
    const form = h('form', {
      class: 'login__box',
      onsubmit: async (e) => {
        e.preventDefault();
        btn.disabled = true;
        err.textContent = '';
        try {
          const r = await fetch(API + '/auth/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'omit',
            body: JSON.stringify({ login: login.value.trim(), password: pass.value })
          });
          const data = await r.json().catch(() => null);
          if (!r.ok) throw new Error((data && data.error && data.error.message) || 'Не получилось войти');
          token.set(data.token);
          pass.value = '';
          await boot();
        } catch (e2) {
          err.textContent = e2.message === 'Failed to fetch' ? 'Нет связи с сервером' : e2.message;
        } finally {
          btn.disabled = false;
        }
      }
    },
    h('div', { class: 'login__brand' }, h('span', { class: 'logo', 'aria-hidden': 'true' }),
      h('div', null, h('div', { text: 'домщенков.рф' }), h('div', { class: 'muted small', text: 'Заявки с сайта' }))),
    field('Логин', login), field('Пароль', pass), err, btn);
    document.title = 'Вход · домщенков.рф';
    app.replaceChildren(h('main', { class: 'login' }, form));
    setTimeout(() => login.focus(), 0);
  }

  async function logout() {
    try { await api('/auth/logout', { method: 'POST' }); } catch (_) { /* всё равно выходим */ }
    token.set('');
    viewLogin('Вы вышли');
  }

  /* ---------- каркас ---------- */
  function shell() {
    const r = route();
    const link = (path, text) => h('a', { href: '#' + path, text, 'aria-current': r.path === path ? 'page' : null });
    const top = h('header', { class: 'top' },
      h('div', { class: 'top__brand' }, h('span', { class: 'logo', 'aria-hidden': 'true' }), 'домщенков.рф'),
      h('nav', { class: 'nav', 'aria-label': 'Разделы' }, link('/leads', 'Заявки'), link('/reviews', 'Отзывы'), link('/stats', 'Сводка')),
      h('div', { class: 'top__me' }, h('span', { class: 'muted', text: S.me ? S.me.name : '' }),
        h('button', { class: 'btn btn--sm', type: 'button', text: 'Выйти', onclick: logout })));
    // aria-busy: экранные дикторы ждут конца загрузки; data-view — какой адрес показан (для проверок)
    S.main = h('main', { class: 'main', id: 'main', 'aria-busy': 'true', 'data-view': location.hash });
    app.replaceChildren(top, S.main);
  }

  async function render() {
    if (!token.get()) return viewLogin();
    if (!S.meta) return boot();
    const { path, q } = route();
    shell();
    try {
      if (path === '/reviews') await viewReviews(q);
      else if (path === '/stats') await viewStats(q);
      else await viewLeads(q);
    } catch (e) {
      if (!e.silent) S.main.append(notice(e.message, true));
    }
    S.main.setAttribute('aria-busy', 'false');
    if (path === '/leads' && q.get('lead')) openLead(+q.get('lead'));
    else closeDrawer(true);
  }

  /* ---------- базы пород и опрос новых заявок ---------- */
  async function loadBreeds() {
    S.breeds = await api('/breeds');
    const totalNew = S.breeds.reduce((s, b) => s + (b.new || 0), 0);
    document.title = (totalNew ? '(' + totalNew + ') ' : '') + 'Заявки · домщенков.рф';
    const grew = S.lastNew != null && totalNew > S.lastNew;
    S.lastNew = totalNew;
    return grew;
  }
  function startPolling() {
    stopPolling();
    S.timer = setInterval(async () => {
      try {
        const grew = await loadBreeds();
        if (grew) {
          toast('Новая заявка на сайте');
          const r = route();
          if (r.path === '/leads' && !S.drawer && (+r.q.get('page') || 1) === 1) render();
        }
      } catch (_) { /* следующая попытка через минуту */ }
    }, POLL_MS);
  }
  function stopPolling() { if (S.timer) clearInterval(S.timer); S.timer = null; }

  /* ---------- заявки ---------- */
  const STATUS_FILTERS = () => [
    ['open', 'Открытые'], ['new', 'Новые'], ['overdue', 'Просроченные'], ['all', 'Все'], ['closed', 'Закрытые'],
    ...listOf('statuses').filter((s) => !['new', 'duplicate'].includes(s.value)).map((s) => [s.value, s.label])
  ];

  function leadParams(q) {
    const p = new URLSearchParams();
    const base = q.get('base') || 'all';
    const status = q.get('status') || 'open';
    if (base !== 'all') p.set('breed', base);
    if (status === 'overdue') p.set('overdue', 'true');
    else if (status !== 'all') p.set('status', status);
    for (const [from, to] of [['kind', 'kind'], ['q', 'q'], ['from', 'created_from'], ['to', 'created_to']]) {
      if (q.get(from)) p.set(to, q.get(from));
    }
    return p;
  }

  async function viewLeads(q) {
    await loadBreeds();
    startPolling();
    const state = Object.fromEntries(q.entries());
    const base = state.base || 'all';
    const page = Math.max(1, +state.page || 1);
    const set = (patch) => go('/leads', { ...state, page: '', lead: '', ...patch });

    // базы: «Все заявки», каждая порода, «Без породы»
    const all = S.breeds.reduce((a, b) => ({ total: a.total + b.total, open: a.open + b.open, new: a.new + b.new,
                                              overdue: a.overdue + b.overdue }), { total: 0, open: 0, new: 0, overdue: 0 });
    const tab = (key, name, c) => h('button', {
      class: 'tab', type: 'button', 'aria-pressed': String(base === key), onclick: () => set({ base: key === 'all' ? '' : key })
    }, h('span', { class: 'tab__name', text: name }),
    h('span', { class: 'tab__nums' },
      h('span', { text: 'всего ' + c.total }), h('span', { text: 'открыто ' + c.open }),
      c.new ? h('span', { class: 'tab__new', text: 'новых ' + c.new }) : null,
      c.overdue ? h('span', { class: 'tab__late', text: 'просрочено ' + c.overdue }) : null));
    const tabs = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Базы заявок' },
      tab('all', 'Все заявки', all), S.breeds.map((b) => tab(b.key, b.name, b)));

    // фильтры
    const status = h('select', { class: 'select', onchange: (e) => set({ status: e.target.value === 'open' ? '' : e.target.value }) },
      STATUS_FILTERS().map(([v, t]) => option(v, t, (state.status || 'open') === v)));
    const kind = h('select', { class: 'select', onchange: (e) => set({ kind: e.target.value }) },
      option('', 'Любая форма', !state.kind), listOf('kinds').map((k) => option(k.value, k.label, state.kind === k.value)));
    const search = h('input', { class: 'input', type: 'search', placeholder: 'Имя, телефон или №', value: state.q || '' });
    const from = h('input', { class: 'input', type: 'date', value: state.from || '' });
    const to = h('input', { class: 'input', type: 'date', value: state.to || '' });
    const apply = () => set({ q: search.value.trim(), from: from.value, to: to.value });
    search.addEventListener('keydown', (e) => { if (e.key === 'Enter') apply(); });
    from.addEventListener('change', apply);
    to.addEventListener('change', apply);
    const actions = h('div', { class: 'filters__actions' },
      h('button', { class: 'btn btn--ink btn--sm', type: 'button', text: 'Найти', onclick: apply }),
      h('button', { class: 'btn btn--sm', type: 'button', text: 'Сбросить', onclick: () => go('/leads', { base: state.base }) }),
      S.me && S.me.role === 'admin'
        ? h('button', { class: 'btn btn--sm', type: 'button', text: 'Выгрузить в Excel', onclick: () => exportCsv(q) }) : null);
    const filters = h('div', { class: 'tile filters' },
      field('Статус', status), field('Форма', kind), field('Поиск', search), field('С даты', from), field('По дату', to), actions);

    S.main.append(tabs, filters);

    const p = leadParams(q);
    p.set('page', String(page));
    p.set('per_page', '50');
    p.set('sort', '-created_at');
    const data = await api('/leads?' + p.toString());

    if (!data.items.length) {
      S.main.append(h('div', { class: 'tile empty', text: 'Заявок по этим условиям нет' }));
      return;
    }
    const td = (label, ...kids) => h('td', { 'data-label': label }, ...kids);
    const rows = data.items.map((l) => h('tr', {
      class: 'row' + (isLate(l) ? ' row--late' : ''), tabindex: '0',
      onclick: () => go('/leads', { ...state, lead: l.id }),
      onkeydown: (e) => { if (e.key === 'Enter') go('/leads', { ...state, lead: l.id }); }
    },
    td('№', h('span', { class: 'num', text: '№' + l.id })),
    td('Дата', h('span', { class: 'nowrap', text: fmtDate(l.created_at) })),
    td('Порода', l.breed ? l.breed.name : h('span', { class: 'muted', text: 'без породы' })),
    td('Форма', labelOf('kinds', l.kind), l.children_count
      ? h('div', null, h('span', { class: 'tag tag--warn', text: '+' + l.children_count + ' ' + plural(l.children_count, 'повторный', 'повторных', 'повторных') })) : null),
    td('Щенок, окрас', [l.puppy_name, l.colour].filter(Boolean).join(', ') || '—'),
    td('Имя', l.anonymised_at ? h('span', { class: 'muted', text: 'данные удалены' }) : (l.name || '—'),
      l.is_repeat ? h('div', null, h('span', { class: 'tag', text: 'уже обращался' })) : null),
    td('Телефон', h('span', { class: 'nowrap', text: l.phone_display || '—' })),
    td('Куда писать', labelOf('channels', l.channel)),
    td('Статус', chip(l.status)),
    td('Ответственный', l.assignee ? l.assignee.name : h('span', { class: 'muted', text: '—' }))));

    const table = h('table', { class: 'list' },
      h('thead', null, h('tr', null, ['№', 'Дата', 'Порода', 'Форма', 'Щенок, окрас', 'Имя', 'Телефон', 'Куда писать', 'Статус', 'Ответственный']
        .map((t) => h('th', { scope: 'col', text: t })))),
      h('tbody', null, rows));
    const pages = Math.max(1, Math.ceil(data.total / data.per_page));
    const pager = h('div', { class: 'pager' },
      h('span', { class: 'muted', text: 'Найдено ' + data.total + ' · страница ' + page + ' из ' + pages }),
      h('div', { class: 'links' },
        h('button', { class: 'btn btn--sm', type: 'button', text: '← Назад', disabled: page <= 1, onclick: () => go('/leads', { ...state, page: page - 1, lead: '' }) }),
        h('button', { class: 'btn btn--sm', type: 'button', text: 'Дальше →', disabled: page >= pages, onclick: () => go('/leads', { ...state, page: page + 1, lead: '' }) })));
    S.main.append(h('div', { class: 'tile tile--table' }, table), pager);
  }

  async function exportCsv(q) {
    try {
      const r = await api('/export/leads.csv?' + leadParams(q).toString(), { raw: true });
      if (!r.ok) throw new Error('Не получилось выгрузить (' + r.status + ')');
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = h('a', { href: url, download: 'zayavki-' + new Date().toISOString().slice(0, 10) + '.csv' });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      if (!e.silent) toast(e.message);
    }
  }

  /* ---------- карточка заявки ---------- */
  function closeDrawer(silent) {
    if (S.drawer) { S.drawer.remove(); S.drawer = null; }
    if (!silent) {
      const { q } = route();
      if (q.get('lead')) { q.delete('lead'); go('/leads', Object.fromEntries(q.entries())); }
    }
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.drawer) closeDrawer(); });

  const HISTORY = { created: 'Создана', repeat: 'Повторный запрос', status: 'Статус', assignee: 'Ответственный',
    breed: 'Порода', puppy: 'Щенок', next_contact: 'Перезвонить', comment: 'Комментарий', edit: 'Изменение',
    merged: 'Склейка контактов' };

  async function openLead(id) {
    if (!id) return;
    const panel = h('div', { class: 'drawer__panel', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Заявка №' + id },
      h('p', { class: 'muted', text: 'Загружаем заявку…' }));
    const drawer = h('div', { class: 'drawer', onclick: (e) => { if (e.target === drawer) closeDrawer(); } }, panel);
    if (S.drawer) S.drawer.remove();
    S.drawer = drawer;
    document.body.append(drawer);
    let d;
    try {
      d = await api('/leads/' + id);
    } catch (e) {
      if (!e.silent) panel.replaceChildren(notice(e.message, true), h('button', { class: 'btn', type: 'button', text: 'Закрыть', onclick: () => closeDrawer() }));
      return;
    }
    if (S.drawer !== drawer) return;
    panel.replaceChildren(...leadCard(d));
    panel.focus();
  }

  function dl(pairs) {
    return h('dl', { class: 'kv' }, pairs.filter(([, v]) => v != null && v !== '' && v !== false)
      .map(([k, v]) => [h('dt', { text: k }), h('dd', null, v)]));
  }

  function leadCard(d) {
    const anon = !!d.anonymised_at;
    const head = h('div', { class: 'drawer__head' },
      h('div', null, h('h2', { text: 'Заявка №' + d.id }),
        h('div', { class: 'muted small', text: fmtDate(d.created_at) + ' · ' + labelOf('origins', d.origin) }),
        h('div', { class: 'links' }, chip(d.status), d.parent_id
          ? h('button', { class: 'btn btn--sm', type: 'button', text: 'Основная заявка №' + d.parent_id, onclick: () => openFromCard(d.parent_id) }) : null)),
      h('button', { class: 'btn btn--sm drawer__close', type: 'button', text: 'Закрыть', onclick: () => closeDrawer() }));

    const L = d.links || {};
    const person = h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'Кто' }),
      anon ? notice('Данные человека удалены по требованию 152-ФЗ — заявка осталась только в статистике') : dl([
        ['Имя', d.name],
        ['Телефон', d.phone_display],
        ['Куда писать', labelOf('channels', d.channel)],
        ['Обращался раньше', d.is_repeat ? 'да' : null]
      ]),
      anon ? null : h('div', { class: 'links' },
        safeHref(L.tel) ? h('a', { class: 'btn btn--sm btn--ink', href: safeHref(L.tel), text: 'Позвонить' }) : null,
        safeHref(L.whatsapp) ? h('a', { class: 'btn btn--sm', href: safeHref(L.whatsapp), target: '_blank', rel: 'noopener noreferrer', text: 'WhatsApp' }) : null,
        safeHref(L.telegram) ? h('a', { class: 'btn btn--sm', href: safeHref(L.telegram), target: '_blank', rel: 'noopener noreferrer', text: 'Telegram' }) : null));

    const utm = d.utm || {};
    const request = h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'Что хотел' }), dl([
      ['Форма', labelOf('kinds', d.kind)],
      ['Порода', d.breed ? d.breed.name : (d.breed_input ? 'не распознана: ' + d.breed_input : 'не выбрана')],
      ['Щенок', d.puppy_name || d.puppy_slug],
      ['Окрас', d.colour],
      ['Вопрос', (d.details || {}).question],
      ['Пометка формы', d.note],
      ['Заголовок окна', d.form_title],
      ['Страница', d.page_path],
      ['Источник', sourceLabel(d.source, d.medium)],
      ['Кампания', utm.campaign],
      ['Отметки', d.flags && d.flags.length ? d.flags.join(', ') : null],
      ['Причина спама', d.spam_reason],
      ['Согласие', d.consent_version ? d.consent_version + ' · ' + fmtDate(d.consent_at) : null]
    ]));

    const sections = [head, person, request];
    if (!anon) sections.push(workForm(d));

    if (d.children && d.children.length) {
      sections.push(h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'Повторные запросы этого человека' }),
        h('ul', { class: 'mini' }, d.children.map((c) => h('li', null,
          h('button', { type: 'button', text: '№' + c.id, onclick: () => openFromCard(c.id) }),
          ' · ' + fmtDate(c.created_at) + ' · ' + labelOf('kinds', c.kind) + (c.puppy_name ? ' · ' + c.puppy_name : '') + (c.colour ? ' · ' + c.colour : ''))))));
    }
    if (d.other_leads && d.other_leads.length) {
      sections.push(h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'Другие заявки человека' }),
        h('ul', { class: 'mini' }, d.other_leads.map((o) => h('li', null,
          h('button', { type: 'button', text: '№' + o.id, onclick: () => openFromCard(o.id) }),
          ' · ' + fmtDate(o.created_at) + ' · ' + (o.breed ? o.breed.name : 'без породы') + ' · ' + labelOf('kinds', o.kind) + ' · ',
          chip(o.status))))));
    }
    if (d.journey) {
      const j = d.journey;
      sections.push(h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'Что смотрел на сайте до заявки' }), dl([
        ['Первый заход', j.first_seen_at ? fmtDate(j.first_seen_at) + (j.first_landing ? ' · ' + j.first_landing : '') : null],
        ['Откуда пришёл', sourceLabel(j.first_source, j.first_medium)],
        ['Визитов', j.visits ? String(j.visits) : null],
        ['Дней до заявки', j.days_to_request != null ? String(j.days_to_request) : null],
        ['Породы', j.breeds_viewed && j.breeds_viewed.length ? j.breeds_viewed.join(', ') : null],
        ['Щенки', j.puppies_viewed && j.puppies_viewed.length ? j.puppies_viewed.join(', ') : null],
        ['Тест породы', j.quiz && j.quiz.winner ? j.quiz.winner + (j.quiz.second ? ', затем ' + j.quiz.second : '') : null],
        ['Последние страницы', j.pages_before && j.pages_before.length
          ? h('ul', { class: 'mini' }, j.pages_before.map((p) => h('li', { text: fmtDate(p.at) + ' · ' + p.path }))) : null]
      ])));
    }
    sections.push(h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'История' }),
      h('ul', { class: 'feed' }, (d.history || []).slice().reverse().map((x) => h('li', null,
        h('span', { class: 'feed__meta', text: fmtDate(x.at) + ' · ' + x.actor_label }),
        h('span', null, HISTORY[x.action] || x.action,
          x.old_value || x.new_value ? ': ' + historyValue(x.action, x.old_value) + ' → ' + historyValue(x.action, x.new_value) : ''),
        x.comment ? h('span', { class: 'review__text', text: x.comment }) : null)))));
    return sections;
  }
  function historyValue(action, v) {
    if (v == null) return '—';
    if (action === 'status' || action === 'created') return labelOf('statuses', v);
    if (action === 'next_contact' && /^\d{4}-/.test(v)) return fmtDate(v);
    return v;
  }
  function openFromCard(id) {
    const { q } = route();
    go('/leads', { ...Object.fromEntries(q.entries()), lead: id });
  }

  const toLocalInput = (iso) => {
    if (!iso) return '';
    const dt = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return dt.getFullYear() + '-' + pad(dt.getMonth() + 1) + '-' + pad(dt.getDate()) + 'T' + pad(dt.getHours()) + ':' + pad(dt.getMinutes());
  };

  function workForm(d) {
    const msg = h('div');
    const reload = () => openLead(d.id).then(() => loadBreeds().catch(() => {}));
    const fail = (e) => { if (!e.silent) msg.replaceChildren(notice(e.message, true)); };

    const statuses = listOf('statuses').filter((s) => s.value !== 'duplicate' || d.status === 'duplicate');
    const status = h('select', { class: 'select' }, statuses.map((s) => option(s.value, s.label, s.value === d.status)));
    const lost = h('select', { class: 'select' }, option('', 'Выберите причину', !d.lost_reason),
      listOf('lost_reasons').map((r) => option(r.value, r.label, r.value === d.lost_reason)));
    const lostField = field('Причина отказа', lost);
    const amount = h('input', { class: 'input', type: 'number', min: '0', step: '100', inputmode: 'numeric',
                                value: d.sale_amount != null ? String(Number(d.sale_amount)) : '' });
    const amountField = field('Сумма продажи, ₽', amount);
    const next = h('input', { class: 'input', type: 'datetime-local', value: toLocalInput(d.next_contact_at) });
    const assignee = h('select', { class: 'select' }, option('', 'Никто', !d.assignee),
      listOf('managers').map((m) => option(String(m.id), m.name, d.assignee && d.assignee.id === m.id)));
    const sync = () => { lostField.hidden = status.value !== 'lost'; amountField.hidden = status.value !== 'won'; };
    status.addEventListener('change', sync);
    sync();

    const save = h('button', { class: 'btn btn--ink', type: 'button', text: 'Сохранить' });
    save.addEventListener('click', async () => {
      const body = {};
      if (status.value !== d.status) body.status = status.value;
      if (status.value === 'lost' && lost.value !== (d.lost_reason || '')) body.lost_reason = lost.value || null;
      if (status.value === 'won') {
        const v = amount.value === '' ? null : amount.value;
        if (String(v) !== String(d.sale_amount == null ? null : Number(d.sale_amount))) body.sale_amount = v;
      }
      const nextIso = next.value ? new Date(next.value).toISOString() : null;
      const curNext = d.next_contact_at ? new Date(d.next_contact_at).toISOString() : null;
      if (nextIso !== curNext) body.next_contact_at = nextIso;
      const a = assignee.value ? +assignee.value : null;
      if (a !== (d.assignee ? d.assignee.id : null)) body.assignee_id = a;
      if (!Object.keys(body).length) { msg.replaceChildren(notice('Ничего не изменилось')); return; }
      if (body.status === 'lost' && !lost.value) { msg.replaceChildren(notice('Укажите причину отказа', true)); return; }
      save.disabled = true;
      try {
        await api('/leads/' + d.id, { method: 'PATCH', body, version: d.version });
        toast('Сохранено');
        await reload();
      } catch (e) {
        if (e.code === 'version_conflict') { toast('Заявку только что изменил другой менеджер — показываем свежую'); await reload(); }
        else fail(e);
      } finally { save.disabled = false; }
    });

    const take = !d.assignee ? h('button', { class: 'btn', type: 'button', text: 'Взять в работу', onclick: async () => {
      try { await api('/leads/' + d.id + '/take', { method: 'POST' }); toast('Заявка ваша'); await reload(); } catch (e) { fail(e); }
    } }) : null;

    const text = h('textarea', { class: 'textarea', placeholder: 'Например: позвонила, ждёт видео с мамой щенка', maxlength: '4000' });
    const comment = h('button', { class: 'btn', type: 'button', text: 'Добавить комментарий', onclick: async () => {
      if (!text.value.trim()) return;
      try { await api('/leads/' + d.id + '/comments', { method: 'POST', body: { text: text.value.trim() } }); text.value = ''; toast('Комментарий добавлен'); await reload(); } catch (e) { fail(e); }
    } });

    return h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'Работа с заявкой' }),
      h('div', { class: 'work' }, field('Статус', status), lostField, amountField, field('Перезвонить', next), field('Ответственный', assignee)),
      h('div', { class: 'links' }, save, take), msg,
      field('Комментарий', text), h('div', { class: 'links' }, comment));
  }

  /* ---------- отзывы ---------- */
  async function viewReviews(q) {
    stopPolling();
    const st = q.get('status') || 'pending';
    const tabs = h('div', { class: 'tabs', role: 'group', 'aria-label': 'Отзывы по статусу' },
      listOf('review_statuses').map((s) => h('button', {
        class: 'tab', type: 'button', 'aria-pressed': String(st === s.value), onclick: () => go('/reviews', { status: s.value })
      }, h('span', { class: 'tab__name', text: s.label }))));
    S.main.append(tabs);
    const data = await api('/reviews?status=' + encodeURIComponent(st) + '&per_page=100');
    if (!data.items.length) { S.main.append(h('div', { class: 'tile empty', text: 'Здесь пока пусто' })); return; }
    const act = (r, status, label, ask) => h('button', { class: 'btn btn--sm' + (status === 'withdrawn' ? ' btn--danger' : ''), type: 'button', text: label,
      onclick: async () => {
        if (ask && !window.confirm(ask)) return;
        try { await api('/reviews/' + r.id, { method: 'PATCH', body: { status } }); toast('Готово'); render(); } catch (e) { if (!e.silent) toast(e.message); }
      } });
    S.main.append(h('div', { class: 'cards' }, data.items.map((r) => h('article', { class: 'tile review' },
      h('div', null, h('b', { text: r.display_name }), r.city ? ', ' + r.city : '', h('div', { class: 'stars', 'aria-label': 'Оценка ' + r.rating + ' из 5', text: '★'.repeat(r.rating) + '☆'.repeat(5 - r.rating) })),
      h('div', { class: 'muted small', text: fmtDate(r.created_at) + (r.breed ? ' · ' + r.breed.name : '') + (r.name && r.name !== r.display_name ? ' · полное имя: ' + r.name : '') + (r.phone ? ' · ' + fmtPhone(r.phone) : '') }),
      r.text ? h('p', { class: 'review__text', text: r.text }) : h('p', { class: 'muted', text: 'Текст удалён по просьбе автора' }),
      r.spam_reason ? h('span', { class: 'tag tag--warn', text: 'подозрение на спам: ' + r.spam_reason }) : null,
      h('div', { class: 'links' },
        r.status !== 'approved' && r.status !== 'withdrawn' ? act(r, 'approved', 'Опубликовать') : null,
        r.status === 'pending' ? act(r, 'rejected', 'Отклонить') : null,
        r.status !== 'withdrawn' ? act(r, 'withdrawn', 'Снять по просьбе автора', 'Снять отзыв и удалить имя, телефон и текст автора? Это нельзя отменить.') : null)))));
  }

  /* ---------- сводка ---------- */
  async function viewStats(q) {
    stopPolling();
    const today = new Date();
    const iso = (dt) => dt.toISOString().slice(0, 10);
    const from = h('input', { class: 'input', type: 'date', value: q.get('from') || iso(new Date(today.getTime() - 29 * 864e5)) });
    const to = h('input', { class: 'input', type: 'date', value: q.get('to') || iso(today) });
    const apply = () => go('/stats', { from: from.value, to: to.value });
    from.addEventListener('change', apply);
    to.addEventListener('change', apply);
    S.main.append(h('div', { class: 'tile filters' }, field('С даты', from), field('По дату', to)));
    const s = await api('/stats?from=' + from.value + '&to=' + to.value);
    const stat = (num, cap) => h('div', { class: 'tile' }, h('div', { class: 'stat__num', text: String(num) }), h('div', { class: 'muted', text: cap }));
    S.main.append(h('div', { class: 'stats' },
      stat(s.totals.leads, 'заявок'), stat(s.totals.won, 'продано'), stat(s.totals.repeat_requests, 'повторных запросов'),
      stat(duration(s.response.median_minutes), 'обычно ждут первого ответа'),
      stat(s.visits.sessions, 'визитов на сайт'),
      stat(s.visits.conversion != null ? (s.visits.conversion * 100).toFixed(1) + '%' : '—', 'визитов стали заявкой')));
    const bars = (title, rows) => {
      const max = Math.max(1, ...rows.map((r) => r.count));
      return h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: title }),
        rows.length ? h('div', { class: 'bars' }, rows.map((r) => h('div', { class: 'bar' },
          h('span', { text: r.label }),
          h('span', { class: 'bar__track' }, h('span', { class: 'bar__fill', vars: { '--w': (r.count / max * 100).toFixed(1) + '%' } })),
          h('span', { class: 'nowrap', text: String(r.count) })))) : h('p', { class: 'muted', text: 'Нет данных' }));
    };
    S.main.append(
      bars('По породам', s.by_breed.map((b) => ({ label: b.name, count: b.count }))),
      bars('По формам', s.by_kind.map((k) => ({ label: labelOf('kinds', k.kind), count: k.count }))),
      bars('По статусам', s.by_status.map((k) => ({ label: labelOf('statuses', k.status), count: k.count }))),
      bars('Откуда пришли', s.by_source.map((k) => ({ label: sourceLabel(k.source), count: k.count }))));
    // сервер присылает только дни с заявками: дорисовываем пустые, чтобы шкала времени была ровной
    const counts = new Map(s.by_day.map((d) => [d.date, d.count]));
    const daysList = [];
    for (let t = Date.parse(s.period.from + 'T00:00:00Z'), end = Date.parse(s.period.to + 'T00:00:00Z');
      t <= end && daysList.length < 400; t += 864e5) {
      const date = new Date(t).toISOString().slice(0, 10);
      daysList.push({ date, count: counts.get(date) || 0 });
    }
    const maxDay = Math.max(1, ...daysList.map((d) => d.count));
    S.main.append(h('section', { class: 'tile' }, h('h3', { class: 'section-title', text: 'Заявки по дням' }),
      h('div', { class: 'days', role: 'img', 'aria-label': 'Заявки по дням' }, daysList.map((d) => h('span', {
        title: fmtDate(d.date + 'T12:00:00Z', false) + ': ' + d.count, vars: { '--h': (d.count / maxDay * 100).toFixed(1) + '%' } }))),
      daysList.length ? h('div', { class: 'days__axis', 'aria-hidden': 'true' },
        h('span', { text: fmtDate(daysList[0].date + 'T12:00:00Z', false) }),
        h('span', { text: 'максимум ' + maxDay + ' в день' }),
        h('span', { text: fmtDate(daysList[daysList.length - 1].date + 'T12:00:00Z', false) })) : null));
  }

  /* ---------- старт ---------- */
  async function boot() {
    if (!token.get()) return viewLogin();
    try {
      [S.me, S.meta] = await Promise.all([api('/me'), api('/meta')]);
      TZ = S.meta.timezone || TZ;
    } catch (e) {
      if (!e.silent) viewLogin(e.message);
      return;
    }
    S.lastNew = null;
    render();
  }

  boot();
})();
