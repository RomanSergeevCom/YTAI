#!/usr/bin/env python3
"""
gen_access.py — сидер web/_data/access.json (клиент-гейт yt.rya.ae).

Пароли ЧЕЛОВЕКОЧИТАЕМЫЕ: `<словоканала>-<слово>` (напр. reflux-otter, realty-harbor) —
легко прочитать, запомнить, продиктовать, пошарить. Каналы и страницы группируются по
префиксу канала.

Идемпотентно:
  • существующие пароли НЕ перезаписываются (можно гонять после добавления страниц);
  • `--force` — перегенерировать ВСЕ пароли каналов/страниц заново (portal + bypass сохраняются);
  • portal (rs/winston) и personalBypass — SHA-256 (не показываются); каналы/страницы — plaintext
    (показываются в share-bar для шеринга, по решению);
  • при битом access.json — АВАРИЯ (не перезаписываю, чтобы не потерять кастомные пароли).

Запуск:  python3 gen_access.py [WEB_DIR=~/RYA/yt-rya-ae/web] [--force]
"""
import glob
import hashlib
import json
import os
import re
import secrets
import sys

CH_CODES = {"ytcr", "ytcg", "ytrf", "ytfp", "ytuvi", "ytmsen", "ytciv", "ytagefree", "ytch"}
ALIAS = {"civ": "ytciv", "ytrf01": "ytrf", "ytagefree10": "ytagefree"}
EXCLUDE_SUBSTR = ("/_generated/deck/", "/thumbnail/")
PORTAL_PWS = ["rs", "winston"]

# человекочитаемый префикс на канал (группирует пароли)
CHWORD = {
    "ytcr": "realty", "ytcg": "connect", "ytrf": "reflux", "ytfp": "pravmir",
    "ytuvi": "gems", "ytmsen": "neuro", "ytciv": "civ", "ytagefree": "elders", "ytch": "burodd",
}
# простые запоминающиеся слова (без двусмысленностей)
NOUNS = [
    "harbor", "otter", "cedar", "falcon", "anchor", "comet", "willow", "ember", "maple", "river",
    "raven", "lotus", "onyx", "quartz", "basalt", "cobalt", "indigo", "saffron", "amber", "jade",
    "cobra", "delta", "pine", "fjord", "tundra", "meadow", "canyon", "summit", "lagoon", "aurora",
    "zephyr", "cinder", "marble", "copper", "ivory", "coral", "topaz", "garnet", "opal", "beacon",
    "compass", "lantern", "harvest", "orchard", "thistle", "juniper", "spruce", "birch", "alder", "heron",
    "kestrel", "marlin", "walrus", "badger", "lynx", "ibex", "marten", "puffin", "narwhal", "axiom",
]


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def url_key(rel):
    p = "/" + rel.replace(os.sep, "/")
    return re.sub(r"index\.html?$", "", p, flags=re.I)


def channel_of(rel):
    seg = rel.replace(os.sep, "/").split("/")[0].lower()
    seg = ALIAS.get(seg, seg)
    return seg if seg in CH_CODES else None


def make_pw(ch, used):
    """`<chword>-<noun>`, уникальный среди used; при исчерпании — суффикс-цифра."""
    slug = CHWORD.get(ch, (ch or "page").replace("yt", "") or "page")
    pool = list(NOUNS)
    secrets.SystemRandom().shuffle(pool)
    for n in pool:
        pw = f"{slug}-{n}"
        if pw not in used:
            used.add(pw); return pw
    # пул исчерпан — добавляем цифры
    while True:
        pw = f"{slug}-{secrets.choice(NOUNS)}{secrets.randbelow(90) + 10}"
        if pw not in used:
            used.add(pw); return pw


