#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка-навигатор «Ревью v1 по видео» — ОДНА таблица (канон Романа: вкладку не дробить).

Зачем: ТЗ-вкладка — для монтажёра (коротко, только правки). Навигатор — для Романа: весь кат
в его хронологии, ПОЛНАЯ транскрибация без пропусков, кадры экранов, находки аудита и термины
на своих таймкодах. Было только у YTUVI01 (montage/doc_tab_review_v1.py на зашитых rows_v4.json);
здесь всё собирается из карточки проекта и артефактов v6 — работает на любом фильме.

Структура: главы = строки с заливкой, label в [скобках] + HEADING_3 (попадает в оглавление);
подглавы — HEADING_4 с лёгкой заливкой; куски: № | ⏱ TC | Статус | Транскрибация | Экран (кадры) |
Находки / что показать. Статус пустой — его ставит Роман, правки снимает s13_doc_edits.py.

Источники: prep_config.json (главы, подглавы, перечисления, nav_tab) · words.json (транскрипт) ·
screens_v6.json + vlm_v6.jsonl (экраны) · audit_findings_v6.json (находки) · terms_v6.json (термины)
Кадры: thumbs/<sid>.jpg → Drive (shots_remote/nav) → montage/nav_ids.json → insertInlineImage.

usage: python3 doc_tab_review_v1.py [--upload] [--no-images] [--dry-run]
  --upload    перед сборкой залить кадры на Drive и обновить nav_ids.json
  --no-images собрать текст без картинок (быстро, для проверки структуры)
  --dry-run   ничего не писать в док: напечатать, что получилось бы
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

W6 = Path(__file__).parent
sys.path.insert(0, str(W6))
sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/ytuvi_doctabs'))
import proj_config as P  # noqa: E402
from doctab_lib import get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _batch_update  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--upload', action='store_true')
ap.add_argument('--no-images', action='store_true')
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()

