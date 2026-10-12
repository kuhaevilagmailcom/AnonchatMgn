(function wallModule() {
  'use strict';
  const root = document.querySelector('[data-page="wall"]');
  if (!root) return;
  const $ = (s, p = document) => p.querySelector(s);
  const $$ = (s, p = document) => [...p.querySelectorAll(s)];
  const tg = window.Telegram?.WebApp;
  const base = (window.ANON_MGN_API_BASE || $('meta[name="api-base"]')?.content || '').replace(/\/$/, '');
  // Consistent Lucide-family outline glyphs. Every icon uses the same 24px canvas.
  // Do not add arbitrary paths/emoji to the action row.
  const paths = {
    image:'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
    play:'<path d="m8 5 12 7-12 7V5Z"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    back:'<path d="m15 18-6-6 6-6"/>',
    heart:'<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78Z"/>',
    comment:'<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
    share:'<path d="m15 14 5-5-5-5"/><path d="M20 9H9a5 5 0 0 0-5 5v2"/>',
    menu:'<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    send:'<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    x:'<path d="M18 6 6 18M6 6l12 12"/>',
    shield:'<path d="m12 22 7-4V6l-7-4-7 4v12l7 4Z"/><path d="M9 12h6"/>',
    edit:'<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.37 2.63a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4Z"/>',
    trash:'<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v5m4-5v5"/>'
  };
  const icon = key => `<svg class="wall-icon wall-icon--${key}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths[key] || paths.comment}</svg>`;
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

  const mediaCache=new Map();
  async function authorizedBlob(path){
    const res=await fetch(base+path,{headers:{'X-Telegram-Init-Data':tg?.initData||''},cache:'no-store'});
    if(!res.ok)throw Error('Медиа недоступно');
    return URL.createObjectURL(await res.blob());
  }
  const mediaObserver=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{
    for(const entry of entries){if(entry.isIntersecting){mediaObserver.unobserve(entry.target);loadImage(entry.target);}}
  },{rootMargin:'220px'}):null;
function loadImage(img){
  if(!img||!img.isConnected||img.dataset.loaded||img.dataset.loading)return;
  img.dataset.loading='1';
  const path=img.dataset.wallThumb;
  (async()=>{
    try{
      let src=mediaCache.get(path);
      if(!src){src=await authorizedBlob(path);mediaCache.set(path,src);}
      if(img.isConnected){img.src=src;img.dataset.loaded='1';}
    }catch(_){img.alt='Ошибка загрузки'}
    finally{delete img.dataset.loading}
  })();
}
function hydrateMedia(container=document){
  for(const img of $$('[data-wall-thumb]',container)){
    if(!img.dataset.loaded){
      if(mediaObserver)mediaObserver.observe(img);
      else loadImage(img);
    }
  }
}
  function mediaHtml(items=[]){
    if(!items.length)return '';
    const photos=items.every(m=>m.kind==='image');
    return '<div class="wall-post-media '+(photos?'photos':'video')+' wall-count-'+items.length+'">'+items.map(m=>{
      const thumb=esc(m.poster||m.url),id=Number(m.id);
      if(m.kind==='video')return `<button type="button" class="wall-video-tile" data-wall-action="video" data-media-id="${id}" aria-label="Воспроизвести видео"><img data-wall-thumb="${thumb}" alt="Видео"><span class="wall-play">${icon('play')}</span></button>`;
      return `<button type="button" class="wall-photo-tile" data-wall-action="photo" data-media-id="${id}" aria-label="Открыть фото"><img data-wall-thumb="${thumb}" loading="lazy" alt="Фото публикации"></button>`;
    }).join('')+'</div>';
  }
  function openViewer(inner){
    let viewer=$('#wallPhotoViewer');
    if(!viewer){viewer=document.createElement('div');viewer.id='wallPhotoViewer';viewer.className='wall-photo-viewer';document.body.append(viewer)}
    viewer.hidden=false;viewer.innerHTML=`<button class="wall-viewer-close" aria-label="Закрыть">${icon('x')}</button><div class="wall-viewer-content">${inner}</div>`;
    viewer.querySelector('.wall-viewer-close').onclick=()=>{viewer.querySelector('video')?.pause();viewer.hidden=true;viewer.innerHTML=''};
  }
  async function viewMedia(id,kind){
    const item=[...(state.current?.media||[]),...state.posts.flatMap(p=>p.media||[])].find(m=>m.id===id);
    if(!item){flash('Медиа не найдено');return}
    openViewer('<div class="wall-viewer-loading">Загрузка медиа…</div>');
    try{
      const src=await authorizedBlob(item.url);
      const content=$('#wallPhotoViewer .wall-viewer-content');
      if(!content){URL.revokeObjectURL(src);return}
      if(kind==='photo'){content.innerHTML='<img alt="Фото публикации">';content.querySelector('img').src=src}
      else{content.innerHTML='<video controls playsinline preload="metadata" autoplay></video>';content.querySelector('video').src=src}
      setTimeout(()=>URL.revokeObjectURL(src),180000);
    }catch(err){flash(err.message)}
  }
  let draft=null;
  const uuid=()=>{try{return crypto.randomUUID().replace(/-/g,'')}catch(_){return Date.now().toString(36)+Math.random().toString(36).slice(2)}};
  function draftPreview(){
    const target=$('#wallMediaPreview'),submit=$('.wall-publish');
    if(!target||!draft)return;
    target.innerHTML=draft.items.map(m=>`<div class="wall-draft-item">${m.kind==='video'?`<span class="wall-draft-video">${icon('play')}</span>`:'<img data-draft-media="'+m.id+'" alt="Фото">'}<button type="button" data-wall-action="remove-media" data-media-id="${m.id}" aria-label="Убрать вложение">${icon('x')}</button></div>`).join('')+(draft.uploading?'<div class="wall-uploading">Загрузка файлов…</div>':'');
    for(const m of draft.items){
      const img=$('[data-draft-media="'+m.id+'"]');
      if(img){
        if(m.localUrl)img.src=m.localUrl;
        else img.dataset.wallThumb=m.poster||m.url;
      }
    }
    hydrateMedia(target);if(submit)submit.disabled=draft.uploading>0;
  }
  async function uploadSelected(fileList){
    if(!draft)return;
    const currentDraft=draft;
    const files=[...fileList];if(!files.length)return;
    const videos=files.filter(f=>f.type.startsWith('video/'));
    if(videos.length>1 || (videos.length && (files.length>1||currentDraft.items.length)) ||
      (currentDraft.items.some(m=>m.kind==='video')&&files.length)){
      flash('Можно прикрепить одно видео отдельно');return;
    }
    if(files.length+currentDraft.items.length>4){flash('Можно прикрепить максимум четыре фото');return}
    for(const file of files){
      const video=file.type.startsWith('video/');
      if(!video&&!['image/jpeg','image/png','image/webp'].includes(file.type)){flash('Допустимы JPEG, PNG, WebP и MP4');continue}
      if(video&&file.type!=='video/mp4'){flash('Поддерживается MP4, не MOV');continue}
      if(file.size>(video?50:10)*1024*1024){flash('Файл слишком большой');continue}
      if(draft!==currentDraft)return;
      currentDraft.uploading++;draftPreview();
      const data=new FormData();data.append('file',file);
      try{
        const res=await fetch(base+'/api/miniapp/wall/upload',{method:'POST',headers:{'X-Telegram-Init-Data':tg?.initData||''},body:data,cache:'no-store'});
        const info=await res.json().catch(()=>({}));
        if(!res.ok)throw Error(info.message||'Не удалось загрузить файл');
        if(draft!==currentDraft){
          api('/api/miniapp/wall/media/'+info.media.id+'/delete','POST',{}).catch(()=>{});
        }else{
          currentDraft.items.push({...info.media,localUrl:video?'':URL.createObjectURL(file),isNew:true});
        }
      }catch(err){flash(err.message)}
      finally{currentDraft.uploading--;if(draft===currentDraft)draftPreview()}
    }
  }

  function postHtml(p,detail=false){
    return `<article class="wall-post" data-wall-post="${p.id}">
      <header class="wall-post-head">
        <span class="wall-avatar" aria-hidden="true">${esc((p.nick||'А').slice(0,1).toUpperCase())}</span>
        <div class="wall-post-meta"><strong>${esc(p.nick||'Аноним')}</strong><small>${time(p.created_at)}${p.updated_at>p.created_at?' · изменён':''}</small></div>
        <button class="wall-icon-btn" data-wall-action="menu" data-id="${p.id}" aria-label="Меню публикации">${icon('menu')}</button>
      </header>
      ${p.body?'<div class="wall-post-body">'+esc(p.body)+'</div>':''}
      ${mediaHtml(p.media||[])}
      <footer class="wall-post-actions">
        <button type="button" class="wall-action wall-action-like ${p.liked?'liked':''}" data-wall-action="like" data-id="${p.id}" aria-label="Нравится" aria-pressed="${Boolean(p.liked)}">${icon('heart')}<span class="wall-action-count">${p.likes||''}</span></button>
        <button type="button" class="wall-action wall-action-comment" data-wall-action="open" data-id="${p.id}" aria-label="Комментарии: ${p.comments||0}">${icon('comment')}<span class="wall-action-count">${p.comments||''}</span></button>
        <button type="button" class="wall-action wall-action-share" data-wall-action="share" data-id="${p.id}" aria-label="Поделиться">${icon('share')}</button>
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
      hydrateMedia(box);
    }catch(err){if(!more)box.innerHTML='<div class="wall-empty">Не удалось загрузить стену</div>';flash(err.message)}
    finally{state.busy=false;}
  }
  function sheet(title,html){
    const opening=overlay.hidden;
    overlay.hidden=false;overlay.innerHTML=`<div class="wall-sheet ${opening?'wall-sheet-enter':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">${html}</div>`;
    document.body.classList.add('wall-sheet-open');overlay.scrollTop=0;
  }
  function header(title){
    return `<header class="wall-sheet-header"><span></span><strong>${esc(title)}</strong><button class="wall-icon-btn" data-wall-close aria-label="Закрыть">${icon('x')}</button></header>`;
  }
  function close(){
    if(draft){draft.items.forEach(m=>m.localUrl&&URL.revokeObjectURL(m.localUrl));draft=null}
    ++ticket;overlay.hidden=true;overlay.innerHTML='';state.reply=null;
    document.body.classList.remove('wall-sheet-open');
  }
  function compose(post=null){
  state.current=post||null;
  draft={items:[...(post?.media||[])],uploading:0,clientKey:uuid()};
  const title=post?'Редактировать':'Новая публикация';
  sheet(title,header(title)+`<form class="wall-compose" id="wallPostForm">
    <div class="wall-compose-user"><span class="wall-avatar">${esc(($('[data-nick]')?.textContent||'А').slice(0,1).toUpperCase())}</span><strong>${esc($('[data-nick]')?.textContent||'Аноним')}</strong></div>
    <textarea id="wallPostText" maxlength="1000" placeholder="Что нового? Напиши что-нибудь…">${esc(post?.body||'')}</textarea>
    <div class="wall-media-preview" id="wallMediaPreview"></div>
    <input type="file" id="wallFileInput" accept="image/jpeg,image/png,image/webp,video/mp4" multiple hidden>
    <div class="wall-compose-foot">
      <div class="wall-compose-tools"><button type="button" id="wallAttach" class="wall-attach" aria-label="Прикрепить фото или видео">${icon('image')}</button>
      <small id="wallCount"></small></div>
      <button class="wall-publish" type="submit">${post?'Сохранить':'Опубликовать'}</button>
    </div></form>`);
  const input=$('#wallPostText'),counter=$('#wallCount'),submit=$('.wall-publish');
  input.addEventListener('input',()=>counter.textContent=input.value.length+' / 1000');
  counter.textContent=input.value.length+' / 1000';input.focus();
  $('#wallAttach').onclick=()=>$('#wallFileInput').click();
  $('#wallFileInput').onchange=e=>{uploadSelected(e.target.files);e.target.value='';};
  draftPreview();
  $('#wallPostForm').onsubmit=async e=>{
    e.preventDefault();if(submit.disabled||draft.uploading)return;
    const text=input.value.trim(),ids=draft.items.map(m=>m.id);
    if(!text&&!ids.length){flash('Напиши текст или прикрепи фото/видео');return}
    submit.disabled=true;
    try{
      const result=await api(post?'/api/miniapp/wall/'+post.id+'/edit':'/api/miniapp/wall','POST',{
        body:text,media_ids:ids,client_key:draft.clientKey
      });
      draft.items.forEach(m=>m.localUrl&&URL.revokeObjectURL(m.localUrl));draft=null;
      close();flash(post?'Изменено':'Опубликовано');
      await feed();if(post||result.id)openPost(post?.id||result.id);
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
      hydrateMedia(overlay);
      const commentKey=uuid();
      $('#wallCommentForm').onsubmit=async e=>{
        e.preventDefault();const input=$('#wallCommentText'),send=$('.wall-send');if(!input.value.trim())return;
        send.disabled=true;
        try{
          await api('/api/miniapp/wall/'+id+'/comments','POST',{body:input.value.trim(),parent_id:state.reply?.id||null,client_key:commentKey});
          try{tg?.HapticFeedback?.notificationOccurred('success')}catch(_){}
          await openPost(id);feed();
        }catch(err){flash(err.message);send.disabled=false}
      };
    }catch(err){if(current===ticket)$('.wall-sheet',overlay).innerHTML=header('Обсуждение')+'<div class="wall-empty">'+esc(err.message)+'</div>';}
  }
  function reply(id,nick){
    state.reply={id,nick};const target=$('#wallReplyTo');if(!target)return;
    target.hidden=false;target.innerHTML=`<span>Ответ для <b>${esc(nick)}</b></span><button data-wall-action="cancel-reply" aria-label="Отменить">${icon('x')}</button>`;
    try{tg?.HapticFeedback?.selectionChanged()}catch(_){}
    $('#wallCommentText')?.focus();
  }
  async function share(id){
    const url=link(id);
    try{tg?.HapticFeedback?.impactOccurred('soft')}catch(_){}
    if(typeof navigator.share==='function'){
      try{await navigator.share({title:'Стена АНОН МГН',url});return}
      catch(err){if(err?.name==='AbortError')return}
    }
    if(typeof tg?.openTelegramLink==='function'){
      tg.openTelegramLink('https://t.me/share/url?url='+encodeURIComponent(url));
      return;
    }
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
    if(action==='open'){
      try{tg?.HapticFeedback?.selectionChanged()}catch(_){}
      return openPost(id);
    }
    if(action==='photo'||action==='video')return viewMedia(Number(el.dataset.mediaId),action);
    if(action==='remove-media'&&draft){
      const mid=Number(el.dataset.mediaId),m=draft.items.find(x=>x.id===mid);
      draft.items=draft.items.filter(x=>x.id!==mid);
      if(m?.isNew)api('/api/miniapp/wall/media/'+mid+'/delete','POST',{}).catch(()=>{});
      if(m?.localUrl)URL.revokeObjectURL(m.localUrl);
      draftPreview();return;
    }
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
        const buttons=$('[data-wall-action="like"][data-id="'+id+'"]');
        if(!buttons.includes(el))buttons.push(el);
        buttons.forEach(btn=>{
          const wasLiked=btn.classList.contains('liked');
          btn.classList.toggle('liked',r.liked);
          btn.setAttribute('aria-pressed',String(Boolean(r.liked)));
          const count=btn.querySelector('.wall-action-count');
          if(count)count.textContent=r.likes||'';
          // Animate only successful new likes; do not move neighboring actions.
          if(r.liked&&!wasLiked){
            btn.classList.remove('wall-liked-pop');
            void btn.offsetWidth;
            btn.classList.add('wall-liked-pop');
            btn.addEventListener('animationend',()=>btn.classList.remove('wall-liked-pop'),{once:true});
          }
        });
        try{tg?.HapticFeedback?.impactOccurred(r.liked?'light':'soft')}catch(_){}
      }catch(err){
        console.warn('Wall like update failed:',err);
        flash('Не удалось обновить лайк. Попробуй ещё раз.');
      }finally{el.disabled=false;}
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
  window.AnonWall={onPage(page){if(page==='wall')feed()},openPost,close,isOpen(){return !overlay.hidden}};
})();
