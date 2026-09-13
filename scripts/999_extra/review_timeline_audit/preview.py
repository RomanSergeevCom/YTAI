#!/usr/bin/env python3
"""preview.py <png> <sec> [out] — композит прозрачного оверлея 4K на кадр hires (1920) → jpg."""
import sys
from pathlib import Path
from PIL import Image
W6 = Path(__file__).parent
sys.path.insert(0, str(W6))
import proj_config as P  # noqa: E402
MOCK = Path(P.need('project_dir')) / '00_Setup/05_Review/mockups'
png, sec = sys.argv[1], int(sys.argv[2])
out = sys.argv[3] if len(sys.argv) > 3 else str(W6 / 'previews' / f'{Path(png).stem}_{sec}.jpg')
Path(out).parent.mkdir(exist_ok=True)
p = Path(png) if '/' in png else MOCK / (png if png.endswith('.png') else png + '.png')
bg = Image.open(W6 / 'hires' / f'h{sec + 1:04d}.jpg').convert('RGBA')
ov = Image.open(p).convert('RGBA').resize(bg.size, Image.LANCZOS)
Image.alpha_composite(bg, ov).convert('RGB').save(out, quality=88)
print(out)
