#!/usr/bin/env python3
"""Экспорт вкладки ТЗ в PDF → PNG-страницы (для визуальной проверки).
usage: export_tab_pdf.py OUT_DIR [DPI] [TAB_ID]   (по умолчанию вкладка v4)"""
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path.home() / 'YTAI/scripts/999_extra/ytuvi_doctabs'))
from doctab_lib import DOCS, access_token  # noqa: E402

OUT = Path(sys.argv[1])
DPI = sys.argv[2] if len(sys.argv) > 2 else '70'
TAB = sys.argv[3] if len(sys.argv) > 3 else 't.917mzqkshtpx'   # v4; v3 = t.30zmdzjrl8w9
OUT.mkdir(parents=True, exist_ok=True)
url = f'https://docs.google.com/document/d/{DOCS["01"]}/export?format=pdf&tab={TAB}'
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {access_token()}'})
pdf = OUT / 'tab.pdf'
with urllib.request.urlopen(req) as r:
    pdf.write_bytes(r.read())
print('pdf', pdf.stat().st_size // 1024, 'KB')
subprocess.run(['pdftoppm', '-r', DPI, '-png', str(pdf), str(OUT / 'p')], check=True)
pages = sorted(OUT.glob('p-*.png'))
print('страниц:', len(pages), pages[0].name if pages else '')
