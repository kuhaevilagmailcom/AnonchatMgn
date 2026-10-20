/* GPS regression tests for the Telegram city game: automatic updates with consent. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.resolve(__dirname,'../miniapp/web/city.js'),'utf8');

async function scenario(granted){
  const nodes={};let watchCallback=null,updates=0,centres=0;
  const make=id=>({
    id,hidden:false,disabled:false,textContent:'',children:[],attrs:{},className:'',
    dataset:{},classList:{add(){},remove(){},toggle(){}},
    addEventListener(){},append(){},replaceChildren(){},setAttribute(){},removeAttribute(){}
  });
  const document={
    hidden:false,body:make('body'),createElement:make,
    getElementById:id=>nodes[id]||(nodes[id]=make(id)),addEventListener(){}
  };
  function layer(){return{
    addTo(){return this},on(){return this},bindTooltip(){return this},
    setLatLng(){updates++;return this},setRadius(){return this},setStyle(){return this},
    getBounds(){return{pad(){return this}}}
  }}
  const map={attributionControl:{setPrefix(){}},setView(){return this},
    on(){return this},getZoom(){return 15},fitBounds(){},flyTo(){centres++},
    flyToBounds(){},removeLayer(){},invalidateSize(){}};
  const L={map:()=>map,tileLayer:layer,layerGroup:()=>({addTo(){return this},clearLayers(){}}),
    polygon:layer,circle:layer,marker:layer,divIcon:x=>x,latLngBounds:()=>({})};
  let watchStarts=0;
  const navigator={
    permissions:{query:async()=>({state:granted?'granted':'denied'})},
    geolocation:{
      getCurrentPosition(ok){ok({coords:{latitude:53.393547,longitude:59.063386,accuracy:12},timestamp:Date.now()})},
      watchPosition(ok){watchStarts++;watchCallback=ok;return 1},
      clearWatch(){}
    }
  };
  const window={L,innerHeight:740,addEventListener(){},setInterval(){return 1},clearInterval(){},
    setTimeout(){return 1},localStorage:{getItem(){return'dark'},setItem(){}},
    Telegram:{WebApp:{initData:'mock',ready(){},expand(){},setHeaderColor(){},
      setBackgroundColor(){},BackButton:{show(){},onClick(){}}}}};
  const fetch=async url=>({ok:true,json:async()=>url.endsWith('/road-shapes')?
    {shapes:{}}:{zones:[],leaderboard:[],can_capture:true,cooldown_remaining_s:0}});
  new Function('document','window','navigator','L','fetch','setTimeout','clearTimeout',
    'setInterval','requestAnimationFrame',source)(
      document,window,navigator,L,fetch,()=>1,()=>{},()=>1,fn=>fn());
  for(let i=0;i<50;i++)await Promise.resolve();
  if(granted){
    assert.equal(watchStarts,1,'permission must auto-start native GPS watch');
    assert.ok(centres>=1,'map must show first granted position');
    const originalCentres=centres;
    watchCallback({coords:{latitude:53.394,longitude:59.064,accuracy:8},timestamp:Date.now()});
    assert.ok(updates>=2,'marker and accuracy circle must move with position');
    assert.equal(centres,originalCentres,'auto-tracking must not recenter while exploring');
  }else{
    assert.equal(watchStarts,0,'no GPS request if permission was not granted');
    assert.equal(centres,0,'do not move to position without prior consent');
  }
}

(async()=>{
  await scenario(true);
  await scenario(false);
  console.log('City GPS consent, automatic marker updates and stable camera OK');
})().catch(error=>{console.error(error);process.exitCode=1});
