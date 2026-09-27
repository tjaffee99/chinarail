"""Build data/network.json (and the line geometry used for tiles) from extract_osm.py output.

    python3 tools/build_network.py /path/to/raw.pickle /path/to/geometry.pickle

Lines
  urban     route_master relations for subway / light_rail / monorail / tram / funicular, and
            suburban route=train masters (市域/市郊); one line per master, or per route relation
            when a route has no master. Stops come from the route members (stop / platform roles),
            snapped to the station node they belong to.
  intercity route=railway relations (China maps each railway line as one). Stops are the
            passenger stations on the line's track (within 150 m), ordered along the track.
Station record, line record and city record are documented in curate.py.
"""
import json, math, os, pickle, re, sys
from collections import defaultdict
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), '..')
raw = pickle.load(open(sys.argv[1], 'rb'))
RELS, WAYS, NODES, PLACES = raw['relations'], raw['ways'], raw['stations'], raw['places']
URBAN_ROUTE = {'subway': 'm', 'light_rail': 'l', 'monorail': 'l', 'tram': 't', 'funicular': 'f'}

def cjk(s): return bool(s and re.search(r'[一-鿿]', s))
def zh_of(t): return t.get('name:zh') or t.get('name:zh-Hans') or (t.get('name') if cjk(t.get('name')) else None) or t.get('name:zh-Hant') or t.get('name') or ''
def en_of(t):
    en = t.get('name:en') or ''
    if not en and t.get('name') and not cjk(t.get('name')): en = t['name']
    return en

def xy(lon, lat):   # local metres (equirectangular around China)
    return np.array([lon * 111320 * math.cos(math.radians(32)), lat * 110540])

# ---------------------------------------------------------------- stations
def stn_name(t):
    n = zh_of(t)
    return n[:-1] if len(n) >= 3 and n.endswith('站') and not n.endswith('车站') else n
def is_passenger_station(t):
    if not (zh_of(t) or t.get('name:en')) or '综合体' in zh_of(t): return False
    if t.get('disused') or t.get('abandoned'): return False
    if t.get('railway') not in ('station', 'halt') and t.get('public_transport') != 'station': return False
    if t.get('station') in ('freight', 'yard') or t.get('railway:traffic_mode') == 'freight' or t.get('usage') == 'freight': return False
    if t.get('passenger') == 'no': return False
    return True
def is_urban_station(t):
    return t.get('station') in ('subway', 'light_rail', 'monorail', 'tram') or t.get('subway') == 'yes' or t.get('light_rail') == 'yes' \
        or t.get('monorail') == 'yes' or t.get('tram') == 'yes' or t.get('railway') == 'tram_stop'

stations = []          # [zh, en, lon, lat, kind, lines, transfers]
st_index = {}          # osm node id -> station index
by_zh = defaultdict(list)   # one station per name within 400 m (OSM often has a node per line)
def station_for(nid):
    if nid in st_index: return st_index[nid]
    lon, lat, t = NODES[nid]
    name = stn_name(t)
    for j in by_zh.get(name, ()):
        if name and float(np.hypot(*(xy(stations[j][2], stations[j][3]) - xy(lon, lat)))) < 400:
            st_index[nid] = j; return j
    by_zh[name].append(len(stations))
    st_index[nid] = len(stations)
    stations.append([name, en_of(t), round(lon, 5), round(lat, 5), '', [], []])
    return st_index[nid]

# grid of passenger station nodes for snapping
grid = defaultdict(list)
for nid, (lon, lat, t) in NODES.items():
    if is_passenger_station(t) or t.get('railway') == 'tram_stop':
        grid[(int(lon * 50), int(lat * 50))].append(nid)
def nearby_stations(lon, lat, r_m):
    out = []
    cx, cy = int(lon * 50), int(lat * 50)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for nid in grid.get((cx + dx, cy + dy), ()):
                a = NODES[nid]
                d = float(np.hypot(*(xy(a[0], a[1]) - xy(lon, lat))))
                if d <= r_m: out.append((d, nid))
    return sorted(out)

