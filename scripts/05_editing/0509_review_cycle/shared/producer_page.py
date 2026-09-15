#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""producer_page — страница продюсера (ноутбук): вердикт + стадии + ссылки + экраны и находки.

Расширяет stages/review_page.py (экраны кадрами по главам + находки аудита): review_page гоняется
как есть сабпроцессом (он пишет work/{cut}/review_page.html и thumbs/), а эта страница берёт его
стили и тело (лента глав, навигация, карточки экранов, фильтры) и ставит сверху блок продюсера:
  · «Вердикт продюсера» — work/{cut}/producer_summary.json, иначе авто по правкам/находкам:
    цифры, обязательные правки (с локальными кадрами), открытые решения, чувствительные, снятые;
  · таблица стадий из review_state.json (статус · хост · результат · когда);
  · ссылки на все поверхности (док-вкладки, лист, Drive, ревью-JSON, бриф для телефона, тикет).
Кадры — только локальные файлы (work/{cut}/thumbs, err_frames_annotated), без data-URI: страница
для ноутбука, открывается двойным щелчком из 05_Review/.

usage:
  YTAI_CARD=<…/05_Review/review_card.json> python3 producer_page.py [--out path] [--no-screens]
→ {REVIEW_DIR}/{CODE}_{cut}_review_producer.html
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / 'stages'))
sys.path.insert(0, str(ROOT))
from _bootstrap import P, W6, M, REVIEW_DIR, MOCK  # noqa: E402
from pravki_lib import (KIND_RU, CAT_RU, CAT_ICON, SEV_RANK, load_pravki, counts, verdict_lines,  # noqa: E402
                        load_summary, favicon_href, latest_review_json, sec_tc)

E = html.escape
FAVICON = '🎬'
STAGES_PY = ROOT / 'stages' / 'review_page.py'


def rel(path, base):
    """относительный href от папки страницы к файлу (локальные ссылки без file://)."""
    try:
        return os.path.relpath(str(path), str(base)).replace(os.sep, '/')
    except ValueError:
        return str(path)


# ── review_page.py: запуск и разбор ──────────────────────────────────────────
def run_review_page():
    """→ (style, body_rest, msg). body_rest — от ленты глав до </body> (без шапки review_page)."""
    if not STAGES_PY.exists():
        return '', '', 'review_page.py нет рядом — экраны не показаны'
    out = W6 / 'review_page.html'
    r = subprocess.run([sys.executable, str(STAGES_PY), '--out', str(out)], capture_output=True, text=True,
                       env=dict(os.environ, YTAI_CARD=str(P.CARD_PATH), PYTHONUNBUFFERED='1'))
    if r.returncode != 0 or not out.exists():
        return '', '', f'review_page.py не собрался (rc={r.returncode}): {(r.stderr or r.stdout)[-300:]}'
    src = out.read_text(encoding='utf-8')
    m = re.search(r'<style>(.*?)</style>', src, re.S)
    style = m.group(1) if m else ''
    i = src.find('<div class="timeline">')
    j = src.rfind('</body>')
    body = src[i:j] if i >= 0 and j > i else ''
    if not body:
        m2 = re.search(r'<body>(.*?)</body>', src, re.S)
        body = m2.group(1) if m2 else ''
    thumbs_rel = rel(out.parent / 'thumbs', OUT.parent)
    body = body.replace('src="thumbs/', f'src="{thumbs_rel}/')
    return style, body, (r.stdout or '').strip().splitlines()[-1] if r.stdout.strip() else 'review_page собран'


# ── блок продюсера ───────────────────────────────────────────────────────────
def stage_rows():
    """Таблица стадий из review_state.json (порядок — из review.py, если он импортируется)."""
    state_f = REVIEW_DIR / 'review_state.json'
    state = {}
    if state_f.exists():
        try:
            state = json.loads(state_f.read_text(encoding='utf-8'))
        except Exception:
            state = {}
    st = state.get('stages', {})
    order, desc, sym = [], {}, {}
    try:
        import review as RV  # noqa: WPS433 — только константы, main() под __name__
        order = [(n, h) for n, h, *_ in (RV.STAGES_MONTAGE if P.MODE == 'montage_tz' else RV.STAGES_CUT)]
        desc, sym = RV.STAGE_DESC, RV.SYM
    except Exception:
        pass
    names = [n for n, _ in order] + [n for n in st if n not in {n for n, _ in order}]
    # стадия chapters (главы по плану частей) пуста без card.chapters_plan — у такого фильма строку не показываем
    # НИКОГДА, даже если run записал в стейт «пропуск» (RU-страница продюсера YTUVI/YTCH/YTEVO не меняется)
    if not P.get('chapters_plan'):
        names = [n for n in names if n != 'chapters']
    hosts = dict(order)
    rows = []
    for n in names:
        s = st.get(n, {})
        status = s.get('status', 'todo')
        tool = desc.get(n, ('', ''))[0]
        rows.append(f'<tr class="st-{E(status)}"><td>{E(n)}</td><td>{E(s.get("host") or hosts.get(n, ""))}</td>'
                    f'<td>{E(sym.get(status, "·").strip())} {E(status)}</td>'
                    f'<td class="mut">{E(tool)}</td>'
                    f'<td>{E(str(s.get("msg") or ""))[:110]}</td>'
                    f'<td class="mut">{E(str(s.get("finished") or s.get("started") or ""))}</td></tr>')
    if not rows:
        return '', 'review_state.json нет — стадии ещё не запускались через review.py'
    note = (f'состояние обновлено {E(str(state.get("updated", "")))}' if state else
            'review_state.json нет — показан порядок стадий, все «todo»')
    return ('<div class="wrap-x"><table class="stages"><tr><th>стадия</th><th>хост</th><th>статус</th>'
            '<th>инструмент</th><th>результат</th><th>когда</th></tr>' + ''.join(rows) + '</table></div>'), note


