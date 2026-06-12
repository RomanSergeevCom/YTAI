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
TRELLO_HOME = "https://trello.com/u/romansergeevcom/boards"

TRELLO_ICO = ('<svg class="ico" viewBox="0 0 24 24" fill="currentColor" width="13" height="13">'
              '<rect x="2.5" y="2.5" width="19" height="19" rx="3.5" fill="none" '
              'stroke="currentColor" stroke-width="2"/>'
              '<rect x="6.5" y="6.5" width="4.5" height="11" rx="1"/>'
              '<rect x="13" y="6.5" width="4.5" height="7" rx="1"/></svg>')


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
    text = esc(f"{p.get('code') or ''} {p.get('title') or ''} {p.get('channel_id') or ''}".lower())
    inner = (
        f'<div class="row1"><span class="ch-id">{head}</span>'
        f'<span style="display:inline-flex;align-items:center;gap:5px">{due_badge(p)}'
        f'<span class="go" title="Открыть карточку в Trello">↗</span></span></div>'
        f'<div class="title">{title}</div>'
        f'<div class="meta-row" style="margin-top:8px">'
        f'<span style="font-size:10px;color:var(--text-mute)">{ch}</span></div>'
    )
    attrs = f'data-ch="{ch}" data-text="{text}" style="--c:{esc(color)}"'
    if url:
        return (f'<a class="card" {attrs} href="{esc(url)}" '
                f'target="_blank" rel="noopener">{inner}</a>')
    return f'<div class="card" {attrs}>{inner}</div>'


