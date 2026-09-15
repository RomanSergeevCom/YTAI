#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Наглядная HTML-страница ревью ката: экраны кадрами по главам + находки аудита.

Зачем: до вкладки в доке (она для монтажёра и пишет наружу) Роману нужно ГЛАЗАМИ увидеть,
что нашли модели и агенты. Страница самодостаточна: кадры лежат рядом в thumbs/,
открывается двойным щелчком, работает без сети.

Источники (всё из рабочей копии): prep_config.json · screens_v6.json · vlm_v6.jsonl ·
llm_v6.json · words.json · audit_findings_v6.json (если аудит уже прошёл).

usage: python3 review_page.py [--out review_page.html] [--thumb-width 900]
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--out', default=str(W6 / 'review_page.html'))
ap.add_argument('--thumb-width', type=int, default=900)
a = ap.parse_args()

OUT = Path(a.out)
THUMBS = OUT.parent / 'thumbs'
THUMBS.mkdir(exist_ok=True)
HIRES = W6 / 'hires'

# ── данные ────────────────────────────────────────────────────────────────
screens = json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))
vlm = {}
if (W6 / 'vlm_v6.jsonl').exists():
    for ln in open(W6 / 'vlm_v6.jsonl', encoding='utf-8'):
        try:
            r = json.loads(ln)
            vlm[r['id']] = r
        except Exception:
            pass
llm = {}
if (W6 / 'llm_v6.json').exists():
    for r in json.load(open(W6 / 'llm_v6.json', encoding='utf-8')):
        llm[r['id']] = r

findings, unverified = [], []
af = W6 / 'audit_findings_v6.json'
if af.exists():
    data = json.load(open(af, encoding='utf-8'))
    findings = [f for f in data.get('confirmed', []) if f.get('confirmed', True)]
    # находка без голосов — не «опровергнута», а недопроверена (линзы упали). Показываем её
    # отдельной пометкой: страница не должна выглядеть чистой там, где проверка не доехала.
    unverified = [f for f in data.get('findings', []) if f.get('status') == 'unverified']

words = []
wp = Path(P.WORDS)
if wp.exists():
    for s in json.load(open(wp, encoding='utf-8'))['segments']:
        for w in s.get('words') or []:
            words.append((w['w'], float(w['s'])))

DUR = P.duration_sec()
CH_NAME = P.get('ch_name', {})
CH_ACCENT = ['#3FA34D', '#2FB4C7', '#E08A2E', '#C74FA5', '#3F6FC7', '#D9A521']
CH = [(int(t), n) for t, n in P.CHAPTERS]
CH_COL = {n: CH_ACCENT[i % len(CH_ACCENT)] for i, (t, n) in enumerate(CH)}
CH_END = {n: (CH[i + 1][0] if i + 1 < len(CH) else int(DUR)) for i, (t, n) in enumerate(CH)}

KIND_RU = {'typo': 'опечатка', 'grammar': 'грамматика', 'fact': 'факт', 'currency': 'валюта/число',
           'language': 'английский без перевода', 'mismatch': 'экран ≠ озвучка', 'design': 'вёрстка',
           'other': 'правка'}


