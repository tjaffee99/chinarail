(() => {
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// ---------------------------------------------------------------- rail tile archive
// The rail network is a pre-built vector tileset packed into a few binary chunk
// files (see data/manifest.json); the base map is streamed from OpenFreeMap.
let manifest = null, D = null;
const chunkCache = new Map();
const fileCache = new Map();
function parseChunk(buf, off) {
  const dv = new DataView(buf, off); const n = dv.getUint32(4, true);
  const base = off + 8 + n * 12; const idx = new Map();
  for (let i = 0; i < n; i++) { const o = 8 + i * 12; idx.set(dv.getUint32(o, true), [base + dv.getUint32(o + 4, true), dv.getUint32(o + 8, true)]); }
  return { buf, idx };
}
function fetchBuf(url) {
  return fetch(url).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); });
}
function loadFile(fn) {
  if (!fileCache.has(fn)) {
    const p = fetchBuf('data/tiles/' + fn)
      .catch(e => { fileCache.delete(fn); throw e; });
    fileCache.set(fn, p);
  }
  return fileCache.get(fn);
}
function loadChunk(src, key) {
  const info = manifest[src].chunks[key];
  if (!info) return Promise.resolve(null);
  const id = src + '/' + key;
  if (!chunkCache.has(id)) {
    const p = loadFile(info[0]).then(buf => parseChunk(buf, info[1])).catch(e => { chunkCache.delete(id); throw e; });
    chunkCache.set(id, p);
  }
  return chunkCache.get(id);
}
async function getTile(src, z, x, y) {
  const m = manifest[src];
  if (!m || z < m.minzoom || z > m.maxzoom) return null;
  const key = z <= m.lowmax ? 'low' : ((x >> (z - m.rz)) + '_' + (y >> (z - m.rz)));
  const ch = await loadChunk(src, key);
  if (!ch) return null;
  const e = ch.idx.get(((z << 26) | (x << 13) | y) >>> 0);
  return e ? new Uint8Array(ch.buf, e[0], e[1]) : null;
}
async function gunzip(u8) {
  if (u8[0] !== 0x1f || u8[1] !== 0x8b) return u8.slice().buffer;
  const s = new Blob([u8]).stream().pipeThrough(new DecompressionStream('gzip'));
  return await new Response(s).arrayBuffer();
}
// Glyphs: Latin, Greek and punctuation ranges are served locally; any other
// range (Cyrillic, Thai, Arabic… in base-map labels outside China) falls back to
// OpenFreeMap's Noto Sans. CJK is drawn with the system font (localIdeographFontFamily).
const OFM = 'https://tiles.openfreemap.org';
const GLYPH_RANGES = new Set(['0-255', '256-511', '512-767', '768-1023', '8192-8447', '8448-8703']);
const REMOTE_FONT = { NotoSansMedium: 'Noto Sans Bold', NotoSansRegular: 'Noto Sans Regular' };
maplibregl.addProtocol('tpg', async (params) => {
  const m = params.url.match(/^tpg:\/\/([^/]+)\/([\d-]+)/);
  if (!m) return { data: new ArrayBuffer(0) };
  const font = decodeURIComponent(m[1]).split(',')[0].trim();
  try {
    if (GLYPH_RANGES.has(m[2])) return { data: await fetchBuf('data/glyphs/' + font + '/' + m[2] + '.pbf') };
    const remote = REMOTE_FONT[font] || 'Noto Sans Regular';
    return { data: await fetchBuf(OFM + '/fonts/' + encodeURIComponent(remote) + '/' + m[2] + '.pbf') };
  } catch (_) { return { data: new ArrayBuffer(0) }; }
});
maplibregl.addProtocol('tp', async (params) => {
  const m = params.url.match(/^tp:\/\/(\w+)\/(\d+)\/(\d+)\/(\d+)/);
  const t = await getTile(m[1], +m[2], +m[3], +m[4]);
  return { data: t ? await gunzip(t) : new ArrayBuffer(0) };
});
// ---------------------------------------------------------------- theme + palette
function isDark() {
  const a = document.documentElement.getAttribute('data-theme');
  if (a === 'dark') return true; if (a === 'light') return false;
  return matchMedia('(prefers-color-scheme: dark)').matches;
}
const PAL = {
  light: { land:'#F2F0EB', urban:'#EAE7E0', water:'#A7D2F2', waterLine:'#8FC3EA', park:'#CDE8C0', reserve:'#DDEEDA', airport:'#E6E4EC', uni:'#EEE6DC',
           road:'#FFFFFF', roadCase:'#D6D1C7', motor:'#FFFFFF', motorCase:'#D2CDC3', roadLow:'#D9D5CC', bnd:'#B0A99E', bnd4:'#C9C3B9', bndGlow:'#DDD7CC',
           hsr:'#2E63D6', rail:'#8657D8', track:'#BDB7AE', hsrText:'#1F4BB0', railText:'#6A3FC0', casing:'#FFFFFF', label:'#3A3A3C', label2:'#6C6C72', halo:'rgba(255,255,255,0.92)',
           city:'#2C2C2E', town:'#5A5A60', building:'#E3DFD7', buildingEdge:'#D6D1C7', wood:'#DCEAD2', sand:'#EEE8D8', ice:'#FBFBFD', road2:'#FDFBF6', path:'#CFC9BE', poi:'#7A7A80', waterLabel:'#4A7FAE', stnFill:'#FFFFFF', stnStroke:'#2C2C2E', sel:'#0A7AFF', dimOp:0.22 },
  dark:  { land:'#1F2124', urban:'#26282C', water:'#1A3957', waterLine:'#22476B', park:'#1F3829', reserve:'#1D2B22', airport:'#282830', uni:'#2A2724',
           road:'#3A3D43', roadCase:'#2B2D31', motor:'#43464D', motorCase:'#2F3136', roadLow:'#35383D', bnd:'#6E7177', bnd4:'#46494E', bndGlow:'#2C2F33',
           hsr:'#6D98FF', rail:'#AE8BF5', track:'#55585F', hsrText:'#9DBBFF', railText:'#C7AEFA', casing:'#1E2023', label:'#E9E9EE', label2:'#A1A1A8', halo:'rgba(24,25,28,0.92)',
           city:'#F2F2F7', town:'#C4C4CA', building:'#2B2D31', buildingEdge:'#35383D', wood:'#1E2E23', sand:'#2A2823', ice:'#2C3036', road2:'#36393F', path:'#44474D', poi:'#8E8E95', waterLabel:'#7FA8D0', stnFill:'#1E2023', stnStroke:'#E9E9EE', sel:'#3D9BFF', dimOp:0.2 }
};
let P = PAL[isDark() ? 'dark' : 'light'];

// ---------------------------------------------------------------- state
const MODES = [
  { k: 'h', name: 'High-speed', layers: ['rail-h', 'rail-h-case'], stn: ['h'] },
  { k: 'r', name: 'Rail', layers: ['rail-r', 'rail-r-dash'], stn: ['r'] },
  { k: 'm', name: 'Metro', layers: ['u-m', 'u-s'], stn: [] },
  { k: 'l', name: 'Light rail', layers: ['u-l'], stn: [] },
  { k: 't', name: 'Tram', layers: ['u-t', 'u-f'], stn: [] },
];
const vis = { h: true, r: true, m: true, l: true, t: true };
let labelMode = 'both';
let sel = null;          // selected line id
let selStation = null;
const view = { stack: [] };

// ---------------------------------------------------------------- style
const W = (pairs) => ['interpolate', ['exponential', 1.5], ['zoom'], ...pairs.flat()];
function nameField(big) {
  if (labelMode === 'en') return ['get', 'n'];
  if (labelMode === 'zh') return ['get', 'z'];
  return ['case', ['any', ['==', ['get', 'n'], ['get', 'z']], ['==', ['get', 'n'], '']], ['get', 'z'],
    ['format', ['get', 'n'], {}, '\n', {}, ['get', 'z'], { 'font-scale': 0.86, 'text-color': P.label2 }]];
}
// station name with a row of route bullets underneath (image generated on demand: see styleimagemissing)
function nameWithBullets() {
  const img = ['image', ['concat', 'bs|', ['to-string', ['get', 'i']]]];
  const n = ['get', 'n'], z = ['get', 'z'];
  if (labelMode === 'en') return ['format', n, {}, '\n', {}, img, {}];
  if (labelMode === 'zh') return ['format', z, {}, '\n', {}, img, {}];
  return ['case', ['any', ['==', n, z], ['==', n, '']], ['format', z, {}, '\n', {}, img, {}],
    ['format', n, {}, '\n', {}, z, { 'font-scale': 0.86, 'text-color': P.label2 }, '\n', {}, img, {}]];
}
// POI categories: [OpenMapTiles classes, light label colour, dark label colour]; dot colour = light colour
const POI_COLORS = {
  food: ['#F08A24', '#C8660B', '#F7A95A'], shop: ['#E6A700', '#A87A00', '#F2C94C'], hotel: ['#8E5CE6', '#7443CC', '#B596F2'],
  health: ['#E5484D', '#C53034', '#F07B7F'], edu: ['#9B7652', '#7D5A38', '#C6A27E'], park: ['#35A457', '#1F8440', '#6CCB86'],
  culture: ['#D8508F', '#B53574', '#EC89B7'], transport: ['#2E80E6', '#1C62BA', '#72A9F0'], other: ['#8E8E93', '#6C6C72', '#A1A1A8'],
};
const POI_CAT = ['match', ['get', 'class'],
  ['restaurant', 'fast_food', 'cafe', 'bar', 'beer', 'ice_cream', 'bakery', 'food_court', 'pub'], 'food',
  ['shop', 'grocery', 'clothing_store', 'supermarket', 'mall', 'department_store', 'jewelry', 'books', 'gift', 'shoes', 'hardware', 'mobile_phone', 'electronics', 'furniture', 'convenience', 'alcohol_shop', 'bag', 'cosmetics', 'florist', 'hairdresser', 'optician'], 'shop',
  ['lodging', 'hotel'], 'hotel',
  ['hospital', 'pharmacy', 'doctors', 'dentist', 'clinic', 'veterinary'], 'health',
  ['college', 'school', 'library', 'kindergarten', 'university'], 'edu',
  ['park', 'garden', 'playground', 'zoo', 'campsite', 'golf', 'stadium', 'pitch', 'sports_centre', 'swimming_pool', 'attraction'], 'park',
  ['museum', 'art_gallery', 'theatre', 'cinema', 'music', 'castle', 'monument', 'place_of_worship', 'religion', 'historic', 'arts_centre'], 'culture',
  ['airport', 'harbor', 'ferry_terminal', 'parking', 'fuel', 'car', 'bicycle_rental'], 'transport',
  'other'];
