#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вкладка «Главы · {ver}» — все главы и подглавы фильма В ОДНОМ МЕСТЕ + варианты дизайна заставки.

Зачем: Роман 22.09.2026 — «мне не нравится дизайн глав… Выдели все главы в одном месте в документе
и предложи (создай дизайн), главы + подглавы и на весь экран (может быть контраста не хватает)».
Раньше главы были размазаны: строки-заливки во вкладке ТЗ, HEADING в навигаторе, плашки на таймлайне
и картинка info_structure_map — но единого списка «вот все главы, вот как они выглядят» не было.

Структура (канон 5.6 — ОДНА таблица):
  шапка: что это + три варианта заставки крупными картинками, каждый одной строкой «за что»
         + раздел «ПОДГЛАВЫ» — панели перечислений (card.prog), по обзорному кадру на главу
  таблица: № | Кадр из ката | Глава и подглавы | ⏱ | Что сейчас | Как надо

Сюда же переехала проблема «заставки глав вразнобой» (ТЗ-48 снято 22.09.2026 по просьбе Романа:
«Надо проблему с главами отдельно вынести в Главы · v2») — текст берётся из карточки:
`ch_notes` (что с заставкой в кате), `ch_state` (что сейчас / как надо), `ch_extra` (похожие на
заставку места, главами не являющиеся). Выбранная буква заставки — `ch_plate_variant`.

Картинки — только из публичной папки кадров (shots_remote), как на вкладке ТЗ: кадры глав
`ch_card_NN.jpg` (их кладёт ensure_shots), демо вариантов `ch_demo_a|b|c.jpg` и обзорные
панели подглав `prog_NN_0.jpg`.

usage: doc_tab_chapters_v1.py [--tab TITLE] [--dry-run]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from _bootstrap import P, W6, M, T  # noqa: E402
from doctab_lib import get_doc, iter_tabs  # noqa: E402
from doctab_lib import batch_update as _batch_update  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--tab')
ap.add_argument('--dry-run', action='store_true')
a = ap.parse_args()

DOC_ID = P.need('doc_id')
TAB_TITLE = a.tab or f'Главы · {P.CUT_VERSION}'
HDR = ['№', 'Кадр из ката', 'Глава и подглавы', '⏱', 'Что сейчас', 'Как надо']
WIDTHS = [30, 262, 260, 70, 300, 300]
IMG_W = 250
FONT = 10
DEMOS = [('a', 'ПОЛОТНО', 'кадр уходит в затемнение, номер и имя по центру — максимум контраста, кадр почти не виден'),
         ('b', 'ШТОРКА', 'плотная левая треть, ведущая и кадр справа остаются чистыми'),
         ('c', 'НИЖНЯЯ ТРЕТЬ', 'кадр цел целиком, подложка только снизу — мягче всех, но и слабее по акценту')]


def u16(s):
    return len(s.encode('utf-16-le')) // 2


def shot_id(name, shots):
    """id картинки в публичной папке кадров. Панель перечисления лежит в mockups 4K-PNG с альфой —
    в доке от неё остался бы тёмный прямоугольник без кадра, поэтому сначала ищем композит s12
    («панель поверх настоящего кадра», dp_*.jpg), потом плоский jpg, и только потом сам PNG."""
    stem = name.rsplit('.', 1)[0]
    for cand in (f'dp_{stem}.jpg', f'{stem}.jpg', f'{stem}.png'):
        if shots.get(cand):
            return shots[cand], cand
    return None, name


def tmm(sec):
    return f'{int(sec) // 60}:{int(sec) % 60:02d}'


def batch_update(doc_id, reqs, tries=4):
    for k in range(tries):
        try:
            return _batch_update(doc_id, reqs)
        except Exception as e:                                   # noqa: BLE001
            if k == tries - 1:
                raise
            print('  batch повтор:', ' '.join(str(e).split())[:300], flush=True)
            time.sleep(8 * (k + 1))


