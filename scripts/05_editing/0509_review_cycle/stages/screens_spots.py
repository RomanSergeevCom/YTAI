#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Места ката, где экрана нет, — с дословной речью вокруг каждого.

Зачем отдельный шаг. Предложить экран нельзя, не зная, что в этом месте говорят, а вычитывать
ради этого весь транскрипт — и дорого, и ненадёжно: пересказ по памяти превращается в сочинение,
которое потом уезжает на плашку во весь кадр. Поэтому материал собирает код: он знает, где экрана
нет (`screens_plan.json`, `on_screen: false`), какие главы вообще остались без подтем, что звучит
вокруг точки (`shared/said.py`, дословно) и что здесь уже помечено чувствительным (`risk.json`).
Ничего не предлагает и не оценивает — только выкладывает материал. Решение и текст пишет человек
в `screens_proposal.json` (тот же приём, что `picks.json` у `kb_visuals`).

⚠️ Молчание честнее выдуманной цитаты: экран часто и ставят в паузу, поэтому `quote` может быть
пустой. Это не ошибка — это признак, что подпись придётся брать из соседней речи или из акта.

    python3 stages/screens_spots.py
    python3 stages/screens_spots.py --out /tmp/spots.json
    python3 stages/screens_spots.py --selftest

exit: 0 — ок · 1 — нет входов · 2 — у части точек нет ни цитаты, ни речи
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCHEMA = 'screens-spots-v1'
RISK_PAD = 6.0          # на сколько секунд вокруг точки смотрим реестр чувствительного
QUOTE_LIMIT = 14        # слов в короткой подписи (как у витрины экранов)
QUOTE_WINDOW = 4.0      # дальше этого молчим, а не берём речь из другого места фильма
MAX_MIN = 99            # said.TC_RE держит минуты в двух знаках — дальше окно молча пустеет

TC_RE = re.compile(r'^(\d+):(\d{2}(?:\.\d+)?)$')


def tosec(tc):
    """'7:18.00' → 438.0; число — как есть"""
    if isinstance(tc, (int, float)):
        return float(tc)
    m = TC_RE.match(str(tc or '').strip())
    return int(m.group(1)) * 60 + float(m.group(2)) if m else 0.0


def tc(sec):
    """438 → '7:18' — для глаза, не для машины"""
    m, s = divmod(max(0.0, float(sec)), 60)
    return f'{int(m)}:{int(s):02d}'


def bounds(chap, dur):
    """[(сек, 'NN')] + длительность → {'NN': (t0, t1)}"""
    out = {}
    for i, (t0, no) in enumerate(chap):
        t1 = chap[i + 1][0] if i + 1 < len(chap) else dur
        out[str(no)] = (float(t0), float(t1))
    return out


def act_at(acts, sec):
    """акт, в который попадает секунда; тезисы и утверждения акта — материал для подтем"""
    for a in acts or []:
        if float(a.get('t0', 0)) <= sec < float(a.get('t1', 0)):
            return a
    return None


def risk_at(risks, sec, pad=RISK_PAD):
    """что реестр чувствительного уже нашёл рядом с этой секундой"""
    out = []
    for r in risks or []:
        if float(r.get('t0', r.get('sec', 0))) - pad <= sec <= float(r.get('t1', r.get('sec', 0))) + pad:
            out.append({'key': r.get('key', ''), 'topic': r.get('topic', ''),
                        'action': r.get('action', ''), 'hard': bool(r.get('hard')),
                        'hit': r.get('hit', '')})
    return out


