#!/usr/bin/env python3
"""Одноразово забирає з OpenStreetMap (Overpass API) адресні точки та населені пункти
Житомирської області і зберігає компактні TSV: data/osm/addr.tsv.gz, data/osm/places.tsv.gz.
Дані © учасники OpenStreetMap, ліцензія ODbL."""
import gzip, json, sys, time, urllib.parse, urllib.request

MIRRORS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.private.coffee/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter"]
AREA = 'area["ISO3166-2"="UA-18"]->.a;'
Q_PLACE = f'[out:json][timeout:170];{AREA}node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|allotments)$"](area.a);out tags qt;'

def q_addr(s, w, n, e):
    return f'[out:json][timeout:170];{AREA}nwr["addr:housenumber"](area.a)({s},{w},{n},{e});out tags center qt;'

def run(q):
    last = None
    for attempt in range(4):
        for url in MIRRORS:
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": "svitlo-zt (github.com/primusua-ux/svitlo-zt)"})
                with urllib.request.urlopen(req, timeout=200) as r:
                    d = json.load(r)
                if "remark" in d and "error" in d["remark"].lower():
                    raise RuntimeError(d["remark"])
                return d["elements"]
            except Exception as e:
                last = e; print("помилка", url, e, flush=True); time.sleep(15)
    raise last

def addr_elements():
    """Область частинами по 0.5 градуса, щоб кожен запит був коротким."""
    seen = set()
    lat = 49.5
    while lat < 51.8:
        lon = 27.0
        while lon < 30.0:
            els = run(q_addr(lat, lon, lat + 0.5, lon + 0.5))
            print(f"частина {lat:.1f},{lon:.1f}: {len(els)}", flush=True)
            for e in els:
                k = (e["type"], e["id"])
                if k not in seen:
                    seen.add(k); yield e
            time.sleep(2); lon += 0.5
        lat += 0.5

def clean(s):
    return (s or "").replace("\t", " ").replace("\n", " ").strip()

def main(out):
    n = 0
    with gzip.open(f"{out}/addr.tsv.gz", "wt", encoding="utf-8") as f:
        for e in addr_elements():
            lat = e.get("lat") or e.get("center", {}).get("lat"); lon = e.get("lon") or e.get("center", {}).get("lon")
            t = e.get("tags", {})
            if lat is None: continue
            f.write("\t".join([f"{lat:.6f}", f"{lon:.6f}", clean(t.get("addr:housenumber")),
                               clean(t.get("addr:street")), clean(t.get("addr:place")),
                               clean(t.get("addr:city")), clean(t.get("addr:suburb"))]) + "\n"); n += 1
    print("адресних точок:", n)
    els = run(Q_PLACE)
    with gzip.open(f"{out}/places.tsv.gz", "wt", encoding="utf-8") as f:
        for e in els:
            t = e.get("tags", {})
            f.write("\t".join([f"{e['lat']:.6f}", f"{e['lon']:.6f}", clean(t.get("place")),
                               clean(t.get("name:uk") or t.get("name")), clean(t.get("old_name:uk") or t.get("old_name"))]) + "\n")
    print("населених пунктів:", len(els))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/osm")
