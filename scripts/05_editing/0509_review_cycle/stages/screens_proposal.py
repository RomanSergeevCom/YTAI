#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Предложения экранов на пустые места ката — и гейт к ним.

Зачем. `screens_spots.py` выкладывает материал: где экрана нет и что там звучит. Сам текст
экрана пишет человек — руками, в `work/{cut}/screens_proposal.json` (тот же приём, что
`picks.json` у `kb_visuals`: модель и код не решают, что показать). А вот проверить написанное
обязан код, иначе на плашку во весь кадр уедет сочинённая цитата, несуществующий вид или
чувствительная тема без подтверждения фонда.

Что проверяется:
  1. вид есть в витрине канала (`bdd_plates.py`, список `plates`) и набор полей совпадает точно;
  2. цитата звучит в кате ДОСЛОВНО (ищем подряд идущие слова, как `claims_pick`);
  3. таймкод внутри своей главы и внутри длины ката, и не накрывает уже стоящий экран;
  4. чувствительное: `hard` — отказ; любое другое попадание или пересечение с `risk.json`
     требует `fund_confirm` и внятной записи, ЧТО именно подтверждает фонд;
  5. лимиты `claims_pick`: ≤12 слов, ≤1 крупная фраза на главу (считая уже стоящие),
     без слов-паразитов, крупную фразу говорит героиня, а не куратор фонда.

⚠️ Пункт 4 намеренно мягче, чем у `claims_pick`. Тот кандидата просто выбрасывает — и правильно,
потому что там на экран идёт дословная реплика героини. Здесь же редакционная плашка (долги,
календарь алиментов, дата смерти) — это ровно то, что фонд подтверждает, а не то, что удаляют:
политика канала `sensitivity.policy = fund_confirm`, «⛔ только по прямым письменным запретам».

⚠️ В карточку (`card.sub`) предложения НЕ пишутся (решение Романа 24.09.2026): `sub_no_screen`
и `sub_img` — ПОРЯДКОВЫЕ номера, новая подглава сдвинула бы их все и потребовала пересборки
всех поверхностей. Предложение живёт своим файлом и доезжает до карты XMind и до колонки
«Как надо» во вкладке «Главы».

    python3 stages/screens_proposal.py check
    python3 stages/screens_proposal.py check --fix-quotes     # переписать цитату словами ката
    python3 stages/screens_proposal.py kinds                  # показать виды и их поля
    python3 stages/screens_proposal.py --selftest

exit: 0 — годно · 1 — нет входов · 2 — гейт не пройден
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCHEMA = 'screens-proposal-v1'
# plate_for_claim — плита к фразе, которая в `card.claims` УЖЕ есть; claim — фраза, которой там нет.
# Разделены нарочно: правило «≤1 крупная фраза на главу» иначе считает плиту к своей же фразе второй
ROLES = ('plate_for_sub', 'plate_for_claim', 'plate_for_chapter', 'new_subtopic', 'claim')
MAX_WORDS = 12          # как --max-words у claims_pick
LONG_FIELD = 120        # длиннее — предупреждение: плита рисует поле в одну-две строки
# слова-паразиты устной речи: в потоке незаметны, на плашке читаются как небрежность
FILLER = ('вроде как', 'то есть', 'как сказать', 'как бы', 'ну вот', 'это самое', 'в общем')


def kinds(src):
    """исходник bdd_plates.py → {'q_sub': ['over', 'title'], …} — виды витрины и их поля.

    Читаем СПИСОК `plates` внутри main(), а не все `def`-ы: `q_ch_light`, `lower_b/c/d/f`,
    `q_timeline`, `q_compare` в коде есть, но в витрину не входят — плашки B, C, D Роман снял,
    F отклонил. Импортировать модуль нельзя: он на уровне модуля читает брендбук и выходит,
    если файла нет. Приём тот же, что у `screens_library.py`, — читать исходник рендера."""
    tree = ast.parse(src)
    funcs = {n.name: [a.arg for a in n.args.args]
             for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    out = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'plates' for t in node.targets)):
            continue
        for el in getattr(node.value, 'elts', []):
            if not (isinstance(el, ast.Tuple) and len(el.elts) == 2):
                continue
            name, call = el.elts[0], el.elts[1]
            if not (isinstance(name, ast.Constant) and isinstance(call, ast.Call)):
                continue
            fn = getattr(call.func, 'id', '')
            if fn in funcs:
                out[str(name.value)] = [a for a in funcs[fn] if a != 'shot']
    return out


def words_of(s):
    return [w for w in re.split(r'\s+', str(s or '').strip()) if w]


def filler_in(s):
    low = ' ' + str(s or '').lower().replace('ё', 'е') + ' '
    return [f for f in FILLER if f in low]


