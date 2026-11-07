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
    if (checkLayout) assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No horizontal document overflow');
  }
  async function closeCookies(page) {
    const button = page.locator('[data-cookie-choice="necessary"]');
    if (await button.isVisible()) await button.click();
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
    await page.screenshot({ path: path.join(artifacts, 'paw-loader-mobile.png') });
    const releasedAt = Date.now();
    releaseHero();
    await page.waitForFunction(() => !document.documentElement.classList.contains('site-loading'), null, { timeout: 2000 });
    assert.ok(Date.now() - releasedAt < 2000, 'Hero completion reveals the page without waiting for lazy images');
    assert.ok(blockedLazy > 0, 'At least one below-fold image was pending during reveal');
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), false);
    await page.evaluate(() => window.__siteReady);
  });

  await test('hero-error-does-not-trap-page', {}, async page => {
    await page.route('**/*', route => heroRequest(route.request().url()) ? route.abort() : route.fallback());
    await ready(page);
    assert.equal(await page.locator('#site-loader').isVisible(), false);
    await closeCookies(page);
    await page.locator('[data-burger]').click();
    assert.equal(await page.locator('#mmenu').isVisible(), true);
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

  await test('loader-skip-and-reduced-motion', { reducedMotion: 'reduce' }, async page => {
    await page.route('**/*', route => heroRequest(route.request().url()) ? undefined : route.fallback());
    await page.goto(base.href, { waitUntil: 'domcontentloaded' });
    assert.ok(await page.locator('.site-loader__fill').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration) <= .001), 'Reduced motion removes visible paw transitions');
    assert.ok(await page.locator('.site-loader').evaluate(el => parseFloat(getComputedStyle(el).transitionDuration) <= .001), 'Reduced motion removes visible loader transitions');
    await page.locator('.site-loader__skip').click();
    await page.waitForFunction(() => !document.documentElement.classList.contains('site-loading'));
    assert.equal(await page.locator('#site-content').evaluate(el => el.inert), false);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'main', 'Skip moves focus to page content');
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
    await page.waitForTimeout(250); // allow IntersectionObserver and the shared read/write frame to settle
    const before = await carousel.locator('[data-carousel-viewport]').evaluate(el => el.scrollLeft);
    await carousel.locator('[data-carousel-next]').click();
    await page.waitForFunction(({ before }) => Math.abs(document.querySelector('#foto-video [data-carousel-viewport]').scrollLeft - before) > 20, { before });
    const more = page.locator('[data-rvw-more]');
    await more.scrollIntoViewIfNeeded();
    const opened = await page.locator('.rvws .media-carousel__item.is-open').count();
    await more.click();
    assert.ok(await page.locator('.rvws .media-carousel__item.is-open').count() > opened, 'More reviews reveals another batch');
    const fold = page.locator('[data-rvw-toggle]:visible').first();
    if (await fold.count()) {
      await fold.click();
      assert.equal(await fold.getAttribute('aria-expanded'), 'true');
      await fold.click();
      assert.equal(await fold.getAttribute('aria-expanded'), 'false');
    }
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
