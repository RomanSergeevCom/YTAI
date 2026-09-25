#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Заметки Романа из вкладки дока → `work/{cut}/notes_roman.json`.

Зачем. Роман смотрит кат и пишет замечания прямо в док: своя вкладка, таблица
«таймкод · кадр · комментарий». Это самый ценный вход круга — но он живёт только в Google,
и каждая сессия перечитывает его руками, теряя куски. Здесь он один раз превращается в файл:
дальше его читают предложения экранов, страница сверки и ТЗ.

Ничего не толкует: раскладывает по таймкодам, подтягивает главу и дословную речь вокруг,
и всё. Что с заметкой делать — решает человек и пишет в `screens_proposal.json`.

⚠️ Пустой таймкод — не ошибка: Роман иногда пишет замечание к предыдущей строке или к фильму
целиком. Такие строки сохраняются с `sec: null` и порядковым номером, чтобы не потерялись.

    python3 stages/doc_notes_read.py --tab t.ojvzpi1u3w4v
    python3 stages/doc_notes_read.py --tab «Правки Романа» --out /tmp/notes.json
    python3 stages/doc_notes_read.py --selftest

exit: 0 — ок · 1 — вкладка не найдена · 2 — в таблице не нашлось ни одного таймкода
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCHEMA = 'doc-notes-v1'
TC_RE = re.compile(r'^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$')


def tosec(s):
    """'25:13' → 1513; '1:02:03' → 3723; не таймкод → None"""
    m = TC_RE.match(str(s or ''))
    if not m:
        return None
    a, b, c = m.group(1), m.group(2), m.group(3)
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def tc(sec):
    m, s = divmod(int(sec), 60)
    return f'{m}:{s:02d}'


def pick_cols(rows):
    """→ (колонка таймкода, колонка комментария).

    Раскладку не угадываем по номеру: у Романа кадр может стоять и слева, и посередине.
    Колонка таймкода — та, где больше всего ячеек читаются как таймкод; колонка комментария —
    самая «текстовая» из оставшихся."""
    if not rows:
        return 0, 1
    n = max(len(r) for r in rows)
    tc_score = [sum(1 for r in rows if i < len(r) and tosec(r[i]) is not None) for i in range(n)]
    col_tc = max(range(n), key=lambda i: tc_score[i])
    txt_score = [sum(len(str(r[i])) for r in rows if i < len(r)) if i != col_tc else -1 for i in range(n)]
    return col_tc, max(range(n), key=lambda i: txt_score[i])


def build(rows, chapter_of=None, say=None):
    """строки таблицы → записи заметок. chapter_of/say — необязательные справочники."""
    col_tc, col_txt = pick_cols(rows)
    out = []
    for i, r in enumerate(rows):
        get = lambda j: ' '.join(str(r[j]).split()) if j < len(r) else ''   # noqa: E731
        sec = tosec(get(col_tc))
        text = get(col_txt)
        other = ' '.join(get(j) for j in range(len(r)) if j not in (col_tc, col_txt)).strip()
        if not text and not other and sec is None:
            continue                                   # пустая строка таблицы — не заметка
        rec = {'n': len(out) + 1, 'row': i, 'sec': sec, 'tc': tc(sec) if sec is not None else '',
               'note': text, 'aside': other}
        if sec is not None and chapter_of:
            rec['ch'] = chapter_of(sec)
        if sec is not None and say:
            rec['said'] = (say(tc(sec), sec) or {}).get('text', '')
        out.append(rec)
    return out


