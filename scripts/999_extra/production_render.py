#!/usr/bin/env python3
"""
production_render.py — static-fill the yt.rya.ae/production cockpit from production.json.

Keeps the existing /production.html design 100% intact (head, CSS, rya-site-v1 chrome,
topbar) and regenerates ONLY the data regions: toolbar stats, channel filter pills, the
kanban board (columns = real Trello stages), footer stats, and the drawer (turned into a
"🔴 добей в первую очередь" top-stuck action list).

Re-runnable (cron-safe): splits the live HTML at the stable `<!-- TOOLBAR -->` anchor,
keeps everything before it verbatim, regenerates everything after. Static output — works
without a server (matches portal rule), freshness comes from re-running on a schedule.

Usage:
    python3 production_render.py                      # default repo ~/RYA/yt-rya-ae
    python3 production_render.py --repo /path/to/portal

Pairs with production_trello.py (which produces production.json). Paired doc in README.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

ANCHOR = '<main class="main">'   # stable: lives in preserved prefix, never regenerated
CODE_RE = re.compile(r"^(YT[A-Z]{2,4}\d+)[_ ]+")


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def due_badge(p) -> str:
    d = p.get("days_since_update")
    if d is None:
        return '<span class="due">—</span>'
    cls = "due crit" if p.get("stuck") else ("due warn" if d >= 7 else "due")
    return f'<span class="{cls}">{d}д</span>'


def clean_title(p) -> str:
    t = p.get("title", "") or ""
    code = p.get("code")
    if code:
        t = CODE_RE.sub("", t)            # strip leading "YTCR05_" / "YTCG 26 " prefix
    return t.strip() or (p.get("title") or "—")


def card_html(p) -> str:
    color = p.get("channel_color") or "#8A92A8"
    head = esc(p.get("code") or p.get("channel_id") or "")
    url = p.get("url")
    title = esc(clean_title(p))
    ch = esc(p.get("channel_id") or "")
    inner = (
        f'<div class="row1"><span class="ch-id">{head}</span>{due_badge(p)}</div>'
        f'<div class="title">{title}</div>'
        f'<div class="meta-row" style="margin-top:8px">'
        f'<span style="font-size:10px;color:var(--text-mute)">{ch}</span></div>'
    )
    if url:
        return (f'<a class="card" style="--c:{esc(color)}" href="{esc(url)}" '
                f'target="_blank" rel="noopener">{inner}</a>')
    return f'<div class="card" style="--c:{esc(color)}">{inner}</div>'


def main() -> int:
    ap = argparse.ArgumentParser(description="Render production cockpit from production.json")
    ap.add_argument("--repo", default=str(Path.home() / "RYA/yt-rya-ae"))
    args = ap.parse_args()
    repo = Path(args.repo).expanduser()
    feed = json.loads((repo / "web/_data/production.json").read_text(encoding="utf-8"))
    html_path = repo / "web/production.html"
    original = html_path.read_text(encoding="utf-8")
    if ANCHOR not in original:
        raise SystemExit(f"anchor {ANCHOR!r} not found in {html_path} — aborting (won't clobber)")
    prefix = original.split(ANCHOR, 1)[0] + ANCHOR + "\n"
    # asset version: follow the chrome in the preserved head (patch_site_chrome bumps it)
    m_v = re.search(r"site\.css\?v=(\d+)", prefix)
    asset_v = m_v.group(1) if m_v else "8"

    projects = feed.get("projects", [])
    s = feed.get("summary", {})
    gen = (feed.get("generated") or "")[:16].replace("T", " ")

    # ---- columns: group in-flight + done by stage, ordered by stage_order ----
    stages: dict[tuple, dict] = {}
    for p in projects:
        if p.get("stage_class") in ("service",) and False:
            continue
        key = (p.get("stage_order", 0), p.get("stage_label", p.get("list", "?")))
        stages.setdefault(key, {"cards": [], "class": p.get("stage_class")})
        stages[key]["cards"].append(p)
    cols_html = []
    for (order, label), col in sorted(stages.items()):
        cards = sorted(col["cards"], key=lambda p: (p.get("days_since_update") or -1), reverse=True)
        n_stuck = sum(1 for c in cards if c.get("stuck"))
        head_cls = "col-head crit" if n_stuck else "col-head"
        body = "\n".join("            " + card_html(c) for c in cards) or \
            '            <div class="card" style="opacity:.4"><div class="title" style="color:var(--text-mute)">—</div></div>'
        cols_html.append(
            f'        <div class="col">\n'
            f'          <div class="{head_cls}"><span class="ttl">{esc(label)}</span>'
            f'<span class="cnt">{len(cards)}</span></div>\n'
            f'          <div class="col-body">\n{body}\n          </div>\n'
            f'        </div>'
        )

    # ---- channel filter pills (in-flight counts) ----
    ch_counts: dict[str, dict] = {}
    for p in projects:
        if not p.get("in_flight"):
            continue
        c = ch_counts.setdefault(p["channel_id"], {"n": 0, "color": p.get("channel_color") or "#8A92A8"})
        c["n"] += 1
    pills = "\n".join(
        f'        <span class="flt-pill active"><span class="dot" style="background:{esc(v["color"])}"></span>'
        f'{esc(k)} <span class="cnt">{v["n"]}</span></span>'
        for k, v in sorted(ch_counts.items(), key=lambda kv: -kv[1]["n"]))

    # ---- drawer: top-stuck action list ----
    stuck = sorted([p for p in projects if p.get("stuck")],
                   key=lambda p: (p.get("days_since_update") or 0), reverse=True)[:12]
    if stuck:
        rows = "\n".join(
            f'        <a class="file-row" href="{esc(p.get("url") or "#")}" target="_blank" rel="noopener" '
            f'style="text-decoration:none">'
            f'<span class="ext" style="background:{esc(p.get("channel_color") or "#8A92A8")};color:#0A0D16">'
            f'{esc((p.get("days_since_update") or 0))}д</span>'
            f'<span class="name">{esc(p.get("code") or "")} · {esc(clean_title(p))}</span>'
            f'<span style="color:var(--text-mute);font-size:10.5px">{esc(p.get("stage_label") or p.get("list"))}</span>'
            f'</a>'
            for p in stuck)
        drawer = (
            '  <aside class="drawer">\n'
            '    <div class="drw-head">\n'
            '      <div class="breadcrumb"><b>Анти-drag</b> › добей в первую очередь</div>\n'
            f'      <h2>🔴 Дольше всех висят — {len(stuck)} из {s.get("stuck", 0)}</h2>\n'
            '      <div class="meta-row">\n'
            f'        <span class="chip stage">● {s.get("in_flight", 0)} в работе</span>\n'
            f'        <span class="chip due-warn">⏱ {s.get("stuck", 0)} застряли &gt;{feed.get("stuck_days_threshold", 14)}д</span>\n'
            '      </div>\n'
            '    </div>\n'
            '    <div class="drw-section">\n'
            '      <h4>Завершить = реализовать выручку</h4>\n'
            '      <div class="files-list">\n'
            f'{rows}\n'
            '      </div>\n'
            '    </div>\n'
            '    <div class="drw-section">\n'
            '      <h4>Почему это здесь</h4>\n'
            '      <div class="kv">\n'
            '        <span class="k">Источник</span><span class="v">Trello (доска на канал)</span>\n'
            f'        <span class="k">Каналы</span><span class="v">{esc(", ".join(feed.get("boards", [])))}</span>\n'
            f'        <span class="k">Обновлено</span><span class="v">{esc(gen)}</span>\n'
            '        <span class="k">Правило</span><span class="v">дни-в-стадии из даты переезда карточки</span>\n'
            '      </div>\n'
            '    </div>\n'
            '  </aside>\n'
        )
    else:
        drawer = '  <aside class="drawer"><div class="drw-head"><h2>Нет застрявших 🎉</h2></div></aside>\n'

    # ---- assemble ----
    rest = f"""    <!-- TOOLBAR (generated) -->
    <div class="toolbar">
      <div class="toolbar-left">
        <h1>Production board</h1>
        <span class="meta">{s.get('in_flight',0)} в работе · {s.get('stuck',0)} застряли &gt;{feed.get('stuck_days_threshold',14)}д · из Trello · обновлено {esc(gen)}</span>
      </div>
    </div>

    <!-- FILTER BAR (generated) -->
    <div class="filter-bar">
      <div class="filters">
        <span class="flt-label">Канал</span>
{pills}
      </div>
      <div class="search-mini">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
        <input placeholder="Найти эпизод / гостя…"/>
      </div>
    </div>

    <!-- KANBAN BOARD (generated) -->
    <div class="board">
      <div class="board-grid">

{chr(10).join(cols_html)}

      </div>
    </div>

    <!-- FOOTER STATS (generated) -->
    <div class="foot-stats">
      <div class="group">
        <span class="pill"><b style="color:var(--accent)">{s.get('in_flight',0)}</b> в работе</span>
        <span class="pill"><b style="color:#FCA5A5">{s.get('stuck',0)}</b> застряли</span>
        <span class="pill"><b>{s.get('done',0)}</b> опубликовано</span>
        <span class="pill">{esc(len(feed.get('boards',[])))} каналов</span>
      </div>
      <div class="group" style="color:var(--text-mute);font-size:11px">
        <span>Источник: Trello</span>
        <span>Обновлено: {esc(gen)}</span>
      </div>
    </div>

  </main>

{drawer}
</div>
<script src="/assets/site.js?v={asset_v}" defer></script>
</body>
</html>
"""
    html_path.write_text(prefix + rest, encoding="utf-8")
    print(f"rendered → {html_path}")
    print(f"  {len(stages)} stage columns · {s.get('in_flight',0)} in-flight · {s.get('stuck',0)} stuck · {len(feed.get('boards',[]))} channels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
