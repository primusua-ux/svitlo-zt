#!/usr/bin/env python3
"""Зіставляє адресні точки OpenStreetMap з базою ztoe і пише плитки data/pts/<lat10>_<lon10>.json.
Запуск: python3 scripts/build_points.py data
Лише стандартна бібліотека."""
import csv, gzip, json, math, os, re, sys
from collections import defaultdict, Counter

D = sys.argv[1] if len(sys.argv) > 1 else "data"

from norm import LAT2CYR, street_key, house_key, place_key

def dist(a, b, c, d):
    x = (d - b) * math.cos(math.radians((a + c) / 2)) * 111.32; y = (c - a) * 110.54
    return math.hypot(x, y)

# ---------- база ztoe ----------
index = json.load(open(f"{D}/index.json", encoding="utf-8"))
# zt[(rem, sp)] = {(typ,name): {house: [codes]}}, плюс відображувані назви
zt, disp, by_place = {}, {}, defaultdict(list)
for rem, info in index.items():
    data = json.load(open(f"{D}/{info['file']}", encoding="utf-8"))
    for sp, streets in data.items():
        m = defaultdict(lambda: defaultdict(list))
        for st, codes in streets.items():
            k = street_key(st); disp[(rem, sp, k)] = st
            for code, hs in codes.items():
                for h in hs.split(","):
                    hk = house_key(h)
                    if code not in m[k][hk]: m[k][hk].append(code)
        zt[(rem, sp)] = m
        by_place[place_key(sp)].append((rem, sp))
total_houses = sum(len(h) for m in zt.values() for h in m.values())

# ---------- OSM ----------
places = []
for ln in gzip.open(f"{D}/osm/places.tsv.gz", "rt", encoding="utf-8"):
    la, lo, kind, name, old = ln.rstrip("\n").split("\t")
    if name: places.append((float(la), float(lo), kind, name, old))
pgrid = defaultdict(list)
for p in places: pgrid[(int(p[0] * 10), int(p[1] * 10))].append(p)

RAD = {"city": 9.0, "town": 4.0, "village": 2.0, "hamlet": 1.2}
def near_places(la, lo, n=8):
    out = []
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            for p in pgrid.get((int(la * 10) + dy, int(lo * 10) + dx), ()):
                if p[2] not in RAD: continue
                d = dist(la, lo, p[0], p[1])
                if d <= RAD[p[2]] * 1.6: out.append((d / RAD[p[2]], p))
    out.sort(key=lambda x: x[0])
    return out[:n]

# географія РЕМ: за населеними пунктами з унікальною назвою
anchor = []  # (lat, lon, rem)
for p in places:
    if p[2] in ("suburb", "neighbourhood", "allotments"): continue
    c = by_place.get(place_key(p[3]), [])
    if len(c) == 1: anchor.append((p[0], p[1], c[0][0]))
agrid = defaultdict(list)
for a in anchor: agrid[(int(a[0] * 5), int(a[1] * 5))].append(a)
def rem_rank(la, lo):
    """РЕМ у порядку близькості (за найближчими якорями)."""
    best = {}
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for a in agrid.get((int(la * 5) + dy, int(lo * 5) + dx), ()):
                d = dist(la, lo, a[0], a[1])
                if d < best.get(a[2], 1e9): best[a[2]] = d
    return best

def candidates(la, lo, city=""):
    """Кандидати (rem, sp) для точки, від найімовірнішого."""
    names = []; ratio = {}
    if city: names.append(place_key(city)); ratio[names[0]] = 0
    for d, p in near_places(la, lo):
        for nm in (p[3], p[4]):
            k = place_key(nm) if nm else ""
            if k and k not in names: names.append(k); ratio[k] = d
    rr = None; out = []; first = True
    for k in names:
        if not (first or ratio[k] <= 1.0): continue
        c = by_place.get(k, [])
        if len(c) > 1:
            rr = rr or rem_rank(la, lo)
            c = sorted(c, key=lambda x: rr.get(x[0], 1e9))
            c = [x for x in c if rr.get(x[0], 1e9) < 40][:1]
        out.extend(x for x in c if x not in out)
        if out: first = False
    return out

