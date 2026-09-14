#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Локальный QA превью для дока (0 токенов) — замена 11 агентов `cloud/_legacy/v7_tools/wf_preview_qa_v7.js`.

    preview_qc_local.py [--vlm] [--apply] [--only SUBSTR] [--no-stale] [--out preview_qc.json]

Проверяет каждое превью из `W6/previews_doc/manifest.json` (imgs: overlay | fix | err; tz: кадры ТЗ без
картинки) + карточки глав (`ch_img` карточки) + файлы dp_*.jpg на диске, которых нет в манифесте (orphan,
только low). Роман 10.09: «справа картинки создавай бОльшего размера, чтобы видно было, про что ты говоришь».

  a) геометрия — альфа-рамка исходного 4K-PNG (overlay/fix) или рамка ошибки (err) непуста и лежит внутри
     кропа с полем ≥3 % (кроп пересчитывается как в s12: box169/norm169 + previews_v7.json); ширина превью
     ≥ MIN_PREVIEW_W; «stale» — превью не совпадает с пересборкой из текущего кадра/рамки;
  b) читаемость — превью ужимается до 350 px (ширина колонки дока) и читается Apple Vision OCR
     (`999_extra/bin/vision_ocr_ru`): ≥70 % слов известного текста (титул термина/места, текст fix-драфта,
     подглава/прогресс из карточки, экранный текст ошибки, цитата «…» из заголовка ТЗ) должны распознаться;
  c) kind=frame — детектор чёрного кадра/перехода (средняя яркость, дисперсия лапласиана) и выбор лучшей
     секунды ±3 с по совпадению OCR кадра (`ocr_hires.jsonl`, без повторного OCR) с текстом ТЗ; если титр
     мелкий — кроп на него (рамка из bbox строк OCR);
  d) подпись «M:SS · что видно» — только из данных (вид + титул/текст), ничего не выдумывается;
  e) --vlm — Qwen2.5-VL-7B (mlx, `environment/.venv_vlm`) отвечает да/нет «виден ли титр, о котором речь»
     только для kind=frame (картинки ≤1280 px, один процесс на все кадры).

Выход: `W6/preview_qc.json` {items:[{img, preview, kind, tz, t, ok, problems[], fix:{t?, box?, minw?}, caption}],
counts} + сводка ≤2 КБ; код возврата 0 — нет high, 2 — есть. `--apply` записывает fix/cap в
`pravki/previews_v7.json` (метка _project, как читает s12); без него — только показывает, что записал бы.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from PIL import Image

from _bootstrap import P, W6, M, HERE, ROOT  # noqa: E402
import s12_doc_previews as S12  # noqa: E402  (box169 / norm169 / ATTACH / load_ovr — та же геометрия, что у рендера)

FW, FH, PW, PH = S12.FW, S12.FH, S12.PW, S12.PH
MOCK, HIRES, COMP, OUT = S12.MOCK, S12.HIRES, S12.COMP, S12.OUT
OVR = S12.OVR
OCR_BIN = Path.home() / 'YTAI/scripts/999_extra/bin/vision_ocr_ru'
VLM_PY = Path.home() / 'YTAI/environment/.venv_vlm/bin/python'
VLM_MODEL = 'mlx-community/Qwen2.5-VL-7B-Instruct-4bit'

# ── пороги ────────────────────────────────────────────────────────────────
MIN_PREVIEW_W = 800         # уже — в доке (262pt ≈ 524 px на retina) уже мыло; карточки глав 900 px проходят
MARGIN = 0.03               # поле вокруг объекта внутри кропа
READ_OK = 0.70              # доля распознанных слов при 350 px
READ_W = 350
WORD_SIM = 0.75             # нечёткое совпадение слова (OCR путает Й/И, латиницу)
DARK_MEAN = 30.0            # почти чёрный кадр
FLAT_LAP = 15.0             # плоский кадр (заливка/размытие)
TRANS_RATIO = 0.5           # лапласиан < 0.5 медианы соседей — переход/наплыв
STALE_DIFF = 28.0           # средняя разница пересборки и превью (0–255)
SMALL_TEXT_W = 0.25         # титр уже четверти кадра → предлагаем кроп
BEST_GAIN = 0.15            # насколько сосед должен быть лучше, чтобы предлагать смену секунды

LAT2CYR = str.maketrans('ABCEHKMOPTXYaceopxy', 'АВСЕНКМОРТХУасеорху')


def clean(t):
    return re.sub(r'\s+', ' ', str(t or '').strip())


def tcs(sec):
    sec = int(round(sec))
    return f'{sec // 60}:{sec % 60:02d}'


