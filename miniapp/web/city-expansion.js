/* РАЙОНЫ · Inventory, warehouses, premium pets and map chests.
   All real changes occur through server-authenticated endpoints. No fake actions. */
(function(root) {
  'use strict';
  const $=id=>document.getElementById(id);
  const make=(tag,klass,content)=>{
    const el=document.createElement(tag);
    if(klass)el.className=klass;
    if(content!==undefined)el.textContent=String(content);
    return el;
  };
  const RARITY={common:'Обычный',uncommon:'Необычный',rare:'Редкий',
    epic:'Эпический',legendary:'Легендарный'};
  const fmt=value=>Number(value||0).toLocaleString('ru-RU');
  const hp=value=>fmt(value)+' HP / 5 мин';
  function mount(ctx) {
    const {state,api,load,feedback,switchTab,chooseZone,petAction,locate,insidePolygon}=ctx;
    const inv=$('districtInventory'), content=$('inventoryContent');
    const warehouse=$('districtWarehouses'), whBody=$('warehouseContent');
    const detail=$('petDetails'),detailBody=$('petDetailsBody');
    let filter='pets',selectedPet=null,busy=false,drawnChests=[],chestLayer=null,lastData={};
    const pets=()=>state.inventoryPets||[];
    const items=()=>state.items||[];
    const catalog=()=>state.premiumCatalog||[];
    const btn=(label,action,dataset={})=>{
      const b=make('button','district-button',label);b.type='button';
      b.dataset.action=action;Object.assign(b.dataset,dataset);return b;
    };
    const actionInfo=(title,text)=>{
      const node=make('div','district-empty');
      node.append(make('strong','',title),make('p','',text));return node;
    };
    async function send(url,payload={},resultText='Готово') {
      if(busy)return;
      busy=true;
      try{
        const result=await api(url,{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload)
        });
        await load();
        if(resultText)feedback(resultText==='RESULT'?result.description:resultText,'success');
        return result;
      }catch(e){
        feedback(e.message||'Не удалось выполнить действие','error');
      }finally{busy=false;render();}
    }
    function inventoryCard(p) {
      const row=make('button','district-inventory-row');
      row.type='button';row.dataset.petId=String(p.id);
      const icon=make('span','district-emoji',p.emoji);
      const desc=make('span','district-text');
      desc.append(make('strong','',p.name+' · Ур. '+p.level),
        make('small','',(RARITY[p.rarity]||p.rarity)+' · '+(p.zone_id?
            (state.zones.find(z=>z.id===p.zone_id)?.name||'Защищает район'):
            'В инвентаре')));
      const arrow=make('span','district-arrow','›');
      row.append(icon,desc,arrow);return row;
    }
    function renderInventory(){
      $('invTotal').textContent=pets().length+' питомцев';
      $('inventoryTabs').querySelectorAll('button').forEach(b=>{
        b.classList.toggle('active',b.dataset.invFilter===filter);
      });
      content.replaceChildren();
      const picked=pets().filter(p=>{
        if(filter==='pets')return true;
        if(filter==='defense')return Boolean(p.zone_id);
        if(filter==='rare')return ['rare','epic','legendary'].includes(p.rarity);
        return false;
      });
      if(filter==='items'){
        if(!items().length){content.append(actionInfo('Предметов пока нет',
          'Ищи на карте сундуки 📦 и получай щиты, аптечки и усиления.'));return}
        for(const i of items()){
          const row=make('div','district-inventory-row');
          const text=make('span','district-text');
          text.append(make('strong','',i.emoji+' '+i.name+' · '+i.quantity+' шт.'),
            make('small','',i.description));
          const use=btn('Применить','use-item',{kind:i.kind});
          row.append(text,use);content.append(row);
        }
      }else{
        if(!picked.length)content.append(actionInfo('Пока пусто',
          filter==='defense'?'Установи питомца на свой район':
          filter==='rare'?'Редких питомцев можно купить или найти в сундуке':
          'Купи питомца в маркете или найди в сундуке'));
        for(const p of picked)content.append(inventoryCard(p));
      }
    }
    function renderDetail(){
      const p=pets().find(p=>p.id===selectedPet);
      if(!p){detail.hidden=true;return}
      detail.hidden=false;detailBody.replaceChildren();
      const em=make('div','district-detail-emoji',p.emoji);
      const title=make('h2','',p.name+' · Ур. '+p.level);
      const rar=make('div','district-detail-rarity',RARITY[p.rarity]||p.rarity);
      const stats=make('div','district-detail-stats');
      const zone=state.zones.find(z=>z.id===p.zone_id);
      const rows=[
        ['Урон','−'+hp(p.hp_5m)],['Доход','+'+fmt(p.stars_h)+' ⭐/ч'],
        ['Защита',p.pet_hp+'/100'],
        ['Район',p.zone_id?(zone?.name||'Захваченный квартал'):'В инвентаре'],
        ['Статус',p.zone_id?'Защищает территорию':'В запасе']
      ];
      for(const [k,v] of rows){
        const row=make('div','district-stat-row');
        row.append(make('span','',k),make('strong','',v));stats.append(row);
      }
      const actions=make('div','district-detail-actions');
      if(p.zone_id){
        actions.append(btn('Вернуть в инвентарь','recall',{petId:p.id}));
      }else{
        const owned=state.zones.filter(z=>z.mine);
        if(owned.length){
          const select=make('select','district-zone-select');
          select.id='petTargetZone';select.setAttribute('aria-label','Район для питомца');
          for(const z of owned){
            const option=make('option','',z.name);
            option.value=String(z.id);
            if(z.id===state.selectedId)option.selected=true;
            select.append(option);
          }
          actions.append(make('label','district-help','Выбери свой район'),select);
        }else{
          actions.append(make('p','district-help','Сначала захвати район на карте.'));
        }
        const place=btn('Установить на район','place',{petId:p.id});
        place.disabled=!owned.length;
        actions.append(place);
      }
      if(p.next_stats && p.upgrade_cost!=null){
        const next=p.next_stats;
        const preview=make('section','district-upgrade-preview');
        preview.append(make('strong','district-upgrade-heading','Улучшение · БЫЛО → СТАЛО'));
        for(const [caption,before,after] of [
          ['Уровень',p.level,next.level],
          ['Урон','−'+hp(p.hp_5m),'−'+hp(next.hp_5m)],
          ['Доход','+'+fmt(p.stars_h)+' ⭐/ч','+'+fmt(next.stars_h)+' ⭐/ч']
        ]){
          const row=make('div','district-upgrade-line');
          row.append(make('span','',caption),make('small','',String(before)),
            make('span','district-upgrade-arrow','→'),make('strong','',String(after)));
          preview.append(row);
        }
        actions.append(preview);
      }
      const upgrade=btn(p.upgrade_cost==null?'Максимальный уровень':
        'Улучшить · '+fmt(p.upgrade_cost)+' ⭐','upgrade',{petId:p.id});
      upgrade.disabled=p.upgrade_cost==null||state.wallet<p.upgrade_cost;
      actions.append(upgrade);
      detailBody.append(em,title,rar,stats,actions,
        make('p','district-help',
          'Улучшения и питомцы сохраняются после смерти. Все характеристики рассчитывает сервер.'));
    }
    function renderPremium(){
      const list=$('premiumCatalog');if(!list)return;
      list.replaceChildren();
      for(const p of catalog()){
        const row=make('div','pet-product');
        const icon=make('span','pet-product-emoji',p.emoji);
        const info=make('div','pet-product-info');
        info.append(make('strong','',p.name+' · '+(RARITY[p.rarity]||p.rarity)),
          make('small','',
            'Доход: +'+fmt(p.stars_h)+' ⭐/ч · Урон: −'+hp(p.hp_5m)));
        const box=make('div','pet-product-price');
        const buy=btn('Оплатить','premium',{kind:p.kind});
        box.append(make('small','',fmt(p.xtr)+' Telegram Stars'),buy);
        row.append(icon,info,box);list.append(row);
      }
    }
    function renderWarehouses(){
      const info=state.warehouse;
      whBody.replaceChildren();
      const invites=state.invitations||[];
      if(invites.length){
        whBody.append(make('h3','district-heading','Приглашения'));
        for(const invite of invites){
          const row=make('div','district-invite');
          const label=make('div','district-text');
          label.append(make('strong','',invite.emoji+' '+invite.warehouse),
            make('small','','Пригласил '+invite.inviter));
          const accept=btn('Принять','invite-response',{id:invite.id,accept:'true'});
          const decline=btn('Нет','invite-response',{id:invite.id,accept:'false'});
          row.append(label,accept,decline);whBody.append(row);
        }
      }
      if(!info){
        const form=make('form','district-form');
        form.id='warehouseCreate';
        form.append(make('p','district-help',
          'Создай свой склад, пригласи друзей по нику и объединяйте районы.'));
        const name=make('input');name.name='name';name.placeholder='Название склада';name.maxLength=28;name.required=true;name.minLength=3;
        const desc=make('input');desc.name='description';desc.placeholder='Короткое описание';desc.maxLength=140;
        const emoji=make('select');emoji.name='emoji';
        ['📦','🏚️','🏠','🏭','🛡️','🏴','👑','⚡'].forEach(x=>{
          const op=make('option','',x);op.value=x;emoji.append(op);
        });
        const button=make('button','district-button primary','Создать склад');button.type='submit';
        form.append(name,desc,emoji,button);whBody.append(form);
        return;
      }
      const head=make('div','district-warehouse-head');
      head.append(make('div','district-warehouse-emoji',info.emoji));
      const ht=make('div');
      ht.append(make('h3','',info.name),make('p','',info.description));
      head.append(ht);whBody.append(head);
      const metrics=make('div','district-warehouse-metrics');
      [['Участники',info.members.length+'/10'],['Уровень',info.level],
       ['Районы',info.zones],['Доход','+'+info.income_h+' ⭐/ч']].forEach(([k,v])=>{
         const div=make('div');div.append(make('small','',k),make('strong','',v));metrics.append(div)
       });
      whBody.append(metrics,make('h3','district-heading','Участники'));
      for(const member of info.members){
        const row=make('div','district-member');
        const d=make('span','district-text');
        d.append(make('strong','',member.nickname),
          make('small','',(member.role==='owner'?'Владелец':member.role==='moderator'?'Модератор':'Участник')+
            ' · '+member.zones+' районов'));
        row.append(d);
        if(info.mine&&member.id!==info.owner_id){
          const isMod=member.role==='moderator';
          row.append(btn(isMod?'Снять модератора':'Модератор','warehouse-role',{
            uid:member.id,role:isMod?'member':'moderator'
          }));
          row.append(btn('Исключить','warehouse-kick',{uid:member.id}));
        }
        whBody.append(row);
      }
      if(info.mine||info.my_role==='moderator'){
        const form=make('form','district-form');form.id='warehouseInvite';
        form.append(make('h3','district-heading','Пригласить по нику'));
        const nick=make('input');nick.name='nickname';nick.placeholder='Ник из АНОН МГН';nick.required=true;nick.maxLength=40;
        const sub=make('button','district-button primary','Отправить приглашение');sub.type='submit';
        form.append(nick,sub);whBody.append(form);
        if(info.mine){
          const d=btn('Удалить склад','warehouse-disband');d.classList.add('muted');
          whBody.append(d);
        }
      }else{
        whBody.append(btn('Покинуть склад','warehouse-leave'));
      }
      whBody.append(make('h3','district-heading','Совместные задания'));
      for(const mission of info.missions||[]){
        const row=make('div','district-invite');
        const label=make('span','district-text');
        label.append(make('strong','',mission.label),
          make('small','',mission.progress+'/'+mission.target+
            ' захватов · награда +'+mission.reward+' игровых ⭐'));
        row.append(label);
        const collect=btn(mission.claimed?'Получено':
          mission.claimable?'Забрать':'В процессе','mission-claim',{tier:mission.tier});
        collect.disabled=!mission.claimable;
        row.append(collect);whBody.append(row);
      }
      whBody.append(make('h3','district-heading','Достижения'));
      for(const a of info.achievements||[]){
        whBody.append(make('div','district-achievement',(a.done?'✅ ':'◻️ ')+a.name));
      }
    }
    function renderChests(){
      if(!state.map||!root.L)return;
      if(!chestLayer)chestLayer=root.L.layerGroup().addTo(state.map);
      chestLayer.clearLayers();
      drawnChests=[];
      const boxes=Array.isArray(state.chests)?state.chests:[];
      for(const chest of boxes){
        if(chest.opened)continue;
        const marker=root.L.marker([chest.lat,chest.lon],{
          title:'Сундук · '+chest.place,zIndexOffset:1600,
          icon:root.L.divIcon({
            className:'district-chest-icon',
            html:'<span aria-hidden="true">'+chest.emoji+'</span>',
            iconSize:[33,33],iconAnchor:[16,16]
          })
        }).addTo(chestLayer);
        marker.on('click',()=>openChest(chest));
        drawnChests.push(marker);
      }
    }
    async function openChest(chest){
      if(busy)return;
      const answer=root.confirm?.(
        chest.emoji+' Сундук · '+chest.place+'\n\n'
          +'Для открытия нужно находиться рядом по GPS. Открыть?');
      if(answer===false)return;
      try{
        const gps=await locate(false);
        await send('/api/city/chests/open',{
          id:chest.id,lat:gps.lat,lon:gps.lon,accuracy_m:gps.accuracy,
          timestamp_s:gps.timestamp/1000
        },'RESULT');
      }catch(e){feedback(e.message,'error')}
    }
    function render(data){
      if (data) lastData=data;
      data=lastData;
      state.inventoryPets=Array.isArray(data.inventory_pets)?data.inventory_pets:[];
      state.items=Array.isArray(data.items)?data.items:[];
      state.effects=Array.isArray(data.effects)?data.effects:[];
      state.premiumCatalog=Array.isArray(data.premium_catalog)?data.premium_catalog:[];
      state.chests=Array.isArray(data.chests)?data.chests:[];
      state.warehouse=data.warehouse||null;
      state.invitations=data.invitations||[];
      renderInventory();renderPremium();renderWarehouses();renderChests();
      if(!detail.hidden)renderDetail();
    }
    $('inventoryTabs').addEventListener('click',e=>{
      const b=e.target.closest('[data-inv-filter]');
      if(!b)return;filter=b.dataset.invFilter;renderInventory();
    });
    content.addEventListener('click',e=>{
      const use=e.target.closest('[data-action="use-item"]');
      if(use){
        const type=use.dataset.kind;
        const zone=state.zones.find(z=>z.id===state.selectedId&&z.mine);
        send('/api/city/items/use',{kind:type,zone_id:zone?.id},
          'Предмет применён');return;
      }
      const pet=e.target.closest('[data-pet-id]');
      if(pet){selectedPet=Number(pet.dataset.petId);renderDetail()}
    });
    $('closePetDetails').addEventListener('click',()=>{detail.hidden=true});
    detail.addEventListener('click',e=>{if(e.target===detail)detail.hidden=true});
    detailBody.addEventListener('click',async e=>{
      const b=e.target.closest('[data-action]');if(!b)return;
      const action=b.dataset.action,id=Number(b.dataset.petId);
      if(action==='upgrade'){
        const p=pets().find(x=>x.id===id);
        if(!p||p.upgrade_cost==null)return;
        const result=await send('/api/city/pets/upgrade',{pet_id:id},'Питомец улучшен');
        if(result?.after) {
          renderDetail();
          const report=make('div','district-upgrade-done');
          report.append(make('strong','','Улучшение выполнено'),
            make('p','',result.before.level+' → '+result.after.level+
              ' уровень · −'+hp(result.before.hp_5m)+' → −'+hp(result.after.hp_5m)));
          detailBody.prepend(report);
        }
      }else if(action==='place'||action==='recall'){
        const zoneId=action==='place'?Number($('petTargetZone')?.value):state.selectedId;
        if(action==='place'&&(!zoneId||!state.zones.some(z=>z.id===zoneId&&z.mine)))return;
        await petAction(action,{pet_id:id,zone_id:zoneId});
        detail.hidden=true;
      }
    });
    $('premiumCatalog').addEventListener('click',e=>{
      const b=e.target.closest('[data-action="premium"]');
      if(!b)return;
      const pet=catalog().find(p=>p.kind===b.dataset.kind);
      if(!pet)return;
      if(!root.confirm('Покупка '+pet.emoji+' за '+pet.xtr+
        ' настоящих Telegram Stars. Продолжить?'))return;
      send('/api/city/premium/invoice',{kind:pet.kind},
        'Счёт отправлен в Telegram-бот. Питомец появится после оплаты.');
    });
    whBody.addEventListener('submit',e=>{
      e.preventDefault();
      const form=e.target;
      if(form.id==='warehouseCreate'){
        send('/api/city/warehouse/create',{
          name:form.elements.name.value,
          emoji:form.elements.emoji.value,
          description:form.elements.description.value
        },'Склад создан');
      }
      if(form.id==='warehouseInvite'){
        send('/api/city/warehouse/invite',{
          nickname:form.elements.nickname.value
        },'Приглашение записано. Проверь Telegram.');
      }
    });
    whBody.addEventListener('click',e=>{
      const b=e.target.closest('[data-action]');if(!b)return;
      const act=b.dataset.action;
      if(act==='invite-response')send('/api/city/warehouse/respond',{
        id:Number(b.dataset.id),accept:b.dataset.accept==='true'
      },'Приглашение обработано');
      if(act==='warehouse-role')send('/api/city/warehouse/role',{
        user_id:Number(b.dataset.uid),role:b.dataset.role
      },'Роль участника изменена');
      if(act==='warehouse-kick' && root.confirm('Исключить игрока из склада?'))
        send('/api/city/warehouse/kick',{user_id:Number(b.dataset.uid)},'Игрок исключён');
      if(act==='warehouse-leave'&&root.confirm('Покинуть склад?'))
        send('/api/city/warehouse/leave',{},'Ты вышел со склада');
      if(act==='mission-claim')
        send('/api/city/warehouse/missions/claim',{tier:Number(b.dataset.tier)},
          'Награда за совместное задание получена');
      if(act==='warehouse-disband'&&root.confirm('Удалить склад навсегда?'))
        send('/api/city/warehouse/disband',{confirm:'УДАЛИТЬ СКЛАД'},'Склад удалён');
    });
    $('districtMore').addEventListener('click',e=>{
      const b=e.target.closest('[data-more-page]');
      if(!b)return;
      const key=b.dataset.morePage;
      if(key==='warehouses')renderWarehouses();
      switchTab(key);
    });
    return {render,renderInventory,renderWarehouses,renderChests,openChest};
  }
  root.RaionyExpansion={mount};
})(window);