M = W6.parent / 'montage'
DOC_ID = P.need('doc_id')
TAB_TITLE = P.get('nav_tab') or 'Ревью v1 по видео'
THUMBS = W6 / 'thumbs'
SHOTS_REMOTE = P.get('shots_remote', 'gdrive:YTUVI_plan_v3_shots').rstrip('/') + '/nav'
WIDTHS = [24, 58, 40, 230, 160, 164]          # сумма 676pt — как на вкладке ТЗ
FONT = 9
IMG_W = 150
HDR = ['№', '⏱ TC', 'Статус', 'Транскрибация', 'Экран (кадры из ката)', 'Находки / что показать']
CH_BG = {'red': 0.85, 'green': 0.93, 'blue': 0.85}
SUB_BG = {'red': 0.94, 'green': 0.97, 'blue': 0.94}
HDR_BG = {'red': 0.90, 'green': 0.90, 'blue': 0.92}
GAP = 12.0                                    # ближе этого границы кусков склеиваем
KIND_RU = {'typo': 'опечатка', 'grammar': 'грамматика', 'fact': 'факт', 'currency': 'валюта/число',
           'language': 'англ. без перевода', 'mismatch': 'экран ≠ озвучка', 'design': 'вёрстка',
           'other': 'правка'}


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def tc(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


def batch_update(doc_id, reqs, tries=4):
    """backoff на 429/5xx и сетевые сбои (doctab_lib не ретраит)"""
    for k in range(tries):
        try:
            return _batch_update(doc_id, reqs)
        except Exception as e:                                   # noqa: BLE001
            if k == tries - 1:
                raise
            print('  batch повтор:', str(e)[:110], flush=True)
            time.sleep(8 * (k + 1))


# ── данные ────────────────────────────────────────────────────────────────
DUR = float(P.get('total_sec', P.duration_sec()))
CHAP = [(int(t), n) for t, n in P.CHAPTERS]
CH_NAME = P.get('ch_name', {})
CH_END = {n: (CHAP[i + 1][0] if i + 1 < len(CHAP) else int(DUR)) for i, (t, n) in enumerate(CHAP)}
SUB = [(int(s), int(c), str(t)) for s, c, t in P.get('sub', [])]
PROG = P.get('prog', {})
PROG_T = {k: [int(x) for x in v] for k, v in P.get('prog_t', {}).items()}

segs = []
for s in json.load(open(P.WORDS, encoding='utf-8'))['segments']:
    st = s['start']
    st = float(st) if not isinstance(st, str) else int(st.split(':')[0]) * 60 + float(st.split(':')[1])
    segs.append((st, s['text'].strip()))
segs.sort()

screens = json.load(open(W6 / 'screens_v6.json', encoding='utf-8'))
vlm = {}
if (W6 / 'vlm_v6.jsonl').exists():
    for ln in open(W6 / 'vlm_v6.jsonl', encoding='utf-8'):
        try:
            r = json.loads(ln)
            vlm[r['id']] = r
        except Exception:
            pass

findings, unverified = [], []
af = W6 / 'audit_findings_v6.json'
if af.exists():
    d = json.load(open(af, encoding='utf-8'))
    findings = [f for f in d.get('findings', []) if f.get('confirmed')]
    unverified = [f for f in d.get('findings', []) if f.get('status') == 'unverified']
by_screen = {}
for f in findings + unverified:
    by_screen.setdefault(f.get('screen_id'), []).append(f)

terms = {'terms': [], 'locs': []}
if (W6 / 'terms_v6.json').exists():
    terms = json.load(open(W6 / 'terms_v6.json', encoding='utf-8'))

nav_ids = json.load(open(M / 'nav_ids.json', encoding='utf-8')) if (M / 'nav_ids.json').exists() else {}


def upload_thumbs():
    """кадры экранов → Drive (наследует доступ родительской папки) → nav_ids.json {файл: id}"""
    subprocess.run(['rclone', 'copy', str(THUMBS), SHOTS_REMOTE, '--include', '*.jpg',
                    '--transfers', '8', '--checkers', '8'], check=True)
    ls = subprocess.run(['rclone', 'lsjson', SHOTS_REMOTE, '--files-only'],
                        capture_output=True, text=True, check=True)
    ids = {e['Name']: e['ID'] for e in json.loads(ls.stdout)}
    json.dump(ids, open(M / 'nav_ids.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'кадров на Drive: {len(ids)} → montage/nav_ids.json')
    return ids


if a.upload:
    nav_ids = upload_thumbs()

# ── границы кусков: главы, подглавы, пункты перечислений, экраны ──────────
bounds = {0.0}
for t, n in CHAP:
    bounds.add(float(t))
for s, c, t in SUB:
    bounds.add(float(s))
for k, ts in PROG_T.items():
    bounds |= {float(x) for x in ts}
for e in screens:
    bounds.add(float(e['t0']))
bounds = sorted(b for b in bounds if b < DUR)
keep = [bounds[0]]
hard = {float(t) for t, _ in CHAP} | {float(s) for s, _, _ in SUB} | {
    float(x) for ts in PROG_T.values() for x in ts}
for b in bounds[1:]:
    if b in hard or b - keep[-1] >= GAP:     # границы структуры не склеиваем никогда
        keep.append(b)
bounds = keep


def seg_text(t0, t1):
    """полная транскрибация куска: все сегменты, начавшиеся в [t0, t1)"""
    return ' '.join(txt for st, txt in segs if t0 <= st < t1).strip()


def screens_in(t0, t1):
    return [e for e in screens if t0 <= e['t0'] < t1]


def screen_cell(es):
    out = []
    for e in es:
        v = vlm.get(e['id']) or {}
        text = (v.get('vlm_text') or e['text_best'] or '').strip()
        lines = [l.strip() for l in re.split(r'\n|\s\|\s', text) if l.strip()][:4]
        out.append(f'{e["tc"]} · {e["id"]}' + (f'\n«{" / ".join(lines)}»' if lines else ' (без текста)'))
    return '\n'.join(out)


def find_cell(es, t0, t1):
    out = []
    for e in es:
        for f in by_screen.get(e['id'], []):
            mark = '❌' if f.get('confirmed') else '⏳'
            fix = (f.get('fix_text_final') or f.get('fix_text') or '').replace('\n', ' / ')
            line = f'{mark} {KIND_RU.get(f.get("kind"), f.get("kind"))}: {f.get("problem", "")[:150]}'
            if fix:
                line += f'\n✅ «{fix[:120]}»'
            if not f.get('confirmed'):
                line += '\n(ждёт проверки линзами)'
            out.append(line)
    tt = [f'💡 термин {t["key"]}: плашка на {t["tc"]}' for t in terms.get('terms', [])
          if t0 <= float(t['t']) < t1][:4]
    ll = [f'🗺 локация {t["key"]}: мини-карта на {t["tc"]}' for t in terms.get('locs', [])
          if t0 <= float(t['t']) < t1][:3]
    return '\n'.join(out + tt + ll)


# ── строки ────────────────────────────────────────────────────────────────
rows = []
num = 0
for i, b in enumerate(bounds):
    t1 = bounds[i + 1] if i + 1 < len(bounds) else DUR
    # глава
    for t, n in CHAP:
        if float(t) == b:
            nf = sum(1 for f in findings if any(e['id'] == f.get('screen_id')
                                                for e in screens_in(float(t), CH_END[n])))
            rows.append({'kind': 'ch',
                         'cells': ['', tc(t), '', f'[{int(n)}. {CH_NAME.get(n, "ГЛАВА " + n)} · {tc(t)}–{tc(CH_END[n])}]',
                                   '', f'{nf} находок в главе' if nf else ''],
                         'imgs': []})
    # подглава
    for s, c, t in SUB:
        if float(s) == b:
            rows.append({'kind': 'sub', 'cells': ['', tc(s), '', f'▸ {t}', '', ''], 'imgs': []})
    # пункт перечисления
    for k, ts in PROG_T.items():
        for j, x in enumerate(ts):
            if float(x) == b:
                items = PROG[k]['items']
                rows.append({'kind': 'sub', 'cells': [
                    '', tc(x), '', f'▸ {PROG[k]["title"]} — {j + 1}/{len(items)}: {items[j]}', '', ''], 'imgs': []})
    es = screens_in(b, t1)
    txt = seg_text(b, t1)
    if not txt and not es:
        continue
    num += 1
    rows.append({'kind': 'row', 'cells': [
        f'{num:02d}', f'{tc(b)}–{tc(t1)}', '', txt or '(без озвучки)', screen_cell(es), find_cell(es, b, t1)],
        'imgs': [e['id'] for e in es]})

head = [
    (1, f'{P.CODE} · {TAB_TITLE} — кат v1 целиком, {tc(DUR)}', {}),
    (0, 'Как читать:', {'bold': True}),
    (0, '▸ кат в его хронологии: главы — строки с заливкой, подглавы и пункты перечислений — строками ▸', {}),
    (0, '▸ «Транскрибация» — полная расшифровка озвучки без пропусков; «Экран» — что в этот момент на экране', {}),
    (0, '▸ «Находки»: ❌ подтверждённая ошибка и ✅ как должно быть; 💡 термин и 🗺 локация — где нужна плашка или карта', {}),
    (0, '▸ «Статус» — твоя колонка: ✅ согласен / ⚠️ поправить / ❌ убрать. По ней собираем следующую версию ТЗ', {}),
    (0, f'Короткое ТЗ монтажёру (только правки) — вкладка «{P.get("tab_title", "ТЗ монтажёру")}».', {}),
]

print(f'строк: {len(rows)} (глав {sum(r["kind"] == "ch" for r in rows)}, '
      f'подглав {sum(r["kind"] == "sub" for r in rows)}, кусков {num}) · '
      f'находок в таблице {sum(len(by_screen.get(s, [])) for r in rows for s in r["imgs"])} · '
      f'кадров {sum(len(r["imgs"]) for r in rows)}')
if a.dry_run:
    for r in rows[:14]:
        print(' ', r['kind'], '|', ' | '.join(str(c)[:48].replace('\n', '⏎') for c in r['cells']))
    raise SystemExit('--dry-run: док не тронут')

# ── запись во вкладку ─────────────────────────────────────────────────────
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
    for k in range(4):
        try:
            d = get_doc(DOC_ID)
            break
        except Exception as e:                                   # noqa: BLE001
            if k == 3:
                raise
            print('  get_doc повтор:', str(e)[:100], flush=True)
            time.sleep(10 * (k + 1))
    for t in iter_tabs(d):
        if t['tabProperties']['tabId'] == tab_id:
            return t['documentTab']['body']['content']
    raise SystemExit('вкладка потерялась')


body = tab_body()
first = next(c for c in body if 'paragraph' in c)
start, end = first['startIndex'], body[-1]['endIndex'] - 1
if end > start:
    batch_update(DOC_ID, [{'deleteContentRange': {
        'range': {'tabId': tab_id, 'startIndex': start, 'endIndex': end}}}])
print('вкладка очищена', flush=True)

HEAD = {1: 'HEADING_1', 2: 'HEADING_2'}
cur = tab_body()[-1]['endIndex'] - 1
reqs = []
for h, text, opts in head:
    tnl = text + '\n'
    n = u16(tnl)
    reqs += [{'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': tnl}},
             {'updateParagraphStyle': {'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n},
                                       'paragraphStyle': {'namedStyleType': HEAD.get(h, 'NORMAL_TEXT')},
                                       'fields': 'namedStyleType'}}]
    if opts.get('bold'):
        reqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + n - 1},
                                         'textStyle': {'bold': True}, 'fields': 'bold'}})
    cur += n
