#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Плиты глав и подглав на языке брендбука фонда «Бюро Добрых Дел» — предложение к выбору.

Зачем отдельный файл, а не блок J в make_infographics_v6.py: канон YTCH в
`YTs/YTCH/review_profile.json` ЗАМЕРЕН ПО КАТУ МОНТАЖЁРА (`style._canon_note`), то есть это
зафиксированная импровизация, а не язык фонда. Брендбук (23.09.2026) задаёт другой красный,
другой шрифт, логотип и геометрию. Подменять канон вслепую нельзя — Роман смотрит доску и
решает по картинке. Пока решения нет, рендер живёт сбоку и ничего в канале не трогает.

⚠️ `make_infographics_v6.py` НЕ импортируется и не правится: 23.09.2026 его держит соседняя
сессия (незакоммиченные правки, красный golden). Форма функций здесь намеренно повторяет
блок J (`_bdd_body`/`_bdd_css`/`BDD_NM` ≈ `_chov_body`/`_chov_css`/`CHOV_NM`), чтобы вклейка
потом была вставкой двух функций рядом с `_chov_css` и трёх ключей в словарь — без нового
блока и без нового `want()`.

⚠️ Вывод — в `mockups/bdd/`, а не в корень `mockups/`. Корень глобится чужими масками:
`screens_library.to_glob()` превращает блок E в `*_t.png` по корню (однажды это затянуло
158 чужих файлов), а `golden.py` объявляет выход шага `infographics_html` как `mockups/src/*.html`
и чистит glob перед прогоном. Подпапка невосприимчива к обоим, и откат — один `rm -rf`.

⚠️ Шрифт инлайнится base64, а не подключается по `file://`: заблокированный или ненайденный
шрифт подменяется МОЛЧА — картинка выходит правильной, но не тем начертанием. В системе есть
Montserrat Regular/Medium/SemiBold/Bold и НЕТ Black: запрос 900 у системного даёт подделку из 700.

    python3 stages/bdd_plates.py all
    python3 stages/bdd_plates.py all --board
    YTAI_RENDER_HTML_ONLY=1 python3 stages/bdd_plates.py ch     # без chrome, только HTML

Источник цифр — `YTs/YTCH/brand_profile.json` (схема brand-profile-v1). Хексы здесь не хардкодятся:
в профиле у каждого числа записана полоса брендбука, по которой его можно сверить с оригиналом.
"""
import argparse
import time
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from _bootstrap import P, W6, HERE  # noqa: E402
from render import render  # noqa: E402

YTAI = Path(__file__).resolve().parents[4]
BRAND_FILE = YTAI / 'YTs' / str(P.get('channel', 'YTCH')) / 'brand_profile.json'

OUT = Path(P.MOCK) / 'bdd'
SRC = OUT / 'src'

CANVAS_W, CANVAS_H = 3840, 2160
STAMP = time.strftime('%d.%m.%Y, %H:%M')


# ─────────────────────────────── профиль бренда ───────────────────────────────
def load_brand():
    if not BRAND_FILE.exists():
        raise SystemExit(f'нет профиля бренда: {BRAND_FILE}')
    return json.loads(BRAND_FILE.read_text('utf-8'))


BRAND = load_brand()


def B(dotted, default=None):
    """Значение из brand_profile.json по точечному пути; нет — падаем обратно в профиль канала.

    Падение назад важно: когда блок `style` переедет в review_profile.json, удаление
    brand_profile.json оставит модуль рабочим."""
    cur = BRAND
    for k in dotted.split('.'):
        if not isinstance(cur, dict) or k not in cur:
            return P.profile(dotted, default)
        cur = cur[k]
    return cur


def C(name):
    """Хекс цвета палитры по имени."""
    return BRAND['palette'][name]['hex']


RED = C('red')
CORAL = C('coral')
WHITE = C('white')
BLACK = C('black')
TEAL = C('teal')
OLIVE = C('olive')
AMBER = C('amber')
SLATE = C('slate')
CREAM = C('cream')
CHANNEL = C('channel')   # цвет канала YTCH — редакционный голос, не голос фонда

MARGIN = int(B('style.margin_px', 123))
SATUR = float(B('rules.photo_saturation', 0.55))
RADIUS = int(B('rules.shape_radius_px', 120))
SHAPE_A = float(B('rules.shape_alpha', 0.85))


# ─────────────────────────────── шрифты ───────────────────────────────
# Роман 23.09.2026: «Когда шрифты показывай этот который они используют или другой. Можно и
# другие использовать, важно, чтобы хорошо выглядело». Поэтому семейств два, и каждый макет
# подписан тем, которым набран. Montserrat — то, чем фонд пользуется сейчас; Onest — замена
# на пробу: кириллица у него на 10 % уже (замер: «ЖУМАГУЛ ПАНФИЛОВА» 1225 против 1362 на
# кегле 100), значит длинное имя влезает крупнее и не жмётся.
FONT_DIR = YTAI / BRAND['fonts']['dir']

FONT_SETS = {
    'montserrat': {
        'family': 'Montserrat BDD', 'dir': FONT_DIR, 'heavy': 900,
        'faces': {400: 'Montserrat-Regular.ttf', 700: 'Montserrat-Bold.ttf',
                  900: 'Montserrat-Black.ttf'},
        'label': 'Montserrat 900/400 — шрифт фонда',
    },
    'onest': {
        'family': 'Onest BDD', 'dir': FONT_DIR / 'alt', 'heavy': 800,
        'faces': {400: 'Onest-Regular.ttf', 700: 'Onest-Bold.ttf',
                  800: 'Onest-ExtraBold.ttf'},
        'label': 'Onest 800/400 — альтернатива, кириллица уже на 10 %',
    },
}
ACTIVE = 'montserrat'


def FS():
    return FONT_SETS[ACTIVE]


def use_font(key):
    global ACTIVE
    if key not in FONT_SETS:
        raise SystemExit(f'нет такого шрифта: {key}. Есть: {", ".join(FONT_SETS)}')
    ACTIVE = key


def face_path(weight):
    fs = FS()
    return fs['dir'] / fs['faces'][weight]


def HEAVY():
    return FS()['heavy']


def font_label():
    return FS()['label']


def check_fonts():
    """Падаем ДО запуска chrome, если начертания нет: иначе подмена пройдёт незаметно."""
    bad = []
    for key, fs in FONT_SETS.items():
        for w, fn in fs['faces'].items():
            p = fs['dir'] / fn
            if not p.exists():
                bad.append(f'{key} {w}: {p}')
    if bad:
        raise SystemExit('нет файлов начертаний, рендер остановлен:\n  ' + '\n  '.join(bad))


_FONT_CSS_CACHE = {}


def font_css():
    if ACTIVE in _FONT_CSS_CACHE:
        return _FONT_CSS_CACHE[ACTIVE]
    fs = FS()
    out = []
    for w in sorted(fs['faces']):
        b64 = base64.b64encode((fs['dir'] / fs['faces'][w]).read_bytes()).decode()
        out.append(f"@font-face{{font-family:'{fs['family']}';font-weight:{w};"
                   f"font-style:normal;src:url(data:font/ttf;base64,{b64}) "
                   f"format('truetype');}}")
    css = ''.join(out)
    _FONT_CSS_CACHE[ACTIVE] = css
    return css


_PIL_CACHE = {}


def measure(text, px, weight=None):
    """Ширина строки НАСТОЯЩИМ файлом шрифта. Прикидка «прописная = 0,66 кегля» врёт:
    именно она обрезала «ПРОИСХОЖДЕНИЕ РУБИНА» в блоке J."""
    from PIL import ImageFont
    w = HEAVY() if weight is None else weight
    key = (ACTIVE, w, px)
    if key not in _PIL_CACHE:
        _PIL_CACHE[key] = ImageFont.truetype(str(face_path(w)), px)
    return _PIL_CACHE[key].getlength(str(text))


def fit_fs(lines, col, cap, by='word', floor=110, ls=0.0, weight=None):
    """Кегль, при котором текст влезает в колонку `col` при потолке `cap`."""
    parts = []
    for s in lines:
        if not s:
            continue
        parts += [w for w in str(s).split(' ') if w] if by == 'word' else [str(s)]
    if not parts:
        return cap
    worst = 0.0
    for p in parts:
        w = measure(p.upper(), 100, weight) / 100.0          # ширина на кегль 1
        worst = max(worst, w + len(p) * ls)
    return max(floor, min(cap, int(col / worst))) if worst else cap


def wrap_lines(text, col, fs, weight=None):
    """Жадный перенос по ширине колонки — тем же файлом шрифта, каким меряет браузер."""
    words, lines, cur = [w for w in str(text).upper().split(' ') if w], [], ''
    for w in words:
        trial = f'{cur} {w}'.strip()
        if cur and measure(trial, 100, weight) / 100.0 * fs > col:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def fit_block(text, col, cap, max_h, lh=1.02, floor=110, weight=None):
    """Кегль, при котором текст влезает в колонку И в отведённую ВЫСОТУ.

    ⚠️ `fit_fs` гарантирует только, что влезет самое длинное СЛОВО: число строк она не
    ограничивает. На «КЕМ ХОТЕЛА СТАТЬ СВЕТА?» это дало три строки по 300 px и заголовок
    уехал за нижний край кадра. Здесь после подбора ширины текст переносится тем же шрифтом
    и кегль уменьшается, пока высота не уложится в бюджет."""
    fs = fit_fs([text], col, cap, weight=weight)
    while fs > floor:
        if len(wrap_lines(text, col, fs, weight)) * fs * lh <= max_h:
            return fs
        fs -= 4
    return floor


# ─────────────────────────────── данные фильма ───────────────────────────────
def esc(t):
    return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def chapters():
    """[(num:str, name:str, sec:int)] из карточки."""
    ch = P.get('chapters') or []
    names = P.get('ch_name') or {}
    return [(str(n), str(names.get(str(n), '')), int(s)) for s, n in ch]


def subs():
    """[(sec, ch_int, title)] из карточки."""
    return [(int(s), int(c), str(t)) for s, c, t in (P.get('sub') or [])]


def frame(sec):
    """кадр ката под секунду (hires снят 1 fps: hNNNN = секунда NNNN−1)."""
    if sec is None:
        return None
    f = W6 / 'hires' / f'h{int(sec) + 1:04d}.jpg'
    return f if f.exists() else None


def shot_div(f, satur=None):
    """Кадр-подложка. Насыщенность режется фильтром — ровно правило стр. 21 брендбука."""
    if not f:
        return f'<div class="shot" style="background:{SLATE}"></div>'
    s = SATUR if satur is None else satur
    return (f'<div class="shot" style="filter:saturate({s});'
            f'background-image:url(\'file://{f}\')"></div>')


def logo_img(width_px, on_busy=True):
    """Логотип. На неоднородном фоне — на белой подложке (правило стр. 34 брендбука):
    дом в логотипе обведён чёрным и на кадре тонет."""
    p = YTAI / BRAND['logo']['horizontal']
    if not p.exists():
        return ''
    b64 = base64.b64encode(p.read_bytes()).decode()
    img = f'<img src="data:image/png;base64,{b64}" style="width:{width_px}px;display:block">'
    if not on_busy:
        return img
    # ⚠️ inline-block обязателен: блочная подложка растягивается на всю ширину родителя
    # и превращается в белую плиту во весь экран с крошечным логотипом в углу
    pad = int(width_px * 0.09)
    return (f'<div style="display:inline-block;background:{WHITE};'
            f'border-radius:{int(RADIUS*0.45)}px;'
            f'padding:{pad}px {pad}px {int(pad*0.9)}px">{img}</div>')


# ─────────────────────────────── геометрия бренда ───────────────────────────────
def shape(x, y, w, h, color, rot=0, skew=0, alpha=None, radius=None, z=1):
    """Крупная скруглённая фигура фирменного цвета с полупрозрачным наложением (стр. 22).

    Брендбучные фигуры — не прямоугольники, а скруглённые четырёхугольники с неравными
    сторонами; поворот и скос дают их, оставаясь одним div-ом с управляемыми числами."""
    a = SHAPE_A if alpha is None else alpha
    r = RADIUS if radius is None else radius
    tr = f'rotate({rot}deg) skewX({skew}deg)' if (rot or skew) else 'none'
    return (f'<div style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;'
            f'background:{color};opacity:{a};border-radius:{r}px;transform:{tr};z-index:{z}"></div>')


def ring(size, stroke, color, extra=''):
    return (f'<div style="position:absolute;width:{size}px;height:{size}px;border-radius:50%;'
            f'border:{stroke}px solid {color};left:50%;top:50%;'
            f'transform:translate(-50%,-50%);{extra}"></div>')


# ─────────────────────────────── раскладки ───────────────────────────────
def base_css():
    fs = FS()
    return f"""
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{CANVAS_W}px;height:{CANVAS_H}px;overflow:hidden}}
body{{font-family:'{fs['family']}',Arial,sans-serif;position:relative;background:{CREAM}}}
.pl{{position:absolute;inset:0;overflow:hidden}}
.pl .shot{{position:absolute;inset:0;background-size:cover;background-position:center}}
.nm{{text-transform:uppercase;font-weight:{fs['heavy']};line-height:1.02;letter-spacing:.01em}}
.num{{font-weight:{fs['heavy']};letter-spacing:.24em}}
.body{{font-weight:400;line-height:1.3}}
.draft{{position:absolute;right:48px;bottom:36px;font-weight:400;font-size:26px;
        letter-spacing:.12em;z-index:99}}
