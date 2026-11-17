const DATA = {
  day: { users: '2 106', messages: '71 482', session: '17:58', safe: '98,9%', values: [12, 18, 16, 25, 38, 51, 67, 74, 70, 82, 92, 86], labels: ['00','02','04','06','08','10','12','14','16','18','20','22'] },
  week: { users: '12 842', messages: '486 291', session: '18:42', safe: '98,7%', values: [42, 55, 49, 73, 67, 96, 114], labels: ['Пн','Вт','Ср','Чт','Пт','Сб','Вс'] },
  month: { users: '38 940', messages: '1 842 604', session: '19:06', safe: '98,4%', values: [42, 48, 53, 50, 62, 68, 71, 75, 79, 84, 92, 101], labels: ['1','3','6','9','12','15','18','21','24','27','29','30'] }
};

const dialogs = [
  ['#A8F2-91C','Музыка и кино','18:42','142','В диалоге'],['#C44B-20E','Отношения','12:08','87','В диалоге'],['#19D7-A2F','Игры','09:31','64','В диалоге'],['#7BE1-40D','Жизнь и учёба','24:16','211','Завершён'],['#52AA-77C','Путешествия','06:49','39','В диалоге'],['#F11C-89B','Без темы','03:15','18','Завершён'],['#904E-33A','Музыка и кино','31:02','286','В диалоге']
];
const cases = [
  {risk:'high',label:'Высокий',text:'Повторные оскорбления после предупреждения',id:'#M-8291 · диалог A8F2-91C'},
  {risk:'medium',label:'Средний',text:'Подозрение на нежелательный контакт',id:'#M-8288 · диалог 19D7-A2F'},
  {risk:'high',label:'Высокий',text:'Автофильтр обнаружил угрозу',id:'#M-8274 · диалог 52AA-77C'},
  {risk:'medium',label:'Средний',text:'Массовая отправка одинаковых сообщений',id:'#M-8269 · диалог C44B-20E'}
];

const $ = (q, root=document) => root.querySelector(q);
const $$ = (q, root=document) => [...root.querySelectorAll(q)];
let currentPeriod = 'week';
const tg = window.Telegram?.WebApp;

function formatNumber(value) { return Number(value || 0).toLocaleString('ru-RU'); }

async function adminApi(path, params = {}) {
  const query = new URLSearchParams(params).toString();
  const response = await fetch(`/api/miniapp/admin${path}${query ? `?${query}` : ''}`, {
    cache: 'no-store',
    headers: {'X-Telegram-Init-Data': tg?.initData || ''}
  });
  let body = {};
  try { body = await response.json(); } catch (_) {}
  if (!response.ok) throw new Error(body.error || body.message || `Ошибка ${response.status}`);
  return body;
}

function showAuthCover(message) {
  const cover = document.createElement('div');
  cover.className = 'auth-cover';
  cover.innerHTML = `<div><h2>Аналитика закрыта</h2><p>${message}</p><button type="button">Вернуться в Mini App</button></div>`;
  cover.querySelector('button').onclick = () => location.href = '../';
  document.body.append(cover);
}

