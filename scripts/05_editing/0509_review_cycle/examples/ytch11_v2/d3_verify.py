#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Верификация дока «YTCH11_Review_v2_video» (гейт 1 тикета) — до ALL PASS.

Проверки:
  1. Таблица найдена, строк = 1 шапка + 15 глав + 57 кусков.
  2. Глав ровно 15, label каждой = [скобки] и стоит HEADING_3 (оглавление).
  3. ПАРТИЦИЯ: слова всех транскрипт-ячеек (минус подписи спикеров) ==
     слова YTCH11_v2.words.json — каждое слово ровно в одной строке.
  4. Картинок в колонке «Экран» = 57 (по одной на кусок).
  5. Bold-диапазонов в транскрибации >= числа принятых опорных фраз.
  6. Ширины колонок = из контента.
Usage: python3 d3_verify.py [doc_id]  (default: из review_v2_doc_id.txt)"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import api  # noqa: E402

WORK = os.path.dirname(os.path.abspath(__file__))
S = os.path.dirname(WORK)
doc_id = sys.argv[1] if len(sys.argv) > 1 else \
    open(os.path.join(WORK, 'review_v2_doc_id.txt')).read().strip()
content = json.load(open(os.path.join(WORK, 'doc_content_review_v2.json')))
final = json.load(open(os.path.join(WORK, 'review_rows_final.json')))
rows_c = content['table']['rows']
n_ch = sum(1 for r in rows_c if r['kind'] == 'chapter')
n_row = sum(1 for r in rows_c if r['kind'] == 'row')
n_bold = sum(len(r.get('bold') or []) for r in rows_c if r['kind'] == 'row')

doc = api('GET', f'https://docs.googleapis.com/v1/documents/{doc_id}')
body = doc['body']['content']
tbl = [el for el in body if 'table' in el][-1]
trs = tbl['table']['tableRows']

fails = []


def check(name, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f' — {detail}' if detail else ''))
    if not ok:
        fails.append(name)


def cell_text(cell):
    out = []
    for el in cell.get('content', []):
        for pe in el.get('paragraph', {}).get('elements', []):
            out.append(pe.get('textRun', {}).get('content', ''))
    return ''.join(out)


def cell_imgs(cell):
    n = 0
    for el in cell.get('content', []):
        for pe in el.get('paragraph', {}).get('elements', []):
            if 'inlineObjectElement' in pe:
                n += 1
    return n


def cell_bold_runs(cell):
    n = 0
    for el in cell.get('content', []):
        for pe in el.get('paragraph', {}).get('elements', []):
            tr = pe.get('textRun')
            if tr and tr.get('textStyle', {}).get('bold') and tr['content'].strip():
                n += 1
    return n


# 1. размер таблицы
check('таблица: строк', len(trs) == 1 + n_ch + n_row,
      f'{len(trs)} == 1+{n_ch}+{n_row}')

# померженные главы: ячейка 0 содержит label; главы = строки где ячеек меньше
# (merge) либо текст начинается с '['
ch_rows, piece_rows = [], []
for ri in range(1, len(trs)):
    kind = rows_c[ri - 1]['kind']
    (ch_rows if kind == 'chapter' else piece_rows).append(ri)
check('глав', len(ch_rows) == 15, str(len(ch_rows)))

# 2. label глав: [скобки] + HEADING_3 на label-параграфе
bad_lbl = []
for ri in ch_rows:
    c0 = trs[ri]['tableCells'][0]
    txt = cell_text(c0)
    first = txt.split('\n', 1)[0]
    h3 = any(el.get('paragraph', {}).get('paragraphStyle', {})
             .get('namedStyleType') == 'HEADING_3'
             for el in c0.get('content', []))
    if not (first.startswith('[') and first.rstrip().endswith(']') and h3):
        bad_lbl.append(ri)
check('label глав ([скобки] + HEADING_3)', not bad_lbl, str(bad_lbl))

# 3. партиция слов
w = json.load(open(os.path.join(S, 'YTCH11_v2.words.json')))
flatw = [wd['w'] for seg in w['segments'] for wd in seg['words']]


def toks(t):
    return re.findall(r'[А-Яа-яЁёA-Za-z0-9]+', t.lower().replace('ё', 'е'))


LBL = re.compile(r'(?m)^(Лиза|Виталик|Гуля|Маша|Люба|Роман \(ЗК\)): ')
wt = toks(' '.join(flatw))
ct = []
for ri in piece_rows:
    ct += toks(LBL.sub('', cell_text(trs[ri]['tableCells'][3])))
check('ПАРТИЦИЯ (каждое слово ровно в одной строке)', ct == wt,
      f'{len(ct)} == {len(wt)} токенов')
if ct != wt:
    for i, (a, b) in enumerate(zip(wt, ct)):
        if a != b:
            print(f'   первый дифф @ {i}: {wt[i - 2:i + 3]} vs {ct[i - 2:i + 3]}')
            break

# 4. картинки
n_img = sum(cell_imgs(trs[ri]['tableCells'][4]) for ri in piece_rows)
check('картинок в «Экран»', n_img == n_row, f'{n_img} == {n_row}')

# 5. bold-фразы
n_runs = sum(cell_bold_runs(trs[ri]['tableCells'][3]) for ri in piece_rows)
check('bold-диапазонов в транскрибации', n_runs >= n_bold,
      f'{n_runs} >= {n_bold} фраз')

# 6. ширины
want = content['table']['widths']
got = []
for tc in trs[0]['tableCells']:
    wsty = tc.get('tableCellStyle', {})
    got.append(None)
cols = tbl['table'].get('tableStyle', {}).get('tableColumnProperties', [])
got = [int(c.get('width', {}).get('magnitude', 0)) for c in cols]
check('ширины колонок', got == want, f'{got} == {want}')

print()
if fails:
    print('ИТОГ: FAIL —', ', '.join(fails))
    sys.exit(1)
print(f'ИТОГ: ALL PASS — {n_ch} глав, {n_row} кусков, {n_img} кадров, '
      f'{n_runs} bold-прогонов, {len(wt)} токенов партиции')
print(f'https://docs.google.com/document/d/{doc_id}/edit')