def link_list(out_dir):
    L = []
    if P.DOC_ID:
        url = f'https://docs.google.com/document/d/{P.DOC_ID}/edit'
        L.append(f'📄 <a href="{url}">док сценария</a> — вкладки «{E(P.get("tab_title") or "")}»'
                 + (f', «{E(P.get("nav_tab"))}»' if P.get('nav_tab') else ''))
    sheet = P.SHEET_URL or (f'https://docs.google.com/spreadsheets/d/{P.get("notes_sheet_id")}/edit'
                            if P.get('notes_sheet_id') else '')
    if sheet:
        L.append(f'📋 <a href="{sheet}">лист ТЗ / заметок</a>')
    for key, label in (('materials_id', 'Drive · Review_materials'), ('project_folder_id', 'Drive · папка проекта'),
                       ('sprint_folder_id', 'Drive · спринт')):
        if P.get(key):
            L.append(f'📁 <a href="https://drive.google.com/drive/folders/{E(str(P.get(key)))}">{label}</a>')
    for f in sorted(REVIEW_DIR.glob(f'{P.CODE}_review_*.json')):
        L.append(f'🎬 <a href="{rel(f, out_dir)}">{E(f.name)}</a> — ревью-таймлайн (панель UXP → Review)')
    for name, label in ((f'{P.CODE}_{P.CUT_VERSION}_brief.html', '📱 бриф для телефона'),
                        ('REVIEW_STATE.md', '🎫 тикет REVIEW_STATE.md'),
                        (f'{P.CODE}_review_v6_summary.md', '📝 сводка ревью-таймлайна')):
        f = REVIEW_DIR / name
        if f.exists():
            L.append(f'{label}: <a href="{rel(f, out_dir)}">{E(name)}</a>')
    rp = W6 / 'review_page.html'
    if rp.exists():
        L.append(f'🖼 <a href="{rel(rp, out_dir)}">review_page.html</a> — только экраны и находки')
    return L


def must_cards(pravki, out_dir):
    act = [p for p in pravki if not p['_rejected']]
    must = sorted([p for p in act if p['_must']], key=lambda p: (SEV_RANK.get(p['severity'], 9), p['_sec']))
    o = []
    for p in must:
        img = ''
        f = p['_frame']
        if f is None and p['_screen'] and (W6 / 'thumbs' / f'{p["_screen"]}.jpg').exists():
            f = W6 / 'thumbs' / f'{p["_screen"]}.jpg'
        if f is not None and f.exists():
            img = f'<a href="{rel(f, out_dir)}"><img loading="lazy" src="{rel(f, out_dir)}" alt="{E(p["num"])}"></a>'
        do = ''.join(f'<li>{E(x)}</li>' for x in p['_do'][:6])
        o.append(f'<div class="pcard"><div class="pimg">{img}</div><div>'
                 f'<div class="ptop"><b class="pnum">{E(p["num"])}</b><span class="ptc">{E(sec_tc(p["_sec"]))}</span>'
                 f'<span class="pcls c-{E(p["class"] or "other")}">{E(KIND_RU.get(p["class"] or "other", p["class"]))}</span>'
                 + (f'<span class="psev s-{E(p["severity"])}">{E(p["severity"])}</span>' if p['severity'] else '')
                 + ('<span class="pcls">⚠️ чувствительное</span>' if p['_sensitive'] else '')
                 + f'</div><div class="ptitle">{E(p["_title"])}</div>'
                 + (f'<ul class="pdo">{do}</ul>' if do else '<div class="mut">текст ТЗ — в доке</div>')
                 + '</div></div>')
    return must, ''.join(o)


