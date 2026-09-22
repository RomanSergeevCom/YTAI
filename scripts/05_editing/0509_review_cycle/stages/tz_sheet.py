#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Лист «ТЗ монтажёру» в таблице «YTUVI01 Review Notes» (запрос Романа 07.09:
«документ перенеси в гугл-таблицу, добавляй ссылки и скриншоты»).

Источник: pravki_v2.json (30 ТЗ, номера = вкладке дока «Ревью v2 · правки» и
маркерам секвенции Review_v3_tz). Ссылки: drive_clips.json (клипы пула) +
shots_ids.json (скриншоты/мокапы в gdrive:YTUVI_plan_v3_shots).
Идемпотентно: лист пересоздаётся целиком при каждом запуске.
"""
import json
import sys
import urllib.parse
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT, T, LANG, tz_label  # noqa: E402
from doctab_lib import access_token  # noqa: E402
import urllib.request

# id листа — из карточки (notes_sheet_id); легаси — pravki/notes_sheet.json; пусто = отказ (лист чужого фильма хуже отсутствия)
SID = (P.get('notes_sheet_id') or (json.loads((M / 'notes_sheet.json').read_text())['id']
                                   if (M / 'notes_sheet.json').exists() else P.need('notes_sheet_id')))
TAB = T('c2.sheet_tab')                   # 'ТЗ монтажёру' / 'Edit notes'
HDR = list(T('c2.sheet_hdr'))             # ['ТЗ', 'v1 TC', …, '⏳ Решение Романа', 'Статус'] / EN — с ним же сверяет verify ниже

pravki = json.loads((M / 'pravki_v2.json').read_text())['all']
_opt = lambda p: __import__('json').load(open(p)) if p.exists() else {}
# необязательные обогащалки от мягкой стадии drive: без публичной папки кадров их нет
drive_clips = _opt(M / 'drive_clips.json')
shots_ids = _opt(M / 'shots_ids.json')
# файлы материалов в Drive-папке проекта (Review_materials) — ссылки ведём ТУДА,
# на каждом файле висит коммент с ТЗ/таймкодом/источником
proj_ids = json.loads((M / 'proj_material_ids.json').read_text()) \
    if (M / 'proj_material_ids.json').exists() else {}

MATERIALS_FOLDER = P.folder_url('materials_id')          # дубль 2 из 4 — теперь из карточки
PROJECT_FOLDER = P.folder_url('project_folder_id')
SPRINT_FOLDER = P.folder_url('sprint_folder_id')

CAT = {k: T(f'c2.sheet_cat.{k}') for k in ('cut', 'insert', 'graphics', 'structure', 'color', 'check')}
CAT_BG = {'cut': {'red': 0.99, 'green': 0.87, 'blue': 0.86},
          'insert': {'red': 0.87, 'green': 0.95, 'blue': 0.87},
          'graphics': {'red': 1.0, 'green': 0.97, 'blue': 0.82},
          'structure': {'red': 1.0, 'green': 0.92, 'blue': 0.82},
          'color': {'red': 0.87, 'green': 0.92, 'blue': 0.98},
          'check': {'red': 0.93, 'green': 0.93, 'blue': 0.93}}


def api(method, url, body=None):
    req = urllib.request.Request(url, method=method,
                                 headers={'Authorization': f'Bearer {access_token()}',
                                          'Content-Type': 'application/json'})
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        print('API ERROR:', e.read().decode()[:800])
        raise


# --dump-rows FILE: весь путь листа на офлайн-двойнике Sheets API — вызовы и строки → FILE, без Google API
DUMP = sys.argv[sys.argv.index('--dump-rows') + 1] if '--dump-rows' in sys.argv else None
if DUMP:
    _CALLS, _PUT = [], {}

    def api(method, url, body=None):  # noqa: F811
        _CALLS.append({'method': method, 'url': url, 'body': body})
        if method == 'GET' and '/values/' in url:
            return {'values': _PUT.get('values', [])}
        if method == 'GET':
            return {'sheets': []}
        if method == 'PUT':
            _PUT['values'] = body['values']
            return {}
        if url.endswith(':batchUpdate'):
            return {'replies': [{} for _ in body['requests'][:-1]] + [{'addSheet': {'properties': {'sheetId': 0}}}]}
        return {}


def q(v):
    v = str(v)
    return "'" + v if v and (v[0].isdigit() or v[0] in "=+") else v


# легенда — c2.sheet_legend; спринт — card sprint_name (иначе «{канал} S1», было зашито «YTUVI S1»);
# RU-шаблон ссылается на вкладки литералами (как было), EN — на имена из карточки
LEGEND = T('c2.sheet_legend', code=P.CODE, materials=MATERIALS_FOLDER, project=PROJECT_FOLDER, sprint=SPRINT_FOLDER,
           sprint_name=P.get('sprint_name') or T('c2.sprint_default', ch=P.CHANNEL),
           nav_tab=P.get('nav_tab') or T('c2.nav_tab_default').replace('{ver}', P.CUT_VERSION),
           tz_tab=P.get('tab_title') or str(P.profile('doc.tab_tz_template', T('c2.tz_tab_template'))).format(ver=P.CUT_VERSION))


def clip_link(text):
    """К упоминанию клипа RYA-XXX-NNNN в тексте материала — Drive-ссылка из пула."""
    import re
    m = re.search(r'(RYA-[A-Z0-9]+-\d{4})', text)
    if not m:
        return None
    e = drive_clips.get(m.group(1) + '.MP4')
    return f'https://drive.google.com/file/d/{e[0]["id"]}/view' if e else None


def img_formula(img_name):
    did = shots_ids.get(img_name)
    return f'=IMAGE("https://drive.google.com/uc?export=view&id={did}")' if did else ''


# ── строки ──
rows = []
decision_rows = []          # индексы (0-based среди данных) для оранжевой подсветки
purple_rows = []            # строки с 💬 комментами Романа (фиолетовый текст в J)
for i, p in enumerate(pravki):
    key = f'ТЗ-{i + 1:02d}'                     # внутренний ключ (данные)
    num = tz_label(i + 1)                      # что видит монтажёр: ТЗ-07 / FIX-07
    if p.get('status') == 'rejected':          # Роман снял (вкладка дока 09.09) — номер сохраняем, строку не пишем
        continue
    mat_lines, imgs = [], []
    for mr in p.get('material_rich') or []:
        t = mr['t']
        link = clip_link(t)
        if link:
            t += f'\n{T("c2.link_clip")}{link}'
        img = mr.get('img')
        if img:  # ссылка на файл ВСЕГДА: приоритет — папка проекта (там комменты)
            fid = proj_ids.get(img) or shots_ids.get(img)
            if fid:
                t += f'\n{T("c2.link_file")}https://drive.google.com/file/d/{fid}/view'
        mat_lines.append('• ' + t)
        if mr.get('src'):
            mat_lines.append(T('c2.src_prefix') + mr['src'])
        if mr.get('preview') or img:             # v7: крупное превью «про что речь» (s12), иначе оригинал
            imgs.append(mr.get('preview') or img)
    imgs = imgs[:3] + [''] * (3 - min(3, len(imgs)))
    # ТЗ-02 (легаси YTUVI01): в pravki category=check, но там реальная работа (русская плашка) — не прятать.
    # Только для ru: на английском канале второе ТЗ — чужое, категорию не подменяем.
    cat = 'graphics' if (key == 'ТЗ-02' and LANG == 'ru') else p['category']
    status = T('c2.sheet_status_decide') if p.get('decision') else ('info' if cat == 'check' else 'todo')
    if p.get('decision'):
        decision_rows.append(len(rows))
    rc = p.get('roman_comment') or []
    if rc:
        purple_rows.append(len(rows))
    jcell = '\n'.join(([p['decision']] if p.get('decision') else []) + ['💬 ' + c for c in rc])
    rows.append([
        q(num), q(p['tc_range']), CAT.get(cat, cat), p['title'],
        q(p['nado']), '\n'.join(mat_lines),
        img_formula(imgs[0]) if imgs[0] else '',
        img_formula(imgs[1]) if imgs[1] else '',
        img_formula(imgs[2]) if imgs[2] else '',
        jcell, status,
    ])
    p['_cat_shown'] = cat

# ── лист: снести и создать заново (идемпотентно) ──
meta = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{SID}?fields=sheets.properties')
old = next((s['properties']['sheetId'] for s in meta['sheets']
            if s['properties']['title'] == TAB), None)
reqs = []
if old is not None:
    reqs.append({'deleteSheet': {'sheetId': old}})
reqs.append({'addSheet': {'properties': {'title': TAB, 'index': 1,
                                         'gridProperties': {'rowCount': max(60, len(rows) + 10), 'columnCount': 12}}}})
res = api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{SID}:batchUpdate',
          {'requests': reqs})
gid = res['replies'][-1]['addSheet']['properties']['sheetId']

api('PUT', f'https://sheets.googleapis.com/v4/spreadsheets/{SID}/values/'
    f'{urllib.parse.quote(TAB + "!A1")}?valueInputOption=USER_ENTERED',
    {'values': [['ℹ️', '', LEGEND], HDR] + rows})

# ── вёрстка (в стиле notes_sync.cmd_fmt) ──
def fmt_col(c0, c1, width, wrap='WRAP', font=10, bold=False, fg=None, bg=None,
            halign='LEFT', valign='TOP'):
    fmt = {'wrapStrategy': wrap, 'verticalAlignment': valign, 'horizontalAlignment': halign,
           'textFormat': {'fontSize': font, 'bold': bold}}
    if fg:
        fmt['textFormat']['foregroundColor'] = fg
    if bg:
        fmt['backgroundColor'] = bg
    return [
        {'updateDimensionProperties': {
            'range': {'sheetId': gid, 'dimension': 'COLUMNS', 'startIndex': c0, 'endIndex': c1},
            'properties': {'pixelSize': width}, 'fields': 'pixelSize'}},
        {'repeatCell': {
            'range': {'sheetId': gid, 'startRowIndex': 2, 'endRowIndex': len(rows) + 2,
                      'startColumnIndex': c0, 'endColumnIndex': c1},
            'cell': {'userEnteredFormat': fmt},
            'fields': 'userEnteredFormat(wrapStrategy,verticalAlignment,horizontalAlignment,'
                      'textFormat,backgroundColor)'}},
    ]

reqs = [
    {'updateSheetProperties': {'properties': {'sheetId': gid, 'gridProperties': {
        'frozenRowCount': 2, 'frozenColumnCount': 2}},
        'fields': 'gridProperties.frozenRowCount,gridProperties.frozenColumnCount'}},
    {'updateDimensionProperties': {
        'range': {'sheetId': gid, 'dimension': 'ROWS', 'startIndex': 2, 'endIndex': len(rows) + 2},
        'properties': {'pixelSize': 135}, 'fields': 'pixelSize'}},
    # строка 1 — легенда (объединённая, перенос), строка 2 — шапка таблицы
    {'updateDimensionProperties': {
        'range': {'sheetId': gid, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 1},
        'properties': {'pixelSize': 88}, 'fields': 'pixelSize'}},
    {'updateDimensionProperties': {
        'range': {'sheetId': gid, 'dimension': 'ROWS', 'startIndex': 1, 'endIndex': 2},
        'properties': {'pixelSize': 30}, 'fields': 'pixelSize'}},
    # merge не может пересекать границу frozenColumnCount=2 → легенда в C1:K1
    {'mergeCells': {'range': {'sheetId': gid, 'startRowIndex': 0, 'endRowIndex': 1,
                              'startColumnIndex': 2, 'endColumnIndex': 11},
                    'mergeType': 'MERGE_ALL'}},
    {'repeatCell': {
        'range': {'sheetId': gid, 'startRowIndex': 0, 'endRowIndex': 1},
        'cell': {'userEnteredFormat': {
            'textFormat': {'fontSize': 9},
            'backgroundColor': {'red': 0.98, 'green': 0.97, 'blue': 0.92},
            'wrapStrategy': 'WRAP', 'verticalAlignment': 'MIDDLE'}},
        'fields': 'userEnteredFormat(textFormat,backgroundColor,wrapStrategy,verticalAlignment)'}},
    {'repeatCell': {
        'range': {'sheetId': gid, 'startRowIndex': 1, 'endRowIndex': 2},
        'cell': {'userEnteredFormat': {
            'textFormat': {'bold': True, 'fontSize': 10},
            'backgroundColor': {'red': 0.93, 'green': 0.94, 'blue': 0.95},
            'wrapStrategy': 'CLIP', 'verticalAlignment': 'MIDDLE'}},
        'fields': 'userEnteredFormat(textFormat,backgroundColor,wrapStrategy,verticalAlignment)'}},
    {'setBasicFilter': {'filter': {'range': {
        'sheetId': gid, 'startRowIndex': 1, 'endRowIndex': 60,
        'startColumnIndex': 0, 'endColumnIndex': 11}}}},
]
reqs += fmt_col(0, 1, 58, bold=True, halign='CENTER', valign='MIDDLE')       # A ТЗ
reqs += fmt_col(1, 2, 92, bold=True, halign='CENTER')                        # B v1 TC
reqs += fmt_col(2, 3, 96, font=9, halign='CENTER', valign='MIDDLE')          # C Тип
reqs += fmt_col(3, 4, 170, bold=True, font=9)                                # D Название
reqs += fmt_col(4, 5, 420)                                                   # E Что сделать
reqs += fmt_col(5, 6, 340, font=9)                                           # F Материал
reqs += fmt_col(6, 9, 240)                                                   # G-I кадры
reqs += fmt_col(9, 10, 260, bg={'red': 1.0, 'green': 0.95, 'blue': 0.87})    # J решение
reqs += fmt_col(10, 11, 64, halign='CENTER', valign='MIDDLE')                # K статус
# тип — фон по категории (как показана в листе)
shown = [p for p in pravki if p.get('status') != 'rejected']       # порядок строк листа = pravki без снятых
for i, p in enumerate(shown):
    bg = CAT_BG.get(p.get('_cat_shown') or p['category'])
    if bg:
        reqs.append({'repeatCell': {
            'range': {'sheetId': gid, 'startRowIndex': i + 2, 'endRowIndex': i + 3,
                      'startColumnIndex': 2, 'endColumnIndex': 3},
            'cell': {'userEnteredFormat': {'backgroundColor': bg}},
            'fields': 'userEnteredFormat.backgroundColor'}})
# строки с 💬 комментами Романа — фиолетовый жирный текст в J
for r in purple_rows:
    reqs.append({'repeatCell': {
        'range': {'sheetId': gid, 'startRowIndex': r + 2, 'endRowIndex': r + 3,
                  'startColumnIndex': 9, 'endColumnIndex': 10},
        'cell': {'userEnteredFormat': {'textFormat': {'bold': True, 'fontSize': 10,
                 'foregroundColor': {'red': 0.42, 'green': 0.18, 'blue': 0.70}}, 'wrapStrategy': 'WRAP'}},
        'fields': 'userEnteredFormat(textFormat,wrapStrategy)'}})
# строки с решением — заметный оранжевый фон в J
for r in decision_rows:
    reqs.append({'repeatCell': {
        'range': {'sheetId': gid, 'startRowIndex': r + 2, 'endRowIndex': r + 3,
                  'startColumnIndex': 9, 'endColumnIndex': 10},
        'cell': {'userEnteredFormat': {'backgroundColor':
                 {'red': 1.0, 'green': 0.85, 'blue': 0.6},
                 'textFormat': {'bold': True, 'fontSize': 10},
                 'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP'}},
        'fields': 'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
api('POST', f'https://sheets.googleapis.com/v4/spreadsheets/{SID}:batchUpdate',
    {'requests': reqs})

# ── verify: перечитать и сверить номера/строки ──
got = api('GET', f'https://sheets.googleapis.com/v4/spreadsheets/{SID}/values/'
          f'{urllib.parse.quote(TAB + f"!A1:K{len(rows) + 2}")}?valueRenderOption=FORMULA')
vals = got.get('values', [])
assert len(vals[0]) > 2 and vals[0][2].startswith(LEGEND.split(':')[0]), 'легенда не на месте'   # 'Секвенция' / 'Sequence'
assert vals[1][:len(HDR)] == HDR, 'шапка не совпала'
assert len(vals) - 2 == len(rows), f'строк {len(vals)-2} вместо {len(rows)}'
n_img = sum(1 for r in vals[2:] for c in r[6:9] if str(c).startswith('=IMAGE'))
n_lnk = sum(str(r[5]).count('🔗') for r in vals[2:] if len(r) > 5)
print(f'ALL PASS: {len(rows)} ТЗ, {n_img} кадров, {n_lnk} ссылок, {len(decision_rows)} решений')
print(f'https://docs.google.com/spreadsheets/d/{SID}/edit#gid={gid}')
if DUMP:
    Path(DUMP).parent.mkdir(parents=True, exist_ok=True)
    Path(DUMP).write_text(json.dumps({'schema': 'fake-sheets-dump-v1', 'tab': TAB, 'hdr': HDR, 'legend': LEGEND,
                                      'rows': rows, 'calls': _CALLS}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'--dump-rows: вызовов {len(_CALLS)}, строк {len(rows)} → {DUMP} (Google API не вызывался)')
