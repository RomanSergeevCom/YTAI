#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_local_fixes.py — слить результат локальной полировки (s14: polish/r3/local_fixes.json {ТЗ-NN: parts})
в pravki/tz_overrides.json как parts_replace, через кодовый страж guard_v7b (HARD блокирует ТЗ:
потерянные/выдуманные таймкоды, <88 % слов, ≥2 таймкода в строке). Аналог merge_r3.py для облачных батчей.

usage: merge_local_fixes.py [--dry]
"""
import json
import sys

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402
from guard_v7b import guard  # noqa: E402

SP = W6 / 'polish'
OV = M / 'tz_overrides.json'
DRY = '--dry' in sys.argv


def main():
    fixes_p = SP / 'r3' / 'local_fixes.json'
    data_p = SP / 'r3_data.json'
    if not fixes_p.exists() or not data_p.exists():
        print('нет polish/r3/local_fixes.json или r3_data.json — сначала polish_todo.py и s14_polish_local.py')
        return 0
    fixes = json.load(open(fixes_p, encoding='utf-8'))
    data = json.load(open(data_p, encoding='utf-8'))
    ov = json.load(open(OV, encoding='utf-8')) if OV.exists() else {}
    if ov.get('_project') and ov['_project'] != P.PROJECT:
        raise SystemExit(f'{OV}: _project={ov["_project"]!r} — чужой проект, не сливаю (карточка: {P.PROJECT})')
    ov.setdefault('_project', P.PROJECT)
    merged, blocked = [], []
    for num, parts in fixes.items():
        if num not in data:
            continue
        hard, warn = guard(num, data[num]['parts'], parts)
        if hard:
            blocked.append((num, hard[:2]))
            continue
        for k in [k for k, v in parts.items() if not v]:
            parts.pop(k)
        ov.setdefault(num, {})['parts_replace'] = parts
        merged.append(num)
        for w in warn:
            print(f'  {num} warn: {w[:110]}')
    print(f'слито: {len(merged)} {merged} · заблокировано guard: {blocked}')
    if not DRY and merged:
        P.write_json_atomic(OV, ov)
        print('→', OV)
    return 0


if __name__ == '__main__':
    sys.exit(main())
