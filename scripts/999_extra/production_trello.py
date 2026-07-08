#!/usr/bin/env python3
"""
production_trello.py — anti-drag production scoreboard feed, sourced from TRELLO.

Trello is where Roman actually runs production. One board per channel — board name
STARTS with the channel code ("YTCR — Core Realty Dubai", reform 2026-06-12); the code
is extracted via CH_RE. Lists = playbook §2 numbered statuses, unified across boards:

    01Created → 02Script → 03Shooting → 04PreEditing → 05Editing → 06Review
    → 07Revisions → 08Gate → 09Ready → 10Published → 11Archived

Cards = projects; card name carries the project code (regex ^(YT[A-Z]{2,4}\\d+)_),
same as the YTAI pipeline. "Days in stage" is REAL: taken from the card's last move
into its current list (updateCard action with data.listAfter), so STUCK detection works.

Emits the same contract as production_board.py:  <repo>/web/_data/production.json
Consumed by /production/ (RYA-bot wires it) and Rearden /roster + weekly nudge.

Creds (read-only) come from an env file Winston provisioned — NEVER hardcode:
    ~/.config/rya/trello.env   →   TRELLO_KEY, TRELLO_TOKEN   (chmod 600)

Paired doc: production_trello_README.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.trello.com/1"
# RSC = разовые продакшн-проекты (анимация), псевдо-канал в той же экосистеме (Hybrid:
# стандартные YT-этапы). Регэкспы принимают и YT-каналы, и код RSC. \d+ = трёхзначная нумерация.
CODE_RE = re.compile(r"^((?:YT[A-Z]{2,4}|RSC)\d+)_")
BOARD_RE = re.compile(r"^(?:YT[A-Z]|RSC)")    # real YT channel boards + RSC production board
CH_RE = re.compile(r"^(YT[A-Za-z]+|RSC)")     # channel code = leading token of board name
ENV_PATH = Path.home() / ".config/rya/trello.env"
DEFAULT_STUCK_DAYS = 14

# Channels absent from channels.json registry still get a stable distinct color.
FALLBACK_COLORS = {
    "YTCGRU": "#7DD3FC",   # kin to YTCG #93C5FD
    "YTCN":   "#F87171",
    "YTGOLD": "#EAB308",
    "YTLM":   "#A3E635",
    "YTMS":   "#38BDF8",   # kin to YTMSEN #4EA8DE
    "YTUAE":  "#34D399",
    "RSC":    "#F59E0B",   # янтарь — разовые продакшн-проекты (не YouTube-канал)
}
FALLBACK_PALETTE = ["#60A5FA", "#FB923C", "#E879F9", "#F472B6", "#2DD4BF", "#FACC15"]


def channel_color(ch: str, colors: dict) -> str:
    return (colors.get(ch) or FALLBACK_COLORS.get(ch)
            or FALLBACK_PALETTE[sum(ch.encode()) % len(FALLBACK_PALETTE)])

# Trello list name (lowercased) → (scoreboard label, order, class)
# class: "flight" = in production · "done" = published · "service"/"booking" = hidden by default
# Labels = EXACT Trello list names (playbook §2 tokens) — доска и кокпит говорят одним языком.
STAGE_MAP = {
    # numbered playbook scheme (reform 2026-06-12, все доски)
    "01created":          ("01Created",          10, "flight"),
    "02script":           ("02Script",           20, "flight"),
    "03shooting":         ("03Shooting",         30, "flight"),
    "04preediting":       ("04PreEditing",       40, "flight"),
    "05editing":          ("05Editing",          50, "flight"),
    "06review":           ("06Review",           60, "flight"),
    "07revisions":        ("07Revisions",        65, "flight"),
    "08gate":             ("08Gate",             68, "flight"),
    "09ready":            ("09Ready",            70, "flight"),
    "10published":        ("10Published",        90, "done"),
    "11archived":         ("11Archived",         99, "service"),
    # booking-воронка YTCR (pre-pipeline, до 01Created)
    "not booked yet":     ("Not booked yet",      1, "booking"),
    "tentatively agreed": ("Tentatively agreed",  2, "booking"),
    "under review":       ("Under review",        3, "booking"),
    # legacy aliases (имена списков до реформы) — на случай отката/новой сырой доски
    "start":              ("01Created",          10, "flight"),
    "script":             ("02Script",           20, "flight"),
    "script approved":    ("02Script",           20, "flight"),  # YTGOLD variant
    "source":             ("03Shooting",         30, "flight"),
    "editing":            ("05Editing",          50, "flight"),
    "ready":              ("09Ready",            70, "flight"),
    "yt":                 ("10Published",        90, "done"),
    "youtube":            ("10Published",        90, "done"),
    "end":                ("10Published",        90, "done"),    # YTCH separator
    "vk":                 ("10Published",        91, "done"),    # YTGOLD/YTLM/YTMS
    "archive":            ("11Archived",         99, "service"),
    "archived":           ("11Archived",         99, "service"),
}


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


def api_get(path: str, key: str, token: str, **params):
    params.update(key=key, token=token)
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:           # rate limit → back off
                time.sleep(1.5 * (attempt + 1)); continue
            raise
        except Exception:
            time.sleep(0.8); continue
    raise RuntimeError(f"Trello API failed: {path}")


def days_in_stage(card_id, cur_list_id, key, token, now):
    """Real days since the card last entered its current list (or was created there)."""
    acts = api_get(f"cards/{card_id}/actions", key, token,
                   filter="updateCard,createCard,moveCardToBoard", limit=50)
    enter = None
    for a in acts:                      # newest first
        d = a.get("data", {})
        la = d.get("listAfter") or {}
        if la.get("id") == cur_list_id:
            enter = a.get("date"); break
        if a.get("type") == "createCard" and d.get("list", {}).get("id") == cur_list_id:
            enter = a.get("date"); break
    if not enter:
        return None, None
    dt = datetime.fromisoformat(enter.replace("Z", "+00:00"))
    return dt.date().isoformat(), (now - dt).days


def main() -> int:
    ap = argparse.ArgumentParser(description="Trello → production.json scoreboard feed")
    ap.add_argument("--out", default=str(Path.home() / "RYA/yt-rya-ae/web/_data/production.json"))
    ap.add_argument("--boards", default="", help="comma allowlist of channel codes (default: all open YT boards)")
    ap.add_argument("--stuck-days", type=int, default=DEFAULT_STUCK_DAYS)
    ap.add_argument("--include-booking", action="store_true", help="show YTCR pre-prod booking lists")
    ap.add_argument("--include-service", action="store_true", help="show Source/Archive lists")
    ap.add_argument("--channels-json", default=str(Path.home() / "RYA/yt-rya-ae/web/_data/channels.json"),
                    help="for per-channel colors")
    args = ap.parse_args()

    key, token = load_creds()
    now = datetime.now(timezone.utc)
    allow = {b.strip().upper() for b in args.boards.split(",") if b.strip()} or None

    # channel colors from portal registry (best-effort)
    colors = {}
    try:
        cj = json.loads(Path(args.channels_json).read_text())
        for ch in cj.get("channels", []):
            colors[(ch.get("id") or "").upper()] = ch.get("color")
    except Exception:
        pass

    boards = api_get("members/me/boards", key, token, filter="open",
                     fields="name,closed,shortUrl")
    boards = [b for b in boards if not b.get("closed") and BOARD_RE.match(b.get("name", ""))]
    for b in boards:                    # channel code = leading token ("YTCR — …" → YTCR)
        b["ch"] = CH_RE.match(b["name"]).group(1).upper()
    if allow:
        boards = [b for b in boards if b["ch"] in allow]
    # dedupe by channel code (keep first open)
    seen, uniq = set(), []
    for b in sorted(boards, key=lambda b: b["name"]):
        if b["ch"] in seen:
            continue
        seen.add(b["ch"]); uniq.append(b)
    boards = uniq

    projects, skipped_service, skipped_booking, skipped_closed = [], 0, 0, 0
    for b in boards:
        ch = b["ch"]
        lists = api_get(f"boards/{b['id']}/lists", key, token, filter="all",
                        fields="name,pos,closed")
        lname = {l["id"]: l["name"] for l in lists}
        closed_lists = {l["id"] for l in lists if l.get("closed")}
        cards = api_get(f"boards/{b['id']}/cards", key, token, filter="open",
                        fields="name,idList,due,dateLastActivity,shortUrl")
        for c in cards:
            if c["idList"] in closed_lists or c["idList"] not in lname:
                skipped_closed += 1; continue   # template/junk cards on archived lists
            raw_list = lname.get(c["idList"], "")
            label, order, klass = STAGE_MAP.get(raw_list.strip().lower(),
                                                (raw_list, 0, "unknown"))
            if klass == "service" and not args.include_service:
                skipped_service += 1; continue
            if klass == "booking" and not args.include_booking:
                skipped_booking += 1; continue
            m = CODE_RE.match(c["name"])
            code = m.group(1) if m else None
            in_flight = klass == "flight"
            last_update, days = (None, None)
            if in_flight:               # only spend an actions-call on in-flight cards
                last_update, days = days_in_stage(c["id"], c["idList"], key, token, now)
            stuck = bool(in_flight and days is not None and days >= args.stuck_days)
            projects.append({
                "channel_id": ch,
                "channel_color": channel_color(ch, colors),
                "code": code,
                "title": c["name"],
                "board": b["name"],
                "board_url": b.get("shortUrl"),
                "list": raw_list,
                "stage_label": label,
                "stage_order": order,
                "stage_class": klass,
                "in_flight": in_flight,
                "due": c.get("due"),
                "url": c.get("shortUrl"),
                "last_update": last_update,
                "days_since_update": days,
                "dateLastActivity": c.get("dateLastActivity", "")[:10] or None,
                "stuck": stuck,
            })

    inflight = [p for p in projects if p["in_flight"]]
    stuck = sorted([p for p in inflight if p["stuck"]],
                   key=lambda p: (p["days_since_update"] or 0), reverse=True)
    hist: dict[str, int] = {}
    for p in inflight:                  # key by normalized stage (Start/start → one bucket)
        hist[p["stage_label"]] = hist.get(p["stage_label"], 0) + 1

    feed = {
        "generated": now.isoformat(timespec="seconds"),
        "source": "trello",
        "boards": [b["name"] for b in boards],
        "board_links": [{"code": b["ch"], "name": b["name"], "url": b.get("shortUrl"),
                         "color": channel_color(b["ch"], colors)} for b in boards],
        "stuck_days_threshold": args.stuck_days,
        "summary": {
            "total": len(projects),
            "in_flight": len(inflight),
            "done": len([p for p in projects if p["stage_class"] == "done"]),
            "stuck": len(stuck),
            "stage_histogram": hist,
            "hidden_service": skipped_service,
            "hidden_booking": skipped_booking,
            "hidden_closed_list": skipped_closed,
        },
        "stuck_list": [
            {"code": p["code"], "title": p["title"], "channel_id": p["channel_id"],
             "list": p["list"], "days_since_update": p["days_since_update"]}
            for p in stuck
        ],
        "projects": projects,
    }

    out_path = Path(args.out).expanduser()
    out_path.write_text(json.dumps(feed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    s = feed["summary"]
    print(f"production.json ← Trello ({len(boards)} boards: {', '.join(feed['boards'])})")
    print(f"  → {out_path}")
    print(f"  projects: {s['total']}  in-flight: {s['in_flight']}  done: {s['done']}  "
          f"STUCK(>{args.stuck_days}d): {s['stuck']}  (hidden: {s['hidden_service']} service, {s['hidden_booking']} booking)")
    if hist:
        print("  in-flight by stage: " + ", ".join(
            f"{k}:{v}" for k, v in sorted(hist.items(), key=lambda kv: -kv[1])))
    if stuck:
        print("  ⚠ STUCK:")
        for p in stuck:
            print(f"     {(p['code'] or p['title'])[:24]:<24} {p['list']:<10} {p['days_since_update']}d")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
