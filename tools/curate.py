"""Curate data/network.json in place.

The network was extracted from OpenStreetMap (25 Sep 2026). OSM route relations
include things that are not passenger routes (depot tracks, bridges, reversing
spurs, yard wiring), duplicate relations, and names that are auto-romanised
pinyin blobs. This script hides the former and fixes the latter. It is
idempotent: run it again after editing the tables in names.py.

Line record: [kind, zh, en, ref, colour, city, stations, branches, loop, km, hidden, label]
  hidden: 0 shown · 1 connector (original extract) · 2 hidden by this script
  label:  short English name drawn along the line on the map
Station record: [zh, en, lon, lat, kind, lines, transfers, complex]  complex: id of the complex's main station, or -1
"""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import jieba, pypinyin
from names import LINE_EN, URBAN, STATION_EN, FREIGHT
jieba.setLogLevel(60)

ROOT = os.path.join(os.path.dirname(__file__), '..')
P = os.path.join(ROOT, 'data', 'network.json')
d = json.load(open(P))
L, S, C = d['lines'], d['stations'], d['cities']
URBAN_K = set('mlstf')
reasons = {}

def hide(i, why):
    if not L[i][10]:
        L[i][10] = 2
        reasons[i] = why

for l in L:
    while len(l) < 12: l.append('')
    if l[10] == 2: l[10] = 0          # re-evaluate on every run

# ---------------------------------------------------------------- pinyin helper
DIR = {'东': 'East', '西': 'West', '南': 'South', '北': 'North'}
def py(zh):
    """Readable pinyin for a Chinese place name: words separated, capitalised."""
    zh = re.sub(r'\s+', '', zh)
    suffix = ''
    for k, v in (('火车站', ' Railway Station'), ('站', '')):
        if zh.endswith(k) and len(zh) > len(k) + 1: zh, suffix = zh[:-len(k)], v; break
    if not suffix and len(zh) >= 3 and zh[-1] in DIR and zh[-2] not in DIR:
        zh, suffix = zh[:-1], ' ' + DIR[zh[-1]]
    words = []
    for w in jieba.cut(zh):
        if re.fullmatch(r'[一-鿿]+', w):
            s = ''.join(p.replace('lv', 'lü').replace('nv', 'nü') for p in pypinyin.lazy_pinyin(w))
            words.append(s[:1].upper() + s[1:])
        elif w.strip(): words.append(w)
    out = ' '.join(words)
    out = re.sub(r"([aeiouv])(a|e|o)", lambda m: m.group(0), out)
    return out + suffix

BLOB = re.compile(r'[A-Za-z]{15,}')
CAMEL = re.compile(r'^(?:[A-Z][a-z]+){2,}$')

# ---------------------------------------------------------------- stations
TYPO = [('Raliway', 'Railway'), ('Exhibiation', 'Exhibition'), ('Shaungdian', 'Shuangdian'),
        ('BaoquanRoad', 'Baoquan Road'), ('TangParadise', 'Tang Paradise'), ('HaiZhou', 'Haizhou')]
for s in S:
    en = s[1] or ''
    for a, b in TYPO: en = en.replace(a, b)
    # "Xi'an North Railway Station" -> "Xi'an North", except stops named after a station ("火车站")
    if not s[0].endswith('车站'): en = re.sub(r'(?i)\s+(?:railway\s+|train\s+)?station$', '', en)
    if s[0] in STATION_EN: en = STATION_EN[s[0]]
    elif re.search(r'[一-鿿]', s[0]) and (not en or en == s[0] or re.search(r'[一-鿿]', en)
                                                  or BLOB.fullmatch(en.replace(' ', '')) and ' ' not in en
                                                  or CAMEL.match(en)):
        en = py(s[0])
    s[1] = en

