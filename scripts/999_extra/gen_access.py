#!/usr/bin/env python3
"""
gen_access.py — сидер web/_data/access.json (клиент-гейт yt.rya.ae).

Идемпотентно:
  • portal.hashes  = SHA-256 от 'rs' и 'winston' (не показываются на сайте);
  • personalBypass = SHA-256 от длинного случайного секрета (печатается ОДИН раз
    при первом создании — сохрани его; вводится на каждом устройстве Романа,
    переживает ротацию паролей);
  • channels[<code>].password = plaintext (показывается в share-bar, по решению);
  • pages[<url>].password      = plaintext, авто-короткий код (можно вручную править).

Существующие записи НИКОГДА не перезаписываются — можно безопасно гонять после
добавления новых страниц. Ключи pages — нормализованный URL (как в site.js).

Запуск:  python3 gen_access.py [WEB_DIR=~/RYA/yt-rya-ae/web]
"""
import glob
import hashlib
import json
import os
import re
import secrets
import sys

ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"  # без 0/o/1/l/i
CH_CODES = {"ytcr", "ytcg", "ytrf", "ytfp", "ytuvi", "ytmsen", "ytciv", "ytagefree", "ytch"}
ALIAS = {"civ": "ytciv", "ytrf01": "ytrf", "ytagefree10": "ytagefree"}
EXCLUDE_SUBSTR = ("/_generated/deck/", "/thumbnail/")
PORTAL_PWS = ["rs", "winston"]


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def code(n=4):
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


def url_key(rel):
    """web-относительный путь файла → нормализованный URL (как site.js normPath)."""
    p = "/" + rel.replace(os.sep, "/")
    p = re.sub(r"index\.html?$", "", p, flags=re.I)
    return p


def channel_of(rel):
    seg = rel.replace(os.sep, "/").split("/")[0].lower()
    seg = ALIAS.get(seg, seg)
    return seg if seg in CH_CODES else None


def title_of(path, fallback):
    try:
        h = open(path, encoding="utf-8", errors="ignore").read(4000)
        m = re.search(r"<title>(.*?)</title>", h, re.I | re.S)
        if m:
            t = re.sub(r"\s+", " ", m.group(1)).strip()
            # отрезать хвосты "· yt.rya.ae", "— yt.rya.ae"
            t = re.split(r"\s*[·—|]\s*yt\.rya\.ae", t, flags=re.I)[0].strip()
            return t or fallback
    except Exception:
        pass
    return fallback


def load_channels_json(web):
    try:
        data = json.load(open(os.path.join(web, "_data", "channels.json"), encoding="utf-8"))
        return {c["id"].lower(): c.get("name", c["id"]) for c in data.get("channels", [])}
    except Exception:
        return {}


def main():
    web = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/RYA/yt-rya-ae/web")
    out = os.path.join(web, "_data", "access.json")

    # существующий конфиг (для идемпотентности)
    acc = {}
    if os.path.exists(out):
        try:
            acc = json.load(open(out, encoding="utf-8"))
        except Exception:
            acc = {}

    acc.setdefault("version", 1)
    acc["_note"] = ("Soft sharing-gate. portal/bypass = SHA-256; channels/pages = plaintext "
                    "(показываются для шеринга). Не настоящая защита — контент клиентский.")

    # portal
    acc.setdefault("portal", {})
    acc["portal"]["label"] = "yt.rya.ae"
    acc["portal"]["hashes"] = [sha256(p) for p in PORTAL_PWS]

    # personal bypass — создаём один раз
    new_bypass = None
    if not (acc.get("personalBypass") or {}).get("hash"):
        new_bypass = secrets.token_urlsafe(18)
        acc["personalBypass"] = {"hash": sha256(new_bypass)}

    names = load_channels_json(web)
    added_ch, added_pg, kept = [], [], 0

    # channels
    acc.setdefault("channels", {})
    for c in sorted(CH_CODES):
        if c in acc["channels"] and acc["channels"][c].get("password"):
            kept += 1
            acc["channels"][c]["label"] = names.get(c, acc["channels"][c].get("label", c.upper()))
            continue
        acc["channels"][c] = {"label": names.get(c, c.upper()), "password": f"{c.replace('yt','')}-{code()}"}
        added_ch.append(c)

    # pages
    acc.setdefault("pages", {})
    files = sorted(glob.glob(os.path.join(web, "**", "*.html"), recursive=True))
    for f in files:
        rel = os.path.relpath(f, web)
        relu = "/" + rel.replace(os.sep, "/")
        if any(s in relu for s in EXCLUDE_SUBSTR):
            continue
        try:
            head = open(f, encoding="utf-8", errors="ignore").read(2000)
            if "rya-site-optout" in head:
                continue
        except Exception:
            pass
        key = url_key(rel)
        ch = channel_of(rel)
        if ch is None:
            # портал-уровень (/, /channel.html, /production.html) — только portal-пароль (rs/winston)
            acc["pages"].pop(key, None)
            continue
        if key in acc["pages"] and acc["pages"][key].get("password"):
            kept += 1
            # обновить title/channel мягко
            acc["pages"][key].setdefault("channel", ch)
            continue
        seg0 = rel.replace(os.sep, "/").split("/")[0].lower()
        slug = (ch or ALIAS.get(seg0, seg0) or "page").replace("yt", "") or "page"
        fb = (ch.upper() if ch else seg0.upper()) + " · " + os.path.basename(rel).replace(".html", "")
        acc["pages"][key] = {
            "title": title_of(f, fb),
            "channel": ch,
            "password": f"{slug}-{code()}",
        }
        added_pg.append(key)

    # стабильная сортировка ключей pages
    acc["pages"] = {k: acc["pages"][k] for k in sorted(acc["pages"])}

    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(acc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"access.json → {out}")
    print(f"  channels: +{len(added_ch)} new  ({', '.join(added_ch) or '—'})")
    print(f"  pages:    +{len(added_pg)} new, {kept} kept, {len(acc['pages'])} total")
    print(f"  portal:   {', '.join(PORTAL_PWS)}  (SHA-256)")
    if new_bypass:
        print("\n  ╔══════════════════════════════════════════════════════════════╗")
        print("  ║  PERSONAL BYPASS SECRET (показывается ОДИН раз — сохрани!)   ║")
        print(f"  ║   {new_bypass}")
        print("  ║  Вводи как пароль на каждом своём устройстве → больше не    ║")
        print("  ║  спросит никогда (переживает ротацию паролей).              ║")
        print("  ╚══════════════════════════════════════════════════════════════╝")
    else:
        print("  bypass:   kept existing hash")


if __name__ == "__main__":
    main()
