#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «ТЗ монтажёру · v3» в сценарном доке (запрос Романа 07.09: «где google doc»; формат v7 — 10.09).

ОДНА таблица (канон): главы = зрительские экраны-заставки (строки с заливкой + HEADING_3 + [скобки]),
ТЗ из pravki_v2.json (тот же источник, что лист «ТЗ монтажёру» и маркеры секвенции — номера синхронны).

v7 (Роман 10.09, эталон — карта структуры info_structure_map.png):
- «ТЗ монтажёру» — списками: метки блоков и заголовки списков жирным, таймкоды пунктов моноширинным
  серым (▸ встаёт столбцом); в опечатках «было → стало» изменённые знаки красным (стало — жирным
  на розовом, было — зачёркнуто);
- «Материал» — КРУПНОЕ превью (s12: оверлей на реальном кадре + кроп на то, о чём речь) в СВОЁМ
  абзаце на всю ширину колонки; под ним короткая подпись «таймкод · что видно»; ссылки и источник —
  мелким серым;
- комменты Романа 💬 — фиолетовым, один раз (s10 уже кладёт их в текст ТЗ).
build_rows() — чистая функция без записи в док (её использует s13_doc_edits.py); пишет только main().
"""
import copy
import json
import os
import re
import sys
import time
from bisect import bisect_right
from pathlib import Path

M = Path(__file__).parent
sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/ytuvi_doctabs'))
sys.path.insert(0, str(M.parent / 'v6'))
from doctab_lib import DOCS, get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _batch_update  # noqa: E402
from typo_diff import diff_spans, typo_line, typo_offsets  # noqa: E402

DOC_ID = DOCS['01']
# вкладка задаётся снаружи: TZ_TAB='ТЗ монтажёру · v4'. v3 ЗАМОРОЖЕНА — в ней правки Романа
# (он удалял неактуальное руками 11.09), пересобирать её нельзя, иначе правки затрутся.
TAB_TITLE = os.environ.get('TZ_TAB') or 'ТЗ монтажёру · v3'
FROZEN = {'ТЗ монтажёру · v3'}
SHEET_URL = 'https://docs.google.com/spreadsheets/d/1xeCzuOr_W-WuaeehgUOhTWHzYmsdvW7w0wYwT8XPejY/edit'
WIDTHS = [34, 62, 22, 282, 276]          # v7: «Материал» шире; №/TC без переноса «ТЗ / -30», «9:32–10:1 / 0» (сумма 676pt)
FONT = 9
IMG_W = 262                               # превью на всю ширину колонки «Материал» (276 − поля)
HDR = ['№', '⏱ TC', '', 'ТЗ монтажёру', 'Материал / ссылки']
LABELS = ('❌ СЕЙЧАС ·', '✅ СДЕЛАТЬ ·', '📋 СПИСОК ·', '📍 ГДЕ ·', '📚 ИСТОЧНИК ·', '🎬 НА ТАЙМЛАЙНЕ ·')
CH_BG = {'Green': {'red': 0.85, 'green': 0.93, 'blue': 0.85},
         'Yellow': {'red': 0.98, 'green': 0.95, 'blue': 0.78}}
CAT = {'graphics': '🎨', 'structure': '🧭', 'cut': '✂️', 'insert': '➕',
       'color': '🎛', 'check': '🔍'}
CAT_BG = {'cut': {'red': 0.99, 'green': 0.87, 'blue': 0.86},
          'insert': {'red': 0.87, 'green': 0.95, 'blue': 0.87},
          'graphics': {'red': 1.0, 'green': 0.97, 'blue': 0.82},
          'structure': {'red': 1.0, 'green': 0.92, 'blue': 0.82},
          'color': {'red': 0.87, 'green': 0.92, 'blue': 0.98},
          'check': {'red': 0.93, 'green': 0.93, 'blue': 0.93}}
PURPLE = {'red': 0.42, 'green': 0.18, 'blue': 0.70}
RED = {'red': 0.80, 'green': 0.05, 'blue': 0.05}
PINK = {'red': 1.0, 'green': 0.85, 'blue': 0.85}
GREY = {'red': 0.45, 'green': 0.45, 'blue': 0.45}
LINK = {'red': 0.06, 'green': 0.33, 'blue': 0.8}
# пункт «таймкод ▸ …»: s10 добивает «0:57» цифровым пробелом U+2007 до ширины «33:42» — он входит в моно-спан
ITEM_TC = re.compile(r'^( +)( ?~?\d{1,2}:\d{2}(?:\.\d+)?(?:–\d{1,2}:\d{2})?)  ▸ ', re.M)
URL_RE = re.compile(r'https?://[^\s)\]»]+')

CHAPTERS = [
    {'no': 1, 'sec': 0, 'name': 'ВСТУПЛЕНИЕ / ХУК', 'img': 'chapter_0018_tizer.jpg', 'color': 'Green'},
    {'no': 2, 'sec': 135, 'name': 'КОРОЛЬ САМОЦВЕТОВ', 'img': 'chapter_0215_korol.jpg', 'color': 'Green'},
    {'no': 3, 'sec': 377, 'name': 'АНАТОМИЯ ЦВЕТА', 'img': 'chapter_0617_anatomia.jpg', 'color': 'Green'},
    {'no': 5, 'sec': 777, 'name': 'КОМУ ПОДХОДИТ РУБИН', 'img': 'chapter_1257_komu.jpg', 'color': 'Green'},
    {'no': 6, 'sec': 916, 'name': 'ПРОИСХОЖДЕНИЕ РУБИНА', 'img': 'chapter_1516_proishozhdenie.jpg', 'color': 'Green'},
    {'no': 7, 'sec': 1558, 'name': '➕ РЕКОРДЫ АУКЦИОНОВ — НОВАЯ', 'img': 'card_auctions.png', 'color': 'Yellow'},  # тот же драфт, что в ТЗ-19
    {'no': 8, 'sec': 1731, 'name': 'ИСКУССТВЕННЫЙ РУБИН', 'img': 'chapter_2851_iskusstvennyi.jpg', 'color': 'Green'},
    {'no': 9, 'sec': 2019, 'name': 'СПОСОБЫ ОБРАБОТКИ', 'img': 'chapter_3339_obrabotka.jpg', 'color': 'Green'},
    {'no': 10, 'sec': 2322, 'name': 'ФИНАЛ + CTA', 'img': 'chapter_4007_final.jpg', 'color': 'Green'},
]
MATERIALS_FOLDER = 'https://drive.google.com/drive/folders/1s6KJ3ka4L98hwur23KtAraucneMRQN7w'
PROJECT_FOLDER = 'https://drive.google.com/drive/folders/1rVYvtG-5rpUO--DnV9z3n-LJXSUl7hdH'
SPRINT_FOLDER = 'https://drive.google.com/drive/folders/1af9NONmWnWkfvPLdbVGqNjg2Zc1ecxFL'


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def tmm(sec):
    t = int(round(sec))
    return f'{t // 60}:{t % 60:02d}'


def tc_sec(tc):
    m = re.match(r'(\d+):(\d{2})', str(tc).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def clean(t):
    return re.sub(r'\s+', ' ', str(t or '').strip())


def load():
    return (json.load(open(M / 'pravki_v2.json'))['all'], json.load(open(M / 'shots_ids.json')),
            json.load(open(M / 'proj_material_ids.json')) if (M / 'proj_material_ids.json').exists() else {},
            json.load(open(M / 'drive_clips.json')))


# ═══════════════════ чистая сборка строк таблицы ═══════════════════
def clip_link_line(text, drive_clips):
    for name in re.findall(r'RYA-[A-Z0-9]+-\d{3,4}', text or ''):
        e = drive_clips.get(name + '.MP4') or drive_clips.get(name + '.MOV')
        if e:
            return f'🔗 клип: https://drive.google.com/file/d/{e[0]["id"]}/view'
    return None


def mat_cell(p, shots_ids, proj_ids, drive_clips):
    """→ (текст, [(индекс пустой строки под картинку, имя)], подписи, мелкие строки)"""
    lines, imgs, caps, small = [], [], [], []
    for it in p.get('material_rich') or []:
        disp = it.get('preview') or it.get('img')
        if disp and disp in shots_ids:
            imgs.append((len(lines), disp))
            lines.append('')                                   # свой абзац под картинку
        cap, t = clean(it.get('cap')), clean(it.get('t'))
        if cap:
            lines.append(cap)
            caps.append(cap)
            if t and not it.get('cap_replaces_t') and t not in cap:
                lines.append('• ' + t)
        elif t:
            lines.append('• ' + t)
        for s in ([clip_link_line(it.get('t'), drive_clips)] +
                  [f'🔗 файл: https://drive.google.com/file/d/{fid}/view'
                   for fid in [(proj_ids.get(it['img']) or shots_ids.get(it['img'])) if it.get('img') else None] if fid] +
                  (['📚 источник: ' + clean(it['src'])] if it.get('src') else [])):
            if s:
                lines.append(s)
                small.append(s)
    return '\n'.join(lines), imgs, caps, small


def tz_row(p, shots_ids, proj_ids, drive_clips):
    title = clean(p['title'])
    body = f"【{title}】\n{p['nado']}"
    if p.get('decision'):
        body += '\n❓ РЕШЕНИЕ РОМАНА: ' + p['decision']
    purple = []
    for c in p.get('roman_comment') or []:                 # s10 уже печатает «💬 …» в nado — не дублируем
        line = '💬 ' + c
        if line not in body:
            body += '\n' + line
        purple.append(line)
    bold = [f'【{title}】'] + [l for l in LABELS if l in body] + (['❓ РЕШЕНИЕ РОМАНА:'] if p.get('decision') else [])
    mat, imgs, caps, small = mat_cell(p, shots_ids, proj_ids, drive_clips)
    return {'kind': 'tz', 'num': p['num'], 'cat': p['category'],
            'cells': [p['num'], f"⏱ {p.get('tc_range', p['v1_tc'])}", CAT.get(p['category'], '·'), body, mat],
            'bold': bold, 'purple': purple, 'imgs': imgs, 'caps': caps, 'small': small,
            'typo': p.get('typo') or []}


def clean_title(t):
    """заголовок для шапки: без переносов и OCR-скобок «ПУТАЛ[И]» → «ПУТАЛИ»"""
    return clean(re.sub(r'\[([^\]]*)\]', r'\1', str(t or '')).replace('\n', ' / '))


def build_head(act, rejected):
    """шапка вкладки — СПИСКАМИ (финальный QA 10.09: сплошные абзацы в шапке тоже не читаются)"""
    decisions = [p for p in act if p.get('decision')]
    li = lambda t: (0, '▸ ' + t, {})                                            # noqa: E731
    head = [
        (1, f'YTUVI01 · {TAB_TITLE} — по секвенции Review_v6_tz (формат 11.09)', {}),
        (0, 'Как читать:', {'bold': True}),
        li('каждый таймкод — отдельной строкой: «таймкод ▸ что там», как в карте структуры'),
        li('справа — крупное превью: наш драфт или стрелка на реальном кадре, кроп на то, о чём речь; под ним «таймкод · что видно»'),
        li('опечатки — строкой «было → стало»: изменённые знаки выделены в доке красным'),
        li('суммы — цифрами'),
        (0, 'Рабочая секвенция: YTUVI01_5_Review_v6_tz_v1 (или последняя _vN) — панель UXP → Review → Review_v6. Слои:', {'bold': True}),
        li('V1 — оригинал монтажёра (не тронут)'),
        li('V2 — футажи: видео и фото'),
        li('V3 — инфографика, плашки терминов, мини-карты локаций, нарисованные исправления'),
        li('V4 — плашки ТЗ: полный текст и ссылки (маркер клипа / кнопка панели «Copy ТЗ @ playhead»)'),
        li('V5 — стрелки правок на кадре'),
        li('V6 — главы, подглавы, прогресс перечислений гл.08/09'),
        li('маркеры секвенции — только 10 разноцветных глав; глава «Проверка геммолога» удалена (07.09); CTA сразу после рендера'),
        (0, 'Ссылки:', {'bold': True}),
        li(f'живой чек-лист со статусами — лист «ТЗ монтажёру»: {SHEET_URL}'),
        li('полный разбор с транскрибацией — вкладка «Ревью v2 · правки»'),
        li(f'📁 все материалы (на каждом файле — коммент с ТЗ, таймкодом и источником): {MATERIALS_FOLDER}'),
        li(f'📁 папка проекта: {PROJECT_FOLDER}'),
        li(f'📁 спринт YTUVI S1: {SPRINT_FOLDER}'),
        (2, f'❓ Решения Романа ({len(decisions)})', {}),
    ]
    for p in decisions:
        head.append((0, f"• {p['num']} · {p['v1_tc']} · {clean_title(p['title'])} — {p['decision']}", {}))
    if rejected:
        head.append((0, '🚫 Снято Романом (09–10.09) — не менять, номера сохранены:', {'bold': True}))
        for p in rejected:
            head.append(li(f"{p['num']} · {clean_title(p['title'])}"))
    return head


def build_rows(pravki_all, shots_ids, proj_ids, drive_clips):
    """ЧИСТО: → (rows, head). rows[i] = dict(kind, cells[5], bold, purple, imgs, caps, small, typo, …)"""
    pr = copy.deepcopy(pravki_all)
    for i, p in enumerate(pr):
        p['num'] = f'ТЗ-{i + 1:02d}'
        p['_sec'] = tc_sec(p['v1_tc'].split('–')[0].split('/')[0])
    rejected = [p for p in pr if p.get('status') == 'rejected']      # Роман снял — номера сохранены, строк нет
    act = [p for p in pr if p.get('status') != 'rejected']
    ch_starts = [c['sec'] for c in CHAPTERS]
    by_ch = {i: [] for i in range(len(CHAPTERS))}
    for p in act:
        if p['_sec'] is not None:
            by_ch[max(0, bisect_right(ch_starts, p['_sec'] + 0.01) - 1)].append(p)
    for lst in by_ch.values():                                 # QA 10.09: внутри главы — по времени, не по номеру ТЗ
        lst.sort(key=lambda p: p['_sec'])
    rows = []
    for p in act:
        if p['_sec'] is None:                                  # ТЗ-30 «весь фильм» — первой строкой
            r = tz_row(p, shots_ids, proj_ids, drive_clips)
            r['cells'][1] = '⏱ весь фильм'
            rows.append(r)
    for ci, ch in enumerate(CHAPTERS):
        ch_end = CHAPTERS[ci + 1]['sec'] if ci + 1 < len(CHAPTERS) else 2440
        label = f"[{ch.get('no', ci + 1)}. {ch['name']} · {tmm(ch['sec'])}–{tmm(ch_end)}]"
        rows.append({'kind': 'ch', 'label': label, 'color': ch['color'], 'cat': None,
                     'cells': ['', '', '', label, ''], 'bold': [], 'purple': [], 'caps': [], 'small': [],
                     'typo': [], 'imgs': [(-1, ch['img'])] if ch.get('img') else []})
        for p in by_ch.get(ci) or []:
            rows.append(tz_row(p, shots_ids, proj_ids, drive_clips))
    return rows, build_head(act, rejected)


# ═══════════════════ запись во вкладку ═══════════════════
def batch_update(doc_id, reqs, tries=5):
    """backoff на 429/5xx и сетевые сбои (doctab_lib не ретраит)"""
    for k in range(tries):
        try:
            return _batch_update(doc_id, reqs)
        except RuntimeError as e:
            m = re.search(r'Docs API (\d+)', str(e))
            if m and m.group(1) in ('429', '500', '502', '503', '504') and k < tries - 1:
                time.sleep(6 * 2 ** k)
                continue
            raise
        except OSError:
            if k < tries - 1:
                time.sleep(6 * 2 ** k)
                continue
            raise


def cell_text(cell):
    return ''.join(e['textRun'].get('content', '') for c in cell.get('content', [])
                   for e in c.get('paragraph', {}).get('elements', []) if 'textRun' in e)


def index_of(cell, pos):
    """смещение в тексте ячейки (только textRun, картинки не считаются) → индекс документа"""
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


def main(force=False):
    if TAB_TITLE in FROZEN and not force:
        raise SystemExit(f'«{TAB_TITLE}» заморожена: там правки Романа. Запускай с TZ_TAB=«ТЗ монтажёру · v4».')
    import socket
    socket.setdefaulttimeout(300)                              # зависшее соединение не должно висеть вечно
    pravki, shots_ids, proj_ids, drive_clips = load()
    rows, headp = build_rows(pravki, shots_ids, proj_ids, drive_clips)
    n_imgs = sum(len(r['imgs']) for r in rows)
    print(f"строк: {len(rows)} (глав {sum(r['kind'] == 'ch' for r in rows)}, ТЗ {sum(r['kind'] == 'tz' for r in rows)}), "
          f'картинок {n_imgs}', flush=True)

    doc = get_doc(DOC_ID)
    tab_id = next((t['tabProperties']['tabId'] for t in iter_tabs(doc)
                   if t['tabProperties'].get('title') == TAB_TITLE), None)
    if tab_id is None:
        resp = batch_update(DOC_ID, [{'addDocumentTab': {'tabProperties': {'title': TAB_TITLE}}}])
        tab_id = resp['replies'][0]['addDocumentTab']['tabProperties']['tabId']
        print('создана вкладка', tab_id)
    else:
        print('вкладка найдена', tab_id)

    def tab_body():
        """весь док (~30 с: get_doc тянет все вкладки) → тело нашей вкладки; с повтором на сетевые сбои"""
        for k in range(4):
            try:
                d = get_doc(DOC_ID)
                break
            except Exception as e:                               # noqa: BLE001
                if k == 3:
                    raise
                print('  get_doc повтор:', str(e)[:100], flush=True)
                time.sleep(10 * (k + 1))
        for t in iter_tabs(d):
            if t['tabProperties']['tabId'] == tab_id:
                return t['documentTab']['body']['content']
        raise SystemExit('tab lost')

    body = tab_body()
    first = next(c for c in body if 'paragraph' in c)
    start, end = first['startIndex'], body[-1]['endIndex'] - 1
    if end > start:
        batch_update(DOC_ID, [{'deleteContentRange': {
            'range': {'tabId': tab_id, 'startIndex': start, 'endIndex': end}}}])
    print('вкладка очищена', flush=True)

    # ── шапка — ОДНОЙ пачкой: индексы считаем сами (раньше get_doc на каждый абзац = ~30 с × 13) ──
    HEAD = {1: 'HEADING_1', 2: 'HEADING_2'}
    cur = tab_body()[-1]['endIndex'] - 1
    reqs = []
    for h, text, opts in headp:
        tnl = text + '\n'
        n = u16(tnl)
        reqs += [{'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': tnl}},
                 {'updateParagraphStyle': {
                     'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n},
                     'paragraphStyle': {'namedStyleType': HEAD.get(h, 'NORMAL_TEXT')},
                     'fields': 'namedStyleType'}}]
        if opts.get('bold'):
            reqs.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n - 1},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += n
    batch_update(DOC_ID, reqs)
    print(f'шапка: {len(headp)} абзацев', flush=True)

    # ── таблица + текст (с конца, чтобы индексы не ехали) ──
    cur = tab_body()[-1]['endIndex'] - 1
    batch_update(DOC_ID, [{'insertTable': {'location': {'tabId': tab_id, 'index': cur},
                                           'rows': len(rows) + 1, 'columns': 5}}])
    tbl = [el for el in tab_body() if 'table' in el][-1]
    cells = [row['tableCells'] for row in tbl['table']['tableRows']]
    all_cells = [HDR] + [r['cells'] for r in rows]
    reqs = []
    for ri in range(len(all_cells) - 1, -1, -1):
        for cj in range(4, -1, -1):
            txt = str(all_cells[ri][cj])
            if txt:
                reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cells[ri][cj]['content'][0]['startIndex']},
                                            'text': txt}})
    for i in range(0, len(reqs), 400):
        batch_update(DOC_ID, reqs[i:i + 400])
        print(f'text batch {i // 400 + 1}', flush=True)

    # ── картинки: превью в своём пустом абзаце (материал), у глав — в конец ячейки ──
    trows = [el for el in tab_body() if 'table' in el][-1]['table']['tableRows']
    img_reqs = []
    for ri in range(len(all_cells) - 1, 0, -1):
        r = rows[ri - 1]
        if not r['imgs']:
            continue
        cell = trows[ri]['tableCells'][4]
        base = cell['content'][0]['startIndex']
        lines = str(r['cells'][4]).split('\n')
        for li, name in sorted(r['imgs'], key=lambda x: -x[0]):
            did = shots_ids.get(name)
            if not did:
                continue
            idx = cell['endIndex'] - 1 if li < 0 else base + (u16('\n'.join(lines[:li]) + '\n') if li else 0)
            img_reqs.append({'insertInlineImage': {
                'location': {'tabId': tab_id, 'index': idx},
                'uri': f'https://drive.google.com/uc?export=view&id={did}',
                'objectSize': {'width': {'magnitude': IMG_W, 'unit': 'PT'}}}})
    img_reqs.sort(key=lambda q: -q['insertInlineImage']['location']['index'])
    ok, fails = 0, []
    for i in range(0, len(img_reqs), 20):
        chunk = img_reqs[i:i + 20]
        try:
            batch_update(DOC_ID, chunk)
            ok += len(chunk)
        except Exception as e:                                   # по одной — битая картинка не валит пачку
            print('  img batch err → по одной:', str(e)[:120], flush=True)
            for q in chunk:
                try:
                    batch_update(DOC_ID, [q])
                    ok += 1
                except Exception as e2:
                    fails.append(q['insertInlineImage']['uri'])
                    print('  img err:', str(e2)[:120])
        print(f'  картинки {ok}/{len(img_reqs)}', flush=True)
    print(f'картинок: {ok}, сбоев: {len(fails)}', flush=True)

    # ── стили ──
    tbl = [el for el in tab_body() if 'table' in el][-1]
    tstart = tbl['startIndex']
    trows = tbl['table']['tableRows']
    sreqs = []

    def style(cell, s, e, text_style, fields):
        a, b = index_of(cell, s), index_of(cell, e)
        if a is not None and b is not None and b > a:
            sreqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': a, 'endIndex': b},
                                              'textStyle': text_style, 'fields': fields}})
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

    stat = {'bold': 0, 'head': 0, 'mono': 0, 'typo': 0, 'purple': 0, 'caps': 0}
    for ri, r in enumerate(rows, start=1):
        tc = trows[ri]['tableCells']
        c3, c4 = tc[3], tc[4]
        t3, t4 = cell_text(c3), cell_text(c4)
        if r['kind'] == 'ch':
            p = t3.find(r['label'])
            if p >= 0:
                style(c3, p, p + len(r['label']), {'bold': True, 'fontSize': {'magnitude': 10, 'unit': 'PT'}}, 'bold,fontSize')
                a, b = index_of(c3, p), index_of(c3, p + len(r['label']))
                sreqs.append({'updateParagraphStyle': {
                    'range': {'tabId': tab_id, 'startIndex': a, 'endIndex': b + 1},
                    'paragraphStyle': {'namedStyleType': 'HEADING_3'}, 'fields': 'namedStyleType'}})
            sreqs.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {'tableStartLocation': {'tabId': tab_id, 'index': tstart},
                                                     'rowIndex': ri, 'columnIndex': 0},
                               'rowSpan': 1, 'columnSpan': 5},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': CH_BG.get(r['color'], CH_BG['Green'])}}},
                'fields': 'backgroundColor'}})
            continue
        for cj in (0, 1):                                      # № + TC жирным целиком
            t = cell_text(tc[cj]).rstrip('\n')
            if t:
                style(tc[cj], 0, len(t), {'bold': True}, 'bold')
        for span in r['bold']:
            p = t3.find(span)
            if p >= 0 and style(c3, p, p + len(span), {'bold': True}, 'bold'):
                stat['bold'] += 1
        # заголовки списков: строка, за которой идут пункты с отступом 8 пробелов
        lines = t3.split('\n')
        off = 0
        for i, ln in enumerate(lines):
            if ln.strip() and not ln.startswith(' ' * 8) and i + 1 < len(lines) and lines[i + 1].startswith(' ' * 8):
                s = off + len(ln) - len(ln.lstrip())
                if style(c3, s, off + len(ln), {'bold': True}, 'bold'):
                    stat['head'] += 1
            off += len(ln) + 1
        for m in ITEM_TC.finditer(t3):                         # таймкоды пунктов — моноширинные серые
            if style(c3, m.start(2), m.end(2), {'weightedFontFamily': {'fontFamily': 'Roboto Mono'},
                                                'foregroundColor': {'color': {'rgbColor': GREY}}},
                     'weightedFontFamily,foregroundColor'):
                stat['mono'] += 1
        for ty in r['typo']:                                   # опечатки: изменённые знаки — красным
            line = typo_line(ty['was'], ty['now'])
            p = t3.find(line)
            if p < 0:
                print('  !! typo-строка не найдена:', r['num'], line)
                continue
            wo, no = typo_offsets(ty['was'])
            sw, sn = diff_spans(ty['was'], ty['now'])
            for s, e in sn:
                stat['typo'] += style(c3, p + no + s, p + no + e,
                                      {'bold': True, 'foregroundColor': {'color': {'rgbColor': RED}},
                                       'backgroundColor': {'color': {'rgbColor': PINK}}},
                                      'bold,foregroundColor,backgroundColor')
            for s, e in sw:
                stat['typo'] += style(c3, p + wo + s, p + wo + e,
                                      {'strikethrough': True, 'foregroundColor': {'color': {'rgbColor': RED}},
                                       'backgroundColor': {'color': {'rgbColor': PINK}}},
                                      'strikethrough,foregroundColor,backgroundColor')
        for span in r['purple']:                               # 💬 комменты Романа — фиолетовым, жирным
            p = t3.find(span)
            if p >= 0 and style(c3, p, p + len(span), {'bold': True, 'foregroundColor': {'color': {'rgbColor': PURPLE}}},
                                'bold,foregroundColor'):
                stat['purple'] += 1
        for cap in r['caps']:                                  # подпись под превью — жирным
            p = t4.find(cap)
            if p >= 0 and style(c4, p, p + len(cap), {'bold': True}, 'bold'):
                stat['caps'] += 1
        pos = 0
        for sm in r['small']:                                  # ссылки и источник — мелким серым
            p = t4.find(sm, pos)
            if p >= 0:
                style(c4, p, p + len(sm), {'fontSize': {'magnitude': 8, 'unit': 'PT'},
                                           'foregroundColor': {'color': {'rgbColor': GREY}}}, 'fontSize,foregroundColor')
                pos = p + len(sm)
        if r['cat'] in CAT_BG:
            sreqs.append({'updateTableCellStyle': {
                'tableRange': {'tableCellLocation': {'tableStartLocation': {'tabId': tab_id, 'index': tstart},
                                                     'rowIndex': ri, 'columnIndex': 2},
                               'rowSpan': 1, 'columnSpan': 1},
                'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': CAT_BG[r['cat']]}}},
                'fields': 'backgroundColor'}})
    for cj, w in enumerate(WIDTHS):
        sreqs.append({'updateTableColumnProperties': {
            'tableStartLocation': {'tabId': tab_id, 'index': tstart},
            'columnIndices': [cj],
            'tableColumnProperties': {'widthType': 'FIXED_WIDTH', 'width': {'magnitude': w, 'unit': 'PT'}},
            'fields': 'widthType,width'}})
    for i in range(0, len(sreqs), 400):
        batch_update(DOC_ID, sreqs[i:i + 400])
        print(f'style batch {i // 400 + 1}/{(len(sreqs) + 399) // 400}', flush=True)
    print('стили:', stat, flush=True)

    # ── АКТИВНЫЕ ссылки (Роман 07.09): все URL во вкладке → textStyle.link ──
    runs = []

    def walk_runs(content):
        for c in content:
            for e in c.get('paragraph', {}).get('elements', []):
                tr = e.get('textRun')
                if tr and 'http' in tr.get('content', ''):
                    runs.append((e['startIndex'], tr['content']))
            for row in c.get('table', {}).get('tableRows', []):
                for cell in row.get('tableCells', []):
                    walk_runs(cell.get('content', []))
    walk_runs(tab_body())
    lreqs = []
    for start, txt in runs:
        for m in URL_RE.finditer(txt):
            s = start + u16(txt[:m.start()])
            lreqs.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': s, 'endIndex': s + u16(m.group(0))},
                'textStyle': {'link': {'url': m.group(0)}, 'foregroundColor': {'color': {'rgbColor': LINK}},
                              'underline': True},
                'fields': 'link,foregroundColor,underline'}})
    for i in range(0, len(lreqs), 400):
        batch_update(DOC_ID, lreqs[i:i + 400])
    print('активных ссылок:', len(lreqs))
    if fails:
        print('⚠️ не вставились картинки:', fails)
    print(f'https://docs.google.com/document/d/{DOC_ID}/edit?tab={tab_id}')


if __name__ == '__main__':
    main()
