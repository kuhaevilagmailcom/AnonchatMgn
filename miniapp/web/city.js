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
    count: $('count'), mine: $('mineCount'), captures: $('captureCount'),
    zone: $('zone'), owner: $('owner'), ownerCard: $('ownerCard'),
    state: $('zoneState'), details: $('zoneDetails'),
    theme: $('theme'), sheetToggle: $('sheetToggle'), status: $('status'),
    capture: $('capture'), captureLabel: $('captureLabel'),
    locate: $('locate'), refresh: $('refresh'), top: $('topbutton'),
    leaders: $('leaders'), toast: $('toast'),
    mapTab: $('showmap'), topTab: $('showtop'), rulesTab: $('showrules')
  };

  const state = {
    zones: [], leaderboard: [], selectedId: null, gps: null, map: null,
    territoryLayers: new Map(), territoryGroup: null, markerGroup: null,
    gpsMarker: null, accuracyCircle: null, locating: false, capturing: false,
    canCapture: false, radius: 100, maxAccuracy: 75, cooldownEnd: 0,
    activeTab: 'map', toastTimer: null, hasFramed: false, expanded: false, theme: 'dark',
    baseLayer: null, basemapType: null,
    gpsWatchId: null, telegramPollId: null, gpsEnabled: false, autoCentered: false
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
  }
  const ZONE_ICONS = {
    mall: '<path d="M4 10h16v11H4zM3 10l2-6h14l2 6M8 10V4m8 6V4M9 21v-6h6v6"/>',
    park: '<path d="M12 3 5 13h3l-4 5h16l-4-5h3L12 3ZM12 18v4"/>',
    district: '<path d="m12 2 8 4v6c0 5-4 8-8 10-4-2-8-5-8-10V6l8-4Z"/><path d="m8 11 3 3 5-5"/>'
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
            gl.on('load', () => { vectorLoaded = true; });
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
    map.on('zoomend', () => {
      const showCaptureZones = map.getZoom() >= 14;
      for (const item of state.territoryLayers.values()) {
        item.captureRadius.setStyle({ opacity: showCaptureZones ? .75 : 0, fillOpacity: showCaptureZones ? .06 : 0 });
      }
    });
    window.addEventListener('resize', () => map.invalidateSize());
    return true;
  }

  function drawTerritories() {
    if (!state.map) return;
    state.territoryGroup.clearLayers();
    state.territoryLayers.clear();
    const all = [];
    const ordered = [...state.zones].sort((a, b) =>
      (a.kind === 'district' ? -1 : 0) - (b.kind === 'district' ? -1 : 0));
    // Outlines are rendered ONLY when created from real OSM roads by the API.
    // A landmark without verified geometry remains a visible, clickable pin.
    for (const zone of ordered) {
      const selected = state.selectedId === zone.id;
      let polygon = null;
      if (Array.isArray(zone.polygon) && zone.polygon.length >= 4) {
        const color = ownerColor(zone);
        polygon = L.polygon(zone.polygon, {
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
      let updated = 0;
      for (const zone of state.zones) {
        const shape = shapes[String(zone.id)];
        if (Array.isArray(shape) && shape.length>=4) {
          zone.polygon=shape;
          updated++;
        }
      }
      if (updated) drawTerritories();
    } catch (error) {
      // Road data are optional: icons continue to work without fake outlines.
      console.warn('Street geometry unavailable', error);
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
    ui.capture.disabled = !state.canCapture || !!zone.mine ||
      state.capturing || state.locating || remaining > 0;
    if (!state.canCapture) {
      ui.captureLabel.textContent = 'Только просмотр';
    } else if (zone.mine) {
      ui.captureLabel.textContent = 'Уже твоё';
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
    if (gps.accuracy < 0 || gps.accuracy > 3000) return;
    state.gps = gps;
    state.gpsEnabled = true;
    state.gpsUpdateAt = Date.now();
    drawLocation(gps, focus);
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
            stopTracking();
            feedback('Доступ к геолокации закрыт', 'error');
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
      state.leaderboard = Array.isArray(data.leaderboard) ? data.leaderboard : [];
      state.canCapture = !!data.can_capture;
      state.radius = number(data.capture_radius_m, 100);
      state.maxAccuracy = number(data.max_accuracy_m, 75);
      state.cooldownEnd = Date.now() + number(data.cooldown_remaining_s) * 1000;
      if (state.selectedId && !state.zones.some(z => z.id === state.selectedId)) state.selectedId = null;
      renderHud(data);
      renderBoard();
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
    if (!zone || state.capturing || cooldownS() > 0 || !state.canCapture || zone.mine) return;
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
  ui.rulesTab.addEventListener('click', () => { switchTab('rules'); });
  ui.capture.addEventListener('click', capture);
  setInterval(() => { if (selectedZone() && !state.capturing && !state.locating) renderSelection(); }, 1000);

  applyTheme(initialTheme());
  tg?.BackButton?.show();
  tg?.BackButton?.onClick(() => { window.location.href = './index.html'; });
  if (createMap()) {
    load().then(() => { autoLocateIfGranted(); fetchRoadShapes(); });
  }
})();