#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S6: пакеты для агентов аудита — по главам (screens + OCR bbox + VLM + LLM-флаги + озвучка).

→ audit_pack/ch_NN[_a|_b].json  и  audit_pack/INDEX.json (список пакетов с кол-вом экранов)
Каждый экран: id, tc, t0–t1, chapter, hires-кадры (best + last), OCR-текст всех кадров события,
строки best-кадра с bbox (0..1, origin левый верх), VLM-транскрипция/описание, флаги Qwen3,
озвучка ±8 с. Агент СМОТРИТ кадры сам (Read image) — OCR/VLM только подсказка.
"""
import json, re, sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402

PACK = W6 / 'audit_pack'
PACK.mkdir(exist_ok=True)
WORDS = P.WORDS
CH_NAME = dict(P.get('ch_name') or {})
if not CH_NAME:
    raise SystemExit('в карточке нет ch_name — пакеты глав легли бы по чужой структуре; заполни chapters + ch_name')

ws = []
for seg in json.load(open(WORDS, encoding='utf-8'))['segments']:
    for w in seg.get('words') or []:
        ws.append((w['w'], float(w['s'])))


def vo(t0, t1, pad=8.0):
    return ' '.join(w for w, s in ws if t0 - pad <= s <= t1 + pad)


ev = json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))
vlm = {}
if (W6 / 'vlm_v6.jsonl').exists():
    for ln in open(W6 / 'vlm_v6.jsonl', encoding='utf-8'):
        try:
            r = json.loads(ln); vlm[r['id']] = r
        except Exception:
            pass
llm = {}
if (W6 / 'llm_v6.json').exists():
    for r in json.load(open(W6 / 'llm_v6.json', encoding='utf-8')):
        llm[r['id']] = {k: r.get(k) for k in ('typos', 'grammar', 'currency_numbers', 'english_only',
                                                'facts_to_check', 'mismatch_with_vo', 'severity')}

by_ch = {}
for e in ev:
    v = vlm.get(e['id'], {})
    rec = {
        'id': e['id'], 'tc': e['tc'], 't0': e['t0'], 't1': e['t1'], 'dur': e['dur'], 'chapter': e['chapter'],
        'frame_best': str(W6 / 'hires' / e['best_frame']), 'frame_last': str(W6 / 'hires' / e['last_frame']),
        'frames_all_secs': list(range(e['t0'], e['t1'] + 1)),
        'ocr_best': e['text_best'], 'ocr_all_frames': e['texts_all'],
        'ocr_lines_best_bbox': [{'t': l['t'], 'x': l['x'], 'y': l['y'], 'w': l['bw'], 'h': l['bh']} for l in e['lines_best']],
        'vlm_text': v.get('vlm_text'), 'vlm_desc': v.get('vlm_desc'),
        'llm_flags': llm.get(e['id']),
        'voiceover_around': vo(e['t0'], e['t1']),
    }
    by_ch.setdefault(e['chapter'], []).append(rec)

index = []
for ch, recs in sorted(by_ch.items()):
    parts = [recs]
    if len(recs) > 26:                      # длинные главы — пополам, чтобы агент реально смотрел каждый кадр
        h = len(recs) // 2
        parts = [recs[:h], recs[h:]]
    for i, part in enumerate(parts):
        name = f'ch_{ch}' + (f'_{"ab"[i]}' if len(parts) > 1 else '')
        # .get: глава, которой нет в ch_name карточки, раньше роняла сборку пакетов KeyError'ом
        pack = {'pack': name, 'chapter': ch, 'chapter_name': CH_NAME.get(ch, f'ГЛАВА {ch}'),
                'range_tc': f'{part[0]["tc"]}–{part[-1]["tc"]}', 'n_screens': len(part),
                'hires_dir': str(W6 / 'hires'), 'frame_naming': 'h{sec+1:04d}.jpg = секунда sec (кадр = сек+1)',
                'screens': part}
        json.dump(pack, open(PACK / f'{name}.json', 'w'), ensure_ascii=False, indent=1)
        index.append({'pack': name, 'file': str(PACK / f'{name}.json'), 'chapter': ch, 'n': len(part),
                      'range': pack['range_tc']})
json.dump(index, open(PACK / 'INDEX.json', 'w'), ensure_ascii=False, indent=1)
print(json.dumps(index, ensure_ascii=False, indent=1))
print('vlm covered:', sum(1 for e in ev if e['id'] in vlm), '/', len(ev), '| llm covered:', sum(1 for e in ev if e['id'] in llm))
