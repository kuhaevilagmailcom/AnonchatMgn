(() => {
  'use strict';

  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const tg = window.Telegram?.WebApp || null;
  const API_BASE = (window.ANON_MGN_API_BASE || document.querySelector('meta[name="api-base"]')?.content || '').replace(/\/$/, '');

  const ICONS = {
    'house':'<path d="M3 10.8 12 3l9 7.8v9.2a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1z"/>',
    'search':'<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
    'gamepad-2':'<path d="M6.7 8h10.6a4 4 0 0 1 3.8 5.1l-1.1 4a2.6 2.6 0 0 1-4.2 1.3l-2-1.6h-3.6l-2 1.6A2.6 2.6 0 0 1 4 17.1l-1.1-4A4 4 0 0 1 6.7 8Z"/><path d="M7 12v4M5 14h4M16.5 12.5h.01M18.5 15h.01"/>',
    'bell':'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/>',
    'user-round':'<circle cx="12" cy="8" r="4"/><path d="M4.5 21a7.5 7.5 0 0 1 15 0"/>',
    'settings':'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21h-4a1.8 1.8 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3h4a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9A1.7 1.7 0 0 0 21 10h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
    'message-circle':'<path d="M21 11.5a8.4 8.4 0 0 1-9 8.2 9.2 9.2 0 0 1-3.7-.8L3 21l1.6-4.1A8.1 8.1 0 0 1 3 12c0-4.7 4-8.5 9-8.5s9 3.4 9 8Z"/>',
    'messages-circle':'<path d="M21 11.5a8.4 8.4 0 0 1-9 8.2 9.2 9.2 0 0 1-3.7-.8L3 21l1.6-4.1A8.1 8.1 0 0 1 3 12c0-4.7 4-8.5 9-8.5s9 3.4 9 8Z"/><path d="M8 12h.01M12 12h.01M16 12h.01"/>',
    'messages-square':'<path d="M7 17H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v2"/><path d="M8 7h5M8 11h3"/><path d="M9 12a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-5l-4 2v-2a2 2 0 0 1-2-2z"/>',
    'users':'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    'target':'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M22 12h-3M12 22v-3M2 12h3"/>',
    'chart-no-axes-column':'<path d="M5 20v-6M10 20V8M15 20V4M20 20v-9"/>',
    'chevron-right':'<path d="m9 18 6-6-6-6"/>',
    'arrow-right':'<path d="M5 12h14M13 6l6 6-6 6"/>',
    'arrow-left':'<path d="M19 12H5M11 18l-6-6 6-6"/>',
    'shield-check':'<path d="M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"/><path d="m9 12 2 2 4-4"/>',
    'sparkles':'<path d="m12 3-1.2 3.2L8 7.4l2.8 1.2L12 12l1.2-3.4L16 7.4l-2.8-1.2zM5 14l-.8 2.1L2 17l2.2.9L5 20l.8-2.1L8 17l-2.2-.9zM19 14l-.7 1.7-1.8.8 1.8.8L19 19l.7-1.7 1.8-.8-1.8-.8z"/>',
    'trophy':'<path d="M8 4h8v4a4 4 0 0 1-8 0zM8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4M12 12v5M8 21h8M9 17h6"/>',
    'thumbs-up':'<path d="M7 10v12H3a1 1 0 0 1-1-1V11a1 1 0 0 1 1-1zM7 10l4-8a2 2 0 0 1 2 2v5h5a3 3 0 0 1 2.9 3.7l-2 7A3 3 0 0 1 16 22H7"/>',
    'flame':'<path d="M13 2s1 4-2 6c-2 1.4-4 3.2-4 6.5A5 5 0 0 0 12 20a5 5 0 0 0 5-5c0-2.5-1.2-4.1-2.7-5.8.1 2.1-.7 3.4-2.3 4.3 1-4.8 1-7.6 1-11.5Z"/>',
    'gift':'<rect x="3" y="8" width="18" height="13" rx="2"/><path d="M12 8v13M3 12h18M7.5 8C5 8 4 6.5 4.8 5.2 5.7 3.8 8 4.2 12 8M16.5 8C19 8 20 6.5 19.2 5.2 18.3 3.8 16 4.2 12 8"/>',
    'link':'<path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1"/>',
    'mail':'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    'pencil':'<path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4"/>',
    'x':'<path d="M18 6 6 18M6 6l12 12"/>',
    'copy':'<rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    'circle-check':'<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',
    'trash-2':'<path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v6M14 11v6"/>',
    'rotate-ccw':'<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    'external-link':'<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
  };

  const state = {
    page: 'home', subview: null, searching: false,
    user: { id:0, nick:'Аноним', photo_url:'', rank:'Новичок', stars:0, age:0, district:'', same_district:0 },
    stats: { online:0, chatting:0, searching:0, dialogs:0, messages:0, ratings:0, games:0, battle_games:0, number_games:0, streak:0, best_streak:0, quest_current:0, quest_target:20 },
    status:'free', referral_url:'https://t.me/AnonChatMgn_Bot', referral:{invited:0,earned:0},
    notifications:[], activity:null, quests:[], top:[],
    settings: { age:0, district:'', same_district:0 }
  };

  function renderIcons(root=document){
    $$('[data-icon]', root).forEach(el => {
      const name=el.dataset.icon, body=ICONS[name]; if(!body || el.dataset.ready) return;
      el.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`; el.dataset.ready='1';
    });
  }
  function haptic(type='light') { try { tg?.HapticFeedback?.impactOccurred(type); } catch(_){} }
  function notifyHaptic(type='success') { try { tg?.HapticFeedback?.notificationOccurred(type); } catch(_){} }
  function esc(v=''){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  function toast(msg){const el=$('#toast');el.textContent=msg;el.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove('show'),2200)}
  function apiHeaders(){const h={'Content-Type':'application/json'};if(tg?.initData)h['X-Telegram-Init-Data']=tg.initData;return h}
  async function api(path, options={}){
    const res=await fetch(`${API_BASE}${path}`,{...options,headers:{...apiHeaders(),...(options.headers||{})}});
    let data=null;try{data=await res.json()}catch(_){ }
    if(!res.ok)throw new Error(data?.message||data?.detail||`HTTP ${res.status}`);return data;
  }
  async function tryApi(path,options,fallback=null){try{return await api(path,options)}catch(e){console.warn('[miniapp]',e.message);return fallback}}

  function initTelegram(){
    if(!tg)return;
    try{tg.ready();if(window.matchMedia('(max-width: 480px)').matches)tg.expand();tg.setHeaderColor?.('#090b0e');tg.setBackgroundColor?.('#090b0e');tg.disableVerticalSwipes?.();}
    catch(_){}
    const u=tg.initDataUnsafe?.user;
    if(u){state.user.id=u.id||0;state.user.nick=u.username?`@${u.username}`:([u.first_name,u.last_name].filter(Boolean).join(' ')||'Аноним');state.user.photo_url=u.photo_url||'';}
  }

  function demoFallback(){
    state.stats={...state.stats,online:34,chatting:22,searching:12,dialogs:682,messages:8884,ratings:128,games:43,battle_games:31,number_games:12,streak:7,best_streak:23,quest_current:14,quest_target:20};
    state.user={...state.user,nick:state.user.nick==='Аноним'?'Аноним-4821':state.user.nick,rank:'Легенда',stars:1250};
    state.referral_url=`https://t.me/AnonChatMgn_Bot?start=ref_${state.user.id||7770001}`;
    state.notifications=[
      {id:'n1',type:'personal',icon:'message-circle',title:'Обратная связь',text:'Мы увидим твои предложения и найденные баги.',time:'сейчас',unread:true},
      {id:'n2',type:'games',icon:'gamepad-2',title:'Игры с собеседником',text:'Битва мнений и Числа доступны в активном диалоге.',time:'сегодня',unread:true},
      {id:'n3',type:'system',icon:'target',title:'Квесты дня',text:'Выполняй задания и получай звёзды.',time:'сегодня',unread:false}
    ];
  }

  async function loadAll(){
    const data=await tryApi('/api/miniapp/me',{},null);
    if(data){
      if(data.user)state.user={...state.user,...data.user};
      if(data.stats)state.stats={...state.stats,...data.stats};
      state.status=data.status||state.status;
      state.referral_url=data.referral_url||state.referral_url;
      state.referral={...state.referral,...(data.referral||{})};
      state.settings={age:Number(data.user?.age||0),district:data.user?.district||'',same_district:Number(data.user?.same_district||0)};
      if(Array.isArray(data.notifications))state.notifications=data.notifications;
    } else if(!tg?.initData) demoFallback();
    else toast('Не удалось загрузить данные. Открой Mini App заново.');
    const notes=await tryApi('/api/miniapp/notifications',{},null);if(Array.isArray(notes?.items))state.notifications=notes.items;
    renderAll();
  }

  function setText(attr,value){$$(`[data-${attr}]`).forEach(el=>el.textContent=value)}
  function renderAvatar(){
    const first=(state.user.nick||'А').replace('@','').trim().charAt(0).toUpperCase()||'А';setText('avatar-fallback',first);
    $$('[data-avatar]').forEach(img=>{if(state.user.photo_url){img.src=state.user.photo_url;img.classList.add('show');img.nextElementSibling?.classList.add('hide')}else{img.classList.remove('show');img.nextElementSibling?.classList.remove('hide')}})
  }
  function animateNumber(el,to){const from=Number(el.dataset.value||0),target=Number(to||0);el.dataset.value=String(target);if(Math.abs(target-from)>5000){el.textContent=target;return}const start=performance.now(),dur=420;const step=t=>{const p=Math.min(1,(t-start)/dur),ease=1-Math.pow(1-p,3);el.textContent=Math.round(from+(target-from)*ease);if(p<1)requestAnimationFrame(step)};requestAnimationFrame(step)}
  function syncStreakFlames(root=document){const days=Math.max(0,Number(state.stats.streak||0)),active=Math.min(7,days);$$('[data-streak-flame]',root).forEach((el,i)=>{el.classList.toggle('active',i<active);el.style.setProperty('--flame-delay',`${i*90}ms`)})}
  function renderAll(){
    renderIcons();setText('nick',state.user.nick);setText('rank',state.user.rank||'Легенда');setText('stars',Number(state.user.stars||0));renderAvatar();
    const m={online:'online',chatting:'chatting',searching:'searching',dialogs:'dialogs',messages:'messages',ratings:'ratings',games:'games','battle-games':'battle_games',streak:'streak'};
    Object.entries(m).forEach(([attr,key])=>$$(`[data-${attr}]`).forEach(el=>animateNumber(el,state.stats[key]||0)));
    const cur=Number(state.stats.quest_current||0),tar=Math.max(1,Number(state.stats.quest_target||20));setText('quest-progress-text',`${cur}/${tar}`);$$('[data-quest-progress]').forEach(el=>requestAnimationFrame(()=>el.style.width=`${Math.min(100,cur/tar*100)}%`));
    syncSegments();syncSearchUI();syncStreakFlames();renderNotifications($('#notifyTabs .active')?.dataset.notify||'all');
  }

  function syncSegments(){
    $$('[data-setting]').forEach(group=>{const key=group.dataset.setting;$$('button',group).forEach(b=>b.classList.toggle('active',String(b.dataset.value)===String(state.settings[key]||'')))});
  }
  function syncSearchUI(){
    const radar=$('#radar'),btn=$('#searchToggle'),title=$('#searchStatusTitle'),text=$('#searchStatusText');
    const status=state.status;
    if(status==='queued'||state.searching){state.searching=true;radar.classList.add('searching');title.textContent='Ищем собеседника';text.textContent='Ты в очереди. Можно закрыть Mini App — поиск продолжится.';btn.innerHTML='Остановить поиск <span data-icon="x"></span>';}
    else if(status==='paired'){state.searching=false;radar.classList.remove('searching');title.textContent='Собеседник найден';text.textContent='Диалог уже активен в Telegram.';btn.innerHTML='Открыть чат <span data-icon="external-link"></span>';}
    else{state.searching=false;radar.classList.remove('searching');title.textContent='Можно начинать';text.textContent='Настрой поиск и нажми кнопку.';btn.innerHTML='Начать поиск <span data-icon="arrow-right"></span>';}
    renderIcons(btn);
  }

  function go(page){
    if(!['home','search','games','notifications','profile'].includes(page))return;
    if(state.subview)closeSubview();state.page=page;haptic('light');
    $$('.page').forEach(p=>p.classList.toggle('is-active',p.dataset.page===page));$$('#bottomNav [data-nav]').forEach(b=>b.classList.toggle('active',b.dataset.nav===page));
    window.scrollTo({top:0,behavior:'smooth'});try{tg?.BackButton?.[page==='home'?'hide':'show']()}catch(_){}
  }

  function renderNotifications(filter='all'){
    const list=$('#notificationList');if(!list)return;const items=state.notifications.filter(n=>filter==='all'||n.type===filter);
    list.innerHTML=items.length?items.map(n=>`<article class="notification-item ${n.unread?'unread':''}" data-notification="${esc(n.id)}"><div class="notification-icon"><span data-icon="${esc(n.icon||'bell')}"></span></div><div class="notification-copy"><strong>${esc(n.title)}</strong><p>${esc(n.text||'')}</p><small>${esc(n.time||'')}</small></div><div class="notification-meta">${n.unread?'<i class="unread-dot"></i>':''}<span class="row-chevron" data-icon="chevron-right"></span></div></article>`).join(''):'<div class="empty">Здесь пока тихо.</div>';
    renderIcons(list);const unread=state.notifications.filter(n=>n.unread).length;setText('unread-count',unread);$('.nav-dot').hidden=unread===0;
  }

  async function updateSetting(key,value){
    const prev=state.settings[key];state.settings[key]=key==='same_district'?Number(value):value;syncSegments();haptic('light');
    const payload={...state.settings};const r=await tryApi('/api/miniapp/settings',{method:'POST',body:JSON.stringify(payload)},null);
    if(!r){state.settings[key]=prev;syncSegments();if(tg?.initData)toast('Не удалось сохранить настройку');return}if(r.user){state.user={...state.user,...r.user};state.settings={age:Number(state.user.age||0),district:state.user.district||'',same_district:Number(state.user.same_district||0)};renderAll()}
  }

  async function toggleSearch(){
    if(state.status==='paired'){try{tg?.close()}catch(_){};return}
    const btn=$('#searchToggle');btn.disabled=true;
    try{
      if(state.searching||state.status==='queued'){
        const r=await api('/api/miniapp/search/stop',{method:'POST',body:'{}'});state.status=r?.status||'free';state.searching=false;toast('Поиск остановлен');
      }else{
        const r=await api('/api/miniapp/search/start',{method:'POST',body:JSON.stringify(state.settings)});state.status=r?.status||'queued';state.searching=state.status==='queued';if(r?.stats)state.stats={...state.stats,...r.stats};
        if(state.status==='paired'){notifyHaptic('success');toast('Собеседник найден — открой чат в Telegram');confetti()}else toast(`Ищем собеседника${r?.position?` · очередь ${r.position}`:''}`);
      }
    }catch(e){
      if(!tg?.initData){state.status=state.searching?'free':'queued';state.searching=!state.searching;toast(state.searching?'Демо: поиск начат':'Демо: поиск остановлен')}else toast(e.message||'Не получилось выполнить действие');
    }finally{btn.disabled=false;syncSearchUI();renderAll()}
  }

  async function sendBattleInvite(total){
    closeSheet();
    if(state.status!=='paired'){toast('Сначала найди собеседника');haptic('medium');return}
    try{const r=await api('/api/miniapp/games/battle/invite',{method:'POST',body:JSON.stringify({total})});toast(r?.message||'Приглашение отправлено');notifyHaptic('success')}
    catch(e){toast(e.message||'Не получилось запустить игру')}
  }

  function startGame(){
    if(state.status!=='paired'){toast('Сначала найди собеседника');haptic('medium');return}
    showSheet(`<h2>Битва мнений</h2><p>Сколько случайных вопросов сыграть с текущим собеседником?</p><div class="sheet-actions"><button id="battle5">5 вопросов</button><button class="primary" id="battle10">10 вопросов</button></div>`);
    $('#battle5').onclick=()=>sendBattleInvite(5);$('#battle10').onclick=()=>sendBattleInvite(10);
  }

  function showSheet(html){$('#sheetContent').innerHTML=html;renderIcons($('#sheetContent'));$('#sheetBackdrop').hidden=false;haptic('light')}
  function closeSheet(){$('#sheetBackdrop').hidden=true}
  function editProfile(){
    showSheet(`<h2>Изменить ник</h2><p>Ник виден в профиле и топе. В анонимном диалоге собеседник его не видит.</p><div class="sheet-field"><label>Ник</label><input id="nickInput" maxlength="24" value="${esc((state.user.nick||'').replace(/^@/,''))}"></div><div class="sheet-actions"><button id="cancelNick">Отмена</button><button class="primary" id="saveNick">Сохранить</button></div>`);
    $('#cancelNick').onclick=closeSheet;$('#saveNick').onclick=async()=>{const nick=$('#nickInput').value.trim();if(!nick)return toast('Введите ник');const r=await tryApi('/api/miniapp/profile/nick',{method:'POST',body:JSON.stringify({nick})},null);if(r?.nick)state.user.nick=r.nick;else if(!tg?.initData)state.user.nick=nick;else return toast(r?.message||'Не получилось сохранить');renderAll();closeSheet();toast('Ник сохранён')};
  }
  function openSubview(kind){
    state.subview=kind;$('#subview').hidden=false;document.body.style.overflow='hidden';try{tg?.BackButton?.show()}catch(_){};renderSubview(kind);haptic('light')
  }
  function closeSubview(){state.subview=null;$('#subview').hidden=true;document.body.style.overflow='';try{tg?.BackButton?.[state.page==='home'?'hide':'show']()}catch(_){} }
  async function renderSubview(kind){
    const title=$('#subviewTitle'),body=$('#subviewBody');body.innerHTML='<div class="empty">Загрузка…</div>';
    const titles={settings:'Настройки',activity:'Моя активность',quests:'Цели дня',streak:'Серия активности',referral:'Пригласить друга',top:'Топ',online:'Онлайн сейчас',feedback:'Обратная связь',help:'Помощь',support:'Поддержать проект',rules:'Правила и приватность'};title.textContent=titles[kind]||'';
    if(kind==='settings')return renderSettings(body);
    if(kind==='feedback')return renderFeedback(body);
    if(kind==='rules')return renderRules(body);
    if(kind==='help')return renderHelp(body);
    if(kind==='support')return renderSupport(body);
    if(kind==='online')return renderOnline(body);
    if(kind==='referral')return renderReferral(body);
    if(kind==='activity')return renderActivity(body);
    if(kind==='quests')return renderQuests(body);
    if(kind==='streak')return renderStreak(body);
    if(kind==='top')return renderTop(body);
  }

  function renderSettings(body){
    const ageOptions=['<option value="0">Не указывать</option>',...Array.from({length:8},(_,i)=>`<option value="${i+13}">${i+13}</option>`)].join('');
    body.innerHTML=`<section class="section-card glass"><h3>Профиль и поиск</h3>
      <div class="setting-row"><div><strong>Возраст</strong><small>Необязательно, 13–20</small></div><select id="ageSetting">${ageOptions}</select></div>
      <div class="setting-row"><div><strong>Район</strong><small>Необязательно</small></div><select id="districtSetting"><option value="">Не выбран</option><option value="Правобережный">Правобережный</option><option value="Левобережный">Левобережный</option><option value="Орджоникидзевский">Орджоникидзевский</option></select></div>
      <div class="setting-row"><div><strong>Область поиска</strong><small>Фильтр работает только при выбранном районе</small></div><select id="sameDistrictSetting"><option value="0">Весь город</option><option value="1">Только мой район</option></select></div>
    </section>
    <section class="section-card glass"><h3>Данные</h3><button class="secondary-button tap" id="resetSettings"><span data-icon="rotate-ccw"></span> Сбросить настройки поиска</button><button class="danger-button tap" id="forgetProfile"><span data-icon="trash-2"></span> Удалить профиль</button></section>`;
    renderIcons(body);$('#ageSetting').value=String(state.settings.age||0);$('#districtSetting').value=state.settings.district||'';$('#sameDistrictSetting').value=String(state.settings.same_district||0);
    const save=async()=>{const p={age:Number($('#ageSetting').value||0),district:$('#districtSetting').value,same_district:Number($('#sameDistrictSetting').value||0)};const r=await tryApi('/api/miniapp/settings',{method:'POST',body:JSON.stringify(p)},null);if(!r&&tg?.initData)return toast('Не удалось сохранить');state.settings=p;if(r?.user)state.user={...state.user,...r.user};renderAll();toast('Настройки сохранены')};
    ['ageSetting','districtSetting','sameDistrictSetting'].forEach(id=>$('#'+id).onchange=save);
    $('#resetSettings').onclick=async()=>{await tryApi('/api/miniapp/settings/reset',{method:'POST',body:'{}'},null);state.settings={age:0,district:'',same_district:0};renderSettings(body);renderAll();toast('Настройки сброшены')};
    $('#forgetProfile').onclick=()=>{
      showSheet(`<h2>Удалить профиль?</h2><p>Опыт, статистика, ник и настройки будут удалены. Это действие нельзя отменить.</p><div class="sheet-actions"><button id="cancelForget">Отмена</button><button class="primary" id="confirmForget">Удалить</button></div>`);
      $('#cancelForget').onclick=closeSheet;
      $('#confirmForget').onclick=async()=>{try{await api('/api/miniapp/profile/forget',{method:'POST',body:'{}'});closeSheet();toast('Профиль удалён');setTimeout(()=>tg?.close?.(),600)}catch(e){toast(e.message)}};
    };
  }

  function renderReferral(body){body.innerHTML=`<section class="section-card glass"><h3>Пригласить друга</h3><p>Приглашено: <b>${Number(state.referral.invited||0)}</b> · Получено: <b>${Number(state.referral.earned||0)} ★</b></p><div class="sheet-field"><label>Твоя ссылка</label><input id="refLink" readonly value="${esc(state.referral_url)}"></div><button class="secondary-button tap" id="copyRef"><span data-icon="copy"></span> Скопировать ссылку</button></section>`;renderIcons(body);$('#copyRef').onclick=async()=>{try{await navigator.clipboard.writeText(state.referral_url);toast('Ссылка скопирована')}catch(_){toast(state.referral_url)}}}
  async function renderActivity(body){const d=await tryApi('/api/miniapp/activity',{},null);state.activity=d||state.activity||{today:{dialogs:0,messages:0,games:0},week:{dialogs:0,messages:0,games:0},month:{dialogs:0,messages:0,games:0},all:{dialogs:state.stats.dialogs,messages:state.stats.messages,games:state.stats.games,good_ratings:state.stats.ratings}};const a=state.activity;body.innerHTML=['today','week','month','all'].map((k,i)=>`<section class="section-card glass"><h3>${['Сегодня','7 дней','30 дней','Всё время'][i]}</h3><div class="kv-grid"><div class="kv"><small>Диалоги</small><strong>${Number(a[k]?.dialogs||0)}</strong></div><div class="kv"><small>Сообщения</small><strong>${Number(a[k]?.messages||0)}</strong></div><div class="kv"><small>Игры</small><strong>${Number(a[k]?.games||0)}</strong></div><div class="kv"><small>Хорошие оценки</small><strong>${Number(a[k]?.good_ratings||0)}</strong></div></div></section>`).join('')}
  async function renderQuests(body){const d=await tryApi('/api/miniapp/quests',{},null);state.quests=d?.items||state.quests;if(!state.quests.length)state.quests=[{title:'Отправь 20 сообщений',current:state.stats.quest_current,target:state.stats.quest_target,done:false},{title:'Проведи 3 диалога',current:0,target:3,done:false},{title:'Сыграй 1 игру',current:0,target:1,done:false}];body.innerHTML=`<div class="quest-list">${state.quests.map(q=>`<article class="quest-item ${q.done?'done':''}"><div class="quest-line"><strong>${esc(q.title)}</strong><b>${q.done?'Готово':'В процессе'}</b></div><p>${Number(q.current||0)}/${Number(q.target||1)}</p><div class="progress"><i style="width:${Math.min(100,Number(q.current||0)/Math.max(1,Number(q.target||1))*100)}%"></i></div></article>`).join('')}</div>`}
  async function renderStreak(body){const d=await tryApi('/api/miniapp/streak',{},null);if(d){state.stats.streak=d.current||0;state.stats.best_streak=d.best||0}const days=Number(state.stats.streak||0),best=Number(state.stats.best_streak||0);body.innerHTML=`<section class="section-card streak-card glass"><div class="streak-hero"><span class="streak-big-flame"><span data-icon="flame"></span></span><div class="streak-hero-copy"><small>Текущая серия</small><strong>${days} ${days===1?'день':(days>=2&&days<=4?'дня':'дней')}</strong><p>Серия продолжается без ограничения по дням.</p></div></div><div class="streak-week-title"><strong>Последние 7 активных дней</strong><span>${Math.min(days,7)}/7</span></div><div class="streak-week">${Array.from({length:7},(_,i)=>`<span class="streak-flame" data-streak-flame><span data-icon="flame"></span></span>`).join('')}</div><div class="streak-record"><span>Лучшая серия</span><strong>${best} ${best===1?'день':(best>=2&&best<=4?'дня':'дней')}</strong></div><p>Активный день засчитывается, если был хотя бы один диалог.</p></section>`;renderIcons(body);syncStreakFlames(body)}
  async function renderTop(body){const d=await tryApi('/api/miniapp/top',{},null);state.top=d?.items||state.top;if(!state.top.length&&!tg?.initData)state.top=[{place:1,nick:'Аноним-4821',stars:1380},{place:2,nick:'mgn_user',stars:1240},{place:3,nick:'Аноним-1520',stars:1110}];body.innerHTML=`<section class="section-card glass"><h3>Топ 10</h3><div class="top-list">${state.top.length?state.top.map(x=>`<div class="top-item"><span class="top-place">${Number(x.place)}</span><div><strong>${esc(x.nick)}</strong><small>${esc(x.rank||'')}</small></div><b>${Number(x.stars||x.xp||0)} ★</b></div>`).join(''):'<div class="empty">Топ пока пуст.</div>'}</div></section>`}
  function renderFeedback(body){body.innerHTML=`<section class="section-card glass"><h3>Напиши нам</h3><p>Предложения, вопросы и найденные баги попадут администраторам.</p><div class="sheet-field"><label>Сообщение</label><textarea id="feedbackText" maxlength="1000" placeholder="Что можно улучшить?"></textarea></div><button id="sendFeedback" class="secondary-button tap">Отправить</button></section>`;$('#sendFeedback').onclick=async()=>{const text=$('#feedbackText').value.trim();if(!text)return toast('Напиши сообщение');const r=await tryApi('/api/miniapp/feedback',{method:'POST',body:JSON.stringify({text})},null);if(r||!tg?.initData){$('#feedbackText').value='';toast('Отправлено, спасибо')}else toast('Не получилось отправить')}}
  function renderRules(body){body.innerHTML=`<section class="section-card glass"><h3>Анонимность</h3><p>Собеседнику не показываются твой Telegram username, имя и профиль. Ник из бота используется только в профиле и топе.</p></section><section class="section-card glass"><h3>Общение</h3><p>Не публикуй чужие персональные данные. Для нарушений используй жалобу в активном диалоге.</p></section><section class="section-card glass"><h3>Удаление данных</h3><p>Профиль можно удалить в настройках Mini App — это то же действие, что и /forget в боте.</p></section>`}
  async function renderOnline(body){const d=await tryApi('/api/miniapp/online',{},null)||{online:state.stats.online,chatting:state.stats.chatting,searching:state.stats.searching,free:Math.max(0,state.stats.online-state.stats.chatting-state.stats.searching),peak:state.stats.online};body.innerHTML=`<section class="section-card glass"><h3>Онлайн сейчас</h3><div class="kv-grid"><div class="kv"><small>Всего</small><strong>${Number(d.online||0)}</strong></div><div class="kv"><small>Общаются</small><strong>${Number(d.chatting||0)}</strong></div><div class="kv"><small>Ищут</small><strong>${Number(d.searching||0)}</strong></div><div class="kv"><small>Свободны</small><strong>${Number(d.free||0)}</strong></div><div class="kv"><small>Пик сегодня</small><strong>${Number(d.peak||0)}</strong></div></div></section>`}
  function renderHelp(body){body.innerHTML=`<section class="section-card glass"><h3>Поиск</h3><p>Выбери район при желании и нажми «Начать поиск». Фильтр «только мой район» работает, когда район указан у обоих.</p></section><section class="section-card glass"><h3>Во время диалога</h3><p>Команды бота: /next — следующий собеседник, /stop — завершить диалог, /game — игры.</p></section><section class="section-card glass"><h3>Жалоба</h3><p>Если собеседник нарушает правила, используй кнопку жалобы в самом диалоге.</p></section>`}
  function renderSupport(body){body.innerHTML=`<section class="section-card glass"><h3>Поддержать АНОН МГН</h3><p>Оплата поддержки работает через Telegram Stars в самом боте, чтобы платёж обрабатывался тем же безопасным платежным обработчиком.</p><button class="secondary-button tap" id="openSupportBot"><span data-icon="external-link"></span> Открыть бота</button></section>`;renderIcons(body);$('#openSupportBot').onclick=()=>{try{tg?.openTelegramLink?.('https://t.me/AnonChatMgn_Bot')}catch(_){location.href='https://t.me/AnonChatMgn_Bot'}}}

  async function confetti(){const box=$('#confetti');for(let i=0;i<20;i++){const p=document.createElement('i');p.style.left=`${35+Math.random()*30}%`;p.style.top=`${30+Math.random()*8}%`;p.style.background=["#ff5b92","#ff9fbd","#a46cff","#ffc95b"][i%4];p.style.animationDelay=`${Math.random()*.18}s`;box.appendChild(p);setTimeout(()=>p.remove(),1300)}}

  function bind(){
    document.addEventListener('click',e=>{
      const nav=e.target.closest('[data-nav]');if(nav){go(nav.dataset.nav);return}
      const op=e.target.closest('[data-open]');if(op){const k=op.dataset.open;if(k==='edit-profile')editProfile();else openSubview(k);return}
      const setting=e.target.closest('[data-setting] button');if(setting){updateSetting(setting.closest('[data-setting]').dataset.setting,setting.dataset.value);return}
      const game=e.target.closest('[data-game]');if(game){startGame(game.dataset.game);return}
      const nf=e.target.closest('[data-notify]');if(nf){$$('[data-notify]').forEach(b=>b.classList.toggle('active',b===nf));renderNotifications(nf.dataset.notify);return}
      const ni=e.target.closest('[data-notification]');if(ni){const item=state.notifications.find(n=>String(n.id)===ni.dataset.notification);if(item){item.unread=false;tryApi(`/api/miniapp/notifications/${encodeURIComponent(item.id)}/read`,{method:'POST',body:'{}'},null);renderNotifications($('#notifyTabs .active')?.dataset.notify||'all');toast(item.title)}return}
    });
    $('#searchToggle').onclick=toggleSearch;$('#sheetClose').onclick=closeSheet;$('#sheetBackdrop').onclick=e=>{if(e.target===$('#sheetBackdrop'))closeSheet()};$('#subviewBack').onclick=closeSubview;
    try{tg?.BackButton?.onClick(()=>{if(state.subview)closeSubview();else if(state.page!=='home')go('home');else tg.close()})}catch(_){}
  }

  async function boot(){renderIcons();initTelegram();bind();await loadAll();$('#app').classList.add('ready');setTimeout(()=>$('#boot').classList.add('hide'),180)}
  boot();
})();