def producer_block(pravki, out_dir):
    summary = load_summary(W6)
    c = counts(pravki)
    dur = P.get('duration_sec')
    vl = verdict_lines(pravki, float(dur) if dur else None, summary)
    act = [p for p in pravki if not p['_rejected']]
    dec = [p for p in act if str(p.get('decision') or '').strip()]
    cut = [p for p in act if p.get('category') == 'cut']
    rej = [p for p in pravki if p['_rejected']]
    must, cards = must_cards(pravki, out_dir)
    o = ['<section class="producer" id="producer"><h2>Вердикт продюсера</h2>']
    if summary and (summary.get('verdict_short') or summary.get('headline')):
        o.append(f'<p class="vshort"><b>{E(summary.get("verdict_short") or summary.get("headline"))}</b>'
                 + (f'<br>{E(summary["verdict"])}' if summary.get('verdict') else '') + '</p>')
    o.append('<ul class="vlines">' + ''.join(f'<li>{E(x)}</li>' for x in vl) + '</ul>')
    stat = [('ТЗ в работе', c['n_active']), ('обязательных', c['n_must']), ('решений', c['n_decisions']),
            ('вырезать', c['n_cut']), ('⚠️ чувствительных', c['n_sensitive']), ('снято Романом', c['n_rejected'])]
    o.append('<div class="pstats">' + ''.join(f'<div><b>{v}</b><span>{E(k)}</span></div>' for k, v in stat) + '</div>')
    if summary and summary.get('strengths'):
        o.append('<h3>Что работает</h3><ul class="vlines">' + ''.join(f'<li>{E(str(x))}</li>' for x in summary['strengths']) + '</ul>')
    o.append(f'<h3>Обязательные правки <small>{len(must)}</small></h3>')
    o.append(cards or '<p class="mut">обязательных правок нет</p>')
    if cut:
        o.append(f'<h3>Убрать / вырезать <small>{len(cut)}</small></h3><ul class="vlines">' + ''.join(
            f'<li><b>{E(p["num"])}</b> · {E(p.get("tc_range") or sec_tc(p["_sec"]))} · {E(p["_title"])}'
            + (f' — {E(p["_do"][0])}' if p['_do'] else '') + '</li>' for p in cut) + '</ul>')
    o.append(f'<h3>Открытые решения <small>{len(dec) + len((summary or {}).get("decisions") or [])}</small></h3>')
    items = [f'<li>{E(str(d))}</li>' for d in ((summary or {}).get('decisions') or [])]
    items += [f'<li><b>{E(p["num"])}</b> · {E(sec_tc(p["_sec"]))} · {E(p["_title"])} — ❓ {E(str(p["decision"]).strip())}</li>'
              for p in dec]
    o.append('<ul class="vlines">' + ''.join(items) + '</ul>' if items else '<p class="mut">открытых вопросов нет</p>')
    if rej:
        o.append(f'<h3>Снято Романом <small>{len(rej)}</small></h3><p class="mut">' +
                 ' · '.join(f'{E(p["num"])} {E(p["_title"][:40])}' for p in rej) + '</p>')
    o.append('<h3>Все ТЗ</h3><div class="wrap-x"><table class="tz"><tr><th>№</th><th>tc</th><th>заголовок</th>'
             '<th>класс</th><th>категория</th><th>severity</th><th>сделать</th></tr>')
    for p in act:
        o.append(f'<tr class="{"must" if p["_must"] else ""}"><td>{E(p["num"])}</td><td>{E(sec_tc(p["_sec"]))}</td>'
                 f'<td>{"⚠️ " if p["_sensitive"] else ""}{E(p["_title"])}</td><td>{E(KIND_RU.get(p["class"] or "other", p["class"]))}</td>'
                 f'<td>{E(CAT_ICON.get(p.get("category"), ""))} {E(CAT_RU.get(p.get("category"), p.get("category") or ""))}</td>'
                 f'<td>{E(p["severity"])}</td><td class="mut">{E(p["_do"][0][:140]) if p["_do"] else ""}</td></tr>')
    o.append('</table></div>')
    table, note = stage_rows()
    o.append(f'<h2>Стадии</h2><p class="mut">{note}</p>{table}')
    o.append('<h2>Поверхности</h2><ul class="vlines links">' + ''.join(f'<li>{x}</li>' for x in link_list(out_dir)) + '</ul>')
    o.append('</section>')
    return ''.join(o), {'must': len(must), 'decide': len(dec), 'cut': len(cut), 'rejected': len(rej), 'all': len(act)}


