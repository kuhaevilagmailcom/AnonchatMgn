/* Chromium smoke tests for the MGN ZAHVAT game layout. */
'use strict';
const assert=require('node:assert/strict');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..','miniapp','web');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png'};
const zoneNames=['Парк','Притяжение','Сквер','Ветеранов','Стела','Ашик','Гостинка','Контик','Джазик','Ленинский район','Экопарк','Пикник'];
const zones=zoneNames.map((name,i)=>({
  id:i+1,name,kind:i===9?'district':i>=5&&i<=8?'mall':'park',
  official_name:name==='Ашик'?'ТРК «Семейный парк»':name,address:'Магнитогорск',
  lat:53.39+i*.003,lon:58.98+i*.001,
  polygon:[[53.39+i*.003,58.98],[53.391+i*.003,58.981],[53.391+i*.003,58.982]],
  mine:false,occupied:false,size:'Малый'
}));
const data=JSON.stringify({can_capture:true,cooldown_remaining_s:0,my_zones:0,total_captures:0,
  capture_radius_m:100,max_accuracy_m:75,zones,leaderboard:[]});
const server=http.createServer((req,res)=>{
  const route=new URL(req.url,'http://127.0.0.1').pathname;
  if(route==='/api/city/state'){
    res.writeHead(200,{'Content-Type':'application/json'});return res.end(data);
  }
  const file=path.resolve(root,'.'+decodeURIComponent(route==='/'?'/index.html':route));
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){
    res.writeHead(404);return res.end('Not found');
  }
  res.writeHead(200,{'Content-Type':types[path.extname(file)]||'application/octet-stream'});
  fs.createReadStream(file).pipe(res);
});
const leafletStub='('+function fakeLeaflet(){
  function item(){return{addTo(){return this},on(){return this},setStyle(){return this},bindTooltip(){return this},
    getBounds(){return{pad(){return this}}},clearLayers(){return this}}}
  const map={setView(){return this},on(){return this},getZoom(){return 14},fitBounds(){},flyToBounds(){},
    flyTo(){},invalidateSize(){},removeLayer(){}};
  window.L={map(){return map},tileLayer:item,layerGroup:item,polygon:item,circle:item,circleMarker:item,
    latLngBounds(){return{}},divIcon(o){return o},tooltip(){return{setContent(){return this}}},
    marker(coords,opts){
      const el=document.createElement('button');
      el.type='button';el.className=opts.icon?.className||'test-marker';
      const index=window.__fakePinIndex||0;window.__fakePinIndex=index+1;
      el.style.cssText='position:absolute;z-index:500;left:'+(37+(index%3)*61)+'px;top:'+(211+Math.floor((index%12)/3)*53)+'px';
      el.innerHTML=opts.icon?.html||'';
      el.setAttribute('aria-label',opts.title||'GPS');
      document.getElementById('map').append(el);
      return{addTo(){return this},on(name,fn){el.addEventListener(name,fn);return this},bindTooltip(){return this}};
    }
  };
}.toString()+')();';
(async()=>{
  const chrome=process.env.CHROME_BIN||['/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium'].find(fs.existsSync);
  assert.ok(chrome,'Chrome required');
  await new Promise(ok=>server.listen(0,'127.0.0.1',ok));
  let browser;
  try{
    browser=await chromium.launch({executablePath:chrome,headless:true,args:['--no-sandbox']});
    for(const width of [320,360,390,430]){
      const context=await browser.newContext({viewport:{width,height:740},isMobile:true,hasTouch:true});
      try{
        const page=await context.newPage(),errors=[];
        page.on('pageerror',e=>errors.push(e.message));
        await page.route('https://telegram.org/js/telegram-web-app.js',r=>r.fulfill({status:200,contentType:'application/javascript',body:''}));
        await page.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',r=>r.fulfill({status:200,contentType:'application/javascript',body:leafletStub}));
        await page.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',r=>r.fulfill({status:200,contentType:'text/css',body:'.leaflet-container{position:relative}'}));
        await page.addInitScript(()=>{
          window.Telegram={WebApp:{initData:'test',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},
            HapticFeedback:{selectionChanged(){}},BackButton:{show(){},onClick(){}}}};
        });
        await page.goto('http://127.0.0.1:'+server.address().port+'/city.html',{waitUntil:'domcontentloaded'});
        await page.waitForFunction(()=>document.querySelector('#count')?.textContent==='0 / 12',{timeout:5000});
        assert.deepEqual(errors,[],width+'px page errors');
        const sizes=await page.evaluate(()=>{
          const rect=selector=>{const r=document.querySelector(selector).getBoundingClientRect();
            return{width:r.width,height:r.height}};
          return{scroll:document.documentElement.scrollWidth,map:rect('#map'),panel:rect('#panel'),
            tabs:Array.from(document.querySelectorAll('#tabs button')).map(b=>rect('#'+b.id)),
            icons:document.querySelectorAll('.zone-pin-inner svg').length};
        });
        assert.ok(sizes.scroll<=width+1,width+'px horizontal overflow');
        assert.ok(Math.abs(sizes.panel.width-width)<=1,width+'px panel not full width');
        assert.ok(sizes.panel.height<=275,width+'px panel too tall: '+sizes.panel.height);
        assert.ok(sizes.map.height>=740,width+'px map not full screen');
        assert.ok(sizes.tabs.every(t=>t.width>70),width+'px tab too narrow');
        assert.equal(sizes.icons,12,width+'px expected 12 icon pins');
        assert.ok(sizes.panel.height<=130,width+'px empty panel takes too much map');
        assert.equal(await page.locator('#capture').isVisible(),false,
          width+'px capture action should only appear after choosing a place');
        assert.equal(await page.locator('#ownerCard').isVisible(),false,
          width+'px owner row should stay hidden until a zone is selected');
        assert.equal(await page.locator('#distance').count(),0,
          width+'px persistent distance instructions returned');
        assert.equal(await page.locator('#gpsQuality').count(),0,
          width+'px persistent GPS instructions returned');
        await page.click('#theme');
        assert.equal(await page.locator('body').getAttribute('data-map-theme'),'light');
        await page.click('#theme');
        assert.equal(await page.locator('body').getAttribute('data-map-theme'),'dark');
        await page.locator('[aria-label="Ашик"]').click();
        assert.equal(await page.locator('#zone').textContent(),'Ашик');
        assert.equal(await page.locator('#ownerCard').isVisible(),true);
        assert.equal(await page.locator('#capture').isVisible(),true);
        const dock=await page.evaluate(()=>{
          const box=id=>document.querySelector(id).getBoundingClientRect();
          return {panel:box('#panel').height,captureBottom:box('#capture').bottom,navTop:box('#tabs').top};
        });
        assert.ok(dock.panel<=202,width+'px selected panel too tall: '+dock.panel);
        assert.ok(dock.captureBottom<=dock.navTop+1,
          width+'px capture button is hidden underneath navigation');
        assert.match(await page.locator('#zoneDetails').textContent(),/Семейный парк/);
        await page.click('#showtop');
        assert.equal(await page.locator('#leaderboard').isVisible(),true);
        await page.click('#showmap');
        await page.click('#sheetToggle');
        assert.ok((await page.locator('#panel').getAttribute('class')).includes('is-expanded'));
        assert.deepEqual(errors,[],width+'px errors after interaction');
        console.log('City mobile UI OK: '+width+'px');
      }finally{await context.close()}
    }
  }finally{
    if(browser)await browser.close();
    await new Promise(ok=>server.close(ok));
  }
})().catch(error=>{console.error(error);process.exitCode=1});
