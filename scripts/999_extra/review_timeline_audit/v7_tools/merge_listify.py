#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слить результаты listify-polish (final_B*.json, иначе prop_B*.json) в tz_overrides.json как parts_replace.
Перед записью — повторный guard_v7 (HARD блокирует ТЗ). Остальные ключи overrides ТЗ сохраняются.
usage: merge_listify.py [--dry]"""
import json
import sys
from pathlib import Path

SP = Path(__file__).parent
sys.path.insert(0, str(SP))
from guard_v7 import guard  # noqa: E402

OV = SP.parent / 'tz_overrides.json'        # v7_tools лежит внутри work/v6 (был путь первого видео)
DATA = json.load(open(SP / 'lint_tz_parts.json'))
DRY = '--dry' in sys.argv
ov = json.load(open(OV))
merged, blocked = [], []
for i in range(1, 8):
    f = SP / 'listify' / f'final_B{i}.json'
    if not f.exists():
        f = SP / 'listify' / f'prop_B{i}.json'
        print(f'B{i}: final нет — беру {f.name}')
    if not f.exists():
        print(f'B{i}: нет файлов')
        continue
    for num, parts in json.load(open(f)).items():
        hard, warn = guard(num, DATA[num]['parts'], parts)
        if hard:
            blocked.append((num, hard))
            continue
        for k in [k for k, v in parts.items() if not v]:
            parts.pop(k)
        ov.setdefault(num, {})['parts_replace'] = parts
        merged.append(num)
        if warn:
            print(f'  {num} warn: ' + ' | '.join(w[:90] for w in warn))
missing = sorted(set(DATA) - set(merged) - {b[0] for b in blocked})
print(f'слито: {len(merged)} {sorted(merged)}')
print(f'заблокировано guard: {[(n, h[:2]) for n, h in blocked]}')
print(f'нет результата: {missing}')
if not DRY:
    json.dump(ov, open(OV, 'w'), ensure_ascii=False, indent=1)
    print('→', OV)
