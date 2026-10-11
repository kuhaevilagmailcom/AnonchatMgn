/* Wall action-bar smoke test without a browser or Telegram token.
   Verifies actual post renderer and the accessibility/animation contract. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const js = fs.readFileSync('miniapp/web/wall.js', 'utf8');
const css = fs.readFileSync('miniapp/web/wall.css', 'utf8');
const html = fs.readFileSync('miniapp/web/index.html', 'utf8');

const noop = () => {};
const root = { addEventListener: noop, querySelectorAll: () => [] };
const overlay = { addEventListener: noop, hidden: true };
const basic = { addEventListener: noop, onclick: null, hidden: false };
const dom = {
  querySelector(selector) {
    if (selector === '[data-page="wall"]') return root;
    if (selector === '#wallOverlay') return overlay;
    return basic;
  },
  querySelectorAll: () => [],
};
const context = {
  document: dom,
  window: { Telegram: { WebApp: { initData: '' } } },
  navigator: {},
  setTimeout,
  clearTimeout,
  Date,
  URL,
  console,
};
const injected = js.replace(
  'window.AnonWall={onPage(page)',
  'window.__wallTest={icon,postHtml};window.AnonWall={onPage(page)',
);
assert.notEqual(injected, js, 'Test hook insertion must find the Wall public API');
vm.runInNewContext(injected, context, { filename: 'wall.js' });

const { icon, postHtml } = context.window.__wallTest;
const makePost = (liked = false) => ({
  id: 7, nick: 'Аноним', body: 'Тест', created_at: 100,
  updated_at: 100, likes: 14, comments: 3, liked, media: [],
});
const regular = postHtml(makePost(), false);
const active = postHtml(makePost(true), true);

for (const kind of ['heart', 'comment', 'share']) {
  assert.ok(icon(kind).includes('viewBox="0 0 24 24"'), kind + ': same viewBox');
  assert.ok(icon(kind).includes('stroke-width="1.85"'), kind + ': same stroke');
  assert.ok(regular.includes('wall-icon--' + kind), kind + ': icon in action row');
}
for (const action of ['like', 'open', 'share']) {
  const found = regular.match(new RegExp('data-wall-action="' + action + '"', 'g')) || [];
  assert.equal(found.length, 1, action + ': no duplicate buttons');
}
assert.doesNotMatch(regular, /Обсудить/, 'Remove redundant Discuss CTA');
assert.match(regular, /aria-label="Комментарии: 3"/);
assert.match(regular, /aria-pressed="false"/);
assert.match(active, /aria-pressed="true"/);
assert.match(active, /wall-action-like liked/);
assert.match(js, /navigator\.share/);
assert.match(js, /tg\.openTelegramLink/);
assert.match(css, /@keyframes wall-heart-pop/);
assert.match(css, /@keyframes wall-dialog-in/);
assert.match(css, /prefers-reduced-motion:reduce/);
assert.match(html, /wall\.js\?v=3/);
assert.match(html, /wall\.css\?v=3/);
assert.match(html, /data-nav="wall" hidden/);
console.log('Wall UI checks passed: canonical icons, single actions, animation, accessibility and admin-only menu.');
