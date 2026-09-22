#!/usr/bin/env python3
"""
lut_lib.py — the YTAI LUT library: import, validate, list, archive, mirror.

The library separates what the old single-stage setup fused together:
  pre      optional dynamic-range boost, applied BEFORE develop
  develop  log -> Rec.709, chosen DETERMINISTICALLY by camera+gamma. Technical.
  look     taste on top of a normal picture. One per channel = channel DNA.

Cubes live in store/ (not in git, ~670 MB) and are mirrored to the YTAI Shared
Drive so editors can take just their channel's cubes. manifest.json IS in git:
it is the versioned part, the bytes are immutable and restorable from Drive.

Usage:
  python3 lut_lib.py --import                 # dry run, prints what it WOULD do
  python3 lut_lib.py --import --apply
  python3 lut_lib.py --validate --deep
  python3 lut_lib.py --list --stage develop --camera "DJI Pocket 4 Pro"
  python3 lut_lib.py --legacy --apply         # archive the three Arthur Popov cubes
  python3 lut_lib.py --sync --push --apply    # mirror store/ to the Shared Drive

Nothing writes without --apply. The source collection (~/Downloads/Luts) is only
ever READ: zips are streamed, never extracted to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cube as C          # noqa: E402
import naming as N        # noqa: E402

MODULE_DIR = Path(__file__).resolve().parent
STORE = Path(os.environ.get("LUT_STORE", MODULE_DIR / "store"))
STATE = MODULE_DIR / "state"
MANIFEST = MODULE_DIR / "manifest.json"
DEFAULT_SRC = Path.home() / "Downloads" / "Luts"

DRIVE_TEAM_ID = "0AOtX-FTAK2yYUk9PVA"          # Shared Drive "YTAI"
DRIVE_PATH = "_color/lut_library"
STAGES = ("pre", "develop", "look", "composed", "legacy")

MONTHS_RU = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
             "августа", "сентября", "октября", "ноября", "декабря")


def die(msg: str, code: int = 2):
    print(f"\n✗ {msg}\n", file=sys.stderr)
    sys.exit(code)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def ts_compact() -> str:
    return time.strftime("%Y-%m-%d_%H%M")


def when_ru() -> str:
    t = time.localtime()
    return (f"{t.tm_mday} {MONTHS_RU[t.tm_mon - 1]} {t.tm_year}, "
            f"{t.tm_hour:02d}:{t.tm_min:02d}")


def save_json(path: Path, obj) -> None:
    """Atomic write — tmp then replace, so a crash never leaves half a manifest."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def empty_manifest() -> dict:
    return {
        "schema": "lut-manifest-v1",
        "_note": ("Источник правды по каждому кубу. Байты лежат в store/ (не в git), "
                  "сюда пишутся метаданные и хэши. Метаданные из ИМЕНИ файла "
                  "доказательством не считаются — смотри поля evidence и conflicts."),
        "version": 0,
        "generated": None,
        "tool": "scripts/15_color/1501_lut_library/lut_lib.py",
        "store_root": "store",
        "counts": {},
        "luts": [],
        "duplicates": [],
        "rejected": [],
    }


def load_manifest() -> dict:
    return load_json(MANIFEST, None) or empty_manifest()


def stamp_manifest(man: dict, bump: bool = True) -> dict:
    """Version + build time, per Roman's rule that every document carries both."""
    if bump:
        man["version"] = int(man.get("version") or 0) + 1
        man["generated"] = now_iso()
        man["generated_ru"] = when_ru()
    return man


# ================================================================= import

def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def folder_stage(top: str, tax: dict) -> str | None:
    """Classify by the collection's own top folder. Prefix match on collapsed spaces:
    the collection has a trailing space in «…Luna » and a double space in
    «Universal LUTs  от Серёжи 7», so equality would miss both."""
    flat = re.sub(r"\s+", " ", nfc(top)).strip()
    for skip in tax["skip_folders"]:
        if flat.startswith(re.sub(r"\s+", " ", skip).strip()):
            return None
    for prefix, stage in tax["folder_stage"].items():
        if flat.startswith(prefix):
            return stage
    return None


