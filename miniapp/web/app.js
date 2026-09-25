if (typeof window === 'undefined') {
  // Emergency Bothost fallback: some deployments incorrectly use this browser bundle
  // as the Node entrypoint. In that case, hand control to the real Python bot.
  const { spawn } = require('node:child_process');
  const path = require('node:path');

  const mainPath = path.resolve(__dirname, '../../main.py');
  const child = spawn(process.env.PYTHON_BIN || 'python', [mainPath], {
    cwd: path.dirname(mainPath),
    env: process.env,
    stdio: 'inherit',
  });

  const forward = signal => {
    if (!child.killed) child.kill(signal);
  };
  process.on('SIGTERM', () => forward('SIGTERM'));
  process.on('SIGINT', () => forward('SIGINT'));

  child.on('error', error => {
    console.error('Failed to start Python bot:', error);
    process.exit(1);
  });
  child.on('exit', code => {
    process.exit(code ?? 1);
  });
} else {
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const tg = window.Telegram?.WebApp;
  const tgAtLeast = version => Boolean(tg && (!tg.isVersionAtLeast || tg.isVersionAtLeast(version)));
  const apiBase = (window.ANON_MGN_API_BASE || $('meta[name="api-base"]')?.content || '').replace(/\/$/, '');
  // Game icon metaphors follow the 24x24 / 2px Tabler Icons system.
  const paths = {
    'settings':'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.12 2.12-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.04 1.56V20h-3v-.08a1.7 1.7 0 0 0-1.05-1.56 1.7 1.7 0 0 0-1.88.34l-.05.06-2.13-2.12.06-.06A1.7 1.7 0 0 0 7 14.7a1.7 1.7 0 0 0-1.56-1.04H5v-3h.44A1.7 1.7 0 0 0 7 9.61a1.7 1.7 0 0 0-.35-1.88l-.06-.06 2.13-2.12.05.06a1.7 1.7 0 0 0 1.88.34A1.7 1.7 0 0 0 11.7 4.4V4h3v.4a1.7 1.7 0 0 0 1.04 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.12 2.12-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.04H21v3h-.04A1.7 1.7 0 0 0 19.4 15Z"/>',
    'chevron-right':'<path d="m9 18 6-6-6-6"/>','chevron-left':'<path d="m15 18-6-6 6-6"/>','arrow-right':'<path d="M5 12h14M13 6l6 6-6 6"/>','x':'<path d="m6 6 12 12M18 6 6 18"/>',
    'paperclip':'<path d="m21.4 11.6-8.9 8.9a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 1 1-2.8-2.8l8.5-8.5"/>',
    'smile':'<circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/>',
    'mic':'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5M8 22h8"/>',
    'send':'<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    'messages-circle':'<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/><path d="M8 12h.01M12 12h.01M16 12h.01"/>','message-circle':'<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/>','messages-square':'<path d="M14 17H5l-3 3V7a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4Z"/><path d="M18 9h1a3 3 0 0 1 3 3v9l-3-2h-5"/>',
    'search':'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>','house':'<path d="m3 11 9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1Z"/>','gamepad-2':'<path d="M12 5h3.5a5 5 0 0 1 0 10H10l-4.015 4.227a2.3 2.3 0 0 1-3.923-2.035l1.634-8.173A5 5 0 0 1 8.6 5H12"/><path d="m14 15 4.07 4.284a2.3 2.3 0 0 0 3.925-2.023l-1.6-8.232M8 9v2M7 10h2M14 10h2"/>','bell':'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>','user-round':'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    'target':'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>','shield-check':'<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3Z"/><path d="m9 12 2 2 4-4"/>','swords':'<path d="M21 3v5l-11 9-4 4-3-3 4-4 9-11h5M5 13l6 6M14.32 17.32 18 21l3-3-3.365-3.365M10 5.5 8 3H3v5l3 2.5"/>','hash':'<path d="M5 9h14M4 15h14M10 3 8 21M16 3l-2 18"/>',
    'pencil':'<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z"/>','thumbs-up':'<path d="M7 10v12H3V10h4ZM7 20h10.5a2 2 0 0 0 2-1.6l1.4-7A2 2 0 0 0 19 9h-5l1-4a2 2 0 0 0-2-2l-6 7"/>','chart':'<path d="M3 3v18h18M7 16v2M12 12v6M17 7v11"/>','trophy':'<path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0ZM7 6H4v2a3 3 0 0 0 3 3M17 6h3v2a3 3 0 0 1-3 3"/>','link':'<path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1"/>','sliders':'<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>','mail':'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>','circle-help':'<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 1 1 5.8 1c0 2-3 2-3 4M12 18h.01"/>','wifi-off':'<path d="m1 1 22 22M8.5 8.5A9 9 0 0 1 21 9M3 9a14 14 0 0 1 2.5-1.7M5 13a10 10 0 0 1 7-2.6M19 13a10 10 0 0 0-2.1-1.4M8.5 16.5a5 5 0 0 1 7 0M12 20h.01"/>','copy':'<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>','gift':'<rect x="3" y="8" width="18" height="13" rx="2"/><path d="M12 8v13M3 12h18M7.5 8C5 8 4 6.8 4 5.5S5 3 6.5 3C9 3 12 8 12 8M16.5 8C19 8 20 6.8 20 5.5S19 3 17.5 3C15 3 12 8 12 8"/>'
  };
  const state = {page:'home', modal:null, status:'free', position:null, user:{nick:'Аноним',rank:'Новичок',stars:0,age:0,district:'',gender:'',looking_for:'',photo_url:''},stats:{online:0,chatting:0,searching:0,dialogs:0,messages:0,ratings:0,games:0,battle_games:0,number_games:0,streak:0,best_streak:0,quest_current:0,quest_target:20},referral:{invited:0,earned:0},referral_url:'',bot_url:'',events:[],subscription:null};
  let statusRequestSeq = 0;
  let statusAppliedSeq = 0;
  let statusTimer = null;
  let searchBusy = false;
  const chat = {latest:0,startedAt:0,sent:0,received:0,timer:null,seen:new Set(),stickersLoaded:false,recording:false,recorder:null,stream:null,chunks:[],recordTimer:null,mediaCache:new Map()};
  const svg = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[n] || paths['circle-help']}</svg>`;
  function icons(root=document){$$('[data-icon]',root).forEach(el=>{el.innerHTML=svg(el.dataset.icon)})}
  function esc(v=''){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  function haptic(type='light'){try{if(tgAtLeast('6.1'))tg.HapticFeedback?.impactOccurred(type)}catch(_){}}
  function notify(type='success'){try{if(tgAtLeast('6.1'))tg.HapticFeedback?.notificationOccurred(type)}catch(_){}}
  function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),2400)}
  async function request(path, options={}){
    const headers={'Content-Type':'application/json',...(options.headers||{})}; if(tg?.initData)headers['X-Telegram-Init-Data']=tg.initData;
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),5000);
    let res;
    try{res=await fetch(apiBase+path,{cache:'no-store',...options,headers,signal:controller.signal})}
    catch(e){if(e?.name==='AbortError')throw new Error('Сервер не ответил за 5 секунд');throw new Error('Нет соединения с сервером')}
    finally{clearTimeout(timeout)}
    let data={}; try{data=await res.json()}catch(_){} if(!res.ok)throw new Error(data.message||`Ошибка ${res.status}`); return data;
  }
  async function safe(path,options,fallback=null){try{return await request(path,options)}catch(e){if(tg?.initData)toast(e.message);return fallback}}
  async function upload(path, formData){
    const headers={}; if(tg?.initData)headers['X-Telegram-Init-Data']=tg.initData;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    let res;
    try{res=await fetch(apiBase+path,{method:'POST',body:formData,headers,cache:'no-store',signal:controller.signal})}
    catch(e){if(e?.name==='AbortError')throw new Error('Загрузка заняла слишком долго');throw new Error('Нет соединения с сервером')}
    finally{clearTimeout(timeout)}
    let data={};try{data=await res.json()}catch(_){}
    if(!res.ok)throw new Error(data.message||`Ошибка ${res.status}`);
    return data;
  }
  async function mediaBlobUrl(url){
    if(!url)return '';
    if(chat.mediaCache.has(url))return chat.mediaCache.get(url);
    const headers={};if(tg?.initData)headers['X-Telegram-Init-Data']=tg.initData;
    const res=await fetch(apiBase+url,{headers,cache:'no-store'});
    if(!res.ok)throw new Error('Медиа недоступно');
    const blob=await res.blob();
    const objectUrl=URL.createObjectURL(blob);
    chat.mediaCache.set(url,objectUrl);
    return objectUrl;
  }
  function normalizeStatus(value){return value==='paired'?'paired':value==='queued'?'queued':'free'}
  function applyStatusSnapshot(data, seq=0){
    if(!data)return false;
    if(seq && seq<statusAppliedSeq)return false;
    if(seq)statusAppliedSeq=seq;
    const previous=state.status;
    state.status=normalizeStatus(data.status);
    state.position=state.status==='queued'?(data.position||null):null;
    if(data.stats)state.stats={...state.stats,...data.stats};
    render();
    if(state.status==='paired' && previous!=='paired' && state.page==='search')go('chat');
    if(state.status!=='paired' && state.page==='chat')go(state.status==='queued'?'search':'home');
    return true;
  }
  async function syncStatus(silent=true){
    if(!tg?.initData)return false;
    const seq=++statusRequestSeq;
    try{
      const data=await request(`/api/miniapp/status?_=${Date.now()}`);
      return applyStatusSnapshot(data,seq);
    }catch(e){
      if(!silent)toast(e.message);
      return false;
    }
  }
  function startStatusSync(){
    if(statusTimer||!tg?.initData)return;
    statusTimer=setInterval(()=>{if(!document.hidden)syncStatus(true)},2000);
  }
  function demo(){Object.assign(state.user,{nick:'Аноним-4821',rank:'Завсегдатай',stars:1250,age:17,district:'Правый берег',gender:'m',looking_for:'f'});Object.assign(state.stats,{online:34,chatting:22,searching:12,dialogs:682,messages:8884,ratings:128,games:43,battle_games:31,number_games:12,streak:7,best_streak:23,quest_current:14});state.referral={invited:8,earned:400};state.referral_url='https://t.me/AnonChatMgn_Bot?start=ref_demo';state.bot_url='https://t.me/AnonChatMgn_Bot';state.subscription={claimed:false,amount:100,url:'https://t.me/anonmgn'};state.events=[{id:'demo1',type:'personal',icon:'message-circle',title:'Диалог активен',text:'Собеседник найден. Возвращайся в чат.',time:'сейчас',unread:true},{id:'demo2',type:'games',icon:'gamepad-2',title:'Новая игра',text:'Можно пригласить собеседника в Битву мнений или Числа.',time:'сегодня',unread:false}]}
  function setAll(key,value){$$(`[data-${key}]`).forEach(el=>el.textContent=value)}
  function render(){setAll('nick',state.user.nick);setAll('rank',state.user.rank);setAll('stars',state.user.stars);setAll('online',state.stats.online);setAll('chatting',state.stats.chatting);setAll('searching',state.stats.searching);setAll('dialogs',state.stats.dialogs);setAll('messages',state.stats.messages);setAll('ratings',state.stats.ratings);setAll('games',state.stats.games);setAll('battle-games',state.stats.battle_games);setAll('number-games',state.stats.number_games);setAll('streak',state.stats.streak);setAll('invited',state.referral.invited);setAll('ref-earned',state.referral.earned);setAll('quest-progress-text',`${state.stats.quest_current}/${state.stats.quest_target}`);$$('[data-quest-progress]').forEach(el=>el.style.width=`${Math.min(100,state.stats.quest_current/Math.max(1,state.stats.quest_target)*100)}%`);const initial=(state.user.nick||'А').replace(/^./u,m=>m.toUpperCase()).slice(0,1);$$('[data-avatar-fallback]').forEach(el=>el.textContent=initial);$$('[data-avatar]').forEach(el=>{if(state.user.photo_url){el.src=state.user.photo_url;el.hidden=false}else{el.removeAttribute('src');el.hidden=true}});$$('[data-flame]').forEach((el,i)=>el.classList.toggle('on',i<Math.min(7,state.stats.streak)));$$('[data-setting]').forEach(group=>$$('button',group).forEach(b=>b.classList.toggle('active',String(b.dataset.value)===String(state.user[group.dataset.setting]||''))));renderSearch();renderEvents();}
  function renderSearch(){
    const card=$('.search-card'),title=$('#searchTitle'),text=$('#searchText'),button=$('#searchToggle');
    const heroTitle=$('.hero h1'),heroText=$('.hero p'),heroButton=$('.hero .primary');
    card.classList.toggle('searching',state.status==='queued');
    button.disabled=searchBusy;
    if(state.status==='paired'){
      title.textContent='Чат активен';
      text.textContent='Собеседник найден. Можно общаться прямо здесь.';
      button.innerHTML=`Открыть чат ${svg('arrow-right')}`;
      button.dataset.action='chat';
      if(heroTitle)heroTitle.textContent='Чат активен';
      if(heroText)heroText.textContent='Собеседник найден. Продолжай общение в Mini App.';
      if(heroButton){heroButton.innerHTML=`Открыть чат ${svg('arrow-right')}`;heroButton.dataset.nav='chat'}
      const nav=$('#searchNav');if(nav){nav.dataset.nav='chat';nav.querySelector('small').textContent='Чат';nav.querySelector('[data-icon]')?.setAttribute('data-icon','message-circle');icons(nav)}
    }else if(state.status==='queued'){
      const nav=$('#searchNav');if(nav){nav.dataset.nav='search';nav.querySelector('small').textContent='Поиск';nav.querySelector('[data-icon]')?.setAttribute('data-icon','search');icons(nav)}
      if(heroButton)heroButton.dataset.nav='search';
      title.textContent='Идёт поиск';
      text.textContent=state.position?`Твоя позиция в очереди: ${state.position}`:'Ищем собеседника. Можно закрыть Mini App.';
      button.textContent='Остановить поиск';
      button.dataset.action='stop';
      if(heroTitle)heroTitle.textContent='Идёт поиск';
      if(heroText)heroText.textContent='Поиск продолжается в фоне.';
      if(heroButton)heroButton.textContent='Остановить поиск';
    }else{
      const nav=$('#searchNav');if(nav){nav.dataset.nav='search';nav.querySelector('small').textContent='Поиск';nav.querySelector('[data-icon]')?.setAttribute('data-icon','search');icons(nav)}
      if(heroButton)heroButton.dataset.nav='search';
      title.textContent='Найти собеседника';
      text.textContent='Настрой предпочтения и начни поиск.';
      button.innerHTML=`Найти собеседника ${svg('arrow-right')}`;
      button.dataset.action='start';
      if(heroTitle)heroTitle.textContent='Найти собеседника';
      if(heroText)heroText.textContent='Подберём человека для разговора.';
      if(heroButton)heroButton.innerHTML=`Найти собеседника ${svg('arrow-right')}`;
    }
  }
  function renderEvents(filter='all'){const list=$('#eventList');const items=state.events.filter(x=>filter==='all'||x.type===filter);list.innerHTML=items.length?items.map(x=>`<article class="event surface"><span>${svg(x.icon||'bell')}</span><div><strong>${esc(x.title)}</strong><p>${esc(x.text)}</p><small>${esc(x.time||'')}</small></div></article>`).join(''):'<div class="empty">Здесь пока тихо.</div>';const unread=state.events.some(x=>x.unread);$$('[data-event-dot]').forEach(el=>el.hidden=!unread)}
  async function load(){if(!tg?.initData)demo();else{const seq=++statusRequestSeq;const data=await safe(`/api/miniapp/me?_=${Date.now()}`,{},null);if(data){state.user={...state.user,...data.user};state.stats={...state.stats,...data.stats};state.referral=data.referral||state.referral;state.referral_url=data.referral_url||'';state.bot_url=data.bot_url||'';state.events=data.notifications||[];applyStatusSnapshot(data,seq);return}}render()}
  function go(page){
    if(page==='chat' && state.status!=='paired')page=state.status==='queued'?'search':'home';
    state.page=page;
    document.body.classList.toggle('chat-open',page==='chat');
    $('.page').forEach(p=>p.classList.toggle('active',p.dataset.page===page));
    $('#bottomNav button').forEach(b=>b.classList.toggle('active',b.dataset.nav===page));
    window.scrollTo({top:0,behavior:'auto'});
    haptic();
    if(page==='search')syncStatus(true);
    if(page==='chat'){syncChat(true);startChatSync()}else stopChatSync();
    try{if(tgAtLeast('6.1'))page==='home'?tg.BackButton.hide():tg.BackButton.show()}catch(_){}
  }
  function openModal(kind,title,eyebrow='АНОН МГН'){$('#modalTitle').textContent=title;$('#modalEyebrow').textContent=eyebrow;$('#modalBody').innerHTML='<div class="loading"><i class="spinner"></i>Загрузка…</div>';$('#modal').hidden=false;document.body.style.overflow='hidden';state.modal=kind;try{if(tgAtLeast('6.1'))tg.BackButton.show()}catch(_){};haptic();renderModal(kind)}
  function closeModal(){$('#modal').hidden=true;document.body.style.overflow='';state.modal=null;try{if(tgAtLeast('6.1'))state.page==='home'?tg.BackButton.hide():tg.BackButton.show()}catch(_){}}
  function panel(title,text){return `<section class="panel"><h3>${title}</h3><p>${text}</p></section>`}
  async function renderModal(kind){const body=$('#modalBody');
    if(kind==='edit-profile'){body.innerHTML=`${panel('Ник в приложении','Используй любое имя, которое тебе нравится.')}<div class="form-field"><label>Новый ник · 2–24 символа</label><input id="nick" maxlength="24" value="${esc(state.user.nick.replace(/^@/,''))}" placeholder="Аноним"></div><div class="modal-actions"><button class="action" data-close-modal>Отмена</button><button class="action accent" id="saveNick">Сохранить</button></div>`;$('#saveNick').onclick=saveNick;bindClose(body);return}
    if(kind==='quests'){const d=await safe('/api/miniapp/quests',{},null);const items=d?.items||[{title:'Отправь 20 сообщений',current:state.stats.quest_current,target:20},{title:'Проведи 3 диалога',current:0,target:3},{title:'Сыграй 1 игру',current:0,target:1}];body.innerHTML=items.map(q=>`<article class="quest"><div><strong>${esc(q.title)}</strong><b>${q.done?'Готово':`${q.current}/${q.target}`}</b></div><p>${q.done?'Цель выполнена':'Продолжай — прогресс сохранится автоматически.'}</p><i class="progress"><i style="width:${Math.min(100,q.current/Math.max(1,q.target)*100)}%"></i></i></article>`).join('');return}
    if(kind==='streak'){const d=await safe('/api/miniapp/streak',{},null);if(d){state.stats.streak=d.current;state.stats.best_streak=d.best;render()}body.innerHTML=`${panel('Текущая серия',`<b>${state.stats.streak} дней</b> подряд. Серия не ограничена семью днями.`)}<div class="flame-grid">${Array.from({length:7},(_,i)=>`<i class="${i<Math.min(7,state.stats.streak)?'on':''}"></i>`).join('')}</div>${panel('Личный рекорд',`${state.stats.best_streak} дней. Активным считается день, когда ты общался в боте.`)}`;return}
    if(kind==='activity'){const d=await safe('/api/miniapp/activity',{},null)||{today:{},week:{},month:{},all:{dialogs:state.stats.dialogs,messages:state.stats.messages,games:state.stats.games,good_ratings:state.stats.ratings}};body.innerHTML=['today','week','month','all'].map((k,i)=>`<section class="panel"><h3>${['Сегодня','7 дней','30 дней','Всё время'][i]}</h3><div class="kv-grid"><div class="kv"><small>Диалоги</small><strong>${d[k]?.dialogs||0}</strong></div><div class="kv"><small>Сообщения</small><strong>${d[k]?.messages||0}</strong></div><div class="kv"><small>Игры</small><strong>${d[k]?.games||0}</strong></div><div class="kv"><small>Хорошие оценки</small><strong>${d[k]?.good_ratings||0}</strong></div></div></section>`).join('');return}
    if(kind==='top'){const d=await safe('/api/miniapp/top',{},null);const items=d?.items||(!tg?.initData?[{place:1,nick:'Аноним-4821',rank:'Завсегдатай',stars:1380},{place:2,nick:'northwind',rank:'Свой человек',stars:1240},{place:3,nick:'Аноним-1520',rank:'Собеседник',stars:1110}]:[]);body.innerHTML=items.length?`<div class="top-list">${items.map(x=>`<div class="top-item"><i>${x.place}</i><span><strong>${esc(x.nick)}</strong><small>${esc(x.rank||'')}</small></span><b>${x.stars||0} ★</b></div>`).join('')}</div>`:'<div class="empty">В топе пока никого.</div>';return}
    if(kind==='referral'){body.innerHTML=`${panel('Твои приглашения',`Приглашено: <b>${state.referral.invited}</b> · Получено: <b>${state.referral.earned} ★</b>`)}<div class="copy-box"><input id="refLink" readonly value="${esc(state.referral_url)}"><button id="copyRef" aria-label="Скопировать">${svg('copy')}</button></div><p class="hint">Друг должен впервые запустить бота по этой ссылке.</p>`;$('#copyRef').onclick=copyReferral;return}
    if(kind==='settings'){await settings(body);return}
    if(kind==='feedback'){body.innerHTML=`${panel('Напиши команде','Сообщение уйдёт всем администраторам бота.')}<div class="form-field"><label>Сообщение · до 1000 символов</label><textarea id="feedback" maxlength="1000" placeholder="Что случилось или что можно улучшить?"></textarea></div><div class="modal-actions one"><button class="action accent" id="sendFeedback">Отправить</button></div>`;$('#sendFeedback').onclick=sendFeedback;return}
    if(kind==='help'){body.innerHTML=panel('Поиск','Банк и пол — предпочтения. Если точного совпадения нет, бот всё равно постарается быстро найти собеседника.')+panel('Диалог','/next — следующий собеседник, /stop — закончить, /game — открыть игры. Личные контакты и ссылки отправлять можно.')+panel('Приватность','Обычные пользователи не видят Telegram ID и username. Для нарушений используй кнопку жалобы в чате.');return}
    if(kind==='battle'){body.innerHTML=`${panel('Битва мнений','Оба отвечают отдельно. Идеальное совпадение 5/5 или 10/10 принесёт каждому 25 ★.')}<div class="modal-actions"><button class="action" data-battle="5">5 вопросов</button><button class="action accent" data-battle="10">10 вопросов</button></div>`;$$('[data-battle]',body).forEach(b=>b.onclick=()=>inviteBattle(+b.dataset.battle));return}
    if(kind==='numbers'){body.innerHTML=`${panel('Числа · 3 раунда','Точное совпадение даёт полную награду, близкое — половину. Для пары награда доступна один раз.')}<div class="modal-actions one"><button class="action" data-range="10">1–10 · до 25 ★</button><button class="action" data-range="100">1–100 · до 50 ★</button><button class="action accent" data-range="1000">1–1000 · до 100 ★</button></div>`;$$('[data-range]',body).forEach(b=>b.onclick=()=>inviteNumbers(+b.dataset.range));return}
  }
  async function settings(body){const sub=await safe('/api/miniapp/subscription',{},null)||(!tg?.initData?state.subscription:null);state.subscription=sub;body.innerHTML=`<div class="setting"><div><strong>Твой пол</strong><small>необязательно</small></div><div class="segments" id="gender"><button data-value="m">Парень</button><button data-value="f">Девушка</button><button data-value="">Не указывать</button></div></div><div class="setting"><div><strong>Кого ищешь</strong><small>предпочтение</small></div><div class="segments" id="looking"><button data-value="m">Парня</button><button data-value="f">Девушку</button><button data-value="">Неважно</button></div></div><div class="setting"><div><strong>Твой берег</strong><small>необязательно</small></div><select id="district"><option value="">Любой</option><option value="Правый берег">Правый берег</option><option value="Левый берег">Левый берег</option></select></div><div class="setting"><div><strong>Возраст</strong><small>необязательно · 13–20</small></div><input id="age" type="number" inputmode="numeric" min="13" max="20" placeholder="Не указан"></div>${sub&&!sub.claimed?`<section class="panel reward"><span>${svg('gift')}</span><span><strong>${sub.amount} ★ за подписку</strong><small>Одноразовая награда</small></span><button id="subscribe">Получить</button></section>`:''}<section class="panel reward"><span>${svg('gift')}</span><span><strong>Поддержать проект</strong><small>Оплата Telegram Stars откроется в боте</small></span><button id="support">Открыть</button></section><div class="modal-actions"><button class="action" id="resetSettings">Сбросить</button><button class="action accent" id="saveSettings">Сохранить</button></div><div class="modal-actions one"><button class="action danger" id="forget">Удалить профиль</button></div>`;$('#district').value=state.user.district||'';$('#age').value=state.user.age||'';$$('#gender button').forEach(b=>b.classList.toggle('active',b.dataset.value===(state.user.gender||'')));$$('#looking button').forEach(b=>b.classList.toggle('active',b.dataset.value===(state.user.looking_for||'')));$$('#gender button,#looking button').forEach(b=>b.onclick=()=>{$$('button',b.parentElement).forEach(x=>x.classList.remove('active'));b.classList.add('active')});$('#saveSettings').onclick=saveSettings;$('#resetSettings').onclick=resetSettings;$('#forget').onclick=confirmForget;$('#support').onclick=openSupport;if($('#subscribe'))$('#subscribe').onclick=claimSubscription;}
  function bindClose(root=document){$$('[data-close-modal]',root).forEach(b=>b.onclick=closeModal)}
  async function saveNick(){const nick=$('#nick').value.trim();if(nick.length<2)return toast('Минимум 2 символа');const r=await safe('/api/miniapp/profile/nick',{method:'POST',body:JSON.stringify({nick})},null);if(r||!tg?.initData){state.user.nick=r?.nick||nick;render();closeModal();toast('Ник сохранён');notify()}}
  async function saveSettings(){const payload={age:+($('#age').value||0),district:$('#district').value,gender:$('#gender .active')?.dataset.value||'',looking_for:$('#looking .active')?.dataset.value||'',same_district:0};const r=await safe('/api/miniapp/settings',{method:'POST',body:JSON.stringify(payload)},null);if(r||!tg?.initData){state.user={...state.user,...payload,...(r?.user||{})};render();closeModal();toast('Настройки сохранены');notify()}}
  async function resetSettings(){const r=await safe('/api/miniapp/settings/reset',{method:'POST',body:'{}'},null);if(r||!tg?.initData){Object.assign(state.user,{age:0,district:'',gender:'',looking_for:''});render();settings($('#modalBody'));toast('Настройки сброшены')}}
  function confirmForget(){const body=$('#modalBody');body.innerHTML=`${panel('Удалить профиль?','Ник, звёзды, статистика и настройки будут удалены без возможности восстановления.')}<div class="modal-actions"><button class="action" id="cancelForget">Отмена</button><button class="action danger" id="doForget">Удалить</button></div>`;$('#cancelForget').onclick=()=>settings(body);$('#doForget').onclick=forgetProfile}
  async function forgetProfile(){const r=await safe('/api/miniapp/profile/forget',{method:'POST',body:'{}'},null);if(r){notify();try{tg?.close()}catch(_){location.reload()}}}
  async function claimSubscription(){if(!state.subscription)return;try{tg?.openTelegramLink?.(state.subscription.url)}catch(_){};toast('Подпишись и нажми ещё раз для проверки');const b=$('#subscribe');if(b){b.textContent='Проверить';b.onclick=async()=>{const r=await safe('/api/miniapp/subscription/claim',{method:'POST',body:'{}'},null);if(r){state.user.stars=r.stars;render();settings($('#modalBody'));toast(`+${r.amount} ★`);notify()}}}}
  function openSupport(){if(!state.bot_url)return toast('Ссылка на бота пока недоступна');try{tg?.openTelegramLink?.(state.bot_url)}catch(_){location.href=state.bot_url}}
  async function copyReferral(){try{await navigator.clipboard.writeText(state.referral_url);toast('Ссылка скопирована')}catch(_){$('#refLink').select();document.execCommand('copy');toast('Ссылка скопирована')}haptic()}
  async function sendFeedback(){const text=$('#feedback').value.trim();if(!text)return toast('Сначала напиши сообщение');const r=await safe('/api/miniapp/feedback',{method:'POST',body:JSON.stringify({text})},null);if(r||!tg?.initData){closeModal();toast('Сообщение отправлено');notify()}}
  async function updateSetting(key,value){const prev=state.user[key];state.user[key]=value;render();const payload={age:state.user.age||0,district:state.user.district||'',gender:state.user.gender||'',looking_for:state.user.looking_for||'',same_district:0};const r=await safe('/api/miniapp/settings',{method:'POST',body:JSON.stringify(payload)},null);if(!r&&tg?.initData){state.user[key]=prev;render()}else if(r?.user){state.user={...state.user,...r.user};render()}}
  function clearChatView(){
    chat.latest=0;chat.startedAt=0;chat.sent=0;chat.received=0;chat.seen.clear();
    const list=$('#chatMessages');if(list)list.querySelectorAll('.chat-message,.chat-system').forEach(x=>x.remove());
    const empty=$('#chatEmpty');if(empty)empty.hidden=false;
    $('#chatSent')&&($('#chatSent').textContent='0');$('#chatReceived')&&($('#chatReceived').textContent='0');
  }
  function formatChatDuration(){
    const el=$('#chatDuration');if(!el)return;
    if(!chat.startedAt){el.textContent='чат активен';return}
    const seconds=Math.max(0,Math.floor(Date.now()/1000-chat.startedAt));
    if(seconds<60)el.textContent='меньше минуты';
    else el.textContent=`${Math.max(1,Math.floor(seconds/60))} мин`;
  }
  function scrollChatBottom(){
    const list=$('#chatMessages');if(list)requestAnimationFrame(()=>{list.scrollTop=list.scrollHeight});
  }
  async function attachMediaToEvent(node,event){
    if(!event.media_url)return;
    try{
      const url=await mediaBlobUrl(event.media_url);
      if(event.kind==='photo'){
        const img=document.createElement('img');img.className='chat-photo';img.alt='Фото';img.src=url;img.onload=scrollChatBottom;node.prepend(img);
      }else if(event.kind==='voice'){
        const audio=document.createElement('audio');audio.className='chat-voice';audio.controls=true;audio.preload='metadata';audio.src=url;node.prepend(audio);
      }else if(event.kind==='sticker'){
        const img=document.createElement('img');img.className='chat-sticker';img.alt=event.text||'Стикер';img.src=url;img.onload=scrollChatBottom;node.prepend(img);
      }
    }catch(_){}
  }
  function appendChatEvent(event){
    if(!event||chat.seen.has(event.id))return;
    chat.seen.add(event.id);
    const list=$('#chatMessages');if(!list)return;
    const empty=$('#chatEmpty');if(empty)empty.hidden=true;
    if(event.kind==='system'){
      const el=document.createElement('div');el.className='chat-system';el.textContent=event.text||'';list.appendChild(el);scrollChatBottom();return;
    }
    const row=document.createElement('div');row.className=`chat-message ${event.mine?'mine':'theirs'}`;
    const bubble=document.createElement('div');bubble.className='chat-bubble';
    if(event.text){
      const p=document.createElement('p');p.textContent=event.text;bubble.appendChild(p);
    }
    const time=document.createElement('small');
    const dt=new Date((event.created_at||Math.floor(Date.now()/1000))*1000);
    time.textContent=dt.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
    bubble.appendChild(time);row.appendChild(bubble);list.appendChild(row);
    attachMediaToEvent(bubble,event);scrollChatBottom();
  }
  async function syncChat(force=false){
    if(!tg?.initData||state.status!=='paired')return false;
    try{
      const data=await request(`/api/miniapp/chat/state?after=${force?chat.latest:chat.latest}&_=${Date.now()}`);
      if(data.status!=='paired'){
        applyStatusSnapshot(data);
        return false;
      }
      if(data.started_at && chat.startedAt && Number(data.started_at)!==Number(chat.startedAt))clearChatView();
      chat.startedAt=Number(data.started_at||chat.startedAt||0);
      chat.sent=Number(data.sent||0);chat.received=Number(data.received||0);
      $('#chatSent')&&($('#chatSent').textContent=String(chat.sent));
      $('#chatReceived')&&($('#chatReceived').textContent=String(chat.received));
      (data.events||[]).forEach(appendChatEvent);
      chat.latest=Math.max(chat.latest,Number(data.latest||0),...(data.events||[]).map(x=>Number(x.id||0)));
      formatChatDuration();
      return true;
    }catch(e){
      if(force)toast(e.message);
      return false;
    }
  }
  function startChatSync(){
    if(chat.timer||!tg?.initData)return;
    chat.timer=setInterval(()=>{if(!document.hidden&&state.status==='paired'){syncChat(false);formatChatDuration()}},1000);
  }
  function stopChatSync(){if(chat.timer){clearInterval(chat.timer);chat.timer=null}}
  async function sendChatText(){
    const input=$('#chatInput');if(!input)return;
    const text=input.value.trim();if(!text)return;
    const button=$('#chatSend');if(button)button.disabled=true;
    try{
      await request('/api/miniapp/chat/text',{method:'POST',body:JSON.stringify({text})});
      input.value='';input.style.height='auto';await syncChat(false);haptic();
    }catch(e){toast(e.message)}
    finally{if(button)button.disabled=false}
  }
  async function sendChatPhoto(file){
    if(!file)return;
    if(file.size>8*1024*1024)return toast('Фото максимум 8 МБ');
    const form=new FormData();form.append('file',file,file.name||'photo.jpg');
    try{await upload('/api/miniapp/chat/photo',form);await syncChat(false);notify()}
    catch(e){toast(e.message)}
    finally{const input=$('#photoInput');if(input)input.value=''}
  }
  async function sendVoiceBlob(blob){
    if(!blob||!blob.size)return;
    if(blob.size>12*1024*1024)return toast('Голосовое слишком большое');
    const ext=blob.type.includes('mp4')?'m4a':blob.type.includes('ogg')?'ogg':'webm';
    const form=new FormData();form.append('file',blob,`voice.${ext}`);
    try{await upload('/api/miniapp/chat/voice',form);await syncChat(false);notify()}
    catch(e){toast(e.message)}
  }
  async function toggleVoiceRecording(){
    const btn=$('#micButton');if(!btn)return;
    if(chat.recording){
      chat.recording=false;btn.classList.remove('recording');clearTimeout(chat.recordTimer);chat.recordTimer=null;
      try{chat.recorder?.stop()}catch(_){}
      return;
    }
    if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined')return toast('Запись голоса не поддерживается');
    try{
      chat.stream=await navigator.mediaDevices.getUserMedia({audio:true});
      const types=['audio/mp4','audio/ogg;codecs=opus','audio/webm;codecs=opus','audio/webm'];
      const mime=types.find(x=>MediaRecorder.isTypeSupported?.(x))||'';
      chat.chunks=[];
      chat.recorder=new MediaRecorder(chat.stream,mime?{mimeType:mime}:undefined);
      chat.recorder.ondataavailable=e=>{if(e.data?.size)chat.chunks.push(e.data)};
      chat.recorder.onstop=()=>{
        const blob=new Blob(chat.chunks,{type:chat.recorder?.mimeType||mime||'audio/webm'});
        chat.stream?.getTracks().forEach(t=>t.stop());chat.stream=null;chat.recorder=null;chat.chunks=[];
        sendVoiceBlob(blob);
      };
      chat.recorder.start();chat.recording=true;btn.classList.add('recording');toast('Запись голосового… нажми ещё раз для отправки');haptic('medium');
      chat.recordTimer=setTimeout(()=>{if(chat.recording)toggleVoiceRecording()},60000);
    }catch(_){toast('Не удалось получить доступ к микрофону')}
  }
  async function loadStickers(){
    const tray=$('#stickerTray'),grid=$('#stickerGrid');if(!tray||!grid)return;
    tray.hidden=!tray.hidden;if(tray.hidden||chat.stickersLoaded)return;
    grid.innerHTML='<div class="sticker-loading">Загрузка…</div>';
    const data=await safe('/api/miniapp/chat/stickers',{},null);
    grid.innerHTML='';
    if(!data?.items?.length){grid.innerHTML='<div class="sticker-loading">Стикеры пока недоступны</div>';return}
    chat.stickersLoaded=true;
    data.items.forEach(item=>{
      const b=document.createElement('button');b.type='button';b.className='sticker-item';b.title=item.emoji||'Стикер';
      const img=document.createElement('img');img.alt=item.emoji||'Стикер';b.appendChild(img);grid.appendChild(b);
      mediaBlobUrl(item.url).then(url=>img.src=url).catch(()=>{b.textContent=item.emoji||'🙂'});
      b.onclick=async()=>{
        tray.hidden=true;
        try{await request('/api/miniapp/chat/sticker',{method:'POST',body:JSON.stringify({id:item.id})});await syncChat(false);haptic()}
        catch(e){toast(e.message)}
      };
    });
  }
  function confirmLongChat(action){
    if(!chat.startedAt||Date.now()/1000-chat.startedAt<300)return Promise.resolve(true);
    const message=`Диалог идёт уже ${Math.max(5,Math.floor((Date.now()/1000-chat.startedAt)/60))} мин. Точно ${action}?`;
    if(tg?.showConfirm)return new Promise(resolve=>{try{tg.showConfirm(message,resolve)}catch(_){resolve(window.confirm(message))}});
    return Promise.resolve(window.confirm(message));
  }
  async function stopChat(){
    if(!(await confirmLongChat('завершить чат')))return;
    try{
      const data=await request('/api/miniapp/chat/stop',{method:'POST',body:'{}'});
      clearChatView();applyStatusSnapshot(data);go('home');toast('Диалог завершён');notify();
    }catch(e){toast(e.message)}
  }
  async function nextChat(){
    if(!(await confirmLongChat('найти следующего')))return;
    try{
      clearChatView();
      const data=await request('/api/miniapp/chat/next',{method:'POST',body:'{}'});
      applyStatusSnapshot(data);
      if(state.status==='paired')go('chat');else go('search');
      toast(state.status==='paired'?'Новый собеседник найден':'Ищем нового собеседника');
      notify();
    }catch(e){toast(e.message)}
  }

  async function toggleSearch(){
    if(searchBusy)return;
    searchBusy=true;renderSearch();
    try{
      await syncStatus(true);
      const action=$('#searchToggle').dataset.action;
      if(action==='chat'){go('chat');return}
      const path=action==='stop'?'/api/miniapp/search/stop':'/api/miniapp/search/start';
      const seq=++statusRequestSeq;
      const data=await request(path,{method:'POST',body:'{}'});
      applyStatusSnapshot(data,seq);
      await syncStatus(true);
      notify();
      toast(state.status==='paired'?'Чат активен':state.status==='queued'?'Поиск запущен':'Поиск остановлен');
    }catch(e){
      toast(e.message);
      await syncStatus(true);
    }finally{
      searchBusy=false;
      renderSearch();
    }
  }
  async function inviteBattle(total){const r=await safe('/api/miniapp/games/battle/invite',{method:'POST',body:JSON.stringify({total})},null);if(r||!tg?.initData){closeModal();toast(r?.message||'Приглашение отправлено');notify()}}
  async function inviteNumbers(range_max){const r=await safe('/api/miniapp/games/numbers/invite',{method:'POST',body:JSON.stringify({range_max})},null);if(r||!tg?.initData){closeModal();toast(r?.message||'Приглашение отправлено');notify()}}
  function bind(){document.addEventListener('click',e=>{const nav=e.target.closest('[data-nav]');if(nav)go(nav.dataset.nav);const open=e.target.closest('[data-open]');if(open){const labels={'settings':'Настройки','edit-profile':'Изменить ник','quests':'Цели дня','streak':'Серия активности','activity':'Моя активность','top':'Топ 10','referral':'Приглашения','feedback':'Обратная связь','help':'Помощь и правила'};openModal(open.dataset.open,labels[open.dataset.open]||'АНОН МГН')}const game=e.target.closest('[data-game]');if(game)openModal(game.dataset.game,game.dataset.game==='battle'?'Битва мнений':'Числа','ИГРА ВДВОЁМ')});$$('[data-close-modal]').forEach(b=>b.onclick=closeModal);$('#searchToggle').onclick=toggleSearch;$$('[data-setting] button').forEach(b=>b.onclick=()=>updateSetting(b.parentElement.dataset.setting,b.dataset.value));$$('#eventFilter button').forEach(b=>b.onclick=()=>{$$('#eventFilter button').forEach(x=>x.classList.remove('active'));b.classList.add('active');renderEvents(b.dataset.filter)});window.addEventListener('online',()=>{$('#offline').hidden=true;if(tg?.initData){load();syncStatus(true)}});window.addEventListener('offline',()=>{if(tg?.initData)$('#offline').hidden=false});window.addEventListener('focus',()=>syncStatus(true));window.addEventListener('pageshow',()=>syncStatus(true));document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncStatus(true)});try{if(tgAtLeast('6.1'))tg.BackButton.onClick(()=>state.modal?closeModal():state.page!=='home'?go('home'):tg.close())}catch(_){}}
  async function boot(){
    const bootEl=$('#boot'),appEl=$('#app');
    const watchdog=setTimeout(()=>{bootEl?.classList.add('hide');appEl?.classList.add('ready')},6500);
    try{
      icons();
      try{tg?.ready();tg?.expand();if(tgAtLeast('6.1')){tg.setHeaderColor?.('#050506');tg.setBackgroundColor?.('#050506')}if(tgAtLeast('7.7'))tg.disableVerticalSwipes?.()}catch(_){}
      bind();
      await load();
      await syncStatus(true);
      startStatusSync();
    }catch(e){
      console.error('Mini App boot failed',e);
      if(tg?.initData)toast(e?.message||'Ошибка запуска Mini App');
    }finally{
      clearTimeout(watchdog);
      appEl?.classList.add('ready');
      setTimeout(()=>bootEl?.classList.add('hide'),180);
    }
  }
  boot();
})();

}
