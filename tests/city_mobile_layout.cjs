/* Chromium smoke tests for the MGN ZAHVAT game layout. */
'use strict';
const assert=require('node:assert/strict');
const http=require('node:http');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..','miniapp','web');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png'};
const zoneNames=['Парк','Притяжение','Сквер','Ветеранов','Стела','Ашик','Гостинка','Контик','Джазик','Ленинский район','Экопарк','Пикник','Площадь Победы','Соцгород','Комсомольская площадь','Левобережный ДК'];
const zones=zoneNames.map((name,i)=>({
  id:i+1,name,kind:i===9?'district':i>=5&&i<=8?'mall':'park',
  official_name:name==='Ашик'?'ТРК «Семейный парк»':name,address:'Магнитогорск',
  lat:53.39+i*.003,lon:58.98+i*.001,
  polygon:[[53.39+i*.003,58.98],[53.391+i*.003,58.981],[53.391+i*.003,58.982]],
  mine:i===0,occupied:i===0,size:'Малый'
}));
const cat={kind:'cat',name:'Кот',emoji:'🐈',price:100,stars_h:1,hp_5m:.5};
const pet={id:77,kind:'cat',name:'Кот',emoji:'🐈',rarity:'common',
  rarity_name:'Обычный',level:2,pet_hp:100,zone_id:1,
  stars_h:1.12,hp_5m:.54,upgrade_cost:300,
  next_stats:{level:3,stars_h:1.24,hp_5m:.58}};
