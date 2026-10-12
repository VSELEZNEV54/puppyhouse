/* Puppy House — вариант C «Editorial премиум». Vanilla JS, без зависимостей. */
(function () {
  'use strict';

  var doc = document.documentElement;
  doc.classList.add('js');

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

  function plural(n, forms) {
    var a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return forms[2];
    if (b > 1 && b < 5) return forms[1];
    if (b === 1) return forms[0];
    return forms[2];
  }

  /* ---------- Scroll lock (menu / modal) ---------- */
  var locks = 0;
  function lock() { locks++; doc.classList.add('is-locked'); }
  function unlock() { locks = Math.max(0, locks - 1); if (!locks) doc.classList.remove('is-locked'); }

  /* ---------- Toast for not-yet-built pages ---------- */
  var toastEl = $('[data-toast]');
  var toastTimer;
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('is-on'); }, 2800);
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href^="/"]');
    if (!a || e.defaultPrevented) return;
    e.preventDefault();
    toast('Раздел появится на следующем этапе');
  });

  /* ---------- In-page anchors: smooth scroll (instant with reduced motion) ---------- */
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href^="#"]');
    if (!a || e.defaultPrevented) return;
    var id = a.getAttribute('href').slice(1);
    var target = id ? document.getElementById(id) : null;
    if (!target) return;
    e.preventDefault();
    var top = id === 'top' ? 0 : target.getBoundingClientRect().top + window.scrollY - (window.innerWidth < 768 ? 68 : 76);
    window.scrollTo({ top: Math.max(0, top), behavior: reduceMotion.matches ? 'auto' : 'smooth' });
    if (history.replaceState) history.replaceState(null, '', '#' + id);
    // move focus for keyboard / screen reader users without a second jump
    if (id !== 'top') {
      if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });
    }
  });

  /* ---------- Header: transparent over hero → cream on scroll ---------- */
  var hdr = $('[data-header]');
  function onScrollHeader() {
    if (!hdr) return;
    hdr.classList.toggle('is-solid', window.scrollY > 24);
  }
  onScrollHeader();
  window.addEventListener('scroll', onScrollHeader, { passive: true });

  /* ---------- Dropdown «Породы» ---------- */
  var dd = $('[data-dd]');
  var ddBtn = dd && $('[data-dd-btn]', dd);
  var ddTimer, ddHoverAt = 0;
  function setDD(open) {
    if (!dd) return;
    dd.classList.toggle('is-open', open);
    ddBtn.setAttribute('aria-expanded', String(open));
  }
  if (dd) {
    ddBtn.addEventListener('click', function () {
      var open = ddBtn.getAttribute('aria-expanded') === 'true';
      // a click right after hover-open should not immediately close it
      if (open && Date.now() - ddHoverAt < 500) return;
      setDD(!open);
    });
    dd.addEventListener('mouseenter', function () {
      if (!finePointer.matches) return;
      clearTimeout(ddTimer);
      if (ddBtn.getAttribute('aria-expanded') !== 'true') { ddHoverAt = Date.now(); setDD(true); }
    });
    dd.addEventListener('mouseleave', function () {
      if (!finePointer.matches) return;
      ddTimer = setTimeout(function () { setDD(false); }, 220);
    });
    dd.addEventListener('focusout', function (e) { if (!dd.contains(e.relatedTarget)) setDD(false); });
    document.addEventListener('click', function (e) { if (!dd.contains(e.target)) setDD(false); });
  }

  /* ---------- Focus trap helper ---------- */
  function trap(container, e) {
    if (e.key !== 'Tab') return;
    var f = $$('a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])', container)
      .filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  /* ---------- Mobile menu ---------- */
  var menu = $('[data-menu]');
  var burger = $('[data-burger]');
  var menuReturn = null, menuCloseTimer;
  function openMenu() {
    if (!menu) return;
    clearTimeout(menuCloseTimer);
    menuReturn = document.activeElement;
    menu.hidden = false;
    // force reflow so the transition runs
    void menu.offsetWidth;
    menu.classList.add('is-open');
    burger.setAttribute('aria-expanded', 'true');
    lock();
    var x = $('[data-menu-close]', menu);
    if (x) x.focus();
  }
  function closeMenu(restoreFocus) {
    if (!menu || menu.hidden) return;
    menu.classList.remove('is-open');
    burger.setAttribute('aria-expanded', 'false');
    unlock();
    menuCloseTimer = setTimeout(function () { menu.hidden = true; }, reduceMotion.matches ? 0 : 320);
    if (restoreFocus !== false && menuReturn && menuReturn.focus) menuReturn.focus();
  }
  if (menu && burger) {
    burger.addEventListener('click', openMenu);
    $('[data-menu-close]', menu).addEventListener('click', function () { closeMenu(); });
    menu.addEventListener('keydown', function (e) { trap(menu, e); });
    // in-page anchors close the menu
    menu.addEventListener('click', function (e) {
      var a = e.target.closest('a[href^="#"]');
      if (a) closeMenu(false);
    });
    var subBtn = $('[data-sub-btn]', menu);
    if (subBtn) {
      subBtn.addEventListener('click', function () {
        var open = subBtn.getAttribute('aria-expanded') === 'true';
        subBtn.setAttribute('aria-expanded', String(!open));
        document.getElementById(subBtn.getAttribute('aria-controls')).hidden = open;
      });
    }
    // leaving mobile layout closes the menu
    window.matchMedia('(min-width: 1200px)').addEventListener('change', function (m) { if (m.matches) closeMenu(false); });
  }

  /* ---------- Tooltip (chip «Метрика РКФ») ---------- */
  $$('[data-tip]').forEach(function (tip) {
    var btn = $('[data-tip-btn]', tip);
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var open = !tip.classList.contains('is-open');
      tip.classList.toggle('is-open', open);
      btn.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', function (e) {
      if (!tip.contains(e.target)) { tip.classList.remove('is-open'); btn.setAttribute('aria-expanded', 'false'); }
    });
  });
  function closeTips() {
    $$('[data-tip].is-open').forEach(function (t) { t.classList.remove('is-open'); $('[data-tip-btn]', t).setAttribute('aria-expanded', 'false'); });
  }

  /* ---------- Esc closes overlays (modal closes natively via <dialog>) ---------- */
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    if (menu && !menu.hidden) { closeMenu(); return; }
    if (dd && dd.classList.contains('is-open')) { setDD(false); ddBtn.focus(); return; }
    closeTips();
  });

  /* ---------- Puppy filter ---------- */
  var tabs = $$('[data-filter]');
  var cards = $$('[data-pup]');
  var grid = $('[data-pups-grid]');
  var emptyBox = $('[data-pups-empty]');
  var countEl = $('[data-pups-count]');
  var currentFilter = 'all';
  function applyFilter(f) {
    currentFilter = f;
    var shown = 0;
    tabs.forEach(function (t) { t.setAttribute('aria-pressed', String(t.dataset.filter === f)); });
    cards.forEach(function (c) {
      var on = f === 'all' || c.dataset.breed === f;
      c.hidden = !on;
      c.classList.remove('is-shown');
      if (on) {
        if (!reduceMotion.matches) {
          void c.offsetWidth;
          c.style.setProperty('--i', (shown * 0.05) + 's');
          c.classList.add('is-shown');
        }
        shown++;
      }
    });
    if (emptyBox) emptyBox.hidden = shown > 0;
    if (grid) { grid.hidden = shown === 0; grid.scrollLeft = 0; }
    if (countEl) countEl.textContent = shown + ' ' + plural(shown, ['щенок', 'щенка', 'щенков']);
  }
  tabs.forEach(function (t) { t.addEventListener('click', function () { applyFilter(t.dataset.filter); }); });

  /* ---------- Phone mask +7 (___) ___-__-__ ---------- */
  function formatPhone(d) {
    var s = '+7 (' + d.slice(0, 3);
    if (d.length >= 4) s += ') ' + d.slice(3, 6);
    if (d.length >= 7) s += '-' + d.slice(6, 8);
    if (d.length >= 9) s += '-' + d.slice(8, 10);
    return s;
  }
  function phoneDigits(v) {
    var d = String(v || '').replace(/\D/g, '');
    if (/^\s*\+7/.test(v)) d = d.slice(1);
    if (d.length > 10 && /^[78]/.test(d)) d = d.slice(1);
    return d.slice(0, 10);
  }
  $$('[data-phone]').forEach(function (input) {
    var prev = '';
    input.addEventListener('focus', function () {
      if (!input.value) { input.value = '+7 ('; prev = ''; }
      requestAnimationFrame(function () { var n = input.value.length; try { input.setSelectionRange(n, n); } catch (err) { /* noop */ } });
    });
    input.addEventListener('blur', function () { if (!phoneDigits(input.value).length) input.value = ''; });
    input.addEventListener('input', function (e) {
      var d = phoneDigits(input.value);
      // deleting a mask symbol (")", " ", "-") should delete the digit before it
      if (e.inputType && e.inputType.indexOf('delete') === 0 && d === prev && d.length) d = d.slice(0, -1);
      prev = d;
      input.value = formatPhone(d);
      var n = input.value.length;
      try { input.setSelectionRange(n, n); } catch (err) { /* noop */ }
      if (input.getAttribute('aria-invalid') === 'true' && d.length === 10) clearErr(input);
    });
  });

  /* ---------- Forms: validation + fake submit ---------- */
  var METHOD = { telegram: 'Telegram', whatsapp: 'WhatsApp', max: 'MAX', call: 'call' };

  function errEl(field) {
    var id = (field.getAttribute('aria-describedby') || '').split(' ')[0];
    return id ? document.getElementById(id) : null;
  }
  function setErr(field, msg) {
    var el = errEl(field);
    field.setAttribute('aria-invalid', 'true');
    if (field.tagName === 'FIELDSET') field.classList.add('is-invalid');
    if (el) { el.textContent = msg; el.hidden = false; }
  }
  function clearErr(field) {
    var el = errEl(field);
    field.removeAttribute('aria-invalid');
    if (field.tagName === 'FIELDSET') field.classList.remove('is-invalid');
    if (el) { el.textContent = ''; el.hidden = true; }
  }

  function validate(form) {
    var firstBad = null;
    var name = form.elements.name;
    var phone = form.elements.phone;
    var consent = form.elements.consent;
    var set = $('fieldset', form);
    var method = $('input[name="method"]:checked', form);

    if (!name.value.trim()) { setErr(name, 'Напишите, как к вам обращаться'); firstBad = firstBad || name; } else clearErr(name);
    if (phoneDigits(phone.value).length !== 10) { setErr(phone, 'Проверьте номер: после +7 нужно 10 цифр'); firstBad = firstBad || phone; } else clearErr(phone);
    if (!method) { setErr(set, 'Выберите, куда вам написать'); firstBad = firstBad || $('input[name="method"]', form); } else clearErr(set);
    if (!consent.checked) { setErr(consent, 'Без согласия на обработку данных мы не сможем отправить заявку'); firstBad = firstBad || consent; } else clearErr(consent);

    if (firstBad) firstBad.focus();
    return !firstBad;
  }

  function resetForm(form) {
    form.reset();
    $$('[aria-invalid]', form).forEach(clearErr);
    $$('fieldset', form).forEach(clearErr);
    var btn = $('[data-submit]', form);
    if (btn) { btn.disabled = false; btn.querySelector('span').textContent = btn.dataset.label || btn.querySelector('span').textContent; }
  }

  $$('form[data-form]').forEach(function (form) {
    var btn = $('[data-submit]', form);
    btn.dataset.label = btn.querySelector('span').textContent;
    // live-clear errors
    form.addEventListener('input', function (e) {
      var t = e.target;
      if (t.name === 'name' && t.value.trim()) clearErr(t);
    });
    form.addEventListener('change', function (e) {
      var t = e.target;
      if (t.name === 'method') clearErr($('fieldset', form));
      if (t.name === 'consent' && t.checked) clearErr(t);
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!validate(form)) return;
      btn.disabled = true;
      btn.querySelector('span').textContent = 'Отправляем…';
      var data = {
        name: form.elements.name.value.trim(),
        method: $('input[name="method"]:checked', form).value
      };
      setTimeout(function () { onSent(form, data); }, 900);
    });
  });

  function onSent(form, data) {
    var m = METHOD[data.method];
    if (form.dataset.form === 'order') {
      var wrap = form.parentElement;
      var done = $('[data-done]', wrap);
      $('[data-done-text]', done).textContent = m === 'call'
        ? 'Спасибо, ' + data.name + '. Куратор позвонит вам в течение 15 минут, а если сейчас поздний вечер — утром. Пока ждёте, почитайте, что говорят владельцы наших щенков.'
        : 'Спасибо, ' + data.name + '. Куратор напишет вам в ' + m + ' в течение 15 минут, а если сейчас поздний вечер — утром. Пока ждёте, почитайте, что говорят владельцы наших щенков.';
      form.hidden = true;
      done.hidden = false;
      done.classList.add('is-in-done');
      done.focus();
    } else {
      var viewForm = $('[data-view="form"]', modal);
      var viewDone = $('[data-view="done"]', modal);
      $('[data-done-title]', viewDone).textContent = 'Спасибо, ' + data.name;
      $('[data-done-text]', viewDone).textContent = m === 'call'
        ? 'Куратор позвонит вам в течение 15 минут. Ночью — утром, после 9:00.'
        : 'Куратор пришлёт цену и видео в ' + m + ' в течение 15 минут. Ночью — утром, после 9:00.';
      viewForm.hidden = true;
      viewDone.hidden = false;
      viewDone.classList.add('is-in-done');
      modal.setAttribute('aria-labelledby', 'pm-done-title');
      viewDone.focus();
    }
  }

  /* ---------- Modal «Узнать цену» ---------- */
  var modal = $('#price-modal');
  var modalReturn = null;
  if (modal) {
    var mForm = $('#price-form');
    var mTitle = $('#pm-title');
    var mSub = $('#pm-sub');
    var mThumb = $('[data-pm-thumb]', modal);
    var mBreed = $('[data-pm-breed]', modal);
    var doneTitle = $('[data-done-title]', modal);
    doneTitle.id = 'pm-done-title';

    var openModal = function (opts) {
      opts = opts || {};
      modalReturn = document.activeElement;
      resetForm(mForm);
      $('[data-view="form"]', modal).hidden = false;
      $('[data-view="done"]', modal).hidden = true;
      modal.setAttribute('aria-labelledby', 'pm-title');

      if (opts.name) {
        mTitle.textContent = 'Узнать цену: ' + opts.name;
        mSub.textContent = opts.kind + ', ' + opts.age + '. Пришлём цену, видео и условия брони в удобный мессенджер. Это ни к чему не обязывает.';
        mForm.elements.puppy.value = opts.name + ' — ' + opts.kind + ', ' + opts.age;
        mBreed.hidden = true;
        if (opts.img) {
          var im = $('img', mThumb);
          if (!im) {
            im = document.createElement('img');
            im.width = 80; im.height = 100; im.alt = '';
            mThumb.appendChild(im);
          }
          im.src = opts.img.currentSrc || opts.img.src;
          mThumb.style.setProperty('--bg', opts.bg || '');
          mThumb.hidden = false;
        }
      } else {
        mTitle.textContent = 'Узнать цену щенка';
        mSub.textContent = 'Расскажите, какая порода интересует, — пришлём щенков в наличии с ценами и видео.';
        mForm.elements.puppy.value = '';
        mBreed.hidden = false;
        mThumb.hidden = true;
        if (opts.breed) mForm.elements.breed.value = opts.breed;
      }
      if (menu && !menu.hidden) closeMenu(false);
      modal.showModal();
      lock();
      requestAnimationFrame(function () { $('#pm-name').focus(); });
    };

    modal.addEventListener('close', function () {
      unlock();
      if (modalReturn && modalReturn.focus && document.contains(modalReturn)) modalReturn.focus();
    });
    modal.addEventListener('click', function (e) { if (e.target === modal) modal.close(); });
    modal.addEventListener('keydown', function (e) { trap(modal, e); });
    $$('[data-modal-close]', modal).forEach(function (b) { b.addEventListener('click', function () { modal.close(); }); });

    var BREED_BY_FILTER = { 'maltipu': 'Мальтипу', 'francuzskij-buldog': 'Французский бульдог', 'toj-pudel': 'Той-пудель', 'border-kolli': 'Бордер-колли' };

    document.addEventListener('click', function (e) {
      var priceBtn = e.target.closest('[data-price]');
      if (priceBtn) {
        var card = priceBtn.closest('[data-pup]');
        var media = $('.pup__media', card);
        openModal({
          name: card.dataset.name, kind: card.dataset.kind, age: card.dataset.age,
          img: $('img', card), bg: media ? getComputedStyle(media).getPropertyValue('--bg') : ''
        });
        return;
      }
      var generic = e.target.closest('[data-open-modal]');
      if (generic) {
        var inEmpty = generic.closest('[data-pups-empty]');
        openModal({ breed: inEmpty ? BREED_BY_FILTER[currentFilter] : '' });
      }
    });
  }

  /* ---------- FAQ accordion ---------- */
  $$('[data-acc-btn]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      var panel = document.getElementById(btn.getAttribute('aria-controls'));
      if (panel) panel.classList.toggle('is-open', !open);
    });
  });

  /* ---------- SEO «Читать полностью» ---------- */
  var seoBtn = $('[data-seo-btn]');
  var seoMore = $('[data-seo-more]');
  function setSeo(open, scroll) {
    seoBtn.setAttribute('aria-expanded', String(open));
    seoBtn.querySelector('span').textContent = open ? 'Свернуть' : 'Читать полностью';
    if (open) { seoMore.removeAttribute('hidden'); seoMore.classList.add('is-showing'); }
    else {
      seoMore.setAttribute('hidden', 'until-found');
      seoMore.classList.remove('is-showing');
      if (scroll) {
        var sec = seoBtn.closest('section');
        if (sec && sec.getBoundingClientRect().top < 0) sec.scrollIntoView({ behavior: reduceMotion.matches ? 'auto' : 'smooth', block: 'start' });
      }
    }
  }
  if (seoBtn && seoMore) {
    seoBtn.addEventListener('click', function () { setSeo(seoBtn.getAttribute('aria-expanded') !== 'true', true); });
    seoMore.addEventListener('beforematch', function () { setSeo(true, false); });
  }

  /* ---------- Reviews carousel ---------- */
  $$('[data-carousel]').forEach(function (root) {
    var track = $('[data-track]', root);
    var prev = $('[data-prev]', root);
    var next = $('[data-next]', root);
    if (!track || !prev || !next) return;
    var step = function () {
      var first = track.firstElementChild;
      return first ? first.getBoundingClientRect().width + 6 : track.clientWidth * 0.8;
    };
    var update = function () {
      var max = track.scrollWidth - track.clientWidth - 2;
      prev.disabled = track.scrollLeft <= 2;
      next.disabled = track.scrollLeft >= max;
    };
    prev.addEventListener('click', function () { track.scrollBy({ left: -step(), behavior: reduceMotion.matches ? 'auto' : 'smooth' }); });
    next.addEventListener('click', function () { track.scrollBy({ left: step(), behavior: reduceMotion.matches ? 'auto' : 'smooth' }); });
    track.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update);
    update();
  });

  /* ---------- Reveal on scroll ---------- */
  var reveals = $$('[data-reveal]');
  if (!reduceMotion.matches && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('is-in'); io.unobserve(en.target); }
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.06 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add('is-in'); });
  }

  /* ---------- Subtle hero parallax (transform only) ---------- */
  var px = $('[data-parallax]');
  if (px) {
    var ticking = false;
    var runPx = function () {
      ticking = false;
      if (reduceMotion.matches) { px.style.transform = ''; return; }
      var h = px.parentElement.clientHeight;
      var y = Math.min(window.scrollY * 0.06, h * 0.045);
      px.style.transform = 'translate3d(0,' + y.toFixed(1) + 'px,0) scale(1.1)';
    };
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; requestAnimationFrame(runPx); }
    }, { passive: true });
    reduceMotion.addEventListener('change', runPx);
  }
})();
