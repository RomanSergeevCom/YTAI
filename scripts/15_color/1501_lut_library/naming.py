#!/usr/bin/env python3
"""
naming.py — latin ids for the LUT store, and metadata inference with evidence.

Two jobs:

1. slugify/build_id — every file in the store is [a-z0-9_]{1,64}.cube. Latin only
   is a hard project rule; the collection ships one cyrillic filename
   (DJI Pocket 4р D-Log Ocean.cube, U+0440 where a latin P belongs) and folder
   names in NFD, so normalisation is not optional.

2. classify — infer vendor/camera/gamma/family from three sources ranked by trust:
       comments inside the cube  >  archive path  >  file name
   and record WHICH source gave what in `evidence`. The collection proves why:
   DJI Action basic.cube carries "# Mavic 3 Pro, D-Log M, 2023-03-24" inside, so
   its own name lies about the camera. Anything where sources disagree comes back
   confidence="conflict" and must not reach a channel profile unsigned.

Naming canon (matches the approved plan):
    pre/      pre__{scope}__{target}.cube
    develop/  {vendor}_{camera}__{gamma}_{gamut}__rec709__{family}[__{variant}].cube
    look/     look__{name}[__{variant}].cube
    composed/ {CHANNEL}__{develop_short}__{look}.cube
    legacy/   {author_slug}/legacy_{author_slug}__{gamma}__rec709__{role}.cube
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
MAX_ID = 64
ID_RE = re.compile(r"^[a-z0-9_]{1,%d}$" % MAX_ID)

_TAX = None


def taxonomy() -> dict:
    global _TAX
    if _TAX is None:
        _TAX = json.loads((MODULE_DIR / "taxonomy.json").read_text(encoding="utf-8"))
    return _TAX


def nfc(s: str) -> str:
    """macOS hands out NFD; every comparison must normalise first or miss silently."""
    return unicodedata.normalize("NFC", s)


def has_cyrillic(s: str) -> bool:
    return any(unicodedata.name(ch, "").startswith("CYRILLIC") for ch in s)


def slugify(s: str) -> str:
    """Latin, lowercase, [a-z0-9_]. Transliterates cyrillic rather than dropping it."""
    tax = taxonomy()
    s = nfc(s).strip()
    out = []
    for ch in s:
        low = ch.lower()
        if low in tax["transliterate"]:
            out.append(tax["transliterate"][low])
        elif ch in tax["char_replace"]:
            out.append(tax["char_replace"][ch])
        elif ch.isalnum() and ch.isascii():
            out.append(low)
        else:
            out.append("_")
    slug = re.sub(r"_+", "_", "".join(out)).strip("_")
    return slug[:MAX_ID]


def token(s: str) -> str:
    """Tight token for a semantic block: S-Gamut3.Cine -> sgamut3cine, D-Log2 -> dlog2.

    Separators are DROPPED, not turned into underscores, because `__` is the block
    separator in the canon and `_` inside a block would blur the two apart.
    """
    return re.sub(r"[^a-z0-9]", "", slugify(s).lower())


def join_id(*blocks: str) -> str:
    """Join semantic blocks with `__`, skipping empties. Canon separator."""
    return "__".join(b for b in blocks if b)


def check_id(value: str) -> str:
    if not ID_RE.match(value):
        raise ValueError(f"id {value!r} is not [a-z0-9_]{{1,{MAX_ID}}}")
    return value


# ---------------------------------------------------------------- inference

def _find_token(text: str, table: dict) -> tuple[str | None, str | None]:
    """Longest matching key wins — 'Pocket 4P' must beat 'Pocket 4'."""
    best_key = None
    for key in sorted(table, key=len, reverse=True):
        if key.lower() in text.lower():
            best_key = key
            break
    return (table[best_key], best_key) if best_key else (None, None)


def classify(filename: str, archive: str = "", inner_path: str = "",
             comments: list[str] | None = None, stage: str = "develop") -> dict:
    """Infer metadata with provenance. Never asserts more than the sources support."""
    tax = taxonomy()
    comments = comments or []
    name = nfc(filename)
    stem = re.sub(r"\.cube$", "", name, flags=re.I)
    ctext = " ".join(comments)
    # ⚠️ Only the ZIP basename, never the whole relative path: the collection's top
    # folder is literally «Проявочные LUTs для LOG (sony, canon, panasonic, apple)»,
    # so a full-path haystack labels every Panasonic cube as Canon.
    archive_base = nfc(archive).split("/")[-1]
    haystack = f"{archive_base} {inner_path} {name}"

    meta = {
        "stage": stage,
        "vendor": None, "camera": None, "family": None, "variant": None,
        "in_gamma": None, "in_gamut": None,
        "out_gamma": "Rec.709", "out_gamut": "Rec.709",
        "evidence": [], "conflicts": [], "name_flags": [],
    }

    if has_cyrillic(stem):
        meta["name_flags"].append("cyrillic_in_name")
    if "  " in name:
        meta["name_flags"].append("double_space")
    if name != name.strip():
        meta["name_flags"].append("trailing_space")

    # --- Pre-LUT is its own stage regardless of which folder it shipped in.
    if re.search(r"pre[-_ ]?lut", stem, re.I):
        meta["stage"] = "pre"
        meta["out_gamma"], meta["out_gamut"] = "WDR", "wide"
        meta["evidence"].append(f"filename:{stem} contains Pre-LUT")

    # --- gamma: archive path first (the vendor zip is authoritative), then name.
    for key, (gamma, gamut) in tax["gamma_by_path"].items():
        if key.lower() in f"{archive} {inner_path}".lower():
            meta["in_gamma"], meta["in_gamut"] = gamma, gamut
            meta["evidence"].append(f"archive:{key} -> {gamma}")
            break
    if meta["in_gamma"] is None:
        for key, (gamma, gamut) in sorted(tax["gamma_by_name"].items(),
                                          key=lambda kv: -len(kv[0])):
            if key.lower() in name.lower():
                meta["in_gamma"], meta["in_gamut"] = gamma, gamut
                meta["evidence"].append(f"filename:{key} -> {gamma}")
                break

    # --- comments outrank everything; they are the generator's own statement.
    for pat, gamma in (("d-log2", "D-Log2"), ("d-log m", "D-Log M"),
                       ("s-log3", "S-Log3"), ("v-log", "V-Log")):
        if pat in ctext.lower():
            if meta["in_gamma"] and meta["in_gamma"].lower() != gamma.lower():
                meta["conflicts"].append(
                    f"комментарий внутри куба говорит {gamma}, имя/архив — {meta['in_gamma']}")
            meta["in_gamma"] = gamma
            if not meta["in_gamut"]:
                meta["in_gamut"] = tax["gamma_by_name"].get(gamma, [None, None])[1]
            meta["evidence"].append(f"comment:{gamma}")
            break

    vendor, vk = _find_token(haystack, tax["vendor_by_token"])
    if vendor:
        meta["vendor"] = vendor
        meta["evidence"].append(f"token:{vk} -> vendor {vendor}")

    camera, ck = _find_token(name, tax["camera_by_token"])
    if camera:
        meta["camera"] = camera
        meta["evidence"].append(f"filename:{ck} -> camera {camera}")
        # The collection proves filenames lie about the model.
        m = re.search(r"#\s*([A-Za-z0-9 ]+?),\s*[DVSFC]-?Log", ctext)
        if m and slugify(m.group(1)) != camera:
            meta["conflicts"].append(
                f"комментарий внутри куба называет «{m.group(1).strip()}», "
                f"а имя файла — «{ck}». Модель из имени НЕ принимается.")
            meta["camera"] = None

    # family/variant tokens belong to DEVELOP names only. In a look name the sign is
    # part of the name itself ("Contr +"), and words like "blue" are colours, not
    # families — Porsche xblue must not become look__blue.
    if meta["stage"] == "develop":
        family, fk = _find_token(stem, tax["family_by_token"])
        if family:
            meta["family"] = family
            meta["evidence"].append(f"filename:{fk} -> family {family}")

        variants = []
        if re.search(r"legacy", stem, re.I):
            variants.append("legacy")
        # The Panasonic pack ships two sibling folders: "Standard (No WB Offset)" and
        # "WB Offset - Green & Warm Boost". A plain substring match tags BOTH, which
        # collapses the two variants onto one id.
        if (re.search(r"\bWBO\b|WB Offset", haystack, re.I)
                and not re.search(r"No WB Offset", haystack, re.I)):
            variants.append("wboffset")
        if re.search(r"(?:^|[\s_])\+\s*$", stem):
            variants.append("plus")
        elif re.search(r"(?:^|[\s_])-\s*$", stem):
            variants.append("minus")
        meta["variant"] = "__".join(variants) if variants else None
        if {"plus", "push"} <= set(variants) or {"minus", "pull"} <= set(variants):
            meta["conflicts"].append(
                "нельзя смешивать авторский plus/minus и нашу лестницу push/pull")

    meta["confidence"] = "conflict" if meta["conflicts"] else (
        "verified" if len(meta["evidence"]) >= 2 else "inferred")
    return meta


# ---------------------------------------------------------------- id building

def build_id(meta: dict, fallback: str) -> str:
    """Compose the store id from inferred metadata; fall back to a slug of the name."""
    stage = meta.get("stage", "develop")
    stem = re.sub(r"\.cube$", "", nfc(fallback), flags=re.I)

    if stage == "pre":
        return check_id(join_id("pre", token(meta.get("in_gamma") or "any"), "wdr")[:MAX_ID])

    if stage == "look":
        return check_id(join_id("look", slugify(stem))[:MAX_ID])

    if stage == "legacy":
        return check_id(meta["id"])

    vendor = token(meta.get("vendor") or "unknown")
    camera = token(meta.get("camera") or "")
    head = f"{vendor}_{camera}" if camera else vendor
    gamma = token(meta.get("in_gamma") or "unknown")
    gamut = token(meta.get("in_gamut") or "unknown")
    candidate = join_id(head, f"{gamma}_{gamut}", "rec709",
                        token(meta.get("family") or ""),
                        meta.get("variant") or "")
    if not candidate.strip("_"):
        candidate = slugify(stem)
    return check_id(candidate[:MAX_ID].rstrip("_"))


def project_name(index: int, channel: str, short: str) -> str:
    """Name a cube gets inside a project: numeric prefix keeps it atop Lumetri's list."""
    return check_id(slugify(f"{index:02d}_{channel}_{short}"))


