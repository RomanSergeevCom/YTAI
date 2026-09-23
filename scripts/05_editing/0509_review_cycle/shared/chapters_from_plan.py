#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chapters_from_plan.py — главы нового ката по плану частей (ytai-part-v1) через сверку с прошлым рендером.

Зачем: план частей (UXP «Parts», напр. YTCR04_part_Review_v5_parts.json) описывает целевой таймлайн v5 кусками
прошлого рендера v4 (part.base_segments[]: source_in/out_sec — ось рендера v4, timeline_in/out_sec — ось плана,
chapter — имя главы) и маркерами глав (part.chapter_markers[]: tc_sec на оси плана, name). Монтажёр собрал кат не
кадр-в-кадр по плану, поэтому начало главы в кате ищем по речи: кат ↔ v4 (align.json) → v4 → base_segment → глава.

usage: chapters_from_plan.py [--plan parts.json] [--cut-words words.json] [--against-words v4.words.json]
                             [--align W6/align.json] [--out W6/chapters_proposal.json] [--apply]
                             [--pause 0.3] [--window 3.0] [--tol 1.0] [--min-span-words 8] [--min-run-words 6]
                             [--min-anchor-words 12] [--quiet]
По умолчанию: --plan = карточка chapters_plan, --cut-words = карточка words (P.WORDS), --against-words = первый
words.json из карточки align_against, --align = work/{cut}/align.json (сначала align.py --against <v4.words.json>).

Алгоритм:
 1. Пословное соответствие кат → v4: для каждого спана cut_map (≥ min-span-words слов) слова ката и v4 внутри спана
    сверяются difflib (align склеивает соседние куски, внутри спана возможны прыжки — пословно их не теряем).
 2. Слово ката → время v4 → base_segment, чей source-диапазон его содержит → глава; время плана слова
    p = timeline_in + (t_v4 − source_in). Прогоны одной главы короче min-run-words, окружённые чужими главами, — шум.
 3. Для каждой главы (порядок маркеров плана) первым берётся самый ранний её прогон ≥ min-anchor-words слов, который
    идёт ПОСЛЕ начала предыдущей главы; более ранние прогоны (эхо хука, повтор) → предупреждение. Если все прогоны
    главы стоят раньше начала предыдущей — ИНВЕРСИЯ (порядок ката ≠ план).
 4. Начало главы (f — первое сопоставленное слово, l — последнее сопоставленное слово ката перед f, U — несопоставленная
    речь между ними):
      film_start   — первая глава с маркером в 0 → 0.0;
      anchor       — маркер плана совпадает с началом её первого куска v4 (M ≥ p_f − tol): начало = f; несопоставленная
                     речь перед f остаётся предыдущей главе (так в плане);
      absorbed     — маркер раньше первого куска v4 (в плане перед ним вставки): несопоставленная речь перед f
                     принадлежит этой главе → начало = первое слово U;
      interpolated — то же, но между l и f по плану стоит ещё маркер (глава из одних вставок): начало делится
                     линейно по оси плана t = e_l + (M − p_l)·(s_f − e_l)/(p_f − p_l), не раньше первого слова U;
      missing_interpolated — у главы нет материала v4 в кате (глава из вставок): её начало интерполируется в U перед
                     следующей главой с материалом (привязка к слову, как выше);
      missing_silence — U пусто, но перед следующей главой пауза ≥ 2 с (эпик/титры без речи): начало по плану внутри
                     паузы (не ближе 0.5 с к словам), без привязки к слову;
                     нет ни речи, ни паузы / не тот порядок → глава не ставится, предупреждение (missing).
 5. Привязка: к первому слову после паузы ≥ pause с в пределах ±window с (не заходя в речь предыдущей главы), затем
    вниз к сетке кадров P.FPS_EXACT (29.97 → 30000/1001): frame = floor(sec·fps), sec = frame/fps (3 знака).
 6. Начала обязаны строго возрастать в порядке маркеров. Нарушение → exit 2 с объяснением (решает Роман), карточка не
    трогается; нет главы → предупреждение (exit 0).

Выход W6/chapters_proposal.json:
  {schema: 'chapters-proposal-v1', code, cut_version, status: 'ok' | 'inversion', plan, cut_words, against_words, align,
   base_tag, fps_exact, params{…}, chapters: [{n, name, sec, frame, tc, method, plan_tc_sec, first_mapped_sec,
   first_mapped_tc, mapped_words, runs[[t0, t1, words]…], snapped_from, pause_before}], missing: [name],
   warnings: [str], inversions: [str], card_patch: {chapters: [[sec, 'NN']…], ch_name: {'NN': name}}}
