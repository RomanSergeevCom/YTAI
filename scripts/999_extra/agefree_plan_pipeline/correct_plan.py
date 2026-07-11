#!/usr/bin/env python3
"""Ground a reconstructed plan_NN.json against the real transcripts:
 - locate each beat's quote in its cited source_file (word-level difflib alignment)
 - snap tc_in/tc_out to true segment boundaries
 - if quote not verbatim (coverage<0.6), replace with exact transcript text of the located span
 - emit corrected plan + change report
Usage: correct_plan.py NN"""
import re, json, sys, difflib, os, glob
NN = sys.argv[1]
SCR = "/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad"
PROJ = {"03":"YTAgeFree03_Caregiver_Burnout","04":"YTAgeFree04_Avoiding_Breakdowns",
        "05":"YTAgeFree05_Home_Safety_Bathroom","06":"YTAgeFree06_Dementia_Home_Setup"}[NN]
DISK = f"/Volumes/T7-Beige-RYA/YTAgeFree/{PROJ}/99_Pipeline/Transcripts"
plan = json.load(open(f"{SCR}/plan_{NN}.json"))

def norm_words(s): return re.sub(r'[^а-яёa-z0-9 ]', ' ', (s or '').lower()).split()
def mmss(x): return f"{int(x//60)}:{x%60:05.2f}"

def tpath(fname):
    stem = fname.replace(".MP4","").replace(".mp4","")
    for c in (f"{DISK}/{stem}/{stem}_transcript.json", f"{DISK}/{stem}/{stem}.json", f"{DISK}/{stem}.json"):
        if os.path.exists(c): return c
    g = glob.glob(f"{DISK}/{stem}*/*.json")
    return g[0] if g else None

_cache = {}
def word_index(path):
    """return (words[], wseg[] parallel: segment dict per word)"""
    if path in _cache: return _cache[path]
    segs = json.load(open(path)).get("segments", [])
    words, wseg = [], []
    for s in segs:
        for w in norm_words(s.get("text","")):
            words.append(w); wseg.append(s)
    _cache[path] = (words, wseg, segs)
    return _cache[path]

def locate(path, quote):
    """Anchor on the LONGEST CONTIGUOUS word match (not scattered blocks), then map the
    quote's word span onto the file at that offset. Robust to common-word noise."""
    words, wseg, segs = word_index(path)
    qw = norm_words(quote)
    if not qw or not words: return None
    sm = difflib.SequenceMatcher(None, qw, words, autojunk=False)
    m = sm.find_longest_match(0, len(qw), 0, len(words))
    if m.size == 0: return {"cov": 0.0, "s": None, "e": None, "verbatim": "", "spk": ""}
    cov = m.size / len(qw)                      # contiguous coverage
    j_start = max(0, m.b - m.a)                  # file idx aligned to quote word 0
    j_end = min(len(words) - 1, j_start + len(qw) - 1)
    seg0 = wseg[j_start]; seg1 = wseg[j_end]
    verbatim = " ".join(s.get("text", "") for s in segs
                        if s["start"] >= seg0["start"] - 0.01 and s["end"] <= seg1["end"] + 0.01).strip()
    return {"cov": cov, "s": seg0["start"], "e": seg1["end"], "verbatim": verbatim, "spk": seg0.get("speaker", "")}

report = []
def fix_beats(beats, tag):
    for b in beats:
        p = tpath(b.get("source_file",""))
        old_tc = f'{b.get("tc_in")}–{b.get("tc_out")}'
        if not p:
            report.append(f"  ❌ NOFILE {b.get('source_file')} [{tag}] {b.get('quote','')[:40]}"); continue
        loc = locate(p, b.get("quote",""))
        cov = loc["cov"] if loc else 0.0
        try:
            ci = int(b['tc_in'].split(':')[0])*60 + float(b['tc_in'].split(':')[1])
        except: ci = None
        drift = (ci - loc["s"]) if (ci is not None and loc and loc["s"] is not None) else None
        # unresolved: quote not verbatim in this file
        if cov < 0.40:
            report.append(f"  ❌ UNRESOLVED {b.get('source_file')[:18]} [{old_tc}] cov={cov:.2f} «{b.get('quote','')[:44]}»"); continue
        # suspicious: strong match but far from cited tc → likely the cite was right / phrase repeats. leave untouched.
        if drift is not None and abs(drift) > 12:
            report.append(f"  ⚠️ SUSPICIOUS {b['source_file'][:16]} cited[{old_tc}] vs found[{mmss(loc['s'])}] Δ{drift:+.0f}s cov={cov:.2f} — LEFT AS-IS, check «{b['quote'][:40]}»"); continue
        new_in, new_out = mmss(loc["s"]), mmss(loc["e"])
        # human-written quotes are clean sentences; keep them. Snap only the in-point (verified by anchor).
        # flag lightly-paraphrased (cov 0.40-0.62) for eyeball, but keep quote + snap tc.
        if drift is not None and abs(drift) > 2.0:
            b["tc_in"] = new_in
            tag2 = "⏱ TC SNAP " if cov >= 0.62 else "≈ PARAPHRASE"
            report.append(f"  {tag2} {b['source_file'][:16]} [{old_tc.split('–')[0]}→{new_in}] Δ{drift:+.1f}s cov={cov:.2f}")
        elif cov < 0.62:
            report.append(f"  ≈ PARAPHRASE {b['source_file'][:16]} [{old_tc.split('–')[0]}] cov={cov:.2f} — quote loose but locatable")

if plan.get("hook"): fix_beats(plan["hook"]["beats"], "HOOK")
for s in plan.get("sections", []): fix_beats(s["beats"], f"S{s.get('n')}")
if plan.get("cta"): fix_beats(plan["cta"]["beats"], "CTA")

json.dump(plan, open(f"{SCR}/plan_{NN}_fixed.json","w"), ensure_ascii=False, indent=1)
print(f"===== {NN} · {PROJ} — corrections =====")
print("\n".join(report) if report else "  (no changes)")
nfix = sum(1 for r in report if "QUOTE FIX" in r); nsnap = sum(1 for r in report if "TC SNAP" in r)
nun = sum(1 for r in report if "UNRESOLVED" in r or "NOFILE" in r)
print(f"\n  quote_fixes={nfix}  tc_snaps={nsnap}  unresolved={nun}  → plan_{NN}_fixed.json")
