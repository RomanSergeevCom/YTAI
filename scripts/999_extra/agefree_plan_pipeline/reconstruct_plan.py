#!/usr/bin/env python3
"""Reconstruct a full plan.json from a rendered ytagefree plan page (agefree_plan_html.py output).
Also extracts render inputs (drive_url, tr_url, sources) and the verbatim folders <div class="dbox">.
Usage: reconstruct_plan.py NN  -> writes plan_NN.json + folders_NN.html + inputs_NN.json to scratch."""
import re, html, json, sys
NN = sys.argv[1]
SCR = "/private/tmp/claude-501/-Users-romansergeev-YTAI/ef55ceeb-461d-4280-9fc6-05257ea4e213/scratchpad"
PAGE = f"/Users/romansergeev/RYA/yt-rya-ae/web/ytagefree/{NN}/index.html"
t = open(PAGE, encoding="utf-8").read()

def unesc(s): return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()
def clean_head(s):  # strip trailing 🔗 alink text
    return unesc(s).replace("🔗", "").strip()

def parse_beats(block):
    out = []
    for bm in re.finditer(r'<div class="beat"><div class="src">(.*?)</div>\s*<div class="q">(.*?)</div>(?:<div class="why">(.*?)</div>)?</div>', block, re.S):
        src, q, why = bm.group(1), bm.group(2), bm.group(3)
        tc = re.search(r'<span class="tc">(.*?)</span>', src)
        f = re.search(r'<span class="file">(.*?)</span>', src)
        sp = re.search(r'<span class="spk">(.*?)</span>', src)
        tcv = unesc(tc.group(1)) if tc else ""
        m2 = re.match(r'(.+?)–(.+)', tcv)
        out.append({"tc_in": (m2.group(1) if m2 else tcv), "tc_out": (m2.group(2) if m2 else ""),
                    "source_file": unesc(f.group(1)) if f else "", "speaker": unesc(sp.group(1)) if sp else "",
                    "quote": unesc(q), "why": unesc(why) if why else ""})
    return out

def parse_broll(block):
    return [unesc(x) for x in re.findall(r'<span class="b">(.*?)</span>', block)]

plan = {"code": f"YTAgeFree{NN}"}
plan["title"] = unesc(re.search(r'<div class="lede"><h1>(.*?)</h1>', t, re.S).group(1))
mprom = re.search(r'<div class="promise">(.*?)</div>', t, re.S)
plan["logline"] = unesc(mprom.group(1)) if mprom else ""
mp = re.search(r'<div class="promise">.*?</div>\s*<p style="color:var\(--text-dim\)">(.*?)</p>', t, re.S)
plan["promise"] = unesc(mp.group(1)) if mp else ""
malt = re.search(r'Альт\. заголовки:\s*(.*?)</div>', t, re.S)
if malt:
    plan["alt_titles"] = [x.strip() for x in unesc(malt.group(1)).split(" · ") if x.strip()]
mau = re.search(r'<span class="m">👥\s*(.*?)</span>', t, re.S)
plan["audience"] = unesc(mau.group(1)) if mau else ""
mdur = re.search(r'<span class="m">⏱\s*~(\d+):(\d+)</span>', t)
if mdur: plan["est_duration_sec"] = int(mdur.group(1))*60 + int(mdur.group(2))

# split into sec blocks (hook + numbered). Each: <div class="sec ...">...</div-chain until next sec/cta/notes/srcfoot
# capture from each sec open to just before next sec/cta/dbox/notes/srcfoot
anchors = [m.start() for m in re.finditer(r'<div class="(?:sec |cta|notes|srcfoot)', t)]
anchors.append(len(t))
hook = None; sections = []
for i in range(len(anchors)-1):
    seg = t[anchors[i]:anchors[i+1]]
    if seg.startswith('<div class="sec'):
        num = unesc(re.search(r'<div class="num">(.*?)</div>', seg).group(1))
        h = clean_head(re.search(r'<h2>(.*?)</h2>', seg).group(1))
        g = re.search(r'<div class="goal">(.*?)</div>', seg, re.S)
        obj = {"heading": h, "goal": unesc(g.group(1)) if g else "",
               "beats": parse_beats(seg), "broll": parse_broll(seg)}
        if "HOOK" in num:
            hook = obj
        else:
            mn = re.search(r'(\d+)', num); obj["n"] = int(mn.group(1)) if mn else len(sections)+1
            sections.append(obj)
if hook: plan["hook"] = hook
plan["sections"] = sections

# cta
mcta = re.search(r'<div class="cta" id="cta">(.*?)</div>\s*(?:<div class="notes"|<div class="srcfoot"|</div>\s*'+re.escape('{COPY_JS}')+')', t, re.S)
mcta = re.search(r'<div class="cta" id="cta">(.*)', t, re.S)
if mcta:
    ctablk = mcta.group(1)
    # cut at notes/srcfoot
    ctablk = re.split(r'<div class="notes"|<div class="srcfoot"', ctablk)[0]
    mtx = re.search(r'<p style="color:var\(--text-dim\)">(.*?)</p>', ctablk, re.S)
    plan["cta"] = {"text": unesc(mtx.group(1)) if mtx else "", "beats": parse_beats(ctablk)}
# notes
mn = re.search(r'<div class="notes" id="notes">(.*?)</div>', t, re.S)
if mn:
    plan["editor_notes"] = [unesc(x) for x in re.findall(r'<li>(.*?)</li>', mn.group(1), re.S)]

# render inputs
drive = re.search(r'📁 Открыть папку проекта</a>', t)
mdr = re.search(r'href="(https://drive\.google\.com/drive/folders/[^"]+)"[^>]*>📁 Открыть папку проекта', t)
mtr = re.search(r'href="(https://drive\.google\.com/drive/folders/[^"]+)"[^>]*>📝 Пословная', t)
msrc = re.search(r'Исходники \(на Drive / SSD[^:]*:\s*(.*?)</div>', t, re.S)
sources = re.findall(r'<code>(.*?)</code>', msrc.group(1)) if msrc else []
inputs = {"drive": mdr.group(1) if mdr else "", "transcription": mtr.group(1) if mtr else "",
          "sources": sources}
# verbatim folders block
mfold = re.search(r'(<div class="dbox" id="folders">.*?</div>)\s*(?=<div class="sec)', t, re.S)
folders_html = mfold.group(1) if mfold else ""

json.dump(plan, open(f"{SCR}/plan_{NN}.json", "w"), ensure_ascii=False, indent=1)
json.dump(inputs, open(f"{SCR}/inputs_{NN}.json", "w"), ensure_ascii=False, indent=1)
open(f"{SCR}/folders_{NN}.html", "w").write(folders_html)
nb = len(hook["beats"]) if hook else 0
nb += sum(len(s["beats"]) for s in sections) + len(plan.get("cta", {}).get("beats", []))
print(f"plan_{NN}.json: title={plan['title'][:40]!r} sections={len(sections)} beats={nb} "
      f"cta_beats={len(plan.get('cta',{}).get('beats',[]))} notes={len(plan.get('editor_notes',[]))} "
      f"folders_html={len(folders_html)}b sources={len(sources)}")