def collapse(codes):
    """['3.2','3.2ю'] -> ['3.2'] (та сама підчерга для побутових і юридичних)."""
    plain = {c for c in codes if not c.endswith("ю")}
    return sorted(c for c in set(codes) if not (c.endswith("ю") and c[:-1] in plain))

# перейменовані вулиці: назва <-> стара назва з OSM, прив'язано до клітинки 0.1 градуса
alias = defaultdict(lambda: defaultdict(set)); street_rows = []
for ln in gzip.open(f"{D}/osm/streets.tsv.gz", "rt", encoding="utf-8"):
    la, lo, name, old = ln.rstrip("\n").split("\t"); la = float(la); lo = float(lo)
    street_rows.append((la, lo, name, old))
    if old:
        for o in re.split(r"[;,]", old):
            if not o.strip(): continue
            a, b = street_key(name), street_key(o)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    c = (int(la * 10) + dy, int(lo * 10) + dx)
                    alias[c][a].add(b); alias[c][b].add(a)

def _toks(name):
    t = name.split(); return {x for x in t if x.isdigit()}, {x for x in t if not x.isdigit()}

def find_street(m, sk, la, lo, fuzzy=True):
    """Ключ вулиці в базі населеного пункту m для OSM-ключа sk (тип, перейменування, скорочені імена)."""
    if sk in m: return sk
    alts = [k for k in m if k[1] == sk[1]]
    if len(alts) == 1: return alts[0]
    for ak in alias[(int(la * 10), int(lo * 10))].get(sk, ()):
        if ak in m: return ak
        alts = [k for k in m if k[1] == ak[1]]
        if len(alts) == 1: return alts[0]
    if fuzzy:
        # "1-й провулок Остапа Вишні" ~ "пров 1-й О.Вишні": ті самі номери, слова одного є частиною іншого
        d1, w1 = _toks(sk[1])
        if w1:
            alts = []
            for k in m:
                if k[0] != sk[0]: continue
                d2, w2 = _toks(k[1])
                if d1 == d2 and w2 and (w1 < w2 or w2 < w1) and max((w1 & w2), key=len, default="")[:1] and len(max(w1 & w2, key=len)) >= 4:
                    alts.append(k)
            if len(alts) == 1: return alts[0]
    return None

# рівень населеного пункту
plist = []; pl_hit = set()
for la, lo, kind, name, old in places:
    if kind not in RAD: continue
    for nm in (name, old):
        c = by_place.get(place_key(nm), []) if nm else []
        if len(c) > 1:
            rr = rem_rank(la, lo); c = sorted(c, key=lambda x: rr.get(x[0], 1e9)); c = [x for x in c if rr.get(x[0], 1e9) < 40][:1]
        if c:
            rem, sp = c[0]
            if (rem, sp) in pl_hit: break
            pl_hit.add((rem, sp))
            codes = collapse([x for hs in zt[(rem, sp)].values() for cs in hs.values() for x in cs])
            plist.append([round(la, 5), round(lo, 5), RAD[kind], rem, sp, "|".join(codes)]); break

# розширений пошук: землі громади бувають далеко від центру села (масиви забудови біля міста)
spgrid = defaultdict(list)
for q in plist: spgrid[(int(q[0] * 10), int(q[1] * 10))].append(q)
def ext_cands(la, lo, exclude, rmax=8.0):
    out = []
    for dy in (-1, 0, 1):
        for dx in (-2, -1, 0, 1, 2):
            for q in spgrid.get((int(la * 10) + dy, int(lo * 10) + dx), ()):
                if (q[3], q[4]) in exclude: continue
                d = dist(la, lo, q[0], q[1])
                if d <= rmax: out.append((d, (q[3], q[4])))
    return [x[1] for x in sorted(out)]