def tc(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


def vo(t0, t1, pad=3.0):
    return ' '.join(w for w, s in words if t0 - pad <= s <= t1 + pad)


def thumb(screen):
    """best-кадр → thumbs/{id}.jpg нужной ширины (делаем один раз)"""
    dst = THUMBS / f'{screen["id"]}.jpg'
    if dst.exists():
        return dst.name
    src = HIRES / screen['best_frame']
    if not src.exists():
        return ''
    try:
        from PIL import Image
        im = Image.open(src).convert('RGB')
        w = a.thumb_width
        im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        im.save(dst, quality=72, optimize=True)
    except Exception as ex:
        print('!! кадр', src.name, ex)
        return ''
    return dst.name


def flags_of(sid):
    """флаги локального корректора: только содержательное, артефакты распознавания отсеиваем"""
    r = llm.get(sid) or {}
    out = []
    for key, label in (('typos', 'опечатка'), ('currency_numbers', 'валюта/число'),
                       ('english_only', 'англ. без перевода'), ('foreign_script', 'чужой алфавит'),
                       ('facts_to_check', 'проверить факт')):
        for v in (r.get(key) or [])[:3]:
            v = str(v).strip()
            if not v or 'артефакт' in v.lower() or 'не опечатка' in v.lower():
                continue
            out.append((label, v[:90]))
    if (r.get('mismatch_with_vo') or '').strip():
        out.append(('экран ≠ озвучка', str(r['mismatch_with_vo'])[:90]))
    return out


by_screen = {}
for f in findings:
    by_screen.setdefault(f.get('screen_id'), []).append(f)

# ── разметка ──────────────────────────────────────────────────────────────
E = html.escape


def screen_card(e):
    sid = e['id']
    v = vlm.get(sid) or {}
    text = (v.get('vlm_text') or e['text_best'] or '').strip()
    lines = [l for l in re.split(r'\n|\s\|\s', text) if l.strip()][:6]
    fl = flags_of(sid)
    fnd = by_screen.get(sid, [])
    t = thumb(e)
    cls = 'card' + (' has-find' if fnd else (' has-flag' if fl else ''))
    parts = [f'<article class="{cls}" id="{sid}" data-ch="{e["chapter"]}" '
             f'data-find="{1 if fnd else 0}" data-flag="{1 if fl else 0}">']
    parts.append('<div class="shot">')
    if t:
        parts.append(f'<img loading="lazy" src="thumbs/{t}" alt="{E(sid)}">')
    for f in fnd:
        b = f.get('bbox_final') or f.get('bbox') or {}
        if all(k in b for k in 'xywh'):
            parts.append(f'<span class="box" style="left:{b["x"]*100:.2f}%;top:{b["y"]*100:.2f}%;'
                         f'width:{b["w"]*100:.2f}%;height:{b["h"]*100:.2f}%"></span>')
    parts.append(f'<span class="tc">{E(e["tc"])}</span>')
    parts.append(f'<span class="dur">{e["dur"]} с</span></div>')
    parts.append('<div class="body">')
    if lines:
        parts.append('<div class="ontext">' + ''.join(f'<span>{E(l.strip())}</span>' for l in lines) + '</div>')
    if v.get('vlm_desc'):
        parts.append(f'<p class="desc">{E(v["vlm_desc"])}</p>')
    say = vo(e['t0'], e['t1'])
    if say:
        parts.append(f'<p class="vo">🎙 {E(say[:240])}</p>')
    for f in fnd:
        kind = KIND_RU.get(f.get('kind'), f.get('kind', ''))
        parts.append('<div class="find">')
        parts.append(f'<div class="ftop"><b>{E(kind)}</b><span class="sev sev-{E(f.get("severity","medium"))}">'
                     f'{E(f.get("severity", ""))}</span></div>')
        parts.append(f'<p class="prob">{E(f.get("problem", ""))}</p>')
        if f.get('on_screen_text') or f.get('fix_text_final') or f.get('fix_text'):
            parts.append('<p class="diff"><s>' + E(f.get('on_screen_text', '')) + '</s> → <ins>'
                         + E(f.get('fix_text_final') or f.get('fix_text') or '') + '</ins></p>')
        if f.get('evidence'):
            parts.append(f'<p class="ev">📚 {E(str(f["evidence"])[:220])}</p>')
        parts.append('</div>')
    for label, v2 in fl:
        parts.append(f'<p class="flag"><b>{E(label)}</b> · {E(v2)}</p>')
    parts.append('</div></article>')
    return ''.join(parts)


nav = ''.join(
    f'<a href="#ch{n}" style="--c:{CH_COL[n]}">{n} · {E(CH_NAME.get(n, "ГЛАВА " + n))}</a>' for _, n in CH)

bar = ''.join(
    f'<a class="seg" href="#ch{n}" style="left:{t / DUR * 100:.3f}%;width:{(CH_END[n] - t) / DUR * 100:.3f}%;'
    f'--c:{CH_COL[n]}" title="{E(CH_NAME.get(n, n))} · {tc(t)}–{tc(CH_END[n])}">'
    f'<b>{n}</b><span>{E(CH_NAME.get(n, ""))}</span></a>' for t, n in CH)
ticks = ''.join(f'<i style="left:{e["t0"] / DUR * 100:.3f}%" class="{"f" if by_screen.get(e["id"]) else ""}"></i>'
                for e in screens)

sections = []
for t, n in CH:
    inside = [e for e in screens if e['chapter'] == n]
    nf = sum(len(by_screen.get(e['id'], [])) for e in inside)
    sections.append(
        f'<section id="ch{n}" class="chapter" style="--c:{CH_COL[n]}">'
        f'<h2><span class="num">{n}</span>{E(CH_NAME.get(n, "ГЛАВА " + n))}'
        f'<small>{tc(t)}–{tc(CH_END[n])} · {len(inside)} экранов'
        + (f' · <b class="nf">{nf} находок</b>' if nf else '') + '</small></h2>'
        f'<div class="grid">' + ''.join(screen_card(e) for e in inside) + '</div></section>')

n_find = len(findings)
stat = [('экранов', len(screens)), ('кадров', len(list(HIRES.glob('h*.jpg')))),
        ('слов в озвучке', len(words)), ('находок аудита', n_find)]
if unverified:
    stat.append(('ждут проверки', len(unverified)))
audit_note = ('' if af.exists() else
              '<div class="pending">⏳ Аудит агентами ещё идёт — находки появятся здесь после его конца. '
              'Сейчас на странице виден весь инвентарь экранов и флаги локального корректора.</div>')
if unverified:
    _u = ', '.join(f'{f.get("tc")} {f.get("screen_id")}' for f in unverified[:16])
    audit_note += (f'<div class="pending">⚠️ {len(unverified)} находок без проверки линзами '
                   f'(проверка не доехала) — они НЕ попали ни в подтверждённые, ни в отклонённые: '
                   f'{E(_u)}{" …" if len(unverified) > 16 else ""}. Догнать: s6b_pack_verify.py → '
                   f'Workflow(wf_verify_rest_v6.js) → merge_verify_v6.py.</div>')

FAVICON = ('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<text y=".9em" font-size="90">💎</text></svg>')

page = f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(P.CODE)} · ревью ката</title>
<link rel="icon" href="{FAVICON}">
<style>
:root {{
  --bg:#0E1014; --panel:#151922; --line:#232A36; --ink:#E8EAEF; --mut:#9AA3B2;
  --red:#E2564A; --amber:#D9A521;
}}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",Helvetica,Arial,sans-serif }}
a {{ color:inherit; text-decoration:none }}
header {{ padding:28px 32px 16px; border-bottom:1px solid var(--line); position:relative }}
h1 {{ margin:0 0 6px; font-size:26px; letter-spacing:-.01em }}
.sub {{ color:var(--mut); font-size:14px }}
.stats {{ display:flex; gap:26px; margin:18px 0 4px; flex-wrap:wrap }}
.stats div b {{ display:block; font-size:24px; line-height:1.1 }}
.stats div span {{ color:var(--mut); font-size:12px; text-transform:uppercase; letter-spacing:.06em }}
.pending {{ margin:16px 0 0; padding:10px 14px; background:#1B1E17; border:1px solid #3A3A22;
  border-radius:8px; color:#E4D9A8; font-size:14px }}
.timeline {{ position:relative; height:52px; margin:22px 32px 0; background:var(--panel);
  border:1px solid var(--line); border-radius:8px; overflow:hidden }}
.seg {{ position:absolute; top:0; bottom:0; border-right:1px solid var(--bg);
  background:color-mix(in srgb, var(--c) 22%, transparent); padding:6px 8px; overflow:hidden }}
.seg:hover {{ background:color-mix(in srgb, var(--c) 38%, transparent) }}
.seg b {{ color:var(--c); font-size:12px; display:block }}
.seg span {{ font-size:11px; color:var(--mut); white-space:nowrap }}
.ticks {{ position:absolute; left:0; right:0; bottom:0; height:8px }}
.ticks i {{ position:absolute; width:2px; height:8px; background:#4A5468 }}
.ticks i.f {{ background:var(--red); height:10px; bottom:0 }}
nav {{ position:sticky; top:0; z-index:5; display:flex; gap:6px; flex-wrap:wrap;
  padding:12px 32px; background:rgba(14,16,20,.92); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line) }}
nav a {{ padding:6px 12px; border:1px solid var(--line); border-radius:999px; font-size:13px;
  color:var(--mut) }}
nav a:hover {{ border-color:var(--c); color:var(--c) }}
.filters {{ margin-left:auto; display:flex; gap:6px }}
.filters button {{ font:inherit; font-size:13px; padding:6px 12px; border-radius:999px; cursor:pointer;
  background:transparent; color:var(--mut); border:1px solid var(--line) }}
.filters button.on {{ color:var(--ink); border-color:#4A5468; background:var(--panel) }}
.chapter {{ padding:30px 32px 8px }}
.chapter h2 {{ display:flex; align-items:baseline; gap:12px; margin:0 0 16px; font-size:19px }}
.chapter h2 .num {{ color:var(--c); font-variant-numeric:tabular-nums }}
.chapter h2 small {{ color:var(--mut); font-weight:400; font-size:13px; margin-left:auto }}
.nf {{ color:var(--red) }}
.grid {{ display:grid; gap:18px; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)) }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden }}
.card.has-flag {{ border-color:#4A431F }}
.card.has-find {{ border-color:var(--red); box-shadow:0 0 0 1px rgba(226,86,74,.25) }}
.shot {{ position:relative; aspect-ratio:16/9; background:#000 }}
.shot img {{ width:100%; height:100%; object-fit:cover; display:block }}
.box {{ position:absolute; border:2px solid var(--red); border-radius:3px;
  box-shadow:0 0 0 9999px rgba(10,10,14,.42) }}
.tc, .dur {{ position:absolute; bottom:8px; font-size:12px; padding:2px 7px; border-radius:5px;
  background:rgba(10,10,14,.78); font-variant-numeric:tabular-nums }}
.tc {{ left:8px }} .dur {{ right:8px; color:var(--mut) }}
.body {{ padding:12px 14px 14px }}
.ontext {{ display:flex; flex-direction:column; gap:2px; margin-bottom:8px }}
.ontext span {{ font-weight:600; font-size:14px; letter-spacing:.01em }}
.desc {{ margin:0 0 8px; color:var(--mut); font-size:13px }}
.vo {{ margin:0; color:#8D96A6; font-size:12.5px; font-style:italic;
  border-left:2px solid var(--line); padding-left:9px }}
.flag {{ margin:9px 0 0; font-size:12.5px; color:#D9C98A }}
.find {{ margin:11px 0 0; padding:10px 11px; background:#1C1417; border:1px solid #46282A; border-radius:8px }}
.ftop {{ display:flex; align-items:center; gap:8px; margin-bottom:5px; font-size:13px }}
.sev {{ font-size:11px; padding:1px 7px; border-radius:999px; border:1px solid currentColor }}
.sev-high {{ color:var(--red) }} .sev-medium {{ color:var(--amber) }} .sev-low {{ color:var(--mut) }}
.prob {{ margin:0 0 6px; font-size:13px }}
.diff {{ margin:0 0 6px; font-size:13.5px }}
.diff s {{ color:#C78A86 }} .diff ins {{ color:#8BD48A; text-decoration:none; font-weight:600 }}
.ev {{ margin:0; font-size:12px; color:var(--mut) }}
footer {{ padding:28px 32px 60px; color:var(--mut); font-size:13px }}
@media (max-width:640px) {{ header,nav,.chapter,footer {{ padding-left:16px; padding-right:16px }}
  .timeline {{ margin-left:16px; margin-right:16px }} }}
</style></head><body>
<header>
  <h1>{E(P.CODE)} · {E(str(P.get('film_subject') or P.get('project_name') or P.FILM or 'ревью ката'))}</h1>
  <div class="sub">Ревью ката v1 · {tc(DUR)} · 3840×2160 · монтажёр сдал 11.09.2026</div>
  <div class="stats">{''.join(f'<div><b>{v}</b><span>{k}</span></div>' for k, v in stat)}</div>
  {audit_note}
</header>
<div class="timeline">{bar}<div class="ticks">{ticks}</div></div>
<nav>{nav}
  <div class="filters">
    <button class="on" data-f="all">все экраны</button>
    <button data-f="flag">с флагами</button>
    <button data-f="find">находки</button>
  </div>
</nav>
{''.join(sections)}
<footer>
  Кадры — 1 fps из ката, текст экранов — Qwen2.5-VL-7B, флаги — Qwen3-8B, всё локально на Memex.
  Красная рамка на кадре — то место, куда смотреть. Страница самодостаточна: кадры лежат рядом в <code>thumbs/</code>.
</footer>
<script>
const cards = [...document.querySelectorAll('.card')];
document.querySelectorAll('.filters button').forEach(b => b.addEventListener('click', () => {{
  document.querySelectorAll('.filters button').forEach(x => x.classList.toggle('on', x === b));
  const f = b.dataset.f;
  cards.forEach(c => {{
    const show = f === 'all' || (f === 'find' && c.dataset.find === '1')
      || (f === 'flag' && (c.dataset.flag === '1' || c.dataset.find === '1'));
    c.style.display = show ? '' : 'none';
  }});
  document.querySelectorAll('.chapter').forEach(s => {{
    s.style.display = [...s.querySelectorAll('.card')].some(c => c.style.display !== 'none') ? '' : 'none';
  }});
}}));
</script>
</body></html>'''

OUT.write_text(page, encoding='utf-8')
print(f'→ {OUT}  ({OUT.stat().st_size // 1024} КБ) · экранов {len(screens)} · находок {n_find} · '
      f'кадров в thumbs/ {len(list(THUMBS.glob("*.jpg")))}')
