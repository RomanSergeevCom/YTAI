#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кодовый страж listify-polish (YTUVI01 Review v7).

usage: python3 guard_v7.py PROPOSAL.json [DATA.json]
  PROPOSAL.json: {"ТЗ-NN": {<parts_replace>}, ...}
  DATA.json (по умолчанию lint_tz_parts.json рядом): оригиналы {"ТЗ-NN": {"parts": {...}, ...}}
Печатает HARD (блокирует) и WARN (на суд проверяющего) по каждому ТЗ; exit 0, если HARD нет.
HARD: потерянные/новые таймкоды, потерянные ссылки, сохранено <95% содержательных слов, строка с ≥2 таймкодами
(диапазон «a–b» = один), неверная структура, нет обязательного фрагмента.
"""
import json
import re
import sys
from pathlib import Path

TC1 = re.compile(r'(?<![\d:])\d{1,2}:\d{2}(?![\d:])')
TCR = re.compile(r'(?<![\d:])\d{1,2}:\d{2}(?:\s*[–-]\s*\d{1,2}:\d{2})?(?![\d:])')
URL = re.compile(r'https?://[^\s;,)»"]+')
KEYS = {'now', 'do', 'list', 'where', 'src', 'tl'}
# фикстура YTUVI01: фрагменты, которые правка обязана сохранить. Требуются только если они ЕСТЬ в оригинале этой
# ТЗ — у другого фильма номер ТЗ-12 не про «23.976».
MUST = {'ТЗ-12': ['23.976', 'Interpret'], 'ТЗ-17': ['оставить ВТОРОЙ', '25:48']}


def strings(parts, errs=None):
    out = []
    for k, v in (parts or {}).items():
        if errs is not None and k not in KEYS:
            errs.append(f'лишний блок «{k}» (можно только {sorted(KEYS)})')
        for el in v or []:
            if isinstance(el, str):
                out.append(el)
            elif isinstance(el, dict):
                if el.get('h'):
                    out.append(el['h'])
                its = el.get('items')
                if isinstance(its, list):
                    out += [str(x) for x in its]
                elif isinstance(its, str) and its.startswith('@prog:'):
                    pass
                elif errs is not None:
                    errs.append(f'в элементе с h={el.get("h")!r} нет списка items')
            elif errs is not None:
                errs.append(f'элемент не строка и не {{h, items}}: {el!r}'[:120])
    return out


def words(s):
    return {w for w in re.findall(r'\w+', s.lower()) if len(w) >= 4}


def guard(num, orig_parts, prop):
    hard, warn = [], []
    so = '\n'.join(strings(orig_parts))
    sp_list = strings(prop, hard)
    sp = '\n'.join(sp_list)
    to, tp = set(TC1.findall(so)), set(TC1.findall(sp))
    if to - tp:
        hard.append('потеряны таймкоды: ' + ', '.join(sorted(to - tp)))
    if tp - to:
        hard.append('новые таймкоды (их не было): ' + ', '.join(sorted(tp - to)))
    uo, up = set(URL.findall(so)), set(URL.findall(sp))
    if uo - up:
        hard.append('потеряны ссылки: ' + ' '.join(sorted(uo - up)))
    wo, wp = words(so), words(sp)
    kept = len(wo & wp) / max(1, len(wo))
    if kept < 0.95:
        hard.append(f'сохранено слов {kept:.0%} (<95%), потеряны: ' + ', '.join(sorted(wo - wp)[:25]))
    added = sorted(wp - wo)
    if len(added) > max(6, 0.15 * len(wp)):
        warn.append('много новых слов (проверь, не выдумано ли): ' + ', '.join(added[:30]))
    for s in sp_list:
        if len(TCR.findall(s)) >= 2:
            hard.append('≥2 таймкода в одной строке: ' + s[:140])
        if len(s) > 230 and not s.lstrip('▸ ').startswith('http'):
            warn.append(f'длинная строка ({len(s)} зн.): ' + s[:100] + '…')
    for lit in MUST.get(num, []):
        if lit in so and lit not in sp:
            hard.append('нет обязательного фрагмента: ' + lit)
    return hard, warn


if __name__ == '__main__':
    prop = json.load(open(sys.argv[1]))
    data = json.load(open(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / 'lint_tz_parts.json'))
    bad = 0
    for num, pr in prop.items():
        if num not in data:
            print(f'❌ {num}: нет в данных')
            bad += 1
            continue
        hard, warn = guard(num, data[num]['parts'], pr)
        print(('❌' if hard else '✅'), num)
        for h in hard:
            print('   HARD:', h)
        for w in warn:
            print('   warn:', w)
        bad += bool(hard)
    print('GUARD OK' if not bad else f'GUARD FAIL: {bad}')
    sys.exit(1 if bad else 0)
