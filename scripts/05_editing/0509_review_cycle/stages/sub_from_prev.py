#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Подглавы прошлого круга → `card.sub` на оси нового ката.

Зачем. Список подглав живёт в ТЗ прошлого круга текстом («📋 СПИСОК · Подглавы (плашки)»),
на оси СТАРОГО ката. В карточке нового ката `sub` пуст, поэтому молчат все, кто от него зависит:
блоки C и M рендера (плашки и титры подтем), `sub_cards.py`, списки ТЗ-30 в `s10_format_tz`,
вкладка «Главы», раскладка панелей в `make_review_v6`. Эта стадия переносит список на новую ось.

Как. Три шага на каждую подглаву:
  1. проекция  — `Projector` из align.json (тот же движок, что у обратной связи): старая секунда → новая;
  2. досадка по речи — подпись подглавы почти всегда взята из слов героини, поэтому вокруг проекции
     (± radius) ищем окно, где звучит больше всего значимых слов подписи. Это чинит случай, когда
     проекция попала в один огромный спан и ошибка спана больше окна снапа;
  3. снап на паузу — `chapters_from_plan.snap_after_pause` (одна реализация на стадию), затем
     `frame_floor` по fps фильма. Плашка встаёт на первом слове после паузы, а не посреди слова.

Главу подглавы определяем по НОВОЙ оси (в какую главу `card.chapters` попала секунда), а не по
номеру «(гл.N)» из старого текста: между кругами нумерация глав меняется (в v5 YTCH12 добавился
ТИЗЕР, и все номера уехали на единицу). Номер из текста служит проверкой — расхождение печатаем.

`sub_no_screen` (подглавы, титра которых в кате нет) берём из обратной связи: `feedback.json`
→ пункт прошлого ТЗ с `key='structure'`, его `checks` знают по каждой подписи, нашлась ли она.

