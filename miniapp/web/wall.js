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
    share:'<path d="M12 16V3"/><path d="m7 8 5-5 5 5"/><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/>',
    menu:'<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    send:'<path d="M12 19V5M5 12l7-7 7 7"/>',
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
  // The keyboard changes the visual viewport without always changing 100dvh.
  // Size the dialog to the actually visible area so its composer stays accessible.
  const syncWallViewport = () => {
    if (overlay.hidden) return;
    const viewport = window.visualViewport;
    if (!viewport) return;
    overlay.style.setProperty('--wall-viewport-height', Math.round(viewport.height) + 'px');
    overlay.style.setProperty('--wall-viewport-top', Math.max(0, Math.round(viewport.offsetTop)) + 'px');
  };
  window.visualViewport?.addEventListener('resize', syncWallViewport);
  window.visualViewport?.addEventListener('scroll', syncWallViewport);
  window.addEventListener('resize', syncWallViewport);
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
  const trackSlug=(value,length=24)=>String(value||'').toLowerCase().replace(/[^a-z0-9-]/g,'-').replace(/^-+|-+$/g,'').slice(0,length);
  // Telegram reliably passes startapp to Mini Apps. Keep UTM markers inside it.
  const link=(id=null,{source='anonmgn',medium='post',campaign='wall'}={})=>{
    let start='wall'+(id==null?'':'_'+Number(id));
    for(const [name,value,max] of [['source',source,24],['medium',medium,24],['campaign',campaign,32]]){
      const clean=trackSlug(value,max);
      if(clean)start+='__utm_'+name+'_'+clean;
    }
    return 'https://t.me/AnonChatMgn_Bot/anonmgn?startapp='+start;
  };
  const wallAvatar=()=>'<span class="wall-avatar wall-avatar--brand" aria-hidden="true"><img src="./assets/anon-mgn-wall-avatar.jpg" alt="" loading="lazy"></span>';
  async function copyWallLink(id=null){
    if(!state.isAdmin)return;
    const url=link(id,{source:'anonmgn',medium:'post',campaign:id==null?'wall':'post'});
    try{await navigator.clipboard.writeText(url);flash('Ссылка скопирована')}
    catch(_){
      if(typeof tg?.showAlert==='function')tg.showAlert(url);
      else flash('Скопируй ссылку: '+url);
    }
  }

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

  let wallViewerURL=null, wallViewerRequest=0, wallGallery=[], wallGalleryIndex=0;
  function closeViewer(){
    wallViewerRequest++;
    const viewer=$('#wallPhotoViewer');
    if(!viewer)return;
    viewer.querySelector('video')?.pause();
    viewer.hidden=true;
    viewer.innerHTML='';
    if(wallViewerURL){URL.revokeObjectURL(wallViewerURL);wallViewerURL=null;}
  }
  function ensureViewer(){
    let viewer=$('#wallPhotoViewer');
    if(viewer)return viewer;
    viewer=document.createElement('div');
    viewer.id='wallPhotoViewer';
    viewer.className='wall-photo-viewer';
    viewer.setAttribute('role','dialog');
    viewer.setAttribute('aria-modal','true');
    viewer.setAttribute('aria-label','Просмотр медиа');
    document.body.append(viewer);
    let touchX=null,touchY=null;
    viewer.addEventListener('touchstart',e=>{
      if(e.touches.length!==1)return;
      touchX=e.touches[0].clientX;touchY=e.touches[0].clientY;
    },{passive:true});
    viewer.addEventListener('touchend',e=>{
      if(touchX===null||e.changedTouches.length===0)return;
      const deltaX=e.changedTouches[0].clientX-touchX;
      const deltaY=e.changedTouches[0].clientY-touchY;
      touchX=null;touchY=null;
      if(wallGallery.length>1&&Math.abs(deltaX)>65&&Math.abs(deltaX)>Math.abs(deltaY)*1.4){
        showGalleryPhoto(wallGalleryIndex+(deltaX<0?1:-1));
      }
    },{passive:true});
    viewer.addEventListener('click',e=>{
      const action=e.target.closest('[data-wall-viewer]')?.dataset.wallViewer;
      if(action==='close')closeViewer();
      if(action==='prev')showGalleryPhoto(wallGalleryIndex-1);
      if(action==='next')showGalleryPhoto(wallGalleryIndex+1);
    });
    return viewer;
  }
  function openViewer(){
    const viewer=ensureViewer();
    viewer.hidden=false;
    viewer.innerHTML='<div class="wall-viewer-top"><span class="wall-viewer-counter"></span>'+
      '<button class="wall-viewer-close" type="button" data-wall-viewer="close" aria-label="Закрыть">'+icon('x')+'</button></div>'+
      '<button class="wall-viewer-arrow prev" type="button" data-wall-viewer="prev" aria-label="Предыдущее фото" hidden>'+icon('back')+'</button>'+
      '<div class="wall-viewer-content"></div>'+
      '<button class="wall-viewer-arrow next" type="button" data-wall-viewer="next" aria-label="Следующее фото" hidden>'+icon('back')+'</button>';
  }
  async function displayViewerAsset(item,isPhoto){
    const viewer=ensureViewer(),token=++wallViewerRequest,frame=viewer.querySelector('.wall-viewer-content');
    viewer.querySelector('video')?.pause();
    if(wallViewerURL){URL.revokeObjectURL(wallViewerURL);wallViewerURL=null;}
    if(!frame)return;
    frame.innerHTML='<div class="wall-viewer-loading" role="status">'+(isPhoto?'Загружаем фотографию…':'Загружаем видео…')+'</div>';
    try{
      const url=await authorizedBlob(item.url);
      if(viewer.hidden||token!==wallViewerRequest){URL.revokeObjectURL(url);return;}
      wallViewerURL=url;
      frame.innerHTML=isPhoto?'<img alt="Фото публикации">':'<video controls playsinline preload="metadata"></video>';
      const media=frame.querySelector(isPhoto?'img':'video');
      media.src=url;
      if(!isPhoto)media.load();
    }catch(err){
      console.warn('Wall media playback failed:',err);
      if(token===wallViewerRequest&&frame.isConnected)frame.textContent='Не удалось открыть медиа';
    }
  }
  function showGalleryPhoto(next){
    if(wallGallery.length===0)return;
    wallGalleryIndex=(next+wallGallery.length)%wallGallery.length;
    const viewer=ensureViewer();
    const counter=viewer.querySelector('.wall-viewer-counter');
    if(counter)counter.textContent=(wallGalleryIndex+1)+' / '+wallGallery.length;
    for(const button of viewer.querySelectorAll('.wall-viewer-arrow')){
      button.hidden=wallGallery.length<2;
    }
    displayViewerAsset(wallGallery[wallGalleryIndex],true);
  }
  async function viewMedia(id,kind){
    const post=(state.current?.media||[]).some(m=>m.id===id)?state.current:
      state.posts.find(p=>(p.media||[]).some(m=>m.id===id));
    const items=post?.media||[];
    const item=items.find(m=>m.id===id);
    if(!item){flash('Файл не найден');return;}
    wallGallery=[];
    openViewer();
    if(kind==='video')displayViewerAsset(item,false);
    else{
      wallGallery=items.filter(m=>m.kind==='image');
      showGalleryPhoto(wallGallery.findIndex(m=>m.id===id));
    }
  }
  document.addEventListener('keydown',e=>{
    const viewer=$('#wallPhotoViewer');
    if(!viewer||viewer.hidden)return;
    if(e.key==='Escape')closeViewer();
    if(e.key==='ArrowLeft'&&wallGallery.length>1)showGalleryPhoto(wallGalleryIndex-1);
    if(e.key==='ArrowRight'&&wallGallery.length>1)showGalleryPhoto(wallGalleryIndex+1);
  });
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

  // Instant UI, eventual server confirmation, rapid-tap coalescing.
  const likeRequests=new Map();
  const asCount=n=>Math.max(0,Number(n)||0);
  const expectedCount=entry=>Math.max(0,entry.count+
    (entry.desired===entry.confirmed?0:entry.desired?1:-1));
  function paintLike(id,liked,count,animate=false){
    count=asCount(count);
    state.posts.forEach(p=>{if(p.id===id){p.liked=liked;p.likes=count;}});
    if(state.current?.id===id){state.current.liked=liked;state.current.likes=count;}
    const buttons=Array.from(document.querySelectorAll('[data-wall-action="like"][data-id="'+id+'"]'));
    for(const btn of buttons){
      const previous=btn.classList.contains('liked');
      btn.classList.toggle('liked',liked);
      btn.setAttribute('aria-pressed',String(liked));
      btn.setAttribute('aria-label',liked?'Убрать лайк':'Поставить лайк');
      const number=btn.querySelector('.wall-action-count');
      if(number){number.textContent=count?String(count):'';number.hidden=count===0;}
      if(animate&&liked&&!previous){
        btn.classList.remove('wall-liked-pop');
        void btn.offsetWidth;
        btn.classList.add('wall-liked-pop');
        btn.addEventListener('animationend',()=>btn.classList.remove('wall-liked-pop'),{once:true});
      }
    }
  }
  async function syncLike(id,entry){
    if(entry.inflight)return;
    entry.inflight=true;
    try{
      while(entry.desired!==entry.confirmed){
        const answer=await api('/api/miniapp/wall/'+id+'/like','POST',{liked:entry.desired});
        entry.confirmed=Boolean(answer.liked);
        entry.count=asCount(answer.likes);
        paintLike(id,entry.desired,expectedCount(entry));
      }
    }catch(err){
      entry.desired=entry.confirmed;
      paintLike(id,entry.confirmed,entry.count);
      console.warn('Failed to save Wall like:',err);
      flash('Не удалось сохранить лайк');
    }finally{
      entry.inflight=false;
      if(likeRequests.get(id)===entry)likeRequests.delete(id);
    }
  }
  function toggleLike(id){
    let entry=likeRequests.get(id);
    if(!entry){
      const post=state.posts.find(p=>p.id===id)||
        (state.current?.id===id?state.current:null);
      if(!post)return;
      entry={confirmed:Boolean(post.liked),desired:Boolean(post.liked),
        count:asCount(post.likes),inflight:false};
      likeRequests.set(id,entry);
    }
    entry.desired=!entry.desired;
    paintLike(id,entry.desired,expectedCount(entry),true);
    try{tg?.HapticFeedback?.impactOccurred('light')}catch(_){}
    return syncLike(id,entry);
  }
  function applyPendingLike(post){
    const pending=likeRequests.get(post.id);
    if(pending){post.liked=pending.desired;post.likes=expectedCount(pending);}
    return post;
  }

  function postHtml(p,detail=false){
    return `<article class="wall-post" data-wall-post="${p.id}">
      <header class="wall-post-head">
        ${wallAvatar()}
        <div class="wall-post-meta"><strong>${esc(p.nick||'Аноним')}</strong><small>${time(p.created_at)}${p.updated_at>p.created_at?' · изменён':''}</small></div>
        <button class="wall-icon-btn" data-wall-action="menu" data-id="${p.id}" aria-label="Меню публикации">${icon('menu')}</button>
      </header>
      ${p.title?'<h2 class="wall-post-title">'+esc(p.title)+'</h2>':''}
      ${p.body?'<div class="wall-post-body">'+esc(p.body)+'</div>':''}
      ${mediaHtml(p.media||[])}
      <footer class="wall-post-actions">
        <button type="button" class="wall-action wall-action-like ${p.liked?'liked':''}" data-wall-action="like" data-id="${p.id}" aria-label="${p.liked?'Убрать лайк':'Поставить лайк'}" aria-pressed="${Boolean(p.liked)}">${icon('heart')}<span class="wall-action-count" ${p.likes?"":'hidden'}>${p.likes||''}</span></button>
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
      state.posts=more?state.posts.concat((data.items||[]).map(applyPendingLike)):(data.items||[]).map(applyPendingLike);
      state.offset=data.offset;state.more=Boolean(data.more);state.isAdmin=Boolean(data.is_admin);
      $('#wallModeration').hidden=!state.isAdmin;
      $('#wallCopyLink').hidden=!state.isAdmin;
      box.innerHTML=state.posts.length?state.posts.map(p=>postHtml(p)).join(''):`<div class="wall-empty">${icon('comment')}<strong>Здесь пока тихо</strong><p>Стань первым, кто начнёт обсуждение.</p></div>`;
      $('#wallMore').hidden=!state.more;
      hydrateMedia(box);
    }catch(err){if(!more)box.innerHTML='<div class="wall-empty">Не удалось загрузить стену</div>';flash(err.message)}
    finally{state.busy=false;}
  }
  function sheet(title,html){
    const opening=overlay.hidden;
    overlay.hidden=false;overlay.innerHTML=`<div class="wall-sheet ${opening?'wall-sheet-enter':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">${html}</div>`;
    document.body.classList.add('wall-sheet-open');overlay.scrollTop=0;syncWallViewport();
  }
  function header(title){
    return `<header class="wall-sheet-header"><span></span><strong>${esc(title)}</strong><button class="wall-icon-btn" data-wall-close aria-label="Закрыть">${icon('x')}</button></header>`;
  }
  function close(){
    if(draft){draft.items.forEach(m=>m.localUrl&&URL.revokeObjectURL(m.localUrl));draft=null}
    closeActionSheet();
    ++ticket;overlay.hidden=true;overlay.innerHTML='';state.reply=null;
    document.body.classList.remove('wall-sheet-open');
    overlay.style.removeProperty('--wall-viewport-height');
    overlay.style.removeProperty('--wall-viewport-top');
  }

  function closeActionSheet(){
    const layer=$('#wallActionLayer');
    if(!layer)return;
    layer.classList.add('closing');
    setTimeout(()=>layer.remove(),160);
  }
  function actionSheet(title,subtitle,buttons){
    $('#wallActionLayer')?.remove();
    const layer=document.createElement('div');
    layer.id='wallActionLayer';layer.className='wall-action-layer';
    layer.innerHTML=`<button type="button" class="wall-action-backdrop" data-wall-action-close aria-label="Закрыть"></button>
      <section class="wall-action-sheet" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="wall-action-group"><div class="wall-action-heading"><strong>${esc(title)}</strong>${subtitle?'<small>'+esc(subtitle)+'</small>':''}</div>
        ${buttons}</div>
        <button type="button" class="wall-action-cancel" data-wall-action-close>Отмена</button>
      </section>`;
    document.body.append(layer);
    try{tg?.HapticFeedback?.selectionChanged()}catch(_){}
    layer.addEventListener('click',e=>{
      if(e.target.closest('[data-wall-action-close]')){closeActionSheet();return;}
      const button=e.target.closest('[data-wall-action]');
      if(!button)return;
      e.preventDefault();closeActionSheet();handle(button);
    });
  }
  function confirmAction(title,message,action,id,extra=''){
    const glyph=action==='hide'?'shield':'trash';
    actionSheet(title,message,`<button type="button" class="wall-action-cell danger" data-wall-action="${action}" data-id="${id}" ${extra}>${icon(glyph)}<span>Подтвердить</span></button>`);
  }
  function compose(post=null){
  state.current=post||null;
  draft={items:[...(post?.media||[])],uploading:0,clientKey:uuid()};
  const title=post?'Редактировать':'Новая публикация';
  sheet(title,header(title)+`<form class="wall-compose" id="wallPostForm">
    <div class="wall-compose-user">${wallAvatar()}<div><strong>${esc($('[data-nick]')?.textContent||'Аноним')}</strong><small>Автор публикации</small></div></div>
    <input class="wall-title-input" id="wallPostTitle" maxlength="100" placeholder="Заголовок темы (необязательно)" value="${esc(post?.title||'')}">
    <textarea id="wallPostText" maxlength="1000" placeholder="Что нового? Напиши что-нибудь…">${esc(post?.body||'')}</textarea>
    <label class="wall-privacy-row"><span><b>Показывать мой ник</b><small>Если выключить, все увидят «Аноним»</small></span><input type="checkbox" id="wallShowNick" ${post?.show_nick===false?'':'checked'}><i aria-hidden="true"></i></label>
    <div class="wall-media-preview" id="wallMediaPreview"></div>
    <input type="file" id="wallFileInput" accept="image/jpeg,image/png,image/webp,video/mp4" multiple hidden>
    <div class="wall-compose-foot">
      <div class="wall-compose-tools"><button type="button" id="wallAttach" class="wall-attach" aria-label="Прикрепить фото или видео">${icon('image')}</button>
      <small id="wallCount"></small></div>
      <button class="wall-publish" type="submit">${post?'Сохранить':'Опубликовать'}</button>
    </div></form>`);
  const input=$('#wallPostText'),titleInput=$('#wallPostTitle'),counter=$('#wallCount'),submit=$('.wall-publish');
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
        title:titleInput.value.trim(),body:text,show_nick:$('#wallShowNick').checked,
        media_ids:ids,client_key:draft.clientKey
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
          ${wallAvatar()}
          <div class="wall-comment-main"><div class="wall-comment-top"><strong>${esc(c.nick)}</strong>${c.is_author?'<b class="wall-author-label">Автор</b>':''}<small>${time(c.created_at)}</small></div>
          <p>${esc(c.body)}</p><div class="wall-comment-opts">
          <button data-wall-action="reply" data-comment="${c.id}" data-nick="${esc(c.nick)}">Ответить</button>
          <button data-wall-action="${c.mine?'delete-comment':'report-comment'}" data-comment="${c.id}">${c.mine?'Удалить':'Пожаловаться'}</button></div></div></article>`;
        walk(c.id,Math.min(depth+1,2));
      }
    }walk(0,0);
    return html;
  }
  async function openPost(id,{scrollToReplies=false}={}){
    id=Number(id);if(!Number.isInteger(id)||id<1)return;
    const current=++ticket;state.reply=null;
    sheet('Обсуждение',header('Обсуждение')+'<div class="wall-loading">Загружаем комментарии…</div>');
    try{
      const data=await api('/api/miniapp/wall/'+id);if(current!==ticket)return;
      state.current=applyPendingLike(data.post);state.isAdmin=Boolean(data.is_admin);
      $('#wallCopyLink').hidden=!state.isAdmin;
      $('.wall-sheet',overlay).innerHTML=`${header('Обсуждение')}<div class="wall-detail-scroll">
        ${postHtml(state.current,true)}<div class="wall-comments-title"><strong>Ответы</strong><span>${data.comments.length}</span></div>
        ${commentsHtml(data.comments)}${data.truncated?'<div class="wall-note">Показаны первые 500 ответов.</div>':''}</div>
        <form id="wallCommentForm" class="wall-comment-form" novalidate>
          <div id="wallReplyTo" hidden></div>
          <div class="wall-comment-row"><textarea id="wallCommentText" rows="1" maxlength="500" placeholder="Написать ответ…"></textarea>
          <button class="wall-send" type="submit" aria-label="Отправить">${icon('send')}</button></div>
        </form>`;
      hydrateMedia(overlay);
      if(scrollToReplies){
        const scroller=$('.wall-detail-scroll',overlay);
        requestAnimationFrame(()=>{if(scroller)scroller.scrollTop=scroller.scrollHeight;});
      }
      const commentKey=uuid();
      const resizeComment=()=>{
        const input=$('#wallCommentText');if(!input)return;
        input.style.height='0';input.style.height=Math.min(104,Math.max(28,input.scrollHeight))+'px';
      };
      $('#wallCommentText').addEventListener('input',resizeComment);
      resizeComment();
      $('#wallCommentForm').onsubmit=async e=>{
        e.preventDefault();const input=$('#wallCommentText'),send=$('.wall-send');if(!input.value.trim())return;
        send.disabled=true;
        try{
          await api('/api/miniapp/wall/'+id+'/comments','POST',{body:input.value.trim(),parent_id:state.reply?.id||null,client_key:commentKey});
          try{tg?.HapticFeedback?.notificationOccurred('success')}catch(_){}
          await openPost(id,{scrollToReplies:true});feed();
        }catch(err){flash(err.message);send.disabled=false}
      };
    }catch(err){if(current===ticket)$('.wall-sheet',overlay).innerHTML=header('Обсуждение')+'<div class="wall-empty">'+esc(err.message)+'</div>';}
  }
  function reply(id,nick){
    state.reply={id,nick};const target=$('#wallReplyTo');if(!target)return;
    target.hidden=false;target.innerHTML=`<span>Ответ для <b>${esc(nick)}</b></span><button data-wall-action="cancel-reply" aria-label="Отменить">${icon('x')}</button>`;
    try{tg?.HapticFeedback?.selectionChanged()}catch(_){}
    const input=$('#wallCommentText');
    if(input){
      try{input.focus({preventScroll:true})}catch(_){input.focus()}
      requestAnimationFrame(syncWallViewport);
    }
  }
  async function share(id){
    const post=state.current?.id===id?state.current:state.posts.find(p=>p.id===id);
    const heading='Пост №'+id+' · Стена АНОН МГН';
    const quoted=[post?.title?.trim(),post?.body?.trim()].filter(Boolean).join('\n')||'Публикация с фото';
    const summary=heading+'\n\n❝ '+quoted.slice(0,850)+' ❞';
    try{tg?.HapticFeedback?.impactOccurred('soft')}catch(_){}
    // Native Telegram sends the attached photo + numbered blockquote + one post button.
    if(typeof tg?.shareMessage==='function'){
      try{
        const saved=await api('/api/miniapp/wall/'+id+'/share','POST',{});
        if(saved.prepared_id){
          tg.shareMessage(saved.prepared_id,ok=>{
            if(ok===false)flash('Публикация не отправлена');
          });
          return;
        }
      }catch(err){console.warn('Native Wall share unavailable:',err)}
    }
    // OS share sheets cannot attach Telegram inline buttons, but don't leak raw URLs.
    if(typeof navigator.share==='function'){
      try{
        const payload={title:'АНОН МГН · Стена',text:summary};
        if(typeof File!=='undefined'&&typeof navigator.canShare==='function'){
          try{
            const shareData=await api('/api/miniapp/wall/'+id+'/share-details','POST',{});
            const response=await fetch(shareData.preview_url,{cache:'no-store'});
            if(response.ok){
              const file=new File([await response.blob()],'anon-mgn-'+id+'.jpg',{type:'image/jpeg'});
              if(navigator.canShare({files:[file]}))payload.files=[file];
            }
          }catch(_){}
        }
        await navigator.share(payload);
        return;
      }catch(err){if(err?.name==='AbortError')return}
    }
    if(typeof tg?.showAlert==='function'){
      tg.showAlert('Чтобы отправить пост с фотографией и кнопкой, обнови Telegram.');
      return;
    }
    try{await navigator.clipboard.writeText(summary);flash('Текст публикации скопирован')}
    catch(_){flash('Не удалось поделиться публикацией')}
  }
  function menu(id){
    const p=state.current?.id===id?state.current:state.posts.find(x=>x.id===id);
    if(!p)return;state.current=p;
    const actions=p.mine?`<button class="wall-action-cell" data-wall-action="edit" data-id="${id}">${icon('edit')}<span>Редактировать</span></button>
      <button class="wall-action-cell danger" data-wall-action="ask-delete" data-id="${id}">${icon('trash')}<span>Удалить публикацию</span></button>`:
      `<button class="wall-action-cell" data-wall-action="report" data-id="${id}">${icon('shield')}<span>Пожаловаться</span></button>`;
    actionSheet('Публикация','Выберите действие',actions+(state.isAdmin?`<button type="button" class="wall-action-cell" data-wall-action="copy-link" data-id="${id}">${icon('share')}<span>Скопировать ссылку</span></button>`:'')+(state.isAdmin?`<button class="wall-action-cell danger" data-wall-action="ask-hide" data-id="${id}">${icon('shield')}<span>Скрыть как модератор</span></button>`:''));
  }
  function reportMenu(type,id){
    actionSheet('Причина жалобы','Автор жалобы не показывается пользователю',[
      ['Спам или реклама','Спам или реклама'],
      ['Оскорбления или травля','Оскорбления или травля'],
      ['Личные данные','Публикация личных данных'],
      ['Другое нарушение','Нарушение правил'],
    ].map(([label,reason])=>`<button class="wall-action-cell" data-wall-action="submit-report" data-kind="${type}" data-id="${id}" data-reason="${esc(reason)}"><span>${esc(label)}</span></button>`).join(''));
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
    if(action==='copy-link')return copyWallLink(id);
    if(action==='menu')return menu(id);
    if(action==='reply')return reply(Number(el.dataset.comment),el.dataset.nick);
    if(action==='cancel-reply'){state.reply=null;$('#wallReplyTo').hidden=true;return;}
    if(action==='edit')return compose(state.current);
    if(action==='like')return toggleLike(id);
    if(action==='ask-delete')return confirmAction('Удалить публикацию?','Вернуть её после удаления не получится.','delete',id);
    if(action==='delete'){
      try{await api('/api/miniapp/wall/'+id+'/delete','POST',{});close();flash('Удалено');feed()}
      catch(err){flash(err.message)}return;
    }
    if(action==='delete-comment')return confirmAction('Удалить комментарий?','Он исчезнет из обсуждения.','confirm-delete-comment',Number(el.dataset.comment));
    if(action==='confirm-delete-comment'){
      try{await api('/api/miniapp/wall/comments/'+id+'/delete','POST',{});openPost(state.current.id);feed()}
      catch(err){flash(err.message)}return;
    }
    if(action==='report'||action==='report-comment'){
      return reportMenu(action==='report'?'post':'comment',action==='report'?id:Number(el.dataset.comment));
    }
    if(action==='submit-report'){
      try{
        await api('/api/miniapp/wall/report','POST',{type:el.dataset.kind,id,reason:el.dataset.reason||'Нарушение правил'});
        try{tg?.HapticFeedback?.notificationOccurred('success')}catch(_){}
        flash('Жалоба отправлена');
      }catch(err){flash(err.message)}return;
    }
    if(action==='ask-hide')return confirmAction('Скрыть публикацию?','Она сразу пропадёт со стены для всех пользователей.','hide',id);
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
  $('#wallCopyLink').onclick=()=>copyWallLink();
  $('#wallMore').onclick=()=>feed(true);
  $('#wallModeration').onclick=moderation;
  $$('[data-wall-sort]',root).forEach(b=>b.onclick=()=>{
    if(state.mode===b.dataset.wallSort)return;
    state.mode=b.dataset.wallSort;
    $$('[data-wall-sort]',root).forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-selected',x===b?'true':'false')});
    feed();
  });
  function closeTop(){if($('#wallActionLayer'))closeActionSheet();else close()}
  window.AnonWall={onPage(page){if(page==='wall')feed()},openPost,makeLink:link,copyLink:copyWallLink,close:closeTop,isOpen(){return Boolean($('#wallActionLayer'))||!overlay.hidden}};
})();
