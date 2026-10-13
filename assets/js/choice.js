/* Puppy House — подбор породы, сравнения, стартовый набор (группа choice). Ванильный JS, без библиотек.
   1. Тест /podbor-porody/: шаги-радиогруппы, прогресс, «Назад», результат без перезагрузки (#rezultat-<порода>).
   2. Чек-лист /magazin/: отметки запоминаются в этом браузере, кнопка «Распечатать».
   Кнопки «Узнать цену» с data-modal-title / -sub / -breed / -note настраивает общая модалка в main.js. */
(() => {
  'use strict';

  const d = document;
  const $ = (sel, ctx = d) => ctx.querySelector(sel);
  const $$ = (sel, ctx = d) => Array.from(ctx.querySelectorAll(sel));
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const scrollBehavior = reduceMotion ? 'auto' : 'smooth';

  // хранилище может быть недоступно (приватный режим, запрет cookies) — страница работает и без него
  const store = {
    get(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { window.localStorage.setItem(key, value); } catch (e) { /* ничего */ } },
    del(key) { try { window.localStorage.removeItem(key); } catch (e) { /* ничего */ } }
  };

  // прокрутить к элементу, если его верх не виден (с учётом липкой шапки)
  const bringIntoView = (el) => {
    const top = el.getBoundingClientRect().top;
    if (top < 80 || top > window.innerHeight * 0.6) {
      window.scrollTo({ top: window.scrollY + top - 96, behavior: scrollBehavior });
    }
  };

  /* ---------- 1. тест ---------- */
  const quiz = $('[data-quiz]');
  if (quiz) {
    const form = $('[data-quiz-form]', quiz);
    const steps = $$('[data-step]', form);
    const countEl = $('[data-quiz-count]', quiz);
    const bar = $('[data-quiz-bar]', quiz);
    const back = $('[data-quiz-back]', quiz);
    const next = $('[data-quiz-next]', quiz);
    const hint = $('[data-quiz-hint]', quiz);
    const result = $('[data-quiz-result]', quiz);
    const order = (quiz.dataset.order || '').split(',');
    const nextHTML = next.innerHTML;
    const lastLabel = next.dataset.last;
    let cur = 0;
    let lastPointer = 0;
    let timer = 0;

    const show = (i, focus) => {
      clearTimeout(timer);
      cur = i;
      steps.forEach((s, k) => { s.hidden = k !== i; });
      countEl.textContent = String(i + 1);
      bar.style.setProperty('--p', String((i + 1) / steps.length));
      back.disabled = i === 0;
      if (i === steps.length - 1) next.textContent = lastLabel; else next.innerHTML = nextHTML;
      hint.textContent = '';
      if (focus) {
        bringIntoView(quiz);
        $('legend', steps[i]).focus({ preventScroll: true });
      }
    };

    const answers = () => {
      const out = {};
      steps.forEach((s) => { out[s.dataset.key] = $('input:checked', s); });
      return out;
    };

    const goNext = () => {
      clearTimeout(timer);
      const step = steps[cur];
      if (!$('input:checked', step)) {
        hint.textContent = quiz.dataset.hint;
        $('input', step).focus();
        return;
      }
      if (cur < steps.length - 1) show(cur + 1, true);
      else finish();
    };

    const section = quiz.closest('section');
    const showResult = (win, second, picked) => {
      form.hidden = true;
      result.hidden = false;
      if (section) section.classList.add('is-done');
      $$('[data-result]', result).forEach((el) => { el.hidden = el.dataset.result !== win; });
      $$('[data-honest]', result).forEach((el) => { el.hidden = el.dataset.honest !== win; });
      const item = $('[data-result="' + win + '"]', result);
      const wi = order.indexOf(win);

      // причины: вопросы, где у этой породы за выбранный ответ ≥ 2 балла, — самые сильные первыми
      const reasons = $$('[data-reason]', item);
      const ranked = picked ? reasons
        .map((li) => {
          const input = picked[li.dataset.reason];
          const score = input ? Number(input.dataset.s.split(',')[wi]) : 0;
          return { li, score };
        })
        .filter((r) => r.score >= 2)
        .sort((x, y) => y.score - x.score)
        .slice(0, 3) : [];
      const useOwn = ranked.length >= 2;
      reasons.forEach((li) => { li.hidden = !useOwn || !ranked.some((r) => r.li === li); });
      $$('[data-reason-default]', item).forEach((li) => { li.hidden = useOwn; });

      // «Тоже может подойти» + ссылка на сравнение именно этой пары
      $$('[data-alt]', result).forEach((el) => {
        el.hidden = el.dataset.alt !== second;
        $$('[data-win]', el).forEach((a) => { a.hidden = a.dataset.win !== win; });
      });
      $('.cho-res__alt', result).hidden = !second;
      $('[data-quiz-allergy]', result).hidden = !(picked && picked.coat && picked.coat.value === 'allergy');

      try { history.replaceState(null, '', '#rezultat-' + win); } catch (e) { /* file:// */ }
      bringIntoView(result);
      $('.cho-res__title', item).focus({ preventScroll: true });
    };

    const finish = () => {
      const picked = answers();
      const totals = order.map(() => 0);
      Object.values(picked).forEach((input) => {
        if (!input) return;
        input.dataset.s.split(',').forEach((v, k) => { totals[k] += Number(v); });
      });
      // при равенстве — порядок пород на сайте
      const ranked = order.map((slug, k) => ({ slug, k, score: totals[k] }))
        .sort((x, y) => y.score - x.score || x.k - y.k);
      showResult(ranked[0].slug, ranked[1].slug, picked);
    };

    const restart = () => {
      form.reset();
      result.hidden = true;
      form.hidden = false;
      if (section) section.classList.remove('is-done');
      try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* file:// */ }
      show(0, true);
    };

    // мышь и палец: выбор варианта сразу ведёт к следующему вопросу; клавиатура — стрелками выбрать, Enter / «Дальше»
    form.addEventListener('pointerdown', (e) => { if (e.target.closest('.cho-opt')) lastPointer = Date.now(); });
    form.addEventListener('click', (e) => {
      const input = e.target.closest('.cho-opt__input');
      if (!input || Date.now() - lastPointer > 1200) return;
      lastPointer = 0;
      hint.textContent = '';
      clearTimeout(timer);
      timer = setTimeout(goNext, reduceMotion ? 0 : 280);
    });
    form.addEventListener('change', () => { hint.textContent = ''; });
    form.addEventListener('submit', (e) => { e.preventDefault(); goNext(); });
    back.addEventListener('click', () => { if (cur > 0) show(cur - 1, true); });
    $$('[data-quiz-restart]', quiz).forEach((b) => b.addEventListener('click', restart));

    // «Пройти тест» в шапке страницы: после прокрутки — фокус на текущий вопрос
    $$('[data-quiz-start]').forEach((a) => a.addEventListener('click', () => {
      if (!result.hidden) return;
      setTimeout(() => $('legend', steps[cur]).focus({ preventScroll: true }), reduceMotion ? 0 : 450);
    }));

    show(0, false);

    // ссылка на результат: /podbor-porody/#rezultat-maltipu
    const m = /^#rezultat-([a-z-]+)$/.exec(location.hash);
    if (m && order.includes(m[1])) showResult(m[1], null, null);
  }

  /* ---------- 2. чек-лист ---------- */
  const list = $('[data-checklist]');
  if (list) {
    const KEY = 'ph-kit-checklist';
    const boxes = $$('input[type="checkbox"]', list);
    let saved = [];
    try { saved = JSON.parse(store.get(KEY) || '[]'); } catch (e) { saved = []; }
    boxes.forEach((b) => { b.checked = Array.isArray(saved) && saved.includes(b.name); });
    list.addEventListener('change', () => {
      const on = boxes.filter((b) => b.checked).map((b) => b.name);
      if (on.length) store.set(KEY, JSON.stringify(on)); else store.del(KEY);
    });
    const print = $('[data-print]', list);
    if (print && typeof window.print === 'function') {
      print.hidden = false;
      print.addEventListener('click', () => window.print());
    }
  }
})();