async function loadLiveData() {
  if (!tg?.initData) {
    showAuthCover('Открой эту страницу через кнопку в Telegram-боте. Так мы проверим, что ты администратор, и покажем реальные данные.');
    return;
  }
  try {
    tg.ready(); tg.expand();
    const [dashboard, analytics] = await Promise.all([
      adminApi('/bootstrap'), adminApi('/analytics', {period: '7'})
    ]);
    const s = dashboard.stats || {};
    DATA.week.users = formatNumber(s.active_week);
    DATA.week.messages = formatNumber(s.messages_week);
    const activity = (analytics.message_activity || []).map(x => Number(x.messages) || 0);
    if (activity.length) DATA.week.values = activity;
    DATA.week.labels = (analytics.message_activity || []).map(x => new Intl.DateTimeFormat('ru-RU', {weekday:'short'}).format(new Date(Number(x.day_start) * 1000)).replace('.', ''));
    $('[data-metric="users"]').textContent = formatNumber(s.active_week);
    $('[data-metric="messages"]').textContent = formatNumber(s.messages_week);
    $('#onlineNow').textContent = formatNumber(dashboard.online);
    const liveParts = $$('.live-stats strong');
    if (liveParts[0]) liveParts[0].textContent = formatNumber(dashboard.queue);
    if (liveParts[1]) liveParts[1].textContent = formatNumber(Number(dashboard.dialogs || 0) * 2);
    const funnelValues = $$('.funnel > div > strong');
    if (funnelValues[0]) funnelValues[0].textContent = formatNumber(s.users);
    if (funnelValues[2]) funnelValues[2].firstChild.textContent = `${formatNumber(s.active_week)} `;
    const dialogSummary = $$('.dialog-summary strong');
    if (dialogSummary[0]) dialogSummary[0].textContent = formatNumber(dashboard.dialogs);
    const totalLabels = $$('.intel-metrics strong');
    if (totalLabels[0]) totalLabels[0].textContent = formatNumber(s.dialogs);
    setPeriod('week');
    const badge = document.createElement('div'); badge.className = 'live-source-badge'; badge.textContent = '● РЕАЛЬНЫЕ ДАННЫЕ'; document.body.append(badge);
  } catch (error) {
    showAuthCover(error.message.includes('403') ? 'У этого аккаунта нет доступа к административной статистике.' : error.message);
  }
}

function renderMiniBars() {
  const heights = [11,18,15,24,21,30,27,34,26,32];
  $('[data-bars="users"]').innerHTML = heights.map(h => `<i style="height:${h}px"></i>`).join('');
}

function setupNavigation() {
  $$('.nav-item').forEach(link => link.addEventListener('click', e => {
    e.preventDefault();
    const id = link.dataset.section;
    $$('.nav-item').forEach(x => x.classList.toggle('active', x === link));
    $$('.page-section').forEach(x => x.classList.toggle('active', x.id === id));
    $('.sidebar').classList.remove('open');
    history.replaceState(null, '', `#${id}`);
    window.scrollTo({top:0,behavior:'smooth'});
  }));
  $('.mobile-menu').addEventListener('click', () => $('.sidebar').classList.toggle('open'));
  document.addEventListener('click', e => {
    if (innerWidth <= 780 && !e.target.closest('.sidebar') && !e.target.closest('.mobile-menu')) $('.sidebar').classList.remove('open');
  });
}

function openInitialSection() {
  const requested = location.hash.slice(1);
  const id = ['overview','audience','dialogs','retention','moderation'].includes(requested) ? requested : 'overview';
  $$('.nav-item').forEach(x => x.classList.toggle('active', x.dataset.section === id));
  $$('.page-section').forEach(x => x.classList.toggle('active', x.id === id));
}

function fitCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width*dpr); canvas.height = Math.round(rect.height*dpr);
  const ctx = canvas.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0);
  return {ctx,w:rect.width,h:rect.height};
}

