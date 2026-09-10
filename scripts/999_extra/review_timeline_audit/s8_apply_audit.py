#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S8: подтверждённые находки аудита → pravki_v2.json (ТЗ-33+) + audit_v6.json (стрелки V5,
исправления V3, LT V4) + кадры ошибок для Drive/листа.

Вход: audit_findings_v6.json = {"confirmed":[...]} (результат workflow: screen_id, tc, t0, t1, frame, kind,
severity, on_screen_text, problem, fix_text_final, evidence, bbox_final, existing_tz).
Правила: одна НОВАЯ ТЗ на экран (несколько находок одного экрана сливаются); находка под existing_tz
не получает номера, но получает стрелку ann_tz{NN}{x}.png. Категория новых ТЗ = graphics (🎨).
Идемпотентно: новые ТЗ помечены `source: audit_v6` и при повторном запуске заменяются.
"""
import json, re, subprocess, sys
from pathlib import Path

W6 = Path(__file__).parent
M = W6.parent / 'montage'
ERR = W6 / 'err_frames'
ERR.mkdir(exist_ok=True)
WORDS = '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/YTUVI01_v1.words.json'
KIND_RU = {'typo': 'ОПЕЧАТКА', 'grammar': 'ГРАММАТИКА', 'fact': 'ФАКТ-ОШИБКА', 'currency': 'ФОРМАТ ВАЛЮТЫ/ЧИСЛА',
           'language': 'АНГЛИЙСКИЙ БЕЗ ПЕРЕВОДА', 'mismatch': 'ЭКРАН ≠ ОЗВУЧКА', 'design': 'ВЁРСТКА', 'other': 'ПРАВКА'}
FIXABLE = {'typo', 'grammar', 'currency', 'fact'}        # где рисуем правильную плашку на V3

ws = []
for seg in json.load(open(WORDS, encoding='utf-8'))['segments']:
    for w in seg.get('words') or []:
        ws.append((w['w'], float(w['s'])))


def anchor(t0, t1):
    return ' '.join(w for w, s in ws if t0 - 2 <= s <= t1 + 2)[:160]


def tc(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


data = json.load(open(W6 / 'audit_findings_v6.json'))
conf = [f for f in data['confirmed'] if f.get('confirmed', True)]
print('confirmed findings:', len(conf))

pr = json.load(open(M / 'pravki_v2.json'))
allp = [p for p in pr['all'] if p.get('source') != 'audit_v6']          # идемпотентность
base_n = len(allp)

by_screen = {}
for f in conf:
    by_screen.setdefault(f['screen_id'], []).append(f)

annotations, new_tz, existing_ann = [], [], {}
for sid, fs in sorted(by_screen.items(), key=lambda kv: kv[1][0]['t0']):
    fs.sort(key=lambda f: {'high': 0, 'medium': 1, 'low': 2}[f['severity']])
    ex = next((f['existing_tz'] for f in fs if re.match(r'ТЗ-\d\d', f.get('existing_tz') or '')), None)
    t0, t1 = fs[0]['t0'], max(f['t1'] for f in fs)
    if ex:
        k = existing_ann.get(ex, 0)
        existing_ann[ex] = k + 1
        num = f'{ex}{"bcdefgh"[k]}'                       # ТЗ-21b, ТЗ-21c …
    else:
        num = f'ТЗ-{base_n + len(new_tz) + 1:02d}'
    lines = []
    for f in fs:
        fix = f.get('fix_text_final') or f.get('fix_text') or ''
        lines.append(f"[{KIND_RU.get(f['kind'], 'ПРАВКА')}] «{f['on_screen_text']}»"
                     + (f" → «{fix}»" if fix else '') + f". {f['problem']}"
                     + (f" Источник: {f['evidence']}" if f.get('evidence') else ''))
    # главная находка экрана: сначала та, у которой есть нарисованное исправление, потом по severity
    fs.sort(key=lambda f: (0 if f.get('fix_draw') else 1, {'high': 0, 'medium': 1, 'low': 2}[f['severity']]))
    main = fs[0]
    fix_main = main.get('fix_text_final') or main.get('fix_text') or ''
    # рисуем исправление только если есть fix_draw (или короткий fix у FIXABLE и fix_draw не запрещён)
    draws = bool(main.get('fix_draw')) or ('fix_draw' not in main and main['kind'] in FIXABLE and fix_main and len(fix_main) <= 60)
    if not ex:
        title = f"{KIND_RU.get(main['kind'], 'ПРАВКА')}: «{main['on_screen_text'][:38]}»" + ('…' if len(main['on_screen_text']) > 38 else '')
        entry = {
            'notes': ['audit_v6'], 'v1_tc': tc(t0), 'tc_range': f'{tc(t0)}–{tc(t1)}',
            'title': title, 'category': 'graphics', 'source': 'audit_v6',
            'est': f"На экране @{tc(t0)}: «{main['on_screen_text']}».",
            'nado': ('\n'.join(lines) + f"\nЯкорь озвучки: «{anchor(t0, t1)}»."
                     + (f"\nДрафт исправления — на V3 (fix_{num.replace('ТЗ-', 'tz')}.png), стрелка — на V5." if draws else '\nСтрелка «где ошибка» — на V5.')),
            'material_rich': [{'t': f'Кадр {tc(t0)} с отметкой ошибки (стрелка)', 'img': f'v6_err_{sid}.jpg'}]
                             + ([{'t': f'Драфт исправленного титра ({(main.get("fix_draw") or fix_main)[:40]})', 'img': f'fix_{num.replace("ТЗ-", "tz")}.png'}]
                                if draws else []),
            'sheet_answer': '', 'decision': '',
        }
        new_tz.append(entry)
    bb = main.get('bbox_final') or main['bbox']
    annotations.append({
        'tz': num, 'kind': main['kind'], 'screen_id': sid, 't0': t0, 't1': t1, 'frame': main['frame'],
        'bbox': [bb['x'], bb['y'], bb['w'], bb['h']],
        'text': (f"«{main['on_screen_text'][:60]}» → «{fix_main[:60]}»" if fix_main else main['problem'][:120]),
        'fix': ({'text': main['fix_draw']} if main.get('fix_draw') else
                (None if 'fix_draw' in main else
                 ({'text': fix_main} if main['kind'] in FIXABLE and fix_main and len(fix_main) <= 60 else None))),
        'existing': bool(ex),
    })

pr['all'] = allp + new_tz
json.dump(pr, open(M / 'pravki_v2.json', 'w'), ensure_ascii=False, indent=1)
print(f'pravki: {base_n} + {len(new_tz)} новых ТЗ (ТЗ-{base_n + 1:02d}…ТЗ-{base_n + len(new_tz):02d}); стрелок: {len(annotations)}'
      f' (к существующим ТЗ: {sum(1 for a in annotations if a["existing"])})')

# размещения на таймлайне: стрелка V5 на t0 экрана (≤4.8 с), исправление V3 — там же
placements = []
for a in annotations:
    # ставим на секунду КАДРА, который смотрел агент (титр уже дописан), а не на старт анимации
    m = re.search(r'h(\d{4})\.jpg$', a['frame'])
    t = float(int(m.group(1)) - 1) if m else float(a['t0'])
    t = max(t, float(a['t0']))
    dur = min(4.8, max(3.0, a['t1'] - t + 1.0))
    fn = a['tz'].replace('ТЗ-', 'tz')
    placements.append({'sid': f'v5_ann_{fn}', 'track': 'V5', 'png': f'ann_{fn}.png', 't': t, 'dur': dur})
    if a['fix']:
        placements.append({'sid': f'v3_fix_{fn}', 'track': 'V3', 'png': f'fix_{fn}.png', 't': t, 'dur': dur})
json.dump({'annotations': annotations, 'placements': placements, 'new_tz_from': base_n + 1,
           'new_tz_count': len(new_tz)}, open(W6 / 'audit_v6.json', 'w'), ensure_ascii=False, indent=1)
print('audit_v6.json →', len(placements), 'размещений')

# кадры ошибок (чистые; композит со стрелкой делает s9 после рендера G)
for a in annotations:
    src = Path(a['frame'])
    dst = ERR / f'v6_err_{a["screen_id"]}.jpg'
    if src.exists() and not dst.exists():
        subprocess.run(['cp', str(src), str(dst)], check=True)
print('кадры →', ERR)
