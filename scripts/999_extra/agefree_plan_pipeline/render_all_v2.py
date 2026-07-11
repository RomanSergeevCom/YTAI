#!/usr/bin/env python3
"""Render all 4 pages with v2 (exact quotes + numbers/anchors + chrono) into the repo (staged)."""
import sys, json
from pathlib import Path
sys.path.insert(0, "/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad")
import agefree_plan_html_v2 as V
SCR = "/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad"
for nn in ("03","04","05","06"):
    plan = json.load(open(f"{SCR}/plan_{nn}_final.json"))
    inp = json.load(open(f"{SCR}/inputs_{nn}.json"))
    folders = open(f"{SCR}/folders_{nn}.html").read()
    dest = Path(f"/Users/romansergeev/RYA/yt-rya-ae/web/ytagefree/{nn}")
    dest.mkdir(parents=True, exist_ok=True)
    html = V.render(plan, inp["drive"], inp["transcription"], inp["sources"], folders)
    (dest/"index.html").write_text(html, encoding="utf-8")
    print(f"[{nn}] wrote {len(html)}b")
