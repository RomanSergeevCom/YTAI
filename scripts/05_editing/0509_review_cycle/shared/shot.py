#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shot.py — уменьшенная копия картинки для чтения в главном потоке сессии.

Сырой Retina-скриншот 600 КБ ≈ 1 600 токенов; кроп 800 px ≈ 500. Правило гигиены:
в поток попадают только копии, сделанные этим скриптом.

    shot.py <png|jpg> [--max 1280] [--crop x,y,w,h] [--bbox x,y,w,h (0..1)] [--pad 0.06] [--out path]
    shot.py hires/h0312.jpg --bbox 0.12,0.71,0.55,0.09 --max 800      # кроп по OCR-bbox с полями

Печатает путь копии (по умолчанию — в $YTAI_SCRATCH или /tmp/ytai_shots/).
"""
import argparse
import os
import sys
from pathlib import Path

from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--max', type=int, default=1280, help='длинная сторона результата, px')
    ap.add_argument('--crop', help='x,y,w,h в пикселях')
    ap.add_argument('--bbox', help='x,y,w,h нормированные 0..1 (OCR-bbox)')
    ap.add_argument('--pad', type=float, default=0.06, help='поля вокруг bbox, доля кадра')
    ap.add_argument('--out')
    ap.add_argument('--quality', type=int, default=82)
    a = ap.parse_args()
    im = Image.open(a.src)
    if im.mode in ('RGBA', 'P', 'LA'):
        bg = Image.new('RGB', im.size, (16, 16, 20))
        bg.paste(im.convert('RGBA'), mask=im.convert('RGBA').split()[-1])
        im = bg
    else:
        im = im.convert('RGB')
    W, H = im.size
    if a.bbox:
        x, y, w, h = [float(v) for v in a.bbox.split(',')]
        px, py = a.pad * W, a.pad * H
        box = (max(0, x * W - px), max(0, y * H - py), min(W, (x + w) * W + px), min(H, (y + h) * H + py))
        im = im.crop(tuple(int(v) for v in box))
    elif a.crop:
        x, y, w, h = [int(v) for v in a.crop.split(',')]
        im = im.crop((x, y, x + w, y + h))
    w, h = im.size
    if max(w, h) > a.max:
        k = a.max / max(w, h)
        im = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    out = a.out
    if not out:
        d = Path(os.environ.get('YTAI_SCRATCH', '/tmp/ytai_shots'))
        d.mkdir(parents=True, exist_ok=True)
        tag = ('_bbox' if a.bbox else '_crop' if a.crop else '') + f'_{a.max}'
        out = str(d / (Path(a.src).stem + tag + '.jpg'))
    im.save(out, 'JPEG', quality=a.quality, optimize=True)
    print(f'{out}  ({im.size[0]}×{im.size[1]}, {os.path.getsize(out) // 1024} КБ)')


if __name__ == '__main__':
    sys.exit(main())
