#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ревью-таймлайн YTCH12 v4 по канону 6 слоёв (KB review-timeline, 07.09): build_model review_overlay.
  V1 = рендер монтажёра ЦЕЛИКОМ (лайт 4K, кадр-в-кадр с мастером) — не тронут, A1 цело
  V3 = инфографика: подпись Гули (Жимагул Панфилова, куратор фонда) на каждом её входе
  V4 = плашки ТЗ (lower-third) в таймкод ТЗ; ПОЛНЫЙ текст ТЗ — в маркере клипа (item_marker) /
       кнопка панели «Copy ТЗ @ playhead»
  V6 = структура: карта структуры (0:00), титул, карточки предложенных глав (мокапы в стиле YTCH11)
Маркеры секвенции = ТОЛЬКО главы, разноцветные. Стиллы ≤4,8 с, всё на сетке 25p.
Арбитраж: плашки ТЗ уступают карточкам V6 (сдвиг за конец, если ≤6 с, иначе — в dropped).
Выход: 00_Setup/05_Review/YTCH12_review_v4.json (+ _summary.md).
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path

M = Path(__file__).parent
PROJECT = Path('/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta')
REV = PROJECT / '00_Setup/05_Review'
MOCK = REV / 'mockups'
RENDER = Path('/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/03_Exports/YTCH12_v4_light_4K.mp4')
FPS, D, CARD = 25.0, 4.8, 2.4
MCOL = ['Green', 'Cyan', 'Orange', 'Magenta', 'Blue', 'Yellow']
TCOL = {'cut': 'Red', 'insert': 'Green', 'graphics': 'Yellow', 'structure': 'Orange', 'color': 'Blue',
        'fund': 'Orange', 'check': 'Violet'}


def grid(t):
    return round(round(t * FPS) / FPS, 2)


def sec(t):
    import re
    m = re.findall(r'\d+(?:\.\d+)?', str(t or ''))
    p = [float(x) for x in m[:3]]
    if not p:
        return None
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else (p[0] * 60 + p[1] if len(p) == 2 else p[0])


def seg(sid, track, color, path, dur, tl, item_marker=None, prio=5):
    p = Path(path)
    d = {'segment_id': sid, 'role': 'shown', 'track': track, 'audio_track': 'A2', 'keep_audio': False,
         'color': color, 'source_file': p.name, 'source_path': str(p), 'clip_id': p.stem, 'kind': 'graphic',
         'use': 'TRUE', 'speaker': '', 'source_in_sec': 0.0, 'source_out_sec': round(min(dur, D), 3),
         'timeline_in_sec': grid(tl), 'timeline_out_sec': grid(grid(tl) + min(dur, D)), '_prio': prio}
    if item_marker:
        d['item_marker'] = item_marker
    return d


