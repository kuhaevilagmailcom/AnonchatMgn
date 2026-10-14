/* Mobile smoke tests for the current ANON MGN Mini App without retired screens.
   Run: npm install --no-save playwright-core@1.56.0 && node tests/mobile_layout.cjs */
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const root = path.resolve(__dirname, '..', 'miniapp', 'web');
const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.svg': 'image/svg+xml',
};
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
  if (pathname.startsWith('/api/')) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    return res.end('{"message":"Not found"}');
  }
  const file = path.resolve(root, '.' + decodeURIComponent(pathname === '/' ? '/index.html' : pathname));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404);
    return res.end('Not found');
  }
  res.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
(async () => {
  const chrome = process.env.CHROME_BIN ||
    ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium'].find(fs.existsSync);
  assert.ok(chrome, 'Chromium/Google Chrome is required for mobile smoke tests');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  let browser;
  try {
    browser = await chromium.launch({ executablePath: chrome, headless: true, args: ['--no-sandbox'] });
    for (const width of [320, 360, 390, 430]) {
      const context = await browser.newContext({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true });
      try {
        const page = await context.newPage();
        await page.route('https://telegram.org/js/telegram-web-app.js', route =>
          route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
        await page.addInitScript(() => {
          window.Telegram = { WebApp: {
            initData: '', initDataUnsafe: {}, platform: 'android', version: '8.0',
            ready() {}, expand() {}, onEvent() {}, offEvent() {},
            isVersionAtLeast() { return true; },
            setHeaderColor() {}, setBackgroundColor() {}, disableVerticalSwipes() {},
            HapticFeedback: { impactOccurred() {}, selectionChanged() {} },
            BackButton: { show() {}, hide() {}, onClick() {} },
          }};
        });
        await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'domcontentloaded' });
        await page.waitForSelector('#app');
        const measurements = await page.evaluate(() => {
          document.querySelector('#boot')?.classList.add('hide');
          document.querySelector('#app')?.classList.add('ready');
          const sections = Array.from(document.querySelectorAll('.page[data-page]'));
          const original = sections.filter(p => p.classList.contains('active'));
          const widths = [];
          for (const section of sections) {
            sections.forEach(p => p.classList.toggle('active', p === section));
            widths.push({ page: section.dataset.page, width: document.documentElement.scrollWidth });
          }
          sections.forEach(p => p.classList.toggle('active', original.includes(p)));
          const chatSend = document.querySelector('#chatSend');
          const r = chatSend?.getBoundingClientRect();
          return {
            widths,
            navs: Array.from(document.querySelectorAll('#bottomNav [data-nav]')).map(x => x.dataset.nav),
            hasRetiredDOM: Boolean(document.querySelector('[data-page="wall"],[data-nav="wall"],#wallOverlay')),
            hasRetiredAssets: Array.from(document.scripts).some(s => /(?:wall\.js|admin-wall\.js)/.test(s.src)),
            chatButton: r ? { width:r.width,height:r.height } : null,
          };
        });
        assert.ok(!measurements.hasRetiredDOM, 'retired UI is still mounted');
        assert.ok(!measurements.hasRetiredAssets, 'retired JS bundle is loaded');
        assert.ok(measurements.navs.includes('home') && measurements.navs.includes('search'), 'main navigation missing');
        assert.ok(measurements.chatButton && measurements.chatButton.width >= 30, 'chat send button missing');
        for (const item of measurements.widths)
          assert.ok(item.width <= width + 1, width + 'px: ' + item.page + ' overflows: ' + item.width);
        process.stdout.write('Mini App screens OK: ' + width + 'px\n');
      } finally {
        await context.close();
      }
    }
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
