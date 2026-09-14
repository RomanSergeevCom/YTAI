#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_mockups.py — 4K-мокапы графики в визуальном языке клиента (режим montage_tz).

Каждый экран: HTML (mockups/src/Gxx_V.html) → PNG 3840×2160 через infographic/render.py
(chrome-headless-shell). Экраны берутся из каталога плана — montage_plan.json → gfx_catalog[*].screens:
готовое тело `html` (+ `theme` dark|light|alpha) или раскладка `layout` + `text` (mockup_layouts.py).
Тексты экранов живут в плане, не в коде; цвета/шрифты — профиль канала `style.mockup.*` →
план `mockups.style` → дефолты первого проекта (YTEVO: Gilroy, #0B1220 / #F0EFEA / #D0021B).

QC раскладки — локально, без облака: скрипт в странице после загрузки шрифтов ищет текст
за title-safe (5 %) и переполненные блоки и пишет отчёт в body[data-qc]; прогон
chrome --dump-dom его читает. Превью: плашки с альфой композитятся на реальный кадр съёмки
(plan.mockups.bg_frame, на экран — bg_override). Слайды клиента (каталог kind=client, поле file)
не перерисовываются — берутся из mockups/client_slides как есть.

Папка мокапов — P.MOCK (карточка mockups_dir / окружение YTAI_MOCKUPS_DIR / 05_Review/mockups);
ассеты (логотипы, кадры-подложки, qr) — plan.mockups.assets (по умолчанию mockups/src) и
копируются в MOCK/src, если папка мокапов другая.

  python3 build_mockups.py                 # все экраны всех планов (главный + scenes)
  python3 build_mockups.py --only G08,G14  # перерендер части (манифест собирается целиком)
  python3 build_mockups.py --qc-only       # перегенерить HTML и перепроверить QC без PNG
  python3 build_mockups.py --list          # какие экраны есть в каталоге
"""
import argparse
import html as _html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mt_common import P, REVIEW_DIR, load_plan, scene_plans, gfx_catalog_list  # noqa: E402
from mockup_layouts import DEFAULT_STYLE, W, H, rgb, render_layout  # noqa: E402
from render import render, CHROME  # noqa: E402

MOCK = P.MOCK
SRC, THUMBS, CLIENT = MOCK / 'src', MOCK / 'thumbs', MOCK / 'client_slides'

BASE_CSS_T = """
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{W}px;height:{H}px;overflow:hidden}}
body{{font-family:GR,'Helvetica Neue',sans-serif;color:#fff;position:relative;-webkit-font-smoothing:antialiased}}
body.dark{{background:{navy}}}
body.light{{background:{light};color:{navy}}}
body.alpha{{background:transparent}}
.vig{{position:absolute;inset:0;background:radial-gradient(ellipse 70% 60% at 30% 35%,rgba({vig_rgb},.35),rgba({navy_rgb},0) 70%),radial-gradient(ellipse at 50% 50%,rgba(0,0,0,0) 55%,rgba(0,0,0,.5) 100%)}}
.ghost{{position:absolute;font-family:GB;line-height:.78;letter-spacing:-.02em;color:rgba(255,255,255,.045);white-space:nowrap;text-transform:uppercase}}
body.light .ghost{{color:rgba({navy_rgb},.05)}}
.draft{{position:absolute;right:60px;bottom:36px;font:30px GM;letter-spacing:.08em;color:rgba(255,255,255,.4)}}
body.light .draft{{color:rgba({navy_rgb},.4)}}
.logo{{position:absolute;right:192px;top:130px;height:110px}}
.over{{font:600 52px GBo;letter-spacing:.16em;text-transform:uppercase;color:{red}}}
body.dark .over{{color:{red_on_dark}}}
.red{{color:{red}}}
.rule{{width:180px;height:8px;background:{red};margin:44px 0}}
"""

QC_JS = """<script>
window.addEventListener('load',function(){document.fonts.ready.then(function(){
  var S=[192,108,3648,2052],out=[];
  document.querySelectorAll('.t,.box').forEach(function(el){
    var r=el.getBoundingClientRect(),n=el.getAttribute('data-n')||(el.textContent||el.tagName).trim().slice(0,22);
    if(r.width<1||r.height<1)return;
    if(r.left<S[0]-2||r.top<S[1]-2||r.right>S[2]+2||r.bottom>S[3]+2)
      out.push('за title-safe: '+n+' ['+[r.left,r.top,r.right,r.bottom].map(Math.round).join(',')+']');
    // у крупного текста при плотном интерлиньяже буквы выходят за строку — это задумано, не ошибка;
    // реальная беда — текст шире своего блока, а у карточек — содержимое выше карточки
    if(el.scrollWidth>el.clientWidth+4)out.push('шире блока: '+n);
    if(el.classList.contains('box')&&el.scrollHeight>el.clientHeight+4)out.push('не влезает по высоте: '+n);
  });
  document.body.setAttribute('data-qc',out.length?out.join(' | '):'ok');
});});
</script>"""


# ---------------- стиль / страница ----------------
def style_tokens(plan):
    """Дефолты → профиль канала style.mockup → план mockups.style. Бейдж DRAFT: план → профиль → дефолт."""
    S = dict(DEFAULT_STYLE)
    prof = P.profile('style.mockup', {}) or {}
    if isinstance(prof, dict):
        S.update(prof)
    mk = plan.get('mockups') or {}
    S.update(mk.get('style') or {})
    badge = mk.get('draft_badge') or (prof.get('draft_badge') if isinstance(prof, dict) else None) \
        or P.profile('style.draft_badge') or DEFAULT_STYLE['draft_badge']
    S['draft_badge'] = badge
    return S


def font_dirs(S):
    d = [Path(S.get('font_dir', '~/Library/Fonts')).expanduser(), Path.home() / 'Library/Fonts',
         Path('/Library/Fonts'), Path.home() / 'YTAI/fonts']
    return d


def font_face(S):
    faces = []
    for fam, f in S['fonts']:
        p = next((d / f'{f}.ttf' for d in font_dirs(S) if (d / f'{f}.ttf').exists()),
                 next((d / f'{f}.otf' for d in font_dirs(S) if (d / f'{f}.otf').exists()), None))
        if p is None:
            print(f'⚠️ шрифт {f} не найден в {[str(x) for x in font_dirs(S)]} — Chrome возьмёт фолбэк', flush=True)
            p = Path(S.get('font_dir', '~/Library/Fonts')).expanduser() / f'{f}.ttf'
        faces.append(f"@font-face{{font-family:{fam};src:url('{p.as_uri()}')}}")
    return '\n'.join(faces)


def base_css(S):
    return BASE_CSS_T.format(W=W, H=H, navy=S['navy'], light=S['light'], red=S['red'], red_on_dark=S['red_on_dark'],
                             navy_rgb=rgb(S['navy']), vig_rgb=rgb(S['vig_blue']))


def page(S, body, cls):
    return ("<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'><style>"
            + font_face(S) + base_css(S) + "</style></head>"
            + f"<body class='{cls}'>" + body + f'<div class="draft">{S["draft_badge"]}</div>' + QC_JS + "</body></html>")


# ---------------- экраны из планов ----------------
def collect_screens(plans):
    """[(gid, variant, title, body_fn, extra)] по всем планам; общий экран берётся из первого плана, где он описан."""
    seen, screens, clients = set(), [], {}
    S_main = style_tokens(plans[0])
    for plan in plans:
        # стиль и бейдж — от главного плана; план сцены перебивает только своим блоком mockups
        S = style_tokens(plan) if plan.get('mockups') else S_main
        for g in gfx_catalog_list(plan):
            gid = g['id']
            if g.get('kind') == 'client' and g.get('file') and gid not in clients:
                clients[gid] = (g['file'], g.get('title', gid))
            for sc in g.get('screens') or []:
                var = sc.get('variant', 'A')
                if (gid, var) in seen:
                    continue
                seen.add((gid, var))
                screens.append((gid, var, sc.get('title') or g.get('title', gid), sc, S))
    return screens, clients


def screen_body(sc, S):
    if sc.get('html') is not None:
        return sc['html'], sc.get('theme', 'dark')
    if sc.get('layout'):
        body, theme = render_layout(S, sc['layout'], sc.get('text') or {})
        return body, sc.get('theme') or theme
    raise SystemExit(f'экран {sc.get("variant")}: нет ни html, ни layout')


# ---------------- рендер / QC / превью ----------------
def qc(html_path):
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
                            f'--window-size={W},{H}', '--force-device-scale-factor=1',
                            '--allow-file-access-from-files', '--virtual-time-budget=5000',
                            f'--user-data-dir={td}', '--dump-dom', html_path.resolve().as_uri()],
                           capture_output=True, text=True, timeout=120)
    m = re.search(r'data-qc="([^"]*)"', r.stdout)
    return _html.unescape(m.group(1)) if m else 'нет отчёта QC'


def make_thumb(src_img, out, bg=None):
    im = Image.open(src_img).convert('RGBA')
    if bg is not None:
        base = bg.copy()
        base.alpha_composite(im)
        im = base
    im = im.convert('RGB')
    im.thumbnail((1600, 900))
    im.save(out, quality=86)


def make_qr(url, S):
    import qrcode
    q = qrcode.QRCode(border=1, box_size=20, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    q.make_image(fill_color=S['navy'], back_color='white').save(SRC / 'qr.png')


def sync_assets(assets_dir):
    """Ассеты (логотипы, подложки) → MOCK/src, если папка мокапов не совпадает с папкой ассетов."""
    assets_dir = Path(assets_dir)
    if not assets_dir.exists() or assets_dir.resolve() == SRC.resolve():
        return 0
    n = 0
    for f in assets_dir.iterdir():
        if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.svg', '.webp') and f.is_file():
            dst = SRC / f.name
            if not dst.exists() or dst.stat().st_size != f.stat().st_size:
                shutil.copy2(f, dst)
                n += 1
    return n


def load_bg(name, assets_dir):
    for d in (SRC, Path(assets_dir)):
        p = d / name
        if p.exists():
            return Image.open(p).convert('RGBA').resize((W, H))
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', default=None, help='id экранов через запятую (G08,G14)')
    ap.add_argument('--qc-only', action='store_true', help='перегенерить HTML с текущим QC и перепроверить — без рендера PNG')
    ap.add_argument('--plans', default=None, help='планы через запятую (по умолчанию plan_file карточки + его scenes)')
    ap.add_argument('--list', action='store_true', help='показать экраны каталога и выйти')
    a = ap.parse_args()
    only = set(a.only.split(',')) if a.only else None

    if a.plans:
        plans = [load_plan(x.strip()) for x in a.plans.split(',') if x.strip()]
    else:
        main_plan = load_plan()
        plans = [main_plan] + [load_plan(p) for p, _ in scene_plans(main_plan) if p.exists()]
    mk = plans[0].get('mockups') or {}
    S = style_tokens(plans[0])
    screens, clients = collect_screens(plans)
    if a.list:
        for gid, var, title, sc, _ in screens:
            print(f'{gid}_{var:<2} {"html" if sc.get("html") else sc.get("layout"):<12} {title}')
        for gid, (fname, title) in clients.items():
            print(f'{gid}_A  client:{fname:<8} {title}')
        print(f'экранов {len(screens)} · слайдов клиента {len(clients)} · папка {MOCK}')
        return
    if not screens and not clients:
        raise SystemExit('в каталоге плана нет экранов (gfx_catalog[*].screens) — нечего рендерить')

    for d in (SRC, THUMBS):
        d.mkdir(parents=True, exist_ok=True)
    assets_dir = Path(P.resolve(mk.get('assets', 'mockups/src')))
    n_copied = sync_assets(assets_dir)
    if n_copied:
        print(f'ассеты скопированы в {SRC}: {n_copied}')
    client_dir = Path(P.resolve(mk.get('client_slides', 'mockups/client_slides')))
    if not a.qc_only and mk.get('qr_url'):
        make_qr(mk['qr_url'], S)
    bg = load_bg(mk['bg_frame'], assets_dir) if mk.get('bg_frame') else None
    if bg is None:
        print('⚠️ plan.mockups.bg_frame не задан/не найден — превью плашек на однотонном фоне', flush=True)
        bg = Image.new('RGBA', (W, H), S['navy'])
    bg_override = mk.get('bg_override') or {}

    old = {}
    man_path = MOCK / 'manifest.json'
    if man_path.exists():
        for m in json.loads(man_path.read_text(encoding='utf-8')):
            old[(m['id'], m['variant'])] = m

    manifest = []
    for gid, var, title, sc, S_scr in screens:
        key = f'{gid}_{var}'
        body, cls = screen_body(sc, S_scr)
        alpha = cls == 'alpha'
        html_path, png = SRC / f'{key}.html', MOCK / f'{key}.png'
        if a.qc_only:
            html_path.write_text(page(S_scr, body, cls), encoding='utf-8')
            report = qc(html_path)
        elif only is None or gid in only:
            html_path.write_text(page(S_scr, body, cls), encoding='utf-8')
            render(html_path, png, size=f'{W}x{H}', alpha=alpha)
            report = qc(html_path)
            bgi = bg
            ov = sc.get('bg') or bg_override.get(gid)
            if alpha and ov:
                bgi = load_bg(ov, assets_dir) or bg
            make_thumb(png, THUMBS / f'{key}.jpg', bgi if alpha else None)
        elif png.exists():
            report = old.get((gid, var), {}).get('qc', 'не перепроверялся')
        else:
            report = 'не рендерился (--only)'
        manifest.append({'id': gid, 'variant': var, 'title': title, 'kind': 'new', 'alpha': alpha,
                         'png': f'{key}.png', 'thumb': f'thumbs/{key}.jpg', 'qc': report})
        print(f"{key:<7} {'α' if alpha else ' '} {title:<44} QC: {report}")

    for gid, (fname, title) in clients.items():
        key = f'{gid}_A'
        src = client_dir / fname
        if not src.exists():
            print(f'{key:<7}   {title:<44} ⚠️ нет слайда {src}')
            continue
        if CLIENT.resolve() != client_dir.resolve():
            CLIENT.mkdir(parents=True, exist_ok=True)
            if not (CLIENT / fname).exists():
                shutil.copy2(src, CLIENT / fname)
        make_thumb(src, THUMBS / f'{key}.jpg')
        manifest.append({'id': gid, 'variant': 'A', 'title': title, 'kind': 'client', 'alpha': False,
                         'png': f'client_slides/{fname}', 'thumb': f'thumbs/{key}.jpg', 'qc': 'слайд клиента'})
        print(f'{key:<7}   {title:<44} (слайд клиента, {fname})')

    man_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    bad = [m for m in manifest if m['kind'] == 'new' and m['qc'] != 'ok' and not m['qc'].startswith('не рендерился')]
    print(f"\nэкранов: {len(manifest)} · новых {sum(m['kind'] == 'new' for m in manifest)} · "
          f"слайдов клиента {len(clients)} · QC с замечаниями: {len(bad)}")
    print(f'→ {man_path}')


if __name__ == '__main__':
    main()
