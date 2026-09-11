#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Индекс упоминаний терминов и локаций (озвучка words.json + экраны screens_v6.json).

Правило (Роман: «все термины при каждом упоминании»): каждое упоминание → плашка,
НО повтор того же термина в пределах COOLDOWN с считается тем же упоминанием (плашка
уже была на экране только что). Локации — то же для мини-карт.
→ terms_v6.json {terms:[{key,t,tc,src,hit}], locs:[{key,t,tc,src,hit}], stats}
"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from terms_catalog import TERM_RX, LOC_RX, MAP_WINDOWS, PLACE  # noqa

W6 = Path(__file__).parent
WORDS = '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/YTUVI01_v1.words.json'
COOLDOWN = 45.0


def tc(t):
    return f'{int(t) // 60}:{int(t) % 60:02d}'


d = json.load(open(WORDS, encoding='utf-8'))
words = [(w['w'], float(w['s'])) for s in d['segments'] for w in s['words']]
# скользящее окно из 3 слов — ловим «high jewelry», «шри ланка», «голубиная кровь»
mentions = {'terms': [], 'locs': []}
for i, (w, t) in enumerate(words):
    win = ' '.join(x[0] for x in words[i:i + 3]).lower()
    first = re.sub(r'[^а-яёa-z0-9 ]', '', w.lower())
    for kind, table in (('terms', TERM_RX), ('locs', LOC_RX)):
        for row in table:
            key, rx = row[0], row[1]
            m = rx.search(win)
            if m and m.start() < len(first) + 1:      # матч начинается с текущего слова
                mentions[kind].append({'key': key, 't': round(t, 2), 'tc': tc(t), 'src': 'vo', 'hit': win[:40]})

# экраны: английские/термин-титры без озвучки (Mong Hsu, pigeon blood, Iron-rich…)
scr = W6 / 'screens_v6.json'
if scr.exists():
    for e in json.load(open(scr, encoding='utf-8')):
        txt = e['text_best'].lower()
        for kind, table in (('terms', TERM_RX), ('locs', LOC_RX)):
            for row in table:
                key, rx = row[0], row[1]
                if rx.search(txt):
                    mentions[kind].append({'key': key, 't': float(e['t0']), 'tc': tc(e['t0']),
                                           'src': 'screen', 'hit': e['text_best'][:40]})

out = {'terms': [], 'locs': [], 'stats': {}}
for kind in ('terms', 'locs'):
    last = {}
    for m in sorted(mentions[kind], key=lambda x: x['t']):
        if m['key'] in last and m['t'] - last[m['key']] < COOLDOWN:
            continue
        last[m['key']] = m['t']
        out[kind].append(m)
    cnt = {}
    for m in out[kind]:
        cnt[m['key']] = cnt.get(m['key'], 0) + 1
    out['stats'][kind] = {'raw': len(mentions[kind]), 'plates': len(out[kind]), 'by_key': cnt}
# ── канон названий (Роман 11.09) ──────────────────────────────────────────────
# cover: место попало в окно большой карты (перечисление «пояса») → мини-карту не ставим
for m in out['locs']:
    for a, b, name, _why in MAP_WINDOWS:
        if a <= m['t'] <= b:
            m['cover'] = name
            break
# note: сноска «одна страна — два имени» — ОДИН раз, на первом видимом упоминании места
noted = set()
for m in sorted(out['locs'], key=lambda x: x['t']):
    if (PLACE.get(m['key']) or {}).get('note') and not m.get('cover') and m['key'] not in noted:
        m['note'] = True
        noted.add(m['key'])
out['stats']['locs']['covered'] = sum(1 for m in out['locs'] if m.get('cover'))
out['stats']['locs']['notes'] = sorted(noted)
# ── группы: термины, упомянутые в одном окне (≤ GROUP_WIN с), идут ОДНОЙ плашкой (до 3 определений) ──
GROUP_WIN = 5.0
groups = []
for m in out['terms']:
    if groups and m['t'] - groups[-1]['t'] <= GROUP_WIN and len(groups[-1]['keys']) < 3 and m['key'] not in groups[-1]['keys']:
        groups[-1]['keys'].append(m['key'])
    else:
        groups.append({'t': m['t'], 'tc': m['tc'], 'keys': [m['key']]})
out['term_groups'] = groups
out['stats']['term_groups'] = {'plates': len(groups), 'multi': sum(1 for g in groups if len(g['keys']) > 1)}
json.dump(out, open(W6 / 'terms_v6.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(out['stats'], ensure_ascii=False, indent=1))
