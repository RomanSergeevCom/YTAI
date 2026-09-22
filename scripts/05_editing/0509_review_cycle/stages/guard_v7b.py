#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кодовый страж второго прохода (финальный QA → правки текста ТЗ). usage: guard_v7b.py PROPOSAL.json [DATA.json]
PROPOSAL.json: {"ТЗ-NN": {<parts_replace>}}; DATA — r3_data.json рядом (оригиналы parts).
HARD: ≥2 таймкодов в строке; потеряны таймкоды (кроме ALLOW_TC); сохранено <88% содержательных слов; структура; обязательные фрагменты.
warn: новые таймкоды; потерянные ссылки; таймкод не в начале строки; <95% слов; много новых слов."""
import json
import re
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'shared'))
    from i18n import LANG  # noqa: E402
except Exception:                                   # noqa: BLE001 — страж должен работать и без карточки
    LANG = 'ru'

TC1 = re.compile(r'(?<![\d:])\d{1,2}:\d{2}(?![\d:])')
TCR = re.compile(r'(?<![\d:])~?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?(?![\d:])')
URL = re.compile(r'https?://[^\s;,)»"]+')
KEYS = {'now', 'do', 'list', 'where', 'src', 'tl'}
# фикстуры YTUVI01. MUST — фрагменты, которые правка обязана сохранить: требуются, только если они ЕСТЬ в оригинале.
# ALLOW_TC (потеря таймкода → warn, а не HARD) — номера ТЗ русского фильма: в EN не применяются (страж строже).
MUST = {'ТЗ-12': ['23.976', 'Interpret'], 'ТЗ-17': ['оставить ВТОРОЙ', '25:48'], 'ТЗ-30': ['КАРТА ВЫПУСКА']}
ALLOW_TC = {'ТЗ-04', 'ТЗ-07', 'ТЗ-10', 'ТЗ-17', 'ТЗ-37', 'ТЗ-38', 'ТЗ-55', 'ТЗ-71', 'ТЗ-73', 'ТЗ-23', 'ТЗ-41'}
if LANG == 'en':
    ALLOW_TC = set()


def strings(parts, errs=None):
    out = []
    for k, v in (parts or {}).items():
        if errs is not None and k not in KEYS:
            errs.append(f'лишний блок «{k}»')
        if errs is not None and not isinstance(v, list):
            errs.append(f'блок «{k}» не список')
            continue
        for el in v or []:
            if isinstance(el, str):
                out.append(el)
            elif isinstance(el, dict):
                if el.get('h'):
                    out.append(el['h'])
                its = el.get('items')
                if isinstance(its, list):
                    out += [str(x) for x in its]
                elif not (isinstance(its, str) and its.startswith('@prog:')) and errs is not None:
                    errs.append(f'в элементе h={el.get("h")!r} нет списка items')
            elif errs is not None:
                errs.append(f'элемент не строка и не {{h, items}}: {el!r}'[:120])
    return out


def words(s):
    return {w for w in re.findall(r'\w+', s.lower()) if len(w) >= 4}


def guard(num, orig, prop):
    hard, warn = [], []
    so = '\n'.join(strings(orig))
    sp_list = strings(prop, hard)
    sp = '\n'.join(sp_list)
    to, tp = set(TC1.findall(so)), set(TC1.findall(sp))
    if to - tp:
        (warn if num in ALLOW_TC else hard).append('потеряны таймкоды: ' + ', '.join(sorted(to - tp)))
    if tp - to:
        warn.append('новые таймкоды: ' + ', '.join(sorted(tp - to)))
    uo, up = set(URL.findall(so)), set(URL.findall(sp))
    if uo - up:
        warn.append('потеряны ссылки: ' + ' '.join(sorted(uo - up)))
    wo, wp = words(so), words(sp)
    kept = len(wo & wp) / max(1, len(wo))
    if kept < 0.88:
        hard.append(f'сохранено слов {kept:.0%} (<88%), потеряны: ' + ', '.join(sorted(wo - wp)[:30]))
    elif kept < 0.95:
        warn.append(f'сохранено слов {kept:.0%}, потеряны: ' + ', '.join(sorted(wo - wp)[:30]))
    added = sorted(wp - wo)
    if len(added) > max(8, 0.2 * len(wp)):
        warn.append('много новых слов (не выдумано ли?): ' + ', '.join(added[:30]))
    if 'do' not in prop or not strings({'do': prop.get('do')}):
        hard.append('нет блока «Как надо»')
    for s in sp_list:
        s0 = s.strip()
        if len(TCR.findall(s0)) >= 2:
            hard.append('≥2 таймкода в одной строке: ' + s0[:140])
        m = TCR.search(s0)
        if m and m.start() > 2 and not s0.lstrip('@~').startswith(m.group(0).lstrip('~')):
            warn.append('таймкод не в начале строки: ' + s0[:120])
        if len(s0) > 230 and not s0.lstrip('▸ ').startswith('http'):
            warn.append(f'длинная строка ({len(s0)} зн.): ' + s0[:90] + '…')
    for lit in MUST.get(num, []):
        if lit in so and lit not in sp:
            hard.append('нет обязательного фрагмента: ' + lit)
    return hard, warn


if __name__ == '__main__':
    prop = json.load(open(sys.argv[1]))
    data = json.load(open(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).parent / 'r3_data.json'))
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