# ── данные ────────────────────────────────────────────────────────────────
CHAP = [(int(t), n) for t, n in P.CHAPTERS]
CH_NAME = P.get('ch_name', {})
CH_IMG = P.get('ch_img', {})
SUB = [(int(s), int(c), str(t)) for s, c, t in P.get('sub', [])]
DUR = int(P.duration_sec())
shots = json.loads((M / 'shots_ids.json').read_text(encoding='utf-8')) if (M / 'shots_ids.json').exists() else {}
STATE = P.get('ch_state', {})     # {'04': ['что сейчас', 'как надо']} — из карточки
EXTRA = P.get('ch_extra', [])     # места, похожие на заставку, но не привязанные к главе
NOTES = P.get('ch_notes', {})     # {'04': '⚠️ НЕТ НОМЕРА · 11:17 …'} — из карточки
PROG = P.get('prog', {})          # {'08': {'title': …, 'items': [...]}} — перечисления внутри главы
PICKED = str(P.get('ch_plate_variant', '')).strip().lower()   # выбранная Романом буква заставки
NO_NUM = [no for no, t in sorted(NOTES.items()) if 'НЕТ НОМЕРА' in str(t)]

rows = []
for i, (sec, no) in enumerate(CHAP):
    end = CHAP[i + 1][0] if i + 1 < len(CHAP) else DUR
    subs = [f'▸ {tmm(s)} · {t}' for s, c, t in SUB if f'{c:02d}' == no]
    pg = PROG.get(no) or {}
    if not subs and pg:                       # подглавы этой главы — перечисление, а не титульные экраны
        subs = [f'▸ «{pg.get("title", "")}» — панель перечисления:'] + \
               [f'      {k} · {it}' for k, it in enumerate(pg.get('items') or [], 1)]
    body = f'{no}. {CH_NAME.get(no, "")}' + ('\n' + '\n'.join(subs) if subs else '\n▸ подглав в кате нет')
    st = STATE.get(no) or ['', '']
    rows.append({'no': no, 'img': CH_IMG.get(no, ''), 'body': body,
                 'tc': f'{tmm(sec)}–{tmm(end)}', 'now': st[0], 'do': st[1] if len(st) > 1 else ''})

_no_num = (f'У глав {", ".join(NO_NUM)} номера на заставке нет, у остальных есть — два разных приёма в одном фильме. '
           if NO_NUM else '')
head = [(1, f'{P.CODE} · {TAB_TITLE} — все главы фильма и дизайн заставок', {'bold': True}),
        (0, f'Кат {P.CUT_VERSION}, {tmm(DUR)}. Заставки глав в кате несогласованы. {_no_num}'
            f'Оба приёма — светлый текст по светлому кадру, контраста не хватает. '
            f'Здесь всё про главы в одном месте: что в кате сейчас, что надо, и как выглядит новая заставка.', {}),
        (0, '', {}),
        (2, ('ВАРИАНТЫ ЗАСТАВКИ — выбран ' + PICKED.upper()) if PICKED else 'ВАРИАНТЫ ЗАСТАВКИ — выбери букву',
         {'bold': True}),
        (0, 'Все три нарисованы поверх настоящего кадра этого фильма, глава 05. '
            + (f'Роман выбрал {PICKED.upper()} — все десять глав собраны в этом стиле и стоят на таймлайне.'
               if PICKED else 'Скажи букву — соберу все десять глав в этом стиле и поставлю на таймлайн.'), {})]


def find_tab(doc):
    for t in iter_tabs(doc):
        if t['tabProperties'].get('title') == TAB_TITLE:
            return t['tabProperties']['tabId']
    return None


def tab_body(tab_id):
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


def fresh_table(tab_id, nrows, empty=False, tries=6):
    """та же защита, что во вкладке-навигаторе: чтение большого дока отстаёт от записи,
    и таблица прошлой попытки приходит со старыми индексами (см. doc_tab_review_v1.fresh_table)"""
    for k in range(tries):
        tables = [el for el in tab_body(tab_id) if 'table' in el]
        ok = tables and len(tables[-1]['table']['tableRows']) == nrows
        if ok and empty:
            ok = not any(e.get('textRun', {}).get('content', '').strip()
                         for r in tables[-1]['table']['tableRows'] for c in r['tableCells']
                         for el in c['content'] if 'paragraph' in el
                         for e in el['paragraph'].get('elements', []))
        if ok:
            return tables[-1]
        print(f'  жду {"пустую " if empty else ""}таблицу {nrows} строк', flush=True)
        time.sleep(6 * (k + 1))
    raise SystemExit(f'таблица {nrows} строк не появилась в чтении вкладки')