--apply (только status ok): копия карточки review_card.json.bak-chapters-<YYYYmmdd-HHMMSS>, затем в карточке
chapters = card_patch.chapters и ch_name = card_patch.ch_name (остальные ключи не трогаются).
exit: 0 — ок (возможно с предупреждениями), 2 — инверсия, 1 — нет входов.
env: YTAI_CARD=<review_card.json>; YTAI_WORK_DIR — куда писать (тесты).
"""
import argparse
import bisect
import datetime
import difflib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
from _bootstrap import P, W6  # noqa: E402
from align import norm, tosec  # noqa: E402  (та же нормализация слов, что у align.json)


def tcf(sec):
    sec = max(0.0, float(sec))
    m, s = divmod(sec, 60)
    return f'{int(m)}:{s:05.2f}'


def load_words(path):
    """words.json (wordrole) → [{w, n, s, e}] по времени; s/e — числа или «M:SS.sss»; пустые слова пропускаются"""
    d = json.load(open(path, encoding='utf-8'))
    out = []
    for seg in d.get('segments') or []:
        for w in seg.get('words') or []:
            n = norm(w.get('w', ''))
            s, e = w.get('s', w.get('start')), w.get('e', w.get('end'))
            if n and s is not None and e is not None:
                out.append({'w': str(w['w']).strip(), 'n': n, 's': tosec(s), 'e': tosec(e)})
    out.sort(key=lambda x: (x['s'], x['e']))
    return out


def load_plan(path):
    d = json.load(open(path, encoding='utf-8'))
    part = d.get('part') if isinstance(d.get('part'), dict) else d
    markers = sorted(({'name': str(m['name']), 'M': float(m['tc_sec'])} for m in part.get('chapter_markers') or []
                      if m.get('name') is not None and m.get('tc_sec') is not None), key=lambda m: m['M'])
    segs = sorted(({'id': str(b.get('seg_id', i)), 'ch': str(b['chapter']), 'src0': float(b['source_in_sec']),
                    'src1': float(b['source_out_sec']), 'tl0': float(b['timeline_in_sec'])}
                   for i, b in enumerate(part.get('base_segments') or []) if b.get('chapter') is not None),
                  key=lambda b: b['src0'])
    if not markers:
        raise SystemExit(f'{path}: нет part.chapter_markers[]')
    if not segs:
        raise SystemExit(f'{path}: нет part.base_segments[] с chapter')
    return d.get('schema', ''), markers, segs


def default_against():
    raw = P.get('align_against') or []
    raw = [raw] if isinstance(raw, str) else list(raw)
    for t in raw:
        p = Path(P.resolve(t))
        try:
            segs = (json.load(open(p, encoding='utf-8')).get('segments') or [])[:5]
        except Exception:
            continue
        if not any(('scene' in s or 'source_file' in s) for s in segs):
            return str(p)
    return ''


def pick_base(al, against):
    bases = al.get('bases') or {}
    ap = Path(against).resolve() if against else None
    for tag, b in bases.items():
        if ap and Path(b.get('file', '')).resolve() == ap:
            return tag, b
    stem = Path(against).stem.replace('.words', '') if against else ''
    if stem in bases:
        return stem, bases[stem]
    if len(bases) == 1:
        return next(iter(bases.items()))
    raise SystemExit(f'align.json: не нашёл базу для {against} среди {list(bases)} — align.py --against {against}')


def map_words(cw, bw, cut_map, min_span_words):
    """cut_map → {индекс слова ката: индекс слова v4} (difflib внутри каждого спана; при пересечении — длинный спан)"""
    cs, bs = [w['s'] for w in cw], [w['s'] for w in bw]
    best = {}
    for sp in cut_map:
        if int(sp.get('words') or 0) < min_span_words:
            continue
        c0, c1 = bisect.bisect_left(cs, sp['cut_t0'] - 0.05), bisect.bisect_right(cs, sp['cut_t1'] + 0.05)
        b0, b1 = bisect.bisect_left(bs, sp['base_t0'] - 0.05), bisect.bisect_right(bs, sp['base_t1'] + 0.05)
        if c1 <= c0 or b1 <= b0:
            continue
        sm = difflib.SequenceMatcher(None, [w['n'] for w in cw[c0:c1]], [w['n'] for w in bw[b0:b1]], autojunk=False)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                ci, bi = c0 + blk.a + k, b0 + blk.b + k
                if ci not in best or best[ci][1] < sp['words']:
                    best[ci] = (bi, sp['words'])
    return {ci: bi for ci, (bi, _) in best.items()}


def assign(cw, bw, mapping, segs):
    """слово ката → {ch, p_s, p_e, seg}: глава и время плана по base_segment, содержащему время v4"""
    starts = [b['src0'] for b in segs]
    out = {}
    for ci, bi in mapping.items():
        t = bw[bi]['s']
        k = bisect.bisect_right(starts, t) - 1
        seg = None
        if k >= 0 and t < segs[k]['src1']:
            seg = segs[k]
        else:                                             # слово на стыке кусков: допуск 0.05 с
            for b in segs[max(0, k):k + 2]:
                if b['src0'] - 0.05 <= t < b['src1'] + 0.05:
                    seg = b
                    break
        if seg is None:
            continue                                      # кусок v4, которого нет в плане (выброшенные дубли)
        out[ci] = {'ch': seg['ch'], 'seg': seg['id'], 'p_s': seg['tl0'] + (t - seg['src0']),
                   'p_e': seg['tl0'] + (bw[bi]['e'] - seg['src0'])}
    return out


def make_runs(cw, A, gap_sec=10.0):
    runs, cur = [], None
    for ci in sorted(A):
        ch = A[ci]['ch']
        if cur and cur['ch'] == ch and cw[ci]['s'] - cw[cur['i1']]['e'] <= gap_sec:
            cur['i1'] = ci
            cur['n'] += 1
        else:
            cur = {'ch': ch, 'i0': ci, 'i1': ci, 'n': 1}
            runs.append(cur)
    return runs


def drop_noise(runs, A, min_run_words):
    """короткий прогон, у которого соседние прогоны — другие главы, = случайное совпадение фразы → снять привязку"""
    keep, dropped = [], 0
    for i, r in enumerate(runs):
        prev_same = i > 0 and runs[i - 1]['ch'] == r['ch']
        next_same = i + 1 < len(runs) and runs[i + 1]['ch'] == r['ch']
        if r['n'] < min_run_words and not prev_same and not next_same:
            for ci in [c for c in A if r['i0'] <= c <= r['i1'] and A[c]['ch'] == r['ch']]:
                del A[ci]
            dropped += 1
        else:
            keep.append(r)
    return keep, dropped


def frame_floor(sec):
    fps = float(P.FPS_EXACT)
    fr = int(math.floor(sec * fps + 1e-6))
    return fr, round(fr / fps, 3)


def snap_after_pause(cw, t, lo, hi_sec, pause=0.3, window=3.0):
    """→ индекс первого слова после паузы ≥ pause, ближайшего к t (±window), индекс > lo, начало ≤ hi_sec.
    Нет слова после паузы — первое слово от t; нет и такого — первое в окне; пусто — None.
    Единственная реализация снапа в стадии: ею пользуются и главы (build), и подглавы (sub_from_prev)."""
    i0 = lo + 1 if lo is not None else 0
    j = bisect.bisect_left([w['s'] for w in cw], t - window)
    cands = [i for i in range(max(i0, j), len(cw)) if cw[i]['s'] <= min(hi_sec, t + window)]
    good = [i for i in cands if i == 0 or cw[i]['s'] - cw[i - 1]['e'] >= pause]
    if good:
        return min(good, key=lambda i: (abs(cw[i]['s'] - t), i))
    after = [i for i in cands if cw[i]['s'] >= t - 1e-6]
    return after[0] if after else (cands[0] if cands else None)


def build(cw, bw, al_base, markers, segs, a):
    warnings, inversions = [], []
    mapping = map_words(cw, bw, al_base.get('cut_map') or [], a.min_span_words)
    A = assign(cw, bw, mapping, segs)
    runs, dropped = drop_noise(make_runs(cw, A), A, a.min_run_words)
    if dropped:
        warnings.append(f'{dropped} short stray match(es) (< {a.min_run_words} words between other chapters) ignored')
    assigned = sorted(A)
    names = [m['name'] for m in markers]
    if len(set(names)) != len(names):
        warnings.append('duplicate chapter names in chapter_markers — the first marker of each name is used')
    plan_chapters = {b['ch'] for b in segs}
    for ch in sorted(plan_chapters - set(names)):
        warnings.append(f'base_segments chapter «{ch}» has no chapter marker — its material is not used for starts')

    def pause_before(i):
        return i == 0 or cw[i]['s'] - cw[i - 1]['e'] >= a.pause

    def last_assigned_before(i):
        k = bisect.bisect_left(assigned, i) - 1
        return assigned[k] if k >= 0 else None

    def snap(t, lo, hi_sec):
        return snap_after_pause(cw, t, lo, hi_sec, a.pause, a.window)

    # ── 3. первый прогон главы, монотонно по маркерам ──
    by_ch = {}
    for r in runs:
        by_ch.setdefault(r['ch'], []).append(r)
    first, inverted = {}, set()                            # имя → прогон; главы с инверсией (не «missing»)
    prev_i0, prev_name = -1, None
    for m in markers:
        rs = by_ch.get(m['name']) or []
        if not rs:
            continue
        big = [r for r in rs if r['n'] >= a.min_anchor_words] or [max(rs, key=lambda r: r['n'])]
        after = [r for r in big if r['i0'] > prev_i0]
        before = [r for r in big if r['i0'] <= prev_i0]
        if after:
            first[m['name']] = after[0]
            for r in before:
                warnings.append(f'«{m["name"]}»: {r["n"]} matched words at {tcf(cw[r["i0"]]["s"])} come before the start of '
                                f'«{prev_name}» — treated as an echo / repeat, not the chapter start')
            prev_i0, prev_name = after[0]['i0'], m['name']
        else:
            r = before[0]
            inverted.add(m['name'])
            inversions.append(f'«{m["name"]}» material first appears at {tcf(cw[r["i0"]]["s"])} (plan {tcf(A[r["i0"]]["p_s"])}), '
                              f'but only BEFORE «{prev_name}» starts ({tcf(cw[prev_i0]["s"])}): the cut order differs from '
                              f'the plan (the editor moved this chapter earlier, or the plan order is wrong)')

    # ── 4–5. начала ──
    res = {}
    for k, m in enumerate(markers):
        r = first.get(m['name'])
        if r is None:
            continue
        f = r['i0']
        l = last_assigned_before(f)
        u0 = (l + 1) if l is not None else 0
        has_u = u0 < f
        p_f = A[f]['p_s']
        if k == 0 and m['M'] <= 0.5:
            res[m['name']] = {'sec_raw': 0.0, 'idx': None, 'method': 'film_start', 'f': f, 'l': l, 'from': 0.0}
            continue
        if m['M'] < p_f - a.tol and has_u:
            if l is not None and A[l]['p_e'] <= m['M'] + a.tol and p_f - A[l]['p_e'] > 0.5:
                t = cw[l]['e'] + (m['M'] - A[l]['p_e']) * (cw[f]['s'] - cw[l]['e']) / (p_f - A[l]['p_e'])
                method = 'interpolated' if t > cw[u0]['s'] + a.window else 'absorbed'
                t = max(t, cw[u0]['s'])
            else:
                t, method = cw[u0]['s'], 'absorbed'
            i = snap(t, l, cw[f]['s'])
        else:
            t, method = cw[f]['s'], 'anchor'
            i = f if pause_before(f) else snap(t, l, cw[f]['s'] + a.window)
        i = f if i is None else i
        res[m['name']] = {'sec_raw': cw[i]['s'], 'idx': i, 'method': method, 'f': f, 'l': l, 'from': t}

    # глава без материала v4: интерполяция в несопоставленной речи (или в тишине) перед следующей главой с материалом
    missing = []
    for k, m in enumerate(markers):
        if m['name'] in res or m['name'] in first or m['name'] in inverted:
            continue
        nxt = next((x for x in markers[k + 1:] if x['name'] in res), None)
        prv = next((x for x in reversed(markers[:k]) if x['name'] in res), None)
        why = ''
        if nxt is None:
            why = 'no later chapter with v4 material to anchor to'
        else:
            f = res[nxt['name']]['f']
            l = last_assigned_before(f)
            u0 = (l + 1) if l is not None else 0
            lo = res[prv['name']]['sec_raw'] if prv else -1.0
            hi = res[nxt['name']]['sec_raw']
            if u0 >= f:
                # речи нет, но есть тишина (титры / эпик-монтаж без слов): ставим по плану внутрь тишины, без привязки к слову
                g0, g1 = (cw[l]['e'] if l is not None else 0.0), cw[f]['s']
                if l is not None and g1 - g0 >= 2.0 and A[l]['p_e'] - a.tol <= m['M'] < A[f]['p_s']:
                    t = g0 + (m['M'] - A[l]['p_e']) * (g1 - g0) / max(0.5, A[f]['p_s'] - A[l]['p_e'])
                    margin = min(0.5, (g1 - g0) / 4)
                    t = min(max(t, g0 + margin), g1 - margin)
                    if lo < t < hi:
                        res[m['name']] = {'sec_raw': t, 'idx': None, 'method': 'missing_silence', 'f': None, 'l': l, 'from': t}
                        warnings.append(f'«{m["name"]}»: no speech of this chapter in the cut — start {tcf(t)} placed along the '
                                        f'plan inside the {g1 - g0:.1f} s pause before «{nxt["name"]}»; check by eye')
                        continue
                why = f'no unmatched speech or pause ≥ 2 s right before «{nxt["name"]}» ({tcf(cw[f]["s"])})'
            elif l is None or not (A[l]['p_e'] - a.tol <= m['M'] < A[f]['p_s']):
                why = 'its plan position is not between the neighbouring matched material'
            else:
                t = cw[l]['e'] + (m['M'] - A[l]['p_e']) * (cw[f]['s'] - cw[l]['e']) / max(0.5, A[f]['p_s'] - A[l]['p_e'])
                t = max(t, cw[u0]['s'])
                i = snap(t, l, cw[f]['s'])
                if i is not None and lo < cw[i]['s'] < hi:
                    res[m['name']] = {'sec_raw': cw[i]['s'], 'idx': i, 'method': 'missing_interpolated', 'f': None,
                                      'l': l, 'from': t}
                    warnings.append(f'«{m["name"]}»: no v4 material in the cut (inserts only) — start {tcf(cw[i]["s"])} '
                                    f'interpolated along the plan between matched neighbours; check by eye')
                    continue
                why = f'the interpolated start does not fit between «{prv["name"] if prv else "film start"}» and «{nxt["name"]}»'
        missing.append(m['name'])
        warnings.append(f'«{m["name"]}» (plan {tcf(m["M"])}): chapter not placed — {why}')

    chapters, prev = [], None
    for m in markers:
        x = res.get(m['name'])
        if x is None:
            continue
        fr, sec = frame_floor(x['sec_raw'])
        ch = {'name': m['name'], 'sec': sec, 'frame': fr, 'tc': tcf(sec), 'method': x['method'], 'plan_tc_sec': m['M'],
              'first_mapped_sec': round(cw[x['f']]['s'], 3) if x.get('f') is not None else None,
              'first_mapped_tc': tcf(cw[x['f']]['s']) if x.get('f') is not None else '',
              'mapped_words': sum(r['n'] for r in by_ch.get(m['name']) or []),
              'runs': [[round(cw[r['i0']]['s'], 2), round(cw[r['i1']]['e'], 2), r['n']] for r in (by_ch.get(m['name']) or [])][:8],
              'snapped_from': round(x['from'], 3),
              'pause_before': (round(cw[x['idx']]['s'] - cw[x['idx'] - 1]['e'], 2) if x['idx'] else None),
              'first_mapped_pause': (round(cw[x['f']]['s'] - cw[x['f'] - 1]['e'], 2) if x.get('f') else None)}
        if prev is not None and ch['sec'] <= prev['sec']:
            inversions.append(f'«{ch["name"]}» starts at {ch["tc"]}, not after «{prev["name"]}» ({prev["tc"]}) — starts must '
                              f'strictly increase in plan order')
        chapters.append(ch)
        prev = ch
    # материал главы глубоко внутри чужой главы — перестановка или повтор
    for i, ch in enumerate(chapters):
        end = chapters[i + 1]['sec'] if i + 1 < len(chapters) else float('inf')
        for r in by_ch.get(ch['name']) or []:
            if r['n'] >= a.min_anchor_words and cw[r['i0']]['s'] >= end + a.window:
                warnings.append(f'«{ch["name"]}»: {r["n"]} matched words at {tcf(cw[r["i0"]]["s"])}–{tcf(cw[r["i1"]]["e"])} '
                                f'sit inside a later chapter — moved or repeated material')
    for n, ch in enumerate(chapters, 1):
        ch['n'] = f'{n:02d}'
    return chapters, missing, warnings, inversions, {'mapped_words': len(mapping), 'assigned_words': len(A),
                                                      'runs': len(runs)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--plan')
    ap.add_argument('--cut-words')
    ap.add_argument('--against-words')
    ap.add_argument('--align', default=str(W6 / 'align.json'))
    ap.add_argument('--out', default=str(W6 / 'chapters_proposal.json'))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--pause', type=float, default=0.3)
    ap.add_argument('--window', type=float, default=3.0)
    ap.add_argument('--tol', type=float, default=1.0)
    ap.add_argument('--min-span-words', type=int, default=8)
    ap.add_argument('--min-run-words', type=int, default=6)
    ap.add_argument('--min-anchor-words', type=int, default=12)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    plan = a.plan or (P.resolve(P.get('chapters_plan')) if P.get('chapters_plan') else '')
    cutp = a.cut_words or P.WORDS
    against = a.against_words or default_against()
    for label, p in (('plan (card chapters_plan / --plan)', plan), ('cut words', cutp),
                     ('against words (card align_against / --against-words)', against), ('align.json', a.align)):
        if not p or not Path(p).exists():
            print(f'[chapters] no input: {label} → {p or "—"}', file=sys.stderr)
            return 1
    schema, markers, segs = load_plan(plan)
    if schema and schema != 'ytai-part-v1':
        print(f'[chapters] ⚠️ plan schema {schema!r} (expected ytai-part-v1)', flush=True)
    cw, bw = load_words(cutp), load_words(against)
    al = json.load(open(a.align, encoding='utf-8'))
    tag, base = pick_base(al, against)
    chapters, missing, warnings, inversions, stats = build(cw, bw, base, markers, segs, a)
    status = 'inversion' if inversions else 'ok'
    patch = {'chapters': [[c['sec'], c['n']] for c in chapters], 'ch_name': {c['n']: c['name'] for c in chapters}}
    out = {'schema': 'chapters-proposal-v1', 'code': P.CODE, 'cut_version': P.CUT_VERSION, 'status': status,
           'plan': str(plan), 'cut_words': str(cutp), 'against_words': str(against), 'align': str(a.align),
           'base_tag': tag, 'fps_exact': P.FPS_EXACT,
           'params': {k: getattr(a, k) for k in ('pause', 'window', 'tol', 'min_span_words', 'min_run_words', 'min_anchor_words')},
           'stats': stats, 'chapters': chapters, 'missing': missing, 'warnings': warnings, 'inversions': inversions,
           'card_patch': patch}
    P.write_json_atomic(a.out, out)
    lines = [f'[chapters] {P.CODE} {P.CUT_VERSION} · plan {Path(plan).name} · markers {len(markers)} · placed {len(chapters)} · '
             f'missing {len(missing)} · words mapped {stats["assigned_words"]}/{len(cw)} → {a.out}']
    if not a.quiet:
        for c in chapters:
            lines.append(f'  {c["n"]} {c["tc"]:>9} {c["method"]:<20} plan {tcf(c["plan_tc_sec"]):>8} · first v4 match '
                         f'{c["first_mapped_tc"] or "—":>8} · words {c["mapped_words"]:>4} · {c["name"]}')
    for w in warnings:
        lines.append(f'  ⚠️ {w}')
    if inversions:
        lines.append('  ⛔ INVERSION — chapter starts do not follow the plan order; the card is NOT changed. Ask Roman:')
        lines += [f'     · {x}' for x in inversions]
        lines.append('     options: (a) the plan order stands → the moved piece is a structure fix for the editor; '
                     '(b) the cut order stands → reorder / rename the chapter markers in the plan and rerun')
        print('\n'.join(lines), flush=True)
        return 2
    if a.apply:
        card = P.CARD_PATH
        if card is None or not Path(card).exists():
            print('\n'.join(lines + ['  no card to patch (YTAI_CARD)']), flush=True)
            return 1
        raw = json.loads(Path(card).read_text(encoding='utf-8'))
        bak = Path(card).with_name(Path(card).name + '.bak-chapters-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        bak.write_text(Path(card).read_text(encoding='utf-8'), encoding='utf-8')
        raw['chapters'], raw['ch_name'] = patch['chapters'], patch['ch_name']
        P.write_json_atomic(card, raw)
        lines.append(f'  card patched: chapters {len(patch["chapters"])} · ch_name → {card} (backup {bak.name})')
    print('\n'.join(lines), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
