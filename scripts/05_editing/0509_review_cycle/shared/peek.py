#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peek.py — сводка большого JSON/JSONL без затягивания его в контекст сессии.

    peek.py <file.json|.jsonl> [--path a.b.0] [--n 2] [--keys] [--grep text] [--max 2000]

Печатает: размер файла, тип/длину корня, ключи (с типами и длинами), первые N записей
(усечённо), при --path — то же для вложенного узла; при --grep — записи, где встречается
текст (усечённые), не больше --max символов на весь вывод. Правило гигиены: JSON > 50 КБ
читать только так.
"""
import argparse
import json
import sys
from pathlib import Path


def load(path):
    p = Path(path)
    if p.suffix == '.jsonl':
        rows = []
        with open(p, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        rows.append({'_raw': line[:200]})
        return rows
    return json.loads(p.read_text(encoding='utf-8'))


def walk(obj, path):
    for part in [x for x in path.split('.') if x]:
        if isinstance(obj, list):
            obj = obj[int(part)]
        else:
            obj = obj[part]
    return obj


def short(v, n=140):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + '…'


def describe(obj, n):
    out = []
    if isinstance(obj, dict):
        out.append(f'dict · {len(obj)} ключей')
        for k, v in list(obj.items())[:60]:
            ln = f' · {len(v)}' if hasattr(v, '__len__') and not isinstance(v, str) else ''
            out.append(f'  {k}: {type(v).__name__}{ln}  {short(v, 90)}')
    elif isinstance(obj, list):
        out.append(f'list · {len(obj)} записей')
        if obj and isinstance(obj[0], dict):
            keys = {}
            for r in obj[:200]:
                for k in r:
                    keys[k] = keys.get(k, 0) + 1
            out.append('  ключи записей: ' + ', '.join(f'{k}({c})' for k, c in list(keys.items())[:40]))
        for r in obj[:n]:
            out.append('  - ' + short(r, 400))
    else:
        out.append(f'{type(obj).__name__}: {short(obj, 300)}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--path', default='')
    ap.add_argument('--n', type=int, default=2)
    ap.add_argument('--grep')
    ap.add_argument('--max', type=int, default=2000)
    a = ap.parse_args()
    size = Path(a.file).stat().st_size
    obj = load(a.file)
    lines = [f'{a.file} · {size // 1024} КБ']
    node = walk(obj, a.path) if a.path else obj
    if a.path:
        lines.append(f'узел {a.path}:')
    lines += describe(node, a.n)
    if a.grep:
        hits = []
        items = node if isinstance(node, list) else (list(node.values()) if isinstance(node, dict) else [node])
        for i, r in enumerate(items):
            s = json.dumps(r, ensure_ascii=False)
            if a.grep.lower() in s.lower():
                hits.append(f'  [{i}] ' + short(r, 300))
        lines.append(f'grep «{a.grep}»: {len(hits)} записей')
        lines += hits[:a.n * 3]
    text = '\n'.join(lines)
    print(text if len(text) <= a.max else text[:a.max] + f'\n… (обрезано до {a.max} символов)')


if __name__ == '__main__':
    sys.exit(main())