batch_update(DOC_ID, reqs)
print(f'шапка: {len(head)} абзацев', flush=True)

cur = tab_body()[-1]['endIndex'] - 1
batch_update(DOC_ID, [{'insertTable': {'location': {'tabId': tab_id, 'index': cur},
                                       'rows': len(rows) + 1, 'columns': len(HDR)}}])
tbl = [el for el in tab_body() if 'table' in el][-1]
cells = [r['tableCells'] for r in tbl['table']['tableRows']]
all_cells = [HDR] + [r['cells'] for r in rows]
reqs = []
for ri in range(len(all_cells) - 1, -1, -1):
    for cj in range(len(HDR) - 1, -1, -1):
        txt = str(all_cells[ri][cj])
        if txt:
            reqs.append({'insertText': {'location': {'tabId': tab_id,
                                                     'index': cells[ri][cj]['content'][0]['startIndex']},
                                        'text': txt}})
for i in range(0, len(reqs), 400):
    batch_update(DOC_ID, reqs[i:i + 400])
    print(f'  текст {min(i + 400, len(reqs))}/{len(reqs)}', flush=True)

# ── оформление: ширины, кегль, заливка глав и подглав, HEADING в ячейке ──
tbl = [el for el in tab_body() if 'table' in el][-1]
tstart = tbl['startIndex']
style = [{'updateTableColumnProperties': {
    'tableStartLocation': {'tabId': tab_id, 'index': tstart},
    'columnIndices': [i], 'tableColumnProperties': {'widthType': 'FIXED_WIDTH',
                                                    'width': {'magnitude': w, 'unit': 'PT'}},
    'fields': 'widthType,width'}} for i, w in enumerate(WIDTHS)]
