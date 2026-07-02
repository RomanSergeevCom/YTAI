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

CH_CODES = {"ytcr", "ytcg", "ytcgru", "ytrf", "ytfp", "ytuvi", "ytmsen", "ytciv", "ytagefree", "ytch", "ytaz", "ytlab", "ytuae", "ytrscen", "ytep", "analiz", "playbook", "method", "wvp", "kb"}
ALIAS = {"civ": "ytciv", "ytrf01": "ytrf", "ytagefree10": "ytagefree"}
# Под-зоны со СВОИМ паролем, физически вложенные в путь другого канала:
# точный url-ключ страницы → код под-зоны (перебивает channel_of по первому сегменту).
# /ytciv/worldviewprojection/ живёт под ytciv, но гейтится отдельным паролем wvp.
PAGE_CHANNEL_OVERRIDE = {"/ytciv/worldviewprojection/": "wvp"}
EXCLUDE_SUBSTR = ("/_generated/deck/", "/thumbnail/")
MARK_COMMENT = "<!-- " + MARK + " -->"  # детект по КОММЕНТАРИЮ, не по голой строке (иначе контент со словом rya-site-v1 ложно «уже пропатчен»)
HTML_TAG_RE = re.compile(r"<html\b(?:\"[^\"]*\"|'[^']*'|[^>])*>", re.I)  # кавычко-устойчиво (атрибут со знаком > не ломает)
ATTR_STRIP_RE = re.compile(r'\s+data-(channel|page|rya-theme|rya-haschrome|rya-hub)="[^"]*"')


KB_GATED = {"playbook": "playbook", "method": "method", "yt-upload": "kb", "channel-launch": "playbook"}


def channel_of(rel):
    parts = rel.replace(os.sep, "/").split("/")
    seg = parts[0].lower()
    seg = ALIAS.get(seg, seg)
    if seg == "kb":
        if len(parts) >= 2 and parts[1] and not parts[1].lower().startswith("index.htm"):
            return KB_GATED.get(parts[1].lower())
        return "kb"
    return seg if seg in CH_CODES else None


def url_key(rel):
    p = "/" + rel.replace(os.sep, "/")
    return re.sub(r"index\.html?$", "", p, flags=re.I)


def classify(h):
    # core = страница реально на канонической палитре портала (#0A0D16) → безопасно
    # унифицировать токены. Всё остальное → brand: только навигация, палитру/шрифты
    # НЕ трогаем (имя токена --bg-card встречается и у брендовых — не сигнал).
    return "core" if "#0A0D16" in h else "brand"


def has_chrome(h):
    return bool(re.search(r'class\s*=\s*["\'][^"\']*\b(topbar|hdr)\b', h))


def _strip_html_attrs(tag):
    inner = ATTR_STRIP_RE.sub("", tag[5:-1])  # без "<html" и ">"
    return "<html" + inner + ">"


def set_html_attrs(h, attrs):
    """Добавить attrs в первый тег <html …>, убрав прежние data-rya-*/data-channel/data-page."""
    m = HTML_TAG_RE.search(h)
    if not m:
        return h, False
    newtag = "<html" + ATTR_STRIP_RE.sub("", m.group(0)[5:-1]) + " " + attrs + ">"
    return h[:m.start()] + newtag + h[m.end():], True


def reset_versions(h, v):
    return re.sub(r'(/assets/site\.(?:css|js)\?v=)\d+', r"\g<1>" + str(v), h)


def revert(h):
    h = re.sub(r'\s*<!-- ' + re.escape(MARK) + r' -->.*?<link rel="stylesheet" href="/assets/site\.css\?v=\d+">\s*',
               "\n", h, flags=re.S)
    h = re.sub(r'\s*<script src="/assets/site\.js\?v=\d+" defer></script>\s*', "\n", h)
    # снятие data-rya-* атрибутов ТОЛЬКО в теге <html> (не по всему документу)
    m = HTML_TAG_RE.search(h)
    if m:
        h = h[:m.start()] + _strip_html_attrs(m.group(0)) + h[m.end():]
    return h


def is_hub(key):
    # корень канала: путь ровно "/<код-канала>/" (один сегмент, и это канал, не алиас-редирект)
    m = re.fullmatch(r"/([A-Za-z0-9]+)/", key)
    return bool(m) and m.group(1).lower() in CH_CODES


def inject(h, rel):
    key = url_key(rel)
    ch = PAGE_CHANNEL_OVERRIDE.get(key) or channel_of(rel)
    theme = classify(h)
    attrs = html_attrs(ch, key, theme, has_chrome(h), is_hub(key))
    h, ok = set_html_attrs(h, attrs)
    # head: перед </head>; фолбэки — после <head>, перед <body>, в начало
    i = h.lower().rfind("</head>")
    if i >= 0:
        h = h[:i] + head_block(ASSET_V) + h[i:]
    else:
        mh = re.search(r"<head\b[^>]*>", h, re.I)
        mb = re.search(r"<body\b[^>]*>", h, re.I)
        if mh:
            h = h[:mh.end()] + head_block(ASSET_V) + h[mh.end():]
        elif mb:
            h = h[:mb.start()] + head_block(ASSET_V) + h[mb.start():]
        else:
            h = head_block(ASSET_V) + h
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
    # --only=SUBSTR — ограничить и patch, и revert файлами, чей относительный путь
    # содержит SUBSTR (защита: `--revert --only=ytrf/05/index.html` снимет только её,
    # а не все страницы).
    only = next((a.split("=", 1)[1] for a in args if a.startswith("--only=")), None)
    pos = [a for a in args if not a.startswith("--")]
    web = pos[0] if pos else os.path.expanduser("~/RYA/yt-rya-ae/web")

    patched, updated, already, excluded, reverted = [], [], [], [], []
    rel = lambda p: os.path.relpath(p, web)

    for f in sorted(glob.glob(os.path.join(web, "**", "*.html"), recursive=True)):
        relu = "/" + rel(f).replace(os.sep, "/")
        if only and only not in relu:
            continue
        try:
            h = open(f, encoding="utf-8").read()
        except Exception as e:
            print("  ! read fail", rel(f), e); continue

        if any(s in relu for s in EXCLUDE_SUBSTR) or "rya-site-optout" in h[:2000]:
            excluded.append(f); continue

        if do_revert:
            if MARK_COMMENT in h:
                nh = revert(h)
                if not dry:
                    open(f, "w", encoding="utf-8").write(nh)
                reverted.append(f)
            continue

        if MARK_COMMENT in h:
            m = re.search(r"/assets/site\.css\?v=(\d+)", h)
            if m:
                cur = int(m.group(1))
                if cur == ASSET_V:
                    already.append(f); continue
                nh = reset_versions(h, ASSET_V)
                if not dry:
                    open(f, "w", encoding="utf-8").write(nh)
                updated.append((f, cur)); continue
            # маркер есть, но css-ссылка отсутствует → битая инъекция: снять остатки и заново
            h = revert(h)

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
