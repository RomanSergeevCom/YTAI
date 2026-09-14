#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mockup_layouts — типовые раскладки экранов для build_mockups.py (4K, 3840×2160).

Экран в каталоге плана (montage_plan.json → gfx_catalog[*].screens[*]) задаётся либо готовым
телом `html` (+ `theme`: dark | light | alpha), либо раскладкой и текстами:

    {"variant": "A", "title": "Плашка: Дарья Благо", "layout": "lower_third",
     "text": {"name": "Дарья Благо", "role": "Директор АНО «Эволюция»"}}

Раскладки: lower_third · title_plate · title · quote · cards · list · formula · domain.
Все цвета/шрифты — из словаря стиля S (build_mockups.style_tokens(): профиль канала
`style.mockup.*` → план `mockups.style` → дефолты первого проекта). Тексты — только из плана.

`recognize(body)` — обратная задача для конвертера из легаси: если тело экрана побайтно
воспроизводится раскладкой (плашка спикера, титр совета), возвращает {layout, text}.

    python3 mockup_layouts.py   # самопроверка: раскладка → recognize → та же раскладка
"""
import html as _html
import re

W, H = 3840, 2160

DEFAULT_STYLE = {
    'navy': '#0B1220', 'red': '#D0021B', 'red_on_dark': '#FF4D5E', 'light': '#F0EFEA',
    'vig_blue': '#2C3E8F', 'grad_a': '#3A4DB0', 'grad_b': '#E0506A',
    'text_dim': '#CDD3E0', 'text_soft': '#E6E9F2', 'text_mute': '#AEB6C8', 'text_ghost': '#8A92A8',
    'fonts': [['GB', 'Gilroy-Black'], ['GX', 'Gilroy-ExtraBold'], ['GBo', 'Gilroy-Bold'],
              ['GM', 'Gilroy-Medium'], ['GR', 'Gilroy-Regular']],
    'font_dir': '~/Library/Fonts',
    'logo_dark': 'logo_white.png', 'logo_light': 'logo_red.png',
    'draft_badge': 'DRAFT · мокап R.Y.A — финал в стиле клиента',
}


def rgb(hex_color):
    h = hex_color.lstrip('#')
    return ','.join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def e(x):
    return _html.escape(str(x if x is not None else ''), quote=False)


# ---------------- элементы ----------------
def plate(S, inner, pos):
    return (f'<div class="box" data-n="плашка" style="position:absolute;{pos};display:flex;align-items:stretch;'
            f'border-radius:22px;overflow:hidden;background:rgba({rgb(S["navy"])},.9);box-shadow:0 24px 70px rgba(0,0,0,.35)">'
            f'<div style="width:22px;background:{S["red"]}"></div>{inner}</div>')


def logo(S, theme, extra=''):
    name = S['logo_dark'] if theme == 'dark' else S['logo_light']
    return f'<img class="logo" src="{name}"{extra}>' if name else ''


def grad_dots(S, n=8):
    dots = ''.join(f'<i style="position:relative;display:block;width:34px;height:34px;border-radius:50%;'
                   f'background:linear-gradient(180deg,{S["grad_a"]},{S["grad_b"]})"></i>' for _ in range(n - 1))
    dots += (f'<i style="position:relative;display:block;width:56px;height:56px;border-radius:50%;'
             f'background:{S["red"]};box-shadow:0 0 40px rgba({rgb(S["red"])},.55)"></i>')
    return ('<div style="display:inline-flex;align-items:center;gap:52px;position:relative">'
            '<div style="position:absolute;left:0;right:0;top:50%;height:4px;background:rgba(255,255,255,.2);'
            'transform:translateY(-50%)"></div>' + dots + '</div>')


# ---------------- раскладки ----------------
def lower_third(S, t):
    """Плашка спикера внизу слева: name + role, логотип справа. Тема alpha."""
    inner = (f'<div style="padding:50px 90px 54px 70px">'
             f'<div class="t" style="font:112px GX;line-height:1;white-space:nowrap">{t["name"]}</div>'
             f'<div class="t" style="font:58px GM;color:{S["text_dim"]};margin-top:26px;white-space:nowrap">{t["role"]}</div></div>'
             f'<div style="display:flex;align-items:center;padding:0 80px;border-left:2px solid rgba(255,255,255,.12)">'
             f'<img src="{S["logo_dark"]}" style="height:84px"></div>')
    return plate(S, inner, 'left:192px;bottom:170px'), 'alpha'


def title_plate(S, t):
    """Титр-плашка вверху слева: over (напр. «Совет 01») + name + desc + extra. Тема alpha."""
    inner = (f'<div style="padding:46px 90px 52px 70px">'
             f'<div class="t" style="font:600 48px GBo;letter-spacing:.16em;text-transform:uppercase;color:{S["red_on_dark"]}">{t["over"]}</div>'
             f'<div class="t" style="font:150px GB;text-transform:uppercase;line-height:1;margin-top:18px">{t["name"]}</div>'
             f'<div class="t" style="font:58px GM;color:{S["text_soft"]};margin-top:24px;white-space:nowrap">{t["desc"]}</div>'
             f'<div class="t" style="font:46px GM;color:{S["text_mute"]};margin-top:14px;white-space:nowrap">{t.get("extra", "")}</div></div>')
    return plate(S, inner, 'left:192px;top:150px'), 'alpha'


def title(S, t):
    """Полноэкранная карточка: over + title (капсом, крупно) + sub + lead. theme: dark|light."""
    theme = t.get('theme', 'dark')
    sub = f'<div class="t" style="font:600 68px GBo;margin-top:60px;color:{S["text_soft"] if theme == "dark" else S["navy"]}">{e(t["sub"])}</div>' if t.get('sub') else ''
    lead = f'<div class="t" style="font:54px GM;line-height:1.35;margin-top:50px;color:{S["text_mute"]};max-width:3000px">{e(t["lead"])}</div>' if t.get('lead') else ''
    vig = '<div class="vig"></div>' if theme == 'dark' else ''
    size = int(t.get('size', 170))
    return (f'{vig}{logo(S, theme)}<div style="position:absolute;left:192px;top:{int(t.get("top", 420))}px;width:3300px">'
            f'<div class="over t">{e(t.get("over", ""))}</div>'
            f'<div class="t" style="font:{size}px GB;text-transform:uppercase;line-height:1;margin-top:36px">{t["title"]}</div>'
            f'{sub}{lead}</div>'), theme


def quote(S, t):
    """Цитата: over + большая цитата + подпись. theme: dark|light."""
    theme = t.get('theme', 'dark')
    vig = '<div class="vig"></div>' if theme == 'dark' else ''
    return (f'{vig}{logo(S, theme)}<div class="over t" style="position:absolute;left:192px;top:240px">{e(t.get("over", ""))}</div>'
            f'<div style="position:absolute;left:192px;top:520px;width:3300px">'
            f'<div class="t" style="font:{int(t.get("size", 140))}px GB;text-transform:uppercase;line-height:1.1">{t["quote"]}</div>'
            f'<div class="rule" style="margin:56px 0 0"></div>'
            f'<div class="t" style="font:54px GM;color:{S["text_mute"]};margin-top:36px">{e(t.get("by", ""))}</div></div>'), theme


def cards(S, t):
    """over + title + сетка карточек [{n?, h, d}] (до 6, по 3 в ряд). theme: dark|light."""
    theme = t.get('theme', 'dark')
    items = t.get('cards') or []
    cols = min(3, max(1, len(items)))
    cw = {1: 3456, 2: 1674, 3: 1080}[cols]
    gap = 108 if cols == 3 else 108
    out = []
    for i, c in enumerate(items):
        n = c.get('n') or f'{i + 1:02d}'
        if theme == 'dark':
            box = f'background:rgba(255,255,255,.045);border:2px solid rgba(255,255,255,.1)'
            dcol = S['text_dim']
        else:
            box = f'background:#fff;box-shadow:0 30px 80px rgba({rgb(S["navy"])},.1)'
            dcol = 'inherit'
        out.append(f'<div class="box" data-n="карточка {i + 1}" style="width:{cw}px;height:590px;padding:56px 64px;border-radius:28px;'
                   f'{box};display:flex;flex-direction:column;overflow:hidden">'
                   f'<div class="t" style="font:70px GB;color:{S["red_on_dark"] if theme == "dark" else S["red"]}">{e(n)}</div>'
                   f'<div class="t" style="font:{int(c.get("size", 110))}px GB;text-transform:uppercase;line-height:1;margin-top:24px">{e(c["h"])}</div>'
                   f'<div class="t" style="font:50px GM;line-height:1.3;color:{dcol};margin-top:30px">{e(c.get("d", ""))}</div></div>')
    vig = '<div class="vig"></div>' if theme == 'dark' else ''
    return (f'{vig}{logo(S, theme)}<div style="position:absolute;left:192px;top:220px"><div class="over t">{e(t.get("over", ""))}</div>'
            f'<div class="t" style="font:190px GB;text-transform:uppercase;line-height:1;margin-top:30px">{t["title"]}</div></div>'
            f'<div style="position:absolute;left:192px;top:720px;display:grid;grid-template-columns:repeat({cols},{cw}px);'
            f'column-gap:{gap}px;row-gap:70px">{"".join(out)}</div>'), theme


def list_screen(S, t):
    """over + title + маркированный список items + (необязательно) контактный бокс {h, lines[]}. theme: light|dark."""
    theme = t.get('theme', 'light')
    lis = ''.join(f'<div style="display:flex;align-items:baseline;gap:28px;margin-bottom:30px">'
                  f'<span style="width:18px;height:18px;border-radius:50%;background:{S["red"]};flex-shrink:0"></span>'
                  f'<span class="t" style="font:62px GM;line-height:1.25">{e(x)}</span></div>' for x in t.get('items') or [])
    box = ''
    if t.get('box'):
        b = t['box']
        lines = ''.join(f'<div class="t" style="font:52px GM;color:{S["text_dim"]};margin-top:24px;line-height:1.3">{e(x)}</div>' for x in b.get('lines') or [])
        box = (f'<div class="box" style="position:absolute;left:2448px;top:700px;width:1200px;padding:56px 60px;border-radius:26px;'
               f'background:{S["navy"]};color:#fff"><div class="t" style="font:600 46px GBo;letter-spacing:.12em;text-transform:uppercase;'
               f'color:{S["red_on_dark"]}">{e(b.get("h", ""))}</div>{lines}</div>')
    vig = '<div class="vig"></div>' if theme == 'dark' else ''
    return (f'{vig}{logo(S, theme)}<div style="position:absolute;left:192px;top:200px"><div class="over t">{e(t.get("over", ""))}</div>'
            f'<div class="t" style="font:170px GB;text-transform:uppercase;line-height:1;margin-top:26px">{t["title"]}</div></div>'
            f'<div style="position:absolute;left:192px;top:700px;width:2100px">{lis}</div>{box}'), theme


def formula(S, t):
    """Плашка-формула по центру внизу: over + title. Тема alpha."""
    return (f'<div class="box" data-n="формула" style="position:absolute;left:520px;width:2800px;bottom:170px;border-radius:26px;'
            f'background:rgba({rgb(S["navy"])},.88);padding:54px 90px 64px;text-align:center;box-shadow:0 24px 70px rgba(0,0,0,.35)">'
            f'<div class="t" style="font:600 52px GBo;letter-spacing:.16em;text-transform:uppercase;color:{S["red_on_dark"]}">{t.get("over", "")}</div>'
            f'<div class="t" style="font:124px GB;text-transform:uppercase;line-height:1.05;margin-top:26px;white-space:nowrap">{t["title"]}</div></div>'), 'alpha'


def domain(S, t):
    """Плашка домена/ссылки внизу справа: логотип + текст (tail выделяется красным). Тема alpha."""
    tail = t.get('tail', '')
    txt = e(t['text']) + (f'<span style="color:{S["red_on_dark"]}">{e(tail)}</span>' if tail else '')
    return (f'<div class="box" data-n="домен" style="position:absolute;right:192px;bottom:170px;display:flex;align-items:center;gap:44px;'
            f'border-radius:22px;background:rgba({rgb(S["navy"])},.9);padding:36px 60px 40px 50px;box-shadow:0 24px 70px rgba(0,0,0,.35)">'
            f'<img src="{S["logo_dark"]}" style="height:70px"><div style="width:3px;height:90px;background:rgba(255,255,255,.18)"></div>'
            f'<div class="t" style="font:92px GX;line-height:1;white-space:nowrap">{txt}</div></div>'), 'alpha'


LAYOUTS = {'lower_third': lower_third, 'title_plate': title_plate, 'title': title, 'quote': quote,
           'cards': cards, 'list': list_screen, 'formula': formula, 'domain': domain}


def render_layout(S, name, text):
    if name not in LAYOUTS:
        raise SystemExit(f'неизвестная раскладка «{name}» — есть: {", ".join(LAYOUTS)}')
    return LAYOUTS[name](S, text or {})


# ---------------- распознавание легаси-тел ----------------
_LT_RX = re.compile(r'<div class="t" style="font:112px GX;line-height:1;white-space:nowrap">(.*?)</div>'
                    r'<div class="t" style="font:58px GM;color:#[0-9A-Fa-f]{6};margin-top:26px;white-space:nowrap">(.*?)</div>', re.S)
_TP_RX = re.compile(r'text-transform:uppercase;color:#[0-9A-Fa-f]{6}">(.*?)</div>'
                    r'<div class="t" style="font:150px GB;text-transform:uppercase;line-height:1;margin-top:18px">(.*?)</div>'
                    r'<div class="t" style="font:58px GM;color:#[0-9A-Fa-f]{6};margin-top:24px;white-space:nowrap">(.*?)</div>'
                    r'<div class="t" style="font:46px GM;color:#[0-9A-Fa-f]{6};margin-top:14px;white-space:nowrap">(.*?)</div>', re.S)


def recognize(body, S=None):
    """Тело экрана → {layout, text}, если раскладка воспроизводит его побайтно; иначе None."""
    S = S or DEFAULT_STYLE
    m = _LT_RX.search(body)
    if m:
        t = {'name': m.group(1), 'role': m.group(2)}
        if lower_third(S, t)[0] == body:
            return {'layout': 'lower_third', 'text': t}
    m = _TP_RX.search(body)
    if m:
        t = {'over': m.group(1), 'name': m.group(2), 'desc': m.group(3), 'extra': m.group(4)}
        if title_plate(S, t)[0] == body:
            return {'layout': 'title_plate', 'text': t}
    return None


if __name__ == '__main__':
    S = DEFAULT_STYLE
    for name, t in (('lower_third', {'name': 'Имя Фамилия', 'role': 'Должность'}),
                    ('title_plate', {'over': 'Совет 01', 'name': 'Труд', 'desc': 'описание', 'extra': 'ещё'})):
        body, theme = render_layout(S, name, t)
        r = recognize(body, S)
        assert r and r['layout'] == name and r['text'] == t, name
        print(f'{name}: ok ({theme}, {len(body)} байт)')
    for name in ('title', 'quote', 'cards', 'list', 'formula', 'domain'):
        body, theme = render_layout(S, name, {'title': 'Заголовок', 'quote': 'Цитата', 'text': 'сайт.рус',
                                              'cards': [{'h': 'А', 'd': 'а'}, {'h': 'Б', 'd': 'б'}], 'items': ['раз', 'два']})
        print(f'{name}: ok ({theme}, {len(body)} байт)')
