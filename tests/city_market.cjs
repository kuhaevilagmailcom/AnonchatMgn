/* Offline real-UI market smoke test, no Telegram or tile servers required. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,'../miniapp/web/city.js'),'utf8');

function fakeNode(tag) {
  return {
    tag,textContent:'',className:'',dataset:{},style:{},hidden:false,
    disabled:false,children:[],listeners:{},attrs:{},
    classList:{items:new Set(),add(k){this.items.add(k)},remove(k){this.items.delete(k)},
      toggle(k,yes){if(yes)this.add(k);else this.remove(k)}},
    addEventListener(name,fn){this.listeners[name]=fn},
    setAttribute(name,value){this.attrs[name]=value},
    removeAttribute(name){delete this.attrs[name]},
    replaceChildren(){this.children=[]},
    append(...children){this.children.push(...children)},
    click(){return this.listeners.click?.()}
  };
}
async function flush(){for(let i=0;i<70;i++) await Promise.resolve();}
(async()=>{
  const nodes={};const markers=[];const posts=[];
  const document={
    hidden:false,body:fakeNode('body'),addEventListener(){},
    getElementById:id=>nodes[id]||(nodes[id]=fakeNode(id)),
    createElement:fakeNode
  };
  const layer=()=>({
    handlers:{},addTo(){return this},clearLayers(){return this},
    on(name,fn){this.handlers[name]=fn;return this},
    setStyle(){return this},bindTooltip(){return this},setLatLng(){return this},
    setRadius(){return this},getBounds(){return {pad(){return this}}}
  });
  const map={attributionControl:{setPrefix(){}},setView(){return this},
    on(){return this},getZoom(){return 14},flyTo(){},flyToBounds(){},
    fitBounds(){},invalidateSize(){},removeLayer(){}};
  const L={map:()=>map,tileLayer:layer,polygon:layer,circle:layer,
    layerGroup:layer,divIcon:o=>o,latLngBounds:()=>({}),
    marker(_coords,opts){const marker=layer();marker.title=opts.title;markers.push(marker);return marker}};
  const window={
    L,innerHeight:780,addEventListener(){},setTimeout(){return 1},
    setInterval(){return 1},clearInterval(){},localStorage:{getItem(){return'dark'},setItem(){}},
    Telegram:{WebApp:{
      ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},initData:'test',
      BackButton:{show(){},onClick(){}},HapticFeedback:{selectionChanged(){},notificationOccurred(){}}
    }}
  };
  const catalog=[
    {kind:'cat',emoji:'🐈',name:'Кот',price:100,stars_h:1,hp_5m:.5},
    {kind:'bird',emoji:'🐤',name:'Птица',price:500,stars_h:3,hp_5m:1},
    {kind:'pig',emoji:'🐷',name:'Свинка',price:1000,stars_h:6,hp_5m:1.5},
    {kind:'snake',emoji:'🐍',name:'Змея',price:2500,stars_h:10,hp_5m:2.5},
    {kind:'lion',emoji:'🦁',name:'Лев',price:5000,stars_h:18,hp_5m:4}
  ];
  const zone={id:1,name:'Ашик',lat:53.38,lon:58.98,polygon:[],
    mine:true,occupied:true,owner_name:'Тест',kind:'mall',size:'Малый'};
  let wallet=1100,pets=[],guards=[],claimed=0;
  async function fetch(url,options={}){
    if(url==='/api/city/state')return {
      ok:true,json:async()=>({zones:[zone],leaderboard:[],catalog,wallet,
        my_pets:pets,guards, hp:93.2,max_hp:100,pending_stars:claimed?0:pets.length?2:0,
        can_capture:true,cooldown_remaining_s:0,my_zones:1,total_captures:1})
    };
    if(url==='/api/city/road-shapes')return {ok:true,json:async()=>({shapes:{},extra_count:0})};
    const body=options.body?JSON.parse(options.body):{};
    posts.push({url,body});
    if(url==='/api/city/pets/buy'){
      if(wallet>=100){wallet-=100;pets=[{id:1,kind:'cat',zone_id:null,active:false}];}
      return {ok:true,json:async()=>({ok:true,pet_id:1,balance:wallet})};
    }
    if(url==='/api/city/pets/place'){
      pets=[{id:1,kind:'cat',zone_id:1,active:true}];
      guards=[{zone_id:1,kind:'cat',mine:true}];
      return {ok:true,json:async()=>({ok:true,pet_id:1,zone_id:1})};
    }
    if(url==='/api/city/pets/claim'){
      claimed=1;wallet+=2;
      return {ok:true,json:async()=>({ok:true,stars:2,balance:wallet})};
    }
    throw Error('Unexpected request: '+url);
  }
  const navigator={permissions:{query:async()=>({state:'denied'})}};
  new Function('document','window','navigator','L','fetch','setTimeout','clearTimeout',
    'setInterval','requestAnimationFrame',source)(
      document,window,navigator,L,fetch,()=>1,()=>{},()=>1,fn=>fn());
  await flush();
  nodes.myZonesButton.click();
  assert.equal(nodes.districtInventory.hidden,false,
    'side control must open inventory');
  assert.equal(nodes.myZones.hidden,true,
    'side control must no longer open My Districts');
  nodes.showmarket.click();
  assert.equal(nodes.market.hidden,false);
  assert.equal(nodes.wallet.textContent,'1 100 ⭐');
  assert.equal(nodes.hpValue.textContent,'93.2');
  assert.equal(nodes.petCatalog.children.length,5);
  assert.match(nodes.petCatalog.children[0].children[1].children[1].textContent,/⭐\/ч/);
  assert.match(nodes.petCatalog.children[0].children[1].children[2].textContent,/Урон: −0,5 HP \/ 5 мин/);
  assert.doesNotMatch(nodes.petCatalog.children[0].children[1].children[2].textContent,/HP\/ч/);
  await nodes.petCatalog.listeners.click({
    target:{closest:()=>({dataset:{buyKind:'cat'}})}
  });
  await flush();
  assert.equal(wallet,1000);
  assert.equal(nodes.petCount.textContent,'1');
  assert.equal(posts[0].url,'/api/city/pets/buy');
  assert.ok(posts[0].body.request_id,'purchase retries must be idempotent');
  assert.ok(markers.find(m=>m.title==='Ашик'));
  markers.find(m=>m.title==='Ашик').handlers.click();
  nodes.showmarket.click();
  await nodes.petInventory.listeners.click({
    target:{closest:()=>({dataset:{petAction:'place',petId:'1'}})}
  });
  await flush();
  assert.equal(posts[1].url,'/api/city/pets/place');
  assert.equal(posts[1].body.zone_id,1);
  assert.equal(nodes.zoneGuard.hidden,false);
  assert.equal(nodes.zoneGuard.textContent,'🐈');
  assert.equal(nodes.petCount.textContent,'1');
  await nodes.claimIncome.click();
  await flush();
  assert.equal(posts[2].url,'/api/city/pets/claim');
  assert.equal(wallet,1002);
  assert.ok(nodes.wallet.textContent.includes('1'));
  console.log('City market, purchases, pet deployment, earned stars and HP UI OK');
})().catch(error=>{console.error(error);process.exitCode=1});
