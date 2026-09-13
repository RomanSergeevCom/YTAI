#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перенести результаты preview-QA (journal.jsonl workflow) в v6/previews_v7.json:
подписи cap_suggest → cap; fix {t, box, minw} → поправки превью (img:<имя> или ТЗ-NN.frames[k]).
Печатает все problems для ручного просмотра. usage: apply_qa.py JOURNAL [--dry]"""
import ast
import json
import re
import sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402
SP = W6 / 'polish'  # рабочие файлы полировки ТЗ
OVR = M / 'previews_v7.json'
J = Path(sys.argv[1])
DRY = '--dry' in sys.argv

batches = json.load(open(SP / 'pqa' / 'batches.json'))
by_prev = {Path(e['preview']).name: e for b in batches for e in b}
man = json.load(open(W6 / 'previews_doc' / 'manifest.json'))
ovr = json.load(open(OVR)) if OVR.exists() else {}

items = []
for ln in open(J):
    if not ln.strip():
        continue
    r = json.loads(ln)
    if r.get('type') != 'result':
        continue
    res = r['result']
    if isinstance(res, str):
        try:
            res = ast.literal_eval(res)
        except Exception:
            res = json.loads(res)
    items += (res or {}).get('items', [])

n_cap = n_fix = 0
for it in items:
    name = Path(it['preview']).name
    e = by_prev.get(name)
    if not e:
        print('?? нет в батчах:', name)
        continue
    fx = {k: v for k, v in (it.get('fix') or {}).items() if k in ('t', 'box', 'minw') and v not in (None, [], '')}
    if 'box' in fx and (len(fx['box']) != 4 or fx['box'][2] <= fx['box'][0] or fx['box'][3] <= fx['box'][1]):
        print('!! кривая рамка, пропускаю:', name, fx['box'])
        fx.pop('box')
    cap = (it.get('cap_suggest') or '').strip()
    if e['img']:
        o = ovr.setdefault('img:' + e['img'], {})
        if cap:
            o['cap'] = cap
            n_cap += 1
        if fx and not it.get('ok'):
            o.update(fx)
            n_fix += 1
    else:
        tz = e['tz']
        k = int(re.search(r'_(\d+)\.jpg$', name).group(1)) - 1
        cur = ovr.get(tz, {}).get('frames') or [{'t': x.get('t'), 'cap': x.get('cap')} for x in man['tz'].get(tz, [])]
        while len(cur) <= k:
            cur.append({})
        if cap:
            cur[k]['cap'] = cap
            n_cap += 1
        if fx and not it.get('ok') and not cur[k].get('grid'):
            cur[k].update({kk: vv for kk, vv in fx.items() if kk in ('t', 'box')})
            n_fix += 1
        ovr.setdefault(tz, {})['frames'] = cur
    mark = '✅' if it.get('ok') else '🛠'
    print(f"{mark} {e['tz']} {name}: {cap}" + (f"  fix={fx}" if fx and not it.get('ok') else ''))
    for p in it.get('problems') or []:
        print('     –', p[:200])
print(f'\nQA: превью {len(items)} · подписей {n_cap} · поправок {n_fix}')
if not DRY:
    json.dump(ovr, open(OVR, 'w'), ensure_ascii=False, indent=1)
    print('→', OVR)
