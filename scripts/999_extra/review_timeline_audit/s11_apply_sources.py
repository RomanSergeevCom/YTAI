#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S11: источники картинок → material_rich[].src (Роман 10.09: «мне надо понимать,
откуда ты их берёшь — контекст, источник; если из книги, то какая книга и ссылка на саму книгу»).

Вход: sources_research.json {items:[{img, source_title_ru, drive_link, url, license, ...}]}
(библиограф-агент: сверка md5 с архивом Digital_Originals + ссылка на сам PDF в Drive-зеркале).
Выход: pravki_v2.json — у каждой картинки-материала строка src, которую док и лист печатают
как «📚 источник: …». Идемпотентно.
"""
import json
from pathlib import Path

W6 = Path(__file__).parent
M = W6.parent / 'montage'
if (W6 / 'sources_research.json').exists():
    src = json.load(open(W6 / 'sources_research.json'))
else:
    # на новом проекте библиограф-агент ещё не ходил — это законное состояние, но не тихое
    print('!! sources_research.json нет — источники картинок НЕ проставлены (нужен прогон библиографа)')
    src = {'items': []}
fixes = json.load(open(W6 / 'sources_fixes.json')) if (W6 / 'sources_fixes.json').exists() else {}

INFO = {}
for it in src['items']:
    f = fixes.get(it['img'], {})
    it = {**it, **f}
    line = it['source_title_ru'].strip()
    links = [x for x in (it.get('drive_link'), it.get('url')) if x]
    if it.get('license'):
        line += f" · {it['license']}"
    if links:
        line += ' — ' + ' · '.join(links)
    INFO[it['img']] = line

# книги/журналы, на которые ссылаются текстовые материалы без картинки (имя PDF → Drive-ссылка
# на сам файл в зеркале архива YTUVI-Digital_Originals)
BOOKS = json.load(open(W6 / 'book_links.json')) if (W6 / 'book_links.json').exists() else {}
BOOK_TITLE = {
    'SSEF_ACG_1_Ruby': 'SSEF «Advanced Coloured Gemstones», книга 1 «Ruby» (Швейцарский геммологический институт)',
    'SSEF_ACG_3_Corundum_Treatments': 'SSEF «Advanced Coloured Gemstones», книга 3 «Corundum Treatments»',
    '1965-07_JoG_v9n11': 'журнал Gem-A «The Journal of Gemmology», июль 1965, т.9 №11',
}
import re as _re

pr = json.load(open(M / 'pravki_v2.json'))

# v7 (Роман 10.09 «форматируй лучше»): у наших драфтов источник — короткой строкой, без повтора длинного
# хвоста у каждой картинки. Старые авто-тексты считаются авто (перезаписываются), ручные src — нет.
OLD_AUTO = {
    'кадр рендера v1 (03_Exports/YTUVI01_v1_Corundum_Ruby.mp4) с нашей отметкой ошибки — слой V5/V3 ревью-секвенции',
    'наш драфт (генератор make_infographics_v6.py, стиль канала — перерисовать); география карт — Natural Earth 50m, public domain',
}


def auto_src(img):
    if img.startswith('v6_cafe_'):
        return 'кадр рендера v1 @39:46 — общий план в кафе'
    if img.startswith(('v6_err_', 'ann_')):
        return 'кадр рендера v1 + наша отметка ошибки (стрелка — слой V5)'
    if img.startswith('fix_'):
        return 'наш драфт исправления поверх кадра v1 (слой V3) — перерисовать в стиле канала'
    if img.startswith(('map_', 'mapfull_')):
        return 'наш драфт — перерисовать в стиле канала · карта: Natural Earth 50m (public domain)'
    if img.startswith(('term_', 'termgrp_', 'sub_', 'prog_', 'info_', 'card_', 'mock_')):
        return 'наш драфт — перерисовать в стиле канала'
    if img.startswith('chapter_'):
        return 'стоп-кадр заставки главы из рендера v1'
    return None


n = miss = 0
for p in pr['all']:
    for mr in p.get('material_rich') or []:
        img = mr.get('img')
        if not img:
            pdfs = _re.findall(r'([\w\-\.]+)\.pdf', mr.get('t', ''))
            for base in pdfs:
                key = base.replace('_RESTORED', '')
                link = BOOKS.get(base + '.pdf') or BOOKS.get(key + '.pdf')
                if link:
                    mr['src'] = f"{BOOK_TITLE.get(key, base)} — файл книги в архиве: {link}"
                    n += 1
                    break
            continue
        manual = mr.get('src') and not mr.get('src_auto') and mr['src'] not in OLD_AUTO
        if img in INFO:
            mr['src'] = INFO[img]
            mr.pop('src_auto', None)
            n += 1
        elif manual:                             # источник задан вручную (tz_overrides)
            n += 1
        elif auto_src(img):
            mr['src'] = auto_src(img)
            mr['src_auto'] = True
            n += 1
        else:
            miss += 1
            print('  без источника:', img)
json.dump(pr, open(M / 'pravki_v2.json', 'w'), ensure_ascii=False, indent=1)
print(f'источники проставлены: {n} · без источника: {miss}')