def overlaps(sec, busy, gap):
    """→ имя экрана, окно которого накрывает секунду; иначе пусто"""
    for t0, t1, who in busy:
        if t0 - gap <= sec <= t1 + gap:
            return who
    return ''


def gate(items, ctx):
    """→ [(уровень, строка)] — 'FAIL' валит гейт, 'WARN' только печатается"""
    out = []
    seen_n, claims_ch = set(), dict(ctx.get('claims_by_ch') or {})

    def bad(n, msg):
        out.append(('FAIL', f'#{n}: {msg}'))

    def warn(n, msg):
        out.append(('WARN', f'#{n}: {msg}'))

    for it in items:
        n = it.get('n')
        if n in seen_n:
            bad(n, 'номер повторяется')
        seen_n.add(n)

        role = str(it.get('role', ''))
        if role not in ROLES:
            bad(n, f'роль «{role}» не из {"/".join(ROLES)}')

        kind = str(it.get('kind', ''))
        kf = ctx['kinds'].get(kind)
        if kf is None:
            bad(n, f'вида «{kind}» нет в витрине канала; есть: {", ".join(sorted(ctx["kinds"]))}')
        else:
            got, want = set((it.get('fields') or {})), set(kf)
            if got != want:
                bad(n, f'поля вида «{kind}»: лишние {sorted(got - want) or "—"}, '
                       f'нет {sorted(want - got) or "—"} (нужны {kf})')
            if ctx.get('mock') and not ctx['mock'](kind):
                warn(n, f'макета «{kind}» в mockups/bdd нет — показать будет нечем')

        ch = str(it.get('ch', ''))
        sec = float(it.get('sec', -1))
        b = ctx['bounds'].get(ch)
        if b is None:
            bad(n, f'главы «{ch}» в карточке нет')
        elif not (b[0] <= sec < b[1]):
            bad(n, f'секунда {sec:.0f} вне главы {ch} ({b[0]:.0f}–{b[1]:.0f})')
        if not (0 <= sec < ctx['dur']):
            bad(n, f'секунда {sec:.0f} вне ката (0–{ctx["dur"]:.0f})')
        who = overlaps(sec, ctx.get('busy') or [], ctx.get('gap', 0.4))
        if who:
            bad(n, f'секунда {sec:.0f} накрывает экран «{who}», который в кате уже стоит')

        texts = [str(v) for v in (it.get('fields') or {}).values() if isinstance(v, str)]
        for t in texts + [str(it.get('quoted') or '')]:
            f = filler_in(t)
            if f:
                bad(n, f'слова-паразиты на экране: {", ".join(f)}')
        for t in texts:
            if len(t) > LONG_FIELD:
                warn(n, f'поле длиной {len(t)} знаков — кегль на плите уедет')

        q = it.get('quoted')
        if q:
            if ctx.get('find'):
                found = ctx['find'](q)
                if not found:
                    bad(n, f'в кате так не говорят: «{q}»')
                elif ctx.get('norm', str)(found) != ctx.get('norm', str)(q):
                    warn(n, f'в кате сказано иначе: «{found}» (--fix-quotes перепишет)')
            if role in ('claim', 'plate_for_claim') and len(words_of(q)) > ctx.get('max_words', MAX_WORDS):
                bad(n, f'крупная фраза длиннее {ctx.get("max_words", MAX_WORDS)} слов')
        elif role in ('claim', 'plate_for_claim'):
            bad(n, 'у крупной фразы нет поля quoted — она обязана звучать в кате')

        if role in ('claim', 'plate_for_claim'):
            if str(it.get('speaker') or '') == str(ctx.get('fund_speaker') or '\0'):
                bad(n, 'крупной фразой говорит куратор фонда, а не героиня')
        if role == 'claim':                     # новая фраза, которой в карточке ещё нет
            claims_ch[ch] = claims_ch.get(ch, 0) + 1
            if claims_ch[ch] > 1:
                bad(n, f'в главе {ch} уже есть крупная фраза — приём перестаёт быть событием')

        hits = []
        for rx, topic in (ctx.get('sens') or []):
            for t in texts + [str(it.get('quoted') or '')]:
                if rx.search(t):
                    hits.append(topic)
        hard = [r for r in ctx.get('risk_at', lambda s: [])(sec) if r.get('hard')]
        soft = [r.get('topic', '') for r in ctx.get('risk_at', lambda s: [])(sec) if not r.get('hard')]
        if hard:
            bad(n, f'прямой запрет канала: {", ".join(sorted({r.get("topic", "") for r in hard}))}')
        if (hits or soft) and not (it.get('fund_confirm') and str(it.get('fund_note') or '').strip()):
            bad(n, f'чувствительное ({", ".join(sorted(set(hits + soft)))}) — нужны '
                   f'fund_confirm: true и fund_note «что подтверждает фонд»')
    return out