freq = Counter()
for m in zt.values():
    for nm in {k[1] for k in m}: freq[nm] += 1
COMMON = 25
anchors = defaultdict(list)   # клітинка ~1 км -> [(lat, lon, rem, sp)]
def add_anchor(la, lo, rem, sp): anchors[(int(la * 100), int(lo * 100))].append((la, lo, rem, sp))
def anchored(la, lo, r=0.8):
    out = set()
    for dy in (-1, 0, 1):
        for dx in (-2, -1, 0, 1, 2):
            for a in anchors.get((int(la * 100) + dy, int(lo * 100) + dx), ()):
                if dist(la, lo, a[0], a[1]) <= r: out.add((a[2], a[3]))
    return out

stats = Counter(); house_rows = []; cells = defaultdict(list); matched_houses = set(); seen = set(); street_hit = set()
mh = []   # знайдені будинки: (lat, lon, ключ вулиці в OSM, rem, sp, k, коди)
def take_house(la, lo, rem, sp, k, hk, hn, codes, osk=None):
    key = (rem, sp, k, hk, round(la, 4), round(lo, 4))
    if key in seen: return
    mh.append((la, lo, osk or k, rem, sp, k, "|".join(collapse(codes))))
    seen.add(key); matched_houses.add((rem, sp, k, hk)); stats["matched"] += 1
    house_rows.append((la, lo, rem, sp, k, hk, hn.strip(), "|".join(collapse(codes))))

# попередній прохід: якорі з рідкісних назв вулиць. Землі громади бувають далеко від центру села (Смоківка належить до Вересів,
# хоча найближчий населений пункт там Глибочиця), тож для поширених назв вулиць спершу дивимось на якорі поруч
for ln in gzip.open(f"{D}/osm/addr.tsv.gz", "rt", encoding="utf-8"):
    cols = ln.rstrip("\n").split("\t"); la = float(cols[0]); lo = float(cols[1]); hn = cols[2]; st = cols[3] or cols[4]
    if not hn or not st: continue
    sk = street_key(st)
    if freq[sk[1]] > COMMON: continue
    hk = house_key(hn); cs = candidates(la, lo, cols[5]); hits = set()
    for rem, sp in cs + ext_cands(la, lo, set(cs)):
        m = zt[(rem, sp)]; k = find_street(m, sk, la, lo)
        if k is not None and hk in m[k]: hits.add((rem, sp))
    if len(hits) == 1: add_anchor(la, lo, *next(iter(hits)))
stats["pre_anchors"] = sum(len(v) for v in anchors.values())

pend_h = []; polyof = {}
for ln in gzip.open(f"{D}/osm/addr.tsv.gz", "rt", encoding="utf-8"):
    cols = ln.rstrip("\n").split("\t")
    la, lo, hn, st, pl, city, sub = cols[:7]
    la = float(la); lo = float(lo); stats["osm"] += 1
    if len(cols) > 7 and cols[7]: polyof[(la, lo, hn.strip())] = cols[7]
    st = st or pl
    near = cols[8].split("|") if len(cols) > 8 and cols[8] else []
    if not hn or (not st and not near): stats["no_street"] += 1; continue
    hk = house_key(hn); hit = None
    cands = candidates(la, lo, city)
    an = [x for x in anchored(la, lo, 0.4) if x in zt]
    if an: cands = sorted(an) + [c for c in cands if c not in an]
    if not st:
        # адреса без назви вулиці: беремо найближчі вулиці, але лише якщо номер будинку є рівно на одній з них
        # найближча вулиця з таким номером приймається, якщо вона перша в списку; інакше лише за однозначності
        hits = []
        for i, nm in enumerate(near):
            sk1 = street_key(nm)
            for rem, sp in cands:
                m = zt[(rem, sp)]; k = find_street(m, sk1, la, lo)
                if k is not None and hk in m[k]: hits.append((i, (rem, sp, k, m[k][hk]))); break
        if hits and hits[0][0] == 0: hits = [hits[0][1]]
        else: hits = [h[1] for h in hits]
        if len({h[:3] for h in hits}) == 1:
            take_house(la, lo, hits[0][0], hits[0][1], hits[0][2], hk, hn, hits[0][3]); stats["inferred_street"] += 1
        else: stats["no_street"] += 1
        continue
    sk = street_key(st)
    for rem, sp in cands:
        m = zt[(rem, sp)]; k = find_street(m, sk, la, lo)
        if k is not None and hk in m[k]: hit = (rem, sp, k, m[k][hk]); break
    if hit: take_house(la, lo, hit[0], hit[1], hit[2], hk, hn, hit[3], sk)
    else: pend_h.append((la, lo, hn, sk, hk, tuple(cands)))

