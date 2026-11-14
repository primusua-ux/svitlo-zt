#!/usr/bin/env python3
"""Зіставляє адресні точки OpenStreetMap з базою ztoe і пише плитки data/pts/<lat10>_<lon10>.json.
Запуск: python3 scripts/build_points.py data
Лише стандартна бібліотека."""
import csv, gzip, json, math, os, re, sys
from collections import defaultdict, Counter

D = sys.argv[1] if len(sys.argv) > 1 else "data"

# ---------- нормалізація ----------
LAT2CYR = str.maketrans("ABCEHIKMOPTXaceiopxy", "АВСЕНІКМОРТХасеіорху")
TYPES = [
    ("prov", r"провулок|пров|пер|переулок|пр-к|прк"),
    ("prosp", r"проспект|просп|пр-т|пр"),
    ("pl", r"площа|пл|майдан|м-н"),
    ("blv", r"бульвар|б-р|бул"),
    ("shose", r"шосе"),
    ("proizd", r"проїзд|пр-д"),
    ("uzviz", r"узвіз"),
    ("tupyk", r"тупик|туп"),
    ("nab", r"набережна|наб"),
    ("vul", r"вулиця|вул|ул|улица|в"),
]
TYPE_RE = [(t, re.compile(r"(?<![\w-])(?:%s)\.?(?![\w-])" % p, re.I)) for t, p in TYPES]

def street_key(s):
    """-> (тип, нормалізована назва з відсортованими словами)"""
    s = s.translate(LAT2CYR).lower().replace("ё", "е")
    s = re.sub(r"[ʼ'’`\"«»]", "", s)
    typ = "vul"
    for t, rx in TYPE_RE:
        if rx.search(s):
            typ = t; s = rx.sub(" ", s); break
    s = re.sub(r"(\d+)\s*-?\s*(?:й|ий|ій|я|а|го|ша|га|тя|та|ти)(?![а-яіїєґ])", r"\1", s)
    s = re.sub(r"[.,;()№]", " ", s)
    toks = [t for t in s.replace("-", " ").split() if t]
    return typ, " ".join(sorted(toks))

def house_key(h):
    h = h.translate(LAT2CYR).upper()
    h = re.sub(r"[\s]", "", h)
    h = re.sub(r"^(\d+)-([А-ЯІЇЄҐ])$", r"\1\2", h)
    h = re.sub(r"(?:КОРП(?:УС)?\.?|К\.)(\d+)", r"/\1", h)
    return h

def place_key(s):
    s = re.sub(r"^(місто|м\.|село|с\.|селище|смт\.?|с/рада|хутір)\s*", "", s.strip(), flags=re.I)
    s = s.lower().replace("ё", "е")
    return re.sub(r"[ʼ'’`\"\s-]", "", s)

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

def near_places(la, lo, n=6, rmax=12):
    out = []
    for dy in (-1, 0, 1, 2, -2):
        for dx in (-2, -1, 0, 1, 2):
            for p in pgrid.get((int(la * 10) + dy, int(lo * 10) + dx), ()):
                d = dist(la, lo, p[0], p[1])
                lim = rmax if p[2] in ("city", "town") else 6
                if d <= lim: out.append((d, p))
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

def candidates(la, lo, city):
    """Кандидати (rem, sp) для точки, від найімовірнішого."""
    names = []
    if city: names.append(place_key(city))
    for d, p in near_places(la, lo):
        if p[2] in ("suburb", "neighbourhood", "allotments"): continue
        for nm in (p[3], p[4]):
            k = place_key(nm) if nm else ""
            if k and k not in names: names.append(k)
    rr = None; out = []
    for k in names:
        c = by_place.get(k, [])
        if len(c) > 1:
            rr = rr or rem_rank(la, lo)
            c = sorted(c, key=lambda x: rr.get(x[0], 1e9))
            c = [x for x in c if rr.get(x[0], 1e9) < 60][:2]
        out.extend(x for x in c if x not in out)
    return out

stats = Counter(); cells = defaultdict(list); matched_houses = set(); seen = set()
for ln in gzip.open(f"{D}/osm/addr.tsv.gz", "rt", encoding="utf-8"):
    la, lo, hn, st, pl, city, sub = ln.rstrip("\n").split("\t")
    la = float(la); lo = float(lo); stats["osm"] += 1
    st = st or pl
    if not st or not hn: stats["no_street"] += 1; continue
    sk = street_key(st); hk = house_key(hn); hit = None
    cands = candidates(la, lo, city)
    if not cands: stats["no_place"] += 1; continue
    for rem, sp in cands:
        m = zt[(rem, sp)]
        if sk in m and hk in m[sk]: hit = (rem, sp, sk, m[sk][hk]); break
        # та сама назва з іншим типом (вул./пров.), якщо однозначно
        alts = [k for k in m if k[1] == sk[1] and hk in m[k]]
        if len(alts) == 1: hit = (rem, sp, alts[0], m[alts[0]][hk]); break
    if not hit:
        rem, sp = cands[0]; m = zt[(rem, sp)]
        stats["street_ok_house_missing" if (sk in m) else "street_missing"] += 1
        continue
    rem, sp, k, codes = hit
    key = (rem, sp, k, hk, round(la, 4), round(lo, 4))
    if key in seen: continue
    seen.add(key); matched_houses.add((rem, sp, k, hk)); stats["matched"] += 1
    cells[(math.floor(la * 10), math.floor(lo * 10))].append((la, lo, sp, disp[(rem, sp, k)], hn.strip(), "|".join(codes)))

# ---------- запис плиток ----------
out = f"{D}/pts"; os.makedirs(out, exist_ok=True)
for f in os.listdir(out): os.remove(f"{out}/{f}")
keys = []
for (cy, cx), pts in sorted(cells.items()):
    la0, lo0 = cy * 10000, cx * 10000
    names, nidx, streets, sidx, P = [], {}, [], {}, []
    for la, lo, sp, st, hn, codes in sorted(pts):
        if sp not in nidx: nidx[sp] = len(names); names.append(sp)
        sk = (nidx[sp], st)
        if sk not in sidx: sidx[sk] = len(streets); streets.append([nidx[sp], st])
        P.append([round(la * 1e5) - la0, round(lo * 1e5) - lo0, sidx[sk], hn, codes])
    k = f"{cy}_{cx}"; keys.append(k)
    json.dump({"o": [la0, lo0], "n": names, "s": streets, "p": P}, open(f"{out}/{k}.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
json.dump(keys, open(f"{out}/index.json", "w"), separators=(",", ":"))

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