def title_of(path, fallback):
    try:
        h = open(path, encoding="utf-8", errors="ignore").read(4000)
        m = re.search(r"<title>(.*?)</title>", h, re.I | re.S)
        if m:
            t = re.sub(r"\s+", " ", m.group(1)).strip()
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
    args = sys.argv[1:]
    force = "--force" in args
    pos = [a for a in args if not a.startswith("--")]
    web = pos[0] if pos else os.path.expanduser("~/RYA/yt-rya-ae/web")
    out = os.path.join(web, "_data", "access.json")

    acc = {}
    if os.path.exists(out):
        try:
            acc = json.load(open(out, encoding="utf-8"))
        except Exception as e:
            print(f"АВАРИЯ: {out} повреждён ({e}). НЕ перезаписываю, чтобы не потерять пароли.")
            print("Почини JSON вручную или удали файл, затем запусти снова.")
            sys.exit(1)

    if force:
        acc["channels"] = {}
        acc["pages"] = {}

    acc.setdefault("version", 1)
    acc["_note"] = ("Soft sharing-gate. ОДИН пароль на канал (plaintext, открывает все страницы канала, "
                    "показывается для шеринга). portal/bypass = SHA-256. Страницы пароля НЕ имеют. "
                    "Не настоящая защита — контент клиентский.")

    acc.setdefault("portal", {})
    acc["portal"]["label"] = "yt.rya.ae"
    acc["portal"]["hashes"] = [sha256(p) for p in PORTAL_PWS]

    new_bypass = None
    if not (acc.get("personalBypass") or {}).get("hash"):
        new_bypass = secrets.token_urlsafe(18)
        acc["personalBypass"] = {"hash": sha256(new_bypass)}

    names = load_channels_json(web)
    acc.setdefault("channels", {})
    acc.setdefault("pages", {})

    # used = все уже существующие пароли (для дедупа коллизий)
    used = set()
    for v in acc["channels"].values():
        if v.get("password"):
            used.add(v["password"])
    for v in acc["pages"].values():
        if v.get("password"):
            used.add(v["password"])

    added_ch, added_pg, kept, stripped = [], [], 0, 0

    for c in sorted(CH_CODES):
        if acc["channels"].get(c, {}).get("password"):
            kept += 1
            acc["channels"][c]["label"] = names.get(c, acc["channels"][c].get("label", c.upper()))
            continue
        acc["channels"][c] = {"label": names.get(c, c.upper()), "password": make_pw(c, used)}
        added_ch.append(c)

    for f in sorted(glob.glob(os.path.join(web, "**", "*.html"), recursive=True)):
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
            acc["pages"].pop(key, None)  # портал-уровень (/, /channel.html, …) → только portal-пароль
            continue
        prev = acc["pages"].get(key, {})
        fb = ch.upper() + " · " + os.path.basename(rel).replace(".html", "")
        title = prev.get("title") or title_of(f, fb)
        # ОДИН пароль на канал → у страниц пароля НЕТ, только title+channel (для оверлея и навигации)
        if "password" in prev:
            stripped += 1
        acc["pages"][key] = {"title": title, "channel": ch}
        if not prev:
            added_pg.append(key)

    acc["pages"] = {k: acc["pages"][k] for k in sorted(acc["pages"])}

    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(acc, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"access.json → {out}{'   [--force: пароли каналов перегенерированы]' if force else ''}")
    print(f"  channels: +{len(added_ch)} new ({', '.join(added_ch) or '—'}), {kept} kept — ОДИН пароль на канал")
    print(f"  pages:    +{len(added_pg)} new, {stripped} стрипнуто page-паролей, {len(acc['pages'])} total (title+channel, без паролей)")
    print(f"  portal:   {', '.join(PORTAL_PWS)} (SHA-256)")
    # коллизии только среди паролей каналов
    allpw = [v['password'] for v in acc['channels'].values() if v.get('password')]
    dups = {p for p in allpw if allpw.count(p) > 1}
    print(f"  collisions: {sorted(dups) if dups else 'нет'}")
    if new_bypass:
        print("\n  ╔══════════════════════════════════════════════════════════════╗")
        print("  ║  PERSONAL BYPASS SECRET (показывается ОДИН раз — сохрани!)   ║")
        print(f"  ║   {new_bypass}")
        print("  ║  Вводи как пароль на любом своём устройстве → больше не     ║")
        print("  ║  спросит никогда (переживает ротацию паролей).              ║")
        print("  ╚══════════════════════════════════════════════════════════════╝")
    else:
        print("  bypass:   сохранён существующий hash")


if __name__ == "__main__":
    main()