def snap_stop(nid):
    """Map a stop member (stop_position / platform / station node) to its station node."""
    if nid not in NODES: return None
    lon, lat, t = NODES[nid]
    if t.get('railway') in ('station', 'halt', 'tram_stop') or t.get('public_transport') == 'station':
        return nid
    name = zh_of(t)
    near = nearby_stations(lon, lat, 500)
    same = [n for d, n in near if name and zh_of(NODES[n][2]) == name]
    if same: return same[0]
    close = [n for d, n in near if d <= 150]
    return close[0] if close else nid

# ---------------------------------------------------------------- geometry helpers
def way_len(wid):
    c = WAYS[wid][1]
    return sum(float(np.hypot(*(xy(*a) - xy(*b)))) for a, b in zip(c, c[1:]))

def chain(way_ids):
    """Main path through the ways as a list of (lon, lat): the longest shortest path over the
    node graph (ways join at any shared node, not only their ends), found by a double sweep."""
    import heapq
    adj = defaultdict(list); pos = {}
    for w in way_ids:
        if w not in WAYS: continue
        c, refs = WAYS[w][1], WAYS[w][2]
        for (n1, p1), (n2, p2) in zip(zip(refs, c), zip(refs[1:], c[1:])):
            d = float(np.hypot(*(xy(*p1) - xy(*p2))))
            adj[n1].append((n2, d)); adj[n2].append((n1, d)); pos[n1] = p1; pos[n2] = p2
    if not adj: return []
    def sweep(src):
        dist, prev, h = {src: 0.0}, {}, [(0.0, src)]
        while h:
            du, u = heapq.heappop(h)
            if du > dist[u]: continue
            for v, w in adj[u]:
                if du + w < dist.get(v, 1e18): dist[v] = du + w; prev[v] = u; heapq.heappush(h, (du + w, v))
        far = max(dist, key=dist.get)
        return far, prev
    # each connected piece: its longest path; relations often have small breaks between pieces
    seen, pieces = set(), []
    for n0 in adj:
        if n0 in seen: continue
        comp, stack = {n0}, [n0]
        while stack:
            u = stack.pop()
            for v, _ in adj[u]:
                if v not in comp: comp.add(v); stack.append(v)
        seen |= comp
        a, _ = sweep(n0)
        b, prev = sweep(a)
        path = [b]
        while path[-1] in prev: path.append(prev[path[-1]])
        P = [pos[n] for n in reversed(path)]
        L_ = sum(float(np.hypot(*(xy(*p1) - xy(*p2)))) for p1, p2 in zip(P, P[1:]))
        if L_ > 500: pieces.append((L_, P))
    if not pieces: return []
    pieces.sort(key=lambda t: -t[0])
    out = list(pieces[0][1]); rest = [p for _, p in pieces[1:]]
    while rest:   # attach the nearest remaining piece to either end
        best = None
        for j, P in enumerate(rest):
            for end in (0, 1):
                E = xy(*(out[0] if end == 0 else out[-1]))
                for rev in (False, True):
                    Q = P[::-1] if rev else P
                    q = Q[-1] if end == 0 else Q[0]
                    d = float(np.hypot(*(E - xy(*q))))
                    if best is None or d < best[0]: best = (d, j, end, Q)
        d, j, end, Q = best
        out = (Q + out) if end == 0 else (out + Q)
        rest.pop(j)
    return out

def project(poly, lon, lat):
    """Distance along polyline and offset of a point."""
    P = np.array([xy(*p) for p in poly]); X = xy(lon, lat)
    A, B = P[:-1], P[1:]; AB = B - A
    t = np.clip(((X - A) * AB).sum(1) / np.maximum((AB * AB).sum(1), 1e-9), 0, 1)
    Q = A + AB * t[:, None]; d = np.hypot(*(X - Q).T); j = int(np.argmin(d))
    seg = np.hypot(*AB.T); cum = np.concatenate([[0], np.cumsum(seg)])
    return cum[j] + seg[j] * t[j], float(d[j])

