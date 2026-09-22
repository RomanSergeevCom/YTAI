#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polish_todo.py — вход для локальной полировки ТЗ (s14) из lint_v7.json, без облака.

Раньше local_todo.json / r3_data.json собирал облачный QA (wf_final_doc_qa → apply). Теперь:
  lint_v7.json  {"ТЗ-NN": {"multi": [строки с ≥2 таймкодами], "long": [строки >220 знаков]}}
  pravki        parts каждой ТЗ ({now:[…], do:[…], list:[…], where:[…], …})
→ W6/polish/local_todo.json {"ТЗ-NN": [{"text", "block", "kind": "h"|"i"|"s"}]}
→ W6/polish/r3_data.json    {"ТЗ-NN": {"parts": …}}      (оригиналы для s14 и guard_v7b)

usage: polish_todo.py            (карточка — через YTAI_CARD / поиск)
Печатает: сколько ТЗ и строк ушло в полировку; exit 0 всегда (0 строк — тоже нормально).
"""
import json
import sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT, LANG  # noqa: E402

SP = W6 / 'polish'
SP.mkdir(parents=True, exist_ok=True)


import re

LABEL = re.compile(r'^\s*(?:[^\w«(]{0,3}\s*)?(?:СЕЙЧАС|СДЕЛАТЬ|СПИСОК|ГДЕ|ИСТОЧНИК|НА ТАЙМЛАЙНЕ|РОМА|ПОЧЕМУ)\s*[·:—-]\s*', re.I)


def norm(s):
    """Строка lint хранится с меткой блока («▶ СДЕЛАТЬ · …»), в parts — без; сравниваем по очищенной форме."""
    s = LABEL.sub('', str(s)).strip()
    return re.sub(r'\s+', ' ', s)


def locate(parts, line):
    """(block, kind, оригинальная строка parts): 's' — голая строка блока, 'h' — заголовок группы, 'i' — пункт."""
    target = norm(line)
    for block, elems in (parts or {}).items():
        if not isinstance(elems, list):
            continue
        for el in elems:
            if isinstance(el, str) and (el == line or norm(el) == target):
                return block, 's', el
            if isinstance(el, dict):
                if el.get('h') and (el['h'] == line or norm(el['h']) == target):
                    return block, 'h', el['h']
                if isinstance(el.get('items'), list):
                    for it in el['items']:
                        if isinstance(it, str) and (it == line or norm(it) == target):
                            return block, 'i', it
    return None, None, None


def main():
    if LANG == 'en':
        # локальная полировка — русский промпт Qwen; в EN остаётся только кодовый lint/guard.
        # «строк 0» — сигнал review.py st_polish: s14/merge не запускать
        print('EN: local polish skipped (guard only)')
        print('polish todo: ТЗ 0, строк 0 (EN)')
        return 0
    lint_p = W6 / 'lint_v7.json'
    if not lint_p.exists():
        print('lint_v7.json нет — сначала s10_format_tz.py')
        return 0
    lint = json.load(open(lint_p, encoding='utf-8'))
    pr = json.load(open(M / 'pravki_v2.json', encoding='utf-8'))['all']
    by_num = {f'ТЗ-{i + 1:02d}': p for i, p in enumerate(pr)}
    todo, data, lost = {}, {}, []
    for num, v in lint.items():
        if not isinstance(v, dict):
            continue
        p = by_num.get(num)
        if not p or p.get('status') == 'rejected':
            continue
        lines = [ln for ln in (v.get('long') or []) + (v.get('multi') or []) if isinstance(ln, str)]
        entries = []
        for ln in dict.fromkeys(lines):
            block, kind, orig = locate(p.get('parts'), ln)
            if block is None:
                lost.append((num, ln[:60]))
                continue
            entries.append({'text': orig, 'block': block, 'kind': kind})   # текст — как в parts, чтобы s14 нашёл место
        if entries:
            todo[num] = entries
            data[num] = {'parts': p.get('parts') or {}}
    P.write_json_atomic(SP / 'local_todo.json', todo)
    P.write_json_atomic(SP / 'r3_data.json', data)
    print(f'polish todo: ТЗ {len(todo)}, строк {sum(len(x) for x in todo.values())}, не найдено в parts: {len(lost)}'
          + (f' (например {lost[0]})' if lost else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
