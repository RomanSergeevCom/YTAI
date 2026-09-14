#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мокапы графики YTCH12 v4 в стиле канала (эталон — карточки YTCH11 того же монтажёра):
чёрный полный кадр, белый узкий гротеск КАПСОМ по центру, слова столбиком.
  card_NN.png      — карточки зрительских глав (из structure_v4.json → final.asis.chapters)
  card_title.png   — титул «… / фильм» (final.film_title)
  lt_gulya.png     — подпись Гули (прозрачный PNG, нижняя треть)
  structure_map.png — карта структуры одним кадром: шкала 0–50:45 + список глав и подглав
Все PNG 3840×2160 с бейджем «DRAFT · перерисовать в стиле канала».
Выход: 00_Setup/05_Review/mockups/ (+ src/*.html). Рендер: infographic/render.py (chrome-headless-shell).
Usage: mk_cards_v4.py [--test]
"""
import html
import json
import os
import subprocess
import sys

WORK = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(WORK), 'mockups')
SRC = os.path.join(OUT, 'src')
RENDER = os.path.expanduser('~/YTAI/scripts/999_extra/infographic/render.py')
TOTAL = 3045.48
E = html.escape
FONT = "'PT Sans Narrow','Avenir Next Condensed','Arial Narrow',sans-serif"
BADGE = ('<div style="position:absolute;right:64px;bottom:52px;font:600 34px Inter,Helvetica,sans-serif;'
         'color:rgba(255,255,255,.38);letter-spacing:.02em">DRAFT · перерисовать в стиле канала</div>')
GULYA = ('Жимагул Панфилова', 'куратор по семьям · фонд «Бюро Добрых Дел»')


def tc(s):
    s = int(s)
    return f'{s // 60}:{s % 60:02d}'


def sec(t):
    p = [float(x) for x in str(t).replace(',', '.').split(':')]
    return p[0] * 60 + p[1] if len(p) == 2 else (p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0])


def lines_of(title):
    """1–4 слова → строки столбиком как в YTCH11; длинные титры — по 1–2 слова в строке."""
    w = title.upper().split()
    if len(w) <= 4:
        return w
    out, cur = [], []
    for x in w:
        cur.append(x)
        if len(' '.join(cur)) >= 11:
            out.append(' '.join(cur))
            cur = []
    if cur:
        out.append(' '.join(cur))
    return out


def page(body, bg='#000'):
    return (f'<!doctype html><meta charset="utf-8"><style>html,body{{margin:0;width:3840px;height:2160px;'
            f'background:{bg};overflow:hidden}}</style><body>{body}{BADGE}</body>')


def card_html(title, subtitle=''):
    ls = lines_of(title)
    size = 300 if len(ls) <= 3 else 250
    rows = ''.join(f'<div>{E(x)}</div>' for x in ls)
    sub = (f'<div style="margin-top:70px;font:700 120px/1 {FONT};text-transform:none">{E(subtitle)}</div>'
           if subtitle else '')
    return page(f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;'
                f'justify-content:center;color:#fff;font:700 {size}px/1.16 {FONT};text-align:center;'
                f'letter-spacing:.01em">{rows}{sub}</div>')


def lt_html(name, role):
    return ('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;width:3840px;height:2160px;'
            'background:transparent;overflow:hidden}</style><body>'
            '<div style="position:absolute;left:0;bottom:250px;width:2200px;padding:44px 0 50px 220px;'
            'background:linear-gradient(90deg,rgba(0,0,0,.78) 0%,rgba(0,0,0,.62) 55%,rgba(0,0,0,0) 100%)">'
            f'<div style="font:700 128px/1.05 {FONT};color:#fff;text-transform:uppercase;letter-spacing:.01em">{E(name)}</div>'
            f'<div style="margin-top:18px;font:500 62px/1.2 Inter,Helvetica,sans-serif;color:#e6e6e6">{E(role)}</div></div>'
            + BADGE + '</body>')


def map_html(chs, film_title, total=TOTAL):
    cols = ['#3f7f5b', '#4f6fa8', '#8a5fa6', '#b07a3a', '#3f8a8f', '#a4525a', '#6f7f3a']
    bar, lst = [], []
    for i, c in enumerate(chs):
        a = sec(c['v4_tc'])
        b = sec(chs[i + 1]['v4_tc']) if i + 1 < len(chs) else total
        left, width = 100 * a / total, 100 * (b - a) / total
        bar.append(f'<div style="position:absolute;left:{left:.3f}%;width:{width:.3f}%;top:0;bottom:0;'
                   f'background:{cols[i % len(cols)]};border-right:6px solid #000;box-sizing:border-box;'
                   f'display:flex;align-items:center;justify-content:center;font:700 54px {FONT};color:#fff">{i + 1}</div>')
        subs = ''.join(f'<div style="font:500 40px/1.35 Inter,Helvetica,sans-serif;color:#aaa;margin-left:150px">'
                       f'{E(s["tc"])} ▸ {E(s["title"])}</div>' for s in (c.get('subchapters') or []))
        lst.append(f'<div style="break-inside:avoid;margin-bottom:22px"><div style="font:700 62px/1.25 {FONT};color:#fff">'
                   f'<span style="display:inline-block;width:70px;color:{cols[i % len(cols)]}">{i + 1:02d}</span>'
                   f'<span style="display:inline-block;width:170px;color:#999;font-family:\'Roboto Mono\',Menlo,monospace;'
                   f'font-size:48px">{E(tc(sec(c["v4_tc"])))}</span>{E(c["title"].upper())}</div>{subs}</div>')
    return page('<div style="position:absolute;inset:120px 160px">'
                f'<div style="font:700 110px/1 {FONT};color:#fff;text-transform:uppercase">{E(film_title)} · структура</div>'
                f'<div style="margin-top:18px;font:500 50px Inter,Helvetica,sans-serif;color:#aaa">'
                f'{len(chs)} глав · 0:00–{tc(total)} · карточки ставятся в кат v4 без перестановок</div>'
                f'<div style="position:relative;height:120px;margin:60px 0 70px;border-radius:14px;overflow:hidden">{"".join(bar)}</div>'
                f'<div style="column-count:2;column-gap:140px">{"".join(lst)}</div></div>', bg='#0b0b0c')


def render(name, doc, alpha=False):
    os.makedirs(SRC, exist_ok=True)
    hp = os.path.join(SRC, name + '.html')
    open(hp, 'w', encoding='utf-8').write(doc)
    out = os.path.join(OUT, name + '.png')
    cmd = ['python3', RENDER, hp, out] + (['--alpha'] if alpha else [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    ok = r.returncode == 0 and os.path.exists(out)
    print(('OK  ' if ok else 'FAIL') + f' {name}.png' + ('' if ok else ' ' + (r.stderr or r.stdout)[-200:]), flush=True)
    return out if ok else None


def main():
    os.makedirs(OUT, exist_ok=True)
    if '--test' in sys.argv:
        render('test_card', card_html('ГДЕ МАМА СВЕТЫ?'))
        render('test_title', card_html('СВЕТА', 'фильм'))
        render('lt_gulya', lt_html(*GULYA), alpha=True)
        return
    st = json.load(open(os.path.join(WORK, 'structure_v4.json'), encoding='utf-8'))
    fin = st['final']
    chs = fin['asis']['chapters']
    made = {'title': render('card_title', card_html(fin['film_title'], 'фильм'))}
    for i, c in enumerate(chs, 1):
        made[f'card_{i:02d}'] = render(f'card_{i:02d}', card_html(c['title'], c.get('subtitle') or ''))
    made['lt_gulya'] = render('lt_gulya', lt_html(*GULYA), alpha=True)
    made['structure_map'] = render('structure_map', map_html(chs, fin['film_title']))
    json.dump({k: v for k, v in made.items() if v}, open(os.path.join(WORK, 'mockups_index.json'), 'w'),
              ensure_ascii=False, indent=1)
    print('mockups:', sum(1 for v in made.values() if v), '/', len(made))


if __name__ == '__main__':
    main()