def zip_member_name(info: zipfile.ZipInfo) -> tuple[str, bool]:
    """Decode a zip entry name. Returns (name, utf8_flag_was_missing).

    The collection has one entry whose UTF-8 flag is not set while the bytes ARE
    UTF-8 (a cyrillic «р» inside «DJI Pocket 4р D-Log Ocean.cube»). Python then
    decodes it as cp437 and hands back mojibake; round-tripping the bytes fixes it.
    """
    if info.flag_bits & 0x800:
        return nfc(info.filename), False
    # Most entries leave the flag clear simply because their names are ASCII — that
    # is legal and uninteresting. Only report it when it actually changed the name.
    try:
        fixed = nfc(info.filename.encode("cp437").decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError):
        return nfc(info.filename), not info.filename.isascii()
    return fixed, fixed != nfc(info.filename)


def iter_collection(src: Path, tax: dict):
    """Yield (stage, basename, bytes, origin) for every importable cube. READ ONLY.

    zips are streamed with zf.open/read — nothing is ever extracted to disk.
    """
    for path in sorted(src.rglob("*")):
        if path.is_dir() or path.name.startswith("._"):
            continue
        rel = path.relative_to(src)
        stage = folder_stage(rel.parts[0], tax)
        if stage is None:
            continue

        if path.suffix.lower() == ".zip":
            try:
                zf = zipfile.ZipFile(path)
            except zipfile.BadZipFile:
                yield ("__error__", path.name, b"", {"error": "bad zip"})
                continue
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name, flag_missing = zip_member_name(info)
                base = name.split("/")[-1]
                if "__MACOSX" in name or base.startswith("._") or base == ".DS_Store":
                    continue
                if not base.lower().endswith(".cube"):
                    continue
                inner = "/".join(name.split("/")[:-1])
                yield (stage, base, zf.read(info), {
                    "kind": "zip", "archive": str(rel), "member": name,
                    "inner": inner, "zip_utf8_flag_missing": flag_missing,
                })
        elif path.suffix.lower() == ".cube":
            yield (stage, nfc(path.name), path.read_bytes(), {
                "kind": "loose", "archive": None,
                "member": str(rel), "inner": str(rel.parent),
                "zip_utf8_flag_missing": False,
            })


