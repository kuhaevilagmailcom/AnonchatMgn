(() => {
'use strict';
const tg=window.Telegram?.WebApp;tg?.ready();tg?.expand();
const $=id=>document.getElementById(id);
const map=L.map('map',{zoomControl:false}).setView([53.407,58.98],12);
L.control.zoom({position:'topright'}).addTo(map);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
const headers=()=>({'X-Telegram-Init-Data':tg?.initData||''});
let selected=null,markers=[],positionMarker=null,playerId=null,zones=[];
function message(s){$('status').textContent=s}
async function api(path,opts={}){
 const response=await fetch(path,{...opts,headers:{...headers(),...(opts.headers||{})}});
 if(!response.ok){let msg='Ошибка '+response.status;try{const body=await response.json();msg=body.message||msg}catch{msg=await response.text()||msg}throw Error(msg)}
 return response.json();
}
function locate(onSuccess){
 if(!navigator.geolocation){message('GPS недоступен в этом браузере');return}
 message('Запрашиваем геолокацию…');
 navigator.geolocation.getCurrentPosition(p=>{
  const coords=p.coords;
  if(positionMarker)map.removeLayer(positionMarker);
  positionMarker=L.circle([coords.latitude,coords.longitude],{radius:Math.max(10,coords.accuracy),color:'#4adeb0',fillOpacity:.15}).addTo(map);
  map.setView([coords.latitude,coords.longitude],Math.max(15,map.getZoom()));
  message('Позиция найдена. Точность: '+Math.round(coords.accuracy)+' м');
  onSuccess?.(p);
 },e=>message('Геолокация: '+e.message+' — проверь разрешения Telegram и iOS'),{enableHighAccuracy:true,maximumAge:0,timeout:15000});
}
async function load(){
 try{
  const state=await api('/api/city/state');playerId=state.user_id;zones=state.zones;
  markers.forEach(m=>map.removeLayer(m));markers=[];
  for(const z of zones){
   const owned=z.mine;const marker=L.circleMarker([z.lat,z.lon],{radius:12,weight:2,color:owned?'#4adeb0':z.occupied?'#ff687f':'#a879ff',fillOpacity:.65}).addTo(map);
   marker.bindTooltip(z.name);
   marker.on('click',()=>{
    selected=z;$('zone').textContent=z.name;
    $('capture').disabled=owned;
    message(owned?'Твоя территория':'Подойди к точке в радиусе 100 метров и нажми «Захватить»');
   });
   markers.push(marker);
  }
  $('count').textContent=zones.length+' точек';
  if(!zones.length)message('Игровые точки пока не опубликованы');
 }catch(e){message(e.message)}
}
$('locate').addEventListener('click',()=>locate());
$('refresh').addEventListener('click',load);
$('capture').addEventListener('click',()=>{
 if(!selected)return;
 const zone=selected;$('capture').disabled=true;
 locate(async p=>{
  try{
   const result=await api('/api/city/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
    zone_id:zone.id,lat:p.coords.latitude,lon:p.coords.longitude,accuracy_m:p.coords.accuracy,timestamp_s:p.timestamp/1000
   })});
   await load();message('Захвачено: '+zone.name);tg?.HapticFeedback?.notificationOccurred('success');
  }catch(e){message(e.message)}
  finally{$('capture').disabled=false}
 });
});
load();
})();