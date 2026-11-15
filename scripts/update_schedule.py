#!/usr/bin/env python3
"""Забирає графік погодинних відключень з ztoe.com.ua і пише data/schedule.json,
потім оновлює діючі відключення (з координатами для переліку аварій) і публікує все у гілку live.
Лише стандартна бібліотека Python."""
import html, json, re, sys, urllib.request
from datetime import datetime, timezone

URL = "https://www.ztoe.com.ua/unhooking-search.php"
OUT = sys.argv[1] if len(sys.argv) > 1 else "data/schedule.json"

def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (svitlo-zt schedule mirror)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("cp1251", errors="replace").replace("\r", "")

def parse_grid(t):
    grid = {}
    for m in re.finditer(r'<b style="font-size:12pt;color:black;">(\d\.\d)</b>(?:</a>)?</td>(.*?)</tr>', t, re.S):
        cols = re.findall(r'background:\s*(#[0-9a-fA-F]{6}|white)', m.group(2))
        if len(cols) != 48:
            raise ValueError(f"підчерга {m.group(1)}: {len(cols)} клітинок замість 48")
        # червоний (#ff3333 та подібні) = відключення; білий = світло є
        grid[m.group(1)] = "".join("0" if c.lower() in ("#ffffff", "white") else "1" for c in cols)
    if len(grid) != 12:
        raise ValueError(f"знайдено {len(grid)} підчерг замість 12")
    return grid

def parse(t):
    # На сторінці може бути кілька таблиць: на сьогодні і (звечора) на завтра. Кожна починається з рядка з датою.
    heads = list(re.finditer(r'colspan="48"><b[^>]*>(\d{2})\.(\d{2})\.(\d{4})</b>', t))
    if not heads:
        raise ValueError("не знайдено дату графіка")
    days = {}
    for i, h in enumerate(heads):
        part = t[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(t)]
        try: days[f"{h.group(3)}-{h.group(2)}-{h.group(1)}"] = parse_grid(part)
        except ValueError as e: print("таблиця", h.group(0)[-18:-4], "пропущена:", e)
    if not days:
        raise ValueError("жодної повної таблиці графіка")
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d")
    first = today if today in days else min(days)
    upd = re.search(r'оновлення інформації\s*-\s*(\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{4})', t)
    h = re.search(r'<h3>(.*?)Пошук черги', t, re.S)
    notice = ""
    if h:
        notice = re.sub(r'<br\s*/?>', '\n', h.group(1))
        notice = html.unescape(re.sub(r'<[^>]+>', '', notice))
        notice = "\n".join(x.strip() for x in notice.split("\n") if x.strip())
    return {
        "date": first,
        "source_updated": f"{upd.group(2)} {upd.group(1)}" if upd else "",
        "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notice": notice,
        "grid": days[first],   # 48 символів на підчергу, крок 30 хв з 00:00; 1 = відключення
        "days": days,          # усі опубліковані дні, зокрема завтра
    }

if __name__ == "__main__":
    import os, subprocess
    try:
        data = parse(fetch()); changed = True
        try:
            old = json.load(open(OUT, encoding="utf-8"))
            changed = not all(old.get(k) == data[k] for k in ("date", "source_updated", "notice", "grid", "days"))
        except (OSError, ValueError):
            pass
        if changed:
            json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("графік оновлено:", data["date"], data["source_updated"])
        else:
            print("графік без змін")
    except Exception as e:
        print("графік: помилка", e)
    # діючі відключення + публікація у гілку live (лише в GitHub Actions)
    if os.environ.get("GITHUB_ACTIONS"):
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "publish_live.py")])
