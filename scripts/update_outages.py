#!/usr/bin/env python3
"""Діючі та планові відключення з офіційного сервісу Житомиробленерго «Чому немає світла?» (PowerOn)
+ статус обласних аварійних відключень з офіційного Telegram-каналу. Пише компактний outages.json.
Запуск: python3 scripts/update_outages.py data out/outages.json"""
import html, json, re, sys, time, urllib.request
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from norm import street_key, house_key, place_key

D, OUT = sys.argv[1], sys.argv[2]
API = "https://api-ztoe-poweron.inneti.net/api/pw_accidents"
UA = {"Accept": "application/ld+json", "User-Agent": "Mozilla/5.0 (svitlo-zt; github.com/primusua-ux/svitlo-zt)"}

def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(2 + 3 * i)

KYIV = ZoneInfo("Europe/Kyiv")
def ts(s):
    """Час у сервісі позначений як +00:00, але насправді це київський місцевий час (звірено з графіком)."""
    try: return int(datetime.fromisoformat(s[:19]).replace(tzinfo=KYIV).timestamp())
    except Exception: return 0
def ts_utc(s):
    try: return int(datetime.fromisoformat(s).timestamp())
    except Exception: return 0

# ---------- наша база адрес ----------
index = json.load(open(f"{D}/index.json", encoding="utf-8"))
db = {}          # rem -> place_key -> (sp, {street_key: (st, {house_key: [codes]})})
qtotal = Counter()
for rem, info in index.items():
    d = json.load(open(f"{D}/{info['file']}", encoding="utf-8")); db[rem] = {}
    for sp, streets in d.items():
        m = {}
        for st, codes in streets.items():
            hs = defaultdict(list)
            for code, lst in codes.items():
                for h in lst.split(","):
                    hs[house_key(h)].append(code)
            m.setdefault(street_key(st), (st, {}))[1].update(hs)
        db[rem].setdefault(place_key(sp), (sp, {}))[1].update(m)
        for st, hs in m.values():
            for h, codes in hs.items():
                for q in {c.rstrip("ю") for c in codes}: qtotal[q] += 1

def find(rem, city, street):
    p = db.get(rem, {}).get(place_key(city))
    if not p: return None
    sp, m = p; sk = street_key(street)
    if sk in m: return sp, m[sk][0], m[sk][1]
    alts = [k for k in m if k[1] == sk[1]]
    if len(alts) == 1: return sp, m[alts[0]][0], m[alts[0]][1]
    return None

# ---------- PowerOn ----------
first = json.loads(get(API + "?page=1"))
total = first["hydra:totalItems"]; per = max(1, len(first["hydra:member"])); pages = (total + per - 1) // per
def page(n): return json.loads(get(f"{API}?page={n}"))["hydra:member"]
rows = list(first["hydra:member"])
with ThreadPoolExecutor(6) as ex:
    for part in ex.map(page, range(2, pages + 1)): rows += part

now = int(time.time()); stats = Counter(); acc = defaultdict(list); qoff = defaultdict(set); seen = set()
for r in rows:
    if r.get("id") in seen: continue
    seen.add(r.get("id"))
    rem = ((r.get("otg") or {}).get("name") or "").replace(" РЕМ", "").strip()
    city = (r.get("city") or {}).get("name") or ""; street = (r.get("street") or {}).get("name") or ""
    t0, t1 = ts(r.get("dateEvent") or ""), ts(r.get("datePlanIn") or "")
    kom = (r.get("koment") or "").strip()
    kind = "plan" if r.get("typeOff") == 0 else ("gpv" if r.get("switchSubReason") == 2 else "acc")
    stats[kind] += 1
    hit = find(rem, city, street)
    houses = [house_key(h) for h in (r.get("buildingNames") or "").split(",") if h.strip()]
    if not hit: stats[kind + "_unmatched"] += 1; continue
    sp, st, hs = hit
    if kind == "gpv":
        if t0 <= now and not (t1 and t1 < now - 600):      # лише ті, що тривають зараз
            for h in houses:
                for q in {c.rstrip("ю") for c in hs.get(h, ())}: qoff[q].add((rem, sp, st, h))
        continue
    if t1 and t1 < now - 6 * 3600 and kind == "plan": continue           # давно завершені планові
    acc[f"{rem}|{sp}|{st}"].append([0 if kind == "acc" else 1, t0, t1, kom[:80], ",".join(sorted(set(houses)))])

live = {q: round(len(qoff[q]) / qtotal[q], 3) for q in sorted(qtotal) if qtotal[q]}

# ---------- Telegram: обласні аварійні відключення (ГАВ / СпецГАВ) ----------
gav = {"active": False, "checked": False}
try:
    t = get("https://t.me/s/ztoe_ua").decode("utf-8", "replace")
    posts = re.findall(r'data-post="ztoe_ua/(\d+)".*?(?:tgme_widget_message_text[^>]*>(.*?)</div>).*?<time[^>]*datetime="([^"]+)"', t, re.S)
    last = None
    for pid, body, dt in posts:
        txt = re.sub(r"<[^>]+>", " ", html.unescape(body)); low = txt.lower()
        if not re.search(r"аварійн\w* відключен|\bгав\b|спецгав|екстрен\w* відключен|графіки\W+(?:погодинних відключень\W+)?(?:електроенергії\W+)?(?:наразі\W+)?не діють", low): continue
        off = bool(re.search(r"скасован|повертаємось до графік", low))
        on = bool(re.search(r"запроваджено|застосовано|застосовуються|вводяться|не діють|діють екстрен", low))
        if off or on: last = (int(pid), off, ts_utc(dt))
    gav["checked"] = bool(posts)
    if last:
        pid, off, when = last
        gav.update({"active": (not off) and now - when < 36 * 3600, "since": when, "url": f"https://t.me/ztoe_ua/{pid}"})
except Exception as e:
    gav["error"] = str(e)[:120]

out = {"updated": now, "total": len(seen), "acc": acc, "live": live, "gav": gav}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print(dict(stats)); print("вулиць з аваріями/ремонтами:", len(acc)); print("live:", live); print("gav:", gav)
