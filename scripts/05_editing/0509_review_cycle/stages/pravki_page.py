#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Страница сверки: заметка Романа → кадр ката → предложенный экран.

Зачем. Заметки Романа живут во вкладке дока, предложения экранов — в JSON, а сами плиты —
в `mockups/bdd/plan/`. Пока они врозь, решать нечего: чтобы сказать «да» или «нет», надо
видеть все три вещи рядом и на одной секунде. Страница их и сводит — один самодостаточный
HTML, который открывается с диска и никуда не ходит.

Что читает (ничего не считает заново):
  work/{cut}/notes_roman.json     заметки из вкладки (`stages/doc_notes_read.py`)
  work/{cut}/screens_proposal.json предложения (`stages/screens_proposal.py check`)
  mockups/bdd/plan/NN_kind.png    отрисованные плиты (`stages/bdd_plates.py plan`)
  work/{cut}/hires/hNNNN.jpg      кадр ката на секунде
  карточка                        главы, имена, что переименовали (`ch_state`, `new_ch`)

⚠️ Кадры этого фильма на портал не выкладываются (в кадре ребёнок): страница остаётся
локальным файлом и уходит только Роману.

    python3 stages/pravki_page.py
    python3 stages/pravki_page.py --out ~/Desktop/pravki.html --budget 6

