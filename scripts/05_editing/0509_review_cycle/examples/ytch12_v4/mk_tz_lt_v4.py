#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Плашки ТЗ для слоя V4 ревью-таймлайна (канон KB review-timeline / скилл infographic, правило 5):
прозрачный PNG 3840×2160, тёмная плашка снизу (~28% высоты, скругление 24px, rgba(10,10,12,.88)),
слева цветной корешок по категории, номер ТЗ крупно, заголовок + первое действие ✅, таймкод.
Источник — pravki_v4.json (активные ТЗ с таймкодом; номера = док/лист/маркеры).
Выход: 00_Setup/05_Review/mockups/tz/tz_NN.png + v4_review/tz_index.json {ТЗ-NN: path}.
"""
import html
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

WORK = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(WORK), 'mockups', 'tz')
SRC = os.path.join(OUT, 'src')
RENDER = os.path.expanduser('~/YTAI/scripts/999_extra/infographic/render.py')
E = html.escape
FONT = "'PT Sans Narrow','Avenir Next Condensed','Arial Narrow',sans-serif"
SPINE = {'cut': '#d9534f', 'insert': '#3c9d5d', 'graphics': '#e0b030', 'structure': '#e07b2a',
         'color': '#4a7fd0', 'fund': '#f08c1a', 'check': '#9a9a9a'}
LABEL = {'cut': '✂️ СЖАТЬ / РЕЗАТЬ', 'insert': '➕ ВСТАВИТЬ', 'graphics': '🎨 ГРАФИКА', 'structure': '🧭 СТРУКТУРА',
         'color': '🎛 ТЕХНИКА', 'fund': '⚠️ ФОНД · БЛЮР / СОГЛАСИЕ', 'check': '🔍 ПРОВЕРИТЬ'}
SEV = {'must': 'ОБЯЗАТЕЛЬНО', 'should': 'ЖЕЛАТЕЛЬНО', 'nice': 'ПОЛИРОВКА'}


def first_do(nado):
    for ln in nado.split('\n'):
        if ln.startswith('✅ СДЕЛАТЬ'):
            return ln.split('·', 1)[1].strip()
    return ''


def cut(t, n):
    t = re.sub(r'\s+', ' ', t).strip()
    return t if len(t) <= n else t[:n - 1].rsplit(' ', 1)[0] + '…'


def lt_html(p):
    col = SPINE.get(p['category'], '#9a9a9a')
    return ('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;width:3840px;height:2160px;'
            'background:transparent;overflow:hidden}</style><body>'
            '<div style="position:absolute;left:180px;right:180px;bottom:150px;min-height:380px;border-radius:24px;'
            'background:rgba(10,10,12,.88);display:flex;overflow:hidden">'
            f'<div style="width:34px;background:{col}"></div>'
            '<div style="flex:1;padding:44px 64px 40px 60px;display:flex;flex-direction:column;gap:18px">'
            '<div style="display:flex;align-items:baseline;gap:40px">'
            f'<span style="font:700 116px/1 {FONT};color:{col}">{E(p["num"])}</span>'
            f'<span style="font:600 50px/1 Inter,Helvetica,sans-serif;color:#cfcfcf">{E(LABEL.get(p["category"], ""))} · '
            f'{E(SEV.get(p.get("severity"), ""))}</span>'
            f'<span style="margin-left:auto;font:500 50px/1 Menlo,monospace;color:#9a9a9a">⏱ {E(p.get("tc_range") or "")}</span></div>'
            f'<div style="font:700 78px/1.12 {FONT};color:#fff">{E(cut(p["title"], 90))}</div>'
            f'<div style="font:500 56px/1.25 Inter,Helvetica,sans-serif;color:#e8e8e8">✅ {E(cut(first_do(p["nado"]), 170))}</div>'
            '</div></div>'
            '<div style="position:absolute;right:200px;bottom:84px;font:600 32px Inter,sans-serif;color:rgba(255,255,255,.45)">'
            'DRAFT · плашка ТЗ ревью</div></body>')


def render(p):
    name = 'tz_' + p['num'].split('-')[1]
    hp, out = os.path.join(SRC, name + '.html'), os.path.join(OUT, name + '.png')
    open(hp, 'w', encoding='utf-8').write(lt_html(p))
    r = subprocess.run(['python3', RENDER, hp, out, '--alpha'], capture_output=True, text=True, timeout=180)
    return p['num'], (out if r.returncode == 0 and os.path.exists(out) else None)


def main():
    os.makedirs(SRC, exist_ok=True)
    pr = json.load(open(os.path.join(WORK, 'pravki_v4.json'), encoding='utf-8'))['all']
    for i, p in enumerate(pr):
        p['num'] = f'ТЗ-{i + 1:02d}'
    act = [p for p in pr if p.get('status') != 'rejected' and p.get('v1_tc')]
    with ThreadPoolExecutor(4) as ex:
        res = dict(ex.map(render, act))
    json.dump({k: v for k, v in res.items() if v}, open(os.path.join(WORK, 'tz_index.json'), 'w'), ensure_ascii=False, indent=1)
    bad = [k for k, v in res.items() if not v]
    print(f'плашек ТЗ: {len(res) - len(bad)}/{len(act)}' + (f' · сбой: {bad}' if bad else ''))


if __name__ == '__main__':
    main()
