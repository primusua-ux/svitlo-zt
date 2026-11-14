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
    ("prosp", r"проспект|просп|пр-т"),
    ("pl", r"площа|пл|майдан|м-н"),
    ("blv", r"бульвар|б-р|бул|б"),
    ("shose", r"шосе"),
    ("proizd", r"проїзд|пр-д"),
    ("uzviz", r"узвіз"),
    ("tupyk", r"тупик|туп"),
    ("nab", r"набережна|наб"),
    ("vul", r"вулиця|вул|ул|улица"),
]
TYPE_RE = [(t, re.compile(r"(?<![\w-])(?:%s)(?:\.|(?![\w-]))" % p, re.I)) for t, p in TYPES]

def street_key(s):
    """-> (тип, нормалізована назва з відсортованими словами)"""
    s = s.translate(LAT2CYR).lower().replace("ё", "е")
    s = re.sub(r"[ʼ'’`\"«»]", "", s)
    s = re.sub(r"(\d+)\s*-?\s*(?:й|ий|ій|я|а|го|ша|га|тя|та|ти)(?![а-яіїєґ])", r"\1 ", s)
    typ = None
    for t, rx in TYPE_RE:
        if rx.search(s):
            s = rx.sub(" ", s)
            if typ is None or typ == "vul": typ = t
    s = re.sub(r"[.,;()№]", " ", s)
    toks = [t for t in s.replace("-", " ").split() if len(t) > 1 or t.isdigit()]
    return typ or "vul", " ".join(sorted(toks))

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

def find_street(m, sk, la, lo):
    """Ключ вулиці в базі населеного пункту m для OSM-ключа sk (з урахуванням типу і перейменувань)."""
    if sk in m: return sk
    alts = [k for k in m if k[1] == sk[1]]
    if len(alts) == 1: return alts[0]
    for ak in alias[(int(la * 10), int(lo * 10))].get(sk, ()):
        if ak in m: return ak
        alts = [k for k in m if k[1] == ak[1]]
        if len(alts) == 1: return alts[0]
    return None

stats = Counter(); house_rows = []; cells = defaultdict(list); matched_houses = set(); seen = set(); street_hit = set()
for ln in gzip.open(f"{D}/osm/addr.tsv.gz", "rt", encoding="utf-8"):
    la, lo, hn, st, pl, city, sub = ln.rstrip("\n").split("\t")
    la = float(la); lo = float(lo); stats["osm"] += 1
    st = st or pl
    if not st or not hn: stats["no_street"] += 1; continue
    sk = street_key(st); hk = house_key(hn); hit = None
    cands = candidates(la, lo, city)
    if not cands: stats["no_place"] += 1; continue
    st_found = False
    for rem, sp in cands:
        m = zt[(rem, sp)]; k = find_street(m, sk, la, lo)
        if k is None: continue
        st_found = True
        if hk in m[k]: hit = (rem, sp, k, m[k][hk]); break
    if not hit:
        stats["street_ok_house_missing" if st_found else "street_missing"] += 1; continue
    rem, sp, k, codes = hit
    key = (rem, sp, k, hk, round(la, 4), round(lo, 4))
    if key in seen: continue
    seen.add(key); matched_houses.add((rem, sp, k, hk)); stats["matched"] += 1
    house_rows.append((la, lo, rem, sp, k, hk, hn.strip(), "|".join(collapse(codes))))

# рівень вулиці: відрізки доріг з назвою
sseen = set()
for la, lo, name, old in street_rows:
    cands = candidates(la, lo)
    if not cands: continue
    for nm in [name] + [o for o in re.split(r"[;,]", old) if o.strip()]:
        sk = street_key(nm); done = False
        for rem, sp in cands[:3]:
            m = zt[(rem, sp)]; k = find_street(m, sk, la, lo)
            if k is None: continue
            key = (rem, sp, k, round(la, 3), round(lo * 0.65, 3))
            if key not in sseen:
                sseen.add(key); street_hit.add((rem, sp, k)); stats["street_pts"] += 1
                codes = collapse([c for cs in m[k].values() for c in cs])
                cells[(math.floor(la * 10), math.floor(lo * 10))].append((la, lo, rem, sp, disp[(rem, sp, k)], "", "|".join(codes)))
            done = True; break
        if done: break

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

# ---------- запис плиток ----------
out = f"{D}/pts"; os.makedirs(out, exist_ok=True)
for f in os.listdir(out): os.remove(f"{out}/{f}")
keys = []
for (cy, cx), pts in sorted(cells.items()):
    la0, lo0 = cy * 10000, cx * 10000
    names, nidx, streets, sidx, P = [], {}, [], {}, []
    for la, lo, rem, sp, st, hn, codes in sorted(pts):
        if (rem, sp) not in nidx: nidx[(rem, sp)] = len(names); names.append([rem, sp])
        sk = (nidx[(rem, sp)], st)
        if sk not in sidx: sidx[sk] = len(streets); streets.append([nidx[(rem, sp)], st])
        P.append([round(la * 1e5) - la0, round(lo * 1e5) - lo0, sidx[sk], hn, codes])
    k = f"{cy}_{cx}"; keys.append(k)
    json.dump({"o": [la0, lo0], "n": names, "s": streets, "p": P}, open(f"{out}/{k}.json", "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
json.dump(keys, open(f"{out}/index.json", "w"), separators=(",", ":"))
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