def skeleton(chap, ch_name, subs, screens, dur):
    """→ ([точки без речи], [предупреждения]) — только адреса, ничего про содержание.

    Две породы точек: экран, который в кате не стоит (`plan_off`), и глава, у которой нет ни
    одной подтемы (`empty_chapter`). Вторая — не ошибка ката, а место, где предложить тему."""
    bb = bounds(chap, dur)
    warn, spots = [], []
    for s in screens or []:
        if s.get('on_screen'):
            continue
        no = str(s.get('chapter', ''))
        t0, t1 = bb.get(no, (0.0, dur))
        sec = tosec(s.get('source_tc') or s.get('tc') or s.get('tc_in'))
        if not (t0 <= sec < t1):
            warn.append(f'{s.get("id")}: секунда {tc(sec)} вне главы {no} ({tc(t0)}–{tc(t1)})')
        spots.append({'id': str(s.get('id', '')), 'why_spot': 'plan_off', 'kind_now': str(s.get('kind', '')),
                      'ch': no, 'ch_name': str(ch_name.get(no, '')), 'ch_t0': t0, 'ch_t1': t1,
                      'sec': round(sec, 2), 'tc': tc(sec), 'label': str(s.get('text', '')),
                      'mockup': str(s.get('mockup', '')), 'dur_planned': s.get('dur')})
    with_subs = {f'{int(c):02d}' for _, c, _ in subs or []}
    for t0, no in chap:
        no = str(no)
        if no in with_subs:
            continue
        t1 = bb[no][1]
        spots.append({'id': f'ch_{no}_empty', 'why_spot': 'empty_chapter', 'kind_now': 'chapter',
                      'ch': no, 'ch_name': str(ch_name.get(no, '')), 'ch_t0': float(t0), 'ch_t1': t1,
                      'sec': round(float(t0), 2), 'tc': tc(t0), 'label': '', 'mockup': '',
                      'dur_planned': None})
    spots.sort(key=lambda x: (x['sec'], x['id']))
    return spots, warn


def enrich(spots, acts, risks, words, say=None, quote=None):
    """добавить к каждой точке речь, акт и чувствительные пометки. Ничего не сочиняет."""
    quote = quote or (lambda ws, sec: '')
    for sp in spots:
        a = act_at(acts, sp['sec']) or {}
        sp['act'] = a.get('act')
        sp['act_title'] = a.get('title', '')
        sp['act_summary'] = a.get('summary', '')
        # тезисы и утверждения акта нужны там, где подтем нет вовсе: из них и растёт тема
        sp['act_theses'] = [str(t) for t in (a.get('theses') or [])] if sp['why_spot'] == 'empty_chapter' else []
        sp['quote'] = quote(words, sp['sec']) if words else ''
        sp['verbatim'] = ''
        if say:
            said = say(tc(sp['sec']) if sp['sec'] < MAX_MIN * 60 else '', sp['sec'])
            sp['verbatim'] = (said or {}).get('text', '')
        sp['risk'] = risk_at(risks, sp['sec'])
    return spots


def report(spots):
    """строки для глаза — счёт по породам и что осталось без речи"""
    off = sum(1 for s in spots if s['why_spot'] == 'plan_off')
    emp = sum(1 for s in spots if s['why_spot'] == 'empty_chapter')
    blind = [s['id'] for s in spots if not s['quote'] and not s['verbatim']]
    risky = sum(1 for s in spots if s['risk'])
    return off, emp, blind, risky


def main():
    ap = argparse.ArgumentParser(description='места ката без экрана + дословная речь вокруг них')
    ap.add_argument('--out', default='', help='куда писать (по умолчанию work/{cut}/screens_spots.json)')
    a = ap.parse_args()

    sys.path.insert(0, str(HERE))
    from _bootstrap import P, W6                                    # noqa: PLC0415
    sys.path.insert(0, str(HERE.parent / 'shared'))
    import said as SAID                                             # noqa: PLC0415
    from screens_page import load_words, quote_at                   # noqa: PLC0415

    plan_f = W6 / 'screens_plan.json'
    if not plan_f.exists():
        print(f'!! нет {plan_f} — сначала review.py run --only screens_plan')
        return 1
    plan = json.loads(plan_f.read_text(encoding='utf-8'))

    def _load(name, default):
        f = W6 / name
        try:
            return json.loads(f.read_text(encoding='utf-8')) if f.exists() else default
        except ValueError:
            print(f'⚠️ {name}: битый JSON — иду без него')
            return default

    acts = (_load('acts_compact.json', {}) or {}).get('acts') or []
    risks = _load('risk.json', []) or []
    words = load_words(P.WORDS)
    dur = float(P.duration_sec())
    if dur >= MAX_MIN * 60:
        print(f'⚠️ кат длиннее {MAX_MIN} минут: said.TC_RE читает минуты двумя знаками, речь будет пустой')

    spots, warn = skeleton([(int(t), str(n)) for t, n in P.CHAPTERS], P.get('ch_name', {}) or {},
                           [(int(s), int(c), str(t)) for s, c, t in (P.get('sub') or [])],
                           plan.get('screens') or [], dur)
    enrich(spots, acts, risks, words, say=SAID.said, quote=lambda ws, sec: quote_at(ws, sec, QUOTE_LIMIT, QUOTE_WINDOW))

    off, emp, blind, risky = report(spots)
    d = {'schema': SCHEMA, 'code': P.CODE, 'cut_version': P.CUT_VERSION, 'duration_sec': dur,
         'built': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
         'counts': {'spots': len(spots), 'plan_off': off, 'empty_chapters': emp,
                    'no_quote': len(blind), 'with_risk': risky},
         'spots': spots}
    out = Path(a.out).expanduser() if a.out else (W6 / 'screens_spots.json')
    P.write_json_atomic(out, d)
    for w in warn:
        print('⚠️', w)
    print(f'точек {len(spots)}: без экрана {off} · глав без подтем {emp} · с пометкой фонда {risky}')
    print(f'→ {out}')
    if blind:
        print(f'⚠️ без речи вовсе ({len(blind)}): {", ".join(blind[:8])}')
        return 2
    return 0


