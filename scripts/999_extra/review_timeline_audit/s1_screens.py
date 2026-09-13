#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v6 S1: инвентарь ЭКРАНОВ ката из ocr.jsonl (1 fps) — умная группировка.

Отличие от night/s2: анимация «допечатки» титра даёт разный текст на соседних
секундах → там события дробились. Здесь секунды сливаются, если множества
контентных слов пересекаются (Jaccard ≥ .3 или одно ⊂ другого), дырка ≤ 2 с.
best = кадр с максимумом текста (устаканившийся титр), плюс last (последний кадр).

→ screens_v6.json: [{id, t0, t1, dur, best_sec, best_frame, last_frame, text_best,
                     lines_best[{t,c,x,y,bw,bh}], texts_all[], faces_avg, chapter}]
+ hires/ : кадры 1920×1080 из 4K-рендера для best (ffmpeg -ss) — для точного OCR/VLM.
"""
import json, os, re, subprocess, sys
from pathlib import Path

# ⚠️ В конвейере этот скрипт НЕ участвует: инвентарь экранов собирает s2_ocr_hires.py
# по hires-кадрам. Хуже того, здесь кадры именуются на единицу иначе (h{sec} против
# h{sec+1} у s2) — смешать два инвентаря значит сдвинуть ВСЕ таймкоды ревью на секунду.
# Оставлен только для археологии прошлых прогонов.
if os.environ.get('YTAI_ALLOW_S1') != '1':
    raise SystemExit(
        's1_screens.py не входит в конвейер — инвентарь экранов делает s2_ocr_hires.py.\n'
        'Нумерация кадров здесь на единицу другая: смешаешь с s2 — все таймкоды уедут на секунду.\n'
        'Если действительно нужно (разбор старого прогона): YTAI_ALLOW_S1=1 python3 s1_screens.py')

W6 = Path(__file__).parent
NIGHT = W6.parent / 'night'
HIRES = W6 / 'hires'
HIRES.mkdir(exist_ok=True)
RENDER = '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/03_Exports/YTUVI01_v1_Corundum_Ruby.mp4'

CHAPTERS = [(0, '01'), (135, '02'), (377, '03'), (675, '04'), (777, '05'), (916, '06'),
            (1558, '07'), (1731, '08'), (2019, '09'), (2322, '10')]


def chapter(sec):
    c = '01'
    for t, n in CHAPTERS:
        if sec >= t:
            c = n
    return c


def words(lines):
    s = set()
    for l in lines:
        for w in re.findall(r'[а-яёa-z0-9]+', l['t'].lower()):
            if len(w) >= 3 or w.isdigit():
                s.add(w)
    return s


recs = {}
for ln in open(NIGHT / 'ocr.jsonl', encoding='utf-8'):
    d = json.loads(ln)
    m = re.search(r'f(\d+)\.jpg', d['file'])
    sec = int(m.group(1)) - 1
    lines = [l for l in d.get('lines', []) if l.get('t', '').strip()]
    recs[sec] = {'sec': sec, 'faces': d.get('faces', 0), 'lines': lines, 'words': words(lines),
                 'frame': f'f{sec + 1:04d}.jpg'}

events, cur = [], None
for sec in sorted(recs):
    r = recs[sec]
    if not r['words']:
        continue
    if cur is not None and sec - cur['t1'] <= 2:
        u = cur['union']
        inter = len(u & r['words'])
        jac = inter / max(1, len(u | r['words']))
        sub = r['words'] <= u or u <= r['words'] or inter >= min(len(u), len(r['words'])) * .6
        if jac >= .3 or sub:
            cur['t1'] = sec
            cur['union'] |= r['words']
            cur['secs'].append(sec)
            continue
    cur = {'t0': sec, 't1': sec, 'union': set(r['words']), 'secs': [sec]}
    events.append(cur)

out = []
for i, e in enumerate(events):
    secs = e['secs']
    best = max(secs, key=lambda s: (sum(len(l['t']) for l in recs[s]['lines']), s))
    texts = []
    for s in secs:
        t = ' | '.join(l['t'] for l in recs[s]['lines'])
        if t and (not texts or texts[-1] != t):
            texts.append(t)
    out.append({
        'id': f's{i + 1:03d}', 't0': e['t0'], 't1': e['t1'], 'dur': e['t1'] - e['t0'] + 1,
        'chapter': chapter(e['t0']),
        'best_sec': best, 'best_frame': recs[best]['frame'], 'last_frame': recs[secs[-1]]['frame'],
        'text_best': ' | '.join(l['t'] for l in recs[best]['lines']),
        'lines_best': recs[best]['lines'],
        'texts_all': texts,
        'faces_avg': round(sum(recs[s]['faces'] for s in secs) / len(secs), 2),
    })

json.dump(out, open(W6 / 'screens_v6.json', 'w'), ensure_ascii=False, indent=1)
print('events:', len(out), '| секунд с текстом:', sum(len(e['secs']) for e in events))

# ── hires-кадры для best (и last, если отличается) ──
if '--no-frames' not in sys.argv:
    todo = []
    for e in out:
        for sec in {e['best_sec'], e['t1']}:
            p = HIRES / f'h{sec:04d}.jpg'
            if not p.exists():
                todo.append((sec, p))
    print('hires todo:', len(todo))
    for n, (sec, p) in enumerate(sorted(todo)):
        # середина секунды (fps=1 кадр night = t=sec+0.5? ffmpeg fps=1 берёт кадр ближайший к sec)
        subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-ss', f'{sec + 0.5:.2f}', '-i', RENDER,
                        '-frames:v', '1', '-vf', 'scale=1920:-2', '-q:v', '2', str(p)], check=False)
        if n % 50 == 0:
            print(f'  {n}/{len(todo)}', flush=True)
    print('hires done:', len(list(HIRES.glob('h*.jpg'))))
