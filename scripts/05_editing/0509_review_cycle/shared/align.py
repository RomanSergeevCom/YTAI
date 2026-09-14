#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""align.py — n-gram сверка транскрипта ката с планом / прошлыми версиями / исходниками (наследник a4_align_v4, a2_align).

usage: align.py [--cut words.json] --against <words.json|assembly.json> [...] [--n 4] [--min-match 6]
                [--hole-sec 5] [--hole-words 8] [--out W6/align.json] [--quiet]

Кат по умолчанию — P.WORDS (карточка фильма, env YTAI_CARD). Базы:
  • words.json (wordrole: segments[].words[{w,s,e}] в секундах) — прошлая версия ката, план, другой рендер;
  • *_Claude4_assembly.json (segments[].{scene, source_file, words[{w,s,e "M:SS.sss"}]}) — исходники съёмки:
    адрес каждого куска ката = сцена · файл · src-TC.
Выход W6/align.json:
  {cut, cut_words, speech_end, bases: {tag: {file, kind, coverage_pct, covered_sec, spans, cut_map, new, unused, moved}}}
  cut_map — спаны ката, найденные в базе [{cut_t0, cut_t1, tag, base_t0, base_t1, words, text}]
            (для исходников tag = «сцена|файл»);
  new     — речь ката, которой в базе нет (дыры ≥ hole-sec и ≥ hole-words слов): CTA, графика, чужие синхроны;
  unused  — речь базы, не вошедшая в кат (та же логика по оси базы; для исходников — по каждому файлу);
  moved   — спаны, идущие в базе не по порядку (перестановки > 8 с).
coverage_pct считается по словам ката, попавшим в найденные спаны. Сводка в консоль — строка на базу.
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
from _bootstrap import P, W6  # noqa: E402


def norm(w):
    return re.sub(r'[^а-яa-z0-9]', '', str(w).lower().replace('ё', 'е'))


def tosec(x):
    if isinstance(x, (int, float)):
        return float(x)
    p = [float(v) for v in str(x).replace(',', '.').split(':')]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else (p[0] * 60 + p[1] if len(p) == 2 else p[0])


def tc(s):
    s = int(s)
    return f'{s // 60}:{s % 60:02d}'


def load_base(path):
    """→ (kind, words[(n, raw, tag, s, e)]) — words.json или Claude4_assembly.json"""
    d = json.load(open(path, encoding='utf-8'))
    segs = d.get('segments') or []
    is_asm = any(('scene' in s or 'source_file' in s) for s in segs[:5])
    out = []
    for seg in segs:
        tag = f'{seg.get("scene", "")}|{seg.get("source_file", "")}' if is_asm else Path(path).stem
        for w in seg.get('words') or []:
            n = norm(w.get('w', ''))
            if n:
                out.append((n, w['w'], tag, tosec(w['s']), tosec(w['e'])))
    if not is_asm:
        out.sort(key=lambda x: x[3])
    return ('assembly' if is_asm else 'words'), out


def align(cw, sw, N=4, min_match=6):
    """cw/sw: [(n, raw, tag, s, e)]. Жадно: кандидаты по N-грамме, растяжение с допуском 2 промахов,
    спан не пересекает границу tag ни в запросе, ни в базе. → [{q_t0, q_t1, tag, b_t0, b_t1, words, text, qi0, qi1}]"""
    idx = collections.defaultdict(list)
    for i in range(len(sw) - N + 1):
        idx[tuple(x[0] for x in sw[i:i + N])].append(i)
    matches, ci = [], 0
    while ci <= len(cw) - N:
        cands = idx.get(tuple(x[0] for x in cw[ci:ci + N]))
        if not cands:
            ci += 1
            continue
        best = None
        for si0 in cands[:50]:
            si, cj, miss = si0, ci, 0
            while cj < len(cw) and si < len(sw) and miss <= 2:
                if cw[cj][2] != cw[ci][2] or sw[si][2] != sw[si0][2]:
                    break
                if cw[cj][0] == sw[si][0]:
                    cj += 1; si += 1; miss = 0
                elif cj + 1 < len(cw) and cw[cj + 1][0] == sw[si][0]:
                    cj += 2; si += 1
                elif si + 1 < len(sw) and cw[cj][0] == sw[si + 1][0]:
                    cj += 1; si += 2
                else:
                    miss += 1; cj += 1; si += 1
            ln = si - si0 - miss
            if best is None or ln > best[2]:
                best = (si0, cj - miss, ln)
        si0, cend, ln = best
        if ln >= min_match:
            cend = max(cend, ci + 1)
            s_first, s_last = sw[si0], sw[min(si0 + ln - 1, len(sw) - 1)]
            matches.append({'q_t0': cw[ci][3], 'q_t1': cw[cend - 1][4], 'tag': s_first[2], 'q_tag': cw[ci][2],
                            'b_t0': s_first[3], 'b_t1': s_last[4], 'words': ln,
                            'text': ' '.join(x[1] for x in cw[ci:cend])[:150], 'qi0': ci, 'qi1': cend - 1})
            ci = cend
        else:
            ci += 1
    merged = []
    for m in matches:                                    # склейка соседей: тот же файл с обеих сторон, зазоры неотрицательные
        if (merged and m['tag'] == merged[-1]['tag'] and m['q_tag'] == merged[-1]['q_tag']
                and 0 <= m['q_t0'] - merged[-1]['q_t1'] < 2.0
                and 0 <= m['b_t0'] - merged[-1]['b_t1'] < 20.0):
            merged[-1]['q_t1'], merged[-1]['b_t1'] = m['q_t1'], m['b_t1']
            merged[-1]['words'] += m['words']
            merged[-1]['qi1'] = m['qi1']
        else:
            merged.append(dict(m))
    return merged


