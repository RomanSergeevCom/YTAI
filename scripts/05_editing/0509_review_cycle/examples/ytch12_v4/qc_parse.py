#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Техконтроль v4: qc_ffmpeg.log (run_local_v4.sh, стадия B) → qc.json.

  black    — чёрные прогоны (blackdetect d≥0.4, pix_th 0.10)
  freeze   — фризы кадра ≥2 с (freezedetect n=0.003)
  silence  — тишина ≥1.5 с на −45 dB (silencedetect)
  cuts     — склейки (select gt(scene,0.30) → pts_time)
  long_shots — планы без склейки ≥20 с
  loudness — ebur128 Summary: I (LUFS), LRA (LU), true peak (dBFS)
"""
import json
import os
import re
import subprocess

WORK = os.path.dirname(os.path.abspath(__file__))
RENDER = '/Volumes/T9-Black-RYA/YTCH/YTCH12_Sveta/03_Exports/YTCH12_Sveta_montage_1.mp4'


def pairs(starts, ends, total):
    out = []
    for i, a in enumerate(starts):
        b = ends[i] if i < len(ends) else total
        out.append({'t0': round(a, 2), 't1': round(b, 2), 'dur': round(b - a, 2)})
    return out


def main():
    L = open(os.path.join(WORK, 'qc_ffmpeg.log'), errors='ignore').read()
    total = float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                  '-of', 'csv=p=0', RENDER], capture_output=True, text=True).stdout)
    black = [{'t0': float(a), 't1': float(b), 'dur': float(c)} for a, b, c in
             re.findall(r'black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)', L)]
    freeze = pairs([float(x) for x in re.findall(r'freeze_start: ([\d.]+)', L)],
                   [float(x) for x in re.findall(r'freeze_end: ([\d.]+)', L)], total)
    silence = pairs([max(0.0, float(x)) for x in re.findall(r'silence_start: (-?[\d.]+)', L)],
                    [float(x) for x in re.findall(r'silence_end: ([\d.]+)', L)], total)
    cuts = sorted({round(float(x), 2) for x in re.findall(r'pts_time:([\d.]+)', L)})
    edges = [0.0] + cuts + [total]
    long_shots = [{'t0': a, 't1': b, 'dur': round(b - a, 1)}
                  for a, b in zip(edges, edges[1:]) if b - a >= 20]
    S = L[L.rfind('Summary:'):] if 'Summary:' in L else ''
    g = lambda pat: (lambda m: float(m.group(1)) if m else None)(re.search(pat, S))
    loud = {'I_LUFS': g(r'I:\s+(-?[\d.]+) LUFS'), 'LRA_LU': g(r'LRA:\s+([\d.]+) LU'),
            'TP_dBFS': g(r'Peak:\s+(-?[\d.]+) dBFS')}
    out = {'total_sec': round(total, 2), 'black': black, 'freeze': freeze, 'silence': silence,
           'cuts': cuts, 'long_shots': long_shots, 'loudness': loud,
           'summary': {'cuts': len(cuts), 'cuts_per_min': round(len(cuts) / (total / 60), 1),
                       'black_n': len(black), 'black_sec': round(sum(x['dur'] for x in black), 1),
                       'freeze_n': len(freeze), 'silence_n': len(silence),
                       'long_shots_n': len(long_shots)}}
    json.dump(out, open(os.path.join(WORK, 'qc.json'), 'w'), ensure_ascii=False, indent=1)
    s = out['summary']
    print('total %.1fs · cuts %d (%.1f/min) · black %d (%.1fs) · freeze %d · silence %d · long shots %d'
          % (total, s['cuts'], s['cuts_per_min'], s['black_n'], s['black_sec'], s['freeze_n'],
             s['silence_n'], s['long_shots_n']))
    print('loudness:', loud)


if __name__ == '__main__':
    main()