function drawActivity() {
  const canvas = $('#activityChart'); if (!canvas.offsetWidth) return;
  const {ctx,w,h} = fitCanvas(canvas), data=DATA[currentPeriod].values;
  const pad={t:15,r:12,b:10,l:34}, max=Math.max(...data)*1.18;
  ctx.clearRect(0,0,w,h); ctx.font='9px Segoe UI'; ctx.textAlign='right'; ctx.textBaseline='middle';
  for(let i=0;i<5;i++) { const y=pad.t+(h-pad.t-pad.b)*i/4; ctx.strokeStyle='#242424';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();ctx.fillStyle='#777';ctx.fillText(`${Math.round(max*(4-i)/4)}k`,pad.l-8,y); }
  const pts=data.map((v,i)=>({x:pad.l+(w-pad.l-pad.r)*i/(data.length-1),y:pad.t+(h-pad.t-pad.b)*(1-v/max),v}));
  const previous=data.map((v,i)=>v*(.72+Math.sin(i*1.8)*.08));
  const prevPts=previous.map((v,i)=>({x:pad.l+(w-pad.l-pad.r)*i/(data.length-1),y:pad.t+(h-pad.t-pad.b)*(1-v/max)}));
  ctx.beginPath();prevPts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle='#5c5c62';ctx.lineWidth=1.5;ctx.setLineDash([5,6]);ctx.stroke();ctx.setLineDash([]);
  const grad=ctx.createLinearGradient(0,pad.t,0,h);grad.addColorStop(0,'rgba(247,67,184,.24)');grad.addColorStop(1,'rgba(247,67,184,0)');
  ctx.beginPath();ctx.moveTo(pts[0].x,h-pad.b);pts.forEach(p=>ctx.lineTo(p.x,p.y));ctx.lineTo(pts.at(-1).x,h-pad.b);ctx.closePath();ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle='#f743b8';ctx.lineWidth=3;ctx.lineJoin='round';ctx.stroke();
  pts.forEach(p=>{ctx.beginPath();ctx.arc(p.x,p.y,3.5,0,Math.PI*2);ctx.fillStyle='#090909';ctx.fill();ctx.strokeStyle='#f743b8';ctx.lineWidth=2;ctx.stroke();});
  canvas._points=pts;
}

function setupChartTooltip(){
  const canvas=$('#activityChart'), tip=$('#chartTooltip');
  canvas.addEventListener('pointermove',e=>{ const r=canvas.getBoundingClientRect(), x=e.clientX-r.left; let p=canvas._points?.reduce((a,b)=>Math.abs(b.x-x)<Math.abs(a.x-x)?b:a); if(!p)return; tip.hidden=false;tip.style.left=`${p.x}px`;tip.style.top=`${p.y}px`;tip.innerHTML=`<b>${p.v} тыс.</b> сообщений`; });
  canvas.addEventListener('pointerleave',()=>tip.hidden=true);
}

function drawWave(){
  const canvas=$('#waveChart'); if(!canvas.offsetWidth)return; const {ctx,w,h}=fitCanvas(canvas);ctx.clearRect(0,0,w,h);
  const grad=ctx.createLinearGradient(0,0,w,0);grad.addColorStop(0,'#f743b8');grad.addColorStop(.5,'#ffffff');grad.addColorStop(1,'#f743b8');
  ctx.beginPath(); for(let x=0;x<=w;x+=3){const y=h/2+Math.sin(x*.07)*8+Math.sin(x*.19)*4+Math.sin(x*.015)*13;(x?ctx.lineTo(x,y):ctx.moveTo(x,y));}ctx.strokeStyle=grad;ctx.lineWidth=2;ctx.stroke();
  ctx.lineTo(w,h);ctx.lineTo(0,h);ctx.closePath();const fill=ctx.createLinearGradient(0,0,0,h);fill.addColorStop(0,'rgba(247,67,184,.18)');fill.addColorStop(1,'rgba(247,67,184,0)');ctx.fillStyle=fill;ctx.fill();
}

function setPeriod(period){
  currentPeriod=period;const d=DATA[period];Object.entries({users:d.users,messages:d.messages,session:d.session,safe:d.safe}).forEach(([k,v])=>$(`[data-metric="${k}"]`).textContent=v);
  $$('.period-switch button').forEach(b=>b.classList.toggle('active',b.dataset.period===period));
  $('#activityAxis').innerHTML=d.labels.map(x=>`<span>${x}</span>`).join('');$('#activityAxis').style.gridTemplateColumns=`repeat(${d.labels.length},1fr)`;drawActivity();
}

function renderHeatmap(){
  const el=$('#heatmap'),days=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'],hours=['00','02','04','06','08','10','12','14','16','18','20','22'];let html='<span></span>'+hours.map(h=>`<span class="hour">${h}</span>`).join('');
  days.forEach((d,di)=>{html+=`<span class="day">${d}</span>`;hours.forEach((_,hi)=>{const v=Math.max(7,Math.min(94,12+hi*4+(di>4?18:0)+Math.sin((hi+di)*1.7)*17));html+=`<i class="cell" style="--v:${v.toFixed(0)}" title="${d}, ${hours[hi]}:00 — активность ${v.toFixed(0)}%"></i>`;});});el.innerHTML=html;
}

