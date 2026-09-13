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
from terms_catalog import TERM_RX, LOC_RX, MAP_WINDOWS, PLACE, TERM_EXTRA  # noqa
import proj_config as P  # noqa: E402

W6 = Path(__file__).parent
WORDS = P.WORDS
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
                mentions[kind].append({'key': key, 't': round(t, 2), 'tc': tc(t), 'src': 'vo', 'hit': win})

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
                                           'src': 'screen', 'hit': e['text_best'][:200], 'screen_id': e['id']})

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

# ── «английское слово ВИДНО в кадре» (Роман 11.09: «17 JEWELS вместе с переводом») ──
# Не языковой детектор (OCR читает «НОРМА» как «HORMA», «ТЕМПЕРАТУРЫ» как «TEMP АТУРЫ»),
# а сверка с формами из каталога: en=[...] у термина/места. Фразе достаточно VLM-текста
# (он чище OCR), одиночному слову нужны оба источника.
EN_WIN = 4.0
EN_STOP = {'uvi', 'ntd', 'nid', 'kor', 'hun', 'isi', 'dar', 'mois', 'temp', 'temi'}
HOMO = set('ABCEHKMOPTXYacehkmoprxy')
EN = {'terms': {k: v['en'] for k, v in TERM_EXTRA.items() if v.get('en')},
      'locs': {k: p['en'] for k, p in PLACE.items() if p.get('en')}}
VLM = {}
vp = W6 / 'vlm_v6.jsonl'
if vp.exists():
    for ln in open(vp, encoding='utf-8'):
        try:
            v = json.loads(ln)
        except ValueError:
            continue
        VLM[v['id']] = v.get('vlm_text') or ''


def _norm(s):
    return re.sub(r'\s+', ' ', str(s or '').replace('’', "'").replace('|', ' ')).lower()


def _seen(form, ocr, vlm):
    core = re.sub(r"[^a-z]", '', form)
    if core in EN_STOP or (core and all(c in HOMO for c in form if c.isalpha())):
        return False
    rx = re.compile(r'(?<![a-z])' + re.escape(form).replace('\\ ', r'[\s-]+').replace("'", "'?") + r'(?![a-z])')
    return bool(rx.search(vlm)) and (' ' in form or bool(rx.search(ocr)))


scr = json.load(open(W6 / 'screens_v6.json', encoding='utf-8')) if (W6 / 'screens_v6.json').exists() else []
seen_pairs = set()
for kind in ('terms', 'locs'):
    for m in out[kind]:
        for e in scr:
            if not (float(e['t0']) - EN_WIN <= m['t'] <= float(e['t1']) + EN_WIN):
                continue
            ocr, vlm = _norm(e.get('text_best')), _norm(VLM.get(e['id']))
            forms = [f for f in EN[kind].get(m['key'], []) if _seen(f, ocr, vlm)]
            if forms:
                m['en_on_screen'] = True
                m['en_forms'] = sorted(set(m.get('en_forms', []) + forms), key=len, reverse=True)
                m['screen_id'] = e['id']
                m['screen_tc'] = tc(e['t0'])
                m['screen_text'] = (VLM.get(e['id']) or e.get('text_best') or '')[:400]
                seen_pairs.add((kind, m['key'], e['id']))

# экраны, где английское имя видно, а своего упоминания рядом нет
out['en_screens'] = []
for e in scr:
    ocr, vlm = _norm(e.get('text_best')), _norm(VLM.get(e['id']))
    for kind in ('terms', 'locs'):
        for key, forms in EN[kind].items():
            hit = [f for f in forms if _seen(f, ocr, vlm)]
            if hit and (kind, key, e['id']) not in seen_pairs:
                out['en_screens'].append({'kind': kind, 'key': key, 'screen_id': e['id'],
                                          't': float(e['t0']), 'tc': tc(e['t0']), 'forms': sorted(set(hit), key=len, reverse=True),
                                          'text': (VLM.get(e['id']) or e.get('text_best') or '')[:400],
                                          'faces': e.get('faces_avg')})
out['stats']['en'] = {'on_screen_terms': sum(1 for m in out['terms'] if m.get('en_on_screen')),
                      'on_screen_locs': sum(1 for m in out['locs'] if m.get('en_on_screen')),
                      'screens_without_mention': len(out['en_screens'])}
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
