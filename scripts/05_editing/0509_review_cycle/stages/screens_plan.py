#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Раскладка экранов фильма на оси ката → `work/{cut}/screens_plan.json` (`screens-plan-v1`).

Зачем. Роман 22.09.2026: «сделай дизайн глав и фраз и расположил их (экранов)». Макеты
(`mockups/ch_ov_NN`, `sub_NN`, `subt_NN`, `claim_NN`) отвечают на вопрос «как выглядит»,
но не отвечают «где стоит и сколько висит». Этот файл — ответ: один список, где у каждого
экрана есть таймкод входа, таймкод выхода, длительность, текст и макет.

Его читают три поверхности: витрина `{CODE}_{cut}_screens.html`, текст структуры
(`structure_text.py`) и таймлайн ревью (`make_review_v6`). Раньше каждая считала раскладку
сама — и `subt_NN` с `claim_NN` не попадали на таймлайн вообще, потому что их никто не считал.

Правила длительности (канон канала, при нужде — ключи `screen_dur` в профиле):
  заставка главы  3.5 с   — читается название, кадр не успевает надоесть
  плашка подглавы 4.5 с   — подпись длиннее и стоит поверх речи
  крупная фраза   по реплике (но не короче 3 с и не длиннее 8 с)

Экраны не наслаиваются: если плашка попала в окно заставки главы, она отодвигается за него;
если после сдвига она уезжает в следующую главу — не ставится, и это видно в отчёте.

usage: screens_plan.py [--dry-run]
exit: 0 — ок · 1 — нет входов (карточка без глав) · 2 — есть экраны без макета
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

from _bootstrap import P, W6  # noqa: E402

from chapters_from_plan import tcf  # noqa: E402

GAP = 0.4                                          # минимальный зазор между соседними экранами


def dur_for(kind):
    d = P.profile(f'screen_dur.{kind}') or {'chapter': 3.5, 'sub': 4.5, 'claim': 5.0}.get(kind, 4.0)
    return float(d)


def mock(name):
    """→ имя файла макета, если он отрисован; иначе пусто (экран останется без картинки)"""
    for ext in ('.png', '.jpg'):
        if (Path(P.MOCK) / f'{name}{ext}').exists():
            return f'{name}{ext}'
    return ''


def claim_spans():
    """секунда → длительность реплики: её посчитал claims_pick, второй раз по словам не ищем"""
    p = W6 / 'claims_pick.json'
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding='utf-8'))
    return {int(r['sec']): float(r['end']) - float(r['sec']) for r in (d.get('picked') or [])}


def build():
    chap = [(float(s), str(n)) for s, n in (P.get('chapters') or [])]
    if not chap:
        return None, ['в карточке нет chapters']
    dur = float(P.get('duration_sec', 0)) or (chap[-1][0] + 60)
    names = P.get('ch_name', {}) or {}
    sub = [(int(s), int(c), str(t)) for s, c, t in (P.get('sub', []) or [])]
    no_screen = {int(x) for x in (P.get('sub_no_screen', []) or [])}
    claims = [(int(c[0]), str(c[1]), str(c[2] if len(c) > 2 else '')) for c in (P.get('claims', []) or [])]
    spans = claim_spans()
    warn = []

    S = []
    for i, (sec, no) in enumerate(chap):
        S.append({'id': f'ch_{no}', 'kind': 'chapter', 'chapter': no, 'sec': float(sec),
                  'dur': dur_for('chapter'), 'text': str(names.get(no, '')),
                  'mockup': mock(f'ch_ov_{no}'), 'on_screen': True,
                  'why': 'заставка главы — зритель понимает, о чём следующий кусок'})
    for j, (sec, ch, label) in enumerate(sub, 1):
        S.append({'id': f'sub_{j:02d}', 'kind': 'sub', 'chapter': f'{ch:02d}', 'sec': float(sec),
                  'dur': dur_for('sub'), 'text': label,
                  'mockup': mock(f'sub_{j:02d}') or mock(f'subt_{j:02d}'),
                  'on_screen': j not in no_screen,
                  'why': 'плашка подглавы — внутри главы сменилась тема'})
    for k, (sec, big, small) in enumerate(claims, 1):
        d = spans.get(sec, dur_for('claim'))
        S.append({'id': f'claim_{k:02d}', 'kind': 'claim',
                  'chapter': next((n for t, n in reversed(chap) if t <= sec), chap[0][1]),
                  'sec': float(sec), 'dur': max(3.0, min(8.0, round(d, 1))),
                  'text': ' / '.join(x for x in (big, small) if x),
                  'mockup': mock(f'claim_{k:02d}'), 'on_screen': False,
                  'why': 'крупная фраза — реплика, ради которой глава существует'})

    S.sort(key=lambda s: (s['sec'], {'chapter': 0, 'claim': 1, 'sub': 2}[s['kind']]))
    out, prev_end = [], -GAP
    for s in S:
        t_in = max(s['sec'], prev_end + GAP)
        if s['kind'] != 'chapter':
            nxt = next((t for t, _ in chap if t > s['sec']), dur)
            if t_in + s['dur'] > nxt:                # сдвиг уводит в следующую главу — лучше не ставить
                warn.append(f'{s["id"]} «{s["text"][:40]}» на {tcf(s["sec"])} не встал: упёрся в {tcf(nxt)}')
                continue
        t_out = min(dur, t_in + s['dur'])
        if t_out <= t_in:
            warn.append(f'{s["id"]} за концом фильма')
            continue
        out.append({'id': s['id'], 'kind': s['kind'], 'chapter': s['chapter'],
                    'tc_in': round(t_in, 2), 'tc_out': round(t_out, 2), 'dur': round(t_out - t_in, 2),
                    'tc': tcf(t_in), 'text': s['text'], 'source_tc': tcf(s['sec']),
                    'mockup': s['mockup'], 'on_screen': s['on_screen'], 'why': s['why']})
        prev_end = t_out
    return {'schema': 'screens-plan-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION,
            'duration_sec': dur, 'fps': P.FPS, 'mockups_dir': str(P.MOCK),
            'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'screens': out}, warn


def main():
    ap = argparse.ArgumentParser(description='раскладка экранов фильма на оси ката')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    plan, warn = build()
    if plan is None:
        print(f'!! {warn[0]}')
        return 1
    by = {}
    for s in plan['screens']:
        by[s['kind']] = by.get(s['kind'], 0) + 1
    lost = [s for s in plan['screens'] if not s['mockup']]
    print(f'экранов {len(plan["screens"])}: ' + ' · '.join(f'{k} {v}' for k, v in sorted(by.items()))
          + f' · всего на экране {round(sum(s["dur"] for s in plan["screens"]))} с из {int(plan["duration_sec"])}')
    for s in plan['screens']:
        flag = '' if s['mockup'] else '  ⚠ нет макета'
        print(f'  {s["tc"]:>9} +{s["dur"]:<4} {s["kind"]:<7} гл.{s["chapter"]} {s["text"][:52]}{flag}')
    for w in warn:
        print(f'  ⚠ {w}')
    if not a.dry_run:
        P.write_json_atomic(W6 / 'screens_plan.json', plan)
        print(f'записано: {W6 / "screens_plan.json"}')
    return 2 if lost else 0


if __name__ == '__main__':
    sys.exit(main())