def main():
    total = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                                  str(RENDER)], capture_output=True, text=True, check=True).stdout)
    vch = json.loads((M / 'viewer_chapters.json').read_text())
    st = json.loads((M / 'structure_v4.json').read_text())['final']
    mk = json.loads((M / 'mockups_index.json').read_text()) if (M / 'mockups_index.json').exists() else {}
    tzi = json.loads((M / 'tz_index.json').read_text()) if (M / 'tz_index.json').exists() else {}
    pr = json.loads((M / 'pravki_v4.json').read_text())['all']
    for i, p in enumerate(pr):
        p['num'] = f'ТЗ-{i + 1:02d}'
    words = json.loads((REV / 'YTCH12_v4.words.json').read_text())
    S, drops = [], []

    # V6 — структура
    if mk.get('structure_map'):
        S.append(seg('v6_structmap', 'V6', 'Orange', mk['structure_map'], D, 0.0, prio=1))
    t_title = sec(st.get('title_card_tc'))
    if mk.get('title') and t_title is not None:
        S.append(seg('v6_title', 'V6', 'Orange', mk['title'], CARD, t_title, prio=1))
    for c in vch:
        if c.get('img') and (MOCK / c['img']).exists() and c['sec'] > 0.5:
            S.append(seg(f'v6_card_{c["no"]:02d}', 'V6', 'Orange', MOCK / c['img'], CARD, c['sec'], prio=1))
    # V3 — подпись Гули на каждом её входе (начало блока Speaker 2 после паузы в её речи > 60 с)
    if mk.get('lt_gulya'):
        last = -999
        for p in words['paragraphs']:
            if p['speaker'] == 'Speaker 2':
                s0 = float(p['start'])
                if s0 - last > 60:
                    S.append(seg(f'v3_lt_gulya_{int(s0)}', 'V3', 'Yellow', mk['lt_gulya'], D, s0 + 0.5, prio=3))
                last = float(p['end'])
    # V4 — плашки ТЗ (уступают карточкам V6)
    v6 = sorted((s['timeline_in_sec'], s['timeline_out_sec']) for s in S if s['track'] == 'V6')
    v4_end = -1.0
    for p in pr:
        if p.get('status') == 'rejected' or p['num'] not in tzi:
            continue
        t0 = sec(str(p.get('v1_tc') or '').split('–')[0])
        if t0 is None:
            continue
        t = max(t0, v4_end)
        for a, b in v6:
            if a - 0.01 <= t < b:
                t = b
        if t - t0 > 6.0:
            drops.append({'num': p['num'], 'tc': p.get('tc_range'), 'why': 'наезд на соседние плашки/карточки > 6 с'})
            continue
        text = f'{p["num"]} 【{p["title"]}】\n{p["nado"]}'
        s = seg(f'v4_{p["num"]}', 'V4', TCOL.get(p['category'], 'Violet'), tzi[p['num']], D, t, item_marker=text, prio=4)
        S.append(s)
        v4_end = s['timeline_out_sec']
    S.sort(key=lambda s: (s['timeline_in_sec'], s['track']))
    for s in S:
        assert abs(s['timeline_in_sec'] * FPS - round(s['timeline_in_sec'] * FPS)) < 1e-6, s['segment_id']
        assert s['timeline_out_sec'] <= total + 0.01 or s['track'] != 'V1', s['segment_id']
    cnt = {t: sum(s['track'] == t for s in S) for t in ('V3', 'V4', 'V6')}

    chapter_markers = []
    for i, c in enumerate(vch):
        end = vch[i + 1]['sec'] if i + 1 < len(vch) else total
        chapter_markers.append({'tc_sec': c['sec'], 'duration_sec': round(end - c['sec'], 3),
                                'name': f'{c["no"]:02d}. {c["title"]}', 'comment': c.get('purpose', ''),
                                'color': MCOL[i % len(MCOL)]})
    out = {
        'schema': 'ytai-part-v1',
        'part': {'code': 'YTCH12', 'project_name': 'YTCH12_Sveta', 'name': 'Review_v4', 'stage': 'Review', 'fps': FPS,
                 'sequence_name': 'YTCH12_5_Review_v4_tz', 'build_model': 'review_overlay', 'seed_clip': '',
                 'base_clip': RENDER.name, 'base_clip_path': str(RENDER), 'markers': False, 'min_builder': '1.11.0',
                 'chapter_markers': chapter_markers, 'bin': '05_Review',
                 'created': datetime.now().isoformat(timespec='minutes'),
                 'note': '6 слоёв (канон 07.09): V1 оригинал монтажа v4 не тронут (лайт 4K) · V3 подпись Гули · '
                         'V4 плашки ТЗ (полный текст — маркер клипа / «Copy ТЗ @ playhead») · V6 карта структуры + титул + '
                         'карточки ПРЕДЛАГАЕМЫХ глав (в кате их нет). Маркеры секвенции = только главы. Док: YTCH12_Review_v4.'},
        'segments': S,
        'tracks': 'V1 = оригинал · V3 = подписи/инфографика · V4 = ТЗ · V6 = структура (карточки глав, титул, карта)',
        'audio_policy': 'A1 (голос рендера) не трогается; стиллы без звука',
        'required_imports': sorted({s['source_path'] for s in S}),
        'counts': {'segments': len(S), **cnt, 'chapter_markers': len(chapter_markers), 'dropped': len(drops),
                   'total_dur_sec': round(total, 2)},
        'dropped': drops,
    }
    dst = REV / 'YTCH12_review_v4.json'
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    md = ['# YTCH12_review_v4 — ревью-таймлайн по канону 6 слоёв', '',
          f'Создан: {out["part"]["created"]} · секвенция `YTCH12_5_Review_v4_tz` · база: {RENDER.name} '
          f'({int(total // 60)}:{int(total % 60):02d}, 25p, 3840×2160) — нужен смонтированный **T9-Black**.', '',
          f'- V6 структура: {cnt["V6"]} (карта, титул, карточки глав) · V3 подписи: {cnt["V3"]} · V4 плашки ТЗ: {cnt["V4"]}',
          f'- Маркеры глав: {len(chapter_markers)} · выпало по арбитражу: {len(drops)}',
          '- Панель UXP → Review → «YTCH12_review_v4». partsBuilder ≥ 1.11.0. Текст ТЗ — маркер клипа V4 или «Copy ТЗ @ playhead».',
          '', '| # | TC | Глава |', '|---|---|---|']
    md += [f'| {c["no"]} | {int(c["sec"]) // 60}:{int(c["sec"]) % 60:02d} | {c["title"]} |' for c in vch]
    (REV / 'YTCH12_review_v4_summary.md').write_text('\n'.join(md) + '\n')
    for old in ('YTCH12_review_v4_full.json', 'YTCH12_review_v4_full_summary.md'):
        (REV / old).unlink(missing_ok=True)
    print(f'→ {dst} · сегментов {len(S)} {cnt} · маркеров {len(chapter_markers)} · выпало {len(drops)}')


if __name__ == '__main__':
    main()
