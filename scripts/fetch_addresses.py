#!/usr/bin/env python3
"""Повна база адрес і черг з форми пошуку ztoe.com.ua (19 запитів, по одному на РЕМ, поле `all`).
Включає адреси, які не вимикаються за графіком (черга "0").
Запуск: python3 scripts/fetch_addresses.py data/ztoe_addresses.csv"""
import csv, html, re, sys, time, urllib.parse, urllib.request
OUT = sys.argv[1] if len(sys.argv) > 1 else "data/ztoe_addresses.csv"
URL = "https://www.ztoe.com.ua/unhooking-search.php"
def post(d):
    for i in range(4):
        try:
            req = urllib.request.Request(URL, data=urllib.parse.urlencode(d).encode(), headers={"User-Agent": "Mozilla/5.0 (svitlo-zt)"})
            return urllib.request.urlopen(req, timeout=180).read().decode("cp1251", "replace").replace("\r", "")
        except Exception as e:
            print("повтор", d, e, flush=True); time.sleep(10 * (i + 1))
    raise RuntimeError("не вдалося завантажити " + str(d))
ROW = re.compile(r'<tr><td align="center">(.*?)</td><td align="center">(.*?)</td><td align="center">(.*?)</td><td align="center">(.*?)</td><td align="center">(.*?)</td><td align="center">(.*?)</td><td align="center">(.*?)</td>\s*</tr>', re.S)
t = post({})
rems = [(v, html.unescape(n).strip()) for v, n in re.findall(r'<option value="(\d+)"[^>]*>([^<]*)', re.search(r'<select name="rem_id".*?</select>', t, re.S).group(0)) if v != "0"]
rows = []
for v, name in rems:
    t = post({"rem_id": v, "all": "1"}); n = 0
    for m in ROW.findall(t):
        r = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip() for x in m]
        if r[4] == "Черга" or not r[2]: continue
        if not r[4].isdigit():
            if "не вимикається" in r[4]: r[4], r[5] = "0", "0"
            else: continue
        rows.append(r); n += 1
    print(name, n, flush=True); time.sleep(1)
if len(rows) < 20000: raise SystemExit(f"підозріло мало рядків: {len(rows)}")
with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f); w.writerow(["РЕМ", "Населений пункт", "Вулиця", "Будинки", "Черга", "Підчерга", "Примітка"]); w.writerows(rows)
print("рядків:", len(rows))
