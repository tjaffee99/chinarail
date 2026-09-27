"""Generate the rail vector tiles (data/tiles/*.bin + data/manifest.json) from the curated
network and the line geometry written by build_network.py.

    python3 tools/make_tiles.py /path/to/geometry.pickle

Only track used by a listed (visible) line is drawn. Layers and properties:
  rail  l primary line id · ls "|id|id|" all lines on this track · k kind (h r m l s t f)
        c colour and r badge text (urban) · nm / nz line name for labels (intercity, z5-11)
  stn   i station id · n / z names · k kind · x lines at the station complex · c ring colour
        rk rank · ls line ids · ks kinds at this node · kc kinds at the complex
        cx complex main station · rep 1 if this node is the complex's main station
Archive: chunks of tiles ("TPK1" + index + gzipped MVT), z<=7 in one chunk, deeper zooms
grouped by their z6 ancestor; see app.js getTile().
"""
import gzip, json, math, os, pickle, struct, sys
from collections import defaultdict
import mapbox_vector_tile
from shapely.geometry import LineString, MultiLineString, box, Point
from shapely.ops import linemerge
from shapely import affinity

ROOT = os.path.join(os.path.dirname(__file__), '..')
D = json.load(open(os.path.join(ROOT, 'data', 'network.json')))
L, S, C = D['lines'], D['stations'], D['cities']
G = pickle.load(open(sys.argv[1], 'rb'))
GEOM, WAYS = G['geometry'], G['ways']
MINZ, MAXZ, LOWMAX, RZ, EXT, BUF = 3, 12, 7, 6, 4096, 64

def visible(i): return 0 <= i < len(L) and not L[i][10]
def merc(lon, lat):
    lat = max(-85, min(85, lat))
    return ((lon + 180) / 360, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2)

# ---------------------------------------------------------------- rail features
way_lines = defaultdict(set)
for li, ways in enumerate(GEOM):
    if visible(li):
        for w in ways: way_lines[w].add(li)
# ---------------------------------------------------------------- gaps
# Some line relations omit a stretch their trains run over another line's track (e.g. a
# corridor using an intercity line between two of its stops). Where a line has no track of its
# own between consecutive stops, route it along the rail network (shortest path over OSM
# nodes) and draw that track as part of the line.
import heapq
import numpy as np
def mxy(lon, lat): return np.array([lon * 111320 * math.cos(math.radians(32)), lat * 110540])
node_pos, node_adj = {}, defaultdict(list)
for w, v in WAYS.items():
    c, t, refs = v
    if t.get('service') or t.get('railway') not in ('rail', 'narrow_gauge'): continue
    for (n1, p1), (n2, p2) in zip(zip(refs, c), zip(refs[1:], c[1:])):
        d = float(np.hypot(*(mxy(*p1) - mxy(*p2))))
        node_adj[n1].append((n2, d, w)); node_adj[n2].append((n1, d, w)); node_pos[n1] = p1; node_pos[n2] = p2
NID = np.array(list(node_pos)); NXY = np.array([mxy(*node_pos[n]) for n in NID])
def route(A, B):
    d = float(np.hypot(*(A - B)))
    dA = np.hypot(*(NXY - A).T); dB = np.hypot(*(NXY - B).T)
    inside = dA + dB <= 1.5 * d + 2000
    ok = set(NID[inside].tolist())
    src = NID[(dA < 1500) & inside]; dst = set(NID[(dB < 1500) & inside].tolist())
    if not len(src) or not dst: return None
    dist = {int(n): float(dA[i]) * 3 for n, i in zip(src, np.where((dA < 1500) & inside)[0])}; prev = {}
    h = [(v, k) for k, v in dist.items()]; heapq.heapify(h)
    while h:
        du, u = heapq.heappop(h)
        if du > dist.get(u, 1e18): continue
        if u in dst:
            ways = set()
            while u in prev: u, w = prev[u]; ways.add(w)
            return ways
        for v, wlen, w in node_adj[u]:
            if v not in ok: continue
            nd = du + wlen
            if nd < dist.get(v, 1e18): dist[v] = nd; prev[v] = (u, w); heapq.heappush(h, (nd, v))
    return None
