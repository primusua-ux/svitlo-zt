#!/usr/bin/env python3
"""Одноразово забирає з OpenStreetMap (Overpass API) адресні точки та населені пункти
Житомирської області і зберігає компактні TSV: data/osm/addr.tsv.gz, data/osm/places.tsv.gz.
Дані © учасники OpenStreetMap, ліцензія ODbL."""
import gzip, json, sys, time, urllib.parse, urllib.request

MIRRORS = ["https://overpass-api.de/api/interpreter",
           "https://overpass.private.coffee/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter"]
AREA = 'area["ISO3166-2"="UA-18"]->.a;'
Q_ADDR = f'[out:json][timeout:900][maxsize:2000000000];{AREA}nwr["addr:housenumber"](area.a);out tags center qt;'
Q_PLACE = f'[out:json][timeout:300];{AREA}node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|allotments)$"](area.a);out tags qt;'

def run(q):
    last = None
    for attempt in range(3):
        for url in MIRRORS:
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                             headers={"User-Agent": "svitlo-zt (github.com/primusua-ux/svitlo-zt)"})
                with urllib.request.urlopen(req, timeout=1000) as r:
                    return json.load(r)["elements"]
            except Exception as e:
                last = e; print("помилка", url, e, file=sys.stderr); time.sleep(20)
    raise last

def clean(s):
    return (s or "").replace("\t", " ").replace("\n", " ").strip()

def main(out):
    els = run(Q_ADDR); n = 0
    with gzip.open(f"{out}/addr.tsv.gz", "wt", encoding="utf-8") as f:
        for e in els:
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
