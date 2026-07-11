#!/usr/bin/env python3
"""agefree_plan_html_v2 — as v1 (agefree_plan_html) but: EXACT full quotes, per-block number +
🔗 anchor, per-block FINAL-video timecode («в ролике»), and a full running-chrono KPI header.
Reuses PALETTE/COPY_JS/esc/alink/structure_block from agefree_plan_html."""
import sys, json, argparse, html
from pathlib import Path
sys.path.insert(0, "/Users/romansergeev/YTAI/scripts/999_extra")
import agefree_plan_html as G

esc = G.esc
PACE = 1.125  # финальный ролик ускорен на ~12.5% (канон серии +10–15%)

EXTRA_CSS = """
.bnum{font:700 11px 'Space Grotesk',monospace;color:var(--accent-ink);background:var(--accent);border-radius:6px;padding:2px 8px;margin-right:2px}
.blink{cursor:pointer;font-size:12px;opacity:.5;margin:0 6px 0 2px;user-select:none;vertical-align:middle}
.blink:hover{opacity:1}
.finat{font-family:ui-monospace,monospace;font-size:11.5px;font-weight:700;color:var(--accent);background:rgba(228,255,110,.09);border:1px solid var(--accent-2);border-radius:6px;padding:2px 9px;margin-left:auto;white-space:nowrap}
.finat::before{content:'▶ '}
.srcline{font-size:11px;color:var(--text-mute);margin:6px 0 2px}
.kpi{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0 6px}
.kpi .k{background:var(--bg-elev);border:1px solid var(--border);border-radius:10px;padding:9px 15px;min-width:96px}
.kpi .k b{font:700 20px 'Space Grotesk',sans-serif;color:var(--accent);display:block;line-height:1.1}
.kpi .k .ok{color:var(--green)} .kpi .k .am{color:var(--amber)}
.kpi .k span{font-size:11px;color:var(--text-mute)}
.chrono{background:var(--bg-2);border:1px solid var(--border-soft);border-radius:12px;padding:12px 16px;margin:6px 0 20px}
.chrono h3{font-size:12px;color:var(--text-mute);text-transform:uppercase;letter-spacing:.07em;margin-bottom:8px}
.chrono .row{display:flex;gap:10px;align-items:baseline;padding:3px 0;font-size:13.5px;border-top:1px solid var(--border-soft)}
.chrono .row:first-of-type{border-top:0}
.chrono .ft{font-family:ui-monospace,monospace;font-size:12px;font-weight:700;color:var(--accent);min-width:46px}
.chrono .rt{color:var(--text-dim)}
.beat{scroll-margin-top:80px}
"""

def mmss(x):
    x = max(0, int(round(x))); return f"{x//60}:{x%60:02d}"

def beat_html(b, bn, final_at):
    src = (f'<span class="bnum">#{bn}</span>{G.alink(f"b{bn}")}'
           f'<span class="tc">{esc(b.get("tc_in"))}–{esc(b.get("tc_out"))}</span>'
           f'<span class="file">{esc(b.get("source_file"))}</span>')
    if b.get("speaker"): src += f'<span class="spk">{esc(b["speaker"])}</span>'
    src += f'<span class="finat">{mmss(final_at)} в ролике</span>'
    why = f'<div class="why">{esc(b["why"])}</div>' if b.get("why") else ""
    return (f'<div class="beat" id="b{bn}"><div class="src">{src}</div>'
            f'<div class="q">{esc(b.get("quote"))}</div>{why}</div>')

def section_html(s, order, hook=False, aid=""):
    num = "HOOK · 0:00" if hook else f'СЕКЦИЯ {s.get("n","")}'
    idattr = f' id="{aid}"' if aid else ""
    head = (f'<div class="sec {"hook" if hook else ""}"{idattr}><div class="num">{esc(num)}</div>'
            f'<h2>{esc(s.get("heading") or s.get("angle"))}{(" " + G.alink(aid)) if aid else ""}</h2>')
    if s.get("goal"): head += f'<div class="goal">{esc(s["goal"])}</div>'
    head += "</div>"
    beats = "".join(beat_html(b, *order[id(b)]) for b in (s.get("beats") or []))
    broll = ""
    if s.get("broll"):
        broll = '<div class="broll">' + "".join(f'<span class="b">{esc(x)}</span>' for x in s["broll"]) + "</div>"
    return head + beats + broll

