#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feedback_visuals — картинки для колонок 5–6 вкладки «Обратная связь по кату vN» (контракт docs/feedback_v1.md §8–§9).

Зачем: Роман хочет видеть в доке у каждого пункта две картинки — «экран с ошибкой» (стрелка на место ошибки)
и «как надо» (мокап, превью стадии или наш драфт, обязательно с указанием, откуда взято). Рендереры дока и HTML
картинок не рисуют — они берут готовое из `work/{cut}/feedback_visuals/index.json`, который строит этот модуль.

    import feedback_visuals as FV
    index = FV.build(fb, review_dir, out_dir, only_missing=False)     # index['rows']['{part}:{n}'] = {'err', 'fix'}

Что строится (для строк buckets new/block/open/blur/closed без dup_of):
  err (колонка 5), kind ∈ arrow|frame|none:
    Часть 1 — превью стадии с отметкой (manifest previews_doc или material_rich пункта: dp_*.jpg, v6_err_*.jpg);
    доказательство «экран» с известным положением текста → кадр на секунде доказательства + красная рамка и стрелка;
    иначе кадр на месте пункта с подписью; нет времени/кадра → none (причина — в source.text и why).
  fix (колонка 6) — ОБЯЗАТЕЛЕН, kind ∈ mockup|preview|draft|reference|card:
    готовый мокап/превью стадии (mockups/card_NN.png по названию главы, card_title, lt_gulya, structure_map,
    material_rich Части 1, плашка ТЗ прошлой версии mockups/tz/tz_NN.png) → референс по URL из текста пункта
    (картинка не качается) → наш драфт (PIL в стиле канала: титр поверх кадра / полоса «вырезать» / карточка «КАК НАДО»).
    Текст драфтов — только из модели (заголовок, ✅, 📍); ничего не сочиняется.
Подписи — строго «M:SS · что видно» / «сводно · …» (CAP_RE — копия stages/doc_pdf_qc.py). JPEG ≤1000 px, ≤160 КБ,
кадр не растягивается сверх исходника. Один и тот же вход даёт побайтно те же файлы (время в картинку не идёт).