def main() -> int:
    ap = argparse.ArgumentParser(description="Render production cockpit from production.json")
    ap.add_argument("--repo", default=str(Path.home() / "RYA/yt-rya-ae"))
    args = ap.parse_args()
    repo = Path(args.repo).expanduser()
    feed = json.loads((repo / "web/_data/production.json").read_text(encoding="utf-8"))
    # clean URL since 2026-06-12: /production/ (старый /production.html — redirect-стаб)
    html_path = repo / "web/production/index.html"
    if not html_path.exists():          # first run after the move: seed from the legacy file
        legacy = repo / "web/production.html"
        if legacy.exists():
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
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
        klass = col.get("class") or "flight"
        body = "\n".join("            " + card_html(c) for c in cards) or \
            '            <div class="card" style="opacity:.4"><div class="title" style="color:var(--text-mute)">—</div></div>'
        cols_html.append(
            f'        <div class="col" data-klass="{esc(klass)}">\n'
            f'          <div class="{head_cls}"><span class="ttl">{esc(label)}</span>'
            f'<span class="cnt">{len(cards)}</span></div>\n'
            f'          <div class="col-body">\n{body}\n          </div>\n'
            f'        </div>'
        )

    # ---- channel filter pills — EVERY board gets a pill (even 0 in-flight),
    #      each carries a direct link to its Trello board ----
    board_links = feed.get("board_links") or []
    blmap = {b.get("code"): b for b in board_links}
    ch_counts: dict[str, dict] = {}
    for p in projects:
        c = ch_counts.setdefault(p["channel_id"], {"n": 0, "color": p.get("channel_color") or "#8A92A8"})
        if p.get("in_flight"):
            c["n"] += 1
    for b in board_links:
        ch_counts.setdefault(b.get("code"), {"n": 0, "color": b.get("color") or "#8A92A8"})
    pill_rows = []
    for k, v in sorted(ch_counts.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        link = blmap.get(k, {}).get("url")
        tr = (f'<a class="tr-link" href="{esc(link)}" target="_blank" rel="noopener" '
              f'title="Доска {esc(k)} в Trello">↗</a>') if link else ""
        pill_rows.append(
            f'        <span class="flt-pill active" data-ch="{esc(k)}">'
            f'<span class="dot" style="background:{esc(v["color"])}"></span>'
            f'{esc(k)} <span class="cnt">{v["n"]}</span>{tr}</span>')
    pills = ('        <span class="flt-pill active" data-ch="*" title="Показать все каналы">Все</span>\n'
             + "\n".join(pill_rows))
    n_booking = sum(1 for p in projects if p.get("stage_class") == "booking")
    n_service = sum(1 for p in projects if p.get("stage_class") == "service")

    # ---- drawer: Trello boards quick-links section ----
    if board_links:
        b_rows = "\n".join(
            f'        <a class="file-row" href="{esc(b.get("url") or "#")}" target="_blank" '
            f'rel="noopener" style="text-decoration:none">'
            f'<span class="ext" style="background:{esc(b.get("color") or "#8A92A8")};color:#0A0D16">{esc(b.get("code") or "")}</span>'
            f'<span class="name" style="font-size:11.5px">{esc(((b.get("name") or "").split("—", 1)[-1]).strip() or b.get("code") or "")}</span>'
            f'<span style="color:var(--text-mute);font-size:10px">Trello ↗</span></a>'
            for b in board_links)
        boards_section = (
            '    <div class="drw-section">\n'
            f'      <h4>Доски Trello — {len(board_links)} каналов '
            f'<a href="{TRELLO_HOME}" target="_blank" rel="noopener">все доски ↗</a></h4>\n'
            '      <div class="files-list">\n'
            f'{b_rows}\n'
            '      </div>\n'
            '    </div>\n'
        )
    else:
        boards_section = ""

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
            f'{boards_section}'
            '    <div class="drw-section">\n'
            '      <h4>Почему это здесь</h4>\n'
            '      <div class="kv">\n'
            '        <span class="k">Источник</span><span class="v">Trello (доска на канал)</span>\n'
            f'        <span class="k">Обновлено</span><span class="v">{esc(gen)} UTC</span>\n'
            '        <span class="k">Правило</span><span class="v">дни-в-стадии из даты переезда карточки</span>\n'
            '      </div>\n'
            '    </div>\n'
            '  </aside>\n'
        )
    else:
        drawer = ('  <aside class="drawer"><div class="drw-head"><h2>Нет застрявших 🎉</h2></div>\n'
                  f'{boards_section}  </aside>\n')

    # ---- assemble ----
    rest = f"""    <!-- UX ADD-ONS (generated) -->
    <style>
    .board-grid{{display:flex;gap:12px;min-width:max-content}}
    .board-grid .col{{flex:0 0 262px;width:262px}}
    .card .go{{font-size:10px;color:var(--text-mute);opacity:.55}}
    .card:hover .go{{color:var(--accent);opacity:1}}
    .flt-pill{{user-select:none}}
    .flt-pill.off{{opacity:.35}}
    .flt-pill .tr-link{{font-size:11px;color:var(--text-mute);margin-left:2px;padding:0 3px;border-radius:4px}}
    .flt-pill .tr-link:hover{{color:var(--accent-ink);background:var(--accent)}}
    .flt-pill.flt-toggle:not(.active){{opacity:.45}}
    @media(max-width:1100px){{.page{{grid-template-columns:1fr}}.drawer{{display:none}}}}
    </style>

    <!-- TOOLBAR (generated) -->
    <div class="toolbar">
      <div class="toolbar-left">
        <h1>Production board</h1>
        <span class="meta">{s.get('in_flight',0)} в работе · {s.get('stuck',0)} застряли &gt;{feed.get('stuck_days_threshold',14)}д · {esc(len(feed.get('boards',[])))} каналов · обновлено {esc(gen)} UTC</span>
      </div>
      <div class="toolbar-right" style="gap:8px">
        <a class="btn primary" href="{TRELLO_HOME}" target="_blank" rel="noopener">{TRELLO_ICO} Открыть Trello</a>
      </div>
    </div>

    <!-- FILTER BAR (generated) -->
    <div class="filter-bar">
      <div class="filters">
        <span class="flt-label">Канал</span>
{pills}
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-shrink:0">
        <span class="flt-pill flt-toggle" data-klass="booking" title="Показать/скрыть брони (пре-прод YTCR)">Бронь <span class="cnt">{n_booking}</span></span>
        <span class="flt-pill flt-toggle" data-klass="service" title="Показать/скрыть Архив">Архив <span class="cnt">{n_service}</span></span>
        <div class="search-mini">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
          <input placeholder="Найти эпизод / гостя…"/>
        </div>
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
        <span>Источник: <a href="{TRELLO_HOME}" target="_blank" rel="noopener" style="color:var(--text-dim);text-decoration:underline">Trello ↗</a></span>
        <span>Обновлено: {esc(gen)} UTC</span>
      </div>
    </div>

  </main>

{drawer}
</div>
<script>
(function () {{
  var cards = [].slice.call(document.querySelectorAll('.card[data-ch]'));
  var pills = [].slice.call(document.querySelectorAll('.flt-pill[data-ch]'));
  var cols  = [].slice.call(document.querySelectorAll('.col[data-klass]'));
  var off = {{}}, q = '';
  function apply() {{
    cards.forEach(function (c) {{
      var hide = off[c.getAttribute('data-ch')] ||
                 (q && c.getAttribute('data-text').indexOf(q) < 0);
      c.style.display = hide ? 'none' : '';
    }});
    cols.forEach(function (col) {{
      var vis = 0;
      [].slice.call(col.querySelectorAll('.card[data-ch]')).forEach(function (c) {{
        if (c.style.display !== 'none') vis++;
      }});
      var cnt = col.querySelector('.col-head .cnt');
      if (cnt) cnt.textContent = vis;
    }});
  }}
  pills.forEach(function (p) {{
    p.addEventListener('click', function (e) {{
      if (e.target.closest && e.target.closest('.tr-link')) return; // ↗ = открыть доску
      var ch = p.getAttribute('data-ch');
      if (ch === '*') {{
        off = {{}};
        pills.forEach(function (x) {{ x.classList.add('active'); x.classList.remove('off'); }});
      }} else {{
        off[ch] = !off[ch];
        p.classList.toggle('off', !!off[ch]);
        p.classList.toggle('active', !off[ch]);
      }}
      apply();
    }});
  }});
  var inp = document.querySelector('.search-mini input');
  if (inp) inp.addEventListener('input', function () {{
    q = inp.value.trim().toLowerCase(); apply();
  }});
  // Бронь / Архив — выключены по умолчанию, тогглы включают
  function setKlass(k, on) {{
    cols.forEach(function (col) {{
      if (col.getAttribute('data-klass') === k) col.style.display = on ? '' : 'none';
    }});
  }}
  [].slice.call(document.querySelectorAll('.flt-toggle')).forEach(function (t) {{
    var k = t.getAttribute('data-klass');
    setKlass(k, false);
    t.addEventListener('click', function () {{
      setKlass(k, t.classList.toggle('active'));
    }});
  }});
}})();
</script>
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