def tc_first(s):
    m = re.search(r'(\d{1,2}):(\d{2})', str(s or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def words(s):
    s = str(s or '').translate(LAT2CYR).lower().replace('ё', 'е')
    return [w for w in re.findall(r'[а-яa-z0-9]+', s) if len(w) >= 3 or w.isdigit()]


def word_hit(w, got_w):
    return w in got_w or any((len(w) >= 4 and (w in g or g in w)) or SequenceMatcher(None, w, g).ratio() >= WORD_SIM
                             for g in got_w)


def match_ratio(expected, got):
    """доля слов expected, найденных среди got (точно, вложением или похожестью ≥ WORD_SIM)"""
    exp = list(dict.fromkeys(words(expected)))
    if not exp:
        return None, []
    got_w = set(words(' '.join(got) if isinstance(got, (list, tuple)) else got))
    miss = [w for w in exp if not word_hit(w, got_w)]
    return round(1 - len(miss) / len(exp), 2), miss


def text_box(lines, exp_text):
    """рамка (4K) вокруг строк OCR кадра, где стоит текст ТЗ: якорь — строка с максимумом совпавших слов
    (только слова ≥3 букв — цифры «1»/«5» ловятся где угодно), к ней — соседи в пределах 0,3 кадра."""
    exp_w = {w for w in words(exp_text) if len(w) >= 3}
    if not exp_w:
        return None, 0
    scored = []
    for l in lines:
        got = set(words(l['t']))
        n = sum(1 for w in exp_w if word_hit(w, got))
        if n:
            scored.append((n, l))
    if not scored:
        return None, 0
    scored.sort(key=lambda x: -x[0])
    n_anchor, anchor = scored[0]
    if n_anchor < min(2, len(exp_w)):
        return None, n_anchor
    acx, acy = (anchor['x'] + anchor['bw'] / 2), (anchor['y'] + anchor['bh'] / 2)
    keep = [l for _, l in scored if abs(l['x'] + l['bw'] / 2 - acx) <= 0.3 and abs(l['y'] + l['bh'] / 2 - acy) <= 0.3]
    x0, y0 = min(l['x'] for l in keep) * FW, min(l['y'] for l in keep) * FH
    x1, y1 = max(l['x'] + l['bw'] for l in keep) * FW, max(l['y'] + l['bh'] for l in keep) * FH
    return (x0, y0, x1, y1), n_anchor


# ── кадры ─────────────────────────────────────────────────────────────────
N_FRAMES = len(list(HIRES.glob('h*.jpg'))) if HIRES.exists() else 0


def frame_path(sec):
    sec = max(0, min(N_FRAMES - 1, int(round(sec))))
    return HIRES / f'h{sec + 1:04d}.jpg'


def frame4k(sec=None, path=None):
    p = Path(path) if path and Path(path).exists() else frame_path(sec if sec is not None else 0)
    return Image.open(p).convert('RGB').resize((FW, FH), Image.LANCZOS)


def luma_lap(sec):
    """(средняя яркость, std, дисперсия лапласиана) по кадру 480×270"""
    p = frame_path(sec)
    if not p.exists():
        return None
    a = np.asarray(Image.open(p).convert('L').resize((480, 270), Image.BILINEAR), dtype=np.float32)
    lap = np.abs(4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:])
    return float(a.mean()), float(a.std()), float(lap.var())


def alpha_bbox(png, cut_bottom=0):
    ov = Image.open(png)
    if ov.mode != 'RGBA':
        return None, 1.0
    a = ov.getchannel('A')
    if cut_bottom:
        a = a.crop((0, 0, ov.width, ov.height - cut_bottom))
    bb = a.point(lambda v: 255 if v > 8 else 0).getbbox()
    if not bb:
        return None, 0.0
    sx, sy = FW / ov.width, FH / ov.height
    bb = (bb[0] * sx, bb[1] * sy, bb[2] * sx, bb[3] * sy)
    return bb, (bb[2] - bb[0]) * (bb[3] - bb[1]) / (FW * FH)


def placement(bb, box, margin=MARGIN):
    """'in' — bb внутри box с полем margin·размер box (у края кадра поле не требуется);
    'tight' — целиком внутри, но поле уже; 'cut' — часть объекта за кропом"""
    x0, y0, x1, y1 = box
    if bb[0] < x0 - 1 or bb[1] < y0 - 1 or bb[2] > x1 + 1 or bb[3] > y1 + 1:
        return 'cut'
    mw, mh = (x1 - x0) * margin, (y1 - y0) * margin
    ok_l = bb[0] >= x0 + (mw if x0 > 0 else 0)
    ok_t = bb[1] >= y0 + (mh if y0 > 0 else 0)
    ok_r = bb[2] <= x1 - (mw if x1 < FW else 0)
    ok_b = bb[3] <= y1 - (mh if y1 < FH else 0)
    return 'in' if (ok_l and ok_t and ok_r and ok_b) else 'tight'


def inside(bb, box, margin=MARGIN):
    return placement(bb, box, margin) == 'in'


def suggest_box(bb, minw=0.45):
    """кроп 16:9 вокруг объекта с полями 6 %/8 % — то, что запишется в previews_v7.json (box) при --apply"""
    return list(S12.box169(*bb, minw=minw, padx=0.06, pady=0.08))


def img_diff(a, b):
    a = np.asarray(a.convert('L').resize((160, 90), Image.BILINEAR), dtype=np.float32)
    b = np.asarray(b.convert('L').resize((160, 90), Image.BILINEAR), dtype=np.float32)
    return float(np.abs(a - b).mean())


# ── OCR ───────────────────────────────────────────────────────────────────
def ocr_files(paths):
    """Apple Vision OCR пачкой: список путей в stdin → {path: [{t, c, x, y, bw, bh}]}"""
    if not paths:
        return {}
    if not OCR_BIN.exists():
        raise SystemExit(f'нет {OCR_BIN} — swiftc -O vision_ocr_ru.swift (см. память reference_local_vision_ocr_screen_map)')
    p = subprocess.run([str(OCR_BIN)], input='\n'.join(str(x) for x in paths), capture_output=True, text=True, timeout=900)
    out = {}
    for ln in p.stdout.splitlines():
        try:
            d = json.loads(ln)
        except Exception:
            continue
        out[d['file']] = [l for l in d.get('lines', []) if l.get('t', '').strip()]
    return out


def load_ocr_hires():
    f = W6 / 'ocr_hires.jsonl'
    out = {}
    if not f.exists():
        return out
    for ln in open(f, encoding='utf-8'):
        try:
            d = json.loads(ln)
            m = re.search(r'h(\d+)\.jpg', d['file'])
            if m:
                out[int(m.group(1)) - 1] = [l for l in d.get('lines', []) if l.get('t', '').strip() and l.get('c', 0) >= 0.3]
        except Exception:
            pass
    return out


# ── ожидаемый текст по имени картинки (из данных, не из головы) ───────────
def load_catalogs():
    cat = {'terms': {}, 'places': {}, 'sub': [], 'prog': {}, 'ch_name': {}}
    try:
        import terms_catalog as TC
        cat['terms'] = {k: (title, sub) for k, _, title, sub, _ in TC.TERMS}
        cat['places'] = {p['key']: p for p in TC.PLACES}
    except Exception as ex:                                     # noqa: BLE001
        print('  ⚠️ каталог терминов не загружен:', ex)
    try:
        import make_infographics_v6_data as D
        cat['sub'] = D.SUB
        cat['prog'] = {k: (v[0], v[1]) for k, v in D.PROG.items()}
        cat['ch_name'] = dict(zip([n for _, n in P.CHAPTERS], D.CH_NAME))
    except Exception as ex:                                     # noqa: BLE001
        print('  ⚠️ данные структуры не загружены:', ex)
    return cat


def quoted(s):
    return [q for q in re.findall(r'«([^»]{2,})»', str(s or ''))]


def first_do_line(p):
    for el in ((p.get('parts') or {}).get('do') or []):
        if isinstance(el, str):
            return el
        if isinstance(el, dict):
            return el.get('h') or (el.get('items') or [''])[0]
    return ''


def qt(s):
    """«…» вокруг текста без удвоения кавычек (титул «ШЁЛК» уже в кавычках)"""
    return '«' + clean(s).strip('«»') + '»'


def title_body(p):
    """заголовок ТЗ без класса «ВЁРСТКА: » — что именно на экране"""
    return clean(re.sub(r'^[А-ЯЁ /-]+:\s*', '', str(p.get('title') or '')))


def lines_in_bbox(lines, bbox, pad=0.02):
    x, y, w, h = bbox
    out = []
    for l in lines:
        cx, cy = l['x'] + l['bw'] / 2, l['y'] + l['bh'] / 2
        if x - pad <= cx <= x + w + pad and y - pad <= cy <= y + h + pad:
            out.append(l['t'])
    return out


def expected_for(item, cat, ann_by_tz, ann_by_screen, pr_by_num, ocr_hires):
    """→ (ожидаемый текст для OCR, варианты «что видно» для подписи (длинный → короткий), строгость 'high'|'low'|None)"""
    stem = Path(item['img']).stem if item.get('img') else Path(item['preview']).stem
    kind = item['kind']
    p = pr_by_num.get(item.get('tz') or '', {})
    if stem.startswith('term_'):
        t = cat['terms'].get(stem[5:])
        return (t[0] if t else ''), [f'плашка термина {qt(t[0])}' if t else 'плашка термина'], 'high' if t else None
    if stem.startswith('termgrp_'):
        titles = [cat['terms'][k][0] for k in stem[8:].split('_') if k in cat['terms']]
        return ' '.join(titles), ['плашка терминов: ' + ', '.join(qt(x) for x in titles), 'плашка терминов'], 'high' if titles else None
    if stem.startswith('map_') and not stem.startswith('mapfull_'):
        key = re.sub(r'_note$', '', stem[4:])
        pl = cat['places'].get(key)
        return (pl.get('ru', '') if pl else ''), [f'карта {qt(pl.get("label") or pl.get("ru"))}' if pl else 'мини-карта'], 'high' if pl else None
    if stem.startswith('mapfull_'):
        return '', ['карта региона'], None
    if stem.startswith('sub_'):
        i = int(stem[4:]) - 1
        s = cat['sub'][i] if 0 <= i < len(cat['sub']) else None
        return (s[2] if s else ''), [f'подглава {qt(s[2])}' if s else 'плашка подглавы', 'плашка подглавы'], 'high' if s else None
    if stem.startswith('prog_'):
        m = re.match(r'prog_(\d+)_(\d+)', stem)
        pg = cat['prog'].get(m.group(1)) if m else None
        if pg:
            k = int(m.group(2))
            it = pg[1][k - 1] if 0 < k <= len(pg[1]) else ''
            return f'{pg[0]} {it}', [f'прогресс {qt(pg[0])} · {k} из {len(pg[1])} · {it}', f'прогресс · {k} из {len(pg[1])}'], 'high'
        return '', ['плашка прогресса'], None
    if stem.startswith('info_videomap_ch'):
        n = stem[len('info_videomap_ch'):]
        nm = cat['ch_name'].get(n, '')
        return nm, [f'карта главы {int(n)} {qt(nm)}' if nm else 'карта главы', 'карта главы'], 'low'
    if stem.startswith('info_'):
        return '', ['карта структуры фильма'], None
    if stem.startswith('fix_tz'):
        num = 'ТЗ-' + re.sub(r'[^0-9]', '', stem[len('fix_tz'):])
        a = ann_by_tz.get(num) or {}
        fx = clean(((a.get('fix') or {}).get('text') or '').replace('\n', ' '))
        ty = (pr_by_num.get(num, {}).get('typo') or [{}])[0]
        whats = []
        if ty.get('was') and ty.get('now'):
            whats.append(f'было {qt(ty["was"])} → стало {qt(ty["now"])}')
            whats.append(f'было → стало {qt(ty["now"])}')
        elif fx:
            whats.append(f'было / стало: {qt(fx)}')
        whats.append('было / стало')
        return fx or clean(ty.get('now')), whats, 'high' if (fx or ty.get('now')) else None
    if stem.startswith('v6_err_'):
        anns = ann_by_screen.get(stem[len('v6_err_'):]) or []
        on_screen, under = '', []
        for a in anns:
            q = quoted(str(a.get('text') or '').split('→')[0])
            if q and not on_screen:
                on_screen = q[0]
            under += lines_in_bbox(ocr_hires.get(int(a.get('t0', -1)), []), a['bbox'])   # что именно под стрелкой
        exp = ' '.join(under) or on_screen
        whats = ([f'где ошибка: {qt(on_screen)}'] if on_screen else []) + ['где ошибка (стрелка на кадре)']
        return exp, whats, 'low' if exp else None
    if stem.startswith(('ann_tz', 'tz_lt_')):
        num = 'ТЗ-' + re.sub(r'[^0-9]', '', stem)
        pp = pr_by_num.get(num, {})
        return clean(pp.get('title')) + ' ' + clean(first_do_line(pp))[:80], [f'плашка {num} на кадре'], 'low'
    if kind == 'ch':
        nm = cat['ch_name'].get(item.get('ch') or '', '')
        return '', [f'глава {int(item["ch"])} {qt(nm)}' if nm else 'карточка главы', 'карточка главы'], None
    if kind == 'frame':
        q = quoted(p.get('title')) + [t.get('was', '') for t in (p.get('typo') or [])]
        exp = ' '.join(q)
        whats = ([f'кадр: {qt(q[0])}'] if q else []) + [f'кадр: {title_body(p)}' if title_body(p) else 'кадр ТЗ', 'кадр ТЗ']
        return exp, whats, 'low' if exp else None
    return '', [title_body(p) or 'кадр'], None


# ── VLM (только kind=frame, по флагу) ──────────────────────────────────────
VLM_PROG = r'''
import json, os, sys
os.environ.setdefault('HF_HOME', os.path.expanduser('~/YTAI/models/huggingface'))
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config
tasks = json.load(open(sys.argv[1]))
model, processor = load(sys.argv[3])
config = load_config(sys.argv[3])
out = []
for t in tasks:
    f = apply_chat_template(processor, config, t['q'], num_images=1)
    r = generate(model, processor, f, [t['img']], max_tokens=6, temperature=0.0, verbose=False)
    out.append({'img': t['img'], 'answer': (r.text if hasattr(r, 'text') else str(r)).strip()})
json.dump(out, open(sys.argv[2], 'w'), ensure_ascii=False)
'''


def vlm_yes_no(tasks):
    """tasks: [{img (≤1280 px), q}] → {img: 'yes'|'no'|raw}. Один процесс venv_vlm на все вопросы."""
    if not tasks:
        return {}
    if not VLM_PY.exists():
        print(f'  ⚠️ нет {VLM_PY} — VLM пропущен')
        return {}
    tmp = Path(tempfile.mkdtemp(prefix='pqc_vlm_'))
    (tmp / 'in.json').write_text(json.dumps(tasks, ensure_ascii=False), encoding='utf-8')
    p = subprocess.run([str(VLM_PY), '-c', VLM_PROG, str(tmp / 'in.json'), str(tmp / 'out.json'), VLM_MODEL],
                       capture_output=True, text=True, timeout=3600)
    if p.returncode != 0 or not (tmp / 'out.json').exists():
        print('  ⚠️ VLM упал:', (p.stderr or '')[-400:])
        return {}
    out = {}
    for r in json.load(open(tmp / 'out.json', encoding='utf-8')):
        a = r['answer'].strip().lower()
        out[r['img']] = 'yes' if a.startswith(('yes', 'да')) else 'no' if a.startswith(('no', 'нет')) else a[:20]
    return out


# ── сборка списка превью ──────────────────────────────────────────────────
def collect_items(man, pr, act_nums, ch_img):
    items, seen = [], set()
    owner = {}
    for num, p in act_nums:
        for mr in p.get('material_rich') or []:
            if mr.get('img'):
                owner.setdefault(mr['img'], num)
        for img, _ in S12.ATTACH.get(num, []):
            owner.setdefault(img, num)
    for img, e in man.get('imgs', {}).items():
        items.append({'img': img, 'preview': e['preview'], 'kind': e['kind'], 'tz': owner.get(img), 't': e.get('t'),
                      'variants': e.get('variants', False)})
        seen.add(e['preview'])
    for num, lst in man.get('tz', {}).items():
        for k, e in enumerate(lst, 1):
            items.append({'img': None, 'preview': e['preview'], 'kind': 'frame', 'tz': num, 't': e.get('t'), 'k': k,
                          'cap_now': e.get('cap'), 'grid': bool(e.get('grid'))})
            seen.add(e['preview'])
    for n, f in (ch_img or {}).items():
        start = next((t for t, nn in P.CHAPTERS if nn == n), 0)
        items.append({'img': None, 'preview': f, 'kind': 'ch', 'tz': None, 't': start, 'ch': n})
        seen.add(f)
    pr_by_num = dict(act_nums)
    for f in sorted(OUT.glob('dp_*.jpg')):
        if f.name in seen:
            continue
        m = re.match(r'dp_tz(\d+)_(\d+)\.jpg', f.name)
        if m:
            num = f'ТЗ-{int(m.group(1)):02d}'
            items.append({'img': None, 'preview': f.name, 'kind': 'frame', 'tz': num,
                          't': tc_first(pr_by_num.get(num, {}).get('tc_range')), 'k': int(m.group(2)), 'orphan': True})
        else:
            kind = 'fix' if f.name.startswith('dp_fix_') else 'err' if f.name.startswith('dp_v6_err_') else 'overlay'
            src = f.name[3:-4] + ('.jpg' if kind == 'err' else '.png')
            items.append({'img': src, 'preview': f.name, 'kind': kind, 'tz': owner.get(src), 't': None, 'orphan': True})
    return items


# ── проверки по видам ─────────────────────────────────────────────────────
def check_geometry(it, ovr, ann_by_tz, ann_by_screen, do_stale):
    """→ (problems, fix, box, base_img_for_stale) — геометрия как в s12"""
    probs, fix = [], {}
    img = it['img']
    o = ovr.get('img:' + img, {}) if img else {}
    pv = Image.open(OUT / it['preview']).convert('RGB')
    if it['kind'] == 'overlay':
        png = MOCK / img
        if not png.exists():
            return [('high', 'no_source', f'нет исходника {png.name}')], fix, None, None
        bb, frac = alpha_bbox(png, cut_bottom=100)
        if not bb:
            return [('high', 'alpha_empty', 'у исходного PNG пустая альфа (нечего показывать)')], fix, None, None
        sec = it['t']
        box = S12.norm169(o['box']) if o.get('box') else ((0, 0, FW, FH) if frac > 0.5 else S12.box169(*bb, minw=o.get('minw', 0.45)))
        pl = placement(bb, box)
        if pl != 'in':
            probs.append(('high' if pl == 'cut' else 'low', 'overlay_cut' if pl == 'cut' else 'overlay_tight',
                          f'плашка {"выходит за кроп" if pl == "cut" else "впритык к краю кропа (поле < 3 %)"}: '
                          f'альфа {tuple(int(v) for v in bb)} vs кроп {box}'))
            fix['box'] = suggest_box(bb, minw=o.get('minw', 0.45))
        if do_stale and sec is not None:
            rebuilt = S12.comp(frame4k(sec), png).crop(box).resize((PW, PH), Image.LANCZOS)
            d = img_diff(rebuilt, pv)
            if d > STALE_DIFF:
                probs.append(('low', 'stale', f'превью не совпадает с пересборкой из кадра {tcs(sec)} (diff {d:.0f})'))
        return probs, fix, box, None
    if it['kind'] == 'fix':
        key = 'ТЗ-' + re.sub(r'[^0-9]', '', Path(img).stem[len('fix_tz'):])
        a = ann_by_tz.get(key)
        png = MOCK / img
        if not a or not png.exists():
            return [('high', 'no_source', f'нет аннотации/исходника для {img}')], fix, None, None
        x, y, w, h = a['bbox']
        if it.get('t') is None:
            it['t'] = int(a['t0'])
        box = S12.norm169(o['box']) if o.get('box') else S12.box169(x * FW, y * FH, (x + w) * FW, (y + h) * FH,
                                                                     minw=o.get('minw', 0.40), padx=0.06, pady=0.10)
        bbs = []
        for f in [png] + [MOCK / f'{png.stem}_{v}.png' for v in ('A', 'B')]:
            if f.exists():
                bb, _ = alpha_bbox(f)
                if bb:
                    bbs.append(bb)
        if not bbs:
            return [('high', 'alpha_empty', 'у fix-драфта пустая альфа')], fix, box, None
        ubb = (min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs))
        pl = placement(ubb, box)
        if pl != 'in':
            probs.append(('high' if pl == 'cut' else 'low', 'overlay_cut' if pl == 'cut' else 'overlay_tight',
                          f'драфт (заплатка+бейдж) {"режется кропом" if pl == "cut" else "впритык к краю кропа (поле < 3 %)"}: '
                          f'альфа {tuple(int(v) for v in ubb)} vs кроп {box}'))
            fix['box'] = suggest_box(ubb, minw=o.get('minw', 0.40))
        if do_stale:
            base = frame4k(a['t0'], a.get('frame'))
            rebuilt = base.crop(box).resize((PW, PH), Image.LANCZOS)
            d = img_diff(rebuilt, pv.crop((0, 0, PW, PH)))
            if d > STALE_DIFF:
                probs.append(('low', 'stale', f'панель БЫЛО не совпадает с кадром {tcs(a["t0"])} (diff {d:.0f})'))
        return probs, fix, box, None
    if it['kind'] == 'err':
        sid = Path(img).stem[len('v6_err_'):]
        anns = ann_by_screen.get(sid) or []
        src = COMP / img
        if not anns or not src.exists():
            return [('high', 'no_source', f'нет аннотаций/кадра для {img}')], fix, None, None
        xs0, ys0, xs1, ys1 = [], [], [], []
        for a in anns:
            x, y, w, h = a['bbox']
            cx, cy = (x + w / 2) * FW, (y + h / 2) * FH
            rx, ry = max(w * FW / 2 + 70, 160), max(h * FH / 2 + 60, 90)
            xs0.append(cx - rx), ys0.append(cy - ry), xs1.append(cx + rx), ys1.append(cy + ry)
        ell = (max(0, min(xs0)), max(0, min(ys0)), min(FW, max(xs1)), min(FH, max(ys1)))
        box = S12.norm169(o['box']) if o.get('box') else S12.box169(*ell, minw=o.get('minw', 0.5), padx=0.03, pady=0.05)
        if not inside(ell, box, margin=0.0):
            probs.append(('high', 'arrow_cut', f'обводка ошибки режется кропом: {tuple(int(v) for v in ell)} vs {box}'))
            fix['box'] = suggest_box(ell, minw=o.get('minw', 0.5))
        # плашка с текстом ТЗ (ann_tzNN.png) режется кропом почти всегда — так задуман кроп на ошибку, не проверяем
        if it.get('t') is None:
            it['t'] = int(anns[0]['t0'])
        it['err_bbox_w'] = max(a['bbox'][2] for a in anns)   # ширина места ошибки (доля кадра) — для подсказки minw
        if do_stale:
            rebuilt = Image.open(src).convert('RGB').resize((FW, FH), Image.LANCZOS).crop(box).resize((PW, PH), Image.LANCZOS)
            d = img_diff(rebuilt, pv)
            if d > STALE_DIFF:
                probs.append(('low', 'stale', f'превью не совпадает с пересборкой кадра со стрелкой (diff {d:.0f})'))
        return probs, fix, box, None
    return probs, fix, None, None


