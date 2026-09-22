#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7 S13: снять правки Романа во вкладке «ТЗ монтажёру · v3» ДО любой регенерации.

Роман правит вкладку прямо в доке (удаляет строки «не менять», дописывает комменты), а регенерация
вкладки его правки стирает. Скрипт сравнивает ТЕКУЩУЮ вкладку с тем, что сгенерировала последняя
сборка: чистая часть doc_tab_tz_v3.py исполняется на снимке (скрипт + pravki + ids) из папки BK,
т.е. «ожидаемый» текст = ровно то, что вставила сборка. Док только читается.

Выход: doc_edits_<rev>.json + печать: пропавшие/лишние строки таблицы, построчный диф ячеек
(ТЗ / материал / TC), диф шапки, Drive-комменты после SINCE. Переносить в pravki руками:
удалённая строка ТЗ → status: rejected; дописка → roman_comment; удалённая строка внутри ТЗ →
правка текста (overrides).

usage: s13_doc_edits.py [SINCE_ISO_UTC]                 — ожидаемое = build_rows() текущего сборщика по ТЕКУЩЕМУ
                                                           pravki (запускать ДО любых правок pravki после сборки дока)
       s13_doc_edits.py --bk BACKUP_DIR [SINCE_ISO_UTC] — ожидаемое = чистая часть сборщика на снимке (как 10.09:
                                                           сборщик v6 без build_rows)
