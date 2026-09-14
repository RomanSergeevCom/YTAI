#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «Ревью по видео · v4» в доке ревью YTCH12 (навигатор с полной транскрибацией, канон YTCH11
Review_v2_video) — копия d3_review_build.py, переведённая на ВКЛАДКУ: во все запросы подставляется tabId,
тело читается из вкладки. Вёрстка та же: pre_table (обязательные правки) → одна таблица по таймлайну
(главы = merged-строки [скобки] + HEADING_3 + заливка-подсказка; куски = полная транскрибация + bold,
кадр 150pt в «Экран», ТЗ блоками) → post.
Usage: d4_review_build.py <doc_id> [content.json] [tab_title]
Картинки: media_manifest.json ({имя: thumbnailLink}) — освежать `u_media_v4.py --refresh` перед сборкой!
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import batch_update as _bu, get_doc, iter_tabs  # noqa: E402

WORK = os.path.dirname(os.path.abspath(__file__))
DOC_ID = sys.argv[1]
CONTENT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(WORK, 'doc_content_review_v4.json')
TAB_TITLE = sys.argv[3] if len(sys.argv) > 3 else 'Ревью по видео · v4'
MANIFEST = os.path.join(WORK, 'media_manifest.json')
SHADES = {'act': {'red': 0.72, 'green': 0.78, 'blue': 0.88}, 'chapter': {'red': 0.85, 'green': 0.90, 'blue': 0.97},
          'red': {'red': 0.99, 'green': 0.92, 'blue': 0.92}, 'green': {'red': 0.93, 'green': 0.98, 'blue': 0.93},
          'yellow': {'red': 1.00, 'green': 0.97, 'blue': 0.85}}
TAB = None


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def inject(o):
    """tabId во все location/range/tableStartLocation (у них есть index или startIndex)."""
    if isinstance(o, dict):
        if ('index' in o or 'startIndex' in o) and 'tabId' not in o and not ('rowIndex' in o):
            o['tabId'] = TAB
        for v in o.values():
            inject(v)
    elif isinstance(o, list):
        for v in o:
            inject(v)
    return o


def bu(reqs, tries=5):
    for k in range(tries):
        try:
            return _bu(DOC_ID, inject(reqs))
        except (RuntimeError, OSError) as e:
            if k < tries - 1 and any(c in str(e) for c in ('429', '500', '502', '503', '504', 'timed out', 'reset')):
                time.sleep(6 * 2 ** k)
                continue
            raise


def body_content():
    for k in range(4):
        try:
            d = get_doc(DOC_ID)
            break
        except Exception:                                # noqa: BLE001
            if k == 3:
                raise
            time.sleep(8 * (k + 1))
    for t in iter_tabs(d):
        if t['tabProperties']['tabId'] == TAB:
            return t['documentTab']['body']['content']
    raise SystemExit('tab lost')


def end_index():
    return body_content()[-1]['endIndex'] - 1


def add_paras(paras):
    HEAD = {1: 'HEADING_1', 2: 'HEADING_2', 3: 'HEADING_3'}
    cur = end_index()
    reqs = []
    for item in paras:
        h, text = item[0], item[1]
        tnl = text + '\n'
        n = u16(tnl)
        reqs += [{'insertText': {'location': {'index': cur}, 'text': tnl}},
                 {'updateParagraphStyle': {'range': {'startIndex': cur, 'endIndex': cur + n},
                                           'paragraphStyle': {'namedStyleType': HEAD.get(h, 'NORMAL_TEXT')},
                                           'fields': 'namedStyleType'}}]
        cur += n
    if reqs:
        bu(reqs)


def table_at_end():
    return [el for el in body_content() if 'table' in el][-1]