"""


# потолок кегля и ширина колонки на каждый вариант — как CHOV_NM в блоке J
BDD_NM = {
    'e': (1180, 300),      # внутри круга
    'f': (2180, 300),      # правее фигур
    'g': (2600, 260),      # по полю кадра
}


def _bdd_css(variant):
    if variant == 'e':
        return f".draft{{color:rgba(255,255,255,.55)}}"
    return f".draft{{color:rgba(255,255,255,.6)}}"


def _bdd_body(variant, num, name, sub, shot, sec=None):
    """Тело плиты. Сигнатура повторяет _chov_body блока J — чтобы вклейка была механической."""
    col, cap = BDD_NM[variant]

    # ── E · ПЛИТА: разделитель самого брендбука (стр. 37) ──
    if variant == 'e':
        fs = fit_fs([name], col, cap)
        d0 = 1700                                    # внешнее тонкое кольцо
        d1, d2 = 1610, 1470                          # тёмно-красный диск, коралловый диск
        d3 = 1360                                    # внутреннее тонкое кольцо
        inner = (
            ring(d0, 4, 'rgba(255,255,255,.85)')
            + f'<div style="position:absolute;width:{d1}px;height:{d1}px;border-radius:50%;'
              f'background:#D2171D;left:50%;top:50%;transform:translate(-50%,-50%)"></div>'
            + f'<div style="position:absolute;width:{d2}px;height:{d2}px;border-radius:50%;'
              f'background:{CORAL};left:50%;top:50%;transform:translate(-50%,-50%)"></div>'
            + ring(d3, 4, 'rgba(255,255,255,.9)')
            + f'<div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);'
              f'width:{col}px;text-align:center;color:{WHITE}">'
              f'<div class="num" style="font-size:{int(fs*0.42)}px;margin-bottom:{int(fs*0.42)}px">'
              f'{esc(num)}</div>'
              f'<div class="nm" style="font-size:{fs}px">{esc(name)}</div>'
              f'</div>'
        )
        return f'<div class="pl" style="background:{RED}">{inner}</div>'

    # ── F · ФИГУРЫ НА КАДРЕ: грамматика банеров (стр. 22 + 36) ──
    if variant == 'f':
        # Блок прижат к НИЗУ и знает свой бюджет высоты: кружок номера + заголовок.
        # Считаем от бюджета, а не «сверху вниз и как ляжет» — иначе третья строка уезжает за край.
        bot = MARGIN + 40
        dia_k, gap_k = 1.25, 0.38
        budget = CANVAS_H - bot - 1020                        # верх блока не выше 1020 px
        fs = cap
        for _ in range(64):                                   # высота круга зависит от fs — сходимся
            h_txt = budget - int(fs * dia_k) - int(fs * gap_k)
            new = fit_block(name, col, cap, max(160, h_txt))
            if new == fs:
                break
            fs = new
        ul = max(12, int(fs * 0.075))                # подчёркивание ≥12 px: на 1920 не исчезает
        dia = int(fs * dia_k)
        x0 = MARGIN + 60
        parts = [shot_div(shot)]
        parts.append(shape(-420, 980, 2500, 1500, CORAL, rot=-7, skew=-5, z=2))
        parts.append(shape(-500, -260, 1850, 1180, RED, rot=6, skew=6, alpha=.88, z=2))
        parts.append(shape(2980, 1420, 1400, 1100, AMBER, rot=-9, alpha=.9, z=2))
        parts.append(
            f'<div style="position:absolute;left:{x0}px;bottom:{bot}px;width:{col}px;z-index:5">'
            f'<div style="width:{dia}px;height:{dia}px;border-radius:50%;'
            f'border:{max(5,int(fs*0.035))}px solid {WHITE};display:flex;align-items:center;'
            f'justify-content:center;margin-bottom:{int(fs*gap_k)}px">'
            f'<span class="num" style="font-size:{int(fs*0.44)}px;color:{WHITE};'
            f'letter-spacing:.04em">{esc(num)}</span></div>'
            f'<div class="nm" style="font-size:{fs}px;color:{WHITE};'
            f'text-decoration:underline;text-decoration-thickness:{ul}px;'
            f'text-underline-offset:{int(ul*1.6)}px">{esc(name)}</div>'
            f'</div>')
        parts.append(f'<div style="position:absolute;left:{MARGIN}px;top:{MARGIN}px;z-index:6">'
                     f'{logo_img(520)}</div>')
        return f'<div class="pl">{"".join(parts)}</div>'

    # ── G · КРУГ: цвет бренда без шума бренда ──
    dia = 560
    fs = fit_block(name, col, cap, CANVAS_H - (MARGIN + 60) - dia - 96 - 940)
    ul = max(12, int(fs * 0.075))
    parts = [shot_div(shot, satur=0.35),
             f'<div style="position:absolute;inset:0;background:rgba(20,18,18,.42)"></div>']
    parts.append(
        f'<div style="position:absolute;left:{MARGIN}px;bottom:{MARGIN + 60}px;'
        f'width:{col}px;z-index:5">'
        f'<div style="width:{dia}px;height:{dia}px;border-radius:50%;background:{RED};'
        f'display:flex;align-items:center;justify-content:center;margin-bottom:96px">'
        f'<span class="num" style="font-size:{int(dia*0.40)}px;color:{WHITE};'
        f'letter-spacing:.02em">{esc(num)}</span></div>'
        f'<div class="nm" style="font-size:{fs}px;color:{WHITE};'
        f'text-decoration:underline;text-decoration-color:{RED};'
        f'text-decoration-thickness:{ul}px;text-underline-offset:{int(ul*1.7)}px">'
        f'{esc(name)}</div></div>')
    return f'<div class="pl">{"".join(parts)}</div>'


# ⚠️ у варианта f колонка обязана быть УЖЕ внутреннего диаметра круга (1560 − 2×11 % = 1218),
# иначе текст вылезает из круга, в который его и просили положить (правило стр. 36)
SUB_NM = {'e': (2100, 190), 'f': (1180, 170)}
SUB_DIA_F = 1560


def _bdd_sub_body(variant, over, title, shot):
    """Плашка подглавы. `over` — «ГЛАВА 04 · ДЕТСКИЙ ДОМ», `title` — имя подглавы."""
    col, cap = SUB_NM[variant]
    # высота, а не только ширина: имена подглав бывают длиннее «Последней Пасхи»
    max_h = {'e': 520, 'f': 620}[variant]
    fs = fit_block(title, col, cap, max_h)
    ul = max(12, int(fs * 0.085))
    small = int(fs * float(B('rules.body_ratio', 0.5)))

    if variant == 'e':
        # фигура слева снизу, заголовок внутри, пояснение вдвое мельче под ним
        parts = [shot_div(shot)]
        parts.append(shape(-380, 1180, 3100, 1240, CORAL, rot=-4, skew=-4, alpha=.9, z=2))
        parts.append(shape(-420, 1460, 1500, 980, RED, rot=-4, skew=-4, alpha=.86, z=2))
        parts.append(
            f'<div style="position:absolute;left:{MARGIN + 60}px;bottom:{MARGIN + 60}px;'
            f'width:{col}px;z-index:5">'
            f'<div class="num" style="font-size:{int(small*0.78)}px;color:{WHITE};opacity:.95;'
            f'margin-bottom:{int(fs*0.26)}px">{esc(over)}</div>'
            f'<div class="nm" style="font-size:{fs}px;color:{WHITE};'
            f'text-decoration:underline;text-decoration-thickness:{ul}px;'
            f'text-underline-offset:{int(ul*1.6)}px">{esc(title)}</div>'
            f'</div>')
        parts.append(f'<div style="position:absolute;left:{MARGIN}px;top:{MARGIN}px;z-index:6">'
                     f'{logo_img(440)}</div>')
        return f'<div class="pl">{"".join(parts)}</div>'

    # F · текст в круге слева, пояснение справа сверху — буквально стр. 36
    dia = SUB_DIA_F
    parts = [shot_div(shot)]
    parts.append(shape(2560, -320, 1900, 1420, OLIVE, rot=-10, skew=-6, alpha=.88, z=2))
    parts.append(shape(2880, 900, 1500, 1600, TEAL, rot=7, alpha=.85, z=2))
    parts.append(shape(-560, 1180, 2100, 1420, RED, rot=-5, skew=-5, alpha=.9, z=2))
    parts.append(
        f'<div style="position:absolute;left:{MARGIN + 40}px;top:{(CANVAS_H - dia)//2}px;'
        f'width:{dia}px;height:{dia}px;border-radius:50%;border:6px solid rgba(255,255,255,.85);'
        f'display:flex;flex-direction:column;align-items:flex-start;justify-content:center;'
        f'padding:0 {int(dia*0.11)}px;z-index:5">'
        f'<div class="num" style="font-size:{int(small*0.62)}px;color:{WHITE};opacity:.95;'
        f'letter-spacing:.12em;margin-bottom:{int(fs*0.24)}px">{esc(over)}</div>'
        f'<div class="nm" style="font-size:{fs}px;color:{WHITE};'
        f'text-decoration:underline;text-decoration-thickness:{ul}px;'
        f'text-underline-offset:{int(ul*1.6)}px">{esc(title)}</div></div>')
    parts.append(
        f'<div style="position:absolute;right:{MARGIN + 40}px;top:{MARGIN + 40}px;'
        f'width:1150px;text-align:right;z-index:6">'
        f'{logo_img(440)}'
        f'<div class="body" style="font-size:{small}px;color:{WHITE};margin-top:{int(small*0.9)}px">'
        f'выпускница детского дома<br>одна с ребёнком</div></div>')
    return f'<div class="pl">{"".join(parts)}</div>'


# ══════════════════════════ ТИХИЙ ЯЗЫК (набор v2) ══════════════════════════
# Вердикт Романа 23.09.2026 по первой доске: «пока лучше всегда» — про КОНТРОЛЬ, нынешнее
# ПОЛОТНО; «но шрифт и цвета должны быть как в гайдлайне, с ярко красным слишком шумно».
#
# Отсюда язык набора: грамматика ПОЛОТНА (кадр уходит в затемнение, текст лежит прямо на кадре,
# плашки нет) + типографика и палитра брендбука. Ярко-красный #EC1F26 перестаёт быть ПОЛЕМ и
# становится ЧЕРТОЙ: на печатной полосе красное поле работает, на документальном кадре оно
# забивает лицо. Ведущий акцент — коралл #F37769, он вдвое тише и тоже основной цвет фонда.
SCRIM = 'rgba(8,8,10,.74)'
SHADOW = 'text-shadow:0 10px 50px rgba(0,0,0,.92)'
# Акценты глав. ⚠️ На ЗАТЕМНЁННОМ кадре работают не все цвета гаммы: олива и сизый на
# скриме вымываются в серый — глава 05 попала на сизый и надпись «ГЛАВА 05» прочиталась
# бледной. На тёмном крутим только контрастную тройку, олива и сизый живут в фишках на свету.
QUIET_ACCENTS = [CORAL, TEAL, OLIVE, AMBER, SLATE]        # полная гамма — для фишек
DARK_ACCENTS = [CORAL, AMBER, TEAL]                        # что читается на скриме


def accent_for(num):
    try:
        return DARK_ACCENTS[(int(num) - 1) % len(DARK_ACCENTS)]
    except Exception:
        return CORAL


def eyebrow(text, color, fs, mb):
    return (f'<div class="num" style="font-size:{fs}px;color:{color};'
            f'letter-spacing:.26em;margin-bottom:{mb}px;{SHADOW}">{esc(text)}</div>')


def rule(w=None, h=None, color=None, mt=0):
    w = RULE_W if w is None else w
    h = RULE_H if h is None else h
    return (f'<div style="width:{w}px;height:{h}px;background:{color or RED};'
            f'border-radius:{max(3,h//3)}px;margin-top:{mt}px"></div>')


# ⚠️ Черта канала на затемнённом кадре тонет: 450×14 ложилась на скамейку и читалась как
# артефакт сжатия, а не как акцент. Раз красный теперь ЕДИНСТВЕННОЕ место ярко-красного —
# он должен быть виден. Замер профиля (450×14) выведен от кегля заставок, здесь он поднят.
_r = B('style.rule', [450, 14])
RULE_W, RULE_H = max(560, int(_r[0])), max(18, int(_r[1]))


# Кегли заставки главы и плашки подглавы. Канон витрины — 380/210 px на кадре 3840; режим
# `titles` поднимает их: Роман 25.09.2026 «шрифт должен быть очень крупный». Переменные, а не
# параметры: по подписи функции гейт предложений и KB 1.1 читают поля вида
CH_CAP, CH_MAXH, SUB_CAP, SUB_MAXH = 380, 1080, 210, 520


NBSP = '\u00a0'
HANG_RX = re.compile(r'(?<![^\s«(])([А-ЯЁа-яёA-Za-z]{1,2}) ')


def hang(t):
    """«А ЧТО С ПАПОЙ?» → «А ЧТО С\u00a0ПАПОЙ?»: предлог, союз и частица до двух букв не висят в
    конце строки. На крупном кегле висячее «С» или «В» читается как ошибка набора (Роман 25.09.2026)."""
    prev = None
    while prev != t:
        prev, t = t, HANG_RX.sub(lambda m: m.group(1) + NBSP, t)
    return t


def q_ch(num, name, shot):
    """J · Заставка главы — ПОЛОТНО на языке фонда."""
    acc = accent_for(num)
    name = hang(str(name))
    fs = fit_block(name, 3300, CH_CAP, CH_MAXH)
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;inset:0;background:{SCRIM}"></div>'
            f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;text-align:center;padding:0 {MARGIN}px">'
            + eyebrow(f'ГЛАВА {num}', acc, 104, 46)
            + f'<div class="nm" style="font-size:{fs}px;max-width:3300px;color:{WHITE};{SHADOW}">'
              f'{esc(name)}</div>'
            + f'<div style="margin-top:78px">{rule()}</div>'
            + '</div></div>')


def q_ch_light(num, name, shot):
    """J · Заставка главы, светлая — кремовый мир брендбука, но без красного поля."""
    fs = fit_block(name, 3300, 360, 1040)
    ul = max(12, int(fs * 0.055))
    return (f'<div class="pl">{shot_div(shot, satur=0.22)}'
            f'<div style="position:absolute;inset:0;background:rgba(243,242,230,.94)"></div>'
            f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;text-align:center;padding:0 {MARGIN}px">'
            + eyebrow(f'ГЛАВА {num}', RED, 100, 44)
            + f'<div class="nm" style="font-size:{fs}px;max-width:3300px;color:{BLACK};'
              f'text-decoration:underline;text-decoration-color:{RED};'
              f'text-decoration-thickness:{ul}px;text-underline-offset:{int(ul*1.7)}px">'
              f'{esc(name)}</div>'
            + '</div></div>')


def q_sub(over, title, shot):
    """C · Плашка подглавы — текст прямо на кадре, плашки нет (канон канала)."""
    title = hang(str(title))
    fs = fit_block(title, 2600, SUB_CAP, SUB_MAXH)
    grad = GRAD_L
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;left:0;right:0;bottom:0;height:1150px;'
            f'background:{grad}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;bottom:{MARGIN + 120}px;'
            f'width:2600px">'
            + eyebrow(over, CORAL, 62, 26)
            + f'<div class="nm" style="font-size:{fs}px;color:{WHITE};{SHADOW}">{esc(title)}</div>'
            + f'<div style="margin-top:34px">{rule(420, 16)}</div>'
            + '</div></div>')


def q_lower(name, role, shot, logo=False):
    """L · Подпись человека. Канон канала: имя · роль · город, единообразно."""
    acc = RED if logo else CORAL
    grad = GRAD_L
    fs = fit_block(name, 2000, 150, 340)
    bar = (f'<div style="width:14px;align-self:stretch;background:{acc};'
           f'border-radius:7px;flex:none"></div>')
    lg = (f'<div style="margin-bottom:30px">{logo_img(420)}</div>') if logo else ''
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;left:0;right:0;bottom:0;height:900px;'
            f'background:{grad}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;bottom:300px;width:2300px">'
            f'{lg}'
            f'<div style="display:flex;gap:40px;align-items:stretch">{bar}'
            f'<div><div class="nm" style="font-size:{fs}px;color:{WHITE};{SHADOW}">'
            f'{esc(name)}</div>'
            f'<div class="body" style="font-size:{int(fs*0.44)}px;color:{WHITE};opacity:.90;'
            f'margin-top:20px;{SHADOW}">{esc(role)}</div></div></div></div></div>')


def q_claim(lead, key, shot):
    """N · Крупная фраза — реплика сильнее пересказа, поэтому во весь кадр."""
    text = f'{lead} {key}'.strip()
    fs = fit_block(text, 3200, 250, 1000)
    return (f'<div class="pl">{shot_div(shot, satur=0.30)}'
            f'<div style="position:absolute;inset:0;background:rgba(8,8,10,.82)"></div>'
            f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;text-align:center;padding:0 {MARGIN+180}px">'
            f'<div style="font-weight:{HEAVY()};font-size:{int(fs*1.5)}px;'
            f'color:{CORAL};line-height:.6;margin-bottom:{int(fs*0.30)}px">«</div>'
            f'<div class="nm" style="font-size:{fs}px;color:{WHITE};text-transform:none;'
            f'line-height:1.18;{SHADOW}">{esc(lead)} '
            f'<span style="color:{CORAL}">{esc(key)}</span></div>'
            f'<div style="margin-top:56px">{rule(420, 16)}</div>'
            f'</div></div>')


def q_list(title, items, shot):
    """D · Перечисление — фигуры брендбука входят фишками, а не полями."""
    fs = fit_block(title, 2900, 190, 420)
    chips = []
    for i, it in enumerate(items):
        col = QUIET_ACCENTS[i % len(QUIET_ACCENTS)]
        chips.append(
            f'<div style="background:{col};opacity:.94;border-radius:{int(RADIUS*0.6)}px;'
            f'padding:44px 66px;font-weight:{HEAVY()};font-size:108px;color:{WHITE};'
            f'text-transform:uppercase;letter-spacing:.01em">{esc(it)}</div>')
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;inset:0;background:{SCRIM}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;top:50%;'
            f'transform:translateY(-50%);width:3300px">'
            + eyebrow('ФОНД «БЮРО ДОБРЫХ ДЕЛ»', CORAL, 66, 30)
            + f'<div class="nm" style="font-size:{fs}px;color:{WHITE};{SHADOW}">{esc(title)}</div>'
            + f'<div style="margin-top:44px;margin-bottom:84px">{rule(420, 16)}</div>'
            + f'<div style="display:flex;gap:44px;flex-wrap:wrap">{"".join(chips)}</div>'
            + '</div></div>')


# ══════════════ ПЛАШКИ С ИМЕНЕМ — варианты ══════════════
# Канон канала: «имя · роль · город, единообразно» (rules_text профиля). Ниже шесть строёв
# одной и той же подписи — выбирать по тому, сколько воздуха в кадре и кто в кадре.
# ⚠️ Горизонтальный градиент в блоке фиксированной высоты даёт ЖЁСТКУЮ ВЕРХНЮЮ КРОМКУ:
# на светлом небе она читается как линия поперёк кадра (поймано на n_strip и n_split).
# Гасим вертикально — тогда подложка растворяется вверх и кромки нет вовсе.
GRAD_L = ('linear-gradient(to top,rgba(8,8,10,.90) 0%,rgba(8,8,10,.74) 34%,'
          'rgba(8,8,10,.40) 66%,rgba(8,8,10,0) 100%)')


def _lower_shell(shot, inner, bottom=300, grad_h=900):
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;left:0;right:0;bottom:0;height:{grad_h}px;'
            f'background:{GRAD_L}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;bottom:{bottom}px;width:2500px">'
            f'{inner}</div></div>')


def _nm(text, fs, color=None):
    return (f'<div class="nm" style="font-size:{fs}px;color:{color or WHITE};{SHADOW}">'
            f'{esc(text)}</div>')


def _role(text, fs, color=None, mt=20):
    return (f'<div class="body" style="font-size:{fs}px;color:{color or WHITE};opacity:.90;'
            f'margin-top:{mt}px;{SHADOW}">{esc(text)}</div>')


def lower_a(name, role, shot):
    """A · вертикальная черта слева — базовая."""
    fs = fit_block(name, 2000, 150, 340)
    return _lower_shell(shot,
                        f'<div style="display:flex;gap:40px;align-items:stretch">'
                        f'<div style="width:14px;background:{CORAL};border-radius:7px;'
                        f'flex:none"></div><div>{_nm(name, fs)}{_role(role, int(fs*0.44))}'
                        f'</div></div>')


def lower_b(name, role, shot):
    """B · черта ПОД именем — роль уходит под черту."""
    fs = fit_block(name, 2300, 150, 340)
    return _lower_shell(shot, _nm(name, fs)
                        + f'<div style="margin:26px 0 22px">{rule(420, 14, RED)}</div>'
                        + _role(role, int(fs * 0.44), mt=0))


def lower_c(name, role, shot):
    """C · на скруглённой фигуре брендбука — самая «фондовая»."""
    fs = fit_block(name, 1900, 132, 300)
    return _lower_shell(shot,
                        f'<div style="display:inline-block;background:{CORAL};opacity:.95;'
                        f'border-radius:{int(RADIUS*0.55)}px;padding:48px 76px 54px">'
                        f'{_nm(name, fs)}{_role(role, int(fs*0.46), mt=14)}</div>')


def lower_d(name, role, shot):
    """D · минимальная — ничего, кроме текста и тени."""
    fs = fit_block(name, 2300, 128, 300)
    return _lower_shell(shot, _nm(name, fs) + _role(role, int(fs * 0.46)), bottom=280, grad_h=720)


def lower_e(name, role, shot):
    """E · с логотипом фонда — для людей фонда, черта красная."""
    fs = fit_block(name, 2000, 150, 340)
    return _lower_shell(shot,
                        f'<div style="margin-bottom:30px">{logo_img(420)}</div>'
                        f'<div style="display:flex;gap:40px;align-items:stretch">'
                        f'<div style="width:14px;background:{RED};border-radius:7px;'
                        f'flex:none"></div><div>{_nm(name, fs)}{_role(role, int(fs*0.44))}'
                        f'</div></div>')


def lower_f(name, role, city, shot):
    """F · три строки: имя · роль · город — полный канон канала."""
    fs = fit_block(name, 2100, 140, 320)
    small = int(fs * 0.42)
    return _lower_shell(shot,
                        f'<div style="display:flex;gap:40px;align-items:stretch">'
                        f'<div style="width:14px;background:{AMBER};border-radius:7px;'
                        f'flex:none"></div><div>{_nm(name, fs)}'
                        f'{_role(role, small)}'
                        f'<div class="body" style="font-size:{int(small*0.88)}px;color:{AMBER};'
                        f'margin-top:10px;letter-spacing:.06em;{SHADOW}">{esc(city)}</div>'
                        f'</div></div>')


# ══════════════ ЭКРАНЫ ДЛЯ ВИЗУАЛИЗАЦИИ ВО ВРЕМЯ РАССКАЗА ══════════════
# Герой говорит долго и без монтажных склеек — это канон канала. Экран здесь не украшение,
# а способ дать глазу опору, пока идёт речь: цифра, срок, путь, сумма, место, термин.
def _center(shot, inner, scrim=None, satur=None):
    return (f'<div class="pl">{shot_div(shot, satur=satur if satur is not None else SATUR)}'
            f'<div style="position:absolute;inset:0;background:{scrim or SCRIM}"></div>'
            f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;text-align:center;'
            f'padding:0 {MARGIN+120}px">{inner}</div></div>')


def q_stat(value, caption, shot):
    """Крупная цифра — «только 1 % поступают в вуз»."""
    fs = big_line(value, CANVAS_W - 2 * (MARGIN + 120), 900)
    return _center(shot,
                   f'<div style="font-weight:{HEAVY()};font-size:{fs}px;line-height:.92;'
                   f'color:{CORAL};white-space:nowrap;{SHADOW}">{esc(value)}</div>'
                   f'<div style="margin:40px 0 46px">{rule(560, 18)}</div>'
                   + _nm(caption, fit_block(caption, 2900, 150, 420)),
                   scrim='rgba(8,8,10,.80)', satur=0.30)


def big_line(text, col, cap, floor=160):
    """Кегль для ОДНОЙ строки, которая не имеет права переноситься.

    ⚠️ Константа здесь и стоила дефекта: «150 000 ₽» на кегле 700 даёт 3648 px при поле
    3354 px, и знак рубля уезжал на вторую строку. Меряем настоящим файлом шрифта."""
    w = measure(str(text), 100) / 100.0
    return max(floor, min(cap, int(col / w))) if w else cap


def q_money(summa, what, shot):
    """Сумма — канон канала: суммы цифрами."""
    # тонкая шпация внутри числа и неразрывная перед ₽: знак валюты не отрывается от суммы
    summa = str(summa).replace(' ', ' ')
    col = CANVAS_W - 2 * (MARGIN + 120)
    fs = big_line(summa, col, 700)
    return _center(shot,
                   f'<div style="font-weight:{HEAVY()};font-size:{fs}px;line-height:.95;'
                   f'color:{WHITE};white-space:nowrap;{SHADOW}">{esc(summa)}</div>'
                   f'<div style="margin:38px 0 42px">{rule(460, 18, AMBER)}</div>'
                   + _role(what, 132, mt=0),
                   scrim='rgba(8,8,10,.82)', satur=0.28)


def q_question(text, shot):
    """Крупный вопрос — держит внимание на повороте рассказа."""
    fs = fit_block(text, 3100, 280, 1000)
    return _center(shot,
                   f'<div style="font-weight:{HEAVY()};font-size:{int(fs*1.4)}px;color:{CORAL};'
                   f'line-height:.8;margin-bottom:{int(fs*0.22)}px;{SHADOW}">?</div>'
                   + _nm(text, fs),
                   scrim='rgba(8,8,10,.80)', satur=0.30)


def q_timeline(points, shot):
    """Хронология — [(метка, текст)], слева направо по черте."""
    cells = []
    for i, (lab, txt) in enumerate(points):
        col = DARK_ACCENTS[i % len(DARK_ACCENTS)]
        cells.append(
            f'<div style="flex:1;text-align:left;padding-right:56px">'
            f'<div style="width:34px;height:34px;border-radius:50%;background:{col};'
            f'margin-bottom:34px"></div>'
            f'<div class="num" style="font-size:78px;color:{col};letter-spacing:.14em;'
            f'margin-bottom:18px;{SHADOW}">{esc(lab)}</div>'
            f'<div class="nm" style="font-size:96px;color:{WHITE};{SHADOW}">{esc(txt)}</div>'
            f'</div>')
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;inset:0;background:{SCRIM}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;top:50%;'
            f'transform:translateY(-50%)">'
            + eyebrow('ХРОНОЛОГИЯ', CORAL, 66, 34)
            + f'<div style="height:8px;background:rgba(255,255,255,.28);border-radius:4px;'
              f'margin:46px 0 54px"></div>'
            + f'<div style="display:flex">{"".join(cells)}</div></div></div>')


def q_steps(items, shot):
    """Путь — этапы фишками со стрелками."""
    cells = []
    for i, it in enumerate(items):
        col = QUIET_ACCENTS[i % len(QUIET_ACCENTS)]
        if i:
            cells.append(f'<div style="font-weight:{HEAVY()};font-size:130px;color:{CORAL};'
                         f'padding:0 34px;align-self:center;{SHADOW}">›</div>')
        cells.append(
            f'<div style="background:{col};opacity:.95;border-radius:{int(RADIUS*0.6)}px;'
            f'padding:52px 62px;font-weight:{HEAVY()};font-size:104px;color:{WHITE};'
            f'text-transform:uppercase;max-width:1000px">{esc(it)}</div>')
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;inset:0;background:{SCRIM}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;top:50%;'
            f'transform:translateY(-50%)">'
            + eyebrow('ПУТЬ', CORAL, 66, 34)
            + f'<div style="display:flex;align-items:stretch;flex-wrap:wrap;gap:0">'
              f'{"".join(cells)}</div></div></div>')


def q_compare(left, right, shot):
    """Два столбца — (заголовок, строки) слева и справа."""
    def col(side, color):
        head, rows = side
        rs = ''.join(f'<div class="body" style="font-size:104px;color:{WHITE};opacity:.92;'
                     f'margin-top:26px;{SHADOW}">{esc(r)}</div>' for r in rows)
        return (f'<div style="flex:1">'
                f'<div class="num" style="font-size:74px;color:{color};letter-spacing:.18em;'
                f'margin-bottom:24px;{SHADOW}">{esc(head)}</div>'
                f'<div style="height:10px;background:{color};border-radius:5px;'
                f'margin-bottom:38px"></div>{rs}</div>')
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;inset:0;background:{SCRIM}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;top:50%;'
            f'transform:translateY(-50%);display:flex;gap:170px">'
            f'{col(left, SLATE)}{col(right, CORAL)}</div></div>')


def q_term(term, definition, shot):
    """Плашка-определение — кремовая карточка брендбука поверх кадра."""
    fs = fit_block(term, 2600, 200, 440)
    return (f'<div class="pl">{shot_div(shot, satur=0.30)}'
            f'<div style="position:absolute;inset:0;background:rgba(8,8,10,.62)"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;bottom:{MARGIN+120}px;'
            f'max-width:2900px;background:{CREAM};border-radius:{int(RADIUS*0.7)}px;'
            f'padding:78px 92px 86px">'
            + eyebrow('ЧТО ЭТО', RED, 58, 24)
            + f'<div class="nm" style="font-size:{fs}px;color:{BLACK}">{esc(term)}</div>'
            + f'<div style="margin:30px 0 30px">{rule(360, 14, RED)}</div>'
            + f'<div class="body" style="font-size:{int(fs*0.44)}px;color:{BLACK};opacity:.86">'
              f'{esc(definition)}</div></div></div>')


def q_place(region, place, shot):
    """Локация — типографская, без карты: место называется, а не рисуется."""
    return _center(shot,
                   eyebrow(region, AMBER, 82, 34)
                   + _nm(place, fit_block(place, 3000, 300, 700))
                   + f'<div style="margin-top:46px">{rule(460, 18, AMBER)}</div>',
                   scrim='rgba(8,8,10,.78)', satur=0.30)


# ══════════ ПЛАШКИ С ИМЕНЕМ, НАБОР 3 — «инфа внизу / локация» ══════════
# Роман 23.09.2026: B, C и D не нравятся; F «этот нет», НО «добавлять так инфу внизу или
# локацию — оч круто». Значит идея верна, а исполнение F было тесным: город шёл третьей
# строкой вплотную под ролью и читался как приписка. Ниже город получает СВОЮ зону.
def name_loc(name, role, loc, shot):
    """N1 · локация отдельной зоной под волосяной линией — воздух вместо третьей строки."""
    fs = fit_block(name, 2100, 148, 330)
    small = int(fs * 0.44)
    return _lower_shell(shot,
        f'<div style="display:flex;gap:40px;align-items:stretch">'
        f'<div style="width:14px;background:{CORAL};border-radius:7px;flex:none"></div>'
        f'<div style="flex:1">{_nm(name, fs)}{_role(role, small)}'
        f'<div style="height:2px;background:rgba(255,255,255,.34);margin:32px 0 22px;'
        f'max-width:1500px"></div>'
        f'<div style="display:flex;align-items:center;gap:20px">'
        f'<div style="width:20px;height:20px;border-radius:50%;background:{AMBER};'
        f'flex:none"></div>'
        f'<div class="body" style="font-size:{int(small*0.94)}px;color:{AMBER};'
        f'letter-spacing:.10em;text-transform:uppercase;{SHADOW}">{esc(loc)}</div>'
        f'</div></div></div>', bottom=280, grad_h=1000)


def name_split(name, role, loc, extra, shot):
    """N2 · имя слева, локация и контекст — в правый нижний угол: кадр уравновешен."""
    fs = fit_block(name, 1900, 140, 320)
    small = int(fs * 0.44)
    grad = GRAD_L
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;left:0;right:0;bottom:0;height:980px;'
            f'background:{grad}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;bottom:300px;width:2000px">'
            f'<div style="display:flex;gap:40px;align-items:stretch">'
            f'<div style="width:14px;background:{CORAL};border-radius:7px;flex:none"></div>'
            f'<div>{_nm(name, fs)}{_role(role, small)}</div></div></div>'
            f'<div style="position:absolute;right:{MARGIN}px;bottom:306px;text-align:right;'
            f'max-width:1200px">'
            f'<div class="nm" style="font-size:{int(small*0.86)}px;color:{AMBER};'
            f'letter-spacing:.10em;{SHADOW}">{esc(loc)}</div>'
            f'<div style="height:2px;background:rgba(255,255,255,.3);margin:20px 0 0;'
            f'margin-left:auto;width:340px"></div>'
            f'<div class="body" style="font-size:{int(small*0.82)}px;color:{WHITE};'
            f'opacity:.95;margin-top:20px;{SHADOW}">{esc(extra)}</div>'
            f'</div></div>')


def name_strip(name, role, items, shot):
    """N3 · подвал-полоса во всю ширину: локация · дата · контекст одной лентой."""
    fs = fit_block(name, 2300, 140, 320)
    small = int(fs * 0.44)
    cells = []
    for i, (lab, val) in enumerate(items):
        cells.append(
            f'<div style="padding-right:110px">'
            f'<div class="body" style="font-size:44px;color:{WHITE};opacity:.62;'
            f'letter-spacing:.16em;text-transform:uppercase">{esc(lab)}</div>'
            f'<div class="body" style="font-size:62px;color:{WHITE};margin-top:10px">'
            f'{esc(val)}</div></div>')
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;left:0;right:0;bottom:0;height:1000px;'
            f'background:{GRAD_L}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;bottom:430px;width:2400px">'
            f'<div style="display:flex;gap:40px;align-items:stretch">'
            f'<div style="width:14px;background:{CORAL};border-radius:7px;flex:none"></div>'
            f'<div>{_nm(name, fs)}{_role(role, small)}</div></div></div>'
            f'<div style="position:absolute;left:0;right:0;bottom:0;height:250px;'
            f'background:rgba(8,8,10,.86);border-top:6px solid {RED};'
            f'display:flex;align-items:center;padding:0 {MARGIN}px">'
            f'{"".join(cells)}</div></div>')


# ══════════ ЭКРАНЫ ИЗ САМОГО ТЕКСТА ФИЛЬМА ══════════
# Собраны разбором транскрипта v5: суммы, сроки, даты и календарь выплат звучат в речи,
# но на экране их нет — а это ровно то, что зритель не удержит на слух.
# ⚠️ Правило скилла: подписывать ВСЕ данные и ставить источник — таймкод реплики.
def _src(tc):
    return (f'<div class="body" style="position:absolute;left:{MARGIN}px;bottom:{MARGIN}px;'
            f'font-size:42px;color:{WHITE};opacity:.52;letter-spacing:.08em">'
            f'со слов героини · {esc(tc)}</div>')


def d_debts(rows, tc, shot):
    """Долги — горизонтальные столбики, каждое число подписано."""
    mx = max(v for _, v in rows) or 1
    bars = []
    for i, (lab, val) in enumerate(rows):
        w = int(2300 * val / mx)
        col = [CORAL, AMBER][i % 2]
        bars.append(
            f'<div style="margin-bottom:64px">'
            f'<div class="body" style="font-size:72px;color:{WHITE};margin-bottom:22px;'
            f'{SHADOW}">{esc(lab)}</div>'
            f'<div style="display:flex;align-items:center;gap:36px">'
            f'<div style="width:{w}px;height:76px;background:{col};'
            f'border-radius:38px"></div>'
            f'<div class="nm" style="font-size:96px;color:{col};{SHADOW}">'
            f'{val:,}&nbsp;₽</div></div></div>'.replace(',', ' '))
    return (f'<div class="pl">{shot_div(shot, satur=0.28)}'
            f'<div style="position:absolute;inset:0;background:rgba(8,8,10,.84)"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;top:50%;'
            f'transform:translateY(-50%);width:3300px">'
            + eyebrow('ДОЛГИ ЗА КВАРТИРУ', CORAL, 66, 40)
            + ''.join(bars) + '</div>' + _src(tc) + '</div>')


def d_calendar(months, paid, tc, shot):
    """Календарь выплат — месяц платил / месяц нет. Самая честная форма для этой реплики."""
    cells = []
    for m in months:
        on = m in paid
        cells.append(
            f'<div style="flex:1;text-align:center">'
            f'<div style="height:190px;border-radius:{int(RADIUS*0.42)}px;'
            f'background:{OLIVE if on else "rgba(255,255,255,.10)"};'
            f'border:{"none" if on else f"4px solid rgba(255,255,255,.26)"};'
            f'display:flex;align-items:center;justify-content:center">'
            f'<span class="nm" style="font-size:76px;color:{WHITE};'
            f'opacity:{1 if on else .42}">{"✓" if on else "—"}</span></div>'
            f'<div class="body" style="font-size:52px;color:{WHITE};margin-top:22px;'
            f'opacity:{.95 if on else .55};text-transform:uppercase;letter-spacing:.06em">'
            f'{esc(m)}</div></div>')
    leg = (f'<div style="display:flex;gap:54px;margin-top:66px">'
           f'<div style="display:flex;align-items:center;gap:20px">'
           f'<div style="width:46px;height:46px;border-radius:12px;background:{OLIVE}"></div>'
           f'<span class="body" style="font-size:54px;color:{WHITE}">платил</span></div>'
           f'<div style="display:flex;align-items:center;gap:20px">'
           f'<div style="width:46px;height:46px;border-radius:12px;'
           f'border:4px solid rgba(255,255,255,.4)"></div>'
           f'<span class="body" style="font-size:54px;color:{WHITE};opacity:.8">'
           f'не платил</span></div></div>')
    return (f'<div class="pl">{shot_div(shot, satur=0.28)}'
            f'<div style="position:absolute;inset:0;background:rgba(8,8,10,.84)"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;top:50%;'
            f'transform:translateY(-50%)">'
            + eyebrow('АЛИМЕНТЫ ПО МЕСЯЦАМ', CORAL, 66, 44)
            + f'<div style="display:flex;gap:26px">{"".join(cells)}</div>{leg}</div>'
            + _src(tc) + '</div>')


def d_life(points, tc, shot):
    """Хронология жизни — колонки с переносом; линия и точки инлайн-SVG.

    ⚠️ Чистый SVG-текст здесь НЕ годится: он не переносится, и на пяти точках подписи
    «кома после пожара» и «забрали в интернат» наехали друг на друга. Колонка переносит
    сама, а SVG остаётся ровно тем, чем должен быть, — линией с точками."""
    n = len(points)
    cells = []
    for i, (age, what) in enumerate(points):
        col = DARK_ACCENTS[i % len(DARK_ACCENTS)]
        cells.append(
            f'<div style="flex:1;padding-right:56px">'
            f'<div style="width:34px;height:34px;border-radius:50%;background:{col};'
            f'margin-bottom:38px"></div>'
            f'<div class="nm" style="font-size:96px;color:{col};margin-bottom:20px;'
            f'{SHADOW}">{esc(age)}</div>'
            f'<div class="body" style="font-size:62px;color:{WHITE};opacity:.93;'
            f'line-height:1.24;{SHADOW}">{esc(what)}</div></div>')
    return (f'<div class="pl">{shot_div(shot, satur=0.30)}'
            f'<div style="position:absolute;inset:0;background:rgba(8,8,10,.82)"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;top:50%;'
            f'transform:translateY(-50%)">'
            + eyebrow('ЧТО БЫЛО КОГДА', CORAL, 66, 44)
            + f'<div style="height:8px;background:rgba(255,255,255,.30);'
              f'border-radius:4px;margin-bottom:-21px"></div>'
            + f'<div style="display:flex;align-items:flex-start">{"".join(cells)}</div>'
            + '</div>' + _src(tc) + '</div>')


def d_date(day, month_year, what, tc, shot):
    """Дата — когда одна дата несёт весь поворот рассказа."""
    return (f'<div class="pl">{shot_div(shot, satur=0.22)}'
            f'<div style="position:absolute;inset:0;background:rgba(8,8,10,.86)"></div>'
            f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
            f'align-items:center;justify-content:center;text-align:center;'
            f'padding:0 {MARGIN+160}px">'
            f'<div class="nm" style="font-size:'
            f'{big_line(day, CANVAS_W - 2 * (MARGIN + 160), 620)}px;color:{WHITE};'
            f'line-height:.92;white-space:nowrap;{SHADOW}">{esc(day)}</div>'
            f'<div class="num" style="font-size:150px;color:{CORAL};margin-top:24px;'
            f'{SHADOW}">{esc(month_year)}</div>'
            f'<div style="margin:56px 0 52px">{rule(560, 18)}</div>'
            f'<div class="body" style="font-size:112px;color:{WHITE};opacity:.94;'
            f'max-width:2900px;{SHADOW}">{esc(what)}</div>'
            f'</div>{_src(tc)}</div>')


# ══════════ УТОЧНЕНИЯ — голос редакции, а не голос героя ══════════
# Роман 23.09.2026: «формат комментариев добавить, добавлять если что-то нужно прояснить
# на видео». Это отдельный регистр: герой говорит от себя, а уточнение говорит канал.
# Поэтому оно набрано ЦВЕТОМ КАНАЛА (#FB7185), а не фирменным цветом фонда — зритель по
# цвету видит, кто сейчас говорит. Правило скилла для lower-third соблюдено: тёмная плашка
# снизу, скругление, слева цветной корешок.
def c_note(label, text, source, shot):
    """Плашка-уточнение внизу — короткая ремарка поверх идущей речи."""
    fs = fit_block(text, 2500, 92, 300, lh=1.26, weight=400)
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;left:{MARGIN}px;bottom:{MARGIN + 90}px;'
            f'max-width:3100px;background:rgba(10,10,12,.88);'
            f'border-radius:{int(RADIUS*0.30)}px;display:flex;overflow:hidden">'
            f'<div style="width:20px;background:{CHANNEL};flex:none"></div>'
            f'<div style="padding:54px 72px 58px">'
            f'<div class="num" style="font-size:52px;color:{CHANNEL};letter-spacing:.20em;'
            f'margin-bottom:26px">{esc(label)}</div>'
            f'<div class="body" style="font-size:{fs}px;color:{WHITE};line-height:1.26">'
            f'{esc(text)}</div>'
            f'<div class="body" style="font-size:46px;color:{WHITE};opacity:.56;'
            f'margin-top:26px">{esc(source)}</div>'
            f'</div></div></div>')


def c_full(label, text, source, shot):
    """Полноэкранное уточнение — для правовой или фактической оговорки, которую нельзя
    проскочить: цифра не подтверждена, формулировка требует рамки."""
    fs = fit_block(text, 2900, 150, 900, lh=1.22, weight=400)
    return (f'<div class="pl">{shot_div(shot, satur=0.24)}'
            f'<div style="position:absolute;inset:0;background:rgba(8,8,10,.88)"></div>'
            f'<div style="position:absolute;left:{MARGIN+120}px;right:{MARGIN+120}px;top:50%;'
            f'transform:translateY(-50%)">'
            f'<div style="display:flex;align-items:center;gap:32px;margin-bottom:54px">'
            f'<div style="width:88px;height:88px;border-radius:50%;background:{CHANNEL};'
            f'display:flex;align-items:center;justify-content:center">'
            f'<span class="nm" style="font-size:58px;color:{WHITE}">i</span></div>'
            f'<div class="num" style="font-size:64px;color:{CHANNEL};letter-spacing:.20em">'
            f'{esc(label)}</div></div>'
            f'<div class="body" style="font-size:{fs}px;color:{WHITE};line-height:1.22;'
            f'{SHADOW}">{esc(text)}</div>'
            f'<div style="margin:54px 0 30px">{rule(460, 16, CHANNEL)}</div>'
            f'<div class="body" style="font-size:58px;color:{WHITE};opacity:.62">'
            f'{esc(source)}</div></div></div>')


# ─────────────────────────────── сборка ───────────────────────────────
def page(name, body, css='', draft=True):
    draft_txt = str(B('style.draft_badge', 'DRAFT'))
    html = ('<!doctype html><meta charset="utf-8"><style>'
            + font_css() + base_css() + css + '</style>' + body
            + (f'<div class="draft">{esc(draft_txt.upper())}</div>' if draft else ''))
    SRC.mkdir(parents=True, exist_ok=True)
    p = SRC / f'{name}.html'
    p.parent.mkdir(parents=True, exist_ok=True)        # имя может нести подпапку (plan/NN_kind)
    p.write_text(html, encoding='utf-8')
    if os.environ.get('YTAI_RENDER_HTML_ONLY') == '1':
        print(f'  ✓ {name}.html  (без chrome)', flush=True)
        return None
    png = OUT / f'{name}.png'
    png.parent.mkdir(parents=True, exist_ok=True)      # имя может нести подпапку (plan/NN_kind)
    # непрозрачно: compare_page.embed() кладёт альфу на почти-чёрный (12,12,14),
    # и у кремовой плиты появилась бы чёрная кайма
    render(p, png, size=f'{CANVAS_W}x{CANVAS_H}', alpha=False)
    verify_png(png)
    print(f'  ✓ {name}.png', flush=True)
    return png


def verify_png(png):
    """render.py при таймауте может положить частичный скриншот — проверяем размер, а не глаза."""
    from PIL import Image
    with Image.open(png) as im:
        if im.size != (CANVAS_W, CANVAS_H):
            raise SystemExit(f'{png.name}: {im.size[0]}×{im.size[1]}, '
                             f'ожидалось {CANVAS_W}×{CANVAS_H} — рендер оборвался')


CH_VARIANTS = [('e', 'ПЛИТА'), ('f', 'ФИГУРЫ НА КАДРЕ'), ('g', 'КРУГ')]
SUB_VARIANTS = [('e', 'ПЛАШКА-ФИГУРА'), ('f', 'КРУГ + ТЕКСТ СПРАВА СВЕРХУ')]


def pick_chapter(idx):
    ch = chapters()
    if not ch:
        raise SystemExit('в карточке нет chapters')
    i = max(0, min(idx, len(ch) - 1))
    return ch[i]


def pick_sub(idx):
    sb = subs()
    if not sb:
        return None
    i = max(0, min(idx, len(sb) - 1))
    return sb[i]


# у пяти видов имя в витрине и имя функции рендера не совпадают — ровно тот же список,
# что держит сборщик KB 1.1 (`scripts/site/gen_kb_screens.py`). Третьей копии заводить нельзя
PLAN_FN = {'q_lower_a': 'lower_a', 'q_lower_e': 'lower_e',
           'n_loc': 'name_loc', 'n_split': 'name_split', 'n_strip': 'name_strip'}


def render_plan(a):
    """Предложения экранов (`work/{cut}/screens_proposal.json`) → по плите на каждое.

    Зачем отдельный режим, а не демо-список: витрина `quiet` показывает, КАК выглядит вид,
    на одном и том же кадре и с придуманным текстом. Чтобы решать, нужен ли экран ЗДЕСЬ,
    надо видеть его текст на СВОЁМ кадре этой секунды — иначе выбираешь шрифт, а не фильм.

    Порядок полей берётся из подписи функции рендера, а не из порядка ключей в JSON:
    словарь в файле человек пишет как удобно, а `q_sub(over, title, shot)` ждёт своё.
    Списки из JSON (`rows`, `points`, `items`, `months`) идут как есть — рендер их только
    обходит; `paid` проверяется через `in`, и списку это безразлично."""
    import inspect                                              # noqa: PLC0415
    src = Path(a.plan).expanduser() if a.plan else (W6 / 'screens_proposal.json')
    if not src.exists():
        print(f'!! нет {src} — предложения собирает stages/screens_proposal.py', file=sys.stderr)
        return 1
    items = json.loads(src.read_text(encoding='utf-8')).get('items') or []
    if a.only:
        want = {int(x) for x in str(a.only).split(',')}
        items = [i for i in items if int(i.get('n', 0)) in want]
    outdir = OUT / 'plan'
    print(f'предложений {len(items)} → {outdir}\n')
    made, bad = [], []
    for it in items:
        n, kind = int(it.get('n', 0)), str(it.get('kind', ''))
        fn = globals().get(PLAN_FN.get(kind, kind))
        if not callable(fn):
            bad.append(f'#{n}: вида «{kind}» в рендере нет')
            continue
        params = [p for p in inspect.signature(fn).parameters if p != 'shot']
        fields = it.get('fields') or {}
        miss = [p for p in params if p not in fields]
        if miss:
            bad.append(f'#{n} {kind}: нет полей {miss}')
            continue
        sec = int(float(it.get('sec', 0)))
        shot = frame(sec)
        if not shot:
            bad.append(f'#{n} {kind}: нет кадра ката на {sec} с — плита легла бы на пустой фон')
            continue
        name = f'plan/{n:02d}_{kind}'
        page(name, fn(*[fields[p] for p in params], shot))
        made.append((n, kind, it.get('tc', ''), OUT / f'{name}.png'))
    for b in bad:
        print('  ✗ ' + b, file=sys.stderr)
    print(f'\nотрисовано {len(made)} из {len(items)}' + (f' · не вышло {len(bad)}' if bad else ''))
    return 2 if bad else 0


FILM_VARIANTS = [
    ('a', 'ПОЛОТНО', 'кадр в затемнение, название по центру во всю ширину — как заставки глав'),
    ('b', 'СТОЛБИК', 'название в три строки у левого поля во всю высоту — как набрано в самом кате'),
    ('c', 'ПО НИЗУ', 'кадр почти открыт, название во всю ширину по нижней трети'),
]


def film_title(variant, title, shot):
    """Название фильма после хука (Роман 25.09.2026: «сначала хук, потом название фильма»).

    Не вид витрины и не входит в `plates`: название фильма ставится один раз, его не
    предлагают по местам. Кегль подбирается под кадр, а не константой — «очень крупный»."""
    title = hang(str(title))
    words = [w for w in title.split(' ') if w]
    if variant == 'a':
        fs = fit_block(title, 3400, 760, 1500)
        return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
                f'<div style="position:absolute;inset:0;background:{SCRIM}"></div>'
                f'<div style="position:absolute;inset:0;display:flex;flex-direction:column;'
                f'align-items:center;justify-content:center;text-align:center;padding:0 {MARGIN}px">'
                f'<div class="nm" style="font-size:{fs}px;line-height:.98;max-width:3400px;'
                f'color:{WHITE};{SHADOW}">{esc(title)}</div>'
                f'<div style="margin-top:90px">{rule(700, 22)}</div></div></div>')
    if variant == 'b':
        lines = [words[0], ' '.join(words[1:-1]), words[-1]] if len(words) >= 3 else words
        lines = [x for x in lines if x]
        fs = min(fit_fs(lines, 2300, 900), int(1880 / (len(lines) * 0.96)))
        body = ''.join(f'<div style="color:{CORAL if i else WHITE}">{esc(x)}</div>'
                       for i, x in enumerate(lines))
        return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
                f'<div style="position:absolute;inset:0;background:{GRAD_L}"></div>'
                f'<div class="nm" style="position:absolute;left:{MARGIN}px;top:50%;'
                f'transform:translateY(-50%);font-size:{fs}px;line-height:.96;{SHADOW}">{body}</div>'
                f'</div>')
    fs = fit_block(title, 3500, 620, 720)
    return (f'<div class="pl">{shot_div(shot, satur=SATUR)}'
            f'<div style="position:absolute;left:0;right:0;bottom:0;height:1250px;'
            f'background:{GRAD_L}"></div>'
            f'<div style="position:absolute;left:{MARGIN}px;right:{MARGIN}px;bottom:{MARGIN + 60}px">'
            f'<div class="nm" style="font-size:{fs}px;line-height:.98;color:{WHITE};{SHADOW}">'
            f'{esc(title)}</div><div style="margin-top:46px">{rule(560, 20)}</div></div></div>')


def lit_frame(sec, last, floor=38):
    """первый кадр не темнее floor (яркость 0–255) от sec до last: из затемнения, в которое
    уходит начало фильма и склейки, заставка вышла бы чёрным прямоугольником без кадра."""
    from PIL import Image, ImageStat                             # noqa: PLC0415
    for s_ in range(int(sec), max(int(sec), int(last)) + 1):
        f = frame(s_)
        if f and ImageStat.Stat(Image.open(f).convert('L').resize((64, 36))).mean[0] >= floor:
            return f
    return None


def render_titles(a):
    """Все заставки глав и плашки подглав фильма — крупно, каждая на СВОЁМ кадре, + название.

    ⚠️ Кадр берётся не на секунде начала главы, а через несколько секунд: в начале главы в
    кате стоит его СОБСТВЕННАЯ заставка, и новая легла бы поверх старой — два названия разом.
    Для глав, которых в кате нет, сдвиг тот же: так все примеры сравнимы между собой."""
    global CH_CAP, CH_MAXH, SUB_CAP, SUB_MAXH
    CH_CAP, CH_MAXH, SUB_CAP, SUB_MAXH = 640, 1500, 340, 760
    chap = [(int(t), str(n)) for t, n in P.CHAPTERS]
    names = P.get('ch_name', {}) or {}
    dur = float(P.duration_sec())
    made, miss = [], []
    for i, (t0, no) in enumerate(chap):
        t1 = chap[i + 1][0] if i + 1 < len(chap) else dur
        shot = lit_frame(t0 + 6, int(t1) - 1) or frame(t0)
        if not shot:
            miss.append(f'глава {no}: нет кадра')
            continue
        page(f'titles/title_ch_{no}', q_ch(no, str(names.get(no, '')), shot))
        made.append(f'title_ch_{no}')
    on_cut = {j for j in range(1, len(P.get('sub') or []) + 1)} - {int(x) for x in (P.get('sub_no_screen') or [])}
    for j, (sec, ch, label) in enumerate(P.get('sub') or [], 1):
        # у подглавы, чья плашка в кате УЖЕ стоит, её собственный титр ещё на экране — берём кадр
        # после него, иначе пример выйдет с двумя подписями (YTCH12, подпись куратора 11:16)
        shot = lit_frame(int(sec) + (7 if j in on_cut else 1), int(sec) + 20)
        if not shot:
            miss.append(f'подглава {j:02d}: нет кадра')
            continue
        over = f'ГЛАВА {int(ch):02d} · {names.get(f"{int(ch):02d}", "")}'.rstrip(' ·')
        page(f'titles/title_sub_{j:02d}', q_sub(over, str(label), shot))
        made.append(f'title_sub_{j:02d}')
    title = str(a.film or P.get('film_title') or '').strip().upper()
    if title:
        shot = frame(int(a.film_sec))
        for v, _nm, _why in FILM_VARIANTS:
            page(f'titles/title_film_{v}', film_title(v, title, shot))
            made.append(f'title_film_{v}')
        # подписи вариантов — рядом с картинками: вкладка дока читает их отсюда, а не держит копию
        (OUT / 'titles' / 'film_variants.json').write_text(json.dumps(
            {'title': title, 'variants': [{'v': v, 'name': nm, 'why': why} for v, nm, why in FILM_VARIANTS]},
            ensure_ascii=False, indent=1), encoding='utf-8')
    else:
        miss.append('название фильма: нет ни --film, ни film_title в карточке')
    for m in miss:
        print('  ✗ ' + m, file=sys.stderr)
    print(f'\nотрисовано {len(made)} · глав {len(chap)} · подглав {len(P.get("sub") or [])}'
          + (f' · не вышло {len(miss)}' if miss else ''))
    return 2 if miss else 0


def main():
    ap = argparse.ArgumentParser(description='плиты глав и подглав на языке брендбука БДД')
    ap.add_argument('what', nargs='?', default='quiet',
                    choices=['ch', 'sub', 'all', 'board', 'quiet', 'plan', 'titles'])
    ap.add_argument('--film', default='', help='название фильма для titles (иначе card.film_title)')
    ap.add_argument('--film-sec', type=int, default=8, help='секунда кадра под название фильма')
    ap.add_argument('--plan', default='', help='файл предложений (по умолчанию work/{cut}/screens_proposal.json)')
    ap.add_argument('--only', default='', help='отрисовать только эти номера предложений: 7,12')
    ap.add_argument('--frame', type=int, default=790, help='секунда кадра-подложки (без титров)')
    ap.add_argument('--ch', type=int, default=5, help='номер главы для демо (1-based)')
    ap.add_argument('--sub', type=int, default=1, help='номер подглавы для демо (1-based)')
    ap.add_argument('--board', action='store_true', help='собрать витрину сравнения')
    ap.add_argument('--width', type=int, default=1920, help='ширина картинок в витрине')
    ap.add_argument('--fonts', action='store_true', help='продублировать 3 экрана вторым шрифтом')
    ap.add_argument('--font', default='montserrat', help='montserrat | onest')
    a = ap.parse_args()

    check_fonts()
    use_font(a.font)
    OUT.mkdir(parents=True, exist_ok=True)

    if a.what == 'plan':
        return render_plan(a)
    if a.what == 'titles':
        return render_titles(a)

    num, name, _sec = pick_chapter(a.ch - 1)
    sb = pick_sub(a.sub - 1)
    shot = frame(a.frame)

    # ⚠️ печатаем всё разрешённое: YTAI_MOCKUPS_DIR в старой сессии молча уводит вывод,
    # а _find_card() идёт вверх от cwd и может подцепить чужой фильм
    print(f'проект   {P.get("code")} · кат {P.CUT_VERSION} · канал {P.get("channel")}')
    print(f'вывод    {OUT}')
    print(f'бренд    {BRAND_FILE.name}  красный {RED}  коралл {CORAL}')
    print(f'шрифт    {font_label()}')
    print(f'глава    {num} · {name}')
    print(f'подглава {sb[2] if sb else "—"}')
    print(f'кадр     {shot if shot else "НЕТ — плиты лягут на сизый фон"}')
    print()

    made = []
    if a.what == 'quiet':
        ch_of = f'{sb[1]:02d}' if sb else '01'
        ch_map = dict((n, nm) for n, nm, _ in chapters())
        over = f'ГЛАВА {ch_of} · {ch_map.get(ch_of, "")}'.rstrip(' ·')
        claims = P.get('claims') or []
        lead, key = (claims[0][1], claims[0][2]) if claims else ('', '')
        subj = str(P.get('film_subject') or '')
        GUEST, ROLE = 'СВЕТЛАНА', subj or 'выпускница детского дома'
        # ⚠️ ЖИМАГУЛ, через «И»: так на сайте фонда (burodd.ru/team/zhimagul-panfilova) и на
        # подписи 11:16. «ЖУМАГУЛ» — опечатка ката на 19:33; витрина её повторяла до 25.09.2026
        FUND, FROLE = 'ЖИМАГУЛ ПАНФИЛОВА', 'куратор по семьям · фонд «Бюро Добрых Дел»'
        LOC = 'Нижегородская область'
        chn = [(n, nm) for n, nm, _ in chapters()]
        plates = [
            ('q_ch',         q_ch(num, name, shot)),
            ('q_sub',        q_sub(over, sb[2] if sb else '', shot)),
            ('q_claim',      q_claim(lead, key, shot)),
            # ── плашки с именем: базовая, фондовая и три с инфой внизу ──
            ('q_lower_a',    lower_a(GUEST, ROLE, shot)),
            ('q_lower_e',    lower_e(FUND, FROLE, shot)),
            ('n_loc',        name_loc(GUEST, ROLE, LOC, shot)),
            ('n_split',      name_split(GUEST, ROLE, LOC, '13 лет в детском доме', shot)),
            ('n_strip',      name_strip(GUEST, ROLE,
                                        [('Место', LOC), ('В детском доме', '13 лет'),
                                         ('Сейчас', 'одна с ребёнком')], shot)),
            # ── из самого текста фильма ──
            ('d_debts',      d_debts([('За свет', 13000),
                                      ('Вода и капремонт', 27000)], '27:44', shot)),
            ('d_calendar',   d_calendar(['ноя', 'дек', 'янв', 'фев', 'мар', 'апр', 'май',
                                         'июн', 'июл', 'авг'],
                                        {'дек', 'янв', 'фев', 'мар', 'апр', 'май'},
                                        '44:44', shot)),
            ('d_life',       d_life([('4 года', 'кома после пожара'),
                                     ('9 лет', 'забрали в интернат'),
                                     ('13 лет', 'прожила в детском доме'),
                                     ('20 лет', 'уехала к нему'),
                                     ('8 лет', 'прожила вместе')], '15:17', shot)),
            ('d_date',       d_date('5 марта', '2024 года',
                                    'в её день рождения умерла мама', '35:53', shot)),
            # ── прочие виды ──
            ('q_stat',       q_stat('1 %', 'выпускников детских домов поступают в вуз', shot)),
            ('q_money',      q_money('150 000 ₽', 'мотоцикл брату', shot)),
            ('q_question',   q_question(name, shot)),
            ('q_steps',      q_steps(['Детский дом', 'Училище', 'Иваново',
                                      'Свой дом'], shot)),
            ('q_term',       q_term('Сопровождаемое жизнеустройство',
                                    'фонд ведёт выпускника после детского дома: жильё, '
                                    'профессия, работа и человек рядом', shot)),
            ('q_place',      q_place('Нижегородская область', 'Село', shot)),
            ('c_note',       c_note('УТОЧНЕНИЕ',
                                     'Со слов героини долг за свет ≈13 000 ₽, за воду и '
                                     'капремонт ≈27 000 ₽. Входит ли первая сумма во вторую, '
                                     'из разговора не следует.',
                                     'реплика 27:44 · уточняется у фонда', shot)),
            ('c_full',       c_full('УТОЧНЕНИЕ РЕДАКЦИИ',
                                    'Суммы, сроки и статусы названы героиней по памяти. '
                                    'Перед выпуском их подтверждает юрист фонда: '
                                    'непроверенные цифры в титры не выносим.',
                                    'правило канала · rules_text профиля', shot)),
            ('q_list',       q_list('Наши задачи',
                                    ['Навыки', 'Профессию', 'Рабочее место'], shot)),
        ]
        plates = [(n, b) for n, b in plates if b is not None]
        for nm_, body in plates:
            page(nm_, body)
            made.append((nm_, nm_, OUT / f'{nm_}.png'))
        # те же три экрана вторым шрифтом — сравнить набор
        if a.fonts:
            keep = ACTIVE
            for fkey in FONT_SETS:
                if fkey == keep:
                    continue
                use_font(fkey)
                for nm_, fn in (('q_ch', lambda: q_ch(num, name, shot)),
                                ('n_loc', lambda: name_loc(GUEST, ROLE, LOC, shot)),
                                ('d_date', lambda: d_date('5 марта', '2024 года',
                                                          'в её день рождения умерла мама',
                                                          '35:53', shot))):
                    page(f'{nm_}__{fkey}', fn())
            use_font(keep)
        if a.board:
            return build_quiet_board(a, num, name, sb)
        print(f'\nготово: {len(made)} макетов в {OUT}')
        return 0
    if a.what in ('ch', 'all'):
        for v, label in CH_VARIANTS:
            body = _bdd_body(v, num, name, None, shot, a.frame)
            p = page(f'bdd_ch_{v}', body, _bdd_css(v))
            made.append((f'bdd_ch_{v}', label, p))
    if a.what in ('sub', 'all') and sb:
        ch_of = f'{sb[1]:02d}'
        ch_name = dict((n, nm) for n, nm, _ in chapters()).get(ch_of, '')
        over = f'ГЛАВА {ch_of} · {ch_name}'.rstrip(' ·')
        for v, label in SUB_VARIANTS:
            body = _bdd_sub_body(v, over, sb[2], shot)
            p = page(f'bdd_sub_{v}', body, _bdd_css(v))
            made.append((f'bdd_sub_{v}', label, p))

    if a.board or a.what == 'board':
        return build_board(a, num, name, sb)
    print(f'\nготово: {len(made)} макетов в {OUT}')
    return 0


def build_board(a, num, name, sb):
    """Витрина сравнения через stages/compare_page.py.

    ⚠️ Пути только абсолютные: compare_page.resolve() резолвит имя со слешем от cwd,
    а не от mockups/. ⚠️ Недостающая пара там печатает «!! нет — пропуск» и страница всё
    равно пишется — доска с молча выпавшими вариантами выглядит готовой, поэтому проверяем сами."""
    mock = Path(P.MOCK)
    pairs = [
        (OUT / 'bdd_ch_e.png', 'A · ПЛИТА — разделитель брендбука: красное поле, кольца, коралловый диск'),
        (OUT / 'bdd_ch_f.png', 'B · ФИГУРЫ НА КАДРЕ — фигуры заходят на кадр, заголовок подчёркнут'),
        (OUT / 'bdd_ch_g.png', 'C · КРУГ — почти монохромный кадр, один красный круг'),
        (mock / 'ch_demo_a.png', 'СЕЙЧАС · ПОЛОТНО — канон канала, замеренный по кату (контроль)'),
        (OUT / 'bdd_sub_e.png', 'A · ПЛАШКА-ФИГУРА — фигура слева снизу, пояснение вдвое мельче'),
        (OUT / 'bdd_sub_f.png', 'B · КРУГ + ТЕКСТ СПРАВА СВЕРХУ — буквально правило стр. 36'),
        (mock / 'subt_05.png', 'СЕЙЧАС · ТИТР ПОДГЛАВЫ — канон канала (контроль)'),
    ]
    missing = [str(p) for p, _ in pairs if not p.exists()]
    if missing:
        print('НЕ СОБРАНО — нет исходников:', file=sys.stderr)
        for m in missing:
            print('  ' + m, file=sys.stderr)
        return 2

    out = Path(P.REVIEW_DIR) / f'{P.get("code")}_bdd_varianty.html'
    argv = [sys.executable, str(HERE / 'compare_page.py'),
            '--title', 'Экраны YTCH на языке брендбука фонда — выбрать',
            '--width', str(a.width), '--out', str(out)]
    for p, cap in pairs:
        argv += ['--pair', f'{p}:{cap}']
    argv += ['--head', '1:ЗАСТАВКА ГЛАВЫ — ЯЗЫК ФОНДА ПРОТИВ НЫНЕШНЕГО КАНОНА',
             '--head', '5:ПЛАШКА ПОДГЛАВЫ']
    for n in board_notes(num, name, sb, a):
        argv += ['--note', n]
    r = subprocess.run(argv, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0 or '!! нет' in r.stdout:
        sys.stderr.write(r.stderr)
        return 2
    print(f'\nвитрина: {out}')
    return 0


def build_quiet_board(a, num, name, sb):
    """Витрина своим сборщиком: под каждым экраном путь в блоке кода."""
    mock = Path(P.MOCK)
    M = FONT_SETS['montserrat']['label']
    O = FONT_SETS['onest']['label']
    CANON = 'PT Sans Narrow — нынешний канон канала'
    rows = [
        ('head', 'ГЛАВА, ПОДГЛАВА, ФРАЗА'),
        ('pic', mock / 'ch_demo_a.png', 'КОНТРОЛЬ · заставка главы сейчас, красный #C1272D', CANON),
        ('pic', OUT / 'q_ch.png', 'ЗАСТАВКА ГЛАВЫ', M),
        ('pic', OUT / 'q_sub.png', 'ПЛАШКА ПОДГЛАВЫ', M),
        ('pic', OUT / 'q_claim.png', 'КРУПНАЯ ФРАЗА', M),
        ('head', 'ПЛАШКИ С ИМЕНЕМ — и три с инфой внизу'),
        ('pic', OUT / 'q_lower_a.png', 'ИМЯ A · базовая, черта слева', M),
        ('pic', OUT / 'q_lower_e.png', 'ИМЯ E · с логотипом фонда', M),
        ('pic', OUT / 'n_loc.png', 'ИМЯ + ЛОКАЦИЯ · локация своей зоной под волосяной линией', M),
        ('pic', OUT / 'n_split.png', 'ИМЯ + ИНФО СПРАВА · кадр уравновешен по диагонали', M),
        ('pic', OUT / 'n_strip.png', 'ИМЯ + ПОДВАЛ-ПОЛОСА · место, срок и статус одной лентой', M),
        ('head', 'УТОЧНЕНИЯ — голос редакции, цветом канала #FB7185'),
        ('pic', OUT / 'c_note.png', 'УТОЧНЕНИЕ · короткая ремарка поверх идущей речи', M),
        ('pic', OUT / 'c_full.png', 'УТОЧНЕНИЕ РЕДАКЦИИ · полноэкранная оговорка', M),
        ('head', 'ВИЗУАЛИЗАЦИЯ ИЗ САМОГО ТЕКСТА ФИЛЬМА'),
        ('pic', OUT / 'd_debts.png', 'ДОЛГИ · суммы из речи, каждая подписана', M),
        ('pic', OUT / 'd_calendar.png', 'КАЛЕНДАРЬ АЛИМЕНТОВ · платил / не платил по месяцам', M),
        ('pic', OUT / 'd_life.png', 'ХРОНОЛОГИЯ ЖИЗНИ · линия и точки инлайн-SVG', M),
        ('pic', OUT / 'd_date.png', 'ДАТА · когда одна дата несёт поворот рассказа', M),
        ('head', 'ПРОЧИЕ ВИДЫ'),
        ('pic', OUT / 'q_stat.png', 'ЦИФРА', M),
        ('pic', OUT / 'q_money.png', 'СУММА · знак рубля больше не переносится', M),
        ('pic', OUT / 'q_question.png', 'ВОПРОС', M),
        ('pic', OUT / 'q_steps.png', 'ПУТЬ', M),
        ('pic', OUT / 'q_term.png', 'ТЕРМИН', M),
        ('pic', OUT / 'q_place.png', 'МЕСТО', M),
        ('pic', OUT / 'q_list.png', 'ПЕРЕЧИСЛЕНИЕ', M),
        ('head', 'ТОТ ЖЕ МАКЕТ ДРУГИМ ШРИФТОМ'),
        ('pic', OUT / 'q_ch__onest.png', 'ЗАСТАВКА ГЛАВЫ', O),
        ('pic', OUT / 'n_loc__onest.png', 'ИМЯ + ЛОКАЦИЯ', O),
        ('pic', OUT / 'd_date__onest.png', 'ДАТА', O),
    ]
    out = Path(P.REVIEW_DIR) / f'{P.get("code")}_ekrany_brend_v3.html'
    res = board(rows, 'Экраны YTCH · язык фонда на грамматике канала',
                out, quiet_notes(num, name, a), width=a.width, stamp=STAMP)
    if res is None:
        return 2
    print(f'\nвитрина: {out}')
    return 0


def quiet_notes(num, name, a):
    pg = BRAND.get('source', {}).get('pages', {})
    return [
        'Правка Романа 23.09.2026: варианты B, C и D убраны. F в прежнем виде отклонён, но '
        'идея «инфа внизу или локация» принята — город больше не третья строка вплотную '
        'к роли, а своя зона: под волосяной линией, в правом углу или в подвале-полосе.',
        f'ШРИФТЫ. Основной — {FONT_SETS["montserrat"]["label"]} (им пользуется фонд). '
        f'Вторым набором те же три макета в {FONT_SETS["onest"]["label"]}: у Onest кириллица '
        f'уже, длинное имя влезает крупнее — сравнить в конце витрины. Шрифт подписан на '
        f'каждом макете.',
        'НОВОЕ — экраны из самого текста фильма. Транскрипт v5 разобран: суммы, сроки, даты и '
        'календарь выплат звучат в речи, но на экране их нет, а на слух зритель их не удержит. '
        'Долги, алименты по месяцам, хронология жизни и дата 5 марта — всё это реплики героини, '
        'не выдуманные цифры; под каждым экраном стоит таймкод, откуда взято.',
        f'Ярко-красный {RED} — только черта, не поле. Ведущий акцент коралл {CORAL}. '
        f'Кадр приглушён до {int(SATUR*100)} % (стр. {pg.get("photos")}). Диаграммы — '
        f'инлайн-SVG, каждое значение подписано.',
        '⚠️ «За свет 13 тысяч, за воду, капремонт всё вместе 27 тысяч» — из речи не следует, '
        'входит ли 13 в 27. На экране показаны как две отдельные строки, как и сказано; '
        'если фонд уточнит — поправим.',
        '⚠️ Верно «ЖИМАГУЛ» (сайт фонда). В кате на 19:33 — «ЖУМАГУЛ», это правка монтажёру.',
        'ПУТИ ДЛЯ КОПИРОВАНИЯ:',
        f'макеты 4К:  {OUT}',
        f'исходники HTML:  {SRC}',
        f'эта витрина:  {Path(P.REVIEW_DIR) / (str(P.get("code")) + "_ekrany_brend_v3.html")}',
        f'шрифты:  {FONT_DIR}  и  {FONT_DIR / "alt"}',
        f'рендер:  {HERE / "bdd_plates.py"}',
        'пересобрать:  python3 stages/bdd_plates.py quiet --fonts --board',
        'В канале не изменено ничего: review_profile.json не тронут.',
    ]


def board_notes(num, name, sb, a):
    src = BRAND.get('source', {})
    pg = src.get('pages', {})
    return [
        f'Все макеты — на одном кадре ({a.frame} с) и одной главе {num} «{name}»: '
        f'доска сравнивает ГРАММАТИКУ, а не красоту кадров. Длинное имя взято нарочно — '
        f'это стресс-случай автоподбора кегля.',
        f'Цвета из брендбука: красный {RED} и коралл {CORAL} (стр. {pg.get("colors_primary")}), '
        f'доп. палитра — бирюза/олива/янтарь/сизый (стр. {pg.get("colors_extra")}). '
        f'Нынешний канон канала замерен по кату монтажёра и несёт другой красный #C1272D.',
        f'Заголовок капсом, подчёркнут, текст вдвое мельче — правило стр. {pg.get("headings")}. '
        f'Кадр приглушён до {int(SATUR*100)} % насыщенности — правило стр. {pg.get("photos")}. '
        f'Фигуры со скруглёнными углами и полупрозрачным наложением — стр. {pg.get("shapes")}.',
        'Шрифт — Montserrat (Роман 23.09.2026: «актуальный, используют»). Брендбук называет '
        'фирменным Intro, лицензионных файлов Intro нет; начертания нарезаны из вариативного '
        'Montserrat[wght].ttf, потому что в системе нет Black и запрос 900 давал подделку из 700.',
        'Логотип стоит на подглаве (банеры стр. 36 его требуют) и НЕ стоит на заставке главы — '
        'на разделителях самого брендбука логотипа нет. На кадре он лежит на белой подложке: '
        'дом обведён чёрным и на фотографии тонет (правило стр. 34).',
        'Контрольные картинки «СЕЙЧАС» — нынешний канон, без изменений. Без якоря «красивее» '
        'побеждает по умолчанию и доска перестаёт быть решением.',
        'Ничего в канале не изменено: review_profile.json не тронут, макеты лежат отдельно '
        'в mockups/bdd/. Выбор — за Романом.',
    ]




# ─────────────────────────── своя витрина ───────────────────────────
# Почему не compare_page.py: он даёт под картинкой только имя файла, а Роман 23.09.2026
# просит «каждый экран должен иметь ссылку для копирования» — то есть ПОЛНЫЙ путь, и по
# домашнему правилу путь даётся текстом в блоке кода, а не ссылкой. Плюс он молча
# пропускает недостающую пару и кладёт альфу на почти-чёрный. Свой сборщик проще, чем
# чинить общий файл, которым сейчас пользуется соседняя сессия.
BOARD_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0A0D16;color:#F0F2F8;
     font:15px/1.55 -apple-system,system-ui,'Helvetica Neue',sans-serif}
.wrap{max-width:1280px;margin:0 auto;padding:30px 24px 90px}
h1{font-size:1.8rem;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:#8A92A8;font:500 12.5px ui-monospace,monospace;margin-bottom:20px}
.notes{background:#181D2B;border:1px solid #3A4258;border-left:3px solid #FB7185;
       border-radius:11px;padding:14px 17px;margin:0 0 26px;color:#C8CDD9}
.notes div+div{margin-top:7px}
h2{font-size:1.16rem;margin:38px 0 14px;color:#E4FF6E;letter-spacing:.01em}
figure{margin:0 0 30px}
figure img{width:100%;display:block;border-radius:10px;border:1px solid #252B3D}
.cap{margin-top:9px;font-size:14.5px;color:#F0F2F8;font-weight:600}
.meta{margin-top:3px;font-size:12.5px;color:#8A92A8}
code{display:block;margin-top:8px;padding:9px 12px;background:#12172400;
     background-color:#141A28;border:1px solid #252B3D;border-radius:8px;
     font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#C8CDD9;
     white-space:pre-wrap;word-break:break-all;user-select:all}
.foot{margin-top:40px;border-top:1px solid #3A4258;padding-top:16px;
      color:#8A92A8;font-size:12.5px}
"""


