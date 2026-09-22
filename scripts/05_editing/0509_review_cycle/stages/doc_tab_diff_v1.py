#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «Сверка v{N-1} → v{N}»: что монтажёр закрыл из ТЗ прошлой версии ката.

Конвейер отвечает на вопрос «что не так в новой версии», и закрытые пункты в его ТЗ не попадают
вовсе — а продюсеру нужно ровно обратное: сделал монтажёр работу или нет. Данные считает
shared/tz_diff.py (tz_diff.json), эта стадия только раскладывает их в документ.

Канон вкладок (Роман, 03.09.2026): ОДНА таблица на вкладку. Секции — строки внутри неё:
заливка, название в [квадратных скобках], HEADING_3 в ячейке (тогда секции видны в панели
«Структура» документа). Никаких «заголовок + таблица на каждую секцию».

Каждая строка несёт доказательство — текст с экрана, реплику из транскрипта или число из align.
Статуса без доказательства не бывает: вместо него «нужен глаз».

usage: doc_tab_diff_v1.py [--diff work/v{N}/tz_diff.json] [--tab «Сверка v4 → v5»] [--force]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _bootstrap import P, W6  # noqa: E402
from doctab_lib import get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _batch_update  # noqa: E402

DOC_ID = P.need('doc_id')
WIDTHS = [30, 56, 70, 230, 90, 200]            # сумма 676pt, как у вкладки ТЗ
HDR = ['№', 'ТК', 'Категория', 'Что требовалось', 'Статус', 'Доказательство']
FONT = 9
C_STATUS = 4

SECTIONS = [('structure', 'СТРУКТУРА'), ('graphics', 'ГРАФИКА'), ('cut', 'ВЫРЕЗЫ'),
            ('insert', 'ВСТАВКИ'), ('fund', 'ФОНД И ЮРИДИЧЕСКОЕ'), ('check', 'ПРОВЕРКИ'),
            ('color', 'ЦВЕТ И ЗВУК')]
FILL = {'сделано': (0.87, 0.95, 0.87), 'не сделано': (0.99, 0.89, 0.89),
        'ждёт фонд': (1.0, 0.96, 0.85), 'нужен глаз': (0.94, 0.94, 0.94)}
MARK = {'сделано': '✅ сделано', 'не сделано': '❌ не сделано',
        'ждёт фонд': '⚠️ ждёт фонд', 'нужен глаз': '👁 нужен глаз'}


def u16(s):
    return len(s)


def batch_update(doc_id, reqs):
    return _batch_update(doc_id, reqs) if reqs else None


def build_rows(diff):
    """строки таблицы: секции + пункты; возвращает (rows, порядковые номера секций)"""
    rows, sect_idx = [], []
    by = {}
    for r in diff['rows']:
        by.setdefault(r['category'] or '—', []).append(r)
    for key, human in SECTIONS:
        items = by.pop(key, [])
        if not items:
            continue
        tally = {}
        for it in items:
            tally[it['status']] = tally.get(it['status'], 0) + 1
        summary = ' · '.join(f'{MARK.get(k, k)} {v}' for k, v in sorted(tally.items()))
        sect_idx.append(len(rows))
        rows.append({'kind': 'sec', 'cells': [f'[{human}]', '', '', summary, '', '']})
        for it in sorted(items, key=lambda x: (x.get('sec') is None, x.get('sec') or 0)):
            rows.append({'kind': 'tz', 'status': it['status'], 'cells': [
                str(it['n']), it['tc'][:14], it['category'],
                it['title'][:220], MARK.get(it['status'], it['status']), it['why'][:260]]})
    for key, items in by.items():                        # категории, которых нет в SECTIONS
        sect_idx.append(len(rows))
        rows.append({'kind': 'sec', 'cells': [f'[{key.upper()}]', '', '', '', '', '']})
        for it in items:
            rows.append({'kind': 'tz', 'status': it['status'], 'cells': [
                str(it['n']), it['tc'][:14], it['category'], it['title'][:220],
                MARK.get(it['status'], it['status']), it['why'][:260]]})
    return rows, sect_idx


def head_paragraphs(diff):
    t = diff['tally']
    total = diff['total']
    a = diff.get('align') or {}
    return [
        (1, f'Сверка {Path(diff["old_file"]).stem} → {diff["code"]} {diff["cut_version"]}', {}),
        (0, f'Всего пунктов прошлого ТЗ: {total}. '
            + ' · '.join(f'{MARK.get(k, k)}: {v}' for k, v in sorted(t.items())), {'bold': True}),
        (0, f'Монтаж по align: перестановок {a.get("moved", "—")}, '
            f'из прошлой версии выпало {a.get("dropped_sec", 0):.0f} с.', {}),
        (0, 'Статус ставится только при доказательстве: текст с экрана нового ката (OCR), '
            'реплика из транскрипта или число из align. Где доказательства нет — «нужен глаз», '
            'решает человек. «Ждёт фонд» — чувствительные пункты, они не в зоне монтажёра.', {}),
    ]


