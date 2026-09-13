#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Review_v6 — 6-слойный ревью-таймлайн (канон feedback_review_6layer_timeline) + тикет v6:

V1 = ОРИГИНАЛ (рендер v1, не тронут, A1 цел)
V2 = футажи видео+фото (как в v5)
V3 = ВСЯ инфографика: драфты v5 (тёмные полноэкранные → прозрачные панели, где уместно)
     + плашки-определения ТЕРМИНОВ при каждом упоминании + МИНИ-КАРТЫ локаций
     + нарисованные ИСПРАВЛЕНИЯ (валюта «$30,3 МЛН», правильные титры) из аудита
V4 = плашки ТЗ (полный текст + ссылки в маркере мастер-клипа; дубль — кнопка панели
     «Copy ТЗ @ playhead», v2.17.0)
V5 = стрелки-обводки «где ошибка» (v5: 6 + все находки аудита экранов audit_v6.json)
V6 = структура: главы (ch_ov_*) + ПОДглавы (sub_NN) + прогресс перечислений гл.08/09
     (prog_08_N/prog_09_N) + подсказки структуры (str_*)
Маркеры секвенции = ТОЛЬКО 10 разноцветных глав.

Арбитраж наездов на дорожке: приоритеты (V3: fix > info > map > term); младший сдвигается
вперёд до конца старшего (≤ MAX_SHIFT с), иначе выпадает — с записью в drop-лог.
Сетка 25p: все tc кратны 0.04. Стиллы ≤ 4.8 с. sequence_name НЕ кончается на _v\\d.
"""
import json, re, sys
from datetime import datetime
from pathlib import Path

W6 = Path(__file__).parent
M = W6.parent / 'montage'
sys.path.insert(0, str(W6))
from terms_catalog import TERMS, LOCS  # noqa: E402

import proj_config as P  # noqa: E402

PROJECT = Path(P.get('project_dir', '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby'))
# review_dir/mockups_dir из карточки: когда SSD проекта не смонтирован, собираем в рабочую копию
REVIEW_DIR = Path(P.get('review_dir') or (PROJECT / '00_Setup/05_Review'))
RENDER = Path(P.get('render', '')) if P.get('render') else PROJECT / '03_Exports'
MOCK = Path(P.get('mockups_dir') or (REVIEW_DIR / 'mockups'))
REFS = REVIEW_DIR / 'refs'
FOOT = Path(P.get('footage_dir', '/Volumes/T7-Blue-2-RYA/YTUVI-Footage'))
NAT = PROJECT / P.get('host_scene', '01_Source/02_Natalia_Gems')

V1_DUR = float(P.get('duration_sec', 2440.48))     # длительность ката из карточки
FPS = float(P.get('fps', 25.0))
D = 4.8
TOTAL = float(P.get('total_sec', V1_DUR + 19.16))  # кат + хвост ревью-секвенции
MAX_SHIFT = 6.0
MATERIALS_FOLDER = P.folder_url('materials_id')           # дубль 4 из 4 — из карточки

# Главы — из карточки проекта (chapters + ch_name), цвета маркеров Premiere по кругу.
# Здесь были зашиты 10 глав первого фильма: на другом кате маркеры секвенции легли бы
# по чужой структуре. «➕» — глава, заставки которой в кате нет (new_ch).
_MCOL = P.get('ch_marker_colors') or ['Green', 'Cyan', 'Orange', 'Magenta', 'Blue', 'Yellow']
_NEW = set(P.get('new_ch', []))
_ends = [float(t) for t, _ in P.CHAPTERS[1:]] + [TOTAL]
CHAPTERS = [(float(t), e, _MCOL[i % len(_MCOL)],
             f'{n} {"➕" if int(n) in _NEW else "·"} {P.get("ch_name", {}).get(n, "ГЛАВА " + n)}')
            for i, ((t, n), e) in enumerate(zip(P.CHAPTERS, _ends))]

pravki = json.load(open(M / 'pravki_v2.json'))['all']
terms = json.load(open(W6 / 'terms_v6.json'))
audit = P.audit_or_die(W6 / 'audit_v6.json') or {'placements': []}
# ТЗ, снятые Романом (status=rejected, 09.09): их плашки V4, стрелки V5 и fix V3 на таймлайн не идут
REJECTED = {i + 1 for i, p in enumerate(pravki) if p.get('status') == 'rejected'}


def rejected_sid(sid):
    m = re.search(r'tz(\d+)', sid)
    return bool(m) and int(m.group(1)) in REJECTED


audit['placements'] = [a for a in audit['placements'] if not rejected_sid(a['sid'])]
# v7: находки аудита, которые Роман переквалифицировал (ТЗ живо, но «ошибки» нет): их стрелки V5 на таймлайн не идут.
# Номера — из карточки проекта (no_arrow). У YTUVI01 это было ТЗ-41 («титр за головой — приём канала», 10.09);
# зашитое число молча сняло бы стрелку с ТЗ-41 нового фильма.
NO_ARROW = set(int(x) for x in P.get('no_arrow', []))
audit['placements'] = [a for a in audit['placements']
                       if not (a['track'] == 'V5' and (m := re.search(r'tz(\d+)', a['sid'])) and int(m.group(1)) in NO_ARROW)]
drive_clips = json.load(open(M / 'drive_clips.json')) if (M / 'drive_clips.json').exists() else {}
proj_ids = json.load(open(M / 'proj_material_ids.json')) if (M / 'proj_material_ids.json').exists() else {}
shots_ids = json.load(open(M / 'shots_ids.json')) if (M / 'shots_ids.json').exists() else {}
DROPS = []


def grid(t):
    return round(round(float(t) * FPS) / FPS, 3)


def seg(sid, track, color, path, si, so, tl, keep_audio=True, kind='broll',
        speaker='', audio='A2', item_marker=None, prio=5):
    p = Path(path)
    d = {'segment_id': sid, 'role': 'shown', 'track': track,
         'audio_track': audio, 'keep_audio': keep_audio, 'color': color,
         'source_file': p.name, 'source_path': str(p), 'clip_id': p.stem, 'kind': kind,
         'use': 'TRUE', 'speaker': speaker,
         'source_in_sec': round(si, 3), 'source_out_sec': round(so, 3),
         'timeline_in_sec': grid(tl), 'timeline_out_sec': grid(grid(tl) + (so - si)), '_prio': prio}
    if item_marker:
        d['item_marker'] = item_marker
    return d


def still(sid, path, tl, track, color, dur=D, item_marker=None, prio=5):
    return seg(sid, track, color, path, 0.0, min(dur, D), tl, keep_audio=False,
               kind='graphic', item_marker=item_marker, prio=prio)


def clip_link(text):
    m = re.search(r'(RYA-[A-Z0-9]+-\d{4})', text or '')
    if not m:
        return None
    e = drive_clips.get(m.group(1) + '.MP4')
    return f'https://drive.google.com/file/d/{e[0]["id"]}/view' if e else None


def material_links(p):
    out = []
    for mr in p.get('material_rich') or []:
        t = mr.get('t', '')
        link = clip_link(t)
        img = mr.get('img')
        fid = (proj_ids.get(img) or shots_ids.get(img)) if img else None
        line = t
        if link:
            line += f' → {link}'
        if fid:
            line += f' → https://drive.google.com/file/d/{fid}/view'
        out.append(line)
    return out


# ══ V2 — футажи и стиллы по ТЗ ══
# Список — из карточки проекта (ключ v2): у каждого фильма свои вставки со своими таймкодами.
# Здесь были зашиты 26 вставок первого фильма с абсолютными таймкодами (Бирма, Могок, CTA на 40:40) —
# на другом кате они легли бы в случайные места. Путь — абсолютный или с префиксом FOOT/ REFS/ NAT/ MOCK/.
# Запись: {"kind": "seg"|"still", "sid", "path", "t", "in", "out", "opts": {keep_audio, speaker, kind, dur, prio}}
_ROOTS = {'FOOT': FOOT, 'REFS': REFS, 'NAT': NAT, 'MOCK': MOCK}


def _path(p):
    head, _, rest = str(p).partition('/')
    return _ROOTS[head] / rest if head in _ROOTS else Path(p)


def _entry(e, track, color):
    """запись карточки → сегмент раскладки (те же seg()/still(), что и раньше)"""
    if e.get('kind', 'still') == 'seg':
        return seg(e['sid'], track, e.get('color', color), _path(e['path']), float(e['in']), float(e['out']),
                   float(e['t']), **e.get('opts', {}))
    return still(e['sid'], _path(e['path']), float(e['t']), track, e.get('color', color), **e.get('opts', {}))


def _entries(key, track, color, prio):
    return [_entry({**e, 'opts': {'prio': prio, **e.get('opts', {})}} if prio else e, track, color)
            for e in P.get(key, [])]


V2 = _entries('v2', 'V2', 'Cyan', None)

# ══ V3 — инфографика: драфты v5 (прозрачные версии где уместно) prio 3 ══
V3_INFO = [
    # Роман 10.09: «создать пример кадра для удобства восприятия всей структуры»
    still('v3_structmap', MOCK / 'info_structure_map.png', 0.0, 'V3', 'Green', prio=2),
    # «карта выпуска» с «ВЫ ЗДЕСЬ» — пример на КАЖДОЙ смене главы (2–3 сек, ТЗ-30)
    *[still(f'v3_videomap_{i + 1:02d}', MOCK / f'info_videomap_ch{i + 1:02d}.png', tc + 0.2,
            'V3', 'Green', dur=3.0, prio=2)
      for i, (tc, end, color, name) in enumerate(CHAPTERS)],
    # проектные драфты (схемы, большие карты, карточки) — из карточки (ключ v3_info), prio 3.
    # У YTUVI01 тут были 14 драфтов с его таймкодами (Моос, «рубиновый пояс», аукционы, обработки).
    *_entries('v3_info', 'V3', 'Green', 3),
]
# термины (prio 6) и мини-карты (prio 5). Если упоминание попадает на ТИТУЛЬНЫЙ экран ката
# (событие OCR без лица в кадре = карточка/заставка), плашку сдвигаем за его конец (≤ +8 с),
# чтобы не ложиться на крупный титр.
SCREENS = json.load(open(W6 / 'screens_v6.json')) if (W6 / 'screens_v6.json').exists() else []
TITLE_CARDS = [(e['t0'], e['t1']) for e in SCREENS if e.get('faces_avg', 1) < 0.3 and e['dur'] >= 2]


def dodge_title(t):
    for a, b in TITLE_CARDS:
        if a - 0.5 <= t <= b and (b + 0.5) - t <= 8.0:
            return grid(b + 0.5)
    return t


V3_TERMS = [still(f'v3_term_{"_".join(g["keys"])}_{int(g["t"])}',
                  MOCK / (f'term_{g["keys"][0]}.png' if len(g['keys']) == 1 else 'termgrp_' + '_'.join(g['keys']) + '.png'),
                  dodge_title(g['t']), 'V3', 'Green', prio=6)
            for g in terms['term_groups']]


def map_png(m):
    """сноска «одна страна — два имени» — только на первом упоминании (terms_index ставит note)"""
    if m.get('note') and (MOCK / f'map_{m["key"]}_note.png').exists():
        return MOCK / f'map_{m["key"]}_note.png'
    return MOCK / f'map_{m["key"]}.png'


# m['cover'] — место попало в окно большой карты (перечисление «пояса»): мини-карту не ставим
V3_MAPS = [still(f'v3_map_{m["key"]}_{int(m["t"])}', map_png(m), dodge_title(m['t']), 'V3', 'Green', prio=5)
           for m in terms['locs'] if not m.get('cover')]
# исправления из аудита (prio 1 — главнее всего на V3)
# v7 (Роман 10.09 «суммы цифрами»): если у fix есть варианты оформления fix_*_A/_B.png (ТЗ-21 цены) —
# на таймлайн идут ОБА встык, каждый полной длины: А, затем Б (Роман выбирает глазом)
V3_FIX = []
for a in audit['placements']:
    if a['track'] != 'V3':
        continue
    variants = [MOCK / f"{Path(a['png']).stem}_{v}.png" for v in ('A', 'B')]
    if all(v.exists() for v in variants):
        dur = min(a.get('dur', D), D)
        V3_FIX.append(still(a['sid'] + '_A', variants[0], a['t'], 'V3', 'Green', dur=dur, prio=1))
        V3_FIX.append(still(a['sid'] + '_B', variants[1], grid(a['t'] + dur), 'V3', 'Green', dur=dur, prio=1))
    else:
        V3_FIX.append(still(a['sid'], MOCK / a['png'], a['t'], 'V3', 'Green', dur=a.get('dur', D), prio=1))

# ══ V5 — стрелки правок (v5: 6 + аудит). Если аудит дал стрелку по тому же ТЗ рядом (±6 с) —
# ручная стрелка v5 уступает (у аудита точный bbox + нарисованное исправление) ══
AUDIT_V5 = [(a['sid'], a['t']) for a in audit['placements'] if a['track'] == 'V5']


def superseded(base_sid, t):
    num = re.search(r'tz(\d+)', base_sid).group(1)
    return any(re.search(rf'tz{num}[a-z]', sid) and abs(tt - t) < 6 for sid, tt in AUDIT_V5)


# ручные стрелки (до аудита) — из карточки (ключ v5_base); sid обязан содержать tzNN (по нему
# ищется замена стрелкой аудита). У YTUVI01 тут были 6 стрелок под его номера ТЗ.
V5_BASE = _entries('v5_base', 'V5', 'Red', 2)
V5 = [s for s in V5_BASE if not superseded(s['segment_id'], s['timeline_in_sec'])] + [
    still(a['sid'], MOCK / a['png'], a['t'], 'V5', 'Red', dur=a.get('dur', D), prio=1)
    for a in audit['placements'] if a['track'] == 'V5']
for s in V5_BASE:
    if superseded(s['segment_id'], s['timeline_in_sec']):
        DROPS.append(f'V5: {s["segment_id"]} (ручная стрелка v5) заменена стрелкой аудита')

# ══ V6 — главы (prio 1) + подсказки (2) + прогресс (3) + подглавы (4) ══
def _ch_plate(i):
    """плашка главы для V6: ручная ch_ov_NN.png, иначе «карта выпуска» стадии H (info_videomap_chNN)."""
    manual = MOCK / f'ch_ov_{i:02d}.png'
    return manual if manual.exists() else MOCK / f'info_videomap_ch{i:02d}.png'


V6 = [still(f'v6_ch{i + 1:02d}', _ch_plate(i + 1), tc, 'V6', 'Magenta', prio=1)
      for i, (tc, end, color, name) in enumerate(CHAPTERS)]
# подсказки структуры (prio 2) — из карточки (ключ v6_extra); у YTUVI01 — три плашки под ТЗ-30/18/19
V6 += _entries('v6_extra', 'V6', 'Magenta', 2)
# Роман 09.09: «структура должна быть ДО, и каждый пункт показывать до» — обзор списка сразу после плашки
# главы, затем панель с подсветкой следующего пункта за 3 с до смены подтемы (LEAD)
LEAD = 3.0
sys.path.insert(0, str(W6))
from make_infographics_v6_data import SUB, PROG_T, PROG_FINAL  # noqa: E402  (те же данные, что рендерят sub_NN/prog_NN)
# Раскладка панелей прогресса выводится из таймкодов смены подтем (prog_t карточки): обзор — через 5 с после
# плашки главы, каждый пункт — за LEAD до своей смены, но не ближе 5 с к предыдущей панели; итог (prog_final) —
# последним. Раньше таблица была ручной под гл.08/09 первого фильма; на его данных правило даёт её же.
PROG = []
for _ch, _ts in PROG_T.items():
    _cur = float(next(t for t, n in P.CHAPTERS if n == _ch)) + 5.0
    PROG.append((_ch, 0, _cur))
    for _k, _t in enumerate(_ts, 1):
        _cur = max(float(_t) - LEAD, _cur + 5.0)
        PROG.append((_ch, _k, _cur))
    if _ch in PROG_FINAL:
        _cur = max(float(PROG_FINAL[_ch][0]) - LEAD, _cur + 5.0)
        PROG.append((_ch, len(_ts), _cur))
V6 += [still(f'v6_prog_{ch}_{k}_{int(t)}', MOCK / f'prog_{ch}_{k}.png', t, 'V6', 'Magenta', prio=3) for ch, k, t in PROG]
PROG_SECS = {int(t) for _, _, t in PROG}
# Плашка подглавы уступает титру ката, если ложится на него (сдвиг за его конец): sub_dodge {сек: новая сек}.
# sub_skip — подглавы, которые не ставим вовсе. У YTUVI01: {57: 61.0} («А МОЖЕТ НЕ ТАКОЙ…», QA 10.09) и {1762}.
SUB_DODGE = {int(k): float(v) for k, v in P.get('sub_dodge', {}).items()}
SUB_SKIP = set(int(x) for x in P.get('sub_skip', []))
for i, (sec, ch, label) in enumerate(SUB):
    if any(abs(sec - ps) <= 6 for ps in PROG_SECS) or sec in SUB_SKIP:
        continue                                    # подтему уже несёт прогресс-панель
    V6.append(still(f'v6_sub_{i + 1:02d}', MOCK / f'sub_{i + 1:02d}.png', SUB_DODGE.get(sec, float(sec)), 'V6', 'Magenta',
                    dur=4.0, prio=4))

# ══ V4 — плашки ТЗ + полный текст и ссылки в маркере мастер-клипа ══
def tc_sec(tc):
    m = re.match(r'(\d+):(\d{2})', str(tc).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


V4 = []
for i, p in enumerate(pravki):
    num = f'ТЗ-{i + 1:02d}'
    if p.get('status') == 'rejected':
        continue
    png = MOCK / f'tz_lt_{i + 1:02d}.png'
    sec = tc_sec(p['v1_tc'].split('–')[0].split('/')[0])
    if not png.exists() or sec is None:
        if num == 'ТЗ-30':
            sec = 43.6
        else:
            continue
    full = f"{num} · {p['title']}\n\n{p['nado']}"
    if p.get('decision'):
        full += f"\n\n⏳ РЕШЕНИЕ РОМАНА: {p['decision']}"
    links = material_links(p) + [f'📁 Review_materials: {MATERIALS_FOLDER}']
    V4.append(still(f'v4_lt_{i + 1:02d}', png, float(sec), 'V4', 'Yellow', prio=1,
                    item_marker={'name': f'{num} · {p["title"]}', 'comment': full + '\n\n🔗 ' + '\n🔗 '.join(links),
                                 'links': links}))


# ══ арбитраж наездов на дорожке ══
def arbitrate(items, track):
    """Старшие (меньший prio) ставятся первыми; младший при наезде ищет ближайшее свободное
    окно: вперёд (≤ MAX_SHIFT) или назад (≤ MAX_BACK — плашка чуть раньше слова допустима),
    иначе выпадает с записью в DROPS."""
    MAX_BACK = 3.0
    items = sorted(items, key=lambda s: (s['_prio'], s['timeline_in_sec']))
    placed = []

    def clash_of(a, b, lst):
        return next((p for p in lst if a < p['timeline_out_sec'] - 0.001 and b > p['timeline_in_sec'] + 0.001), None)

    for s in items:
        dur = round(s['timeline_out_sec'] - s['timeline_in_sec'], 3)
        t0 = s['timeline_in_sec']
        if clash_of(t0, t0 + dur, placed) is None:
            placed.append(s)
            continue
        # кандидаты: концы/начала занятых окон в пределах сдвига
        cands = []
        for p in placed:
            fwd = p['timeline_out_sec']
            if 0 < fwd - t0 <= MAX_SHIFT:
                cands.append((fwd - t0, fwd))
            back = p['timeline_in_sec'] - dur
            if 0 < t0 - back <= MAX_BACK and back >= 0:
                cands.append((t0 - back + 0.5, back))    # назад — чуть менее желательно
        best = None
        for cost, ti in sorted(cands):
            ti = grid(ti)
            if clash_of(ti, grid(ti + dur), placed) is None and grid(ti + dur) <= TOTAL:
                best = ti
                break
        if best is None:
            c = clash_of(t0, t0 + dur, placed)
            DROPS.append(f'{track}: {s["segment_id"]} выпал (наезд на {c["segment_id"]}, нет окна ±{MAX_SHIFT}/{MAX_BACK} с)')
            continue
        s['timeline_in_sec'] = best
        s['timeline_out_sec'] = grid(best + dur)
        placed.append(s)
    return sorted(placed, key=lambda s: s['timeline_in_sec'])


SEGMENTS = (arbitrate(V2, 'V2') + arbitrate(V3_FIX + V3_INFO + V3_MAPS + V3_TERMS, 'V3')
            + arbitrate(V4, 'V4') + arbitrate(V5, 'V5') + arbitrate(V6, 'V6'))

chapter_markers = [{'tc_sec': tc, 'duration_sec': round(end - tc, 3), 'name': name, 'comment': '', 'color': color}
                   for tc, end, color, name in CHAPTERS]

# ── верификация ──
errs = []
for s in SEGMENTS:
    if not Path(s['source_path']).exists():
        errs.append('нет файла: ' + s['source_path'])
    if s['kind'] == 'graphic' and s['timeline_out_sec'] - s['timeline_in_sec'] > D + 0.001:
        errs.append(f'стилл длиннее {D} с: {s["segment_id"]}')
    for k in ('timeline_in_sec', 'timeline_out_sec'):
        if abs(s[k] * FPS - round(s[k] * FPS)) > 0.01:
            errs.append(f'не на сетке 25p: {s["segment_id"]} {k}={s[k]}')
for tr in ('V2', 'V3', 'V4', 'V5', 'V6'):
    tt = sorted([s for s in SEGMENTS if s['track'] == tr], key=lambda x: x['timeline_in_sec'])
    for a, b in zip(tt, tt[1:]):
        if b['timeline_in_sec'] < a['timeline_out_sec'] - 0.001:
            errs.append(f'наезд {tr}: {a["segment_id"]} → {b["segment_id"]}')
assert not errs, '\n'.join(errs[:30])
for s in SEGMENTS:
    s.pop('_prio', None)

cnt = {tr: sum(1 for s in SEGMENTS if s['track'] == tr) for tr in ('V2', 'V3', 'V4', 'V5', 'V6')}
print('OK:', len(SEGMENTS), 'сегментов', cnt, '| маркеров:', len(chapter_markers), '| выпало:', len(DROPS))
for d in DROPS:
    print('  ⤷', d)

out = {
    'schema': 'ytai-part-v1',
    'part': {
        'code': P.CODE, 'project_name': P.get('project_name', P.CODE),
        'name': 'Review_v6', 'stage': 'Review', 'fps': FPS,
        'sequence_name': f'{P.CODE}_5_Review_v6_tz', 'build_model': 'review_overlay',
        'seed_clip': '', 'base_clip': RENDER.name, 'base_clip_path': str(RENDER),
        'markers': False, 'min_builder': '1.11.0',
        'chapter_markers': chapter_markers, 'bin': '05_Review',
        'created': datetime.now().isoformat(timespec='minutes'),
        'note': '6 слоёв (канон 07.09) + тикет v6: V1 оригинал не тронут · V2 футажи · V3 инфографика '
                '(прозрачные панели, термины при каждом упоминании, мини-карты локаций, нарисованные '
                'исправления) · V4 плашки ТЗ (полный текст+ссылки в маркере мастер-клипа; кнопка панели '
                '«Copy ТЗ @ playhead») · V5 стрелки «где ошибка» (аудит всех экранов) · V6 главы + подглавы + '
                f'прогресс перечислений. Маркеры секвенции = ТОЛЬКО {len(chapter_markers)} глав. Материалы с комментами: '
                + MATERIALS_FOLDER,
    },
    'segments': SEGMENTS,
    'tracks': 'V1 = оригинал · V2 = футажи · V3 = инфографика+термины+карты+исправления · V4 = ТЗ · '
              'V5 = стрелки ошибок · V6 = главы/подглавы/прогресс',
    'audio_policy': 'A1 (голос) не трогается; звук футажа и CTA → A2; стилы без звука',
    'required_imports': sorted({s['source_path'] for s in SEGMENTS}),
    'counts': {'segments': len(SEGMENTS), **cnt, 'chapter_markers': len(chapter_markers),
               'dropped': len(DROPS), 'total_dur_sec': TOTAL},
    'dropped': DROPS,
}
dst = REVIEW_DIR / f'{P.CODE}_review_v6.json'
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print('→', dst)
md = ['# Review_v6 — 6 слоёв + аудит экранов, термины, карты, подглавы', '',
      f'Создан: {out["part"]["created"]}. Секвенция: `{P.CODE}_5_Review_v6_tz_v{{N}}`.', '',
      f'- V2 футажи: {cnt["V2"]} · V3 инфографика/термины/карты/исправления: {cnt["V3"]} · V4 ТЗ: {cnt["V4"]} · '
      f'V5 стрелки: {cnt["V5"]} · V6 структура: {cnt["V6"]}.',
      f'- Выпало по арбитражу наездов: {len(DROPS)} (см. `dropped` в JSON).',
      '- Требует partsBuilder ≥1.11.0; текст ТЗ — маркер клипа или кнопка «Copy ТЗ @ playhead» (панель v2.17.0).']
(REVIEW_DIR / f'{P.CODE}_review_v6_summary.md').write_text('\n'.join(md))
