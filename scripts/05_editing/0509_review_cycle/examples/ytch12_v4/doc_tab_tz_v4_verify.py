#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify вкладки «ТЗ монтажёру · v4» (метод KB review-timeline, формат v7) — до ALL PASS:
строк = 1 + главы + ТЗ; главы [скобки] + HEADING_3; все активные ТЗ-номера на месте и по порядку;
у каждого ТЗ с картинкой-материалом — превью ≥ 250pt в «Материале»; у глав — мокап карточки;
в тексте ТЗ нет строк с ≥2 таймкодами (диапазон a–b = один); ширины колонок; метки блоков жирные."""
import json
import re
import sys
from pathlib import Path

M = Path(__file__).parent
sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import get_doc, iter_tabs  # noqa: E402
import doc_tab_tz_v4 as B  # noqa: E402

st = json.loads((M / 'review_v4_doc.json').read_text())
man = json.loads((M / 'media_manifest.json').read_text())
rows, act, rejected, chs = B.build_rows(json.loads((M / 'pravki_v4.json').read_text())['all'], man)
doc = get_doc(st['doc_id'])
tab = next(t for t in iter_tabs(doc) if t['tabProperties']['tabId'] == st['tz_tab'])
body = tab['documentTab']['body']['content']
inl = tab['documentTab'].get('inlineObjects', {})
tbl = [el for el in body if 'table' in el][-1]
trs = tbl['table']['tableRows']
fails = []
TC_RE = re.compile(r'(?<![\d:])\d{1,2}:\d{2}(?:[.,]\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:[.,]\d+)?)?(?![\d:])')


def check(name, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f' — {detail}' if detail else ''))
    if not ok:
        fails.append(name)


def cell_text(cell):
    return B.cell_text(cell)


def cell_imgs(cell):
    out = []
    for c in cell.get('content', []):
        for e in c.get('paragraph', {}).get('elements', []):
            if 'inlineObjectElement' in e:
                oid = e['inlineObjectElement']['inlineObjectId']
                w = inl.get(oid, {}).get('inlineObjectProperties', {}).get('embeddedObject', {}).get('size', {}) \
                    .get('width', {}).get('magnitude', 0)
                out.append(w)
    return out


check('таблица: строк', len(trs) == 1 + len(rows), f'{len(trs)} == 1+{len(rows)}')
n_ch = sum(r['kind'] == 'ch' for r in rows)
bad = []
for ri, r in enumerate(rows, 1):
    if r['kind'] != 'ch':
        continue
    c3 = trs[ri]['tableCells'][3]
    first = cell_text(c3).split('\n', 1)[0]
    h3 = any(el.get('paragraph', {}).get('paragraphStyle', {}).get('namedStyleType') == 'HEADING_3'
             for el in c3.get('content', []))
    if not (first.startswith('[') and first.rstrip().endswith(']') and h3):
        bad.append(ri)
check(f'главы [скобки] + HEADING_3 ({n_ch})', not bad, str(bad))
nums_doc = [cell_text(trs[ri]['tableCells'][0]).split('\n')[0].strip() for ri, r in enumerate(rows, 1) if r['kind'] == 'tz']
nums_want = [r['num'] for r in rows if r['kind'] == 'tz']
check(f'ТЗ-номера на месте ({len(nums_want)})', nums_doc == nums_want,
      f'первое расхождение: {next(((a, b) for a, b in zip(nums_doc, nums_want) if a != b), "—")}')
noimg = [r['num'] for ri, r in enumerate(rows, 1) if r['kind'] == 'tz' and r['imgs']
         and not any(w >= 250 for w in cell_imgs(trs[ri]['tableCells'][4]))]
check('превью ≥250pt у ТЗ с материалом', not noimg, ', '.join(noimg[:10]))
nocard = [r['label'] for ri, r in enumerate(rows, 1) if r['kind'] == 'ch' and r['imgs'] and not cell_imgs(trs[ri]['tableCells'][4])]
check('мокапы карточек у глав', not nocard, ', '.join(nocard[:5]))
multi = []
for ri, r in enumerate(rows, 1):
    if r['kind'] != 'tz':
        continue
    for ln in cell_text(trs[ri]['tableCells'][3]).split('\n'):
        if ln.startswith(('💬', '❓')):
            continue
        if len(TC_RE.findall(ln)) >= 2:
            multi.append(f'{r["num"]}: {ln[:60]}')
check('строк с ≥2 таймкодами нет', not multi, '; '.join(multi[:5]))
got = [int(c.get('width', {}).get('magnitude', 0)) for c in tbl['table'].get('tableStyle', {}).get('tableColumnProperties', [])]
check('ширины колонок', got == B.WIDTHS, f'{got} == {B.WIDTHS}')
nolab = []
for ri, r in enumerate(rows, 1):
    if r['kind'] != 'tz':
        continue
    c3 = trs[ri]['tableCells'][3]
    runs = [e['textRun'] for c in c3.get('content', []) for e in c.get('paragraph', {}).get('elements', []) if 'textRun' in e]
    if not any(t.get('textStyle', {}).get('bold') and '✅ СДЕЛАТЬ' in t.get('content', '') for t in runs):
        nolab.append(r['num'])
check('метки блоков жирные (✅ СДЕЛАТЬ)', not nolab, ', '.join(nolab[:8]))
print()
if fails:
    print('ИТОГ: FAIL —', ', '.join(fails))
    sys.exit(1)
print(f'ИТОГ: ALL PASS — {n_ch} глав, {len(nums_want)} ТЗ')
print(f'https://docs.google.com/document/d/{st["doc_id"]}/edit?tab={st["tz_tab"]}')
