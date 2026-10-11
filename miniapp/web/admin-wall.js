(function wallAdminModule(){
  'use strict';
  const tg=window.Telegram?.WebApp;
  const base=(window.ANON_MGN_API_BASE||document.querySelector('meta[name="api-base"]')?.content||'').replace(/\/$/,'');
  const state={tab:'posts',filter:'all',q:'',page:0,post:0};
  let canSeeUsers=false;
  const esc=s=>String(s??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const date=ts=>new Date(Number(ts||0)*1000).toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
  const icon=(name)=>{
    const paths={
      heart:'<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78Z"/>',
      comments:'<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
      hide:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
      trash:'<path d="M4 7h16M9 4h6M6 7l1 14h10l1-14M10 11v6m4-6v6"/>',
      arrow:'<path d="m15 18-6-6 6-6"/>',
      play:'<path d="m8 5 12 7-12 7V5Z"/>'
    };
    return '<svg class="admin-wall-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(paths[name]||paths.comments)+'</svg>';
  };
  const page=()=>document.querySelector('#adminCenter #adminContent');
  async function api(path,method='GET',payload){
    const resp=await fetch(base+'/api/miniapp/wall/admin'+path,{
      method,headers:{'X-Telegram-Init-Data':tg?.initData||'',...(payload!==undefined?{'Content-Type':'application/json'}:{})},
      body:payload===undefined?undefined:JSON.stringify(payload),cache:'no-store'
    });
    const json=await resp.json().catch(()=>({}));
    if(!resp.ok)throw Error(json.message||'Не удалось загрузить данные стены');
    return json;
  }
  const metrics=(name,value)=>`<div class="admin-stat"><small>${name}</small><strong>${value}</strong></div>`;
  const mediaHtml=list=>(list||[]).length?'<div class="admin-wall-grid">'+list.map(m=>
    `<button type="button" class="admin-wall-asset" data-wa="viewmedia" data-url="${esc(m.url)}">${m.kind==='video'?
      '<span class="admin-wall-video">'+icon('play')+'Видео</span><img data-wall-admin-thumb="'+esc(m.poster||'')+'" alt="Превью видео">':
      '<img data-wall-admin-thumb="'+esc(m.poster||m.url)+'" alt="Фото публикации">'}</button>`
  ).join('')+'</div>':'';
  function actions(kind,id,hidden){
    const normal=hidden===0?'<button type="button" data-wa="act" data-kind="'+kind+'" data-id="'+id+'" data-op="hide">'+icon('hide')+'Скрыть</button>':
      '<button type="button" data-wa="act" data-kind="'+kind+'" data-id="'+id+'" data-op="restore">'+icon('hide')+'Восстановить</button>';
    return '<div class="admin-wall-actions">'+normal+
      '<button type="button" class="danger" data-wa="act" data-kind="'+kind+'" data-id="'+id+'" data-op="delete">'+icon('trash')+'Удалить</button></div>';
  }
  async function loadImages(){
    for(const img of page()?.querySelectorAll('[data-wall-admin-thumb]')||[]){
      if(!img.dataset.wallAdminThumb||img.dataset.done)continue;
      img.dataset.done='1';
      try{
        const resp=await fetch(base+img.dataset.wallAdminThumb,{headers:{'X-Telegram-Init-Data':tg?.initData||''}});
        if(resp.ok){
          const u=URL.createObjectURL(await resp.blob());
          if(img.isConnected)img.src=u;
          setTimeout(()=>URL.revokeObjectURL(u),180000);
        }
      }catch(_){}
    }
  }
  async function display(){
    const target=page();if(!target)return;
    target.innerHTML='<div class="admin-loading">Загружаем стену…</div>';
    try{
      let html;
      if(state.tab==='posts')html=await posts();
      else if(state.tab==='detail')html=await detail();
      else if(state.tab==='reports')html=await reports();
      else html=await audit();
      target.innerHTML=html;loadImages();
    }catch(e){target.innerHTML='<div class="admin-error">'+esc(e.message)+'</div>';}
  }
  async function posts(){
    const [stats,list]=await Promise.all([
      api('/overview'),api('/posts?'+new URLSearchParams({filter:state.filter,q:state.q,page:state.page}))
    ]);
    const filters=[['all','Все'],['active','Активные'],['hidden','Скрытые'],['reports','С жалобами']];
    return '<div class="admin-page-heading"><div><small>ДОСТУПНО АДМИНИСТРАЦИИ</small><h2>Стена</h2></div></div>'+
      '<section class="admin-stats">'+metrics('Публикаций',stats.total)+metrics('Сегодня',stats.today)+
      metrics('Комментариев',stats.comments)+metrics('Жалоб',stats.reports)+metrics('Авторов',stats.authors)+metrics('Скрытых',stats.hidden)+'</section>'+
      '<div class="admin-wall-links"><button data-wa="tab" data-tab="reports">Жалобы</button><button data-wa="tab" data-tab="audit">Журнал действий</button></div>'+
      '<form class="admin-wall-search" data-wa-form="search"><input name="q" placeholder="ID, ник, username или текст" value="'+esc(state.q)+'"><button type="submit">Найти</button></form>'+
      '<div class="admin-wall-filters">'+filters.map(([id,title])=>'<button class="'+(state.filter===id?'active':'')+'" data-wa="filter" data-filter="'+id+'">'+title+'</button>').join('')+'</div>'+
      (list.items.length?list.items.map(p=>`<article class="admin-wall-entry">
        <div class="admin-wall-entry-top"><strong>#${p.id} · ${esc(p.nick)}</strong><small>${date(p.created_at)}</small></div>
        <p>${esc(p.body||'Публикация с медиа')}</p>${mediaHtml(p.media)}
        <div class="admin-wall-meta">ID ${p.author_id} · ${esc(p.username?'@'+p.username:'без username')}
          · ${p.hidden===0?'Опубликован':p.hidden===1?'Скрыт':'Удалён'}</div>
        <div class="admin-wall-metrics">${icon('heart')}${p.likes} ${icon('comments')}${p.comments}</div>
        <button class="admin-wall-open" data-wa="open" data-id="${p.id}">Открыть публикацию</button>
        </article>`).join(''):'<div class="admin-empty">Публикаций не найдено</div>')+
      '<div class="admin-wall-pager">'+(state.page?'<button data-wa="prev">← Назад</button>':'')+
      '<span>Страница '+(state.page+1)+'</span>'+(list.has_more?'<button data-wa="next">Далее →</button>':'')+'</div>';
  }
  async function detail(){
    const data=await api('/posts/'+state.post),p=data.post;
    return '<div class="admin-wall-links"><button data-wa="tab" data-tab="posts">'+icon('arrow')+'К публикациям</button></div>'+
      '<article class="admin-wall-entry"><h2>Публикация #'+p.id+'</h2>'+
      '<strong>'+esc(p.nick)+'</strong><div class="admin-wall-meta">ID '+p.author_id+' · '+esc(p.username?'@'+p.username:'без username')+' · '+date(p.created_at)+'</div>'+
      '<p>'+esc(p.body||'Без текста')+'</p>'+mediaHtml(p.media)+
      (canSeeUsers?'<button class="admin-wall-open" data-action="openUser" data-value="'+p.author_id+'">Карточка автора</button>':'')+
      actions('post',p.id,p.hidden)+'</article>'+
      '<h3 class="admin-wall-subheading">Комментарии · '+data.comments.length+'</h3>'+
      (data.comments.length?data.comments.map(c=>'<article class="admin-wall-entry"><strong>'+esc(c.nick)+'</strong>'+
        '<div class="admin-wall-meta">ID '+c.author_id+' · '+esc(c.username?'@'+c.username:'без username')+' · '+date(c.created_at)+' · '+(c.hidden?'Скрыт':'Виден')+'</div>'+
        '<p>'+esc(c.body)+'</p>'+(canSeeUsers?'<button data-action="openUser" data-value="'+c.author_id+'">Карточка автора</button>':'')+
        actions('comment',c.id,c.hidden)+'</article>').join(''):
        '<div class="admin-empty">Комментариев ещё нет</div>')+
      (data.truncated?'<p>Показаны первые 500 комментариев</p>':'');
  }
  async function reports(){
    const data=await api('/reports');
    return '<div class="admin-wall-links"><button data-wa="tab" data-tab="posts">← Стена</button></div>'+
      '<h2 class="admin-wall-subheading">Жалобы · '+data.items.length+'</h2>'+
      (data.items.length?data.items.map(r=>'<article class="admin-wall-entry"><small>'+date(r.created_at)+' · Жалоба #'+r.id+'</small>'+
      '<h3>'+esc(r.reason)+'</h3><p>'+esc(r.body)+'</p><div class="admin-wall-meta">Автор ID '+r.author_id+' · Заявитель ID '+r.reporter_id+'</div>'+
      '<div class="admin-wall-actions">'+(r.post_id?'<button data-wa="open" data-id="'+r.post_id+'">Открыть контекст</button>':'')+
      '<button data-wa="act" data-kind="'+r.type+'" data-id="'+r.target_id+'" data-op="hide">Скрыть</button>'+
      '<button data-wa="act" data-kind="'+r.type+'" data-id="'+r.target_id+'" data-op="dismiss">Отклонить</button></div></article>').join(''):
      '<div class="admin-empty">Жалоб нет</div>');
  }
  async function audit(){
    const data=await api('/audit');
    return '<div class="admin-wall-links"><button data-wa="tab" data-tab="posts">← Стена</button></div>'+
      '<h2 class="admin-wall-subheading">История модерации</h2>'+
      (data.items.length?data.items.map(a=>'<div class="admin-wall-entry">'+
        '<strong>'+esc(a.action)+' · '+esc(a.target_type)+' #'+a.target_id+'</strong>'+
        '<div class="admin-wall-meta">Модератор '+a.actor_id+' · '+date(a.created_at)+'</div></div>').join(''):
        '<div class="admin-empty">Действий пока нет</div>');
  }
  document.addEventListener('click',async e=>{
    const b=e.target.closest('#adminCenter [data-wa]');if(!b)return;
    const action=b.dataset.wa;
    try{
      if(action==='tab'){state.tab=b.dataset.tab;await display()}
      else if(action==='filter'){state.filter=b.dataset.filter;state.page=0;await display()}
      else if(action==='open'){state.post=Number(b.dataset.id);state.tab='detail';await display()}
      else if(action==='next'||action==='prev'){state.page+=action==='next'?1:-1;await display()}
      else if(action==='act'){
        const kind=b.dataset.kind, id=Number(b.dataset.id),operation=b.dataset.op;
        if(!confirm((operation==='delete'?'Удалить':operation==='restore'?'Восстановить':operation==='dismiss'?'Отклонить жалобу':'Скрыть')+' материал #'+id+'?'))return;
        b.disabled=true;
        await api('/action','POST',{type:kind,id,action:operation});
        await display();
      }
      else if(action==='viewmedia'){
        const res=await fetch(base+b.dataset.url,{headers:{'X-Telegram-Init-Data':tg?.initData||''}});
        if(!res.ok)throw Error('Не удалось открыть файл');
        const blob=URL.createObjectURL(await res.blob());
        const video=res.headers.get('Content-Type')?.startsWith('video/');
        let viewer=document.querySelector('#adminWallViewer');
        if(!viewer){viewer=document.createElement('div');viewer.id='adminWallViewer';document.body.append(viewer)}
        viewer.innerHTML='<button class="admin-wall-viewer-close">×</button>'+(video?'<video controls playsinline autoplay></video>':'<img alt="Фотография">');
        viewer.hidden=false;viewer.querySelector(video?'video':'img').src=blob;
        viewer.querySelector('button').onclick=()=>{viewer.querySelector('video')?.pause();viewer.hidden=true;URL.revokeObjectURL(blob)};
      }
    }catch(err){alert(err.message||'Ошибка управления стеной');b.disabled=false}
  });
  document.addEventListener('submit',e=>{
    if(!e.target.matches('#adminCenter [data-wa-form="search"]'))return;
    e.preventDefault();state.q=String(new FormData(e.target).get('q')||'').trim().slice(0,100);
    state.tab='posts';state.page=0;display();
  });
  window.AnonWallAdmin={render(userAccess){canSeeUsers=Boolean(userAccess);state.tab='posts';return posts()},hydrate:loadImages};
})();
