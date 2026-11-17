#!/usr/bin/env python3
"""Статистика для сторінки stats.html: графік, фактичний стан підчерг, аварії й планові роботи,
база адрес і покриття карти в одному компактному stats.json.

Запускається з publish_live.py не частіше ніж раз на годину; результат лежить у гілці live поруч з outages.json.
Запуск вручну: python3 scripts/build_stats.py data LIVE_DIR OUT_FILE
  data      статичні дані репозиторію (index.json, rem/, coverage.csv)
  LIVE_DIR  тека з schedule.json, outages.json, history.json; якщо файлу там немає, він береться з гілки live
  OUT_FILE  куди записати stats.json
Формат описано в кінці файлу (out = {...}).
"""
import csv, json, os, sys, time, urllib.request
from collections import defaultdict
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from norm import house_key

D, LIVE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
RAW = "https://raw.githubusercontent.com/primusua-ux/svitlo-zt/live/"
KYIV = ZoneInfo("Europe/Kyiv")
QUEUES = [f"{a}.{b}" for a in range(1, 7) for b in (1, 2)]

def live(name):
    p = os.path.join(LIVE, name)
    if os.path.exists(p): return json.load(open(p, encoding="utf-8"))
    with urllib.request.urlopen(RAW + name, timeout=60) as r: return json.loads(r.read())

sched, outs, hist = live("schedule.json"), live("outages.json"), live("history.json")
NOW = outs.get("updated") or int(time.time())          # момент знімка аварій
today = sched.get("date") or datetime.fromtimestamp(NOW, KYIV).strftime("%Y-%m-%d")
days = sched.get("days") or {today: sched.get("grid") or {}}
tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()

# ---------- база адрес: підчерги кожного будинку і зведення по населених пунктах ----------
index = json.load(open(f"{D}/index.json", encoding="utf-8"))
REMS = sorted(index)
ri = {r: i for i, r in enumerate(REMS)}
street_q = {}                     # (rem, sp, st) -> {house_key: {queue}}
addr = defaultdict(lambda: defaultdict(int))   # (rem, sp) -> {"3.2": n, "3.2ю": n, "0": n}
for rem, info in index.items():
    for sp, streets in json.load(open(f"{D}/{info['file']}", encoding="utf-8")).items():
        for st, codes in streets.items():
            hs = street_q.setdefault((rem, sp, st), {})
            for code, lst in codes.items():
                q = code.rstrip("ю")
                for h in lst.split(","):
                    if not h.strip(): continue
                    addr[(rem, sp)][code] += 1
                    hs.setdefault(house_key(h), set()).add(q)

# ---------- аварії та планові роботи (той самий набір, що в переліку «Де аварії») ----------
CAUSES, ci = [], {}
def cause(s):
    s = (s or "").strip() or "не вказано"
    if s not in ci: ci[s] = len(CAUSES); CAUSES.append(s)
    return ci[s]
ev = []
def add(kind, rem, sp, st, t0, t1, note, hs, matched):
    if not (kind == 0 or (t1 and t1 > NOW - 3600)): return          # як accItems() на сайті
    houses = [h for h in (hs or "").split(",") if h.strip()]
    qs = set()
    if matched:
        m = street_q.get((rem, sp, st)) or {}
        for h in houses: qs |= m.get(house_key(h), set())
        if not houses:
            for v in m.values(): qs |= v
    if rem not in ri: ri[rem] = len(REMS); REMS.append(rem)
    ev.append([kind, ri[rem], sp, st, t0 or 0, t1 or 0, cause(note), len(houses), matched,
               ",".join(sorted(qs))])
for k, lst in (outs.get("acc") or {}).items():
    rem, sp, st = k.split("|")
    for e in lst: add(e[0], rem, sp, st, e[1], e[2], e[3], e[4], 1)
for e in outs.get("raw") or []:
    add(e[0], e[5], e[6], e[7], e[1], e[2], e[3], e[4], 0)

# ---------- покриття карти ----------
cov = []
with open(f"{D}/coverage.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        if r["РЕМ"] not in ri: ri[r["РЕМ"]] = len(REMS); REMS.append(r["РЕМ"])
        cov.append([ri[r["РЕМ"]], r["Населений пункт"], int(r["Будинків у базі"]), int(r["З координатами"])])

# ---------- години без світла по днях ----------
hd = dict((hist or {}).get("days") or {})
for d, grid in days.items(): hd[d] = {q: (grid.get(q) or "").count("1") for q in QUEUES}

gav = outs.get("gav") or {}
out = {
    "v": 1,
    "generated": int(time.time()),                    # коли зібрано
    "at": NOW,                                         # момент знімка аварій і фактичного стану
    "date": today,                                     # день графіка
    "source_updated": sched.get("source_updated"),     # коли обленерго оновило графік
    "tomorrow": tomorrow in days,
    "gav": {"active": bool(gav.get("active")), "url": gav.get("url")},
    "notice": (sched.get("notice") or "").strip(),
    "addresses_updated": open(f"{D}/addresses_updated.txt").read().strip() if os.path.exists(f"{D}/addresses_updated.txt") else None,
    "grid": days,                                      # день -> підчерга -> 48 символів, 1 = вимкнено
    "hours": {d: hd[d] for d in sorted(hd)},           # день -> підчерга -> пів годин без світла
    "live": outs.get("live") or {},                    # підчерга -> частка вимкнених будинків за PowerOn
    "rems": REMS,
    "causes": CAUSES,
    # [тип 0 аварія / 1 планові, РЕМ (індекс), нас. пункт, вулиця, початок, кінець (unix), причина (індекс),
    #  кількість будинків у записі, зіставлено з базою 1/0, підчерги будинків через кому ("0" не вимикаються за графіком)]
    "ev": ev,
    # [РЕМ (індекс), нас. пункт, {код: будинків}], код "3.2" житлові, "3.2ю" нежитлові, "0"/"0ю" не вимикаються
    "addr": [[ri[r], sp, dict(sorted(c.items()))] for (r, sp), c in sorted(addr.items())],
    # [РЕМ (індекс), нас. пункт, будинків у базі, з координатами]
    "cov": cov,
}
os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(f"stats: {len(ev)} записів, {len(out['addr'])} нас. пунктів, {os.path.getsize(OUT) // 1024} КБ")