# one English spelling per station: "Fangshandong" / "Fangshan Dong" / "Fangshan East" -> "Fangshan East"
DIRWORD = {'Dong': 'East', 'Xi': 'West', 'Nan': 'South', 'Bei': 'North'}
for s in S:
    en, zh = s[1] or '', s[0]
    if len(zh) >= 3 and zh[-1] in DIR:
        m = re.fullmatch(r"(.+?) ?(Dong|Xi|Nan|Bei)", en, re.I)
        if m and m.group(2).capitalize() in DIRWORD and DIRWORD[m.group(2).capitalize()] == DIR[zh[-1]]:
            base = m.group(1)
            en = (base[:1].upper() + base[1:]) + ' ' + DIR[zh[-1]]
    s[1] = en
by_name = {}
for i, s in enumerate(S): by_name.setdefault(s[0], []).append(i)
for zh, ids in by_name.items():
    if len(ids) < 2: continue
    for i in ids:     # nodes of the same station (same name within 3 km) share the most common spelling
        grp = [j for j in ids if abs(S[j][2] - S[i][2]) < 0.03 and abs(S[j][3] - S[i][3]) < 0.03]
        names = [S[j][1] for j in grp if S[j][1]]
        if len(set(names)) > 1:
            best = max(set(names), key=lambda n: (names.count(n), ' ' in n, -len(n)))
            for j in grp: S[j][1] = best

# ---------------------------------------------------------------- hide non-routes
NONROUTE = re.compile(r'特大桥|大桥|隧道|动车段|动车所|动车走行|车辆段|机务段|出入段|出入库|出入场|停车场|联络线|联线|疏解|'
                      r'走行线|绕行线|直通线|发车线|立折线|折返线|货车|货运|货线|专用线|附属线|下联线|上联线|进港|港口|码头|'
                      r'[\u4e00-\u9fff][A-H]\d线|示范段|宽轨')
NORTH_KOREA = [(124.2, 39.8), (124.4, 40.03), (125.0, 40.42), (125.6, 40.78), (126.2, 41.2), (126.9, 41.72), (127.4, 41.42),
               (128.1, 41.38), (128.2, 41.95), (128.9, 42.0), (129.3, 42.35), (129.7, 42.42), (129.9, 42.92), (130.25, 42.88),
               (130.65, 42.4), (130.7, 42.28), (129.7, 41.0), (129.0, 40.0), (128.5, 38.6), (127.0, 38.0), (125.0, 37.6), (124.5, 38.0)]
def inpoly(x, y, poly):
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1: inside = not inside
    return inside
KEEP_FEW = {'淮安有轨电车1号线'}
HANGUL = re.compile(r'[가-힯]')
for i, l in enumerate(L):
    if l[10]: continue
    zh, en = l[1], l[2]
    st = [S[x] for x in l[6]]
    in_nk = st and sum(inpoly(x[2], x[3], NORTH_KOREA) for x in st) >= 0.6 * len(st)
    if HANGUL.search(zh) or HANGUL.search(en) or re.search(r'[ŏŭ\u0400-\u04ff]', zh + en) or zh in ('白茂线',) or in_nk:
        hide(i, 'outside China'); continue
    base = re.sub(r'^\(原\)', '', re.sub(r'(重载铁路|铁路|线)$', '', zh))
    if l[0] == 'r' and (base in FREIGHT or re.search(r'港(?:线|铁路|支线|二线)$|煤|矿', zh)):
        hide(i, 'freight only'); continue
    if l[0] in 'hr' and not re.search(r'[一-鿿]', zh):
        hide(i, 'intercity line without a name (industrial or mine track)'); continue
    if l[0] in URBAN_K and not (zh or en or l[3]):
        hide(i, 'urban line without a name or number'); continue
    if l[0] in URBAN_K and not (zh or en):
        l[2] = en = (f'Tram {l[3]}' if l[0] == 't' else f'Line {l[3]}')
    if NONROUTE.search(zh) and '城际' not in zh:
        hide(i, 'non-passenger track'); continue
    if l[0] == 'r' and (len(set(l[6])) < 3 or '旧线' in zh):
        hide(i, 'conventional line with under three stops, or an old alignment'); continue
    few = len(l[6]) < 2 and not (l[0] in URBAN_K and zh in KEEP_FEW)
    if few and (l[0] in URBAN_K or (l[9] or 0) < 30):
        hide(i, 'fewer than two stations mapped'); continue