usage: sub_from_prev.py [--dry-run] [--radius 45] [--pause 0.3] [--window 3.0]
exit: 0 — ок · 1 — нет входов (prev_pravki / align / список) · 2 — есть подглавы вне своей главы
"""
import argparse
import datetime
import json
import math
import os
import re
import sys
from pathlib import Path

from _bootstrap import P, W6  # noqa: E402

import tz_diff as TD  # noqa: E402
from align import norm as wnorm  # noqa: E402  (та же нормализация слов, что в align.json)
from chapters_from_plan import frame_floor, load_words, snap_after_pause, tcf  # noqa: E402
from feedback_model import Projector  # noqa: E402

# строка списка: «        7:05.4  ▸ Последняя Пасха (гл.3)»
LINE_RX = re.compile(r'^\s*(\d+):(\d{1,2}(?:[.,]\d+)?)\s+▸\s+(.+?)\s*\(гл\.\s*(\d+)\)\s*$')
HEAD_RX = re.compile(r'СПИСОК.*Подглав', re.I)


def parse_list(nado):
    """текст `nado` пункта структуры → [(sec_old, подпись, № главы в старой нумерации)]"""
    out, seen = [], False
    for raw in str(nado or '').splitlines():
        if HEAD_RX.search(raw):
            seen = True
            continue
        m = LINE_RX.match(raw)
        if m:
            sec = int(m.group(1)) * 60 + float(m.group(2).replace(',', '.'))
            out.append((round(sec, 2), m.group(3).strip(), int(m.group(4))))
        elif seen and out and not raw.strip():
            break                                        # список кончился пустой строкой
    return out


def chapter_of(sec, chap, dur):
    """секунда → («NN», начало, конец) главы из card.chapters"""
    for i, (t0, no) in enumerate(chap):
        t1 = chap[i + 1][0] if i + 1 < len(chap) else dur
        if t0 <= sec < t1:
            return str(no), float(t0), float(t1)
    return (str(chap[-1][1]), float(chap[-1][0]), dur) if chap else ('', 0.0, dur)


def _same(a, b):
    """слова одного корня: русские окончания меняются, начало — нет"""
    return a == b or (len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5])


def weigh(cw):
    """вес слова = насколько оно редкое в этом фильме. «алименты» звучат раз, «все» — сотни раз:
    без веса частотные слова подписи находятся где угодно и тянут плашку не туда."""
    cnt = {}
    for w in cw:
        k = w['n'][:5]
        cnt[k] = cnt.get(k, 0) + 1
    return lambda k: 1.0 / math.log(2.0 + cnt.get(k[:5], 0))


def find_by_speech(cw, target, caption, radius, wt, win=14.0, need=0.5):
    """→ (секунда, доля веса найденных слов) окна речи, где звучит подпись; None — не нашлась.

    Подпись подглавы монтажёр берёт из слов героини, поэтому её значимые слова звучат рядом.
    Ищем окно длиной win, где их суммарный вес максимален; при равенстве — ближе к проекции."""
    keys = [k for k in (wnorm(w) for w in TD.words_of(caption)) if k]
    if not keys:
        return None
    full = sum(wt(k) for k in keys)
    lo, hi = target - radius, target + radius
    idx = [i for i, w in enumerate(cw) if lo <= w['s'] <= hi]
    best = None
    for a in idx:
        t0 = cw[a]['s']
        hit, first, b = set(), None, a
        while b < len(cw) and cw[b]['s'] - t0 <= win:
            for k in keys:
                if k not in hit and _same(cw[b]['n'], k):
                    hit.add(k)
                    first = cw[b]['s'] if first is None else min(first, cw[b]['s'])
                    break
            b += 1
        score = sum(wt(k) for k in hit) / full
        # возвращаем ПЕРВОЕ совпавшее слово, а не начало окна: слова подписи могут звучать
        # в конце окна, и плашка тогда встаёт за десяток секунд до своей темы
        cand = (round(score, 3), -abs(t0 - target), first)
        if score and (best is None or cand > best):
            best = cand
    if best and best[0] >= need:
        return best[2], round(best[0], 2)
    return None


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M')


def phrase_start(cw, t, lo_sec, pause=0.3, back=9.0):
    """→ индекс начала фразы: последнее слово после паузы на отрезке [t − back, t]; нет такого — None.

    Слова подписи звучат В СЕРЕДИНЕ фразы («…это была последняя моя Пасха»), а плашка должна встать
    на её начале. Поэтому для найденного по речи места идём НАЗАД до ближайшей паузы, а не к
    ближайшей вообще (`snap_after_pause` ищет в обе стороны и часто уводит вперёд, за тему)."""
    cands = [i for i, w in enumerate(cw) if max(lo_sec, t - back) <= w['s'] <= t + 0.05]
    good = [i for i in cands if i == 0 or cw[i]['s'] - cw[i - 1]['e'] >= pause]
    return good[-1] if good else None


def no_screen_set(captions):
    """→ множество порядковых номеров (1-based) подглав, титра которых в кате нет (по feedback.json)"""
    fb = W6 / 'feedback.json'
    if not fb.exists():
        return set(), 'feedback.json нет — все подглавы помечены как «титра нет»'
    d = json.loads(fb.read_text(encoding='utf-8'))
    checks = next((it.get('checks') or [] for it in (d.get('part2') or []) if it.get('key') == 'structure'), [])
    found = {TD.norm(c.get('q', '')) for c in checks if c.get('found')}
    if not found:
        return set(range(1, len(captions) + 1)), 'в feedback.json ни одна подглава не найдена на экране'
    return {i for i, cap in enumerate(captions, 1) if TD.norm(cap.strip('«»')) not in found}, ''


def main():
    ap = argparse.ArgumentParser(description='подглавы прошлого круга → card.sub на оси нового ката')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--radius', type=float, default=45.0, help='± секунд вокруг проекции для поиска по речи')
    ap.add_argument('--pause', type=float, default=0.3)
    ap.add_argument('--window', type=float, default=3.0)
    a = ap.parse_args()

    prev = P.get('prev_pravki', '')
    if not prev:
        print('!! в карточке нет prev_pravki — переносить нечего')
        return 1
    pp = Path(P.resolve(prev))
    if not pp.exists():
        print(f'!! нет {pp}')
        return 1
    items = json.loads(pp.read_text(encoding='utf-8')).get('all') or []
    st = next((it for it in items if it.get('key') == 'structure'), None)
    if not st:
        print(f'!! в {pp.name} нет пункта key="structure"')
        return 1
    rows = parse_list(st.get('nado', ''))
    if not rows:
        print(f'!! в пункте структуры {pp.name} не найден список подглав')
        return 1

    al = W6 / 'align.json'
    if not al.exists():
        print(f'!! нет {al} — сначала стадия align')
        return 1
    bases = json.loads(al.read_text(encoding='utf-8')).get('bases') or {}
    tag = next(iter(bases)) if len(bases) == 1 else next((k for k in bases if P.get('prev_cut_version', '') in k), '')
    if not tag:
        print(f'!! в align.json не выбрать базу прошлого ката из {list(bases)}')
        return 1
    proj = Projector(bases[tag])

    cw = load_words(P.WORDS)
    wt = weigh(cw)
    dur = float(P.get('duration_sec', 0)) or (cw[-1]['e'] if cw else 0.0)
    chap = [(float(s), str(n)) for s, n in (P.get('chapters') or [])]
    if not chap:
        print('!! в карточке нет chapters — главу подглавы определять не по чему')
        return 1

    out, report, bad = [], [], 0
    for sec_old, cap, ch_old in rows:
        pr = proj.project(sec_old)
        base = pr.get('sec_new')
        if base is None:
            report.append((sec_old, cap, None, 'none', '—', '', 'проекция не легла'))
            bad += 1
            continue
        err = float(pr.get('err') or 0.0)
        hit = find_by_speech(cw, base, cap, a.radius, wt)
        how, score = ('речь', hit[1]) if hit else ('проекция', '')
        t = hit[0] if hit else base
        win = max(a.window, err + a.window) if not hit else a.window
        no, t0, t1 = chapter_of(t, chap, dur)
        i = (phrase_start(cw, t, t0, a.pause) if hit else None)
        if i is None:                                     # нашли по проекции (или фраза без паузы) — обычный снап
            i = snap_after_pause(cw, t, None, min(t1 - 0.5, t + win), a.pause, win)
        sec = frame_floor(cw[i]['s'])[1] if i is not None else frame_floor(t)[1]
        no, t0, t1 = chapter_of(sec, chap, dur)
        note = ''
        if not t0 <= sec < t1:
            note, bad = 'вне главы', bad + 1
        elif int(no) != ch_old + 1:
            note = f'нумерация: было гл.{ch_old}, стало гл.{no}'
        out.append([int(sec), int(no), cap])
        report.append({'caption': cap, 'sec_old': sec_old, 'sec': sec, 'ch': no, 'how': how,
                       'score': score or None, 'err': round(err, 1),
                       'note': note or (f'ошибка проекции {err:.1f} с' if err > 3 else ''),
                       # «уверенно» = место найдено по словам подписи; «по проекции» просит сверки глазами
                       'sure': how == 'речь' and (score or 0) >= 0.7})

    out.sort(key=lambda x: x[0])
    for i in range(1, len(out)):                          # строго по возрастанию: две плашки в одну секунду не ставим
        if out[i][0] <= out[i - 1][0]:
            out[i][0] = out[i - 1][0] + 1
    caps = [r[2] for r in out]
    ns, warn = no_screen_set(caps)
    order = {r['caption']: i for i, r in enumerate(report)}
    for i, (_sec, _no, cap) in enumerate(out, 1):
        report[order[cap]]['n'] = i

    w = max((len(r['caption']) for r in report), default=10)
    print(f'подглав в списке {len(rows)} · перенесено {len(out)} · база {tag}')
    for r in report:
        tc_new = tcf(r['sec']) if r['sec'] is not None else '—'
        print(f'  {tcf(r["sec_old"]):>9} → {tc_new:>9}  гл.{r["ch"]:<3} {r["caption"]:<{w}}  {r["how"]}'
              + (f' {r["score"]}' if r['score'] else '') + (f'  ⚠ {r["note"]}' if r['note'] else ''))
    if warn:
        print(f'  ⚠ {warn}')
    print(f'титра в кате нет у {len(ns)} из {len(out)}: {sorted(ns)}')
    print(f'уверенно по речи {sum(1 for r in report if r["sure"])} из {len(report)} '
          f'— остальные просят сверки глазами')

    if not a.dry_run:
        p = Path(os.environ.get('YTAI_CARD') or (Path(P.REVIEW_DIR) / 'review_card.json'))
        card = json.loads(p.read_text(encoding='utf-8'))
        card['sub'] = out
        card['sub_no_screen'] = sorted(ns)
        P.write_json_atomic(p, card)
        P.write_json_atomic(W6 / 'sub_from_prev.json',
                            {'schema': 'sub-transfer-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION,
                             'base': tag, 'built': _now(), 'rows': report})
        print(f'записано в {p.name}: sub {len(out)} · sub_no_screen {len(ns)} · отчёт sub_from_prev.json')
    return 2 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