def ext_house(la, lo, sk, hk, pool):
    hits = []
    for rem, sp in pool:
        m = zt[(rem, sp)]; k = find_street(m, sk, la, lo)
        if k is not None and hk in m[k]: hits.append((rem, sp, k, m[k][hk]))
    return hits[0] if len(hits) == 1 else None

rest = []; unm = []
for la, lo, hn, sk, hk, cands in pend_h:          # прохід А: рідкісні назви вулиць
    hit = ext_house(la, lo, sk, hk, ext_cands(la, lo, cands)) if freq[sk[1]] <= COMMON else None
    if hit:
        take_house(la, lo, hit[0], hit[1], hit[2], hk, hn, hit[3], sk); add_anchor(la, lo, hit[0], hit[1]); stats["ext_house"] += 1
    else: rest.append((la, lo, hn, sk, hk, cands))

# рівень вулиці: відрізки доріг з назвою
sseen = set(); pend_s = []
smatch = defaultdict(list)   # клітинка 0.01 градуса -> [(lat, lon, назва в OSM, rem, sp, k)]
def take_street(la, lo, rem, sp, k, osm_name=""):
    if osm_name: smatch[(int(la * 100), int(lo * 100))].append((la, lo, street_key(osm_name), rem, sp, k))
    key = (rem, sp, k, round(la, 3), round(lo * 0.65, 3))
    if key in sseen: return
    sseen.add(key); street_hit.add((rem, sp, k)); stats["street_pts"] += 1
    codes = collapse([c for cs in zt[(rem, sp)][k].values() for c in cs])
    cells[(math.floor(la * 10), math.floor(lo * 10))].append((la, lo, rem, sp, disp[(rem, sp, k)], "", "|".join(codes)))

def street_names(name, old): return [name] + [o for o in re.split(r"[;,]", old) if o.strip()]
for la, lo, name, old in street_rows:
    cands = candidates(la, lo); done = False
    an = [x for x in anchored(la, lo, 0.4) if x in zt]
    if an: cands = sorted(an) + [c for c in cands if c not in an]
    for nm in street_names(name, old):
        sk = street_key(nm)
        for rem, sp in cands[:3]:
            k = find_street(zt[(rem, sp)], sk, la, lo)
            if k is not None: take_street(la, lo, rem, sp, k, name); done = True; break
        if done: break
    if not done: pend_s.append((la, lo, name, old, tuple(cands)))

rest_s = []
for la, lo, name, old, cands in pend_s:           # прохід А для вулиць
    done = False
    for nm in street_names(name, old):
        sk = street_key(nm)
        if freq[sk[1]] > COMMON: continue
        hits = [(rem, sp, k) for rem, sp in ext_cands(la, lo, cands) for k in [find_street(zt[(rem, sp)], sk, la, lo, fuzzy=True)] if k is not None]
        if len(hits) == 1:
            take_street(la, lo, *hits[0], name); add_anchor(la, lo, hits[0][0], hits[0][1]); stats["ext_street"] += 1; done = True; break
    if not done: rest_s.append((la, lo, name, old, cands))

