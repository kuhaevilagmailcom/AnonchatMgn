/* МГН: ЗАХВАТ — map, Telegram location, capture and ranking. */
(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const tg = window.Telegram?.WebApp;
  tg?.ready();
  tg?.expand();
  try {
    tg?.setHeaderColor?.('#000000');
    tg?.setBackgroundColor?.('#000000');
  } catch (_) { /* Older Telegram clients may reject theme setters. */ }

  const CITY = [53.405, 58.983];
  const PALETTE = ['#e57ac6', '#a28aff', '#ffba80', '#70d3c9', '#f18c9b', '#b9d47b'];
  const ui = {
    panel: $('panel'), view: $('mapView'), board: $('leaderboard'), rules: $('rules'),
    market: $('market'), shop: $('petCatalog'), inventory: $('petInventory'),
    wallet: $('wallet'), hpValue: $('hpValue'), hpHud: $('hpHud'), hpFill: $('hpFill'),
    pendingStars: $('pendingStars'), petCount: $('petCount'),
    placeHint: $('placeHint'), claimIncome: $('claimIncome'), zoneGuard: $('zoneGuard'),
    count: $('count'), mine: $('mineCount'), captures: $('captureCount'),
    zone: $('zone'), owner: $('owner'), ownerCard: $('ownerCard'),
    state: $('zoneState'), details: $('zoneDetails'),
    theme: $('theme'), sheetToggle: $('sheetToggle'), status: $('status'),
    capture: $('capture'), captureLabel: $('captureLabel'),
    locate: $('locate'), refresh: $('refresh'), top: $('topbutton'),
    leaders: $('leaders'), toast: $('toast'),
    mapTab: $('showmap'), topTab: $('showtop'), marketTab: $('showmarket'), rulesTab: $('showrules')
  };

  const state = {
    zones: [], leaderboard: [], selectedId: null, gps: null, map: null,
    territoryLayers: new Map(), territoryGroup: null, markerGroup: null,
    gpsMarker: null, accuracyCircle: null, locating: false, capturing: false,
    canCapture: false, radius: 100, maxAccuracy: 75, cooldownEnd: 0,
    activeTab: 'map', toastTimer: null, hasFramed: false, expanded: false, theme: 'dark',
    baseLayer: null, basemapType: null,
    gpsWatchId: null, telegramPollId: null, gpsEnabled: false, autoCentered: false,
    roadPolygons: new Map(), roadTimer: null, roadSignature: "",
    catalog: [], myPets: [], guards: [], wallet: 0, hp: 100, pendingStars: 0,
    actionBusy: false, petGroup: null, petAgents: [], lastPresenceAt: 0,
    lastAttackedZone: null
  };

  function safeText(value, fallback = '') {
    return String(value == null ? fallback : value).slice(0, 160);
  }
  function number(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }
  function distanceM(latA, lonA, latB, lonB) {
    const dLat = (latB - latA) * Math.PI / 180;
    const dLon = (lonB - lonA) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
      Math.cos(latA * Math.PI / 180) * Math.cos(latB * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return 12742000 * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  function humanDistance(metres) {
    return metres >= 1000 ? (metres / 1000).toFixed(1).replace('.', ',') + ' км' : Math.round(metres) + ' м';
  }
  function cooldownS() {
    return Math.max(0, Math.ceil((state.cooldownEnd - Date.now()) / 1000));
  }
  function humanTime(seconds) {
    return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
  }
  function selectedZone() {
    return state.zones.find(zone => zone.id === state.selectedId) || null;
  }
  function ownerColor(zone) {
    if (zone.mine) return '#e57ac6';
    if (!zone.occupied) return '#80767d';
    // The nickname is display-only; choose a stable color without exposing user IDs.
    let hash = 0;
    const key = zone.owner_name && zone.owner_name !== 'Аноним' ? zone.owner_name : 'anon-' + zone.id;
    for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
    return PALETTE[(hash >>> 0) % PALETTE.length];
  }
  function feedback(message, kind = 'info') {
    if (!message) return;
    ui.toast.textContent = safeText(message, '');
    ui.toast.hidden = false;
    ui.toast.dataset.kind = kind;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { ui.toast.hidden = true; }, 4000);
  }
  function setStatus(message) { ui.status.textContent = message; }
  function touch(kind = 'selection') {
    try {
      if (kind === 'success') tg?.HapticFeedback?.notificationOccurred('success');
      else if (kind === 'error') tg?.HapticFeedback?.notificationOccurred('error');
      else tg?.HapticFeedback?.selectionChanged();
    } catch (_) { /* optional client feature */ }
  }

  async function api(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {
        'X-Telegram-Init-Data': tg?.initData || '',
        ...(options.headers || {})
      },
      cache: 'no-store'
    });
    if (!response.ok) {
      if (response.status === 403) throw new Error('Игра временно доступна только администраторам для тестирования.');
      if (response.status === 401) throw new Error('Открой игру через Telegram, чтобы войти.');
      const body = (await response.text()).slice(0, 250);
      throw new Error(body || 'Ошибка сервера (' + response.status + ')');
    }
    return response.json();
  }

  function renderHud(data) {
    const occupied = state.zones.filter(zone => zone.occupied).length;
    ui.count.textContent = occupied + ' / ' + state.zones.length;
    ui.mine.textContent = String(number(data.my_zones));
    ui.captures.textContent = String(number(data.total_captures));
    ui.hpHud.textContent = String(Math.ceil(state.hp));
  }
  const ZONE_ICONS = {
    mall: '<path d="M4 10h16v11H4zM3 10l2-6h14l2 6M8 10V4m8 6V4M9 21v-6h6v6"/>',
    culture: '<path d="M3 21h18M5 21V9l7-5 7 5v12M9 21v-7h6v7M7 11h.01M17 11h.01"/>',
    park: '<path d="M12 3 5 13h3l-4 5h16l-4-5h3L12 3ZM12 18v4"/>',
    district: '<path d="m12 2 8 4v6c0 5-4 8-8 10-4-2-8-5-8-10V6l8-4Z"/><path d="m8 11 3 3 5-5"/>',
    block: '<path d="M4 4h16v16H4zM4 12h16M12 4v16"/>',
    culture: '<path d="M3 21h18M6 21V9l6-5 6 5v12M9 13h6v8M3 11l9-8 9 8"/>'
  };
  function zoneMarkerHtml(zone, color, selected) {
    const kind = ZONE_ICONS[zone.kind] ? zone.kind : 'park';
    const cls = 'zone-pin-inner';
    const icon = '<svg viewBox="0 0 24 24" aria-hidden="true">' + ZONE_ICONS[kind] + '</svg>';
    return '<div class="' + cls + '" style="--zone-color:' + color + '">' + icon + '</div>';
  }

  function applyTheme(name) {
    state.theme = name === 'light' ? 'light' : 'dark';
    document.body.dataset.mapTheme = state.theme;
    ui.theme.classList.toggle('is-active', state.theme === 'light');
    ui.theme.setAttribute('aria-label', state.theme === 'light' ? 'Включить тёмную карту' : 'Включить светлую карту');
    ui.theme.setAttribute('title', state.theme === 'light' ? 'Тёмная карта' : 'Светлая карта');
    if (state.basemapType === 'vector' && state.baseLayer) {
      try {
        const gl = state.baseLayer.getMaplibreMap();
        gl?.setStyle(MAP_STYLES[state.theme]);
      } catch (error) {
        console.warn('Не удалось переключить стиль карты', error);
        feedback('Не удалось сменить тему карты', 'error');
      }
    }
    try { window.localStorage?.setItem('mgn_city_map_theme', state.theme); } catch (_) {}
  }
  function initialTheme() {
    try { return window.localStorage?.getItem('mgn_city_map_theme') || 'dark'; } catch (_) { return 'dark'; }
  }
  function togglePanel() {
    state.expanded = !state.expanded;
    ui.panel.classList.toggle('is-expanded', state.expanded);
    ui.sheetToggle.setAttribute('aria-expanded', String(state.expanded));
    ui.sheetToggle.setAttribute('aria-label', state.expanded ? 'Свернуть панель карты' : 'Развернуть панель карты');
    requestAnimationFrame(() => state.map?.invalidateSize());
  }
  // OpenFreeMap serves OSM-derived vector maps with no API key.
  // Official Leaflet bridge: https://openfreemap.org/quick_start/
  const MAP_STYLES = {
    dark: 'https://tiles.openfreemap.org/styles/dark',
    light: 'https://tiles.openfreemap.org/styles/positron'
  };

  function createFallbackLayer(map) {
    // Only used when this device cannot render vector maps (e.g. WebGL off).
    // The city document now sends Referer in accordance with OSM tile policy.
    const fallback = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      minZoom: 10, maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
      referrerPolicy: 'strict-origin-when-cross-origin',
      crossOrigin: true
    }).addTo(map);
    fallback.on('tileerror', () => {
      if (!fallback.errorShown) {
        fallback.errorShown = true;
        feedback('Не удалось загрузить карту. Проверь подключение и обнови игру.', 'error');
      }
    });
    state.baseLayer = fallback;
    state.basemapType = 'raster';
  }

  function createMap() {
    if (!window.L) {
      setStatus('Не удалось загрузить карту. Проверь интернет и обнови игру.');
      ui.capture.disabled = true;
      feedback('Картографический движок недоступен', 'error');
      return false;
    }
    const map = L.map('map', {
      zoomControl: false, preferCanvas: true, minZoom: 10, maxZoom: 19
    }).setView(CITY, 12);
    // The blue/yellow mark before "Leaflet" is its logo, not a country flag.
    // Remove the optional library branding; keep map data credit intact.
    map.attributionControl?.setPrefix(false);
    state.map = map;
    let vectorReady = false;
    let vectorLoaded = false;
    if (window.maplibregl && typeof L.maplibreGL === 'function') {
      try {
        if (window.maplibregl.supported?.() !== false) {
          const layer = L.maplibreGL({
            style: MAP_STYLES[state.theme],
            interactive: false
          }).addTo(map);
          state.baseLayer = layer;
          state.basemapType = 'vector';
          vectorReady = true;
          const gl = layer.getMaplibreMap();
          if (gl) {
            gl.on('load', () => { vectorLoaded = true; scheduleRoadPolygons(gl); });
            gl.on('idle', () => scheduleRoadPolygons(gl));
            // If the vector provider is unreachable, remove the blank canvas.
            window.setTimeout(() => {
              if (state.map !== map || state.baseLayer !== layer || vectorLoaded) return;
              if (gl.isStyleLoaded?.()) return;
              try { map.removeLayer(layer); } catch (_) {}
              createFallbackLayer(map);
              feedback('Основная карта недоступна, включена резервная.', 'error');
            }, 13000);
          }
        }
      } catch (error) {
        console.warn('MapLibre недоступен, используем резервную карту', error);
        if (state.baseLayer) {
          try { map.removeLayer(state.baseLayer); } catch (_) {}
          state.baseLayer = null;
        }
        vectorReady = false;
      }
    }
    if (!vectorReady) createFallbackLayer(map);
    // The Leaflet/MapLibre bridge takes the legal data attribution from the
    // vector style automatically. Do NOT add it a second time here.
    state.territoryGroup = L.layerGroup().addTo(map);
    state.markerGroup = L.layerGroup().addTo(map);
    state.petGroup = L.layerGroup().addTo(map);
    map.on('zoomend', () => {
      const showCaptureZones = map.getZoom() >= 14;
      const blocksVisible = map.getZoom() >= 13;
      if (state.showBlocks !== blocksVisible) {
        state.showBlocks = blocksVisible;
        drawTerritories();
      }
      for (const item of state.territoryLayers.values()) {
        item.captureRadius.setStyle({ opacity: showCaptureZones ? .75 : 0, fillOpacity: showCaptureZones ? .06 : 0 });
      }
    });
    window.addEventListener('resize', () => map.invalidateSize());
    return true;
  }

  function scheduleRoadPolygons(gl) {
    if (!window.MGNRoadBlocks || !state.zones.length ||
        !gl?.querySourceFeatures || state.map?.getZoom?.() < 13) return;
    clearTimeout(state.roadTimer);
    state.roadTimer = setTimeout(() => {
      if (!state.zones.length || state.basemapType !== 'vector') return;
      try {
        const features = gl.querySourceFeatures('openmaptiles', {
          sourceLayer: 'transportation'
        });
        if (!Array.isArray(features) || features.length < 4) return;
        const center = state.map.getCenter?.();
        const signature = [
          Math.round(state.map.getZoom() * 2),
          center ? Math.round(center.lat * 150) : 0,
          center ? Math.round(center.lng * 150) : 0,
          features.length
        ].join(':');
        if (signature === state.roadSignature) return;
        state.roadSignature = signature;
        const bounds = state.map.getBounds?.()?.pad?.(.5);
        const visibleZones = bounds ? state.zones.filter(z =>
          bounds.contains([z.lat, z.lon])) : state.zones;
        const matched = window.MGNRoadBlocks.matchZonePolygons(
          features, visibleZones, {latitude: center?.lat || CITY[0], maxSegments: 24000}
        );
        let changed = false;
        for (const zone of visibleZones) {
          const shape = matched[zone.id];
          if (!shape || !Array.isArray(shape.polygon) || shape.polygon.length < 3) continue;
          // The server may have a complete, persisted OSM polygon already.
          if (state.roadPolygons.get(zone.id)?.source === 'server') continue;
          state.roadPolygons.set(zone.id, shape);
          changed = true;
        }
        if (changed) drawTerritories();
      } catch (error) {
        console.warn('Street polygons not available at this zoom', error);
      }
    }, 700);
  }

  function drawTerritories() {
    if (!state.map) return;
    state.territoryGroup.clearLayers();
    state.territoryLayers.clear();
    const all = [];
    const ordered = state.zones.filter(z => z.id < 100000 || state.map.getZoom() >= 13).sort((a, b) =>
      (a.kind === 'district' ? -1 : 0) - (b.kind === 'district' ? -1 : 0));
    // Outlines are rendered ONLY when created from real OSM roads by the API.
    // A landmark without verified geometry remains a visible, clickable pin.
    for (const zone of ordered) {
      const selected = state.selectedId === zone.id;
      let polygon = null;
      const roadOutline = state.roadPolygons.get(zone.id)?.polygon || zone.polygon;
      if (Array.isArray(roadOutline) && roadOutline.length >= 3) {
        const color = ownerColor(zone);
        polygon = L.polygon(roadOutline, {
          color, weight: selected ? 3 : 2,
          opacity: zone.kind === 'district' ? .85 : 1,
          dashArray: zone.occupied ? null : '7 5',
          fillColor: color, fillOpacity: selected ? .26 : zone.occupied ? .15 : .07,
          lineCap: 'round', lineJoin: 'round'
        }).addTo(state.territoryGroup);
        polygon.on('click', () => chooseZone(zone.id));
      }
      const color = ownerColor(zone);
      const captureRadius = L.circle([zone.lat,zone.lon],{
        radius:state.radius,color,weight:1,dashArray:'3 6',
        opacity:state.map.getZoom()>=15?.4:0,
        fillColor:color,fillOpacity:0,interactive:false
      }).addTo(state.territoryGroup);
      state.territoryLayers.set(zone.id,{polygon,point:null,captureRadius});
      all.push([zone.lat,zone.lon]);
    }
    for (const zone of ordered) {
      const item = state.territoryLayers.get(zone.id);
      const kind = ZONE_ICONS[zone.kind] ? zone.kind : 'park';
      const selected = state.selectedId === zone.id;
      const icon = L.divIcon({
        className:'zone-pin'+(zone.mine?' is-mine':zone.occupied?' is-held':' is-free')+
          (selected?' is-selected':'')+(kind==='district'?' is-district':''),
        html:zoneMarkerHtml(zone,ownerColor(zone),selected),
        iconSize:kind==='district'?[39,39]:[33,33],
        iconAnchor:kind==='district'?[19,19]:[16,16]
      });
      item.point=L.marker([zone.lat,zone.lon],{
        icon,keyboard:true,title:zone.name,
        zIndexOffset:selected?500:kind==='district'?50:150
      }).addTo(state.territoryGroup);
      item.point.on('click',()=>chooseZone(zone.id));
    }
    drawPetAgents();
    if (!state.hasFramed && all.length) {
      state.hasFramed=true;
      state.map.fitBounds(L.latLngBounds(all), {
        maxZoom:12,paddingTopLeft:[20,90],
        paddingBottomRight:[20,Math.min(185,Math.round(window.innerHeight*.24))]
      });
    }
  }
  async function fetchRoadShapes() {
    try {
      const response = await api('/api/city/road-shapes');
      const shapes = response.shapes || {};
      // Server has created actual OSM-verified small quarters in SQLite.
      if (response.extra_count > 0) await load();
      let updated = 0;
      for (const zone of state.zones) {
        const shape = shapes[String(zone.id)];
        if (Array.isArray(shape) && shape.length>=3) {
          zone.polygon=shape;
          state.roadPolygons.set(zone.id, {polygon: shape, source: 'server'});
          updated++;
        }
      }
      if (updated) drawTerritories();
    } catch (error) {
      // Road data are optional: icons continue to work without fake outlines.
      console.warn('Street geometry unavailable', error);
    }
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function guardedZone(id) {
    return state.zones.find(z => z.id === id);
  }
  function renderMarket() {
    ui.wallet.textContent = state.wallet.toLocaleString('ru-RU') + ' ⭐';
    ui.hpValue.textContent = state.hp.toFixed(1).replace(/\.0$/, '');
    ui.hpHud.textContent = String(Math.ceil(state.hp));
    ui.hpFill.style.width = state.hp + '%';
    ui.pendingStars.textContent = state.pendingStars.toLocaleString('ru-RU') + ' ⭐';
    ui.claimIncome.disabled = state.actionBusy || state.pendingStars <= 0;
    ui.shop.replaceChildren();
    for (const pet of state.catalog) {
      const row = element('div', null, 'pet-product');
      const emoji = element('span', pet.emoji, 'pet-product-emoji');
      const info = element('div', null, 'pet-product-info');
      info.append(element('strong', pet.name),
        element('small', '+' + pet.stars_h + ' ⭐/ч · −' + pet.hp_h + ' HP/ч'));
      const buyBox = element('div', null, 'pet-product-price');
      const buy = element('button', 'Купить');
      buy.type = 'button';
      buy.dataset.buyKind = pet.kind;
      buy.disabled = state.actionBusy || state.wallet < pet.price;
      const price = element('small', pet.price.toLocaleString('ru-RU') + ' ⭐');
      buyBox.append(price, buy);
      row.append(emoji, info, buyBox);
      ui.shop.append(row);
    }
    ui.inventory.replaceChildren();
    ui.petCount.textContent = String(state.myPets.length);
    const zone = selectedZone();
    ui.placeHint.textContent = zone?.mine ?
      'Выбран район: ' + zone.name : 'Чтобы поставить питомца, выбери свой район на карте.';
    if (!state.myPets.length) {
      ui.inventory.append(element('p', 'Пока пусто. Купленные питомцы появятся здесь.', 'market-note'));
    }
    for (const pet of state.myPets) {
      const info = state.catalog.find(i => i.kind === pet.kind);
      if (!info) continue;
      const row = element('div', null, 'pet-inventory-row');
      const emoji = element('span', info.emoji, 'pet-product-emoji');
      const desc = element('div', null, 'pet-inventory-label');
      const location = pet.zone_id ? guardedZone(pet.zone_id)?.name || 'Район' : 'В запасе';
      desc.append(element('strong', info.name + ' · #' + pet.id),
        element('small', location + (pet.zone_id ? ' · +' + info.stars_h + ' ⭐/ч' : '')));
      const button = element('button', pet.zone_id ? 'Снять' : 'Поставить', 'pet-action');
      button.type = 'button';
      button.dataset.petAction = pet.zone_id ? 'recall' : 'place';
      button.dataset.petId = String(pet.id);
      button.disabled = state.actionBusy || (!pet.zone_id && !zone?.mine);
      row.append(emoji, desc, button);
      ui.inventory.append(row);
    }
  }

  async function petAction(action, values = {}) {
    if (state.actionBusy) return;
    if (action === 'place' && !selectedZone()?.mine) {
      feedback('Выбери свой район на карте', 'error'); return;
    }
    state.actionBusy = true;
    renderMarket();
    try {
      const result = await api('/api/city/pets/' + action, {
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(values)
      });
      await load();
      if (action === 'buy') feedback('Питомец куплен. Выбери свой район!', 'success');
      else if (action === 'place') feedback('Защитник отправлен на район', 'success');
      else if (action === 'recall') feedback('Питомец вернулся в запас', 'success');
      else feedback('Получено ' + (result.stars || 0) + ' ⭐', 'success');
      touch('success');
    } catch (error) {
      feedback(error.message, 'error');
      touch('error');
    } finally {
      state.actionBusy = false;
      renderMarket();
    }
  }

  function insidePolygon(poly, lat, lon) {
    if (!Array.isArray(poly) || poly.length < 3) return false;
    if (window.MGNRoadBlocks?.contains)
      return window.MGNRoadBlocks.contains(poly, lat, lon);
    let inside = false;
    for (let i=0,j=poly.length-1;i<poly.length;j=i++) {
      const a=poly[i],b=poly[j];
      if ((a[0]>lat)!==(b[0]>lat) &&
          lon < (b[1]-a[1])*(lat-a[0])/(b[0]-a[0])+a[1]) inside=!inside;
    }
    return inside;
  }
  function drawPetAgents() {
    if (!state.petGroup) return;
    state.petGroup.clearLayers();
    state.petAgents = [];
    const shown = state.guards.slice(0, 75);
    for (const guard of shown) {
      const zone = guardedZone(guard.zone_id);
      const kind = state.catalog.find(p=>p.kind===guard.kind);
      if (!zone || !kind) continue;
      const poly = state.roadPolygons.get(zone.id)?.polygon || zone.polygon;
      const box = Array.isArray(poly) && poly.length >= 3 ? poly : null;
      const anchor = box && insidePolygon(box,zone.lat,zone.lon) ?
        [zone.lat,zone.lon] : box ? box[0] : [zone.lat,zone.lon];
      const marker = L.marker(anchor, {
        interactive:false,zIndexOffset:1200,
        icon:L.divIcon({
          className:'pet-agent',
          html:'<span aria-hidden="true">' + kind.emoji + '</span>',
          iconSize:[31,31],iconAnchor:[15,15]
        })
      }).addTo(state.petGroup);
      state.petAgents.push({marker,anchor,polygon:box,zoneId:zone.id,phase:zone.id*1.71});
    }
  }
  function animatePets() {
    if (document.hidden || !state.petAgents.length) return;
    const t = Date.now()/2600;
    for (const pet of state.petAgents) {
      if (!pet.polygon || !pet.marker.setLatLng) continue; // no verified borders: stay put
      const box = pet.polygon;
      const idx = Math.floor((t/4+pet.phase)%box.length);
      const edge = box[idx], inside = pet.anchor;
      const f = .07 + .08 * (1+Math.sin(t+pet.phase))/2;
      const lat = inside[0] + (edge[0]-inside[0])*f;
      const lon = inside[1] + (edge[1]-inside[1])*f;
      if (insidePolygon(box,lat,lon)) pet.marker.setLatLng([lat,lon]);
    }
  }

  async function sendPresence(gps) {
    if (!state.guards.length || !gps || document.hidden ||
        gps.accuracy > 35 || Date.now()-state.lastPresenceAt < 15000) return;
    state.lastPresenceAt = Date.now();
    try {
      const result = await api('/api/city/presence',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
          lat:gps.lat,lon:gps.lon,accuracy_m:gps.accuracy,
          timestamp_s:gps.timestamp/1000
        })
      });
      state.hp = Math.max(1, Math.min(100, Number(result.hp) || 1));
      renderMarket();
      if (state.lastAttackedZone !== result.zone_id && result.zone_id) {
        const zone = guardedZone(result.zone_id);
        feedback('Защитник ' + (zone?.name || 'района') + ' атакует. HP падает медленно.', 'info');
      }
      state.lastAttackedZone = result.zone_id || null;
    } catch (error) {
      // Geolocation/gameplay is optional. No alerts on repeated noisy fixes.
      console.warn('GPS HP update unavailable', error);
    }
  }

  function renderBoard() {
    ui.leaders.replaceChildren();
    if (!state.leaderboard.length) {
      const item = document.createElement('li');
      item.className = 'rule';
      item.textContent = 'Пока никто не захватил территорию. Первый район ждёт тебя.';
      ui.leaders.append(item);
      return;
    }
    state.leaderboard.forEach((player, index) => {
      const item = document.createElement('li');
      item.className = 'leader';
      const rank = document.createElement('span');
      rank.className = 'leader-rank';
      rank.textContent = String(index + 1).padStart(2, '0');
      const name = document.createElement('span');
      name.className = 'leader-name' + (player.mine ? ' is-me' : '');
      name.textContent = safeText(player.name, 'Аноним') + (player.mine ? ' · ТЫ' : '');
      const amount = document.createElement('strong');
      amount.className = 'leader-count';
      amount.textContent = String(number(player.zones));
      const suffix = document.createElement('span');
      suffix.className = 'leader-caption';
      suffix.textContent = 'район';
      item.append(rank, name, amount, suffix);
      ui.leaders.append(item);
    });
  }

  function renderSelection() {
    const zone = selectedZone();
    ui.panel.classList.toggle('has-selection', Boolean(zone));
    ui.ownerCard.hidden = !zone;
    ui.capture.hidden = !zone;
    ui.zoneGuard.hidden = !zone || !state.guards.some(g => g.zone_id === zone.id);
    if (!ui.zoneGuard.hidden) {
      const defender = state.guards.find(g => g.zone_id === zone.id);
      ui.zoneGuard.textContent = state.catalog.find(p => p.kind === defender.kind)?.emoji || '🐈';
    }

    if (!zone) {
      ui.zone.textContent = 'Выбери место на карте';
      ui.details.textContent = '';
      ui.details.hidden = true;
      ui.capture.disabled = true;
      ui.captureLabel.textContent = 'Выбери место';
      return;
    }

    ui.zone.textContent = zone.name;
    ui.details.textContent = [
      zone.official_name && zone.official_name !== zone.name ? zone.official_name : '',
      zone.address || ''
    ].filter(Boolean).join(' · ');
    ui.details.hidden = !ui.details.textContent;
    ui.owner.textContent = zone.mine ? 'Ты' :
      zone.occupied ? (zone.owner_name || 'Аноним') : 'Никого';
    ui.state.textContent = zone.mine ? 'Твоя' : zone.occupied ? 'Занято' : 'Свободно';
    ui.state.className = 'owner-state ' + (zone.mine ? 'mine' : zone.occupied ? 'occupied' : '');

    const remaining = cooldownS();
    ui.capture.disabled = !state.canCapture ||
      state.capturing || state.locating || (!zone.mine && remaining > 0);
    if (!state.canCapture) {
      ui.captureLabel.textContent = 'Только просмотр';
    } else if (zone.mine) {
      ui.captureLabel.textContent = 'Защитить район';
    } else if (remaining > 0) {
      ui.captureLabel.textContent = 'Повтор через ' + humanTime(remaining);
    } else if (state.capturing || state.locating) {
      ui.captureLabel.textContent = 'Проверяем позицию…';
    } else {
      ui.captureLabel.textContent = 'Захватить';
    }
  }

  function chooseZone(id) {
    const zone = state.zones.find(z => z.id === id);
    if (!zone) return;
    state.selectedId = zone.id;
    switchTab('map');
    renderSelection();
    drawTerritories();
    const layer = state.territoryLayers.get(id)?.polygon;
    if (!layer && state.map) state.map.flyTo([zone.lat, zone.lon], 15, {duration:.5});
    if (layer && state.map) {
      state.map.flyToBounds(layer.getBounds().pad(.5), {
        maxZoom: 15, duration: .55,
        paddingTopLeft: [25, 85],
        paddingBottomRight: [25, Math.min(245, Math.round(window.innerHeight * .30))]
      });
    }
    touch();
  }

  function switchTab(tab) {
    state.activeTab = tab;
    ui.panel.setAttribute('data-tab', tab);
    const pages = [
      [ui.view, ui.mapTab, 'map'],
      [ui.board, ui.topTab, 'top'],
      [ui.market, ui.marketTab, 'market'],
      [ui.rules, ui.rulesTab, 'rules']
    ];
    for (const [section, button, key] of pages) {
      const active = key === tab;
      section.hidden = !active;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    }
    ui.panel.scrollTop = 0;
    touch();
    requestAnimationFrame(() => state.map?.invalidateSize());
  }

  function normaliseLocation(lat, lon, accuracy, timestamp) {
    const safeAccuracy = accuracy == null ? 9999 : Math.max(0, number(accuracy, 9999));
    return {
      lat: number(lat, NaN), lon: number(lon, NaN),
      accuracy: safeAccuracy, timestamp: number(timestamp, Date.now())
    };
  }
  function browserLocation() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error('Встроенный GPS недоступен.'));
      navigator.geolocation.getCurrentPosition(
        position => resolve(normaliseLocation(
          position.coords.latitude, position.coords.longitude,
          position.coords.accuracy, position.timestamp
        )),
        error => reject(new Error(error.code === 1 ? 'Нет разрешения на геолокацию. Разреши её в Telegram или настройках телефона.' : 'GPS не ответил. Попробуй на открытом воздухе.')),
        { enableHighAccuracy: true, maximumAge: 0, timeout: 16000 }
      );
    });
  }
  function telegramLocation() {
    return new Promise((resolve, reject) => {
      const manager = tg?.LocationManager;
      if (!manager) return reject(new Error('Telegram GPS недоступен'));
      const timeout = setTimeout(() => reject(new Error('Telegram GPS не ответил')), 12000);
      const request = () => {
        try {
          manager.getLocation(data => {
            clearTimeout(timeout);
            if (!data) return reject(new Error('Доступ к геолокации отклонён'));
            resolve(normaliseLocation(
              data.latitude, data.longitude, data.horizontal_accuracy, Date.now()
            ));
          });
        } catch (error) { clearTimeout(timeout); reject(error); }
      };
      try {
        if (manager.isInited) request();
        else manager.init(request);
      } catch (error) { clearTimeout(timeout); reject(error); }
    });
  }
  function drawLocation(gps, focus) {
    if (!state.map || !Number.isFinite(gps.lat) || !Number.isFinite(gps.lon)) return;
    const point = [gps.lat, gps.lon];
    if (!state.accuracyCircle) {
      state.accuracyCircle = L.circle(point, {
        radius: Math.max(5, Math.min(gps.accuracy, 500)),
        color: '#e57ac6', weight: 1.5, fillColor: '#e57ac6', fillOpacity: .12
      }).addTo(state.markerGroup);
    } else {
      state.accuracyCircle.setLatLng(point);
      state.accuracyCircle.setRadius(Math.max(5, Math.min(gps.accuracy, 500)));
    }
    if (!state.gpsMarker) {
      state.gpsMarker = L.marker(point, {
        icon: L.divIcon({
          className: 'user-position', html: '<div class="gps-marker"></div>',
          iconSize: [24, 24], iconAnchor: [12, 12]
        }), zIndexOffset: 2000
      }).addTo(state.markerGroup).bindTooltip('Ты здесь', {
        permanent: true, direction: 'top', offset: [0, -14], className: 'you-label'
      });
    } else state.gpsMarker.setLatLng(point);
    ui.locate.classList.add('is-active');
    // Automatically centre ONCE after consent; never hijack a user exploring the map.
    if (focus) {
      state.map.flyTo(point, Math.max(state.map.getZoom(), 15), {duration:.5});
      state.autoCentered = true;
    }
  }

  function updateGPS(gps, focus = false) {
    if (!gps || !Number.isFinite(gps.lat) || !Number.isFinite(gps.lon)) return;
    // Ignore less accurate background readings rather than teleporting the dot.
    if (gps.accuracy < 0) return; // Missing accuracy must not hide the user marker.
    state.gps = gps;
    state.gpsEnabled = true;
    state.gpsUpdateAt = Date.now();
    drawLocation(gps, focus);
    sendPresence(gps);
    renderSelection();
  }

  function startBrowserWatch() {
    if (state.gpsWatchId !== null || !navigator.geolocation?.watchPosition) return false;
    try {
      state.gpsWatchId = navigator.geolocation.watchPosition(
        p => updateGPS(normaliseLocation(
          p.coords.latitude,p.coords.longitude,p.coords.accuracy,p.timestamp
        ), !state.autoCentered && !document.hidden),
        error => {
          if (error.code === 1) {
            // Browser permission can be denied even while Telegram native GPS is granted.
            if (state.gpsWatchId !== null) {
              try {navigator.geolocation.clearWatch(state.gpsWatchId);} catch (_) {}
              state.gpsWatchId = null;
            }
            if (tg?.LocationManager?.isAccessGranted) startTelegramPolling();
            else feedback('Доступ к геолокации закрыт', 'error');
          }
        },
        {enableHighAccuracy:true, maximumAge:5000, timeout:20000}
      );
      return true;
    } catch (_) {return false;}
  }
  function startTelegramPolling() {
    if (state.telegramPollId !== null) return;
    if (!tg?.LocationManager?.isAccessGranted) return;
    state.telegramPollId = window.setInterval(async () => {
      if (document.hidden || state.locating) return;
      // In Telegram iOS, WebKit watchPosition can stall without an error.
      // Poll Telegram only if no valid browser location arrived recently.
      if (Date.now() - (state.gpsUpdateAt || 0) < 18000) return;
      try {
        const gps = await telegramLocation();
        updateGPS(gps, !state.autoCentered);
      } catch (_) { /* permissions can change on another screen */ }
    }, 12000);
  }
  function startTracking() {
    if (!state.gpsEnabled || document.hidden) return;
    // Native watchPosition updates continuously when supported.
    // Telegram LocationManager has no watch method; use low-rate polling there.
    startBrowserWatch();
    // iOS fallback runs alongside watchPosition, but polls only if it stalls.
    startTelegramPolling();
  }
  function stopTracking() {
    if (state.gpsWatchId !== null) {
      try {navigator.geolocation?.clearWatch(state.gpsWatchId);} catch (_) {}
      state.gpsWatchId = null;
    }
    if (state.telegramPollId !== null) {
      window.clearInterval(state.telegramPollId);
      state.telegramPollId = null;
    }
  }

  async function locate(focus = true, auto = false) {
    if (state.locating) {
      if (focus && state.gps) drawLocation(state.gps,true);
      return state.gps;
    }
    state.locating = true;
    ui.locate.classList.add('is-loading');
    renderSelection();
    try {
      let gps;
      if (tg?.LocationManager) {
        try { gps = await telegramLocation(); }
        catch (_) { gps = await browserLocation(); }
      } else gps = await browserLocation();
      if (!Number.isFinite(gps.lat) || !Number.isFinite(gps.lon))
        throw new Error('GPS вернул неверные координаты.');
      // A manual tap always recentres; an automatic lookup recentres once only.
      updateGPS(gps, focus || !state.autoCentered);
      startTracking();
      if (!auto) feedback('Местоположение обновлено', 'success');
      return gps;
    } catch (error) {
      if (!auto) feedback(error.message || 'Не удалось определить GPS', 'error');
      if (auto) return null;
      throw error;
    } finally {
      state.locating = false;
      ui.locate.classList.remove('is-loading');
      renderSelection();
    }
  }
  function autoLocateIfGranted() {
    // Initializing Telegram's location manager is not a permission request.
    // On iOS isAccessGranted is only reliable AFTER init() has completed.
    const manager = tg?.LocationManager;
    if (manager) {
      const check = () => {
        if (manager.isAccessGranted) locate(false,true).then(startTracking).catch(() => {});
      };
      try {
        if (manager.isInited) check();
        else manager.init(check);
      } catch (_) { /* unsupported Telegram version */ }
    }
    // Browser permission APIs can be missing on older iOS/WebKit clients.
    // Do not trigger an unsolicited OS permission dialog on startup.
    navigator.permissions?.query?.({name:'geolocation'})
      .then(result => {
        if (result.state === 'granted') locate(false,true).then(startTracking).catch(() => {});
        result.onchange = () => {
          if (result.state === 'granted') locate(false,true).then(startTracking).catch(() => {});
          else stopTracking();
        };
      }).catch(() => {});
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopTracking();
    else if (state.gpsEnabled) {
      locate(false,true).then(() => startTracking()).catch(() => {});
    } else autoLocateIfGranted();
  });
  window.addEventListener('pagehide', stopTracking);

  async function load() {
    ui.refresh.classList.add('is-loading');
    try {
      const data = await api('/api/city/state');
      state.zones = Array.isArray(data.zones) ? data.zones : [];
      if (state.basemapType === 'vector' && state.baseLayer?.getMaplibreMap) {
        scheduleRoadPolygons(state.baseLayer.getMaplibreMap());
      }
      state.leaderboard = Array.isArray(data.leaderboard) ? data.leaderboard : [];
      state.catalog = Array.isArray(data.catalog) ? data.catalog : [];
      state.myPets = Array.isArray(data.my_pets) ? data.my_pets : [];
      state.guards = Array.isArray(data.guards) ? data.guards : [];
      state.wallet = number(data.wallet);
      state.hp = Math.max(1, Math.min(100, number(data.hp, 100)));
      state.pendingStars = number(data.pending_stars);
      state.canCapture = !!data.can_capture;
      state.radius = number(data.capture_radius_m, 100);
      state.maxAccuracy = number(data.max_accuracy_m, 75);
      state.cooldownEnd = Date.now() + number(data.cooldown_remaining_s) * 1000;
      if (state.selectedId && !state.zones.some(z => z.id === state.selectedId)) state.selectedId = null;
      renderHud(data);
      renderBoard();
      renderMarket();
      drawTerritories();
      renderSelection();
      if (!state.zones.length) feedback('Пока нет активных игровых районов');
    } catch (error) {
      ui.count.textContent = '—';
      ui.capture.disabled = true;
      ui.captureLabel.textContent = 'Игра недоступна';
      setStatus(error.message);
      feedback(error.message, 'error');
    } finally { ui.refresh.classList.remove('is-loading'); }
  }

  async function capture() {
    const zone = selectedZone();
    if (!zone || state.capturing || !state.canCapture) return;
    if (zone.mine) { switchTab('market'); return; }
    if (cooldownS() > 0) return;
    state.capturing = true;
    renderSelection();
    try {
      const gps = await locate(false);
      const metres = distanceM(gps.lat, gps.lon, zone.lat, zone.lon);
      if (gps.accuracy > state.maxAccuracy) throw new Error('GPS неточный: ±' + Math.round(gps.accuracy) + ' м. Нужно не хуже ±' + state.maxAccuracy + ' м.');
      if (metres + gps.accuracy > state.radius) throw new Error('До точки ' + humanDistance(metres) + '. Для захвата необходимо быть ближе ' + state.radius + ' м с учётом GPS.');
      await api('/api/city/capture', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          zone_id: zone.id, lat: gps.lat, lon: gps.lon,
          accuracy_m: gps.accuracy, timestamp_s: gps.timestamp / 1000
        })
      });
      touch('success');
      await load();
      feedback('Район «' + zone.name + '» теперь твой!', 'success');
    } catch (error) {
      touch('error');
      feedback(error.message, 'error');
    } finally {
      state.capturing = false;
      renderSelection();
    }
  }

  ui.theme.addEventListener('click', () => { applyTheme(state.theme === 'dark' ? 'light' : 'dark'); touch(); });
  ui.sheetToggle.addEventListener('click', togglePanel);
  ui.locate.addEventListener('click', () => { locate(true).catch(() => {}); });
  ui.refresh.addEventListener('click', () => { load(); });
  ui.top.addEventListener('click', () => { switchTab('top'); });
  ui.mapTab.addEventListener('click', () => { switchTab('map'); });
  ui.topTab.addEventListener('click', () => { switchTab('top'); });
  ui.marketTab.addEventListener('click', () => { switchTab('market'); renderMarket(); });
  ui.rulesTab.addEventListener('click', () => { switchTab('rules'); });
  ui.capture.addEventListener('click', capture);
  ui.claimIncome.addEventListener('click', () => { petAction('claim'); });
  ui.shop.addEventListener('click', event => {
    const button = event.target.closest('[data-buy-kind]');
    if (button) petAction('buy', {kind: button.dataset.buyKind});
  });
  ui.inventory.addEventListener('click', event => {
    const button = event.target.closest('[data-pet-action]');
    if (!button) return;
    petAction(button.dataset.petAction, {
      pet_id: Number(button.dataset.petId), zone_id: state.selectedId
    });
  });
  setInterval(() => { if (selectedZone() && !state.capturing && !state.locating) renderSelection(); }, 1000);
  setInterval(animatePets, 2300);

  applyTheme(initialTheme());
  tg?.BackButton?.show();
  tg?.BackButton?.onClick(() => { window.location.href = './index.html'; });
  if (createMap()) {
    load().then(() => { autoLocateIfGranted(); fetchRoadShapes(); });
  }
})();