function makePoiDot(color) {
  const s = 13 * DPR; const [c, ctx] = canvas(s, s);
  ctx.beginPath(); ctx.arc(s / 2, s / 2, 5.3 * DPR, 0, 7); ctx.fillStyle = color; ctx.fill();
  ctx.lineWidth = 1.5 * DPR; ctx.strokeStyle = '#FFFFFF'; ctx.stroke();
  ctx.beginPath(); ctx.arc(s / 2, s / 2, 1.7 * DPR, 0, 7); ctx.fillStyle = '#FFFFFF'; ctx.fill();
  return img(c);
}
// base map (OpenMapTiles schema) names
const EN = ['coalesce', ['get', 'name:en'], ['get', 'name_en'], ['get', 'name:latin'], ['get', 'name']];
const ZH = ['coalesce', ['get', 'name:zh'], ['get', 'name']];
function baseName() {
  if (labelMode === 'en') return EN;
  if (labelMode === 'zh') return ZH;
  return ['case', ['==', EN, ZH], ZH, ['format', EN, {}, '\n', {}, ZH, { 'font-scale': 0.86, 'text-color': P.label2 }]];
}
function modeFilter(ks) { return ['in', ['get', 'k'], ['literal', ks]]; }
function stnModeFilter() {
  const ks = [];
  if (vis.h) ks.push('h'); if (vis.r) ks.push('r');
  if (vis.m || vis.l) ks.push('m'); if (vis.t) ks.push('t', 'f');
  return ks;
}
function buildStyle() {
  const selKey = sel == null ? '|none|' : '|' + sel + '|';
  const dim = sel == null ? 1 : P.dimOp;
  const L = [];
  L.push({ id: 'bg', type: 'background', paint: { 'background-color': P.land } });
  // ---- base map: OpenFreeMap / OpenMapTiles
  const B = { source: 'base' };
  const cls = (...c) => ['in', ['get', 'class'], ['literal', c]];
  L.push({ ...B, id: 'landcover', type: 'fill', 'source-layer': 'landcover', filter: cls('wood', 'forest', 'grass', 'wetland', 'sand', 'ice', 'glacier', 'rock'),
    paint: { 'fill-color': ['match', ['get', 'class'], ['wood', 'forest'], P.wood, ['sand', 'rock'], P.sand, ['ice', 'glacier'], P.ice, P.park], 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 3, 0.45, 10, 0.7, 14, 0.85] } });
  L.push({ ...B, id: 'landuse', type: 'fill', 'source-layer': 'landuse', filter: cls('residential', 'suburb', 'neighbourhood', 'commercial', 'industrial', 'retail', 'railway', 'quarry'),
    paint: { 'fill-color': P.urban, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 9, 1, 15, 0.8] } });
  L.push({ ...B, id: 'landuse-civic', type: 'fill', 'source-layer': 'landuse', minzoom: 11, filter: cls('school', 'university', 'college', 'hospital', 'kindergarten', 'stadium', 'pitch', 'cemetery', 'playground', 'zoo', 'theme_park'),
    paint: { 'fill-color': ['match', ['get', 'class'], ['stadium', 'pitch', 'playground', 'zoo', 'theme_park', 'cemetery'], P.park, P.uni] } });
  L.push({ ...B, id: 'park', type: 'fill', 'source-layer': 'park',
    paint: { 'fill-color': ['match', ['get', 'class'], ['national_park', 'nature_reserve', 'protected_area'], P.reserve, P.park], 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 4, 0.5, 10, 0.9] } });
  L.push({ ...B, id: 'aeroway-area', type: 'fill', 'source-layer': 'aeroway', minzoom: 10, filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': P.airport } });
  L.push({ ...B, id: 'aeroway-runway', type: 'line', 'source-layer': 'aeroway', minzoom: 11, filter: ['all', ['==', ['geometry-type'], 'LineString'], cls('runway', 'taxiway')],
    paint: { 'line-color': P.roadCase, 'line-width': ['interpolate', ['exponential', 1.5], ['zoom'], 11, ['match', ['get', 'class'], 'runway', 2, 0.5], 17, ['match', ['get', 'class'], 'runway', 40, 10]] } });
  L.push({ ...B, id: 'waterway', type: 'line', 'source-layer': 'waterway', filter: ['any', cls('river', 'canal'), ['>=', ['zoom'], 13]], layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': P.water, 'line-width': ['interpolate', ['exponential', 1.5], ['zoom'], 8, ['match', ['get', 'class'], 'river', 0.8, 0.4], 14, ['match', ['get', 'class'], ['river', 'canal'], 3, 1], 18, ['match', ['get', 'class'], ['river', 'canal'], 12, 3]] } });
  L.push({ ...B, id: 'water', type: 'fill', 'source-layer': 'water', filter: ['!=', ['get', 'brunnel'], 'tunnel'], paint: { 'fill-color': P.water } });
  L.push({ ...B, id: 'building', type: 'fill', 'source-layer': 'building', minzoom: 14,
    paint: { 'fill-color': P.building, 'fill-outline-color': P.buildingEdge, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 14, 0, 15, 1] } });
  L.push({ ...B, id: 'bnd4', type: 'line', 'source-layer': 'boundary', minzoom: 4, filter: ['all', ['==', ['get', 'admin_level'], 4], ['!=', ['get', 'maritime'], 1]], layout: { 'line-join': 'round' },
    paint: { 'line-color': P.bnd4, 'line-width': W([[4, 0.6], [10, 1.2], [14, 2]]), 'line-dasharray': [3, 2] } });
  const bnd2 = ['all', ['==', ['get', 'admin_level'], 2], ['!=', ['get', 'maritime'], 1]];
  L.push({ ...B, id: 'bnd2-glow', type: 'line', 'source-layer': 'boundary', filter: ['all', bnd2, ['!=', ['get', 'disputed'], 1]], layout: { 'line-join': 'round' },
    paint: { 'line-color': P.bndGlow, 'line-width': W([[3, 3], [10, 8]]), 'line-opacity': 0.55 } });
  L.push({ ...B, id: 'bnd2', type: 'line', 'source-layer': 'boundary', filter: ['all', bnd2, ['!=', ['get', 'disputed'], 1]], layout: { 'line-join': 'round' },
    paint: { 'line-color': P.bnd, 'line-width': W([[3, 0.9], [10, 1.8]]) } });
  L.push({ ...B, id: 'bnd2-disputed', type: 'line', 'source-layer': 'boundary', filter: ['all', bnd2, ['==', ['get', 'disputed'], 1]], layout: { 'line-join': 'round' },
    paint: { 'line-color': P.bnd, 'line-width': W([[3, 0.9], [10, 1.8]]), 'line-dasharray': [2, 2] } });
  // roads (OpenMapTiles 'transportation'; rail classes are left to our own rail tiles)
  const ROADS = ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'minor', 'service'];
  const roadW = (stops) => ['interpolate', ['exponential', 1.5], ['zoom'], ...stops.flatMap(([z, m, t, p, s, te, mi, sv]) => [z, ['match', ['get', 'class'], 'motorway', m, 'trunk', t, 'primary', p, 'secondary', s, 'tertiary', te, 'minor', mi, sv]])];
  const roadF = ['all', ['==', ['geometry-type'], 'LineString'], cls(...ROADS)];
  const notTunnel = ['!=', ['get', 'brunnel'], 'tunnel'];
  L.push({ ...B, id: 'path', type: 'line', 'source-layer': 'transportation', minzoom: 14, filter: ['all', cls('path', 'track'), notTunnel],
    paint: { 'line-color': P.path, 'line-width': W([[14, 0.6], [18, 1.8]]), 'line-dasharray': [2, 1.5] } });
  L.push({ ...B, id: 'road-tunnel', type: 'line', 'source-layer': 'transportation', minzoom: 12, filter: ['all', roadF, ['==', ['get', 'brunnel'], 'tunnel']], layout: { 'line-join': 'round' },
    paint: { 'line-color': P.roadCase, 'line-opacity': 0.6, 'line-dasharray': [3, 2], 'line-width': roadW([[12, 1.6, 1.4, 1.2, 1, 0.8, 0.5, 0.3], [18, 18, 16, 15, 13, 12, 10, 5]]) } });
  L.push({ ...B, id: 'road-case', type: 'line', 'source-layer': 'transportation', minzoom: 11, filter: ['all', roadF, notTunnel], layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': ['match', ['get', 'class'], ['motorway', 'trunk'], P.motorCase, P.roadCase], 'line-width': roadW([[11, 3.2, 2.9, 2.6, 2.2, 1.8, 1.2, 0.6], [14, 7, 6.4, 6, 5.2, 4.4, 3.6, 2], [18, 26, 24, 22, 20, 18, 15, 8]]) } });
  L.push({ ...B, id: 'road', type: 'line', 'source-layer': 'transportation', minzoom: 5, filter: ['all', roadF, notTunnel,
      ['any', ['>=', ['zoom'], 11], cls('motorway', 'trunk', 'primary'), ['all', ['>=', ['zoom'], 8], cls('secondary')], ['all', ['>=', ['zoom'], 9.5], cls('tertiary')]]],
    layout: { 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': ['step', ['zoom'], P.roadLow, 11, ['match', ['get', 'class'], ['minor', 'service'], P.road2, ['motorway', 'trunk'], P.motor, P.road]],
      'line-width': roadW([[5, 0.5, 0.4, 0.3, 0.2, 0.2, 0.2, 0.1], [8, 1, 0.9, 0.7, 0.5, 0.4, 0.3, 0.2], [11, 1.6, 1.4, 1.2, 1, 0.8, 0.5, 0.3], [14, 5, 4.6, 4.2, 3.6, 3, 2.4, 1.2], [18, 22, 20, 18, 16, 14, 12, 6]]) } });
  // intercity rail
  const on = k => vis[k] ? 'visible' : 'none';
  const kindColor = ['match', ['get', 'k'], 'h', P.hsr, 'r', P.rail, P.track];
  L.push({ id: 'rail-x', type: 'line', source: 'rail', 'source-layer': 'rail', minzoom: 8, filter: ['==', ['get', 'k'], 'x'], layout: { visibility: vis.r ? 'visible' : 'none', 'line-join': 'round' },
    paint: { 'line-color': P.track, 'line-opacity': sel == null ? 0.9 : 0.4, 'line-width': W([[8, 0.5], [12, 1.1], [16, 2.2]]) } });
  L.push({ id: 'rail-r-case', type: 'line', source: 'rail', 'source-layer': 'rail', minzoom: 8, filter: ['==', ['get', 'k'], 'r'], layout: { visibility: on('r'), 'line-join': 'round' },
    paint: { 'line-color': P.casing, 'line-opacity': dim, 'line-width': W([[8, 3], [12, 5], [15, 7.4], [18, 10]]) } });
  L.push({ id: 'rail-r', type: 'line', source: 'rail', 'source-layer': 'rail', filter: ['==', ['get', 'k'], 'r'], layout: { visibility: on('r'), 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': P.rail, 'line-opacity': dim, 'line-width': W([[3, 0.55], [5, 0.85], [7, 1.25], [9, 1.8], [12, 2.8], [15, 4.4], [18, 6.2]]) } });
  L.push({ id: 'rail-h-case', type: 'line', source: 'rail', 'source-layer': 'rail', minzoom: 6, filter: ['==', ['get', 'k'], 'h'], layout: { visibility: on('h'), 'line-join': 'round' },
    paint: { 'line-color': P.casing, 'line-opacity': dim, 'line-width': W([[6, 3], [9, 4.6], [12, 6.2], [15, 8.4], [18, 11.5]]) } });
  L.push({ id: 'rail-h', type: 'line', source: 'rail', 'source-layer': 'rail', filter: ['==', ['get', 'k'], 'h'], layout: { visibility: on('h'), 'line-join': 'round', 'line-cap': 'round' },
    paint: { 'line-color': P.hsr, 'line-opacity': dim, 'line-width': W([[3, 0.9], [5, 1.35], [7, 1.9], [9, 2.6], [12, 3.6], [15, 5.2], [18, 7.5]]) } });
  // urban rail
  const ucase = { type: 'line', source: 'rail', 'source-layer': 'rail', minzoom: 10, layout: { 'line-join': 'round', 'line-cap': 'round' } };
  L.push(Object.assign({ id: 'u-case', filter: ['in', ['get', 'k'], ['literal', ['m', 'l', 's', 't']]], paint: { 'line-color': P.casing, 'line-opacity': sel == null ? 0.95 : 0.3, 'line-width': ['interpolate', ['exponential', 1.5], ['zoom'], 10, ['match', ['get', 'k'], 't', 2.8, 'l', 3.6, 4.4], 14, ['match', ['get', 'k'], 't', 5.5, 'l', 7.5, 9], 17, ['match', ['get', 'k'], 't', 9, 'l', 12, 14]] } }, ucase));
  const uline = (id, k, w, extra = {}) => ({ id, type: 'line', source: 'rail', 'source-layer': 'rail', filter: ['==', ['get', 'k'], k], layout: Object.assign({ visibility: on(id === 'u-s' ? 'm' : id === 'u-f' ? 't' : k), 'line-join': 'round', 'line-cap': 'round' }, extra.layout || {}), paint: Object.assign({ 'line-color': ['coalesce', ['get', 'c'], P.rail], 'line-opacity': dim, 'line-width': W(w) }, extra.paint || {}) });
  L.push(uline('u-t', 't', [[9, 0.8], [12, 1.8], [14, 3], [17, 6]]));
  L.push(uline('u-f', 'f', [[11, 1], [14, 2], [17, 4]], { paint: { 'line-dasharray': [1, 1] } }));
  L.push(uline('u-l', 'l', [[8, 0.8], [11, 1.8], [14, 4.4], [17, 8.5]]));
  L.push(uline('u-s', 's', [[7, 0.8], [10, 1.6], [12, 2.8], [14, 4.8], [17, 9.5]]));
  L.push(uline('u-m', 'm', [[7, 0.9], [9, 1.6], [11, 2.6], [12, 3.4], [14, 5.6], [17, 11]]));
  // line names along intercity lines, and route bullets along metro lines
  const shownKinds = ['h', 'r'].filter(k => vis[k]);
  L.push({ id: 'rail-name', type: 'symbol', source: 'rail', 'source-layer': 'rail', minzoom: 6, maxzoom: 12, filter: ['all', ['has', 'nm'], ['in', ['get', 'k'], ['literal', shownKinds]]],
    layout: { visibility: sel == null ? 'visible' : 'none', 'symbol-placement': 'line', 'symbol-spacing': 520, 'text-field': labelMode === 'zh' ? ['get', 'nz'] : ['get', 'nm'],
      'text-font': ['NotoSansMedium'], 'text-size': ['interpolate', ['linear'], ['zoom'], 6, 10.5, 11, 12.5], 'text-max-angle': 28, 'text-letter-spacing': 0.02, 'text-padding': 6,
      'symbol-sort-key': ['match', ['get', 'k'], 'h', 0, 1] },
    paint: { 'text-color': ['match', ['get', 'k'], 'h', P.hsrText, P.railText], 'text-halo-color': P.halo, 'text-halo-width': 2 } });
  L.push({ id: 'badges', type: 'symbol', source: 'rail', 'source-layer': 'rail', minzoom: 12, filter: ['all', modeFilter(['m', 'l', 's']), ['!=', ['coalesce', ['get', 'r'], ''], '']],
    layout: { 'symbol-placement': 'line', 'symbol-spacing': 420, 'icon-image': ['concat', 'b|', ['get', 'c'], '|', ['get', 'r']], 'icon-rotation-alignment': 'viewport', 'icon-size': 1, 'icon-padding': 4, visibility: sel == null ? 'visible' : 'none' } });
  // selection
  const selF = ['in', selKey, ['get', 'ls']];
  L.push({ id: 'sel-case', type: 'line', source: 'rail', 'source-layer': 'rail', filter: selF, layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': P.casing, 'line-width': W([[3, 3.4], [8, 5.6], [12, 8.4], [14, 11], [17, 16]]) } });
  L.push({ id: 'sel-line', type: 'line', source: 'rail', 'source-layer': 'rail', filter: selF, layout: { 'line-join': 'round', 'line-cap': 'round' }, paint: { 'line-color': sel != null && D ? lineColor(sel) : P.sel, 'line-width': W([[3, 1.8], [8, 3.2], [12, 5], [14, 7], [17, 11]]) } });
  // intercity stations: white dots ringed in the line colour, hubs ringed dark; train glyph from z11
  const sk = stnModeFilter();
  const hub = ['any', ['>=', ['get', 'rk'], 10], ['>', ['get', 'x'], 2]];
  L.push({ id: 'stn-rail', type: 'symbol', source: 'rail', 'source-layer': 'stn', filter: ['in', ['get', 'k'], ['literal', sk.filter(k => k === 'h' || k === 'r')]],
    layout: { 'icon-image': ['step', ['zoom'], ['case', hub, 'hub', ['match', ['get', 'k'], 'h', 'dot-h', 'dot-r']], 11, ['match', ['get', 'k'], 'h', 'st-h', 'st-r']],
      'icon-size': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 8, 0.85, 11, 0.8, 14, 1], 'icon-allow-overlap': true, 'icon-ignore-placement': true,
      'symbol-sort-key': ['-', 0, ['get', 'rk']],
      'text-field': sel != null ? '' : ['step', ['zoom'], ['case', ['>=', ['get', 'rk'], 11], nameField(), ''], 7, ['case', ['>=', ['get', 'rk'], 8], nameField(), ''], 9, ['case', ['>=', ['get', 'rk'], 5], nameField(), ''], 11, nameField()],
      'text-font': ['case', hub, ['literal', ['NotoSansMedium']], ['literal', ['NotoSansRegular']]],
      'text-size': ['interpolate', ['linear'], ['zoom'], 5, ['case', hub, 12, 10.5], 10, ['case', hub, 14, 12], 16, ['case', hub, 16, 13.5]],
      'text-justify': 'auto', 'text-optional': true, 'text-max-width': 12, 'text-line-height': 1.15,
      'text-variable-anchor': ['left', 'right', 'top', 'bottom'], 'text-radial-offset': ['step', ['zoom'], 0.7, 11, 1.05] },
    paint: { 'text-color': ['case', hub, P.label, P.label2], 'text-halo-color': P.halo, 'text-halo-width': 1.8,
      'icon-opacity': sel != null ? 0.35 : ['step', ['zoom'], ['case', ['>=', ['get', 'rk'], 8], 1, 0], 6, ['case', ['>=', ['get', 'rk'], 5], 1, 0], 8, 1],
      'text-opacity': sel == null ? 1 : 0.35 } });
  const uk = ['in', ['get', 'k'], ['literal', sk.filter(k => k === 'm' || k === 't' || k === 'f')]];
  // metro station dots as icons (not circles) so that route badges and labels avoid them
  const th = isDark() ? 'D' : 'L';
  const uDot = (id, minzoom, extra, transfer) => ({ id, type: 'symbol', source: 'rail', 'source-layer': 'stn', minzoom, filter: ['all', uk, extra],
    layout: { 'icon-image': transfer ? 'hubm|' + th : ['concat', 'sd|' + th + '|', ['coalesce', ['get', 'c'], '#888888']],
      'icon-size': ['interpolate', ['linear'], ['zoom'], 11, transfer ? 0.42 : 0.38, 14, transfer ? 0.85 : 0.78, 17, transfer ? 1.3 : 1.15],
      'icon-allow-overlap': true, 'icon-padding': 0, 'symbol-sort-key': ['-', 0, ['get', 'x']] },
    paint: { 'icon-opacity': sel == null ? 1 : 0.3 } });
  L.push(uDot('stn-u1', 12, ['<=', ['get', 'x'], 1], false));
  L.push(uDot('stn-u', 11, ['>', ['get', 'x'], 1], true));
  // metro station names; from z14 with the route bullets underneath, as on a transit map
  const uLabel = (id, minzoom, extra) => ({ id, type: 'symbol', source: 'rail', 'source-layer': 'stn', minzoom, filter: ['all', uk, extra],
    layout: { visibility: sel == null ? 'visible' : 'none', 'text-field': ['step', ['zoom'], nameField(), 14.5, nameWithBullets()], 'text-font': ['NotoSansMedium'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 12, 11, 16, 13.5], 'text-variable-anchor': ['left', 'right', 'top', 'bottom'], 'text-radial-offset': 0.85, 'text-justify': 'auto',
      'text-max-width': 10, 'text-line-height': 1.2, 'symbol-sort-key': ['-', 0, ['get', 'x']] },
    paint: { 'text-color': P.label, 'text-halo-color': P.halo, 'text-halo-width': 1.6, 'text-opacity': sel == null ? 1 : 0.3 } });
  L.push(uLabel('stn-u-label', 12, ['>', ['get', 'x'], 1]));
  L.push(uLabel('stn-u1-label', 13.5, ['<=', ['get', 'x'], 1]));
  // selected line stations (always labelled)
  L.push({ id: 'sel-stn', type: 'circle', source: 'rail', 'source-layer': 'stn', filter: selF,
    paint: { 'circle-color': P.stnFill, 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 2.5, 10, 4, 14, 6.5, 17, 8], 'circle-stroke-color': ['case', ['>', ['get', 'x'], 1], P.stnStroke, sel != null && D ? lineColor(sel) : P.stnStroke], 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 5, 1.4, 12, 2.2, 17, 3] } });
  L.push({ id: 'sel-stn-label', type: 'symbol', source: 'rail', 'source-layer': 'stn', filter: selF,
    layout: { 'text-field': nameField(), 'text-font': ['NotoSansMedium'], 'text-size': ['interpolate', ['linear'], ['zoom'], 6, 11, 16, 14], 'text-variable-anchor': ['left', 'right', 'top', 'bottom'], 'text-radial-offset': 0.9, 'text-justify': 'auto', 'text-max-width': 10, 'text-line-height': 1.15, 'symbol-sort-key': ['-', 0, ['get', 'rk']] },
    paint: { 'text-color': P.label, 'text-halo-color': P.halo, 'text-halo-width': 1.8 } });
  L.push({ id: 'sel-pt', type: 'circle', source: 'selpt', paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 7, 14, 12, 17, 16], 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': P.sel, 'circle-stroke-width': 3 } });
  // ---- base map labels
  const halo = { 'text-halo-color': P.halo, 'text-halo-width': 1.5 };
  const waterName = (id, geom, extra) => ({ ...B, id, type: 'symbol', 'source-layer': 'water_name', filter: ['==', ['geometry-type'], geom], ...extra,
    layout: { 'text-field': baseName(), 'text-font': ['NotoSansRegular'], 'text-size': ['match', ['get', 'class'], 'ocean', 14, 'sea', 12.5, 11.5], 'text-max-width': 6, 'text-letter-spacing': 0.08, 'symbol-placement': geom === 'Point' ? 'point' : 'line' },
    paint: { 'text-color': P.waterLabel, ...halo } });
  L.push(waterName('water-name', 'Point', {}));
  L.push(waterName('water-name-line', 'LineString', { minzoom: 10 }));
  L.push({ ...B, id: 'waterway-name', type: 'symbol', 'source-layer': 'waterway', minzoom: 12, filter: cls('river', 'canal'),
    layout: { 'text-field': baseName(), 'text-font': ['NotoSansRegular'], 'text-size': 11, 'symbol-placement': 'line', 'symbol-spacing': 400 },
    paint: { 'text-color': P.waterLabel, ...halo } });
  L.push({ ...B, id: 'road-name', type: 'symbol', 'source-layer': 'transportation_name', minzoom: 13, filter: cls('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'minor'),
    layout: { 'text-field': baseName(), 'text-font': ['NotoSansRegular'], 'text-size': ['interpolate', ['linear'], ['zoom'], 13, 10, 17, 12.5], 'symbol-placement': 'line', 'symbol-spacing': 350, 'text-max-angle': 30, 'text-padding': 2, 'text-line-height': 1 },
    paint: { 'text-color': P.label2, ...halo } });
  // points of interest: colour-coded by category, label in the same hue (as Apple Maps does)
  const poiF = ['all', ['<=', ['get', 'rank'], ['step', ['zoom'], 3, 16, 12, 17, 30]], ['!', cls('railway', 'bus', 'aerialway')]];
  L.push({ ...B, id: 'poi', type: 'symbol', 'source-layer': 'poi', minzoom: 15, filter: poiF,
    layout: { 'icon-image': ['concat', 'pc|', POI_CAT], 'icon-size': 1, 'text-field': baseName(), 'text-font': ['NotoSansMedium'], 'text-size': 11, 'text-max-width': 8,
      'text-anchor': 'left', 'text-offset': [0.85, 0], 'text-line-height': 1.1, 'text-optional': true, 'symbol-sort-key': ['get', 'rank'], 'text-padding': 3 },
    paint: { 'text-color': ['match', POI_CAT, ...Object.entries(POI_COLORS).flatMap(([k, v]) => [k, isDark() ? v[2] : v[1]]), P.poi], ...halo } });
  L.push({ ...B, id: 'road-shield', type: 'symbol', 'source-layer': 'transportation_name', minzoom: 7,
    filter: ['all', ['has', 'ref'], cls('motorway', 'trunk', 'primary'), ['any', cls('motorway'), ['>=', ['zoom'], 10]]],
    layout: { 'symbol-placement': 'line', 'symbol-spacing': ['interpolate', ['linear'], ['zoom'], 7, 300, 14, 600], 'icon-rotation-alignment': 'viewport', 'icon-padding': 6,
      'icon-image': ['concat', 'sh|', ['match', ['get', 'class'], 'motorway', 'm', 'o'], '|',
        ['let', 'r', ['get', 'ref'], ['slice', ['var', 'r'], 0, ['case', ['>=', ['index-of', ';', ['var', 'r']], 0], ['index-of', ';', ['var', 'r']], ['min', ['length', ['var', 'r']], 7]]]]] } });
  L.push({ ...B, id: 'airport', type: 'symbol', 'source-layer': 'aerodrome_label', minzoom: 8, filter: ['has', 'iata'],
    layout: { 'icon-image': 'ap', 'icon-size': ['interpolate', ['linear'], ['zoom'], 8, 0.8, 12, 1], 'text-field': ['step', ['zoom'], ['get', 'iata'], 11, baseName()], 'text-font': ['NotoSansMedium'],
      'text-size': ['interpolate', ['linear'], ['zoom'], 8, 11, 14, 13], 'text-max-width': 8, 'text-anchor': 'left', 'text-offset': [1.05, 0], 'text-optional': true, 'text-padding': 4 },
    paint: { 'text-color': isDark() ? '#6FB1FF' : '#1767D2', ...halo } });
  const place = (id, classes, minzoom, size, font, color, extra = {}) => ({ ...B, id, type: 'symbol', 'source-layer': 'place', minzoom, filter: ['all', cls(...classes), ...(extra.filter || [])],
    layout: Object.assign({ 'text-field': baseName(), 'text-font': [font], 'text-size': size, 'text-max-width': 8, 'text-line-height': 1.1, 'symbol-sort-key': ['get', 'rank'], 'text-padding': 4 }, extra.layout || {}),
    paint: Object.assign({ 'text-color': color, ...halo }, extra.paint || {}) });
  L.push(place('place-s', ['suburb', 'quarter', 'neighbourhood'], 12, ['interpolate', ['linear'], ['zoom'], 12, 10, 16, 12], 'NotoSansRegular', P.town, { layout: { 'text-transform': 'uppercase', 'text-letter-spacing': 0.06 }, paint: { 'text-opacity': 0.75 } }));
  L.push(place('place-v', ['village', 'hamlet'], 12, ['interpolate', ['linear'], ['zoom'], 12, 10.5, 16, 12.5], 'NotoSansRegular', P.town));
  L.push(place('place-t', ['town'], 9, ['interpolate', ['linear'], ['zoom'], 9, 11, 14, 13.5], 'NotoSansRegular', P.town));
  L.push(place('place-c', ['city'], 3, ['interpolate', ['linear'], ['zoom'], 3, ['case', ['==', ['get', 'capital'], 2], 13, ['<=', ['get', 'rank'], 3], 12, 11], 10, ['case', ['==', ['get', 'capital'], 2], 18, ['<=', ['get', 'rank'], 4], 16, 14], 14, 17], 'NotoSansMedium', P.city,
    { filter: [['<=', ['coalesce', ['get', 'rank'], 99], ['step', ['zoom'], 5, 5, 8, 6, 11, 7, 99]]] }));
  L.push(place('place-state', ['state', 'province'], 4, ['interpolate', ['linear'], ['zoom'], 4, 10.5, 7, 13], 'NotoSansRegular', P.label2,
    { layout: { 'text-transform': 'uppercase', 'text-letter-spacing': 0.1, 'text-max-width': 7 }, paint: { 'text-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.8, 8, 0] } }));
  L.push(place('place-country', ['country'], 1, ['interpolate', ['linear'], ['zoom'], 1, 11, 5, 15], 'NotoSansMedium', P.label2,
    { layout: { 'text-transform': 'uppercase', 'text-letter-spacing': 0.12, 'text-max-width': 6 }, paint: { 'text-opacity': ['interpolate', ['linear'], ['zoom'], 6, 1, 7, 0] } }));
  return {
    version: 8,
    glyphs: 'tpg://{fontstack}/{range}',
    sources: {
      base: { type: 'vector', url: OFM + '/planet' },
      rail: { type: 'vector', tiles: ['tp://rail/{z}/{x}/{y}'], minzoom: 3, maxzoom: 12, bounds: [72, 16, 136.6, 54.6] },
      selpt: { type: 'geojson', data: { type: 'FeatureCollection', features: selStation == null || !D ? [] : [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [D.stations[selStation][2], D.stations[selStation][3]] } }] } },
    },
    layers: L,
  };
}

// ---------------------------------------------------------------- images (badges, station icons)
const DPR = Math.min(3, Math.max(2, window.devicePixelRatio || 1));
function lum(hex) {
  const h = hex.replace('#', ''); const r = parseInt(h.slice(0, 2), 16) / 255, g = parseInt(h.slice(2, 4), 16) / 255, b = parseInt(h.slice(4, 6), 16) / 255;
  const f = v => v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
function textOn(hex) { return lum(hex || '#888888') > 0.52 ? '#1C1C1E' : '#FFFFFF'; }
function makeBadge(color, text) {
  const fs = 11 * DPR, h = 17 * DPR, pad = 4.5 * DPR;
  const c = document.createElement('canvas'); const ctx = c.getContext('2d');
  ctx.font = `700 ${fs}px -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif`;
  const w = Math.max(h, Math.ceil(ctx.measureText(text).width + pad * 2));
  c.width = w + 2 * DPR; c.height = h + 2 * DPR;
  ctx.font = `700 ${fs}px -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif`;
  const r = 4.5 * DPR;
  ctx.fillStyle = '#FFFFFF';
  rr(ctx, 0, 0, w + 2 * DPR, h + 2 * DPR, r + DPR); ctx.fill();
  ctx.fillStyle = color; rr(ctx, DPR, DPR, w, h, r); ctx.fill();
  ctx.fillStyle = textOn(color); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(text, DPR + w / 2, DPR + h / 2 + 0.5 * DPR);
  return { width: c.width, height: c.height, data: ctx.getImageData(0, 0, c.width, c.height).data };
}
function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
function makeTrainIcon(bg) {
  const s = 20 * DPR; const c = document.createElement('canvas'); c.width = s; c.height = s; const ctx = c.getContext('2d');
  ctx.fillStyle = '#FFFFFF'; rr(ctx, 0, 0, s, s, 5.5 * DPR); ctx.fill();
  ctx.fillStyle = bg; rr(ctx, 1.5 * DPR, 1.5 * DPR, s - 3 * DPR, s - 3 * DPR, 4.5 * DPR); ctx.fill();
  const u = DPR; ctx.fillStyle = '#FFFFFF';
  rr(ctx, 6 * u, 4.2 * u, 8 * u, 9.2 * u, 2.4 * u); ctx.fill();
  ctx.fillStyle = bg; rr(ctx, 7.3 * u, 5.6 * u, 5.4 * u, 3.4 * u, 0.8 * u); ctx.fill();
  ctx.beginPath(); ctx.arc(8.2 * u, 11 * u, 0.85 * u, 0, 7); ctx.arc(11.8 * u, 11 * u, 0.85 * u, 0, 7); ctx.fill();
  ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 1.3 * u; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.moveTo(7.6 * u, 14.2 * u); ctx.lineTo(6.2 * u, 16 * u); ctx.moveTo(12.4 * u, 14.2 * u); ctx.lineTo(13.8 * u, 16 * u); ctx.stroke();
  return { width: s, height: s, data: ctx.getImageData(0, 0, s, s).data };
}
function canvas(w, h) { const c = document.createElement('canvas'); c.width = Math.ceil(w); c.height = Math.ceil(h); return [c, c.getContext('2d')]; }
function img(c) { return { width: c.width, height: c.height, data: c.getContext('2d').getImageData(0, 0, c.width, c.height).data }; }
// station dot: white disc with a coloured ring (Apple-style)
function makeDot(ring, r, w, fill) {
  const s = (r + w + 1) * 2 * DPR; const [c, ctx] = canvas(s, s);
  ctx.beginPath(); ctx.arc(s / 2, s / 2, r * DPR, 0, 7); ctx.fillStyle = fill; ctx.fill();
  ctx.lineWidth = w * DPR; ctx.strokeStyle = ring; ctx.stroke();
  return img(c);
}
// row of route bullets for a station label
function makeBulletRow(si) {
  const ids = D && D.stations[si] ? sortLines(allLinesAt(si).filter(x => !D.lines[x][10] && 'mlstf'.includes(D.lines[x][0]))).slice(0, 8) : [];
  if (!ids.length) { const [c] = canvas(1, 1); return img(c); }
  const fs = 10.5 * DPR, h = 15 * DPR, pad = 3.5 * DPR, gap = 2.5 * DPR;
  const [m, mctx] = canvas(1, 1); mctx.font = `700 ${fs}px -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif`;
  const items = ids.map(i => { const t = badgeText(D.lines[i]); return { t, col: D.lines[i][4] || (D.lines[i][0] === 't' ? '#3FA34D' : '#888888'), w: t ? Math.max(h, mctx.measureText(t).width + pad * 2) : h * 0.7 }; });
  const W = items.reduce((a, b) => a + b.w, 0) + gap * (items.length - 1) + 2 * DPR;
  const [c, ctx] = canvas(W, h + 2 * DPR);
  ctx.font = mctx.font; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  let x = DPR;
  for (const it of items) {
    ctx.fillStyle = '#FFFFFF'; rr(ctx, x - DPR, 0, it.w + 2 * DPR, h + 2 * DPR, 5 * DPR); ctx.fill();
    ctx.fillStyle = it.col;
    if (it.t) { rr(ctx, x, DPR, it.w, h, 4 * DPR); ctx.fill(); ctx.fillStyle = textOn(it.col); ctx.fillText(it.t, x + it.w / 2, DPR + h / 2 + 0.5 * DPR); }
    else { ctx.beginPath(); ctx.arc(x + it.w / 2, DPR + h / 2, it.w / 2, 0, 7); ctx.fill(); }
    x += it.w + gap;
  }
  return img(c);
}
// road shields: expressways green (red band = national G, yellow band = provincial S); other national roads red, provincial yellow
function makeShield(kind, ref) {
  const fs = 10 * DPR, h = 15 * DPR, pad = 4 * DPR;
  const [m, mctx] = canvas(1, 1); const font = `700 ${fs}px -apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif`; mctx.font = font;
  const w = Math.max(h * 1.2, mctx.measureText(ref).width + pad * 2);
  const [c, ctx] = canvas(w + 2 * DPR, h + 2 * DPR); ctx.font = font; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const p = ref[0];
  let bg = '#FFFFFF', fg = '#1C1C1E', band = null;
  if (kind === 'm') { bg = '#1E7B4A'; fg = '#FFFFFF'; band = p === 'G' ? '#D0202E' : p === 'S' ? '#F2B705' : null; }
  else if (p === 'G') { bg = '#C8202E'; fg = '#FFFFFF'; }
  else if (p === 'S') { bg = '#F2B705'; fg = '#1C1C1E'; }
  ctx.fillStyle = '#FFFFFF'; rr(ctx, 0, 0, w + 2 * DPR, h + 2 * DPR, 4 * DPR); ctx.fill();
  ctx.fillStyle = bg; rr(ctx, DPR, DPR, w, h, 3 * DPR); ctx.fill();
  if (bg === '#FFFFFF') { ctx.strokeStyle = '#9A9AA0'; ctx.lineWidth = DPR; rr(ctx, 1.5 * DPR, 1.5 * DPR, w - DPR, h - DPR, 3 * DPR); ctx.stroke(); }
  if (band) { ctx.save(); rr(ctx, DPR, DPR, w, h, 3 * DPR); ctx.clip(); ctx.fillStyle = band; ctx.fillRect(DPR, DPR, w, 3 * DPR); ctx.restore(); }
  ctx.fillStyle = fg; ctx.fillText(ref, DPR + w / 2, DPR + h / 2 + (band ? 1.2 : 0.5) * DPR);
  return img(c);
}
// airport: blue tile with a plane
function makeAirport() {
  const s = 18 * DPR, u = DPR; const [c, ctx] = canvas(s, s);
  ctx.fillStyle = '#FFFFFF'; rr(ctx, 0, 0, s, s, 5 * u); ctx.fill();
  ctx.fillStyle = '#1C7CF4'; rr(ctx, 1.2 * u, 1.2 * u, s - 2.4 * u, s - 2.4 * u, 4 * u); ctx.fill();
  ctx.save(); ctx.translate(s / 2, s / 2); ctx.rotate(Math.PI / 4); ctx.fillStyle = '#FFFFFF';
  ctx.beginPath();
  ctx.moveTo(0, -6 * u); ctx.quadraticCurveTo(1 * u, -6 * u, 1 * u, -4.5 * u); ctx.lineTo(1 * u, -1.2 * u); ctx.lineTo(5.5 * u, 1.3 * u); ctx.lineTo(5.5 * u, 2.4 * u);
  ctx.lineTo(1 * u, 1 * u); ctx.lineTo(1 * u, 3.8 * u); ctx.lineTo(2.4 * u, 5 * u); ctx.lineTo(2.4 * u, 5.9 * u); ctx.lineTo(0, 5.1 * u);
  ctx.lineTo(-2.4 * u, 5.9 * u); ctx.lineTo(-2.4 * u, 5 * u); ctx.lineTo(-1 * u, 3.8 * u); ctx.lineTo(-1 * u, 1 * u); ctx.lineTo(-5.5 * u, 2.4 * u); ctx.lineTo(-5.5 * u, 1.3 * u);
  ctx.lineTo(-1 * u, -1.2 * u); ctx.lineTo(-1 * u, -4.5 * u); ctx.quadraticCurveTo(-1 * u, -6 * u, 0, -6 * u); ctx.fill(); ctx.restore();
  return img(c);
}
const HSR_BADGE = '#2E63D6', RAIL_BADGE = '#8657D8';
function addIcons(map, force = false) {
  // add once; on a theme change update in place (same size), which keeps laid-out tiles valid
  const set = (id, im) => { if (!map.hasImage(id)) map.addImage(id, im, { pixelRatio: DPR }); else if (force) map.updateImage(id, im); };
  set('st-h', makeTrainIcon(HSR_BADGE)); set('st-r', makeTrainIcon(RAIL_BADGE));
  set('dot-h', makeDot(P.hsr, 3.2, 1.7, P.stnFill)); set('dot-r', makeDot(P.rail, 2.8, 1.5, P.stnFill));
  set('hub', makeDot(P.stnStroke, 4.2, 2, P.stnFill)); set('ap', makeAirport());
}
const STATIC_ICONS = new Set(['st-h', 'st-r', 'dot-h', 'dot-r', 'hub', 'ap']);

// ---------------------------------------------------------------- helpers over data
// line: [k, zh, en, ref, color, city, stations, branches, loop, lengthKm, connector]
// station: [zh, en, lon, lat, kind, lines, transfers]
const KNAME = { h: 'High-speed railway', r: 'Railway', m: 'Metro', l: 'Light rail', s: 'Suburban rail', t: 'Tram', f: 'Funicular' };
function lineColor(id) { const l = D.lines[id]; return l[4] || (l[0] === 'h' ? P.hsr : P.rail); }
function badgeText(l) {
  const ref = l[3] || '';
  if (ref && ref.length <= 4) return ref;
  const m = /Line\s+([A-Za-z]?\d+[A-Za-z]?)\b/.exec(l[2] || ''); if (m) return m[1];
  if (l[0] === 't') return 'T'; if (l[0] === 'f') return 'F';
  return '';
}
function badgeHTML(id, cls = '') {
  const l = D.lines[id];
  if (l[0] === 'h') return `<span class="badge hsr ${cls}" aria-hidden="true">HSR</span>`;
  if (l[0] === 'r') return `<span class="badge rl ${cls}" aria-hidden="true">RL</span>`;
  const c = l[4] || '#888888'; const t = badgeText(l);
  return `<span class="badge ${t ? '' : 'round'} ${cls}" style="background:${c};color:${textOn(c)}" aria-hidden="true">${esc(t)}</span>`;
}
function cityName(ci) { const c = D.cities[ci]; return c ? (c[1] || c[0]) : ''; }
function lineTitle(id) {
  const l = D.lines[id];
  if (l[0] === 'h' || l[0] === 'r') return l[2] || l[1];
  return l[2] || l[1];
}
function lineSub(id) {
  const l = D.lines[id];
  if (l[0] === 'h' || l[0] === 'r') return `${l[1]} · ${KNAME[l[0]]}${l[9] ? ' · ' + l[9].toLocaleString() + ' km' : ''}`;
  return `${l[1]} · ${cityName(l[5])}`;
}
function termini(id) {
  const st = D.lines[id][6]; if (st.length < 2) return '';
  const a = D.stations[st[0]], b = D.stations[st[st.length - 1]];
  if (D.lines[id][8]) return 'Loop line';
  return `${a[1] || a[0]} – ${b[1] || b[0]}`;
}
function stnName(s) { return s[1] || s[0]; }
function stnLines(si) { return D.stations[si][5]; }
function allLinesAt(si) {
  // lines serving the station plus lines at linked transfer stations
  const s = D.stations[si]; const set = new Set(s[5]);
  for (const t of s[6]) for (const l of D.stations[t][5]) set.add(l);
  return [...set];
}
function sortLines(ids) {
  const ord = { m: 0, s: 1, l: 2, t: 3, f: 4, h: 5, r: 6 };
  return ids.sort((a, b) => {
    const A = D.lines[a], B = D.lines[b];
    if (ord[A[0]] !== ord[B[0]]) return ord[A[0]] - ord[B[0]];
    const na = parseInt(A[3], 10), nb = parseInt(B[3], 10);
    if (!isNaN(na) && !isNaN(nb) && na !== nb) return na - nb;
    if (isNaN(na) !== isNaN(nb)) return isNaN(na) ? 1 : -1;
    return (A[2] || A[1]).localeCompare(B[2] || B[1]);
  });
}

// ---------------------------------------------------------------- panel rendering
const body = $('#body');
function setBody(html, expand) {
  if (expand) $('#panel').classList.remove('min');
  body.innerHTML = html; body.scrollTop = 0; $('#phead').classList.remove('scrolled');
}
body.addEventListener('scroll', () => $('#phead').classList.toggle('scrolled', body.scrollTop > 2));
const ICON_CITY = '<span class="ico city"><svg viewBox="0 0 16 16" fill="currentColor"><path d="M2 14V7l4-2v2l4-2v9zm9 0V3h3v11z"/></svg></span>';
const BACK = '<button class="back" data-act="back"><svg viewBox="0 0 9 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 1.5 2 7l5.5 5.5"/></svg>Back</button>';
const CLOSE = '<button class="ibtn" data-act="close" aria-label="Close"><svg viewBox="0 0 12 12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M2 2l8 8M10 2l-8 8"/></svg></button>';

function renderHome() {
  view.stack = [];
  const nMetro = D.lines.filter(l => 'mlstf'.includes(l[0]) && !l[10]).length;
  const nHsr = D.lines.filter(l => l[0] === 'h' && !l[10]).length;
  const nRail = D.lines.filter(l => l[0] === 'r' && !l[10]).length;
  const nSt = D.stations.filter(s => s[5].some(i => !D.lines[i][10])).length;
  const cities = D.cities.map((c, i) => [i, c]).filter(([i, c]) => c[5] > 0).sort((a, b) => b[1][5] - a[1][5] || b[1][4] - a[1][4]);
  let h = `<div class="stats"><div><b>${nMetro}</b><span>urban lines</span></div><div><b>${nHsr + nRail}</b><span>intercity lines</span></div><div><b>${nSt.toLocaleString()}</b><span>stations</span></div></div>`;
  h += `<div class="opts"><span>Labels</span><div class="seg" role="group" aria-label="Label language">` +
    ['en', 'both', 'zh'].map(m => `<button data-lab="${m}" aria-pressed="${labelMode === m}">${m === 'en' ? 'English' : m === 'zh' ? '中文' : 'Both'}</button>`).join('') + `</div></div>`;
  h += `<div class="sec">Key</div><div class="legend">
    <i style="background:var(--hsr);height:5px"></i><span>High-speed railway</span>
    <i style="background:var(--rail)"></i><span>Conventional railway</span>
    <i class="track"></i><span>Other track (freight, depots, links)</span>
    <i style="background:linear-gradient(90deg,#E4002B 0 25%,#0057B8 25% 50%,#009A44 50% 75%,#F2A900 75%)"></i><span>Metro and light rail, in official line colours</span></div>`;
  h += `<div class="sec">Cities with urban rail · ${cities.length}</div>`;
  for (const [i, c] of cities) {
    h += `<button class="row" data-city="${i}">${ICON_CITY}<span class="t"><b>${esc(c[1] || c[0])}</b><span>${esc(c[0])}</span></span><span class="n">${c[5]} line${c[5] > 1 ? 's' : ''}</span></button>`;
  }
  h += `<div class="note">Data from OpenStreetMap, extracted 25 Sep 2026, with depot tracks, bridges, duplicate and non-passenger relations removed. Lines appear as mapped there; recently opened or reorganised services may differ from timetables.</div>`;
  setBody(h);
}
function renderCity(ci, push = true) {
  const c = D.cities[ci];
  const ids = sortLines(D.lines.map((l, i) => i).filter(i => D.lines[i][5] === ci && !D.lines[i][10]));
  const groups = { m: [], s: [], l: [], t: [], f: [] };
  for (const i of ids) (groups[D.lines[i][0]] || (groups[D.lines[i][0]] = [])).push(i);
  let h = BACK + `<div class="dhead">${ICON_CITY.replace('ico city', 'ico city" style="width:34px;height:34px;border-radius:9px')}<div><h2>${esc(c[1] || c[0])}</h2><div class="zh">${esc(c[0])}</div><div class="meta">${ids.length} urban rail line${ids.length > 1 ? 's' : ''}</div></div>${CLOSE}</div>`;
  const GN = { m: 'Metro', s: 'Suburban & airport rail', l: 'Light rail, monorail & maglev', t: 'Tram', f: 'Funicular' };
  for (const k of ['m', 's', 'l', 't', 'f']) {
    if (!groups[k].length) continue;
    h += `<div class="sec">${GN[k]}</div>`;
    for (const i of groups[k]) h += lineRow(i, false);
  }
  if (push) pushView(['city', ci]);
  setBody(h, true);
}
function lineRow(i, showCity = true) {
  const l = D.lines[i];
  const sub = (l[0] === 'h' || l[0] === 'r') ? `${esc(l[1])}${l[9] ? ' · ' + l[9].toLocaleString() + ' km' : ''}` : `${esc(l[1])}${showCity ? ' · ' + esc(cityName(l[5])) : ''}`;
  return `<button class="row" data-line="${i}">${badgeHTML(i)}<span class="t"><b>${esc(lineTitle(i))}</b><span>${sub}</span></span><span class="n">${l[6].length ? l[6].length + ' stops' : ''}</span></button>`;
}
function renderLine(id, push = true) {
  const l = D.lines[id]; const col = lineColor(id);
  const kind = KNAME[l[0]];
  const meta = [kind, l[0] === 'h' || l[0] === 'r' ? '' : cityName(l[5]), l[6].length ? `${l[6].length} stations` : '', l[9] ? `${l[9].toLocaleString()} km` : ''].filter(Boolean).join(' · ');
  let h = (view.stack.length ? BACK : '') + `<div class="dhead">${badgeHTML(id)}<div><h2>${esc(lineTitle(id))}</h2><div class="zh">${esc(l[1])}</div><div class="meta">${esc(meta)}</div>${termini(id) ? `<div class="meta">${esc(termini(id))}</div>` : ''}</div>${CLOSE}</div>`;
  if (!l[6].length) h += `<div class="note">OpenStreetMap has no station data for this line.</div>`;
  h += stopList(l[6], col, id, !!l[8]);
  for (const br of l[7]) {
    const main = new Set(l[6]); const extra = br.filter(s => !main.has(s));
    if (!extra.length) continue;
    const a = D.stations[br[0]], b = D.stations[br[br.length - 1]];
    h += `<div class="sec">Branch · ${esc(stnName(a))} – ${esc(stnName(b))}</div>` + stopList(br, col, id, false);
  }
  if (push) pushView(['line', id]);
  setBody(h, true);
}
function stopList(st, col, lineId, loop) {
  let h = `<ol class="stops${loop ? ' loop' : ''}" style="--lc:${col}">`;
  const seen = new Set();
  for (const si of st) {
    const s = D.stations[si]; if (!s) continue;
    const other = sortLines(allLinesAt(si).filter(x => x !== lineId && !D.lines[x][10]));
    const urb = other.filter(x => 'mlstf'.includes(D.lines[x][0]));
    const inter = other.filter(x => 'hr'.includes(D.lines[x][0]));
    let tx = urb.slice(0, 6).map(x => badgeHTML(x, 'sm')).join('');
    if (inter.length) tx += `<span class="badge sm ${inter.some(x => D.lines[x][0] === 'h') ? 'hsr' : 'rl'}" title="Rail connection">🚆︎</span>`.replace('🚆︎', '<svg viewBox="0 0 10 10" width="10" height="10" fill="currentColor"><rect x="2.3" y="0.8" width="5.4" height="6.4" rx="1.4"/><rect x="3.1" y="1.8" width="3.8" height="2" fill="#0003"/><path d="M3 7.6 2 9.4M7 7.6 8 9.4" stroke="currentColor" stroke-width="1" stroke-linecap="round"/></svg>');
    const x = other.length > 0;
    h += `<li class="stop${x ? ' x' : ''}" data-stn="${si}" tabindex="0"><span class="rail"></span><span class="st"><b>${esc(stnName(s))}</b>${s[1] && s[1] !== s[0] ? `<span>${esc(s[0])}</span>` : ''}</span><span class="tx">${tx}</span></li>`;
  }
  return h + '</ol>';
}
function renderStation(si, push = true) {
  const s = D.stations[si];
  const lines = sortLines([...s[5]]);
  const trs = s[6];
  const kind = s[4] === 'h' ? 'High-speed rail station' : s[4] === 'r' ? 'Railway station' : s[4] === 't' ? 'Tram stop' : 'Metro station';
  let h = (view.stack.length ? BACK : '') + `<div class="dhead"><span class="ico stn" style="border-color:${s[4] === 'h' ? 'var(--hsr)' : s[4] === 'r' ? 'var(--rail)' : '#2C2C2E'}"></span><div><h2>${esc(stnName(s))}</h2>${s[1] && s[1] !== s[0] ? `<div class="zh">${esc(s[0])}</div>` : ''}<div class="meta">${kind}</div></div>${CLOSE}</div>`;
  const real = lines.filter(i => !D.lines[i][10]);
  if (real.length) { h += `<div class="sec">Lines</div>`; for (const i of real) h += lineRow(i, false); }
  if (trs.length) {
    h += `<div class="sec">Connections nearby</div>`;
    for (const t of trs) {
      const o = D.stations[t]; const ol = sortLines(o[5].filter(i => !D.lines[i][10]));
      const k = o[4] === 'h' ? 'High-speed rail station' : o[4] === 'r' ? 'Railway station' : o[4] === 't' ? 'Tram stop' : 'Metro station';
      h += `<button class="row" data-stn="${t}"><span class="ico stn" style="border-color:${o[4] === 'h' ? 'var(--hsr)' : o[4] === 'r' ? 'var(--rail)' : '#2C2C2E'}"></span><span class="t"><b>${esc(stnName(o))}</b><span>${esc(k)}${ol.length ? ' · ' + ol.length + ' line' + (ol.length > 1 ? 's' : '') : ''}</span></span></button>`;
    }
  }
  if (push) pushView(['stn', si]);
  setBody(h, true);
}
function renderChooser(ids) {
  let h = `<div class="dhead"><div><h2>${ids.length} lines here</h2><div class="meta">Choose one to see its route and stations</div></div>${CLOSE}</div>`;
  for (const i of sortLines(ids)) h += lineRow(i);
  pushView(['choose', ids]);
  setBody(h, true);
}
function pushView(v) { view.stack.push(v); }
function goBack() {
  view.stack.pop();
  const v = view.stack.pop();
  if (!v) { clearSelection(); renderHome(); return; }
  if (v[0] === 'city') { clearSelection(); renderCity(v[1]); }
  else if (v[0] === 'line') { selectLine(v[1], { fit: false }); }
  else if (v[0] === 'stn') { showStation(v[1], { fly: false }); }
  else if (v[0] === 'choose') { clearSelection(); renderChooser(v[1]); }
  else renderHome();
}

// ---------------------------------------------------------------- search
function norm(s) { return (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[\s\-–—'’·.()（）]/g, ''); }
let IDX = null;
function buildIndex() {
  IDX = [];
  D.lines.forEach((l, i) => { if (l[10]) return; IDX.push({ t: 'l', i, a: norm(l[2]), b: norm(l[1]), c: norm(cityName(l[5])), r: norm(l[3]) }); });
  const seen = new Map();
  D.stations.forEach((s, i) => {
    if (!s[5].some(x => !D.lines[x][10])) return;
    const key = s[0] + '|' + s[4] + '|' + Math.round(s[2] * 20) + '|' + Math.round(s[3] * 20);
    if (seen.has(key)) return; seen.set(key, i);
    IDX.push({ t: 's', i, a: norm(s[1]), b: norm(s[0]) });
  });
  D.cities.forEach((c, i) => { if (c[5] > 0) IDX.push({ t: 'c', i, a: norm(c[1]), b: norm(c[0]) }); });
}
function search(q) {
  const n = norm(q); if (!n) return [];
  const words = q.toLowerCase().trim().split(/\s+/).map(norm).filter(Boolean);
  const nums = words.filter(w => /^[a-z]?\d+[a-z]?$/.test(w));
  const res = [];
  for (const e of IDX) {
    let sc = 0;
    const hay = e.a + ' ' + e.b + ' ' + (e.c || '') + ' ' + (e.r || '');
    if (e.a === n || e.b === n) sc = 100;
    else if (e.a.startsWith(n) || e.b.startsWith(n)) sc = 60;
    else if (words.every(w => hay.includes(w))) sc = 30;
    else continue;
    if (e.t === 'c') sc += 25; else if (e.t === 'l') sc += 10;
    if (e.t === 'l' && nums.length) { if (nums.includes(e.r)) sc += 40; else if (e.r && /^\d+$/.test(e.r)) sc -= 15; }
    if (e.t === 's') { const s = D.stations[e.i]; sc += Math.min(8, s[5].length * 2) + (s[4] === 'h' ? 3 : 0); }
    res.push([sc, e]);
  }
  res.sort((a, b) => b[0] - a[0]);
  return res.slice(0, 50).map(r => r[1]);
}
function renderResults(q) {
  const res = search(q);
  if (!res.length) { setBody(`<div class="note">No lines, stations or cities match “${esc(q)}”.</div>`); return; }
  let h = '';
  for (const e of res) {
    if (e.t === 'l') h += lineRow(e.i);
    else if (e.t === 'c') { const c = D.cities[e.i]; h += `<button class="row" data-city="${e.i}">${ICON_CITY}<span class="t"><b>${esc(c[1] || c[0])}</b><span>${esc(c[0])} · ${c[5]} lines</span></span></button>`; }
    else {
      const s = D.stations[e.i];
      const ls = sortLines(allLinesAt(e.i).filter(x => !D.lines[x][10]));
      const city = ls.map(x => D.lines[x][5]).find(ci => ci >= 0);
      const sub = [s[1] && s[1] !== s[0] ? s[0] : '', city != null ? cityName(city) : (s[4] === 'h' ? 'High-speed rail' : s[4] === 'r' ? 'Railway' : '')].filter(Boolean).join(' · ');
      h += `<button class="row" data-stn="${e.i}"><span class="ico stn" style="border-color:${s[4] === 'h' ? 'var(--hsr)' : s[4] === 'r' ? 'var(--rail)' : '#2C2C2E'}"></span><span class="t"><b>${esc(stnName(s))}</b><span>${esc(sub)}</span></span><span class="tx" style="display:flex;gap:3px">${ls.slice(0, 4).map(x => badgeHTML(x, 'sm')).join('')}</span></button>`;
    }
  }
  setBody(h);
}

// ---------------------------------------------------------------- map
let map;
function applyStyle() { map.setStyle(buildStyle(), { diff: true }); }
function lineBounds(id) {
  const st = D.lines[id][6].concat(...D.lines[id][7]);
  if (!st.length) return null;
  let a = [180, 90, -180, -90];
  for (const si of st) { const s = D.stations[si]; a = [Math.min(a[0], s[2]), Math.min(a[1], s[3]), Math.max(a[2], s[2]), Math.max(a[3], s[3])]; }
  return a;
}
function padding() {
  const mobile = innerWidth <= 640;
  if (mobile) return { top: 60, bottom: $('#panel').classList.contains('min') ? 150 : Math.round(innerHeight * 0.52) + 20, left: 30, right: 30 };
  return { top: 60, bottom: 60, left: Math.min(380, innerWidth * 0.45), right: 70 };
}
function selectLine(id, { fit = true } = {}) {
  sel = id; selStation = null;
  applyStyle();
  if (fit) {
    const b = lineBounds(id);
    if (b) {
      if (b[2] - b[0] < 0.002 && b[3] - b[1] < 0.002) map.flyTo({ center: [b[0], b[1]], zoom: 14 });
      else map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: padding(), maxZoom: 14.5, duration: 900 });
    }
  }
  renderLine(id);
}
function clearSelection() { if (sel != null || selStation != null) { sel = null; selStation = null; applyStyle(); } }
function showStation(si, { fly = true } = {}) {
  const s = D.stations[si];
  selStation = si; applyStyle();
  if (fly) {
    const z = Math.max(map.getZoom(), s[4] === 'h' || s[4] === 'r' ? 12.5 : 14);
    map.flyTo({ center: [s[2], s[3]], zoom: z, padding: padding(), duration: 800 });
  }
  renderStation(si);
}
function flyCity(ci) {
  const c = D.cities[ci];
  const ids = D.lines.map((l, i) => i).filter(i => D.lines[i][5] === ci && !D.lines[i][10]);
  let a = null;
  for (const id of ids) { const b = lineBounds(id); if (!b) continue; a = a ? [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])] : b; }
  if (a) map.fitBounds([[a[0], a[1]], [a[2], a[3]]], { padding: padding(), maxZoom: 13, duration: 900 });
  else if (c[2] != null) map.flyTo({ center: [c[2], c[3]], zoom: 10.5 });
}
const CHINA = [[73.5, 18.0], [134.8, 53.6]];
function home() { map.fitBounds(CHINA, { padding: padding(), duration: 900 }); }

// panel clicks
$('#panel').addEventListener('click', e => {
  const b = e.target.closest('[data-line],[data-stn],[data-city],[data-act],[data-lab],[data-mode]');
  if (!b) return;
  if (b.dataset.act === 'back') return goBack();
  if (b.dataset.act === 'close') { clearSelection(); view.stack = []; $('#q').value = ''; $('#qclear').classList.remove('show'); return renderHome(); }
  if (b.dataset.lab) { labelMode = b.dataset.lab; try { localStorage.setItem('cra-lab', labelMode); } catch (_) {} applyStyle(); renderHome(); return; }
  if (b.dataset.line != null) return selectLine(+b.dataset.line);
  if (b.dataset.stn != null) return showStation(+b.dataset.stn);
  if (b.dataset.city != null) { clearSelection(); flyCity(+b.dataset.city); return renderCity(+b.dataset.city); }
});
$('#panel').addEventListener('keydown', e => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('li[data-stn]')) { e.preventDefault(); showStation(+e.target.dataset.stn); }
});
// chips
function renderChips() {
  const sw = { h: 'var(--hsr)', r: 'var(--rail)', m: 'linear-gradient(90deg,#E4002B 0 50%,#0057B8 50%)', l: 'linear-gradient(90deg,#00A3E0 0 50%,#7F3F98 50%)', t: '#3FA34D' };
  $('#chips').innerHTML = MODES.map(m => `<button class="chip" data-mode="${m.k}" aria-pressed="${vis[m.k]}"><span class="sw" style="background:${sw[m.k]}"></span>${m.name}</button>`).join('');
}
$('#chips').addEventListener('click', e => {
  const b = e.target.closest('[data-mode]'); if (!b) return;
  vis[b.dataset.mode] = !vis[b.dataset.mode];
  b.setAttribute('aria-pressed', vis[b.dataset.mode]);
  applyStyle();
});
// search
let qt = null;
$('#q').addEventListener('focus', () => $('#panel').classList.remove('min'));
$('#q').addEventListener('input', e => {
  const v = e.target.value; $('#qclear').classList.toggle('show', !!v);
  clearTimeout(qt);
  qt = setTimeout(() => { if (v.trim()) { view.stack = []; renderResults(v); } else renderHome(); }, 120);
});
$('#q').addEventListener('keydown', e => { if (e.key === 'Enter') { const f = body.querySelector('.row'); if (f) f.click(); } if (e.key === 'Escape') { e.target.value = ''; $('#qclear').classList.remove('show'); renderHome(); } });
$('#qclear').addEventListener('click', () => { $('#q').value = ''; $('#qclear').classList.remove('show'); renderHome(); $('#q').focus(); });
$('#grip').addEventListener('click', () => $('#panel').classList.toggle('min'));
$('#zin').addEventListener('click', () => map.zoomIn());
$('#zout').addEventListener('click', () => map.zoomOut());
$('#compass').addEventListener('click', () => map.easeTo({ bearing: 0, pitch: 0 }));
$('#home').addEventListener('click', () => { clearSelection(); home(); });

// ---------------------------------------------------------------- boot
async function boot() {
  try { const lm = localStorage.getItem('cra-lab'); if (lm) labelMode = lm; } catch (_) {}
  const [m, d] = await Promise.all([fetch('data/manifest.json').then(r => r.json()), fetch('data/network.json').then(r => r.json())]);
  manifest = m; D = d;
  for (const c of D.cities) c[5] = 0;
  for (const l of D.lines) if (!l[10] && 'mlstf'.includes(l[0]) && D.cities[l[5]]) D.cities[l[5]][5]++;
  buildIndex(); renderChips(); renderHome();
  if (innerWidth <= 640) $('#panel').classList.add('min');
  map = window.__map = new maplibregl.Map({
    container: 'map', style: buildStyle(), bounds: CHINA, fitBoundsOptions: { padding: padding() },
    minZoom: 1.5, maxZoom: 19, maxPitch: 60, attributionControl: false, hash: 'view',
    localIdeographFontFamily: '"PingFang SC","PingFang TC","Hiragino Sans GB","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei",sans-serif',
    fadeDuration: 150,
  });
  map.on('styleimagemissing', e => {
    const id = e.id;
    if (id.startsWith('b|')) {
      const [, color, text] = id.split('|');
      if (!map.hasImage(id)) map.addImage(id, makeBadge(color || '#888888', text || ''), { pixelRatio: DPR });
    } else if (id.startsWith('bs|')) {
      if (!map.hasImage(id)) map.addImage(id, makeBulletRow(+id.slice(3)), { pixelRatio: DPR });
    } else if (id.startsWith('sh|')) {
      const [, kind, ref] = id.split('|');
      if (!map.hasImage(id)) map.addImage(id, makeShield(kind, ref || ''), { pixelRatio: DPR });
    } else if (id.startsWith('sd|')) {
      const [, t, col] = id.split('|');
      if (!map.hasImage(id)) map.addImage(id, makeDot(col, 5, 2.1, t === 'D' ? PAL.dark.stnFill : PAL.light.stnFill), { pixelRatio: DPR });
    } else if (id.startsWith('hubm|')) {
      const t = id.slice(5), pal = t === 'D' ? PAL.dark : PAL.light;
      if (!map.hasImage(id)) map.addImage(id, makeDot(pal.stnStroke, 6.2, 2.3, pal.stnFill), { pixelRatio: DPR });
    } else if (id.startsWith('pc|')) {
      if (!map.hasImage(id)) map.addImage(id, makePoiDot((POI_COLORS[id.slice(3)] || POI_COLORS.other)[0]), { pixelRatio: DPR });
    } else if (STATIC_ICONS.has(id)) addIcons(map);
  });
  if (innerWidth <= 640 && !/[#&]view=/.test(location.hash)) map.jumpTo({ center: [110.5, 31.5], zoom: 3 });
  map.on('load', () => { addIcons(map); $('#loading').classList.add('done'); });
  map.on('rotate', () => { $('#compass svg').style.transform = `rotate(${-map.getBearing()}deg)`; });
  const railLayers = ['u-m', 'u-s', 'u-l', 'u-t', 'u-f', 'rail-h', 'rail-r', 'sel-line'];
  const stnLayers = ['stn-u', 'stn-u1', 'stn-rail', 'sel-stn'];
  const hitBox = (p, r) => [[p.x - r, p.y - r], [p.x + r, p.y + r]];
  map.on('mousemove', e => {
    const f = map.queryRenderedFeatures(hitBox(e.point, 5), { layers: [...stnLayers, ...railLayers].filter(l => map.getLayer(l)) });
    map.getCanvasContainer().classList.toggle('pointer', f.length > 0);
  });
  map.on('click', e => {
    const layers = l => l.filter(x => map.getLayer(x));
    const st = map.queryRenderedFeatures(hitBox(e.point, 7), { layers: layers(stnLayers) });
    if (st.length) {
      st.sort((a, b) => (b.properties.x || 0) - (a.properties.x || 0));
      return showStation(st[0].properties.i, { fly: false });
    }
    const fs = map.queryRenderedFeatures(hitBox(e.point, 6), { layers: layers(railLayers) });
    const ids = new Set();
    for (const f of fs) {
      const ls = String(f.properties.ls || '').split('|').filter(Boolean).map(Number);
      for (const x of ls) ids.add(x);
      if (!ls.length && f.properties.l >= 0) ids.add(f.properties.l);
    }
    let arr = [...ids].filter(i => D.lines[i]);
    arr = arr.filter(i => !D.lines[i][10]);
    if (sel != null && arr.includes(sel) && arr.length > 1) arr = arr.filter(i => i !== sel).concat([sel]);
    if (!arr.length) { if (sel != null || selStation != null) { clearSelection(); view.stack = []; $('#q').value = ''; $('#qclear').classList.remove('show'); renderHome(); } return; }
    view.stack = [];
    if (arr.length === 1) selectLine(arr[0], { fit: false });
    else renderChooser(arr);
  });
  // theme changes
  const reTheme = () => { const want = isDark() ? PAL.dark : PAL.light; if (want !== P) { P = want; applyStyle(); addIcons(map, true); } };
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', reTheme);
  new MutationObserver(reTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}
boot().catch(err => {
  $('#loading div').innerHTML = `<span>The map data did not load (${esc(err.message)}). Reload the page to try again.</span>`;
});
})();
