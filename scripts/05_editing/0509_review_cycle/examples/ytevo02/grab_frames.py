#!/usr/bin/env python3
"""grab_frames.py — кадры по СКВОЗНОМУ таймкоду съёмочного дня YTEVO01.

Пять клипов лежат встык на одной таймлинии (C0005..C0009). Скрипт переводит
глобальную секунду в пару (файл, смещение) и дёргает кадр через ffmpeg.

  python3 grab_frames.py --every 10                 # сетка каждые 10 с
  python3 grab_frames.py --at 0,45.5,300 --width 1280
"""
import argparse
import subprocess
from pathlib import Path

SRC = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/01_Source/Video/01_Evolution_Manifesto/CAM-A")

# (имя, длительность) в порядке укладки на таймлинию
CLIPS = [
    ("C0005.MP4", 342.720),
    ("C0006.MP4", 342.720),
    ("C0007.MP4", 341.760),
    ("C0008.MP4", 20.160),
    ("C0009.MP4", 341.760),
]
TOTAL = sum(d for _, d in CLIPS)


def resolve(t):
    """глобальная секунда -> (файл, смещение внутри файла)"""
    acc = 0.0
    for name, dur in CLIPS:
        if t < acc + dur:
            return name, t - acc
        acc += dur
    name, dur = CLIPS[-1]
    return name, dur - 0.05


def tc(t):
    m, s = divmod(t, 60)
    return f"{int(m):02d}m{s:06.3f}s".replace(".", "_")


def grab(t, outdir, width):
    name, off = resolve(t)
    out = outdir / f"t{tc(t)}__{Path(name).stem}.jpg"
    if out.exists():
        return out
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{off:.3f}", "-i", str(SRC / name), "-frames:v", "1",
         "-vf", f"scale={width}:-2", "-q:v", "3", str(out)],
        check=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=None)
    ap.add_argument("--at", default=None, help="список секунд через запятую")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--outdir", default=str(Path(__file__).resolve().parent / "frames"))
    a = ap.parse_args()

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if a.at:
        times = [float(x) for x in a.at.split(",") if x.strip()]
    elif a.every:
        times = [t for t in frange(0.0, TOTAL, a.every)]
    else:
        ap.error("нужен --every или --at")

    for t in times:
        p = grab(t, outdir, a.width)
        print(f"{t:8.2f}  {p.name}")


def frange(start, stop, step):
    t = start
    while t < stop:
        yield t
        t += step


if __name__ == "__main__":
    main()
