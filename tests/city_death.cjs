/* Regression: lethal HP, freeing owned zones, death overlay and server respawn. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname,'../miniapp/web/city.js'),'utf8');

function fakeElement(tag) {
  return {
    tag, textContent:'', hidden:false, disabled:false, style:{}, dataset:{},
    className:'', children:[], attrs:{}, events:{},
    classList: {
      items:new Set(),
      add(value){this.items.add(value)},
      remove(value){this.items.delete(value)},
      toggle(value,enabled){enabled?this.add(value):this.remove(value)},
      contains(value){return this.items.has(value)}
    },
    addEventListener(name,listener){this.events[name]=listener},
    click(){return this.events.click?.()},
    setAttribute(name,value){this.attrs[name]=value},
    removeAttribute(name){delete this.attrs[name]},
    replaceChildren(){this.children=[]},
    append(...items){this.children.push(...items)},
    setLatLng(){return this}
  };
}
async function flush(){for(let i=0;i<100;i++) await Promise.resolve();}

(async()=>{
  const nodes={},posts=[],zoneId=7;let watch=null;
  let fakeTime=Date.now(),lethal=false,dead=false,revived=false,presenceCalls=0;
  class Clock extends Date {
    static now(){return fakeTime}
  }
  const document={
    hidden:false,body:fakeElement('body'),addEventListener(){},
    getElementById:id=>nodes[id]||(nodes[id]=fakeElement(id)),
    createElement:fakeElement
  };
  const layer=()=>({
    events:{},addTo(){return this},clearLayers(){return this},
    on(name,handler){this.events[name]=handler;return this},
    bindTooltip(){return this},setStyle(){return this},setRadius(){return this},
    setLatLng(){return this},getBounds(){return{pad(){return this}}}
  });
  const map={attributionControl:{setPrefix(){}},setView(){return this},
    on(){return this},getZoom(){return 14},flyTo(){},flyToBounds(){},
    fitBounds(){},invalidateSize(){},removeLayer(){}};
  const L={map:()=>map,tileLayer:layer,polygon:layer,circle:layer,
    marker:layer,layerGroup:layer,divIcon:()=>({}),latLngBounds:()=>({})};
  const zone={id:zoneId,name:'Квартал ЛБ',lat:53.39,lon:59.06,kind:'block',
    polygon:[],size:'Малый',owner_name:'Игрок',official_name:'',address:'Левый берег'};
  function world(){return {...zone,mine:!dead,occupied:!dead,
    owner_name:dead?null:'Игрок'};}
  const gpsFix=()=>({coords:{latitude:53.39,longitude:59.06,accuracy:5},
    timestamp:fakeTime});
  const navigator={
    permissions:{query:async()=>({state:'granted'})},
    geolocation:{
      getCurrentPosition(success){success(gpsFix())},
      watchPosition(success){watch=success;return 42},
      clearWatch(){}
    }
  };
  const window={
    L,innerHeight:750,addEventListener(){},
    localStorage:{getItem(){return'dark'},setItem(){}},
    Telegram:{WebApp:{
      initData:'test',ready(){},expand(){},setHeaderColor(){},
      setBackgroundColor(){},BackButton:{show(){},onClick(){}},
      HapticFeedback:{notificationOccurred(){},selectionChanged(){}}
    }}
  };
  async function fetch(url,options={}){
    posts.push(url);
    if(url==='/api/city/state') return{ok:true,json:async()=>({
      zones:[world()],leaderboard:[],catalog:[],my_pets:[],guards:[],
      wallet:450,pending_stars:0,can_capture:true,
      hp:dead?0:revived?100:0.4,max_hp:100,dead,deaths:dead?1:revived?1:0,
      zones_lost:dead?1:revived?1:0,
      my_zones:dead?0:1,total_captures:1,cooldown_remaining_s:0
    })};
    if(url==='/api/city/road-shapes')return{ok:true,json:async()=>({shapes:{},extra_count:0})};
    if(url==='/api/city/presence') {
      presenceCalls++;
      if(lethal) {
        dead=true;
        return{ok:true,json:async()=>({
          hp:0,max_hp:100,dead:true,died:true,deaths:1,
          zones_lost:1,zone_id:12,attacked_by:'lion'
        })};
      }
      return{ok:true,json:async()=>({hp:0.4,max_hp:100,dead:false,died:false,
        zone_id:null,attacked_by:null})};
    }
    if(url==='/api/city/respawn') {
      assert.equal(options.method,'POST','rebirth must use authenticated POST');
      assert.equal(dead,true,'cannot respawn while alive');
      dead=false;revived=true;lethal=false;
      return{ok:true,json:async()=>({hp:100,max_hp:100,dead:false,
        deaths:1,zones_lost:1})};
    }
    throw Error('Unexpected URL: '+url);
  }
  new Function('document','window','navigator','L','fetch','setTimeout',
    'clearTimeout','setInterval','requestAnimationFrame','Date',source)(
    document,window,navigator,L,fetch,()=>1,()=>{},()=>1,fn=>fn(),Clock
  );
  await flush();
  assert.equal(nodes.deathScreen.hidden,true,'death screen must be hidden while alive');
  assert.equal(nodes.hpHud.textContent,'1','alive HP must be visible');
  assert.equal(typeof watch,'function','consented GPS watch must be active');
  assert.equal(nodes.myZonesList.children.length,1,'area starts under player control');

  fakeTime += 18000;
  lethal=true;
  watch(gpsFix());
  await flush();
  assert.equal(dead,true);
  assert.equal(nodes.deathScreen.hidden,false,'fatal GPS hit opens death screen');
  assert.equal(nodes.deathLost.textContent,'1','death screen shows lost territories');
  assert.equal(nodes.hpHud.textContent,'0','HP must reach 0 instead of stopping at 1');
  assert.equal(nodes.myZonesList.children.length,1,'empty my-zones prompt shown');
  assert.equal(nodes.myZonesList.children[0].className,'my-zones-empty');
  assert.equal(document.body.classList.contains('city-is-dead'),true);
  const previousPresenceCalls=presenceCalls;
  fakeTime += 18000;
  watch(gpsFix());
  await flush();
  assert.equal(presenceCalls,previousPresenceCalls,
    'dead player does not repeatedly lose territories or receive damage');
  nodes.respawn.click();
  await flush();
  assert.equal(revived,true,'respawn endpoint called');
  assert.equal(nodes.deathScreen.hidden,true,'death screen closes after server confirms');
  assert.equal(nodes.hpHud.textContent,'100','respawn restores 100 HP');
  assert.equal(nodes.hpFill.style.width,'100%','market HP is full after respawn');
  assert.equal(document.body.classList.contains('city-is-dead'),false);
  assert.ok(posts.includes('/api/city/respawn'));
  assert.equal(nodes.mapView.hidden,false,'player returns to main map');
  console.log('City death, free territories, zero HP and explicit respawn UI OK');
})().catch(error=>{console.error(error);process.exitCode=1});
