/* Puppy House — страница щенка /shchenki/<slug>/.
   1. Галерея: миниатюры меняют большой кадр (фото щенка, родитель, видео по запросу, документы).
   2. Режимы общей модалки main.js: кнопки с data-pp-modal="video | wait | litter" открывают её
      через [data-pup] (как карточка щенка); заголовок, подпись и пометку заявки main.js берёт
      из data-modal-title / -sub / -note кнопки, а здесь меняются кнопка отправки и текст успеха.
   3. Нижняя панель на мобиле: «Узнать цену» открывает модалку этого щенка (если он в наличии),
      иначе — общую с выбранной породой. */
(() => {
  'use strict';

  const d = document;
  const page = d.querySelector('[data-pp]');
  if (!page) return;

  const $ = (sel, ctx = d) => ctx.querySelector(sel);
  const $$ = (sel, ctx = d) => Array.from(ctx.querySelectorAll(sel));
  const breed = page.dataset.ppBreed;
  const status = page.dataset.ppStatus;

  /* ---------- 1. галерея ---------- */
  const stage = $('[data-pp-stage]', page);
  const thumbs = $$('[data-pp-thumb]', page);
  if (stage && thumbs.length) {
    const img = $('[data-pp-img]', stage);
    const cap = $('[data-pp-cap]', stage);
    const play = $('[data-pp-play]', stage);
    const pill = $('[data-pp-status-pill]', stage);
    const show = (btn) => {
      const src = $('img', btn).getAttribute('src');
      const kind = btn.dataset.kind;
      thumbs.forEach((t) => t.setAttribute('aria-pressed', String(t === btn)));
      if (img.getAttribute('src') !== src) {
        const t = $('img', btn);
        img.src = src;
        img.width = t.width; img.height = t.height;
      }
      img.alt = btn.dataset.alt || '';
      img.style.objectPosition = btn.dataset.pos || '';
      stage.className = stage.className.replace(/\bpp-stage--\w+/g, '').trim() + ' pp-stage--' + kind;
      cap.textContent = btn.dataset.cap || '';
      cap.hidden = !btn.dataset.cap;
      play.hidden = kind !== 'video';
      if (pill) pill.hidden = kind !== 'photo';
    };
    thumbs.forEach((btn) => btn.addEventListener('click', () => show(btn)));
    // стрелки влево / вправо между миниатюрами
    thumbs.forEach((btn, i) => btn.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      e.preventDefault();
      const next = thumbs[(i + (e.key === 'ArrowRight' ? 1 : thumbs.length - 1)) % thumbs.length];
      next.focus();
      show(next);
    }));
  }

  /* ---------- 2. режимы модалки ---------- */
  const modal = $('#price-modal');
  const form = $('#price-form');
  if (!modal || !form) return;
  const submit = $('[data-submit]', form);
  const doneText = $('#pm-done-text');
  const breedSelect = $('#pm-breed');
  const breedField = $('[data-pm-breed]', modal);
  const DEFAULT_LABEL = submit.dataset.label;
  const CONTACT = { telegram: 'Telegram', whatsapp: 'WhatsApp' };
  const NIGHT = ' Ночью — утром, после 9:00.';

  const MODES = {
    video: {
      label: 'Записаться на звонок',
      done: (c) => (c === 'call'
        ? 'Куратор позвонит в течение 15 минут и договорится о времени видеозвонка.'
        : 'Куратор напишет в ' + CONTACT[c] + ' в течение 15 минут и предложит время видеозвонка.') + NIGHT
    },
    wait: {
      label: 'Записаться',
      done: (c) => (c === 'call'
        ? 'Вы в листе ожидания. Куратор позвонит, когда откроем бронь.'
        : 'Вы в листе ожидания. Куратор напишет в ' + CONTACT[c] + ', когда откроем бронь.') + NIGHT
    },
    litter: {
      label: 'Узнать о помёте',
      done: (c) => (c === 'call'
        ? 'Куратор позвонит, как только появятся новые щенки.'
        : 'Куратор напишет в ' + CONTACT[c] + ', как только появятся новые щенки.') + NIGHT
    }
  };
  let mode = null;

  const setLabel = (text) => { submit.dataset.label = text; submit.textContent = text; };

  // main.js открывает модалку своим обработчиком на document; этот зарегистрирован позже и срабатывает после него
  d.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-open-modal]');
    if (!trigger || !modal.open) return;
    const m = MODES[trigger.dataset.ppModal];
    mode = m || null;
    setLabel(m ? m.label : (trigger.dataset.modalSubmit || DEFAULT_LABEL));
    // общая заявка (без щенка, кнопки шапки и меню) — порода этой страницы уже выбрана
    if (breedField && !breedField.hidden && breedSelect && !trigger.dataset.modalBreed) breedSelect.value = breed;
  });

  // текст успеха: main.js пишет свой, для режимов заменяем его
  if (doneText && 'MutationObserver' in window) {
    let own = '';
    new MutationObserver(() => {
      if (!mode || doneText.textContent === own) return;
      const c = form.querySelector('input[name="contact"]:checked');
      own = mode.done(c ? c.value : 'telegram');
      doneText.textContent = own;
    }).observe(doneText, { childList: true, characterData: true, subtree: true });
  }

  /* ---------- 3. нижняя панель на мобиле ---------- */
  const mainBtn = $('[data-pp-main]', page);
  if (status === 'available' && mainBtn) {
    let back = null;
    let y = 0;
    // перехват до обработчика main.js: открываем модалку этого щенка
    d.addEventListener('click', (e) => {
      const btn = e.target.closest('.mbar [data-open-modal]');
      if (!btn) return;
      e.stopPropagation();
      e.preventDefault();
      back = btn;
      y = window.scrollY;
      mainBtn.click();
    }, true);
    // main.js вернёт фокус на кнопку щенка вверху страницы — возвращаем на панель и на прежнее место
    modal.addEventListener('close', () => {
      if (!back) return;
      const b = back;
      back = null;
      window.scrollTo({ top: y, behavior: 'instant' });
      if (b.offsetParent !== null) b.focus({ preventScroll: true });
    });
  }
})();
