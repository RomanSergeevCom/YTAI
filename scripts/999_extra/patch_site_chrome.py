#!/usr/bin/env python3
"""
patch_site_chrome.py — внедрить единую шапку-навигацию + клиент-гейт
(site.css / site.js) во ВСЕ страницы yt.rya.ae. Идемпотентно по маркеру
rya-site-v1, версионно по ?v=ASSET_V (cache-busting). Первичный механизм:
прогонять после любой регенерации страниц.

Что делает на каждой web/**/*.html (кроме исключений):
  • в тег <html …> добавляет data-channel / data-page / data-rya-theme
    (core|brand) / data-rya-haschrome;
  • перед </head> — no-flash + <link site.css?v=N>;
  • перед </body> — <script site.js?v=N defer>.

Исключения: /_generated/deck/ , /thumbnail/ , файлы с маркером rya-site-optout.

Запуск:
  python3 patch_site_chrome.py [WEB_DIR=~/RYA/yt-rya-ae/web] [--dry-run] [--revert]
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from site_chrome import ASSET_V, MARK, head_block, body_script, html_attrs  # noqa: E402

CH_CODES = {"ytcr", "ytcg", "ytrf", "ytfp", "ytuvi", "ytmsen", "ytciv", "ytagefree", "ytch"}
ALIAS = {"civ": "ytciv", "ytrf01": "ytrf", "ytagefree10": "ytagefree"}
EXCLUDE_SUBSTR = ("/_generated/deck/", "/thumbnail/")


def channel_of(rel):
    seg = rel.replace(os.sep, "/").split("/")[0].lower()
    seg = ALIAS.get(seg, seg)
    return seg if seg in CH_CODES else None


def url_key(rel):
    p = "/" + rel.replace(os.sep, "/")
    return re.sub(r"index\.html?$", "", p, flags=re.I)


def classify(h):
    core = ("#0A0D16" in h) or ("--bg-card" in h)
    brand = ("Orbitron" in h) or ("Montserrat" in h) or ("data-theme=" in h) or ("#0A1420" in h)
    return "brand" if (brand and not core) else "core"


def has_chrome(h):
    return bool(re.search(r'class\s*=\s*["\'][^"\']*\b(topbar|hdr)\b', h))


def set_html_attrs(h, attrs):
    """Добавить attrs в первый тег <html …>, убрав прежние data-rya-*/data-channel/data-page."""
    m = re.search(r"<html\b[^>]*>", h, re.I)
    if not m:
        return h, False
    tag = m.group(0)
    inner = tag[5:-1]  # без "<html" и ">"
    inner = re.sub(r'\s+data-(channel|page|rya-theme|rya-haschrome)="[^"]*"', "", inner)
    newtag = "<html" + inner + " " + attrs + ">"
    return h[:m.start()] + newtag + h[m.end():], True


def reset_versions(h, v):
    return re.sub(r'(/assets/site\.(?:css|js)\?v=)\d+', r"\g<1>" + str(v), h)


def revert(h):
    h = re.sub(r'\s*<!-- ' + re.escape(MARK) + r' -->.*?<link rel="stylesheet" href="/assets/site\.css\?v=\d+">\s*',
               "\n", h, flags=re.S)
    h = re.sub(r'\s*<script src="/assets/site\.js\?v=\d+" defer></script>\s*', "\n", h)
    h = re.sub(r'\s+data-(channel|page|rya-theme|rya-haschrome)="[^"]*"', "", h)
    return h


def inject(h, rel):
    ch = channel_of(rel)
    theme = classify(h)
    attrs = html_attrs(ch, url_key(rel), theme, has_chrome(h))
    h, ok = set_html_attrs(h, attrs)
    # head
    i = h.lower().rfind("</head>")
    if i >= 0:
        h = h[:i] + head_block(ASSET_V) + h[i:]
    # body
    j = h.lower().rfind("</body>")
    if j < 0:
        j = h.lower().rfind("</html>")
    if j >= 0:
        h = h[:j] + body_script(ASSET_V) + h[j:]
    else:
        h = h + body_script(ASSET_V)
    return h, ch, theme


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    do_revert = "--revert" in args
    pos = [a for a in args if not a.startswith("--")]
    web = pos[0] if pos else os.path.expanduser("~/RYA/yt-rya-ae/web")

    patched, updated, already, excluded, reverted = [], [], [], [], []
    rel = lambda p: os.path.relpath(p, web)

    for f in sorted(glob.glob(os.path.join(web, "**", "*.html"), recursive=True)):
        relu = "/" + rel(f).replace(os.sep, "/")
        try:
            h = open(f, encoding="utf-8").read()
        except Exception as e:
            print("  ! read fail", rel(f), e); continue

        if any(s in relu for s in EXCLUDE_SUBSTR) or "rya-site-optout" in h[:2000]:
            excluded.append(f); continue

        if do_revert:
            if MARK in h:
                nh = revert(h)
                if not dry:
                    open(f, "w", encoding="utf-8").write(nh)
                reverted.append(f)
            continue

        if MARK in h:
            m = re.search(r"/assets/site\.css\?v=(\d+)", h)
            cur = int(m.group(1)) if m else -1
            if cur == ASSET_V:
                already.append(f); continue
            nh = reset_versions(h, ASSET_V)
            if not dry:
                open(f, "w", encoding="utf-8").write(nh)
            updated.append((f, cur)); continue

        nh, ch, theme = inject(h, rel(f))
        if not dry:
            open(f, "w", encoding="utf-8").write(nh)
        patched.append((f, ch or "—", theme))

    if do_revert:
        print(f"{'DRY ' if dry else ''}REVERTED ({len(reverted)}):")
        for p in reverted:
            print("  -", rel(p))
        print(f"EXCLUDED ({len(excluded)})")
        return

    print(f"{'DRY ' if dry else ''}PATCHED ({len(patched)}):  [channel · theme]")
    for p, ch, th in patched:
        print(f"  + {rel(p):45s} {ch:10s} {th}")
    if updated:
        print(f"VERSION-BUMP ({len(updated)}): v→{ASSET_V}")
        for p, old in updated:
            print(f"  ↑ {rel(p)}  (v{old}→v{ASSET_V})")
    print(f"ALREADY v{ASSET_V} ({len(already)})")
    print(f"EXCLUDED ({len(excluded)}):")
    for p in excluded:
        print("  ·", rel(p))


if __name__ == "__main__":
    main()
