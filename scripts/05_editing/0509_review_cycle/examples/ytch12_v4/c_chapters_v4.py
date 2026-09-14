#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Канонический список ЗРИТЕЛЬСКИХ глав v4 (один источник для дока, листа, таймлайна и мокапов):
structure_v4.json → final.asis.chapters (+ исправления проверяющего якорей ver.checks) →
  viewer_chapters.json  — [{no, sec, title, subtitle, anchor, purpose, img, subchapters}]
  chapters_cards.json   — формат навигатора/part/notes: [{tc_sec, name «Гл.NN ТИТУЛ», act, color, comment, duration_sec}]
Если первая карточка стоит после тизера — глава «ТИЗЕР» с 0:00 (как «Гл.1 Тизер» в YTCH11), без мокапа.
Время карточек — на сетке 25p.
"""
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
TOTAL = 3045.48


def sec(t):
    m = re.findall(r'\d+(?:\.\d+)?', str(t or ''))
    p = [float(x) for x in m[:3]]
    if not p:
        return None
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else (p[0] * 60 + p[1] if len(p) == 2 else p[0])


def grid(s):
    return round(round(s * 25) / 25, 2)


def main():
    st = json.load(open(os.path.join(WORK, 'structure_v4.json'), encoding='utf-8'))
    fin, ver = st['final'], st.get('ver') or {}
    fix = {(c['part'], c['n']): c for c in (ver.get('checks') or []) if not c.get('ok') and c.get('v4_tc')}
    out = []
    for i, c in enumerate(fin['asis']['chapters'], 1):
        f = fix.get(('asis', c['n']))
        tcv = f['v4_tc'] if f else c['v4_tc']
        out.append({'no': 0, 'sec': grid(sec(tcv) or 0), 'title': c['title'].upper(), 'subtitle': c.get('subtitle') or '',
                    'anchor': (f.get('anchor') if f and f.get('anchor') else c.get('anchor')) or '',
                    'purpose': c.get('purpose') or '', 'img': f'card_{i:02d}.png', 'subchapters': c.get('subchapters') or []})
    out.sort(key=lambda x: x['sec'])
    if out and out[0]['sec'] > 1.0:
        out.insert(0, {'no': 0, 'sec': 0.0, 'title': 'ТИЗЕР', 'subtitle': '', 'anchor': '', 'img': None,
                       'purpose': 'холодный вход (карточки нет)', 'subchapters': []})
    out[0]['sec'] = 0.0
    for i, c in enumerate(out, 1):
        c['no'] = i
    json.dump(out, open(os.path.join(WORK, 'viewer_chapters.json'), 'w'), ensure_ascii=False, indent=1)
    cards = []
    for i, c in enumerate(out):
        nxt = out[i + 1]['sec'] if i + 1 < len(out) else TOTAL
        cards.append({'tc_sec': c['sec'], 'name': f'Гл.{c["no"]:02d} {c["title"]}', 'act': c['no'],
                      'color': 'Green', 'comment': '', 'duration_sec': round(nxt - c['sec'], 2)})
    json.dump(cards, open(os.path.join(WORK, 'chapters_cards.json'), 'w'), ensure_ascii=False, indent=1)
    for c in cards:
        t = int(c['tc_sec'])
        print(f'{t // 60}:{t % 60:02d} ({c["duration_sec"] / 60:.1f}m) {c["name"]}')
    print('viewer chapters:', len(out))


if __name__ == '__main__':
    main()
