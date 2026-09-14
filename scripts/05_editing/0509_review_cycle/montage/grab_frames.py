#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grab_frames.py — кадры по СКВОЗНОМУ таймкоду съёмочного дня (режим montage_tz).

Клипы лежат встык на одной таймлинии (карточка `clips`: [{file, dur}] или [[file, start, end]]).
Скрипт переводит глобальную секунду в пару (файл, смещение) и дёргает кадр через ffmpeg.
Файлы ищутся в корне проекта и в 01_Source/Video / 01_Media/Source/Video (find_clip_file).

  python3 grab_frames.py --every 10                 # сетка каждые 10 с → REVIEW_DIR/frames
  python3 grab_frames.py --at 0,45.5,300 --width 1280
  python3 grab_frames.py --story                    # середины склеек montage.json → MOCK/story_frames
  python3 grab_frames.py --story --plan montage_plan_cam2.json   # то же для сцены (frames_sub из plan.scenes)
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import P, REVIEW_DIR, plan_clips, load_plan, clip_at, clips_total, find_clip_file, scene_plans  # noqa: E402


def tc(t):
    m, s = divmod(t, 60)
    return f'{int(m):02d}m{s:06.3f}s'.replace('.', '_')


def grab(clips, t, outdir, width, cache):
    name, off = clip_at(clips, t)
    out = outdir / f't{tc(t)}__{Path(name).stem}.jpg'
    if out.exists():
        return out
    if name not in cache:
        cache[name] = find_clip_file(name)
    src = cache[name]
    if src is None:
        raise SystemExit(f'клип {name} не найден в {P.PROJECT_DIR} (корень / 01_Source/Video / 01_Media/Source/Video)')
    subprocess.run(
        ['ffmpeg', '-nostdin', '-y', '-hide_banner', '-loglevel', 'error',
         '-ss', f'{off:.3f}', '-i', str(src), '-frames:v', '1',
         '-vf', f'scale={width}:-2', '-q:v', '3', str(out)],
        check=True)
    return out


def frange(start, stop, step):
    t = start
    while t < stop:
        yield t
        t += step


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--every', type=float, default=None)
    ap.add_argument('--at', default=None, help='список секунд через запятую')
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--outdir', default=None, help='по умолчанию REVIEW_DIR/frames (или MOCK/story_frames при --story)')
    ap.add_argument('--story', action='store_true', help='кадр в середине каждой склейки montage.json (для страницы структуры)')
    ap.add_argument('--plan', default=None, help='план сцены (по умолчанию главный план карточки)')
    a = ap.parse_args()

    plan = load_plan(a.plan) if a.plan else load_plan()
    clips = plan_clips(plan)
    total = clips_total(clips)
    frames_sub = 'story_frames'
    if a.plan:
        main_plan = load_plan()
        for p, sc in scene_plans(main_plan):
            if p.name == Path(a.plan).name and sc.get('frames_sub'):
                frames_sub = sc['frames_sub']
    outdir = Path(a.outdir) if a.outdir else (P.MOCK / frames_sub if a.story else REVIEW_DIR / 'frames')
    outdir.mkdir(parents=True, exist_ok=True)

    if a.story:
        import json
        mont_path = REVIEW_DIR / (plan.get('out') or 'montage.json')
        if not mont_path.exists():
            raise SystemExit(f'нет {mont_path} — сначала build_montage.py')
        mont = json.loads(mont_path.read_text(encoding='utf-8'))
        times = [round((x['src_in'] + x['src_out']) / 2, 2) for p in mont['pieces'] for x in p['parts'] if x['kind'] == 'say']
        a.width = a.width if a.width != 1280 else 1600
    elif a.at:
        times = [float(x) for x in a.at.split(',') if x.strip()]
    elif a.every:
        times = list(frange(0.0, total, a.every))
    else:
        ap.error('нужен --every, --at или --story')

    cache = {}
    for t in times:
        p = grab(clips, t, outdir, a.width, cache)
        print(f'{t:8.2f}  {p.name}')
    print(f'кадров: {len(times)} → {outdir}')


if __name__ == '__main__':
    main()
