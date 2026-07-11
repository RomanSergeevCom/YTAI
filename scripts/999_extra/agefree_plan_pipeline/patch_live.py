#!/usr/bin/env python3
"""Surgically patch the live page's beat tc-spans from plan_NN_fixed.json (position-based,
in beat order = hook+sections+cta). Only rewrites <span class="tc">…</span>; chrome untouched.
Usage: patch_live.py NN [write]"""
import sys, re, json, html
NN = sys.argv[1]; WRITE = "write" in sys.argv
SCR = "/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad"
PAGE = f"/Users/romansergeev/RYA/yt-rya-ae/web/ytagefree/{NN}/index.html"
plan = json.load(open(f"{SCR}/plan_{NN}_fixed.json"))
beats = list(plan.get("hook", {}).get("beats", []))
for s in plan.get("sections", []): beats += s["beats"]
beats += plan.get("cta", {}).get("beats", [])
t = open(PAGE, encoding="utf-8").read()

it = iter(beats)
changed = [0]
def repl(m):
    blk = m.group(0)
    try: b = next(it)
    except StopIteration: return blk
    new_tc = f'{b["tc_in"]}–{b["tc_out"]}'
    def sub_tc(mm):
        old = mm.group(1)
        if html.unescape(old) != new_tc: changed[0] += 1
        return f'<span class="tc">{html.escape(new_tc)}</span>'
    return re.sub(r'<span class="tc">(.*?)</span>', sub_tc, blk, count=1)

# iterate beat blocks in document order
new = re.sub(r'<div class="beat"><div class="src">.*?</div>\s*<div class="q">.*?</div>(?:<div class="why">.*?</div>)?</div>',
             repl, t, flags=re.S)
leftover = sum(1 for _ in it)
print(f"{NN}: beats={len(beats)} tc_changed={changed[0]} leftover_unconsumed={leftover}")
if WRITE and leftover == 0:
    open(PAGE, "w", encoding="utf-8").write(new)
    print(f"   wrote {PAGE}")
else:
    open(f"{SCR}/patched_{NN}.html", "w").write(new)
