/* Offline road-alignment checks for the game map. Run: node tests/city_roads.cjs */
'use strict';
const assert = require('node:assert/strict');
const {roadsToFaces, matchZonePolygons, contains} = require('../miniapp/web/city-roads.js');

const base = [
  [59.060, 53.390], [59.061, 53.390],
  [59.061, 53.391], [59.060, 53.391]
];
const way = (a,b) => ({
  properties: {class:'minor'},
  geometry: {type:'LineString', coordinates:[a,b]}
});
const roads = base.map((point,i)=>way(point,base[(i+1)%base.length]));
const polygons = roadsToFaces(roads, {latitude:53.3905});
assert.equal(polygons.length, 1, 'one enclosed block yields one polygon');
assert.ok(polygons[0].area > 6000 && polygons[0].area < 10000,
  'area of block matches actual road geometry');
assert.ok(contains(polygons[0].polygon,53.3905,59.0605), 'inside test point');
assert.ok(!contains(polygons[0].polygon,53.394,59.0605), 'outside test point');
assert.equal(roadsToFaces(roads.slice(0,3)).length,0,
  'open road geometries must not invent closed quarters');
const zone = {id:14,lat:53.3905,lon:59.0605,kind:'district'};
const matched = matchZonePolygons(roads,[zone]);
assert.deepEqual(matched[14].polygon,polygons[0].polygon);
assert.ok(matched[14].area_m2 > 6000);
const duplicate = [...roads,...roads];
assert.equal(roadsToFaces(duplicate).length,1,
  'tile-duplicate edges must not create fake extra faces');
const noZone = matchZonePolygons(roads,[{...zone,id:15,lat:53.395}]);
assert.equal(noZone[15],undefined,'distant zone must not get unrelated road block');
console.log('Live road-aligned game polygons OK');
