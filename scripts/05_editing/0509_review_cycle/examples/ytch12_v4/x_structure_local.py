#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальный выбор и проверка структуры (судьи не отработали: session limit).
structure_raw.json → берём предложение P1 «как есть» (порядок ката не меняется, только графика) как
рабочее, P2 «по монтажному листу» — как вариант TO-BE для решения Романа.
Якоря и таймкоды карточек проверяются ЛОКАЛЬНО по YTCH12_v4.words.json и склейкам qc.json:
  · якорь должен встречаться дословно и начинаться в пределах −2…+8 с от таймкода карточки;
  · карточка не должна рвать фразу: перед якорем пауза ≥0,3 с ИЛИ склейка в ±0,6 с;
  · при промахе таймкод исправляется на (начало якоря − 0,4 с), с пометкой в ver.checks.
Выход: structure_v4.json {final, ver} — вход для c_chapters_v4.py / p_pravki_v4.py / mk_cards_v4.py.
"""
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
REV = os.path.dirname(WORK)


def norm(w):
    return re.sub(r'[^а-яa-z0-9]', '', w.lower().replace('ё', 'е'))


def sec(t):
    m = re.search(r'(\d{1,2}):(\d{2})(?:[.,](\d+))?', str(t or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) + (float('0.' + m.group(3)) if m and m.group(3) else 0) if m else None


def tcs(s):
    return f'{int(s) // 60}:{int(s) % 60:02d}' + (f'.{int(round((s % 1) * 10))}' if abs(s % 1) > 0.05 else '')


def main():
    raw = json.load(open(os.path.join(WORK, 'structure_raw.json'), encoding='utf-8'))
    props = {p['key']: p for p in raw['proposals']}
    p1, p2 = props['P1'], props.get('P2') or props.get('P3') or {}
    words = json.load(open(f'{REV}/YTCH12_v4.words.json', encoding='utf-8'))
    W = [(norm(w['w']), float(w['s']), float(w['e'])) for s in words['segments'] for w in s['words'] if norm(w['w'])]
    cuts = json.load(open(os.path.join(WORK, 'qc.json'), encoding='utf-8'))['cuts']

    def find_anchor(anchor, near=None):
        """→ (start, end) первого дословного вхождения (ближайшего к near), иначе None."""
        a = [norm(x) for x in re.findall(r'\w+', anchor) if norm(x)][:8]
        if len(a) < 2:
            return None
        hits = [i for i in range(len(W) - len(a) + 1) if [W[i + k][0] for k in range(len(a))] == a]
        if not hits:
            for n in range(len(a) - 1, 1, -1):             # укорачиваем якорь
                a2 = a[:n]
                hits = [i for i in range(len(W) - n + 1) if [W[i + k][0] for k in range(n)] == a2]
                if hits:
                    a = a2
                    break
        if not hits:
            return None
        i = min(hits, key=lambda i: abs(W[i][1] - near)) if near is not None else hits[0]
        return W[i][1], W[i + len(a) - 1][2]

    def gap_before(t):
        prev = [w for w in W if w[2] <= t + 0.01]
        return (t - prev[-1][2]) if prev else 99.0

    checks, chapters = [], []
    for i, c in enumerate(p1['chapters'], 1):
        t0 = sec(c['v4_tc'])
        pos = find_anchor(c.get('anchor', ''), t0)
        note, ok = '', True
        if pos is None:
            note, ok = 'якорь не найден дословно — таймкод оставлен как предложено', False
        else:
            a0 = pos[0]
            if t0 is None or not (-2.0 <= a0 - t0 <= 8.0):
                note, ok = f'якорь начинается на {tcs(a0)} — таймкод исправлен', False
                t0 = round(max(0.0, a0 - 0.4), 2)
            g = gap_before(a0)
            near_cut = any(abs(a0 - x) < 1.2 or abs(t0 - x) < 0.6 for x in cuts)
            if g < 0.3 and not near_cut:
                note = (note + '; ' if note else '') + f'пауза перед якорем {g:.2f} с — карточка режет фразу, ставить вставкой'
                ok = False
        chapters.append({'n': i, 'title': c['title'], 'subtitle': c.get('subtitle') or '', 'v4_tc': tcs(t0 or 0),
                         'anchor': c.get('anchor', ''), 'end_tc': c.get('end_tc', ''), 'minutes': c.get('minutes', 0),
                         'purpose': c.get('purpose', ''), 'content': c.get('content', ''),
                         'subchapters': c.get('subchapters') or []})
        checks.append({'part': 'asis', 'n': i, 'ok': ok, 'v4_tc': tcs(t0 or 0), 'anchor': c.get('anchor', ''), 'note': note})

    tt = sec(p1.get('title_card_tc'))
    ttl_anchor = 'Детство, что я помню'
    checks.append({'part': 'title', 'n': 0, 'ok': tt is not None, 'v4_tc': tcs(tt or 69.9), 'anchor': ttl_anchor,
                   'note': 'титул на существующее затемнение 1:09,9–1:12,7 (продлить до 4 с)'})

    yt = p1.get('youtube_chapters') or []
    yt_ok = bool(yt) and sec(yt[0]['time']) == 0 and all(sec(yt[k + 1]['time']) - sec(yt[k]['time']) >= 10 for k in range(len(yt) - 1))
    final = {
        'recommendation': 'Сейчас — вариант «как есть» (P1): порядок ката не трогаем, ставим титул, 13 карточек глав, '
                          '17 плашек-подглав и подписи. Это +40 с и один день работы, зато зритель сразу понимает, где он '
                          'в истории. Перестановку по монтажному листу (P2: квартира-хребет с первых минут, фонд позже, '
                          'её слово в финале) выносим отдельным решением — см. ТЗ «Структура v5 (TO-BE)».',
        'film_title': re.sub(r'[\s/]*фильм\s*$', '', str(p1.get('film_title', 'ОДНА С РЕБЁНКОМ')).replace(' / ', ' '),
                             flags=re.I).strip(' /'),
        'title_card_tc': tcs(tt if tt is not None else 69.9), 'title_card_anchor': ttl_anchor,
        'asis': {'chapters': chapters, 'youtube_chapters': yt,
                 'notes': (p1.get('approach', '') + ' · ' + p1.get('effort', ''))[:900]},
        'tobe': {'chapters': p2.get('chapters') or [], 'moves': p2.get('moves') or [],
                 'youtube_chapters': p2.get('youtube_chapters') or [],
                 'time_math': p2.get('effort', ''), 'notes': (p2.get('approach') or '')[:900]},
        'why': 'Судейская панель не отработала (лимит сессии), выбор сделан по критерию «минимум работы монтажёру при '
               'максимуме пользы зрителю»: P1 не требует перемонтажа и совместим с любыми правками из ревью, '
               'а P2 остаётся на столе как целевая структура v5.',
    }
    json.dump({'final': final, 'ver': {'checks': checks, 'youtube_ok': yt_ok, 'youtube_fixes': ''}},
              open(os.path.join(WORK, 'structure_v4.json'), 'w'), ensure_ascii=False, indent=1)
    bad = [c for c in checks if not c['ok']]
    print(f'структура P1: глав {len(chapters)} · подглав {sum(len(c["subchapters"]) for c in chapters)} · '
          f'YouTube-глав {len(yt)} (порядок {"ок" if yt_ok else "проверить"}) · TO-BE из {p2.get("key", "—")}: '
          f'{len(final["tobe"]["chapters"])} глав, {len(final["tobe"]["moves"])} перестановок')
    for c in bad:
        print(f'  ⚠️ {c["part"]}{c["n"]}: {c["note"]} → {c["v4_tc"]}')


if __name__ == '__main__':
    main()
