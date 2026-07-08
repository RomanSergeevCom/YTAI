#!/usr/bin/env python3
"""
create_board.py — завести Trello-доску канала RSC «Production Projects» из шаблона
«YT Template — шаблон доски канала» (=YT Demo, id 66fc09fff3a55640376df3db).

RSC = разовые продакшн-проекты (2D/моушн-анимация для клиентов), НЕ YouTube-канал, но
живёт в той же экосистеме. Hybrid-режим: стандартные YT-этапы 01Created…11Archived, чтобы
кокпит /production/ подхватил доску без правок STAGE_MAP. Доска называется так, чтобы
production_trello.py (BOARD_RE ^(?:YT[A-Z]|RSC)) распознал её по коду RSC.

Идемпотентно: если доска с таким именем уже открыта — переиспользую; списки/метку/карточки
довожу до канона, дубли не пложу.

Креды (read/write): ~/.config/rya/trello.env → TRELLO_KEY, TRELLO_TOKEN (Winston provisioned).

Запуск:
    python3 scripts/999_extra/rsc/create_board.py            # создать/дозаполнить
    python3 scripts/999_extra/rsc/create_board.py --dry-run  # только план
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.trello.com/1"
ENV_PATH = Path.home() / ".config/rya/trello.env"
TEMPLATE_ID = "66fc09fff3a55640376df3db"      # «YT Demo» / YT Template
ORG_ID = "611f8c803fdb8f3dfb31c7c7"           # httpsryaae / RYA Work Space
BOARD_NAME = "RSC — Production Projects"
LISTS = ["01Created", "02Script", "03Shooting", "04PreEditing", "05Editing",
         "06Review", "07Revisions", "08Gate", "09Ready", "10Published", "11Archived"]
# карточки: код в имени парсится CODE_RE ^((?:YT[A-Z]{2,4}|RSC)\d+)_ ; трёхзначная нумерация
START_LIST = "02Script"                        # у всех троих сценарии готовы (Роман расставит точнее)
CARDS = ["RSC001_Teplyj_Dom", "RSC002_AJAX_ARGO", "RSC003_AJAX_ASP7011"]


def load_creds() -> tuple[str, str]:
    if not ENV_PATH.exists():
        sys.exit(f"ERROR: {ENV_PATH} not found (ask Winston to provision Trello creds)")
    kv = {}
    for ln in ENV_PATH.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        kv[k.strip()] = v.strip().strip('"').strip("'")
    try:
        return kv["TRELLO_KEY"], kv["TRELLO_TOKEN"]
    except KeyError:
        sys.exit(f"ERROR: TRELLO_KEY/TRELLO_TOKEN missing in {ENV_PATH}")


KEY, TOKEN = "", ""


def api(method: str, path: str, **params):
    params.update(key=KEY, token=TOKEN)
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get(path, **p):
    return api("GET", path, **p)


def post(path, **p):
    return api("POST", path, **p)


def main():
    global KEY, TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default=BOARD_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    KEY, TOKEN = load_creds()

    # 1) reuse existing board with the same name, else create from template
    boards = get("members/me/boards", filter="open", fields="name,url,shortLink,idOrganization")
    board = next((b for b in boards if b["name"] == args.name), None)
    if board:
        print(f"↻ доска уже есть: {board['name']}  {board['url']}")
    else:
        if args.dry_run:
            print(f"[dry-run] создал бы доску «{args.name}» из шаблона {TEMPLATE_ID} в орг {ORG_ID}")
            return
        board = post("boards", name=args.name, idOrganization=ORG_ID,
                     idBoardSource=TEMPLATE_ID, keepFromSource="none",
                     defaultLists="false", prefs_permissionLevel="org")
        print(f"✓ создана доска: {board['name']}  {board['url']}")
    bid = board["id"]

    # 2) ensure the 11 canonical lists exist (in order)
    lists = get(f"boards/{bid}/lists", filter="all", fields="name,pos,closed")
    have = {l["name"]: l for l in lists if not l.get("closed")}
    for i, ln in enumerate(LISTS):
        if ln in have:
            continue
        if args.dry_run:
            print(f"[dry-run] создал бы список {ln}")
            continue
        lst = post("lists", name=ln, idBoard=bid, pos=(i + 1) * 1000)
        have[ln] = lst
        print(f"  + список {ln}")

    # 3) ensure a red 'Blocked' label
    labels = get(f"boards/{bid}/labels", fields="name,color")
    if not any((l.get("name") or "").lower() == "blocked" for l in labels):
        if not args.dry_run:
            post("labels", name="Blocked", color="red", idBoard=bid)
        print("  + метка Blocked (red)")

    # 4) add project cards to START_LIST (skip if code already present)
    cards = get(f"boards/{bid}/cards", filter="open", fields="name")
    existing_codes = {c["name"].split("_", 1)[0].split(" ", 1)[0] for c in cards}
    target = have.get(START_LIST)
    if not target:
        print(f"! список {START_LIST} не найден — карточки не добавлены")
    else:
        for name in CARDS:
            code = name.split("_", 1)[0]
            if code in existing_codes:
                print(f"  = карточка {code} уже есть")
                continue
            if args.dry_run:
                print(f"[dry-run] добавил бы карточку {name} → {START_LIST}")
                continue
            c = post("cards", idList=target["id"], name=name, pos="bottom")
            print(f"  + карточка {name} → {START_LIST}  {c.get('shortUrl','')}")

    # 5) summary artifacts for channels.json / hub
    print("\n=== АРТЕФАКТЫ (для channels.json / hub) ===")
    print(f"board.id (24-hex): {bid}")
    print(f"shortLink:         {board.get('shortLink','')}")
    print(f"trello URL:        {board['url']}")


if __name__ == "__main__":
    main()