def selftest():
    chap = [(0, '01'), (100, '02'), (200, '03')]
    names = {'01': 'ПЕРВАЯ', '02': 'ВТОРАЯ', '03': 'ТРЕТЬЯ'}
    subs = [(120, 2, 'Подтема')]
    screens = [{'id': 'ch_01', 'kind': 'chapter', 'chapter': '01', 'source_tc': '0:00.00',
                'text': 'ПЕРВАЯ', 'mockup': 'ch_ov_01.png', 'on_screen': True, 'dur': 3.5},
               {'id': 'sub_01', 'kind': 'sub', 'chapter': '02', 'source_tc': '2:00.00',
                'text': 'Подтема', 'mockup': 'sub_01.png', 'on_screen': False, 'dur': 4.5},
               {'id': 'claim_01', 'kind': 'claim', 'chapter': '03', 'source_tc': '3:30.00',
                'text': 'раз / два', 'mockup': 'claim_01.png', 'on_screen': False, 'dur': 5.0}]
    spots, warn = skeleton(chap, names, subs, screens, 300.0)
    assert [s['id'] for s in spots] == ['ch_01_empty', 'sub_01', 'ch_03_empty', 'claim_01'], [s['id'] for s in spots]
    assert not warn, warn
    assert [s['why_spot'] for s in spots].count('empty_chapter') == 2       # главы 01 и 03 без подтем
    assert spots[1]['sec'] == 120.0 and spots[1]['tc'] == '2:00'
    assert spots[3]['ch'] == '03' and spots[3]['ch_t0'] == 200.0

    # секунда вне своей главы обязана попасть в предупреждения, а не пройти молча
    bad = [dict(screens[1], source_tc='9:00.00')]
    _s, w2 = skeleton(chap, names, subs, bad, 300.0)
    assert w2 and 'вне главы' in w2[0], w2

    # ловушка окна: в паузе первое слово «после» звучит через минуту — цитаты быть не должно
    words = [{'w': 'раз', 's': 119.0}, {'w': 'два', 's': 119.5}, {'w': 'потом', 's': 260.0}]
    def q(ws, sec):
        out = []
        for w in ws:
            if w['s'] >= sec - 0.2:
                if not out and w['s'] > sec + QUOTE_WINDOW:
                    return ''
                out.append(w['w'])
        return ' '.join(out)
    acts = [{'act': 3, 'title': 'ТРЕТЬЯ', 't0': 200.0, 't1': 300.0, 'summary': 'про третью',
             'theses': ['тезис раз', 'тезис два']}]
    risks = [{'t0': 199.0, 't1': 200.0, 'sec': 199.5, 'key': 'debts', 'topic': 'долги',
              'action': '⚠️ на подтверждение фонда', 'hard': False, 'hit': 'долг'}]
    enrich(spots, acts, risks, words, say=None, quote=q)
    assert spots[1]['quote'] == '', spots[1]['quote']                       # 2:00 — тишина впереди
    assert spots[2]['act'] == 3 and spots[2]['act_theses'] == ['тезис раз', 'тезис два']
    assert spots[3]['act_theses'] == []                                     # у plan_off тезисы не нужны
    assert spots[2]['risk'] and spots[2]['risk'][0]['key'] == 'debts'
    assert spots[0]['risk'] == []

    off, emp, blind, risky = report(spots)
    assert (off, emp, risky) == (2, 2, 1), (off, emp, risky)
    assert len(blind) == 4                                                  # say=None → речи нет ни у кого

    assert tosec('7:18.00') == 438.0 and tc(438) == '7:18' and tosec(12.5) == 12.5
    print('SELFTEST OK screens_spots')
    return 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
