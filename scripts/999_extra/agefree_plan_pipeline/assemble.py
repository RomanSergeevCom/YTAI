#!/usr/bin/env python3
"""Assemble EXACT complete verbatim quotes from the workflow's chosen segment boundaries.
Reads blocks-result JSON (from wf_quotes) + per-block packet windows, rebuilds each beat's
quote (verbatim, cross-talk removed), snaps tc, computes spoken duration. Writes plan_NN_final.json.
Usage: assemble.py <blocks_result.json>"""
import re, json, sys, os
SCR = "/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad"
result = json.load(open(sys.argv[1]))
blocks = {b["key"]: b for b in (result.get("blocks") or result)}

def mmss(x):
    x=max(0,x); return f"{int(x//60)}:{x%60:05.2f}"
def clean(txt):
    return re.sub(r'\s+', ' ', txt).strip()

def assemble_one(key):
    b = blocks.get(key)
    pk = json.load(open(f"{SCR}/packets/{key.replace(':','_')}.json"))
    win = pk.get("window") or []
    if not b or b.get("first") is None or b.get("last") is None or not win:
        return None
    f, l = b["first"], b["last"]
    f = max(0, min(f, len(win)-1)); l = max(f, min(l, len(win)-1))
    cuts = b.get("inner_cuts") or []
    def is_cut(i):
        for c in cuts:
            a, bb = (c.get("a"), c.get("b")) if isinstance(c, dict) else (c[0], c[1])
            if a is not None and bb is not None and a <= i <= bb: return True
        return False
    kept = [win[i] for i in range(f, l+1) if not is_cut(i)]
    if not kept: return None
    quote = clean(" ".join(s["text"] for s in kept))
    tc_in = win[f]["s"]; tc_out = win[l]["e"]
    dur = sum(s["e"] - s["s"] for s in kept)
    return {"quote": quote, "tc_in": mmss(tc_in), "tc_out": mmss(tc_out), "dur": round(dur, 2),
            "speaker": b.get("speaker", ""), "note": b.get("note", ""), "verify_ok": b.get("verify_ok"),
            "issue": b.get("issue", "")}

PROJ = {"03":"YTAgeFree03","04":"YTAgeFree04","05":"YTAgeFree05","06":"YTAgeFree06"}
report = []
for nn in PROJ:
    plan = json.load(open(f"{SCR}/plan_{nn}.json"))
    flat = []
    if plan.get("hook"): flat += [("hook", b) for b in plan["hook"]["beats"]]
    for s in plan.get("sections", []): flat += [("sec", b) for b in s["beats"]]
    if plan.get("cta"): flat += [("cta", b) for b in plan["cta"]["beats"]]
    changed = miss = 0
    for bi, (_, beat) in enumerate(flat):
        a = assemble_one(f"{nn}:{bi}")
        if not a:
            miss += 1; report.append(f"  {nn}:{bi} MISS (no boundaries) — kept old"); continue
        old_len = len(beat.get("quote", ""))
        beat["quote"] = a["quote"]; beat["tc_in"] = a["tc_in"]; beat["tc_out"] = a["tc_out"]
        beat["dur_sec"] = a["dur"]
        # NOTE: keep existing speaker labels (Мария Литвенова on ZVE1 expert / Елизавета on FX3) —
        # they use cross-clip facts the per-block agents lacked (noisy diarization). Do NOT overwrite.
        changed += 1
        if a["issue"]: report.append(f"  {nn}:{bi} ⚠ verify issue: {a['issue'][:70]}")
    json.dump(plan, open(f"{SCR}/plan_{nn}_final.json", "w"), ensure_ascii=False, indent=1)
    print(f"[{nn}] beats={len(flat)} rebuilt={changed} miss={miss}")
if report:
    print("\n--- flags ---"); print("\n".join(report[:40]))
