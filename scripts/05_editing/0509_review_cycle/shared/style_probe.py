#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Замер канона экранов канала по настоящему кату → ключи `style` в профиль канала.

Зачем. `make_infographics_v6.py` берёт геометрию экранов из `YTs/{CH}/review_profile.json` →
`style`, а чего в профиле нет — из литералов в своей шапке. Литералы — это канон YTUVI
(поля 148, шов на 1500, черта 570×10, плашка #141110). У канала без этих ключей макеты молча
рисуются чужим каноном: у YTCH заставки глав центрованные и без черты, а рисовались бы
левыми со швом. Эта проба меряет канон по экранам самого ката и предлагает ключи.

Что меряем и по чему:
  margin_px  — левое поле: минимальный x строк ЛЕВОВЫРОВНЕННЫХ экранов (подпись человека,
               плашка сбора). Центрованные заставки глав в этот замер не берём — у них
               отступ задан центровкой, а не полем.
  rule       — черта канала: ищем в кадре горизонтальную полосу акцентного цвета (`style.red`).
               Не нашли ни на одном экране — у канала черты нет, и это пишем прямо.
  plate      — цвет плашки: медиана тёмной заливки под текстом левовыровненного экрана.
  title_*    — как набраны заставки глав: центр или левый край, высота прописной, ширина блока.
               Прямо в `style` не идут (кегль считает `fit_fs`), но говорят, какой вариант
               заставки (a|b|c) ближе к канону канала, — это решение пишется в `ch_plate_variant`.

usage: style_probe.py [--apply] [--json FILE]
       без --apply ничего не пишет, только печатает предложение
exit: 0 — замерили · 1 — нет входов (screens_v6.json / кадры)
"""
import argparse
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
from _bootstrap import P, W6  # noqa: E402

FRAME_W, FRAME_H = 3840, 2160                      # канон макетов: 4K, кадры ката меньше — считаем в долях
LEFT_MAX = 0.25                                    # строка считается левовыровненной, если начинается левее


def _hex(rgb):
    return '#%02X%02X%02X' % tuple(int(round(c)) for c in rgb)


def _rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _near(px, ref, tol=46):
    return all(abs(a - b) <= tol for a, b in zip(px[:3], ref))


def load_screens():
    p = W6 / 'screens_v6.json'
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding='utf-8'))
    return d if isinstance(d, list) else (d.get('screens') or [])


def chapter_screens(scr, chapters, tol=6):
    secs = [int(s) for s, _ in (chapters or [])]
    return [s for s in scr if any(abs(int(s.get('t0', -99)) - c) <= tol for c in secs) and len(s.get('lines_best') or []) >= 2]


def left_screens(scr, chapter_ids, min_lines=2, min_dur=3):
    """экраны с левовыровненным ТЕКСТОМ ОФОРМЛЕНИЯ: подпись человека, плашка сбора — не заставки глав.

    Три условия отсекают надписи реального мира (вывески, реклама в кадре), которые OCR тоже видит:
    экран держится на монтаже (dur ≥ min_dur) · строки начинаются с одного x (это набор, а не
    случайные надписи в разных углах) · хотя бы одна строка длинная (bw ≥ 0.2)."""
    out = []
    for s in scr:
        if id(s) in chapter_ids or int(s.get('dur', 0)) < min_dur:
            continue
        L = [x for x in (s.get('lines_best') or []) if x.get('c', 0) >= 0.5 and x.get('bh', 0) >= 0.02]
        if len(L) < min_lines or min(x['x'] for x in L) > LEFT_MAX:
            continue
        x0 = min(x['x'] for x in L)
        col = [x for x in L if abs(x['x'] - x0) <= 0.01]
        if len(col) >= min_lines and max(x['bw'] for x in col) >= 0.2:
            out.append((s, col))
    return out


MAX_RULE_H = 40                                    # черта толще 40 px (в 4K) — это уже не черта, а пятно в кадре


def measure_rule(img, red, y_lo=0.0, y_hi=1.0, min_w=0.04):
    """→ (ширина px, высота px) самой заметной горизонтальной полосы акцентного цвета; None — нет.

    Красного в кадре хватает и без графики (одежда, стены), поэтому полоса засчитывается только
    если она ТОНКАЯ: иначе замер выдаёт «черту» высотой в треть экрана."""
    w, h = img.size
    px = img.convert('RGB').load()
    runs = {}                                       # y → (x0, длина)
    step = max(1, w // 480)
    for y in range(int(h * y_lo), int(h * y_hi)):
        x, best = 0, (0, 0)
        while x < w:
            if _near(px[x, y], red):
                x0 = x
                while x < w and _near(px[x, y], red):
                    x += step
                if x - x0 > best[1]:
                    best = (x0, x - x0)
            x += step
        if best[1] >= w * min_w:
            runs[y] = best
    if not runs:
        return None
    ys = sorted(runs)
    band, cur = [], [ys[0]]
    for a, b in zip(ys, ys[1:]):
        (cur.append(b) if b - a <= 2 else (band.append(cur), cur := [b]))
    band.append(cur)
    thin = [b for b in band if len(b) / h * FRAME_H <= MAX_RULE_H]
    if not thin:
        return None
    thick = max(thin, key=lambda b: st.median([runs[y][1] for y in b]))
    wpx = st.median([runs[y][1] for y in thick])
    return int(round(wpx / w * FRAME_W)), max(1, int(round(len(thick) / h * FRAME_H)))


def measure_plate(img, lines, flat=14):
    """→ цвет плашки под текстом; None — плашки нет (текст лежит прямо на кадре).

    Смотрим полосу у левого края на высоте строк: если там СПЛОШНАЯ заливка (разброс каналов
    ≤ flat), это плашка и её цвет — канон. Разброс больше — под текстом кадр, а не плашка,
    и выдумывать цвет нельзя."""
    w, h = img.size
    px = img.convert('RGB').load()
    y0 = int(min(x['y'] for x in lines) * h)
    y1 = int(min(1.0, max(x['y'] + x['bh'] for x in lines)) * h)
    pool = [px[x, y]
            for y in range(y0, max(y0 + 1, y1), max(1, (y1 - y0) // 40 or 1))
            for x in range(2, max(3, int(w * 0.03)), 2)]   # у самого края: там плашка без букв
    if len(pool) < 8:
        return None
    med = [st.median([c[i] for c in pool]) for i in range(3)]
    if max(st.pstdev([c[i] for c in pool]) for i in range(3)) > flat:
        return None
    return _hex(med)


def _mix(a, b, k):
    return _hex([x + (y - x) * k for x, y in zip(_rgb(a), _rgb(b))])


def derive(patch, rep):
    """замеренное дополняем выведенным ИЗ ПАЛИТРЫ САМОГО КАНАЛА — но не молчком.

    Часть канона по кату не меряется: канал может не использовать черту, плашку или шов вовсе.
    Оставить ключ пустым нельзя — рендер тогда возьмёт литерал из своей шапки, а это канон
    другого канала. Поэтому выводим значение из цветов и полей ЭТОГО канала и пишем, откуда оно."""
    why = {}
    bg = str(P.profile('style.bg', '#101014'))
    mut = str(P.profile('style.mut', '#CDC6B8'))
    # ⚠️ Числа «по умолчанию» здесь запрещены: 148 и 190 — это поле и кегль YTUVI, ровно тот
    # чужой канон, ради которого модуль и написан. Не замерили — ключ НЕ предлагаем и говорим
    # почему: пустой ключ видно в отчёте, а чужой выглядит своим и живёт в профиле годами.
    marg = int(patch.get('margin_px') or rep.get('margin_px') or 0)
    cap = int((rep.get('title') or {}).get('cap_px') or 0)
    if 'margin_px' in patch:
        why['margin_px'] = f'замерено по экранам ката (разброс {rep["margin_px_spread"]})'
    if not patch.get('rule'):
        if cap:
            # кегль заставок известен из замера — черта макета берётся от него, а не от чужого канала
            patch['rule'] = [int(round(cap * 2.2 / 10) * 10), max(8, int(round(cap / 17 / 2) * 2))]
            why['rule'] = (rep.get('rule_note') or 'черта не замерилась')
            why['rule'] += f'; для макетов ревью взята от кегля заставок ({cap} px прописная)'
        else:
            rep.setdefault('not_measured', []).append(
                'rule: заставок глав в кате не нашлось — считать черту не от чего')
    else:
        why['rule'] = 'замерено по экранам ката'
    if not patch.get('plate'):
        patch['plate'] = _mix(bg, '#FFFFFF', 0.04)
        why['plate'] = 'на экранах ката текст лежит прямо на кадре, плашки нет; для макетов — фон канала чуть светлее'
    else:
        why['plate'] = 'замерено по экранам ката'
    if P.profile('style.graph') is None:
        patch['graph'] = _mix(bg, mut, 0.55)
        why['graph'] = 'графит выведен из цветов канала (фон + приглушённый), а не взят у другого канала'
    if P.profile('style.split_x') is None:
        if marg:
            patch['split_x'] = int(round((FRAME_W * 0.45 - marg) / 10) * 10 + marg)
            why['split_x'] = ('канал делит кадр швом только в варианте заставки «шторка»; '
                              f'шов посчитан от поля канала ({marg} px), а не взят у другого канала')
        else:
            rep.setdefault('not_measured', []).append(
                'split_x: поле канала не замерилось — считать шов не от чего')
    return patch, why


def apply_to_profile(path, add):
    """Обновить ключи блока `style` в профиле канала, НЕ переформатируя остальной файл. → сколько ключей.

    Профиль правят руками: массивы записаны в одну строку, ключи сгруппированы по смыслу.
    `json.dump` разнёс бы каждый массив по строкам, и семь новых ключей выглядели бы как
    переписанный файл. Поэтому перерисовываем ТОЛЬКО блок `style`, по ключу на строку и с
    массивами в строку, а всё остальное оставляем байт в байт.

    Существующий ключ ЗАМЕНЯЕТСЯ, а не дописывается вторым: `_canon_note` пишется при каждом
    замере, и наивная дописка оставляла бы в файле два ключа с одним именем."""
    path = Path(path)
    src = path.read_text(encoding='utf-8')
    m = re.search(r'(^[ \t]*)"style"\s*:\s*\{', src, re.M)
    if not m:
        raise SystemExit(f'{path.name}: не нашёл блок "style" — дописывать вслепую нельзя')
    depth, i = 0, src.index('{', m.start())
    while i < len(src):                                    # конец блока style — парная скобка
        depth += (src[i] == '{') - (src[i] == '}')
        if depth == 0:
            break
        i += 1
    style = json.loads(src[src.index('{', m.start()):i + 1])
    before = dict(style)
    style.update(add)
    pad = m.group(1) + ' '
    body = ',\n'.join(f'{pad}"{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in style.items())
    out = src[:m.start()] + f'{m.group(1)}"style": {{\n{body}\n{m.group(1)}}}' + src[i + 1:]
    json.loads(out)                                        # не пишем то, что перестало быть JSON
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(out, encoding='utf-8')
    tmp.replace(path)
    return sum(1 for k, v in add.items() if before.get(k) != v)


def main():
    ap = argparse.ArgumentParser(description='замер канона экранов канала по кату')
    ap.add_argument('--apply', action='store_true', help='дописать замеренные ключи в профиль канала')
    ap.add_argument('--json', help='куда положить полный отчёт')
    a = ap.parse_args()

    from PIL import Image
    scr = load_screens()
    if not scr:
        print(f'!! нет {W6 / "screens_v6.json"} — сначала стадии frames/ocr')
        return 1
    hires = W6 / 'hires'
    red = _rgb(str(P.profile('style.red', '#C1272D')))

    ch = chapter_screens(scr, P.get('chapters') or [])
    left = left_screens(scr, {id(s) for s in ch})
    rep = {'schema': 'style-probe-v1', 'channel': P.get('channel', ''), 'code': P.CODE,
           'cut_version': P.CUT_VERSION, 'frame': [FRAME_W, FRAME_H],
           'chapter_screens': len(ch), 'left_screens': len(left)}

    # ── заставки глав: центр или левый край, высота прописной, ширина блока ──
    cen, caps, wide = [], [], []
    for s in ch:
        L = [x for x in s['lines_best'] if x.get('c', 0) >= 0.9 and x.get('bh', 0) >= 0.05]
        if not L:
            continue
        cen += [x['x'] + x['bw'] / 2 for x in L]
        caps += [x['bh'] * FRAME_H for x in L]
        wide.append(max(x['bw'] for x in L) * FRAME_W)
    if caps:
        rep['title'] = {'center_x': round(st.median(cen), 4), 'cap_px': int(st.median(caps)),
                        'block_w_px': int(max(wide)),
                        'align': 'center' if abs(st.median(cen) - 0.5) < 0.03 else 'left'}

    # ── поле: только левовыровненные экраны ──
    marg = [min(x['x'] for x in L) * FRAME_W for _s, L in left]
    if marg:
        rep['margin_px'] = int(round(st.median(marg)))
        rep['margin_px_spread'] = [int(min(marg)), int(max(marg))]

    # ── черта и плашка: по нескольким самым «оформленным» экранам ──
    rules, plates = [], []
    for s, L in sorted(left, key=lambda p: -len(p[1]))[:8]:
        f = hires / str(s.get('best_frame') or '')
        if not f.exists():
            continue
        with Image.open(f) as im:
            r = measure_rule(im, red)
            if r:
                rules.append(r)
            pl = measure_plate(im, L)
            if pl:
                plates.append(pl)
    if rules:
        rep['rule'] = [int(st.median([r[0] for r in rules])), max(1, int(st.median([r[1] for r in rules])))]
    else:
        rep['rule'] = None
        rep['rule_note'] = 'черты канала на экранах ката нет — канон канала её не использует'
    if plates:
        rep['plate'] = max(set(plates), key=plates.count)

    patch = {k: rep[k] for k in ('margin_px', 'rule', 'plate') if rep.get(k)}
    patch, why = derive(patch, rep)
    rep['proposal'], rep['why'] = patch, why
    print(f'канал {rep["channel"]} · кат {P.CUT_VERSION} · заставок глав {len(ch)} · левовыровненных экранов {len(left)}')
    if rep.get('title'):
        t = rep['title']
        print(f'  заставки глав: {t["align"]} (центр {t["center_x"]}) · прописная {t["cap_px"]} px '
              f'· самая широкая строка {t["block_w_px"]} px из {FRAME_W}')
    if marg:
        print(f'  поле: {rep["margin_px"]} px (разброс {rep["margin_px_spread"][0]}–{rep["margin_px_spread"][1]})')
    print(f'  черта: {rep["rule"] or rep.get("rule_note")}')
    print(f'  плашка: {rep.get("plate") or "не замерилась"}')
    miss = [k for k in ('margin_px', 'rule', 'plate', 'graph', 'split_x')
            if (P.profile(f'style.{k}') is None)]
    print(f'  в профиле нет ключей: {miss or "—"}')

    if a.json:
        Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    for miss in rep.get('not_measured', []):
        print(f'  ⚠️ ключ НЕ предлагается — {miss}')
    print('  предложение в профиль:')
    for k, v in patch.items():
        print(f'    {k} = {v}   — {why.get(k, "")}')
    if a.apply and patch:
        prof = Path.home() / 'YTAI/YTs' / str(P.get('channel', '')) / 'review_profile.json'
        note = (f'Канон экранов канала, замер по кату {P.CODE} {P.CUT_VERSION} (shared/style_probe.py). '
                + ' · '.join(f'{k}: {v}' for k, v in why.items()))
        n = apply_to_profile(prof, dict(patch, _canon_note=note))
        print(f'  → в {prof.name} дописано ключей: {n} (+ _canon_note)')
    elif a.apply:
        print('  нечего дописывать: ни один ключ не замерился')
    return 0


if __name__ == '__main__':
    sys.exit(main())