def holes(spans, words, hole_sec, hole_words, by_tag=False):
    """Дыры покрытия по оси запроса (words) — куски ≥ hole_sec и ≥ hole_words слов; для исходников — внутри файла."""
    groups = collections.defaultdict(list)
    for w in words:
        groups[w[2] if by_tag else ''].append(w)
    res = []
    for tag, ws in groups.items():
        ws.sort(key=lambda x: x[3])
        iv = sorted((m['q_t0'], m['q_t1']) for m in spans if (not by_tag or m.get('q_tag') == tag))
        cur, out = ws[0][3], []
        for a, b in iv:
            if a - cur > hole_sec:
                out.append((cur, a))
            cur = max(cur, b)
        if ws[-1][4] - cur > hole_sec:
            out.append((cur, ws[-1][4]))
        for a, b in out:
            seg = [raw for n, raw, t, s, e in ws if a <= s < b]
            if len(seg) >= hole_words:
                res.append({**({'tag': tag} if by_tag else {}), 't0': round(a, 2), 't1': round(b, 2),
                            'sec': round(b - a, 1), 'words': len(seg), 'text': ' '.join(seg)[:400]})
    res.sort(key=lambda x: (x.get('tag', ''), x['t0']))
    return res


def moved(spans):
    """Перестановки: спаны (>8 с), идущие в базе не по порядку относительно соседей того же tag."""
    s = sorted(spans, key=lambda m: m['q_t0'])
    out = []
    for i, m in enumerate(s):
        if m['q_t1'] - m['q_t0'] <= 8:
            continue
        prev = next((x for x in reversed(s[:i]) if x['tag'] == m['tag']), None)
        nxt = next((x for x in s[i + 1:] if x['tag'] == m['tag']), None)
        if (prev and m['b_t0'] < prev['b_t0'] - 30) or (nxt and m['b_t0'] > nxt['b_t0'] + 30):
            out.append({'cut_t0': round(m['q_t0'], 1), 'cut_t1': round(m['q_t1'], 1), 'tag': m['tag'],
                        'base_t0': round(m['b_t0'], 1), 'base_t1': round(m['b_t1'], 1), 'text': m['text']})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--cut', default=P.WORDS)
    ap.add_argument('--against', nargs='+', required=True)
    ap.add_argument('--n', type=int, default=4)
    ap.add_argument('--min-match', type=int, default=6)
    ap.add_argument('--hole-sec', type=float, default=5.0)
    ap.add_argument('--hole-words', type=int, default=8)
    ap.add_argument('--out', default=str(W6 / 'align.json'))
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args()

    _, cw = load_base(a.cut)
    cw = [(n, raw, 'cut', s, e) for n, raw, t, s, e in cw]
    if len(cw) < a.n:
        raise SystemExit(f'в кате {a.cut} слишком мало слов ({len(cw)})')
    total = cw[-1][4]
    res = {'cut': str(a.cut), 'cut_words': len(cw), 'speech_end': round(total, 2), 'bases': {}}
    lines = [f'[align] {P.CODE} {P.CUT_VERSION} · кат {Path(a.cut).name}: слов {len(cw)}, речь до {tc(total)}']
    for bp in a.against:
        kind, bw = load_base(bp)
        if not bw:
            lines.append(f'  {Path(bp).name}: нет слов — пропуск')
            continue
        tag = Path(bp).stem.replace('.words', '')
        fwd = align(cw, bw, a.n, a.min_match)
        covered_words = sum(m['qi1'] - m['qi0'] + 1 for m in fwd)
        cov_sec = sum(m['q_t1'] - m['q_t0'] for m in fwd)
        rev = align(bw, cw, a.n, a.min_match)                # ось запроса = база (q_tag = файл исходника)
        new = holes(fwd, cw, a.hole_sec, a.hole_words)
        unused = holes(rev, bw, a.hole_sec, a.hole_words, by_tag=(kind == 'assembly'))
        mv = moved(fwd)
        cut_map = [{'cut_t0': round(m['q_t0'], 2), 'cut_t1': round(m['q_t1'], 2), 'tag': m['tag'],
                    'base_t0': round(m['b_t0'], 2), 'base_t1': round(m['b_t1'], 2), 'words': m['words'], 'text': m['text']}
                   for m in fwd]
        pct = round(100.0 * covered_words / max(1, len(cw)), 1)
        res['bases'][tag] = {'file': str(bp), 'kind': kind, 'coverage_pct': pct, 'covered_sec': round(cov_sec, 1),
                             'spans': len(fwd), 'cut_map': cut_map, 'new': new, 'unused': unused, 'moved': mv}
        extra = ''
        if kind == 'assembly':
            sc = collections.Counter()
            for m in fwd:
                sc[m['tag'].split('|')[0]] += m['q_t1'] - m['q_t0']
            extra = ' · сцены: ' + ', '.join(f'{k} {v:.0f}с' for k, v in sc.most_common(6))
        lines.append(f'  vs {tag} ({kind}, слов {len(bw)}): покрытие {pct}% ({cov_sec:.0f}с) · спанов {len(fwd)} · '
                     f'нового в кате {len(new)} ({sum(x["sec"] for x in new):.0f}с) · не вошло из базы {len(unused)} '
                     f'({sum(x["sec"] for x in unused):.0f}с) · перестановок {len(mv)}{extra}')
    P.write_json_atomic(a.out, res)
    lines.append(f'  → {a.out}')
    print('\n'.join(lines)[:2000], flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
