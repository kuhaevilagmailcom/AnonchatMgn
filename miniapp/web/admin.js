/* Mini App admin center. Separate from the public chat SPA. */
(() => {
  'use strict';
  const tg = window.Telegram?.WebApp;
  if (!tg?.initData) return;
  const apiBase = (window.ANON_MGN_API_BASE || document.querySelector('meta[name="api-base"]')?.content || '').replace(/\/$/, '');
  const $ = (s, root=document) => root.querySelector(s);
  const escape = (v='') => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
  const fmt = n => Number(n||0).toLocaleString('ru-RU');
  const date = t => t ? new Date(Number(t)*1000).toLocaleString('ru-RU',{timeZone:'Asia/Yekaterinburg',day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
  const sourceNames = {opening_balance:'Начальный баланс',message:'Сообщения',dialog:'Диалог',rating:'Оценка',referral:'Реферал',battle:'Битва мнений',numbers:'Числа',word_game:'Объясни слово',geoguessr:'GeoGuessr',achievement:'Достижение',daily_quest:'Задание',subscription:'Подписка',report:'Жалоба',admin_award:'Выдал администратор',admin_debit:'Списал администратор',admin_legacy:'Старое начисление',other:'Другое',one_time_reward:'Разовая награда',referral_correction:'Корректировка реферала',game_bonus:'Бонус в диалоге'};
  const labels = {dashboard:'Обзор',users:'Пользователи',user:'Карточка',ledger:'Начисления',rankings:'Топы',reports:'Жалобы',ban:'Бан-лист',mute:'Мут-лист',chats:'Диалоги',games:'Игры',analytics:'Аналитика',admins:'Администраторы',broadcast:'Рассылка',diagnostics:'Диагностика',audit:'Аудит',queue:'Очередь',polls:'Опрос дня'};
  const sections = [
    ['dashboard','Обзор',null],['users','Пользователи','users'],['ledger','Начисления','points'],
    ['queue','Очередь','queue'],
    ['rankings','Топы','stats'],['reports','Жалобы','reports'],['ban','Бан-лист','ban'],
    ['mute','Мут-лист','mute'],['chats','Диалоги','monitor'],['games','Игры','monitor'],
    ['analytics','Аналитика','stats'],['broadcast','Рассылка','broadcast'],
    ['admins','Администраторы','owner'],['polls','Опрос дня','owner'],['audit','Аудит','stats'],
    ['diagnostics','Диагностика','stats']
  ];
  const opt = (items, current) => items.map(([value,title])=>'<option value="'+escape(value)+'"'+(String(value)===String(current)?' selected':'')+'>'+escape(title)+'</option>').join('');
  const navButton=(text,act,value='',className='')=>'<button type="button" class="'+className+'" data-action="'+act+'" data-value="'+escape(value)+'">'+escape(text)+'</button>';
  const state = {permissions:[], owner:false, page:'dashboard', back:'users', selectedId:0, query:'',
    sort:'recent',userFilter:'all',usersPage:0,ledgerPage:0,ledgerKind:'all',ledgerPeriod:'today',
    ledgerSource:'',ledgerUser:'',reportsPage:0,reportsStatus:'new',restrictedPage:0,
    rankingPeriod:'week',chatsPage:0,gamesPage:0,queuePage:0,actionsPage:0,
    modal:null,loading:false,nonce:0, broadcastKey:''};
  const can = p => state.owner || state.permissions.includes(p);
  const root=document.createElement('div');
  root.id='adminCenter';
  root.className='admin-center';
  root.hidden=true;
  root.innerHTML='<div class="admin-shell"><header class="admin-header"><button class="admin-icon-button" data-action="back" aria-label="Назад">←</button><div><small>АНОН МГН / УПРАВЛЕНИЕ</small><h1 id="adminTitle">Панель</h1></div><button class="admin-icon-button" data-action="refresh" aria-label="Обновить">↻</button><button class="admin-icon-button" data-action="close" aria-label="Закрыть">×</button></header><nav id="adminNav" class="admin-nav" aria-label="Разделы админки"></nav><div class="admin-content" id="adminContent"></div><div class="admin-modal" id="adminModal" hidden></div></div>';
  document.body.append(root);
  function toast(text){let el=$('#adminToast');if(!el){el=document.createElement('div');el.id='adminToast';el.className='admin-toast';root.append(el)} el.textContent=text;el.classList.add('on');clearTimeout(el.timer);el.timer=setTimeout(()=>el.classList.remove('on'),3200)}
  const url=(path,params={})=>apiBase+'/api/miniapp/admin'+path+(Object.keys(params).length?'?'+new URLSearchParams(params):'');
  async function api(path,options={},params={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),14000);
    let response;
    try{
      response=await fetch(url(path,params),{cache:'no-store',...options,headers:{'X-Telegram-Init-Data':tg.initData,...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})},signal:controller.signal});
    }catch(error){throw new Error(error?.name==='AbortError'?'Сервер слишком долго отвечает':'Нет соединения с сервером')}
    finally{clearTimeout(timer)}
    const type=response.headers.get('Content-Type')||'';
    const data=type.includes('application/json')?await response.json().catch(()=>({})):null;
    if(!response.ok) throw new Error(data?.message||(response.status===403?'Нет прав доступа':'Ошибка сервера: '+response.status));
    return data;
  }
  const post=(path,body)=>api(path,{method:'POST',body:JSON.stringify(body)});
  const key=()=>{try{return crypto.randomUUID().replace(/-/g,'')}catch(_){return [...Array(4)].map(()=>Math.random().toString(36).slice(2)).join('').slice(0,45)}};
  function allowedSections(){return sections.filter(([_,__,p])=>!p||p==='owner'&&state.owner||p!=='owner'&&can(p))}
  function renderNavigation(){
    $('#adminNav',root).innerHTML=allowedSections().map(([id,label])=>'<button type="button" data-action="nav" data-value="'+id+'" class="'+(state.page===id||state.page==='user'&&id==='users'?'active':'')+'">'+label+'</button>').join('');
  }
  function wrapHeader(hint=''){return '<div class="admin-page-heading"><div><small>'+escape(hint||'ПАНЕЛЬ УПРАВЛЕНИЯ')+'</small><h2>'+escape(labels[state.page]||'Раздел')+'</h2></div></div>'}
  const placeholder='<div class="admin-empty">Нет данных по выбранным условиям</div>';
  const waiting='<div class="admin-loading"><span></span>Загружаем данные…</div>';
  const pill=(txt,kind='')=>'<span class="admin-pill '+kind+'">'+escape(txt)+'</span>';
  const tile=(label,value,note='')=>'<div class="admin-stat"><small>'+escape(label)+'</small><strong>'+escape(String(value))+'</strong>'+(note?'<span>'+escape(note)+'</span>':'')+'</div>';
  function pageNav(page,more,act){return '<div class="admin-pager">'+navButton('← Назад',act,Math.max(0,page-1),page===0?'disabled':'')+
    '<span>Страница '+(page+1)+'</span>'+ (more?navButton('Дальше →',act,page+1):'<button disabled>Дальше →</button>')+'</div>'}
  const row=(title,sub,act,value,after='')=>'<button class="admin-list-row" type="button" data-action="'+act+'" data-value="'+escape(value)+'"><span><b>'+title+'</b><small>'+sub+'</small></span><span class="admin-row-end">'+after+' <b>›</b></span></button>';
  const queryFields=(items)=>Object.entries(items).map(([n,v])=>'<label>'+escape(n)+v+'</label>').join('');
  function showModal(html){state.modal=true;const el=$('#adminModal',root);el.hidden=false;el.innerHTML='<div class="admin-modal-backdrop" data-action="modalClose"></div><div class="admin-modal-sheet"><button class="admin-modal-x" data-action="modalClose">×</button>'+html+'</div>'}
  function closeModal(){state.modal=null;const el=$('#adminModal',root);el.hidden=true;el.innerHTML=''}
  function open(){root.hidden=false;document.body.classList.add('admin-open');render('dashboard');}
  function close(){closeModal();root.hidden=true;document.body.classList.remove('admin-open')}
  function goto(page){
    closeModal();
    if(page!=='user')state.back=state.page==='user'?state.back:state.page;
    state.page=page;
    render();
  }
  async function render(page){
    if(page)state.page=page;
    const token=++state.nonce;
    renderNavigation();
    $('#adminTitle',root).textContent=labels[state.page]||'Админка';
    const target=$('#adminContent',root);
    target.innerHTML=waiting;
    try{
      let result='';
      if(state.page==='dashboard')result=await overview();
      else if(state.page==='users')result=await users();
      else if(state.page==='user')result=await user();
      else if(state.page==='ledger')result=await ledger();
      else if(state.page==='rankings')result=await rankings();
      else if(state.page==='reports')result=await reports();
      else if(state.page==='ban'||state.page==='mute')result=await restrictions();
      else if(state.page==='chats')result=await chats();
      else if(state.page==='queue')result=await queue();
      else if(state.page==='polls')result=await polls();
      else if(state.page==='games')result=await games();
      else if(state.page==='analytics')result=await analytics();
      else if(state.page==='admins')result=await admins();
      else if(state.page==='broadcast')result=broadcast();
      else if(state.page==='diagnostics')result=await diagnostics();
      else if(state.page==='audit')result=await audit();
      if(token===state.nonce)target.innerHTML=result;
    }catch(e){if(token===state.nonce)target.innerHTML='<div class="admin-error">'+escape(e.message)+'</div>'+navButton('Повторить','refresh')}
  }
  async function overview(){
    const d=await api('/bootstrap'),s=d.stats||{},g=d.games||{};
    return wrapHeader('Бот онлайн · '+Math.floor((d.uptime||0)/3600)+' ч работы')+
      '<section class="admin-stats">'+tile('Пользователи',fmt(s.users))+
      tile('Новых сегодня',fmt(s.new_today))+tile('Активны сегодня',fmt(s.active_today))+
      tile('За 7 дней',fmt(s.active_week))+tile('В поиске',fmt(d.queue))+
      tile('Диалогов сейчас',fmt(d.dialogs))+tile('Жалоб открыто',fmt(s.open_reports))+
      tile('Начислено сегодня',fmt(s.xp_today)+' ★')+
      tile('Банов / мутов',fmt(s.banned)+' / '+fmt(s.muted))+
      tile('Активных игр',fmt(g.total))+tile('База данных',(d.db_mb||0)+' МБ')+
      tile('Множитель','×'+d.multiplier)+'</section>'+
      '<div class="admin-subheading">Быстрые действия</div><div class="admin-actions">'+
      allowedSections().filter(([id])=>id!=='dashboard').slice(0,8).map(([id,label])=>navButton(label,'nav',id)).join('')+'</div>';
  }
  async function users(){
    const d=await api('/users',{}, {page:state.usersPage,q:state.query,sort:state.sort,filter:state.userFilter});
    const sorts=[['recent','Недавно были'],['new','Новые'],['xp','По очкам'],['messages','По сообщениям'],['dialogs','По диалогам']];
    const filters=[['all','Все'],['active','Недавно онлайн'],['queue','В поиске'],['dialog','В диалоге'],['ban','Заблокированы'],['mute','В муте'],['support','Поддержали'],['admins','Администраторы']];
    return wrapHeader(d.total+' пользователей')+
      '<form id="adminSearch" class="admin-search"><input name="q" placeholder="ID, @username, ник или имя" value="'+escape(state.query)+'" autocomplete="off"><button type="submit">Найти</button></form>'+
      '<div class="admin-filters"><select data-filter="sort" aria-label="Сортировка">'+opt(sorts,state.sort)+'</select><select data-filter="userFilter" aria-label="Фильтр">'+opt(filters,state.userFilter)+'</select></div>'+
      '<div class="admin-list">'+(d.items.length?d.items.map(u=>row(escape(u.nickname||u.first_name||'Пользователь')+' · '+fmt(u.xp)+' ★',
       escape(u.username?'@'+u.username:'Нет username')+' · ID '+u.user_id+' · '+fmt(u.messages)+' сообщений · '+fmt(u.dialogs)+' диалогов'+
       '<br>Был: '+date(u.last_seen),'user',u.user_id,u.banned?pill('Бан','danger'):'' )).join(''):placeholder)+'</div>'+
      pageNav(state.usersPage,state.usersPage+1<d.pages,'usersPage');
  }
  async function user(){
    if(!state.selectedId)return placeholder;
    const d=await api('/users/'+state.selectedId),u=d.user,ref=d.referrals||{};
    const parts=[
      ['Telegram ID','<code>'+escape(u.user_id)+'</code> '+navButton('Копировать','copy',u.user_id,'tiny')],
      ['Username',escape(u.username?'@'+u.username:'Отсутствует')],['Имя Telegram',escape(u.first_name||'—')],
      ['Зарегистрирован',date(u.created_at)],['Последний визит',date(u.last_seen)],
      ['Статус',escape(({free:'Свободен',queued:'В поиске',paired:'В диалоге'})[d.status]||d.status)],
      ['Возраст / район',escape(String(u.age||'—')+' / '+(u.district||'—'))],
      ['Пол / ищет',escape((u.gender||'—')+' / '+(u.looking_for||'—'))],
      ['Счёт',fmt(u.xp)+' ★'],['Поддержка',fmt(u.support_stars)+' Stars / '+fmt(u.support_rub)+' ₽'],
      ['Сообщений / диалогов',fmt(u.messages)+' / '+fmt(u.dialogs)],
      ['Оценки + / −',fmt(u.good_ratings)+' / '+fmt(u.bad_ratings)],
      ['Жалоб',fmt(u.reports_received)],['Рефералов',fmt(ref.invited)+' · +'+fmt(ref.earned)+' ★'],
      ['Бан',u.banned?'Да · '+escape(u.ban_reason||'—'):'Нет'],
      ['Мут до',Number(u.mute_until)>Date.now()/1000?date(u.mute_until):'Не активен'],
      ['Администратор',d.admin_permissions?.length?escape(d.admin_permissions.join(', ')):'Нет']
    ];
    const buttons=[navButton('История очков','userLedger',u.user_id)];
    if(can('points')){buttons.push(navButton('Выдать очки','openAdjust','+'+u.user_id,'accent'),navButton('Списать очки','openAdjust','-'+u.user_id))}
    if(can('ban'))buttons.push(navButton(u.banned?'Разблокировать':'Заблокировать','openModerate',(u.banned?'unban:':'ban:')+u.user_id,'danger'));
    if(can('mute'))buttons.push(navButton(Number(u.mute_until)>Date.now()/1000?'Снять мут':'Мут на время','openModerate',(Number(u.mute_until)>Date.now()/1000?'unmute:':'mute:')+u.user_id));
    if(d.partner_id&&can('monitor'))buttons.push(navButton('Собеседник: '+d.partner_id,'openUser',d.partner_id));
    return wrapHeader('Данные участника · только для администрации')+
      '<div class="admin-user-hero"><small>ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ</small><h2>'+escape(u.nickname||u.first_name||'Аноним')+'</h2><strong>'+fmt(u.xp)+' ★</strong></div>'+
      '<dl class="admin-details">'+parts.map(([k,v])=>'<div><dt>'+escape(k)+'</dt><dd>'+v+'</dd></div>').join('')+'</dl>'+
      '<div class="admin-actions">'+buttons.join('')+'</div>'+
      '<div class="admin-subheading">История уведомлений</div><div class="admin-list">'+
      ((d.notices||[]).length?(d.notices||[]).map(n=>
        '<article class="admin-report"><strong>'+escape(n.title)+'</strong><p>'+escape(n.body)+'</p>'+
        '<small>'+date(n.created_at)+' · Доставка: '+escape(n.status)+
        (n.last_error?' · '+escape(n.last_error):'')+'</small></article>').join(''):placeholder)+'</div>'+
      navButton('← Вернуться в список','nav','users','text');
  }
  function transactionControls(){
    const periods=[['today','Сегодня'],['week','Неделя'],['month','Месяц'],['all','Всё время']];
    const kinds=[['all','Все операции'],['plus','Начисления'],['minus','Списания']];
    const sources=[['','Все источники'],...Object.entries(sourceNames).map(([a,b])=>[a,b])];
    return '<div class="admin-filters wrap"><select data-filter="ledgerPeriod">'+opt(periods,state.ledgerPeriod)+'</select><select data-filter="ledgerKind">'+opt(kinds,state.ledgerKind)+'</select><select data-filter="ledgerSource">'+opt(sources,state.ledgerSource)+'</select></div>'+
      '<form id="adminLedgerSearch" class="admin-search"><input name="uid" inputmode="numeric" placeholder="Фильтр по ID пользователя" value="'+escape(state.ledgerUser)+'"><button type="submit">Показать</button></form>';
  }
  async function ledger(){
    const d=await api('/transactions',{},{
      page:state.ledgerPage,period:state.ledgerPeriod,kind:state.ledgerKind,
      source:state.ledgerSource,user_id:state.ledgerUser
    });
    const t=d.totals||{},history=d.items||[];
    return wrapHeader('Каждая операция · начисления и списания')+
      transactionControls()+'<div class="admin-stats mini">'+tile('Начислено +',fmt(t.credits)+' ★')+
      tile('Списано −',fmt(t.debits)+' ★')+tile('Операций',fmt(t.n))+
      tile('Начальные балансы',fmt(d.opening_balance)+' ★')+'</div>'+
      '<div class="admin-note">'+escape(d.note||'')+'</div>'+
      '<div class="admin-list">'+(history.length?history.map(tx=>row(
        '<span class="'+(tx.amount>=0?'admin-positive':'admin-negative')+'">'+(tx.amount>0?'+':'')+fmt(tx.amount)+' ★</span> · '+escape(sourceNames[tx.source]||tx.source),
        'ID '+tx.user_id+' · '+date(tx.created_at)+' · Баланс после: '+fmt(tx.balance_after)+' ★'+
        (tx.actor_id?' · админ '+tx.actor_id:'')+
        (tx.reason?'<br>'+escape(tx.reason):'')+
        (tx.reference_id?'<br>Ссылка: '+escape(tx.reference_type||'')+' '+escape(tx.reference_id):''),
        'openUser',tx.user_id,tx.source==='opening_balance'?pill('Архив','muted'):''
      )).join(''):placeholder)+'</div>'+
      pageNav(state.ledgerPage,d.has_more,'ledgerPage')+
      '<div class="admin-actions">'+navButton('Экспорт CSV','exportLedger')+'</div>';
  }
  async function rankings(){
    const d=await api('/rankings',{}, {period:state.rankingPeriod});
    return wrapHeader('Telegram и Mini App · одна база')+
      '<div class="admin-tabs">'+[['week','Неделя'],['month','Месяц'],['all','Всё время']].map(([id,label])=>navButton(label,'rankingPeriod',id,state.rankingPeriod===id?'selected':'')).join('')+'</div>'+
      '<div class="admin-list">'+(d.items?.length?d.items.map(i=>row('#'+i.place+' '+escape(i.nickname||'Аноним')+' · '+fmt(i.xp)+' ★',
      'ID '+i.user_id+' · '+fmt(i.messages)+' сообщений · '+fmt(i.dialogs)+' диалогов','openUser',i.user_id)).join(''):placeholder)+'</div>';
  }
  async function reports(){
    const d=await api('/reports',{}, {page:state.reportsPage,status:state.reportsStatus});
    return wrapHeader('Всего: '+d.total)+'<div class="admin-tabs">'+navButton('Новые','reportsStatus','new',state.reportsStatus==='new'?'selected':'')+
      navButton('Рассмотренные','reportsStatus','done',state.reportsStatus==='done'?'selected':'')+'</div>'+
      '<div class="admin-list">'+(d.items?.length?d.items.map(r=>'<article class="admin-report"><div class="admin-report-head"><strong>Жалоба #'+r.id+'</strong>'+pill(r.status==='new'?'Открыта':'Закрыта',r.status==='new'?'danger':'')+'</div>'+
      '<p>'+escape(r.reason||'')+'</p>'+(r.comment?'<p class="admin-muted">'+escape(r.comment)+'</p>':'')+
      '<small>'+date(r.created_at)+' · от '+r.reporter_id+' → на '+r.target_id+'</small>'+
      '<div class="admin-actions">'+navButton('Нарушитель','openUser',r.target_id)+navButton('Заявитель','openUser',r.reporter_id)+
      (r.status==='new'? (can('ban')?navButton('Бан','openModerate','report_ban:'+r.target_id+':'+r.id,'danger'):'')+
      (can('mute')?navButton('Мут','openModerate','report_mute:'+r.target_id+':'+r.id):'')+
      navButton('Закрыть','openModerate','report_close:0:'+r.id):'')+'</div></article>').join(''):placeholder)+'</div>'+
      pageNav(state.reportsPage,state.reportsPage+1<d.pages,'reportsPage');
  }
  async function restrictions(){
    const kind=state.page;
    const d=await api('/restrictions',{}, {kind,page:state.restrictedPage});
    return wrapHeader('Всего '+d.total)+
      '<div class="admin-list">'+(d.items?.length?d.items.map(u=>'<div class="admin-restriction"><div><b>'+escape(u.nickname||u.first_name||'Аноним')+'</b><small>ID '+u.user_id+' · '+escape(u.username||'нет username')+'</small><small>'+
        (kind==='ban'?escape(u.ban_reason||'Без причины'):'До '+date(u.mute_until))+'</small></div>'+
        navButton('Профиль','openUser',u.user_id)+navButton(kind==='ban'?'Разбан':'Снять мут','openModerate',(kind==='ban'?'unban:':'unmute:')+u.user_id)+'</div>').join(''):placeholder)+'</div>'+
      pageNav(state.restrictedPage,state.restrictedPage+1<d.pages,'restrictedPage');
  }
  async function chats(){
    const d=await api('/chats',{}, {page:state.chatsPage});
    return wrapHeader('Активных пар: '+d.total)+'<div class="admin-note">Только служебные сведения об активных соединениях. Содержимое приватного общения здесь не публикуется.</div>'+
      '<div class="admin-list">'+(d.items?.length?d.items.map(i=>'<div class="admin-pair"><span>💬 Пара</span>'+navButton('ID '+i.user_a,'openUser',i.user_a)+
      '<b>↔</b>'+navButton('ID '+i.user_b,'openUser',i.user_b)+'</div>').join(''):placeholder)+'</div>'+
      pageNav(state.chatsPage,state.chatsPage+1<d.pages,'chatsPage');
  }
  async function queue(){
    const d=await api('/queue',{}, {page:state.queuePage});
    return wrapHeader('Ожидают: '+d.total)+
      '<div class="admin-list">'+(d.items?.length?d.items.map((q,i)=>row(
      '№'+(state.queuePage*15+i+1)+' · ID '+q.user_id,
      'Берег: '+escape(q.district||'любой')+' · пол '+escape(q.gender||'любой')+
      ' · ищет '+escape(q.looking_for||'любого')+' · ожидает '+Math.floor(q.waiting_seconds/60)+' мин',
      'openUser',q.user_id)).join(''):placeholder)+'</div>'+
      pageNav(state.queuePage,state.queuePage+1<d.pages,'queuePage');
  }
  async function polls(){
    const d=await api('/polls'),p=d.active,r=d.results||{};
    return wrapHeader('Управление голосованиями')+
      (p?'<div class="admin-report"><strong>'+escape(p.question)+'</strong><p>'+
      escape(p.option_a)+' · '+fmt(r.a)+' ('+fmt(r.pct_a)+'%)<br>'+
      escape(p.option_b)+' · '+fmt(r.b)+' ('+fmt(r.pct_b)+'%)</p>'+
      '<small>Всего голосов: '+fmt(r.total)+'</small>'+
      navButton('Завершить опрос','closePoll','','danger')+'</div>'+
      '<div class="admin-subheading">Последние голоса</div><div class="admin-list">'+
      (d.voters?.length?d.voters.map(v=>row(escape(v.nickname||v.first_name||'Аноним'),
      'ID '+v.user_id+' · '+(v.choice===0?escape(p.option_a):escape(p.option_b))+' · '+date(v.updated_at),
      'openUser',v.user_id)).join(''):placeholder)+'</div>':placeholder)+
      '<div class="admin-subheading">Новый опрос</div><form id="adminPollForm" class="admin-form">'+
      '<label>Вопрос<input name="question" maxlength="250" required></label>'+
      '<label>Вариант 1<input name="option_a" maxlength="48" required></label>'+
      '<label>Вариант 2<input name="option_b" maxlength="48" required></label>'+
      '<button type="submit" class="admin-primary">Создать опрос</button></form>';
  }
  async function games(){
    const d=await api('/games',{}, {page:state.gamesPage});
    return wrapHeader('Активных игр: '+d.total)+
      '<div class="admin-list">'+(d.items?.length?d.items.map(g=>'<div class="admin-report"><div class="admin-report-head"><strong>Игра #'+g.id+' · '+escape(g.game_type)+'</strong>'+pill(g.status)+'</div>'+
      '<small>Раунд '+(Number(g.question_index)+1)+'/'+g.total_questions+' · '+date(g.updated_at)+'</small>'+
      '<div class="admin-actions">'+navButton('ID '+g.user_a,'openUser',g.user_a)+navButton('ID '+g.user_b,'openUser',g.user_b)+'</div></div>').join(''):placeholder)+'</div>'+
      pageNav(state.gamesPage,state.gamesPage+1<d.pages,'gamesPage');
  }
  async function analytics(){
    const d=await api('/analytics'),p=d.payments||{},g=d.games||{};
    const amounts=[['Поддержка Stars',fmt(p.support_stars_total)+' ★'],['Поддержка СБП',fmt(p.support_sbp_total)+' ₽'],
      ['Anon Plus Stars',fmt(p.anonplus_stars_total)+' ★'],['Anon Plus СБП',fmt(p.anonplus_sbp_total)+' ₽'],
      ['Активных Plus',fmt(p.anonplus_active)],['Игр: битва',fmt(g.battle)],['Игр: числа',fmt(g.numbers)],['Игр: Geo',fmt(g.geo)]];
    const sources=d.sources||[],max=Math.max(1,...sources.map(a=>Number(a.credits)));
    return wrapHeader('Поддержка проекта и экономика')+
      '<section class="admin-stats">'+amounts.map(([k,v])=>tile(k,v)).join('')+'</section><div class="admin-subheading">Начисления по источникам · неделя</div>'+
      '<div class="admin-chart">'+(sources.length?sources.map(s=>'<div class="admin-chart-row"><span>'+escape(sourceNames[s.source]||s.source)+'</span><strong>+'+fmt(s.credits)+' ★</strong><div class="admin-chart-track"><i style="width:'+Math.max(0,Math.min(100,s.credits/max*100))+'%"></i></div></div>').join(''):placeholder)+'</div>';
  }
  async function admins(){
    const d=await api('/admins');
    return wrapHeader('Управление правами · только владелец')+
      '<div class="admin-subheading">Владельцы</div><div class="admin-list">'+(d.owners||[]).map(id=>row('ID '+id,'Права: полный доступ','openUser',id)).join('')+'</div>'+
      '<div class="admin-subheading">Назначенные администраторы</div><div class="admin-list">'+(d.items?.length?d.items.map(u=>'<article class="admin-report"><b>'+escape(u.first_name||u.username||u.user_id)+'</b><small>ID '+u.user_id+' · '+escape(u.permissions)+'</small>'+
        '<div class="admin-actions">'+navButton('Изменить','editAdmin',u.user_id)+'</div></article>').join(''):placeholder)+'</div>'+
      navButton('+ Назначить администратора','editAdmin','0','accent');
  }
  function broadcast(){
    return wrapHeader('Одно сообщение для пользователей')+
      '<form id="adminBroadcastForm" class="admin-form"><label>Сообщение<textarea name="message" maxlength="3000" rows="6" required placeholder="Текст рассылки"></textarea></label>'+
      '<label>Текст кнопки (необязательно)<input name="button_text" maxlength="45" placeholder="Подробнее"></label>'+
      '<label>HTTPS-ссылка кнопки (необязательно)<input name="button_url" placeholder="https://t.me/..."></label>'+
      '<button type="submit" class="admin-primary">Предпросмотр рассылки</button></form>'+
      (state.broadcastKey?'<div class="admin-note">Последняя рассылка: '+escape(state.broadcastKey.slice(0,10))+' · '+navButton('Проверить статус','broadcastStatus')+
      navButton('Остановить','broadcastStop','','danger')+'</div>':'');
  }
  async function diagnostics(){
    const d=await api('/diagnostics');
    return wrapHeader('Статус BotHost и SQLite')+'<section class="admin-stats">'+
      tile('Бот','Онлайн')+tile('Аптайм',Math.floor(d.uptime/3600)+' ч')+
      tile('Версия',String(d.version||'—'))+tile('SQLite',fmt(d.db_bytes)+' байт')+
      tile('Очередь',fmt(d.queue))+tile('Диалоги',fmt(d.pairs))+
      tile('Активные игры',fmt(d.games?.total))+
      tile('Ошибки Telegram',fmt(d.telegram_errors))+
      tile('Недоступные пользователи',fmt(d.unavailable))+
      tile('Последняя очистка',date(d.last_cleanup_at))+
      tile('SQLite',d.db_ok?'Работает':'Ошибка')+
      tile('Задержка БД',String(d.db_query_ms||0)+' мс')+
      tile('Последний бэкап',d.backup_last_success_at?date(d.backup_last_success_at):'Нет')+
      tile('Уведомления в очереди',fmt(d.notifications?.pending||0))+
      tile('Ошибки уведомлений',fmt((d.notifications?.failed||0)+(d.notifications?.undeliverable||0)))+
      tile('Активные рассылки',fmt(d.broadcasts?.running||0))+'</section>'+
      (d.backup_error?'<div class="admin-note">Ошибка бэкапа: '+escape(d.backup_error)+'</div>':'')+
      (state.owner?'<div class="admin-actions">'+navButton('Скачать резервную копию SQLite','backup')+
      navButton('Изменить x1 / x2 / x3','multiplier')+'</div>':'');
  }
  async function audit(){
    const d=await api('/actions',{}, {page:state.actionsPage});
    return wrapHeader('Административные действия')+
      '<div class="admin-list">'+(d.items?.length?d.items.map(i=>row(
      escape(i.action)+' · ID '+i.target_id,
      date(i.created_at)+' · админ '+i.actor_id+(i.reason?' · '+escape(i.reason):''),
      'openUser',i.target_id)).join(''):placeholder)+'</div>'+
      pageNav(state.actionsPage,d.has_more,'actionsPage');
  }
  function startAdjust(value){
    const sign=value.startsWith('-')?-1:1,target=Number(value.slice(1));
    showModal('<h2>'+(sign>0?'Выдать очки':'Списать очки')+'</h2><p class="admin-muted">Пользователь ID '+target+'. Награда не умножается на x2/x3 — это ручная корректировка.</p>'+
      '<form id="adminAdjustForm" class="admin-form"><label>Сумма<input name="amount" type="number" min="1" max="1000000" value="100" required></label>'+
      '<div class="admin-quick">'+[10,25,50,100,250,500].map(n=>navButton(String(n)+' ★','quickAmount',n)).join('')+'</div>'+
      '<label>Причина (обязательно)<textarea name="reason" maxlength="500" required placeholder="Почему начисляем или списываем?"></textarea></label>'+
      '<button class="admin-primary" type="submit">Проверить изменение</button></form>');
    state.adjust={target,sign};
  }
  function startModeration(value){
    const [action,user_id,report_id]=value.split(':');
    const names={ban:'Заблокировать',unban:'Разблокировать',mute:'Выдать мут',unmute:'Снять мут',
      report_ban:'Бан по жалобе',report_mute:'Мут по жалобе',report_close:'Закрыть жалобу'};
    state.moderation={action,user_id:Number(user_id),report_id:Number(report_id||0)};
    showModal('<h2>'+escape(names[action]||action)+'</h2><p class="admin-muted">ID '+escape(user_id||'—')+
      (report_id?' · жалоба #'+escape(report_id):'')+'</p><form id="adminModerationForm" class="admin-form">'+
      (action.includes('mute')&&action!=='unmute'?'<label>Продолжительность, минут<input type="number" name="minutes" min="1" max="43200" value="60" required></label>':'')+
      '<label>Причина действия<textarea name="reason" maxlength="500" required placeholder="Укажи причину"></textarea></label>'+
      '<button type="submit" class="admin-primary">Проверить действие</button></form>');
  }
  async function editAdmin(value){
    const d=await api('/admins'),uid=Number(value),u=(d.items||[]).find(x=>Number(x.user_id)===uid);
    showModal('<h2>Права администратора</h2><form id="adminPermissionsForm" class="admin-form">'+
      '<label>Telegram ID<input name="user_id" type="number" min="1" value="'+(uid||'')+'" required></label>'+
      '<div class="admin-permission-grid">'+(d.permission_names||[]).map(p=>'<label><input type="checkbox" name="permission" value="'+escape(p)+'"'+(String(u?.permissions||'').split(',').includes(p)?' checked':'')+'> '+escape(p)+'</label>').join('')+'</div>'+
      '<p class="admin-muted">Если снять все галочки, права будут отозваны. Права владельцев задаются в конфигурации бота.</p>'+
      '<button type="submit" class="admin-primary">Сохранить права</button></form>');
  }
  async function downloadBackup(){
    const response=await fetch(url('/backup'),{headers:{'X-Telegram-Init-Data':tg.initData},cache:'no-store'});
    if(!response.ok)throw new Error('Не удалось скачать базу: '+response.status);
    const blob=await response.blob();
    const link=document.createElement('a'),object=URL.createObjectURL(blob);
    link.href=object;link.download='anon_mgn_backup.db';document.body.append(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(object),10000);
    toast('Копия базы сформирована');
  }
  async function statusBroadcast(){
    if(!state.broadcastKey)return;
    const d=await api('/broadcast/status',{}, {key:state.broadcastKey});
    toast('Рассылка: '+d.status+' · отправлено '+fmt(d.sent)+' · ожидает '+fmt(d.pending)+' · ошибок '+fmt(d.failed)+' · проверить '+fmt(d.uncertain));
  }
  root.addEventListener('click',async e=>{
    const el=e.target.closest('[data-action]');if(!el||el.disabled)return;
    const action=el.dataset.action,value=el.dataset.value||'';
    try{
      if(action==='close')close();
      else if(action==='back')state.modal?closeModal():state.page==='user'?goto(state.back||'users'):state.page==='dashboard'?close():goto('dashboard');
      else if(action==='refresh')render();
      else if(action==='nav'){if(value==='ledger'){state.ledgerUser='';state.ledgerPage=0}goto(value)}
      else if(action==='openUser'||action==='user'){if(!can('users'))return;state.back=state.page==='user'?'users':state.page;state.selectedId=Number(value);goto('user')}
      else if(action==='userLedger'){state.ledgerUser=String(value);state.ledgerPage=0;goto('ledger')}
      else if(action==='copy'){await navigator.clipboard.writeText(value);toast('ID скопирован')}
      else if(action==='modalClose')closeModal();
      else if(action==='openAdjust')startAdjust(value);
      else if(action==='openModerate')startModeration(value);
      else if(action==='quickAmount'){$('#adminAdjustForm [name="amount"]',root).value=value}
      else if(action==='rankingPeriod'){state.rankingPeriod=value;render()}
      else if(action==='reportsStatus'){state.reportsStatus=value;state.reportsPage=0;render()}
      else if(action==='editAdmin')await editAdmin(value);
      else if(action==='usersPage'){state.usersPage=Number(value);render()}
      else if(action==='ledgerPage'){state.ledgerPage=Number(value);render()}
      else if(action==='reportsPage'){state.reportsPage=Number(value);render()}
      else if(action==='restrictedPage'){state.restrictedPage=Number(value);render()}
      else if(action==='chatsPage'){state.chatsPage=Number(value);render()}
      else if(action==='queuePage'){state.queuePage=Number(value);render()}
      else if(action==='gamesPage'){state.gamesPage=Number(value);render()}
      else if(action==='actionsPage'){state.actionsPage=Number(value);render()}
      else if(action==='backup')await downloadBackup();
      else if(action==='broadcastStop'){if(state.broadcastKey&&confirm('Остановить рассылку?')){
        const info=await post('/broadcast/stop',{key:state.broadcastKey});
        toast('Статус рассылки: '+info.status);render();
      }}
      else if(action==='exportLedger'){
        const params={period:state.ledgerPeriod,kind:state.ledgerKind,
          source:state.ledgerSource,user_id:state.ledgerUser};
        const response=await fetch(url('/transactions/export',params),{
          headers:{'X-Telegram-Init-Data':tg.initData},cache:'no-store'});
        if(!response.ok)throw new Error('Экспорт недоступен: '+response.status);
        const object=URL.createObjectURL(await response.blob());
        const link=document.createElement('a');link.href=object;
        link.download='anon_mgn_history.csv';document.body.append(link);link.click();link.remove();
        setTimeout(()=>URL.revokeObjectURL(object),10000);
      }
      else if(action==='closePoll'){
        if(!confirm('Закрыть текущий опрос?'))return;
        await post('/polls',{action:'close',key:key(),question:''});
        toast('Опрос завершён');render();
      }
      else if(action==='broadcastStatus')await statusBroadcast();
      else if(action==='multiplier'){showModal('<h2>Множитель очков</h2><p class="admin-muted">Устанавливает ручной x1/x2/x3. Автоматический x2 по дням недели действует отдельно.</p><div class="admin-actions">'+[1,2,3].map(n=>navButton('×'+n,'setMultiplier',n)).join('')+'</div>')}
      else if(action==='setMultiplier'){if(!confirm('Установить x'+value+'?'))return;const d=await post('/multiplier',{value:Number(value)});closeModal();toast('Множитель: x'+d.multiplier);render()}
      else if(action==='executeAdjust'){
        if(el.disabled)return;
        el.disabled=true;
        try{const a=state.pending;const r=await post('/adjust',{user_id:a.target,amount:a.amount,reason:a.reason,key:a.key});
          closeModal();toast(r.applied?'Баланс изменён: '+fmt(r.balance)+' ★':'Уже выполнено');render()}
        finally{el.disabled=false}
      }else if(action==='executeModeration'){
        el.disabled=true;
        try{const a=state.pending;const r=await post('/moderate',a);
          closeModal();toast(r.message||'Готово');render()}
        finally{el.disabled=false}
      }else if(action==='executeBroadcast'){
        el.disabled=true;
        try{const a=state.pending;const r=await post('/broadcast',a);state.broadcastKey=a.key;
          closeModal();toast(r.started?'Рассылка запущена':r.message);render()}
        finally{el.disabled=false}
      }
    }catch(error){toast(error.message||'Не удалось выполнить действие')}
  });
  root.addEventListener('change',e=>{
    if(!e.target.dataset.filter)return;
    const f=e.target.dataset.filter;
    state[f]=e.target.value;
    if(f==='sort'||f==='userFilter')state.usersPage=0;
    if(f.startsWith('ledger'))state.ledgerPage=0;
    render();
  });
  root.addEventListener('submit',async e=>{
    e.preventDefault();
    const form=e.target,id=form.id,data=new FormData(form);
    try{
      if(id==='adminSearch'){state.query=String(data.get('q')||'').trim().slice(0,100);state.usersPage=0;render()}
      else if(id==='adminLedgerSearch'){state.ledgerUser=String(data.get('uid')||'').trim();state.ledgerPage=0;render()}
      else if(id==='adminAdjustForm'){
        const amount=Number(data.get('amount')),reason=String(data.get('reason')||'').trim(),a=state.adjust;
        if(!Number.isInteger(amount)||amount<1||amount>1e6||!reason)throw new Error('Укажи сумму и причину');
        const full=amount*a.sign;
        state.pending={target:a.target,amount:full,reason,key:key()};
        const d=await api('/users/'+a.target);
        if(full<0&&d.user.xp+full<0)throw new Error('Нельзя списать больше текущего баланса');
        showModal('<h2>Подтверждение</h2><dl class="admin-details"><div><dt>ID пользователя</dt><dd>'+a.target+'</dd></div>'+
          '<div><dt>Баланс сейчас</dt><dd>'+fmt(d.user.xp)+' ★</dd></div><div><dt>Изменение</dt><dd>'+fmt(full)+' ★</dd></div>'+
          '<div><dt>Станет</dt><dd>'+fmt(d.user.xp+full)+' ★</dd></div><div><dt>Причина</dt><dd>'+escape(reason)+'</dd></div></dl>'+
          navButton('Подтвердить изменение','executeAdjust','','admin-primary'));
      }else if(id==='adminModerationForm'){
        const a=state.moderation,reason=String(data.get('reason')||'').trim();
        if(!reason)throw new Error('Причина обязательна');
        state.pending={...a,reason,minutes:Number(data.get('minutes')||60),key:key()};
        showModal('<h2>Подтвердить действие?</h2><p>'+escape(a.action)+' · пользователь '+a.user_id+
          (a.report_id?' · жалоба #'+a.report_id:'')+'</p><p class="admin-muted">'+escape(reason)+'</p>'+
          navButton('Да, выполнить','executeModeration','','admin-primary danger'));
      }else if(id==='adminPermissionsForm'){
        const user_id=Number(data.get('user_id')),permissions=data.getAll('permission');
        if(!Number.isInteger(user_id)||user_id<1)throw new Error('Неверный Telegram ID');
        if(!confirm('Сохранить права для ID '+user_id+'?'))return;
        await post('/admins',{user_id,permissions});closeModal();toast('Права обновлены');render();
      }else if(id==='adminPollForm'){
        const question=String(data.get('question')||'').trim(),
              option_a=String(data.get('option_a')||'').trim(),
              option_b=String(data.get('option_b')||'').trim();
        if(!question||!option_a||!option_b)throw new Error('Заполни все поля');
        if(!confirm('Опубликовать новый опрос? Предыдущий закроется.'))return;
        await post('/polls',{action:'create',question,option_a,option_b,key:key()});
        toast('Опрос создан');render();
      }else if(id==='adminBroadcastForm'){
        const message=String(data.get('message')||'').trim(),button_text=String(data.get('button_text')||'').trim(),button_url=String(data.get('button_url')||'').trim();
        if(!message)throw new Error('Напиши текст рассылки');
        state.pending={message,button_text,button_url,key:key()};
        showModal('<h2>Предпросмотр рассылки</h2><div class="admin-broadcast-preview">'+escape(message).replace(/\n/g,'<br>')+
          (button_text?'<div class="admin-preview-button">'+escape(button_text)+'</div>':'')+'</div>'+
          '<p class="admin-muted">Сообщение будет разослано пользователям бота. Повторное подтверждение не создаст вторую рассылку.</p>'+
          navButton('Подтвердить рассылку','executeBroadcast','','admin-primary danger'));
      }
    }catch(error){toast(error.message||'Ошибка формы')}
  });
  async function probe(){
    try{
      const data=await api('/bootstrap');
      state.permissions=data.permissions||[];state.owner=Boolean(data.owner);
      const launch=document.createElement('button');
      launch.className='admin-launch';
      launch.type='button';launch.textContent='Админка';launch.setAttribute('aria-label','Открыть админ-панель');
      launch.onclick=open;
      const topbar=$('.topbar');if(topbar)topbar.insertBefore(launch,topbar.lastElementChild);
      const profile=$('[data-page="profile"]');
      if(profile){const button=document.createElement('button');button.type='button';button.className='admin-profile-launch';button.innerHTML='<strong>Администрирование</strong><small>Пользователи, начисления, жалобы, статистика →</small>';button.onclick=open;profile.append(button)}
    }catch(error){if(!String(error.message).includes('прав')&&!String(error.message).includes('403'))console.info('Admin panel unavailable')}
  }
  probe();
})();