def dist_to_ways(way_ids, lon, lat):
    X = xy(lon, lat); best = 1e18
    for w in way_ids:
        c = WAYS[w][1]
        P = np.array([xy(*p) for p in c]); A, B = P[:-1], P[1:]; AB = B - A
        if not len(AB): continue
        t = np.clip(((X - A) * AB).sum(1) / np.maximum((AB * AB).sum(1), 1e-9), 0, 1)
        best = min(best, float(np.hypot(*(X - (A + AB * t[:, None])).T).min()))
    return best

# cells (~250 m) touched by operational main-line track, to drop stations of lines still being
# built: relations often already list them, but their track is railway=construction
OPEN_CELLS = defaultdict(set)   # cell -> main-line ways through it
def _cell(lon, lat): return (round(lon * 400), round(lat * 400))
for _w, (_t, _c, *_) in WAYS.items():
    if _t.get('railway') not in ('rail', 'narrow_gauge') or _t.get('service'): continue
    for (x1, y1), (x2, y2) in zip(_c, _c[1:]):
        n = max(1, int(max(abs(x2 - x1), abs(y2 - y1)) * 800))
        for k in range(n + 1): OPEN_CELLS[_cell(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n)].add(_w)
def nearest_main_way(lon, lat):
    cx, cy = _cell(lon, lat)
    cands = {w for i in range(-2, 3) for j in range(-2, 3) for w in OPEN_CELLS.get((cx + i, cy + j), ())}
    return min(cands, key=lambda w: dist_to_ways([w], lon, lat), default=None)
def near_open_track(lon, lat):
    cx, cy = _cell(lon, lat)
    return any((cx + i, cy + j) in OPEN_CELLS for i in range(-3, 4) for j in range(-3, 4))

def order_stops(nids):
    """Order stations along a corridor: start at the station farthest from the others' centre,
    walk to the nearest unvisited one, then untangle with 2-opt (a shortest open path)."""
    if len(nids) < 3: return list(nids)
    P = np.array([xy(NODES[n][0], NODES[n][1]) for n in nids])
    Dm = np.hypot(*(P[:, None, :] - P[None, :, :]).transpose(2, 0, 1))
    start = int(np.argmax(np.hypot(*(P - P.mean(0)).T)))
    order, left = [start], set(range(len(nids))) - {start}
    while left:
        u = order[-1]; v = min(left, key=lambda j: Dm[u, j]); order.append(v); left.discard(v)
    improved = True
    while improved:
        improved = False
        for a in range(len(order) - 2):
            for b in range(a + 2, len(order)):
                d0 = Dm[order[a], order[a + 1]] + (Dm[order[b], order[b + 1]] if b + 1 < len(order) else 0)
                d1 = Dm[order[a], order[b]] + (Dm[order[a + 1], order[b + 1]] if b + 1 < len(order) else 0)
                if d1 < d0 - 1:
                    order[a + 1:b + 1] = order[a + 1:b + 1][::-1]; improved = True
    return [nids[i] for i in order]

# ---------------------------------------------------------------- lines
lines, geometry = [], []      # geometry[i] = list of way ids

def route_ways(r): return [ref for typ, ref, role in r['members'] if typ == 'w' and ref in WAYS and role in ('', 'forward', 'backward', 'main')]
def route_stops(r):
    out = []
    for typ, ref, role in r['members']:
        if typ == 'n' and (role.startswith('stop') or role.startswith('platform') or role == 'station'):
            s = snap_stop(ref)
            if s is not None and (not out or out[-1] != s): out.append(s)
    return out

# urban: route masters (or lone routes)
in_master = set()
masters = [(rid, r) for rid, r in RELS.items() if r['tags'].get('type') == 'route_master']
for rid, m in masters:
    for typ, ref, role in m['members']:
        if typ == 'r': in_master.add(ref)
