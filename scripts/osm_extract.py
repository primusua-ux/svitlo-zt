#!/usr/bin/env python3
"""GeoJSONSeq (результат osmium export) -> data/osm/addr.tsv.gz, places.tsv.gz, streets.tsv.gz.
Дані © учасники OpenStreetMap, ліцензія ODbL."""
import gzip, json, os, sys
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
PLACES = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "allotments"}

def clean(s):
    return (s or "").replace("\t", " ").replace("\n", " ").strip()

def center(g):
    t, c = g["type"], g["coordinates"]
    if t == "Point": return c[1], c[0]
    if t == "LineString": pts = c
    elif t == "Polygon": pts = c[0]
    elif t == "MultiPolygon": pts = c[0][0]
    elif t == "MultiLineString": pts = c[0]
    else: return None
    if t == "LineString": p = pts[len(pts) // 2]; return p[1], p[0]
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)

na = np_ = ns = 0
with gzip.open(f"{out}/addr.tsv.gz", "wt", encoding="utf-8") as fa, \
     gzip.open(f"{out}/places.tsv.gz", "wt", encoding="utf-8") as fp, \
     gzip.open(f"{out}/streets.tsv.gz", "wt", encoding="utf-8") as fs:
    for ln in open(src, encoding="utf-8"):
        ln = ln.strip().lstrip("\x1e")
        if not ln: continue
        f = json.loads(ln); t = f.get("properties", {}); c = center(f["geometry"])
        if not c: continue
        lat, lon = c
        if t.get("addr:housenumber"):
            fa.write("\t".join([f"{lat:.6f}", f"{lon:.6f}", clean(t.get("addr:housenumber")), clean(t.get("addr:street")),
                                clean(t.get("addr:place")), clean(t.get("addr:city")), clean(t.get("addr:suburb"))]) + "\n"); na += 1
        if f["geometry"]["type"] == "Point" and t.get("place") in PLACES and (t.get("name:uk") or t.get("name")):
            fp.write("\t".join([f"{lat:.6f}", f"{lon:.6f}", t["place"], clean(t.get("name:uk") or t.get("name")),
                                clean(t.get("old_name:uk") or t.get("old_name"))]) + "\n"); np_ += 1
        if f["geometry"]["type"] == "LineString" and t.get("highway") and (t.get("name:uk") or t.get("name")):
            fs.write("\t".join([f"{lat:.6f}", f"{lon:.6f}", clean(t.get("name:uk") or t.get("name")),
                                clean(t.get("old_name:uk") or t.get("old_name"))]) + "\n"); ns += 1
print("адрес:", na, "населених пунктів:", np_, "відрізків вулиць:", ns)