def load(path):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    if d.get('schema') != SCHEMA:
        raise SystemExit(f'{path}: схема «{d.get("schema")}», ожидалась «{SCHEMA}»')
    return d


def main():
    ap = argparse.ArgumentParser(description='гейт предложений экранов')
    ap.add_argument('cmd', nargs='?', default='check', choices=['check', 'kinds'])
    ap.add_argument('--in', dest='inp', default='', help='файл предложений')
    ap.add_argument('--fix-quotes', action='store_true', help='переписать quoted словами ката')
    ap.add_argument('--remap', action='store_true',
                    help='пересчитать ch у каждого предложения по его секунде (после переезда глав)')
    a = ap.parse_args()

    sys.path.insert(0, str(HERE))
    from _bootstrap import P, W6                                    # noqa: PLC0415

    ks = kinds((HERE / 'bdd_plates.py').read_text(encoding='utf-8'))
    if a.cmd == 'kinds':
        for k in sorted(ks):
            print(f'  {k:<12} {", ".join(ks[k])}')
        print(f'видов {len(ks)}')
        return 0

    src = Path(a.inp).expanduser() if a.inp else (W6 / 'screens_proposal.json')
    if not src.exists():
        print(f'!! нет {src} — предложения пишутся руками по work/{{cut}}/screens_spots.json')
        return 1
    d = load(src)
    items = d.get('items') or []

    import claims_pick as CP                                        # noqa: PLC0415
    import screens_plan as SP                                       # noqa: PLC0415
    import tz_diff as TD                                            # noqa: PLC0415
    from chapters_from_plan import load_words                       # noqa: PLC0415

    chap = [(int(t), str(no)) for t, no in P.CHAPTERS]
    dur = float(P.duration_sec())
    bounds = {no: (float(t0), float(chap[i + 1][0] if i + 1 < len(chap) else dur))
              for i, (t0, no) in enumerate(chap)}
    cw = load_words(P.WORDS)
    index = CP.build_index(cw)

    def find(phrase):
        got = CP.find_seq(cw, phrase, nwords=MAX_WORDS, index=index, min_run=4)
        return ' '.join(w['w'] for w in cw[got[0]:got[1] + 1]) if got else ''

    plan_f = W6 / 'screens_plan.json'
    plan = json.loads(plan_f.read_text(encoding='utf-8')) if plan_f.exists() else {'screens': []}
    busy = [(float(s['tc_in']), float(s['tc_out']), str(s['id']))
            for s in (plan.get('screens') or []) if s.get('on_screen')]
    risk_f = W6 / 'risk.json'
    risks = json.loads(risk_f.read_text(encoding='utf-8')) if risk_f.exists() else []

    def risk_at(sec, pad=6.0):
        return [r for r in risks
                if float(r.get('t0', r.get('sec', 0))) - pad <= sec <= float(r.get('t1', r.get('sec', 0))) + pad]

    claims_by_ch = {}
    for c in (P.get('claims') or []):
        no = CP.chapter_of(float(c[0]), chap, dur)
        claims_by_ch[no] = claims_by_ch.get(no, 0) + 1

    ctx = {'kinds': ks, 'bounds': bounds, 'dur': dur, 'busy': busy, 'gap': SP.GAP,
           'claims_by_ch': claims_by_ch, 'sens': CP.sensitive_rx(), 'risk_at': risk_at,
           'fund_speaker': P.get('fund_speaker', ''), 'max_words': MAX_WORDS,
           'find': find, 'norm': TD.norm,
           'mock': lambda k: (Path(P.MOCK) / 'bdd' / f'{k}.png').exists()}

    if a.remap:
        # Границы глав двигают руками, а `ch` у предложения записан числом. Пересчитываем его
        # по секунде — иначе гейт поймает расхождение, но только после того, как половина
        # предложений уже уехала в чужую главу на всех поверхностях
        moved = []
        for it in items:
            was = str(it.get('ch', ''))
            now = CP.chapter_of(float(it.get('sec', 0)), chap, dur)
            if now != was:
                it['ch'], _ = now, moved.append((it.get('n'), was, now))
        if moved:
            P.write_json_atomic(src, d)
            for n, was, now in moved:
                print(f'#{n}: глава {was} → {now}')
        print(f'пересчитано глав: {len(moved)} из {len(items)}')

    if a.fix_quotes:
        fixed = 0
        for it in items:
            q = it.get('quoted')
            if q:
                got = find(q)
                if got and TD.norm(got) != TD.norm(q):
                    it['quoted'], fixed = got, fixed + 1
        if fixed:
            P.write_json_atomic(src, d)
            print(f'цитат переписано словами ката: {fixed}')

    bad = gate(items, ctx)
    for lvl, msg in bad:
        print(('✗ ' if lvl == 'FAIL' else '⚠️ ') + msg)
    fails = sum(1 for lvl, _ in bad if lvl == 'FAIL')
    by_role = {}
    for it in items:
        by_role[it.get('role', '?')] = by_role.get(it.get('role', '?'), 0) + 1
    print(f'предложений {len(items)}: ' + ' · '.join(f'{k} {v}' for k, v in sorted(by_role.items())))
    print(f'видов в витрине {len(ks)} · отказов {fails} · предупреждений {len(bad) - fails}')
    return 2 if fails else 0