const data=JSON.stringify({can_capture:true,cooldown_remaining_s:0,my_zones:1,total_captures:1,
  capture_radius_m:100,max_accuracy_m:75,zones,leaderboard:[],
  wallet:1200,hp:97.5,dead:false,pending_stars:1,
  catalog:[cat],my_pets:[{id:77,kind:'cat',zone_id:1,level:2,active:true}],
  guards:[{zone_id:1,kind:'cat',mine:true,level:2,hp_5m:.54,stars_h:1.12}],
  inventory_pets:[pet],items:[{kind:'medkit',emoji:'❤️',name:'Аптечка',
    rarity:'common',quantity:2,description:'Восстанавливает HP'}],
  effects:[],premium_catalog:[
    {kind:'panda',name:'Панда',emoji:'🐼',rarity:'rare',xtr:15,stars_h:7,hp_5m:2},
    {kind:'wolf',name:'Волк',emoji:'🐺',rarity:'epic',xtr:25,stars_h:10,hp_5m:2.6},
    {kind:'dragon',name:'Дракон',emoji:'🐉',rarity:'legendary',xtr:50,stars_h:15,hp_5m:3.6}
  ],
  chests:[{id:'cycle-1',kind:'common',emoji:'📦',lat:53.39,lon:58.98,
    place:'Парк у Вечного огня',expires_at:9999999999,opened:false}],
  warehouse:null,invitations:[]
});
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
      el.style.cssText='position:absolute;z-index:'+(500+Number(opts.zIndexOffset||0))+';left:'+(37+(index%3)*61)+'px;top:'+(211+Math.floor((index%12)/3)*53)+'px';
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
        // Avoid fetching third-party mapping bundles during UI geometry tests.
        await page.route('https://unpkg.com/**',r=>r.fulfill({
          status:200,contentType:r.request().url().endsWith('.css')?'text/css':'application/javascript',body:''
        }));
        await page.route('https://telegram.org/js/telegram-web-app.js',r=>r.fulfill({status:200,contentType:'application/javascript',body:''}));
        await page.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',r=>r.fulfill({status:200,contentType:'application/javascript',body:leafletStub}));
        await page.route('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',r=>r.fulfill({status:200,contentType:'text/css',body:'.leaflet-container{position:relative}'}));
        await page.addInitScript(()=>{
          window.Telegram={WebApp:{initData:'test',ready(){},expand(){},setHeaderColor(){},setBackgroundColor(){},
            HapticFeedback:{selectionChanged(){}},BackButton:{show(){},onClick(){}}}};
        });
        await page.goto('http://127.0.0.1:'+server.address().port+'/city.html',{waitUntil:'domcontentloaded'});
        await page.waitForFunction(()=>document.querySelector('#hpHud')?.textContent==='98',{timeout:5000});
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
        assert.equal(sizes.icons,16,width+'px expected 16 icon pins');
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
        const lightSector = await page.locator('[aria-label="Ашик"] .zone-pin-inner').last()
          .evaluate(el => ({
            color:el.style.getPropertyValue('--zone-color'),
            background:getComputedStyle(el).backgroundColor,
            border:getComputedStyle(el).borderColor
          }));
        assert.equal(lightSector.color,'#565d68',
          width+'px free-sector color has insufficient contrast in light mode');
        assert.equal(lightSector.background,'rgb(255, 255, 255)',
          width+'px light mode must use a light pin background');
        await page.click('#theme');
        assert.equal(await page.locator('body').getAttribute('data-map-theme'),'dark');
        const darkSector = await page.locator('[aria-label="Ашик"] .zone-pin-inner').last()
          .evaluate(el=>el.style.getPropertyValue('--zone-color'));
        assert.equal(darkSector,'#80767d',
          width+'px dark theme did not restore original area colors');
        assert.notEqual(lightSector.color,darkSector);
        // Fake Leaflet does not remove stale DOM markers on redraw.
        // The last one represents the current light/dark redraw.
        await page.locator('[aria-label="Ашик"]').last().click();
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
        assert.equal(await page.locator('#districtInventory').isVisible(),true);
        assert.equal(await page.locator('#inventoryContent [data-pet-id]').count(),1,
          width+'px purchased pet missing from inventory');
        await page.locator('#inventoryContent [data-pet-id]').first().click();
        assert.ok(await page.locator('#petDetails').isVisible(),
          width+'px tapping pet must open details, not alert');
        assert.match(await page.locator('#petDetailsBody').textContent(),/Кот/);
        assert.match(await page.locator('#petDetailsBody').textContent(),/Ур. 2/);
        assert.match(await page.locator('#petDetailsBody').textContent(),/HP/);
        assert.match(await page.locator('#petDetailsBody').textContent(),/БЫЛО → СТАЛО/);
        assert.equal(await page.locator('#petTargetZone').count(),0,
          width+'px deployed pet should show recall, not district selector');
        await page.click('#closePetDetails');
        assert.ok(await page.locator('#petDetails').isHidden());
        await page.click('#showmarket');
        assert.equal(await page.locator('#premiumCatalog [data-action=premium]').count(),3,
          width+'px XTR premium catalog must show 15, 25 and 50 Telegram Stars');
        assert.match(await page.locator('#premiumCatalog').textContent(),/15 Telegram Stars/);
        await page.click('#showrules');
        assert.ok(await page.locator('#districtMore').isVisible());
        await page.locator('[data-more-page=warehouses]').click();
        assert.ok(await page.locator('#districtWarehouses').isVisible());
        assert.ok(await page.locator('#warehouseCreate').isVisible(),
          width+'px warehouse create form missing');
        await page.click('#showmap');
        const chestMarker=page.locator('.district-chest-icon');
        assert.ok(await chestMarker.count()>0,
          width+'px chest emoji should be on the map');
        // Temporary messages can legitimately cover a pin for a few seconds.
        // Dismiss them before testing the actual on-screen tap.
        await page.locator('#toast').evaluate(node=>{node.hidden=true});
        await chestMarker.last().click();
        assert.ok(await page.locator('#chestDetails').isVisible(),
          width+'px tapping chest should open real game modal');
        assert.match(await page.locator('#chestDetailsTitle').textContent(),/Сундук/);
        assert.ok(await page.locator('#openChest').isVisible(),
          width+'px chest needs a GPS opening action');
        await page.locator('#closeChestDetails').click();
        assert.ok(await page.locator('#chestDetails').isHidden());
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