filled = 0
for li, ways in enumerate(GEOM):
    l = L[li]
    if not visible(li) or l[0] not in 'hr': continue
    own = np.array([mxy(*p) for w in ways for p in WAYS[w][0][::2]]) if ways else np.zeros((0, 2))
    for a, b in zip(l[6], l[6][1:]):
        A, B = mxy(S[a][2], S[a][3]), mxy(S[b][2], S[b][3]); d = float(np.hypot(*(A - B)))
        if d < 3000: continue
        if len(own):
            oA = np.hypot(*(own - A).T); oB = np.hypot(*(own - B).T)
            if ((oA + oB <= 1.3 * d) & (np.minimum(oA, oB) >= 0.2 * d)).any(): continue
        got = route(A, B)
        if got:
            for w in got: way_lines[w].add(li)
            filled += 1
print('gaps between stops routed along the rail network:', filled)

groups = defaultdict(list)
for w, ls in way_lines.items(): groups[frozenset(ls)].append(w)

def primary(ls):
    kinds = [L[i][0] for i in ls]
    order = 'hrmslft'
    k = min(kinds, key=order.index) if any(x in 'hr' for x in kinds) else max(set(kinds), key=kinds.count)
    same = [i for i in ls if L[i][0] == k]
    return max(same, key=lambda i: (L[i][9] or 0, len(L[i][6]))), k

features = []   # (merc geometry, props)
for ls, ws in groups.items():
    lines = [LineString([merc(*p) for p in WAYS[w][0]]) for w in ws if w in WAYS and len(WAYS[w][0]) >= 2]
    if not lines: continue
    merged = linemerge(lines)
    parts = list(merged.geoms) if merged.geom_type == 'MultiLineString' else [merged]
    prim, k = primary(ls)
    props = {'l': prim, 'ls': '|' + '|'.join(str(i) for i in sorted(ls)) + '|', 'k': k}
    if k not in 'hr':
        props['c'] = L[prim][4] or '#888888'
        if L[prim][3]: props['r'] = L[prim][3]
    for g in parts: features.append((g, props, k))
print('rail features', len(features))

# ---------------------------------------------------------------- stations
complex_members = defaultdict(list)
for i, s in enumerate(S):
    if len(s) > 7 and s[7] >= 0: complex_members[s[7]].append(i)
# rank: a station named after a big city ("北京南" -> 北京) outranks a busy junction
CITY = sorted([(c[0], c[2], c[3], c[4]) for c in C if c[0] and len(c[0]) >= 2], key=lambda c: -len(c[0]))
def city_rank(s):
    for zh, lon, lat, pop in CITY:
        if s[0].startswith(zh) and abs(s[2] - lon) < 0.8 and abs(s[3] - lat) < 0.8:
            return 13 if pop > 15e6 else 12 if pop > 8e6 else 11 if pop > 4e6 else 10
    return 0
stn_feats = []
for i, s in enumerate(S):
    vis = [x for x in s[5] if visible(x)]
    if not vis: continue
    rep = s[7] if len(s) > 7 and s[7] >= 0 else i
    members = complex_members.get(rep, [i])
    allv = {x for m in members for x in S[m][5] if visible(x)}
    inter = {L[x][1] for x in allv if L[x][0] in 'hr'}; urb = {L[x][1] for x in allv if L[x][0] not in 'hr'}
    rk = city_rank(S[rep]) or min(9, 1 + 2 * len(inter) + len(urb))
    own_urban = [x for x in vis if L[x][0] not in 'hr']
    col = L[own_urban[0]][4] if len(own_urban) == 1 and L[own_urban[0]][4] else '#FFFFFF'
    props = {'i': i, 'k': s[4], 'n': s[1] or s[0], 'z': s[0], 'x': len(inter | urb), 'c': col, 'rk': rk,
             'ls': '|' + '|'.join(str(x) for x in sorted(vis)) + '|', 'ks': ''.join(sorted({L[x][0] for x in vis})),
             'kc': ''.join(sorted({L[x][0] for x in allv})), 'cx': rep, 'rep': int(rep == i)}
    stn_feats.append((merc(s[2], s[3]), props))