def fill_table(headers, rows_cells, widths, bold_header=True):
    ncols = len(headers)
    bu([{'insertTable': {'location': {'index': end_index()}, 'rows': len(rows_cells) + 1, 'columns': ncols}}])
    tbl = table_at_end()
    cells = [[cc for cc in row['tableCells']] for row in tbl['table']['tableRows']]
    allr = [list(headers)] + [list(r) for r in rows_cells]
    reqs = []
    for ri in range(len(allr) - 1, -1, -1):
        for ci in range(ncols - 1, -1, -1):
            txt = str(allr[ri][ci] if ci < len(allr[ri]) else '')
            if txt:
                reqs.append({'insertText': {'location': {'index': cells[ri][ci]['content'][0]['startIndex']}, 'text': txt}})
    for i in range(0, len(reqs), 300):
        bu(reqs[i:i + 300])
    tbl = table_at_end()
    st = [{'updateTableColumnProperties': {'tableStartLocation': {'index': tbl['startIndex']}, 'columnIndices': [ci],
                                           'tableColumnProperties': {'widthType': 'FIXED_WIDTH',
                                                                     'width': {'magnitude': w, 'unit': 'PT'}},
                                           'fields': 'widthType,width'}} for ci, w in enumerate(widths)]
    if bold_header:
        for cell in tbl['table']['tableRows'][0]['tableCells']:
            s0, e0 = cell['startIndex'] + 1, cell['endIndex'] - 1
            if e0 > s0:
                st.append({'updateTextStyle': {'range': {'startIndex': s0, 'endIndex': e0},
                                               'textStyle': {'bold': True}, 'fields': 'bold'}})
    bu(st)
    return tbl


