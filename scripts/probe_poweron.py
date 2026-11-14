#!/usr/bin/env python3
"""Розвідка API PowerOn: зведення типів записів. Тимчасовий скрипт."""
import json, os, re, urllib.request
from collections import Counter, defaultdict
B = "https://api-ztoe-poweron.inneti.net/api"
def get(path):
    req = urllib.request.Request(B + path, headers={"Accept": "application/ld+json", "User-Agent": "Mozilla/5.0 (svitlo-zt research)"})
    with urllib.request.urlopen(req, timeout=90) as r: return json.load(r)
rows = []; page = 1; per = None
while True:
    d = get(f"/pw_accidents?itemsPerPage=1000&page={page}")
    m = d["hydra:member"]; per = per or len(m); rows += m
    if not m or len(rows) >= d["hydra:totalItems"] or page > 400: break
    page += 1
tally = Counter(); ex = defaultdict(list); keys = Counter()
for r in rows:
    k = r.get("koment") or ""
    kk = "черга" if re.fullmatch(r"\d\.\d", k.strip()) else ("порожньо" if not k.strip() else "текст")
    key = f"typeOff={r.get('typeOff')} subReason={r.get('switchSubReason')} koment={kk}"
    tally[key] += 1
    for f in r: keys[f] += 1
    if len(ex[key]) < 4:
        ex[key].append({"city": (r.get("city") or {}).get("name"), "street": (r.get("street") or {}).get("name"), "b": (r.get("buildingNames") or "")[:80],
                        "from": r.get("dateEvent"), "to": r.get("datePlanIn"), "koment": k[:120], "otg": (r.get("otg") or {}).get("name")})
out = {"total": len(rows), "per_page_returned": per, "pages": page, "fields": keys, "tally": tally.most_common(), "examples": ex,
       "zhytomyr_rows": sum(1 for r in rows if (r.get("city") or {}).get("name") == "Житомир"),
       "options": [(o.get("optionKey"), o.get("date"), o.get("value")) for o in get("/options")["hydra:member"]]}
os.makedirs("data/probe", exist_ok=True)
json.dump(out, open("data/probe/tally.json", "w"), ensure_ascii=False, indent=1)
