# -*- coding: utf-8 -*-
"""Данные структуры Review_v6: подглавы, названия/цвета глав, перечисления.
Единый источник для make_infographics_v6.py (рендер), make_review_v6.py (раскладка) и s10 (списки ТЗ).

С 11.09.2026 всё берётся из карточки проекта prep_config.json. Раньше тут были зашиты
10 глав, 39 подглав и перечисления первого фильма (YTUVI01) — на другом кате графика,
карта структуры и списки ТЗ легли бы по чужой структуре. Значения YTUVI01 живут в его
рабочей копии: ~/Downloads/YTUVI01_Sonya_cut/work/v6/make_infographics_v6_data.py.

Ключи карточки (все, кроме chapters/ch_name, необязательны — пусто = нет такой графики):
  chapters     [[сек, "NN"], …]                     границы глав
  ch_name      {"NN": "ИМЯ"}                        названия
  ch_accent    ["#hex", …]                          цвет главы (по умолчанию палитра по кругу)
  new_ch       [N, …]                               ➕ главы, заставки которых в кате нет
  sub          [[сек, N, "подпись"], …]             подглавы (по титульным экранам ката)
  prog         {"NN": {"title": "…", "items": […]}} перечисления внутри главы
  prog_t       {"NN": [сек, …]}                     таймкоды смены пунктов перечисления
  prog_final   {"NN": [сек, "подпись итога"]}
  prog_note    {"NN:k": "пометка к k-му пункту"}
"""
from _bootstrap import P, T  # noqa: E402

_PALETTE = ['#3FA34D', '#2FB4C7', '#E08A2E', '#C74FA5', '#3F6FC7', '#D9A521']
_CHAP = P.CHAPTERS                                          # [(сек, 'NN'), …]
_NAMES = P.get('ch_name', {})

CH_NAME = [_NAMES.get(n, f'{T("core.chapter")} {n}') for _, n in _CHAP]   # имя из карточки как есть; нет — «ГЛАВА NN»/«CHAPTER NN»
CH_ACCENT = list(P.get('ch_accent') or [_PALETTE[i % len(_PALETTE)] for i in range(len(_CHAP))])

# (сек от, сек до, №) — карта структуры (стадия H) и списки ТЗ (s10) из одного места
# конец последней главы = конец ката. Было `duration + 19.16` — хвост фикстуры первого фильма:
# на кате v2 карта структуры писала финал «34:42–35:35» при длине ката 35:16 (22.09.2026).
_END = int(float(P.get('total_sec', P.duration_sec())) + 0.5)
CH_BOUNDS = [(int(t), int(e), int(n)) for (t, n), e in zip(_CHAP, [t for t, _ in _CHAP[1:]] + [_END])]
NEW_CH = set(int(x) for x in P.get('new_ch', []))

# (сек, глава, подпись) — по OCR-инвентарю титульных экранов ката
SUB = [(int(s), int(c), str(t)) for s, c, t in P.get('sub', [])]

PROG = {k: (v['title'], list(v['items']), CH_ACCENT[int(k) - 1] if int(k) - 1 < len(CH_ACCENT) else _PALETTE[0])
        for k, v in P.get('prog', {}).items()}

# таймкоды СМЕНЫ подтем перечислений (списки ТЗ в s10). Раскладка панелей на таймлайне —
# make_review_v6.PROG, её не трогаем.
PROG_T = {k: [int(x) for x in v] for k, v in P.get('prog_t', {}).items()}
PROG_FINAL = {k: (int(v[0]), str(v[1])) for k, v in P.get('prog_final', {}).items()}
PROG_NOTE = {(k.split(':')[0], int(k.split(':')[1])): v for k, v in P.get('prog_note', {}).items()}
