#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Машинная модель библиотеки видов экранов канала → `YTs/{CH}/screen_kinds.json`.

Зачем: виды экранов живут блоками `make_infographics_v6.py`, и до сих пор их нигде нельзя было
увидеть списком — ни монтажёру, ни Роману. Страница канала и вкладка дока собираются НЕ из
пересказа сессии, а из этого файла: цифры и имена измеряются с кода и с диска, редакторский
текст (когда применять, когда нет) живёт отдельно, в сборщике страницы.

Что считается фактом и откуда берётся:
  · буквы блоков          — `if want('X')` в исходнике рендера;
  · имена файлов вида     — литералы `page(f'…')` внутри блока;
  · одна строка про вид   — таблица видов в докстринге рендера (она же — контракт для --check);
  · сколько нарисовано    — файлы в `mockups/` по маске имени;
  · канон (поля, черта, цвета, шрифт) — профиль канала, а не литералы CSS.

`--check` (ничего не пишет) сверяет три источника: блок есть в коде → он описан в докстринге →
у него есть хоть один файл на диске. Расхождение = выход 2 со списком.

usage: screens_library.py [--check] [--out PATH]
"""
import argparse
import importlib
import json
import re
import sys
import time
from pathlib import Path

from _bootstrap import P, HERE  # noqa: E402

try:                                            # текст про виды — отдельный файл КАЖДОГО канала
    # ⚠️ раньше здесь был жёсткий `import screen_kinds_ytuvi`: на любом другом канале проверка
    # молча сверяла его тексты с чужим рендером, а собственный файл канала не читался вовсе
    TXT = importlib.import_module(f'screen_kinds_{str(P.get("channel", "")).lower()}')
except ImportError:                             # у канала текстов ещё нет: модель соберётся без них
    TXT = None

RENDER = HERE / 'make_infographics_v6.py'
ap = argparse.ArgumentParser()
ap.add_argument('--check', action='store_true', help='только сверка, файл не пишется')
ap.add_argument('--out', default='', help='куда писать (по умолчанию YTs/{CH}/screen_kinds.json)')
a = ap.parse_args()

SRC = RENDER.read_text(encoding='utf-8')
DOC = SRC.split('"""')[1] if '"""' in SRC else ''
# строка таблицы видов в докстринге: «  M. subt_NN  — титр подтемы: приём самого фильма …»
DOC_RX = re.compile(r'^\s{2}([A-Z])\.\s+(\S+(?:\s*/\s*\S+)*)\s+—\s+(.+)$', re.M)
# ⚠️ блок бывает под составным условием (`if want('E') and _E_MOHS:`) — двоеточие не требуем
WANT_RX = re.compile(r"if want\('([A-Z])'\)")
PAGE_RX = re.compile(r"page\(\s*f?'([^']+)'")


def doc_kinds():
    return {m.group(1): {'files_doc': m.group(2).strip(), 'one': m.group(3).strip()}
            for m in DOC_RX.finditer(DOC)}


def code_blocks():
    """буква блока → имена файлов, найденные прямо в вызовах page() этого блока.

    Список неполон нарочно: часть блоков печатает через свой хелпер (блок I — `_namecard`),
    и вытаскивать имя оттуда значило бы разбирать поток данных. Поэтому имена вида берутся
    из таблицы докстринга, а эти — только для сверки «в коде появилось то, чего нет в таблице»."""
    hits = [(m.group(1), m.start()) for m in WANT_RX.finditer(SRC)]
    out = {}
    for i, (letter, pos) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(SRC)
        for m in PAGE_RX.finditer(SRC, pos, end):
            nm = m.group(1)
            if nm:
                out.setdefault(letter, [])
                if nm not in out[letter]:
                    out[letter].append(nm)
        out.setdefault(letter, [])
    return out


def to_glob(tpl):
    """шаблон имени → маска файла: prog_{ch}_{k} → prog_*_*, term_<key> → term_*, fix_tzNN → fix_tz*"""
    g = re.sub(r'\{[^}]*\}', '*', str(tpl).strip())
    g = re.sub(r'<[^>]*>', '*', g)
    g = re.sub(r'NN|<N>', '*', g)
    g = re.sub(r'[A-Za-z0-9]+(?:\|[A-Za-z0-9]+)+', '*', g)     # ch_demo_a|b|c → ch_demo_*
    g = re.sub(r'\*+', '*', g)
    # ⚠️ добивать «*» нельзя: маска `*_t` превращалась в `*_t*` и подбирала ann_tz01.png —
    # блок E на 158 чужих файлов вместо своих трёх. Расширение, и только расширение.
    return g if g.endswith(('.png', '.jpg')) else g + '.png'


def doc_globs(files_doc):
    """«term_<key> / termgrp_*» → ['term_*', 'termgrp_*']"""
    return [to_glob(p) for p in re.split(r'\s*/\s*', files_doc) if p.strip()]


def main():
    mock = Path(P.MOCK)
    doc, code = doc_kinds(), code_blocks()
    problems = []
    for letter in sorted(set(doc) | set(code)):
        if letter not in code:
            problems.append(f'{letter}: описан в докстринге, но блока `want(\'{letter}\')` в коде нет')
        elif letter not in doc:
            problems.append(f'{letter}: блок есть в коде, но в таблице видов докстринга его нет')

    # порядок видов — редакторский (как в screen_kinds_ytuvi.KIND): сначала то, чем фильм живёт,
    # а не алфавит блоков. Виды без карточки текста уходят в конец по алфавиту.
    order = list(TXT.KIND) if TXT else []
    letters = [x for x in order if x in code] + sorted(set(code) - set(order))
    kinds = []
    for letter in letters:
        d = doc.get(letter, {})
        globs = doc_globs(d.get('files_doc', '')) or [to_glob(t) for t in code[letter]]
        files, sample = 0, []
        for g in globs:
            found = sorted(mock.glob(g))
            files += len(found)
            if found:
                sample.append(found[0].name)
                if len(found) > 2:
                    sample.append(found[len(found) // 2].name)
        if letter in doc and not files:
            problems.append(f'{letter}: вид описан и есть в коде, но в mockups/ ни одного файла')
        for nm in code[letter]:                     # имя из кода обязано попадать под маску таблицы
            plain = re.sub(r'\{[^}]*\}', '', nm)
            # префикс маски — без расширения: у литерального имени (info_structure_map.png)
            # иначе не совпадает ни один символ и честный блок попадает в «проблемы»
            if not any(plain.startswith(re.sub(r'\.(png|jpg)$', '', g).split('*')[0]) for g in globs):
                problems.append(f'{letter}: код печатает «{nm}», под таблицу докстринга оно не подходит')
        rec = {'block': letter, 'one': d.get('one', ''), 'files_doc': d.get('files_doc', ''),
               'globs': globs, 'code_names': code[letter], 'rendered': files,
               'examples': sample[:4]}
        ed = (TXT.KIND.get(letter) if TXT else None) or {}
        if ed:                                  # редакторская карточка перекрывает «одну строку» кода
            rec.update({'name': ed.get('name', ''), 'cat': ed.get('cat', ''),
                        'one': ed.get('one') or rec['one'], 'use': list(ed.get('use') or []),
                        'avoid': [list(x) for x in (ed.get('avoid') or [])],
                        'where': ed.get('where', ''), 'legacy': bool(ed.get('legacy'))})
            # раскладки одного вида: какая принята — из карточки фильма, а не из текста
            if ed.get('variants'):
                chosen = str(P.get(ed.get('variant_key', ''), '') or '').strip().lower()
                vs = []
                for ltr, nm, why, fn in ed['variants']:
                    if fn and not (mock / fn).exists():
                        problems.append(f'{letter}: вариант «{ltr}» описан, а файла {fn} в mockups нет')
                    vs.append({'letter': ltr, 'name': nm, 'why': why, 'file': fn,
                               'chosen': ltr == chosen})
                if chosen and not any(v['chosen'] for v in vs):
                    problems.append(f'{letter}: карточка фильма выбрала вариант «{chosen}», '
                                    f'а в тексте такого нет')
                rec['variants'] = vs
                rec['variant_key'] = ed.get('variant_key', '')
        elif TXT:
            problems.append(f'{letter}: вид есть в коде рендера, а карточки текста для него нет')
        kinds.append(rec)
    if TXT:
        for letter in sorted(set(TXT.KIND) - set(code)):
            problems.append(f'{letter}: карточка текста есть, а вида в коде рендера нет')
        cats = {c[0] for c in TXT.EDITORIAL['cats']}
        for letter, ed in TXT.KIND.items():
            if ed.get('cat') not in cats:
                problems.append(f'{letter}: категория «{ed.get("cat")}» не описана в EDITORIAL[cats]')
            for cond, repl in (ed.get('avoid') or []):
                if repl and repl not in TXT.KIND:
                    problems.append(f'{letter}: «когда НЕ» ведёт на несуществующий вид «{repl}»')

    model = {
        'schema': 'screen-kinds-v1',
        'channel': P.get('channel', ''),
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'source': {'render': str(RENDER), 'mockups': str(mock),
                   'film': {'code': P.get('code', ''), 'cut_version': P.CUT_VERSION,
                            'duration_sec': P.get('duration_sec', 0), 'film': P.get('film', '')}},
        'canon': {
            'frame': [3840, 2160],
            'margin_px': int(P.profile('style.margin_px', 148)),
            'rule': list(P.profile('style.rule') or [570, 10]),
            'ivory': P.profile('style.ivory', ''), 'red': P.profile('style.red', ''),
            'mut': P.profile('style.mut', ''), 'plate': P.profile('style.plate', ''),
            'graph': P.profile('style.graph', ''), 'bg': P.profile('style.bg', ''),
            'font_stack': P.profile('style.font_stack', ''),
        },
        'variants': {'ch_plate_variant': P.get('ch_plate_variant', 'a'),
                     'prog_variant': P.get('prog_variant', 'z')},
        'kinds': kinds,
        'editorial': (dict(TXT.EDITORIAL) if TXT else {}),
        'problems': problems,
    }

    print(f'видов в коде: {len(code)} · описано в докстринге: {len(doc)} · '
          f'нарисовано файлов: {sum(k["rendered"] for k in kinds)}')
    for p in problems:
        print('  ⨯', p)
    if a.check:
        return 2 if problems else 0
    out = Path(a.out) if a.out else (Path(P.YTS if hasattr(P, 'YTS') else Path.home() / 'YTAI/YTs')
                                     / str(P.get('channel', '')) / 'screen_kinds.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    P.write_json_atomic(out, model)
    print('→', out)
    return 2 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