# ---------------------------------------------------------------- duplicates
def group(k): return 'u' if k in URBAN_K else k
order = sorted(range(len(L)), key=lambda i: (-len(L[i][6]), -(L[i][9] or 0), i))
kept = []
for i in order:
    l = L[i]
    if l[10]: continue
    si = set(l[6] + [s for b in l[7] for s in b])
    for j in kept:
        m = L[j]
        if group(m[0]) != group(l[0]): continue
        sj = set(m[6] + [s for b in m[7] for s in b])
        common = len(si & sj)
        if l[0] in URBAN_K:
            # urban: only the same mode; metro lines that are a stale/merged subset of a longer line,
            # or any relation whose stops are identical to another's (tram/light-rail services overlap legitimately)
            if m[0] != l[0]: continue
            same = si == sj
            subset = common >= 0.95 * len(si) and l[0] == 'm' and (l[5] == m[5])
            sameref = l[3] and l[3] == m[3] and l[5] == m[5] and common >= 0.8 * len(si)
            if not (same or subset or sameref): continue
        elif common < 0.8 * len(si):
            continue
        hide(i, f'duplicate of {m[1]}'); break
    else:
        kept.append(i)

# ---------------------------------------------------------------- stop order
# Some OSM relations list stops out of order (segments concatenated, or both directions
# interleaved). Re-sequence them along the shortest path when that is clearly shorter.
import math
def dist(a, b):
    A, B = S[a], S[b]
    return math.hypot((A[2] - B[2]) * math.cos(math.radians((A[3] + B[3]) / 2)), A[3] - B[3])
def plen(seq): return sum(dist(a, b) for a, b in zip(seq, seq[1:]))
def two_opt(p):
    p = list(p); improved = True
    while improved:
        improved = False
        for a in range(len(p) - 2):
            for b in range(a + 2, len(p)):
                d0 = dist(p[a], p[a + 1]) + (dist(p[b], p[b + 1]) if b + 1 < len(p) else 0)
                d1 = dist(p[a], p[b]) + (dist(p[a + 1], p[b + 1]) if b + 1 < len(p) else 0)
                if d1 < d0 - 1e-9:
                    p[a + 1:b + 1] = reversed(p[a + 1:b + 1]); improved = True
    return p
def or_opt(p):
    """Move runs of 1-3 stops (either way round) to wherever they fit best."""
    p = list(p); improved = True
    def cost(q): return plen(q)
    while improved:
        improved = False
        base = cost(p)
        for k in (1, 2, 3):
            for a in range(len(p) - k + 1):
                seg = p[a:a + k]; rest = p[:a] + p[a + k:]
                for b in range(len(rest) + 1):
                    if b == a: continue
                    for sg in (seg, seg[::-1]):
                        q = rest[:b] + sg + rest[b:]
                        c = cost(q)
                        if c < base - 1e-9: p, base, improved = q, c, True; break
                    if improved: break
                if improved: break
            if improved: break
    return p
def resequence(p):
    prev = None
    while prev != p:
        prev = p; p = or_opt(two_opt(p))
    return p
def shortest(seq):
    pts = list(dict.fromkeys(seq)); best = None
    for start in pts:
        rem = set(pts); rem.discard(start); p = [start]
        while rem:
            n = min(rem, key=lambda r: dist(p[-1], r)); p.append(n); rem.discard(n)
        if best is None or plen(p) < plen(best): best = p
    return resequence(best)
