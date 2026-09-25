#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Структура фильма человеческим текстом → `work/{cut}/structure.json`.

Зачем. Роман 22.09.2026: «ты структуру написал, но не описал её текстом в начале документа».
Структура у фильма есть, но разложена по ячейкам таблиц: главы — в строке ТЗ-02, подглавы —
в строке ТЗ-01 прошлого круга, экраны — в макетах. Прочитать её подряд нельзя. Этот файл
собирает её в связный текст и отдаёт двум поверхностям:

  short — шапка вкладки «Обратная связь · {ver}»: главы и подглавы, до 40 строк;
  full  — первый блок вкладки «Главы · {ver}»: то же плюс якорные реплики, крупные фразы
          и выбранный дизайн заставки.

Правила текста (проверяются гейтом здесь же, а не глазами в доке):
  • одна строка — одна мысль, таймкод в начале строки;
  • в строке не больше ОДНОГО таймкода — иначе читатель не понимает, к чему он относится;
  • без жаргона стадии (`feedback_view.JARGON`: align, OCR, VLM, bucket…);
  • у каждой главы и подглавы есть таймкод этого ката, а не прошлого.

usage: structure_text.py [--dry-run] [--max-short 40]
exit: 0 — ок · 1 — нет входов · 2 — текст не прошёл собственный гейт
"""
import argparse
import datetime
import json
import re
import sys

from _bootstrap import P, W6  # noqa: E402

import feedback_view as V  # noqa: E402
from chapters_from_plan import tcf  # noqa: E402

TC_RX = re.compile(r'\b\d{1,3}:\d{2}\b')


def tc(sec):
    """0:00 / 12:06 — как во всех поверхностях стадии (без сотых)"""
    m, s = divmod(int(sec), 60)
    return f'{m}:{s:02d}'


def anchors():
    """→ {'NN': 'якорная реплика'} из списка глав в правках этого круга"""
    out = {}
    for p in sorted(P.MONT.glob('pravki*.json')):
        for it in (json.loads(p.read_text(encoding='utf-8')).get('all') or []):
            if not str(it.get('key', '')).endswith('structure'):
                continue
            for blk in (it.get('parts') or {}).get('list') or []:
                for s in blk.get('items') or []:
                    m = re.match(r'\s*(\d+):(\d\d)\s*[–—-]', str(s))
                    a = re.search(r'Якор[ья]\s*:\s*[«"](.+?)[»"]', str(s))
                    if m and a:
                        out[int(m.group(1)) * 60 + int(m.group(2))] = a.group(1).strip()
    return out


def build(max_short=40):
    chap = [(int(s), str(n)) for s, n in (P.get('chapters') or [])]
    if not chap:
        return None, ['в карточке нет chapters']
    names = P.get('ch_name', {}) or {}
    sub = [(int(s), int(c), str(t)) for s, c, t in (P.get('sub', []) or [])]
    no_screen = {int(x) for x in (P.get('sub_no_screen', []) or [])}
    claims = [(int(c[0]), ' '.join(str(x) for x in c[1:] if x)) for c in (P.get('claims', []) or [])]
    anc = anchors()
    sub_by_ch = {}
    for j, (sec, ch, label) in enumerate(sub, 1):
        sub_by_ch.setdefault(ch, []).append((j, sec, label))

    head = (f'СТРУКТУРА ФИЛЬМА {P.CUT_VERSION.upper()} — {len(chap)} глав, {len(sub)} подглав'
            + (f', {len(claims)} крупные фразы' if claims else ''))
    short, full = [head], [head]
    # ⚠️ «Карточки глав стоят все» нельзя писать литералом: на фильме, где главу предложили
    # добавить, текст врал бы ровно в том месте, ради которого его и читают (YTCH12, 25.09.2026)
    new_ch = {str(x) for x in (P.get('new_ch') or [])}
    short.append(('Карточки глав в кате стоят все. ' if not new_ch else
                  f'Карточек глав в кате {len(chap) - len(new_ch)} из {len(chap)} — создать надо '
                  f'{len(new_ch)}. ')
                 + f'Плашек подглав не хватает — {len(no_screen)} из {len(sub)}.')
    full.append(short[1])
    full.append('Ниже — что стоит в кате сейчас и что предлагаем добавить. '
                'Якорная реплика — фраза, ради которой глава существует.')

    for i, (sec, no) in enumerate(chap):
        nm = str(names.get(no, f'ГЛАВА {no}')).strip()
        dot = '' if nm[-1:] in '.?!…' else '.'        # «ПОЧЕМУ ИНТЕРНАТ?» — второй точки не надо
        line = (f'{tc(sec)} — глава {no}. {nm}{dot} '
                + ('Карточки нет — создать.' if no in new_ch else 'Карточка стоит.'))
        short.append(line)
        full.append(line)
        if anc.get(sec):
            full.append(f'          Якорь: «{anc[sec]}»')
        for j, ssec, label in sub_by_ch.get(int(no), []):
            mark = 'плашки нет' if j in no_screen else 'плашка стоит'
            short.append(f'{tc(ssec)} — подглава: {label}. {mark.capitalize()}.')
            full.append(f'{tc(ssec)} — подглава: {label}. {mark.capitalize()}.')
        for csec, ctext in claims:
            if sec <= csec < (chap[i + 1][0] if i + 1 < len(chap) else 10 ** 9):
                full.append(f'{tc(csec)} — крупная фраза: «{ctext}»')

    if claims:
        short.append(f'Крупных фраз предлагаем {len(claims)} — они во вкладке «Главы {P.CUT_VERSION}».')
    var = str(P.get('ch_plate_variant', '') or '').lower()
    if var:
        vname = {'a': 'полотно', 'b': 'шторка', 'c': 'нижняя треть'}.get(var, var)
        full.append(f'Дизайн заставки главы: вариант «{vname}» — он совпадает с тем, '
                    'как заставки набраны в самом кате: по центру, белым, с красным акцентом.')

    if len(short) > max_short:
        # шапка сверки не резиновая: лишнее уходит во вкладку «Главы», но читатель узнаёт, сколько именно
        short = short[:max_short - 1] + [f'…и ещё {len(short) - max_short + 1} строк во вкладке «Главы {P.CUT_VERSION}»']
    return {'schema': 'structure-text-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION,
            'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'head': head, 'short': short, 'full': full,
            'counts': {'chapters': len(chap), 'sub': len(sub), 'claims': len(claims),
                       'sub_missing': len(no_screen)}}, []


def gate(d):
    """→ список нарушений собственных правил текста; пусто — текст годен"""
    bad = []
    for key in ('short', 'full'):
        for ln in d[key]:
            if len(TC_RX.findall(ln)) > 1:
                bad.append(f'{key}: два таймкода в строке — {ln[:70]}')
            for rx in V.JARGON:
                if rx.search(ln):
                    bad.append(f'{key}: жаргон стадии — {ln[:70]}')
                    break
    n = d['counts']
    seen = sum(1 for ln in d['full'] if TC_RX.match(ln.strip()))
    if seen < n['chapters'] + n['sub']:
        bad.append(f'не у всех глав и подглав есть таймкод: строк с таймкодом {seen}, '
                   f'нужно хотя бы {n["chapters"] + n["sub"]}')
    if len(d['full']) > 120:
        bad.append(f'полный текст длиннее 120 строк ({len(d["full"])})')
    return bad


def main():
    ap = argparse.ArgumentParser(description='структура фильма текстом')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max-short', type=int, default=40)
    a = ap.parse_args()

    d, err = build(a.max_short)
    if d is None:
        print(f'!! {err[0]}')
        return 1
    bad = gate(d)
    print(f'структура {P.CUT_VERSION}: {d["counts"]["chapters"]} глав · {d["counts"]["sub"]} подглав '
          f'· {d["counts"]["claims"]} фраз · коротко {len(d["short"])} строк · полно {len(d["full"])} строк')
    for ln in d['short']:
        print(f'  {ln}')
    if bad:
        print('  ГЕЙТ НЕ ПРОЙДЕН:')
        for b in bad:
            print(f'   ✗ {b}')
    else:
        print('  гейт: ALL OK (один таймкод в строке, без жаргона, у всех глав и подглав время)')
    if not a.dry_run and not bad:
        P.write_json_atomic(W6 / 'structure.json', d)
        print(f'записано: {W6 / "structure.json"}')
    return 2 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