style.append({'updateTextStyle': {
    'range': {'tabId': tab_id, 'startIndex': tbl['startIndex'], 'endIndex': tbl['endIndex'] - 1},
    'textStyle': {'fontSize': {'magnitude': FONT, 'unit': 'PT'}}, 'fields': 'fontSize'}})
batch_update(DOC_ID, style)

tbl = [el for el in tab_body() if 'table' in el][-1]
trows = tbl['table']['tableRows']
fills, heads = [], []
for ri, r in enumerate([{'kind': 'hdr'}] + rows):
    bg = HDR_BG if r['kind'] == 'hdr' else (CH_BG if r['kind'] == 'ch' else (SUB_BG if r['kind'] == 'sub' else None))
    if bg:
        fills.append({'updateTableCellStyle': {
            'tableRange': {'tableCellLocation': {'tableStartLocation': {'tabId': tab_id, 'index': tbl['startIndex']},
                                                 'rowIndex': ri, 'columnIndex': 0},
                           'rowSpan': 1, 'columnSpan': len(HDR)},
            'tableCellStyle': {'backgroundColor': {'color': {'rgbColor': bg}}},
            'fields': 'backgroundColor'}})
    if r['kind'] in ('hdr', 'ch', 'sub'):
        cj = 3 if r['kind'] != 'hdr' else 0
        cell = trows[ri]['tableCells'][cj]
        p = cell['content'][0]
        heads.append({'updateParagraphStyle': {
            'range': {'tabId': tab_id, 'startIndex': p['startIndex'], 'endIndex': p['endIndex'] - 1},
            'paragraphStyle': {'namedStyleType': 'HEADING_3' if r['kind'] == 'ch' else
                               ('HEADING_4' if r['kind'] == 'sub' else 'NORMAL_TEXT')},
            'fields': 'namedStyleType'}})
        if r['kind'] == 'hdr':
            heads.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': trows[ri]['tableCells'][0]['content'][0]['startIndex'],
                          'endIndex': trows[ri]['tableCells'][-1]['content'][0]['endIndex'] - 1},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