def render(plan, drive_url, tr_url, sources, folders_html=""):
    code = plan.get("code",""); title = plan.get("title","")
    page = f"/ytagefree/{code[-2:]}/"
    # ---- order + running chrono ----
    flat = []
    if plan.get("hook"): flat += [("HOOK", plan["hook"], b) for b in plan["hook"]["beats"]]
    for s in plan.get("sections", []):
        for b in s["beats"]: flat.append((f'СЕКЦИЯ {s["n"]}', s, b))
    if plan.get("cta"): flat += [("Призыв", plan["cta"], b) for b in plan["cta"]["beats"]]
    order = {}; running = 0.0; sec_start = {}
    for bn, (lab, sec, b) in enumerate(flat, 1):
        dur = b.get("dur_sec")
        if dur is None:
            try:
                def s2(t): p=str(t).split(':'); return int(p[0])*60+float(p[1])
                dur = max(0.0, s2(b["tc_out"]) - s2(b["tc_in"]))
            except: dur = 0.0
        final_at = running / PACE
        order[id(b)] = (bn, final_at)
        if lab not in sec_start: sec_start[lab] = final_at
        running += dur
    total_final = running / PACE
    total_raw = running
    # ---- KPI ----
    kpi = (f'<div class="kpi">'
           f'<div class="k"><b>{len(sources)}</b><span>клипов-исходников</span></div>'
           f'<div class="k"><b>{len(flat)}</b><span>блоков в ролике</span></div>'
           f'<div class="k"><b>{mmss(total_raw)}</b><span>отобрано сырья</span></div>'
           f'<div class="k"><b class="ok">≈{mmss(total_final)}</b><span>хроно ролика · темп +10–15%</span></div>'
           f'</div>')
    # ---- chrono map (sections → final start) ----
    rows = ""
    seen = []
    for lab, sec, b in flat:
        if lab in seen: continue
        seen.append(lab)
        head = sec.get("heading") or sec.get("angle") or lab
        rows += f'<div class="row"><span class="ft">{mmss(sec_start[lab])}</span><span class="rt">{esc(lab)} · {esc(head)}</span></div>'
    chrono = f'<div class="chrono"><h3>⏱ Хронокарта финального ролика (сквозной тайм-код)</h3>{rows}</div>'
    # ---- meta ----
    meta = []
    if plan.get("audience"): meta.append(f'<span class="m">👥 {esc(plan["audience"])}</span>')
    meta.append(f'<span class="m">⏱ ~{mmss(total_final)}</span>')
    meta.append(f'<span class="m">🎬 <b>{len(flat)}</b> блоков</span>')
    meta.append(f'<span class="m">📂 <b>{len(sources)}</b> исходников</span>')
    links = ['<a href="/ytagefree/">← хаб канала</a>', '<a href="/">← все каналы</a>']
    if tr_url: links.insert(0, f'<a href="{esc(tr_url)}" target="_blank">📝 Транскрипция (Drive)</a>')
    if drive_url: links.insert(0, f'<a href="{esc(drive_url)}" target="_blank">📁 Папка проекта (Drive)</a>')
    body = [f'<div class="lede"><h1>{esc(title)}</h1>',
            f'<div class="sub">{esc(code)} · план сборки · дословные полные цитаты + сквозной хроно</div>']
    if plan.get("logline"): body.append(f'<div class="promise">{esc(plan["logline"])}</div>')
    if plan.get("promise"): body.append(f'<p style="color:var(--text-dim)">{esc(plan["promise"])}</p>')
    if plan.get("alt_titles"):
        body.append('<div style="margin-top:8px;font-size:12.5px;color:var(--text-mute)">Альт. заголовки: ' +
                    " · ".join(esc(t) for t in plan["alt_titles"]) + "</div>")
    body.append('<div class="meta">' + "".join(meta) + "</div></div>")
    body.append(kpi); body.append(chrono)
    body.append(folders_html or G.structure_block(code, drive_url, tr_url, sources, None))
    if plan.get("hook"): body.append(section_html(plan["hook"], order, hook=True, aid="hook"))
    for i, s in enumerate(plan.get("sections", []), 1): body.append(section_html(s, order, aid=f"sec-{i}"))
    cta = plan.get("cta") or {}
    if cta.get("beats"):
        body.append(f'<div class="cta" id="cta"><h2>📣 Призыв {G.alink("cta")}</h2>')
        if cta.get("text"): body.append(f'<p style="color:var(--text-dim)">{esc(cta["text"])}</p>')
        body.append("".join(beat_html(b, *order[id(b)]) for b in cta["beats"]) + "</div>")
    if plan.get("editor_notes"):
        body.append('<div class="notes" id="notes"><h3>Заметки монтажёру ' + G.alink("notes") + '</h3><ul>' +
                    "".join(f'<li>{esc(n)}</li>' for n in plan["editor_notes"]) + "</ul></div>")
    body.append('<div class="srcfoot">Исходники (тайм-коды дословные, для поиска кусков): ' +
                " ".join(f'<code>{esc(s)}</code>' for s in sources) + "</div>")
    head = f'''<!DOCTYPE html><html lang="ru" data-channel="ytagefree" data-page="{page}" data-rya-theme="core" data-rya-haschrome="1"><head>
<link rel="icon" type="image/png" href="/favicon.png?v=1"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(code)} — план сборки</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style id="rya-nf">html.rya-gating body{{visibility:hidden}}.rya-overlay,.rya-chrome{{visibility:visible}}</style>
<script>document.documentElement.className+=" rya-gating";window.__ryaFailsafe=setTimeout(function(){{document.documentElement.classList.remove("rya-gating")}},3500);</script>
<link rel="stylesheet" href="/assets/site.css?v=14"><style>{G.PALETTE}{EXTRA_CSS}</style></head>
<body><div class="hdr"><span class="mark">RYA.AE</span><span class="ttl">{esc(code)} · {esc(title)} <span class="dim">план сборки</span></span><span class="links">{"".join(links)}</span></div>
<div class="crumbs"><a href="/">все каналы</a> › <a href="/ytagefree/">YTAgeFree</a> › <b>{esc(code)} план</b></div>
<div class="wrap">{"".join(body)}</div>{G.COPY_JS}
<script defer src="/assets/site.js?v=14"></script></body></html>'''
    return head

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--drive", default=""); ap.add_argument("--transcription", default="")
    ap.add_argument("--sources", default=""); ap.add_argument("--folders", default="")
    a = ap.parse_args()
    plan = json.load(open(a.plan))
    sources = [s.strip() for s in a.sources.split(",") if s.strip()]
    folders_html = open(a.folders).read() if a.folders and Path(a.folders).exists() else ""
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render(plan, a.drive, a.transcription, sources, folders_html), encoding="utf-8")
    print(f"wrote {out/'index.html'}")

if __name__ == "__main__":
    main()
