#!/usr/bin/env python3
"""Post-reform invariant check: names, list sets/order, Blocked label, card counts."""
import json, os, time, urllib.parse, urllib.request

API = "https://api.trello.com/1"
kv = {}
for ln in open(os.path.expanduser("~/.config/rya/trello.env")):
    ln = ln.strip()
    if ln and "=" in ln and not ln.startswith("#"):
        k, v = ln.split("=", 1); kv[k] = v
KEY, TOKEN = kv["TRELLO_KEY"], kv["TRELLO_TOKEN"]

def get(path, **p):
    p.update(key=KEY, token=TOKEN)
    for a in range(5):
        try:
            return json.load(urllib.request.urlopen(f"{API}{path}?{urllib.parse.urlencode(p)}", timeout=30))
        except Exception:
            time.sleep(1.5)
    raise RuntimeError(path)

STATUSES = ["01Created","02Script","03Shooting","04PreEditing","05Editing",
            "06Review","07Revisions","08Gate","09Ready","10Published","11Archived"]
EXPECT = {  # code → (board name, extra leading lists)
 "YTCR": ("YTCR — Core Realty Dubai", ["Tentatively agreed","Under review","Not booked yet"]),
 "YTCG": ("YTCG — Connect Group Dubai", []), "YTCGRU": ("YTCGRU — Connect Group RU", []),
 "YTRF": ("YTRF — Рефлюкс Контроль", []), "YTFP": ("YTFP — Фонд Правмир · Ассистент Здоровья", []),
 "YTUVI": ("YTUVI — Драгоценные камни", []), "YTMSEN": ("YTMSEN — Multiple Sclerosis EN", []),
 "YTMS": ("YTMS — Рассеянный склероз", []), "YTCIV": ("YTCIV — Цивилизация", []),
 "YTAGEFREE": ("YTAgeFree — Старость в радость", []), "YTCH": ("YTCH — burodd.ru", []),
 "YTAZ": ("YTAZ — Незабудки · Всё о деменции", []), "YTCN": ("YTCN — CosmicNootropic", []),
 "YTGOLD": ("YTGOLD — Инвестиции в золото", []), "YTLM": ("YTLM — Лейкемия", []),
 "YTUAE": ("YTUAE — Интервью UAE", []),
}
old = json.load(open("/tmp/trello_inventory.json"))
old_counts = {}
for name, d in old.items():
    code = name.upper()
    old_counts[code] = d["ncards"]

boards = get("/members/me/boards", filter="open", fields="name")
fails, ok = [], []
seen = set()
for b in boards:
    if b["name"] == "RomanSergeevCom":
        continue
    import re
    m = re.match(r"^(YT[A-Za-z]+)", b["name"])
    if not m:
        fails.append(f"UNEXPECTED open board: {b['name']}"); continue
    code = m.group(1).upper(); seen.add(code)
    exp_name, extra = EXPECT.get(code, (None, []))
    if exp_name is None:
        fails.append(f"{code}: unknown open board {b['name']}"); continue
    if b["name"] != exp_name:
        fails.append(f"{code}: name «{b['name']}» != «{exp_name}»")
    lists = sorted(get(f"/boards/{b['id']}/lists", filter="open", fields="name,pos"), key=lambda l: l["pos"])
    names = [l["name"] for l in lists]
    if names != extra + STATUSES:
        fails.append(f"{code}: lists {names}")
    labels = get(f"/boards/{b['id']}/labels", fields="name,color")
    if not any(l["color"] == "red" and l["name"] == "Blocked" for l in labels):
        fails.append(f"{code}: no red Blocked label")
    # card count: open cards on open lists
    open_ids = {l["id"] for l in lists}
    cards = get(f"/boards/{b['id']}/cards", filter="open", fields="idList")
    n = sum(1 for c in cards if c["idList"] in open_ids)
    if code in old_counts and n != old_counts[code]:
        fails.append(f"{code}: cards {n} != before {old_counts[code]}")
    ok.append(f"{code}: OK ({n} cards)")

missing = set(EXPECT) - seen
if missing: fails.append(f"boards missing/closed: {missing}")
# test boards closed?
allb = get("/members/me/boards", filter="all", fields="name,closed")
for nm in ("YT Demo", "YT Test"):
    st = [x for x in allb if x["name"] == nm]
    if st and not st[0]["closed"]:
        fails.append(f"{nm}: still open")

print("\n".join(ok))
print("\nFAILS:" if fails else "\nALL INVARIANTS PASS")
for f in fails: print(" ", f)
