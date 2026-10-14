/* Real mobile browser smoke checks for Wall and reply composer.
   npm install --no-save playwright-core && node tests/mobile_layout.cjs */
'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright-core');
const root = path.resolve(__dirname, '..', 'miniapp', 'web');
const post = {
  id: 17, nick: 'Очень длинный никнейм жителя Магнитогорска',
  title: 'Длинное название публикации для проверки мобильного экрана',
  body: 'Привет, Магнитогорск! '.repeat(9),
  created_at: 1700000000, updated_at: 1700000000,
  comments: 2, likes: 32, liked: false, mine: false,
  show_nick: true, media: [],
};
const detail = {
  post,
  comments: [
    { id: 1, nick: 'Участник', body: 'Первый ответ', created_at: 1700000000 },
    { id: 2, nick: 'Другой участник', body: 'Второй ответ', created_at: 1700000000 },
  ],
  truncated: false, is_admin: false,
};
const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.json': 'application/json',
};
const api = (req, res, pathname) => {
  let payload = {};
  if (pathname === '/api/miniapp/wall/access') payload = { allowed: true, public: true };
  else if (pathname === '/api/miniapp/wall') payload = { items: [post], offset: 1, more: false, is_admin: false };
  else if (pathname === '/api/miniapp/wall/17') payload = detail;
  else if (pathname === '/api/miniapp/status') payload = { status: 'free' };
  res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(payload));
};
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://127.0.0.1').pathname;
  if (pathname.startsWith('/api/')) return api(req, res, pathname);
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
  assert.ok(chrome, 'Chromium/Google Chrome is required for mobile layout tests');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const browser = await chromium.launch({ executablePath: chrome, headless: true, args: ['--no-sandbox'] });
  try {
    for (const width of [320, 360, 390, 430]) {
      const context = await browser.newContext({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true });
      const page = await context.newPage();
      await page.route('https://telegram.org/js/telegram-web-app.js', route =>
        route.fulfill({ status: 200, contentType: 'application/javascript', body: '' }));
      await page.addInitScript(() => {
        window.Telegram = { WebApp: {
          initData: 'test-init-data', initDataUnsafe: {},
          platform: 'android', version: '8.0',
          ready() {}, expand() {}, onEvent() {}, offEvent() {},
          isVersionAtLeast() { return true; },
          setHeaderColor() {}, setBackgroundColor() {}, disableVerticalSwipes() {},
          HapticFeedback: { impactOccurred() {}, selectionChanged() {} },
          BackButton: { show() {}, hide() {}, onClick() {} },
        }};
      });
      await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'domcontentloaded' });
      await page.evaluate(() => {
        document.querySelector('#boot')?.classList.add('hide');
        document.querySelector('#app')?.classList.add('ready');
        document.querySelectorAll('.page').forEach(el => el.classList.toggle('active', el.dataset.page === 'wall'));
        window.AnonWall.onPage('wall');
      });
      await page.waitForSelector('[data-wall-post="17"]', { timeout: 8000 });
      // Cover every top-level page, not only the Wall. Force each layout to render
      // without relying on a live Telegram account or backend session.
      const pageWidths = await page.evaluate(() => {
        const pages = Array.from(document.querySelectorAll('section.page[data-page]'));
        const active = pages.filter(p => p.classList.contains('active'));
        const widths = [];
        for (const target of pages) {
          for (const el of pages) el.classList.toggle('active', el === target);
          widths.push({ section: target.dataset.page, actual: document.documentElement.scrollWidth });
        }
        for (const el of pages) el.classList.toggle('active', active.includes(el));
        return widths;
      });
      for (const item of pageWidths)
        assert.ok(item.actual <= width + 1, width + 'px: ' + item.section + ' page overflows horizontally: ' + item.actual);
      const wall = await page.evaluate(() => {
        const r = el => el.getBoundingClientRect();
        const share = r(document.querySelector('.wall-action-share'));
        const heart = r(document.querySelector('.wall-action-like'));
        const comment = r(document.querySelector('.wall-action-comment'));
        const article = r(document.querySelector('[data-wall-post="17"]'));
        const copy = document.querySelector('#wallCopyLink');
        return {
          scrollWidth: document.documentElement.scrollWidth,
          share: { left: share.left, right: share.right, cy: share.y + share.height / 2 },
          heartCY: heart.y + heart.height / 2,
          commentCY: comment.y + comment.height / 2,
          articleRight: article.right,
          hiddenCopy: getComputedStyle(copy).display === 'none',
        };
      });
      assert.ok(wall.scrollWidth <= width + 1, width + 'px: horizontal page overflow');
      assert.ok(wall.articleRight <= width + 1, width + 'px: wall card outside viewport');
      assert.ok(wall.share.left >= 0 && wall.share.right <= width, width + 'px: share button outside viewport');
      assert.ok(Math.abs(wall.share.cy - wall.heartCY) <= 2, width + 'px: share/like centers differ');
      assert.ok(Math.abs(wall.share.cy - wall.commentCY) <= 2, width + 'px: share/comment centers differ');
      assert.ok(wall.hiddenCopy, width + 'px: admin-only copy link visible');

      await page.click('[data-wall-action="open"][data-id="17"]');
      await page.waitForSelector('#wallCommentText', { timeout: 8000 });
      const reply = await page.evaluate(() => {
        const outer = document.querySelector('.wall-comment-row').getBoundingClientRect();
        const text = document.querySelector('#wallCommentText').getBoundingClientRect();
        const overlay = document.querySelector('#wallOverlay').getBoundingClientRect();
        return {
          centerDelta: Math.abs((outer.top + outer.height / 2) - (text.top + text.height / 2)),
          textLeft: text.left, textRight: text.right,
          overlayBottom: overlay.bottom, overlayTop: overlay.top,
          documentWidth: document.documentElement.scrollWidth,
        };
      });
      assert.ok(reply.centerDelta <= 2, width + 'px: reply textarea vertically off-center');
      assert.ok(reply.textLeft >= 0 && reply.textRight <= width, width + 'px: reply textarea overflow');
      assert.ok(reply.overlayTop >= -1 && reply.overlayBottom <= 742, width + 'px: discussion outside viewport');
      assert.ok(reply.documentWidth <= width + 1, width + 'px: discussion horizontal overflow');
      await context.close();
      process.stdout.write('Mobile layout OK: ' + width + 'px\n');
    }
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
