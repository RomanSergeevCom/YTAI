#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_analysis.py — вытащить результаты многоагентного разбора из journal.jsonl воркфлоу
в один analysis.json (REVIEW_DIR), который ест build_structure_html.py (секции «находки»,
«блоки исходника», «сверка», «чего не хватало»).

Журнал указывается явно или ключом карточки `analysis_journal` — в коде путей прошлого проекта нет.
Схема результатов агентов (canon / viz / check / lens) — как в разборе YTEVO02; с лёгким
дизайном (segment_local + один агент структуры) стадия необязательна: без analysis.json
страница структуры просто не показывает эти секции.

  python3 collect_analysis.py --journal <…/workflows/wf_xxx/journal.jsonl>
  python3 collect_analysis.py            # journal из карточки (analysis_journal)
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import P, REVIEW_DIR, write_json  # noqa: E402

OUT = REVIEW_DIR / 'analysis.json'

# агенты стабильно кладут в поле n мусор (число вариантов), а настоящий номер блока
# живёт в block_title — «БЛОК 11 · …», «Блок 9 — …». Тянем оттуда.
BLOCK_N_RE = re.compile(r'бло\w*\s*№?\s*(\d{1,2})', re.I)


def real_block_n(v, canon):
    m = BLOCK_N_RE.search(v.get('block_title') or '')
    if m:
        return int(m.group(1))
    # запасной путь — сопоставить по таймкоду первого варианта с границами блоков
    tcs = [o.get('tc') for o in (v.get('options') or []) if o.get('tc')]
    if tcs and canon:
        def sec(t):
            p = re.findall(r'\d+', t or '')
            return int(p[0]) * 60 + int(p[1]) if len(p) >= 2 else -1
        t0 = sec(tcs[0])
        for b in canon.get('blocks', []):
            if sec(b.get('tc_in')) <= t0 < sec(b.get('tc_out')):
                return b.get('n')
    return v.get('n')


def collect(journal):
    canon, viz, checks, lenses = None, [], [], []
    for line in Path(journal).read_text(encoding='utf-8').splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get('type') != 'result':
            continue
        r = e.get('result')
        if not isinstance(r, dict):
            continue
        if 'logline' in r and 'blocks' in r:
            canon = r
        elif 'options' in r and 'block_title' in r:
            viz.append(r)
        elif 'verdict' in r and 'errors' in r:
            checks.append(r)
        elif 'lens' in r and 'blocks' in r:
            lenses.append(r)
    for v in viz:
        v['n'] = real_block_n(v, canon)
    seen = {}
    for v in viz:                       # если два результата сели на один блок — берём богаче
        k = v['n']
        if k not in seen or len(v.get('options') or []) > len(seen[k].get('options') or []):
            seen[k] = v
    viz = sorted(seen.values(), key=lambda v: v.get('n') or 0)
    # сверка — та, что нашла больше конкретных ошибок; критик полноты — та, что про missing
    check = max(checks, key=lambda c: len(c.get('errors') or []), default=None)
    critic = max((c for c in checks if c is not check),
                 key=lambda c: len(c.get('missing') or []), default=None)
    return {'canon': canon, 'viz': viz, 'check': check, 'critic': critic, 'lenses_count': len(lenses)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--journal', default=P.get('analysis_journal'), help='journal.jsonl воркфлоу разбора')
    a = ap.parse_args()
    if not a.journal:
        raise SystemExit('укажи --journal <journal.jsonl> (или ключ analysis_journal в карточке)')
    data = collect(Path(a.journal).expanduser())
    write_json(OUT, data)
    canon, viz, check, critic = data['canon'], data['viz'], data['check'], data['critic']
    n_opts = sum(len(v.get('options') or []) for v in viz)
    print(f"canon: {'ok' if canon else 'НЕТ'} · блоков {len(canon['blocks']) if canon else 0}")
    print(f'viz: {len(viz)} блоков · {n_opts} вариантов')
    print(f"check: {'ok' if check else '—'} ({len(check.get('errors') or []) if check else 0} ошибок)")
    print(f"critic: {'ok' if critic else '—'} ({len(critic.get('missing') or []) if critic else 0} пробелов)")
    print(f"линз: {data['lenses_count']}")
    print(f'→ {OUT}')


if __name__ == '__main__':
    main()
