#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Карта выпуска майндкартой: `.xmind`, который можно двигать руками.

Зачем. Картинка `mockups/info_structure_map.png` и текст во вкладке «Главы» показывают структуру,
но переставить в них главу нельзя. Роман 24.09.2026 попросил ту же карту в XMind — чтобы
структуру трогать. Выгрузка ОДНОСТОРОННЯЯ: правки из `.xmind` обратно в карточку не читаются,
поэтому карта помечена версией ката и временем сборки — иначе через неделю не отличить, от
какого круга она осталась.

Откуда данные — ничего не считается заново:
  карточка              главы, имена, подглавы, крупные фразы
  work/{cut}/screens_plan.json    что в кате стоит, а чего нет (`on_screen`)
  work/{cut}/screens_proposal.json  предложения экранов (необязательно)
  work/{cut}/screens_spots.json     дословная речь вокруг точки (необязательно, идёт в заметку)

Что в заголовке ветки: номер, имя, таймкод и ровно одна пометка — «➕ СОЗДАТЬ» или «✓ стоит».
Всё длинное — в заметку топика (`note`): речь, зачем экран, вид плиты и что подтверждает фонд.
Так велит сам писатель карт: «длинному пояснению в заголовке не место, оно ломает карту».

⚠️ Подглавы группируются ПО ПОЛЮ `ch` тройки — как `structure_text.py`, `screens_plan.py` и
`doc_tab_chapters_v1.py`. Блок H `make_infographics_v6.py` группирует по временно́му окну; сегодня
это одно и то же, но если разойдётся — карта, картинка и док покажут разное, поэтому предупреждаем.

⚠️ Писатель `999_extra/xmind_out/xmind_out.py` маркеров и цветов не умеет: пометка — словом
в заголовке, а не значком XMind.

    python3 stages/structure_xmind.py
    python3 stages/structure_xmind.py --out ~/карта.xmind --dump-titles /tmp/titles.json
    python3 stages/structure_xmind.py --selftest

