#!/usr/bin/env python3
"""Статистика всього, що зараз показує сайт: графік, фактичний стан черг, аварії й планові роботи,
база адрес і покриття карти. Пише набір JSON-файлів {rows, meta} для аналітичної панелі.

Поки ніде автоматично не запускається і сайтом не читається. Щоб підключити в майбутньому:
крок у schedule.yml після update_outages.py, а результат публікувати в гілку live поруч із outages.json.

Запуск: python3 scripts/build_stats.py data LIVE_DIR OUT_DIR
  data      статичні дані репозиторію (index.json, rem/, coverage.csv)
  LIVE_DIR  тека з schedule.json, outages.json, history.json; якщо її немає, файли беруться з гілки live
  OUT_DIR   куди писати *.json
"""
import csv, json, os, sys, time, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

D, LIVE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
RAW = "https://raw.githubusercontent.com/primusua-ux/svitlo-zt/live/"
KYIV = ZoneInfo("Europe/Kyiv")
QUEUES = [f"{a}.{b}" for a in range(1, 7) for b in (1, 2)]
CODE = open(os.path.abspath(__file__), encoding="utf-8").read()

def live(name):
    p = os.path.join(LIVE, name)
    if os.path.exists(p): return json.load(open(p, encoding="utf-8"))
    with urllib.request.urlopen(RAW + name, timeout=60) as r: return json.loads(r.read())

def kyiv(t): return datetime.fromtimestamp(t, KYIV).strftime("%Y-%m-%d %H:%M") if t else None

sched, outs, hist = live("schedule.json"), live("outages.json"), live("history.json")
NOW = outs.get("updated") or int(time.time())          # момент знімка аварій
now_k = datetime.fromtimestamp(NOW, KYIV)
today = sched.get("date") or now_k.strftime("%Y-%m-%d")
days = sched.get("days") or {today: sched.get("grid") or {}}
tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
generated = datetime.now(KYIV).strftime("%Y-%m-%d %H:%M")

def write(name, rows, inputs):
    meta = [{"label": "build_stats.py", "value": CODE, "type": "code", "lang": "python"},
            {"label": "Вхідні дані", "value": inputs},
            {"label": "Зібрано", "value": generated + " (Київ)"}]
    os.makedirs(OUT, exist_ok=True)
    json.dump({"rows": rows, "meta": meta}, open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"{name}: {len(rows)} рядків")

# ---------- знімок: коли оновлювалось і що діє ----------
gav = outs.get("gav") or {}
slot_now = (now_k.hour * 60 + now_k.minute) // 30 if now_k.strftime("%Y-%m-%d") == today else None
write("snapshot", [{
    "schedule_date": today,
    "schedule_source_updated": sched.get("source_updated"),
    "outages_updated": kyiv(NOW),
    "snapshot_slot": f"{slot_now // 2:02d}:{slot_now % 2 * 30:02d}" if slot_now is not None else None,
    "tomorrow_published": 1 if tomorrow in days else 0,
    "gav_active": 1 if gav.get("active") else 0,
    "notice": (sched.get("notice") or "").strip(),
    "addresses_updated": open(f"{D}/addresses_updated.txt").read().strip() if os.path.exists(f"{D}/addresses_updated.txt") else None,
}], "schedule.json, outages.json (гілка live), data/addresses_updated.txt")

# ---------- графік: 12 підчерг × 48 пів години на кожен опублікований день ----------
rows = []
for d, grid in sorted(days.items()):
    for q in QUEUES:
        s = grid.get(q) or ""
        for i in range(48):
            if i < len(s):
                rows.append({"day": d, "queue": q, "slot": i, "time": f"{i // 2:02d}:{i % 2 * 30:02d}", "off": int(s[i] == "1")})
write("grid", rows, "schedule.json → days (1 = вимкнено за графіком)")

# ---------- години без світла за графіком по днях ----------
rows = []
hd = dict((hist or {}).get("days") or {})
for d, grid in days.items():                       # опубліковані дні мають пріоритет над історією
    hd[d] = {q: (grid.get(q) or "").count("1") for q in QUEUES}