"""
import difflib
import json
import sys
import urllib.parse
import os
import urllib.request
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402
from doctab_lib import DOCS, access_token, get_doc, iter_tabs  # noqa: E402


ARGS = sys.argv[1:]
BK = Path(ARGS[ARGS.index('--bk') + 1]) if '--bk' in ARGS else None
REST = [a for i, a in enumerate(ARGS) if a != '--bk' and (i == 0 or ARGS[i - 1] != '--bk')]
# SINCE — момент сборки вкладки ЭТОГО проекта; без него правки считаются с чужой даты
SINCE = REST[0] if REST else P.need('tab_built_at')
# Было DOCS['01']: снимали бы правки из дока первого видео и ставили status: rejected
# тем ТЗ нового проекта, у которых совпал номер — тихая порча брифа.
DOC_ID = P.need('doc_id')
TAB_TITLE = os.environ.get('TZ_TAB') or P.need('tab_title')


def expected():
    """→ (HDR, строки таблицы [5 ячеек], абзацы шапки) — то, что вставил бы сборщик."""
    if BK is None:                                          # v7+: чистая функция сборщика

        import doc_tab_tz_v3 as D
        rows, head = D.build_rows(*D.load())
        return D.HDR, [r['cells'] for r in rows], [t for _, t, _ in head]
    # снимок сборщика v6 (без build_rows): исполнить чистую часть до создания вкладки + блок шапки
    src = (BK / 'doc_tab_tz_v3.py').read_text()
    pure = src.split('# ── вкладка ──')[0]
    head = src[src.index('decisions = ['):src.index('HEAD = {1:')]
    ns = {'__file__': str(BK / 'doc_tab_tz_v3.py'), '__name__': 'expected'}
    exec(compile(pure, 'doc_tab_tz_v3[pure]', 'exec'), ns)
    exec(compile(head, 'doc_tab_tz_v3[head]', 'exec'), ns)
    return ns['HDR'], ns['table'], [t for _, t, _ in ns['HEADP']]


def cell_text(cell):
    out = []
    for c in cell.get('content', []):
        for e in c.get('paragraph', {}).get('elements', []):
            if 'textRun' in e:
                out.append(e['textRun'].get('content', ''))
    return ''.join(out).rstrip('\n')


def row_key(cells):
    k = cells[0].strip()
    if k:
        return k
    # строка-главы: метка лежит в колонке «Описание ошибки» (до 22.09.2026 — в колонке 3)
    return 'CH:' + next((c.strip() for c in cells[3:] if c.strip()), '')


def api_get(url):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access_token()}'})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


HDR, exp_table, exp_head = expected()
exp_rows = {row_key([str(c) for c in r]): [str(c) for c in r] for r in exp_table}

doc = get_doc(DOC_ID)
tab = next(t for t in iter_tabs(doc) if t['tabProperties'].get('title') == TAB_TITLE)
body = tab['documentTab']['body']['content']
tables = [el for el in body if 'table' in el]
assert len(tables) == 1, f'таблиц во вкладке: {len(tables)}'
act_head = []
for el in body:
    if 'table' in el:
        break
    t = ''.join(e.get('textRun', {}).get('content', '') for e in el.get('paragraph', {}).get('elements', [])).rstrip('\n')
    if t:
        act_head.append(t)
act_rows, act_order = {}, []
for r in tables[0]['table']['tableRows'][1:]:
    cells = [cell_text(c) for c in r['tableCells']]
    k = row_key(cells)
    act_rows[k] = cells
    act_order.append(k)

rep = {'since': SINCE, 'missing_rows': [], 'extra_rows': [], 'cells': {}, 'head': [], 'comments': [], 'revisions': []}
for k in exp_rows:
    if k not in act_rows:
        rep['missing_rows'].append(k)
for k in act_rows:
    if k not in exp_rows:
        rep['extra_rows'].append({'key': k, 'cells': act_rows[k]})
# v5 22.09.2026: № | TC | кат. | Говорит | Комментарии Романа | ✅ | Описание ошибки | Материал | Как надо.
# «Говорит» (3) не читаем — это речь ката из words.json, Роман её не правит. Зато читаем его
# собственную колонку (4) и чекбокс приёмки (5): раньше их просто не существовало, и всё, что он
# дописывал, система видела только внутри общей ячейки ТЗ.
COLS = {1: 'tc', 4: 'roman', 5: 'accepted', 6: 'tz', 7: 'material', 8: 'do'}
for k, exp in exp_rows.items():
    act = act_rows.get(k)
    if not act:
        continue
    if len(act) != len(exp):              # вкладка собрана старым сборщиком (5 колонок, до «Говорит»)
        print(f'  !! {k}: колонок в доке {len(act)}, у сборщика {len(exp)} — снимай правки кодом той же версии')
        continue
    for ci, name in COLS.items():
        a, b = exp[ci].split('\n'), act[ci].split('\n')
        if a == b:
            continue
        removed, added = [], []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op in ('delete', 'replace'):
                removed += a[i1:i2]
            if op in ('insert', 'replace'):
                added += b[j1:j2]
        rep['cells'].setdefault(k, {})[name] = {'removed': removed, 'added': added}
if exp_head != act_head:
    rep['head'] = [ln for ln in difflib.unified_diff(exp_head, act_head, 'expected', 'actual', lineterm='', n=0)]

cm = api_get(f'https://www.googleapis.com/drive/v3/files/{DOC_ID}/comments?' + urllib.parse.urlencode({
    'fields': 'comments(id,createdTime,modifiedTime,content,resolved,quotedFileContent/value,replies(createdTime,content))',
    'pageSize': 100, 'startModifiedTime': SINCE, 'includeDeleted': 'false'}))
rep['comments'] = cm.get('comments', [])
rv = api_get(f'https://www.googleapis.com/drive/v3/files/{DOC_ID}/revisions?fields=revisions(id,modifiedTime)&pageSize=1000')
rep['revisions'] = [x for x in rv.get('revisions', []) if x['modifiedTime'] >= SINCE]

last = rep['revisions'][-1]['id'] if rep['revisions'] else 'none'
out = W6 / f'doc_edits_{last}.json'
json.dump(rep, open(out, 'w'), ensure_ascii=False, indent=1)

print(f'ожидаемых строк {len(exp_rows)} · в доке {len(act_rows)} · ревизий после {SINCE}: '
      f'{[r["id"] + " " + r["modifiedTime"] for r in rep["revisions"]]}')
print('ПРОПАЛИ строки:', rep['missing_rows'] or '—')
print('ЛИШНИЕ строки:', [x['key'] for x in rep['extra_rows']] or '—')
for k, d in rep['cells'].items():
    for col, dd in d.items():
        print(f'\n■ {k} [{col}]')
        for ln in dd['removed']:
            print('   − ' + ln[:300])
        for ln in dd['added']:
            print('   + ' + ln[:300])
if rep['head']:
    print('\n■ ШАПКА:\n' + '\n'.join(rep['head'][:40]))
print(f'\nDrive-комментов после {SINCE}: {len(rep["comments"])}')
for c in rep['comments']:
    print(' ', c['createdTime'], '·', c['content'][:200], '| q:', (c.get('quotedFileContent') or {}).get('value', '')[:80])
print('→', out)
