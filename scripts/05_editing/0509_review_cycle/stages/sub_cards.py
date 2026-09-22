#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кадры подглав для вкладки «Главы»: на каждую подглаву карточки — кадр из ката.

Зачем (Роман 22.09.2026): «там должны быть ВСЕ экраны глав и ВСЕ экраны подглав, с таймингом».
Главы такой кадр уже имели (`ch_img` → `ch_card_NN.jpg`), подглавы — нет: во вкладке они шли
строчками текста внутри ячейки главы. Теперь у каждой подглавы свой кадр, как у главы.

Кадр берём на секунде подглавы из `sub` карточки: hires/h{sec+1}.jpg (кадр N = секунда N−1).
Подглавы из `sub_no_screen` — титра в кате на них нет, кадр всё равно кладём (это момент, а не
титр), вкладка помечает их отдельно.

Пишет `mockups/sub_card_NN.jpg` (1920×1080, как ch_card_*) и ключ `sub_img` в карточку —
дальше их подхватывает ensure_shots и вставляет doc_tab_chapters_v1.

usage: sub_cards.py [--dry-run]
"""
import shutil
import sys
from pathlib import Path

from _bootstrap import P, W6  # noqa: E402

DRY = '--dry-run' in sys.argv
OUT = Path(P.MOCK)
HIRES = W6 / 'hires'


def main():
    sub = P.get('sub', []) or []
    if not sub:
        print('sub в карточке пуст — кадров подглав не будет')
        return 0
    n_frames = len(list(HIRES.glob('h*.jpg')))
    if not n_frames:
        print(f'!! нет кадров в {HIRES} — сначала стадия screens')
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    img, made, lost = {}, 0, []
    for i, (sec, _ch, _label) in enumerate(sub, 1):
        src = HIRES / f'h{min(int(sec) + 1, n_frames):04d}.jpg'
        name = f'sub_card_{i:02d}.jpg'
        if not src.exists():
            lost.append(f'{name}: нет {src.name}')
            continue
        img[f'{i:02d}'] = name
        dst = OUT / name
        if not dst.exists() and not DRY:
            shutil.copy2(src, dst)          # кадр как есть, 1920×1080 — тот же формат, что ch_card_*
            made += 1
    if not DRY:
        _write_card(img)
    print(f'кадры подглав: всего {len(sub)} · создано {made} · уже были {len(img) - made} '
          f'· в карточке sub_img {len(img)}' + (f' · НЕТ: {lost}' if lost else ''))
    return 2 if lost else 0


def _write_card(img):
    """в proj_config сеттера нет — пишем карточку атомарно, как это делает ensure_shots"""
    import json
    import os
    p = Path(os.environ.get('YTAI_CARD') or (Path(P.REVIEW_DIR) / 'review_card.json'))
    card = json.load(open(p, encoding='utf-8'))
    card['sub_img'] = img
    P.write_json_atomic(p, card)


if __name__ == '__main__':
    sys.exit(main())
