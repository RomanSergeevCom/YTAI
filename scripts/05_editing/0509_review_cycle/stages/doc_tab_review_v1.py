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

from _bootstrap import P, W6, M, HERE, ROOT, T, LANG  # noqa: E402
from i18n import has as i18n_has  # noqa: E402
from doctab_lib import get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _batch_update  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--upload', action='store_true')
ap.add_argument('--no-images', action='store_true')
ap.add_argument('--dry-run', action='store_true')
ap.add_argument('--dump-requests', metavar='FILE',
                help='собрать вкладку на офлайн-двойнике Docs (shared/fake_docs.py): запросы → FILE, без Google API')
a = ap.parse_args()
_FD = None
if a.dump_requests:
    sys.path.insert(0, str(ROOT / 'shared'))
    from fake_docs import FakeDocs  # noqa: E402
    _FD = FakeDocs()
    get_doc, _batch_update = _FD.get_doc, _FD.batch_update

DOC_ID = P.need('doc_id')
TAB_TITLE = P.get('nav_tab') or T('c2.nav_tab_default').replace('{ver}', P.CUT_VERSION)
THUMBS = W6 / 'thumbs'
SHOTS_REMOTE = P.get('shots_remote', 'gdrive:YTUVI_plan_v3_shots').rstrip('/') + '/nav'
WIDTHS = [24, 58, 40, 230, 160, 164]          # сумма 676pt — как на вкладке ТЗ
FONT = 9
IMG_W = 150
HDR = list(T('c2.nav_hdr'))                   # № | ⏱ TC | Статус | Транскрибация | Экран | Находки (EN — свои)
CH_BG = {'red': 0.85, 'green': 0.93, 'blue': 0.85}
SUB_BG = {'red': 0.94, 'green': 0.97, 'blue': 0.94}
HDR_BG = {'red': 0.90, 'green': 0.90, 'blue': 0.92}
GAP = 12.0                                    # ближе этого границы кусков склеиваем
QO, QC = T('c2.qo'), T('c2.qc')               # «…» (ru) / “…” (en) вокруг экранного текста


def kind_name(k):
    """класс находки для ячейки: короткие имена навигатора (c2.nav_kind.*); прочие классы — как есть (ru)
    или общим core.kind_low.* (en)"""
    if i18n_has(f'c2.nav_kind.{k}'):
        return T(f'c2.nav_kind.{k}')
    if LANG == 'en' and i18n_has(f'core.kind_low.{k}'):
        return T(f'core.kind_low.{k}')
    return k


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
            # 110 знаков прятали саму причину: у Docs она в конце тела ответа, а не в начале
            print('  batch повтор:', ' '.join(str(e).split())[:400], flush=True)
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
        out.append(f'{e["tc"]} · {e["id"]}' + (f'\n{QO}{" / ".join(lines)}{QC}' if lines else T('c2.nav_no_text')))
    return '\n'.join(out)


def find_cell(es, t0, t1):
    out = []
    for e in es:
        for f in by_screen.get(e['id'], []):
            mark = '❌' if f.get('confirmed') else '⏳'
            fix = (f.get('fix_text_final') or f.get('fix_text') or '').replace('\n', ' / ')
            line = f'{mark} {kind_name(f.get("kind"))}: {f.get("problem", "")[:150]}'
            if fix:
                line += f'\n✅ {QO}{fix[:120]}{QC}'
            if not f.get('confirmed'):
                line += T('c2.nav_pending')
            out.append(line)
    tt = [T('c2.nav_term', name=t["key"], tc=t["tc"]) for t in terms.get('terms', [])
          if t0 <= float(t['t']) < t1][:4]
    ll = [T('c2.nav_loc', name=t["key"], tc=t["tc"]) for t in terms.get('locs', [])
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
                         'cells': ['', tc(t), '', f'[{int(n)}. {CH_NAME.get(n, T("core.chapter") + " " + n)} · {tc(t)}–{tc(CH_END[n])}]',
                                   '', T('c2.nav_ch_findings', n=nf) if nf else ''],
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
        f'{num:02d}', f'{tc(b)}–{tc(t1)}', '', txt or T('c2.nav_no_voice'), screen_cell(es), find_cell(es, b, t1)],
        'imgs': [e['id'] for e in es]})