for la, lo, hn, sk, hk, cands in rest:            # прохід Б: поширені назви поруч із уже знайденими сусідами
    hit = ext_house(la, lo, sk, hk, anchored(la, lo) - set(cands))
    if hit: take_house(la, lo, hit[0], hit[1], hit[2], hk, hn, hit[3], sk); stats["anchor_house"] += 1
    else: stats["house_unmatched"] += 1; unm.append((la, lo, hn, sk, hk, cands))
for la, lo, name, old, cands in rest_s:
    pool = anchored(la, lo) - set(cands)
    if not pool: continue
    for nm in street_names(name, old):
        sk = street_key(nm)
        hits = [(rem, sp, k) for rem, sp in pool for k in [find_street(zt[(rem, sp)], sk, la, lo)] if k is not None]
        if len(hits) == 1: take_street(la, lo, *hits[0], name); stats["anchor_street"] += 1; break

# та сама адреса у далеких одна від одної точках: лишаємо найближчу до центру свого населеного пункту
center = {(p[3], p[4]): (p[0], p[1]) for p in plist}
groups = defaultdict(list)
for r in house_rows: groups[(r[2], r[3], r[4], r[5])].append(r)
for key, rows in groups.items():
    if len(rows) > 1:
        la = [r[0] for r in rows]; lo = [r[1] for r in rows]
        if dist(min(la), min(lo), max(la), max(lo)) > 0.6:
            c = center.get((key[0], key[1]))
            if not c: stats["dropped_ambiguous"] += len(rows); matched_houses.discard(key); continue
            best = min(rows, key=lambda r: dist(r[0], r[1], c[0], c[1]))
            keep = [r for r in rows if dist(r[0], r[1], best[0], best[1]) <= 0.3]
            stats["dropped_ambiguous"] += len(rows) - len(keep); rows = keep
    for la, lo, rem, sp, k, hk, hn, codes in rows:
        cells[(math.floor(la * 10), math.floor(lo * 10))].append((la, lo, rem, sp, disp[(rem, sp, k)], hn, codes))

# ---------- будинки, яких немає в базі або які не мають номера на карті: підчерга за вулицею ----------
# Беремо лише однозначні випадки: уся вулиця в одній підчерзі або щонайменше три відомі сусіди
# на цій самій вулиці (до 100 м) в одній підчерзі. Такі рядки в плитці мають позначку «приблизно».
hgrid = defaultdict(list)
for h in mh: hgrid[(int(h[0] * 400), int(h[1] * 250))].append(h)
def houses_near(la, lo, r):
    n = int(r / 0.25) + 1
    for dy in range(-n, n + 1):
        for dx in range(-n, n + 1):
            for h in hgrid.get((int(la * 400) + dy, int(lo * 250) + dx), ()):
                if dist(la, lo, h[0], h[1]) <= r: yield h
def resolve(sk, la, lo, cands):
    """Вулиця бази для вулиці з OSM у цій точці або None, якщо неоднозначно."""
    g = {(h[3], h[4], h[5]) for h in houses_near(la, lo, 0.4) if h[2] == sk}
    if len(g) == 1: return next(iter(g))
    if len(g) > 1: return None
    g = set()
    for rem, sp in list(cands[:3]) + list(anchored(la, lo)):
        k = find_street(zt[(rem, sp)], sk, la, lo, fuzzy=False)
        if k is not None: g.add((rem, sp, k))
    if len(g) == 1: return next(iter(g))
    if len(g) > 1: return None
    best = None; bd = 1.5
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-3, -2, -1, 0, 1, 2, 3):
            for q in smatch.get((int(la * 100) + dy, int(lo * 100) + dx), ()):
                if q[2] != sk: continue
                d = dist(la, lo, q[0], q[1])
                if d < bd: bd = d; best = q[3:]
    return best
scode = {}
def code_for(s, la, lo):
    if s not in scode: scode[s] = collapse([c for cs in zt[(s[0], s[1])][s[2]].values() for c in cs])
    if len(scode[s]) == 1: return scode[s][0]
    cs = [h[6] for h in houses_near(la, lo, 0.1) if (h[3], h[4], h[5]) == s]
    if len(cs) >= 3 and len(set(cs)) == 1 and "|" not in cs[0]: return cs[0]
    return None
