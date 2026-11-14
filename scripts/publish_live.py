#!/usr/bin/env python3
"""Публікує часто змінювані дані (графік + діючі відключення) у гілку `live` одним комітом без історії,
щоб основна гілка не розросталась. Викликається з update_schedule.py."""
import os, shutil, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
out = os.path.join(root, ".live"); os.makedirs(out, exist_ok=True)
def git(*a, **kw): return subprocess.run(["git", "-C", root, *a], capture_output=True, text=True, **kw)

# попередня версія outages.json як запасна, якщо сервіс зараз недоступний
if git("fetch", "--depth=1", "origin", "live").returncode == 0:
    old = subprocess.run(["git", "-C", root, "show", "FETCH_HEAD:outages.json"], capture_output=True)
    if old.returncode == 0: open(os.path.join(out, "outages.json"), "wb").write(old.stdout)
shutil.copy(os.path.join(root, "data", "schedule.json"), os.path.join(out, "schedule.json"))
r = subprocess.run([sys.executable, os.path.join(here, "update_outages.py"), os.path.join(root, "data"), os.path.join(out, "outages.json.new")])
if r.returncode == 0: os.replace(os.path.join(out, "outages.json.new"), os.path.join(out, "outages.json"))
else: print("update_outages: помилка, лишаю попередні дані")

entries = []
for name in sorted(os.listdir(out)):
    if name.endswith(".new"): continue
    sha = git("hash-object", "-w", os.path.join(out, name)).stdout.strip()
    entries.append(f"100644 blob {sha}\t{name}")
tree = git("mktree", input="\n".join(entries) + "\n").stdout.strip()
env = dict(os.environ, GIT_AUTHOR_NAME="live-bot", GIT_AUTHOR_EMAIL="live-bot@users.noreply.github.com",
           GIT_COMMITTER_NAME="live-bot", GIT_COMMITTER_EMAIL="live-bot@users.noreply.github.com")
commit = subprocess.run(["git", "-C", root, "commit-tree", tree, "-m", "live " + time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())],
                        capture_output=True, text=True, env=env).stdout.strip()
p = git("push", "-f", "origin", f"{commit}:refs/heads/live")
print("live:", commit[:8], "push", p.returncode, p.stderr.strip()[-200:])
shutil.rmtree(out, ignore_errors=True)
sys.exit(p.returncode)