reordered = 0
for l in L:
    if l[10] or l[8] or len(l[6]) < 4 or len(l[6]) > 150: continue
    seq = list(dict.fromkeys(l[6]))
    local = resequence(seq)                   # fixes local reversals and strays, keeps OSM's overall order
    if (plen(seq) - plen(local)) * 111 > 0.3: seq = local
    b = shortest(seq)                          # badly scrambled lists: rebuild from scratch
    if plen(seq) > 1.2 * plen(b): seq = b
    if seq != l[6]:
        if dist(seq[0], l[6][0]) > dist(seq[-1], l[6][0]): seq.reverse()   # keep the original direction
        reordered += seq != l[6]
        l[6] = seq
    # drop a stop repeated back-to-back (same station, or same name on both sides of the street)
    out = []
    for x in l[6]:
        if out and (x == out[-1] or S[x][0] == S[out[-1]][0]): continue
        out.append(x)
    l[6] = out
print('stop lists re-sequenced:', reordered)

# ---------------------------------------------------------------- names
CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
def cn2int(s):
    if s.isdigit(): return int(s)
    if s == '十': return 10
    if s.startswith('十'): return 10 + CN_NUM[s[1]]
    if len(s) == 2 and s[1] == '十': return CN_NUM[s[0]] * 10
    if len(s) == 3: return CN_NUM[s[0]] * 10 + CN_NUM[s[2]]
    return CN_NUM[s]

for i, l in enumerate(L):
    k, zh = l[0], l[1]
    if k in URBAN_K:
        if zh in URBAN:
            en, ref = URBAN[zh]
            l[2] = en
            if ref is not None: l[3] = ref
        else:
            m = re.search(r'([A-Z]?)([0-9]+|[一二三四五六七八九十]+)号线', zh)
            if m:
                n = m.group(1) + str(cn2int(m.group(2)))
                if '有轨电车' in zh or k == 't':
                    l[2], l[3] = f'Tram Line {n}', ('T' + n if n.isdigit() else n)
                else:
                    l[2] = f'Line {n}' + (' Branch' if '支线' in zh else '')
                    if not re.fullmatch(r'[A-Z]?\d+[A-Z]?', l[3] or ''): l[3] = n
            else:
                en = l[2]
                en = re.sub(r'^(?:Beijing|Shanghai|Guangzhou|Shenzhen|Chengdu|Wuhan|Xi.an|Tianjin|Nanjing|Hangzhou|Chongqing|'
                            r'Changsha|Suzhou|Shenyang|Qingdao|Jinan|Zhengzhou|Kunming|Hefei|Ningbo|Dalian|Changchun|Harbin|'
                            r'Fuzhou|Xiamen|Nanning|Nanchang|Guiyang|Wuxi|Xuzhou|Foshan|Dongguan)\s+'
                            r'(?:Subway|Metro|Rail Transit|Urban Rail Transit)\s+', '', en)
                en = re.sub(r'\s*\((?:[A-Z][a-z]+ )?(?:Metro|Rail Transit|Chongqing Rail Transit)\)$', '', en)
                en = re.sub(r"^[A-Z][a-zü]+(?:['’][a-z]+)?\s+(?:Subway|Metro|Rail Transit|Urban Rail Transit|Tram)\s+(?=\S)", '', en)
                en = re.sub(r'^(?:Subway|Metro|MTR)\s+', '', en)
                en = re.sub(r'^Line ([A-Za-z]+)$', lambda m: m.group(1).capitalize() + ' Line', en)
                l[2] = en
        l[2] = l[2].replace('line', 'Line') if re.fullmatch(r'.* line', l[2]) else l[2]
        l[11] = ''
    else:
        if zh in LINE_EN:
            l[2] = LINE_EN[zh]
        elif BLOB.search(l[2]) or not l[2] or re.search(r'[一-鿿]', l[2]):
            base = re.sub(r'(高速铁路|高速线|高铁|客运专线|客专线|城际铁路|城际线|城际|铁路|线)$', '', zh)
            tail = ('High-Speed Railway' if re.search(r'高速|高铁|客专|客运专线', zh) else
                    'Intercity Railway' if '城际' in zh else 'Railway')
            l[2] = f'{py(base)} {tail}'
        l[2] = l[2].replace('_', ' ').replace(' - ', '–').replace('-', '–').replace('Highspeed', 'High-Speed') \
                   .replace('High Speed', 'High-Speed').replace('high-speed railway', 'High-Speed Railway') \
                   .replace('High–speed', 'High-Speed').replace('High–Speed', 'High-Speed').replace('intercity railway', 'Intercity Railway')
        lab = l[2]
        lab = re.sub(r'High-Speed (?:Railway|Line)|Passenger (?:Railway|Dedicated Line)|PDL', 'HSR', lab)
        lab = re.sub(r'Intercity (?:Railway|Line)', 'Intercity', lab)
        lab = re.sub(r'\s*\(.*?\)', '', lab)
        l[11] = lab