batch_update(DOC_ID, fills + heads)
print(f'оформление: заливок {len(fills)}, заголовков {len(heads)}', flush=True)

# ── кадры экранов: в колонку «Экран», по одному на экран, с конца ─────────
if not a.no_images and nav_ids:
    trows = [el for el in tab_body() if 'table' in el][-1]['table']['tableRows']
    img_reqs = []
    for ri in range(len(rows), 0, -1):
        r = rows[ri - 1]
        if not r['imgs']:
            continue
        cell = trows[ri]['tableCells'][4]
        for sid in reversed(r['imgs']):
            did = nav_ids.get(f'{sid}.jpg')
            if not did:
                continue
            img_reqs.append({'insertInlineImage': {
                'location': {'tabId': tab_id, 'index': cell['endIndex'] - 1},
                'uri': f'https://drive.google.com/uc?export=view&id={did}',
                'objectSize': {'width': {'magnitude': IMG_W, 'unit': 'PT'}}}})
    img_reqs.sort(key=lambda q: -q['insertInlineImage']['location']['index'])
    ok, fails = 0, 0
    for i in range(0, len(img_reqs), 20):
        chunk = img_reqs[i:i + 20]
        try:
            batch_update(DOC_ID, chunk)
            ok += len(chunk)
        except Exception as e:                                   # noqa: BLE001
            print('  img пачкой не вышло → по одной:', str(e)[:110], flush=True)
            for q in chunk:
                try:
                    batch_update(DOC_ID, [q])
                    ok += 1
                except Exception as e2:                          # noqa: BLE001
                    fails += 1
                    print('  img err:', str(e2)[:110])
        print(f'  картинки {ok}/{len(img_reqs)}', flush=True)
    print(f'картинок: {ok}, сбоев: {fails}', flush=True)
elif not a.no_images:
    print('⚠️ nav_ids.json пуст — кадры не вставлены. Запусти с --upload', flush=True)

print(f'✅ вкладка «{TAB_TITLE}» собрана: '
      f'https://docs.google.com/document/d/{DOC_ID}/edit?tab={tab_id}', flush=True)
