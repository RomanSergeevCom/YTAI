#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «ТЗ монтажёру · v4» в доке ревью YTCH12 — метод KB review-timeline (формат v7, адаптация
review_timeline_audit/doc_tab_tz_v3.py под YTCH12).

ОДНА таблица: № | ⏱ TC | категория | ТЗ монтажёру | Материал / превью.
Главы = ЗРИТЕЛЬСКИЕ карточки из предложенной структуры (structure_v4.json → final.asis.chapters):
строка с заливкой + [скобки] + HEADING_3 (оглавление), в «Материале» — мокап карточки главы.
ТЗ — из pravki_v4.json (единый источник: тот же, что лист и маркеры); rejected не печатаются.
ТЗ блоками с метками (❌ СЕЙЧАС · ✅ СДЕЛАТЬ · 📋 СПИСОК · 📍 ГДЕ · 📚 ИСТОЧНИК · 🎬 НА ТАЙМЛАЙНЕ),
пункты списков «tc ▸ …» — таймкод моноширинным серым; ❓ решения Романа; 💬 комменты — фиолетовым.
Превью — КРУПНО, в своём абзаце на всю ширину колонки, под ним подпись «таймкод · что видно».
Картинки — media_manifest.json (thumbnailLink приватной папки; освежать u_media_v4.py --refresh).
Док создаётся при первом запуске (review_v4_doc.json). Первая вкладка дока = эта (переименование).
"""
import json
import re
import sys
import time
import urllib.parse
from bisect import bisect_right
from pathlib import Path

M = Path(__file__).parent
sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import api, get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _bu  # noqa: E402

FOLDER = '1NQTnpDbPMhBxc8-872xWMULS5d9AC8IY'           # YTCH S3/YTCH12_Sveta
DOC_TITLE = 'YTCH12_Review_v4'
TAB_TITLE = 'ТЗ монтажёру · v4'
WIDTHS = [30, 58, 22, 300, 276]
FONT = 9
IMG_W = 262
HDR = ['№', '⏱ TC', '', 'ТЗ монтажёру', 'Материал / превью']
LABELS = ('❌ СЕЙЧАС ·', '✅ СДЕЛАТЬ ·', '📋 СПИСОК ·', '📍 ГДЕ ·', '📚 ИСТОЧНИК ·', '🎬 НА ТАЙМЛАЙНЕ ·')
CH_BG = {'Green': {'red': 0.85, 'green': 0.93, 'blue': 0.85}, 'Yellow': {'red': 0.98, 'green': 0.95, 'blue': 0.78},
         'Red': {'red': 0.98, 'green': 0.86, 'blue': 0.86}}
CAT = {'graphics': '🎨', 'structure': '🧭', 'cut': '✂️', 'insert': '➕', 'color': '🎛', 'check': '🔍', 'fund': '⚠️'}
CAT_BG = {'cut': {'red': 0.99, 'green': 0.87, 'blue': 0.86}, 'insert': {'red': 0.87, 'green': 0.95, 'blue': 0.87},
          'graphics': {'red': 1.0, 'green': 0.97, 'blue': 0.82}, 'structure': {'red': 1.0, 'green': 0.92, 'blue': 0.82},
          'color': {'red': 0.87, 'green': 0.92, 'blue': 0.98}, 'check': {'red': 0.93, 'green': 0.93, 'blue': 0.93},
          'fund': {'red': 1.0, 'green': 0.88, 'blue': 0.70}}
SEV = {'must': '🔴', 'should': '🟠', 'nice': '⚪'}
PURPLE = {'red': 0.42, 'green': 0.18, 'blue': 0.70}
GREY = {'red': 0.45, 'green': 0.45, 'blue': 0.45}
LINK = {'red': 0.06, 'green': 0.33, 'blue': 0.8}
ITEM_TC = re.compile(r'^( +)([  ]?\d{1,2}:\d{2}(?:–\d{1,2}:\d{2})?)  ▸ ', re.M)
URL_RE = re.compile(r'https?://[^\s)\]»]+')
TOTAL = 3045.48
DOC_ID, TAB = None, None


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def tmm(s):
    s = int(round(s))
    return f'{s // 60}:{s % 60:02d}'


def sec(t):
    m = re.findall(r'\d+(?:\.\d+)?', str(t or ''))
    p = [float(x) for x in m[:3]]
    if not p:
        return None
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else (p[0] * 60 + p[1] if len(p) == 2 else p[0])


def clean(t):
    return re.sub(r'\s+', ' ', str(t or '').strip())


def J(name, default=None):
    p = M / name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default


def inject(o):
    if isinstance(o, dict):
        if ('index' in o or 'startIndex' in o) and 'tabId' not in o and 'rowIndex' not in o:
            o['tabId'] = TAB
        for v in o.values():
            inject(v)
    elif isinstance(o, list):
        for v in o:
            inject(v)
    return o


def bu(reqs, tries=5, tab=True):
    for k in range(tries):
        try:
            return _bu(DOC_ID, inject(reqs) if tab else reqs)
        except (RuntimeError, OSError) as e:
            if k < tries - 1 and any(c in str(e) for c in ('429', '500', '502', '503', '504', 'timed out', 'reset')):
                time.sleep(6 * 2 ** k)
                continue
            raise


# ═══════════ чистая сборка строк ═══════════
def chapters():
    """Зрительские главы — ОДИН источник с навигатором/таймлайном/листом: viewer_chapters.json (c_chapters_v4.py)."""
    return [{'no': c['no'], 'sec': c['sec'], 'name': c['title'], 'img': c.get('img') or '',
             'anchor': clean(c.get('anchor')), 'purpose': clean(c.get('purpose'))}
            for c in J('viewer_chapters.json', [])]


def mat_cell(p, man):
    lines, imgs, caps, small = [], [], [], []
    for it in p.get('material_rich') or []:
        if it.get('img') and it['img'] in man:
            imgs.append((len(lines), it['img']))
            lines.append('')
        cap, t = clean(it.get('cap')), clean(it.get('t'))
        if cap:
            lines.append(cap)
            caps.append(cap)
        if t and t != cap:
            lines.append('• ' + t)
        if it.get('src'):
            s = '📚 источник: ' + clean(it['src'])
            lines.append(s)
            small.append(s)
    return '\n'.join(lines), imgs, caps, small


def tz_row(p, man):
    title = clean(p['title'])
    body = f"【{title}】\n{p['nado']}"
    if p.get('decision'):
        body += '\n❓ РЕШЕНИЕ РОМАНА: ' + clean(p['decision'])
    purple = []
    for c in p.get('roman_comment') or []:
        line = '💬 РОМА: ' + c
        body += '\n' + line
        purple.append(line)
    bold = [f'【{title}】'] + [l for l in LABELS if l in body] + (['❓ РЕШЕНИЕ РОМАНА:'] if p.get('decision') else [])
    mat, imgs, caps, small = mat_cell(p, man)
    tcv = '⏱ весь фильм' if not p.get('v1_tc') else f"⏱ {p.get('tc_range') or p['v1_tc']}"
    return {'kind': 'tz', 'num': p['num'], 'cat': p['category'],
            'cells': [f"{p['num']}\n{SEV.get(p.get('severity'), '')}", tcv, CAT.get(p['category'], '·'), body, mat],
            'bold': bold, 'purple': purple, 'imgs': imgs, 'caps': caps, 'small': small}


def build_rows(pravki, man):
    pr = [dict(p) for p in pravki]
    for i, p in enumerate(pr):
        p['num'] = f'ТЗ-{i + 1:02d}'
        p['_sec'] = sec(str(p.get('v1_tc') or '').split('–')[0]) if p.get('v1_tc') else None
    act = [p for p in pr if p.get('status') != 'rejected']
    rejected = [p for p in pr if p.get('status') == 'rejected']
    chs = chapters()
    starts = [c['sec'] for c in chs]
    rows = [tz_row(p, man) for p in act if p['_sec'] is None]
    for ci, ch in enumerate(chs):
        end = chs[ci + 1]['sec'] if ci + 1 < len(chs) else TOTAL
        mine = [p for p in act if p['_sec'] is not None and max(0, bisect_right(starts, p['_sec'] + 0.01) - 1) == ci]
        color = 'Yellow' if any(p.get('severity') in ('must', 'should') for p in mine) else 'Green'
        label = f"[{ch['no']}. {ch['name']} · {tmm(ch['sec'])}–{tmm(end)}]"
        sub = f"\nкарточка перед «{ch['anchor']}»" + (f" · {ch['purpose']}" if ch['purpose'] else '')
        rows.append({'kind': 'ch', 'label': label, 'color': color, 'cat': None,
                     'cells': ['', '', '', label + sub, f'{tmm(ch["sec"])} · карточка главы (мокап)'],
                     'bold': [], 'purple': [], 'caps': [f'{tmm(ch["sec"])} · карточка главы (мокап)'], 'small': [],
                     'imgs': [(0, ch['img'])] if ch['img'] in man else []})
        if ch['img'] in man:
            rows[-1]['cells'][4] = '\n' + rows[-1]['cells'][4]
        rows += [tz_row(p, man) for p in mine]
    return rows, act, rejected, chs


def build_head(act, rejected, chs):
    wf = J('wf_result.json', {}) or {}
    s = wf.get('synth') or {}
    notes = J('notes_sheet.json', {}) or {}
    decisions = [p for p in act if p.get('decision')]
    head = [(1, 'YTCH12 «Одна с ребёнком» · ТЗ монтажёру v4 — монтаж montage_1 от 09.09 (50:45)', {}),
            (0, f'Вердикт: {s.get("verdict_short", "—").upper()} — {clean(s.get("headline"))}', {'bold': True}),
            (0, clean(s.get('verdict')), {}),
            (0, 'Как читать: одна таблица по таймлайну v4; главы — ПРЕДЛАГАЕМЫЕ зрительские карточки (в кате их пока нет — '
                'ТЗ-01 «Структура»); под главой — её ТЗ. Каждое ТЗ блоками: ❌ СЕЙЧАС · ✅ СДЕЛАТЬ · 📋 СПИСОК · 📍 ГДЕ · '
                '📚 ИСТОЧНИК · 🎬 НА ТАЙМЛАЙНЕ; строка = один таймкод. 🔴 обязательно · 🟠 желательно · ⚪ полировка. '
                'Категории: 🧭 структура · ✂️ резать/сжать · ➕ вставить · 🎨 графика · 🎛 техника · ⚠️ фонд (блюр / '
                'письменное согласие / формулировка — НЕ вырез, политика 27.08) · 🔍 проверить. Справа — кадр в таймкод '
                'ТЗ или мокап графики (DRAFT).', {}),
            (0, 'Смотровой таймлайн: 00_Setup/05_Review/YTCH12_review_v4_full.json → панель UXP → Review → секвенция '
                'YTCH12_5_Review_v4_full (лайт 4K на T9-Black, кадр-в-кадр с мастером). Заметки при отсмотре: '
                '«Note @ playhead» → лист «YTCH12 Review Notes» (автопуш ~1–2 мин)'
                + (f': https://docs.google.com/spreadsheets/d/{notes["id"]}/edit' if notes.get('id') else '.'), {}),
            (0, 'Полная транскрибация по кускам с кадрами — вкладка «Ревью по видео · v4».', {}),
            (2, f'❓ Решения Романа ({len(decisions)})', {})]
    for p in decisions:
        head.append((0, f"• {p['num']} · {p.get('tc_range') or 'весь фильм'} · {clean(p['title'])} — {clean(p['decision'])}", {}))
    if rejected:
        head.append((0, '🚫 Снято Романом (номера сохранены): ' + ', '.join(f"{p['num']} {clean(p['title'])[:40]}" for p in rejected), {}))
    return head


# ═══════════ запись ═══════════
def cell_text(cell):
    return ''.join(e['textRun'].get('content', '') for c in cell.get('content', [])
                   for e in c.get('paragraph', {}).get('elements', []) if 'textRun' in e)


def index_of(cell, pos):
    last = None
    for c in cell.get('content', []):
        for e in c.get('paragraph', {}).get('elements', []):
            tr = e.get('textRun')
            if not tr:
                continue
            t = tr.get('content', '')
            if pos < len(t):
                return e['startIndex'] + u16(t[:pos])
            pos -= len(t)
            last = e['endIndex']
    return last if pos == 0 else None


def ensure_doc():
    global DOC_ID, TAB
    st = J('review_v4_doc.json', {}) or {}
    if st.get('doc_id'):
        DOC_ID = st['doc_id']
    else:
        DOC_ID = api('POST', 'https://www.googleapis.com/drive/v3/files?supportsAllDrives=true&fields=id',
                     {'name': DOC_TITLE, 'mimeType': 'application/vnd.google-apps.document', 'parents': [FOLDER]})['id']
        print('док создан:', DOC_ID, flush=True)
    d = get_doc(DOC_ID)
    tabs = list(iter_tabs(d))
    TAB = next((t['tabProperties']['tabId'] for t in tabs if t['tabProperties'].get('title') == TAB_TITLE), None)
    if TAB is None and not st.get('doc_id') and len(tabs) == 1:
        first = tabs[0]['tabProperties']['tabId']
        try:
            _bu(DOC_ID, [{'updateDocumentTabProperties': {'tabProperties': {'tabId': first, 'title': TAB_TITLE},
                                                          'fields': 'title'}}])
            TAB = first
            print('первая вкладка переименована', flush=True)
        except RuntimeError as e:
            print('переименование не удалось:', str(e)[:120], flush=True)
    if TAB is None:
        TAB = _bu(DOC_ID, [{'addDocumentTab': {'tabProperties': {'title': TAB_TITLE}}}])['replies'][0][
            'addDocumentTab']['tabProperties']['tabId']
        print('создана вкладка', TAB, flush=True)
    st.update({'doc_id': DOC_ID, 'tz_tab': TAB})
    (M / 'review_v4_doc.json').write_text(json.dumps(st))
    try:
        bu([{'updateDocumentStyle': {'documentStyle': {'documentFormat': {'documentMode': 'PAGELESS'}},
                                     'fields': 'documentFormat', 'tabId': TAB}}], tab=False)
    except RuntimeError as e:
        print('pageless не применён:', str(e)[:100], flush=True)


def tab_body():
    for k in range(4):
        try:
            d = get_doc(DOC_ID)
            break
        except Exception:                                  # noqa: BLE001
            if k == 3:
                raise
            time.sleep(10 * (k + 1))
    for t in iter_tabs(d):
        if t['tabProperties']['tabId'] == TAB:
            return t['documentTab']['body']['content']
    raise SystemExit('tab lost')


def main():
    import socket
    socket.setdefaulttimeout(300)
    pravki = J('pravki_v4.json')['all']
    man = J('media_manifest.json', {})
    rows, act, rejected, chs = build_rows(pravki, man)
    print(f"строк {len(rows)} (глав {sum(r['kind'] == 'ch' for r in rows)}, ТЗ {sum(r['kind'] == 'tz' for r in rows)}), "
          f"картинок {sum(len(r['imgs']) for r in rows)}", flush=True)
    ensure_doc()
    body = tab_body()
    first = next(c for c in body if 'paragraph' in c)
    s, e = first['startIndex'], body[-1]['endIndex'] - 1
    if e > s:
        bu([{'deleteContentRange': {'range': {'startIndex': s, 'endIndex': e}}}])

    HEAD = {1: 'HEADING_1', 2: 'HEADING_2'}
    cur = tab_body()[-1]['endIndex'] - 1
    reqs = []
    for h, text, opts in build_head(act, rejected, chs):
        tnl = text + '\n'
        n = u16(tnl)
        reqs += [{'insertText': {'location': {'index': cur}, 'text': tnl}},
                 {'updateParagraphStyle': {'range': {'startIndex': cur, 'endIndex': cur + n},
                                           'paragraphStyle': {'namedStyleType': HEAD.get(h, 'NORMAL_TEXT')},
                                           'fields': 'namedStyleType'}}]
        if opts.get('bold'):
            reqs.append({'updateTextStyle': {'range': {'startIndex': cur, 'endIndex': cur + n - 1},
                                             'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += n
    bu(reqs)

    cur = tab_body()[-1]['endIndex'] - 1
    bu([{'insertTable': {'location': {'index': cur}, 'rows': len(rows) + 1, 'columns': 5}}])
    tbl = [el for el in tab_body() if 'table' in el][-1]
    cells = [row['tableCells'] for row in tbl['table']['tableRows']]
    allc = [HDR] + [r['cells'] for r in rows]
    reqs = []
    for ri in range(len(allc) - 1, -1, -1):
        for cj in range(4, -1, -1):
            txt = str(allc[ri][cj])
            if txt:
                reqs.append({'insertText': {'location': {'index': cells[ri][cj]['content'][0]['startIndex']}, 'text': txt}})
    for i in range(0, len(reqs), 400):
        bu(reqs[i:i + 400])
    print('текст таблицы записан', flush=True)

    trows = [el for el in tab_body() if 'table' in el][-1]['table']['tableRows']
    img_reqs = []
    for ri in range(len(allc) - 1, 0, -1):
        r = rows[ri - 1]
        cell = trows[ri]['tableCells'][4]
        base = cell['content'][0]['startIndex']
        lines = str(r['cells'][4]).split('\n')
        for li, name in sorted(r['imgs'], key=lambda x: -x[0]):
            idx = base + (u16('\n'.join(lines[:li]) + '\n') if li else 0)
            img_reqs.append({'insertInlineImage': {'location': {'index': idx}, 'uri': man[name],
                                                   'objectSize': {'width': {'magnitude': IMG_W, 'unit': 'PT'}}}})
    img_reqs.sort(key=lambda q: -q['insertInlineImage']['location']['index'])
    ok, fails = 0, []
    for i in range(0, len(img_reqs), 20):
        chunk = img_reqs[i:i + 20]
        try:
            bu(chunk)
            ok += len(chunk)
        except Exception as ex:                             # noqa: BLE001
            print('  img batch err → по одной:', str(ex)[:120], flush=True)
            for q in chunk:
                try:
                    bu([q])
                    ok += 1
                except Exception:                           # noqa: BLE001
                    fails.append(q['insertInlineImage']['uri'][:60])
    print(f'картинок {ok}/{len(img_reqs)}, сбоев {len(fails)}', flush=True)

    tbl = [el for el in tab_body() if 'table' in el][-1]
    tstart, trows = tbl['startIndex'], tbl['table']['tableRows']
    sreqs = []

    def style(cell, a0, b0, ts, fields):
        a, b = index_of(cell, a0), index_of(cell, b0)
        if a is not None and b is not None and b > a:
            sreqs.append({'updateTextStyle': {'range': {'startIndex': a, 'endIndex': b}, 'textStyle': ts, 'fields': fields}})
            return True
        return False

    for row in trows:
        for c in row['tableCells']:
            t = cell_text(c)
            if t.strip():
                style(c, 0, len(t.rstrip('\n')), {'fontSize': {'magnitude': FONT, 'unit': 'PT'}}, 'fontSize')
    for c in trows[0]['tableCells']:
        t = cell_text(c)
        if t.strip():
            style(c, 0, len(t.rstrip('\n')), {'bold': True}, 'bold')
    stat = {'bold': 0, 'mono': 0, 'purple': 0, 'caps': 0}
    for ri, r in enumerate(rows, start=1):
        tc = trows[ri]['tableCells']
        c3, c4 = tc[3], tc[4]
        t3, t4 = cell_text(c3), cell_text(c4)
        if r['kind'] == 'ch':
            p = t3.find(r['label'])
            if p >= 0:
                style(c3, p, p + len(r['label']), {'bold': True, 'fontSize': {'magnitude': 10, 'unit': 'PT'}}, 'bold,fontSize')
                a, b = index_of(c3, p), index_of(c3, p + len(r['label']))
                sreqs.append({'updateParagraphStyle': {'range': {'startIndex': a, 'endIndex': b + 1},
                                                       'paragraphStyle': {'namedStyleType': 'HEADING_3'},
                                                       'fields': 'namedStyleType'}})
            sreqs.append({'updateTableCellStyle': {'tableRange': {'tableCellLocation': {
                'tableStartLocation': {'index': tstart}, 'rowIndex': ri, 'columnIndex': 0}, 'rowSpan': 1, 'columnSpan': 5},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': CH_BG.get(r['color'], CH_BG['Green'])}}},
                'fields': 'backgroundColor'}})
        else:
            for cj in (0, 1):
                t = cell_text(tc[cj]).rstrip('\n')
                if t:
                    style(tc[cj], 0, len(t), {'bold': True}, 'bold')
            for span in r['bold']:
                p = t3.find(span)
                if p >= 0 and style(c3, p, p + len(span), {'bold': True}, 'bold'):
                    stat['bold'] += 1
            lines, off = t3.split('\n'), 0
            for i, ln in enumerate(lines):
                if ln.strip() and not ln.startswith(' ' * 8) and i + 1 < len(lines) and lines[i + 1].startswith(' ' * 8):
                    style(c3, off + len(ln) - len(ln.lstrip()), off + len(ln), {'bold': True}, 'bold')
                off += len(ln) + 1
            for m in ITEM_TC.finditer(t3):
                if style(c3, m.start(2), m.end(2), {'weightedFontFamily': {'fontFamily': 'Roboto Mono'},
                                                    'foregroundColor': {'color': {'rgbColor': GREY}}},
                         'weightedFontFamily,foregroundColor'):
                    stat['mono'] += 1
            for span in r['purple']:
                p = t3.find(span)
                if p >= 0 and style(c3, p, p + len(span), {'bold': True, 'foregroundColor': {'color': {'rgbColor': PURPLE}}},
                                    'bold,foregroundColor'):
                    stat['purple'] += 1
            pos = 0
            for sm in r['small']:
                p = t4.find(sm, pos)
                if p >= 0:
                    style(c4, p, p + len(sm), {'fontSize': {'magnitude': 8, 'unit': 'PT'},
                                               'foregroundColor': {'color': {'rgbColor': GREY}}}, 'fontSize,foregroundColor')
                    pos = p + len(sm)
            if r['cat'] in CAT_BG:
                sreqs.append({'updateTableCellStyle': {'tableRange': {'tableCellLocation': {
                    'tableStartLocation': {'index': tstart}, 'rowIndex': ri, 'columnIndex': 2}, 'rowSpan': 1, 'columnSpan': 1},
                    'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': CAT_BG[r['cat']]}}}, 'fields': 'backgroundColor'}})
        for cap in r['caps']:
            p = t4.find(cap)
            if p >= 0 and style(c4, p, p + len(cap), {'bold': True}, 'bold'):
                stat['caps'] += 1
    for cj, w in enumerate(WIDTHS):
        sreqs.append({'updateTableColumnProperties': {'tableStartLocation': {'index': tstart}, 'columnIndices': [cj],
                                                      'tableColumnProperties': {'widthType': 'FIXED_WIDTH',
                                                                                'width': {'magnitude': w, 'unit': 'PT'}},
                                                      'fields': 'widthType,width'}})
    for i in range(0, len(sreqs), 400):
        bu(sreqs[i:i + 400])
    print('стили:', stat, flush=True)

    runs = []

    def walk(content):
        for c in content:
            for e in c.get('paragraph', {}).get('elements', []):
                tr = e.get('textRun')
                if tr and 'http' in tr.get('content', ''):
                    runs.append((e['startIndex'], tr['content']))
            for row in c.get('table', {}).get('tableRows', []):
                for cell in row.get('tableCells', []):
                    walk(cell.get('content', []))
    walk(tab_body())
    lreqs = []
    for start, txt in runs:
        for m in URL_RE.finditer(txt):
            a = start + u16(txt[:m.start()])
            lreqs.append({'updateTextStyle': {'range': {'startIndex': a, 'endIndex': a + u16(m.group(0))},
                                              'textStyle': {'link': {'url': m.group(0)},
                                                            'foregroundColor': {'color': {'rgbColor': LINK}}, 'underline': True},
                                              'fields': 'link,foregroundColor,underline'}})
    for i in range(0, len(lreqs), 400):
        bu(lreqs[i:i + 400])
    print('ссылок:', len(lreqs), '| сбои картинок:', fails[:5])
    print(f'https://docs.google.com/document/d/{DOC_ID}/edit?tab={TAB}')


if __name__ == '__main__':
    main()