def selftest():
    src = (HERE / 'bdd_plates.py').read_text(encoding='utf-8')
    ks = kinds(src)
    assert len(ks) == 21, f'видов {len(ks)}: {sorted(ks)}'
    assert ks['d_date'] == ['day', 'month_year', 'what', 'tc'], ks['d_date']
    assert ks['q_sub'] == ['over', 'title'] and ks['q_claim'] == ['lead', 'key'], (ks['q_sub'], ks['q_claim'])
    for dead in ('q_ch_light', 'lower_b', 'lower_c', 'lower_d', 'lower_f', 'q_timeline', 'q_compare'):
        assert dead not in ks, f'{dead} в витрину не входит, а гейт его пропустил'

    ctx = {'kinds': {'q_sub': ['over', 'title'], 'q_claim': ['lead', 'key']},
           'bounds': {'01': (0.0, 100.0), '02': (100.0, 200.0)}, 'dur': 200.0,
           'busy': [(10.0, 13.5, 'ch_01')], 'gap': 0.4, 'claims_by_ch': {'02': 1},
           'sens': [(re.compile('долг'), 'долги')], 'fund_speaker': 'Speaker 2',
           'max_words': 12, 'norm': lambda s: s.lower(),
           'find': lambda q: 'я жила одна' if 'жила одна' in q else '',
           'risk_at': lambda sec: ([{'topic': 'аборт', 'hard': True}] if sec == 77 else []),
           'mock': lambda k: True}
    ok = {'n': 1, 'role': 'plate_for_sub', 'kind': 'q_sub', 'ch': '01', 'sec': 40.0,
          'fields': {'over': 'ГЛАВА 01', 'title': 'Тема'}, 'quoted': None}
    assert gate([ok], ctx) == [], gate([ok], ctx)

    cases = [
        dict(ok, n=2, kind='q_ch'),                                          # вида нет в витрине
        dict(ok, n=3, fields={'over': 'ГЛАВА 01'}),                          # нет поля title
        dict(ok, n=4, sec=150.0),                                            # секунда вне главы 01
        dict(ok, n=5, quoted='такого в кате не звучит совсем'),              # не дословно
        dict(ok, n=6, sec=77.0),                                             # прямой запрет канала
        dict(ok, n=7, role='claim', ch='02', sec=150.0, kind='q_claim',
             fields={'lead': 'раз', 'key': 'два'}, quoted='я жила одна'),    # вторая фраза в главе 02
        dict(ok, n=8, sec=12.0),                                             # накрывает стоящий экран
        dict(ok, n=9, fields={'over': 'ГЛАВА 01', 'title': 'Тема то есть'}),  # слово-паразит
        dict(ok, n=10, fields={'over': 'ГЛАВА 01', 'title': 'про долг'}),    # чувствительное без фонда
    ]
    got = gate(cases, ctx)
    fails = {m.split(':')[0] for lvl, m in got if lvl == 'FAIL'}
    assert fails == {f'#{i}' for i in range(2, 11)}, sorted(fails)

    # плита к фразе, которая в карточке УЖЕ есть, не считается второй фразой главы
    keep = dict(ok, n=12, role='plate_for_claim', ch='02', sec=150.0, kind='q_claim',
                fields={'lead': 'раз', 'key': 'два'}, quoted='я жила одна', speaker='Speaker 1')
    assert [m for lvl, m in gate([keep], ctx) if lvl == 'FAIL'] == [], gate([keep], ctx)

    # чувствительное с подтверждением фонда проходит — политика канала fund_confirm, а не ⛔
    good = dict(ok, n=11, fields={'over': 'ГЛАВА 01', 'title': 'про долг'},
                fund_confirm=True, fund_note='суммы долга подтверждает фонд')
    assert [m for lvl, m in gate([good], ctx) if lvl == 'FAIL'] == []

    assert filler_in('ну вот так') == ['ну вот'] and filler_in('чисто') == []
    assert overlaps(13.7, [(10.0, 13.5, 'x')], 0.4) == 'x' and overlaps(20.0, [(10.0, 13.5, 'x')], 0.4) == ''
    print('SELFTEST OK screens_proposal')
    return 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