def stn_minzoom(p):
    if p['k'] not in 'hr': return 11 if p['x'] <= 1 else 10
    return 3 if p['rk'] >= 10 else 6 if p['rk'] >= 7 else 8 if p['rk'] >= 4 else 10

# ---------------------------------------------------------------- tiling
def tiles_for_zoom(z):
    n = 2 ** z; px = 1 / (n * 256)
    out = defaultdict(lambda: {'rail': [], 'stn': []})
    for g, props, k in features:
        if z < 7 and k not in 'hr' and g.length < 4 * px: continue
        gs = g.simplify(px * 0.5, preserve_topology=False) if z < MAXZ else g
        if gs.is_empty or gs.length < px * 0.5: continue
        x0, y0, x1, y1 = gs.bounds; b = BUF / EXT / n
        for tx in range(max(0, int((x0 - b) * n)), min(n - 1, int((x1 + b) * n)) + 1):
            for ty in range(max(0, int((y0 - b) * n)), min(n - 1, int((y1 + b) * n)) + 1):
                tb = box(tx / n - b, ty / n - b, (tx + 1) / n + b, (ty + 1) / n + b)
                if not tb.intersects(gs): continue
                c = gs.intersection(tb)
                if c.is_empty: continue
                c = affinity.affine_transform(c, [n * EXT, 0, 0, n * EXT, -tx * EXT, -ty * EXT])
                pr = dict(props)
                if k in 'hr' and 5 <= z <= 11:
                    lab = L[props['l']]; pr['nm'] = lab[11] or lab[2] or lab[1]; pr['nz'] = lab[1]
                out[(tx, ty)]['rail'].append({'geometry': c, 'properties': pr})
    for (x, y), props in stn_feats:
        if z < stn_minzoom(props): continue
        tx, ty = int(x * n), int(y * n)
        if not (0 <= tx < n and 0 <= ty < n): continue
        out[(tx, ty)]['stn'].append({'geometry': Point(x * n * EXT - tx * EXT, y * n * EXT - ty * EXT), 'properties': props})
    return out

def encode(layers):
    ls = [{'name': name, 'features': f} for name, f in (('rail', layers['rail']), ('stn', layers['stn'])) if f]
    return gzip.compress(mapbox_vector_tile.encode(ls, default_options={'extents': EXT, 'y_coord_down': True, 'quantize_bounds': None,
                                                                          'on_invalid_geometry': None}), compresslevel=9, mtime=0)

chunks = defaultdict(list)
for z in range(MINZ, MAXZ + 1):
    t = tiles_for_zoom(z)
    for (x, y), layers in t.items():
        key = 'low' if z <= LOWMAX else f'{x >> (z - RZ)}_{y >> (z - RZ)}'
        chunks[key].append((((z << 26) | (x << 13) | y) & 0xffffffff, encode(layers)))
    print('z', z, 'tiles', len(t), flush=True)

def write_chunk(entries):
    entries.sort(); idx, data, off = [], [], 0
    for k, t in entries:
        idx.append(struct.pack('<III', k, off, len(t))); data.append(t); off += len(t)
    return b'TPK1' + struct.pack('<I', len(entries)) + b''.join(idx) + b''.join(data)

TDIR = os.path.join(ROOT, 'data', 'tiles')
for f in os.listdir(TDIR): os.remove(os.path.join(TDIR, f))
man, fi, buf, pos = {}, 0, [], 0
def flush():
    global fi, buf, pos
    if buf:
        open(os.path.join(TDIR, f'rail_{fi}.bin'), 'wb').write(b''.join(buf)); fi += 1; buf, pos = [], 0
for key in ['low'] + sorted(k for k in chunks if k != 'low'):
    blob = write_chunk(chunks[key])
    if pos and pos + len(blob) > 1_500_000: flush()
    man[key] = [f'rail_{fi}.bin', pos, len(blob)]; buf.append(blob); pos += len(blob)
flush()
json.dump({'rail': {'minzoom': MINZ, 'maxzoom': MAXZ, 'lowmax': LOWMAX, 'rz': RZ, 'chunks': man}},
          open(os.path.join(ROOT, 'data', 'manifest.json'), 'w'), separators=(',', ':'))
print('files', fi, 'chunks', len(man))