def tc_range_bounds(p):
    m = re.findall(r'(\d{1,2}):(\d{2})', str(p.get('tc_range') or ''))
    if not m:
        return None
    secs = [int(a) * 60 + int(b) for a, b in m]
    return min(secs), max(secs)


def check_frame(it, ocr_hires, exp_text, p):
    """kind=frame: чёрный/плоский/переход, лучшая секунда ±3 с (в пределах диапазона ТЗ) по OCR-совпадению,
    кроп на мелкий титр."""
    probs, fix = [], {}
    t = it.get('t')
    if t is None or it.get('grid'):
        return probs, fix, None
    t = int(t)
    st = luma_lap(t)
    if st is None:
        return [('high', 'no_frame', f'нет кадра h{t + 1:04d}.jpg')], fix, None

    def score(sec):
        r, _ = match_ratio(exp_text, [l['t'] for l in ocr_hires.get(sec, [])]) if exp_text else (None, [])
        s = luma_lap(sec)
        base = (r or 0.0)
        if s is None:
            return -1
        if s[0] < DARK_MEAN:
            base -= 0.5
        if s[2] < FLAT_LAP:
            base -= 0.3
        return base

    cands = [s for s in range(t - 3, t + 4) if 0 <= s < N_FRAMES]
    rng = tc_range_bounds(p)
    if rng and rng[1] > rng[0]:                              # секунда вне диапазона ТЗ — уже соседнее ТЗ
        cands = [s for s in cands if rng[0] <= s <= rng[1] + 1] or [t]
    neigh = [luma_lap(s)[2] for s in cands if s != t and luma_lap(s)]
    med = float(np.median(neigh)) if neigh else st[2]
    if st[0] < DARK_MEAN:
        probs.append(('high', 'dark_frame', f'кадр {tcs(t)} почти чёрный (яркость {st[0]:.0f})'))
    elif st[2] < FLAT_LAP:
        probs.append(('low', 'flat_frame', f'кадр {tcs(t)} без деталей (лапласиан {st[2]:.0f})'))
    elif med > 0 and st[2] < TRANS_RATIO * med:
        probs.append(('low', 'transition', f'кадр {tcs(t)} размыт относительно соседей (лапласиан {st[2]:.0f} vs {med:.0f}) — похоже на переход'))
    sc = {s: score(s) for s in cands}
    best = max(cands, key=lambda s: (sc[s], -abs(s - t)))
    if best != t and sc[best] >= sc[t] + BEST_GAIN:
        fix['t'] = best
        probs.append(('low', 'better_frame', f'секунда {tcs(best)} читается лучше ({sc[best]:.2f} vs {sc[t]:.2f})'))
    elif probs and any(p[1] in ('dark_frame', 'flat_frame', 'transition') for p in probs) and best != t:
        fix['t'] = best
    # мелкий титр → кроп на него (рамка из строк OCR кадра, где стоит текст ТЗ)
    use_t = fix.get('t', t)
    if exp_text:
        tb, _ = text_box(ocr_hires.get(use_t, []), exp_text)
        if tb and (tb[2] - tb[0]) / FW < SMALL_TEXT_W:
            fix['box'] = suggest_box(tb, minw=0.45)
            probs.append(('low', 'text_small', f'титр занимает {100 * (tb[2] - tb[0]) / FW:.0f} % ширины кадра — предлагаю кроп'))
    return probs, fix, st


