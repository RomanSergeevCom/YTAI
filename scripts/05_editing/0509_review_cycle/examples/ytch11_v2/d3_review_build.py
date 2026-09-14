#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google Doc «Ревью v2 по видео» (pageless) из doc_content_review_v2.json.

Копия d2_doc_build.py с правками под ревью-канон YTUVI01:
  - глава: HEADING_3/bold только на ПЕРВОЙ строке (label в [скобках] → оглавление),
    ⚠️-правки главы в той же ячейке обычным текстом;
  - заливка главы = цвет-подсказка rr['shade'] (green/yellow/red), не фикс-голубая.
rows:
  {'kind':'chapter','text','shade'}           — глава-карточка
  {'kind':'row','cells':[...6...],'img':path,'shade':...,'bold':[...]}
Картинка вставляется в ячейку «экран» (index 4) НАД подписью; thumbnailLink
из манифеста frames_manifest.json ({basename: uri}) — освежать перед сборкой!
"""
import json, os, sys, time
sys.path.insert(0, os.path.expanduser('~/YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import api, batch_update

WORK = os.path.dirname(os.path.abspath(__file__))
CONTENT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WORK, 'doc_content_review_v2.json')
MANIFEST = os.path.join(WORK, 'frames_manifest.json')

SHADES = {
    'act':     {'red': 0.72, 'green': 0.78, 'blue': 0.88},
    'chapter': {'red': 0.85, 'green': 0.90, 'blue': 0.97},
    'red':     {'red': 0.99, 'green': 0.92, 'blue': 0.92},
    'green':   {'red': 0.93, 'green': 0.98, 'blue': 0.93},
    'yellow':  {'red': 1.00, 'green': 0.97, 'blue': 0.85},
}


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def get_doc(doc_id):
    return api('GET', f'https://docs.googleapis.com/v1/documents/{doc_id}')


def body_content(doc_id):
    return get_doc(doc_id)['body']['content']


def end_index(doc_id):
    return body_content(doc_id)[-1]['endIndex'] - 1


def add_paras(doc_id, paras):
    HEAD = {1: 'HEADING_1', 2: 'HEADING_2', 3: 'HEADING_3', 4: 'HEADING_4'}
    for item in paras:
        h, text = item[0], item[1]
        opts = item[2] if len(item) > 2 else {}
        cur = end_index(doc_id)
        text_nl = text + '\n'
        reqs = [{'insertText': {'location': {'index': cur}, 'text': text_nl}}]
        e = cur + u16(text_nl)
        reqs.append({'updateParagraphStyle': {
            'range': {'startIndex': cur, 'endIndex': e},
            'paragraphStyle': {'namedStyleType': HEAD.get(h, 'NORMAL_TEXT')},
            'fields': 'namedStyleType'}})
        if opts.get('bold'):
            reqs.append({'updateTextStyle': {
                'range': {'startIndex': cur, 'endIndex': e - 1},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
        if opts.get('link'):
            reqs.append({'updateTextStyle': {
                'range': {'startIndex': cur, 'endIndex': e - 1},
                'textStyle': {'link': {'url': opts['link']}}, 'fields': 'link'}})
        batch_update(doc_id, reqs)


def main():
    c = json.load(open(CONTENT, encoding='utf-8'))
    man = json.load(open(MANIFEST, encoding='utf-8')) if os.path.exists(MANIFEST) else {}
    rows = c['table']['rows']
    headers = c['table']['headers']
    widths = c['table']['widths']
    ncols = len(headers)

    if len(sys.argv) > 2:
        # режим перезаписи существующего дока (сохраняем URL)
        doc_id = sys.argv[2]
        end = end_index(doc_id)
        if end > 1:
            batch_update(doc_id, [{'deleteContentRange':
                                   {'range': {'startIndex': 1, 'endIndex': end}}}])
        print('doc wiped:', doc_id, flush=True)
    else:
        r = api('POST', 'https://www.googleapis.com/drive/v3/files?supportsAllDrives=true&fields=id',
                {'name': c['doc_title'], 'mimeType': 'application/vnd.google-apps.document',
                 'parents': [c['folder_id']]})
        doc_id = r['id']
        print('doc created:', doc_id, flush=True)
    batch_update(doc_id, [{'updateDocumentStyle': {
        'documentStyle': {'documentFormat': {'documentMode': 'PAGELESS'}},
        'fields': 'documentFormat'}}])
    print('pageless set', flush=True)

    add_paras(doc_id, c.get('paras') or [])

    cur = end_index(doc_id)
    batch_update(doc_id, [{'insertTable': {
        'location': {'index': cur}, 'rows': len(rows) + 1, 'columns': ncols}}])
    body = body_content(doc_id)
    tbl = [el for el in body if 'table' in el][-1]
    cells = [[cc for cc in row['tableCells']] for row in tbl['table']['tableRows']]

    all_rows = [list(headers)]
    for rr in rows:
        if rr['kind'] in ('act', 'chapter'):
            all_rows.append([rr['text']] + [''] * (ncols - 1))
        else:
            cc = list(rr['cells'])[:ncols]
            cc += [''] * (ncols - len(cc))
            all_rows.append(cc)
    reqs = []
    for ri in range(len(all_rows) - 1, -1, -1):
        for ci in range(ncols - 1, -1, -1):
            txt = str(all_rows[ri][ci])
            if not txt:
                continue
            idx = cells[ri][ci]['content'][0]['startIndex']
            reqs.append({'insertText': {'location': {'index': idx}, 'text': txt}})
    for i in range(0, len(reqs), 300):
        batch_update(doc_id, reqs[i:i + 300])
        print(f'  fill {min(i+300,len(reqs))}/{len(reqs)}', flush=True)

    # ---- жирные фразы в транскрибации (колонка 3), ДО картинок (индексы ещё чистые)
    body = body_content(doc_id)
    tbl = [el for el in body if 'table' in el][-1]
    trs = tbl['table']['tableRows']
    breqs = []
    for ri, rr in enumerate(rows, start=1):
        if rr.get('kind') != 'row' or not rr.get('bold'):
            continue
        cell_text = str(rr['cells'][3])
        low = cell_text.lower().replace('\n', ' ')
        s0 = trs[ri]['tableCells'][3]['startIndex'] + 1
        for ph in rr['bold']:
            pos = low.find(ph.lower())
            if pos < 0:
                print('  !! bold miss:', ph[:40], flush=True)
                continue
            a = s0 + u16(cell_text[:pos])
            breqs.append({'updateTextStyle': {
                'range': {'startIndex': a, 'endIndex': a + u16(cell_text[pos:pos+len(ph)])},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
    for i in range(0, len(breqs), 200):
        batch_update(doc_id, breqs[i:i + 200])
    print('bold phrases:', len(breqs), flush=True)

    # ---- картинки: свежий GET, реверсом по строкам
    body = body_content(doc_id)
    tbl = [el for el in body if 'table' in el][-1]
    trs = tbl['table']['tableRows']
    img_reqs = []
    for ri in range(len(rows), 0, -1):
        rr = rows[ri - 1]
        if rr.get('kind') != 'row':
            continue
        img = rr.get('img')
        uri = man.get(os.path.basename(img)) if img else None
        if not uri:
            continue
        cell = trs[ri]['tableCells'][4]
        idx = cell['content'][0]['startIndex']
        img_reqs.append({'insertInlineImage': {
            'location': {'index': idx}, 'uri': uri,
            'objectSize': {'width': {'magnitude': rr.get('img_w', 150), 'unit': 'PT'}}}})
        img_reqs.append({'insertText': {'location': {'index': idx + 1}, 'text': '\n'}})
    print('image requests:', len(img_reqs) // 2, flush=True)
    for i in range(0, len(img_reqs), 40):
        for attempt in range(3):
            try:
                batch_update(doc_id, img_reqs[i:i + 40])
                break
            except Exception as e:
                print('  retry img batch', i, str(e)[:120], flush=True)
                time.sleep(3)
        print(f'  img {min(i+40,len(img_reqs))}/{len(img_reqs)}', flush=True)

    # ---- merges + заливки + ширины
    body = body_content(doc_id)
    tbl = [el for el in body if 'table' in el][-1]
    tstart = tbl['startIndex']
    reqs = []
    for ri, rr in enumerate(rows, start=1):
        shade = None
        if rr['kind'] in ('act', 'chapter'):
            reqs.append({'mergeTableCells': {'tableRange': {
                'tableCellLocation': {'tableStartLocation': {'index': tstart},
                                      'rowIndex': ri, 'columnIndex': 0},
                'rowSpan': 1, 'columnSpan': ncols}}})
            # заливка главы = цвет-подсказка (green/yellow/red), иначе канонная
            shade = SHADES.get(rr.get('shade')) or SHADES[rr['kind']]
        elif rr.get('shade'):
            shade = SHADES.get(rr['shade'])
        if shade:
            reqs.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {
                    'tableStartLocation': {'index': tstart},
                    'rowIndex': ri, 'columnIndex': 0},
                    'rowSpan': 1, 'columnSpan': ncols},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': shade}}},
                'fields': 'backgroundColor'}})
    for ci, w in enumerate(widths):
        reqs.append({'updateTableColumnProperties': {
            'tableStartLocation': {'index': tstart}, 'columnIndices': [ci],
            'tableColumnProperties': {'widthType': 'FIXED_WIDTH',
                                      'width': {'magnitude': w, 'unit': 'PT'}},
            'fields': 'widthType,width'}})
    for i in range(0, len(reqs), 200):
        batch_update(doc_id, reqs[i:i + 200])
    print('merge+shade done', flush=True)

    # ---- стили текста: шапка bold, акт 12pt bold, глава bold; подписи в «экран» 9pt
    body = body_content(doc_id)
    tbl = [el for el in body if 'table' in el][-1]
    trs = tbl['table']['tableRows']
    reqs = []
    for ri, tr in enumerate(trs):
        kind = 'header' if ri == 0 else rows[ri - 1]['kind']
        for ci, cell in enumerate(tr['tableCells']):
            s, e = cell['startIndex'] + 1, cell['endIndex'] - 1
            if e <= s:
                continue
            if kind == 'header' or (ci == 0 and kind in ('act', 'chapter')):
                st = {'bold': True}
                if kind == 'act':
                    st['fontSize'] = {'magnitude': 12, 'unit': 'PT'}
                elif kind == 'chapter':
                    st['fontSize'] = {'magnitude': 11, 'unit': 'PT'}
                e_style = e
                if kind in ('act', 'chapter'):
                    # HEADING только на label (первая строка) → в оглавление
                    # попадает [label], а ⚠️-правки главы остаются обычным текстом
                    label = str(rows[ri - 1]['text']).split('\n', 1)[0]
                    e_style = min(e, s + u16(label))
                    reqs.append({'updateParagraphStyle': {
                        'range': {'startIndex': s, 'endIndex': e_style},
                        'paragraphStyle': {'namedStyleType':
                                           'HEADING_2' if kind == 'act' else 'HEADING_3'},
                        'fields': 'namedStyleType'}})
                reqs.append({'updateTextStyle': {'range': {'startIndex': s, 'endIndex': e_style},
                                                 'textStyle': st,
                                                 'fields': ','.join(st.keys())}})
            elif kind == 'row' and ci == 4:
                reqs.append({'updateTextStyle': {'range': {'startIndex': s, 'endIndex': e},
                                                 'textStyle': {'fontSize': {'magnitude': 9, 'unit': 'PT'}},
                                                 'fields': 'fontSize'}})
            elif kind == 'row' and ci in (1, 2):
                reqs.append({'updateTextStyle': {'range': {'startIndex': s, 'endIndex': e},
                                                 'textStyle': {'fontSize': {'magnitude': 9, 'unit': 'PT'}},
                                                 'fields': 'fontSize'}})
    for i in range(0, len(reqs), 200):
        batch_update(doc_id, reqs[i:i + 200])
    print('text styles done', flush=True)

    add_paras(doc_id, c.get('post') or [])
    print(f'https://docs.google.com/document/d/{doc_id}/edit')
    open(os.path.join(WORK, 'doc_id_%s.txt' % c['doc_title'][-6:]), 'w').write(doc_id)


if __name__ == '__main__':
    main()