if __name__ == "__main__":
    samples = [
        ("Neutral A7s3.cube", "Sony SLOG3.zip", "SLOG3/", []),
        ("Neutral A7s3-Legacy.cube", "Sony SLOG3.zip", "SLOG3/", []),
        ("Utopia A7s3 Sl2sg3c.cube", "Sony SLOG2.zip", "SLOG2/", []),
        ("DJI OSMO Pocket 4P D-Log2 -.cube", "DJI Pocket 4p.zip", "DJI Pocket 4p/", []),
        ("DJI OSMO Pocket 4P D-Log2 +.cube", "DJI Pocket 4p.zip", "DJI Pocket 4p/", []),
        ("DJI Action basic.cube", "DJI ACTION.zip", "", ["# Mavic 3 Pro, D-Log M, 2023-03-24"]),
        ("Vision Canon-Legacy CL3.cube", "LOG film Canon.zip", "C-Log 3/", []),
        ("Slog3 to WDR Pre-LUT.cube", "Sony SLOG3.zip", "SLOG3/", []),
        ("Luna_I-Log_to_Rec709.cube", "", "", []),
    ]
    for fn, arc, inner, com in samples:
        m = classify(fn, arc, inner, com)
        print(f"{fn:<40} -> {build_id(m, fn):<52} [{m['confidence']}]")
        for c in m["conflicts"]:
            print(f"    ! {c}")
    for fn in ["GOLD.cube", "B&W 1.cube", "Contr +.cube", "Silver look contrast.cube"]:
        m = classify(fn, "", "", [], stage="look")
        print(f"{fn:<40} -> {build_id(m, fn):<52} [{m['confidence']}]")