exit: 0 — ок · 1 — нет входов · 2 — круг чтения не сошёлся
"""
import argparse
import datetime
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / 'shared'
# писатель карт лежит вне папки стадии; `_bootstrap` его на sys.path не кладёт, и править
# общий bootstrap ради одного модуля не стоит — дорога локальная, как у 0121_studio_day/daymap.py
XMIND_DIR = HERE.parents[2] / '999_extra' / 'xmind_out'

MARK_NEW = '➕ СОЗДАТЬ'
MARK_OK = '✓ стоит'
MARK_CH_OK = '✓ заставка стоит'
SUMMARY = 'СВОДКА'
ZIP_MEMBERS = {'content.xml', 'meta.xml', 'META-INF/manifest.xml'}


def tc(sec):
    m, s = divmod(max(0.0, float(sec)), 60)
    return f'{int(m)}:{int(s):02d}'


def note(*lines):
    """заметка топика: непустые строки через пустую строку; нет ни одной — заметки нет"""
    body = '\n'.join(str(x).strip() for x in lines if str(x or '').strip())
    return body or None


def tree(card, plan, props, spots, labels, warn):
    """→ дерево для xmind_out: (заголовок, [дети]) в три уровня.

    card   — {'code','film','cut_version','duration_sec','chapters','ch_name','sub','sub_no_screen','claims'}
    plan   — [экран screens_plan]  ·  props — [предложение]  ·  spots — {id: точка}
    labels — {'q_sub': ('плашка подтемы', 'когда ставить'), …}  ·  warn — список, куда писать расхождения
    """
    chap = [(int(t), str(n)) for t, n in card['chapters']]
    dur = float(card['duration_sec'])
    names = card.get('ch_name') or {}
    subs = [(int(s), int(c), str(t)) for s, c, t in (card.get('sub') or [])]
    no_screen = {int(x) for x in (card.get('sub_no_screen') or [])}
    claims = [(int(c[0]), ' '.join(str(x) for x in c[1:] if x)) for c in (card.get('claims') or [])]
    on = {str(s.get('id')): bool(s.get('on_screen')) for s in (plan or [])}

    by_ch = {}
    for j, (sec, c, label) in enumerate(subs, 1):
        by_ch.setdefault(f'{c:02d}', []).append((sec, label, j))
    # сверка с раскладкой блока H: он режет подглавы окном времени, а не полем ch
    for i, (t0, no) in enumerate(chap):
        t1 = chap[i + 1][0] if i + 1 < len(chap) else dur
        win = {s for s, c, _ in subs if t0 <= s < t1}
        mine = {s for s, _, _ in by_ch.get(no, [])}
        if win != mine:
            warn.append(f'глава {no}: по полю ch подглав {len(mine)}, по времени {len(win)} — '
                        f'карта и картинка блока H покажут разное')

    # Плита к УЖЕ размеченной подглаве или фразе своей ветки не заводит: она обогащает её.
    # Иначе один и тот же экран стоит в карте дважды, и «➕ СОЗДАТЬ» больше не пересчитать
    by_spot, props_by_ch = {}, {}
    for p in props or []:
        if str(p.get('role')) in ('plate_for_sub', 'plate_for_claim') and p.get('spot'):
            by_spot[str(p['spot'])] = p
        else:
            props_by_ch.setdefault(str(p.get('ch')), []).append(p)

    def prop_title(p):
        """чем подписать ветку предложения. `label` руками → поле title вида → склейка полей.

        Склейка годится плашке подтемы и вопросу, но не плите данных: у `d_debts` строковое
        поле ровно одно — таймкод, и ветка подписывалась бы «27:45». Поэтому у таких плит
        подпись пишется руками ключом `label`."""
        f = p.get('fields') or {}
        return (str(p.get('label') or '').strip() or str(f.get('title') or '').strip()
                or ' · '.join(str(v) for v in f.values() if isinstance(v, str))
                or str(p.get('kind')))

    def kind_tail(p):
        if not p:
            return ''
        lab = (labels or {}).get(str(p.get('kind')), (str(p.get('kind')), ''))
        return f' · {lab[0]}' + (' ⚠️ фонд' if p.get('fund_confirm') else '')

    def prop_note(p):
        if not p:
            return []
        return [p.get('why'), p.get('how_it_should_be'),
                p.get('fund_confirm') and f'⚠️ фонд: {p.get("fund_note")}',
                f'вид {p.get("kind")} · макет {p.get("mockup")}']

    kids, n_prop = [], 0
    for i, (t0, no) in enumerate(chap):
        t1 = chap[i + 1][0] if i + 1 < len(chap) else dur
        nm = str(names.get(no, f'ГЛАВА {no}')).strip()
        ch_mark = MARK_CH_OK if on.get(f'ch_{no}', True) else MARK_NEW
        rows = []
        for sec, label, j in sorted(by_ch.get(no, [])):
            mark = MARK_NEW if j in no_screen else MARK_OK
            sp = (spots or {}).get(f'sub_{j:02d}') or {}
            p = by_spot.get(f'sub_{j:02d}')
            rows.append((sec, {'title': f'{tc(sec)} ▸ {label}   {mark}{kind_tail(p)}',
                               'note': note(sp.get('verbatim'),
                                            sp.get('act_title') and f'акт {sp.get("act")} · {sp.get("act_title")}',
                                            *prop_note(p)),
                               'children': []}))
        for k, (csec, ctext) in enumerate(claims, 1):
            if not (t0 <= csec < t1):
                continue
            mark = MARK_OK if on.get(f'claim_{k:02d}') else MARK_NEW
            sp = (spots or {}).get(f'claim_{k:02d}') or {}
            p = by_spot.get(f'claim_{k:02d}')
            rows.append((csec, {'title': f'{tc(csec)} ❝ {ctext}   {mark}{kind_tail(p)}',
                                'note': note(sp.get('verbatim'), *prop_note(p)), 'children': []}))
        for p in props_by_ch.get(no, []):
            rows.append((float(p.get('sec', t0)),
                         {'title': f'{tc(p.get("sec", t0))} ✱ {prop_title(p)}   {MARK_NEW}{kind_tail(p)}',
                          'note': note(p.get('quoted') and f'в кате: «{p["quoted"]}»', *prop_note(p)),
                          'children': []}))
            n_prop += 1
        kids.append({'title': f'{no} · {nm}   {tc(t0)}–{tc(t1)}   {ch_mark}',
                     'note': None,
                     'children': [r for _, r in sorted(rows, key=lambda x: x[0])]})

    miss = len(no_screen) + sum(1 for k, _ in enumerate(claims, 1) if not on.get(f'claim_{k:02d}'))
    kids.append({'title': SUMMARY, 'note': None, 'children': [
        {'title': f'глав {len(chap)} · подглав {len(subs)} · крупных фраз {len(claims)}'},
        {'title': f'экранов в кате нет — {miss}'},
        {'title': f'предложено экранов — {len(props or [])}, из них новых мест {n_prop}'},
        {'title': f'собрано {datetime.datetime.now().strftime("%d.%m.%Y %H:%M")} · кат {card["cut_version"]}'},
    ]})

    head = (f'{card["code"]} · {card.get("film_short") or "карта выпуска"} — '
            f'{card["cut_version"]} · {tc(dur)} · {len(chap)} глав · {len(subs)} подглав'
            + (f' · {len(claims)} фразы' if claims else ''))
    return (head, kids), n_prop


def verify(path, expect):
    """круг чтения: карта обязана прочитаться обратно тем же деревом. → [расхождения]"""
    bad = []
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            bad.append('zip битый')
        got = set(z.namelist())
        if got != ZIP_MEMBERS:
            bad.append(f'члены архива {sorted(got)}, ожидались {sorted(ZIP_MEMBERS)}')
    sys.path.insert(0, str(XMIND_DIR))
    import xmind_out as XM                                          # noqa: PLC0415
    titles = XM.read_titles(path)
    d0 = [t for d, t in titles if d == 0]
    d1 = [t for d, t in titles if d == 1]
    # строки СВОДКИ тоже лежат на втором уровне, но экранами не являются: считаем по родителю
    # (read_titles отдаёт дерево обходом в глубину, поэтому родитель — последний виденный d1)
    d2, parent = [], ''
    for d, t in titles:
        if d == 1:
            parent = str(t or '')
        elif d == 2 and parent != SUMMARY:
            d2.append(t)
    if len(d0) != 1:
        bad.append(f'корней {len(d0)}, должен быть один')
    if len(d1) != expect['d1']:
        bad.append(f'глав+сводка {len(d1)}, ожидали {expect["d1"]}')
    if len(d2) != expect['d2']:
        bad.append(f'веток второго уровня {len(d2)}, ожидали {expect["d2"]}')
    if any(d > 2 for d, _ in titles):
        bad.append('есть ветки глубже второго уровня')
    for _d, t in titles:
        if '\n' in str(t or ''):
            bad.append(f'перенос строки в заголовке — ветка схлопнется: «{str(t)[:40]}…»')
        if not str(t or '').strip():
            bad.append('пустой заголовок: поле потерялось при записи')
    n_new = sum(1 for d, t in titles if d == 2 and MARK_NEW in str(t or ''))
    if n_new != expect['new']:
        bad.append(f'пометок «{MARK_NEW}» {n_new}, ожидали {expect["new"]}')
    return bad


def main():
    ap = argparse.ArgumentParser(description='карта выпуска майндкартой (.xmind)')
    ap.add_argument('--out', default='', help='куда писать (по умолчанию 05_Review/{CODE}_{cut}_structure.xmind)')
    ap.add_argument('--dump-titles', default='', help='заголовки дерева в JSON (детерминированно, для сверки)')
    a = ap.parse_args()

    sys.path.insert(0, str(HERE))
    from _bootstrap import P, W6, REVIEW_DIR                        # noqa: PLC0415
    sys.path.insert(0, str(SHARED))
    from screen_kinds_ytch import BDD_KIND                          # noqa: PLC0415
    sys.path.insert(0, str(XMIND_DIR))
    import xmind_out as XM                                          # noqa: PLC0415

    if not P.CHAPTERS:
        print('!! в карточке нет глав — карту строить не из чего')
        return 1

    def _load(name, default):
        f = W6 / name
        return json.loads(f.read_text(encoding='utf-8')) if f.exists() else default

    plan = (_load('screens_plan.json', {}) or {}).get('screens') or []
    props = (_load('screens_proposal.json', {}) or {}).get('items') or []
    spots = {s['id']: s for s in (_load('screens_spots.json', {}) or {}).get('spots') or []}

    card = {'code': P.CODE, 'cut_version': P.CUT_VERSION, 'duration_sec': P.duration_sec(),
            'film_short': str(P.get('film_subject') or P.get('project_name') or '').strip(),
            'chapters': P.CHAPTERS, 'ch_name': P.get('ch_name', {}) or {},
            'sub': P.get('sub') or [], 'sub_no_screen': P.get('sub_no_screen') or [],
            'claims': P.get('claims') or []}

    warn = []
    t, n_prop = tree(card, plan, props, spots, BDD_KIND, warn)
    out = Path(a.out).expanduser() if a.out else (Path(REVIEW_DIR) / f'{P.CODE}_{P.CUT_VERSION}_structure.xmind')
    XM.write(out, t, sheet=f'{P.CODE} · карта выпуска {P.CUT_VERSION}')

    n_ch = len(card['chapters'])
    n_sub = len(card['sub'])
    n_claim = len(card['claims'])
    on = {str(s.get('id')): bool(s.get('on_screen')) for s in plan}
    expect = {'d1': n_ch + 1, 'd2': n_sub + n_claim + n_prop,
              'new': len(set(int(x) for x in card['sub_no_screen']))
                     + sum(1 for k in range(1, n_claim + 1) if not on.get(f'claim_{k:02d}')) + n_prop}
    bad = verify(out, expect)
    for w in warn:
        print('⚠️', w)
    for b in bad:
        print('✗', b)
    if a.dump_titles:
        titles = XM.read_titles(out)
        Path(a.dump_titles).write_text(json.dumps({'schema': 'xmind-titles-v1',
                                                   'titles': [[d, t] for d, t in titles]},
                                                  ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'заголовки → {a.dump_titles}')
    print(f'глав {n_ch} · подглав {n_sub} · фраз {n_claim} · предложений {n_prop} · '
          f'пометок «{MARK_NEW}» {expect["new"]}')
    print(f'→ {out}')
    return 2 if bad else 0


def selftest():
    import tempfile                                                 # noqa: PLC0415
    sys.path.insert(0, str(XMIND_DIR))
    import xmind_out as XM                                          # noqa: PLC0415
    sys.path.insert(0, str(SHARED))
    from screen_kinds_ytch import BDD_KIND                          # noqa: PLC0415
    from screens_proposal import kinds                              # noqa: PLC0415

    # текст про виды и код витрины не должны расходиться
    ks = kinds((HERE / 'bdd_plates.py').read_text(encoding='utf-8'))
    assert set(ks) == set(BDD_KIND), (sorted(set(ks) - set(BDD_KIND)), sorted(set(BDD_KIND) - set(ks)))

    card = {'code': 'YTXX01', 'cut_version': 'v1', 'duration_sec': 300.0, 'film_short': 'проба',
            'chapters': [[0, '01'], [100, '02']], 'ch_name': {'01': 'ПЕРВАЯ', '02': 'ВТОРАЯ'},
            'sub': [[120, 2, 'Подтема раз'], [160, 2, 'Подтема два']], 'sub_no_screen': [2],
            'claims': [[40, 'раз', 'два']]}
    plan = [{'id': 'ch_01', 'on_screen': True}, {'id': 'ch_02', 'on_screen': True},
            {'id': 'claim_01', 'on_screen': False},
            {'id': 'sub_01', 'on_screen': True}, {'id': 'sub_02', 'on_screen': False}]
    props = [{'n': 1, 'ch': '01', 'sec': 60, 'role': 'new_subtopic', 'kind': 'q_sub',
              'fields': {'over': 'ГЛАВА 01', 'title': 'Новая'},
              'why': 'зачем', 'how_it_should_be': 'как надо', 'quoted': 'слова', 'fund_confirm': True,
              'fund_note': 'фонд', 'mockup': 'bdd/q_sub.png'},
             # плита к уже размеченной подглаве: своей ветки не заводит
             {'n': 2, 'ch': '02', 'sec': 160, 'role': 'plate_for_sub', 'spot': 'sub_02', 'kind': 'd_date',
              'fields': {'day': '5 марта', 'month_year': '2024', 'what': 'что', 'tc': '2:40'},
              'why': 'зачем2', 'how_it_should_be': 'как надо 2', 'quoted': None, 'fund_confirm': False,
              'fund_note': '', 'mockup': 'bdd/d_date.png'}]
    spots = {'sub_02': {'verbatim': 'что тут говорят', 'act': 2, 'act_title': 'ВТОРАЯ'}}

    warn = []
    t, n_prop = tree(card, plan, props, spots, BDD_KIND, warn)
    assert n_prop == 1 and warn == [], (n_prop, warn)
    with tempfile.TemporaryDirectory() as td:
        p = XM.write(Path(td) / 'x.xmind', t, sheet='проба')
        expect = {'d1': 3, 'd2': 2 + 1 + 1, 'new': 1 + 1 + 1}        # 2 главы + СВОДКА; подглавы+фраза+предложение
        bad = verify(p, expect)
        assert bad == [], bad
        titles = [x for _d, x in XM.read_titles(p)]
        assert any(MARK_NEW in x and 'Подтема два' in x for x in titles), titles
        assert any(MARK_OK in x and 'Подтема раз' in x for x in titles)
        # плита приросла к своей подглаве именем вида, а не встала второй веткой
        assert sum(1 for x in titles if 'Подтема два' in x) == 1, titles
        assert any('Подтема два' in x and 'дата' in x for x in titles), titles
        assert any('❝ раз два' in x and MARK_NEW in x for x in titles)
        assert not any('q_sub' in x for x in titles), 'машинное имя вида в заголовке — сработает жаргонный гейт'
        assert any('плашка подтемы' in x for x in titles)
        assert max(d for d, _ in XM.read_titles(p)) == 2

        # расхождение группировки по ch и по времени обязано быть слышно
        w2 = []
        bad_card = dict(card, sub=[[40, 2, 'Не в свою главу']], sub_no_screen=[])
        tree(bad_card, plan, [], {}, BDD_KIND, w2)
        assert w2 and 'покажут разное' in w2[0], w2

        # перенос строки в заголовке ловится, а не уезжает в карту
        p2 = XM.write(Path(td) / 'y.xmind', ('корень', [{'title': 'две\nстроки', 'children': []}]))
        assert any('перенос строки' in b for b in verify(p2, {'d1': 1, 'd2': 0, 'new': 0}))
    print('SELFTEST OK structure_xmind')
    return 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
