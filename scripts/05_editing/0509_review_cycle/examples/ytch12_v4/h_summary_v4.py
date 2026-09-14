#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальная HTML-сводка продюсерского ревью YTCH12 v4 → 05_Review/YTCH12_v4_review_producer.html.
Самодостаточная (кадры встроены base64, 360px), тёмная тема портала, favicon inline-SVG.
Материал чувствительный (дети, фонд) — файл локальный, наружу не публикуется.
Вход: wf_result.json (synth, tables, findings, chapters), chapters_cards.json, frames1s/.
"""
import base64
import html
import io
import json
import os
import re

from PIL import Image

WORK = os.path.dirname(os.path.abspath(__file__))
REV = os.path.dirname(WORK)
FR = '/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/00_Setup/05_Review/v4_review/frames1s'
OUT = os.path.join(REV, 'YTCH12_v4_review_producer.html')
E = html.escape
CIRC = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'
COL = {'Green': '#2e7d4f', 'Yellow': '#b8860b', 'Red': '#b23b3b'}


def J(name, default=None):
    p = os.path.join(WORK, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default


def sec(s):
    m = re.findall(r'\d+(?:\.\d+)?', str(s))
    p = [float(x) for x in m[:3]]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else (p[0] * 60 + p[1] if len(p) == 2 else (p[0] if p else 0))


def thumb(s, w=360):
    p = f'{FR}/f{int(s) + 1:04d}.jpg'
    if not os.path.exists(p):
        return ''
    im = Image.open(p)
    im.thumbnail((w, w))
    b = io.BytesIO()
    im.save(b, 'JPEG', quality=72)
    return f'<img src="data:image/jpeg;base64,{base64.b64encode(b.getvalue()).decode()}" alt="кадр {int(s) // 60}:{int(s) % 60:02d}">'


def tc(x):
    x = int(x)
    return f'{x // 60}:{x % 60:02d}'


def main():
    wf = J('wf_result.json', {})
    s = wf.get('synth') or {}
    tabs = wf.get('tables') or {}
    finds = {f['id']: f for f in (wf.get('findings') or []) + ((wf.get('gapfill') or {}).get('findings') or [])}
    chapters = sorted(J('chapters_cards.json'), key=lambda c: c['tc_sec'])
    colors = {c['n']: c for c in (s.get('chapter_colors') or [])}
    summ = {c['n']: c for c in (wf.get('chapters') or [])}

    H = ['<title>YTCH12 · ревью v4</title>',
         '<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22>'
         '<text y=%22.9em%22 font-size=%2290%22>🎬</text></svg>">',
         '<style>:root{--bg:#121417;--fg:#e8e6e1;--mut:#9a9890;--card:#1c1f23;--acc:#d9534f;--line:#2c3036}'
         'body{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Segoe UI,sans-serif;margin:0}'
         'main{max-width:1180px;margin:0 auto;padding:28px 20px 80px}h1{font-size:26px;margin:0 0 6px}'
         'h2{font-size:19px;margin:34px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}'
         '.mut{color:var(--mut)}.v{font-size:17px;background:var(--card);border-left:4px solid var(--acc);padding:14px 16px;border-radius:6px}'
         '.card{background:var(--card);border-radius:8px;padding:12px 14px;margin:10px 0;display:grid;grid-template-columns:360px 1fr;gap:14px}'
         '.card img{width:360px;border-radius:4px}.num{font-weight:700;color:var(--acc);margin-right:6px}'
         'table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:6px 8px;vertical-align:top;text-align:left}'
         '.tag{display:inline-block;border-radius:4px;padding:0 6px;font-size:12px;color:#fff}'
         '.wrap{overflow-x:auto}ul{padding-left:20px}li{margin:4px 0}'
         '@media(max-width:800px){.card{grid-template-columns:1fr}.card img{width:100%}}</style>',
         '<main>',
         '<h1>YTCH12 «Одна с ребёнком» · ревью монтажа v4</h1>',
         '<div class="mut">montage_1 от 09.09 · 50:45 · 1080p25 · ревью 10.09.2026 · '
         'док: YTCH12_Review_v4_video · таймлайн: YTCH12_review_v4_full.json</div>',
         f'<h2>Вердикт: {E(s.get("verdict_short", "—"))}</h2>',
         f'<p class="v"><b>{E(s.get("headline", ""))}</b><br>{E(s.get("verdict", ""))}</p>']
    if s.get('strengths'):
        H.append('<h2>Что работает</h2><ul>' + ''.join(f'<li>{E(x)}</li>' for x in s['strengths']) + '</ul>')
    for k, t in (('vs_v3', 'Что изменилось с v3 (31.08)'), ('vs_v2', 'Что изменилось с v2 («История Светы»)')):
        if s.get(k):
            H.append(f'<h2>{t}</h2><p>{E(s[k])}</p>')
    if s.get('must'):
        H.append('<h2>Обязательные правки</h2>')
        for m in s['must']:
            t0 = sec(m.get('tc', '').split('–')[0]) if m.get('tc') else None
            src = [finds[i] for i in (m.get('ids') or []) if i in finds]
            det = ''.join(f'<li><b>{E(f["id"])}</b> {E(f.get("tc_start", ""))}–{E(f.get("tc_end", ""))}: '
                          f'❌ {E(f.get("now", ""))} → ✅ {E(f.get("todo", ""))}'
                          + (f' · 📚 {E(f["material"])}' if f.get('material') else '') + '</li>' for f in src)
            num = CIRC[m['num'] - 1] if 0 < m['num'] <= len(CIRC) else str(m['num'])
            H.append(f'<div class="card"><div>{thumb(t0) if t0 is not None else ""}</div><div>'
                     f'<div><span class="num">{num}</span><b>{E(m.get("title", ""))}</b> '
                     f'<span class="mut">{E(m.get("tc", ""))}</span></div><p>{E(m.get("todo", ""))}</p>'
                     + (f'<ul class="mut">{det}</ul>' if det else '') + '</div></div>')
    if s.get('should'):
        H.append('<h2>Желательные правки</h2><ol>' + ''.join(
            f'<li><b>{E(m.get("title", ""))}</b> <span class="mut">{E(m.get("tc", ""))}</span> — {E(m.get("todo", ""))}</li>'
            for m in s['should']) + '</ol>')
    if tabs.get('fund_checklist'):
        H.append('<h2>Чек-лист согласования с фондом</h2><p class="mut">⚠️ — не вырез: блюр / письменное согласие / формулировка (политика 27.08).</p>'
                 '<div class="wrap"><table><tr><th>TC</th><th>Что</th><th>Риск</th><th>Действие</th><th>Приоритет</th></tr>'
                 + ''.join(f'<tr><td>{E(c["tc"])}</td><td>{E(c["what"])}</td><td>{E(c["risk"])}</td>'
                           f'<td>{E(c["action"])}</td><td>{E(c["priority"])}</td></tr>' for c in tabs['fund_checklist'])
                 + '</table></div>')
    if tabs.get('graphics_tz'):
        H.append('<h2>Графика, которую нужно добавить</h2><div class="wrap"><table><tr><th>TC</th><th>Тип</th><th>Текст</th><th>Заметка</th></tr>'
                 + ''.join(f'<tr><td>{E(g["tc"])}</td><td>{E(g["type"])}</td><td>{E(g["text"])}</td><td>{E(g.get("note", ""))}</td></tr>'
                           for g in tabs['graphics_tz']) + '</table></div>')
    st = tabs.get('structure') or {}
    if st.get('rules'):
        H.append('<h2>Правила монтажного листа</h2><ul>' + ''.join(
            f'<li><b>{E(r["rule"])}</b> — {E(r["status"])}: {E(r["evidence"])}</li>' for r in st['rules']) + '</ul>')
    if st.get('plan_vs_fact'):
        H.append('<h2>План листа ↔ факт v4</h2><div class="wrap"><table><tr><th>План</th><th>мин</th><th>Факт v4</th><th>мин</th><th>Статус</th></tr>'
                 + ''.join(f'<tr><td>{E(r["plan"])}</td><td>{r["plan_min"]}</td><td>{E(r["fact"])}</td><td>{r["fact_min"]}</td><td>{E(r["status"])}</td></tr>'
                           for r in st['plan_vs_fact']) + '</table></div>')
    if st.get('tobe'):
        H.append('<h2>TO-BE v5 — порядок блоков</h2><div class="wrap"><table><tr><th>#</th><th>Блок</th><th>Источник</th><th>Действие</th><th>мин</th></tr>'
                 + ''.join(f'<tr><td>{r["order"]}</td><td>{E(r["block"])}</td><td>{E(r["source"])}</td><td>{E(r["action"])}</td><td>{r["est_min"]}</td></tr>'
                           for r in st['tobe']) + '</table></div>')
    for k, t in (('time_math', 'Хронометраж'), ('tech_summary', 'Техника'), ('graphics_summary', 'Графика — итог'),
                 ('fund_checklist_summary', 'Фонд — итог')):
        if s.get(k):
            H.append(f'<h2>{t}</h2><p>{E(s[k])}</p>')
    if tabs.get('v2_table'):
        H.append(f'<h2>Выполнение ревью v2</h2><p>{E(tabs.get("v2_summary") or "")}</p><div class="wrap"><table>'
                 '<tr><th>№</th><th>Статус</th><th>Что в v4</th></tr>'
                 + ''.join(f'<tr><td>{E(str(d["n"]))}</td><td>{E(d["status"])}</td><td>{E(d["note"])}</td></tr>'
                           for d in tabs['v2_table'] if not d.get('from')) + '</table></div>')
    H.append('<h2>Карта глав v4</h2>')
    for i, c in enumerate(chapters, 1):
        cc = colors.get(i, {})
        col = cc.get('color') or c.get('color', 'Green')
        sm = summ.get(i, {})
        H.append(f'<div class="card"><div>{thumb(c["tc_sec"] + 2)}</div><div>'
                 f'<div><span class="tag" style="background:{COL[col]}">{E(col)}</span> '
                 f'<b>{E(c["name"])}</b> <span class="mut">{tc(c["tc_sec"])} · {c["duration_sec"] / 60:.1f} мин</span></div>'
                 + (f'<p>{E(sm.get("summary", ""))}</p>' if sm.get('summary') else '')
                 + (f'<p class="mut">{E(sm.get("story_function", ""))}</p>' if sm.get('story_function') else '')
                 + (f'<p>{E(cc.get("comment", ""))}</p>' if cc.get('comment') else '') + '</div></div>')
    H.append('</main>')
    open(OUT, 'w', encoding='utf-8').write('\n'.join(H))
    print('→', OUT, f'{os.path.getsize(OUT) / 1e6:.2f} MB')


if __name__ == '__main__':
    main()