def main():
    global TAB
    import socket
    socket.setdefaulttimeout(300)
    c = json.load(open(CONTENT, encoding='utf-8'))
    man = json.load(open(MANIFEST, encoding='utf-8')) if os.path.exists(MANIFEST) else {}
    rows, headers, widths = c['table']['rows'], c['table']['headers'], c['table']['widths']
    ncols = len(headers)

    d = get_doc(DOC_ID)
    TAB = next((t['tabProperties']['tabId'] for t in iter_tabs(d) if t['tabProperties'].get('title') == TAB_TITLE), None)
    if TAB is None:
        TAB = _bu(DOC_ID, [{'addDocumentTab': {'tabProperties': {'title': TAB_TITLE}}}])['replies'][0][
            'addDocumentTab']['tabProperties']['tabId']
        print('создана вкладка', TAB, flush=True)
    body = body_content()
    first = next(x for x in body if 'paragraph' in x)
    s, e = first['startIndex'], body[-1]['endIndex'] - 1
    if e > s:
        bu([{'deleteContentRange': {'range': {'startIndex': s, 'endIndex': e}}}])
    print('вкладка очищена', TAB, flush=True)

    add_paras(c.get('paras') or [])
    if c.get('pre_table'):
        pt = c['pre_table']
        fill_table(pt['headers'], pt['rows'], pt['widths'])
        print('pre_table:', len(pt['rows']), flush=True)
    add_paras(c.get('paras2') or [])

    # ── основная таблица ──
    cells_rows = []
    for rr in rows:
        cells_rows.append([rr['text']] + [''] * (ncols - 1) if rr['kind'] in ('act', 'chapter')
                          else (list(rr['cells'])[:ncols] + [''] * max(0, ncols - len(rr['cells']))))
    tbl = fill_table(headers, cells_rows, widths)
    print('таблица:', len(rows), 'строк', flush=True)

    # ── bold-фразы в транскрибации (кол.3) — до картинок ──
    trs = table_at_end()['table']['tableRows']
    breqs, miss = [], 0
    for ri, rr in enumerate(rows, start=1):
        if rr.get('kind') != 'row' or not rr.get('bold'):
            continue
        ct = str(rr['cells'][3])
        low = ct.lower().replace('\n', ' ')
        s0 = trs[ri]['tableCells'][3]['startIndex'] + 1
        for ph in rr['bold']:
            pos = low.find(ph.lower())
            if pos < 0:
                miss += 1
                continue
            a = s0 + u16(ct[:pos])
            breqs.append({'updateTextStyle': {'range': {'startIndex': a, 'endIndex': a + u16(ct[pos:pos + len(ph)])},
                                              'textStyle': {'bold': True}, 'fields': 'bold'}})
    for i in range(0, len(breqs), 200):
        bu(breqs[i:i + 200])
    print(f'bold: {len(breqs)} (мимо {miss})', flush=True)

    # ── картинки в «Экран» (кол.4), реверсом ──
    trs = table_at_end()['table']['tableRows']
    img_reqs = []
    for ri in range(len(rows), 0, -1):
        rr = rows[ri - 1]
        uri = man.get(os.path.basename(rr['img'])) if rr.get('kind') == 'row' and rr.get('img') else None
        if not uri:
            continue
        idx = trs[ri]['tableCells'][4]['content'][0]['startIndex']
        img_reqs += [{'insertInlineImage': {'location': {'index': idx}, 'uri': uri,
                                            'objectSize': {'width': {'magnitude': rr.get('img_w', 150), 'unit': 'PT'}}}},
                     {'insertText': {'location': {'index': idx + 1}, 'text': '\n'}}]
    ok = 0
    for i in range(0, len(img_reqs), 40):
        try:
            bu(img_reqs[i:i + 40])
            ok += len(img_reqs[i:i + 40]) // 2
        except Exception as ex:                           # noqa: BLE001
            print('  img batch err → по одной:', str(ex)[:120], flush=True)
            for j in range(i, min(i + 40, len(img_reqs)), 2):
                try:
                    bu(img_reqs[j:j + 2])
                    ok += 1
                except Exception as ex2:                  # noqa: BLE001
                    print('  img err:', str(ex2)[:100], flush=True)
    print(f'картинок: {ok}/{len(img_reqs) // 2}', flush=True)

    # ── merge глав + заливки + стили ──
    tbl = table_at_end()
    tstart = tbl['startIndex']
    reqs = []
    for ri, rr in enumerate(rows, start=1):
        shade = None
        if rr['kind'] in ('act', 'chapter'):
            reqs.append({'mergeTableCells': {'tableRange': {'tableCellLocation': {
                'tableStartLocation': {'index': tstart}, 'rowIndex': ri, 'columnIndex': 0}, 'rowSpan': 1, 'columnSpan': ncols}}})
            shade = SHADES.get(rr.get('shade')) or SHADES[rr['kind']]
        elif rr.get('shade'):
            shade = SHADES.get(rr['shade'])
        if shade:
            reqs.append({'updateTableCellStyle': {'tableRange': {'tableCellLocation': {
                'tableStartLocation': {'index': tstart}, 'rowIndex': ri, 'columnIndex': 0}, 'rowSpan': 1, 'columnSpan': ncols},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': shade}}}, 'fields': 'backgroundColor'}})
    for i in range(0, len(reqs), 200):
        bu(reqs[i:i + 200])
    trs = table_at_end()['table']['tableRows']
    reqs = []
    for ri, tr in enumerate(trs):
        kind = 'header' if ri == 0 else rows[ri - 1]['kind']
        for ci, cell in enumerate(tr['tableCells']):
            s, e = cell['startIndex'] + 1, cell['endIndex'] - 1
            if e <= s:
                continue
            if kind in ('act', 'chapter') and ci == 0:
                label = str(rows[ri - 1]['text']).split('\n', 1)[0]
                es = min(e, s + u16(label))
                reqs += [{'updateParagraphStyle': {'range': {'startIndex': s, 'endIndex': es},
                                                   'paragraphStyle': {'namedStyleType': 'HEADING_3'}, 'fields': 'namedStyleType'}},
                         {'updateTextStyle': {'range': {'startIndex': s, 'endIndex': es},
                                              'textStyle': {'bold': True, 'fontSize': {'magnitude': 11, 'unit': 'PT'}},
                                              'fields': 'bold,fontSize'}}]
            elif kind == 'row' and ci in (1, 2, 4, 5):
                reqs.append({'updateTextStyle': {'range': {'startIndex': s, 'endIndex': e},
                                                 'textStyle': {'fontSize': {'magnitude': 9, 'unit': 'PT'}}, 'fields': 'fontSize'}})
    for i in range(0, len(reqs), 200):
        bu(reqs[i:i + 200])
    add_paras(c.get('post') or [])
    open(os.path.join(WORK, 'review_v4_video_tab.txt'), 'w').write(TAB)
    print(f'https://docs.google.com/document/d/{DOC_ID}/edit?tab={TAB}')


if __name__ == '__main__':
    main()