head = [
    (1, T('c2.nav_head_title', code=P.CODE, tab=TAB_TITLE, dur=tc(DUR), ver=P.CUT_VERSION), {}),
    (0, T('c2.how_to_read'), {'bold': True}),
    (0, T('c2.nav_head_1'), {}),
    (0, T('c2.nav_head_2'), {}),
    (0, T('c2.nav_head_3'), {}),
    (0, T('c2.nav_head_4'), {}),
    (0, T('c2.nav_head_tz', tab=P.get("tab_title", T('c2.nav_head_tz_default'))), {}),
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


def table_text_len(tbl):
    return sum(len(e.get('textRun', {}).get('content', '').strip())
               for r in tbl['table']['tableRows'] for c in r['tableCells']
               for el in c['content'] if 'paragraph' in el
               for e in el['paragraph'].get('elements', []))


def fresh_table(nrows, empty=False, tries=6):
    """Последняя таблица вкладки — ДОЖДАВШИСЬ, что чтение догнало запись.

    get_doc по этому доку отвечает ~30 с и возвращает состояние «до записи». Сразу после
    insertTable в ответе приходит ТАБЛИЦА ПРОШЛОЙ ПОПЫТКИ — с тем же числом строк, но со
    старыми (бо́льшими) индексами: вкладку перед этим очистили, и сегмент стал короче.
    Индексы ячеек уезжают за конец сегмента, и заполнение падает «Precondition check failed»,
    а обычный ретрай шлёт те же мёртвые индексы (YTUVI01 v2, 22.09.2026 — шесть попыток подряд).
    По числу строк свежую таблицу от прошлой не отличить, а по содержимому — можно:
    только что вставленная пустая. `empty=True` — ждать именно такую.
    """
    for k in range(tries):
        tables = [el for el in tab_body() if 'table' in el]
        ok = tables and len(tables[-1]['table']['tableRows']) == nrows
        if ok and empty:
            ok = table_text_len(tables[-1]) == 0
        if ok:
            return tables[-1]
        seen = (f'{len(tables[-1]["table"]["tableRows"])} строк, '
                f'{table_text_len(tables[-1])} знаков' if tables else 'ни одной')
        print(f'  жду {"пустую " if empty else ""}таблицу {nrows} строк (вижу {seen})', flush=True)
        time.sleep(6 * (k + 1))
    raise SystemExit(f'таблица {nrows} строк так и не появилась в чтении вкладки')


def insert_table_at_end(nrows, ncols, tries=4):
    """Вставка таблицы в конец вкладки с ПЕРЕСЧЁТОМ индекса на каждой попытке.

    Док большой, get_doc отвечает ~30 с, и чтение приходит устаревшим: после очистки вкладки
    сегмент стал короче, а endIndex в ответе — ещё прежний. Индекс за концом сегмента Docs API
    отбивает как «Precondition check failed», и обычный ретрай не помогает — он шлёт тот же
    мёртвый индекс (YTUVI01 v2, 22.09.2026: четыре попытки подряд с одним и тем же 400).
    """
    for k in range(tries):
        cur = tab_body()[-1]['endIndex'] - 1
        try:
            _batch_update(DOC_ID, [{'insertTable': {'location': {'tabId': tab_id, 'index': cur},
                                                    'rows': nrows, 'columns': ncols}}])
            return
        except Exception as e:                                   # noqa: BLE001
            if k == tries - 1:
                raise
            print(f'  insertTable повтор (индекс {cur} не принят):', str(e)[:110], flush=True)
            time.sleep(8 * (k + 1))


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

insert_table_at_end(len(rows) + 1, len(HDR))
tbl = fresh_table(len(rows) + 1, empty=True)
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
tbl = fresh_table(len(rows) + 1)
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

tbl = fresh_table(len(rows) + 1)
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
    trows = fresh_table(len(rows) + 1)['table']['tableRows']
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
if _FD is not None:
    _FD.dump(a.dump_requests, {'tab_title': TAB_TITLE})
