# -*- coding: utf-8 -*-
"""Каталог терминов и мест для плашек-определений V3 — ЗАГРУЗЧИК (данные в JSON).

Источники (сливаются по key, фильм перебивает канал):
  1. профиль канала: YTs/{CH}/review_profile.json → "terms_base_file" (обычно review_terms_base.json рядом)
  2. фильм: {05_Review}/review_terms.json (ключ карточки terms_file; необязателен)

КАНОН НАЗВАНИЙ (решение Романа, действует для ТЗ-02/14/15/16/75/76):
  1. Страна на экране — современное имя первым, старое в скобках: «МЬЯНМА (БИРМА)».
  2. Пояснение про переименование даём ОДИН раз, при первом упоминании (поле note).
  3. Город/долина/месторождение всегда подписаны своей страной («долина в Мьянме (Бирме)»).
  4. Термин: русское имя крупно, оригинал мелко (канон ТЗ-14), объяснение — одна мысль ≤90 знаков.

Экспорты те же, что были у зашитого каталога (их позиционно распаковывают четыре скрипта):
  TERMS      [(key, rx, title, sub, def), …]
  TERM_EXTRA {key: {en, read, lead, screen_note, why, was, read_of}}
  PLACES     [dict(key, en, kind, parent, role, rx, ru, old, renamed, region, points, sub, note, screen_note, read_note, label)]
  PLACE      {key: place}; place_family(key)
  MAP_WINDOWS [(t0, t1, key, note), …]
  LOCS       [(key, rx, region, points, label), …]; TERM_RX; LOC_RX
  CONFUSABLES [(wrong, right), …]; CANON_WORDS [str]
Схема JSON — docs/contracts.md §3.
"""
import json
import re
from pathlib import Path

from _bootstrap import P, REVIEW_DIR  # noqa: E402


def _load(path):
    path = Path(path)
    if not path.exists():
        return {}
    d = json.loads(path.read_text(encoding='utf-8'))
    if d.get('schema') not in (None, 'review-terms-v1'):
        raise SystemExit(f'{path}: неизвестная схема {d.get("schema")}')
    return d


def _base_path():
    f = P.profile('terms_base_file')
    if not f:
        return None
    p = Path(f).expanduser()
    return p if p.is_absolute() else (P.YTAI / 'YTs' / P.CHANNEL / p)


def _film_path():
    f = P.get('terms_file', 'review_terms.json')
    p = Path(str(f)).expanduser()
    return p if p.is_absolute() else REVIEW_DIR / p


_base = _load(_base_path()) if _base_path() else {}
_film = _load(_film_path())


def _merge_list(a, b):
    out = {x['key']: dict(x) for x in a}
    for x in b:
        out[x['key']] = {**out.get(x['key'], {}), **x}
    return list(out.values())


_terms = _merge_list(_base.get('terms', []), _film.get('terms', []))
TERM_EXTRA = {**_base.get('extra', {}), **_film.get('extra', {})}
PLACES = _merge_list(_base.get('places', []), _film.get('places', []))
MAP_WINDOWS = [tuple(w) for w in (_base.get('map_windows', []) + _film.get('map_windows', []))]
CONFUSABLES = [tuple(x) for x in (_base.get('confusables', []) + _film.get('confusables', []))]
CANON_WORDS = list(dict.fromkeys(_base.get('canon_words', []) + _film.get('canon_words', [])))

TERMS = [(t['key'], t['rx'], t['title'], t.get('sub', ''), t.get('def', '')) for t in _terms]

for _p in PLACES:                      # заголовок плашки собирается по канону, а не пишется дважды
    _p.setdefault('label', f"{_p['ru']} ({_p['old']})" if _p.get('old') else _p['ru'])
    _p.setdefault('points', [])
    _p.setdefault('region', 'world')

PLACE = {p['key']: p for p in PLACES}


def place_family(key):
    """ключ страны-родителя: 'mogok' → 'burma'; страна и регион — сами себе"""
    return (PLACE.get(key) or {}).get('parent') or key


# СТАРАЯ ФОРМА — её позиционно распаковывают make_infographics_v6, s9_materials_drive, s10_format_tz
LOCS = [(p['key'], p['rx'], p['region'], p['points'], p['label']) for p in PLACES]
TERM_RX = [(k, re.compile(rx), t, s, d) for k, rx, t, s, d in TERMS]
LOC_RX = [(k, re.compile(rx), reg, pts, lab) for k, rx, reg, pts, lab in LOCS]

if __name__ == '__main__':
    print(f'terms {len(TERMS)} · extra {len(TERM_EXTRA)} · places {len(PLACES)} · map_windows {len(MAP_WINDOWS)} '
          f'· base {_base_path()} · film {_film_path()} ({"есть" if _film else "нет"})')