exit: 0 — ок · 1 — нет входов · 2 — часть картинок не влезла или не нашлась
"""
import argparse
import datetime
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = 'v1'

CSS = """
:root{--ink:#17171a;--dim:#6b6b73;--line:#e3e3e8;--bg:#fbfbfc;--card:#fff;
      --red:#EC1F26;--coral:#F37769;--ok:#2e7d32}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:30px;line-height:1.2;margin:0 0 6px}
.lede{color:var(--dim);margin:0 0 26px;max-width:70ch}
.tally{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 30px}
.pill{background:var(--card);border:1px solid var(--line);border-radius:999px;
      padding:6px 14px;font-size:14px}
.pill b{font-weight:700}
h2{font-size:13px;letter-spacing:.09em;text-transform:uppercase;color:var(--dim);
   margin:38px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.row{background:var(--card);border:1px solid var(--line);border-radius:14px;
     padding:18px;margin:0 0 16px;display:grid;grid-template-columns:96px 1fr 1fr;gap:18px}
.tc{font-weight:700;font-size:19px}
.tc small{display:block;font-weight:400;font-size:12px;color:var(--dim);margin-top:3px}
.said{color:var(--dim);font-size:14px;margin-top:8px;font-style:italic}
.note{border-left:3px solid var(--coral);padding-left:12px;margin:0 0 10px;white-space:pre-wrap}
.do{border-left:3px solid var(--ok);padding-left:12px;margin:10px 0 0;white-space:pre-wrap}
.warn{border-left:3px solid var(--red);padding-left:12px;margin:10px 0 0;font-size:14px}
.pics{display:grid;grid-template-columns:1fr 1fr;gap:10px;grid-column:2/4}
.pic figcaption{font-size:12px;color:var(--dim);margin-top:5px}
img{width:100%;height:auto;display:block;border-radius:8px;border:1px solid var(--line)}
.nopic{background:#f2f2f4;border:1px dashed var(--line);border-radius:8px;padding:26px 12px;
       text-align:center;color:var(--dim);font-size:13px}
.kind{display:inline-block;font-size:12px;color:var(--dim);border:1px solid var(--line);
      border-radius:999px;padding:2px 9px;margin-right:6px}
.ch{display:grid;grid-template-columns:52px 1fr 1fr;gap:16px;background:var(--card);
    border:1px solid var(--line);border-radius:14px;padding:14px 18px;margin:0 0 10px}
.was{color:var(--dim);text-decoration:line-through}
.now{font-weight:700}
.new{color:var(--red);font-weight:700}
code{background:#f2f2f4;border-radius:5px;padding:1px 6px;font-size:13px}
.foot{color:var(--dim);font-size:13px;margin-top:40px;border-top:1px solid var(--line);padding-top:14px}
@media(max-width:900px){.row,.ch{grid-template-columns:1fr}.pics{grid-column:auto}}
"""


def esc(s):
    return html.escape(str(s or ''))


def build(notes, props, card, pic, frame_for, plate_for):
    """→ html. pic(path, подпись) → кусок разметки; frame_for/plate_for — где искать картинки."""
    by_sec = {}
    for p in props:
        by_sec.setdefault(int(float(p.get('sec', -1))), []).append(p)
    used = set()
    chap = [(int(t), str(n)) for t, n in (card.get('chapters') or [])]
    names = card.get('ch_name') or {}
    state = card.get('ch_state') or {}
    new_ch = {str(x) for x in (card.get('new_ch') or [])}

    out = []
    # ── главы ──
    out.append('<h2>Главы — что переименовали и что создаём</h2>')
    for sec, no in chap:
        st = list(state.get(no) or ['', ''])
        if not st[0] and no not in new_ch:
            continue                                   # глава не менялась — молчим
        cls = 'new' if no in new_ch else 'now'
        out.append(f'<div class="ch"><div class="tc">{esc(tcf(sec))}</div>'
                   f'<div><span class="{cls}">{esc(names.get(no, ""))}</span>'
                   f'<div class="said">{esc(st[0])}</div></div>'
                   f'<div class="do">{esc(st[1] if len(st) > 1 else "")}</div></div>')

    # ── заметки ──
    out.append('<h2>Твои заметки — и что предлагаю на каждую</h2>')
    for nt in notes:
        sec = nt.get('sec')
        mine = []
        if sec is not None:
            for s in range(int(sec) - 30, int(sec) + 31):
                for p in by_sec.get(s, []):
                    if p['n'] not in used:
                        mine.append(p)
                        used.add(p['n'])
        tc_txt = esc(nt.get('tc') or '—')
        ch = nt.get('ch')
        out.append('<div class="row">')
        out.append(f'<div class="tc">{tc_txt}<small>{esc("глава " + ch if ch else "по фильму")}</small></div>')
        body = [f'<div class="note">{esc(nt.get("note") or "—")}</div>']
        if nt.get('aside'):
            body.append(f'<div class="said">{esc(nt["aside"])}</div>')
        if nt.get('said'):
            body.append(f'<div class="said">в кате: {esc(nt["said"][:260])}</div>')
        for p in mine:
            body.append(f'<div class="do"><span class="kind">{esc(p.get("kind"))}</span>'
                        f'{esc(p.get("how_it_should_be"))}</div>')
            if p.get('fund_confirm'):
                body.append(f'<div class="warn">⚠️ {esc(p.get("fund_note"))}</div>')
        if not mine:
            body.append('<div class="said">экрана не предлагаю — это правка монтажа, '
                        'она уйдёт строкой в ТЗ</div>')
        out.append('<div>' + ''.join(body) + '</div>')
        pics = []
        if sec is not None:
            pics.append(pic(frame_for(int(sec)), f'кадр ката {tc_txt}'))
        for p in mine:
            pics.append(pic(plate_for(p), f'{p.get("kind")} · {p.get("tc")}'))
        out.append('<div class="pics">' + ''.join(pics) + '</div>' if pics else '<div></div>')
        out.append('</div>')

    # ── предложения, не привязанные ни к одной заметке ──
    rest = [p for p in props if p['n'] not in used]
    if rest:
        out.append(f'<h2>Ещё {len(rest)} экранов — из разбора, не из твоих заметок</h2>')
        for p in rest:
            out.append('<div class="row">')
            out.append(f'<div class="tc">{esc(p.get("tc"))}<small>глава {esc(p.get("ch"))}</small></div>')
            b = [f'<div class="do"><span class="kind">{esc(p.get("kind"))}</span>'
                 f'{esc(p.get("how_it_should_be"))}</div>',
                 f'<div class="said">{esc(p.get("why"))}</div>']
            if p.get('quoted'):
                b.append(f'<div class="said">в кате: «{esc(p["quoted"])}»</div>')
            if p.get('fund_confirm'):
                b.append(f'<div class="warn">⚠️ {esc(p.get("fund_note"))}</div>')
            out.append('<div>' + ''.join(b) + '</div>')
            out.append('<div class="pics">' + pic(plate_for(p), f'{p.get("kind")}') + '</div>')
            out.append('</div>')
    return '\n'.join(out)


def tcf(sec):
    m, s = divmod(int(sec), 60)
    return f'{m}:{s:02d}'


def main():
    ap = argparse.ArgumentParser(description='страница сверки: заметка → кадр → экран')
    ap.add_argument('--out', default='', help='куда писать (по умолчанию 05_Review/{CODE}_{cut}_pravki.html)')
    ap.add_argument('--budget', type=float, default=6.0, help='потолок файла, МБ')
    a = ap.parse_args()

    sys.path.insert(0, str(HERE))
    from _bootstrap import P, W6, REVIEW_DIR                       # noqa: PLC0415
    sys.path.insert(0, str(HERE.parent / 'shared'))
    from screens_page import img                                   # noqa: PLC0415

    def _load(name):
        f = W6 / name
        return json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}

    notes = (_load('notes_roman.json') or {}).get('notes') or []
    props = (_load('screens_proposal.json') or {}).get('items') or []
    if not notes and not props:
        print('!! нет ни заметок, ни предложений — собери их сначала')
        return 1
    card = json.loads(Path(P.CARD_PATH).read_text(encoding='utf-8'))

    budget = {'left': int(a.budget * 1024 * 1024), 'put': 0, 'skipped': 0, 'missing': []}
    plan_dir = Path(P.MOCK) / 'bdd' / 'plan'

    def pic(path, cap):
        tag, _ = img(path, 760, 72, budget)
        return f'<figure class="pic">{tag}<figcaption>{esc(cap)}</figcaption></figure>'

    def frame_for(sec):
        return W6 / 'hires' / f'h{int(sec) + 1:04d}.jpg'

    def plate_for(p):
        return plan_dir / f'{int(p["n"]):02d}_{p["kind"]}.png'      # так их назвал bdd_plates.py plan

    stamp = datetime.datetime.now().strftime('%d.%m.%Y, %H:%M')
    fund = sum(1 for p in props if p.get('fund_confirm'))
    head = (f'<h1>Правки Романа по кату {P.CUT_VERSION} — и что предлагаю</h1>'
            f'<p class="lede">Слева твоя заметка из дока, справа — кадр этой секунды и '
            f'плита, которую предлагаю поставить. Плиты нарисованы на языке брендбука фонда '
            f'и на своих кадрах: это макет к решению, а не готовая графика.</p>'
            f'<div class="tally">'
            f'<span class="pill">заметок <b>{len(notes)}</b></span>'
            f'<span class="pill">экранов предлагаю <b>{len(props)}</b></span>'
            f'<span class="pill">глав <b>{len(card.get("chapters") or [])}</b></span>'
            f'<span class="pill">создать заставок <b>{len(card.get("new_ch") or [])}</b></span>'
            f'<span class="pill">ждут фонда <b>{fund}</b></span></div>')
    body = build(notes, props, card, pic, frame_for, plate_for)
    foot = (f'<div class="foot">{P.CODE} · кат {P.CUT_VERSION} · страница {VERSION} · '
            f'собрана {stamp} · картинок {budget["put"]}'
            + (f' · не влезло {budget["skipped"]}' if budget['skipped'] else '')
            + (f' · нет файла: {len(budget["missing"])}' if budget['missing'] else '')
            + '<br>Кадры этого фильма на портал не выкладываются.</div>')
    icon = ('data:image/svg+xml,'
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
            '<text y="26" font-size="26">📝</text></svg>')
    doc = (f'<!doctype html><html lang="ru"><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{esc(P.CODE)} · правки {esc(P.CUT_VERSION)}</title>'
           f'<link rel="icon" href="{icon}"><style>{CSS}</style>'
           f'<body><div class="wrap">{head}{body}{foot}</div></body></html>')

    out = Path(a.out).expanduser() if a.out else (Path(REVIEW_DIR) / f'{P.CODE}_{P.CUT_VERSION}_pravki.html')
    out.write_text(doc, encoding='utf-8')
    kb = len(doc.encode('utf-8')) // 1024
    print(f'заметок {len(notes)} · экранов {len(props)} · картинок {budget["put"]} · {kb} КБ')
    if budget['missing']:
        print(f'⚠️ нет файлов ({len(budget["missing"])}): {", ".join(sorted(set(budget["missing"]))[:6])}')
    if budget['skipped']:
        print(f'⚠️ не влезло в {a.budget} МБ: {budget["skipped"]}')
    print(f'→ {out}')
    return 2 if (budget['missing'] or budget['skipped']) else 0


def selftest():
    notes = [{'n': 1, 'sec': 100, 'tc': '1:40', 'note': 'крупнее', 'ch': '02', 'aside': '', 'said': 'речь'},
             {'n': 2, 'sec': None, 'tc': '', 'note': 'по фильму', 'aside': ''}]
    props = [{'n': 5, 'sec': 105, 'tc': '1:45', 'ch': '02', 'kind': 'q_sub',
              'how_it_should_be': 'поставить', 'why': 'зачем', 'quoted': 'слова',
              'fund_confirm': True, 'fund_note': 'фонд'},
             {'n': 6, 'sec': 900, 'tc': '15:00', 'ch': '05', 'kind': 'q_money',
              'how_it_should_be': 'сумма', 'why': 'зачем2', 'fund_confirm': False}]
    card = {'chapters': [[0, '01'], [76, '02']], 'ch_name': {'01': 'А', '02': 'Б'},
            'ch_state': {'02': ['было', 'стало']}, 'new_ch': ['02']}
    seen = []
    html_ = build(notes, props, card, lambda p, c: f'<i>{c}</i>', lambda s: f'f{s}',
                  lambda p: seen.append(p['n']) or f'p{p["n"]}')
    assert 'крупнее' in html_ and 'по фильму' in html_
    assert 'поставить' in html_ and '⚠️ фонд' in html_
    # предложение в ±30 с прилипло к заметке, дальнее ушло в свой раздел
    assert html_.index('поставить') < html_.index('Ещё 1 экранов'), 'близкое предложение не прилипло'
    assert 'сумма' in html_.split('Ещё 1 экранов')[1]
    assert seen == [5, 6], seen                       # каждая плита запрошена ровно раз
    assert 'было' in html_ and 'стало' in html_       # переименование главы показано
    assert tcf(105) == '1:45'
    print('SELFTEST OK pravki_page')
    return 0


if __name__ == '__main__':
    sys.exit(selftest() if '--selftest' in sys.argv else main())
