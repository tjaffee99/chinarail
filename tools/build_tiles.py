"""Rewrite the rail tile archive (data/tiles/*.bin) to match data/network.json.

Only feature properties are changed; geometry is copied byte-for-byte. Run after
curate.py. Idempotent: the original segment kind is kept in `ko`.

rail layer:  l  primary visible line id (-1 if none)   ls  all line ids "|a|b|"
             k  kind drawn (h r m l s t f, or x = track with no listed route)
             ko original kind   r/c  badge text and colour (urban)
             nm / nz  English / Chinese line name for labels along intercity lines
stn layer:   i station id, n/z names, k kind, x lines served, rk rank, ls line ids
             (stations with no listed line are dropped)
"""
import gzip, json, os, struct
from collections import defaultdict
import mapbox_vector_tile.Mapbox.vector_tile_pb2 as vt

ROOT = os.path.join(os.path.dirname(__file__), '..')
D = json.load(open(os.path.join(ROOT, 'data', 'network.json')))
L, S = D['lines'], D['stations']
MAN = os.path.join(ROOT, 'data', 'manifest.json')
manifest = json.load(open(MAN))
TDIR = os.path.join(ROOT, 'data', 'tiles')

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
    ko = p.get('ko', p['k'])[1]
    p['ko'] = ('string_value', ko)
    vis = [i for i in ids if visible(i)]
    if not vis:
        p['k'] = ('string_value', 'x'); p['l'] = (p['l'][0], -1) if p['l'][0] != 'uint_value' else ('sint_value', -1)
        for k in ('nm', 'nz', 'r', 'c'): p.pop(k, None)
        return p
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
    s = S[p['i'][1]]
    p['n'] = ('string_value', s[1] or s[0])
    if len(vis) < len(ids) and 'x' in p: p['x'] = (p['x'][0], len({L[i][1] for i in vis}))
    return p

def rewrite(raw, z):
    tile = vt.tile(); tile.ParseFromString(gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw)
    for layer in tile.layers:
        keys = list(layer.keys); vals = [read_value(v) for v in layer.values]
        fn = rail_props if layer.name == 'rail' else stn_props if layer.name == 'stn' else None
        if fn is None: continue
        feats = []
        for f in layer.features:
            props = {keys[f.tags[j]]: vals[f.tags[j + 1]] for j in range(0, len(f.tags), 2)}
            props = fn(props, z)
            if props is not None: feats.append((f, props))
        new_keys, new_vals, kidx, vidx = [], [], {}, {}
        kept = []
        for f, props in feats:
            tags = []
            for k, v in props.items():
                if k not in kidx: kidx[k] = len(new_keys); new_keys.append(k)
                if v not in vidx: vidx[v] = len(new_vals); new_vals.append(v)
                tags += [kidx[k], vidx[v]]
            nf = vt.tile.feature(); nf.CopyFrom(f); del nf.tags[:]; nf.tags.extend(tags)
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
    for src, m in manifest.items():
        files = {}
        byfile = defaultdict(list)
        for key, (fn, off, ln) in m['chunks'].items(): byfile[fn].append((off, key, ln))
        newchunks = {}
        for fn, items in sorted(byfile.items()):
            buf = open(os.path.join(TDIR, fn), 'rb').read()
            out, pos = [], 0
            for off, key, ln in sorted(items):
                chunk = write_chunk([(k, rewrite(t, k >> 26)) for k, t in read_chunk(buf[off:off + ln])])
                newchunks[key] = [fn, pos, len(chunk)]; out.append(chunk); pos += len(chunk)
            open(os.path.join(TDIR, fn), 'wb').write(b''.join(out))
            print(fn, pos)
        m['chunks'] = newchunks
    json.dump(manifest, open(MAN, 'w'), separators=(',', ':'))

if __name__ == '__main__':
    main()