function renderDialogs(filter=''){
  const rows=dialogs.filter(r=>r.join(' ').toLowerCase().includes(filter.toLowerCase()));
  $('#dialogTable').innerHTML=`<div class="data-row header"><span>ID диалога</span><span>Тема</span><span>Длительность</span><span>Сообщений</span><span>Статус</span></div>`+rows.map(r=>`<div class="data-row"><strong>${r[0]}</strong><span>${r[1]}</span><span>${r[2]}</span><span>${r[3]}</span><span class="status ${r[4]==='Завершён'?'ended':''}">${r[4]}</span></div>`).join('');
}

function renderCohorts(){
  const labels=['Неделя 42','Неделя 43','Неделя 44','Неделя 45','Неделя 46'];let html='<div class="label">Когорта</div>'+['День 0','День 1','День 3','День 7','День 14','День 21','День 30'].map(x=>`<div class="label">${x}</div>`).join('');
  labels.forEach((l,ri)=>{html+=`<div class="label">${l}</div>`;[100,68-ri*2,52-ri,38+ri,29+ri,24+ri,19+ri].forEach(v=>html+=`<div style="color:${v>55?'#fff':'#423b69'};background:color-mix(in srgb,#705cf6 ${v}%,#f2f0f7)">${v}%</div>`);});$('#cohortGrid').innerHTML=html;
}

function renderCases(filter='all'){
  const list=cases.filter(c=>filter==='all'||c.risk===filter);$('#moderationCases').innerHTML=list.map(c=>`<div class="case-row"><span class="risk ${c.risk}">${c.label}</span><p>${c.text}</p><small>${c.id}</small><button type="button">Проверить</button></div>`).join('');
  $$('#moderationCases button').forEach(b=>b.addEventListener('click',()=>showToast('Кейс открыт в безопасном режиме')));
}

function showToast(message){const t=$('#toast');t.textContent=message;t.classList.add('show');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>t.classList.remove('show'),2600);}

function exportReport(){
  const rows=[['Показатель','Значение'],['Активные пользователи',DATA[currentPeriod].users],['Сообщения',DATA[currentPeriod].messages],['Средняя сессия',DATA[currentPeriod].session],['Без жалоб',DATA[currentPeriod].safe]];
  const blob=new Blob(['\ufeff'+rows.map(r=>r.join(';')).join('\n')],{type:'text/csv;charset=utf-8'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`anon-pulse-${currentPeriod}.csv`;a.click();URL.revokeObjectURL(a.href);showToast('Отчёт скачан в формате CSV');
}

function init(){
  $('#todayLabel').textContent = new Intl.DateTimeFormat('ru-RU', {weekday:'long', day:'numeric', month:'long'}).format(new Date()).replace(/^./, c => c.toUpperCase());
  renderMiniBars();setupNavigation();openInitialSection();setupChartTooltip();renderHeatmap();renderDialogs();renderCohorts();renderCases();setPeriod('week');drawWave();
  $$('.period-switch button').forEach(b=>b.addEventListener('click',()=>setPeriod(b.dataset.period)));
  $('#dialogSearch').addEventListener('input',e=>renderDialogs(e.target.value));
  $('#moderationFilter').addEventListener('change',e=>renderCases(e.target.value));
  $('#exportBtn').addEventListener('click',exportReport);
  $('#backToApp').addEventListener('click', () => location.href = '../');
  $('.profile').addEventListener('click',()=>showToast('Профиль администратора'));
  $('.icon-button').addEventListener('click',()=>showToast('Новых уведомлений: 3'));
  let resize;window.addEventListener('resize',()=>{clearTimeout(resize);resize=setTimeout(()=>{drawActivity();drawWave()},120)});
  loadLiveData();
}
document.addEventListener('DOMContentLoaded',init);