def urban_kind(t):
    rt = t.get('route') or t.get('route_master')
    if rt in URBAN_ROUTE: return URBAN_ROUTE[rt]
    if rt == 'train':
        txt = ' '.join(t.get(k, '') for k in ('name', 'network', 'service', 'operator'))
        if t.get('service') in ('commuter', 'suburban') or re.search(r'市域|市郊|郊铁|机场线|城际快线|快线', txt): return 's'
    return None

groups = []
for rid, m in masters:
    k = urban_kind(m['tags'])
    if not k: continue
    routes = [RELS[ref] for typ, ref, role in m['members'] if typ == 'r' and ref in RELS]
    if routes: groups.append((k, m['tags'], routes))
for rid, r in RELS.items():
    t = r['tags']
    if t.get('type') == 'route' and rid not in in_master:
        k = urban_kind(t)
        if k: groups.append((k, t, [r]))

def split_route(n): return re.split(r'\s*(?:[:：>]|==>|=>|->|<=>|\s-\s|\s\()', n or '')[0].strip()
def clean_name(n, net):
    """'2 白云北路 - 中兴路' -> '贵阳轨道交通2号线'; 'APM: 1号航站楼 => 2号航站楼' -> 'APM'; drop '地铁 ' prefixes."""
    n = re.sub(r'^(?:地铁|轻轨|有轨|有轨电车)\s+', '', n or '')
    n = re.sub(r'^(?i:line\s*)?([A-Z]?\d+)\s.*', r'\1', n)
    n = split_route(n)
    n = n.replace('1️⃣', '1')
    if re.fullmatch(r'(?i:line\s*)?[A-Z]?\d+', n): n = net + re.sub(r'(?i)line\s*', '', n) + '号线'
    return n if cjk(n) else ''
line_network = {}   # line index -> OSM network tag (names the city: "北京地铁" -> 北京)
for k, t, routes in groups:
    ways = sorted({w for r in routes for w in route_ways(r)})
    stop_lists = [route_stops(r) for r in routes]
    stop_lists = [s for s in stop_lists if s]
    if not ways and not stop_lists: continue
    if not stop_lists and ways:
        path = chain(ways)
        near = set()
        for w in ways:
            for lon, lat in WAYS[w][1][::3] + [WAYS[w][1][-1]]:
                for d, nid in nearby_stations(lon, lat, 800): near.add(nid)
        found = [n for n in near if (is_urban_station(NODES[n][2]) or NODES[n][2].get('railway') == 'tram_stop' or k == 's')
                 and dist_to_ways(ways, NODES[n][0], NODES[n][1]) <= 60]
        if path and found:
            found.sort(key=lambda n: project(path, NODES[n][0], NODES[n][1])[0]); stop_lists = [found]
    main = max(stop_lists, key=len) if stop_lists else []
    branches = []
    for s in stop_lists:
        if s is main or set(s) <= set(main) or set(s[::-1]) <= set(main): continue
        if any(set(s) == set(b) for b in branches): continue
        branches.append(s)
    li = len(lines)
    line_network[li] = t.get('network') or next((r['tags'].get('network') for r in routes if r['tags'].get('network')), '') or ''
    loop = bool(main and main[0] == main[-1]) or '环' in (t.get('name') or '') or t.get('roundtrip') == 'yes'
    if main and main[0] == main[-1]: main = main[:-1]
    col = t.get('colour') or next((r['tags'].get('colour') for r in routes if r['tags'].get('colour')), '')
    ref = t.get('ref') or next((r['tags'].get('ref') for r in routes if r['tags'].get('ref')), '')
    lines.append([k, clean_name(zh_of(t), line_network[li]), split_route(en_of(t)), ref, col if re.fullmatch(r'#[0-9A-Fa-f]{6}', col or '') else '', -1,
                  [station_for(s) for s in main], [[station_for(s) for s in b] for b in branches], int(loop), 0, 0, ''])
    geometry.append(ways)