def _embed(path, width):
    import base64 as _b64
    import io
    from PIL import Image
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        flat = Image.new('RGB', im.size, (10, 13, 22))
        flat.paste(im, (0, 0), im)
        im = flat
    else:
        im = im.convert('RGB')
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=88)
    return _b64.b64encode(buf.getvalue()).decode(), im.size


def board(rows, title, out, notes, width=1920, stamp=''):
    """rows: [('head', 'ЗАГОЛОВОК') | ('pic', path, подпись, шрифт)]"""
    missing = [str(r[1]) for r in rows if r[0] == 'pic' and not Path(r[1]).exists()]
    if missing:
        print('НЕ СОБРАНО — нет исходников:', file=sys.stderr)
        for m in missing:
            print('  ' + m, file=sys.stderr)
        return None
    body, n = [], 0
    for r in rows:
        if r[0] == 'head':
            body.append(f'<h2>{esc(r[1])}</h2>')
            continue
        _, path, cap, fontlab = r
        b64, size = _embed(Path(path), width)
        n += 1
        body.append(
            f'<figure><img src="data:image/jpeg;base64,{b64}" alt="">'
            f'<div class="cap">{esc(cap)}</div>'
            f'<div class="meta">шрифт: {esc(fontlab)} · {size[0]}×{size[1]} '
            f'из {CANVAS_W}×{CANVAS_H} · {esc(Path(path).name)}</div>'
            f'<code>{esc(str(path))}</code></figure>')
    nt = ''.join(f'<div>{esc(x)}</div>' for x in notes)
    html = (
        '<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<link rel="icon" href="data:image/svg+xml,'
        "<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22>"
        "<text y=%22.9em%22 font-size=%2290%22>\U0001F5BC️</text></svg>\">"
        f'<title>{esc(P.get("code",""))} · {esc(title)}</title>'
        f'<style>{BOARD_CSS}</style></head><body><div class="wrap">'
        f'<h1>{esc(title)}</h1>'
        f'<div class="sub">{esc(P.get("code",""))} · кат {esc(P.CUT_VERSION)} · '
        f'экранов {n} · собрано {esc(stamp)}</div>'
        f'<div class="notes">{nt}</div>{"".join(body)}'
        f'<div class="foot">Собрано stages/bdd_plates.py · путь под каждым экраном '
        f'выделяется одним кликом</div></div></body></html>')
    Path(out).write_text(html, encoding='utf-8')
    print(f'{out}  ({len(html.encode())/1024:.0f} КБ, экранов {n})')
    return out


if __name__ == '__main__':
    sys.exit(main())
