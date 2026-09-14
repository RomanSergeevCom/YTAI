#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Результаты воркфлоу (task-output JSON) → рабочие файлы + КОМПАКТНАЯ сводка в консоль.
Локально, без агентов: wf_result.json (ревью) и structure_raw.json (предложения структуры).
Usage: x_wf_extract.py <review.output> <structure.output>"""
import collections
import json
import os
import re
import sys

WORK = os.path.dirname(os.path.abspath(__file__))


def load(path):
    """task-output: {summary, agentCount, logs, result:{…}} → сам result."""
    t = open(path, encoding='utf-8').read()
    d = json.loads(t[t.find('{'):])
    r = d.get('result', d)
    return json.loads(r) if isinstance(r, str) else r


def sec(s):
    m = re.findall(r'\d+', str(s or ''))
    return int(m[0]) * 60 + int(m[1]) if len(m) >= 2 else 0


def tc(s):
    s = int(s)
    return f'{s // 60}:{s % 60:02d}'


rev = load(sys.argv[1])
st = load(sys.argv[2])
json.dump(rev, open(os.path.join(WORK, 'wf_result.json'), 'w'), ensure_ascii=False)
json.dump(st, open(os.path.join(WORK, 'structure_raw.json'), 'w'), ensure_ascii=False)

f = rev.get('findings') or []
print('findings:', len(f), '| refuted:', rev.get('counts', {}).get('refuted'))
print('по важности:', dict(collections.Counter(x['severity'] for x in f)))
print('по категориям:', dict(collections.Counter(x['category'] for x in f)))
print('чувствительных:', sum(1 for x in f if x.get('sensitive')))
print('по источнику:', dict(collections.Counter(x.get('src') for x in f)))
tb = rev.get('tables') or {}
print('чек-лист фонда:', len(tb.get('fund_checklist') or []), '| графика ТЗ:', len(tb.get('graphics_tz') or []))
v2 = tb.get('v2_table') or []
print('аудит v2:', dict(collections.Counter(d['status'] for d in v2 if not d.get('from'))))
print('v2 summary:', (tb.get('v2_summary') or '')[:400])
sr = (tb.get('structure') or {})
print('\n== ПРАВИЛА ЛИСТА ==')
for r in sr.get('rules') or []:
    print(f"  [{r['status']}] {r['rule'][:70]} — {r['evidence'][:150]}")
print('\n== MUST ==')
for x in sorted([x for x in f if x['severity'] == 'must'], key=lambda x: sec(x['tc_start'])):
    print(f"  {x['id']:8s} {x['tc_start']:>6s}–{x['tc_end']:<6s} {x['category']:18s}{'⚠️' if x.get('sensitive') else '  '} "
          f"{x['now'][:90]} → {x['todo'][:110]}")
sh = sorted([x for x in f if x['severity'] != 'must'], key=lambda x: sec(x['tc_start']))
open(os.path.join(WORK, 'findings_should.txt'), 'w').write('\n'.join(
    f"{x['id']:8s} {x['tc_start']:>6s}–{x['tc_end']:<6s} {x['severity']:6s} {x['category']:18s} {x['now']} → {x['todo']}"
    for x in sh))
print(f'\n== SHOULD/NICE: {len(sh)} → findings_should.txt ==')
print('\n== ФОНД ==')
for c in tb.get('fund_checklist') or []:
    print(f"  {c['tc']:>7s} [{c['priority']}] {c['what'][:80]} → {c['action'][:90]}")
print('\n== ГРАФИКА ==')
for g in tb.get('graphics_tz') or []:
    print(f"  {g['tc']:>7s} {g['type'][:22]:22s} «{g['text'][:70]}» {g.get('note', '')[:60]}")
print('\n== ГЛАВЫ (вердикты агентов) ==')
for c in rev.get('chapters') or []:
    print(f"  {c['n']:2d} {c['verdict']:6s} {c['name'][:44]:44s} {c['summary'][:90]}")
print('\n== СТРУКТУРА: предложения ==')
for p in st.get('proposals') or []:
    print(f"  [{p['key']}] {p['label']}: {p['approach'][:200]}")
    print(f"      титул «{p['film_title']}» @ {str(p['title_card_tc'])[:40]} · глав {len(p['chapters'])} · "
          f"YouTube {len(p.get('youtube_chapters') or [])} · перестановок {len(p.get('moves') or [])}")
    print(f"      усилия: {p.get('effort', '')[:160]}")
