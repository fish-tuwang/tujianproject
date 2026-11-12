const fs = require('node:fs'), assert = require('node:assert/strict');
const {chromium, webkit, devices} = require('playwright');
const auth = require('./browser-auth.cjs');
const base = process.env.PREVIEW_URL || 'https://117.72.11.77';
const out = process.env.GUNPLA_EVENT_REPORT || 'artifacts/acceptance/gunpla-event-public.json';
const candidate = process.env.GUNPLA_EVENT_CANDIDATE === '1';
const report = {status: 'fail', scope: candidate ? 'candidate CSS with live authenticated APIs' : 'deployed private HTTPS', checks: [], failures: [], profiles: [], errors: []};
const frame = page => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const state = page => page.evaluate(() => ({y: scrollY, height: document.documentElement.scrollHeight,
  railY: document.getElementById('gunpla-events').scrollTop,
  query: GunplaPage.state.query, ids: GunplaPage.state.items.map(item => item.id), url: location.href}));
const shape = snapshot => JSON.stringify({query: snapshot.query, ids: snapshot.ids, url: snapshot.url});

(async () => {
  fs.mkdirSync('artifacts/acceptance', {recursive: true});
  for (const profile of [
    {name: 'desktop', engine: chromium, options: {viewport: {width: 1700, height: 1050}}},
    {name: 'mobile', engine: webkit, options: {...devices['iPhone 13'], deviceScaleFactor: 1}},
  ]) {
    const browser = await profile.engine.launch(profile.engine === chromium ? {channel: 'chrome', headless: true} : {headless: true});
    try {
      const context = await browser.newContext({...profile.options, ...auth.contextOptions()});
      const page = await context.newPage();
      page.setDefaultTimeout(45000);
      page.on('pageerror', error => report.errors.push(error.message));
      if (candidate) await page.route('**/preview/gunpla.css*', async route => {
        const response = await route.fetch();
        assert.equal(response.status(), 200);
        await route.fulfill({response, body: fs.readFileSync('backend/preview/gunpla.css', 'utf8')});
      });
      const check = (name, passed) => {
        const label = profile.name + ' ' + name;
        report.checks.push({name: label, passed});
        if (!passed) report.failures.push(label);
        console.log((passed ? 'PASS ' : 'FAIL ') + label);
      };
      await page.goto(base + '/preview/gunpla.html', {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => window.GunplaPage?.state.ready && !GunplaPage.state.loading && document.querySelectorAll('.event-card').length > 0);
      await page.locator('[data-sale="3"]').click();
      await page.waitForFunction(() => !GunplaPage.state.loading && GunplaPage.state.query.sale_type === '3');
      await page.locator('#gunpla-page-size').selectOption('40');
      await page.waitForFunction(() => !GunplaPage.state.loading && GunplaPage.state.query.limit === 40);
      await page.locator('#gunpla-next').click();
      await page.waitForFunction(() => !GunplaPage.state.loading && GunplaPage.state.query.page === 2);
      const cards = page.locator('.event-card');
      const card = cards.nth(Math.min(2, await cards.count() - 1));
      await card.scrollIntoViewIfNeeded();
      await frame(page);
      const before = await state(page);
      check('activity is clicked after scrolling down', before.y > 100);
      await card.click();
      await page.waitForFunction(() => document.getElementById('event-dialog').open);
      await frame(page);
      const opened = await state(page);
      const geometry = await page.locator('#event-dialog').evaluate(dialog => {
        const box = dialog.getBoundingClientRect();
        return {position: getComputedStyle(dialog).position, top: box.top, bottom: box.bottom, viewport: innerHeight};
      });
      console.log(JSON.stringify({profile: profile.name, beforeY: before.y, openedY: opened.y, geometry}));
      check('opening activity preserves the page scroll position', Math.abs(opened.y - before.y) <= 3);
      check('opening activity does not change document height', Math.abs(opened.height - before.height) <= 3);
      check('activity panel stays inside the viewport', geometry.top >= -1 && geometry.bottom <= geometry.viewport + 1);
      check('activity keeps the selected list and URL', shape(opened) === shape(before));
      if (geometry.position === 'fixed') {
        const image = page.locator('#event-content img');
        await image.evaluate(img => img.decode());
        await image.click();
        await page.waitForFunction(() => document.getElementById('image-viewer').open);
        check('activity image still opens the original viewer', await page.locator('#image-viewer').isVisible());
        await page.locator('#close-image').click();
        check('closing image keeps the activity open and page position', await page.locator('#event-dialog').isVisible() && Math.abs((await state(page)).y - before.y) <= 3);
      }
      await page.locator('#close-event').click();
      await frame(page);
      const closed = await state(page);
      check('closing activity preserves page and rail positions', Math.abs(closed.y - before.y) <= 3 && Math.abs(closed.railY - before.railY) <= 3);
      check('closing activity preserves model filters and records', shape(closed) === shape(before));
      await card.click();
      await page.keyboard.press('Escape');
      await frame(page);
      check('Escape closes activity without jumping the page', !await page.locator('#event-dialog').isVisible() && Math.abs((await state(page)).y - before.y) <= 3);
      await page.reload({waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => window.GunplaPage?.state.ready);
      await frame(page);
      check('refresh keeps the browsing position after activity closes', Math.abs((await state(page)).y - before.y) <= 3);
      report.profiles.push({name: profile.name, beforeY: before.y, openedY: opened.y, closedY: closed.y, geometry});
      await context.close();
    } finally {
      await browser.close();
    }
  }
  assert.deepEqual(report.errors, [], 'no browser JavaScript errors');
  assert.deepEqual(report.failures, [], 'activity scroll regressions');
  report.status = 'pass';
  console.log('GUNPLA_EVENT_SCROLL: ' + report.checks.length + ' passed; desktop Chrome and mobile WebKit');
})().catch(error => {
  report.errors.push(String(error.message).split('\n')[0]);
  console.error(String(error.message).split('\n')[0]);
  process.exitCode = 1;
}).finally(() => fs.writeFileSync(out, JSON.stringify(report, null, 2)));