icells = defaultdict(list)
# а) адреса є на карті, але такого номера немає в базі
inf_h = defaultdict(list)
for la, lo, hn, sk, hk, cands in unm:
    s = resolve(sk, la, lo, cands)
    if not s: continue
    m = zt[(s[0], s[1])][s[2]]
    if hk in m:                                        # номер знайшовся в іншому населеному пункті: це точна адреса
        key = (s[0], s[1], s[2], hk)
        if key not in matched_houses:
            matched_houses.add(key); stats["late_house"] += 1
            cells[(math.floor(la * 10), math.floor(lo * 10))].append((la, lo, s[0], s[1], disp[s], hn.strip(), "|".join(collapse(m[hk]))))
        continue
    c = code_for(s, la, lo)
    if c is None: stats["addr_unknown"] += 1; continue
    inf_h[(s, hk)].append((la, lo, hn.strip(), c, polyof.get((la, lo, hn.strip()), "")))
for (s, hk), rows in inf_h.items():
    wp = [r for r in rows if r[4]]; pd = set()
    for la, lo, hn, c, poly in (wp or rows[:1]):
        if poly in pd and poly: continue
        pd.add(poly); stats["addr_painted"] += 1
        icells[(math.floor(la * 10), math.floor(lo * 10))].append((la, lo, s[0], s[1], disp[s], hn, c, poly))
# б) будівля без номера на карті: за найближчою вулицею
if os.path.exists(f"{D}/osm/bld.tsv.gz"):
    for ln in gzip.open(f"{D}/osm/bld.tsv.gz", "rt", encoding="utf-8"):
        la, lo, poly, near = ln.rstrip("\n").split("\t"); la = float(la); lo = float(lo); stats["bld"] += 1
        near = [(street_key(x.rsplit(":", 1)[0]), float(x.rsplit(":", 1)[1])) for x in near.split("|")]
        d1 = near[0][1]
        if d1 > 60 or not poly: continue
        cands = candidates(la, lo)
        s1 = resolve(near[0][0], la, lo, cands)
        c1 = code_for(s1, la, lo) if s1 else None
        if c1 is None: stats["bld_unknown"] += 1; continue
        ok = True
        for sk2, d in near[1:]:
            if d > max(d1 + 12, d1 * 1.5): continue
            s2 = resolve(sk2, la, lo, cands)
            if s2 and code_for(s2, la, lo) != c1: ok = False; break
        if not ok: stats["bld_ambiguous"] += 1; continue
        icells[(math.floor(la * 10), math.floor(lo * 10))].append((la, lo, s1[0], s1[1], disp[s1], "", c1, poly)); stats["bld_painted"] += 1