# intercity: route=railway relations
for rid, r in RELS.items():
    t = r['tags']
    if t.get('type') != 'route' or t.get('route') != 'railway': continue
    ways = [w for typ, w, role in r['members'] if typ == 'w' and w in WAYS]
    ways = [w for w in ways if WAYS[w][0].get('railway') in ('rail', 'narrow_gauge') and not WAYS[w][0].get('service')]
    if not ways: continue
    L_m = sum(way_len(w) for w in ways)
    def fast(t):
        m = re.match(r'\d+', t.get('maxspeed') or '')
        return t.get('highspeed') == 'yes' or (m is not None and int(m.group()) >= 200)
    hs = sum(way_len(w) for w in ways if fast(WAYS[w][0]))
    name = zh_of(t)
    kind = 'h' if (hs > 0.5 * L_m or re.search(r'高速|高铁|客专|客运专线', name)) else 'r'
    # stops: passenger stations on the track, ordered along its longest path
    lons = [p[0] for w in ways for p in WAYS[w][1]]; lats = [p[1] for w in ways for p in WAYS[w][1]]
    cand = set()
    for w in ways:
        for lon, lat in WAYS[w][1][::4] + [WAYS[w][1][-1]]:
            for d, nid in nearby_stations(lon, lat, 2500):
                cand.add(nid)
    # a high-speed line picks up extra stations only along track not tagged as slow, so a stretch of
    # a parallel conventional line in the relation doesn't add that line's local stations
    def slow(t):
        m = re.match(r'\d+', t.get('maxspeed') or '')
        return t.get('highspeed') != 'yes' and m is not None and int(m.group()) < 200
    near_ways = [w for w in ways if not slow(WAYS[w][0])] if kind == 'h' else ways
    way_set = set(ways)
    stops = [snap_stop(ref) for typ, ref, role in r['members'] if typ == 'n' and ref in NODES]
    stops = [n for n in stops if n is not None and n in NODES and is_passenger_station(NODES[n][2]) and near_open_track(*NODES[n][:2])]
    for nid in cand:
        lon, lat, st = NODES[nid]
        if not is_passenger_station(st) or is_urban_station(st): continue
        # a station the line only passes (under, over or beside) sits closer to its own line's track
        if nid not in stops and dist_to_ways(near_ways, lon, lat) <= 150 and nearest_main_way(lon, lat) in way_set:
            stops.append(nid)
    # one node per station name
    byname = {}
    for nid in stops:
        nm = stn_name(NODES[nid][2]) or str(nid)
        if nm not in byname or NODES[nid][2].get('railway') == 'station': byname[nm] = nid
    stops = list(byname.values())
    stops = order_stops(stops)
    # length along the stops (summing ways would count both tracks of double-track lines)
    along = sum(float(np.hypot(*(xy(*NODES[a][:2]) - xy(*NODES[b][:2])))) for a, b in zip(stops, stops[1:])) * 1.06
    km = round(along / 1000) if len(stops) >= 2 else round(L_m / 2000)
    lines.append([kind, name, en_of(t), t.get('ref', ''), '', -1, [station_for(s) for s in stops], [], 0, km, 0, ''])
    geometry.append(ways)

# drop unnamed stops, and intercity stops without a Chinese name (bus stands, taxi ranks and
# stray tags that OSM files as stations)
def keep(li, s):
    zh, en = stations[s][0], stations[s][1]
    return bool(cjk(zh)) if lines[li][0] in 'hr' else bool(zh or en)
for li, l in enumerate(lines):
    l[6] = [s for s in l[6] if keep(li, s)]
    l[7] = [[s for s in b if keep(li, s)] for b in l[7]]

# ---------------------------------------------------------------- station kinds, lines, transfers
for li, l in enumerate(lines):
    for s in {x for q in [l[6]] + l[7] for x in q}:
        stations[s][5].append(li)
RANK = {'h': 0, 'r': 1, 'm': 2, 's': 2, 'l': 3, 'f': 4, 't': 5}
for s in stations:
    ks = sorted({lines[li][0] for li in s[5]}, key=lambda k: RANK[k])
    s[4] = {'h': 'h', 'r': 'r', 't': 't', 'f': 'f'}.get(ks[0], 'm') if ks else 'm'