def main(diff_path, tab_title, force=False):
    frozen = {tuple(x) for x in (P.get('frozen_tabs') or [])}
    if (DOC_ID, tab_title) in frozen and not force:
        raise SystemExit(f'«{tab_title}» заморожена в карточке — правили руками; --force чтобы перезаписать')

    diff = json.load(open(diff_path, encoding='utf-8'))
    rows, _ = build_rows(diff)
    headp = head_paragraphs(diff)
    print(f'строк: {len(rows)} (секций {sum(r["kind"] == "sec" for r in rows)})', flush=True)

    doc = get_doc(DOC_ID)
    tab_id = next((t['tabProperties']['tabId'] for t in iter_tabs(doc)
                   if t['tabProperties'].get('title') == tab_title), None)
    if tab_id is None:
        resp = batch_update(DOC_ID, [{'addDocumentTab': {'tabProperties': {'title': tab_title}}}])
        tab_id = resp['replies'][0]['addDocumentTab']['tabProperties']['tabId']
        print('создана вкладка', tab_id)
    else:
        print('вкладка найдена', tab_id)

    def body():
        for t in iter_tabs(get_doc(DOC_ID)):
            if t['tabProperties']['tabId'] == tab_id:
                return t['documentTab']['body']['content']
        raise SystemExit('вкладка потерялась')

    b = body()
    first = next(c for c in b if 'paragraph' in c)
    start, end = first['startIndex'], b[-1]['endIndex'] - 1
    if end > start:
        batch_update(DOC_ID, [{'deleteContentRange': {
            'range': {'tabId': tab_id, 'startIndex': start, 'endIndex': end}}}])
    print('вкладка очищена', flush=True)

    # шапка — одной пачкой, индексы считаем сами
    cur = body()[-1]['endIndex'] - 1
    reqs = []
    for h, text, opts in headp:
        tnl = text + '\n'
        n = u16(tnl)
        reqs += [{'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': tnl}},
                 {'updateParagraphStyle': {
                     'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n},
                     'paragraphStyle': {'namedStyleType': 'HEADING_1' if h else 'NORMAL_TEXT'},
                     'fields': 'namedStyleType'}}]
        if opts.get('bold'):
            reqs.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n - 1},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += n
    batch_update(DOC_ID, reqs)

    # ОДНА таблица
    cur = body()[-1]['endIndex'] - 1
    batch_update(DOC_ID, [{'insertTable': {'location': {'tabId': tab_id, 'index': cur},
                                           'rows': len(rows) + 1, 'columns': len(HDR)}}])
    tbl = [el for el in body() if 'table' in el][-1]
    cells = [r['tableCells'] for r in tbl['table']['tableRows']]
    allc = [HDR] + [r['cells'] for r in rows]
    reqs = []
    for ri in range(len(allc) - 1, -1, -1):
        for cj in range(len(HDR) - 1, -1, -1):
            txt = str(allc[ri][cj])
            if txt:
                reqs.append({'insertText': {
                    'location': {'tabId': tab_id, 'index': cells[ri][cj]['content'][0]['startIndex']},
                    'text': txt}})
    for i in range(0, len(reqs), 400):
        batch_update(DOC_ID, reqs[i:i + 400])
        print(f'текст, пачка {i // 400 + 1}', flush=True)

    # оформление: ширины, кегль, заливка секций и статусов, HEADING_3 в ячейке секции
    tbl = [el for el in body() if 'table' in el][-1]
    t_start = tbl['startIndex']
    trows = tbl['table']['tableRows']
    style = [{'updateTableColumnProperties': {
        'tableStartLocation': {'tabId': tab_id, 'index': t_start},
        'columnIndices': [i], 'fields': 'width,widthType',
        'tableColumnProperties': {'widthType': 'FIXED_WIDTH', 'width': {'magnitude': w, 'unit': 'PT'}}}}
        for i, w in enumerate(WIDTHS)]
    for ri, row in enumerate(trows):
        r = None if ri == 0 else rows[ri - 1]
        fill = (0.85, 0.85, 0.85) if ri == 0 else (
            (0.80, 0.85, 0.95) if r['kind'] == 'sec' else None)
        if fill:
            style.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {
                    'tableStartLocation': {'tabId': tab_id, 'index': t_start},
                    'rowIndex': ri, 'columnIndex': 0},
                    'rowSpan': 1, 'columnSpan': len(HDR)},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': dict(
                    zip(('red', 'green', 'blue'), fill))}}},
                'fields': 'backgroundColor'}})
        elif r and r.get('status') in FILL:
            style.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {
                    'tableStartLocation': {'tabId': tab_id, 'index': t_start},
                    'rowIndex': ri, 'columnIndex': C_STATUS},
                    'rowSpan': 1, 'columnSpan': 1},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': dict(
                    zip(('red', 'green', 'blue'), FILL[r['status']]))}}},
                'fields': 'backgroundColor'}})
        for cj, cell in enumerate(row['tableCells']):
            c0 = cell['content'][0]['startIndex']
            c1 = cell['content'][-1]['endIndex'] - 1
            if c1 <= c0:
                continue
            if r and r['kind'] == 'sec' and cj == 0:
                style.append({'updateParagraphStyle': {
                    'range': {'tabId': tab_id, 'startIndex': c0, 'endIndex': c1},
                    'paragraphStyle': {'namedStyleType': 'HEADING_3'},
                    'fields': 'namedStyleType'}})
            style.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': c0, 'endIndex': c1},
                'textStyle': {'fontSize': {'magnitude': FONT, 'unit': 'PT'},
                              'bold': bool(ri == 0 or (r and r['kind'] == 'sec'))},
                'fields': 'fontSize,bold'}})
    for i in range(0, len(style), 400):
        batch_update(DOC_ID, style[i:i + 400])
        print(f'стили, пачка {i // 400 + 1}', flush=True)
    print('готово:', tab_title)
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--diff', default='')
    ap.add_argument('--tab', default='')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    d = Path(a.diff) if a.diff else (W6 / 'tz_diff.json')
    title = a.tab or f'Сверка → {P.CUT_VERSION}'
    raise SystemExit(main(d, title, a.force))
