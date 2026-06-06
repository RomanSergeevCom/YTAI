#!/usr/bin/env python3
"""
site_chrome.py — единый источник версии ассетов + хелперы для генераторов
страниц yt.rya.ae. Чтобы свежесгенерированная страница сразу имела общую
шапку-навигацию + клиент-гейт (site.css / site.js), генератор импортирует
этот модуль и вставляет head_block()/body_script() и html_attrs().

Первичный механизм всё равно — patch_site_chrome.py (прогон по всем
web/**/*.html после любой регенерации). Этот хелпер — лишь чтобы новые
страницы рождались уже совместимыми.

Cache-busting: бампнуть ASSET_V → заново прогнать patch_site_chrome.py.
"""

# ──────────────────────────────────────────────────────────────────────
# Единственное место с версией ассетов. patch_site_chrome.py импортит её.
ASSET_V = 5
MARK = "rya-site-v1"
# ──────────────────────────────────────────────────────────────────────

# Инлайн no-flash (скрыть контент до решения гейта) + страховочный таймер.
# Таймер снимает site.js (clearTimeout window.__ryaFailsafe); если site.js
# не загрузился — контент всё равно покажется (fail-open).
NOFLASH = (
    '<style id="rya-nf">html.rya-gating body{visibility:hidden}'
    '.rya-overlay,.rya-chrome{visibility:visible}</style>'
    '<script>document.documentElement.className+=" rya-gating";'
    'window.__ryaFailsafe=setTimeout(function(){'
    'document.documentElement.classList.remove("rya-gating")},3500);</script>'
)


def head_block(v: int = ASSET_V) -> str:
    """Блок для вставки перед </head>: маркер + no-flash + site.css."""
    return (
        f'\n<!-- {MARK} -->{NOFLASH}'
        f'<link rel="stylesheet" href="/assets/site.css?v={v}">\n'
    )


def body_script(v: int = ASSET_V) -> str:
    """Тег для вставки перед </body>."""
    return f'<script src="/assets/site.js?v={v}" defer></script>\n'


def html_attrs(channel=None, page=None, theme="core", haschrome=False, hub=False) -> str:
    """Строка атрибутов для тега <html …> (без ведущего пробела добавляйте сами)."""
    a = []
    if channel:
        a.append(f'data-channel="{channel}"')
    if page:
        a.append(f'data-page="{page}"')
    a.append(f'data-rya-theme="{theme}"')
    if haschrome:
        a.append('data-rya-haschrome="1"')
    if hub:
        a.append('data-rya-hub="1"')  # корень канала → акцент = цвет канала (site.css)
    return " ".join(a)


if __name__ == "__main__":
    print(f"ASSET_V={ASSET_V} MARK={MARK}")
    print("--- head_block() ---");  print(head_block())
    print("--- body_script() ---"); print(body_script())
    print("--- html_attrs(ytcr,/ytcr/01/) ---"); print(html_attrs("ytcr", "/ytcr/01/"))
