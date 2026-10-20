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
    zone: $('zone'), owner: $('owner'), state: $('zoneState'),
    code: $('sectorCode'), size: $('sectorSize'),
    distance: $('distance'), accuracy: $('gpsQuality'), status: $('status'),
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
    activeTab: 'map', toastTimer: null, hasFramed: false
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
  function labelElement(zone) {
    const container = document.createElement('div');
    container.className = 'label-inner';
    const name = document.createElement('strong');
    name.className = 'label-name';
    name.textContent = zone.name;
    const owner = document.createElement('span');
    owner.className = 'label-owner';
    owner.textContent = zone.mine ? '★ ТВОЯ ТЕРРИТОРИЯ' :
      (zone.occupied ? (zone.owner_name || 'Аноним') : 'Свободно');
    container.append(name, owner);
    return container;
  }
  function createMap() {
    if (!window.L) {
      setStatus('Не загрузилась карта. Проверь интернет и обнови игру.');
      ui.capture.disabled = true;
      feedback('Картографический движок недоступен');
      return false;
    }
    const map = L.map('map', {
      zoomControl: false, preferCanvas: true, minZoom: 10, maxZoom: 19
    }).setView(CITY, 12);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      minZoom: 10, maxZoom: 19, attribution: '© OpenStreetMap contributors',
      crossOrigin: true
    }).addTo(map);
    state.map = map;
    state.territoryGroup = L.layerGroup().addTo(map);
    state.markerGroup = L.layerGroup().addTo(map);
    map.on('zoomend', () => {
      const showCaptureZones = map.getZoom() >= 14;
      for (const item of state.territoryLayers.values()) {
        item.point.setStyle({ opacity: showCaptureZones ? 1 : 0.65, fillOpacity: showCaptureZones ? 1 : 0.65 });
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
    for (const zone of state.zones) {
      if (!Array.isArray(zone.polygon) || zone.polygon.length < 3) continue;
      const color = ownerColor(zone);
      const isSelected = state.selectedId === zone.id;
      const polygon = L.polygon(zone.polygon, {
        color, weight: isSelected ? 4 : 2.5,
        opacity: 1, dashArray: zone.occupied ? null : '9 6',
        fillColor: color, fillOpacity: isSelected ? .38 : zone.occupied ? .24 : .13,
        lineCap: 'round', lineJoin: 'round'
      }).addTo(state.territoryGroup);
      const tooltip = L.tooltip({
        permanent: true, interactive: false, direction: 'center',
        className: 'territory-label ' + (zone.mine ? 'is-owned' : zone.occupied ? 'is-held' : 'is-free'),
        opacity: 1
      });
      tooltip.setContent(labelElement(zone));
      polygon.bindTooltip(tooltip);
      polygon.on('click', () => chooseZone(zone.id));
      const point = L.circleMarker([zone.lat, zone.lon], {
        radius: 5, color: '#fff', weight: 2, fillColor: color,
        fillOpacity: .95
      }).addTo(state.territoryGroup);
      point.on('click', () => chooseZone(zone.id));
      const captureRadius = L.circle([zone.lat, zone.lon], {
        radius: state.radius, color, weight: 1, dashArray: '3 6',
        opacity: state.map.getZoom() >= 14 ? .75 : 0,
        fillColor: color, fillOpacity: state.map.getZoom() >= 14 ? .06 : 0,
        interactive: false
      }).addTo(state.territoryGroup);
      state.territoryLayers.set(zone.id, { polygon, point, captureRadius });
      all.push(...zone.polygon);
    }
    if (!state.hasFramed && all.length) {
      state.hasFramed = true;
      const bounds = L.latLngBounds(all);
      state.map.fitBounds(bounds, {
        maxZoom: 13, paddingTopLeft: [20, 110],
        paddingBottomRight: [20, Math.min(360, Math.round(window.innerHeight * .42))]
      });
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
    if (!zone) {
      ui.code.textContent = 'КОНТРОЛЬ ТЕРРИТОРИЙ';
      ui.size.textContent = 'МГН / ТЕСТ';
      ui.zone.textContent = 'Твой город. Твои правила.';
      ui.owner.textContent = 'Выбери сектор на карте';
      ui.state.textContent = 'НА КАРТЕ';
      ui.state.className = 'owner-state';
      ui.distance.textContent = state.gps ? 'Твоя позиция найдена' : 'Расстояние: —';
      ui.accuracy.textContent = state.gps ? 'GPS ±' + Math.round(state.gps.accuracy) + ' м' : 'GPS не определён';
      setStatus('Нажми на район с цветной границей. После выбора можно проверить местоположение и захватить его.');
      ui.capture.disabled = true;
      ui.captureLabel.textContent = 'ВЫБЕРИ ТЕРРИТОРИЮ';
      return;
    }
    ui.code.textContent = 'СЕКТОР ' + String(zone.id).padStart(2, '0');
    ui.size.textContent = zone.size === 'Большой' ? 'БОЛЬШОЙ РАЙОН' : 'МАЛЫЙ РАЙОН';
    ui.zone.textContent = zone.name;
    ui.owner.textContent = zone.mine ? 'Ты' : (zone.owner_name || 'Аноним');
    ui.state.textContent = zone.mine ? 'ТВОЙ' : zone.occupied ? 'ЗАНЯТО' : 'СВОБОДНО';
    ui.state.className = 'owner-state ' + (zone.mine ? 'mine' : zone.occupied ? 'occupied' : '');
    const gps = state.gps;
    const metres = gps ? distanceM(gps.lat, gps.lon, zone.lat, zone.lon) : Infinity;
    ui.distance.textContent = gps ? 'До точки: ' + humanDistance(metres) : 'Расстояние: нажми GPS';
    ui.accuracy.textContent = gps ?
      (gps.accuracy <= state.maxAccuracy ? 'GPS ±' + Math.round(gps.accuracy) + ' м' : 'GPS неточный') :
      'GPS не определён';
    const cd = cooldownS();
    ui.capture.disabled = !state.canCapture || !!zone.mine || state.capturing || state.locating || cd > 0;
    if (!state.canCapture) {
      ui.captureLabel.textContent = 'РЕЖИМ ПРОСМОТРА';
      setStatus('Сейчас режим тестирования. Захват закрыт.');
    } else if (zone.mine) {
      ui.captureLabel.textContent = 'ТЕРРИТОРИЯ ТВОЯ';
      setStatus('Район уже под твоим контролем. Выбери другой.');
    } else if (cd > 0) {
      ui.captureLabel.textContent = 'ОЖИДАНИЕ ' + humanTime(cd);
      setStatus('Следующий захват будет доступен после окончания таймера.');
    } else if (state.capturing || state.locating) {
      ui.captureLabel.textContent = 'ПРОВЕРЯЕМ GPS…';
      setStatus('Определяем точные координаты для захвата территории.');
    } else {
      ui.captureLabel.textContent = 'ЗАХВАТИТЬ ТЕРРИТОРИЮ';
      if (!gps) setStatus('Нужен GPS: нажми захват или кнопку геолокации на карте.');
      else if (gps.accuracy > state.maxAccuracy) setStatus('Точность GPS слишком низкая. Для захвата требуется не хуже ±' + state.maxAccuracy + ' м.');
      else if (metres + gps.accuracy > state.radius) setStatus('Подойди ближе к метке на карте. Радиус захвата — ' + state.radius + ' м с учётом погрешности GPS.');
      else setStatus('Ты достаточно близко к точке. Можно захватывать!');
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
    if (layer && state.map) {
      state.map.flyToBounds(layer.getBounds().pad(.5), {
        maxZoom: 15, duration: .55,
        paddingTopLeft: [25, 85],
        paddingBottomRight: [25, Math.min(345, Math.round(window.innerHeight * .43))]
      });
    }
    touch();
  }

  function switchTab(tab) {
    state.activeTab = tab;
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
    if (state.gpsMarker) state.map.removeLayer(state.gpsMarker);
    if (state.accuracyCircle) state.map.removeLayer(state.accuracyCircle);
    state.accuracyCircle = L.circle([gps.lat, gps.lon], {
      radius: Math.max(6, Math.min(gps.accuracy, 500)),
      color: '#e57ac6', weight: 1.5, fillColor: '#e57ac6', fillOpacity: .12
    }).addTo(state.markerGroup);
    state.gpsMarker = L.marker([gps.lat, gps.lon], {
      icon: L.divIcon({
        className: 'user-position', html: '<div class="gps-marker"></div>',
        iconSize: [24, 24], iconAnchor: [12, 12]
      }), zIndexOffset: 2000
    }).addTo(state.markerGroup).bindTooltip('ТЫ ЗДЕСЬ', {
      permanent: true, direction: 'top', offset: [0, -14], className: 'you-label'
    });
    // Never jump away from Magnitogorsk if the tester is in a different city.
    if (focus) {
      const fromCity = distanceM(gps.lat, gps.lon, CITY[0], CITY[1]);
      if (fromCity < 18000) state.map.flyTo([gps.lat, gps.lon], Math.max(state.map.getZoom(), 15), { duration: .65 });
      else feedback('Ты сейчас далеко от Магнитогорска. Метка сохранена на карте.');
    }
  }
  async function locate(focus = true, auto = false) {
    if (state.locating) return state.gps;
    state.locating = true;
    ui.locate.classList.add('is-loading');
    renderSelection();
    try {
      let gps;
      if (tg?.LocationManager) {
        try { gps = await telegramLocation(); }
        catch (_) { gps = await browserLocation(); }
      } else gps = await browserLocation();
      if (!Number.isFinite(gps.lat) || !Number.isFinite(gps.lon)) throw new Error('GPS вернул неверные координаты.');
      state.gps = gps;
      drawLocation(gps, focus);
      if (!auto) feedback('Местоположение найдено · точность ±' + Math.round(gps.accuracy) + ' м', 'success');
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
    if (tg?.LocationManager?.isAccessGranted) {
      locate(false, true).catch(() => {});
      return;
    }
    if (navigator.permissions?.query) {
      navigator.permissions.query({ name: 'geolocation' })
        .then(result => { if (result.state === 'granted') locate(false, true).catch(() => {}); })
        .catch(() => {});
    }
  }

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
      ui.captureLabel.textContent = 'ИГРА НЕДОСТУПНА';
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

  ui.locate.addEventListener('click', () => { locate(true).catch(() => {}); });
  ui.refresh.addEventListener('click', () => { load(); });
  ui.top.addEventListener('click', () => { switchTab('top'); });
  ui.mapTab.addEventListener('click', () => { switchTab('map'); });
  ui.topTab.addEventListener('click', () => { switchTab('top'); });
  ui.rulesTab.addEventListener('click', () => { switchTab('rules'); });
  ui.capture.addEventListener('click', capture);
  setInterval(() => { if (selectedZone() && !state.capturing && !state.locating) renderSelection(); }, 1000);

  tg?.BackButton?.show();
  tg?.BackButton?.onClick(() => { window.location.href = './index.html'; });
  if (createMap()) {
    load().then(autoLocateIfGranted);
  }
})();