#!/usr/bin/env python3
"""CSV з базою ztoe -> компактні JSON по РЕМ: data/rem/<n>.json та data/index.json."""
import csv, json, re, sys, os
from collections import defaultdict
src, out = sys.argv[1], sys.argv[2]
os.makedirs(f"{out}/rem", exist_ok=True)

def settlement(s):
    s = re.sub(r"^(місто|м\.)\s*", "м. ", s, flags=re.I)
    s = re.sub(r"^(село|с\.)\s*", "с. ", s, flags=re.I)
    s = re.sub(r"^селище\s*", "селище ", s, flags=re.I)
    return s.strip()

def house(h):
    h = h.strip().upper().replace(" ", "")
    h = re.sub(r"^(\d+)-([А-ЯІЇЄҐA-Z])$", r"\1\2", h)
    return h if h not in (".", "-", "") else None

tree = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(set))))
for r in list(csv.reader(open(src, encoding="utf-8-sig")))[1:]:
    rem, sp, st, hs, q, pq, typ = r
    # "0" = адреса не вимикається за графіком (лише аварійні відключення)
    key = ("0" if q == "0" else f"{q}.{pq}") + ("" if typ.startswith("побутові") else "ю")
    rem, sp, st = (re.sub(r"\s+", " ", x).strip() for x in (rem, sp, st))
    for h in hs.split(","):
        h = house(h)
        if h: tree[rem][settlement(sp)][st.strip()][key].add(h)

def hsort(h):
    m = re.match(r"\d+", h); return (0, int(m.group()), h) if m else (1, 0, h)

index = {}
for n, rem in enumerate(sorted(tree), 1):
    data = {sp: {st: {k: ",".join(sorted(v, key=hsort)) for k, v in sorted(ks.items())}
                 for st, ks in sorted(sts.items())} for sp, sts in sorted(tree[rem].items())}
    json.dump(data, open(f"{out}/rem/{n}.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    index[rem] = {"file": f"rem/{n}.json", "settlements": sorted(data)}
json.dump(index, open(f"{out}/index.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