CLI: feedback_visuals.py --fb PATH --review-dir DIR [--out DIR] [--only-missing] [--selftest]
Никакого proj_config и чтения файлов на уровне модуля.
"""
import argparse
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    import i18n  # noqa: E402
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import i18n  # noqa: E402

T = i18n.T
HERE = Path(__file__).resolve().parent
YTAI = HERE.parent.parent.parent.parent

SCHEMA = 'feedback-visuals-v1'
MAX_W, MAX_KB, Q_START, Q_MIN, W_MIN = 1000, 160, 82, 40, 600
CAP_MAX = 70                                                   # «что видно» — короткая фраза
BUCKETS_FULL = ('new', 'block', 'open', 'blur', 'closed')
CAP_RE = re.compile(r'^(?:\d{1,2}:\d{2}(?:[–-]\d{1,2}:\d{2})?|сводно)\s·\s\S')   # копия stages/doc_pdf_qc.py:59
TC = r'[~≈]?\d{1,2}:\d{2}(?:\.\d+)?(?:\s*[–-]\s*\d{1,2}:\d{2}(?:\.\d+)?)?'
TCR = re.compile(rf'(?<![\d:]){TC}(?!\d|:\d)')                # «на ≈27:09:» — двоеточие после таймкода не мешает
TC_PHRASE = re.compile(rf'(?:\b(?:на|в|с|до|от|около|после|перед|к)\s+)?(?<![\d:]){TC}(?!\d|:\d):?', re.I)
TC_RANGE = re.compile(r'(?<![\d:])(\d{1,2}:\d{2})(?:\.\d+)?\s*[–-]\s*(\d{1,2}:\d{2})(?:\.\d+)?(?![\d:])')
TC_ONE = re.compile(r'(?<![\d:])(\d{1,2}:\d{2})(?:\.\d+)?(?![\d:])')
URL_RE = re.compile(r'(?:https?://)?(?:[a-z0-9-]+\.)+(?:ru|com|org|net|ae|io|su|рф)(?:/[\w./?=&%#-]*)?', re.I)
QUOTE_RE = re.compile(r'«([^«»]{2,})»')
NOT_ON_SCREEN = re.compile(r'текста нет|нет на экран|такого текста|не стоит|отсутству|графики нет', re.I)
JARGON = re.compile(r'(?<![\w/.-])[hsf]\d{3,4}(?![\w-])')
# служебное слово на конце обрезанной фразы («…дубля на 9 с, до», «…от «знаете что» до», «…склейка → »)
TAIL_STOP = re.compile(r'(?:(?<![\d≈~])\s+(?:до|от|и|а|но|на|в|во|с|со|к|ко|по|за|о|об|у|из|не|или|что|как|для|при|под|над|через|после|перед|между)\s*[,;:—-]*|\s*[→←])+$', re.I)   # «9 с» — секунды, не предлог
FRAME_NAME = re.compile(r'^f\d{4,5}\.jpe?g$', re.I)           # кадры прошлого ката (material_rich прошлого ТЗ)
NAMED_MOCK = re.compile(r'^(card_\d+|card_title|lt_\w+|structure_map)\.png$', re.I)   # мокапы, которые берутся по смыслу пункта
DRIVE_URL = 'https://drive.google.com/file/d/{}/view'

STYLE_DEFAULT = {'ivory': '#FFFFFF', 'red': '#C1272D', 'mut': '#BBBBBB', 'bg': '#000000',
                 'font_stack': "'PT Sans Narrow','Arial Narrow',sans-serif", 'draft_badge': ''}
# семейство из style.font_stack → файлы TTF/TTC на этом компьютере (первое найденное; index — по имени начертания)
FONT_FILES = {
    'PT Sans Narrow': ['/System/Library/Fonts/Supplemental/PTSans.ttc', '/Library/Fonts/PTSans.ttc',
                       str(Path.home() / 'Library/Fonts/PTSans-NarrowBold.ttf')],
    'Arial Narrow': ['/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf', '/Library/Fonts/Arial Narrow Bold.ttf'],
    'Helvetica': ['/System/Library/Fonts/Helvetica.ttc'],
    'Arial': ['/System/Library/Fonts/Supplemental/Arial Bold.ttf', '/Library/Fonts/Arial Bold.ttf'],
    'DejaVu Sans': ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'],
}
SYMBOL_FILES = ['/System/Library/Fonts/Supplemental/Arial Unicode.ttf', '/Library/Fonts/Arial Unicode.ttf',
                '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
_font_cache = {}


# ── шрифты ───────────────────────────────────────────────────────────────────
def _ttc_index(path, want_bold):
    """номер начертания в коллекции: жирное «Narrow»/«Bold» либо первое"""
    best = None
    for i in range(0, 16):
        try:
            f = ImageFont.truetype(path, 20, index=i)
        except (OSError, ValueError):
            break
        fam, sty = f.getname()
        narrow = 'narrow' in fam.lower()
        bold = 'bold' in sty.lower()
        score = (narrow, bold == want_bold)
        if best is None or score > best[0]:
            best = (score, i)
    return best[1] if best else 0


def _font(size, style=None, bold=True, symbol=False):
    """шрифт канала (первое семейство из style.font_stack, что есть на диске) заданного кегля;
    symbol=True — шрифт со знаками ✂ ▸ (Arial Unicode); ничего нет → встроенный PIL"""
    stack = [s.strip(" '\"") for s in str((style or STYLE_DEFAULT).get('font_stack') or '').split(',')]
    key = (size, bold, symbol, tuple(stack))
    if key in _font_cache:
        return _font_cache[key]
    f = None
    files = SYMBOL_FILES if symbol else [p for fam in stack + list(FONT_FILES) for p in FONT_FILES.get(fam, [])]
    for p in files:
        if not os.path.isfile(p):
            continue
        try:
            idx = _ttc_index(p, bold) if p.lower().endswith('.ttc') else 0
            f = ImageFont.truetype(p, size, index=idx)
            break
        except (OSError, ValueError):
            continue
    if f is None:
        try:
            f = ImageFont.load_default(size)
        except TypeError:                                      # старый Pillow
            f = ImageFont.load_default()
    _font_cache[key] = f
    return f


def _has_glyph(font, ch):
    try:
        return font.getmask(ch).getbbox() != font.getmask('￿').getbbox()
    except Exception:                                          # noqa: BLE001
        return False


# ── текст ────────────────────────────────────────────────────────────────────
def _tc_str(sec):
    s = int(float(sec))
    return f'{s // 60}:{s % 60:02d}'


def _shorten(text, limit=CAP_MAX):
    """короткая человеческая фраза: без таймкодов и жаргона, ≤limit знаков, обрыв по слову, без многоточий,
    кавычки «» не остаются незакрытыми"""
    s = ' '.join(str(text or '').split())
    s = TC_PHRASE.sub(' ', s)                                  # «на ≈27:09:» / «с 11:09» — вместе с предлогом
    s = JARGON.sub('', s)
    s = re.sub(r'\s*[▸·]\s*', ' ', s)
    s = re.sub(r'\(\s*\)', '', s)
    s = re.sub(r'\(\s+', '(', s)                               # «( «цитата»)» после вырезанного таймкода
    s = re.sub(r'\s+([,.;:!?)])', r'\1', s)
    s = re.sub(r'\s{2,}', ' ', s).strip(' ,;:—-→')
    if len(s) > limit:
        s = s[:limit + 1]
        s = s[:s.rfind(' ')] if ' ' in s else s[:limit]
        s = s.rstrip(' ,;:—-(«')
        s = re.sub(r'\s+\d+$', '', s)                           # обрыв на голой цифре («добавить 4») — без неё
    while s.count('«') > s.count('»'):                         # оборванная цитата (и вложенная «…«…»»): до конца предложения
        i = s.rfind('«')                                       # внутри неё, иначе без цитаты
        j = max(s.rfind('. ', i), s.rfind('? ', i), s.rfind('! ', i))
        s = (s[:j + 1] + '»') if j > i + 10 else s[:i].rstrip(' ,;:—-')
    if s.count('(') > s.count(')'):
        s = s[:s.rfind('(')].rstrip(' ,;:—-')
    s = TAIL_STOP.sub('', s).rstrip(' ,;:—-→')                  # обрыв на «до» / «и» / «→» — фраза без хвоста
    return s.rstrip('.') if not s.endswith('..') else s.rstrip('.')


def _cap(tc, what, prefix=''):
    """подпись «M:SS · что видно» / «сводно · …» по CAP_RE"""
    what = _shorten(what, CAP_MAX - len(prefix)) or T('fb.vis.what_frame')
    return f'{tc or "сводно"} · {prefix}{what}'


def _row_texts(row):
    p = row.get('parts') or {}
    return [str(row.get('title') or '')] + [str(x) for k in ('now', 'do', 'where') for x in (p.get(k) or [])] + \
           [str((row.get('evidence') or {}).get('text') or '')]


def _row_url(row):
    """ссылка-референс ТОЛЬКО из текста самого пункта (заголовок, ❌ ✅ 📍, доказательство) — ничего не выдумывается"""
    for s in _row_texts(row):
        for m in URL_RE.finditer(s):
            u = m.group(0).rstrip('.,;:)»')
            if '.' not in u or u.lower().startswith(('т.е', 'т.к')) or re.match(r'^\d', u):
                continue
            return u if u.lower().startswith('http') else 'https://' + u
    return None


def _do_lines(row):
    return [str(x) for x in ((row.get('parts') or {}).get('do') or []) if str(x).strip()]


def _first_do(row):
    for s in _do_lines(row):
        s2 = s.lstrip('⚠️ ').strip()
        if s2:
            return s2
    return str(row.get('title') or '')


# строка ✅ НАЧИНАЕТСЯ с глагола «вырезать/убрать/удалить/резать» (после номера списка) — только тогда полоса
# говорит «вырезать M:SS–M:SS»; «сжать», «сократить», «оставить … убрать хвост» — не то же самое, их не переводим
CUT_VERB = re.compile(r'^(?:\d+[.)]\s*)?(?:вырез\w*|убрать|убери\w*|удал\w*|резать|режем|cut|remove)\b', re.I)


def _cut_plan(row):
    """текст полосы для пункта «резать»: («вырезать», диапазон) — если строка ✅ начинается с глагола резки
    и в ней есть таймкод; иначе (первая строка ✅ как есть, диапазон из 📍) — ничего не сочиняем"""
    p = row.get('parts') or {}
    for s in _do_lines(row):
        s = s.lstrip('⚠️ ').strip()
        if CUT_VERB.match(s):
            m = TC_RANGE.search(s) or TC_ONE.search(s)
            if m:
                rng = f'{m.group(1)}–{m.group(2)}' if m.re is TC_RANGE else m.group(1)
                return T('fb.vis.draft_cut', rng=rng), None
    rng = None
    for s in list(p.get('where') or []) + _do_lines(row):
        m = TC_RANGE.search(str(s)) or TC_ONE.search(str(s))
        if m:
            rng = f'{m.group(1)}–{m.group(2)}' if m.re is TC_RANGE else m.group(1)
            break
    return _shorten(_first_do(row), 60), rng or (str(row.get('tc_new') or '').lstrip('≈~') or None)


def _quoted(row):
    """предлагаемый текст титра: первая «цитата» из ✅, иначе из заголовка, иначе первая строка ✅ целиком"""
    for s in _do_lines(row) + [str(row.get('title') or '')]:
        m = QUOTE_RE.search(s)
        if m:
            return m.group(1).strip()
    return _first_do(row)


def _num_label(row, fb):
    label = i18n.tz_label(row['n'])
    prev = fb.get('prev_cut_version') or ''
    return label if row.get('part') == 1 or not prev else T('fb.num_prev', label=label, prev=prev)


# ── картинки: загрузка, размер, запись ───────────────────────────────────────
def _hex(c, default=(0, 0, 0)):
    c = str(c or '').strip()
    m = re.match(r'^#([0-9a-f]{6})$', c, re.I)
    if m:
        h = m.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r'^rgba?\((\d+),\s*(\d+),\s*(\d+)', c)
    return tuple(int(x) for x in m.groups()) if m else default


def _open(path):
    try:
        return Image.open(path)
    except Exception:                                          # noqa: BLE001  (нет файла, битый файл)
        return None


def _fit(im):
    """RGB не шире MAX_W; маленькие кадры не растягиваются (лучше меньшая картинка, чем мыло)"""
    im = im.convert('RGB')
    if im.width > MAX_W:
        im = im.resize((MAX_W, max(1, round(im.height * MAX_W / im.width))), Image.LANCZOS)
    return im


def _jpeg(im, path):
    """JPEG ≤160 КБ: сначала вниз качество, потом ширина. Без EXIF/времени → детерминированно."""
    im = _fit(im)
    q, data = Q_START, b''
    while True:
        buf = io.BytesIO()
        im.save(buf, 'JPEG', quality=q, optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) <= MAX_KB * 1024:
            break
        if q > Q_MIN:
            q -= 6
        elif im.width > W_MIN:
            w = max(W_MIN, int(im.width * 0.85))
            im = im.resize((w, max(1, round(im.height * w / im.width))), Image.LANCZOS)
            q = Q_START
        else:
            break
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == data:               # те же байты → файл не трогаем (mtime, Drive-md5)
        return im.width, len(data)
    tmp = str(path) + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)
    return im.width, len(data)


def _canvas(style, w=MAX_W):
    return Image.new('RGB', (w, round(w * 9 / 16)), _hex(style.get('bg'), (0, 0, 0)))


def _over(base, overlay_path):
    """прозрачный PNG (плашка, подпись) поверх кадра; непрозрачный — сам по себе"""
    ov = _open(overlay_path)
    if ov is None:
        return None
    if ov.mode in ('RGBA', 'LA') or (ov.mode == 'P' and 'transparency' in ov.info):
        ov = ov.convert('RGBA')
        base = _fit(base) if base is not None else None
        if base is None:
            base = Image.new('RGB', (min(MAX_W, ov.width), round(min(MAX_W, ov.width) * ov.height / ov.width)), (0, 0, 0))
        ov = ov.resize(base.size, Image.LANCZOS)
        return Image.alpha_composite(base.convert('RGBA'), ov).convert('RGB')
    return _fit(ov)


def _badge(im, style, draw=None):
    """бейдж «DRAFT · перерисовать в стиле канала» в правом нижнем углу (как у мокапов стадии)"""
    txt = str(style.get('draft_badge') or '') or T('fb.vis.draft_badge')
    d = draw or ImageDraw.Draw(im)
    f = _font(max(11, im.width // 70), style, bold=False)
    tw = d.textlength(txt, font=f)
    d.text((im.width - tw - im.width // 60, im.height - im.width // 40), txt, font=f, fill=(255, 255, 255, 110))


def _wrap(draw, text, font, max_w):
    words, lines, cur = str(text).split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


# ── рисование: стрелка, полоса, титр, карточка ───────────────────────────────
def _arrow_box(im, bbox, style):
    """красная скруглённая рамка вокруг bbox (доли кадра: x, y, w, h) + стрелка от ближайшего свободного края"""
    im = _fit(im)
    W, H = im.size
    red = _hex(style.get('red'), (193, 39, 45))
    th = max(3, round(W / 250))
    pad = max(6, round(W / 120))
    x0 = max(0, round(bbox[0] * W) - pad)
    y0 = max(0, round(bbox[1] * H) - pad)
    x1 = min(W - 1, round((bbox[0] + bbox[2]) * W) + pad)
    y1 = min(H - 1, round((bbox[1] + bbox[3]) * H) + pad)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0, x1, y1], radius=max(4, th * 3), outline=red, width=th)
    # стрелка: со стороны, где больше места между рамкой и краем кадра
    room = {'top': y0, 'bottom': H - 1 - y1, 'left': x0, 'right': W - 1 - x1}
    side = max(room, key=room.get)
    L = max(th * 8, min(room[side] * 0.6, W / 6))
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    if side == 'top':
        tip, tail = (cx, y0 - th), (cx, y0 - th - L)
    elif side == 'bottom':
        tip, tail = (cx, y1 + th), (cx, y1 + th + L)
    elif side == 'left':
        tip, tail = (x0 - th, cy), (x0 - th - L, cy)
    else:
        tip, tail = (x1 + th, cy), (x1 + th + L, cy)
    d.line([tail, tip], fill=red, width=th)
    hl = th * 4
    dx, dy = (tip[0] - tail[0]) / L, (tip[1] - tail[1]) / L
    px, py = -dy, dx
    head = [tip, (tip[0] - dx * hl + px * hl * 0.6, tip[1] - dy * hl + py * hl * 0.6),
            (tip[0] - dx * hl - px * hl * 0.6, tip[1] - dy * hl - py * hl * 0.6)]
    d.polygon(head, fill=red)
    return im


def _cut_band(im, txt, sub, style):
    """кадр с полупрозрачной красной полосой по центру: «✂ вырезать M:SS–M:SS» либо «✂ действие» + диапазон строкой ниже"""
    im = _fit(im).convert('RGBA')
    W, H = im.size
    red = _hex(style.get('red'), (193, 39, 45))
    band = Image.new('RGBA', im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    bh = round(H * (0.28 if sub else 0.22))
    y0 = (H - bh) // 2
    d.rectangle([0, y0, W, y0 + bh], fill=red + (170,))
    fs = round(H * 0.22 * 0.5)
    f = _font(fs, style)
    while d.textlength(txt, font=f) > W * 0.8 and fs > 12:       # длинное действие — кегль вниз
        fs -= 2
        f = _font(fs, style)
    sym = _font(fs, style, symbol=True)
    scissors = '✂' if _has_glyph(sym, '✂') else ''
    tw = d.textlength(txt, font=f) + (d.textlength(scissors + ' ', font=sym) if scissors else 0)
    x = (W - tw) / 2
    y = y0 + round(H * 0.22 * 0.22)
    if scissors:
        d.text((x, y), scissors, font=sym, fill=(255, 255, 255, 255))
        x += d.textlength(scissors + ' ', font=sym)
    d.text((x, y), txt, font=f, fill=(255, 255, 255, 255))
    if sub:
        f2 = _font(round(fs * 0.7), style, bold=False)
        d.text(((W - d.textlength(sub, font=f2)) / 2, y + fs * 1.2), sub, font=f2, fill=(255, 255, 255, 255))
    out = Image.alpha_composite(im, band)
    _badge(out, style, ImageDraw.Draw(out))
    return out.convert('RGB')


def _lower_third(im, text, style):
    """предлагаемый титр/подпись нижней плашкой поверх кадра в стиле канала: тёмная панель, красный корешок,
    белый узкий гротеск"""
    im = _fit(im).convert('RGBA')
    W, H = im.size
    panel = _hex(style.get('panel'), (0, 0, 0))
    red = _hex(style.get('red'), (193, 39, 45))
    ivory = _hex(style.get('ivory'), (255, 255, 255))
    f = _font(round(W / 18), style)
    d0 = ImageDraw.Draw(im)
    lines = _wrap(d0, text.upper(), f, W * 0.78)[:3]
    lh = round(W / 18 * 1.15)
    ph = lh * len(lines) + round(W / 22)
    y0 = H - ph - round(H * 0.07)
    layer = Image.new('RGBA', im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0 = round(W * 0.06)
    d.rounded_rectangle([x0, y0, round(W * 0.94), y0 + ph], radius=round(W / 90), fill=panel + (210,))
    d.rectangle([x0, y0, x0 + round(W / 110), y0 + ph], fill=red + (255,))
    y = y0 + round(W / 44)
    for ln in lines:
        d.text((x0 + round(W / 28), y), ln, font=f, fill=ivory + (255,))
        y += lh
    out = Image.alpha_composite(im, layer)
    _badge(out, style, ImageDraw.Draw(out))
    return out.convert('RGB')


def _title_card(text, style):
    """карточка канала: чёрный кадр, белый узкий гротеск КАПСОМ по центру, слова столбиком (как card_NN мокапы)"""
    im = _canvas(style)
    W, H = im.size
    d = ImageDraw.Draw(im)
    f = _font(round(W / 9), style)
    lines = _wrap(d, text.upper(), f, W * 0.86)[:4]
    lh = round(W / 9 * 1.12)
    y = (H - lh * len(lines)) // 2
    for ln in lines:
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2, y), ln, font=f, fill=_hex(style.get('ivory'), (255, 255, 255)))
        y += lh
    _badge(im, style, d)
    return im


def _how_card(title, lines, style, head=None):
    """карточка «КАК НАДО»: фон канала, серая шапка, красная черта, заголовок пункта и до 3 строк ✅"""
    im = _canvas(style)
    W, H = im.size
    d = ImageDraw.Draw(im)
    red = _hex(style.get('red'), (193, 39, 45))
    ivory = _hex(style.get('ivory'), (255, 255, 255))
    mut = _hex(style.get('mut'), (187, 187, 187))
    x0, y = round(W * 0.07), round(H * 0.09)
    f_lbl = _font(round(W / 34), style, bold=False)
    d.text((x0, y), head or T('fb.vis.draft_head'), font=f_lbl, fill=mut)
    y += round(W / 34 * 1.5)
    d.rectangle([x0, y, x0 + round(W * 0.12), y + max(2, round(W / 250))], fill=red)
    y += round(W / 40)
    f_h = _font(round(W / 20), style)
    for ln in _wrap(d, ' '.join(str(title).split()), f_h, W * 0.86)[:2]:
        d.text((x0, y), ln, font=f_h, fill=ivory)
        y += round(W / 20 * 1.15)
    y += round(W / 50)
    f_b = _font(round(W / 30), style, bold=False)
    lh = round(W / 30 * 1.3)
    for s in lines[:3]:
        for j, ln in enumerate(_wrap(d, ' '.join(str(s).split()), f_b, W * 0.82)[:3]):
            if y + lh > H - round(H * 0.1):
                break
            d.text((x0 + (round(W / 40) if j else 0), y), ('• ' if not j else '') + ln, font=f_b, fill=ivory)
            y += lh
        y += round(lh * 0.35)
    _badge(im, style, d)
    return im


# ── контекст сборки: где что лежит ───────────────────────────────────────────
class Ctx:
    """пути и справочники одной сборки; всё читается лениво и переживает отсутствие любого файла"""

    def __init__(self, fb, review_dir, out_dir):
        self.fb = fb
        self.rd = Path(review_dir)
        self.out = Path(out_dir)
        self.cut = str(fb.get('cut_version') or '')
        self.prev = str(fb.get('prev_cut_version') or '')
        self.work = self.rd / 'work' / self.cut
        self.hires = self.work / 'hires'
        self.mock = self.rd / 'mockups'
        self.style = self._style()
        self._screens = self._ocr = self._mr1 = self._mr_prev = self._tz = self._cards = self._ids = self._man = None

    def _style(self):
        st = dict(STYLE_DEFAULT)
        m = re.match(r'^(YT[A-Z]{2,4})', str(self.fb.get('code') or ''))
        if m:
            try:
                prof = json.loads((YTAI / 'YTs' / m.group(1) / 'review_profile.json').read_text(encoding='utf-8'))
                st.update({k: v for k, v in (prof.get('style') or {}).items() if v})
            except (OSError, ValueError):
                pass
        return st

    def rel(self, p):
        try:
            return str(Path(p).resolve().relative_to(self.rd.resolve()))
        except ValueError:
            return str(p)

    # кадры нового ката: h{sec+1:04d}.jpg; нет точного — соседний в пределах ±3 с
    def frame_at(self, sec):
        if sec is None:
            return None, None
        s = int(float(sec))
        for d in (0, 1, -1, 2, -2, 3, -3):
            if s + d < 0:
                continue
            p = self.hires / f'h{s + d + 1:04d}.jpg'
            if p.is_file():
                return p, s + d
        return None, None

    # положение строк текста на кадре (доли кадра): OCR по кадрам → экраны стадии
    def ocr_lines(self, path, sec):
        if self._ocr is None:
            self._ocr = {}
            p = self.work / 'ocr_hires.jsonl'
            if p.is_file():
                with open(p, encoding='utf-8') as f:
                    for ln in f:
                        try:
                            o = json.loads(ln)
                        except ValueError:
                            continue
                        self._ocr[os.path.basename(str(o.get('file') or ''))] = o.get('lines') or []
        lines = self._ocr.get(os.path.basename(str(path))) if path else None
        if lines:
            return lines
        if self._screens is None:
            self._screens = []
            p = self.work / 'screens_v6.json'
            if p.is_file():
                try:
                    self._screens = json.loads(p.read_text(encoding='utf-8')) or []
                except ValueError:
                    self._screens = []
        for sc in self._screens:
            try:
                if float(sc.get('t0')) <= float(sec) <= float(sc.get('t1')) + 0.999:
                    lb = sc.get('lines_best')
                    if isinstance(lb, str):
                        import ast
                        lb = ast.literal_eval(lb)
                    return [x for x in (lb or []) if isinstance(x, dict) and 'x' in x]
            except (TypeError, ValueError, SyntaxError):
                continue
        return []

    def material_rich_part1(self, n):
        if self._mr1 is None:
            self._mr1 = {}
            for p in sorted(self.rd.glob('pravki/pravki_v*.json')):
                try:
                    items = (json.loads(p.read_text(encoding='utf-8')) or {}).get('all') or []
                except (OSError, ValueError):
                    continue
                self._mr1 = {i + 1: (it.get('material_rich') or []) for i, it in enumerate(items) if isinstance(it, dict)}
        return self._mr1.get(int(n), [])

    def material_rich_prev(self, n):
        if self._mr_prev is None:
            self._mr_prev = {}
            pf = self.fb.get('prev_file')
            p = self.rd / pf if pf else None
            if p and p.is_file():
                try:
                    items = (json.loads(p.read_text(encoding='utf-8')) or {}).get('all') or []
                    self._mr_prev = {i + 1: (it.get('material_rich') or []) for i, it in enumerate(items)
                                     if isinstance(it, dict)}
                except (OSError, ValueError):
                    pass
        return self._mr_prev.get(int(n), [])

    def manifest(self):
        """previews_doc/manifest.json → {(n, роль): (path, подпись)}; роль err|fix. Форма записи свободная:
        файл (file/img/name), пункт (n / label «ТЗ-NN» / tz / из имени dp_(fix|err)_tz01), подпись (cap/caption/t)"""
        if self._man is None:
            self._man = {}
            p = self.work / 'previews_doc' / 'manifest.json'
            if p.is_file():
                try:
                    raw = json.loads(p.read_text(encoding='utf-8'))
                except ValueError:
                    raw = None
                entries = raw if isinstance(raw, list) else \
                    (raw.get('items') or raw.get('previews') or list(raw.values()) if isinstance(raw, dict) else [])
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    name = str(e.get('file') or e.get('img') or e.get('name') or '')
                    n = e.get('n') or e.get('tz')
                    if n is None:
                        m = re.search(r'(?:ТЗ-|tz)(\d+)', str(e.get('label') or '') + ' ' + name, re.I)
                        n = int(m.group(1)) if m else None
                    if not name or n is None:
                        continue
                    role = str(e.get('role') or e.get('kind') or '')
                    role = 'fix' if ('fix' in role or 'fix' in name.lower() or 'how' in role) else \
                        ('err' if ('err' in role or 'err' in name.lower() or 'ann' in name.lower()) else 'fix')
                    self._man.setdefault((int(n), role), (self.find_preview(name), str(e.get('cap') or e.get('caption') or e.get('t') or '')))
        return self._man

    def find_preview(self, name):
        name = os.path.basename(str(name))
        for d in (self.work / 'previews_doc', self.work / 'err_frames', self.work / 'previews_v6', self.mock,
                  self.mock / 'tz'):
            p = d / name
            if p.is_file():
                return p
        return None

    def tz_plate(self, n):
        """плашка ТЗ прошлой версии mockups/tz/tz_NN.png по tz_index.json прошлого ревью"""
        if self._tz is None:
            self._tz = {}
            for p in [self.rd / f'{self.prev}_review' / 'tz_index.json'] + sorted(self.rd.glob('v*_review/tz_index.json')):
                if p.is_file():
                    try:
                        self._tz = json.loads(p.read_text(encoding='utf-8')) or {}
                        break
                    except ValueError:
                        continue
        for k in (f'ТЗ-{int(n):02d}', f'ТЗ-{int(n)}', f'FIX-{int(n):02d}', str(n)):
            v = self._tz.get(k)
            if v:
                p = Path(v)
                for c in (p, self.mock / 'tz' / p.name):
                    if c.is_file():
                        return c
        p = self.mock / 'tz' / f'tz_{int(n):02d}.png'
        return p if p.is_file() else None

    def cards(self):
        """карточки глав mockups/card_NN.png → название главы (из src/card_NN.html; запас — structure прошлого ревью)"""
        if self._cards is None:
            self._cards = {}
            for p in sorted(self.mock.glob('card_[0-9][0-9].png')):
                src = self.mock / 'src' / (p.stem + '.html')
                title = ''
                if src.is_file():
                    body = re.sub(r'<style.*?</style>', '', src.read_text(encoding='utf-8', errors='ignore'), flags=re.S)
                    body = re.sub(r'<div[^>]*>DRAFT[^<]*</div>', '', body)
                    title = ' '.join(re.findall(r'>([^<>]+)<', body)).strip()
                self._cards[p] = _norm(title)
            if not any(self._cards.values()):
                for sp in sorted(self.rd.glob('v*_review/structure_v*.json')):
                    try:
                        chs = json.loads(sp.read_text(encoding='utf-8'))['final']['asis']['chapters']
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
                    for i, c in enumerate(chs, 1):
                        p = self.mock / f'card_{i:02d}.png'
                        if p in self._cards:
                            self._cards[p] = _norm(c.get('title') or '')
                    break
        return self._cards

    def drive_url(self, path):
        """Drive-ссылка на файл материала по журналам pravki/*_ids.json (имя → id); нет журнала — null"""
        if self._ids is None:
            self._ids = {}
            for name in ('proj_material_ids.json', 'shots_ids.json', 'feedback_frames_ids.json'):
                p = self.rd / 'pravki' / name
                if not p.is_file():
                    continue
                try:
                    raw = json.loads(p.read_text(encoding='utf-8'))
                except ValueError:
                    continue
                items = raw.items() if isinstance(raw, dict) else []
                for k, v in items:
                    fid = v.get('id') if isinstance(v, dict) else v
                    if isinstance(fid, str) and fid:
                        self._ids.setdefault(os.path.basename(k), fid)
        fid = self._ids.get(os.path.basename(str(path))) if path else None
        return DRIVE_URL.format(fid) if fid else None


def _norm(s):
    return re.sub(r'[^0-9a-zа-яё]+', '', str(s or '').lower().replace('ё', 'е'))


# ── err: колонка 5 ───────────────────────────────────────────────────────────
def _bbox_for(lines, evidence_text):
    """рамка по строкам текста: строки, совпавшие с «цитатами» доказательства; без совпадений — все строки,
    но только если доказательство не говорит «такого текста нет»"""
    quotes = [_norm(q) for q in QUOTE_RE.findall(evidence_text or '')]
    quotes = [q for q in quotes if len(q) >= 3]
    hit = []
    for ln in lines:
        t = _norm(ln.get('t'))
        # цитата внутри строки экрана — любая; строка внутри цитаты — только от 4 знаков
        # («на», «он» из OCR-обрывков совпали бы с чем угодно)
        if len(t) >= 2 and any(q in t or (len(t) >= 4 and t in q) for q in quotes):
            hit.append(ln)
    if not hit and (quotes or NOT_ON_SCREEN.search(evidence_text or '')):
        return None
    use = hit or lines
    if not use:
        return None
    x0 = min(float(l['x']) for l in use)
    y0 = min(float(l['y']) for l in use)
    x1 = max(float(l['x']) + float(l.get('bw') or l.get('w') or 0) for l in use)
    y1 = max(float(l['y']) + float(l.get('bh') or l.get('h') or 0) for l in use)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def _err_what(row):
    ev = row.get('evidence') or {}
    return ev.get('text') or next((s for s in ((row.get('parts') or {}).get('now') or []) if str(s).strip()), '') \
        or row.get('title') or ''


def _build_err(ctx, row):
    out = ctx.out / f'p{row["part"]}_{int(row["n"]):03d}_err.jpg'
    ver = ctx.cut
    what = _err_what(row)
    # (а) Часть 1: превью стадии с отметкой ошибки — manifest previews_doc, затем material_rich пункта
    if row.get('part') == 1:
        cands = []
        m = ctx.manifest().get((int(row['n']), 'err'))
        if m and m[0]:
            cands.append((m[0], m[1]))
        for mr in ctx.material_rich_part1(row['n']):
            img = str(mr.get('img') or '')
            t = str(mr.get('t') or '')
            if re.search(r'err|ann', img, re.I) or re.search(r'ошибк|стрелк', t, re.I):
                p = ctx.find_preview(img)
                if p:
                    cands.append((p, mr.get('cap') or t))
        for p, cap in cands:
            im = _open(p)
            if im is None:
                continue
            sec = row.get('sec_new')
            tc = _tc_str(sec) if sec is not None else None
            m = TC_ONE.match(str(cap or ''))
            # «err_frames/v6_err_*.jpg» — голый кадр ошибки, отметку на нём ставит стадия аудита в err_frames_annotated/;
            # когда аннотированной версии нет (YTCH12 v5: папка пуста), стрелку рисуем сами по положению текста —
            # иначе колонка «экран с ошибкой» у факт-ошибки выходит без стрелки. Готовые превью (previews_doc, …_annotated)
            # не трогаем: у них отметка уже есть.
            annotated = 'annotated' in str(p) or str(p).startswith(str(ctx.work / 'previews_doc'))
            if not annotated and sec is not None:
                bbox = _bbox_for(ctx.ocr_lines(p, sec), row.get('title') or what)
                if bbox:
                    _jpeg(_arrow_box(im, bbox, ctx.style), out)
                    return {'file': ctx.rel(out), 'caption': _cap(tc, what), 'kind': 'arrow',
                            'source': {'text': T('fb.vis.src_frame', ver=ver, tc=tc), 'url': None}}
            _jpeg(im, out)
            return {'file': ctx.rel(out), 'caption': _cap(tc or (m.group(1) if m else None), what),
                    'kind': 'arrow' if annotated else 'frame',
                    'source': {'text': T('fb.vis.src_preview', path=ctx.rel(p)), 'url': ctx.drive_url(p)}}
    # (б) доказательство «экран» + положение текста → рамка и стрелка
    ev = row.get('evidence') or {}
    if ev.get('kind') == 'screen' and ev.get('sec') is not None:
        p, sec = ctx.frame_at(ev.get('sec'))
        if p:
            bbox = _bbox_for(ctx.ocr_lines(p, sec), ev.get('text') or '')
            im = _open(p)
            if im is not None and bbox:
                _jpeg(_arrow_box(im, bbox, ctx.style), out)
                return {'file': ctx.rel(out), 'caption': _cap(_tc_str(sec), what), 'kind': 'arrow',
                        'source': {'text': T('fb.vis.src_frame', ver=ver, tc=_tc_str(sec)), 'url': None}}
    # (в) кадр на месте пункта (frame.file; нет — ближайший к sec_new)
    fr = row.get('frame') or {}
    p = ctx.rd / fr['file'] if fr.get('file') else None
    sec = fr.get('sec') if fr.get('sec') is not None else row.get('sec_new')
    if not (p and p.is_file()):
        p, sec2 = ctx.frame_at(row.get('sec_new'))
        sec = sec2 if p else sec
    if p and p.is_file() and sec is not None:
        im = _open(p)
        if im is not None:
            _jpeg(im, out)
            return {'file': ctx.rel(out), 'caption': _cap(_tc_str(sec), what), 'kind': 'frame',
                    'source': {'text': T('fb.vis.src_frame', ver=ver, tc=_tc_str(sec)), 'url': None}}
    # (г) нечего показать
    if row.get('sec_new') is None:
        return {'file': None, 'caption': '', 'kind': 'none', 'why': 'no_tc',
                'source': {'text': T('fb.vis.none_no_tc'), 'url': None}}
    return {'file': None, 'caption': '', 'kind': 'none', 'why': 'no_frame',
            'source': {'text': T('fb.vis.none_no_frame', tc=_tc_str(row['sec_new'])), 'url': None}}


# ── fix: колонка 6 ───────────────────────────────────────────────────────────
def _mockup_for(ctx, row):
    """готовый мокап/превью стадии для пункта → (path, kind, cap) или None. Порядок §9."""
    n = int(row['n'])
    title = str(row.get('title') or '')
    tl = title.lower()
    key = str(row.get('key') or '').lower()
    if row.get('part') == 1:
        m = ctx.manifest().get((n, 'fix'))
        if m and m[0]:
            return m[0], 'preview', m[1]
        for mr in ctx.material_rich_part1(n):
            img = str(mr.get('img') or '')
            t = str(mr.get('t') or '')
            if re.search(r'fix|how|mock|card|lt_', img, re.I) or re.search(r'драфт|исправл|мокап', t, re.I):
                p = ctx.find_preview(img)
                if p:
                    return p, ('preview' if 'previews' in str(p) else 'mockup'), mr.get('cap') or t
    # мокапы графики по смыслу пункта (обе части)
    if row.get('category') == 'structure' and re.search(r'^структура[:\s]', tl) and re.search(r'глав|подглав|титул', tl):
        p = ctx.mock / 'structure_map.png'
        if p.is_file():
            return p, 'mockup', ''
    if re.search(r'карточк\w* глав', tl) or key.startswith('gfx:карточка главы'):
        want = [_norm(q) for q in QUOTE_RE.findall(title)] or [_norm(q) for s in _do_lines(row) for q in QUOTE_RE.findall(s)]
        for p, name in ctx.cards().items():
            if name and any(w and (w == name or w in name or name in w) for w in want):
                return p, 'mockup', ''
    if re.search(r'\bтитул', tl) and not re.search(r'хроно', tl):
        p = ctx.mock / 'card_title.png'
        if p.is_file():
            return p, 'mockup', ''
    if re.search(r'подпис|титр', tl) and re.search(r'куратор|гул[яи]|жимагул|жумагул|панфилов', tl):
        p = ctx.mock / 'lt_gulya.png'
        if p.is_file():
            return p, 'mockup', ''
    if row.get('part') == 2:
        for mr in ctx.material_rich_prev(n):                    # прочие мокапы прошлого ТЗ: кадры прошлого ката — нет,
            img = str(mr.get('img') or '')                      # именные мокапы (главы, титул, подпись) — только по смыслу выше
            if img and not FRAME_NAME.match(img) and re.search(r'\.png$', img, re.I) and not NAMED_MOCK.match(img):
                p = ctx.find_preview(img)
                if p:
                    return p, 'mockup', mr.get('cap') or ''
        p = ctx.tz_plate(n)
        if p:
            return p, 'card', ''
    return None


def _build_fix(ctx, row, fb):
    out = ctx.out / f'p{row["part"]}_{int(row["n"]):03d}_fix.jpg'
    ver, label = ctx.cut, _num_label(row, fb)
    sec = row.get('sec_new')
    fp, fsec = ctx.frame_at(sec)
    tc = _tc_str(fsec) if fp else (_tc_str(sec) if sec is not None else None)
    url = _row_url(row)
    what = _first_do(row)
    # 1. готовый мокап / превью
    mk = _mockup_for(ctx, row)
    if mk:
        p, kind, cap = mk
        base = _open(fp) if fp else None
        im = _over(base, p)
        if im is not None:
            _jpeg(im, out)
            src = T('fb.vis.src_preview' if kind == 'preview' else 'fb.vis.src_mockup', path=ctx.rel(p))
            if base is not None and _open(p).mode in ('RGBA', 'LA'):
                src = T('fb.vis.src_on_frame', src=src, ver=ver, tc=tc)
            if url:
                src = T('fb.vis.src_plus_ref', src=src, url=url.replace('https://', ''))
            return {'file': ctx.rel(out), 'caption': _cap(tc, cap or what, T('fb.vis.cap_fix', what='')),
                    'kind': kind, 'source': {'text': src, 'url': ctx.drive_url(p) or url}}
    # 2. референс по ссылке из текста пункта — картинка не качается
    if url:
        return {'file': None, 'caption': _cap(tc, what, T('fb.vis.cap_fix', what='')), 'kind': 'reference',
                'source': {'text': T('fb.vis.src_reference', url=url.replace('https://', '')), 'url': url}}
    # 3. наш драфт
    cat = row.get('category')
    frame = _open(fp) if fp else None
    if cat == 'graphics':
        text = _quoted(row)
        im = _lower_third(frame, text, ctx.style) if frame is not None else _title_card(text, ctx.style)
    elif cat == 'cut':
        txt, sub = _cut_plan(row)
        im = _cut_band(frame if frame is not None else _canvas(ctx.style), txt, sub, ctx.style)
    else:
        im = _how_card(row.get('title') or '', _do_lines(row), ctx.style)
    _jpeg(im, out)
    src = T('fb.vis.src_draft', ver=ver, tc=tc, label=label) if (frame is not None and cat in ('graphics', 'cut')) \
        else T('fb.vis.src_draft_noframe', label=label)
    return {'file': ctx.rel(out), 'caption': _cap(tc, what, T('fb.vis.cap_fix', what='')), 'kind': 'draft',
            'source': {'text': src, 'url': None}}


# ── сборка ───────────────────────────────────────────────────────────────────
def rows_wanted(fb):
    return [r for p in ('part1', 'part2') for r in (fb.get(p) or [])
            if r.get('bucket') in BUCKETS_FULL and not r.get('dup_of') and r.get('n') is not None]


def _keep(entry, review_dir):
    """--only-missing: запись остаётся, если её файлы на месте, а err=none — не из-за отсутствующего кадра"""
    if not isinstance(entry, dict) or 'fix' not in entry or 'err' not in entry:
        return False
    for k in ('err', 'fix'):
        e = entry[k] or {}
        if e.get('file') and not (Path(review_dir) / e['file']).is_file():     # абсолютный путь (--out вне 05_Review) остаётся собой
            return False
    e = entry['err'] or {}
    return not (e.get('kind') == 'none' and e.get('why') == 'no_frame')


def _write_json_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)


def build(fb, review_dir, out_dir=None, only_missing=False):
    """картинки колонок 5–6 для всех полных строк → index (и index.json в out_dir). Пути в индексе — от 05_Review."""
    review_dir = Path(review_dir)
    out_dir = Path(out_dir) if out_dir else review_dir / 'work' / str(fb.get('cut_version') or '') / 'feedback_visuals'
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = Ctx(fb, review_dir, out_dir)
    idx_path = out_dir / 'index.json'
    old = {}
    if only_missing and idx_path.is_file():
        try:
            old = (json.loads(idx_path.read_text(encoding='utf-8')) or {}).get('rows') or {}
        except ValueError:
            old = {}
    rows = {}
    for r in rows_wanted(fb):
        key = f'{r["part"]}:{r["n"]}'
        if only_missing and _keep(old.get(key), review_dir):
            rows[key] = old[key]
            continue
        rows[key] = {'err': _build_err(ctx, r), 'fix': _build_fix(ctx, r, fb)}
    index = {'schema': SCHEMA, 'built_at': fb.get('built_at') or '', 'code': fb.get('code'),
             'cut_version': ctx.cut, 'rows': rows}
    _write_json_atomic(idx_path, index)
    return index


def report(index, out_dir):
    """сводка для чата: сколько строк, err/fix по видам, без err и почему, размер папки, примеры"""
    from collections import Counter
    rows = index.get('rows') or {}
    ek, fk, why = Counter(), Counter(), Counter()
    for v in rows.values():
        ek[(v['err'] or {}).get('kind')] += 1
        fk[(v['fix'] or {}).get('kind')] += 1
        if (v['err'] or {}).get('kind') == 'none':
            why[(v['err'] or {}).get('why')] += 1
    nofix = [k for k, v in rows.items() if not (v.get('fix') or {}).get('kind')]
    nosrc = [k for k, v in rows.items() if not ((v.get('fix') or {}).get('source') or {}).get('text')]
    total = sum(p.stat().st_size for p in Path(out_dir).glob('*.jpg'))
    lines = [f'строк: {len(rows)}', f'err по kind: {dict(ek)}', f'fix по kind: {dict(fk)}',
             f'без err: {ek.get("none", 0)} (причины: {dict(why)})', f'без fix: {len(nofix)} {nofix}',
             f'fix без source.text: {len(nosrc)} {nosrc}',
             f'папка: {total / 1024 / 1024:.1f} МБ · {len(list(Path(out_dir).glob("*.jpg")))} файлов']
    seen, ex = set(), []
    for k, v in rows.items():
        kk = ((v['err'] or {}).get('kind'), (v['fix'] or {}).get('kind'))
        if kk not in seen and len(ex) < 6:
            seen.add(kk)
            ex.append(f'{k}: ' + json.dumps(v, ensure_ascii=False))
    refs = [f'{k}: {(v["fix"] or {}).get("source", {}).get("url")}' for k, v in rows.items()
            if ((v['fix'] or {}).get('source') or {}).get('url')]
    lines += ['примеры:'] + ex + [f'референс-URL у строк ({len(refs)}):'] + refs
    return '\n'.join(lines)


# ── самотест: синтетика в tmp, офлайн ────────────────────────────────────────
def _synthetic(root):
    """мини-05_Review: кадры, экран с положением текста, мокапы, плашка ТЗ, material_rich, модель"""
    root = Path(root)
    hires = root / 'work' / 'v9' / 'hires'
    hires.mkdir(parents=True)
    (root / 'work' / 'v9' / 'err_frames').mkdir()
    (root / 'work' / 'v9' / 'previews_doc').mkdir()
    (root / 'mockups' / 'src').mkdir(parents=True)
    (root / 'mockups' / 'tz').mkdir()
    (root / 'pravki').mkdir()
    (root / 'v8_review').mkdir()

    def frame(path, w=1280, h=720, text=None, at=None):
        im = Image.new('RGB', (w, h), (40, 70, 110))
        d = ImageDraw.Draw(im)
        for i in range(0, w, 80):
            d.line([(i, 0), (i, h)], fill=(60, 90, 130), width=2)
        if text:
            d.rectangle([at[0] * w, at[1] * h, (at[0] + at[2]) * w, (at[1] + at[3]) * h], fill=(230, 230, 230))
        im.save(path, 'JPEG', quality=85)

    for s in (11, 76, 100, 200, 300):                            # h0012, h0077, h0101, h0201, h0301
        frame(hires / f'h{s + 1:04d}.jpg', text='X' if s == 76 else None, at=(0.3, 0.7, 0.4, 0.12))
    frame(hires / 'h0501.jpg', w=640, h=360)                     # маленький кадр — не растягивать
    frame(root / 'work' / 'v9' / 'err_frames' / 'v6_err_s001.jpg')
    (root / 'work' / 'v9' / 'screens_v6.json').write_text(json.dumps([
        {'id': 's002', 't0': '75', 't1': '78', 'best_frame': 'h0077.jpg',
         'lines_best': [{'t': 'ДЕТСТВО СВЕТЫ', 'c': 1.0, 'x': 0.3, 'y': 0.7, 'bw': 0.4, 'bh': 0.12}]},
        # экран на месте факт-ошибки Части 1 (sec_new=100): положение титра известно → стрелка на голом кадре err_frames
        {'id': 's003', 't0': '99', 't1': '102', 'best_frame': 'h0101.jpg',
         'lines_best': [{'t': 'ЖУМАГУЛ ПАНФИЛОВА', 'c': 0.5, 'x': 0.03, 'y': 0.82, 'bw': 0.65, 'bh': 0.09}]}]), encoding='utf-8')
    Image.new('RGB', (1920, 1080), (0, 0, 0)).save(root / 'mockups' / 'card_01.png')
    (root / 'mockups' / 'src' / 'card_01.html').write_text(
        '<!doctype html><style>x{}</style><body><div><div>ЗАМУЖ,</div><div>ЧТОБЫ</div><div>ВЫПУСТИЛИ</div></div>'
        '<div style="x">DRAFT · перерисовать</div></body>', encoding='utf-8')
    Image.new('RGB', (1920, 1080), (0, 0, 0)).save(root / 'mockups' / 'card_title.png')
    lt = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
    ImageDraw.Draw(lt).rectangle([100, 800, 1200, 1000], fill=(0, 0, 0, 220))
    lt.save(root / 'mockups' / 'lt_gulya.png')
    lt.save(root / 'mockups' / 'fix_tz01.png')
    lt.save(root / 'mockups' / 'tz' / 'tz_07.png')
    (root / 'v8_review' / 'tz_index.json').write_text(json.dumps({'ТЗ-07': '/nowhere/tz_07.png'}), encoding='utf-8')
    (root / 'pravki' / 'pravki_v2.json').write_text(json.dumps({'all': [
        {'material_rich': [{'t': 'Кадр с отметкой ошибки (стрелка)', 'img': 'v6_err_s001.jpg'},
                           {'t': 'Драфт исправленного титра', 'img': 'fix_tz01.png'}]}, {}, {}]}), encoding='utf-8')
    (root / 'v8_review' / 'pravki_v8.json').write_text(json.dumps({'all': [{}] * 6 + [
        {'material_rich': [{'img': 'f0100.jpg', 'cap': '1:40 · кадр'}]}]}), encoding='utf-8')

    def row(part, n, **kw):
        r = {'part': part, 'n': n, 'label': f'ТЗ-{n:02d}', 'key': '', 'title': 't', 'category': 'insert', 'severity': 'must',
             'sensitive': False, 'blocker': False, 'sec_old': None, 'tc_old': '', 'sec_new': None, 'tc_new': '', 'err': 0.0,
             'how': 'none', 'parts': {'now': [], 'do': [], 'where': []}, 'more': 0, 'status': 'open', 'status_by': 'code',
             'evidence': None, 'checks': [], 'bucket': 'open', 'dup_of': None, 'frame': None, 'typo': [], 'agent_note': ''}
        r.update(kw)
        if r['sec_new'] is not None and not r['tc_new']:
            r['tc_new'] = _tc_str(r['sec_new'])
        if r['sec_new'] is not None and r['frame'] is None:
            r['frame'] = {'file': f'work/v9/hires/h{int(r["sec_new"]) + 1:04d}.jpg', 'sec': int(r['sec_new']), 'what': 'кадр ката v9'}
        return r

    fb = {'schema': 'feedback-v1', 'code': 'YTXX01', 'cut_version': 'v9', 'prev_cut_version': 'v8', 'built_at': '2026-01-01 00:00',
          'prev_file': 'v8_review/pravki_v8.json', 'duration_sec': 600,
          'part1': [
              row(1, 1, bucket='new', category='graphics', title='«ЖУМАГУЛ ПАНФИЛОВА»', sec_new=100.0,
                  parts={'now': ['«ЖУМАГУЛ ПАНФИЛОВА» — факт-ошибка'], 'do': ['Заменить титр на «ЖИМАГУЛ ПАНФИЛОВА»'], 'where': ['1:40']}),
              row(1, 2, bucket='new', category='structure', title='Структура: предложенные главы',
                  parts={'now': ['три правила нарушены'], 'do': ['Поставить карточки глав по списку'], 'where': []}),
              row(1, 3, bucket='new', category='graphics', title='Титр куратора фонда: везде «ЖИМАГУЛ ПАНФИЛОВА»', sec_new=11.0,
                  parts={'now': ['Верное написание — «Жимагул» (burodd.ru/team/zhimagul-panfilova)'], 'do': ['Привести титр к одному написанию'], 'where': ['0:11']}),
          ],
          'part2': [
              row(2, 4, bucket='block', category='graphics', title='карточка главы: «Замуж, чтобы выпустили»', sec_new=76.0,
                  evidence={'kind': 'screen', 'tc': '1:16', 'sec': 76, 'text': 'стоит карточка главы: «ДЕТСТВО СВЕТЫ»'},
                  parts={'now': ['Стоит не та карточка.'], 'do': ['Карточка главы: «Замуж, чтобы выпустили»'], 'where': ['1:16']}),
              row(2, 5, bucket='open', category='cut', title='Хвост после реплики', sec_new=200.0,
                  evidence={'kind': 'speech', 'tc': '3:20', 'sec': 200, 'text': 'хвост по-прежнему звучит: «я не дам ничего»'},
                  parts={'now': ['Висит хвост ≈3:20–3:22.'], 'do': ['Вырезать 3:20–3:22, паузу схлопнуть'], 'where': ['3:20–3:22']}),
              row(2, 6, bucket='open', category='structure', title='Нет бита настоящего после тизера', sec_new=300.0,
                  evidence={'kind': 'speech', 'tc': '5:00', 'sec': 300, 'text': 'моста настоящего нет'},
                  parts={'now': ['После тизера сразу детство.'], 'do': ['Между тизером и главой вставить мост настоящего 30–45 с',
                                                                        'Кадр пряжи перенести сюда', 'Карточка «кто она сегодня»'], 'where': ['5:00']}),
              row(2, 7, bucket='blur', category='insert', title='Фото детей без одежды: кроп или блюр', sec_new=500.0,
                  parts={'now': ['Разворот с голым мальчиком'], 'do': ['Кадрировать на соседнее фото или заблюрить'], 'where': ['8:20–8:50']}),
              row(2, 8, bucket='closed', category='graphics', title='титул: «Одна с ребёнком»', sec_new=999.0,
                  evidence={'kind': 'screen', 'tc': '16:39', 'sec': 999, 'text': 'титул стоит: «ОДНА С РЕБЁНКОМ»'},
                  parts={'now': ['Графики нет.'], 'do': ['Титул: «Одна с ребёнком»'], 'where': ['16:39']}),
              row(2, 9, bucket='open', category='check', title='Сверить фамилию по сайту фонда', sec_new=11.0,
                  parts={'now': ['Фамилия расходится'], 'do': ['Сверить по burodd.ru/team'], 'where': ['0:11']}),
              row(2, 10, bucket='open', category='graphics', title='титр-сумма: «Ремонт котла — 40 000 ₽»', sec_new=999.0,
                  evidence={'kind': 'screen', 'tc': '16:39', 'sec': 999, 'text': 'на экранах нового ката такого текста нет: «Ремонт котла»'},
                  parts={'now': ['Графики нет.'], 'do': ['титр-сумма: «Ремонт котла — 40 000 ₽ / со слов Светланы»'], 'where': ['16:39']}),
              row(2, 11, bucket='open', category='cut', title='дубль', sec_new=200.0, dup_of=3),
              row(2, 12, bucket='fund', category='fund', title='фонд', sec_new=200.0),
              row(2, 13, bucket='open', category='graphics', title='подпись: «Гуля / куратор фонда»', sec_new=76.0,
                  parts={'now': ['Подписи нет'], 'do': ['Подпись куратора при первом появлении'], 'where': ['1:16']}),
          ]}
    return fb


def selftest():
    import filecmp
    import shutil
    fails = []

    def ok(name, cond, msg=''):
        print(('  ok  ' if cond else '  FAIL') + ' ' + name + (f' — {msg}' if msg and not cond else ''))
        if not cond:
            fails.append(name)

    tmp = Path(tempfile.mkdtemp(prefix='fbvis_'))
    try:
        fb = _synthetic(tmp)
        out = tmp / 'work' / 'v9' / 'feedback_visuals'
        idx = build(fb, tmp, out)
        rows = idx['rows']
        ok('индекс: схема и built_at из модели', idx['schema'] == SCHEMA and idx['built_at'] == fb['built_at'])
        ok('строки: полные без dup_of/fund', set(rows) == {'1:1', '1:2', '1:3', '2:4', '2:5', '2:6', '2:7', '2:8', '2:9', '2:10', '2:13'})
        ok('fix у каждой строки', all((v['fix'] or {}).get('kind') for v in rows.values()))
        ok('source.text у каждого fix', all(((v['fix'] or {}).get('source') or {}).get('text') for v in rows.values()))
        # голый кадр из err_frames/ (не annotated) + известное положение текста → стрелку рисуем сами; источник — кадр ката
        ok('Часть 1: err = кадр ошибки, стрелка дорисована по положению текста',
           rows['1:1']['err']['kind'] == 'arrow' and 'v6_err_s001' not in rows['1:1']['err']['source']['text'])
        ok('Часть 1: fix = мокап material_rich', rows['1:1']['fix']['kind'] == 'mockup' and 'fix_tz01' in rows['1:1']['fix']['source']['text'])
        ok('без времени → err none/no_tc', rows['1:2']['err']['kind'] == 'none' and rows['1:2']['err'].get('why') == 'no_tc')
        ok('без времени → fix драфт-карточка', rows['1:2']['fix']['kind'] == 'draft' and rows['1:2']['fix']['caption'].startswith('сводно · '))
        ok('подпись куратора → lt_gulya + референс-URL', rows['1:3']['fix']['kind'] == 'mockup' and 'lt_gulya' in rows['1:3']['fix']['source']['text']
           and rows['1:3']['fix']['source']['url'] == 'https://burodd.ru/team/zhimagul-panfilova')
        ok('экран + положение текста → стрелка', rows['2:4']['err']['kind'] == 'arrow')
        e = rows['2:4']['err']
        if e['file']:
            im = Image.open(tmp / e['file']).convert('RGB')
            W, H = im.size
            pad = max(6, round(W / 120)) + max(3, round(W / 250)) + 2                 # рамка лежит в кольце вокруг bbox
            x0, y0, x1, y1 = int(0.3 * W) - pad, int(0.7 * H) - pad, int(0.7 * W) + pad, int(0.82 * H) + pad
            reds = sum(1 for x in range(max(0, x0), min(W, x1)) for y in range(max(0, y0), min(H, y1))
                       if not (int(0.3 * W) <= x <= int(0.7 * W) and int(0.7 * H) <= y <= int(0.82 * H))
                       and (lambda p: p[0] > 140 and p[1] < 100 and p[2] < 100)(im.getpixel((x, y))))
            ok('стрелка/рамка: в кольце вокруг текста есть красное', reds > 200, f'reds={reds}')
            inner = sum(1 for x in range(int(0.3 * W) + 2, int(0.7 * W) - 2, 3) for y in range(int(0.7 * H) + 2, int(0.82 * H) - 2, 3)
                        if (lambda p: p[0] > 140 and p[1] < 100 and p[2] < 100)(im.getpixel((x, y))))
            ok('стрелка/рамка: сам текст не перекрыт красным', inner == 0, f'inner={inner}')
        # рамка у самого края кадра: координаты не выходят за кадр, стрелка идёт с свободной стороны
        corner = _arrow_box(Image.new('RGB', (1280, 720), (40, 70, 110)), (0.0, 0.0, 0.2, 0.1), STYLE_DEFAULT)
        cw, chh = corner.size
        reds_c = sum(1 for x in range(0, int(0.2 * cw) + 40, 2) for y in range(0, int(0.1 * chh) + 40, 2)
                     if (lambda p: p[0] > 140 and p[1] < 100 and p[2] < 100)(corner.getpixel((x, y))))
        ok('рамка в углу кадра: без исключения и с красным у угла', reds_c > 100, f'reds={reds_c}')
        ok('карточка главы по названию → card_01', rows['2:4']['fix']['kind'] == 'mockup' and 'card_01' in rows['2:4']['fix']['source']['text'])
        ok('речь → кадр', rows['2:5']['err']['kind'] == 'frame')
        ok('cut → драфт с полосой', rows['2:5']['fix']['kind'] == 'draft' and 'наш драфт' in rows['2:5']['fix']['source']['text'])
        ok('structure → карточка КАК НАДО', rows['2:6']['fix']['kind'] == 'draft')
        ok('плашка ТЗ прошлой версии → card', rows['2:7']['fix']['kind'] == 'card' and 'tz_07' in rows['2:7']['fix']['source']['text'])
        ok('нет кадра → err none/no_frame, без исключения', rows['2:8']['err']['kind'] == 'none' and rows['2:8']['err'].get('why') == 'no_frame')
        ok('титул → card_title', rows['2:8']['fix']['kind'] == 'mockup' and 'card_title' in rows['2:8']['fix']['source']['text'])
        ok('референс по URL из текста пункта', rows['2:9']['fix']['kind'] == 'reference' and rows['2:9']['fix']['file'] is None
           and rows['2:9']['fix']['source']['url'] == 'https://burodd.ru/team')
        ok('«такого текста нет» без совпадений → не стрелка', rows['2:10']['err']['kind'] != 'arrow')
        ok('graphics без кадра → титульная карточка (draft)', rows['2:10']['fix']['kind'] == 'draft')
        ok('Часть 2: подпись куратора → lt_gulya поверх кадра', rows['2:13']['fix']['kind'] == 'mockup'
           and 'lt_gulya' in rows['2:13']['fix']['source']['text'] and 'поверх кадра' in rows['2:13']['fix']['source']['text'])
        # подписи по CAP_RE, размер и ширина в лимите, маленький кадр не растянут
        caps = [(k, e['caption']) for k, v in rows.items() for e in (v['err'], v['fix']) if e.get('file') or e.get('kind') == 'reference']
        ok('подписи по CAP_RE', all(CAP_RE.match(c) for _, c in caps), str([c for _, c in caps if not CAP_RE.match(c)][:3]))
        ok('в подписях нет таймкода внутри «что видно»', all(len(TCR.findall(c)) <= 1 for _, c in caps))
        files = sorted(out.glob('*.jpg'))
        ok('файлы: ширина ≤1000 и ≤160 КБ', all(Image.open(f).width <= MAX_W and f.stat().st_size <= MAX_KB * 1024 for f in files))
        small = tmp / rows['2:7']['err']['file']
        ok('маленький кадр не растянут', Image.open(small).width == 640)
        # детерминизм: второй прогон → побайтно те же файлы
        out2 = tmp / 'work' / 'v9' / 'fv2'
        build(fb, tmp, out2)
        same = all(filecmp.cmp(f, out2 / f.name, shallow=False) for f in files)
        ok('детерминизм: два прогона побайтно равны', same and len(files) == len(list(out2.glob('*.jpg'))))
        # only-missing: существующие не перерисовываются, отсутствующий кадр — перестраивается
        stamp = {f.name: f.stat().st_mtime_ns for f in files}
        (out / 'p2_006_fix.jpg').unlink()
        frame_path = tmp / 'work' / 'v9' / 'hires' / 'h1000.jpg'
        shutil.copy(tmp / 'work' / 'v9' / 'hires' / 'h0201.jpg', frame_path)
        idx2 = build(fb, tmp, out, only_missing=True)
        changed = [n for n, t in stamp.items() if (out / n).stat().st_mtime_ns != t]
        rebuilt = {'p2_006_fix.jpg', 'p2_008_fix.jpg', 'p2_010_fix.jpg'}         # удалённый + строки с появившимся кадром
        ok('only-missing: нетронутые записи не перерисованы', set(changed) <= rebuilt, str(changed))
        ok('only-missing: пропавший файл восстановлен', (out / 'p2_006_fix.jpg').is_file())
        ok('only-missing: появившийся кадр подхвачен', idx2['rows']['2:8']['err']['kind'] != 'none')
        ok('индекс записан', (out / 'index.json').is_file() and not (out / 'index.json.tmp').exists())
        # _shorten: без обрыва слова и многоточий
        s = _shorten('фонд впервые звучит на 11:16, правило канала — не раньше 34-й минуты, и это очень длинная фраза для проверки', 70)
        ok('_shorten: ≤70, без таймкода и многоточия', len(s) <= 70 and '11:16' not in s and '…' not in s and not s.endswith(' '))
        s = _shorten('Продлить выход дубля на ≈9 с, до «…две недели обучали на пекаря и на кондитера»', 36)
        ok('_shorten: обрыв не на предлоге, «9 с» — секунды остаются', not re.search(r'\s(до|и|на|от|→)$', s) and s.endswith('9 с'), repr(s))
        s = _shorten('Вырезать; склейка «…чтобы оплатить коммуналку.» → «Я говорю»', 44)
        ok('_shorten: обрыв не на стрелке', not s.endswith('→'), repr(s))
        ok('_shorten: скобка без пробела после вырезанного таймкода', '( ' not in _shorten('«грязи» (8:16 «и я тут»)'))
        s = _shorten('Плашка (атрибуция няни): «Няню оплачивал фонд «Бюро Добрых Дел»»', 50)
        ok('_shorten: вложенная цитата не остаётся открытой', s.count('«') == s.count('»'), repr(s))
        ok('подписи: кавычки «» парные', all(c.count('«') == c.count('»') for _, c in caps), str([c for _, c in caps if c.count('«') != c.count('»')][:2]))
        # полоса «вырезать» — только когда ✅ сама начинается с глагола резки; «сжать/оставить/дать паузу» — не переводим
        cut_row = lambda *do: {'parts': {'do': list(do), 'where': ['1:00–1:10']}, 'tc_new': '1:00', 'title': 'x'}
        ok('_cut_plan: «Вырезать 2:00–2:05» → полоса вырезать', _cut_plan(cut_row('1. Вырезать ≈2:00–2:05, от «а» до «б».'))[0] == T('fb.vis.draft_cut', rng='2:00–2:05'))
        ok('_cut_plan: «Сжать 2:35–3:29 → 30 с» не становится «вырезать»', not _cut_plan(cut_row('Сжать до ~9 мин: ферма 2:35–3:29 → 30 с'))[0].startswith('вырезать'))
        ok('_cut_plan: «Оставить здесь …» не становится «вырезать»', not _cut_plan(cut_row('Оставить здесь: повтор 10:43–11:10 убрать позже'))[0].startswith('вырезать'))
        ok('_cut_plan: «дать 2–3 с без речи» не становится «вырезать»', not _cut_plan(cut_row('После «…беременности» (17:54) дать 2–3 с без речи'))[0].startswith('вырезать'))
        # рамка по тексту: обрывок OCR «на» не считается совпадением с цитатой доказательства
        frag = [{'t': 'на', 'x': 0.1, 'y': 0.1, 'bw': 0.05, 'bh': 0.05}, {'t': 'ОДНА', 'x': 0.4, 'y': 0.3, 'bw': 0.2, 'bh': 0.1}]
        ok('_bbox_for: короткий обрывок OCR не даёт ложной рамки', _bbox_for(frag, 'нет карточки «кто она сегодня»') is None)
        bb = _bbox_for(frag, 'титул стоит: «ОДНА С РЕБЁНКОМ»')
        ok('_bbox_for: цитата «Одна с ребёнком» находит строку', bb is not None and [round(v, 3) for v in bb] == [0.4, 0.3, 0.2, 0.1], str(bb))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('SELFTEST OK' if not fails else f'SELFTEST FAIL: {fails}')
    return 0 if not fails else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--fb', help='work/{cut}/feedback.json')
    ap.add_argument('--review-dir', help='папка 05_Review проекта')
    ap.add_argument('--out', help='папка картинок (по умолчанию work/{cut}/feedback_visuals)')
    ap.add_argument('--only-missing', action='store_true', help='дописать только отсутствующие/пустые записи')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.fb or not a.review_dir:
        ap.error('нужны --fb и --review-dir')
    fb = json.loads(Path(a.fb).read_text(encoding='utf-8'))
    out = Path(a.out) if a.out else Path(a.review_dir) / 'work' / str(fb.get('cut_version') or '') / 'feedback_visuals'
    idx = build(fb, a.review_dir, out, only_missing=a.only_missing)
    print(f'index: {out / "index.json"}')
    print(report(idx, out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
