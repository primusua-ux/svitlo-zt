#!/usr/bin/env python3
"""Розвідка публічного API «Чому немає світла?» (PowerOn) Житомиробленерго. Тимчасовий скрипт."""
import json, os, urllib.request
B = "https://api-ztoe-poweron.inneti.net/api"
os.makedirs("data/probe", exist_ok=True)
def get(path, accept="application/ld+json"):
    req = urllib.request.Request(B + path, headers={"Accept": accept, "User-Agent": "Mozilla/5.0 (svitlo-zt research)",
                                                     "Origin": "https://ztoe-poweron.inneti.net", "Referer": "https://ztoe-poweron.inneti.net/"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, dict(r.headers), r.read()
    except Exception as e:
        body = getattr(e, "read", lambda: b"")()
        return getattr(e, "code", 0), {}, (str(e) + "\n").encode() + body[:2000]
out = {}
for name, path in [("entry", ""), ("docs", "/docs.jsonld"), ("accidents", "/pw_accidents?page=1&itemsPerPage=30"),
                   ("accidents_json", "/pw_accidents?page=1"), ("otgs", "/pw_otgs?page=1&itemsPerPage=30"),
                   ("cities", "/pw_cities?page=1&itemsPerPage=10"), ("streets", "/pw_streets?page=1&itemsPerPage=10"),
                   ("address_queues", "/pw_address_queues?page=1&itemsPerPage=5"), ("options", "/options"), ("gpv", "/a_gpv_g")]:
    st, hd, body = get(path)
    out[name] = {"status": st, "len": len(body), "headers": {k: v for k, v in hd.items() if k.lower() in ("content-type", "access-control-allow-origin", "cache-control")}}
    if name == "docs":
        try:
            d = json.loads(body)
            res = []
            for c in d.get("hydra:supportedClass", []):
                res.append({"title": c.get("hydra:title") or c.get("@id"),
                            "props": [p.get("hydra:title") for p in c.get("hydra:supportedProperty", [])]})
            body = json.dumps(res, ensure_ascii=False).encode()
        except Exception as e:
            body = body[:3000]
    open(f"data/probe/{name}.txt", "wb").write(body[:60000])
json.dump(out, open("data/probe/summary.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
