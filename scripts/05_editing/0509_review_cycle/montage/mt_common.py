#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mt_common — общие функции режима montage_tz (ТЗ на монтаж из исходников, ката нет).

Здесь живёт то, что раньше дублировалось в build_montage.py / build_montage_cam2.py /
grab_frames.py / build_structure_html.py каждого проекта: чтение пословного транскрипта,
якоря «подсказка + слово», формат таймкодов, нормализация списка клипов, чтение плана.

    from mt_common import load_words, anchor, tc, norm_clips, clip_at, load_plan

Карточка фильма (review_card.json, docs/contracts.md §1) даёт `words`, `clips`, `speakers`,
`plan_file`; план (montage_plan.json, §8) — куски, экраны, каталог графики. План сцены может
перебивать `words` / `clips` / `speakers` карточки своими ключами (вторая камера, другой день).
"""
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'stages'))
from _bootstrap import P, REVIEW_DIR, ROOT  # noqa: E402,F401

GAP_MIN, GAP_KEEP, PAD = 0.7, 0.35, 0.3       # пауза ≥0,7 с считается; при подрезке оставляем 0,35; воздух ≤0,3
ANCHOR_WIN = 6.0                              # окно поиска слова вокруг подсказки (как в легаси)


# ---------------- таймкоды / слова ----------------
def to_sec(v):
    if isinstance(v, (int, float)):
        return float(v)
    p = str(v).split(':')
    return float(p[0]) * 60 + float(p[1]) if len(p) == 2 else float(p[0])


def norm(w):
    return re.sub(r'[^\w.]+', '', str(w).lower().replace('ё', 'е')).strip('.')


def tc(t, ms=True):
    t = max(0.0, float(t))
    mm, ss = divmod(t, 60)
    return f'{int(mm):02d}:{ss:05.2f}' if ms else f'{int(mm):02d}:{int(ss):02d}'


def m(mm, ss):
    """минуты+секунды → секунды (для ручных планов: m(16, 51.76))."""
    return mm * 60 + ss


def load_words(path=None):
    """Пословный транскрипт → список {w, n, s, e, sp}, отсортированный по началу слова."""
    path = Path(path or P.WORDS)
    d = json.loads(path.read_text(encoding='utf-8'))
    ws = []
    for seg in d['segments']:
        for w in seg.get('words', []):
            ws.append({'w': w['w'].strip(), 'n': norm(w['w']), 's': to_sec(w['s']),
                       'e': to_sec(w['e']), 'sp': w.get('speaker') or seg.get('speaker')})
    ws.sort(key=lambda x: x['s'])
    return ws


def load_words_doc(path=None):
    path = Path(path or P.WORDS)
    return json.loads(path.read_text(encoding='utf-8'))


def anchor(ws, hint, word, edge, errors=None):
    """Индекс слова: ближайшее к подсказке вхождение word (по началу для in, по концу для out).

    Логика легаси дословно: окно ±6 с, слово совпадает целиком или по началу; если не найдено —
    ошибка копится в errors, а возвращается ближайшее по времени слово, чтобы прогон дошёл до конца
    и показал ВСЕ промахи разом."""
    key = 's' if edge == 'in' else 'e'
    cand = [i for i, w in enumerate(ws) if abs(w[key] - hint) < ANCHOR_WIN and
            (word is None or w['n'] == norm(word) or w['n'].startswith(norm(word)))]
    if not cand:
        if errors is not None:
            errors.append(f'якорь не найден: {word!r} около {tc(hint)} ({edge})')
        return min(range(len(ws)), key=lambda i: abs(ws[i][key] - hint))
    return min(cand, key=lambda i: abs(ws[i][key] - hint))


def word_near(ws, hint, word, edge='in', win=3.0):
    """Проверка якоря: есть ли слово в ±win с от подсказки. Возвращает индекс или None."""
    key = 's' if edge == 'in' else 'e'
    n = norm(word)
    cand = [i for i, w in enumerate(ws) if abs(w[key] - hint) <= win and (w['n'] == n or w['n'].startswith(n))]
    return min(cand, key=lambda i: abs(ws[i][key] - hint)) if cand else None


# ---------------- клипы ----------------
def norm_clips(clips):
    """Список клипов карточки → [(file, start, end)] на сквозной таймлинии.

    Принимает две формы: [{file, dur, path?}] (старты считаются накоплением, округление до мс —
    так 342.72+342.72 даёт ровно 685.44, как в ручных планах) или [[file, start, end]]."""
    out, acc = [], 0.0
    for c in clips or []:
        if isinstance(c, dict):
            dur = float(c['dur'])
            a, b = round(acc, 3), round(acc + dur, 3)
            acc += dur
            out.append((c['file'], a, b))
        else:
            name, a, b = c[0], float(c[1]), float(c[2])
            acc = b
            out.append((name, a, b))
    return out


def clip_at(clips, t):
    """Глобальная секунда → (файл, смещение внутри файла)."""
    for name, a, b in clips:
        if a <= t < b:
            return name, t - a
    name, a, b = clips[-1]
    return name, b - a


def clips_total(clips):
    return round(clips[-1][2], 2) if clips else 0.0


def find_clip_file(name, roots=None):
    """Где лежит файл клипа: рядом с проектом, в 01_Source/Video/**, в 01_Media/Source/Video/**."""
    roots = roots or [Path(P.PROJECT_DIR)] if P.PROJECT_DIR else []
    for r in roots:
        r = Path(r)
        if (r / name).exists():
            return r / name
        for sub in ('01_Source/Video', '01_Media/Source/Video', '01_Source', '01_Media'):
            d = r / sub
            if d.exists():
                hit = next(d.rglob(name), None)
                if hit:
                    return hit
    return None


# ---------------- спикеры ----------------
def speakers_map(plan=None):
    """{'Speaker 1': 'A · Дарья', …} — из плана сцены, иначе из карточки."""
    sp = (plan or {}).get('speakers') or P.get('speakers') or {}
    if isinstance(sp, str):
        sp = json.loads(sp)
    return dict(sp)


def speaker_parts(label):
    """'A · Дарья' → ('A', 'Дарья'); 'за кадром' → ('', 'за кадром'); 'A7 III · Дарья' → ('A7 III', 'Дарья')."""
    s = str(label or '')
    if '·' in s:
        cam, name = [x.strip() for x in s.split('·', 1)]
        return cam, name
    return '', s.strip()


# ---------------- план ----------------
def plan_path(name=None):
    return REVIEW_DIR / (name or P.get('plan_file', 'montage_plan.json'))


def load_plan(path=None):
    p = Path(path) if path else plan_path()
    if not p.is_absolute():
        p = REVIEW_DIR / p
    if not p.exists():
        raise SystemExit(f'нет плана {p} — собери его: build_montage.py --plan-from-legacy <build_montage.py> '
                         f'или structure_call.py --apply (из segments.json + cloud/out/structure.json)')
    return json.loads(p.read_text(encoding='utf-8'))


def plan_words(plan):
    """Транскрипт сцены: ключ words плана (относительно папки карточки) или карточка."""
    w = plan.get('words')
    return Path(P.resolve(w)) if w else Path(P.WORDS)


def plan_clips(plan):
    clips = plan.get('clips') or P.get('clips')
    if isinstance(clips, str):
        clips = json.loads(clips)
    if not clips:
        raise SystemExit('в карточке (или плане сцены) нет «clips» — [{file, dur}] или [[file, start, end]] '
                         'в порядке укладки на сквозную таймлинию')
    return norm_clips(clips)


def gfx_catalog_list(plan):
    """Каталог экранов плана → список словарей (принимает и старую форму {id: [kind, title, place]})."""
    cat = plan.get('gfx_catalog') or []
    if isinstance(cat, dict):
        return [{'id': k, 'kind': v[0], 'title': v[1], 'place': v[2]} if isinstance(v, (list, tuple))
                else {'id': k, **v} for k, v in cat.items()]
    return list(cat)


def gfx_catalog_dict(plan):
    """{id: [kind, title, place]} — форма montage.json (как в эталоне)."""
    return {g['id']: [g.get('kind', 'new'), g.get('title', ''), g.get('place', 'full')] for g in gfx_catalog_list(plan)}


def scene_plans(plan):
    """Дополнительные сцены главного плана: [{plan, out, …}] → пути к планам."""
    out = []
    for s in plan.get('scenes') or []:
        name = s['plan'] if isinstance(s, dict) else str(s)
        out.append((REVIEW_DIR / name, s if isinstance(s, dict) else {'plan': name}))
    return out


def relpath(target, base=None):
    """Относительный путь для HTML: от папки страницы к папке мокапов и т. п."""
    return os.path.relpath(str(target), str(base or REVIEW_DIR))


def write_json(path, data, indent=1):
    P.write_json_atomic(path, data, indent=indent)
