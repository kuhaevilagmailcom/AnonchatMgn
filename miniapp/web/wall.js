(function wallModule() {
  'use strict';
  const root = document.querySelector('[data-page="wall"]');
  if (!root) return;
  const $ = (s, p = document) => p.querySelector(s);
  const $$ = (s, p = document) => [...p.querySelectorAll(s)];
  const tg = window.Telegram?.WebApp;
  const base = (window.ANON_MGN_API_BASE || $('meta[name="api-base"]')?.content || '').replace(/\/$/, '');
  const paths = {
    plus:'<path d="M12 5v14M5 12h14"/>',
    back:'<path d="m15 18-6-6 6-6"/>',
    heart:'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l7.8-7.5a5.5 5.5 0 0 0 1-8.9Z"/>',
    comment:'<path d="M20 11.5A7.5 7.5 0 0 1 12.5 19H8l-4 2v-5a7.5 7.5 0 1 1 16-4.5Z"/><path d="M8 11.5h8"/>',
    share:'<path d="M12 16V3m0 0L7 8m5-5 5 5"/><path d="M5 13v6.5A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V13"/>',
    menu:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    send:'<path d="m21 3-8 18-3.2-7.8L2 10 21 3Z"/><path d="m21 3-11.2 10.2"/>',
    x:'<path d="M18 6 6 18M6 6l12 12"/>',
    shield:'<path d="m12 22 7-4V6l-7-4-7 4v12l7 4Z"/><path d="M9 12h6"/>',
    edit:'<path d="m14 4 6 6M3 21l4.3-1 12-12a3 3 0 0 0-4.2-4.2l-12 12L3 21Z"/>',
    trash:'<path d="M4 7h16M10 4h4M6 7l1 14h10l1-14M10 11v6m4-6v6"/>'
  };
  const icon = key => `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[key] || paths.comment}</svg>`;
  const esc = v => String(v ?? '').replace(/[&<>"']/g, a=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[a]));
  const time = ts => {
    const diff = Math.max(0, Date.now()/1000-Number(ts||0));
    return diff<60?'сейчас':diff<3600?Math.floor(diff/60)+' мин':diff<86400?Math.floor(diff/3600)+' ч':new Date(Number(ts)*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'short'});
  };
  const state = {mode:'new',posts:[],offset:0,more:false,busy:false,current:null,reply:null,isAdmin:false};
  const overlay = $('#wallOverlay');
  let ticket=0;
  const api = async(path,method='GET',data) => {
    const control=new AbortController(),timeout=setTimeout(()=>control.abort(),15000);
    const headers={'X-Telegram-Init-Data':tg?.initData||''};
    if(data!==undefined)headers['Content-Type']='application/json';
    try{
      const res=await fetch(base+path,{method,headers,body:data===undefined?undefined:JSON.stringify(data),cache:'no-store',signal:control.signal});
      const json=await res.json().catch(()=>({}));
      if(!res.ok)throw new Error(json.message||'Ошибка запроса');
      return json;
    }catch(err){if(err.name==='AbortError')throw Error('Сервер долго отвечает');throw err;}
    finally{clearTimeout(timeout)}
  };
  const flash = message => {
    $('.wall-toast')?.remove();
    const el=document.createElement('div');el.className='wall-toast';el.textContent=message;
    document.body.append(el);setTimeout(()=>el.remove(),2600);
  };
  const link=id=>'https://t.me/AnonChatMgn_Bot/anonmgn?startapp=wall_'+id;
  function postHtml(p,detail=false){
    return `<article class="wall-post" data-wall-post="${p.id}">
      <header class="wall-post-head">
        <span class="wall-avatar" aria-hidden="true">${esc((p.nick||'А').slice(0,1).toUpperCase())}</span>
        <div class="wall-post-meta"><strong>${esc(p.nick||'Аноним')}</strong><small>${time(p.created_at)}${p.updated_at>p.created_at?' · изменён':''}</small></div>
        <button class="wall-icon-btn" data-wall-action="menu" data-id="${p.id}" aria-label="Меню публикации">${icon('menu')}</button>
      </header>
      <div class="wall-post-body">${esc(p.body)}</div>
      <footer class="wall-post-actions">
        <button class="${p.liked?'liked':''}" data-wall-action="like" data-id="${p.id}" aria-label="Нравится">${icon('heart')}<span>${p.likes||''}</span></button>
        <button data-wall-action="open" data-id="${p.id}" aria-label="Комментарии">${icon('comment')}<span>${p.comments||''}</span></button>
        <button data-wall-action="share" data-id="${p.id}" aria-label="Поделиться">${icon('share')}</button>
        ${detail?'':'<button class="wall-post-open" data-wall-action="open" data-id="'+p.id+'">Обсудить</button>'}
      </footer></article>`;
  }
  async function feed(more=false){
    if(state.busy)return;
    state.busy=true;
    const box=$('#wallFeed');
    if(!more){state.offset=0;box.innerHTML='<div class="wall-loading">Загрузка обсуждений…</div>'}
    try{
      const data=await api('/api/miniapp/wall?sort='+state.mode+'&offset='+state.offset);
      state.posts=more?state.posts.concat(data.items||[]):data.items||[];
      state.offset=data.offset;state.more=Boolean(data.more);state.isAdmin=Boolean(data.is_admin);
      $('#wallModeration').hidden=!state.isAdmin;
      box.innerHTML=state.posts.length?state.posts.map(p=>postHtml(p)).join(''):`<div class="wall-empty">${icon('comment')}<strong>Здесь пока тихо</strong><p>Стань первым, кто начнёт обсуждение.</p></div>`;
      $('#wallMore').hidden=!state.more;
    }catch(err){if(!more)box.innerHTML='<div class="wall-empty">Не удалось загрузить стену</div>';flash(err.message)}
    finally{state.busy=false;}
  }
  function sheet(title,html){
    overlay.hidden=false;overlay.innerHTML=`<div class="wall-sheet" role="dialog" aria-label="${esc(title)}">${html}</div>`;
    document.body.classList.add('wall-sheet-open');overlay.scrollTop=0;
  }
  function header(title){
    return `<header class="wall-sheet-header"><button class="wall-icon-btn" data-wall-close aria-label="Назад">${icon('back')}</button><strong>${esc(title)}</strong><span></span></header>`;
  }
  function close(){
    ++ticket;overlay.hidden=true;overlay.innerHTML='';state.reply=null;
    document.body.classList.remove('wall-sheet-open');
  }
  function compose(post=null){
    state.current=post||null;
    const title=post?'Редактировать':'Новая публикация';
    sheet(title,`${header(title)}<form class="wall-compose" id="wallPostForm">
      <div class="wall-compose-user"><span class="wall-avatar">${esc(($('[data-nick]')?.textContent||'А').slice(0,1).toUpperCase())}</span><strong>${esc($('[data-nick]')?.textContent||'Аноним')}</strong></div>
      <textarea id="wallPostText" maxlength="1000" placeholder="Что нового? Напиши что-нибудь…" required>${esc(post?.body||'')}</textarea>
      <div class="wall-compose-foot"><small id="wallCount"></small><button class="wall-publish" type="submit">${post?'Сохранить':'Опубликовать'}</button></div>
      </form>`);
    const input=$('#wallPostText'),counter=$('#wallCount'),submit=$('.wall-publish');
    const update=()=>counter.textContent=input.value.length+' / 1000';
    input.addEventListener('input',update);update();input.focus();
    $('#wallPostForm').onsubmit=async e=>{
      e.preventDefault();if(submit.disabled||!input.value.trim())return;
      submit.disabled=true;
      try{
        const result=await api(post?'/api/miniapp/wall/'+post.id+'/edit':'/api/miniapp/wall','POST',{body:input.value.trim()});
        close();flash(post?'Изменено':'Опубликовано');await feed();
        if(post||result.id)openPost(post?.id||result.id);
      }catch(err){flash(err.message);submit.disabled=false}
    };
  }
  function commentsHtml(rows){
    if(!rows.length)return '<div class="wall-empty wall-small-empty">Ответов пока нет. Начни обсуждение.</div>';
    const map=new Map(),ids=new Set(rows.map(c=>c.id));
    rows.forEach(c=>{const parent=ids.has(c.parent_id)?c.parent_id:0;map.set(parent,[...(map.get(parent)||[]),c]);});
    const seen=new Set();let html='';
    function walk(parent,depth){
      for(const c of map.get(parent)||[]){
        if(seen.has(c.id))continue;seen.add(c.id);
        html+=`<article class="wall-comment ${depth?'wall-comment-reply':''}">
          <span class="wall-avatar">${esc((c.nick||'А').slice(0,1).toUpperCase())}</span>
          <div class="wall-comment-main"><div class="wall-comment-top"><strong>${esc(c.nick)}</strong>${c.is_author?'<b class="wall-author-label">Автор</b>':''}<small>${time(c.created_at)}</small></div>
          <p>${esc(c.body)}</p><div class="wall-comment-opts">
          <button data-wall-action="reply" data-comment="${c.id}" data-nick="${esc(c.nick)}">Ответить</button>
          <button data-wall-action="${c.mine?'delete-comment':'report-comment'}" data-comment="${c.id}">${c.mine?'Удалить':'Пожаловаться'}</button></div></div></article>`;
        walk(c.id,Math.min(depth+1,2));
      }
    }walk(0,0);
    return html;
  }
  async function openPost(id){
    id=Number(id);if(!Number.isInteger(id)||id<1)return;
    const current=++ticket;state.reply=null;
    sheet('Обсуждение',header('Обсуждение')+'<div class="wall-loading">Загружаем комментарии…</div>');
    try{
      const data=await api('/api/miniapp/wall/'+id);if(current!==ticket)return;
      state.current=data.post;state.isAdmin=Boolean(data.is_admin);
      $('.wall-sheet',overlay).innerHTML=`${header('Обсуждение')}<div class="wall-detail-scroll">
        ${postHtml(data.post,true)}<div class="wall-comments-title"><strong>Ответы</strong><span>${data.comments.length}</span></div>
        ${commentsHtml(data.comments)}${data.truncated?'<div class="wall-note">Показаны первые 500 ответов.</div>':''}</div>
        <form id="wallCommentForm" class="wall-comment-form">
          <div id="wallReplyTo" hidden></div>
          <div class="wall-comment-row"><textarea id="wallCommentText" rows="1" maxlength="500" placeholder="Написать ответ…" required></textarea>
          <button class="wall-send" type="submit" aria-label="Отправить">${icon('send')}</button></div>
        </form>`;
      $('#wallCommentForm').onsubmit=async e=>{
        e.preventDefault();const input=$('#wallCommentText'),send=$('.wall-send');if(!input.value.trim())return;
        send.disabled=true;
        try{
          await api('/api/miniapp/wall/'+id+'/comments','POST',{body:input.value.trim(),parent_id:state.reply?.id||null});
          await openPost(id);feed();
        }catch(err){flash(err.message);send.disabled=false}
      };
    }catch(err){if(current===ticket)$('.wall-sheet',overlay).innerHTML=header('Обсуждение')+'<div class="wall-empty">'+esc(err.message)+'</div>';}
  }
  function reply(id,nick){
    state.reply={id,nick};const target=$('#wallReplyTo');if(!target)return;
    target.hidden=false;target.innerHTML=`<span>Ответ для <b>${esc(nick)}</b></span><button data-wall-action="cancel-reply" aria-label="Отменить">${icon('x')}</button>`;
    $('#wallCommentText')?.focus();
  }
  async function share(id){
    const url=link(id);
    if(navigator.share){try{await navigator.share({title:'Стена АНОН МГН',url});return}catch(_){}}
    try{await navigator.clipboard.writeText(url);flash('Ссылка скопирована')}
    catch(_){if(tg?.showAlert)tg.showAlert(url);else flash(url);}
  }
  function menu(id){
    const p=state.current?.id===id?state.current:state.posts.find(x=>x.id===id);
    if(!p)return;state.current=p;
    const actions=p.mine?`<button data-wall-action="edit" data-id="${id}">${icon('edit')}Редактировать</button>
      <button class="danger" data-wall-action="delete" data-id="${id}">${icon('trash')}Удалить пост</button>`:
      `<button data-wall-action="report" data-id="${id}">${icon('shield')}Пожаловаться</button>`;
    sheet('Действия',header('Действия')+`<div class="wall-menu">${actions}${state.isAdmin?`<button class="danger" data-wall-action="hide" data-id="${id}">${icon('shield')}Скрыть</button>`:''}</div>`);
  }
  async function moderation(){
    sheet('Жалобы',header('Жалобы')+'<div class="wall-loading">Загрузка…</div>');
    try{
      const data=await api('/api/miniapp/wall/moderation');
      $('.wall-sheet',overlay).innerHTML=header('Жалобы')+
        (data.items.length?data.items.map(r=>`<div class="wall-report"><small>${r.type==='post'?'Публикация':'Комментарий'} #${r.target_id} · ${time(r.created_at)}</small>
        <strong>${esc(r.reason)}</strong><p>${esc(r.body||'Контент удалён')}</p>
        <button data-wall-action="moderate" data-kind="${r.type}" data-id="${r.target_id}">Скрыть и закрыть жалобу</button>
        <button data-wall-action="dismiss" data-kind="${r.type}" data-id="${r.target_id}">Отклонить</button></div>`).join(''):
        '<div class="wall-empty">Жалоб нет</div>');
    }catch(err){flash(err.message)}
  }
  async function handle(el){
    const action=el.dataset.wallAction,id=Number(el.dataset.id);
    if(action==='open')return openPost(id);
    if(action==='share')return share(id);
    if(action==='menu')return menu(id);
    if(action==='reply')return reply(Number(el.dataset.comment),el.dataset.nick);
    if(action==='cancel-reply'){state.reply=null;$('#wallReplyTo').hidden=true;return;}
    if(action==='edit')return compose(state.current);
    if(action==='like'){
      if(el.disabled)return;el.disabled=true;
      try{
        const r=await api('/api/miniapp/wall/'+id+'/like','POST',{});
        const p=state.posts.find(p=>p.id===id);if(p){p.liked=r.liked;p.likes=r.likes;}
        if(state.current?.id===id){state.current.liked=r.liked;state.current.likes=r.likes;}
        $$('[data-wall-action="like"][data-id="'+id+'"]').forEach(btn=>{
          btn.classList.toggle('liked',r.liked);$('span',btn).textContent=r.likes||'';
        });
      }catch(err){flash(err.message)}finally{el.disabled=false;}
      return;
    }
    if(action==='delete'&&window.confirm('Удалить публикацию?')){
      try{await api('/api/miniapp/wall/'+id+'/delete','POST',{});close();flash('Удалено');feed()}
      catch(err){flash(err.message)}return;
    }
    if(action==='delete-comment'&&window.confirm('Удалить комментарий?')){
      try{await api('/api/miniapp/wall/comments/'+el.dataset.comment+'/delete','POST',{});openPost(state.current.id);feed()}
      catch(err){flash(err.message)}return;
    }
    if(action==='report'||action==='report-comment'){
      try{
        await api('/api/miniapp/wall/report','POST',{type:action==='report'?'post':'comment',id:action==='report'?id:Number(el.dataset.comment),reason:'Нарушение правил'});
        flash('Жалоба отправлена');if(action==='report')close();
      }catch(err){flash(err.message)}return;
    }
    if(action==='hide'||action==='moderate'||action==='dismiss'){
      try{
        await api('/api/miniapp/wall/moderate','POST',{type:action==='hide'?'post':el.dataset.kind,id,hide:action!=='dismiss'});
        flash('Готово');if(action==='hide'){close();feed()}else moderation();
      }catch(err){flash(err.message)}
    }
  }
  root.addEventListener('click',e=>{const b=e.target.closest('[data-wall-action]');if(b){e.preventDefault();handle(b)}});
  overlay.addEventListener('click',e=>{
    if(e.target.closest('[data-wall-close]')){close();return;}
    const b=e.target.closest('[data-wall-action]');if(b){e.preventDefault();handle(b)}
  });
  $('#wallComposeButton').onclick=()=>compose();
  $('#wallMore').onclick=()=>feed(true);
  $('#wallModeration').onclick=moderation;
  $$('[data-wall-sort]',root).forEach(b=>b.onclick=()=>{
    if(state.mode===b.dataset.wallSort)return;
    state.mode=b.dataset.wallSort;
    $$('[data-wall-sort]',root).forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-selected',x===b?'true':'false')});
    feed();
  });
  window.AnonWall={onPage(page){if(page==='wall')feed()},openPost};
})();