# transfers: other stations within 300 m, or the same name within 800 m
P = np.array([xy(s[2], s[3]) for s in stations]) if stations else np.zeros((0, 2))
order = np.argsort(P[:, 0]) if len(P) else []
xs = P[order, 0] if len(P) else []
import bisect
for a in range(len(stations)):
    lo = bisect.bisect_left(xs, P[a, 0] - 800); hi = bisect.bisect_right(xs, P[a, 0] + 800)
    for j in order[lo:hi]:
        if j == a: continue
        d = float(np.hypot(*(P[a] - P[j])))
        if d <= 300 or (d <= 800 and stations[a][0] and stations[a][0].rstrip('站') == stations[j][0].rstrip('站')):
            stations[a][6].append(int(j))

# ---------------------------------------------------------------- cities for urban lines
cities, city_idx = [], {}
def city_name(n):
    n = n.split(' ')[0]
    return {'香港': '香港', '澳門': '澳门'}.get(n, re.sub(r'市$', '', n))
PL = [(lon, lat, kind, name, en, pop) for lon, lat, kind, name, en, pop in PLACES.values()
      if name and (name.split(' ')[0].endswith('市') or name.startswith('香港') or name.startswith('澳門'))]
PLX = np.array([xy(p[0], p[1]) for p in PL])
def popn(p):
    try: return int(re.sub(r'[^\d]', '', p or '') or 0)
    except ValueError: return 0
BY_NAME = {city_name(p[3]): j for j, p in enumerate(PL)}
for li, l in enumerate(lines):
    if l[0] in 'hr': continue
    j = None
    net = line_network.get(li, '')
    for n in sorted(BY_NAME, key=len, reverse=True):     # "北京地铁" -> 北京, or the line's own name
        if n and len(n) >= 2 and (net.startswith(n) or l[1].startswith(n)): j = BY_NAME[n]; break
    if j is None and l[2]:
        j = next((BY_NAME[city_name(p[3])] for p in PL if p[4] and len(p[4]) > 3 and l[2].startswith(p[4].replace(' City', '') + ' ')), None)
    if j is None:
        st = [stations[s] for s in l[6]]
        if st: c = np.mean([xy(s[2], s[3]) for s in st], axis=0)
        elif geometry[li]: c = xy(*WAYS[geometry[li][0]][1][0])
        else: continue
        d = np.hypot(*(PLX - c).T)
        # favour big cities, so an airport shuttle or a suburban tram goes to the city it serves
        # rather than the county-level city it happens to sit in
        j = int(np.argmin(d / np.sqrt(np.maximum([popn(p[5]) for p in PL], 100000))))
    p = PL[j]; key = city_name(p[3])
    if key not in city_idx:
        city_idx[key] = len(cities)
        en = (p[4] or '').replace(' City', '')
        cities.append([key, en, round(p[0], 5), round(p[1], 5), popn(p[5]), 0])
    l[5] = city_idx[key]; cities[city_idx[key]][5] += 1
    # a bare number ("2号线", "T1线") gets its city's name
    if re.fullmatch(r'[A-Z]?\d+号?线', l[1]):
        l[1] = key + {'m': '地铁', 't': '有轨电车'}.get(l[0], '') + l[1]

out = {'lines': lines, 'stations': stations, 'cities': cities}
json.dump(out, open(os.path.join(ROOT, 'data', 'network.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
# all rail ways (not only line members) so gaps can be routed along the real network
pickle.dump({'geometry': geometry, 'ways': {w: (v[1], v[0], v[2]) for w, v in WAYS.items() if v[0].get('railway') in ('rail', 'narrow_gauge')
             or any(w in g for g in ())} | {w: (WAYS[w][1], WAYS[w][0], WAYS[w][2]) for g in geometry for w in g}}, open(sys.argv[2], 'wb'), protocol=5)
print('lines', len(lines), {k: sum(1 for l in lines if l[0] == k) for k in 'hrmlstf'}, 'stations', len(stations), 'cities', len(cities))