def main():
    doc = get_doc(DOC_ID)
    tab_id = find_tab(doc)
    if not tab_id:
        batch_update(DOC_ID, [{'addDocumentTab': {'tabProperties': {'title': TAB_TITLE}}}])
        tab_id = find_tab(get_doc(DOC_ID))
        print('вкладка создана', tab_id, flush=True)
    else:
        print('вкладка найдена', tab_id, flush=True)
    if a.dry_run:
        for r in rows:
            print(f"  {r['no']} {r['tc']:>14}  {r['body'].splitlines()[0]}")
        return 0

    body = tab_body(tab_id)
    first = next(c for c in body if 'paragraph' in c)
    s, e = first['startIndex'], body[-1]['endIndex'] - 1
    if e > s:
        batch_update(DOC_ID, [{'deleteContentRange': {'range': {'tabId': tab_id, 'startIndex': s, 'endIndex': e}}}])
    print('вкладка очищена', flush=True)

    # шапка + три варианта (текст; картинки вставим следом, с конца)
    cur = tab_body(tab_id)[-1]['endIndex'] - 1
    reqs, demo_at = [], []
    for lvl, text, opts in head:
        t = text + '\n'
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': t}})
        if lvl:
            reqs.append({'updateParagraphStyle': {
                'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t)},
                'paragraphStyle': {'namedStyleType': f'HEADING_{lvl}'}, 'fields': 'namedStyleType'}})
        if opts.get('bold'):
            reqs.append({'updateTextStyle': {
                'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t) - 1},
                'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += u16(t)
    def block(title, why, img):
        """жирный заголовок + строка «за что» + пустой абзац под картинку; → сдвиг cur"""
        nonlocal cur
        line = title + '\n'
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': line}})
        reqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(line) - 1},
                                         'textStyle': {'bold': True}, 'fields': 'bold'}})
        cur += u16(line)
        w = why + '\n'
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': w}})
        cur += u16(w)
        demo_at.append((img, cur))                     # картинка встанет своим абзацем
        reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': '\n'}})
        cur += 1

    for v, name, why in DEMOS:
        mark = ' ✔ ВЫБРАН' if PICKED == v else ''
        block(f'{v.upper()} — {name}{mark}', why, f'ch_demo_{v}.jpg')

    # ── подглавы: панели перечислений внутри главы (Роман 22.09.2026) ──
    if PROG:
        for lvl, text, opts in [(2, 'ПОДГЛАВЫ — ПАНЕЛИ ПЕРЕЧИСЛЕНИЙ', {'bold': True}),
                                (0, 'Там, где ведущая перечисляет по пунктам, зритель теряет счёт. Панель слева '
                                    'держит весь список на экране и подсвечивает текущий пункт; справа — «ЧТО ДАЛЬШЕ» '
                                    'или «k из n». Ниже — обзорный кадр каждой панели (пункт ещё ни один не '
                                    'подсвечен); полный набор кадров и таймкоды — в ТЗ монтажёру.', {})]:
            t = text + '\n'
            reqs.append({'insertText': {'location': {'tabId': tab_id, 'index': cur}, 'text': t}})
            if lvl:
                reqs.append({'updateParagraphStyle': {
                    'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t)},
                    'paragraphStyle': {'namedStyleType': f'HEADING_{lvl}'}, 'fields': 'namedStyleType'}})
            if opts.get('bold'):
                reqs.append({'updateTextStyle': {
                    'range': {'tabId': tab_id, 'startIndex': cur, 'endIndex': cur + u16(t) - 1},
                    'textStyle': {'bold': True}, 'fields': 'bold'}})
            cur += u16(t)
        for no, pg in sorted(PROG.items()):
            items = list(pg.get('items') or [])
            block(f'ГЛАВА {no} · {CH_NAME.get(no, "")} — «{pg.get("title", "")}»',
                  f'{len(items)} пунктов: ' + ' · '.join(items), f'prog_{no}_0.jpg')

    batch_update(DOC_ID, reqs)
    print(f'шапка: {len(head)} абзацев + {len(DEMOS)} вариантов + подглав {len(PROG)}', flush=True)

    for name, at in sorted(demo_at, key=lambda x: -x[1]):           # с конца — индексы не едут
        did, used = shot_id(name, shots)
        if not did:
            print(f'  !! нет id картинки {name} — пропуск', flush=True)
            continue
        if used != name:
            print(f'     {name} → {used}', flush=True)
        batch_update(DOC_ID, [{'insertInlineImage': {
            'location': {'tabId': tab_id, 'index': at},
            'uri': f'https://drive.google.com/uc?export=download&id={did}',
            'objectSize': {'width': {'magnitude': 460, 'unit': 'PT'}}}}])
    print(f'картинки шапки вставлены: {len(demo_at)}', flush=True)

    cur = tab_body(tab_id)[-1]['endIndex'] - 1
    batch_update(DOC_ID, [{'insertTable': {'location': {'tabId': tab_id, 'index': cur},
                                           'rows': len(rows) + len(EXTRA) + 1, 'columns': len(HDR)}}])
    tbl = fresh_table(tab_id, len(rows) + len(EXTRA) + 1, empty=True)
    cells = [r['tableCells'] for r in tbl['table']['tableRows']]
    all_cells = ([HDR] + [[r['no'], '', r['body'], r['tc'], r['now'], r['do']] for r in rows]
                 + [['—', '', 'ПОХОЖЕ НА ЗАСТАВКУ, но это не глава', t, w, 'решить: переоформить или оставить']
                    for t, w in EXTRA])
    treqs = []
    for ri in range(len(all_cells) - 1, -1, -1):
        for cj in range(len(HDR) - 1, -1, -1):
            txt = str(all_cells[ri][cj])
            if txt:
                treqs.append({'insertText': {'location': {'tabId': tab_id,
                                                          'index': cells[ri][cj]['content'][0]['startIndex']},
                                             'text': txt}})
    for i in range(0, len(treqs), 200):
        batch_update(DOC_ID, treqs[i:i + 200])
    print(f'таблица: {len(rows)} глав', flush=True)

    trows = fresh_table(tab_id, len(rows) + len(EXTRA) + 1)['table']['tableRows']
    ireqs = []
    for ri in range(len(rows), 0, -1):
        name = rows[ri - 1]['img']
        did, _ = shot_id(name, shots)
        if not did:
            continue
        ireqs.append({'insertInlineImage': {
            'location': {'tabId': tab_id, 'index': trows[ri]['tableCells'][1]['content'][0]['startIndex']},
            'uri': f'https://drive.google.com/uc?export=download&id={did}',
            'objectSize': {'width': {'magnitude': IMG_W, 'unit': 'PT'}}}})
    for i in range(0, len(ireqs), 40):
        batch_update(DOC_ID, ireqs[i:i + 40])
    print(f'кадры глав: {len(ireqs)}', flush=True)

    tbl = fresh_table(tab_id, len(rows) + len(EXTRA) + 1)
    tstart = tbl['startIndex']            # начало таблицы — у элемента, а не «первая ячейка − 1»
    trows = tbl['table']['tableRows']
    sreqs = []
    for c in trows[0]['tableCells']:
        st = c['content'][0]['startIndex']
        en = c['content'][-1]['endIndex'] - 1
        if en > st:
            sreqs.append({'updateTextStyle': {'range': {'tabId': tab_id, 'startIndex': st, 'endIndex': en},
                                              'textStyle': {'bold': True}, 'fields': 'bold'}})
    for cj, w in enumerate(WIDTHS):
        sreqs.append({'updateTableColumnProperties': {
            'tableStartLocation': {'tabId': tab_id, 'index': tstart},
            'columnIndices': [cj],
            'tableColumnProperties': {'widthType': 'FIXED_WIDTH', 'width': {'magnitude': w, 'unit': 'PT'}},
            'fields': 'widthType,width'}})
    batch_update(DOC_ID, sreqs)
    print(f'✅ вкладка «{TAB_TITLE}» собрана: '
          f'https://docs.google.com/document/d/{DOC_ID}/edit?tab={tab_id}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
