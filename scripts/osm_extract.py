#!/usr/bin/env python3
"""GeoJSONSeq (результат osmium export) -> data/osm/addr.tsv.gz, places.tsv.gz, streets.tsv.gz.
Для кожної адреси додається контур будівлі (якщо адреса стоїть на будівлі або точка лежить усередині неї).
Дані © учасники OpenStreetMap, ліцензія ODbL."""
import gzip, json, math, os, re, sys
from collections import defaultdict
src, out = sys.argv[1], sys.argv[2]
REL = sys.argv[3] if len(sys.argv) > 3 else None

# зв'язки «будинок -> вулиця» з відношень associatedStreet (OPL: r1 v1 ... T type=associatedStreet,name=... Mw1@house,n2@house)
def opl_unescape(v):
    return re.sub(r"%([0-9a-fA-F]+)%", lambda m: chr(int(m.group(1), 16)), v)
house_street = {}
if REL and os.path.exists(REL):
    for ln in open(REL, encoding="utf-8"):
        parts = ln.split(" "); tags = {}; mem = []
        for x in parts:
            if x.startswith("T"):
                for kv in x[1:].split(","):
                    if "=" in kv: k, v = kv.split("=", 1); tags[opl_unescape(k)] = opl_unescape(v)
            elif x.startswith("M"):
                mem = [m for m in x[1:].strip().split(",") if m]
        name = tags.get("name:uk") or tags.get("name")
        if not name: continue
        for m in mem:
            ref, _, role = m.partition("@")
            if role in ("house", "address", "") and ref[:1] in "nwr": house_street[ref] = name
    print("зв'язків будинок-вулиця з відношень:", len(house_street))
os.makedirs(out, exist_ok=True)
PLACES = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "allotments"}
G = 0.002  # крок сітки для пошуку будівлі за точкою

def clean(s):
    return (s or "").replace("\t", " ").replace("\n", " ").strip()

def outer(g):
    t, c = g["type"], g["coordinates"]
    if t == "Polygon": return c[0]
    if t == "MultiPolygon": return max((p[0] for p in c), key=len)
    return None

