#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сверка ката YTCH11_v2 с исходниками (Claude4_assembly). v1 у YTCH11 нет.

Выход:
  map_src.json — [{v2_t0,v2_t1,scene,src_file,src_t0,src_t1,words,text}] по исходникам
  v2_new.json  — спаны v2, НЕ покрытые исходниками (>5с речи) — CTA/графика/вставки
  stats.txt
"""
import json, re, os, collections

WORK = os.path.dirname(os.path.abspath(__file__))
P = '/Volumes/T7-Beige-RYA/YTCH/YTCH11_Liza_Vitalik'
V2W = P + '/00_Setup/05_Review/YTCH11_v2.words.json'
V2W_TMP = P + '/00_Setup/05_Review/_wordrole_work/YTCH11_v2_words.json'
ASM = P + '/00_Setup/YTCH11_Claude4_assembly.json'
N, MIN_MATCH = 4, 6


def norm(w):
    w = w.lower().replace('ё', 'е')
    return re.sub(r'[^а-яa-z0-9]', '', w)


def tosec(x):
    if isinstance(x, (int, float)):
        return float(x)
    p = [float(v) for v in str(x).split(':')]
    return p[0]*3600+p[1]*60+p[2] if len(p) == 3 else p[0]*60+p[1]


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


def align(cw, sw, scene_of=None):
    """cw: [(n,raw,s,e)] запрос; sw: [(n,raw,tag,s,e)] источник."""
    idx = collections.defaultdict(list)
    for i in range(len(sw) - N + 1):
        idx[tuple(x[0] for x in sw[i:i+N])].append(i)
    matches, ci = [], 0
    while ci < len(cw) - N:
        cands = idx.get(tuple(x[0] for x in cw[ci:ci+N]))
        if not cands:
            ci += 1
            continue
        best = None
        for si0 in cands[:50]:
            si, cj, miss = si0, ci, 0
            while cj < len(cw) and si < len(sw) and miss <= 2:
                if cw[cj][0] == sw[si][0]:
                    cj += 1; si += 1; miss = 0
                elif cj+1 < len(cw) and cw[cj+1][0] == sw[si][0]:
                    cj += 2; si += 1
                elif si+1 < len(sw) and cw[cj][0] == sw[si+1][0]:
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
            s_first, s_last = sw[si0], sw[min(si0+ln-1, len(sw)-1)]
            matches.append({'v2_t0': cw[ci][2], 'v2_t1': cw[min(cend-1, len(cw)-1)][3],
                            'tag': s_first[2], 'src_t0': s_first[3], 'src_t1': s_last[4],
                            'words': ln, 'text': ' '.join(x[1] for x in cw[ci:cend])[:150]})
            ci = cend
        else:
            ci += 1
    merged = []
    for m in matches:
        if (merged and m['tag'] == merged[-1]['tag']
                and m['v2_t0'] - merged[-1]['v2_t1'] < 2.0
                and abs(m['src_t0'] - merged[-1]['src_t1']) < 20.0):
            merged[-1]['v2_t1'] = m['v2_t1']
            merged[-1]['src_t1'] = m['src_t1']
            merged[-1]['words'] += m['words']
        else:
            merged.append(dict(m))
    return merged


def main():
    v2p = V2W if os.path.exists(V2W) else V2W_TMP
    cw = load_words(v2p)
    print('v2 words:', len(cw))

    # --- источники: assembly
    asm = json.load(open(ASM, encoding='utf-8'))
    sw2 = []
    for seg in asm['segments']:
        for w in seg.get('words') or []:
            n = norm(w['w'])
            if n:
                sw2.append((n, w['w'], seg['scene'] + '|' + seg['source_file'],
                            tosec(w['s']), tosec(w['e'])))
    m2 = align(cw, sw2)
    for m in m2:
        sc, sf = m['tag'].split('|', 1)
        m['scene'], m['src_file'] = sc, sf
        del m['tag']
    json.dump(m2, open(os.path.join(WORK, 'map_src.json'), 'w'), ensure_ascii=False, indent=1)
    cov2 = sum(m['v2_t1']-m['v2_t0'] for m in m2)

    # --- не покрыто исходниками: дыры покрытия map_src > 5с с речью
    iv = sorted([(m['v2_t0'], m['v2_t1']) for m in m2])
    holes, cur = [], 0.0
    for a, b in iv:
        if a - cur > 5.0:
            holes.append((cur, a))
        cur = max(cur, b)
    total = cw[-1][3]
    if total - cur > 5.0:
        holes.append((cur, total))
    new = []
    for a, b in holes:
        wtxt = ' '.join(raw for n, raw, s, e in cw if a <= s < b)
        if len(wtxt.split()) < 8:
            continue
        att = [m for m in m2 if m['v2_t0'] < b and m['v2_t1'] > a]
        scenes = collections.Counter()
        for m in att:
            scenes[m['scene']] += m['v2_t1']-m['v2_t0']
        new.append({'v2_t0': round(a, 2), 'v2_t1': round(b, 2),
                    'scenes': dict(scenes.most_common(3)),
                    'text': wtxt[:400]})
    json.dump(new, open(os.path.join(WORK, 'v2_new.json'), 'w'), ensure_ascii=False, indent=1)

    rep = ['v2 speech: %.0fs' % total,
           'covered by sources: %.0fs (%.0f%%), spans %d' % (cov2, 100*cov2/total, len(m2)),
           'not covered by sources (>5s): %d spans, %.0fs' % (len(new), sum(x['v2_t1']-x['v2_t0'] for x in new))]
    open(os.path.join(WORK, 'stats.txt'), 'w').write('\n'.join(rep))
    print('\n'.join(rep))
    for x in new[:30]:
        print('NEW %6.0f-%6.0f %s | %s' % (x['v2_t0'], x['v2_t1'], list(x['scenes'])[:1], x['text'][:80]))


if __name__ == '__main__':
    main()
