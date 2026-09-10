#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Слить второй проход (r3/final_B*.json, иначе prop_B*.json) в tz_overrides.json как parts_replace — через guard_v7b
(HARD блокирует ТЗ). Остальные ключи overrides сохраняются. Печатает warn и сводку. usage: merge_r3.py [--dry]"""
import json
import sys
from pathlib import Path

SP = Path(__file__).parent
sys.path.insert(0, str(SP))
from guard_v7b import guard  # noqa: E402

OV = Path('/Users/romansergeev/Downloads/YTUVI01_Sonya_cut/work/v6/tz_overrides.json')
DATA = json.load(open(SP / 'r3_data.json'))
BATCHES = json.load(open(SP / 'r3_batches.json'))
DRY = '--dry' in sys.argv
ov = json.load(open(OV))
merged, blocked, missing = [], [], []
for i, batch in enumerate(BATCHES, 1):
    f = SP / 'r3' / f'final_B{i}.json'
    if not f.exists():
        f = SP / 'r3' / f'prop_B{i}.json'
        print(f'B{i}: final нет — беру {f.name}')
    got = json.load(open(f)) if f.exists() else {}
    for num in batch:
        parts = got.get(num)
        if not parts:
            missing.append(num)
            continue
        hard, warn = guard(num, DATA[num]['parts'], parts)
        if hard:
            blocked.append((num, hard))
            continue
        for k in [k for k, v in parts.items() if not v]:
            parts.pop(k)
        if num in ('ТЗ-30', 'ТЗ-74', 'ТЗ-75', 'ТЗ-76'):
            parts.pop('list', None)                    # список генерирует s10
        ov.setdefault(num, {})['parts_replace'] = parts
        merged.append(num)
        for w in warn:
            print(f'  {num} warn: {w[:110]}')
print(f'\nслито: {len(merged)}')
print(f'заблокировано guard: {[(n, h[:2]) for n, h in blocked]}')
print(f'нет результата: {missing}')
if not DRY:
    json.dump(ov, open(OV, 'w'), ensure_ascii=False, indent=1)
    print('→', OV)
