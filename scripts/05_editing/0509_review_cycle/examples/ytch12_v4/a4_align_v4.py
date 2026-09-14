#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сверка монтажа v4 (montage_1, 09.09) с тремя базами — n-gram по пословным транскриптам.

  (1) v3 = монтаж 31.08 (YTCH12_Sveta_montage.mp4) — что поменялось в последней итерации;
  (2) v2 = «История Светы» 26.08 — что осталось от прошлого ревью;
  (3) исходники (Claude4_assembly) — адрес каждого куска: сцена · файл · src-TC.

Выход (в папку скрипта):
  map_v3.json / map_v2.json   — [{v4_t0,v4_t1,b_t0,b_t1,words,text}] спаны v4, найденные в базе
  map_src.json                — [{v4_t0,v4_t1,scene,src_file,src_t0,src_t1,words,text}]
  diff_v3.json                — {'new': спаны v4 без v3, 'removed': спаны v3 без v4, 'moved': перестановки}
  diff_v2.json                — то же против v2
  nosrc_v4.json               — речь v4, не найденная в исходниках (>5с) — CTA/графика/чужие синхроны
  stats.txt
"""
import collections
import json
import os
import re

WORK = os.path.dirname(os.path.abspath(__file__))
P = '/Volumes/T7-Beige-RYA/YTCH/YTCH12_Sveta'
REV = P + '/00_Setup/05_Review'
ASM = P + '/00_Setup/YTCH12_Claude4_assembly.json'
N, MIN_MATCH = 4, 6
HOLE_SEC, HOLE_WORDS = 5.0, 8


def wpath(base):
    p = f'{REV}/{base}.words.json'
    return p if os.path.exists(p) else f'{REV}/_wordrole_work/{base}_words.json'


def norm(w):
    w = w.lower().replace('ё', 'е')
    return re.sub(r'[^а-яa-z0-9]', '', w)


def tosec(x):
    if isinstance(x, (int, float)):
        return float(x)
    p = [float(v) for v in str(x).split(':')]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def load_words(path):
    d = json.load(open(path, encoding='utf-8'))
    out = []
    for seg in d['segments']:
        for w in seg.get('words') or []:
            n = norm(w['w'])
            if n:
                out.append((n, w['w'], float(w['s']), float(w['e'])))
    out.sort(key=lambda x: x[2])
    return out


def align(cw, sw):
    """cw: [(n,raw,s,e)] запрос; sw: [(n,raw,tag,s,e)] база. Жадно, окно-кандидаты по N-граммам."""
    idx = collections.defaultdict(list)
    for i in range(len(sw) - N + 1):
        idx[tuple(x[0] for x in sw[i:i + N])].append(i)
    matches, ci = [], 0
    while ci < len(cw) - N:
        cands = idx.get(tuple(x[0] for x in cw[ci:ci + N]))
        if not cands:
            ci += 1
            continue
        best = None
        for si0 in cands[:50]:
            si, cj, miss = si0, ci, 0
            while cj < len(cw) and si < len(sw) and miss <= 2:
                if cw[cj][0] == sw[si][0]:
                    cj += 1; si += 1; miss = 0
                elif cj + 1 < len(cw) and cw[cj + 1][0] == sw[si][0]:
                    cj += 2; si += 1
                elif si + 1 < len(sw) and cw[cj][0] == sw[si + 1][0]:
                    cj += 1; si += 2
                else:
                    miss += 1; cj += 1; si += 1
                if si < len(sw) and sw[si][2] != sw[si0][2]:
                    break
            ln = si - si0
            if best is None or ln > best[2]:
                best = (si0, cj, ln)
        si0, cend, ln = best
        if ln >= MIN_MATCH:
            s_first, s_last = sw[si0], sw[min(si0 + ln - 1, len(sw) - 1)]
            matches.append({'v4_t0': cw[ci][2], 'v4_t1': cw[min(cend - 1, len(cw) - 1)][3],
                            'tag': s_first[2], 'b_t0': s_first[3], 'b_t1': s_last[4],
                            'words': ln, 'text': ' '.join(x[1] for x in cw[ci:cend])[:150]})
            ci = cend
        else:
            ci += 1
    merged = []
    for m in matches:
        if (merged and m['tag'] == merged[-1]['tag']
                and m['v4_t0'] - merged[-1]['v4_t1'] < 2.0
                and 0 <= m['b_t0'] - merged[-1]['b_t1'] < 20.0):
            merged[-1]['v4_t1'] = m['v4_t1']
            merged[-1]['b_t1'] = m['b_t1']
            merged[-1]['words'] += m['words']
        else:
            merged.append(dict(m))
    return merged


def holes(spans, words, key0, key1):
    """Дыры покрытия (>HOLE_SEC и >=HOLE_WORDS слов) в оси query."""
    iv = sorted((m[key0], m[key1]) for m in spans)
    out, cur = [], 0.0
    for a, b in iv:
        if a - cur > HOLE_SEC:
            out.append((cur, a))
        cur = max(cur, b)
    total = words[-1][3]
    if total - cur > HOLE_SEC:
        out.append((cur, total))
    res = []
    for a, b in out:
        ws = [raw for n, raw, s, e in words if a <= s < b]
        if len(ws) >= HOLE_WORDS:
            res.append({'t0': round(a, 2), 't1': round(b, 2), 'sec': round(b - a, 1),
                        'words': len(ws), 'text': ' '.join(ws)})
    return res


def moved(spans):
    """Перестановки: спаны, идущие в базе НЕ по порядку (b_t0 назад относительно соседей)."""
    s = sorted(spans, key=lambda m: m['v4_t0'])
    out = []
    for i in range(1, len(s) - 1):
        prev_b, cur_b, next_b = s[i - 1]['b_t0'], s[i]['b_t0'], s[i + 1]['b_t0']
        if (cur_b < prev_b - 30 or cur_b > next_b + 30) and s[i]['v4_t1'] - s[i]['v4_t0'] > 8:
            out.append({'v4_t0': round(s[i]['v4_t0'], 1), 'v4_t1': round(s[i]['v4_t1'], 1),
                        'b_t0': round(cur_b, 1), 'b_t1': round(s[i]['b_t1'], 1),
                        'text': s[i]['text']})
    return out


def diff_against(cw, base_name, tag):
    bw = load_words(wpath(base_name))
    fwd = align(cw, [(n, raw, tag, s, e) for n, raw, s, e in bw])
    # обратная сверка: база → v4 (что из базы выпало)
    rev = align(bw, [(n, raw, 'v4', s, e) for n, raw, s, e in cw])
    new = holes(fwd, cw, 'v4_t0', 'v4_t1')
    removed = holes(rev, bw, 'v4_t0', 'v4_t1')  # в rev ось query = база
    for m in fwd:
        del m['tag']
    return fwd, {'base': base_name, 'base_total': round(bw[-1][3], 1),
                 'new': new, 'removed': removed, 'moved': moved(fwd)}


def main():
    cw = load_words(wpath('YTCH12_v4'))
    total = cw[-1][3]
    print('v4 words:', len(cw), 'speech end: %.0fs' % total)
    rep = ['v4 words: %d · speech end %.0fs (%d:%02d)' % (len(cw), total, total // 60, total % 60)]

    for base, tag, fn in (('YTCH12_v3', 'v3', 'v3'), ('YTCH12_v2', 'v2', 'v2')):
        if not os.path.exists(wpath(base)):
            rep.append(f'{base}: нет транскрипта — пропуск')
            continue
        fwd, d = diff_against(cw, base, tag)
        json.dump(fwd, open(os.path.join(WORK, f'map_{fn}.json'), 'w'), ensure_ascii=False, indent=1)
        json.dump(d, open(os.path.join(WORK, f'diff_{fn}.json'), 'w'), ensure_ascii=False, indent=1)
        cov = sum(m['v4_t1'] - m['v4_t0'] for m in fwd)
        rep.append('vs %s (%.0fs): covered %.0fs (%.0f%%) · NEW %d spans %.0fs · REMOVED %d spans %.0fs · MOVED %d'
                   % (base, d['base_total'], cov, 100 * cov / total,
                      len(d['new']), sum(x['sec'] for x in d['new']),
                      len(d['removed']), sum(x['sec'] for x in d['removed']), len(d['moved'])))

    asm = json.load(open(ASM, encoding='utf-8'))
    sw = []
    for seg in asm['segments']:
        for w in seg.get('words') or []:
            n = norm(w['w'])
            if n:
                sw.append((n, w['w'], seg['scene'] + '|' + seg['source_file'],
                           tosec(w['s']), tosec(w['e'])))
    ms = align(cw, sw)
    for m in ms:
        sc, sf = m.pop('tag').split('|', 1)
        m['scene'], m['src_file'] = sc, sf
        m['src_t0'], m['src_t1'] = m.pop('b_t0'), m.pop('b_t1')
    json.dump(ms, open(os.path.join(WORK, 'map_src.json'), 'w'), ensure_ascii=False, indent=1)
    nos = holes(ms, cw, 'v4_t0', 'v4_t1')
    json.dump(nos, open(os.path.join(WORK, 'nosrc_v4.json'), 'w'), ensure_ascii=False, indent=1)
    cov = sum(m['v4_t1'] - m['v4_t0'] for m in ms)
    scenes = collections.Counter()
    for m in ms:
        scenes[m['scene']] += m['v4_t1'] - m['v4_t0']
    rep.append('vs sources: covered %.0fs (%.0f%%), spans %d · not in sources %d spans %.0fs'
               % (cov, 100 * cov / total, len(ms), len(nos), sum(x['sec'] for x in nos)))
    rep.append('scenes by speech sec: ' + ', '.join('%s %.0f' % (k, v) for k, v in scenes.most_common()))
    open(os.path.join(WORK, 'stats.txt'), 'w').write('\n'.join(rep) + '\n')
    print('\n'.join(rep))


if __name__ == '__main__':
    main()
