#!/usr/bin/env python3
"""
trello_reform.py — привести все YT-доски Trello к playbook-схеме (yt.rya.ae/playbook §2/§5).

Эталон: YTRF (11 списков 01Created..11Archived + красная метка Blocked).
- board name → "YTXX — Название"
- списки rename по карте (история карточек сохраняется), недостающие создаются
- Source → 03Shooting (исходники получены), VK/end → карточки в 10Published (+зелёная метка VK)
- красная метка → "Blocked"
- YT Demo / YT Test → close
Запуск: python3 trello_reform.py [--apply]   (без --apply = dry-run)
"""
import json, re, sys, time, urllib.parse, urllib.request

API = "https://api.trello.com/1"
APPLY = "--apply" in sys.argv

def creds():
    kv = {}
    for ln in open(f"{__import__('os').path.expanduser('~')}/.config/rya/trello.env"):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1); kv[k.strip()] = v.strip()
    return kv["TRELLO_KEY"], kv["TRELLO_TOKEN"]

KEY, TOKEN = creds()

def req(method, path, **params):
    params.update(key=KEY, token=TOKEN)
    url = f"{API}{path}?" + urllib.parse.urlencode(params)
    r = urllib.request.Request(url, method=method)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (attempt + 1)); continue
            print(f"  !! HTTP {e.code} {method} {path}: {e.read().decode()[:200]}")
            raise
    raise RuntimeError(f"failed {path}")

def get(path, **p): return req("GET", path, **p)
def put(path, **p):
    if not APPLY: print(f"  [dry] PUT {path} {p}"); return None
    return req("PUT", path, **p)
def post(path, **p):
    if not APPLY: print(f"  [dry] POST {path} {p}"); return {"id": "DRY"}
    return req("POST", path, **p)

# board name → new "CODE — Name"
BOARD_NAMES = {
    "YTCR":      "YTCR — Core Realty Dubai",
    "YTCG":      "YTCG — Connect Group Dubai",
    "YTCGRU":    "YTCGRU — Connect Group RU",
    "YTRF":      "YTRF — Рефлюкс Контроль",
    "YTFP":      "YTFP — Фонд Правмир · Ассистент Здоровья",
    "YTUVI":     "YTUVI — Драгоценные камни",
    "YTMSEN":    "YTMSEN — Multiple Sclerosis EN",
    "YTMS":      "YTMS — Рассеянный склероз",
    "YTCIV":     "YTCIV — Цивилизация",
    "YTAgeFree": "YTAgeFree — Старость в радость",
    "YTCH":      "YTCH — burodd.ru",
    "YTAZ":      "YTAZ — Незабудки · Всё о деменции",
    "YTCN":      "YTCN — CosmicNootropic",
    "YTGOLD":    "YTGOLD — Инвестиции в золото",
    "YTLM":      "YTLM — Лейкемия",
    "YTUAE":     "YTUAE — Интервью UAE",
}
CLOSE_BOARDS = {"YT Demo", "YT Test"}
SKIP_BOARDS = {"RomanSergeevCom"}

STATUSES = ["01Created","02Script","03Shooting","04PreEditing","05Editing",
            "06Review","07Revisions","08Gate","09Ready","10Published","11Archived"]
# old list name (lower) → target status
RENAME = {
    "start": "01Created", "script": "02Script", "script approved": "02Script",
    "source": "03Shooting", "editing": "05Editing", "ready": "09Ready",
    "yt": "10Published", "youtube": "10Published",
    "archive": "11Archived", "archived": "11Archived",
}
# lists whose cards merge into 10Published, then the list is archived
MERGE_TO_PUBLISHED = {"vk", "end"}
BOOKING = {"tentatively agreed", "under review", "not booked yet"}  # keep, far left (YTCR)

boards = get("/members/me/boards", filter="open", fields="name")
report = []
for b in boards:
    name = b["name"]
    if name in SKIP_BOARDS:
        report.append(f"SKIP  {name} (личная доска, нет YT-кода — решение за Романом)")
        continue
    if name in CLOSE_BOARDS:
        print(f"== {name}: CLOSE (тестовая)")
        put(f"/boards/{b['id']}", closed="true")
        report.append(f"CLOSE {name}")
        continue
    if name not in BOARD_NAMES:
        report.append(f"??    {name} — не знаю такой канал, не трогаю")
        continue

    new_name = BOARD_NAMES[name]
    print(f"== {name} → «{new_name}»")
    put(f"/boards/{b['id']}", name=new_name)

    lists = sorted(get(f"/boards/{b['id']}/lists", filter="open", fields="name,pos"),
                   key=lambda l: l["pos"])
    by_status = {}           # status → list id
    booking_lists = []       # (id, name) keep relative order
    merge_lists = []         # (id, name) → cards to 10Published
    extra = []
    for l in lists:
        low = l["name"].strip().lower()
        if low in BOOKING:
            booking_lists.append(l)
        elif l["name"] in STATUSES:
            by_status[l["name"]] = l["id"]
        elif low in RENAME:
            tgt = RENAME[low]
            if tgt in by_status:
                merge_lists.append((l, tgt))   # дубль → merge
            else:
                print(f"   rename list «{l['name']}» → {tgt}")
                put(f"/lists/{l['id']}", name=tgt)
                by_status[tgt] = l["id"]
        elif low in MERGE_TO_PUBLISHED:
            merge_lists.append((l, "10Published"))
        else:
            extra.append(l)

    # create missing status lists
    for st in STATUSES:
        if st not in by_status:
            print(f"   create list {st}")
            r = post(f"/boards/{b['id']}/lists", name=st, pos="bottom")
            by_status[st] = r["id"]

    # merge VK/end/dupes → target list, then archive the source list
    for l, tgt in merge_lists if isinstance(merge_lists, list) else []:
        tgt_id = by_status[tgt]
        cards = get(f"/lists/{l['id']}/cards", fields="name")
        low = l["name"].strip().lower()
        for c in cards:
            print(f"   move card «{c['name'][:40]}» ({l['name']} → {tgt})")
            put(f"/cards/{c['id']}", idList=tgt_id)
            if low == "vk":
                # пометить green-меткой VK чтобы не потерять платформу
                labels = get(f"/boards/{b['id']}/labels", fields="name,color")
                green = next((x for x in labels if x["color"] == "green"), None)
                if green:
                    if green.get("name") != "VK":
                        put(f"/labels/{green['id']}", name="VK")
                    post(f"/cards/{c['id']}/idLabels", value=green["id"])
        print(f"   archive list «{l['name']}»")
        put(f"/lists/{l['id']}", closed="true")

    # reorder: booking (как было) → 01..11
    pos = 1000.0
    for l in booking_lists:
        put(f"/lists/{l['id']}", pos=pos); pos += 1000
    for st in STATUSES:
        put(f"/lists/{by_status[st]}", pos=pos); pos += 1000

    # red label → Blocked
    labels = get(f"/boards/{b['id']}/labels", fields="name,color")
    red = next((x for x in labels if x["color"] == "red"), None)
    if red and red.get("name") != "Blocked":
        print("   label red → Blocked")
        put(f"/labels/{red['id']}", name="Blocked")
    elif not red:
        print("   create red Blocked label")
        post(f"/boards/{b['id']}/labels", name="Blocked", color="red")

    if extra:
        report.append(f"OK    {name} → «{new_name}» | EXTRA lists не тронуты: {[l['name'] for l in extra]}")
    else:
        report.append(f"OK    {name} → «{new_name}»")

print("\n--- ИТОГ ---")
for r in report: print(r)
print("\nMODE:", "APPLY" if APPLY else "DRY-RUN")
