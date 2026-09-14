#!/usr/bin/env python3
"""make_standalone.py — самодостаточная версия страницы разбора: один HTML без папок.

Берёт 00_Setup/YTEVO02_structure.html (его собирает build_structure_html.py), встраивает
все превью в data-URI (~1100 px, JPEG q78) и снимает обёртки-ссылки на 4K-файлы, которых
не будет рядом. Такой файл открывается где угодно — с телефона, из почты, без SSD.

Кладёт результат в КОРЕНЬ проекта (чтобы сразу видеть, что это за папка) и рядом с исходником.

  python3 make_standalone.py
"""
import base64
import io
import re
from pathlib import Path

from PIL import Image

SETUP = Path("/Volumes/T9-Black-RYA/YTEVO/YTEVO02_evolution_manifesto/00_Setup")
PROJECT = SETUP.parent
SRC = SETUP / "YTEVO02_structure.html"
OUTS = [PROJECT / "YTEVO02_evolution_manifesto.html",          # в корне проекта — точка входа
        SETUP / "YTEVO02_structure_standalone.html"]
MAXW, QUALITY = 1100, 78


def main():
    h = SRC.read_text(encoding="utf-8")
    # ссылки на 4K-оригиналы рядом с самодостаточным файлом не откроются — убираем обёртку <a>
    h = re.sub(r'<a href="05_Review/[^"]+" target="_blank">(<img[^>]+>)</a>', r"\1", h)

    cache = {}

    def data_uri(rel):
        if rel not in cache:
            im = Image.open(SETUP / rel).convert("RGB")
            im.thumbnail((MAXW, MAXW * 9 // 16))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=QUALITY, optimize=True)
            cache[rel] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        return cache[rel]

    h = re.sub(r'src="(05_Review/[^"]+)"', lambda m: f'src="{data_uri(m.group(1))}"', h)
    left = re.findall(r'(?:src|href)="(05_Review/[^"]+)"', h)
    for out in OUTS:
        out.write_text(h, encoding="utf-8")
    print(f"картинок встроено: {len(cache)} · внешних ссылок осталось: {len(left)} · "
          f"размер {len(h.encode()) / 1e6:.1f} МБ")
    for out in OUTS:
        print("→", out)


if __name__ == "__main__":
    main()
