#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify вкладки «Ревью по видео · v4» (навигатор) — гейт до ALL PASS:
  1. строк = 1 шапка + главы + куски; 2. главы [скобки] + HEADING_3;
  3. ПАРТИЦИЯ: слова транскрипт-ячеек (минус подписи Света/Гуля) == слова YTCH12_v4.words.json;
  4. картинок в «Экран» = число кусков; 5. bold-прогонов ≥ принятых фраз; 6. ширины;
  7. ТЗ-номера из контента — в колонке ТЗ (синхронны с вкладкой «ТЗ монтажёру · v4»).
Usage: d4_verify.py   (док и вкладка — review_v4_doc.json + review_v4_video_tab.txt)"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import get_doc, iter_tabs  # noqa: E402

WORK = os.path.dirname(os.path.abspath(__file__))
REV = os.path.dirname(WORK)
doc_id = json.load(open(os.path.join(WORK, 'review_v4_doc.json')))['doc_id']
tab_id = open(os.path.join(WORK, 'review_v4_video_tab.txt')).read().strip()
content = json.load(open(os.path.join(WORK, 'doc_content_review_v4.json'), encoding='utf-8'))
rows_c = content['table']['rows']
n_ch = sum(r['kind'] == 'chapter' for r in rows_c)
n_row = sum(r['kind'] == 'row' for r in rows_c)
n_bold = sum(len(r.get('bold') or []) for r in rows_c if r['kind'] == 'row')
tz_all = sorted({t for r in rows_c if r['kind'] == 'row' for t in (r.get('tz') or [])})
tab = next(t for t in iter_tabs(get_doc(doc_id)) if t['tabProperties']['tabId'] == tab_id)
tbl = [el for el in tab['documentTab']['body']['content'] if 'table' in el][-1]
trs = tbl['table']['tableRows']
fails = []


def check(name, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f' — {detail}' if detail else ''))
    if not ok:
        fails.append(name)


def els(cell):
    return [e for c in cell.get('content', []) for e in c.get('paragraph', {}).get('elements', [])]


def cell_text(cell):
    return ''.join(e.get('textRun', {}).get('content', '') for e in els(cell))


check('таблица: строк', len(trs) == 1 + n_ch + n_row, f'{len(trs)} == 1+{n_ch}+{n_row}')
ch_rows = [ri for ri in range(1, len(trs)) if rows_c[ri - 1]['kind'] == 'chapter']
piece_rows = [ri for ri in range(1, len(trs)) if rows_c[ri - 1]['kind'] == 'row']
bad = []
for ri in ch_rows:
    c0 = trs[ri]['tableCells'][0]
    first = cell_text(c0).split('\n', 1)[0]
    h3 = any(el.get('paragraph', {}).get('paragraphStyle', {}).get('namedStyleType') == 'HEADING_3'
             for el in c0.get('content', []))
    if not (first.startswith('[') and first.rstrip().endswith(']') and h3):
        bad.append(ri)
check(f'главы [скобки] + HEADING_3 ({len(ch_rows)})', not bad, str(bad))
w = json.load(open(os.path.join(REV, 'YTCH12_v4.words.json'), encoding='utf-8'))


def toks(t):
    return re.findall(r'[а-яёa-z0-9]+', t.lower().replace('ё', 'е'))


LBL = re.compile(r'(?m)^(Света|Гуля): ')
wt = toks(' '.join(wd['w'] for seg in w['segments'] for wd in seg['words']))
ct = []
for ri in piece_rows:
    ct += toks(LBL.sub('', cell_text(trs[ri]['tableCells'][3])))
check('ПАРТИЦИЯ (каждое слово ровно в одной строке)', ct == wt, f'{len(ct)} == {len(wt)} токенов')
if ct != wt:
    i = next((k for k, (x, y) in enumerate(zip(wt, ct)) if x != y), min(len(wt), len(ct)))
    print(f'   первый дифф @ {i}: {wt[i - 2:i + 3]} vs {ct[i - 2:i + 3]}')
n_img = sum(sum(1 for e in els(trs[ri]['tableCells'][4]) if 'inlineObjectElement' in e) for ri in piece_rows)
check('картинок в «Экран»', n_img == n_row, f'{n_img} == {n_row}')
n_runs = sum(sum(1 for e in els(trs[ri]['tableCells'][3]) if e.get('textRun', {}).get('textStyle', {}).get('bold')
                 and e['textRun']['content'].strip()) for ri in piece_rows)
# соседние жирные диапазоны Docs склеивает в один прогон — допуск 2%
check('bold-прогонов в транскрибации', n_runs >= n_bold - max(1, n_bold // 50), f'{n_runs} ≈ {n_bold}')
got = [int(c.get('width', {}).get('magnitude', 0)) for c in tbl['table'].get('tableStyle', {}).get('tableColumnProperties', [])]
check('ширины колонок', got == content['table']['widths'], f'{got} == {content["table"]["widths"]}')
tz_doc = ' '.join(cell_text(trs[ri]['tableCells'][5]) for ri in piece_rows)
miss = [t for t in tz_all if t not in tz_doc]
check(f'ТЗ-номера в колонке ТЗ ({len(tz_all)})', not miss, ', '.join(miss[:10]))
print()
if fails:
    print('ИТОГ: FAIL —', ', '.join(fails))
    sys.exit(1)
print(f'ИТОГ: ALL PASS — {len(ch_rows)} глав, {n_row} кусков, {n_img} кадров, {n_runs} bold, {len(wt)} токенов, {len(tz_all)} ТЗ')
print(f'https://docs.google.com/document/d/{doc_id}/edit?tab={tab_id}')