def main():
    ap = argparse.ArgumentParser(description='заметки Романа из вкладки дока → JSON')
    ap.add_argument('--tab', required=True, help='tabId (t.xxxx) или заголовок вкладки')
    ap.add_argument('--out', default='', help='куда писать (по умолчанию work/{cut}/notes_roman.json)')
    ap.add_argument('--no-speech', action='store_true', help='не подтягивать речь вокруг заметки')
    a = ap.parse_args()

    sys.path.insert(0, str(HERE))
    from _bootstrap import P, W6                                    # noqa: PLC0415
    sys.path.insert(0, str(HERE.parent / 'shared'))
    from doctab_lib import get_doc, iter_tabs, flatten_tab          # noqa: PLC0415

    doc = get_doc(P.need('doc_id'))
    tab = None
    for t in iter_tabs(doc):
        pr = t.get('tabProperties') or {}
        if a.tab in (pr.get('tabId'), pr.get('title')):
            tab = t
            break
    if tab is None:
        have = ', '.join(f'{(t.get("tabProperties") or {}).get("title")!r}' for t in iter_tabs(doc))
        print(f'!! вкладки «{a.tab}» в доке нет. Есть: {have}')
        return 1

    rows = []
    for part in flatten_tab(tab):
        if part.get('kind') == 'table':
            rows += [list(r) for r in (part.get('rows') or [])]

    chap = [(int(t), str(no)) for t, no in P.CHAPTERS]
    dur = float(P.duration_sec())

    def chapter_of(sec):
        for i, (t0, no) in enumerate(chap):
            t1 = chap[i + 1][0] if i + 1 < len(chap) else dur
            if t0 <= sec < t1:
                return no
        return chap[-1][1] if chap else ''

    say = None
    if not a.no_speech:
        try:
            import said as SAID                                     # noqa: PLC0415
            say = lambda t, _s: SAID.said(t, t)                     # noqa: E731
        except Exception as ex:                                     # noqa: BLE001
            print(f'⚠️ речь рядом не подтянулась ({ex}) — заметки собраны без неё')

    notes = build(rows, chapter_of, say)
    withtc = sum(1 for x in notes if x['sec'] is not None)
    d = {'schema': SCHEMA, 'code': P.CODE, 'cut_version': P.CUT_VERSION,
         'tab': (tab.get('tabProperties') or {}).get('title'),
         'tab_id': (tab.get('tabProperties') or {}).get('tabId'),
         'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
         'counts': {'notes': len(notes), 'with_tc': withtc, 'no_tc': len(notes) - withtc},
         'notes': notes}
    out = Path(a.out).expanduser() if a.out else (W6 / 'notes_roman.json')
    P.write_json_atomic(out, d)
    print(f'заметок {len(notes)}: с таймкодом {withtc}, без — {len(notes) - withtc}')
    print(f'→ {out}')
    return 0 if withtc else 2


def selftest():
    rows = [['', 'кадр', 'сначала хук'],
            ['00:10', '', 'слово не произносить'],
            ['', '', ''],
            ['', '', 'ПОЧЕМУ МЕНЯ ОТДАЛИ?'],
            ['06:28', 'подпись', 'призыв фонда']]
    assert tosec('25:13') == 1513 and tosec('1:02:03') == 3723 and tosec('ага') is None
    assert tc(1513) == '25:13'
    assert pick_cols(rows) == (0, 2), pick_cols(rows)
    notes = build(rows, chapter_of=lambda s: '03' if s > 300 else '01')
    assert [x['n'] for x in notes] == [1, 2, 3, 4], notes
    assert notes[0]['sec'] is None and notes[0]['note'] == 'сначала хук'
    assert notes[0]['aside'] == 'кадр'                       # чужая колонка не теряется
    assert notes[1]['tc'] == '0:10' and notes[1]['ch'] == '01'
    assert notes[3]['ch'] == '03' and notes[3]['row'] == 4   # пустая строка пропущена, номер строки честный
    assert all('said' not in x for x in notes)               # без справочника речи ключа нет

    # раскладка колонок определяется по данным, а не по номеру
    flipped = [['кадр', '00:10', 'слово не произносить'], ['кадр', '06:28', 'призыв фонда']]
    assert pick_cols(flipped) == (1, 2), pick_cols(flipped)
    print('SELFTEST OK doc_notes_read')
    return 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