def center(g):
    t, c = g["type"], g["coordinates"]
    if t == "Point": return c[1], c[0]
    if t == "LineString": p = c[len(c) // 2]; return p[1], p[0]
    if t == "MultiLineString": p = c[0][len(c[0]) // 2]; return p[1], p[0]
    r = outer(g)
    if not r: return None
    r = r[:-1] if len(r) > 1 and r[0] == r[-1] else r
    return sum(p[1] for p in r) / len(r), sum(p[0] for p in r) / len(r)

def inside(lat, lon, ring):
    c = False; n = len(ring); j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]; xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi: c = not c
        j = i
    return c

def encode(ring, lat, lon):
    r = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if len(r) > 40: r = r[::(len(r) + 39) // 40]
    if len(r) < 3: return ""
    return ",".join(f"{round((p[1] - lat) * 1e6)},{round((p[0] - lon) * 1e6)}" for p in r)

# прохід 1: усі будівлі в сітку
grid = defaultdict(list); nb = 0; SG = 0.003; sgrid = defaultdict(list)
SKIP = {"garage", "garages", "shed", "roof", "hut", "kiosk", "service", "industrial", "warehouse", "barn", "greenhouse",
        "transformer_tower", "container", "carport", "ruins", "construction", "cowshed", "stable", "sty", "farm_auxiliary",
        "storage_tank", "toilets", "bunker", "church", "chapel", "school", "kindergarten", "hospital", "retail", "commercial", "office"}
for ln in open(src, encoding="utf-8"):
    ln = ln.strip().lstrip("\x1e")
    if not ln: continue
    if '"highway"' in ln and '"LineString"' in ln:
        f = json.loads(ln); t = f.get("properties", {}); nm = t.get("name:uk") or t.get("name")
        if f["geometry"]["type"] == "LineString" and nm and t.get("highway") not in ("footway", "path", "cycleway", "steps", "track"):
            c = f["geometry"]["coordinates"]
            for i in range(len(c) - 1):
                seg = (c[i][1], c[i][0], c[i + 1][1], c[i + 1][0], clean(nm))
                for gy in range(int(min(seg[0], seg[2]) / SG), int(max(seg[0], seg[2]) / SG) + 1):
                    for gx in range(int(min(seg[1], seg[3]) / SG), int(max(seg[1], seg[3]) / SG) + 1):
                        sgrid[(gy, gx)].append(seg)
        continue
    if '"building"' not in ln: continue
    f = json.loads(ln)
    if "building" not in f.get("properties", {}): continue
    r = outer(f["geometry"])
    if not r or len(r) < 4: continue
    xs = [p[0] for p in r]; ys = [p[1] for p in r]
    if max(xs) - min(xs) > 0.01 or max(ys) - min(ys) > 0.01: continue
    ring = tuple((p[0], p[1]) for p in r); nb += 1

    for gy in range(int(min(ys) / G), int(max(ys) / G) + 1):
        for gx in range(int(min(xs) / G), int(max(xs) / G) + 1):
            grid[(gy, gx)].append(ring)
print("будівель:", nb, flush=True)

def seg_dist(la, lo, s):
    k = math.cos(math.radians(la)) * 111320; m = 110540
    ax, ay = (s[1] - lo) * k, (s[0] - la) * m; bx, by = (s[3] - lo) * k, (s[2] - la) * m
    dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy)

def near_streets(la, lo, rmax=80):
    best = {}
    for gy in (int(la / SG) - 1, int(la / SG), int(la / SG) + 1):
        for gx in (int(lo / SG) - 1, int(lo / SG), int(lo / SG) + 1):
            for sg in sgrid.get((gy, gx), ()):
                d = seg_dist(la, lo, sg)
                if d < best.get(sg[4], 1e9): best[sg[4]] = d
    return [k for k, d in sorted(best.items(), key=lambda x: x[1]) if d <= rmax][:3]

na = np_ = ns = npoly = nnear = nrel = 0; used = set()
with gzip.open(f"{out}/addr.tsv.gz", "wt", encoding="utf-8") as fa, \
     gzip.open(f"{out}/places.tsv.gz", "wt", encoding="utf-8") as fp, \
     gzip.open(f"{out}/streets.tsv.gz", "wt", encoding="utf-8") as fs:
    for ln in open(src, encoding="utf-8"):
        ln = ln.strip().lstrip("\x1e")
        if not ln: continue
        f = json.loads(ln); t = f.get("properties", {}); g = f["geometry"]; c = center(g)
        if not c: continue
        lat, lon = c
        if t.get("addr:housenumber"):
            ring = outer(g) if "building" in t else None
            if ring is None and g["type"] == "Point":
                for r in grid.get((int(lat / G), int(lon / G)), ()):
                    if inside(lat, lon, r): ring = r; used.add(r); break
            poly = encode(ring, lat, lon) if ring else ""
            npoly += bool(poly)
            near = ""
            fid = str(f.get("id") or t.get("@id") or "")
            if not t.get("addr:street") and not t.get("addr:place") and fid in house_street:
                t["addr:street"] = house_street[fid]; nrel += 1
            if not t.get("addr:street") and not t.get("addr:place"):
                near = "|".join(near_streets(lat, lon)); nnear += bool(near)
            fa.write("\t".join([f"{lat:.6f}", f"{lon:.6f}", clean(t.get("addr:housenumber")), clean(t.get("addr:street")),
                                clean(t.get("addr:place")), clean(t.get("addr:city")), clean(t.get("addr:suburb")), poly, near]) + "\n"); na += 1
        if g["type"] == "Point" and t.get("place") in PLACES and (t.get("name:uk") or t.get("name")):
            fp.write("\t".join([f"{lat:.6f}", f"{lon:.6f}", t["place"], clean(t.get("name:uk") or t.get("name")),
                                clean(t.get("old_name:uk") or t.get("old_name"))]) + "\n"); np_ += 1
        if g["type"] == "LineString" and t.get("highway") and (t.get("name:uk") or t.get("name")):
            fs.write("\t".join([f"{lat:.6f}", f"{lon:.6f}", clean(t.get("name:uk") or t.get("name")),
                                clean(t.get("old_name:uk") or t.get("old_name"))]) + "\n"); ns += 1
print("адрес без вулиці: взято з відношень", nrel, "; найближчі вулиці для", nnear)
print("адрес:", na, "з контуром будівлі:", npoly, "населених пунктів:", np_, "відрізків вулиць:", ns)