# ---------------------------------------------------------------- direction
# List stops in the order the name reads: "Beijing–Shanghai …" starts at Beijing.
def norm_en(x): return re.sub(r"[’'\s-]", '', x or '').lower()
flipped = 0
for l in L:
    if l[10] or l[0] not in 'hr' or len(l[6]) < 2: continue
    m = re.match(r"^([A-Z][^–(]*?)–(?:.*–)?([A-Z][^–(]*?)\s+(?:High-Speed|Intercity|Railway|Express|Rail)", l[2])
    if not m: continue
    a, b = norm_en(m.group(1)), norm_en(m.group(2))
    names = [norm_en(S[x][1]) for x in l[6]]
    ia = [i for i, n in enumerate(names) if n.startswith(a)]
    ib = [i for i, n in enumerate(names) if n.startswith(b)]
    if ia and ib and min(ia) > max(ib) or (ia and not ib and min(ia) > len(names) / 2) or (ib and not ia and max(ib) < len(names) / 2):
        l[6] = l[6][::-1]; flipped += 1
print('stop lists flipped to match their name:', flipped)

# ---------------------------------------------------------------- station complexes
# A railway station and the metro stations built into it are one place: same label,
# same panel, all lines listed together. Linked by OSM transfers, or metro within 400 m.
def metres(a, b): return dist(a, b) * 111000
parent = list(range(len(S)))
def find(x):
    while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b): parent[find(a)] = find(b)
served = [any(not L[x][10] for x in s[5]) for s in S]
for i, s in enumerate(S):
    for t in s[6]:
        if served[i] and served[t] and metres(i, t) < 800: union(i, t)
import bisect
rail = [i for i, s in enumerate(S) if s[4] in 'hr' and served[i]]
urban = sorted((S[i][2], i) for i, s in enumerate(S) if s[4] not in 'hr' and served[i])
xs = [u[0] for u in urban]
for r in rail:
    lo = bisect.bisect_left(xs, S[r][2] - 0.006); hi = bisect.bisect_right(xs, S[r][2] + 0.006)
    for _, u in urban[lo:hi]:
        if metres(r, u) < 400: union(r, u)
groups = {}
for i in range(len(S)):
    if served[i]: groups.setdefault(find(i), []).append(i)
def rank(i): s = S[i]; return (s[4] == 'h', s[4] == 'r', sum(not L[x][10] for x in s[5]))
ncx = 0
for s in S:
    while len(s) < 8: s.append(-1)
    s[7] = -1
for members in groups.values():
    if len(members) < 2: continue
    rep = max(members, key=rank); ncx += 1
    for m in members: S[m][7] = rep
print('station complexes:', ncx)

json.dump(d, open(P, 'w'), ensure_ascii=False, separators=(',', ':'))
from collections import Counter
print('hidden by curation:', Counter(v.split(' of ')[0] for v in reasons.values()))
if '-v' in sys.argv:
    for i, v in sorted(reasons.items()): print(i, L[i][0], L[i][1], '|', v)
