(()=>{
'use strict';
const tg=window.Telegram?.WebApp;tg?.ready();tg?.expand();
const $=id=>document.getElementById(id);
const map=L.map('map',{zoomControl:false}).setView([53.407,58.98],12);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
let canCapture=false;let selected=null,shapes=[],myMarker=null,accuracyRing=null,position=null,zones=[];
const colors=['#9c64ff','#ff648d','#40b5ef','#f7ac44','#52d7a0','#df73dd'];
const message=t=>$('status').textContent=t;
async function api(path,options={}){
 const response=await fetch(path,{...options,headers:{'X-Telegram-Init-Data':tg?.initData||'',...(options.headers||{})}});
 if(!response.ok){const err=await response.text();throw Error(err.slice(0,180)||'Ошибка '+response.status)}
 return response.json();
}
function sector(zone,index){
 // Игровые секторы разных размеров. Это не кадастровые границы.
 const size=[0.003,0.0046,0.0022,0.006][index%4],width=size*1.45;
 const {lat,lon}=zone;
 return [[lat-size,lon-width],[lat-size*.72,lon+width*.6],[lat+size*.7,lon+width],[lat+size,lon-width*.3]];
}
function select(z,shape){
 selected=z;$('zone').textContent=z.name;
 $('owner').textContent=z.occupied?'Владелец: '+(z.owner_name||'Аноним'):'Свободная территория';
 $('capture').disabled=!canCapture||!!z.mine;
 message(z.mine?'Это твоя территория': 'Подойди к точке захвата внутри сектора. Нужна точность GPS до 75 м.');
 if(shape)map.fitBounds(shape.getBounds(),{padding:[35,35],maxZoom:16});
}
function renderTop(rows){
 const root=$('leaders');root.replaceChildren();
 if(!rows.length){const li=document.createElement('li');li.textContent='Пока нет захватов';root.append(li);return}
 for(const p of rows){const li=document.createElement('li');li.textContent=p.name+(p.mine?' (ты)':'');const b=document.createElement('b');b.textContent=p.zones+' районов';li.append(b);root.append(li)}
}
function showTop(on){$('leaderboard').classList.toggle('open',on);$('showtop').classList.toggle('active',on);$('showmap').classList.toggle('active',!on);if(on){$('panel').scrollTo({top:0,behavior:'smooth'})}}
async function load(){
 try{
  const data=await api('/api/city/state');canCapture=!!data.can_capture;zones=data.zones;$('capture').textContent=canCapture?'ЗАХВАТИТЬ РАЙОН':'ЗАХВАТ ТОЛЬКО ДЛЯ АДМИНОВ';
  shapes.forEach(s=>map.removeLayer(s));shapes=[];
  zones.forEach((z,i)=>{
   const color=z.mine?'#35e2a5':z.occupied?colors[(i+2)%colors.length]:colors[i%colors.length];
   const polygon=L.polygon(sector(z,i),{color,weight:3,opacity:1,fillColor:color,fillOpacity:z.occupied?.38:.19}).addTo(map);
   polygon.bindTooltip(z.name+' · '+(z.owner_name||'Свободно'),{direction:'center',className:'territory-tooltip'});
   polygon.on('click',()=>select(z,polygon));shapes.push(polygon);
   const dot=L.circleMarker([z.lat,z.lon],{radius:4,color:'#fff',weight:2,fillColor:color,fillOpacity:1}).addTo(map);
   dot.on('click',()=>select(z,polygon));shapes.push(dot);
  });
  $('count').textContent=zones.filter(z=>z.occupied).length+'/'+zones.length+' занято';
  renderTop(data.leaderboard||[]);
  if(selected){const latest=zones.find(z=>z.id===selected.id);if(latest){selected=latest;$('zone').textContent=latest.name;$('owner').textContent=latest.occupied?'Владелец: '+(latest.owner_name||'Аноним'):'Свободная территория';$('capture').disabled=!canCapture||!!latest.mine}}
  if(!zones.length)message('Территории ещё не добавлены');
 }catch(e){message('Ошибка загрузки: '+e.message)}
}
function locate(callback){
 if(!navigator.geolocation){message('Геолокация не поддерживается');return}
 message('Определяем твою позицию…');
 navigator.geolocation.getCurrentPosition(p=>{
  position=p;
  const {latitude:lat,longitude:lon,accuracy}=p.coords;
  if(myMarker)map.removeLayer(myMarker);
  if(accuracyRing)map.removeLayer(accuracyRing);
  accuracyRing=L.circle([lat,lon],{radius:Math.max(accuracy,8),color:'#00c9ff',weight:1,fillOpacity:.09}).addTo(map);
  myMarker=L.marker([lat,lon],{icon:L.divIcon({className:'',html:'<div style="width:23px;height:23px;border:4px solid white;border-radius:50%;background:#009dff;box-shadow:0 0 0 8px #009dff55,0 3px 14px #0009"></div>',iconSize:[23,23],iconAnchor:[11,11]})}).addTo(map);
  myMarker.bindTooltip('ТЫ ЗДЕСЬ',{permanent:true,direction:'top',offset:[0,-12]});
  map.setView([lat,lon],Math.max(map.getZoom(),15));
  message('Ты на карте · точность '+Math.round(accuracy)+' м');
  callback?.(p);
 },err=>message('GPS: '+err.message+'. Проверь доступ к геопозиции в Telegram и настройках телефона.'),{enableHighAccuracy:true,maximumAge:0,timeout:15000});
}
$('locate').onclick=()=>locate();
$('refresh').onclick=load;
$('topbutton').onclick=()=>showTop(true);
$('showtop').onclick=()=>showTop(true);
$('showmap').onclick=()=>showTop(false);
$('capture').onclick=()=>{
 if(!selected)return;const z=selected;$('capture').disabled=true;
 locate(async p=>{
  try{
   await api('/api/city/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({zone_id:z.id,lat:p.coords.latitude,lon:p.coords.longitude,accuracy_m:p.coords.accuracy,timestamp_s:p.timestamp/1000})});
   await load();message('Территория захвачена!');tg?.HapticFeedback?.notificationOccurred('success');
  }catch(e){message('Не удалось захватить: '+e.message)}
  finally{$('capture').disabled=false}
 });
};
load();
})();