EXTRA_CSS = """
.producer { padding:24px 32px 8px; border-bottom:1px solid var(--line) }
.producer h2 { margin:18px 0 10px; font-size:21px }
.producer h3 { margin:22px 0 8px; font-size:16px } .producer h3 small { color:var(--mut); font-weight:400 }
.vshort { font-size:17px; background:var(--panel); border-left:4px solid var(--red); padding:12px 14px; border-radius:6px; margin:0 0 10px }
.vlines { margin:0 0 8px; padding-left:20px } .vlines li { margin:3px 0 }
.pstats { display:flex; gap:22px; flex-wrap:wrap; margin:12px 0 4px }
.pstats div b { display:block; font-size:22px; line-height:1.1 } .pstats div span { color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.05em }
.pcard { display:grid; grid-template-columns:360px 1fr; gap:14px; background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:10px 0 }
.pimg img { width:360px; border-radius:4px; display:block; background:#000 }
.ptop { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:4px }
.pnum { color:var(--red) } .ptc { font-variant-numeric:tabular-nums; color:var(--mut) }
.pcls { font-size:11.5px; font-weight:700; border-radius:6px; padding:1px 7px; background:rgba(217,165,33,.16); color:var(--amber) }
.pcls.c-fact, .pcls.c-typo, .pcls.c-mismatch { background:rgba(226,86,74,.2); color:#F09A9E }
.psev { font-size:11px; border:1px solid currentColor; border-radius:999px; padding:0 7px; color:var(--mut) } .psev.s-high { color:var(--red) }
.ptitle { font-weight:700; font-size:15.5px; margin:4px 0 6px }
.pdo { margin:0; padding-left:18px; font-size:14px } .pdo li { margin:3px 0 }
.wrap-x { overflow-x:auto }
table.stages, table.tz { border-collapse:collapse; width:100%; font-size:13.5px }
table.stages td, table.stages th, table.tz td, table.tz th { border-bottom:1px solid var(--line); padding:5px 8px; text-align:left; vertical-align:top }
table.stages th, table.tz th { color:var(--mut); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.05em }
tr.st-done td:nth-child(3) { color:#8BD48A } tr.st-failed td:nth-child(3) { color:var(--red) } tr.st-warn td:nth-child(3) { color:var(--amber) }
table.tz tr.must td:first-child { color:var(--red); font-weight:700 }
.mut { color:var(--mut) }
.links a { color:#9FC4FF; text-decoration:underline; text-decoration-color:var(--line) }
.ptop-note { color:var(--mut); font-size:13px }
@media (max-width:800px) { .pcard { grid-template-columns:1fr } .pimg img { width:100% } .producer { padding:16px } }
"""

FALLBACK_CSS = """
:root { --bg:#0E1014; --panel:#151922; --line:#232A36; --ink:#E8EAEF; --mut:#9AA3B2; --red:#E2564A; --amber:#D9A521 }
* { box-sizing:border-box } body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",Helvetica,Arial,sans-serif }
a { color:inherit; text-decoration:none } header { padding:28px 32px 16px; border-bottom:1px solid var(--line) }
h1 { margin:0 0 6px; font-size:26px } .sub { color:var(--mut); font-size:14px } footer { padding:28px 32px 60px; color:var(--mut); font-size:13px }
"""


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=str(REVIEW_DIR / f'{P.CODE}_{P.CUT_VERSION}_review_producer.html'))
    ap.add_argument('--no-screens', action='store_true', help='не гонять review_page.py (без экранов и находок)')
    a = ap.parse_args()
    OUT = Path(a.out)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    pravki, src = load_pravki(P, W6, M, MOCK)
    style, body_rest, msg = ('', '', 'экраны пропущены (--no-screens)') if a.no_screens else run_review_page()
    block, stats = producer_block(pravki, OUT.parent)
    dur = P.get('duration_sec')
    page = f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(P.CODE)} {E(P.CUT_VERSION)} · продюсер</title>
<link rel="icon" href="{favicon_href(FAVICON)}">
<style>{style or FALLBACK_CSS}{EXTRA_CSS}</style></head><body>
<header>
  <h1>{E(P.CODE)} · {E(P.FILM or P.PROJECT_NAME)}</h1>
  <div class="sub">Страница продюсера · кат {E(P.CUT_VERSION)}{(' · ' + E(sec_tc(dur))) if dur else ''} · {E(P.CHANNEL)} ·
  собрано {datetime.now().strftime('%d.%m.%Y %H:%M')} · правки: {E(src.name)}</div>
  <div class="ptop-note">{E(msg)}</div>
</header>
{block}
{body_rest}
</body></html>'''
    OUT.write_text(page, encoding='utf-8')
    print(f'→ {OUT}  ({OUT.stat().st_size // 1024} КБ) · обязательных {stats["must"]} · решений {stats["decide"]} · '
          f'вырезать {stats["cut"]} · ТЗ {stats["all"]} (снято {stats["rejected"]}) · {msg}')
    return 0


OUT = REVIEW_DIR / f'{P.CODE}_{P.CUT_VERSION}_review_producer.html'

if __name__ == '__main__':
    sys.exit(main())
