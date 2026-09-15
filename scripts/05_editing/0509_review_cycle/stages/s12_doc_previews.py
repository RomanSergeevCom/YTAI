#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v7 S12: КРУПНЫЕ превью для дока и листа (Роман 10.09: «справа картинки создавай бОльшего размера,
чтобы видно было, про что ты говоришь (создавай их)»).

Прозрачные 4K-оверлеи (панели, плашки, карты, fix-драфты) в доке шириной 145pt превращались в тёмные
точки. Здесь каждое такое изображение накладывается на реальный кадр рендера в свой таймкод и кропается
на область, о которой речь:
  • оверлей (prog/sub/term/termgrp/map/mapfull/*_t) → кадр в timeline_in сегмента + кроп по альфе;
  • fix-драфт → «БЫЛО / СТАЛО» столбиком (ТЗ-21 цены: БЫЛО / ВАРИАНТ А / ВАРИАНТ Б);
  • кадр ошибки со стрелкой (v6_err_*) → кроп вокруг места ошибки;
  • ТЗ без картинок → кадр в таймкод ТЗ (кадр/кроп/подпись правятся в previews_v7.json).
Непрозрачные полноэкранные драфты и фото/рефы остаются как есть (в доке они и так читаются).

  --render  → previews_doc/dp_*.jpg + manifest.json + index.html (контактный лист для QA)
  --upload  → rclone copy в gdrive:YTUVI_plan_v3_shots, id → montage/shots_ids.json
  --apply   → pravki material_rich[].preview/cap (+ элементы для ТЗ без картинок и готовые драфты
              ТЗ-10/21/31/32). Идемпотентно; ОБЯЗАТЕЛЬНО после каждого s10+s11 (s10 заменяет
              material_rich у ТЗ из overrides).
Кадры: hires/h{sec+1}.jpg (1920) апскейлятся до 4K, оверлей кладётся в родном 4K — текст драфта чёткий.
"""
import html
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from _bootstrap import P, W6, M, HERE, ROOT, T, LANG  # noqa: E402

REVIEW_DIR = P.REVIEW_DIR
MOCK = P.MOCK
REVIEW = REVIEW_DIR / f'{P.CODE}_review_v6.json'
HIRES = W6 / 'hires'
COMP = W6 / 'err_frames_annotated'
OUT = W6 / 'previews_doc'
OVR = M / 'previews_v7.json'          # ручные поправки превью — принимаются только со своей меткой _project
SHOTS_REMOTE = P.get('shots_remote', 'gdrive:YTUVI_plan_v3_shots')


def load_ovr():
    """Поправки превью по НОМЕРАМ ТЗ — только если файл помечен этим проектом."""
    if not OVR.exists():
        return {}
    o = json.load(open(OVR))
    if o.get('_project') != P.PROJECT:
        print(f'!! previews_v7.json от проекта «{o.get("_project") or "без метки"}», '
              f'а собираем «{P.PROJECT}» — поправки превью НЕ применяю')
        return {}
    return o
FONT = '/Library/Fonts/Arial Unicode.ttf'
FW, FH = 3840, 2160
PW, PH = 1600, 900
# готовые драфты, которые у ТЗ были, но в материалы не попали (Роман: «видно, про что говоришь»)
# Это фикстуры YTUVI01 (ключи — внутренние «ТЗ-NN»). ru — как было (привязываются всегда); en — только если
# файл драфта реально лежит в mockups, иначе второй/двадцать первый ТЗ чужого фильма получил бы текст про рубины.
_ATTACH_FILES = {'ТЗ-21': ('fix_tz21b.png', 'fix_tz21c.png', 'fix_tz21d.png'), 'ТЗ-31': ('fix_tz31b.png',),
                 'ТЗ-32': ('fix_tz32b.png',), 'ТЗ-10': ('fix_tz10b.png',)}
ATTACH = {num: [(img, T(f'c2.pv_att.{Path(img).stem}')) for img in imgs if LANG == 'ru' or (MOCK / img).exists()]
          for num, imgs in _ATTACH_FILES.items()}
ATTACH = {num: lst for num, lst in ATTACH.items() if lst}
SRC_FIX = T('c2.pv_src_fix')
C_RED, C_GREEN, C_BLUE = (193, 39, 45), (46, 139, 62), (31, 79, 209)


def clean(t):
    return re.sub(r'\s+', ' ', str(t or '').strip())


def tcs(sec):
    sec = int(sec)
    return f'{sec // 60}:{sec % 60:02d}'


def tc_first(s):
    m = re.search(r'(\d{1,2}):(\d{2})', str(s or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def frame4k(sec=None, path=None):
    p = Path(path) if path else HIRES / f'h{max(0, min(2439, int(round(sec)))) + 1:04d}.jpg'
    return Image.open(p).convert('RGB').resize((FW, FH), Image.LANCZOS)


def comp(base, png):
    return Image.alpha_composite(base.convert('RGBA'), Image.open(png).convert('RGBA').resize((FW, FH))).convert('RGB')


def box169(x0, y0, x1, y1, minw=0.45, padx=0.05, pady=0.07):
    """кроп 16:9 вокруг области (4K-пиксели) с полями, не уже minw кадра, внутри кадра"""
    x0, x1, y0, y1 = x0 - padx * FW, x1 + padx * FW, y0 - pady * FH, y1 + pady * FH
    w, h = max(x1 - x0, minw * FW), y1 - y0
    if w / h > 16 / 9:
        h = w * 9 / 16
    else:
        w = h * 16 / 9
    w, h = min(w, FW), min(h, FH)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    L, T = min(max(cx - w / 2, 0), FW - w), min(max(cy - h / 2, 0), FH - h)
    return int(L), int(T), int(L + w), int(T + h)


def norm169(box):
    """ручная рамка (из QA) → строго 16:9 вокруг её центра, внутри кадра (иначе fit() сплющит)"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w / h > 16 / 9:
        h = w * 9 / 16
    else:
        w = h * 16 / 9
    w, h = min(w, FW), min(h, FH)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    L, T = min(max(cx - w / 2, 0), FW - w), min(max(cy - h / 2, 0), FH - h)
    return int(L), int(T), int(L + w), int(T + h)


def fit(im):
    return im.resize((PW, PH), Image.LANCZOS)


def tag(im, text, col):
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 40)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle((16, 16, 16 + tw + 40, 16 + 64), radius=12, fill=col)
    d.text((36, 24), text, font=f, fill='white')
    return im


def stack(panels, gap=10):
    out = Image.new('RGB', (PW, sum(p.height for p in panels) + gap * (len(panels) - 1)), (255, 255, 255))
    y = 0
    for p in panels:
        out.paste(p, (0, y))
        y += p.height + gap
    return out


def save(im, name):
    OUT.mkdir(exist_ok=True)
    im.save(OUT / name, quality=86)
    return name


def grid_sheet(secs, cols=2):
    """коллаж кадров (QA 10.09: 4 в ряд не читались при 350 px → 2 колонки; таймкод — в правом нижнем углу,
    где у заставок нет титра)"""
    tw = (PW - 10 * (cols + 1)) // cols
    th = tw * 9 // 16
    rows = (len(secs) + cols - 1) // cols
    out = Image.new('RGB', (PW, rows * (th + 10) + 10), (255, 255, 255))
    f = ImageFont.truetype(FONT, 40)
    for k, s in enumerate(secs):
        im = Image.open(HIRES / f'h{s + 1:04d}.jpg').convert('RGB').resize((tw, th), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        lw = d.textlength(tcs(s), font=f)
        d.rounded_rectangle((tw - lw - 34, th - 58, tw - 8, th - 8), radius=10, fill=(0, 0, 0))
        d.text((tw - lw - 21, th - 55), tcs(s), font=f, fill='white')
        out.paste(im, (10 + (k % cols) * (tw + 10), 10 + (k // cols) * (th + 10)))
    return out


def first_t_map():
    """кадр для плашки, которой нет на таймлайне отдельно: берём первое упоминание ключа"""
    f = W6 / 'terms_v6.json'
    out = {}
    if not f.exists():
        return out
    tj = json.load(open(f, encoding='utf-8'))
    for m in tj.get('terms', []):
        out.setdefault(f"term_{m['key']}.png", m['t'])
    for m in tj.get('locs', []):
        out.setdefault(f"map_{m['key']}.png", m['t'])
        if m.get('note'):
            out.setdefault(f"map_{m['key']}_note.png", m['t'])
    return out


FIRST_T = first_t_map()


def load_common():
    pr = json.load(open(M / 'pravki_v2.json'))
    audit = P.audit_or_die(W6 / 'audit_v6.json') or {'annotations': []}
    ann_by_tz = {a['tz']: a for a in audit['annotations']}
    ann_by_screen = {}
    for a in audit['annotations']:
        ann_by_screen.setdefault(a['screen_id'], []).append(a)
    seg_t = {}
    for s in json.load(open(REVIEW))['segments']:
        seg_t.setdefault(Path(s['source_path']).name, []).append(s['timeline_in_sec'])
    return pr, ann_by_tz, ann_by_screen, seg_t


# ═══════════════════ render ═══════════════════
def render():
    pr, ann_by_tz, ann_by_screen, seg_t = load_common()
    ovr = load_ovr()
    shots = json.load(open(M / 'shots_ids.json'))
    man = {'imgs': {}, 'tz': {}}

    def r_overlay(img, num, o, p):
        png = MOCK / img
        if not (png.exists() and img.endswith('.png')):
            return None
        ov = Image.open(png)
        if ov.mode != 'RGBA':
            return None
        # альфа-рамка без нижней полосы: там водяной знак «DRAFT · …» — он раздувал автокроп на весь кадр (QA 10.09)
        bb = ov.getchannel('A').crop((0, 0, FW, FH - 100)).point(lambda v: 255 if v > 8 else 0).getbbox()
        if not bb:
            return None
        frac = (bb[2] - bb[0]) * (bb[3] - bb[1]) / (FW * FH)
        if frac > 0.97:                                   # непрозрачный полный кадр — остаётся как есть
            return None
        sec = o.get('t')
        if sec is None:
            # 1) где плашка стоит на таймлайне · 2) первое упоминание из terms_v6 (плашки,
            #    которые живут только внутри групповых) · 3) таймкод самого ТЗ
            sec = seg_t[img][0] + 0.4 if seg_t.get(img) else FIRST_T.get(img)
        if sec is None:
            sec = tc_first(p.get('tc_range'))
        if sec is None:
            return None
        im = comp(frame4k(sec), png)
        box = norm169(o['box']) if o.get('box') else ((0, 0, FW, FH) if frac > 0.5 else box169(*bb, minw=o.get('minw', 0.45)))
        return {'preview': save(fit(im.crop(box)), f'dp_{Path(img).stem}.jpg'), 't': int(sec), 'kind': 'overlay'}

    def r_fix(img, num, o, p):
        key = 'ТЗ-' + Path(img).stem[len('fix_tz'):]
        a = ann_by_tz.get(key)
        if not a or re.search(r'_[AB]$', key):
            return None
        x, y, w, h = a['bbox']
        base = frame4k(path=a['frame'])
        box = norm169(o['box']) if o.get('box') else box169(x * FW, y * FH, (x + w) * FW, (y + h) * FH,
                                                            minw=o.get('minw', 0.40), padx=0.06, pady=0.10)
        panels = [tag(fit(base.crop(box)), T('c2.pv_tag_was'), C_RED)]                  # БЫЛО / WAS
        va, vb = MOCK / f'{Path(img).stem}_A.png', MOCK / f'{Path(img).stem}_B.png'
        variants = va.exists() and vb.exists()
        if variants:
            panels += [tag(fit(comp(base, va).crop(box)), T('c2.pv_tag_opt_a'), C_BLUE),  # ВАРИАНТ А / OPTION A
                       tag(fit(comp(base, vb).crop(box)), T('c2.pv_tag_opt_b'), C_BLUE)]
        else:
            panels.append(tag(fit(comp(base, MOCK / img).crop(box)), T('c2.pv_tag_now'), C_GREEN))  # СТАЛО / NOW
        return {'preview': save(stack(panels), f'dp_{Path(img).stem}.jpg'), 't': int(a['t0']), 'kind': 'fix',
                'variants': variants}

    def r_err(img, num, o, p):
        anns = ann_by_screen.get(Path(img).stem[len('v6_err_'):]) or []
        src = COMP / img
        if not (anns and src.exists()):
            return None
        xs0, ys0, xs1, ys1 = [], [], [], []
        for a in anns:
            x, y, w, h = a['bbox']
            cx, cy = (x + w / 2) * FW, (y + h / 2) * FH
            rx, ry = max(w * FW / 2 + 70, 160), max(h * FH / 2 + 60, 90)
            xs0.append(cx - rx), ys0.append(cy - ry), xs1.append(cx + rx), ys1.append(cy + ry)
        box = norm169(o['box']) if o.get('box') else box169(min(xs0), min(ys0), max(xs1), max(ys1),
                                                            minw=o.get('minw', 0.5), padx=0.03, pady=0.05)
        im = Image.open(src).convert('RGB').resize((FW, FH), Image.LANCZOS)
        return {'preview': save(fit(im.crop(box)), f'dp_{Path(img).stem}.jpg'), 't': int(anns[0]['t0']), 'kind': 'err'}

    wanted = {}
    for i, p in enumerate(pr['all']):
        if p.get('status') == 'rejected':
            continue
        num = f'ТЗ-{i + 1:02d}'
        for mr in p.get('material_rich') or []:
            if mr.get('img'):
                wanted.setdefault(mr['img'], (num, p))
        for img, _ in ATTACH.get(num, []):
            wanted.setdefault(img, (num, p))
    for img, (num, p) in wanted.items():
        o = ovr.get('img:' + img, {})
        if o.get('skip'):
            continue
        fn = r_fix if img.startswith('fix_') else r_err if img.startswith('v6_err_') else r_overlay
        try:
            e = fn(img, num, o, p)
        except Exception as ex:                                 # noqa: BLE001
            print('  !!', img, ex)
            continue
        if e:
            man['imgs'][img] = e
            print('✓', img, '→', e['preview'], flush=True)

    # ТЗ без единой картинки (с учётом ATTACH) → кадр в таймкод ТЗ
    for i, p in enumerate(pr['all']):
        if p.get('status') == 'rejected':
            continue
        num = f'ТЗ-{i + 1:02d}'
        o = ovr.get(num, {})
        has = num in ATTACH or any(mr.get('img') and (mr['img'] in shots or mr['img'] in man['imgs'])
                                   for mr in p.get('material_rich') or [])
        if has and not o.get('frames'):
            continue
        frames = o.get('frames') or ([{'t': tc_first(p.get('tc_range'))}] if tc_first(p.get('tc_range')) is not None else [])
        out = []
        for k, fr in enumerate(frames, 1):
            if fr.get('grid'):
                im = grid_sheet(fr['grid'])
            else:
                base = frame4k(fr['t'])
                im = fit(base.crop(norm169(fr['box']) if fr.get('box') else (0, 0, FW, FH)))
            cap = fr.get('cap') or (f"{tcs(fr['t'])} · {clean(p['title'])}" if fr.get('t') is not None else clean(p['title']))
            out.append({'preview': save(im, f"dp_{num.replace('ТЗ-', 'tz')}_{k}.jpg"), 't': fr.get('t'), 'cap': cap})
            print('✓', num, '→', out[-1]['preview'], flush=True)
        if out:
            man['tz'][num] = out

    json.dump(man, open(OUT / 'manifest.json', 'w'), ensure_ascii=False, indent=1)
    # контактный лист для QA
    h = ['<meta charset="utf-8"><title>Превью v7</title><style>body{font:14px Helvetica;background:#f4f4f4;margin:20px}'
         '.t{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 26px}.c{width:420px;background:#fff;padding:8px;border-radius:8px}'
         '.c img{width:420px}.c div{font-size:12px;margin-top:4px}h3{margin:18px 0 4px}</style>']
    for i, p in enumerate(pr['all']):
        if p.get('status') == 'rejected':
            continue
        num = f'ТЗ-{i + 1:02d}'
        cards = [(mr['img'], man['imgs'][mr['img']]['preview']) for mr in (p.get('material_rich') or [])
                 if mr.get('img') in man['imgs']]
        cards += [(img, man['imgs'][img]['preview']) for img, _ in ATTACH.get(num, []) if img in man['imgs']]
        cards += [('кадр ТЗ', e['preview']) for e in man['tz'].get(num, [])]
        if cards:
            h.append(f'<h3>{num} · {html.escape(clean(p["title"]))}</h3><div class="t">')
            h += [f'<div class="c"><img src="{pv}"><div>{html.escape(src)} → {pv}</div></div>' for src, pv in cards]
            h.append('</div>')
    (OUT / 'index.html').write_text('\n'.join(h))
    print(f"превью: {len(man['imgs'])} картинок + {sum(len(v) for v in man['tz'].values())} кадров ТЗ → {OUT / 'index.html'}")


# ═══════════════════ upload ═══════════════════
def upload():
    subprocess.run(['rclone', 'copy', str(OUT), SHOTS_REMOTE, '--include', 'dp_*.jpg', '--transfers', '4'], check=True)
    ls = subprocess.run(['rclone', 'lsjson', SHOTS_REMOTE, '--files-only', '--include', 'dp_*.jpg'],
                        capture_output=True, text=True, check=True)
    ids = {f['Name']: f['ID'] for f in json.loads(ls.stdout)}
    shots = json.load(open(M / 'shots_ids.json'))
    shots.update(ids)
    json.dump(shots, open(M / 'shots_ids.json', 'w'), ensure_ascii=False, indent=1)
    local = {p.name for p in OUT.glob('dp_*.jpg')}
    print(f'shots_ids: +{len(ids)} dp_* | без ID: {sorted(local - set(ids))}')


# ═══════════════════ apply ═══════════════════
def short_t(t):
    return re.sub(T('c2.pv_short_rx'), '', clean(t), flags=re.I)        # «Драфт: …» / «Draft: …» → «…»


def mk_cap(e, mr):
    tc = tcs(e['t']) if e.get('t') is not None else ''
    if e['kind'] == 'fix':
        return f"{tc} · {T('c2.pv_cap_wasvar') if e.get('variants') else T('c2.pv_cap_wasnow')}", False
    if e['kind'] == 'err':
        return f"{tc} · {T('c2.pv_cap_err')}", False
    st = short_t(mr.get('t'))
    if len(st) <= 90:
        return f'{tc} · {st}', True
    return f"{tc} · {st[:80].rsplit(' ', 1)[0]}…", False


def apply():
    d = json.load(open(M / 'pravki_v2.json'))
    man = json.load(open(OUT / 'manifest.json'))
    shots = json.load(open(M / 'shots_ids.json'))
    ovr = load_ovr()
    seg_t = {}
    for s in json.load(open(REVIEW))['segments']:
        seg_t.setdefault(Path(s['source_path']).name, []).append(s['timeline_in_sec'])
    n_prev = n_new = n_att = n_cap = 0
    for i, p in enumerate(d['all']):
        num = f'ТЗ-{i + 1:02d}'
        tz_tc = tcs(tc_first(p.get('tc_range'))) if tc_first(p.get('tc_range')) is not None else ''
        mats = [mr for mr in (p.get('material_rich') or []) if mr.get('gen') != 's12']
        for mr in mats:
            for k in ('preview', 'cap', 'cap_replaces_t'):
                mr.pop(k, None)
        for img, t in ATTACH.get(num, []):
            if not any(mr.get('img') == img for mr in mats):
                mats.append({'t': t, 'img': img, 'src': SRC_FIX, 'src_auto': True, 'gen': 's12'})
                n_att += 1
        for mr in mats:
            e = man['imgs'].get(mr.get('img') or '')
            if e and e['preview'] in shots:
                mr['preview'] = e['preview']
                o = ovr.get('img:' + mr['img'], {})
                if o.get('cap'):                              # подпись из QA (previews_v7.json) — «таймкод · что видно»
                    mr['cap'], mr['cap_replaces_t'] = o['cap'], len(clean(mr.get('t'))) <= 90
                else:
                    mr['cap'], mr['cap_replaces_t'] = mk_cap(e, mr)
                n_prev += 1
            elif mr.get('img') and mr['img'] in shots:          # QA 10.09: подпись «таймкод · что видно» под КАЖДОЙ картинкой
                o = ovr.get('img:' + mr['img'], {})
                mr['cap'], mr['cap_replaces_t'] = (o['cap'], True) if o.get('cap') else auto_cap(mr, seg_t, tz_tc)
                n_cap += 1
        for e in man['tz'].get(num, []):
            if e['preview'] in shots:
                mats.append({'t': e['cap'], 'preview': e['preview'], 'cap': e['cap'], 'cap_replaces_t': True, 'gen': 's12'})
                n_new += 1
        p['material_rich'] = mats
    json.dump(d, open(M / 'pravki_v2.json', 'w'), ensure_ascii=False, indent=1)
    print(f'apply: превью у {n_prev} материалов · подписей у прочих картинок {n_cap} · кадров ТЗ добавлено {n_new} · '
          f'драфтов привязано {n_att}')


_TCX = re.compile(r'@?(\d{1,2}:\d{2}(?:–\d{1,2}:\d{2})?)')


def auto_cap(mr, seg_t, tz_tc):
    """подпись «таймкод · что видно» для картинок без превью (фото, рефы, непрозрачные драфты):
    таймкод — из текста материала («Кадр @5:40 …»), иначе из раскладки таймлайна, иначе ТЗ"""
    t = clean(mr.get('t'))
    m = _TCX.search(t)
    tc = m.group(1) if m else (tcs(seg_t[mr['img']][0]) if seg_t.get(mr.get('img')) else tz_tc)
    what = _TCX.sub('', t, count=1) if m else t
    what = re.sub(T('c2.pv_auto_rx'), '', what, flags=re.I)
    what = clean(what).strip(' •·—-:')
    cap = f'{tc} · {what}' if tc and what else (what or tc)
    if len(cap) > 110:
        cap = cap[:105].rsplit(' ', 1)[0] + '…'
    return cap, len(t) <= 110


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else '--render'
    {'--render': render, '--upload': upload, '--apply': apply}[mode]()
