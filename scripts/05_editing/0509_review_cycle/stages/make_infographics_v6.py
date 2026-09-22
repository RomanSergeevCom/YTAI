#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Инфографика Review_v6 (skill: infographic; chrome-headless-shell; alpha = body transparent).

Новое к v5:
  A. term_<key>.png    — плашки-определения терминов (V3, прозрачные, правый борт)
  B. map_<key>.png     — мини-карты локаций на реальной географии (Natural Earth 50m, PD)
  C. sub_NN.png        — подглавы (V6, прозрачные, левый борт середина — верхняя полоса занята титрами ката)
  D. prog_08_N / prog_09_N — прогресс перечислений «N из M» (V6, левый борт середина; заменяет подглаву)
  E. *_t.png           — прозрачные версии тёмных полноэкранных драфтов (панель по центру)
  F. fix_*.png         — нарисованные ИСПРАВЛЕНИЯ (валюта «$30,3 МЛН» и т.п.) — по OCR-bbox
  G. ann_tzNN / tz_lt_NN для новых ТЗ-33+ — генерятся из pravki_v2.json + audit_v6.json
Все PNG 3840×2160 → {project}/00_Setup/05_Review/mockups/ (+src/*.html).
usage: make_infographics_v6.py [A B C D E F G | all]
"""
import json, math, os, re, sys
from pathlib import Path

from _bootstrap import P, W6, M, HERE, ROOT, T, LANG, tz_label  # noqa: E402
import i18n  # noqa: E402  (has() — есть ли перевод иконки категории)
from render import render  # noqa: E402
from terms_catalog import TERMS, LOCS, PLACE, PLACES, TERM_EXTRA, place_family  # noqa: E402
from make_infographics_v6_data import (SUB, CH_ACCENT, CH_NAME, PROG, PROG_T,  # noqa: E402
                                       CH_BOUNDS, NEW_CH)
from typo_diff import spans_for_fragment  # noqa: E402


MONT = M
OUT = P.MOCK                               # {05_Review}/mockups или mockups_dir из карточки
SRC = OUT / 'src'
SRC.mkdir(parents=True, exist_ok=True)
# стиль канала — из YTs/{CH}/review_profile.json (дефолты = UVI: слоновая кость на чёрном, сериф)
IVORY = P.profile('style.ivory', '#F2EAD8')
RED = P.profile('style.red', '#C1272D')
MUT = P.profile('style.mut', '#CDC6B8')
BG = P.profile('style.bg', '#101014')
PANEL = P.profile('style.panel', 'rgba(10,10,14,.84)')
FONT = P.profile('style.font_stack', "Georgia,'Times New Roman',serif")

BASE_CSS = f"""
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ width:3840px; height:2160px; overflow:hidden; background:transparent!important; }}
body {{ color:{IVORY}; font-family:{FONT}; position:relative; }}
.sans {{ font-family:Helvetica,Arial,sans-serif; }}
.draft {{ position:absolute; right:48px; bottom:36px; font-family:Helvetica,Arial,sans-serif;
  font-size:26px; color:rgba(255,255,255,.45); letter-spacing:.12em; }}
"""
# бейдж драфта — из профиля канала (style.draft_badge), иначе core.draft_badge. Русская графика канона пишет его
# капсом (у YTUVI в профиле строчными), английская — как в профиле.
DRAFT_TXT = str(P.profile('style.draft_badge') or T('core.draft_badge'))
if LANG == 'ru':
    DRAFT_TXT = DRAFT_TXT.upper()
DRAFT = f'<div class="draft">{DRAFT_TXT}</div>'
STAGES = set(sys.argv[1:]) or {'all'}


def want(s):
    return 'all' in STAGES or s in STAGES


def esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def page(name, body, css='', draft=True):
    html = f'<!doctype html><meta charset="utf-8"><style>{BASE_CSS}{css}</style>{body}{DRAFT if draft else ""}'
    p = SRC / f'{name}.html'
    p.write_text(html)
    if os.environ.get('YTAI_RENDER_HTML_ONLY') != '1':     # =1: только HTML в src/, без chrome (golden-регрессия)
        render(p, OUT / f'{name}.png', alpha=True)
    print('✓', name, flush=True)


def flatten_jpg(name, width=1920):
    """4K PNG с альфой → плоский jpg рядом: гугл-док вставляет картинку по ссылке и альфу не показывает.
    Раньше такие jpg делали руками, и после правки CSS во вкладке оставалась старая картинка."""
    if os.environ.get('YTAI_RENDER_HTML_ONLY') == '1':
        return None
    src = OUT / f'{name}.png'
    if not src.exists():
        return None
    from PIL import Image
    im = Image.open(src).convert('RGBA')
    flat = Image.new('RGB', im.size, (12, 12, 14))         # подложка цвета канала, а не белая
    flat.paste(im, (0, 0), im)
    if width and flat.width > width:
        flat = flat.resize((width, round(flat.height * width / flat.width)), Image.LANCZOS)
    out = OUT / f'{name}.jpg'
    flat.save(out, quality=86)
    return out


# ═══════════════════════════ A. термины ═══════════════════════════
TERM_CSS = f"""
.tp {{ position:absolute; right:120px; top:700px; width:1180px; background:{PANEL};
  border-radius:28px; padding:44px 56px 48px 56px; border-left:16px solid {RED}; }}
.tp .lbl {{ font-family:Helvetica,Arial,sans-serif; font-size:30px; letter-spacing:.22em; color:{MUT}; }}
.tp .h {{ font-size:78px; font-weight:bold; line-height:1.08; margin-top:10px; letter-spacing:.02em; }}
.tp .s {{ font-family:Helvetica,Arial,sans-serif; font-size:36px; color:{RED}; margin-top:12px; letter-spacing:.02em; }}
.tp .d {{ font-size:42px; line-height:1.38; color:{IVORY}; margin-top:26px; }}
/* перевод под оригиналом — когда надпись физически в кадре (часы, документ) и её не перерисовать */
.tp .ru {{ font-size:60px; font-weight:bold; line-height:1.1; color:{IVORY}; margin-top:10px; }}
.tp.grp .ru {{ font-size:48px; }}
"""
TERM_BY_KEY = {t[0]: t for t in TERMS}
GRP_CSS = TERM_CSS + f"""
.tp.grp {{ top:560px; padding-top:34px; }}
.tp .item + .item {{ margin-top:30px; padding-top:28px; border-top:2px solid rgba(242,234,216,.18); }}
.tp.grp .h {{ font-size:64px; }}
.tp.grp .d {{ font-size:38px; margin-top:16px; }}
"""


def term_body(key):
    """Роман 11.09: если надпись видна в кадре по-английски — ведём оригиналом, перевод строкой ниже,
    чтобы зритель сопоставил надпись, слова ведущей и смысл. Иначе канон ТЗ-14 (русское крупно)."""
    _, _, title, sub, definition = TERM_BY_KEY[key]
    x = TERM_EXTRA.get(key) or {}
    if x.get('lead') == 'en' and x.get('en'):
        lbl = x.get('lbl') or T('d.ig.term_lbl_onscreen')
        # оригинал уже стоит заголовком — во второй строке его не повторяем
        sub_en = sub.split('·', 1)[-1].strip() if '·' in sub else sub
        head = (f'<div class="h">{x["en"][0].upper()}</div><div class="ru">{title}</div>'
                f'<div class="s">{sub_en}</div>')
    else:
        lbl = T('d.ig.term_lbl')
        head = f'<div class="h">{title}</div><div class="s">{sub}</div>'
    return lbl, f'{head}<div class="d">{definition}</div>'


def term_item(key):
    return f'<div class="item">{term_body(key)[1]}</div>'


if want('A'):
    for key, rx, title, sub, definition in TERMS:
        lbl, body = term_body(key)
        page(f'term_{key}', f"""
<div class="tp"><div class="lbl">{lbl}</div>{body}</div>""", TERM_CSS)
    # группы (термины в одном окне ≤5 с) — одна плашка на 2–3 определения
    tj = W6 / 'terms_v6.json'
    if tj.exists():
        seen = set()
        for g in json.load(open(tj)).get('term_groups', []):
            if len(g['keys']) < 2:
                continue
            name = 'termgrp_' + '_'.join(g['keys'])
            if name in seen:
                continue
            seen.add(name)
            page(name, f"""
<div class="tp grp"><div class="lbl">{T('d.ig.terms_lbl')}</div>{''.join(term_item(k) for k in g['keys'])}</div>""", GRP_CSS)

# ═══════════════════════════ B. мини-карты ═══════════════════════════
# точки: lat, lon, подпись (координаты сверены fact-агентом — facts_v6.json при наличии)
POINTS = {
    'mogok': (22.92, 96.50, 'Могок'), 'monghsu': (21.92, 98.38, 'Монг Су'),
    'montepuez': (-13.12, 39.00, 'Монтепуэз'), 'chanthaburi': (12.61, 102.10, 'Чантхабури'),
    'pailin': (12.85, 102.61, 'Пайлин'), 'ratnapura': (6.68, 80.40, 'Ратнапура'),
    'lucyen': (22.08, 104.75, 'Лук Йен'), 'jegdalek': (34.43, 69.82, 'Джегдалек'),
    'pamir': (38.26, 74.39, 'Памир'), 'hunza': (36.33, 74.67, 'Хунза'),
    'winza': (-7.02, 36.37, 'Винза'), 'longido': (-2.73, 36.70, 'Лонгидо'),
    'andilamena': (-17.02, 48.58, 'Андиламена'), 'mangare': (-3.86, 38.50, 'Мангаре'),
    'chimwadzulu': (-14.81, 34.63, 'Чимвадзулу'), 'aappaluttoq': (63.03, -50.30, 'Аппалутток'),
    'kashmir': (34.20, 74.90, 'Кашмир'), 'songea': (-10.68, 35.65, 'Сунгеа'),
}
CITIES = {'sea': [('Янгон', 16.87, 96.20), ('Мандалай', 21.98, 96.08), ('Бангкок', 13.76, 100.50),
                  ('Коломбо', 6.93, 79.85), ('Ханой', 21.03, 105.85)],
          'africa': [('Мапуту', -25.97, 32.57), ('Найроби', -1.29, 36.82), ('Дар-эс-Салам', -6.79, 39.28),
                     ('Антананариву', -18.88, 47.51)],
          'world': [], 'burma': [('Янгон', 16.87, 96.20), ('Мандалай', 21.98, 96.08), ('Бангкок', 13.76, 100.50),
                                 ('Дакка', 23.81, 90.41), ('Ханой', 21.03, 105.85)],
          'thai': [('Бангкок', 13.76, 100.50), ('Пномпень', 11.56, 104.92), ('Янгон', 16.87, 96.20)],
          'lanka': [('Коломбо', 6.93, 79.85), ('Ченнаи', 13.08, 80.27)], 'viet': [('Ханой', 21.03, 105.85)],
          'moz': [('Мапуту', -25.97, 32.57), ('Антананариву', -18.88, 47.51), ('Лилонгве', -13.96, 33.79), ('Пемба', -12.97, 40.52)],
          'eafr': [('Найроби', -1.29, 36.82), ('Дар-эс-Салам', -6.79, 39.28), ('Додома', -6.16, 35.75)],
          'casia': [('Кабул', 34.53, 69.17), ('Душанбе', 38.56, 68.77), ('Исламабад', 33.69, 73.04), ('Сринагар', 34.08, 74.80)]}
REGIONS = {'sea': (76, 110, 3, 30), 'africa': (26, 54, -28, 2), 'world': (18, 112, -32, 46),
           'burma': (88, 108, 6, 29), 'thai': (95, 110, 5, 22), 'lanka': (76, 90, 3, 16), 'viet': (99, 112, 7, 25),
           'moz': (30, 52, -28, -8), 'eafr': (28, 52, -20, 2), 'casia': (58, 82, 22, 42)}
LOC_REGION = {'mogok': 'burma', 'monghsu': 'burma', 'burma': 'burma', 'thai': 'thai', 'srilanka': 'lanka',
              'vietnam': 'viet', 'mozambique': 'moz', 'malawi': 'moz', 'madagascar': 'moz', 'tanzania': 'eafr',
              'kenya': 'eafr', 'afghan': 'casia', 'kashmir': 'casia'}
# смещение подписи точки: (dx, dy, anchor)
LABEL_OFF = {'monghsu': (30, 58, 'start'), 'mogok': (-30, -22, 'end'), 'pailin': (30, 58, 'start'),
             'chanthaburi': (-30, -22, 'end'), 'longido': (30, -14, 'start'), 'winza': (30, -14, 'start'),
             'hunza': (30, -14, 'start'), 'pamir': (-30, -22, 'end'), 'jegdalek': (-30, 40, 'end'),
             'kashmir': (30, 50, 'start')}
COUNTRY_RU = {'Myanmar': 'МЬЯНМА', 'Thailand': 'ТАИЛАНД', 'Cambodia': 'КАМБОДЖА', 'Vietnam': 'ВЬЕТНАМ',
              'Sri Lanka': 'ШРИ-ЛАНКА', 'Laos': 'ЛАОС', 'India': 'ИНДИЯ', 'Bangladesh': 'БАНГЛАДЕШ', 'China': 'КИТАЙ',
              'Mozambique': 'МОЗАМБИК', 'Tanzania': 'ТАНЗАНИЯ', 'Kenya': 'КЕНИЯ', 'Madagascar': 'МАДАГАСКАР',
              'Malawi': 'МАЛАВИ', 'Zambia': 'ЗАМБИЯ', 'Zimbabwe': 'ЗИМБАБВЕ', 'South Africa': 'ЮАР',
              'Afghanistan': 'АФГАНИСТАН', 'Tajikistan': 'ТАДЖИКИСТАН', 'Pakistan': 'ПАКИСТАН', 'Iran': 'ИРАН',
              'Somalia': 'СОМАЛИ', 'Ethiopia': 'ЭФИОПИЯ', 'Uganda': 'УГАНДА', 'Dem. Rep. Congo': 'ДР КОНГО',
              'Saudi Arabia': 'САУД. АРАВИЯ', 'Oman': 'ОМАН', 'Yemen': 'ЙЕМЕН', 'Egypt': 'ЕГИПЕТ', 'Sudan': 'СУДАН',
              'Nepal': 'НЕПАЛ', 'Malaysia': 'МАЛАЙЗИЯ', 'Indonesia': 'ИНДОНЕЗИЯ', 'Kazakhstan': 'КАЗАХСТАН',
              'Uzbekistan': 'УЗБЕКИСТАН', 'Turkmenistan': 'ТУРКМЕНИСТАН', 'Iraq': 'ИРАК', 'Turkey': 'ТУРЦИЯ',
              'Russia': 'РОССИЯ', 'Mongolia': 'МОНГОЛИЯ', 'Angola': 'АНГОЛА', 'Botswana': 'БОТСВАНА', 'Namibia': 'НАМИБИЯ'}
# английские подписи точек и городов (LANG=en): русские имена выше — данные канала UVI, в английскую графику не идут
POINTS_EN = {'mogok': 'Mogok', 'monghsu': 'Mong Hsu', 'montepuez': 'Montepuez', 'chanthaburi': 'Chanthaburi',
             'pailin': 'Pailin', 'ratnapura': 'Ratnapura', 'lucyen': 'Luc Yen', 'jegdalek': 'Jegdalek', 'pamir': 'Pamir',
             'hunza': 'Hunza', 'winza': 'Winza', 'longido': 'Longido', 'andilamena': 'Andilamena', 'mangare': 'Mangare',
             'chimwadzulu': 'Chimwadzulu', 'aappaluttoq': 'Aappaluttoq', 'kashmir': 'Kashmir', 'songea': 'Songea'}
CITIES_EN = {'Янгон': 'Yangon', 'Мандалай': 'Mandalay', 'Бангкок': 'Bangkok', 'Коломбо': 'Colombo', 'Ханой': 'Hanoi',
             'Мапуту': 'Maputo', 'Найроби': 'Nairobi', 'Дар-эс-Салам': 'Dar es Salaam', 'Антананариву': 'Antananarivo',
             'Дакка': 'Dhaka', 'Пномпень': 'Phnom Penh', 'Ченнаи': 'Chennai', 'Лилонгве': 'Lilongwe', 'Пемба': 'Pemba',
             'Додома': 'Dodoma', 'Кабул': 'Kabul', 'Душанбе': 'Dushanbe', 'Исламабад': 'Islamabad', 'Сринагар': 'Srinagar'}


def country_label(name):
    return COUNTRY_RU.get(name, name.upper()) if LANG == 'ru' else name.upper()

_geo = None


def geo():
    global _geo
    if _geo is None:
        _geo = json.load(open(ROOT / 'geo/ne_50m_countries.geojson'))['features']
    return _geo


HL = {'burma': ['Myanmar'], 'mogok': ['Myanmar'], 'monghsu': ['Myanmar'], 'thai': ['Thailand', 'Cambodia'],
      'srilanka': ['Sri Lanka'], 'vietnam': ['Vietnam'], 'mozambique': ['Mozambique'], 'tanzania': ['Tanzania'],
      'madagascar': ['Madagascar'], 'kenya': ['Kenya'], 'malawi': ['Malawi'],
      'afghan': ['Afghanistan', 'Tajikistan', 'Pakistan'], 'kashmir': []}


def make_map(region, pts, label, mw=1180, mh=760, facts=None, hl=(), nolabel=()):
    """SVG карты региона: суша Natural Earth, страны подписаны, точки месторождений красным."""
    lon0, lon1, lat0, lat1 = REGIONS.get(region, REGIONS['world'])   # регион карточки вне таблицы — мир
    # равнопромежуточная проекция с правильными пропорциями (масштаб по долготе × cos средней широты)
    cosm = math.cos(math.radians((lat0 + lat1) / 2))
    k = min(mw / ((lon1 - lon0) * cosm), mh / (lat1 - lat0))
    kx, ky = k * cosm, k
    ox = (mw - (lon1 - lon0) * kx) / 2
    oy = (mh - (lat1 - lat0) * ky) / 2

    def P(lat, lon):
        return ox + (lon - lon0) * kx, oy + (lat1 - lat) * ky

    paths, labels = [], []
    for f in geo():
        g = f['geometry']
        polys = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        name = f['properties'].get('NAME') or ''
        best_ring, best_area = None, 0
        for poly in polys:
            ring = poly[0]
            # быстрый bbox-отсев
            lons = [c[0] for c in ring]; lats = [c[1] for c in ring]
            if max(lons) < lon0 - 2 or min(lons) > lon1 + 2 or max(lats) < lat0 - 2 or min(lats) > lat1 + 2:
                continue
            d = ' '.join(f'{"M" if i == 0 else "L"}{P(c[1], c[0])[0]:.1f},{P(c[1], c[0])[1]:.1f}'
                         for i, c in enumerate(ring[::2] if len(ring) > 400 else ring)) + 'Z'
            paths.append((d, name in hl))
            # площадь (shoelace) в проекции — для подписи страны берём самый большой видимый полигон
            vis = [c for c in ring if lon0 <= c[0] <= lon1 and lat0 <= c[1] <= lat1]
            if len(vis) > 8 and name in COUNTRY_RU:
                area = 0
                for i in range(len(vis) - 1):
                    x1, y1 = P(vis[i][1], vis[i][0]); x2, y2 = P(vis[i + 1][1], vis[i + 1][0])
                    area += x1 * y2 - x2 * y1
                area = abs(area) / 2
                if area > best_area:
                    best_area = area
                    cx = sum(P(c[1], c[0])[0] for c in vis) / len(vis)
                    cy = sum(P(c[1], c[0])[1] for c in vis) / len(vis)
                    best_ring = (cx, cy)
        if best_ring and (best_area > mw * mh * 0.004 or name in hl):
            labels.append((best_area + (1e9 if name in hl else 0), best_ring[0], best_ring[1], country_label(name)))
    pts = [k for k in pts if k in POINTS]        # точка карточки без координат в таблице — не рисуем (раньше KeyError)
    # точки — сначала, чтобы подписи стран их обходили
    placed = []
    for k in pts:
        la, lo, nm = POINTS[k][:3]
        if facts and k in facts:
            la, lo = facts[k]['lat'], facts[k]['lon']
        if lon0 <= lo <= lon1 and lat0 <= la <= lat1:
            x, y = P(la, lo)
            placed.append((x, y))
    lab_svg = ''
    for area, x, y, nm in sorted(labels, reverse=True):
        must = area >= 1e9
        if any(abs(x - px) < 170 and abs(y - py) < 70 for px, py in placed):
            if not must:
                continue
            y += 110                              # своя страна — подпись обязательна, сдвигаем вниз
        fs = 34 if must else (30 if area > mw * mh * 0.03 else 24)
        lab_svg += (f'<text x="{x:.0f}" y="{y:.0f}" fill="rgba(242,234,216,{".9" if must else ".55"})" font-size="{fs}" '
                    f'text-anchor="middle" font-family="Helvetica,Arial" letter-spacing="2">{nm}</text>')
        placed.append((x, y))
    labels = lab_svg
    land = ''.join(f'<path d="{d}" fill="{"rgba(193,39,45,.30)" if h else "rgba(242,234,216,.16)"}" '
                   f'stroke="rgba(242,234,216,{".8" if h else ".55"})" stroke-width="{3 if h else 2}"/>' for d, h in paths)
    labels = labels if isinstance(labels, str) else ''
    cities = ''
    for nm, la, lo in CITIES.get(region, []):
        if lon0 <= lo <= lon1 and lat0 <= la <= lat1:
            x, y = P(la, lo)
            nm = nm if LANG == 'ru' else CITIES_EN.get(nm, nm)
            cities += (f'<circle cx="{x:.0f}" cy="{y:.0f}" r="6" fill="rgba(242,234,216,.7)"/>'
                       f'<text x="{x + 14:.0f}" y="{y + 10:.0f}" fill="rgba(242,234,216,.7)" font-size="26" font-family="Helvetica,Arial">{nm}</text>')
    dots = ''
    for k in pts:
        la, lo, nm = POINTS[k]
        nm = nm if LANG == 'ru' else POINTS_EN.get(k, nm)
        if facts and k in facts:
            la, lo = facts[k]['lat'], facts[k]['lon']
        if not (lon0 <= lo <= lon1 and lat0 <= la <= lat1):
            continue
        x, y = P(la, lo)
        dx, dy, anch = LABEL_OFF.get(k, (30, -14, 'start'))
        dots += (f'<circle cx="{x:.0f}" cy="{y:.0f}" r="26" fill="{RED}" opacity=".35"/>'
                 f'<circle cx="{x:.0f}" cy="{y:.0f}" r="13" fill="{RED}"/>')
        if k not in nolabel:
            dots += (f'<text x="{x + dx:.0f}" y="{y + dy:.0f}" fill="{IVORY}" font-size="40" font-weight="bold" '
                     f'text-anchor="{anch}" style="paint-order:stroke;stroke:rgba(10,10,14,.9);stroke-width:8px">{nm}</text>')
    return (f'<svg width="{mw}" height="{mh}" viewBox="0 0 {mw} {mh}" style="display:block;border-radius:18px;'
            f'background:rgba(20,28,40,.35)">{land}{labels}{cities}{dots}</svg>')


MAP_CSS = f"""
.mp {{ position:absolute; right:120px; top:560px; width:1280px; background:{PANEL};
  border-radius:28px; padding:36px 50px 44px 50px; border-left:16px solid {RED}; }}
.mp .lbl {{ font-family:Helvetica,Arial,sans-serif; font-size:30px; letter-spacing:.22em; color:{MUT}; }}
.mp .h {{ font-size:64px; font-weight:bold; margin:8px 0 10px; letter-spacing:.02em; }}
.mp .s {{ font-family:Helvetica,Arial,sans-serif; font-size:36px; line-height:1.3; color:{MUT}; margin:0 0 20px; }}
.mp .n {{ font-size:34px; line-height:1.3; color:{IVORY}; margin:0 0 22px;
  padding-left:22px; border-left:8px solid {RED}; }}
"""
if want('B'):
    facts = None
    fp = W6 / 'facts_v6.json'
    if fp.exists():
        try:
            facts = {d['key']: d for d in json.load(open(fp))['deposits'] if 'key' in d}
        except Exception:
            facts = None
    for key, rx, region, pts, label in LOCS:
        region = LOC_REGION.get(key, region)
        p = PLACE[key]
        head = (f'<div class="lbl">{T("d.ig.where_lbl")}</div><div class="h">{label}</div>'
                f'<div class="s">{p["sub"]}</div>')
        svg = make_map(region, pts, label, facts=facts, hl=HL.get(key, ()))
        page(f'map_{key}', f"""
<div class="mp">{head}
 {svg}</div>""", MAP_CSS)
        # вариант со сноской «одна страна — два имени» — только для ПЕРВОГО упоминания (terms_index ставит note)
        if p.get('note'):
            page(f'map_{key}_note', f"""
<div class="mp">{head}<div class="n">{p['note']}</div>
 {svg}</div>""", MAP_CSS)

FULL_CSS = f"""
/* большие карты ЗАМЕНЯЮТ кадр, поэтому подложка глухая: сквозь полупрозрачную просвечивали
   английские подписи карты ката (проверено на превью 19:37) */
.mf {{ position:absolute; left:50%; transform:translateX(-50%); top:300px; width:3000px; background:{BG};
  border-radius:32px; padding:50px 70px 60px 70px; border-top:14px solid {RED}; display:flex; gap:60px; }}
.mf .side {{ width:900px; flex:none; }}
.mf .lbl {{ font-family:Helvetica,Arial,sans-serif; font-size:32px; letter-spacing:.22em; color:{MUT}; }}
.mf .h {{ font-size:84px; font-weight:bold; line-height:1.1; margin:10px 0 30px; }}
.mf .n {{ font-size:40px; line-height:1.4; margin-top:22px; padding-left:28px; border-left:8px solid {RED}; }}
.mf .n b {{ color:{IVORY}; font-size:46px; display:block; }}
.mf .n span {{ color:{MUT}; }}
"""
# Большие карты «Мьянма» и «рубиновый пояс» — данные фильмов UVI о рубинах (русский текст): только для русской
# графики и только когда каталог мест карточки их упоминает. Раньше рисовались на любом фильме любого канала.
_USED_PLACES = set(PLACE) | {pt for p in PLACES for pt in (p.get('points') or [])}
BURMA_PTS = ['mogok', 'monghsu']
BELT_PTS = ['mogok', 'monghsu', 'montepuez', 'chanthaburi', 'pailin', 'ratnapura', 'lucyen', 'jegdalek',
            'pamir', 'hunza', 'winza', 'longido', 'songea', 'andilamena', 'mangare', 'chimwadzulu', 'kashmir']
if want('B') and LANG == 'ru' and _USED_PLACES & set(BURMA_PTS):
    # полноразмерная карта Мьянмы (замена рисованного блоба info_mogok_map, 052)
    notes =('<div class="n"><b>МОГОК</b><span>долина в Мьянме — «голубиная кровь», эталонный цвет</span></div>'
             '<div class="n"><b>МОНГ СУ (Mong Hsu)</b><span>месторождение в Мьянме — массовая добыча с 1990-х, почти всё гретое</span></div>')
    page('mapfull_burma', f"""
<div class="mf"><div class="side"><div class="lbl">ГДЕ ЭТО</div><div class="h">МЬЯНМА <span style="color:{RED}">(БИРМА)</span></div>
 <div style="font-size:40px;color:{MUT}">одна страна — два разных месторождения</div>{notes}</div>
 {make_map('burma', BURMA_PTS, '', mw=1900, mh=1150, hl=['Myanmar'])}</div>""", FULL_CSS)
if want('B') and LANG == 'ru' and _USED_PLACES & set(BELT_PTS):
    # рубиновый пояс В ТРИ ШАГА — страны загораются по мере перечисления в озвучке 19:30–19:40
    # (замена английского титра ката 19:33–19:40 и стопки из 7 мини-карт на 19:40)
    belt_pts = BELT_PTS
    # на общей карте подписываем только опорные точки: остальные читаются по подсветке страны
    belt_nolabel = ['winza', 'longido', 'songea', 'mangare', 'chimwadzulu', 'andilamena', 'pailin',
                    'chanthaburi', 'hunza', 'kashmir', 'jegdalek', 'pamir']
    BELT_STEPS = [
        ('mapfull_belt', '1 из 3 · главные страны рынка',
         ['Myanmar', 'Mozambique', 'Thailand', 'Cambodia'],
         '<div class="n"><b>МЬЯНМА (БИРМА)</b><span>Могок — «голубиная кровь», Монг Су — гретые камни</span></div>'
         '<div class="n"><b>МОЗАМБИК</b><span>Монтепуэз — железистые, главный игрок с 2009 года</span></div>'
         '<div class="n"><b>ТАИЛАНД и КАМБОДЖА</b><span>тёмные камни, почти всегда с нагревом</span></div>'),
        ('mapfull_belt_2', '2 из 3 · Азия',
         ['Vietnam', 'Tajikistan', 'Afghanistan', 'Pakistan', 'Sri Lanka'],
         '<div class="n"><b>ВЬЕТНАМ</b><span>Лук Йен</span></div>'
         '<div class="n"><b>ТАДЖИКИСТАН · АФГАНИСТАН · ПАКИСТАН</b><span>горы Памира и Гиндукуша</span></div>'
         '<div class="n"><b>ШРИ-ЛАНКА (ЦЕЙЛОН)</b><span>остров переименовали в 1972 — это одно место</span></div>'),
        ('mapfull_belt_3', '3 из 3 · Африка',
         ['Tanzania', 'Madagascar', 'Kenya', 'Malawi'],
         '<div class="n"><b>ТАНЗАНИЯ</b><span>Винза, Лонгидо, Сунгеа</span></div>'
         '<div class="n"><b>МАДАГАСКАР · КЕНИЯ · МАЛАВИ</b><span>молодые месторождения Восточной Африки</span></div>'
         '<div class="n"><b>ИТОГО</b><span>рубин добывают на трёх континентах — это и есть «рубиновый пояс»</span></div>'),
    ]
    # панель шире обычной (3400 из 3840): под ней лежит английская карта ката — её надо перекрыть
    for name, step, hl_step, notes in BELT_STEPS:
        page(name, f"""
<div class="mf" style="top:170px;width:3400px"><div class="side"><div class="lbl">ГДЕ ДОБЫВАЮТ</div><div class="h">РУБИНОВЫЙ <span style="color:{RED}">ПОЯС</span></div>
 <div style="font-size:38px;color:{MUT};margin-bottom:6px">{step}</div>{notes}</div>
 {make_map('world', belt_pts, '', mw=2300, mh=1450, hl=hl_step, nolabel=belt_nolabel)}</div>""", FULL_CSS)

# ═══════════════════════════ C. подглавы (V6) ═══════════════════════════
SUB_CSS = f"""
.sw {{ position:absolute; left:150px; top:640px; display:flex; gap:34px; align-items:stretch;
  background:{PANEL}; border-radius:24px; padding:30px 54px 34px 40px; max-width:1500px; }}
.sbar {{ width:12px; border-radius:6px; flex:none; }}
.snum {{ font-family:Helvetica,Arial,sans-serif; font-size:34px; letter-spacing:.24em; font-weight:bold; }}
.sname {{ font-size:64px; font-weight:bold; color:{IVORY}; line-height:1.15; margin-top:8px; max-width:1380px; }}
.sname .tri {{ color:{MUT}; font-size:56px; margin-right:18px; }}
"""
if want('C'):
    for i, (sec, ch, label) in enumerate(SUB):
        acc = CH_ACCENT[ch - 1]
        page(f'sub_{i + 1:02d}', f"""
<div class="sw"><div class="sbar" style="background:{acc}"></div>
 <div><div class="snum" style="color:{acc}">{T('core.chapter')} {ch:02d} · {CH_NAME[ch - 1]}</div>
  <div class="sname"><span class="tri">▸</span>{label}</div></div></div>""", SUB_CSS, draft=False)

# ═══════════════════════════ D. прогресс перечислений (V6) ═══════════════════════════
# Переписано 22.09.2026 по пресету «YTCG P01 · 1.1 Side slide», который выбрал Роман:
# боковая страница, заголовок сверху, под ним список, который НАКАПЛИВАЕТСЯ — пункт за пунктом
# по ходу речи. Будущих пунктов не видно, подсвечивать нечего: свежий пункт дописывается снизу.
#
# Прошлые варианты a/b (тёмная коробка со скруглением, кружки-радиокнопки, полоса прогресса,
# акцент из палитры маркеров Premiere) Роман забраковал: «крайне важно сделать крутой дизайн
# подглав, мне пока не нравится».
#
# Что решили замером по самому кату, а не на вкус:
#  · все пункты одного кегля = текущий искать глазами; размер пре-аттентивен, цвет на пёстром
#    кадре нет. Накопительный список снимает вопрос: свежий пункт всегда последняя строка;
#  · полоса накрывала собственный титр главы ката — страница начинается НИЖЕ него (y 204…260);
#  · кегль 88 px: самая длинная строка «ФЛЮСОВОЕ ЗАЛЕЧИВАНИЕ» (1380 px) влезает в одну строку;
#  · тире короткое (en, 0.5 em) и висячий отступ ровно по его ширине — переносы по тексту.
#    ⚠️ text-indent наследуется: без `text-indent:0` на inline-block тире уезжает влево на IND;
#  · черта 570 × 10 — ровно вдвое больше собственной черты подтемы ката (285 × 5 на 1920).
#
# Две темы (card `prog_variant`): `z` — тёмная (принята Романом), `h` — светлая, для примера.
# ⚠️ Тёмная НЕпрозрачна: на 94 % сквозь неё просвечивали титры ката. Заодно на непрозрачной
# темноте настоящий рубин канала даёт 3,2 : 1 и работает как черта/тире/цифра — на полупрозрачном
# скриме он давал 2,08 и был непригоден.
PROG_X, PROG_RM, PROG_BAND, PROG_TOP = 148, 148, 1780, 300
PROG_COL = PROG_BAND - PROG_X - PROG_RM
PROG_ITEM, PROG_DASH, PROG_GAP = 88, 44, 24
PROG_IND = PROG_DASH + PROG_GAP
PROG_GRAPH = '#7A7365'              # пройденные ПО кости: 3,93 : 1 (профильный MUT там 1,42 — слепой)
PROG_DARK = '#141110'
PROG_THEMES = {
    'z': dict(bg=PROG_DARK, hdr=MUT, rule=RED, cnum=RED, cden=MUT,
              new=IVORY, old=MUT, dnew=RED, dold=MUT, oldop='.45'),
    'h': dict(bg=IVORY, hdr=RED, rule=RED, cnum=RED, cden=PROG_GRAPH,
              new=RED, old=PROG_GRAPH, dnew=RED, dold=PROG_GRAPH, oldop='1'),
}
PROG_VARIANT = str(P.get('prog_variant') or 'z').strip().lower()
if PROG_VARIANT not in PROG_THEMES:                    # буква без темы = панель без цвета, лучше упасть
    raise SystemExit(f'блок D: неизвестный prog_variant «{PROG_VARIANT}», есть {sorted(PROG_THEMES)}')
# нумерация Романа: содержательных глав восемь (01..08), хук и финал без номера.
# Сама панель номер главы больше не печатает (в кадре он уже стоит титром ката), но карта
# выпуска блока H по-прежнему считает подписи отсюда — константа общая, не переносить в блок D.
CH_NO_FINAL = P.get('ch_no_final', {})


def _prog_css(v):
    t = PROG_THEMES[v]
    return f"""
.pshot {{ position:absolute; inset:0; background-size:cover; background-position:center; }}
.pgb {{ position:absolute; left:0; top:{PROG_TOP}px; bottom:0; width:{PROG_BAND}px; background:{t['bg']}; }}
.pgt {{ position:absolute; left:{PROG_X}px; top:692px; width:{PROG_COL}px; display:flex;
  justify-content:space-between; align-items:baseline; }}
.pgt .hd {{ font-family:Helvetica,Arial,sans-serif; font-weight:300; text-transform:uppercase;
  font-size:56px; letter-spacing:.20em; color:{t['hdr']}; }}
.pgt .cn {{ color:{t['cnum']}; letter-spacing:.02em; white-space:nowrap; }}
.pgt .cn b {{ font-size:88px; }}
.pgt .cn i {{ font-size:46px; font-style:normal; color:{t['cden']}; }}
.pgr {{ position:absolute; left:{PROG_X}px; top:828px; width:570px; height:10px; background:{t['rule']}; }}
.pgl {{ position:absolute; left:{PROG_X}px; top:922px; width:{PROG_COL}px; }}
.pgl .r {{ font-size:{PROG_ITEM}px; line-height:1.14; letter-spacing:.02em; color:{t['old']};
  opacity:{t['oldop']}; margin-bottom:46px; padding-left:{PROG_IND}px; text-indent:-{PROG_IND}px; }}
.pgl .r:last-child {{ margin-bottom:0; }}
.pgl .r .d {{ color:{t['dold']}; display:inline-block; width:{PROG_DASH}px;
  margin-right:{PROG_GAP}px; text-indent:0; }}
.pgl .r .q {{ font-family:Helvetica,Arial,sans-serif; font-weight:300; text-transform:uppercase;
  font-size:40px; letter-spacing:.22em; color:inherit; opacity:.8; margin-left:22px; }}
.pgl .r.new {{ color:{t['new']}; opacity:1; }}
.pgl .r.new .d {{ color:{t['dnew']}; }}
"""


def _prog_body(ch, k, variant=None):
    """k=0 — страница пришла с одним заголовком (первый такт пресета); k≥1 — дописано k пунктов."""
    title, items, _acc = PROG[ch]
    n = len(items)
    rows = []
    for j, it in enumerate(items[:k], 1):              # только пройденное: список продолжается
        nm, _, q = esc(it).partition(' · ')
        qq = f'<span class="q">{q}</span>' if q else ''
        rows.append(f'<div class="r {"new" if j == k else ""}">'
                    f'<span class="d">&#8211;</span>{nm}{qq}</div>')
    cn = (f'<div class="cn"><b>{k}</b><i>&#8201;/&#8201;{n}</i></div>' if k else
          f'<div class="cn hd">{T("d.ig.prog_next")}</div>')
    return (f'<div class="pgb"></div><div class="pgt"><div class="hd">{esc(title)}</div>{cn}</div>'
            f'<div class="pgr"></div><div class="pgl">{"".join(rows)}</div>')


if want('D'):
    for ch in PROG:
        for k in range(0, len(PROG[ch][1]) + 1):       # k=0 остаётся: на него завязан make_review_v6
            page(f'prog_{ch}_{k}', _prog_body(ch, k), _prog_css(PROG_VARIANT), draft=False)
    # демо обеих тем на настоящем кадре: принятая тёмная и светлая «для примера»
    _dch = next((c for c in PROG if len(PROG[c][1]) >= 4), next(iter(PROG), None))
    if _dch:
        _dsec = int(P.get('prog_demo_sec', 0)) or int(PROG_T.get(_dch, [0])[1] if len(PROG_T.get(_dch, [])) > 1 else 0)
        _shot = W6 / 'hires' / f'h{_dsec + 1:04d}.jpg'
        bg = (f'<div class="pshot" style="background-image:url(\'file://{_shot}\')"></div>'
              if _shot.exists() else '')
        for v in PROG_THEMES:
            page(f'prog_demo_{v}', bg + _prog_body(_dch, 2, v), _prog_css(v), draft=False)
            flatten_jpg(f'prog_demo_{v}')
        print(f'панель подглав: тема {PROG_VARIANT}, демо z/h по главе {_dch}, кадр {_shot.name}')

# ═══════════════════════════ E. прозрачные версии тёмных драфтов (V3) ═══════════════════════════
CENTER_CSS = f"""
.cp {{ position:absolute; left:50%; transform:translateX(-50%); top:560px; width:2500px; background:{PANEL};
  border-radius:32px; padding:60px 90px 70px 90px; text-align:center; border-top:14px solid {RED}; }}
.cp h1 {{ font-size:96px; letter-spacing:.04em; text-transform:uppercase; font-weight:bold; line-height:1.15; }}
.cp h1 .r {{ color:{RED}; }}
.cp .sub {{ font-size:46px; color:{MUT}; margin-top:22px; }}
.cp .body {{ font-size:50px; line-height:1.55; margin-top:44px; }}
.cp .body .r {{ color:{RED}; }}
.cols {{ display:flex; gap:50px; margin-top:50px; }}
.col {{ flex:1; border:4px solid {MUT}; border-radius:24px; padding:40px 34px; }}
.col .n {{ font-size:90px; font-weight:bold; }}
.col .t {{ font-size:54px; font-weight:bold; margin-top:10px; }}
.col .d {{ font-size:38px; color:{MUT}; margin-top:18px; line-height:1.45; }}
"""
# E — прозрачные драфты фильма UVI о рубинах (русский текст): только русская графика и только если каталог
# терминов карточки несёт эти темы. Раньше рисовались на любом фильме.
_E_MOHS = LANG == 'ru' and 'mohs' in TERM_BY_KEY
_E_SYNTH = LANG == 'ru' and bool({'verneuil', 'flux', 'hydro'} & set(TERM_BY_KEY))
_E_TREAT = LANG == 'ru' and bool({'heat', 'diffusion', 'leadglass'} & set(TERM_BY_KEY))
if want('E') and _E_MOHS:
    page('info_mohs_what_t', f"""
<div class="cp"><h1>ЧТО ТАКОЕ <span class="r">ШКАЛА МООСА</span></h1>
 <div class="body">Шкала твёрдости минералов от 1 до 10: каждый следующий царапает предыдущий.<br>
 Придумана Фридрихом Моосом в 1812 году.<br>
 Шкала <span class="r">нелинейна</span>: между 9 (корунд) и 10 (алмаз) разрыв больше, чем между 1 и 9.</div></div>""",
         CENTER_CSS)
if want('E') and _E_SYNTH:
    page('info_synthesis_list_t', f"""
<div class="cp"><h1>3 СПОСОБА <span class="r">ВЫРАСТИТЬ РУБИН</span></h1>
 <div class="sub">⬇ отсюда начинаются типы искусственных камней</div>
 <div class="cols">
  <div class="col" style="border-color:{RED}"><div class="n" style="color:{RED}">1</div><div class="t">ВЕРНЕЙЛЬ</div>
   <div class="d">порошок в пламени →<br>грушевидная «буля»</div></div>
  <div class="col"><div class="n">2</div><div class="t">ФЛЮС</div><div class="d">раствор во флюсе,<br>месяцы роста</div></div>
  <div class="col"><div class="n">3</div><div class="t">ГИДРОТЕРМАЛЬНЫЙ</div><div class="d">автоклав: затравка,<br>давление, раствор</div></div>
 </div></div>""", CENTER_CSS)
if want('E') and _E_TREAT:
    tr = [('НАГРЕВ', 'норма рынка, стабильный цвет', IVORY),
          ('ЗАПОЛНЕНИЕ ТРЕЩИН', 'масла, смолы, стекло — нестабильно', IVORY),
          ('ФЛЮСОВОЕ ЗАЛЕЧИВАНИЕ', 'синтетика нарастает в трещинах', IVORY),
          ('ДИФФУЗИЯ Ti', 'цвет в тонком слое — сполировывается', IVORY),
          ('ДИФФУЗИЯ Be', 'прокрашен насквозь', RED),
          ('СВИНЦОВОЕ СТЕКЛО', 'ярче, но хрупко: боится химии и нагрева', RED)]
    items = ''.join(
        f'<div style="display:flex;align-items:center;gap:40px;margin:22px 0;text-align:left">'
        f'<div style="width:22px;height:22px;border-radius:50%;background:{c};flex:none"></div>'
        f'<div style="font-size:52px;font-weight:bold;min-width:900px">{n}</div>'
        f'<div style="font-size:40px;color:{MUT}">{d}</div></div>' for n, d, c in tr)
    page('info_treatments_scheme_t', f"""
<div class="cp" style="top:420px"><h1>ОБРАБОТКА <span class="r">РУБИНОВ</span></h1>
 <div class="sub">6 способов — от нормы рынка до «осторожно»</div>
 <div style="margin-top:40px">{items}</div></div>""", CENTER_CSS)

# ═══════════════════════════ G. по аудиту: стрелки V5 · исправления V3 · LT V4 ═══════════════════════════
# audit_v6.json (из s8_apply_audit.py): {"placements":[...], "annotations":[{tz, kind, head, text, bbox:[x,y,w,h] norm,
#   frame, fix:{text, style}|null}], "new_tz_from": 33}
ANN_CSS = f"""
.plate {{ position:absolute; background:rgba(10,10,14,.9); border-radius:24px; padding:34px 46px; max-width:1250px; }}
.plate .h {{ font-size:50px; font-weight:bold; font-family:Helvetica,Arial,sans-serif; letter-spacing:.05em; }}
.plate .t {{ font-size:44px; color:{IVORY}; margin-top:14px; line-height:1.35; }}
.plate .t b {{ color:#fff; }}
"""
FIX_CSS = f"""
.fixwrap {{ position:absolute; }}
.fixpatch {{ position:absolute; background:rgba(10,10,14,.94); border-radius:18px; }}
.fixtxt {{ position:absolute; font-family:{FONT}; font-weight:bold; color:#C1272D;
  white-space:nowrap; letter-spacing:.02em; line-height:1; }}
.fixtxt sub, .fixtxt sup {{ font-size:.6em; line-height:0; }}
.fixbadge {{ position:absolute; background:#2E8B3E; color:#fff; font-family:Helvetica,Arial,sans-serif;
  font-size:30px; font-weight:bold; padding:10px 22px; border-radius:12px; letter-spacing:.08em; }}
"""
LT_COL = {'cut': '#C1272D', 'insert': '#2E8B3E', 'graphics': '#D9A521', 'structure': '#D97721', 'color': '#3A6FB5', 'check': '#777777'}


def lt_ico(cat):
    """иконка+категория LT-плашки ТЗ (d.ig.lt_ico.<cat>); неизвестная категория — пусто, как раньше"""
    key = f'd.ig.lt_ico.{cat}'
    return T(key) if i18n.has(key) else ''

LT_CSS = f"""
.lt {{ position:absolute; left:120px; right:120px; bottom:100px; background:rgba(10,10,14,.88); border-radius:32px;
  padding:56px 70px 56px 0; display:flex; align-items:flex-start; gap:60px; }}
.bar {{ width:26px; align-self:stretch; border-radius:32px 0 0 32px; flex:none; }}
.num {{ font-size:92px; font-weight:bold; color:{IVORY}; flex:none; width:420px; text-align:center; line-height:1.1; }}
.cat {{ font-size:36px; letter-spacing:.1em; margin-top:14px; font-family:Helvetica,Arial,sans-serif; }}
.txt {{ font-size:50px; line-height:1.45; color:{IVORY}; padding-top:10px; }}
.txt b {{ color:#fff; }}
"""
KIND_COL = {'typo': '#C1272D', 'grammar': '#C1272D', 'fact': '#C1272D', 'currency': '#D9A521', 'language': '#D9A521',
            'mismatch': '#D97721', 'design': '#3A6FB5', 'other': '#D9A521'}


def ann_kind(kind):
    """заголовок плашки стрелки «ТЗ-07 · <класс>». currency/language на графике звучат иначе, чем в ТЗ (d.ig.*);
    остальные — core.kind_up. Русская графика знала только 8 классов (прочие → ПРАВКА) — так и остаётся;
    английская называет и foreign_trace/structure/check_source своими именами."""
    if kind in ('currency', 'language'):
        return T(f'd.ig.kind_{kind}')
    if kind in ('typo', 'grammar', 'fact', 'mismatch', 'design', 'other') or (
            LANG == 'en' and i18n.has(f'core.kind_up.{kind}')):
        return T(f'core.kind_up.{kind}')
    return T('core.kind_up.other')


def clean_sp(t):
    return re.sub(r'\s+', ' ', str(t)).strip()


def sample_colours(frame, bbox):
    """Цвет подложки (фон вокруг bbox) и цвет титра (насыщенные пиксели внутри bbox) — чтобы
    нарисованное исправление выглядело «родным» для кадра, а не чёрной заплаткой."""
    from PIL import Image
    import colorsys
    im = Image.open(frame).convert('RGB')
    W, H = im.size
    x, y, w, h = bbox
    x0, y0, x1, y1 = int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)
    px = im.load()
    ring, ink = [], []
    step = 4
    for yy in range(max(0, y0 - 40), min(H, y1 + 40), step):
        for xx in range(max(0, x0 - 40), min(W, x1 + 40), step):
            r, g, b = px[xx, yy]
            inside = x0 <= xx < x1 and y0 <= yy < y1
            hh, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if inside and ss > 0.45 and vv > 0.25:
                ink.append((r, g, b))
            elif not inside:
                ring.append((r, g, b))
    def med(lst, default):
        if not lst:
            return default
        lst = sorted(lst, key=lambda c: c[0] * 0.3 + c[1] * 0.59 + c[2] * 0.11)
        return lst[len(lst) // 2]
    bg = med(ring, (16, 16, 20))
    fg = med(ink, (193, 39, 45))
    return '#%02x%02x%02x' % bg, '#%02x%02x%02x' % fg


# v7 (Роман 10.09): «хочется сумму цифрами показать, чтобы размер числа понять» — у цен два варианта
# оформления (Роман выбирает); «если ошибка в орфографии — выделяй ещё то, что исправляешь» — изменённые
# буквы драфта другим цветом с подчёркиванием (диф по typo-записи ТЗ: было → стало).
# Варианты цен — из карточки (price_variants {"ТЗ-21b": ["$30 300 000", "$30,3 МЛН"]}); зашитые две цены — данные
# YTUVI01 и идут только ему: на другом фильме его ТЗ-21b получило бы чужие суммы.
PRICE_VARIANTS = ({k: tuple(v) for k, v in (P.get('price_variants') or {}).items()} if isinstance(P.get('price_variants'), dict)
                  else {'ТЗ-21b': ('$30 300 000', '$30,3 МЛН'), 'ТЗ-21d': ('$34 800 000', '$34,8 МЛН')}
                  if P.CODE == 'YTUVI01' else {})
_PR_ALL = json.load(open(MONT / 'pravki_v2.json'))['all']


def fix_spans(num, frag):
    """изменённые знаки текста драфта по typo-записи ТЗ (ТЗ-31b → ТЗ-31)"""
    import difflib
    frag = frag.replace('\n', ' ')                     # многострочный драфт: перенос = пробел, позиции те же
    m = re.match(r'ТЗ-(\d+)', num)
    ty = (_PR_ALL[int(m.group(1)) - 1].get('typo') or []) if m else []
    spans = []
    for t in ty:                                        # драфт может нести несколько правок (ТЗ-32b: 2 строки)
        if t['now'] in frag or frag in t['now']:
            spans += spans_for_fragment(t['was'], t['now'], frag)
    if not spans and ty:
        t = max(ty, key=lambda t: difflib.SequenceMatcher(None, t['now'], frag).ratio())
        if difflib.SequenceMatcher(None, t['now'], frag).ratio() >= 0.6:
            spans = spans_for_fragment(t['was'], t['now'], frag)
    return sorted(set(spans))


_SUB = str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789')
_SUP = str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻', '0123456789+−')


def subsup(s):
    """индексы формул настоящими <sub>/<sup> (в Georgia «₂₃» падали на базовую линию — QA 10.09, ТЗ-34)"""
    s = re.sub('[₀-₉]+', lambda m: '<sub>' + m.group(0).translate(_SUB) + '</sub>', s)
    return re.sub('[⁰¹²³⁴-⁹⁺⁻]+', lambda m: '<sup>' + m.group(0).translate(_SUP) + '</sup>', s)


def hl_html(text, spans, col):
    out, k = [], 0
    for s, e in spans:
        out.append(subsup(esc(text[k:s])))
        out.append(f'<span style="color:{col}; text-decoration:underline; text-decoration-thickness:.07em; '
                   f'text-underline-offset:.12em">{subsup(esc(text[s:e]))}</span>')
        k = e
    out.append(subsup(esc(text[k:])))
    return ''.join(out)


def _lum(hexcol):
    try:
        r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
    except (ValueError, TypeError):
        return 0.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


if want('G'):
    aj = W6 / 'audit_v6.json'
    # было «нет audit_v6.json — пропуск»: стадия тихо проходила без единой стрелки ошибки
    audit = P.audit_or_die(aj, 'аудит экранов (стрелки ошибок, стадия G)')
    if audit is None:
        print('G: аудит пропущен по YTAI_NO_AUDIT=1 — стрелок нет')
    else:
        for a in audit.get('annotations', []):
            num = a['tz']
            x, y, w, h = a['bbox']
            cx, cy = (x + w / 2) * 3840, (y + h / 2) * 2160
            rx, ry = max(w * 3840 / 2 + 70, 160), max(h * 2160 / 2 + 60, 90)
            col = KIND_COL.get(a['kind'], '#D9A521')
            # плашка — с той стороны, где свободнее; не перекрывает эллипс
            if cx < 1920:
                px = min(cx + rx + 120, 3840 - 1300)
            else:
                px = max(cx - rx - 120 - 1250, 120)
            py = cy + ry + 60 if cy < 1080 else max(cy - ry - 60 - 320, 80)
            ax, ay = (px if px > cx else px + 1250), py + 80
            tx = cx + rx * (0.8 if ax > cx else -0.8)
            ty = cy + (ry * 0.6 if ay > cy else -ry * 0.6)
            body = f"""
<svg width="3840" height="2160" style="position:absolute;inset:0">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse">
    <path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker></defs>
  <ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx:.0f}" ry="{ry:.0f}" fill="none" stroke="{col}" stroke-width="14" stroke-dasharray="34 22"/>
  <line x1="{ax:.0f}" y1="{ay:.0f}" x2="{tx:.0f}" y2="{ty:.0f}" stroke="{col}" stroke-width="12" marker-end="url(#arr)"/>
</svg>
<div class="plate" style="left:{px:.0f}px; top:{py:.0f}px; border-left:14px solid {col}">
  <div class="h" style="color:{col}">{tz_label(num)} · {ann_kind(a['kind'])}</div><div class="t">{a['text']}</div></div>"""
            page(f'ann_tz{num[3:]}', body, ANN_CSS, draft=False)
            # нарисованное исправление (V3): патч поверх ошибочного элемента + правильный текст
            fx = a.get('fix')
            if fx and fx.get('text'):
                fh = h * 2160
                pad = fx.get('pad', 40)                           # fix.pad — узкая заплатка, чтобы не резать соседние буквы
                fx_lines = fx['text'].split('\n')                 # многострочный титр (ТЗ-32b: 2 строки плашки)
                # кегль считаем И по высоте, И по ширине: иначе длинная замена («1000 ЛЕТ» → «ТЫСЯЧИ ЛЕТ»)
                # вылезает за заплатку. Заплатке разрешаем подрасти до 1.35 ширины рамки.
                maxlen = max(len(x) for x in fx_lines) or 1
                fs = max(40, min(fh * (0.78 if len(fx_lines) == 1 else 0.90 / len(fx_lines)),
                                 w * 3840 * 1.35 / (maxlen * 0.62), 420))
                txt_h = fs * len(fx_lines)
                pw = max(w * 3840, maxlen * fs * 0.62)            # заплатка закрывает старый текст целиком
                try:
                    bgc, fgc = sample_colours(a['frame'], (x, y, w, h))
                except Exception:
                    bgc, fgc = BG, RED
                col_t = fx.get('color', fgc)
                # контраст: сэмплер иногда берёт цвет, почти совпадающий с фоном заплатки —
                # тогда драфт нечитаем (ТЗ-68: светло-серое по бежевому). Подменяем на чёрный/слоновую кость.
                if abs(_lum(col_t) - _lum(bgc)) < 0.30:
                    col_t = BG if _lum(bgc) > 0.5 else IVORY
                L, Ty = x * 3840, y * 2160                       # Ty, не T: T — это i18n.T (перетёр бы его для H/I)
                patch = (f'<div class="fixpatch" style="left:{L - pad:.0f}px; top:{Ty - pad:.0f}px; '
                         f'width:{pw + 2 * pad:.0f}px; height:{max(fh, txt_h) + 2 * pad:.0f}px; background:{bgc}; border-radius:8px"></div>')

                def badge(extra=''):          # fix.badge='above' — плашка над заплаткой (если снизу идёт другой текст)
                    top = Ty - pad - 16 - 56 if fx.get('badge') == 'above' else Ty + fh + pad + 16
                    return (f'<div class="fixbadge" style="left:{L:.0f}px; top:{top:.0f}px">'
                            f'{T("d.ig.fix_badge", num=tz_label(num), extra=extra)}</div>')
                spans = fix_spans(num, fx['text'])
                hl_col = '#1F4FD1' if _lum(bgc) > 0.55 else '#FFD23F'
                # fix.font='sans' — плашки ката в гротеске (белые подписи), чтобы драфт не выглядел сменой шрифта
                ff = "font-family:'Helvetica Neue',Helvetica,Arial,sans-serif; " if fx.get('font') == 'sans' else ''
                body = (patch + f'<div class="fixtxt" style="{ff}left:{L:.0f}px; top:{Ty + (fh - txt_h) / 2:.0f}px; '
                        f'font-size:{fs:.0f}px; color:{col_t}">{hl_html(fx["text"], spans, hl_col).replace(chr(10), "<br>")}</div>'
                        + badge(T('d.ig.fix_underlined') if spans else ''))
                page(f'fix_tz{num[3:]}', body, FIX_CSS, draft=False)
                pv = PRICE_VARIANTS.get(num)
                if pv:                                          # цены: вариант А и вариант Б
                    digits, short = pv
                    W = w * 3840
                    fa = min(fh * 0.78, W / (len(digits) * 0.62))
                    page(f'fix_tz{num[3:]}_A', patch + f'<div class="fixtxt" style="left:{L:.0f}px; '
                         f'top:{Ty + (fh - fa) / 2:.0f}px; font-size:{fa:.0f}px; color:{col_t}">{esc(digits)}</div>'
                         + badge(T('d.ig.fix_var_a')), FIX_CSS, draft=False)
                    fb = min(fh * 0.58, W / (len(short) * 0.62))
                    fb2 = fb * 0.40
                    tb = Ty + (fh - fb - fb2 * 1.15) / 2
                    page(f'fix_tz{num[3:]}_B', patch
                         + f'<div class="fixtxt" style="left:{L:.0f}px; top:{tb:.0f}px; font-size:{fb:.0f}px; color:{col_t}">{esc(short)}</div>'
                         + f'<div class="fixtxt" style="left:{L:.0f}px; top:{tb + fb * 1.08:.0f}px; font-size:{fb2:.0f}px; color:{col_t}">{esc(digits)}</div>'
                         + badge(T('d.ig.fix_var_b')), FIX_CSS, draft=False)
        # LT-плашки для новых ТЗ (стиль v5)
        pravki = json.load(open(MONT / 'pravki_v2.json'))['all']
        start = int(audit.get('new_tz_from', 33))
        for i, p in enumerate(pravki):
            if p.get('status') == 'rejected':
                continue
            num = tz_label(i + 1)                          # «ТЗ-07» / «FIX-07» — надпись на плашке
            col = LT_COL.get(p['category'], '#777')
            # на плашке — только «что сделать» (Роман 10.09: сплошной текст не читается)
            pt = p.get('parts') or {}

            def flat(v):                                   # v7: пункты списков → «заголовок a; b; c»
                if isinstance(v, dict):
                    its = v.get('items') if isinstance(v.get('items'), list) else []
                    h = clean_sp(v.get('h') or '')
                    return (h + ' ' if h else '') + '; '.join(clean_sp(i) for i in its)
                return clean_sp(v)
            nado = ' · '.join(f for f in (flat(x) for x in (pt.get('do') or [])) if f) or \
                ' '.join(clean_sp(ln) for ln in p['nado'].split('\n') if ln.strip())
            if len(nado) > 400:
                nado = nado[:397] + '…'
            page(f'tz_lt_{i + 1:02d}', f'<div class="lt"><div class="bar" style="background:{col}"></div>'
                 f'<div class="num">{num}<div class="cat" style="color:{col}">{lt_ico(p["category"])}</div></div>'
                 f'<div class="txt"><b>{esc(p["title"])}.</b> {esc(nado)}</div></div>', LT_CSS)

# ═══════════ H. КАРТА СТРУКТУРЫ: главы + подглавы одним кадром (Роман 10.09) ═══════════
# «Главы и подглавы описать с нормальным форматированием и создать пример кадра для
#  удобства восприятия всей структуры» → info_structure_map.png (полный обзор для дока и
#  монтажёра) + info_videomap_chNN.png (зрительская «карта выпуска» с «ВЫ ЗДЕСЬ»).
# CH_BOUNDS / NEW_CH — из make_infographics_v6_data (единый источник со списками ТЗ-30/74 в s10)


def _tc(x):
    return f'{int(x) // 60}:{int(x) % 60:02d}'


STRUCT_CSS = f"""
.sm {{ position:absolute; inset:0; background:{BG}; padding:64px 84px 56px; }}
.sm .hd {{ text-align:center; }}
.sm .hd h1 {{ font-size:92px; font-weight:bold; letter-spacing:.05em; text-transform:uppercase; }}
.sm .hd h1 .r {{ color:{RED}; }}
.sm .hd .s {{ font-family:Helvetica,Arial,sans-serif; font-size:31px; color:{MUT};
  letter-spacing:.16em; margin-top:12px; }}
.cols {{ display:flex; gap:84px; margin-top:40px; }}
.col {{ flex:1; }}
.chb {{ display:flex; gap:24px; margin-bottom:24px; }}
.chb .bar {{ width:10px; border-radius:5px; flex:none; }}
.chb .bd {{ flex:1; min-width:0; }}
.chb .lab {{ font-family:Helvetica,Arial,sans-serif; font-size:26px; letter-spacing:.2em;
  font-weight:bold; display:flex; align-items:center; gap:15px; }}
.chb .lab .tc {{ color:{MUT}; letter-spacing:.06em; }}
.chb .lab .plus {{ background:{RED}; color:{IVORY}; border-radius:8px; padding:3px 12px;
  font-size:21px; letter-spacing:.08em; }}
.chb .nm {{ font-size:52px; font-weight:bold; line-height:1.12; margin-top:5px; letter-spacing:.02em; }}
.chb ul {{ list-style:none; margin:10px 0 0 2px; }}
.chb li {{ font-size:34px; color:{IVORY}; opacity:.9; line-height:1.32; display:flex; gap:16px;
  margin-top:6px; }}
.chb li .t {{ font-family:ui-monospace,Menlo,monospace; font-size:28px; color:{MUT};
  min-width:126px; padding-top:5px; }}
.chb li .a {{ color:{MUT}; }}
.chb .none {{ font-size:31px; color:{RED}; margin-top:9px; }}
.sm.here .chb {{ opacity:.40; }}
.sm.here .chb.on {{ opacity:1; }}
.chb.on .nm {{ color:{RED}; }}
.chb .now {{ background:{IVORY}; color:{BG}; border-radius:8px; padding:3px 12px;
  font-size:21px; letter-spacing:.08em; }}
.lg {{ margin-top:30px; border-top:2px solid rgba(242,234,216,.22); padding-top:24px; }}
.lgh {{ font-family:Helvetica,Arial,sans-serif; font-size:25px; letter-spacing:.2em;
  color:{RED}; font-weight:bold; }}
.lgi {{ font-size:32px; color:{IVORY}; opacity:.88; line-height:1.35; margin-top:12px; }}
.lgi b {{ color:{MUT}; font-family:Helvetica,Arial,sans-serif; font-size:26px; letter-spacing:.06em; }}
.foot2 {{ position:absolute; left:84px; right:84px; bottom:26px; display:flex;
  justify-content:space-between; font-family:Helvetica,Arial,sans-serif; font-size:23px;
  color:rgba(255,255,255,.42); letter-spacing:.1em; }}
"""


def _ch_lab(n):
    """подпись главы по нумерации Романа (ch_no_final): содержательные 01..08, хук и финал без номера"""
    fin = str(CH_NO_FINAL.get(f'{n:02d}', f'{n:02d}'))
    return f'{T("core.chapter")} {fin}' if fin not in ('—', '') else T('d.ig.sm_no_no')


def _struct_blocks(here=None, subs=True):
    out = []
    for a, b, n in CH_BOUNDS:
        acc = CH_ACCENT[n - 1]
        items = [(s, l) for s, ch, l in SUB if a <= s < b]
        li = ''.join('<li><span class="t">%s</span><span><span class="a">▸</span> %s</span></li>'
                     % (_tc(s), l) for s, l in items) if subs else ''
        none = '' if (items or not subs) else f'<div class="none">{T("d.ig.sm_none")}</div>'
        plus = f'<span class="plus">{T("d.ig.sm_plus")}</span>' if n in NEW_CH else ''
        now = f'<span class="now">{T("d.ig.here")}</span>' if here == n else ''
        out.append(
            '<div class="chb %s"><div class="bar" style="background:%s"></div><div class="bd">'
            '<div class="lab" style="color:%s">%s<span class="tc">%s–%s</span>%s%s</div>'
            '<div class="nm">%s</div>%s%s</div></div>'
            % ('on' if here == n else '', acc, acc, _ch_lab(n), _tc(a), _tc(b), plus, now,
               CH_NAME[n - 1], ('<ul>%s</ul>' % li) if li else '', none))
    return out


if want('H'):
    # карта на 4K держит примерно 50 строк в колонке; у ката v2 подглав 62 против 36 у первого —
    # низ уезжал за кадр. Масштаб считаем по фактическому числу строк, а не подбираем руками.
    # В колонку на 4K влезает ~40 строк (левая несёт ещё и легенду). У ката v2 подглав 62 (у первого было 36) — в две колонки
    # низ уезжал за кадр. Считаем строки по блокам и раскладываем в столько колонок, сколько нужно.
    _wt = [2 + sum(1 for s_, ch_, _ in SUB if a <= s_ < b) for a, b, _ in CH_BOUNDS]
    _ncol = 2 if sum(_wt) <= 70 else 3
    STRUCT_CSS += '\n.cols { gap:56px; }\n.chb .nm { font-size:46px; }\n.chb li { font-size:30px; }' \
                  '\n.chb li .t { font-size:25px; min-width:104px; }' if _ncol > 2 else ''
    bl = _struct_blocks()
    # шапка и легенда — из карточки проекта: было зашито «10 ГЛАВ · 36 ПОДГЛАВ · кат 40:40»
    # и номера ТЗ первого фильма, то есть карта структуры врала на любом другом кате.
    half = (len(bl) + 1) // 2
    _legend = [f'<div class="lgi">{T("d.ig.sm_legend_map")}</div>',
               f'<div class="lgi">{T("d.ig.sm_legend_sub", n=len(SUB))}</div>']
    _legend += [f'<div class="lgi">{T("d.ig.sm_legend_prog", k=CH_NO_FINAL.get(k, k), title=v[0], n=len(v[1]))}</div>'
                for k, v in sorted(PROG.items())]
    _legend += [f'<div class="lgi">{T("d.ig.sm_legend_new", n=n)}</div>' for n in sorted(NEW_CH)]
    lim = (sum(_wt) + (len(_legend) + 1 if _ncol == 2 else 0)) / _ncol
    cols, cur_col, load = [], [], 0.0
    for b, w in zip(bl, _wt):                       # раскладка по колонкам с балансом по строкам
        if cur_col and load + w / 2 > lim and len(cols) < _ncol - 1:
            cols.append(cur_col); cur_col, load = [], 0.0
        cur_col.append(b); load += w
    cols.append(cur_col)
    lg = (f'<div class="lg"><div class="lgh">{T("d.ig.sm_legend_h")}</div>' + ''.join(_legend) + '</div>')
    body = ''.join('<div class="col">' + ''.join(c) + (lg if (_ncol == 2 and i == 0) else '') + '</div>'
                   for i, c in enumerate(cols))
    _html = (
        '<div class="sm"><div class="hd"><h1>'
        + T('d.ig.sm_h1', nch=sum(1 for _, _, n in CH_BOUNDS
                                  if str(CH_NO_FINAL.get(f'{n:02d}', f'{n:02d}')) not in ('—', '')),
            nsub=len(SUB)) + '</h1>'
        f'<div class="s">{T("d.ig.sm_sub", tc=_tc(P.duration_sec()))}</div></div>'
        f'<div class="cols">{body}</div>' + ('' if _ncol == 2 else lg) +
        f'<div class="foot2"><span>{T("d.ig.sm_foot_plus")}</span>'
        f'<span>{DRAFT_TXT}</span></div></div>')
    print(f'  карта структуры: строк {sum(_wt)}, колонок {_ncol}')
    page('info_structure_map', _html, STRUCT_CSS, draft=False)
    VM_CSS = STRUCT_CSS + """
.vm { position:absolute; inset:0; background:%s; display:flex; flex-direction:column;
  align-items:center; justify-content:center; padding:80px 0; }
.vm h1 { font-size:104px; font-weight:bold; letter-spacing:.05em; text-transform:uppercase; }
.vm h1 .r { color:%s; }
.vm .s { font-family:Helvetica,Arial,sans-serif; font-size:32px; color:%s; letter-spacing:.16em;
  margin-top:14px; }
.vm .list { margin-top:56px; }
.vm .row { display:flex; align-items:center; gap:34px; padding:13px 0; opacity:.42; }
.vm .row.on { opacity:1; }
.vm .row .n { font-family:Helvetica,Arial,sans-serif; font-size:34px; font-weight:bold;
  min-width:74px; text-align:right; }
.vm .row .nm { font-size:64px; font-weight:bold; letter-spacing:.02em; }
.vm .row.on .nm { color:%s; }
.vm .row .here { background:%s; color:%s; font-family:Helvetica,Arial,sans-serif; font-size:26px;
  font-weight:bold; letter-spacing:.08em; border-radius:9px; padding:5px 16px; margin-left:10px; }
""" % (BG, RED, MUT, RED, IVORY, BG)
    for hn in range(1, len(CH_BOUNDS) + 1):          # было range(1, 11) — 10 глав первого фильма
        rows = ''.join(
            '<div class="row %s"><div class="n" style="color:%s">%02d</div>'
            '<div class="nm">%s</div>%s</div>'
            % ('on' if n == hn else '', CH_ACCENT[n - 1], n, CH_NAME[n - 1],
               '<span class="here">%s</span>' % T('d.ig.here') if n == hn else '')
            for a, b, n in CH_BOUNDS)
        page('info_videomap_ch%02d' % hn,
             '<div class="vm"><h1>%s</h1>'
             '<div class="s">%s</div>'
             '<div class="list">%s</div></div>'
             '<div class="foot2"><span>%s</span>'
             '<span>%s</span></div>'
             % (T('d.ig.vm_h1'), T('d.ig.vm_sub'), rows, T('d.ig.vm_foot', n=hn), DRAFT_TXT), VM_CSS, draft=False)


# ═══════════ I. КАРТА НАЗВАНИЙ: что звучит → как подписываем (Роман 11.09) ═══════════
# «нужны рендеры, тоже название, чтобы видеть, когда она называется, как их показывать…
#  иначе очень легко путаться в местах, сопоставлениях, забываешь быстро»
NAME_CSS = STRUCT_CSS + f"""
.nr {{ display:flex; gap:30px; align-items:flex-start; margin-top:22px; }}
.nr .said {{ min-width:760px; max-width:760px; font-size:50px; font-weight:bold; color:{IVORY}; line-height:1.2; }}
.nr .said i {{ display:block; font-family:Helvetica,Arial,sans-serif; font-size:29px; font-style:normal;
  color:{MUT}; letter-spacing:.04em; margin-top:4px; }}
.nr .arr {{ color:{RED}; font-size:34px; padding-top:4px; }}
.nr .scr {{ flex:1; font-size:46px; color:{IVORY}; line-height:1.25; }}
.nr .scr i {{ display:block; font-family:Helvetica,Arial,sans-serif; font-size:29px; font-style:normal;
  color:{MUT}; margin-top:4px; }}
.hdr2 {{ display:flex; gap:30px; font-family:Helvetica,Arial,sans-serif; font-size:25px;
  letter-spacing:.2em; color:{RED}; font-weight:bold; border-bottom:2px solid rgba(242,234,216,.22);
  padding-bottom:12px; }}
.hdr2 .a {{ min-width:790px; }}
"""


def _nrow(said, sub_said, screen, sub_scr):
    return ('<div class="nr"><div class="said">%s%s</div><div class="arr">→</div>'
            '<div class="scr">%s%s</div></div>'
            % (said, f'<i>{sub_said}</i>' if sub_said else '',
               screen, f'<i>{sub_scr}</i>' if sub_scr else ''))


def _namecard(name, title, rows, note, foot):
    half = (len(rows) + 1) // 2
    head = (f'<div class="hdr2"><span class="a">{T("d.ig.nm_head_said")}</span>'
            f'<span>{T("d.ig.nm_head_screen")}</span></div>')
    page(name,
         f'<div class="sm"><div class="hd"><h1>{T("d.ig.nm_h1")}</h1>'
         f'<div class="s">{title}</div></div>'
         f'<div class="cols"><div class="col">{head}{"".join(rows[:half])}'
         f'<div class="lg"><div class="lgh">{T("d.ig.nm_rule")}</div><div class="lgi">{note}</div></div></div>'
         f'<div class="col">{head}{"".join(rows[half:])}</div></div>'
         f'<div class="foot2"><span>{foot}</span>'
         f'<span>{DRAFT_TXT}</span></div></div>', NAME_CSS, draft=False)


def _since(tc, n):
    """«с 3:02 · 5 раз» / «… 3 раза» (ru), «from 3:02 · 5×» (en)"""
    few = 2 <= n % 10 <= 4 and n not in (12, 13, 14)
    return T('d.ig.nm_since_few' if few else 'd.ig.nm_since', tc=tc, n=n)


if want('I'):
    tj = json.load(open(W6 / 'terms_v6.json')) if (W6 / 'terms_v6.json').exists() else {'terms': [], 'locs': []}
    cnt_l, cnt_t = {}, {}
    for m in tj.get('locs', []):
        cnt_l[m['key']] = cnt_l.get(m['key'], 0) + 1
    for m in tj.get('terms', []):
        cnt_t[m['key']] = cnt_t.get(m['key'], 0) + 1
    first_l, first_sec = {}, {}
    for m in sorted(tj.get('locs', []), key=lambda m: m['t']):
        first_l.setdefault(m['key'], m['tc'])
        first_sec.setdefault(m['key'], m['t'])
    first_t = {}
    for m in sorted(tj.get('terms', []), key=lambda m: m['t']):
        first_t.setdefault(m['key'], m['tc'])

    rows = []
    fam_order = sorted({place_family(k) for k in cnt_l},
                       key=lambda f: min(first_sec[k] for k in cnt_l if place_family(k) == f))
    seq = [k for f in fam_order
           for k in sorted((k for k in cnt_l if place_family(k) == f),
                           key=lambda k: (bool(PLACE[k].get('parent')), first_sec[k]))]
    for k in seq:
        pl = PLACE[k]
        said = pl['ru'] + (f' / {pl["old"]}' if pl.get('old') else '')
        n = cnt_l[k]
        sub_said = _since(first_l[k], n)
        if pl.get('en'):
            sub_said += T('d.ig.nm_on_screen') + ', '.join(pl['en'][:2])
        if pl.get('parent'):
            screen = pl['ru']
            sub_scr = pl.get('sub', '').split(' — ')[0]
        else:
            screen = pl['label']
            sub_scr = pl.get('sub', '')[:70]
        rows.append(_nrow(said, sub_said, screen, sub_scr))
    _namecard('info_namemap_places', T('d.ig.nm_places_title', n=len(rows)), rows,
              T('d.ig.nm_places_note'), T('d.ig.nm_places_foot'))

    trows = []
    order = {t[0]: i for i, t in enumerate(TERMS)}
    for k, ttl, sub in sorted(((t[0], t[2], t[3]) for t in TERMS if t[0] in cnt_t),
                              key=lambda x: first_t.get(x[0], '99:99')):
        x = TERM_EXTRA.get(k) or {}
        n = cnt_t[k]
        said = (x['en'][0] if x.get('lead') == 'en' and x.get('en') else ttl)
        sub_said = _since(first_t.get(k, ''), n)
        if x.get('read'):
            sub_said += T('d.ig.nm_read', r=x['read'])
        trows.append(_nrow(said, sub_said, ttl, sub))
    half = (len(trows) + 1) // 2
    _namecard('info_namemap_terms', T('d.ig.nm_terms_title', h=half, n=len(trows)), trows[:half],
              T('d.ig.nm_terms_note'), T('d.ig.nm_terms_foot'))
    _namecard('info_namemap_terms_2', T('d.ig.nm_terms2_title', a=half + 1, n=len(trows)), trows[half:],
              T('d.ig.nm_terms2_note'), T('d.ig.nm_terms_foot'))

print('\nготово →', OUT)


# ═══════════ J. ЗАСТАВКИ ГЛАВ: плашка ch_ov_NN + три варианта дизайна ═══════════
# Генератора плашек глав в репо не было: ch_ov_*.png первого фильма сделал разовый скрипт
# в ~/Downloads, а make_review_v6._ch_plate() просто подбирал готовый файл. Переносим сюда.
#
# Роман 22.09.2026: «мне не нравится дизайн глав… главы + подглавы и на весь экран, может быть
# контраста не хватает». В кате v2 действительно два несогласованных приёма — мелкое «01. РУБИН»
# в углу и полноэкранная засечка без номера, и оба ивори по светлому фону.
# Вариант берём из карточки (`ch_plate_variant`: a | b | c), по умолчанию «a».
CHOV_VARIANT = str(P.get('ch_plate_variant', 'a')).lower()
# кадр под демо: секунды БЕЗ экранного текста (иначе макет ложится на старый титр)
CHOV_DEMO_SECS = [int(x) for x in P.get('ch_demo_secs', [])] or [790]
CHOV_CSS = f"""
.pl {{ position:absolute; inset:0; overflow:hidden; }}
.pl .shot {{ position:absolute; inset:0; background-size:cover; background-position:center; }}
.pl .num {{ font-family:Helvetica,Arial,sans-serif; font-weight:bold; letter-spacing:.28em;
            text-transform:uppercase; }}
.pl .nm {{ font-family:{FONT}; font-weight:bold; text-transform:uppercase; letter-spacing:.03em;
           color:{IVORY}; line-height:1.02; }}
.pl .sub {{ font-family:{FONT}; color:{IVORY}; opacity:.92; }}
.pl .rule {{ background:{RED}; border-radius:4px; }}

/* A: scrim */
.va .scrim {{ position:absolute; inset:0; background:rgba(8,8,10,.72); }}
.va .box {{ position:absolute; inset:0; display:flex; flex-direction:column; align-items:center;
            justify-content:center; gap:34px; text-align:center; }}
.va .num {{ font-size:104px; color:#E8586A; }}
.va .nm {{ font-size:380px; max-width:3400px; text-shadow:0 10px 50px rgba(0,0,0,.92); }}
.va .rule {{ width:460px; height:14px; }}
.va .sub {{ font-size:120px; opacity:.88; }}

/* B: side panel */
.vb .panel {{ position:absolute; left:0; top:0; bottom:0; width:1900px;
              background:linear-gradient(90deg, rgba(10,10,14,.97) 72%, rgba(10,10,14,0)); }}
.vb .box {{ position:absolute; left:170px; top:0; bottom:0; width:1560px; display:flex;
            flex-direction:column; justify-content:center; gap:30px; }}
.vb .num {{ font-size:92px; color:#E8586A; }}
.vb .nm {{ font-size:300px; }}
.vb .rule {{ width:360px; height:13px; }}
.vb .sub {{ font-size:104px; opacity:.86; }}

/* C: lower band */
.vc .band {{ position:absolute; left:0; right:0; bottom:0; height:1180px;
             background:linear-gradient(0deg, rgba(8,8,10,.95) 42%, rgba(8,8,10,0)); }}
.vc .box {{ position:absolute; left:170px; right:170px; bottom:150px; }}
.vc .num {{ font-size:92px; color:#E8586A; margin-bottom:26px; }}
.vc .nm {{ font-size:290px; }}
.vc .rule {{ width:340px; height:12px; margin:32px 0 24px; }}
.vc .sub {{ font-size:100px; opacity:.86; }}
"""


def _chov_body(variant, num, name, sub, shot):
    """плашка главы: номер, имя, подглава; shot — кадр-подложка (для демо) или пусто (альфа)"""
    v = {'a': 'va', 'b': 'vb', 'c': 'vc'}[variant]
    bg = f'<div class="shot" style="background-image:url(\'file://{shot}\')"></div>' if shot else ''
    lay = {'a': '<div class="scrim"></div>', 'b': '<div class="panel"></div>',
           'c': '<div class="band"></div>'}[variant]
    subl = f'<div class="sub">▸ {esc(sub)}</div>' if sub else ''
    return (f'<div class="pl {v}">{bg}{lay}<div class="box">'
            f'<div class="num">{T("core.chapter")} {num}</div>'
            f'<div class="nm">{esc(name)}</div><div class="rule"></div>{subl}</div></div>')


def _first_sub(no):
    """первая подглава главы — для примера в демо; у YTUVI01 подглав пока нет"""
    for x in SUB:
        if int(x[1]) == int(no):
            return x[2]
    return ''


if want('J'):
    for i, nm in enumerate(CH_NAME):                       # CH_NAME — список, индекс = глава − 1
        page(f'ch_ov_{i + 1:02d}', _chov_body(CHOV_VARIANT, f'{i + 1:02d}', nm, '', ''), CHOV_CSS)
    # три варианта на одном кадре — Роману на выбор (поверх настоящей заставки главы)
    di = 4 if len(CH_NAME) >= 5 else 0
    demo_no = f'{di + 1:02d}'
    shot = next((f for f in (W6 / 'hires').glob('h0*.jpg')
                 if f.name in {n: n for n in [f'h{t:04d}.jpg' for t in CHOV_DEMO_SECS]}), None) \
        or OUT / f'ch_card_{demo_no}.jpg'
    if shot.exists():
        for v in ('a', 'b', 'c'):
            page(f'ch_demo_{v}', _chov_body(v, demo_no, CH_NAME[di], _first_sub(di + 1), shot),
                 CHOV_CSS, draft=False)
            flatten_jpg(f'ch_demo_{v}')      # вкладка «Главы» вставляет плоский jpg, а не 4K с альфой
    else:
        print(f'  !! нет кадра {shot.name} — демо вариантов не собрал')
    print(f'заставки глав: {len(CH_NAME)} (вариант {CHOV_VARIANT}) + демо a/b/c по главе {demo_no}')


# ═══════════ K. «БЫЛО → НАДО»: карточка замен для ТЗ со списком правок ═══════════
# Роман 22.09.2026 к ТЗ-16: «Показывай пример как было текст и как надо». Драфт `fix_tzNN`
# (стадия G) рисует ОДНУ замену по bbox и для такой ТЗ не годится: там несколько подписей в
# разных местах кадра (у ТЗ-16 — четыре английские подписи на научной иллюстрации).
# Источник — поле `wasnow: [[было, надо], …]` записи ТЗ (ставится через pravki/tz_overrides.json).
WASNOW_CSS = f"""
.wn {{ position:absolute; inset:0; background:{BG}; padding:110px 140px; }}
.wn .hd {{ font-family:Helvetica,Arial,sans-serif; font-size:48px; letter-spacing:.2em; color:{MUT}; }}
.wn .ttl {{ font-size:104px; font-weight:bold; line-height:1.1; margin:26px 0 70px; letter-spacing:.02em; }}
.wn table {{ width:100%; border-collapse:collapse; }}
.wn th {{ font-family:Helvetica,Arial,sans-serif; font-size:44px; letter-spacing:.18em; text-align:left;
  padding-bottom:28px; border-bottom:6px solid rgba(255,255,255,.18); }}
.wn th.a {{ color:{RED}; width:46%; }}
.wn th.b {{ color:#3FA34D; padding-left:90px; }}
.wn td {{ font-size:62px; line-height:1.32; padding:38px 0; vertical-align:top;
  border-bottom:3px solid rgba(255,255,255,.10); }}
.wn td.a {{ color:{MUT}; }}
.wn td.b {{ color:{IVORY}; font-weight:bold; padding-left:90px; }}
.wn td.b .ar {{ color:{RED}; font-weight:normal; margin-right:26px; }}
"""


def _wasnow_body(title, pairs, hdr_a, hdr_b):
    rows = ''.join(f'<tr><td class="a">{subsup(esc(str(a)))}</td>'
                   f'<td class="b"><span class="ar">→</span>{subsup(esc(str(b)))}</td></tr>' for a, b in pairs)
    return (f'<div class="wn"><div class="hd">{esc(T("core.lbl_do"))}</div><div class="ttl">{esc(title)}</div>'
            f'<table><tr><th class="a">{esc(hdr_a)}</th><th class="b">{esc(hdr_b)}</th></tr>{rows}</table></div>')


if want('K'):
    _pr = json.load(open(MONT / 'pravki_v2.json'))['all']
    _n = 0
    for _i, _p in enumerate(_pr, 1):
        _pairs = [x for x in (_p.get('wasnow') or []) if isinstance(x, (list, tuple)) and len(x) == 2]
        if not _pairs or _p.get('status') == 'rejected':
            continue
        page(f'wasnow_tz{_i:02d}',
             _wasnow_body(_p.get('title') or tz_label(_i), _pairs,
                          T('d.ig.wasnow_a'), T('d.ig.wasnow_b')), WASNOW_CSS)
        _n += 1
    print(f'карточек «было → надо»: {_n}')


# ═══════════ L. ЛОУЭР: подпись человека в кадре (макет монтажёру) ═══════════
# Роман 22.09.2026 к ТЗ-42/43: «Создай пример плашки». Генератора подписи человека в репо не было —
# ТЗ описывало плашку словами, а монтажёр рисовал её на глаз. Источник — поле `lower` записи ТЗ:
# {name, role?, sec?, photo?}; `sec` — секунда ката под подложку (без неё макет на альфе, как титр).
# Место — нижняя треть слева: правило самого ТЗ-41 «подпись под человеком, а не по диагонали от него».
LOWER_CSS = f"""
.lw {{ position:absolute; inset:0; overflow:hidden; }}
.lw .shot {{ position:absolute; inset:0; background-size:cover; background-position:center; }}
.lw .box {{ position:absolute; left:210px; bottom:300px; display:flex; align-items:center; gap:56px;
  background:{PANEL}; border-radius:28px; border-left:18px solid {RED}; padding:52px 86px 56px 64px; }}
.lw .ava {{ width:230px; height:230px; border-radius:50%; flex:none; background-size:cover;
  background-position:center; border:7px solid rgba(255,255,255,.22); }}
.lw .ava.empty {{ background:rgba(255,255,255,.10); }}
.lw .nm {{ font-size:132px; font-weight:bold; letter-spacing:.02em; color:{IVORY}; line-height:1.04; }}
.lw .rl {{ font-family:Helvetica,Arial,sans-serif; font-size:58px; color:{MUT}; margin-top:18px; }}
"""


def _lower_body(name, role, shot, photo):
    bg = f'<div class="shot" style="background-image:url(\'file://{shot}\')"></div>' if shot else ''
    ava = (f'<div class="ava" style="background-image:url(\'file://{photo}\')"></div>' if photo else
           '<div class="ava empty"></div>' if photo is not None else '')
    rl = f'<div class="rl">{esc(role)}</div>' if role else ''
    return (f'<div class="lw">{bg}<div class="box">{ava}'
            f'<div><div class="nm">{esc(name)}</div>{rl}</div></div></div>')


if want('L'):
    _pr = json.load(open(MONT / 'pravki_v2.json'))['all']
    _n = 0
    for _i, _p in enumerate(_pr, 1):
        _lo = _p.get('lower')
        if not isinstance(_lo, dict) or not _lo.get('name') or _p.get('status') == 'rejected':
            continue
        _sec = _lo.get('sec')
        _shot = (W6 / 'hires' / f'h{int(_sec) + 1:04d}.jpg') if _sec is not None else None
        if _shot is not None and not _shot.exists():
            print(f'  !! нет кадра {_shot.name} для {tz_label(_i)} — макет на альфе')
            _shot = None
        _photo = _lo.get('photo') or ''          # '' = кружок есть, но пустой — место под фото
        if _photo:
            _photo = Path(_photo) if Path(_photo).is_absolute() else (M.parent / _photo)
            if not _photo.exists():
                print(f'  !! нет фото {_photo} для {tz_label(_i)} — кружок пустой')
                _photo = ''
        page(f'lower_tz{_i:02d}',
             _lower_body(_lo['name'], _lo.get('role', ''), _shot, _photo if _lo.get('avatar', True) else None),
             LOWER_CSS, draft=False)
        _n += 1
    print(f'макетов лоуэров: {_n}')
