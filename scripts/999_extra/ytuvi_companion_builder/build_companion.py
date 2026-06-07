#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ytuvi_companion_builder — per-video "Production Companion" pages for YTUVI.

For each episode that has a shooting script, builds a single self-contained HTML page
that Наталья Тузова (ген. директор UVI) reads ON SET while filming. Each page combines:
  1. The full VO script (3-col: № / текст озвучки / монтаж), readable.
  2. A fact-check + comment layer: per-claim verdicts (✅/⚠️/❌/🎭/❔), corrections,
     explanations, source links — produced by the multi-agent fact-check workflow.
  3. A cheat-sheet (что проверить · что не утверждать как факт · где нужна экспертиза).
  4. Glossary with pronunciation, and past sources (kickoff quotes).

Inputs  : /tmp/ytuvi_build/parsed/<NN>_blocks.json + /tmp/ytuvi_build/annotations/<NN>.json
Output  : <portal>/ytuvi/<NN>/index.html
Re-run  : after the fact-check workflow refreshes annotations, or scripts change.

Usage: python3 build_companion.py [--codes 01,02,03,04,05] [--out <portal_ytuvi_dir>]
"""
import json, html as _html, re, os, sys, argparse, datetime

BUILD = "/tmp/ytuvi_build"
OUT_BASE = "/Users/romansergeev/RYA/yt-rya-ae/web/ytuvi"

# ---- per-episode metadata (links, status) ----
META = {
    "01": {
        "stone": "Корунд · Рубин",
        "title": "Рубин",
        "hook": "Камень, который зашивали под кожу, из-за которого вводили санкции, и который теперь выращивают за две недели.",
        "script": "https://docs.google.com/document/d/1Z4t45g-MB9UJbwKoGbxjTTPkCrV67c1dhFyvU78aPWQ/edit",
        "trello": "https://trello.com/c/HjCu2qxN",
        "kickoff": ("Kickoff 2026-04-21 (общая встреча с экспертом)", None),
        "status": "script",
    },
    "02": {
        "stone": "Рубин · Сертификат и подделки",
        "title": "Рубин. Сертификат и подделки",
        "hook": "Как читать сертификат и бирку, сколько стоит карат и как не купить стекло вместо рубина.",
        "script": "https://docs.google.com/document/d/1cJOFviJ50Mc3JWI7ynzUWLJaDjw_u1CVz9tpnBKQFC4/edit",
        "trello": "https://trello.com/c/zD3i2nzt",
        "kickoff": ("Kickoff 2026-05-26 (Рубин · сертификат)", None),
        "status": "script",
    },
    "03": {
        "stone": "Корунд · Сапфир",
        "title": "Сапфир",
        "hook": "Тот же минерал, что рубин, но любого цвета — Кашмир, фэнси, падпараджа и почему месторождение решает цену.",
        "script": "https://docs.google.com/document/d/10RQLs61kBnSyN6P3N_PX8IUrrZ9yCrGF0ANzSpqFTDU/edit",
        "trello": "https://trello.com/c/XyFx5Aby",
        "kickoff": ("Kickoff 2026-05-26 (Сапфир · падпараджа)", None),
        "status": "script",
    },
    "04": {
        "stone": "Турмалин · Параиба",
        "title": "Турмалин Параиба",
        "hook": "Неоновый камень, ради которого геолог 15 лет копал холмы — и самый резкий рост цены в истории самоцветов.",
        "script": "https://docs.google.com/document/d/1dOnsoxbYmKfmLn57WtW60wJ_tLbnoS1L9fv0wcHeiNI/edit",
        "trello": "https://trello.com/c/oMxUHf9X",
        "kickoff": ("Zoom-kickoff 2026-05-29 · навигатор", "kickoff.html"),
        "status": "script",
    },
    "05": {
        "stone": "Шпинель (Махенге)",
        "title": "Шпинель",
        "hook": "Камень, который веками принимали за рубин — в том числе в Короне Российской империи.",
        "script": None,
        "trello": "https://trello.com/c/qCjpOeKB",
        "kickoff": ("Zoom-kickoff 2026-06-02 (записан, расшифровка в очереди)", None),
        "status": "prep",
    },
}

SPREADSHEET = "https://docs.google.com/spreadsheets/d/1yPVg3MvXglANpmigtmS_vOSDGOIwMGn7x1QQGEeXSo8/edit"

VERDICT = {
    "solid":      {"icon": "✅", "label": "проверено",        "c": "#4ADE80"},
    "check":      {"icon": "⚠️", "label": "уточнить",         "c": "#F59E0B"},
    "wrong":      {"icon": "❌", "label": "ошибка",           "c": "#F87171"},
    "metaphor":   {"icon": "🎭", "label": "метафора",         "c": "#C4B5FD"},
    "unverified": {"icon": "❔", "label": "не подтверждено",  "c": "#8294A6"},
}

# ---------- text cleanup ----------
def clean_inline(s):
    if not s:
        return ""
    s = s.replace("&#10;", "\n").replace("&nbsp;", " ").replace("\xa0", " ")
    # strip escaping the Google-export added: \*  \-  \!  \(  etc.
    s = re.sub(r"\\([\\\-!*()\[\]._])", r"\1", s)
    return s

def esc(s):
    return _html.escape(clean_inline(s), quote=True)

def rich(s):
    """clean -> escape -> **bold** -> newlines to <br>"""
    s = clean_inline(s)
    s = _html.escape(s, quote=True)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = s.replace("\n", "<br>")
    return s

# ---------- load ----------
def load(code):
    bp = os.path.join(BUILD, "parsed", f"{code}_blocks.json")
    ap = os.path.join(BUILD, "annotations", f"{code}.json")
    blocks = json.load(open(bp, encoding="utf-8")) if os.path.exists(bp) else None
    ann = json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {}
    return blocks, ann

# ---------- components ----------
def fc_card(fc):
    v = VERDICT.get(fc.get("verdict", "unverified"), VERDICT["unverified"])
    n = fc.get("_num")
    parts = [f'<div class="fc fc-{fc.get("verdict","unverified")}" id="fc-{n}">']
    parts.append(f'<div class="fc-h"><span class="fc-b" style="--vc:{v["c"]}">{v["icon"]} {v["label"]}</span>')
    conf = fc.get("confidence")
    if conf:
        parts.append(f'<span class="fc-conf">{esc({"high":"высокая","med":"средняя","low":"низкая"}.get(conf,conf))}</span>')
    # citable number + shareable deep-link (значок), right-aligned
    parts.append(f'<span class="fc-act" style="--vc:{v["c"]}"><a class="fc-num" href="#fc-{n}">FC&nbsp;{n}</a>'
                 f'<button class="fc-cp" data-cp="fc-{n}" title="скопировать ссылку на проверку">🔗</button></span>')
    parts.append("</div>")
    claim = fc.get("claim")
    if claim:
        parts.append(f'<div class="fc-claim">«{esc(claim)}»</div>')
    note = fc.get("note")
    if note:
        parts.append(f'<div class="fc-note">{rich(note)}</div>')
    corr = fc.get("correction")
    if corr:
        parts.append(f'<div class="fc-corr"><b>Как правильно:</b> {rich(corr)}</div>')
    srcs = [s for s in (fc.get("sources") or []) if s]
    if srcs:
        links = " · ".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(host(u))}</a>' for u in srcs[:5])
        parts.append(f'<div class="fc-src">источники: {links}</div>')
    parts.append("</div>")
    return "".join(parts)

def host(u):
    m = re.search(r"https?://([^/]+)", u or "")
    return (m.group(1).replace("www.", "") if m else u)[:34]

def render_block(b, fmap, mmap, emap):
    idx = b.get("idx")
    typ = b.get("type", "vo")
    fcs = fmap.get(idx, [])
    metas = mmap.get(idx, [])
    exps = emap.get(idx, [])
    flagged = bool(fcs or metas or exps)
    if typ == "chapter":
        ch = b.get("chapter") or b.get("vo") or b.get("visual") or ""
        return f'<h2 class="chap" id="ch{idx}">{esc(ch)}</h2>'
    if typ == "note":
        txt = b.get("vo") or b.get("visual") or ""
        return f'<div class="anote">✎ {rich(txt)}</div>'
    # vo block
    cls = "blk" + (" flagged" if flagged else "")
    out = [f'<div class="{cls}" data-fc="{1 if flagged else 0}" id="b{idx}">']
    num = b.get("n")
    dots = "".join(f'<i class="dot" style="background:{VERDICT.get(f.get("verdict","unverified"),VERDICT["unverified"])["c"]}"></i>' for f in fcs)
    out.append(f'<div class="gut"><span class="bn">{esc(num) if num else "·"}</span>{dots}</div>')
    out.append('<div class="bd">')
    vo = b.get("vo")
    if vo:
        out.append(f'<div class="vo">{rich(vo)}</div>')
    onscreen = [o for o in (b.get("onscreen") or []) if o]
    if onscreen:
        chips = "".join(f'<span class="osc">{esc(o)}</span>' for o in onscreen)
        out.append(f'<div class="os"><span class="osl">на экране</span>{chips}</div>')
    vis = b.get("visual")
    if vis and vis.strip():
        out.append(f'<details class="vis"><summary>🎬 монтаж / визуал</summary><div>{rich(vis)}</div></details>')
    for e in exps:
        out.append(f'<div class="exp">💎 <b>Экспертная вставка:</b> {rich(e.get("note",""))}</div>')
    for m in metas:
        out.append(f'<div class="meta-m">🎭 <b>Не утверждать как факт:</b> {rich(m.get("note") or m.get("text",""))}</div>')
    for f in fcs:
        out.append(fc_card(f))
    out.append("</div></div>")
    return "".join(out)

# severity order: red burning first
SEV_PRIMARY = ("wrong", "check", "unverified")   # shown expanded at top — "что проверять"
SEV_RANK = {"wrong": 0, "check": 1, "unverified": 2, "metaphor": 3, "solid": 4}

def fcp_row(f, compact=False):
    """One row in the top fact-check panel: number + verdict + claim (+ correction)."""
    n = f.get("_num")
    vk = f.get("verdict", "unverified")
    v = VERDICT.get(vk, VERDICT["unverified"])
    claim = f.get("claim") or f.get("note") or ""
    out = [f'<li class="fcp-row{" compact" if compact else ""}" data-v="{vk}" data-go="fc-{n}" style="--vc:{v["c"]}">']
    out.append(f'<span class="fcp-n">FC&nbsp;{n}</span>')
    out.append(f'<span class="fcp-ic" title="{esc(v["label"])}">{v["icon"]}</span>')
    out.append('<span class="fcp-tx">')
    out.append(f'<div class="fcp-claim">{esc(claim)}</div>')
    if not compact:
        corr = f.get("correction") or f.get("note")
        if corr:
            out.append(f'<div class="fcp-corr"><b>→ как правильно:</b> {rich(corr)}</div>')
    out.append('</span>')
    out.append(f'<span class="fcp-act"><button class="fcp-cp" data-cp="fc-{n}" '
               f'title="скопировать ссылку на проверку">🔗</button></span>')
    out.append('</li>')
    return "".join(out)

def render_fc_panel(fcs):
    """Top-of-page fact-check dashboard: errors + to-verify expanded (red on top),
    verified + metaphors collapsed. Every row numbered, deep-linkable, copy-able."""
    if not fcs:
        return ""
    cnt = {}
    for f in fcs:
        cnt[f.get("verdict")] = cnt.get(f.get("verdict"), 0) + 1
    primary = sorted((f for f in fcs if f.get("verdict") in SEV_PRIMARY),
                     key=lambda f: (SEV_RANK.get(f.get("verdict"), 9), f.get("_num") or 0))
    secondary = sorted((f for f in fcs if f.get("verdict") not in SEV_PRIMARY),
                       key=lambda f: f.get("_num") or 0)
    P = ['<section class="fcp" id="fcpanel">']
    P.append('<div class="fcp-h"><h2>🔍 Факт-чек — что проверить перед камерой</h2>')
    P.append('<div class="fcp-chips">')
    for k in ("wrong", "check", "metaphor", "solid", "unverified"):
        if cnt.get(k):
            P.append(f'<button class="fcp-chip" data-v="{k}" style="--vc:{VERDICT[k]["c"]}">'
                     f'<i class="d"></i>{VERDICT[k]["icon"]} {cnt[k]}</button>')
    P.append('</div>')
    P.append('<p class="fcp-sub">Клик по строке — перейти к месту в сценарии · '
             '🔗 — скопировать ссылку на конкретную проверку · чипы фильтруют список.</p>')
    P.append('</div>')
    P.append('<ul class="fcp-list">')
    for f in primary:
        P.append(fcp_row(f))
    P.append('</ul>')
    if secondary:
        ns = cnt.get("solid", 0)
        nm = cnt.get("metaphor", 0)
        lbl = " · ".join(x for x in (f'✅ проверено {ns}' if ns else '',
                                     f'🎭 метафоры {nm}' if nm else '') if x)
        P.append(f'<details class="fcp-more"><summary>{lbl} — показать</summary>'
                 '<ul class="fcp-list">')
        for f in secondary:
            P.append(fcp_row(f, compact=True))
        P.append('</ul></details>')
    P.append('</section>')
    return "".join(P)

def render_cheatsheet(ann):
    cs = ann.get("cheatsheet") or {}
    mc = cs.get("must_check") or []
    da = cs.get("dont_assert") or []
    ea = cs.get("expert_authority") or []
    if not (mc or da or ea):
        return ""
    cols = []
    if mc:
        items = "".join(f"<li>{rich(x)}</li>" for x in mc)
        cols.append(f'<div class="csc csc-check"><h4>⚠️ Проверить перед камерой</h4><ul>{items}</ul></div>')
    if da:
        items = "".join(f"<li>{rich(x)}</li>" for x in da)
        cols.append(f'<div class="csc csc-meta"><h4>🎭 Не говорить как факт</h4><ul>{items}</ul></div>')
    if ea:
        items = "".join(f"<li>{rich(x)}</li>" for x in ea)
        cols.append(f'<div class="csc csc-exp"><h4>💎 Где нужна экспертиза Натальи</h4><ul>{items}</ul></div>')
    total = len(mc) + len(da) + len(ea)
    grid = f'<div class="cheat">{"".join(cols)}</div>'
    # collapsed by default — the top fact-check panel now covers «проверить» / «не утверждать»
    return (f'<details class="sec-box"><summary>🧭 Шпаргалка ведущего ({total}) — '
            f'проверить · не утверждать как факт · где нужна экспертиза</summary>{grid}</details>')

def render_glossary(ann):
    g = ann.get("glossary") or []
    if not g:
        return ""
    rows = "".join(
        f'<tr><td class="gt">{esc(x.get("term",""))}</td><td class="gp">{esc(x.get("pron",""))}</td><td class="gm">{rich(x.get("meaning",""))}</td></tr>'
        for x in g
    )
    return (f'<details class="sec-box" open><summary>📖 Глоссарий и произношение ({len(g)})</summary>'
            f'<table class="gloss"><thead><tr><th>термин</th><th>произношение</th><th>что это</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></details>')

def render_sources(ann, meta):
    sm = ann.get("sources_map") or []
    if not sm:
        return ""
    rows = []
    for s in sm:
        who = s.get("who", "")
        tc = s.get("tc", "")
        topic = s.get("topic", "")
        q = s.get("quote", "")
        head = f'<span class="sm-t">{esc(topic)}</span>'
        if who:
            head += f'<span class="sm-w">{esc(who)}{(" · "+esc(tc)) if tc else ""}</span>'
        rows.append(f'<div class="sm"><div class="sm-h">{head}</div><blockquote>{rich(q)}</blockquote></div>')
    return (f'<details class="sec-box"><summary>🎙 Прошлые источники — что говорил эксперт на kickoff ({len(sm)})</summary>'
            f'<div class="smwrap">{"".join(rows)}</div></details>')

# ---------- page ----------
CSS = """
:root{--bg:#0A1420;--paper:#13283A;--ink:#F0F4F8;--muted:#8294A6;--line:#2A3A4E;--tcbg:#10222F;--accent:#22C7C7;--accent2:#8B7FF0;--bar:#0F1E2C;--shadow:0 10px 30px -16px rgba(0,0,0,.6);}
html[data-theme="light"]{--bg:#f6f4ef;--paper:#fffdf8;--ink:#1f1d1a;--muted:#7d7568;--line:#e6e0d4;--tcbg:#efe9dc;--accent:#2f6fb0;--accent2:#6b5fd0;--bar:#fffefb;--shadow:0 1px 3px rgba(0,0,0,.06);}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:17px;line-height:1.62;-webkit-font-smoothing:antialiased}
h1,h2,h3,h4{font-family:'Space Grotesk','Inter',sans-serif;margin:0;letter-spacing:-.01em}
a{color:var(--accent);text-decoration:none}
.wrap{max-width:920px;margin:0 auto;padding:0 20px 140px}
/* topbar */
.topbar{display:flex;align-items:center;gap:12px;padding:11px 20px;border-bottom:1px solid var(--line);background:var(--bar);position:sticky;top:0;z-index:50;backdrop-filter:blur(10px)}
.brand{font-family:'Space Grotesk';font-weight:700;color:var(--accent);font-size:16px}
.crumbs{font-size:13px;color:var(--muted)}.crumbs a{color:var(--muted)}.crumbs b{color:var(--ink)}
.tog{margin-left:auto;display:flex;gap:6px}
.tog button{border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:8px;padding:6px 11px;font-size:.8rem;cursor:pointer}
.tog button:hover{border-color:var(--accent)}
.tog button.on{background:var(--accent);color:#04222a;border-color:var(--accent);font-weight:600}
/* header */
header.doc{padding:30px 0 8px}
.chid{font-family:ui-monospace,Menlo,monospace;font-size:.72rem;letter-spacing:.16em;color:var(--accent);text-transform:uppercase}
h1{font-size:1.85rem;line-height:1.18;margin:7px 0 8px}
.hook{font-size:1.05rem;color:var(--ink);opacity:.92;font-style:italic;margin:.2rem 0 .7rem;max-width:760px}
.links{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 4px}
.links a{font-size:.83rem;color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:7px 12px;background:var(--paper)}
.links a:hover{border-color:var(--accent)}
.links a.primary{border-color:var(--accent);color:var(--accent)}
.stat{font-size:.84rem;color:var(--muted);margin:.6rem 0 0}
.stat b{color:var(--ink)}
/* sticky filter bar */
.bar{position:sticky;top:45px;z-index:40;background:var(--bar);border-bottom:1px solid var(--line);padding:9px 0;margin:14px 0 6px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.bar .lg{display:inline-flex;align-items:center;gap:5px;font-size:.78rem;color:var(--muted)}
.bar .lg i{width:10px;height:10px;border-radius:50%}
.bar .flt{margin-left:auto;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:999px;padding:6px 13px;font-size:.8rem;cursor:pointer}
.bar .flt.on{background:var(--accent);color:#04222a;border-color:var(--accent);font-weight:600}
/* cheat sheet */
.cheat{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:16px 0 6px}
.csc{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:13px 15px}
.csc h4{font-size:.82rem;text-transform:uppercase;letter-spacing:.04em;margin:0 0 8px}
.csc ul{margin:0;padding-left:18px}.csc li{margin:5px 0;font-size:.92rem}
.csc-check{border-left:3px solid #F59E0B}.csc-meta{border-left:3px solid #C4B5FD}.csc-exp{border-left:3px solid #22C7C7}
/* section boxes */
.sec-box{background:var(--paper);border:1px solid var(--line);border-radius:12px;margin:14px 0;padding:0 16px}
.sec-box>summary{cursor:pointer;font-family:'Space Grotesk';font-weight:600;padding:13px 0;list-style:none}
.sec-box>summary::-webkit-details-marker{display:none}
.sec-box>summary::before{content:"▸ ";color:var(--accent)}
.sec-box[open]>summary::before{content:"▾ "}
.sec-h{font-family:'Space Grotesk';font-size:.78rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:30px 0 6px}
/* glossary */
.gloss{width:100%;border-collapse:collapse;font-size:.9rem;margin:0 0 14px}
.gloss th{text-align:left;color:var(--muted);font-weight:600;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;padding:6px 8px;border-bottom:1px solid var(--line)}
.gloss td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
.gloss .gt{font-weight:600;white-space:nowrap}.gloss .gp{color:var(--accent);font-family:ui-monospace,Menlo,monospace;font-size:.82rem;white-space:nowrap}.gloss .gm{color:var(--muted)}
/* sources */
.smwrap{padding:0 0 12px}
.sm{border-left:3px solid var(--accent2);padding:2px 0 2px 13px;margin:11px 0}
.sm-h{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:2px}
.sm-t{font-weight:600;font-size:.9rem}.sm-w{font-size:.76rem;color:var(--muted)}
.sm blockquote{margin:2px 0;color:var(--ink);opacity:.9;font-size:.93rem}
/* script blocks */
.blk{display:flex;gap:14px;padding:16px 0;border-bottom:1px solid var(--line)}
.blk.flagged{background:linear-gradient(90deg,rgba(34,199,199,.05),transparent 60%);margin:0 -14px;padding:16px 14px;border-radius:8px}
.gut{flex:0 0 40px;display:flex;flex-direction:column;align-items:center;gap:4px;padding-top:3px}
.bn{font-family:'Space Grotesk';font-weight:700;color:var(--muted);font-size:.95rem}
.dot{width:9px;height:9px;border-radius:50%}
.bd{flex:1;min-width:0}
.vo{font-size:1.06rem;line-height:1.66}
.os{margin:8px 0 0;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.osl{font-size:.66rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.osc{font-size:.8rem;background:var(--tcbg);color:var(--accent);border-radius:6px;padding:3px 9px}
.vis{margin:9px 0 0}
.vis>summary{cursor:pointer;font-size:.78rem;color:var(--muted);list-style:none}
.vis>summary::-webkit-details-marker{display:none}
.vis>div{font-size:.86rem;color:var(--muted);background:var(--tcbg);border-radius:8px;padding:9px 12px;margin-top:6px;white-space:pre-line}
.chap{font-family:'Space Grotesk';font-size:1.18rem;color:var(--accent);margin:34px 0 6px;padding-top:14px;border-top:2px solid var(--line);scroll-margin-top:110px}
.anote{font-size:.88rem;color:var(--muted);background:var(--tcbg);border:1px dashed var(--line);border-radius:8px;padding:9px 13px;margin:12px 0}
/* fact-check cards */
.fc{border:1px solid var(--line);border-left:4px solid var(--vc,var(--muted));border-radius:9px;padding:10px 13px;margin:9px 0 0;background:var(--bg)}
.fc-solid{--vc:#4ADE80}.fc-check{--vc:#F59E0B}.fc-wrong{--vc:#F87171}.fc-metaphor{--vc:#C4B5FD}.fc-unverified{--vc:#8294A6}
.fc-h{display:flex;align-items:center;gap:9px;margin-bottom:4px}
.fc-b{font-size:.74rem;font-weight:700;color:var(--vc);text-transform:uppercase;letter-spacing:.03em}
.fc-conf{font-size:.7rem;color:var(--muted)}
.fc-claim{font-size:.9rem;color:var(--muted);font-style:italic;margin:2px 0 5px}
.fc-note{font-size:.94rem}
.fc-corr{font-size:.92rem;margin-top:5px;background:var(--tcbg);border-radius:7px;padding:7px 10px}
.fc-corr b{color:var(--accent)}
.fc-src{font-size:.76rem;color:var(--muted);margin-top:6px}
.exp{font-size:.93rem;background:rgba(34,199,199,.08);border-radius:8px;padding:8px 12px;margin:9px 0 0}
.meta-m{font-size:.93rem;background:rgba(196,181,253,.1);border-radius:8px;padding:8px 12px;margin:9px 0 0}
/* fact-check panel (top dashboard) */
.fcp{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:15px 16px;margin:16px 0 8px}
.fcp-h{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.fcp-h h2{font-family:'Space Grotesk';font-size:1.06rem}
.fcp-chips{display:flex;gap:6px;margin-left:auto;flex-wrap:wrap}
.fcp-chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:4px 11px;font-size:.78rem;cursor:pointer;font-family:inherit}
.fcp-chip .d{width:9px;height:9px;border-radius:50%;background:var(--vc)}
.fcp-chip:hover{border-color:var(--vc)}
.fcp-chip.off{opacity:.32;text-decoration:line-through}
.fcp-sub{flex-basis:100%;font-size:.78rem;color:var(--muted);margin:8px 0 2px}
.fcp-list{list-style:none;margin:10px 0 0;padding:0;display:flex;flex-direction:column;gap:6px}
.fcp-row{display:grid;grid-template-columns:auto auto 1fr auto;align-items:start;gap:10px;border:1px solid var(--line);border-left:4px solid var(--vc,var(--muted));border-radius:9px;padding:8px 11px;background:var(--bg);cursor:pointer;scroll-margin-top:120px}
.fcp-row:hover{border-color:var(--vc)}
.fcp-n{font-family:'Space Grotesk';font-weight:700;font-size:.74rem;color:var(--vc);background:var(--tcbg);border-radius:6px;padding:3px 7px;white-space:nowrap;align-self:start;line-height:1.4}
.fcp-ic{font-size:.96rem;line-height:1.5}
.fcp-tx{min-width:0}
.fcp-claim{font-size:.92rem;font-weight:600;line-height:1.45}
.fcp-corr{font-size:.85rem;color:var(--muted);margin-top:3px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.fcp-corr b{color:var(--vc);font-weight:600}
.fcp-row.compact .fcp-claim{font-weight:500;color:var(--muted)}
.fcp-act{align-self:start}
.fcp-cp,.fc-cp{border:none;background:transparent;color:var(--muted);cursor:pointer;font-size:.95rem;border-radius:6px;padding:3px 5px;line-height:1;font-family:inherit}
.fcp-cp:hover,.fc-cp:hover{background:var(--tcbg);color:var(--accent)}
.fcp-more{margin-top:9px}
.fcp-more>summary{cursor:pointer;font-size:.82rem;color:var(--muted);list-style:none}
.fcp-more>summary::-webkit-details-marker{display:none}
.fcp-more>summary::before{content:"▸ ";color:var(--accent)}
.fcp-more[open]>summary::before{content:"▾ "}
.fcp.hide-wrong .fcp-row[data-v="wrong"],.fcp.hide-check .fcp-row[data-v="check"],.fcp.hide-metaphor .fcp-row[data-v="metaphor"],.fcp.hide-solid .fcp-row[data-v="solid"],.fcp.hide-unverified .fcp-row[data-v="unverified"]{display:none}
/* fc card number + copy-link (значок) */
.fc{scroll-margin-top:120px}
.fc-act{margin-left:auto;display:flex;align-items:center;gap:4px}
.fc-num{font-family:'Space Grotesk';font-weight:700;font-size:.7rem;color:var(--vc);background:var(--tcbg);border-radius:6px;padding:3px 7px;text-decoration:none;white-space:nowrap}
.fc:target,.fcp-row:target{outline:2px solid var(--vc);outline-offset:3px}
.fc.flash,.fcp-row.flash{animation:fcflash 1.5s ease}
@keyframes fcflash{0%,28%{box-shadow:0 0 0 3px var(--vc) inset}100%{box-shadow:none}}
/* copy toast */
.fctoast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(18px);background:var(--accent);color:#04222a;font-weight:600;font-size:.85rem;padding:9px 16px;border-radius:10px;box-shadow:var(--shadow);opacity:0;pointer-events:none;transition:.24s;z-index:200}
.fctoast.on{opacity:1;transform:translateX(-50%) translateY(0)}
@media(max-width:600px){.fcp-corr{-webkit-line-clamp:3}}
body.only-fc .blk[data-fc="0"]{display:none}
body.only-fc .anote{display:none}
footer{max-width:920px;margin:0 auto;padding:24px 20px 70px;color:var(--muted);font-size:.78rem;border-top:1px solid var(--line)}
@media(max-width:600px){.blk{gap:9px}.gut{flex-basis:30px}.vo{font-size:1.01rem}}
"""

HEAD = """<!DOCTYPE html><html lang="ru" data-theme="dark"><head>
<link rel="icon" type="image/png" href="/favicon.png?v=1"><link rel="apple-touch-icon" href="/apple-touch-icon.png?v=1">
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>{css}</style></head><body>
<div class="topbar"><span class="brand">💎 yt.rya.ae</span>
<span class="crumbs"><a href="/">channels</a> / <a href="/ytuvi/">YTUVI</a> / <b>{code}</b></span>
<span class="tog"><button id="onlyfc">⚠️ только проверки</button><button id="theme">☀️ свет</button></span></div>
"""

SCRIPT_JS = """
<script>
(function(){
 var t=document.getElementById('theme');
 t.onclick=function(){var h=document.documentElement;var d=h.getAttribute('data-theme')==='dark';h.setAttribute('data-theme',d?'light':'dark');t.textContent=d?'🌙 тьма':'☀️ свет';t.classList.toggle('on',d);};
 var f=document.getElementById('onlyfc');var bar=document.getElementById('barfc');
 function tog(){document.body.classList.toggle('only-fc');var on=document.body.classList.contains('only-fc');f.classList.toggle('on',on);if(bar){bar.classList.toggle('on',on);}}
 f.onclick=tog; if(bar)bar.onclick=tog;
})();
// fact-check panel: jump · copy deep-link · flash · chip filter
(function(){
 var toast=document.createElement('div');toast.className='fctoast';document.body.appendChild(toast);var tt;
 function say(m){toast.textContent=m;toast.classList.add('on');clearTimeout(tt);tt=setTimeout(function(){toast.classList.remove('on');},1600);}
 function flash(el){if(!el)return;el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash');el.scrollIntoView({behavior:'smooth',block:'start'});}
 function fallback(txt){var t=document.createElement('textarea');t.value=txt;t.style.position='fixed';t.style.opacity=0;document.body.appendChild(t);t.focus();t.select();try{document.execCommand('copy');}catch(e){}document.body.removeChild(t);}
 function copyLink(id){var url=location.origin+location.pathname+'#'+id;function done(){if(history.replaceState)history.replaceState(null,'','#'+id);say('🔗 ссылка на '+id.toUpperCase().replace('-',' ')+' скопирована');}if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(url).then(done,function(){fallback(url);done();});}else{fallback(url);done();}}
 document.addEventListener('click',function(e){
  var cp=e.target.closest&&e.target.closest('[data-cp]');
  if(cp){e.preventDefault();e.stopPropagation();copyLink(cp.getAttribute('data-cp'));return;}
  var chip=e.target.closest&&e.target.closest('.fcp-chip[data-v]');
  if(chip){var p=document.getElementById('fcpanel');if(p){chip.classList.toggle('off');p.classList.toggle('hide-'+chip.getAttribute('data-v'));}return;}
  var row=e.target.closest&&e.target.closest('.fcp-row[data-go]');
  if(row){var id=row.getAttribute('data-go');flash(document.getElementById(id));if(history.replaceState)history.replaceState(null,'','#'+id);return;}
 });
 window.addEventListener('load',function(){if(/^#fc-\\d+$/.test(location.hash)){var el=document.querySelector(location.hash);if(el)setTimeout(function(){flash(el);},140);}});
})();
</script></body></html>
"""

def build_page(code):
    meta = META[code]
    blocks, ann = load(code)
    title = f"YTUVI{code} · {meta['title']} — съёмочный компаньон · yt.rya.ae"
    head = HEAD.format(title=esc(title), css=CSS, code=code)
    P = [head, '<div class="wrap">']
    # header
    doc_title = (blocks or {}).get("title") or meta["title"]
    P.append('<header class="doc">')
    P.append(f'<span class="chid">YTUVI · {code} · {esc(meta["stone"])}</span>')
    P.append(f'<h1>{esc(doc_title)}</h1>')
    P.append(f'<p class="hook">{esc(meta["hook"])}</p>')
    # links
    P.append('<div class="links">')
    if meta.get("script"):
        P.append(f'<a class="primary" href="{esc(meta["script"])}" target="_blank" rel="noopener">📝 Сценарий (Google Doc) ↗</a>')
    klabel, kurl = meta.get("kickoff", (None, None))
    if kurl:
        P.append(f'<a href="{esc(kurl)}">🎙 {esc(klabel)} ↗</a>')
    elif klabel:
        P.append(f'<span class="links" style="border:none;padding:0"><a style="opacity:.7;cursor:default" title="локальный транскрипт">🎙 {esc(klabel)}</a></span>')
    if meta.get("trello"):
        P.append(f'<a href="{esc(meta["trello"])}" target="_blank" rel="noopener">🗂 Trello ↗</a>')
    P.append(f'<a href="{esc(SPREADSHEET)}" target="_blank" rel="noopener">📊 ContentList ↗</a>')
    P.append('</div>')
    # stats
    s = ann.get("summary") or {}
    nb = len((blocks or {}).get("blocks") or [])
    fcs = ann.get("factchecks") or []
    if fcs:
        cnts = {}
        for f in fcs:
            cnts[f.get("verdict")] = cnts.get(f.get("verdict"), 0) + 1
        stat = " · ".join(f'{VERDICT[k]["icon"]} {cnts[k]} {VERDICT[k]["label"]}' for k in VERDICT if cnts.get(k))
        P.append(f'<p class="stat">Блоков: <b>{nb}</b> · фактов проверено: <b>{len(fcs)}</b> — {stat}</p>')
    else:
        P.append(f'<p class="stat">Блоков: <b>{nb}</b></p>')
    P.append('</header>')

    if meta["status"] == "prep" or not blocks:
        P.append(render_prep(code, meta))
        P.append('</div>')
        P.append(footer())
        P.append(SCRIPT_JS)
        return "".join(P)

    # number every fact-check in document order (shared by panel + inline cards)
    for i, f in enumerate(fcs):
        f["_num"] = i + 1

    # filter bar + legend
    P.append('<div class="bar">')
    for k in ("solid", "check", "wrong", "metaphor", "unverified"):
        P.append(f'<span class="lg"><i style="background:{VERDICT[k]["c"]}"></i>{VERDICT[k]["label"]}</span>')
    P.append('<button class="flt" id="barfc">показать только блоки с проверками</button>')
    P.append('</div>')

    # fact-check panel (top — red burning first, numbered, deep-linkable)
    P.append(render_fc_panel(fcs))

    # script — THE main content, directly under the fact-check panel
    P.append('<div class="sec-h">📜 Сценарий с факт-чеком и комментариями</div>')
    legend = (blocks or {}).get("legend")
    if legend:
        P.append(f'<div class="anote">{rich(legend)}</div>')
    fmap, mmap, emap = {}, {}, {}
    for f in fcs:
        fmap.setdefault(f.get("block_idx"), []).append(f)
    for m in (ann.get("metaphors") or []):
        mmap.setdefault(m.get("block_idx"), []).append(m)
    for e in (ann.get("expert_points") or []):
        emap.setdefault(e.get("block_idx"), []).append(e)
    for b in (blocks.get("blocks") or []):
        P.append(render_block(b, fmap, mmap, emap))

    # appendix — reference material AFTER the script (like end-of-video material):
    # glossary (kept open — Роман: «супер») · past kickoff sources · cheat-sheet (collapsed)
    appendix = "".join([render_glossary(ann), render_sources(ann, meta), render_cheatsheet(ann)])
    if appendix:
        P.append('<div class="sec-h">📎 Справочно — глоссарий, источники, шпаргалка</div>')
        P.append(appendix)

    P.append('</div>')  # wrap
    P.append(footer())
    P.append(SCRIPT_JS)
    return "".join(P)

def render_prep(code, meta):
    klabel, _ = meta.get("kickoff", ("", None))
    return (
        '<div class="sec-box" open style="padding:16px">'
        '<h3 style="margin:0 0 8px">⏳ Сценарий в работе</h3>'
        f'<p style="color:var(--muted);margin:.3rem 0 .8rem">Полный сценарий по теме «{esc(meta["title"])}» ещё не готов. '
        f'{esc(klabel)}. Страница-компаньон со скриптом, факт-чеком и источниками появится здесь, как только сценарист сдаст драфт.</p>'
        '<p style="color:var(--muted);margin:.3rem 0">Канальная формула выпуска: '
        '<b>Hook → Геология → Свойства → Месторождение → Облагораживание / синтетика → Рынок / аукционы → Сертификат → Вынос</b>.</p>'
        '</div>'
    )

def footer():
    today = datetime.date.today().isoformat()
    return (
        '<footer>yt.rya.ae · Command Center R.Y.A Media Lab FZE · '
        'страница-компаньон для съёмки: сценарий (Google Doc) + факт-чек (multi-agent, web-verified) + источники (Whisper-расшифровки kickoff). '
        f'Для съёмочной группы UVI — Наталья Тузова, ведущие Анастасия Атрашкевич и Юля. Собрано {today}.</footer>'
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="01,02,03,04,05")
    ap.add_argument("--out", default=OUT_BASE)
    a = ap.parse_args()
    for code in [c.strip() for c in a.codes.split(",") if c.strip()]:
        if code not in META:
            print(f"skip {code}: no META"); continue
        outdir = os.path.join(a.out, code)
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, "index.html")
        htmlout = build_page(code)
        with open(path, "w", encoding="utf-8") as f:
            f.write(htmlout)
        b, ann = load(code)
        nb = len((b or {}).get("blocks") or [])
        nf = len((ann or {}).get("factchecks") or [])
        print(f"✓ {code}: {path}  ({len(htmlout)//1024} KB · {nb} blocks · {nf} fact-checks)")

if __name__ == "__main__":
    main()
