#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Гарант перед записью вкладки ТЗ: каждая картинка, на которую ссылается pravki (material_rich[].preview / img),
есть в shots_ids.json — вкладка вставляет картинку только из публичной папки shots_remote, а имени нет в реестре =
картинка молча не встаёт (v2 YTUVI02 трижды падал на term_*, map*, termgrp_*: их грузили разные стадии, не все).

Для каждого имени без id: ищем файл в mockups/, work/{cut}/kb_visuals/doc/, previews_doc/, err_frames_annotated/
→ rclone copy в shots_remote → id в shots_ids.json. Файла нет нигде = битая ссылка в pravki: печатаем список, exit 2
(стадия doc_tz не пишет вкладку с дырами).

usage: ensure_shots.py [--dry-run]
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _bootstrap import P, W6, M  # noqa: E402

DRY = '--dry-run' in sys.argv
SEARCH = [Path(P.MOCK), W6 / 'kb_visuals' / 'doc', W6 / 'previews_doc', W6 / 'err_frames_annotated']


def wanted(pravki):
    """имена картинок активных ТЗ (снятые Романом в док не идут) + кадры-карточки глав из карточки.
    Главы тоже вставляются только из shots_remote: без них verify падает ровно на число глав
    (YTUVI01 v2: «картинок ≥ 86, =76» — не хватало как раз 10 карточек глав)."""
    out = {}
    for i, p in enumerate(pravki):
        if p.get('status') == 'rejected':
            continue
        for it in p.get('material_rich') or []:
            for k in ('preview', 'img'):
                if it.get(k):
                    out.setdefault(it[k], i + 1)
    for no, name in sorted((P.get('ch_img', {}) or {}).items()):
        if name:
            out.setdefault(name, 0)                    # 0 = глава, не ТЗ (в отчёте «глава NN»)
    return out


def main():
    pravki = json.load(open(M / 'pravki_v2.json', encoding='utf-8'))['all']
    shots_path = M / 'shots_ids.json'
    shots = json.load(open(shots_path, encoding='utf-8')) if shots_path.exists() else {}
    need = {n: num for n, num in wanted(pravki).items() if n not in shots}
    if not need:
        print(f'ensure_shots: все {len(wanted(pravki))} картинок pravki есть в shots_ids')
        return 0
    found, lost = {}, []
    for name, num in sorted(need.items(), key=lambda x: x[1]):
        f = next((d / name for d in SEARCH if (d / name).exists()), None)
        if f:
            found[name] = f
        else:
            lost.append(f'{"глава" if num == 0 else f"ТЗ-{num:02d}"}: {name}')
    print(f'ensure_shots: без id {len(need)} · найдено на диске {len(found)} · нет нигде {len(lost)}')
    # Фильм может намеренно не иметь публичной папки кадров (YTCH12: в кадре ребёнок, Роман
    # решил папку не открывать). Тогда картинок во вкладке не будет ни при каком раскладе —
    # но ТЕКСТ ТЗ собрать можно и нужно: иначе жёсткий гейт doc_tz не даст монтажёру вообще
    # ничего. Отказ оставляем только там, где remote задан и заливка реально не удалась.
    if not str(P.get('shots_remote', '') or ''):
        print(f'  shots_remote пуст — вкладка соберётся БЕЗ {len(need)} картинок'
              + (f'; из них нет и на диске: {", ".join(lost)}' if lost else ''))
        return 0
    if found and not DRY:
        remote = P.need('shots_remote')
        with tempfile.TemporaryDirectory() as td:
            for name, f in found.items():
                shutil.copy2(f, Path(td) / name)
            subprocess.run(['rclone', 'copy', td, remote, '--transfers', '4'], check=True)
        ls = json.loads(subprocess.run(['rclone', 'lsjson', remote, '--files-only'],
                                       capture_output=True, text=True, check=True).stdout)
        ids = {x['Name']: x['ID'] for x in ls if x['Name'] in found}
        shots.update(ids)
        P.write_json_atomic(shots_path, shots)
        miss = sorted(set(found) - set(ids))
        print(f'  залито в {remote}: {len(ids)}' + (f' · без id после заливки: {miss}' if miss else ''))
        lost += [f'после заливки нет id: {m}' for m in miss]
    elif found:
        print('  (dry-run) залил бы:', ', '.join(sorted(found))[:600])
    if lost:
        print('!! битые ссылки на картинки в pravki (файла нет ни в одной папке):\n  ' + '\n  '.join(lost))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
