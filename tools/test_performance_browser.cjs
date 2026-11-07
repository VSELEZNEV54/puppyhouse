#!/usr/bin/env node
/* Browser regression checks for the production build. Requires Playwright and Chromium.
   Build first, serve the repository, then run:
     node tools/test_performance_browser.cjs http://127.0.0.1:8766
   CHROME_PATH and PERFORMANCE_ARTIFACTS override the browser/output paths.
   No real forms are submitted; all requests stay on the local test origin. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const base = new URL(process.argv[2] || 'http://127.0.0.1:8766');
if (!['localhost', '127.0.0.1', '[::1]'].includes(base.hostname)) {
  throw new Error('Use a local preview: these tests intentionally delay and abort requests.');
}
const artifacts = process.env.PERFORMANCE_ARTIFACTS || '/workspace/artifacts/pagespeed';
fs.mkdirSync(artifacts, { recursive: true });
const results = [];
const heroRequest = url => /\/assets\/img\/(?:responsive\/)?hero-four-breeds[^/]*\.(jpg|webp)(?:\?|$)/.test(url);

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  async function test(name, options, run) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, ...options });
    // Analytics and API calls are never sent to a production service from this test.
    await context.route('**/*', route => new URL(route.request().url()).origin === base.origin ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const start = Date.now();
    try {
      await run(page, context);
      assert.deepEqual(errors, [], 'No uncaught JavaScript errors');
      results.push({ name, passed: true, durationMs: Date.now() - start });
      console.log(`PASS ${name}`);
    } catch (error) {
      results.push({ name, passed: false, durationMs: Date.now() - start, error: error.message, pageErrors: errors });
      await page.screenshot({ path: path.join(artifacts, `failure-${name}.png`) }).catch(() => {});
      console.error(`FAIL ${name}: ${error.message}`);
    } finally { await context.close(); }
  }
  async function ready(page, route = '/', checkLayout = true) {
    await page.goto(new URL(route, base).href, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => !document.documentElement.classList.contains('site-loading') && !document.documentElement.classList.contains('site-revealing'));
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), false);
    assert.equal(await page.locator('h1').count(), 1);
    assert.equal(await page.locator('h1').evaluate(el => {
      for (let node = el; node; node = node.parentElement) if (Number(getComputedStyle(node).opacity) < .99) return false;
      return true;
    }), true, 'First-screen heading is already visible when loading finishes');
    if (checkLayout) assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No horizontal document overflow');
  }
  async function closeCookies(page) {
    const button = page.locator('[data-cookie-choice="necessary"]');
    if (await button.isVisible()) await button.click();
  }

  async function assertLoaderPresentation(page) {
    assert.equal(await page.locator('#site-loader').innerText(), 'Подождите, сайт загружается');
    assert.equal(await page.locator('#site-loader button, #site-loader a, #site-loader input, #site-loader select, #site-loader textarea, #site-loader [tabindex]').count(), 0, 'Automatic loading screen has no manual controls');
  }

  await test('loader-progress-and-lazy-images', {}, async page => {
    let releaseHero;
    const heroGate = new Promise(resolve => { releaseHero = resolve; });
    let blockedLazy = 0;
    await page.route('**/*', async route => {
      const url = route.request().url();
      if (heroRequest(url)) { await heroGate; await route.continue().catch(() => {}); }
      else if (route.request().resourceType() === 'image' && /\/assets\/img\//.test(url)) { blockedLazy++; /* held until context closes */ }
      else await route.fallback();
    });
    await page.goto(base.href, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.documentElement.classList.contains('site-loading') && parseFloat(document.getElementById('site-loader').style.getPropertyValue('--loaded')) >= .2);
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), true);
    const progress = await page.locator('#site-loader').evaluate(el => parseFloat(el.style.getPropertyValue('--loaded')));
    assert.ok(progress >= .2 && progress < 1, `Paw shows partial progress (${progress}) while hero is pending`);
    await assertLoaderPresentation(page);
    await page.screenshot({ path: path.join(artifacts, 'paw-loader-mobile.png') });
    const releasedAt = Date.now();
    releaseHero();
    await page.waitForFunction(() => !document.documentElement.classList.contains('site-loading'), null, { timeout: 2000 });
    assert.ok(Date.now() - releasedAt < 2000, 'Hero completion reveals the page without waiting for lazy images');
    assert.ok(blockedLazy > 0, 'At least one below-fold image was pending during reveal');
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), false);
    await page.evaluate(() => window.__siteReady);
  });

  await test('responsive-hero-preload-is-reused', { viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75 }, async page => {
    const requests = [];
    page.on('request', request => { if (heroRequest(request.url())) requests.push(request.url()); });
    await ready(page);
    const hero = await page.locator('main img[fetchpriority="high"]').first().evaluate(img => ({ src: img.currentSrc, srcset: img.srcset, sizes: img.sizes }));
    const preload = await page.locator('link[rel="preload"][as="image"]').first().evaluate(link => ({ srcset: link.imageSrcset, sizes: link.imageSizes }));
    assert.equal(preload.srcset, hero.srcset, 'Preload and hero use the same responsive candidates');
    assert.equal(preload.sizes, hero.sizes, 'Preload selects the same viewport size as the rendered hero');
    assert.deepEqual(requests, [hero.src], 'One selected WebP request serves both preload and hero; no duplicate JPEG');
    assert.match(hero.src, /\.webp(?:\?|$)/);
  });

  await test('loader-waits-for-deferred-controls', {}, async page => {
    let releaseScript;
    const scriptGate = new Promise(resolve => { releaseScript = resolve; });
    let held = false;
    await page.route('**/*', async route => {
      if (route.request().resourceType() === 'script' && /\/main(?:\.[a-f0-9]+)?(?:\.min)?\.js(?:\?|$)/.test(route.request().url())) {
        held = true;
        await scriptGate;
        await route.continue().catch(() => {});
      } else await route.fallback();
    });
    await page.goto(base.href, { waitUntil: 'commit' });
    await page.waitForFunction(() => {
      const hero = document.querySelector('main img[fetchpriority="high"]');
      const loader = document.getElementById('site-loader');
      return hero && hero.complete && hero.naturalWidth && loader && parseFloat(loader.style.getPropertyValue('--loaded')) > .2;
    });
    assert.ok(held, 'Deferred control script was held while the hero completed');
    assert.equal(await page.evaluate(() => document.readyState), 'interactive', 'Parser finished while DOMContentLoaded still waits for defer');
    await page.waitForTimeout(250);
    assert.equal(await page.evaluate(() => document.documentElement.classList.contains('site-loading')), true, 'Ready hero alone cannot reveal nonworking controls');
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), true);
    releaseScript();
    await page.waitForFunction(() => !document.documentElement.classList.contains('site-loading'), null, { timeout: 2000 });
    await page.waitForLoadState('domcontentloaded');
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), false);
    await closeCookies(page);
    await page.locator('[data-burger]').click();
    assert.equal(await page.locator('#mmenu').isVisible(), true, 'Controls work as soon as automatic loading finishes');
  });

  await test('hero-error-does-not-trap-page', {}, async page => {
    await page.route('**/*', route => heroRequest(route.request().url()) ? route.abort() : route.fallback());
    await ready(page);
    assert.equal(await page.locator('#site-loader').isVisible(), false);
    await closeCookies(page);
    await page.locator('[data-burger]').click();
    assert.equal(await page.locator('#mmenu').isVisible(), true);
  });

  await test('font-errors-use-fallback-and-reveal', {}, async page => {
    let failedFonts = 0;
    await page.route('**/*', route => {
      if (route.request().resourceType() === 'font') { failedFonts++; return route.abort(); }
      return route.fallback();
    });
    const started = Date.now();
    await ready(page);
    assert.ok(failedFonts > 0, 'Font requests were actually interrupted');
    assert.ok(Date.now() - started < 3000, 'Failed font promises settle without waiting for the loading deadline');
    assert.equal(await page.locator('h1').isVisible(), true, 'Fallback font keeps the heading readable');
    assert.equal(await page.locator('#site-loader').isVisible(), false);
  });

  await test('loader-timeout-with-hung-resources', {}, async page => {
    // Neither load/error nor DOMContentLoaded can complete: the inline deadline must still release the page.
    await page.route('**/*', route => {
      if (['stylesheet', 'script'].includes(route.request().resourceType()) || heroRequest(route.request().url())) return;
      return route.fallback();
    });
    const start = Date.now();
    await page.goto(base.href, { waitUntil: 'commit' });
    await page.waitForSelector('#site-loader', { state: 'attached' });
    await page.waitForFunction(() => document.getElementById('site-content') && !document.documentElement.classList.contains('site-loading'), null, { timeout: 6000 });
    assert.ok(Date.now() - start < 6000, 'Independent four-second deadline reveals content');
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), false);
    await page.evaluate(() => window.__siteReady);
  });

  await test('loader-automatic-and-reduced-motion', { reducedMotion: 'reduce' }, async page => {
    let releaseHero;
    const heroGate = new Promise(resolve => { releaseHero = resolve; });
    await page.route('**/*', async route => {
      if (heroRequest(route.request().url())) { await heroGate; await route.continue().catch(() => {}); }
      else await route.fallback();
    });
    await page.goto(base.href, { waitUntil: 'domcontentloaded' });
    await assertLoaderPresentation(page);
    assert.ok(await page.locator('.site-loader__fill').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration) <= .001), 'Reduced motion removes visible paw transitions');
    assert.ok(await page.locator('.site-loader').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration) <= .001), 'Reduced motion removes visible loader transitions');
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.documentElement.classList.contains('site-loading')), true, 'Loading completes automatically when resources are ready');
    releaseHero();
    await page.waitForFunction(() => !document.documentElement.classList.contains('site-loading'), null, { timeout: 2000 });
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), false);
    await page.evaluate(() => window.__siteReady);
  });

  await test('no-javascript-content', { javaScriptEnabled: false }, async page => {
    await page.goto(base.href, { waitUntil: 'networkidle' });
    assert.equal(await page.locator('#site-loader').isVisible(), false);
    assert.equal(await page.locator('#site-content').getAttribute('inert'), null);
    assert.equal(await page.locator('h1').isVisible(), true);
    assert.equal(await page.locator('main a[href*="maltipu/"]').first().isVisible(), true);
    assert.equal(await page.locator('.hero__main').evaluate(el => getComputedStyle(el).backgroundColor === 'rgba(0, 0, 0, 0)'), false, 'Noscript CSS is loaded');
    await page.screenshot({ path: path.join(artifacts, 'no-javascript-mobile.png') });
  });

  await test('mobile-interactions', {}, async page => {
    await ready(page);
    await page.screenshot({ path: path.join(artifacts, 'optimized-mobile.png') });
    await closeCookies(page);
    await page.locator('[data-burger]').click();
    assert.equal(await page.locator('#mmenu').isVisible(), true);
    await page.locator('[data-menu-close]').click();
    await page.locator('#mmenu').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#mmenu').isVisible(), false);
    await page.locator('[data-open-modal]:visible').first().click();
    assert.equal(await page.locator('#price-modal').evaluate(el => el.open), true);
    assert.equal(await page.locator('#price-modal input[name="name"]').isVisible(), true);
    await page.locator('[data-close-modal]:visible').first().click();
    const carousel = page.locator('#foto-video [data-carousel]');
    await carousel.scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('[data-hdr]').classList.contains('is-scrolled'));
    await page.waitForTimeout(250); // allow IntersectionObserver and the shared read/write frame to settle
    const before = await carousel.locator('[data-carousel-viewport]').evaluate(el => el.scrollLeft);
    await carousel.locator('[data-carousel-next]').click();
    await page.waitForFunction(({ before }) => Math.abs(document.querySelector('#foto-video [data-carousel-viewport]').scrollLeft - before) > 20, { before });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForFunction(() => !document.querySelector('[data-hdr]').classList.contains('is-scrolled'));
    const more = page.locator('[data-rvw-more]');
    await more.scrollIntoViewIfNeeded();
    const opened = await page.locator('.rvws .media-carousel__item.is-open').count();
    await more.click();
    assert.ok(await page.locator('.rvws .media-carousel__item.is-open').count() > opened, 'More reviews reveals another batch');
    await page.locator('.rvws').scrollIntoViewIfNeeded();
    const fold = page.locator('[data-rvw-toggle]').first();
    await fold.waitFor({ state: 'visible' });
    await fold.click();
    assert.equal(await fold.getAttribute('aria-expanded'), 'true');
    await fold.click();
    assert.equal(await fold.getAttribute('aria-expanded'), 'false');
  });

  for (const cssDelay of [1800, 4800]) await test(`delayed-css-${cssDelay}-keeps-review-controls`, {}, async page => {
    let delayed = 0;
    await page.route('**/*.min.css*', async route => {
      delayed++;
      await new Promise(resolve => setTimeout(resolve, cssDelay));
      await route.continue();
    });
    // At 4.8s the deadline deliberately reveals before CSS; inspect full layout once styles arrive.
    await ready(page, '/', cssDelay < 4000);
    assert.ok(delayed > 0, 'Deferred CSS request was actually delayed');
    await closeCookies(page);
    await page.waitForFunction(() => [...document.querySelectorAll('link[data-site-styles]')].every(link => !!link.sheet));
    await page.locator('.rvws').scrollIntoViewIfNeeded();
    const text = page.locator('[data-rvw-text]').first();
    const toggle = page.locator('[data-rvw-toggle]').first();
    await toggle.waitFor({ state: 'visible', timeout: 2000 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No overflow once delayed stylesheet arrives');
    const collapsedHeight = await text.evaluate(el => el.clientHeight);
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
    assert.ok(await text.evaluate(el => el.clientHeight) > collapsedHeight, 'Review expands after CSS arrives late');
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.ok(await text.evaluate(el => el.clientHeight) <= collapsedHeight + 1, 'Review collapses again');
  });

  await test('desktop-and-inner-pages', { viewport: { width: 1440, height: 1000 } }, async page => {
    await ready(page);
    await page.screenshot({ path: path.join(artifacts, 'optimized-desktop.png') });
    await closeCookies(page);
    await page.locator('[data-mega-btn]').click();
    assert.equal(await page.locator('#mega').isVisible(), true);
    await page.keyboard.press('Escape');
    await page.locator('#mega').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#mega').isVisible(), false);
    for (const route of ['/maltipu/', '/shchenki/', '/otzyvy/', '/kontakty/', '/politika-konfidencialnosti/']) {
      await ready(page, route);
      assert.equal(await page.locator('#site-loader').isVisible(), false, route);
      const broken = await page.locator('main img[fetchpriority="high"]').evaluateAll(images => images.filter(img => !img.complete || !img.naturalWidth).map(img => img.currentSrc));
      assert.deepEqual(broken, [], `Eager images load on ${route}`);
      await page.locator('[data-open-modal]:visible').first().click();
      assert.equal(await page.locator('#price-modal').evaluate(el => el.open), true, `Modal opens on ${route}`);
      await page.keyboard.press('Escape');
    }
  });
  await browser.close();
  fs.writeFileSync(path.join(artifacts, 'performance-browser-results.json'), JSON.stringify(results, null, 2) + '\n');
  if (results.some(result => !result.passed)) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