def do_import(args) -> int:
    tax = N.taxonomy()
    src = Path(args.src or DEFAULT_SRC).expanduser().resolve()
    if not src.is_dir():
        die(f"коллекции нет: {src}")
    if STORE.resolve() in src.parents or STORE.resolve() == src:
        die("store внутри коллекции — импорт читал бы собственный вывод")

    man = empty_manifest()
    by_sha: dict[str, dict] = {}
    counts = {"read": 0, "skipped_iphone": 0, "appledouble": 0,
              "cyrillic": 0, "zip_utf8_flag_missing": 0, "conflict": 0}
    per_stage: dict[str, int] = {}
    dup_groups: dict[str, list] = {}
    errors = []

    # Count what we deliberately leave behind, so the number is stated not implied.
    for p in src.rglob("*.cube"):
        if p.name.startswith("._"):
            continue
        if folder_stage(p.relative_to(src).parts[0], tax) is None:
            counts["skipped_iphone"] += 1

    for stage, base, data, origin in iter_collection(src, tax):
        if stage == "__error__":
            errors.append(origin)
            continue
        counts["read"] += 1
        if origin.get("zip_utf8_flag_missing"):
            counts["zip_utf8_flag_missing"] += 1
        # Count non-latin names BEFORE dedupe: the one cyrillic file in the collection
        # is a byte-duplicate, so counting after dedupe silently reports zero.
        if N.has_cyrillic(base):
            counts["cyrillic"] += 1

        sha = hashlib.sha256(data).hexdigest()
        if sha in by_sha:
            keeper = by_sha[sha]
            keeper["aliases"].append(base)
            dup_groups.setdefault(sha, [keeper["orig_name"]]).append(base)
            continue

        try:
            cb = C.parse_cube(data)
        except C.CubeError as exc:
            man["rejected"].append({"orig_name": base, "origin": origin, "why": str(exc)})
            continue

        meta = N.classify(base, origin.get("archive") or "", origin.get("inner") or "",
                          cb.comments, stage=stage)
        lut_id = N.build_id(meta, base)
        if meta["conflicts"]:
            counts["conflict"] += 1

        st = meta["stage"]
        per_stage[st] = per_stage.get(st, 0) + 1
        metrics = C.measure(cb)
        entry = {
            "id": lut_id,
            "stage": st,
            "file": f"{st}/{lut_id}.cube",
            "sha256": sha,
            "bytes": len(data),
            "size": cb.size,
            "dialect": cb.dialect,
            "title": cb.title,
            "domain": {"min": list(cb.domain_min), "max": list(cb.domain_max),
                       "declared": cb.domain_declared},
            "input": {"gamma": meta["in_gamma"], "gamut": meta["in_gamut"]},
            "output": {"gamma": meta["out_gamma"], "gamut": meta["out_gamut"]},
            "vendor": meta["vendor"],
            "camera": [meta["camera"]] if meta["camera"] else [],
            "family": meta["family"],
            "variant": meta["variant"],
            "comments": cb.comments[:8],
            "orig_name": base,
            "origin": origin,
            "aliases": [],
            "name_flags": meta["name_flags"],
            "evidence": meta["evidence"],
            "conflicts": meta["conflicts"],
            "confidence": meta["confidence"],
            "metrics": {k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in metrics.items()},
            "status": "shelf",
            "checked_by": None,
            "imported": now_iso(),
        }
        by_sha[sha] = entry
        man["luts"].append(entry)

        if args.apply:
            dest = STORE / entry["file"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_bytes(data)                 # byte-identical copy, no re-serialise
            os.replace(tmp, dest)
            os.chmod(dest, 0o444)                 # library cubes are not hand-editable

    # id collisions mean a hole in the taxonomy — report, never silently suffix away.
    seen_ids: dict[str, str] = {}
    collisions = []
    for e in man["luts"]:
        if e["id"] in seen_ids:
            collisions.append((e["id"], seen_ids[e["id"]], e["orig_name"]))
        seen_ids[e["id"]] = e["orig_name"]

    man["duplicates"] = [{"sha256": s, "names": n} for s, n in dup_groups.items()]
    man["counts"] = {**per_stage, "unique": len(man["luts"])}
    stamp_manifest(man, bump=args.apply)

    unique = len(man["luts"])
    print(f"\nИМПОРТ {'· ЗАПИСАНО' if args.apply else '· сухой прогон (без --apply ничего не записано)'}")
    print(f"  источник:        {src}   (читается, НЕ меняется)")
    print(f"  прочитано:       {counts['read']} .cube")
    print(f"  пропущено:       {counts['skipped_iphone']}  «для съёмки на айфон» — вшиваются при съёмке")
    print(f"  уникальных:      {unique}")
    print(f"  дубли:           {len(dup_groups)} групп, "
          f"{sum(len(v) - 1 for v in dup_groups.values())} лишних файлов")
    print(f"  ступени:         " + " · ".join(f"{k} {v}" for k, v in sorted(per_stage.items())))
    print(f"  ⚠ кириллица в имени:          {counts['cyrillic']}")
    print(f"  ⚠ сломанный UTF-8-флаг в zip: {counts['zip_utf8_flag_missing']}")
    print(f"  ⚠ конфликт имя↔комментарий:   {counts['conflict']}")
    if collisions:
        print(f"  ⚠ КОЛЛИЗИИ id:               {len(collisions)} — дыра в taxonomy.json:")
        for cid, a, b in collisions[:10]:
            print(f"        {cid}  ←  {a}  и  {b}")
    if man["rejected"]:
        print(f"  ⚠ не разобрано:              {len(man['rejected'])}")
        for r in man["rejected"][:5]:
            print(f"        {r['orig_name']}: {r['why']}")
    if errors:
        print(f"  ⚠ битые архивы:              {len(errors)}")

    if args.apply:
        save_json(MANIFEST, man)
        STATE.mkdir(parents=True, exist_ok=True)
        save_json(STATE / "log" / f"{ts_compact()}_import.json",
                  {"counts": counts, "per_stage": per_stage,
                   "duplicates": len(dup_groups), "collisions": collisions,
                   "unique": unique, "at": now_iso()})
        print(f"\n  → store/ наполнен, манифест v{man['version']} записан")
    else:
        print(f"\n  → ничего не записано. Повтори с --apply")
    return 0


# ================================================================= validate

def do_validate(args) -> int:
    tax = N.taxonomy()
    man = load_manifest()
    if not man["luts"]:
        die("манифест пуст — сначала `--import --apply`")

    errors, warns = [], []
    checked = 0
    for e in man["luts"]:
        if args.stage and e["stage"] != args.stage:
            continue
        if args.id and e["id"] != args.id:
            continue
        checked += 1
        path = STORE / e["file"]

        if not path.exists():
            errors.append(f"{e['id']}: файла нет — {path}")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != e["sha256"]:
            errors.append(f"{e['id']}: sha256 разошёлся с манифестом")
            continue
        if not N.ID_RE.match(e["id"]):
            errors.append(f"{e['id']}: имя не латиница/не канон")
        if N.has_cyrillic(path.name):
            errors.append(f"{e['id']}: кириллица в имени файла")

        if not args.deep:
            continue
        try:
            cb = C.parse_cube(data, path)
        except C.CubeError as exc:
            errors.append(str(exc))
            continue

        m = C.measure(cb)
        q = tax["quality"]
        # A Pre-LUT exists to EXPAND range beyond 1.0 — that is its whole job
        # (the WDR passthrough peaks at 1.05). Flagging it as an error would be
        # flagging the feature.
        if m["out_of_range"] > q["out_of_range_error"] and not cb.domain_declared:
            if e["stage"] == "pre":
                warns.append(f"{e['id']}: {m['out_of_range']*100:.1f}% значений вне [0,1] "
                             f"(max {m['value_max']:.3f}) — для Pre-LUT это норма, он и "
                             f"расширяет диапазон")
            else:
                errors.append(f"{e['id']}: {m['out_of_range']*100:.1f}% значений вне [0,1] "
                              f"без объявленного DOMAIN")
        if e["stage"] in q["monotonic_required_for"]:
            if m["dip_total255"] > q["dip_total255_error"]:
                errors.append(f"{e['id']}: нейтраль заваливается на {m['dip_total255']:.1f}/255 "
                              f"суммарно — перевёрнутая тональная кривая")
            elif m["dip_max255"] > q["dip_max255_warn"]:
                warns.append(f"{e['id']}: нейтраль дрожит на {m['dip_max255']:.2f}/255 — "
                             f"это квантование, а не поломка")
        # Black crush is a real defect at ANY stage and it is validated against
        # footage: Neutral A7s3 crushes 12.3% of the wedge and crushed 32 of 132
        # real frames, while Utopia/IceBlue/Jamaica crush 0.0% and crushed none.
        if m["black_share"] > q["black_share_warn"]:
            warns.append(f"{e['id']}: топит {m['black_share']*100:.1f}% серого клина в чёрный")
        # Blown white is a defect only for a look, whose input IS Rec.709 where 1.0
        # means white. A develop reaches white around input 0.86 by design — that is
        # highlight rolloff, and warning about it would be warning about the feature.
        if e["stage"] == "look" and m["white_share"] > q["white_share_warn"]:
            warns.append(f"{e['id']}: выжигает {m['white_share']*100:.1f}% серого клина")

        # Stage detector is a FLAG, never a verdict — see taxonomy stage_detect._verdict.
        sd = tax["stage_detect"]
        if e["stage"] == "develop" and m["slope_mid"] <= sd["slope_mid_look_max"]:
            warns.append(f"{e['id']}: лежит в проявочных, а ведёт себя как look "
                         f"(наклон {m['slope_mid']:.2f} ≤ {sd['slope_mid_look_max']})")
        if e["stage"] == "look" and m["slope_mid"] >= sd["slope_mid_develop_min"]:
            warns.append(f"{e['id']}: лежит в покрасочных, а ведёт себя как проявка "
                         f"(наклон {m['slope_mid']:.2f} ≥ {sd['slope_mid_develop_min']})")

    shas = {}
    for e in man["luts"]:
        if e["sha256"] in shas:
            errors.append(f"дубль в store: {e['id']} == {shas[e['sha256']]}")
        shas[e["sha256"]] = e["id"]

    print(f"\nВАЛИДАЦИЯ{' --deep' if args.deep else ''}  ·  проверено {checked} кубов")
    print(f"  манифест v{man.get('version')} от {man.get('generated')}")
    for w in warns:
        print(f"  ⚠  {w}")
    for x in errors:
        print(f"  ✗  {x}")
    print(f"\n  ошибок {len(errors)} · предупреждений {len(warns)}")
    if warns and not errors:
        print("  Предупреждения — это повод посмотреть глазами, а не поломка.\n"
              "  Автоклассификатор ступени отвергнут как решающий: см. taxonomy.json → stage_detect.")
    STATE.mkdir(parents=True, exist_ok=True)
    save_json(STATE / "validate_report.json",
              {"at": now_iso(), "checked": checked, "errors": errors, "warns": warns})
    return 2 if errors else (1 if warns else 0)


# ================================================================= list

def do_list(args) -> int:
    man = load_manifest()
    rows = man["luts"]
    if args.stage:
        rows = [r for r in rows if r["stage"] == args.stage]
    if args.camera:
        rows = [r for r in rows if any(args.camera.lower() in str(c).lower()
                                       for c in r.get("camera", []))]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    print(f"\n{'id':<54}{'ст':>4}{'сетка':>6}{'вход':>22}{'увер':>10}  автор/источник")
    for r in sorted(rows, key=lambda r: (r["stage"], r["id"])):
        gin = f"{r['input']['gamma'] or '?'}/{r['input']['gamut'] or '?'}"
        mark = {"verified": "✓", "inferred": "~", "conflict": "!"}.get(r["confidence"], "?")
        print(f"{r['id'][:53]:<54}{r['stage'][:3]:>4}{r['size']:>5}³{gin[:21]:>22}"
              f"{mark + ' ' + r['confidence']:>10}  {(r['origin'].get('archive') or '')[:30]}")
    print(f"\n  всего {len(rows)}   "
          f"(! конфликт — метаданные из имени и из куба расходятся, в профиль канала не годится)")
    return 0


# ================================================================= legacy

def do_legacy(args) -> int:
    """Archive the three channel cubes with attribution, touching nothing in place."""
    tax = N.taxonomy()
    spec = tax["legacy_ytai"]
    known = spec["cubes"]

    search = [
        Path.home() / "YTAI/scripts/05_editing/0500_uxp/LUTs",
        Path.home() / "YTAI/scripts/05_editing/LUTs",
        Path.home() / "Library/Application Support/Adobe/Common/LUTs/Creative/YTAI",
        Path.home() / "Library/Application Support/Adobe/Common/LUTs/Input",
    ]
    found: dict[str, list[Path]] = {}
    for d in search:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.cube")):
            md5 = hashlib.md5(p.read_bytes()).hexdigest()
            if md5 in known:
                found.setdefault(md5, []).append(p)

    print("\nАРХИВ СТАРЫХ КУБОВ КАНАЛА")
    print(f"  атрибуция: {spec['author']}  ({spec['_note']})")
    missing = [k for k in known if k not in found]
    for md5, paths in found.items():
        info = known[md5]
        print(f"\n  {info['id']}")
        print(f"     роль {info['role']} — {info['intent']}")
        print(f"     старые имена: {', '.join(info['aliases'])}")
        print(f"     найдено копий: {len(paths)}")
        for p in paths:
            print(f"        {p}")
    if missing:
        print(f"\n  ⚠ не найдено на диске: {len(missing)} из {len(known)}")

    if not args.apply:
        print("\n  → ничего не записано. Повтори с --apply")
        return 0

    dest_dir = STORE / "legacy" / spec["author_slug"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    man = load_manifest()
    for md5, paths in found.items():
        info = known[md5]
        src = paths[0]
        dest = dest_dir / f"{info['id']}.cube"
        shutil.copyfile(src, dest)
        os.chmod(dest, 0o444)
        data = dest.read_bytes()
        cb = C.parse_cube(data, dest)
        man["luts"] = [e for e in man["luts"] if e["id"] != info["id"]]
        man["luts"].append({
            "id": info["id"], "stage": "legacy",
            "file": f"legacy/{spec['author_slug']}/{info['id']}.cube",
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "md5_legacy": md5, "size": cb.size, "dialect": cb.dialect, "title": cb.title,
            "input": {"gamma": "S-Log3", "gamut": "S-Gamut3.Cine"},
            "output": {"gamma": "Rec.709", "gamut": "Rec.709"},
            "camera": ["Sony FX3", "Sony ZV-E1"],
            "variant": info["role"], "intent": info["intent"],
            "author": spec["author"], "author_slug": spec["author_slug"],
            "author_note": spec["_note"],
            "confidence": "inferred",
            "metrics": {k: (round(v, 4) if isinstance(v, float) else v)
                        for k, v in C.measure(cb).items()},
            "aliases": info["aliases"],
            "found_at": [str(p) for p in paths],
            "status": "archived",
            "notes": ("В сданных проектах НЕ переименовывать и НЕ удалять: имя лута = "
                      "имя Look в доноре Premiere, переименование ломает готовые таймлайны."),
            "imported": now_iso(),
        })

    (dest_dir / "ATTRIBUTION.md").write_text(
        f"# Старые луты канала YTAI — {spec['author']}\n\n"
        f"Собрано {when_ru()} инструментом `lut_lib.py --legacy`.\n\n"
        f"{spec['_note']}\n\n"
        f"{spec['_naming_why']}\n\n"
        + "\n".join(
            f"- `{i['id']}.cube` — роль **{i['role']}**, {i['intent']}.\n"
            f"  Старые имена: {', '.join('`%s`' % a for a in i['aliases'])}."
            for i in known.values())
        + "\n\n⚠️ В сданных проектах эти кубы не переименовывать и не удалять:\n"
          "имя лута = имя Look в доноре Premiere.\n",
        encoding="utf-8")

    stamp_manifest(man)
    save_json(MANIFEST, man)
    print(f"\n  → {len(found)} куба в store/legacy/{spec['author_slug']}/, "
          f"ATTRIBUTION.md записан, манифест v{man['version']}")
    print("  Ничего на местах не переименовано и не удалено.")
    return 0


# ================================================================= sync

def do_sync(args) -> int:
    if not shutil.which("rclone"):
        die("rclone не найден в PATH")
    remote = f"gdrive,team_drive={DRIVE_TEAM_ID}:{DRIVE_PATH}"
    if args.pull:
        src, dst = remote, str(STORE)
    else:
        src, dst = str(STORE), remote
    cmd = ["rclone", "copy", src, dst,
           "--transfers", "4", "--checkers", "8",
           "--drive-chunk-size", "64M", "--drive-pacer-min-sleep", "100ms",
           "--stats", "20s", "--stats-one-line"]
    if not args.apply:
        cmd.append("--dry-run")
    print(f"\n{'ЗЕРКАЛО ← Drive' if args.pull else 'ЗЕРКАЛО → Drive'}"
          f"{'' if args.apply else '  · сухой прогон'}")
    print(f"  {src}\n  → {dst}\n")
    return subprocess.run(cmd).returncode


# ================================================================= cli

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Библиотека лутов YTAI — импорт, проверка, архив, зеркало.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--import", dest="do_import", action="store_true",
                      help="импортировать коллекцию в store/")
    mode.add_argument("--validate", action="store_true", help="проверить store и манифест")
    mode.add_argument("--list", dest="do_list", action="store_true", help="показать библиотеку")
    mode.add_argument("--legacy", action="store_true",
                      help="собрать три старых куба канала в архив с атрибуцией")
    mode.add_argument("--sync", action="store_true", help="зеркало store ↔ Shared Drive YTAI")

    p.add_argument("--apply", action="store_true",
                   help="без него ничего не записывается")
    p.add_argument("--src", help=f"коллекция-источник (по умолчанию {DEFAULT_SRC})")
    p.add_argument("--deep", action="store_true", help="--validate: считать метрики по каждому кубу")
    p.add_argument("--stage", choices=STAGES, help="фильтр по ступени")
    p.add_argument("--id", help="фильтр по id")
    p.add_argument("--camera", help="фильтр по камере")
    p.add_argument("--json", action="store_true", help="--list: выдать JSON")
    p.add_argument("--push", action="store_true", help="--sync: наверх (по умолчанию)")
    p.add_argument("--pull", action="store_true", help="--sync: вниз, восстановить store")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    C.selftest()                      # axis order is load-bearing for every writer
    if args.do_import:
        return do_import(args)
    if args.validate:
        return do_validate(args)
    if args.do_list:
        return do_list(args)
    if args.legacy:
        return do_legacy(args)
    if args.sync:
        return do_sync(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
