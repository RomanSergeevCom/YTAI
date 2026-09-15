#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pravki_lib — общий загрузчик правок (ТЗ) для продюсерских поверхностей стадии 0509.

Им пользуются phone_brief.py и producer_page.py. Ничего не пишет на диск.

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'stages'))
    from _bootstrap import P, W6, M, MOCK
    from pravki_lib import load_pravki, counts, verdict_lines, load_summary, jpeg_data_uri, favicon_href

load_pravki(P, W6, M, MOCK) → (список ТЗ, путь файла). Каждая запись — dict из pravki.json (§5 contracts.md)
плюс служебные поля:
  num        «ТЗ-NN» — из записи или по индексу в `all` (снятые Романом НЕ сдвигают номера, как в doc_tab_tz)
  class      typo|grammar|fact|currency|language|mismatch|design|structure|… — из записи → из
             work/{cut}/audit_v6.json (annotations[tz].kind) → из префикса заголовка («ОПЕЧАТКА: …»)
  severity   high|medium|low — из записи → максимум по подтверждённым находкам экрана ТЗ
             (audit_findings_v6.json) → ''
  _sec, _t1  секунды начала/конца (timeline_*_sec → tc_range → v1_tc)
  _screen    id экрана (s031): из аннотации или имени кадра v6_err_sNNN.jpg в material_rich
  _frame     Path лучшего кадра ТЗ: err_frames_annotated → картинка из material_rich → hires/hNNNN.jpg
             (кадр N = секунда N−1) → None
  _do        строки «✅ СДЕЛАТЬ» (parts.do → разбор поля nado)
  _rejected  status == rejected
  _sensitive bool (sensitive.flag или sensitive == true)
  _must      обязательная: не снята и (severity high или класс fact/typo/mismatch)
  _title     заголовок без префикса класса («ФАКТ-ОШИБКА: «…»» → ««…»»)

