"""Rebuild the rail tile archive (data/tiles/*.bin) to match data/network.json.

Reads the original tiles from git history (SOURCE_REV, the first commit), so it is
reproducible and can be re-run after any change to the curation. Run after curate.py.

- Track with no listed passenger route (freight, depots, links) is removed.
- Line geometry pass (see "line geometry" below): tails past end stops are cut, missing
  end stations are added to the stop lists (written back to data/network.json), and gaps
  between stops are filled from the track of the line that carries them.
- Otherwise geometry is kept as is; properties are rewritten.

rail layer:  l  primary visible line id (-1 if none)   ls  all line ids "|a|b|"
             k  kind drawn (h r m l s t f, or x = track with no listed route)
             ko original kind   r/c  badge text and colour (urban)
             nm / nz  English / Chinese line name for labels along intercity lines
stn layer:   i station id, n/z names, k kind, x lines served, rk rank, ls line ids
             (stations with no listed line are dropped)
"""
import gzip, json, math, os, struct, subprocess
from collections import defaultdict
import mapbox_vector_tile.Mapbox.vector_tile_pb2 as vt

ROOT = os.path.join(os.path.dirname(__file__), '..')
D = json.load(open(os.path.join(ROOT, 'data', 'network.json')))
L, S = D['lines'], D['stations']
MAN = os.path.join(ROOT, 'data', 'manifest.json')
SOURCE_REV = '23a0e31'
def git_blob(path): return subprocess.run(['git', '-C', ROOT, 'show', f'{SOURCE_REV}:{path}'], capture_output=True, check=True).stdout
manifest = json.loads(git_blob('data/manifest.json'))
TDIR = os.path.join(ROOT, 'data', 'tiles')

COMPLEX = {}
for _i, _s in enumerate(S):
    if len(_s) > 7 and _s[7] >= 0: COMPLEX.setdefault(_s[7], []).append(_i)

# ---------------------------------------------------------------- line geometry
# OSM route relations don't always match their own stop lists. A pass over the finest
# tiles (z12) builds each line's track as a point cloud and fixes three things:
#   1. track past a line's last stop is cut (tail tracks, depot runs, unopened extensions);
#   2. if that track ends at a real station missing from the stop list, that station is
#      added as the terminus instead (e.g. a relation that omits its terminal station);
#   3. if a line has no track of its own between two consecutive stops, it borrows the
#      track of the line that carries it there (e.g. a corridor sharing another line).
import numpy as np
def merc(lon, lat):
    return ((lon + 180) / 360, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2)
def st_xy(i): return merc(S[i][2], S[i][3])
SXY = np.array([st_xy(i) for i in range(len(S))])
def mpu_at(i): return 40075016 * math.cos(math.radians(S[i][3]))
URBAN = set('mlstf')
def stops_of(l): return list(dict.fromkeys(x for q in [l[6]] + list(l[7]) for x in q))

TERM = {}   # line id -> [(T xy, other stops xy (m,2), their distance to T (m,), metres per unit)]
TAIL_R = 30000
def build_terminals():
    TERM.clear()
    for li, l in enumerate(L):
        if l[10] or l[8]: continue
        seqs = [l[6]] + [b for b in l[7] if len(b) >= 2]
        stops = stops_of(l)
        out = []
        for q in seqs:
            if len(q) < 2: continue
            for a in (q[0], q[-1]):
                if any(q2 is not q and a in q2[1:-1] for q2 in seqs): continue   # branch junction, not an end
                T = SXY[a]; Q = SXY[[x for x in stops if x != a]]
                out.append((T, Q, np.hypot(*(Q - T).T), mpu_at(a)))
        TERM[li] = out
def past_terminal(P, li):
    """P: (n,2) points. True where P is past one of the line's end stops: within 30 km of it
    and farther from every other stop of the line than the end stop is (so track heading
    towards any stop, however it curves, is never cut)."""
    hit = np.zeros(len(P), bool)
    for T, Q, dQ, mpu in TERM.get(li, ()):
        near = np.hypot(*(P - T).T) * mpu < TAIL_R
        if not near.any(): continue
        dPQ = np.sqrt(((P[near][:, None, :] - Q[None, :, :]) ** 2).sum(-1))
        hit[near] |= ((dPQ - dQ[None, :]) * mpu > 40).all(1)
    return hit
