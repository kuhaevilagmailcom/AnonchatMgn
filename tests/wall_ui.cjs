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
  addEventListener: noop,
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
  'window.__wallTest={icon,postHtml,handle,state,mediaHtml,link};window.AnonWall={onPage(page)',
);
assert.notEqual(injected, js, 'Test hook insertion must find the Wall public API');
vm.runInNewContext(injected, context, { filename: 'wall.js' });

const { icon, postHtml, handle, state, mediaHtml, link } = context.window.__wallTest;
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
assert.match(regular,/anon-mgn-wall-avatar\.jpg/,'wall posts use the attached logo');
assert.match(html,/id="wallCopyLink"/,'wall has a direct link copy button');
assert.match(js,/tg\.shareMessage/,'Telegram native prepared share is preferred');
assert.match(js,/share-details/,'photo share fallback is available');
assert.match(link(null,{source:'tg',medium:'post',campaign:'october'}),/startapp=wall__utm_source_tg__utm_medium_post__utm_campaign_october/);
assert.match(link(42,{source:'channel',medium:'post',campaign:'test'}),/startapp=wall_42__utm_source_channel__utm_medium_post__utm_campaign_test/);
assert.match(js, /tg\.openTelegramLink/);
assert.match(css, /@keyframes wall-heart-pop/);
assert.match(css, /@keyframes wall-dialog-in/);
assert.match(css, /prefers-reduced-motion:reduce/);
assert.match(html, /wall\.js\?v=9/);
assert.match(html, /wall\.css\?v=9/);
assert.match(html, /data-nav="wall" hidden/);
assert.match(js, /id="wallShowNick"/);
assert.match(js, /wall-title-input/);
assert.match(css, /Wall v6 — iOS dark grouped surfaces/);
assert.match(css, /\.wall-privacy-row/);
assert.doesNotMatch(js, /window\.confirm/);
assert.match(js, /id="wallCommentForm" class="wall-comment-form" novalidate/);
assert.match(js, /function actionSheet/);
assert.match(js, /data-wall-action="submit-report"/);
assert.match(css, /\.wall-action-layer/);
console.log('Wall UI checks passed: icons, actions, iOS compose privacy and accessibility.');


// Regression: previously this threw .forEach is not a function after the
// server had already toggled the like, leaving a huge stacktrace on screen.
const button = () => {
  const classes = new Set(['wall-action']);
  const count={textContent:''};
  const attributes={};
  return {
    dataset:{wallAction:'like',id:'7'}, disabled:false,
    classList:{
      contains:x=>classes.has(x),
      toggle:(x,force)=>{if(force)classes.add(x);else classes.delete(x);},
      remove:x=>classes.delete(x),add:x=>classes.add(x),
    },
    querySelector:selector=>selector==='.wall-action-count'?count:null,
    setAttribute:(k,v)=>{attributes[k]=v;},
    addEventListener:noop,offsetWidth:21,
    count,attributes,classes,
  };
};
const one=button(),two=button();
dom.querySelectorAll=selector=>selector.includes('data-wall-action="like"')?[one,two]:[];
state.posts=[makePost(false)];
context.AbortController=AbortController;
context.fetch=async()=>({ok:true,json:async()=>({liked:true,likes:15})});
(async()=>{
  await handle(one);
  for(const btn of [one,two]){
    assert.equal(btn.disabled,false);
    assert.ok(btn.classes.has('liked'));
    assert.equal(btn.attributes['aria-pressed'],'true');
    assert.equal(btn.count.textContent,'15');
  }
  assert.equal(state.posts[0].likes,15);
  context.fetch=async()=>({ok:true,json:async()=>({liked:false,likes:14})});
  await handle(two);
  assert.ok(!one.classes.has('liked')&&!two.classes.has('liked'));
  assert.equal(two.attributes['aria-pressed'],'false');
  assert.equal(one.count.textContent,'14');

  assert.match(css,/\.wall-post-media\.photos\.wall-count-1 \.wall-photo-tile img\{/);
  assert.match(css,/object-fit:contain/);
  assert.match(css,/\.wall-viewer-arrow\[hidden\]/);
  assert.match(js,/function showGalleryPhoto/);
  assert.match(mediaHtml([{id:22,kind:'image',url:'/media/22'}]),/data-media-id="22"/);

  // A slow network must never delay the icon or number changing.
  const pending=[];
  context.fetch=(_url,options)=>new Promise(resolve=>{
    pending.push({resolve,body:JSON.parse(options.body)});
  });
  state.posts=[makePost(false)];
  const first=handle(one);
  assert.equal(pending.length,1,'first tap sends one request');
  assert.equal(pending[0].body.liked,true);
  assert.ok(one.classes.has('liked'),'first tap updates the heart immediately');
  assert.equal(one.count.textContent,'15','first tap updates the count before network response');

  // Second tap while first request is pending is painted immediately, queued
  // as an explicit desired state, and does not fire a second overlapping request.
  await handle(two);
  assert.ok(!one.classes.has('liked'),'rapid unlike is immediate');
  assert.equal(one.count.textContent,'14');
  assert.equal(pending.length,1,'rapid taps are serialized');
  pending[0].resolve({ok:true,json:async()=>({liked:true,likes:15})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(pending.length,2,'the final desired state is persisted');
  assert.equal(pending[1].body.liked,false);
  pending[1].resolve({ok:true,json:async()=>({liked:false,likes:14})});
  await first;
  assert.ok(!one.classes.has('liked'));
  assert.equal(one.count.textContent,'14');
  assert.equal(two.attributes['aria-pressed'],'false');
  assert.match(css,/\.wall-liked-pop::before\{display:none!important\}/);
  assert.match(css,/margin:0 0 0 9px!important/);
  console.log('Wall interaction checks passed: optimistic likes, rapid taps and aligned counters.');
})().catch(err=>{console.error(err);process.exitCode=1});
