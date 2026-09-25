#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Кадры подглав для вкладки «Главы»: на каждую подглаву карточки — кадр из ката.

Зачем (Роман 22.09.2026): «там должны быть ВСЕ экраны глав и ВСЕ экраны подглав, с таймингом».
Главы такой кадр уже имели (`ch_img` → `ch_card_NN.jpg`), подглавы — нет: во вкладке они шли
строчками текста внутри ячейки главы. Теперь у каждой подглавы свой кадр, как у главы.

Кадр берём на секунде подглавы из `sub` карточки: hires/h{sec+1}.jpg (кадр N = секунда N−1).
Подглавы из `sub_no_screen` — титра в кате на них нет, кадр всё равно кладём (это момент, а не
титр), вкладка помечает их отдельно.

Пишет `mockups/sub_card_NN.jpg` (1920×1080) и ключ `sub_img` в карточку; если `ch_img` пуст — тем же
способом кладёт кадры ГЛАВ `mockups/ch_card_NN.jpg` и ключ `ch_img` (у YTUVI01 они были от ручного шага,
и на новом фильме вкладка «Главы» осталась бы без кадров глав) —
дальше их подхватывает ensure_shots и вставляет doc_tab_chapters_v1.

usage: sub_cards.py [--dry-run]
"""
import filecmp
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
        if stale(src, dst) and not DRY:
            shutil.copy2(src, dst)          # кадр как есть, 1920×1080 — тот же формат, что ch_card_*
            made += 1
    ch_img, ch_made, ch_lost = chapter_cards(n_frames)
    if not DRY:
        _write_card(img, ch_img)
    print(f'кадры подглав: всего {len(sub)} · обновлено {made} · совпадали {len(img) - made} '
          f'· в карточке sub_img {len(img)}' + (f' · НЕТ: {lost}' if lost else ''))
    if ch_img:
        print(f'кадры глав: обновлено {ch_made} · в карточке ch_img {len(ch_img)}'
              + (f' · НЕТ: {ch_lost}' if ch_lost else ''))
    elif not P.get('ch_img'):
        print('кадры глав: пропущены — в карточке нет глав')
    else:
        print(f'кадры глав: ch_img в карточке уже заполнен ({len(P.get("ch_img"))}) — не трогаю')
    return 2 if (lost or ch_lost) else 0


def chapter_cards(n_frames):
    """Кадры ГЛАВ той же операцией: у YTUVI01 `ch_card_NN.jpg` лежали от ручного шага, и на новом фильме
    вкладка «Главы» получала пустые ячейки вместо кадров (22.09.2026, YTCR04 v5). Кадр главы = кадр на её
    секунде, как у подглавы. Уже заполненный `ch_img` не трогаем: там может быть выбранный руками кадр."""
    if P.get('ch_img'):
        return {}, 0, []
    img, made, lost = {}, 0, []
    for sec, n in P.CHAPTERS:
        src = HIRES / f'h{min(int(sec) + 1, n_frames):04d}.jpg'
        name = f'ch_card_{n}.jpg'
        if not src.exists():
            lost.append(f'{name}: нет {src.name}')
            continue
        img[n] = name
        dst = OUT / name
        if stale(src, dst) and not DRY:
            shutil.copy2(src, dst)
            made += 1
    return img, made, lost


def stale(src, dst):
    """копировать, если кадра нет ИЛИ под тем же именем лежит другой кадр.

    ⚠️ Раньше проверялось только «файла нет». Имя — это номер главы или подглавы, а номера едут:
    YTCH12 25.09.2026 главы 14 → 26, и `ch_card_05.jpg` остался кадром старой главы 05 (12:06),
    хотя глава 05 теперь на 7:05. Во вкладке «Главы» у 14 глав стояли кадры соседей."""
    return not dst.exists() or not filecmp.cmp(src, dst, shallow=False)


def _write_card(img, ch_img=None):
    """в proj_config сеттера нет — пишем карточку атомарно, как это делает ensure_shots"""
    import json
    import os
    p = Path(os.environ.get('YTAI_CARD') or (Path(P.REVIEW_DIR) / 'review_card.json'))
    card = json.load(open(p, encoding='utf-8'))
    card['sub_img'] = img
    if ch_img:
        card['ch_img'] = ch_img
    P.write_json_atomic(p, card)


if __name__ == '__main__':
    sys.exit(main())
