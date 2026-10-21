/* Layout regression for the standalone city Mini App.
 * Uses the project Playwright Chromium installation; no external map requests.
 */
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');

const root = path.resolve(__dirname, '..', 'miniapp', 'web');
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.png': 'image/png', '.svg': 'image/svg+xml' };
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  const full = path.resolve(root, '.' + decodeURIComponent(pathname));
  if (!full.startsWith(root + path.sep) || !fs.existsSync(full) || !fs.statSync(full).isFile()) {
    res.writeHead(404);
    res.end('Not found');
    return;
  }
  res.writeHead(200, { 'Content-Type': mime[path.extname(full)] || 'application/octet-stream' });
  fs.createReadStream(full).pipe(res);
});

(async () => {
  const browserPath = process.env.CHROME_BIN ||
    ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'].find(fs.existsSync);
  assert.ok(browserPath, 'Chromium is required for the UI layout test');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  let browser;
  try {
    browser = await chromium.launch({ executablePath: browserPath, headless: true, args: ['--no-sandbox'] });
    for (const width of [320, 360, 390, 430]) {
      const context = await browser.newContext({ viewport: { width, height: 740 },
        deviceScaleFactor: 2, hasTouch: true, isMobile: true });
      const page = await context.newPage();
      try {
        await page.route('https://telegram.org/**', route =>
          route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
        await page.route('https://unpkg.com/**', route =>
          route.fulfill({ status: 200, contentType: route.request().url().endsWith('.css')
            ? 'text/css' : 'application/javascript', body: '' }));
        await page.addInitScript(() => {
          window.Telegram = { WebApp: { initData: '',
            ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {},
            BackButton: { show() {}, onClick() {} } } };
        });
        await page.goto('http://127.0.0.1:' + port + '/city.html', { waitUntil: 'domcontentloaded' });
        await page.evaluate(() => { document.querySelector('#toast').hidden = true; });
        const result = await page.evaluate(() => {
          const box = node => {
            const r = document.querySelector(node).getBoundingClientRect();
            return { left: r.left, right: r.right, top: r.top, bottom: r.bottom,
              width: r.width, height: r.height };
          };
          return {
            docWidth: document.documentElement.scrollWidth,
            panel: box('#panel'), nav: box('#tabs'), map: box('#map'),
            action: box('#capture'), mapControl: box('#locate'),
            navItems: [...document.querySelectorAll('.sheet-tabs .tab')].length
          };
        });
        assert.ok(result.docWidth <= width + 1, width + ': horizontal page overflow');
        assert.ok(result.panel.left >= -1 && result.panel.right <= width + 1, width + ': dock overflows');
        assert.ok(result.panel.width >= width - 2, width + ': dock not full width');
        assert.ok(result.panel.height <= 280, width + ': map dock is too large');
        assert.ok(result.panel.top >= 440, width + ': map not visible enough');
        assert.ok(result.action.bottom <= result.nav.top + 2, width + ': capture button hidden beneath nav');
        assert.ok(result.navItems === 4, 'map/tops/market/rules navigation missing');
        assert.equal(await page.locator('#count').count(), 0, width + ': old occupied count returned');
        assert.equal(await page.locator('#mineCount').count(), 0, width + ': old zone count returned');
        assert.equal(await page.locator('#captureCount').count(), 0, width + ': old capture count returned');
        assert.ok(await page.locator('#hpHud').isVisible(), width + ': HP status missing');
        assert.equal(await page.locator('#mapCredits a').count(), 2,
          width + ': both legal map data attributions must stay visible');
        assert.ok(await page.locator('#mapCredits').isVisible(),
          width + ': copyright links must remain accessible');
        const creditStyle = await page.locator('#mapCredits').evaluate(el => ({
          background:getComputedStyle(el).backgroundColor,
          boxShadow:getComputedStyle(el).boxShadow
        }));
        assert.equal(creditStyle.background, 'rgba(0, 0, 0, 0)',
          width + ': black copyright plaque returned');
        assert.equal(creditStyle.boxShadow, 'none',
          width + ': copyright block has unwanted shadow');
        assert.ok(await page.locator('#myZonesButton .ico').isVisible(),
          width + ': real SVG my-zones icon missing');
        await page.locator('#theme').click();
        assert.equal(await page.evaluate(() => document.body.dataset.mapTheme), 'light');
        await page.locator('#sheetToggle').click();
        assert.ok(await page.locator('#panel').evaluate(el => el.classList.contains('is-expanded')));
        await page.locator('#showmarket').click();
        assert.ok(await page.locator('#market').isVisible());
        const marketLayout = await page.evaluate(() => {
          const bb = selector => document.querySelector(selector).getBoundingClientRect();
          const market = document.querySelector('#market');
          const sample = document.createElement('div');
          sample.style.cssText = 'height:950px;width:100%;pointer-events:none';
          sample.id = 'market-scroll-test';
          market.append(sample);
          return {
            headerBottom:bb('.appbar').bottom,
            panelTop:bb('#panel').top, panelBottom:bb('#panel').bottom,
            navBottom:bb('#tabs').bottom, navTop:bb('#tabs').top,
            marketTop:bb('#market').top, marketBottom:bb('#market').bottom,
            marketHeight:market.clientHeight, marketScrollable:market.scrollHeight > market.clientHeight,
            fullWidth:bb('#panel').width,
            screenHeight:document.documentElement.clientHeight,
          };
        });
        assert.ok(marketLayout.panelTop >= marketLayout.headerBottom - 3,
          width + ': market overlaps Mini App header');
        assert.ok(marketLayout.panelTop <= marketLayout.headerBottom + 5,
          width + ': market opens too low instead of using full screen');
        assert.ok(Math.abs(marketLayout.panelBottom - marketLayout.screenHeight) <= 2,
          width + ': market detached from screen bottom');
        assert.ok(Math.abs(marketLayout.navBottom - marketLayout.screenHeight) <= 2,
          width + ': market hides bottom navigation');
        assert.ok(marketLayout.marketBottom <= marketLayout.navTop + 2,
          width + ': market content spills underneath bottom navigation');
        assert.ok(marketLayout.marketTop >= marketLayout.panelTop,
          width + ': market list appears above the drawer');
        assert.ok(Math.abs(marketLayout.fullWidth - width) <= 2,
          width + ': market is not full width');
        assert.ok(marketLayout.marketScrollable,
          width + ': long pet list does not scroll');
        await page.locator('#market').evaluate(node => { node.scrollTop = 250; });
        assert.ok(await page.locator('#market').evaluate(node => node.scrollTop > 50),
          width + ': market scroll is blocked');
        await page.locator('#showtop').click();
        assert.ok(await page.locator('#districtInventory').isVisible(),
          width + ': inventory tab unavailable');
        assert.ok(await page.locator('#inventoryTabs').isVisible());
        await page.locator('#showrules').click();
        assert.ok(await page.locator('#districtMore').isVisible(),
          width + ': compact More menu unavailable');
        await page.locator('#showmap').click();
        assert.ok(await page.locator('#mapView').isVisible());
        await page.locator('#myZonesButton').click();
        assert.ok(await page.locator('#districtInventory').isVisible(),
          width + ': side button must show Inventory, not old My Districts');
        assert.ok(await page.locator('#tabs').isVisible());
        await page.locator('#showmap').click();
        await page.evaluate(() => {
          document.querySelector('#deathScreen').hidden = false;
          document.querySelector('#deathLost').textContent = '56';
        });
        assert.ok(await page.locator('#deathScreen').isVisible(),
          width + ': dead player must see respawn overlay');
        const death = await page.evaluate(() => {
          const get = selector => document.querySelector(selector).getBoundingClientRect();
          const content = get('.city-death-content'),button = get('#respawn');
          return {
            left:content.left,right:content.right,
            top:content.top,bottom:content.bottom,
            buttonBottom:button.bottom,
            width:content.width,
            viewportW:document.documentElement.clientWidth,
            viewportH:document.documentElement.clientHeight
          };
        });
        assert.ok(death.left >= 0 && death.right <= width + 1,
          width + ': death screen overflows horizontally');
        assert.ok(death.top >= 0 && death.bottom <= death.viewportH + 1,
          width + ': death content is clipped');
        assert.ok(death.buttonBottom <= death.viewportH - 5,
          width + ': respawn button is hidden on narrow screens');
        assert.ok(death.width >= 240,
          width + ': death screen is too narrow to use');
        process.stdout.write('City Mini App layout, respawn and controls OK: ' + width + 'px\n');
      } finally {
        await context.close();
      }
    }
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
