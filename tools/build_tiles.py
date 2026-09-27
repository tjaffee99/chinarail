"""Rebuild the rail tile archive (data/tiles/*.bin) to match data/network.json.

Reads the original tiles from git history (SOURCE_REV, the first commit), so it is
reproducible and can be re-run after any change to the curation. Run after curate.py.

- Track with no listed passenger route (freight, depots, links) is removed.
- Track running past a line's terminal station (tail tracks, unopened extensions) is
  clipped at the station.
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

# ---------------------------------------------------------------- terminal clipping
def merc(lon, lat):
    return ((lon + 180) / 360, (1 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / math.pi) / 2)
def st_xy(i): return merc(S[i][2], S[i][3])
TERMINALS = {}   # line id -> [(T, [nearby stops of the line], metres per unit, radius m)]
for li, l in enumerate(L):
    if l[10] or l[8]: continue
    seqs = [l[6]] + [b for b in l[7] if len(b) >= 2]
    stops = list(dict.fromkeys(x for q in seqs for x in q))
    out = []
    for q in seqs:
        if len(q) < 2: continue
        for a in (q[0], q[-1]):
            if any(q2 is not q and a in q2[1:-1] for q2 in seqs): continue   # branch junction, not an end
            T = st_xy(a); mpu = 40075016 * math.cos(math.radians(S[a][3]))
            others = sorted((st_xy(x) for x in stops if x != a), key=lambda P: (P[0] - T[0]) ** 2 + (P[1] - T[1]) ** 2)[:6]
            if not others: continue
            out.append((T, [(P, math.hypot(P[0] - T[0], P[1] - T[1])) for P in others], mpu, 3000 if l[0] in 'mlstf' else 5000))
    TERMINALS[li] = out
# A point is past a terminal T when it is near T and farther from every other nearby stop than T is:
# track heading towards any stop of the line (however it curves) is never cut.
def away(P, T, others, mpu): return all((math.hypot(P[0] - Q[0], P[1] - Q[1]) - dq) * mpu > 40 for Q, dq in others)
def beyond(P, vis):
    for li in vis:
        hit = False
        for T, others, mpu, R in TERMINALS.get(li, ()):
            if math.hypot(P[0] - T[0], P[1] - T[1]) * mpu > R: continue
            if away(P, T, others, mpu): hit = True; break
        if not hit: return False
    return True
def keep_only_dead_ends(tiles):
    """Drop terminals whose 'tail' keeps going past the radius: that is real line
    (typically a stop missing from the OSM relation), not a stub, so it is never cut."""
    bad = set()
    for key, raw in tiles:
        z, tx, ty = key >> 26, (key >> 13) & 0x1fff, key & 0x1fff
        tile = vt.tile(); tile.ParseFromString(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
        for layer in tile.layers:
            if layer.name != 'rail': continue
            keys = list(layer.keys); vals = [read_value(v)[1] for v in layer.values]; ext = layer.extent or 4096
            for f in layer.features:
                p = {keys[f.tags[j]]: vals[f.tags[j + 1]] for j in range(0, len(f.tags), 2)}
                for li in ids_of(p['ls']):
                    for ti, (T, others, mpu, R) in enumerate(TERMINALS.get(li, ())):
                        if (li, ti) in bad: continue
                        for ln in decode_lines(list(f.geometry)):
                            for px, py in ln:
                                P = ((tx + px / ext) / 2 ** z, (ty + py / ext) / 2 ** z)
                                d = math.hypot(P[0] - T[0], P[1] - T[1]) * mpu
                                if R < d < 3 * R and away(P, T, others, mpu): bad.add((li, ti)); break
                            else: continue
                            break
    for li in TERMINALS: TERMINALS[li] = [t for ti, t in enumerate(TERMINALS[li]) if (li, ti) not in bad]
    print('terminals with a stub to clip:', sum(len(v) for v in TERMINALS.values()), '| left alone (track continues):', len(bad))

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
        keep = [not beyond(to_world(p), vis) for p in ln]
        if all(keep): out.append(ln); continue
        cur = []
        for j, p in enumerate(ln):
            if j and keep[j] != keep[j - 1]:            # boundary on this segment: bisect
                a, b = ln[j - 1], p
                lo, hi = 0.0, 1.0
                for _ in range(16):
                    m = (lo + hi) / 2; q = (a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m)
                    if (not beyond(to_world(q), vis)) == keep[j - 1]: lo = m
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
        for f in layer.features:
            props = {keys[f.tags[j]]: vals[f.tags[j + 1]] for j in range(0, len(f.tags), 2)}
            props = fn(props, z)
            if props is None: continue
            geom = None
            if layer.name == 'rail':
                vis = [i for i in ids_of(props['ls'][1]) if visible(i)]
                n = 2 ** z
                to_world = lambda p: ((tx + p[0] / ext) / n, (ty + p[1] / ext) / n)
                lines = decode_lines(list(f.geometry))
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
    keep_only_dead_ends(z12)
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