# ---------- запис плиток ----------
for k in icells: cells.setdefault(k, [])
out = f"{D}/pts"; os.makedirs(out, exist_ok=True)
for f in os.listdir(out): os.remove(f"{out}/{f}")
keys = []
for (cy, cx), pts in sorted(cells.items()):
    la0, lo0 = cy * 10000, cx * 10000
    names, nidx, streets, sidx, P = [], {}, [], {}, []; pdone = set()
    haspoly = defaultdict(list)
    for la, lo, rem, sp, st, hn, codes in pts:
        if hn and polyof.get((la, lo, hn)): haspoly[(rem, sp, st, house_key(hn))].append((la, lo))
    for la, lo, rem, sp, st, hn, codes in sorted(pts):
        if hn and not polyof.get((la, lo, hn)) and any(dist(la, lo, q[0], q[1]) < 0.06 for q in haspoly.get((rem, sp, st, house_key(hn)), ())):
            continue                                   # цю адресу вже показано контуром будівлі
        if (rem, sp) not in nidx: nidx[(rem, sp)] = len(names); names.append([rem, sp])
        sk = (nidx[(rem, sp)], st)
        if sk not in sidx: sidx[sk] = len(streets); streets.append([nidx[(rem, sp)], st])
        row = [round(la * 1e5) - la0, round(lo * 1e5) - lo0, sidx[sk], hn, codes]
        poly = polyof.get((la, lo, hn)) if hn else None
        if poly:
            if (sk, hn, poly) in pdone: continue      # та сама будівля двічі (точка адреси і сама будівля)
            pdone.add((sk, hn, poly)); row.append([int(x) for x in poly.split(",")]); stats["with_outline"] += 1
        P.append(row)
    for la, lo, rem, sp, st, hn, code, poly in sorted(icells.get((cy, cx), ())):
        if (rem, sp) not in nidx: nidx[(rem, sp)] = len(names); names.append([rem, sp])
        sk = (nidx[(rem, sp)], st)
        if sk not in sidx: sidx[sk] = len(streets); streets.append([nidx[(rem, sp)], st])
        P.append([round(la * 1e5) - la0, round(lo * 1e5) - lo0, sidx[sk], hn, code, [int(x) for x in poly.split(",")] if poly else 0, 1])
    k = f"{cy}_{cx}"; keys.append(k)
    json.dump({"o": [la0, lo0], "n": names, "s": streets, "p": P}, open(f"{out}/{k}.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
json.dump(keys, open(f"{out}/index.json", "w"), separators=(",", ":"))

# індекс координат для пошуку за адресою: data/geo/<n>.json = {нас. пункт: {вулиця: {будинок або "": [lat, lon]}}}
geo = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
for pts in cells.values():
    for la, lo, rem, sp, st, hn, codes in pts:
        d = geo[rem][sp][st]; k = house_key(hn) if hn else ""
        if k not in d or (hn and polyof.get((la, lo, hn))): d[k] = [round(la, 5), round(lo, 5)]
os.makedirs(f"{D}/geo", exist_ok=True)
for rem, info in index.items():
    n = info["file"].split("/")[-1]
    json.dump(geo.get(rem, {}), open(f"{D}/geo/{n}", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
json.dump(plist, open(f"{out}/places.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

tot_streets = sum(len(m) for m in zt.values())
print(f"вулиць у базі: {tot_streets}; знайдено на карті: {len(street_hit)} ({100 * len(street_hit) / tot_streets:.1f}%)")
print(f"населених пунктів у базі: {len(zt)}; знайдено на карті: {len(pl_hit)} ({100 * len(pl_hit) / len(zt):.1f}%)")
one = sum(1 for p in plist if "|" not in p[5]); print("населених пунктів з однією підчергою:", one)
# частка будинків бази, досяжних дотиком (будинок, вулиця або нас. пункт)
reach = 0
for (rem, sp), m in zt.items():
    for k, hs in m.items():
        if (rem, sp, k) in street_hit or (rem, sp) in pl_hit: reach += len(hs)
        else: reach += sum(1 for h in hs if (rem, sp, k, h) in matched_houses)
print(f"будинків, досяжних з карти (будь-який рівень): {reach} ({100 * reach / total_houses:.1f}%)")
print(dict(stats))
print(f"будинків у базі ztoe: {total_houses}; з координатами: {len(matched_houses)} ({100 * len(matched_houses) / total_houses:.1f}%)")
print("плиток:", len(keys), "найбільша:", max(len(v) for v in cells.values()) if cells else 0)
# покриття по населених пунктах (для звіту)
per = Counter(); tot = Counter()
for (rem, sp), m in zt.items():
    tot[(rem, sp)] = sum(len(h) for h in m.values())
for rem, sp, k, hk in matched_houses: per[(rem, sp)] += 1
with open(f"{D}/coverage.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["РЕМ", "Населений пункт", "Будинків у базі", "З координатами", "%"])
    for k, t in sorted(tot.items(), key=lambda x: -x[1]):
        w.writerow([k[0], k[1], t, per[k], round(100 * per[k] / t, 1) if t else 0])

print("будинків з контуром:", stats["with_outline"])
