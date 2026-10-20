/* Build game sector outlines from OpenMapTiles road geometry.
 * This does not claim to return official district/cadastral boundaries.
 * No network calls: consumes already loaded transportation vector tiles.
 * Coordinates: GeoJSON roads [lon, lat], output Leaflet polygons [lat, lon].
 */
(function (root) {
  'use strict';

  const M = 111320;
  const ACCEPTED = new Set([
    'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
    'residential', 'minor', 'unclassified', 'living_street'
  ]);

  function roadsToFaces(features, opts = {}) {
    const maxSegments = opts.maxSegments || 24000;
    const minArea = opts.minArea || 750;
    const maxArea = opts.maxArea || 4000000;
    const lat0 = Number.isFinite(opts.latitude) ? opts.latitude : 53.4;
    const metresLon = M * Math.cos(lat0 * Math.PI / 180);
    const nodes = new Map();
    const uniqueEdges = new Set();
    let count = 0;

    function getNode(point) {
      const lon = Number(point[0]), lat = Number(point[1]);
      if (!Number.isFinite(lon) || !Number.isFinite(lat) || lon < -180 ||
          lon > 180 || lat < -90 || lat > 90) return null;
      // Snap neighbouring tile endpoints to a roughly metre-sized grid.
      const lonKey = Math.round(lon * 100000);
      const latKey = Math.round(lat * 100000);
      const key = lonKey + ',' + latKey;
      let node = nodes.get(key);
      if (!node) {
        const a = latKey / 100000, b = lonKey / 100000;
        node = {key, lat: a, lon: b, x: b * metresLon, y: a * M, links: new Map()};
        nodes.set(key, node);
      }
      return node;
    }

    for (const feature of features || []) {
      if (count >= maxSegments) break;
      if (!feature || !feature.geometry || !ACCEPTED.has(feature.properties?.class)) continue;
      if (feature.properties?.brunnel === 'bridge' || feature.properties?.brunnel === 'tunnel') continue;
      const geom = feature.geometry;
      if (geom.type !== 'LineString' && geom.type !== 'MultiLineString') continue;
      const lines = geom.type === 'LineString' ? [geom.coordinates] : geom.coordinates;
      for (const line of lines) {
        if (!Array.isArray(line)) continue;
        for (let i = 1; i < line.length && count < maxSegments; i++) {
          const a = getNode(line[i - 1]), b = getNode(line[i]);
          if (!a || !b || a.key === b.key) continue;
          const distance = Math.hypot(a.x - b.x, a.y - b.y);
          if (distance < .6 || distance > 1800) continue;
          const edge = a.key < b.key ? a.key + '|' + b.key : b.key + '|' + a.key;
          if (uniqueEdges.has(edge)) continue;
          uniqueEdges.add(edge);
          a.links.set(b.key, b);
          b.links.set(a.key, a);
          count++;
        }
      }
    }

    if (!count) return [];
    // Clockwise edge rotation traces exactly the street-network faces.
    for (const node of nodes.values()) {
      node.ordered = Array.from(node.links.values())
        .sort((a, b) =>
          Math.atan2(a.y - node.y, a.x - node.x) -
          Math.atan2(b.y - node.y, b.x - node.x));
    }

    const visited = new Set();
    const faces = [];
    const edgeKey = (a, b) => a.key + '>' + b.key;
    for (const start of nodes.values()) {
      for (const outgoing of start.ordered) {
        const initial = edgeKey(start, outgoing);
        if (visited.has(initial)) continue;
        let from = start, to = outgoing;
        const ring = [];
        let closed = false;
        for (let steps = 0; steps < 650; steps++) {
          const directed = edgeKey(from, to);
          if (visited.has(directed)) {
            closed = directed === initial;
            break;
          }
          visited.add(directed);
          ring.push(from);
          const at = to.ordered;
          const reverse = at.findIndex(n => n.key === from.key);
          if (reverse < 0 || !at.length) break;
          const next = at[(reverse - 1 + at.length) % at.length];
          from = to;
          to = next;
          if (edgeKey(from, to) === initial) {
            closed = true;
            break;
          }
        }
        if (!closed || ring.length < 3) continue;
        let twiceArea = 0;
        for (let i = 0; i < ring.length; i++) {
          const a = ring[i], b = ring[(i + 1) % ring.length];
          twiceArea += a.x * b.y - b.x * a.y;
        }
        const area = twiceArea / 2;
        if (area < minArea || area > maxArea) continue; // external face is negative
        const polygon = ring.map(n => [n.lat, n.lon]);
        const bbox = [
          Math.min(...ring.map(n => n.lat)), Math.min(...ring.map(n => n.lon)),
          Math.max(...ring.map(n => n.lat)), Math.max(...ring.map(n => n.lon))
        ];
        faces.push({polygon, area, bbox});
      }
    }
    return faces;
  }

  function contains(polygon, lat, lon) {
    let inside = false;
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      const a = polygon[i], b = polygon[j];
      if ((a[0] > lat) !== (b[0] > lat) &&
          lon < (b[1] - a[1]) * (lat - a[0]) / (b[0] - a[0]) + a[1])
        inside = !inside;
    }
    return inside;
  }

  function matchZonePolygons(features, zones, opts = {}) {
    const faces = roadsToFaces(features, opts);
    const assigned = {};
    const nearest = (zone, face) => {
      if (contains(face.polygon, zone.lat, zone.lon)) return 0;
      const scale = Math.cos(zone.lat * Math.PI / 180);
      let best = Infinity;
      for (const [lat, lon] of face.polygon) {
        best = Math.min(best, Math.hypot((lat - zone.lat) * M,
                                       (lon - zone.lon) * M * scale));
      }
      return best;
    };
    for (const zone of zones || []) {
      if (!Number.isFinite(zone.lat) || !Number.isFinite(zone.lon)) continue;
      const maxArea = zone.kind === 'district' ? 2500000 : 1200000;
      let best = null;
      for (const face of faces) {
        if (face.area > maxArea) continue;
        const distance = nearest(zone, face);
        // A location mapped onto the road itself may be just outside the face.
        if (distance > 25) continue;
        const score = distance * 100 + Math.abs(
          Math.log(Math.max(1, face.area) /
                   (zone.kind === 'district' ? 200000 : 35000))
        ) * 100;
        if (!best || score < best.score) best = {face, score};
      }
      if (best) {
        assigned[zone.id] = {polygon: best.face.polygon, source: 'roads', area_m2: best.face.area};
      }
    }
    return assigned;
  }

  const api = {roadsToFaces, matchZonePolygons, contains};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.MGNRoadBlocks = api;
})(typeof window !== 'undefined' ? window : {});