for d in sorted(hd):
    for q in QUEUES:
        if q in hd[d]: rows.append({"day": d, "queue": q, "hours_off": hd[d][q] / 2})
write("queue_hours", rows, "history.json (62 дні) + schedule.json → days")

# ---------- фактичний стан черг за PowerOn проти графіка ----------
LIVE_OFF, LIVE_ON = 0.6, 0.03                      # ті самі пороги, що й у index.html
rows = []
for q, v in sorted((outs.get("live") or {}).items()):
    g = (days.get(today) or {}).get(q) or ""
    sch = None if slot_now is None or slot_now >= len(g) else int(g[slot_now] == "1")
    verdict = "вимкнено" if v >= LIVE_OFF else "є світло" if v <= LIVE_ON else "невизначено"
    rows.append({"queue": q, "share_off": v, "scheduled_off": sch, "live_verdict": verdict,
                 "agrees": None if sch is None or verdict == "невизначено" else int((verdict == "вимкнено") == bool(sch))})
write("live_state", rows, "outages.json → live (частка вимкнених будинків підчерги за PowerOn)")

# ---------- аварії та планові роботи (як у переліку «Де аварії») ----------
rows = []
def ev(kind, rem, sp, st, t0, t1, note, hs, matched):
    if not (kind == 0 or (t1 and t1 > NOW - 3600)): return      # та сама умова, що й accItems() на сайті
    t0k = datetime.fromtimestamp(t0, KYIV) if t0 else None
    rows.append({
        "kind": "Аварія" if kind == 0 else "Планові роботи", "rem": rem, "settlement": sp, "street": st,
        "from": kyiv(t0), "to": kyiv(t1), "start_day": t0k.strftime("%Y-%m-%d") if t0k else None,
        "start_hour": t0k.hour if t0k else None,
        "duration_h": round((t1 - t0) / 3600, 1) if t0 and t1 and t1 >= t0 else None,
        "status": "триває" if t0 and t0 <= NOW and (not t1 or t1 >= NOW) else "заплановано" if t0 and t0 > NOW else "мало завершитись",
        "cause": (note or "").strip() or "не вказано",
        "houses": len([h for h in (hs or "").split(",") if h.strip()]),
        "matched": matched})
for k, lst in (outs.get("acc") or {}).items():
    rem, sp, st = k.split("|")
    for e in lst: ev(e[0], rem, sp, st, e[1], e[2], e[3], e[4], 1)
for e in outs.get("raw") or []:
    ev(e[0], e[5], e[6], e[7], e[1], e[2], e[3], e[4], 0)
write("events", rows, "outages.json → acc (зіставлені з базою) і raw (не зіставлені)")

# ---------- база адрес: будинки за РЕМ, підчергою і типом ----------
cnt = Counter()
for rem, info in json.load(open(f"{D}/index.json", encoding="utf-8")).items():
    for sp, streets in json.load(open(f"{D}/{info['file']}", encoding="utf-8")).items():
        for st, codes in streets.items():
            for code, hs in codes.items():
                n = len([h for h in hs.split(",") if h.strip()])
                cnt[(rem, code.rstrip("ю") if code.rstrip("ю") != "0" else "не вимикається", "нежитлові" if code.endswith("ю") else "житлові")] += n
write("addresses", [{"rem": r, "queue": q, "type": t, "houses": n} for (r, q, t), n in sorted(cnt.items())],
      "data/index.json, data/rem/*.json (база обленерго)")

# ---------- покриття карти: будинки бази з координатами OSM ----------
rows = []
with open(f"{D}/coverage.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        rows.append({"rem": r["РЕМ"], "settlement": r["Населений пункт"],
                     "houses": int(r["Будинків у базі"]), "with_coords": int(r["З координатами"])})
write("coverage", rows, "data/coverage.csv (результат build_points.py)")
