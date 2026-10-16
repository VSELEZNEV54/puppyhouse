/* домщенков.рф — страница щенка /shchenki/<slug>/.
   1. Галерея: лента [data-carousel] листает main.js (стрелки, свайп, ← →, лайтбокс по нажатию на кадр).
      Здесь — миниатюры (нажатие → этот кадр), счётчик «2 / 9» и один шаг табуляции на ленту
      (кнопка активного кадра в порядке табуляции, остальные — -1; ← → переводят фокус, main.js).
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
  const breed = page.dataset.breed; // slug породы: значения в списке пород — slug (forms.breed_options)
  const status = page.dataset.ppStatus;
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 1. галерея ---------- */
  const car = $('[data-pp-car]', page);
  if (car) {
    const vp = $('[data-carousel-viewport]', car);
    const slides = $$('.media-carousel__item', car);
    const thumbs = $$('[data-pp-thumb]', car);
    const count = $('[data-pp-count]', car);
    let current = -1;
    const sync = () => {
      const i = Math.max(0, slides.findIndex((li) => li.classList.contains('is-active')));
      if (i === current) return;
      current = i;
      slides.forEach((li, k) => { const b = $('[data-lightbox]', li); if (b) b.tabIndex = k === i ? 0 : -1; });
      thumbs.forEach((t, k) => t.classList.toggle('is-on', k === i));
      if (count) count.textContent = String(i + 1);
    };
    if ('MutationObserver' in window) {
      new MutationObserver(sync).observe(vp, { subtree: true, attributes: true, attributeFilter: ['class'] });
    }
    // нажатие на миниатюру — лента едет к этому кадру (main.js по прокрутке отметит его активным)
    thumbs.forEach((t) => t.addEventListener('click', () => {
      const li = slides[Number(t.dataset.ppThumb)];
      if (!li || !vp) return;
      const dx = li.getBoundingClientRect().left - vp.getBoundingClientRect().left;
      vp.scrollBy({ left: dx, behavior: reduceMotion ? 'auto' : 'smooth' });
    }));
    sync();
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
  const CONTACT = { telegram: 'Telegram', whatsapp: 'WhatsApp', max: 'MAX' };
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
    if (breedField && !breedField.hidden && breedSelect && breed && !trigger.dataset.modalBreed) breedSelect.value = breed;
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
