#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_standalone.py — самодостаточная версия страницы структуры: один HTML без папок.

Берёт REVIEW_DIR/{CODE}_structure.html (его собирает build_structure_html.py), встраивает все
превью в data-URI (~1100 px, JPEG q78) и снимает обёртки-ссылки на 4K-файлы, которых не будет
рядом. Такой файл открывается где угодно — с телефона, из почты, без SSD.

Кладёт результат в КОРЕНЬ проекта ({project_name}.html — точка входа) и рядом с исходником
({CODE}_structure_standalone.html).

  python3 make_standalone.py [--src page.html] [--max-width 1100] [--quality 78]
"""
import argparse
import base64
import io
import re
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import P, REVIEW_DIR, relpath  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', default=str(REVIEW_DIR / f'{P.CODE}_structure.html'))
    ap.add_argument('--max-width', type=int, default=1100)
    ap.add_argument('--quality', type=int, default=78)
    a = ap.parse_args()
    src = Path(a.src)
    if not src.exists():
        raise SystemExit(f'нет {src} — сначала build_structure_html.py')
    outs = [Path(P.PROJECT_DIR) / f'{P.PROJECT_NAME}.html', REVIEW_DIR / f'{P.CODE}_structure_standalone.html']
    rel = relpath(P.MOCK, src.parent).replace('\\', '/')     # напр. «mockups» или «05_Review/mockups»
    rel_rx = re.escape(rel)

    h = src.read_text(encoding='utf-8')
    # ссылки на 4K-оригиналы рядом с самодостаточным файлом не откроются — убираем обёртку <a>
    h = re.sub(rf'<a href="{rel_rx}/[^"]+" target="_blank">(<img[^>]+>)</a>', r'\1', h)
    cache = {}

    def data_uri(relp):
        if relp not in cache:
            im = Image.open(src.parent / relp).convert('RGB')
            im.thumbnail((a.max_width, a.max_width * 9 // 16))
            buf = io.BytesIO()
            im.save(buf, 'JPEG', quality=a.quality, optimize=True)
            cache[relp] = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
        return cache[relp]

    h = re.sub(rf'src="({rel_rx}/[^"]+)"', lambda m: f'src="{data_uri(m.group(1))}"', h)
    left = re.findall(rf'(?:src|href)="({rel_rx}/[^"]+)"', h)
    for out in outs:
        out.write_text(h, encoding='utf-8')
    print(f'картинок встроено: {len(cache)} · внешних ссылок осталось: {len(left)} · '
          f'размер {len(h.encode()) / 1e6:.1f} МБ')
    for out in outs:
        print('→', out)


if __name__ == '__main__':
    main()