# ── main ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--vlm', action='store_true', help='Qwen2.5-VL да/нет для kind=frame')
    ap.add_argument('--apply', action='store_true', help='записать fix/cap в previews_v7.json (иначе только показать)')
    ap.add_argument('--only', help='только превью, в имени которых есть подстрока')
    ap.add_argument('--no-stale', action='store_true', help='не пересобирать кропы для сверки с превью (быстрее)')
    ap.add_argument('--out', help='куда писать отчёт (по умолчанию W6/preview_qc.json)')
    a = ap.parse_args()
    t0 = time.time()
    man_f = OUT / 'manifest.json'
    if not man_f.exists():
        raise SystemExit(f'нет {man_f} — сначала s12_doc_previews.py --render')
    man = json.load(open(man_f, encoding='utf-8'))
    pr = json.load(open(M / 'pravki_v2.json', encoding='utf-8'))['all']
    act_nums = [(f'ТЗ-{i + 1:02d}', p) for i, p in enumerate(pr) if p.get('status') != 'rejected']
    pr_by_num = dict(act_nums)
    audit = P.audit_or_die(W6 / 'audit_v6.json', 'аннотации ошибок') or {'annotations': []}
    ann_by_tz = {x['tz']: x for x in audit['annotations']}
    ann_by_screen = {}
    for x in audit['annotations']:
        ann_by_screen.setdefault(x['screen_id'], []).append(x)
    ovr = S12.load_ovr()
    cat = load_catalogs()
    ocr_hires = load_ocr_hires()
    items = collect_items(man, pr, act_nums, P.get('ch_img') or {})
    if a.only:
        items = [it for it in items if a.only in it['preview'] or a.only in (it.get('img') or '')]
    print(f'[preview_qc_local] {P.CODE}: превью {len(items)} (манифест imgs {len(man.get("imgs", {}))}, кадры ТЗ '
          f'{sum(len(v) for v in man.get("tz", {}).values())}, главы {len(P.get("ch_img") or {})}, '
          f'вне манифеста {sum(1 for it in items if it.get("orphan"))}) · кадров hires {N_FRAMES} · OCR кадров {len(ocr_hires)}', flush=True)

    # 1) геометрия + кадры
    for it in items:
        it['problems'], it['fix'] = [], {}
        pvf = OUT / it['preview']
        if not pvf.exists():
            it['problems'].append(('high', 'missing_file', f'нет файла {it["preview"]}'))
            continue
        w, h = Image.open(pvf).size
        it['w'], it['h'] = w, h
        if w < MIN_PREVIEW_W:
            it['problems'].append(('high' if w < 1000 else 'low', 'too_narrow', f'ширина превью {w} px < {MIN_PREVIEW_W}'))
        exp, what, strict = expected_for(it, cat, ann_by_tz, ann_by_screen, pr_by_num, ocr_hires)
        it['expected'], it['what'], it['strict'] = exp, what, strict
        try:
            if it['kind'] in ('overlay', 'fix', 'err') and it.get('img'):
                probs, fix, box, _ = check_geometry(it, ovr, ann_by_tz, ann_by_screen, not a.no_stale)
                it['problems'] += probs
                it['fix'].update(fix)
                it['box'] = list(box) if box else None
            elif it['kind'] == 'frame':
                probs, fix, st = check_frame(it, ocr_hires, exp, pr_by_num.get(it.get('tz') or '', {}))
                it['problems'] += probs
                it['fix'].update(fix)
                it['frame_stats'] = [round(v, 1) for v in st] if st else None
        except Exception as ex:                                 # noqa: BLE001
            it['problems'].append(('high', 'error', f'{type(ex).__name__}: {ex}'))

    # 2) читаемость при 350 px — OCR одной пачкой
    tmp = Path(tempfile.mkdtemp(prefix='pqc_ocr_'))
    small = {}
    for it in items:
        pvf = OUT / it['preview']
        if not pvf.exists() or not it.get('expected'):
            continue
        im = Image.open(pvf).convert('RGB')
        sm = tmp / it['preview']
        im.resize((READ_W, max(1, round(im.height * READ_W / im.width))), Image.LANCZOS).save(sm, quality=90)
        small[str(sm)] = it
    t_ocr = time.time()
    ocr = ocr_files(list(small))
    for path, it in small.items():
        lines = [l['t'] for l in ocr.get(path, [])]
        ratio, miss = match_ratio(it['expected'], lines)
        it['ocr_ratio'], it['ocr_lines'] = ratio, lines[:8]
        if ratio is not None and ratio < READ_OK:
            sev = it['strict'] or 'low'
            it['problems'].append((sev, 'unreadable_350px', f'при 350 px распознано {ratio:.0%} слов «{clean(it["expected"])[:60]}»; не читается: {", ".join(miss[:5])}'))
            if it['kind'] == 'err' and it.get('err_bbox_w', 1) < 0.15 and not it['fix']:
                it['fix']['minw'] = 0.3                        # мелкое слово под стрелкой: кроп в половину кадра его не показывает
            if it['kind'] == 'frame' and 'box' not in it['fix'] and it.get('t') is not None:
                # титр не читается в целом кадре — кроп на его строки, если OCR кадра их видит
                tb, _ = text_box(ocr_hires.get(int(it['fix'].get('t', it['t'])), []), it['expected'])
                if tb:
                    it['fix']['box'] = suggest_box(tb, minw=0.45)
    t_ocr = time.time() - t_ocr

    # 3) VLM да/нет — только кадры
    t_vlm = 0.0
    if a.vlm:
        t_vlm = time.time()
        tasks = []
        for it in items:
            if it['kind'] == 'frame' and it.get('expected') and (OUT / it['preview']).exists():
                im = Image.open(OUT / it['preview']).convert('RGB')
                im.thumbnail((1280, 1280))
                f = tmp / ('vlm_' + it['preview'])
                im.save(f, quality=88)
                tasks.append({'img': str(f), 'q': ('Is the on-screen title or graphic described here visible in this video frame: '
                                                  f'«{clean(it["expected"])[:160]}»? Answer with one word: yes or no.')})
                it['_vlm_img'] = str(f)
        ans = vlm_yes_no(tasks)
        for it in items:
            if it.get('_vlm_img') in ans:
                it['vlm'] = ans[it['_vlm_img']]
                if it['vlm'] == 'no':
                    it['problems'].append(('low', 'vlm_not_visible', 'VLM: титра/графики, о которой речь, на кадре не видно'))
            it.pop('_vlm_img', None)
        t_vlm = time.time() - t_vlm
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    # 4) подписи + итог
    for it in items:
        t = it['fix'].get('t', it.get('t'))
        whats = it.get('what') or ['']
        cap = ''
        for what in whats:                                    # первый вариант, влезающий в 110 знаков — без обрыва «…»
            cap = f'{tcs(t)} · {what}' if t is not None and what else what
            if len(cap) <= 110:
                break
        it['caption'] = cap
        if it.get('orphan'):
            it['problems'] = [('low', c, w) for _, c, w in it['problems']]
        it['problems'] = [{'severity': s, 'criterion': c, 'what': w} for s, c, w in it['problems']]
        it['ok'] = not any(p['severity'] == 'high' for p in it['problems'])
        for k in ('expected', 'strict', 'what'):
            it.pop(k, None)
    counts = {'items': len(items), 'ok': sum(1 for it in items if it['ok']),
              'high': sum(1 for it in items for p in it['problems'] if p['severity'] == 'high'),
              'low': sum(1 for it in items for p in it['problems'] if p['severity'] == 'low'),
              'by_kind': {}, 'by_criterion': {}, 'orphans': sum(1 for it in items if it.get('orphan')),
              'with_fix': sum(1 for it in items if it['fix'])}
    for it in items:
        bk = counts['by_kind'].setdefault(it['kind'], {'n': 0, 'ok': 0})
        bk['n'] += 1
        bk['ok'] += it['ok']
        for p in it['problems']:
            c = counts['by_criterion'].setdefault(p['criterion'], {'high': 0, 'low': 0})
            c[p['severity']] += 1
    rep = {'schema': 'preview-qc-v1', 'project': P.PROJECT, 'items': items, 'counts': counts,
           'timing': {'total_sec': round(time.time() - t0, 1), 'ocr_sec': round(t_ocr, 1), 'vlm_sec': round(t_vlm, 1)}}
    out = Path(a.out) if a.out else W6 / 'preview_qc.json'
    P.write_json_atomic(out, rep)

    # 5) previews_v7.json — что записали бы (и запись по --apply)
    cur = json.load(open(OVR, encoding='utf-8')) if OVR.exists() else {}
    if cur and cur.get('_project') not in (None, P.PROJECT):
        print(f'  !! {OVR.name} помечен проектом «{cur.get("_project")}» — --apply запрещён')
        can_apply = False
    else:
        can_apply = True
    new = json.loads(json.dumps(cur))
    new['_project'] = P.PROJECT
    n_cap = n_fix = 0
    for it in items:
        if it.get('orphan') or it['kind'] == 'ch':
            continue
        if it.get('img'):
            o = new.setdefault('img:' + it['img'], {})
            if it['caption'] and o.get('cap') != it['caption']:
                o['cap'] = it['caption']
                n_cap += 1
            if it['fix']:
                o.update({k: v for k, v in it['fix'].items() if k in ('t', 'box', 'minw')})
                n_fix += 1
        else:
            tz = it['tz']
            frames = new.setdefault(tz, {}).setdefault('frames', [dict(x) for x in man.get('tz', {}).get(tz, [])])
            k = it.get('k', 1) - 1
            while len(frames) <= k:
                frames.append({})
            fr = {kk: vv for kk, vv in frames[k].items() if kk in ('t', 'box', 'cap', 'grid')}
            if it['caption'] and fr.get('cap') != it['caption']:
                fr['cap'] = it['caption']
                n_cap += 1
            if it['fix'] and not fr.get('grid'):
                fr.update({kk: vv for kk, vv in it['fix'].items() if kk in ('t', 'box')})
                n_fix += 1
            if 't' not in fr and it.get('t') is not None:
                fr['t'] = it['t']
            frames[k] = fr
    if a.apply and can_apply:
        P.write_json_atomic(OVR, new)
        applied = f'записано в {OVR.name}: подписей {n_cap}, поправок {n_fix}'
    else:
        applied = f'dry-run: в {OVR.name} ушло бы подписей {n_cap}, поправок {n_fix} (--apply)'

    lines = [f'превью {counts["items"]}: ok {counts["ok"]} · с high {counts["items"] - counts["ok"]} · замечаний high {counts["high"]} / low {counts["low"]} · '
             f'вне манифеста {counts["orphans"]} · с поправкой {counts["with_fix"]}',
             '  ' + ' · '.join(f'{k}: {v["ok"]}/{v["n"]} ok' for k, v in counts['by_kind'].items())]
    for crit, c in sorted(counts['by_criterion'].items(), key=lambda kv: (-kv[1]['high'], -kv[1]['low'])):
        lines.append(f'  {crit:<18} high {c["high"]:<3} low {c["low"]}')
    ex = [(it, p) for it in items for p in it['problems'] if p['severity'] == 'high'][:5] or \
         [(it, p) for it in items for p in it['problems']][:5]
    if ex:
        lines.append('примеры:')
        lines += [f'  {it["preview"]} ({it["kind"]}, {it.get("tz") or "-"}) [{p["criterion"]}] {p["what"][:100]}' for it, p in ex]
    lines.append(f'{applied} · время {rep["timing"]["total_sec"]} с (OCR {rep["timing"]["ocr_sec"]} с' +
                 (f', VLM {rep["timing"]["vlm_sec"]} с' if a.vlm else '') + f') → {out}')
    print('\n'.join(lines)[:2000], flush=True)
    sys.exit(0 if counts['high'] == 0 else 2)


if __name__ == '__main__':
    main()
