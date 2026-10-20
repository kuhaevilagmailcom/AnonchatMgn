/* Regression guard for Telegram Desktop basemap loading.
 * Run with: node tests/city_map_provider.cjs
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = file => fs.readFileSync(path.join(root, file), 'utf8');
const js = source('miniapp/web/city.js');
const html = source('miniapp/web/city.html');
const css = source('miniapp/web/city.css');
const server = source('anonchat/miniapp_api.py');

assert.match(js, /https:\/\/tiles\.openfreemap\.org\/styles\/dark/);
assert.match(js, /https:\/\/tiles\.openfreemap\.org\/styles\/positron/);
assert.match(js, /L\.maplibreGL\(/);
assert.match(js, /getMaplibreMap\(\)/);
assert.match(js, /getMaplibreMap\(\)[\s\S]*?setStyle\(/);
assert.match(js, /function createFallbackLayer\\(/);
assert.match(js, /map\\.attributionControl\\?\\.setPrefix\\(false\\)/);
assert.doesNotMatch(js, /map\\.attributionControl\\?\\.addAttribution\\(/);
assert.match(js, /referrerPolicy: 'strict-origin-when-cross-origin'/);
assert.match(html, /maplibre-gl@5\.24\.0\/dist\/maplibre-gl\.js/);
assert.match(html, /maplibre-gl-leaflet@0\.1\.4\/leaflet-maplibre-gl\.js/);
assert.match(css, /\.leaflet-tile-pane \.leaflet-tile/);
assert.match(css, /\.maplibregl-canvas/);
assert.match(server, /strict-origin-when-cross-origin.*if request\.path\.endswith\("\/city\.html"\)/s);
assert.match(server, /https:\/\/tiles\.openfreemap\.org/);
assert.match(server, /worker-src 'self' blob:/);
new Function(js);
console.log('City map provider, single attribution and CSP checks passed');