Файл правок: карточка `pravki_file` → pravki/pravki.json → pravki/pravki_v2.json (первый существующий).
"""
import base64
import io
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

try:
    import i18n  # noqa: E402
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import i18n  # noqa: E402

KIND_RU = {'typo': 'опечатка', 'grammar': 'грамматика', 'fact': 'факт-ошибка',
           'currency': 'формат валюты/числа', 'language': 'английский без перевода',
           'mismatch': 'экран ≠ озвучка', 'design': 'вёрстка', 'structure': 'структура',
           'foreign_trace': 'чужой след', 'other': 'правка', '': 'правка'}
CAT_RU = {'graphics': 'графика', 'cut': 'вырезать', 'insert': 'вставить', 'structure': 'структура',
          'color': 'обработка', 'check': 'разобрано'}
CAT_ICON = {'graphics': '🎨', 'cut': '✂️', 'insert': '➕', 'structure': '🃏', 'color': '🔧', 'check': '✅'}
MUST_CLASSES = ('fact', 'typo', 'mismatch')
SEV_RANK = {'high': 0, 'medium': 1, 'low': 2}
# префикс заголовка ТЗ → класс (когда аудит-файлов рядом нет)
TITLE_CLASS = [('ОПЕЧАТ', 'typo'), ('ФАКТ', 'fact'), ('ГРАММАТ', 'grammar'), ('ВАЛЮТ', 'currency'),
               ('ЧИСЛ', 'currency'), ('АНГЛ', 'language'), ('ПЕРЕВОД', 'language'), ('ОЗВУЧ', 'mismatch'),
               ('ВЁРСТ', 'design'), ('ВЕРСТ', 'design'), ('СТРУКТУР', 'structure'), ('ВЫРЕЗ', 'cut')]
# EN-заголовки (s8/s10 на английском канале: «TYPO: “…”», «SCREEN ≠ VOICE: …») — проверяются ПОСЛЕ русских,
# целым словом; значения — из core.kind_up.* (en)
_EN_KINDS = ('typo', 'grammar', 'fact', 'currency', 'language', 'mismatch', 'foreign_trace', 'structure',
             'check_source', 'design')
EN_KIND_UP = {i18n.TL('en', f'core.kind_up.{k}'): k for k in _EN_KINDS}
TITLE_CLASS_EN = list(EN_KIND_UP.items()) + [('MISMATCH', 'mismatch'), ('LAYOUT', 'design'), ('CUT', 'cut')]
# метка блока «✅ СДЕЛАТЬ» в поле nado: русская и английская (core.lbl_do)
DO_LABELS = (i18n.TL('ru', 'core.lbl_do'), i18n.TL('en', 'core.lbl_do'))
# маркеры блоков в поле nado — на них заканчивается блок «✅ СДЕЛАТЬ»
NADO_MARKERS = ('❌', '📍', '📚', '🎞', '🗺', '⏱', '📌', '🔗', '🎬', '📎', '❓')


# ── таймкоды ────────────────────────────────────────────────────────────────
def tc_sec(s):
    """'0:10' / '1:02:03' / '2:46.0–2:48.6' / '~3:05' → секунды первого таймкода (float) или None."""
    if s in (None, ''):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?', str(s))
    if not m:
        try:
            return float(str(s).strip())
        except ValueError:
            return None
    h_or_m, mm, ss, frac = m.groups()
    if ss is not None:
        sec = int(h_or_m) * 3600 + int(mm) * 60 + int(ss)
    else:
        sec = int(h_or_m) * 60 + int(mm)
    if frac:
        sec += float('0.' + frac)
    return float(sec)


def sec_tc(sec):
    """секунды → 'M:SS' (часы не показываем — каты короче часа)."""
    if sec is None:
        return ''
    t = int(round(float(sec)))
    return f'{t // 60}:{t % 60:02d}'


# ── файл правок ──────────────────────────────────────────────────────────────
def pravki_path(M, P=None):
    names = []
    if P is not None and P.get('pravki_file'):
        names.append(str(P.get('pravki_file')))
    names += ['pravki.json', 'pravki_v2.json']
    for n in names:
        p = Path(n) if Path(n).is_absolute() else Path(M) / n
        if p.exists():
            return p
    raise SystemExit(f'Нет файла правок в {M} (искал: {", ".join(names)}). '
                     'Сначала стадия apply (s8_apply_audit) / s10_format_tz.')


def _class_from_title(title):
    head = (title or '').split(':', 1)[0].upper()
    if ':' not in (title or ''):
        return ''
    for key, cls in TITLE_CLASS:
        if key in head:
            return cls
    for key, cls in TITLE_CLASS_EN:
        if re.search(r'(?<![A-Z])' + re.escape(key) + r'(?![A-Z])', head):
            return cls
    return ''


def _strip_class_prefix(title):
    t = (title or '').strip()
    m = re.match(r'^([А-ЯЁA-Z0-9 /\-\.]{3,40}):\s*(.+)$', t)
    if not m:                                   # EN-префиксы вне класса знаков выше («SCREEN ≠ VOICE: …»)
        for key in EN_KIND_UP:
            if t.startswith(key + ':'):
                return t[len(key) + 1:].strip()
    return m.group(2).strip() if m else t


def _screen_from_imgs(p):
    for m in p.get('material_rich') or []:
        mm = re.search(r'(s\d{3})', str(m.get('img', '')))
        if mm:
            return mm.group(1)
    return ''


def _span(p, an):
    t0 = p.get('timeline_in_sec')
    t1 = p.get('timeline_out_sec')
    if t0 is not None:
        return float(t0), float(t1) if t1 is not None else float(t0)
    rng = str(p.get('tc_range') or '')
    if rng:
        parts = re.split(r'\s*[–-]\s*', rng)
        a = tc_sec(parts[0])
        b = tc_sec(parts[1]) if len(parts) > 1 else a
        if a is not None:
            return a, b if b is not None else a
    a = tc_sec(p.get('v1_tc'))
    if a is None and an:
        a = float(an.get('t0', 0))
        return a, float(an.get('t1', a))
    return (a if a is not None else 0.0), (a if a is not None else 0.0)


def _find_img(name, dirs):
    if not name:
        return None
    for d in dirs:
        if d and (Path(d) / name).exists():
            return Path(d) / name
    return None


def frame_for(p, W6, MOCK=None):
    """Лучший кадр для ТЗ: аннотированный кадр аудита → картинка из material_rich → hires по секунде."""
    W6 = Path(W6)
    sid = p.get('_screen') or ''
    dirs = [W6 / 'err_frames_annotated', W6 / 'err_frames', W6 / 'previews_doc', W6 / 'thumbs', MOCK]
    if sid:
        f = W6 / 'err_frames_annotated' / f'v6_err_{sid}.jpg'
        if f.exists():
            return f
    for m in p.get('material_rich') or []:
        f = _find_img(str(m.get('img', '')), dirs)
        if f:
            return f
    sec = p.get('_sec')
    if sec is not None:
        f = W6 / 'hires' / f'h{int(sec) + 1:04d}.jpg'
        if f.exists():
            return f
    return None


def do_lines(p):
    """Строки «✅ СДЕЛАТЬ»: parts.do (строки или {h, items}) → иначе разбор nado."""
    out = []
    do = ((p.get('parts') or {}).get('do')) or []
    for d in do:
        if isinstance(d, dict):
            if d.get('h'):
                out.append(str(d['h']).strip())
            out += [str(x).strip() for x in (d.get('items') or []) if str(x).strip()]
        elif str(d).strip():
            out.append(str(d).strip())
    if out:
        return out
    nado = str(p.get('nado') or '')
    lbl, i = DO_LABELS[0], nado.find(DO_LABELS[0])
    if i < 0:
        lbl, i = DO_LABELS[1], nado.find(DO_LABELS[1])
    if i < 0:
        return out
    block = nado[i + len(lbl):]
    for ln in block.split('\n'):
        s = ln.strip().lstrip('·').strip()
        if not s:
            continue
        if s.startswith(NADO_MARKERS):
            break
        out.append(s)
    return out


def load_pravki(P, W6, M, MOCK=None):
    """→ (pravki: list[dict], path). Класс/severity/кадр подтягиваются из аудита work/{cut}/."""
    W6, M = Path(W6), Path(M)
    path = pravki_path(M, P)
    raw = json.loads(path.read_text(encoding='utf-8'))
    allp = raw['all'] if isinstance(raw, dict) else raw
    ann = {}
    a = W6 / 'audit_v6.json'
    if a.exists():
        try:
            for x in json.loads(a.read_text(encoding='utf-8')).get('annotations', []):
                ann[x.get('tz')] = x
        except Exception:
            pass
    sev_by_screen = {}
    af = W6 / 'audit_findings_v6.json'
    if af.exists():
        try:
            for f in json.loads(af.read_text(encoding='utf-8')).get('confirmed', []):
                if not f.get('confirmed', True):
                    continue
                sid, sev = f.get('screen_id'), f.get('severity', 'medium')
                if sid and SEV_RANK.get(sev, 9) < SEV_RANK.get(sev_by_screen.get(sid, ''), 9):
                    sev_by_screen[sid] = sev
        except Exception:
            pass
    out = []
    for i, p0 in enumerate(allp):
        p = dict(p0)
        p['num'] = p.get('num') or f'ТЗ-{i + 1:02d}'
        p['_rejected'] = p.get('status') == 'rejected'
        an = ann.get(p['num']) or {}
        sid = an.get('screen_id') or _screen_from_imgs(p)
        p['_screen'] = sid
        p['class'] = p.get('class') or an.get('kind') or _class_from_title(p.get('title', '')) or ''
        p['severity'] = p.get('severity') or sev_by_screen.get(sid, '')
        p['_sec'], p['_t1'] = _span(p, an)
        p['_frame'] = frame_for(p, W6, MOCK)
        p['_do'] = do_lines(p)
        s = p.get('sensitive')
        p['_sensitive'] = bool(s.get('flag') if isinstance(s, dict) else s)
        p['_must'] = (not p['_rejected']) and (p['severity'] == 'high' or p['class'] in MUST_CLASSES)
        p['_title'] = _strip_class_prefix(p.get('title', ''))
        out.append(p)
    return out, path


# ── сводные цифры и вердикт ─────────────────────────────────────────────────
def counts(pravki):
    act = [p for p in pravki if not p['_rejected']]
    return {
        'n_all': len(pravki), 'n_active': len(act), 'n_rejected': len(pravki) - len(act),
        'n_must': sum(1 for p in act if p['_must']),
        'n_cut': sum(1 for p in act if p.get('category') == 'cut'),
        'n_decisions': sum(1 for p in act if str(p.get('decision') or '').strip()),
        'n_sensitive': sum(1 for p in act if p['_sensitive']),
        'by_class': Counter(p['class'] or 'other' for p in act),
        'by_category': Counter(p.get('category') or 'other' for p in act),
        'by_severity': Counter(p['severity'] or 'n/a' for p in act),
    }


def load_summary(W6):
    """work/{cut}/producer_summary.json — вердикт, написанный человеком/агентом. Ключи (все опц.):
    verdict_short (заголовок), headline, verdict (абзац), lines [str] (3–5 строк), strengths [str],
    must [{num, tc, title, todo}], decisions [str]. Нет файла → None (страницы считают вердикт сами)."""
    f = Path(W6) / 'producer_summary.json'
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def verdict_lines(pravki, duration_sec=None, summary=None):
    """3–5 строк вердикта: из producer_summary.json, иначе автоматически по правкам."""
    if summary:
        lines = [str(x) for x in (summary.get('lines') or []) if str(x).strip()]
        if not lines:
            for k in ('verdict_short', 'headline', 'verdict'):
                if summary.get(k):
                    lines.append(str(summary[k]))
        if lines:
            return lines[:5]
    c = counts(pravki)
    L = []
    s = f'{c["n_active"]} ТЗ в работе'
    if c['n_rejected']:
        s += f', снято Романом {c["n_rejected"]}'
    s += f' · обязательных {c["n_must"]}'
    if duration_sec:
        s += f' · кат {sec_tc(duration_sec)}'
    L.append(s)
    if c['by_class']:
        L.append('Классы: ' + ' · '.join(f'{KIND_RU.get(k, k)} {v}' for k, v in c['by_class'].most_common()))
    if len(c['by_category']) > 1:
        L.append('Категории: ' + ' · '.join(f'{CAT_RU.get(k, k)} {v}' for k, v in c['by_category'].most_common()))
    sev = c['by_severity']
    if any(k in sev for k in SEV_RANK):
        L.append('Серьёзность (аудит экранов): ' + ' · '.join(
            f'{k} {sev.get(k, 0)}' for k in ('high', 'medium', 'low')) +
            (f' · без оценки {sev["n/a"]}' if sev.get('n/a') else ''))
    L.append(f'Решить Роману: {c["n_decisions"]} · вырезать: {c["n_cut"]} · ⚠️ чувствительных: {c["n_sensitive"]}')
    return L[:5]


# ── картинки и favicon ──────────────────────────────────────────────────────
def jpeg_bytes(path, width=480, quality=62):
    """JPEG-байты уменьшенной копии (ширина ≤ width). PNG с альфой кладём на тёмный фон."""
    from PIL import Image
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        rgba = im.convert('RGBA')
        bg = Image.new('RGB', rgba.size, (16, 16, 20))
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    else:
        im = im.convert('RGB')
    if im.width > width:
        im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def jpeg_data_uri(path, width=480, quality=62):
    """→ (data:image/jpeg;base64,…, размер в байтах)."""
    b = jpeg_bytes(path, width, quality)
    return 'data:image/jpeg;base64,' + base64.b64encode(b).decode('ascii'), len(b)


def favicon_href(emoji):
    """inline SVG-эмодзи для <link rel=icon>, percent-encoded (см. память feedback_html_page_favicon)."""
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
           f"<text y='.9em' font-size='88'>{emoji}</text></svg>")
    return 'data:image/svg+xml,' + urllib.parse.quote(svg, safe='')


def latest_review_json(review_dir, code):
    """Имя свежего {CODE}_review_*.json в 05_Review (для шапок страниц)."""
    files = sorted(Path(review_dir).glob(f'{code}_review_*.json'), key=lambda f: f.stat().st_mtime)
    return files[-1].name if files else ''