def beyond_all(P, vis):
    m = np.ones(len(P), bool)
    for li in vis:
        m &= past_terminal(P, li)
        if not m.any(): break
    return m

def tile_points(key, raw):
    z, tx, ty = key >> 26, (key >> 13) & 0x1fff, key & 0x1fff
    tile = vt.tile(); tile.ParseFromString(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    for layer in tile.layers:
        if layer.name != 'rail': continue
        keys = list(layer.keys); vals = [read_value(v)[1] for v in layer.values]; ext = layer.extent or 4096
        for f in layer.features:
            p = {keys[f.tags[j]]: vals[f.tags[j + 1]] for j in range(0, len(f.tags), 2)}
            pts = [pt for ln in decode_lines(list(f.geometry)) for pt in ln]
            if pts:
                a = np.array(pts, float)
                yield ids_of(p['ls']), np.column_stack(((tx + a[:, 0] / ext) / 2 ** z, (ty + a[:, 1] / ext) / 2 ** z))

V = {}
Z12 = []   # (ids, [linestring (n,2)]) for every z12 rail feature, hidden lines included
def tile_lines(key, raw):
    z, tx, ty = key >> 26, (key >> 13) & 0x1fff, key & 0x1fff
    tile = vt.tile(); tile.ParseFromString(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    for layer in tile.layers:
        if layer.name != 'rail': continue
        keys = list(layer.keys); vals = [read_value(v)[1] for v in layer.values]; ext = layer.extent or 4096
        for f in layer.features:
            p = {keys[f.tags[j]]: vals[f.tags[j + 1]] for j in range(0, len(f.tags), 2)}
            lines = []
            for ln in decode_lines(list(f.geometry)):
                a = np.array(ln, float)
                lines.append(np.column_stack(((tx + a[:, 0] / ext) / 2 ** z, (ty + a[:, 1] / ext) / 2 ** z)))
            yield ids_of(p['ls']), lines
def build_index(z12):
    acc = defaultdict(list)
    for key, raw in z12:
        for ids, lines in tile_lines(key, raw):
            Z12.append((ids, lines))
            P = np.concatenate(lines)
            for i in ids:
                if visible(i): acc[i].append(P)
    V.update({i: np.concatenate(v) for i, v in acc.items()})

def extend_ends():
    """Where a line's track runs on past its end stop and finishes at a station missing from
    the stop list, make that station the terminus."""
    n = 0
    SERVED = np.array([any(visible(x) for x in s[5]) for s in S])
    for li, l in enumerate(L):
        if l[10] or l[8] or l[0] not in 'hr' or len(l[6]) < 2 or li not in V: continue
        for end in (0, -1):
            a = l[6][end]; T = SXY[a]; mpu = mpu_at(a)
            stops = stops_of(l); Q = SXY[[x for x in stops if x != a]]; dQ = np.hypot(*(Q - T).T)
            P = V[li]; dT = np.hypot(*(P - T).T) * mpu
            cand = np.where(dT < TAIL_R)[0]
            if not len(cand): continue
            dPQ = np.sqrt(((P[cand][:, None, :] - Q[None, :, :]) ** 2).sum(-1))
            past = cand[((dPQ - dQ[None, :]) * mpu > 40).all(1)]
            if not len(past) or dT[past].max() < 300: continue
            E = P[past[np.argmax(dT[past])]]
            dE = np.hypot(*(SXY - E).T) * mpu
            ok = (dE < 2000) & SERVED & (np.hypot(*(SXY - T).T) * mpu > 500)
            for x in np.where(ok)[0]:
                # only a major railway station: metro lines routinely end beside other lines' stations
                nlines = sum(visible(y) for y in S[x][5])
                ok[x] = x not in stops and S[x][4] in 'hr' and (nlines >= 3 or (len(S[x]) > 7 and S[x][7] >= 0))
            if ok.any():
                x = int(np.where(ok)[0][np.argmin(dE[ok])])
                if end == 0: l[6].insert(0, x)
                else: l[6].append(x)
                n += 1
    print('line ends extended to a station missing from the stop list:', n)

PATHS = []   # (line id, path polyline (k,2), bbox lo, bbox hi)
def track_path(A, B, d, urban_city):
    """Shortest path along track (any line, hidden connectors included) from station A to B."""
    import heapq
    lo = np.minimum(A, B) - 0.4 * d; hi = np.maximum(A, B) + 0.4 * d
    g = 2.5e-7   # snap grid, about 10 m
    adj = defaultdict(list); pos = {}; ends = []; piece_of = defaultdict(set)
    for ids, lines in Z12:
        kinds = {L[i][0] for i in ids if 0 <= i < len(L)}
        if urban_city is None and kinds and not kinds & set('hr'): continue   # plain track (no relation) counts
        if urban_city is not None and not any(0 <= i < len(L) and L[i][0] in URBAN and L[i][5] == urban_city for i in ids): continue
        for ln in lines:
            if (ln.max(0) < lo).any() or (ln.min(0) > hi).any(): continue
            inside = np.hypot(*(ln - A).T) + np.hypot(*(ln - B).T) <= 1.6 * d
            if not inside.any(): continue
            pid = len(ends); nodes = [(round(x / g), round(y / g)) for x, y in ln]
            ends.append((nodes[0], nodes[-1]))
            for k in nodes: piece_of[k].add(pid)
            for j in range(len(ln) - 1):
                if not (inside[j] or inside[j + 1]): continue
                u = (round(ln[j][0] / g), round(ln[j][1] / g)); v = (round(ln[j + 1][0] / g), round(ln[j + 1][1] / g))
                if u == v: continue
                w = float(np.hypot(*(ln[j] - ln[j + 1])))
                adj[u].append((v, w)); adj[v].append((u, w)); pos[u] = ln[j]; pos[v] = ln[j + 1]
    if not pos: return None
    # tiles clip each line at their own buffer edge, and simplification can drop a junction
    # vertex, so touching tracks may not share a vertex: tie every node to the nearest segment
    tol = 30 / (40075016 * math.cos(math.atan(math.sinh(math.pi * (1 - 2 * A[1])))))
    segs = [(u, v) for u in adj for v, _ in adj[u] if u < v]
    cell = 40 * tol; grid = defaultdict(list)
    for k, (u, v) in enumerate(segs):
        (x0, y0), (x1, y1) = pos[u], pos[v]
        for cx in range(int(min(x0, x1) / cell), int(max(x0, x1) / cell) + 1):
            for cy in range(int(min(y0, y1) / cell), int(max(y0, y1) / cell) + 1):
                grid[(cx, cy)].append(k)
    for u in list(adj):
        X = pos[u]; best = None
        near = {w for w, _ in adj[u]}
        for k in grid.get((int(X[0] / cell), int(X[1] / cell)), ()):
            a, b = segs[k]
            if u in (a, b) or a in near or b in near: continue
            Pa, Pb = pos[a], pos[b]; ab = Pb - Pa; t = min(1, max(0, float(np.dot(X - Pa, ab) / max(np.dot(ab, ab), 1e-30))))
            dd = float(np.hypot(*(X - (Pa + ab * t))))
            if dd <= tol and (best is None or dd < best[0]): best = (dd, a, b)
        if best:
            for w in best[1:]:
                c = float(np.hypot(*(pos[w] - X))); adj[u].append((w, c)); adj[w].append((u, c))
    keys = list(pos); xy = np.array([pos[k] for k in keys])
    # neighbouring tiles leave gaps of up to ~100 m between pieces of one track, and the extract
    # has short holes (a missing bridge or tunnel way): join each piece's ends to the nearest
    # vertex of another piece within 300 m, at a detour penalty
    far = tol * 10; index = {k: i for i, k in enumerate(keys)}
    for pid, (u0, u1) in enumerate(ends):
        for u in (u0, u1):
            if u not in index: continue
            dd = np.hypot(*(xy - pos[u]).T)
            seen = {pid}
            for j in np.argsort(dd)[:60]:
                if dd[j] > far: break
                w = keys[j]
                if piece_of[w] & seen: continue
                seen |= piece_of[w]
                c = float(dd[j]) * 1.5; adj[u].append((w, c)); adj[w].append((u, c))
    dA = np.hypot(*(xy - A).T); dB = np.hypot(*(xy - B).T)
    src = [keys[i] for i in np.where(dA < 0.15 * d)[0]] or [keys[int(np.argmin(dA))]]
    dst = {keys[i] for i in np.where(dB < min(dB.min() * 3 + 1e-6, 0.15 * d))[0]}
    dist = {k: 4 * float(np.hypot(*(pos[k] - A))) for k in src}; prev = {}   # getting onto the track far from A is expensive
    h = [(v, k) for k, v in dist.items()]; heapq.heapify(h)
    while h:
        du, u = heapq.heappop(h)
        if du > dist.get(u, 1e9): continue
        if u in dst:
            path = [u]
            while path[-1] in prev: path.append(prev[path[-1]])
            P = np.array([pos[k] for k in reversed(path)])
            return P if len(P) >= 2 else None
        for v, w in adj[u]:
            nd = du + w
            if nd < dist.get(v, 1e9): dist[v] = nd; prev[v] = u; heapq.heappush(h, (nd, v))
    return None

def find_gaps():
    """Consecutive stops with no track of the line between them: route along the track."""
    n = 0
    for li, l in enumerate(L):
        if l[10]: continue
        for q in [l[6]] + list(l[7]):
            for a, b in zip(q, q[1:]):
                A, B = SXY[a], SXY[b]; d = float(np.hypot(*(A - B))); mpu = mpu_at(a)
                if d * mpu < 2000: continue
                if li in V:
                    P = V[li]; dA = np.hypot(*(P - A).T); dB = np.hypot(*(P - B).T)
                    if ((dA + dB <= 1.35 * d) & (np.minimum(dA, dB) >= 0.2 * d)).any(): continue
                path = track_path(A, B, d, l[5] if l[0] in URBAN else None)
                if path is None: continue
                # the path must reach both stations and stay plausibly direct
                if np.hypot(*(path[0] - A)) * mpu > 1500 or np.hypot(*(path[-1] - B)) * mpu > 1500: continue
                if np.hypot(*np.diff(path, axis=0).T).sum() > 2.2 * d: continue
                PATHS.append((li, path, path.min(0), path.max(0), mpu)); n += 1
    print('gaps between stops routed along the track:', n)

def seg_dist(P, Q):
    """Distance from each point in P (n,2) to the polyline Q (k,2)."""
    A = Q[:-1][None]; B = Q[1:][None]; X = P[:, None]
    AB = B - A; t = np.clip(((X - A) * AB).sum(-1) / np.maximum((AB * AB).sum(-1), 1e-30), 0, 1)
    return np.hypot(*(X - (A + AB * t[..., None])).transpose(2, 0, 1)).min(1)
def borrowers(W, z):
    add = set()
    if not len(W): return add
    lo, hi = W.min(0), W.max(0)
    for li, path, plo, phi, mpu in PATHS:
        tol = max(15 / mpu, 2 / (2 ** z * 256))   # tight: parallel tracks of other lines stay out
        if (lo > phi + tol).any() or (hi < plo - tol).any(): continue
        if (seg_dist(W, path) <= tol).mean() >= 0.6: add.add(li)
    return add

def decode_lines(geom):
    lines, cur, x, y, i = [], None, 0, 0, 0
    while i < len(geom):
        cmd, cnt = geom[i] & 7, geom[i] >> 3; i += 1
        if cmd == 7: continue
        for _ in range(cnt):
            dx, dy = geom[i], geom[i + 1]; i += 2
            x += (dx >> 1) ^ -(dx & 1); y += (dy >> 1) ^ -(dy & 1)
            if cmd == 1: cur = [(x, y)]; lines.append(cur)
            else: cur.append((x, y))
    return lines
def encode_lines(lines):
    out, x, y = [], 0, 0
    zz = lambda v: (v << 1) ^ (v >> 31)
    for ln in lines:
        out.append(1 | (1 << 3)); out += [zz(ln[0][0] - x), zz(ln[0][1] - y)]; x, y = ln[0]
        out.append(2 | ((len(ln) - 1) << 3))
        for px, py in ln[1:]: out += [zz(px - x), zz(py - y)]; x, y = px, py
    return out
def clip(lines, to_world, vis):
    out = []
    for ln in lines:
        W = np.array([to_world(p) for p in ln])
        keep = list(~beyond_all(W, vis))
        if all(keep): out.append(ln); continue
        cur = []
        for j, p in enumerate(ln):
            if j and keep[j] != keep[j - 1]:            # boundary on this segment: bisect
                a, b = ln[j - 1], p
                lo, hi = 0.0, 1.0
                for _ in range(14):
                    m = (lo + hi) / 2; q = (a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m)
                    if (not beyond_all(np.array([to_world(q)]), vis)[0]) == keep[j - 1]: lo = m
                    else: hi = m
                q = (round(a[0] + (b[0] - a[0]) * lo), round(a[1] + (b[1] - a[1]) * lo))
                if keep[j - 1]: cur.append(q); out.append(cur); cur = []
                else: cur = [q]
            if keep[j]: cur.append(p)
        if cur: out.append(cur)
    return [c for c in out if len(c) >= 2 and c[0] != c[-1] or len(c) > 2]

def visible(i): return 0 <= i < len(L) and not L[i][10]
def ids_of(ls): return [int(x) for x in str(ls).split('|') if x]

VALUE_FIELDS = ('string_value', 'float_value', 'double_value', 'int_value', 'uint_value', 'sint_value', 'bool_value')
def read_value(v):
    for f in VALUE_FIELDS:
        if v.HasField(f): return (f, getattr(v, f))
    return ('string_value', '')

def pick_primary(vis, kind, old):
    if old in vis: return old
    same = [i for i in vis if L[i][0] == kind] or vis
    return max(same, key=lambda i: (L[i][9] or 0, len(L[i][6])))

def rail_props(p, z):
    ids = ids_of(p['ls'][1])
    ko = p['k'][1]
    vis = [i for i in ids if visible(i)]
    if not vis: return None
    kinds = {L[i][0] for i in vis}
    kind = ko if ko in kinds else L[pick_primary(vis, ko, -1)][0]
    old = p['l'][1]
    prim = pick_primary(vis, kind, old if old >= 0 else -1)
    p['k'] = ('string_value', kind)
    p['l'] = (p['l'][0] if p['l'][0] != 'uint_value' else 'sint_value', prim)
    if kind in 'hr' and 5 <= z <= 11:
        lab = [i for i in vis if L[i][0] == kind]
        best = max(lab, key=lambda i: (L[i][9] or 0, len(L[i][6]))) if lab else prim
        p['nm'] = ('string_value', L[best][11] or L[best][2])
        p['nz'] = ('string_value', L[best][1])
    else:
        p.pop('nm', None); p.pop('nz', None)
        if 'r' in p: p['r'] = ('string_value', L[prim][3] or '')
        if 'c' in p and L[prim][4]: p['c'] = ('string_value', L[prim][4])
    return p

def stn_props(p, z):
    ids = ids_of(p['ls'][1])
    vis = [i for i in ids if visible(i)]
    if ids and not vis: return None
    si = p['i'][1]; s = S[si]
    p['n'] = ('string_value', s[1] or s[0])
    rep = s[7] if len(s) > 7 and s[7] >= 0 else si
    members = COMPLEX.get(rep, [si])
    own = {L[i][0] for i in vis}
    allv = {i for m in members for i in S[m][5] if visible(i)}
    p['ks'] = ('string_value', ''.join(sorted(own)))                       # modes serving this node
    p['kc'] = ('string_value', ''.join(sorted({L[i][0] for i in allv})))   # modes serving the complex
    p['cx'] = ('int_value', rep); p['rep'] = ('int_value', int(rep == si))
    p['x'] = ('int_value', len({L[i][1] for i in allv}))
    return p

def rewrite(raw, key):
    z, tx, ty = key >> 26, (key >> 13) & 0x1fff, key & 0x1fff
    tile = vt.tile(); tile.ParseFromString(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    for layer in tile.layers:
        keys = list(layer.keys); vals = [read_value(v) for v in layer.values]
        fn = rail_props if layer.name == 'rail' else stn_props if layer.name == 'stn' else None
        if fn is None: continue
        feats = []
        ext = layer.extent or 4096
        n = 2 ** z
        to_world = lambda p: ((tx + p[0] / ext) / n, (ty + p[1] / ext) / n)
        for f in layer.features:
            props = {keys[f.tags[j]]: vals[f.tags[j + 1]] for j in range(0, len(f.tags), 2)}
            geom = None
            if layer.name == 'rail':
                lines = decode_lines(list(f.geometry))
                W = np.array([to_world(p) for ln in lines for p in ln])
                ids = ids_of(props['ls'][1])
                extra = borrowers(W, z) - set(ids)
                if extra: props['ls'] = ('string_value', '|' + '|'.join(str(i) for i in ids + sorted(extra)) + '|')
            props = fn(props, z)
            if props is None: continue
            if layer.name == 'rail':
                vis = [i for i in ids_of(props['ls'][1]) if visible(i)]
                clipped = clip(lines, to_world, vis)
                if not clipped: continue
                if clipped != lines: geom = encode_lines(clipped)
            feats.append((f, props, geom))
        new_keys, new_vals, kidx, vidx = [], [], {}, {}
        kept = []
        for f, props, geom in feats:
            tags = []
            for k, v in props.items():
                if k not in kidx: kidx[k] = len(new_keys); new_keys.append(k)
                if v not in vidx: vidx[v] = len(new_vals); new_vals.append(v)
                tags += [kidx[k], vidx[v]]
            nf = vt.tile.feature(); nf.CopyFrom(f); del nf.tags[:]; nf.tags.extend(tags)
            if geom is not None: del nf.geometry[:]; nf.geometry.extend(geom)
            kept.append(nf)
        del layer.features[:]; layer.features.extend(kept)
        del layer.keys[:]; layer.keys.extend(new_keys)
        del layer.values[:]
        for field, val in new_vals:
            v = layer.values.add(); setattr(v, field, val)
    return gzip.compress(tile.SerializeToString(), compresslevel=9, mtime=0)

def read_chunk(buf):
    n = struct.unpack_from('<I', buf, 4)[0]; base = 8 + n * 12
    return [(k, buf[base + o: base + o + ln]) for k, o, ln in (struct.unpack_from('<III', buf, 8 + i * 12) for i in range(n))]

def write_chunk(entries):
    entries.sort(); idx, data, off = [], [], 0
    for k, t in entries:
        idx.append(struct.pack('<III', k, off, len(t))); data.append(t); off += len(t)
    return b'TPK1' + struct.pack('<I', len(entries)) + b''.join(idx) + b''.join(data)

def main():
    z12 = []
    for fn, off, ln in {tuple(v) for m in manifest.values() for v in m['chunks'].values()}:
        z12 += [(k, t) for k, t in read_chunk(git_blob('data/tiles/' + fn)[off:off + ln]) if k >> 26 == 12]
    build_index(z12)
    extend_ends()
    build_terminals()
    find_gaps()
    json.dump(D, open(os.path.join(ROOT, 'data', 'network.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    for src, m in manifest.items():
        files = {}
        byfile = defaultdict(list)
        for key, (fn, off, ln) in m['chunks'].items(): byfile[fn].append((off, key, ln))
        newchunks = {}
        for fn, items in sorted(byfile.items()):
            buf = git_blob('data/tiles/' + fn)
            out, pos = [], 0
            for off, key, ln in sorted(items):
                chunk = write_chunk([(k, rewrite(t, k)) for k, t in read_chunk(buf[off:off + ln])])
                newchunks[key] = [fn, pos, len(chunk)]; out.append(chunk); pos += len(chunk)
            open(os.path.join(TDIR, fn), 'wb').write(b''.join(out))
            print(fn, pos)
        m['chunks'] = newchunks
    json.dump(manifest, open(MAN, 'w'), separators=(',', ':'))

if __name__ == '__main__':
    main()
