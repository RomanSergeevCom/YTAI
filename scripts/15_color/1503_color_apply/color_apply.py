#!/usr/bin/env python3
"""Раскладка цвета по клипам: выбор человека → план, который кладут на таймлайн.

Собирает `{CODE}_color_plan.json` из двух источников:
  • `{проект}/00_Setup/01_Ingest/{CODE}_color_choice.json` — выбор по ЭТОМУ дню
    (экспозиция по клипам, подписанная человеком);
  • `YTs/{КАНАЛ}/color_profile.json` — ДНК канала (проявка по гамме, look).

⚠️ ТОЛЬКО stdlib. Ни ffmpeg, ни Vision, ни numpy. План обязан собираться, когда
карта с оригиналами размонтирована, — а это НОРМАЛЬНОЕ состояние: на YTEVO03 все
163 оригинала и 108 сайдкаров M01.XML это симлинки на съёмную карту. Гамма берётся
из кэша, а не измеряется заново.

⚠️ Экспозиция пересчитывается. Витрина считала её фильтром ffmpeg поверх
ГАММА-кодированного Rec.709 (умножение кода на 2^X), а Lumetri линеаризует ДО
экспозиции — стопы Lumetri = 2,4 × стопы витрины. Кадры, которые человек смотрел
и утверждал, верны как изображение; переносится в Premiere другое число.

⚠️ Отказ громче тишины. Клип, которому не из чего собрать проявку или чья
экспозиция не влезает в ползунок ±7, попадает в `refused`, и тогда файл НЕ
пишется вовсе. Клип без слоя в Premiere выглядит как обычный клип — молча
пропустить его хуже, чем не собрать план.

  color_apply.py --project <путь>            сухой прогон, ничего не пишет
  color_apply.py --project <путь> --apply    пишет {CODE}_color_plan.json
  color_apply.py --project <путь> --verify   сверяет кубы со store по sha256
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PICK = HERE.parent / "1502_lut_pick"
LIB = HERE.parent / "1501_lut_library"
for _p in (str(PICK), str(LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import color_media as M       # noqa: E402  — клипы, пути, гамма
import color_plan as PL       # noqa: E402  — ключи, профиль, экспозиция, кэш
import lut_select as S        # noqa: E402  — store и манифест

SCHEMA = "color-plan-v1"

ADOBE_LUTS = Path.home() / "Library" / "Application Support" / "Adobe" / "Common" / "LUTs"
CREATIVE_DIR = ADOBE_LUTS / "Creative" / "YTAI"   # сюда — покрасочные (Lumetri → Creative → Look)
INPUT_DIR = ADOBE_LUTS / "Input" / "YTAI"         # сюда — проявочные (Basic Correction → Input LUT)


def die(msg, code=2):
    print(f"\n✗ {msg}\n", file=sys.stderr)
    sys.exit(code)


def project_code(project: Path) -> str:
    m = re.match(r"^(YT[A-Z]{2,4}\d+)_", project.name)
    if not m:
        die(f"из имени папки не читается код проекта: {project.name}")
    return m.group(1)


def install_name(lut_id: str) -> str:
    """Имя, под которым куб ложится в общую папку Adobe.

    ⚠️ Префикс обязателен: Lumetri ссылается на ИМЯ ФАЙЛА, а `look__newstar.cube`
    в общей Creative-папке — столкновение, ждущее своего часа. И выводится оно из
    id, а не из orig_name: переименовывать луты в сданных проектах нельзя никогда,
    значит имя должно быть выводимым и вечным.
    """
    return f"YTAI_{lut_id}.cube"


def collect_clips(project: Path):
    """Все клипы дня как (канонический ключ, сцена, путь, роль камеры)."""
    source = project / "01_Source"
    if not source.is_dir():
        die(f"нет папки исходников: {source}")
    out = []
    # ⚠️ Тот же отбор сцен, что у витрины (color_media.content_scenes): служебная
    # 00_Tests_And_Sync — не фильм. Два разных правила = разные числа у двух
    # инструментов, и спорить, какое верное, будет уже монтажёр.
    for sdir in M.content_scenes(source):
        try:
            clips = M.scene_clips(sdir)
        except M.DuplicateClip as e:
            die(str(e))
        for clip in clips:
            out.append((PL.clip_key(sdir.name, clip.name), sdir.name, clip,
                        M.cam_of(clip, source)))
    return out


def gamma_for(key, clip, cam, cache, seeded):
    """Гамма клипа. Живой замер важнее записи, запись важнее отказа."""
    if clip.exists():
        g = M.sony_gamma(clip)
        if g:
            return M.normalize_gamma(g), "сайдкар M01.XML"
        g = M.dji_gamma(clip)
        if g:
            return M.normalize_gamma(g), "тег com.dji.camera.ColorGammaSxS"
    rec = cache.get(key) or seeded.get(key)
    if rec and rec.get("gamma"):
        return rec["gamma"], f"кэш ({rec.get('source') or 'замер'})"
    return None, "не определена"


def build(project: Path, code: str) -> dict:
    ing = project / "00_Setup" / "01_Ingest"
    choice = PL.load_json_safe(ing / f"{code}_color_choice.json")
    if not choice:
        die(f"нет файла выбора {code}_color_choice.json — сначала витрина "
            f"(1502_lut_pick/lut_board.py)")
    profile = PL.load_profile(project, code)
    if not profile.get("develop"):
        die(f"в профиле канала нет ни одной проявки: {PL.profile_path(project, code)}")

    approved = choice.get("approved") or (
        (choice.get("stage") or {}).get("decided_by") if (choice.get("stage") or {}).get("done") else None)

    cache = PL.load_gamma_cache(project, code)
    seeded = {}
    legacy = PL.load_json_safe(ing / f"{code}_lut_plan.json")
    clips = collect_clips(project)
    if legacy:
        # ⚠️ Карта строится ОТ КАНОНИЧЕСКИХ ключей и проверяется на коллизии здесь,
        # а не внутри посева: страж внутри смотрел на values(), а вызывающий
        # схлопывал их в ключи ЕЩЁ ДО вызова — и последняя сцена побеждала молча.
        # Воспроизводилось: клип DJI получал гамму Sony, отказа не было.
        # scene_clips ловит дубли только ВНУТРИ сцены, между сценами — не ловит.
        by_base = {}
        collided = {}
        for key, _scene, _clip, _cam in clips:
            base = key.split("/")[-1]
            if base in by_base:
                collided.setdefault(base, [by_base[base]]).append(key)
            by_base[base] = key
        if collided:
            lines = "; ".join(f"{b}: {' и '.join(v)}" for b, v in sorted(collided.items())[:5])
            die(f"одно имя файла встречается в разных сценах — гамма из старого плана "
                f"легла бы на клип ЧУЖОЙ сцены, то есть чужая проявка без единого "
                f"сообщения:\n  {lines}", 5)
        seeded = PL.seed_gamma_cache_from_lut_plan(legacy, by_base)

    exposure = choice.get("exposure") or {}
    look = PL.resolve_look(profile)
    luts = {l["id"]: l for l in S.load_library()}

    plan, meta, skipped, refused = {}, {}, {}, {}
    used_develops, by_stop = {}, {}
    gamma_rec = {}

    for key, scene, clip, cam in clips:
        gamma, gsrc = gamma_for(key, clip, cam, cache, seeded)
        if gamma:
            size, mtime = PL._stat_pair(clip)
            old = cache.get(key) or seeded.get(key) or {}
            gamma_rec[key] = {
                "gamma": gamma,
                "gamma_raw": old.get("gamma_raw") or gamma,
                "source": ("sidecar_m01xml" if "сайдкар" in gsrc else
                           "dji_tag" if "тег" in gsrc else
                           old.get("source") or "legacy_lut_plan"),
                "cam": cam, "pix_fmt": old.get("pix_fmt") or "",
                "size": size, "mtime": mtime,
                "measured": old.get("measured") or PL.now_iso(),
            }
        slug = PL.clip_slug(scene, clip.stem)

        try:
            dev, dsrc = PL.resolve_develop(profile, gamma, cam)
        except PL.DevelopUnknown as e:
            # Rec.709 — законный случай: проявлять уже нечего, клип не в логе.
            if gamma == "Rec.709":
                skipped[key] = "снято в Rec.709 — проявка не нужна"
                continue
            refused[key] = str(e)
            continue

        if slug not in exposure:
            refused[key] = f"в выборе нет экспозиции (искали ключ {slug})"
            continue
        prev = float(exposure[slug])
        ok, why = PL.check_lumetri_stops(prev)
        if not ok:
            refused[key] = why
            continue

        plan[key] = {"develop": dev,
                     "exposure": round(PL.to_lumetri_stops(prev), 4),
                     "look": look}
        meta[key] = {"scene": scene, "clip": clip.name, "slug": slug, "cam": cam,
                     "gamma": gamma, "gamma_source": gsrc,
                     "develop_source": dsrc,
                     "exposure_preview": prev,
                     "exposure_source": "roman" if slug in (choice.get("corrected") or {}) else "машина",
                     "src": str(clip)}
        used_develops[dev] = used_develops.get(dev, 0) + 1
        by_stop[f"{prev:+.1f}"] = by_stop.get(f"{prev:+.1f}", 0) + 1

    def cube_block(lut_id, slot):
        e = luts.get(lut_id)
        if not e:
            refused[f"__lut__{lut_id}"] = f"куба {lut_id} нет в манифесте библиотеки"
            return None
        ok, why = S.verify_cube(e)
        if not ok:
            # ⚠️ Блок НЕ отдаём. Иначе при --allow-refused план записывался с
            # адресом куба, который не сошёлся по sha256, и панель дальше
            # пользовалась непроверенным файлом. Куб — единственное, что нельзя
            # «разложить частично»: это не клип, это математика всего канала.
            refused[f"__lut__{lut_id}"] = f"{lut_id}: {why}"
            return None
        return {"slot": slot, "file": e.get("file"), "sha256": e.get("sha256"),
                "store_path": str(S.store_path(e)), "install_name": install_name(lut_id),
                "gamma": (e.get("input") or {}).get("gamma")}

    develops = {}
    for lut_id, n in sorted(used_develops.items()):
        b = cube_block(lut_id, "basic_input_lut")
        if b:
            b["clips"] = n
            develops[lut_id] = b
    look_block = cube_block(look, "creative_look") if look else None
    if look and look_block is None:
        refused.setdefault(f"__lut__{look}", f"{look}: куб покраски не прошёл сверку")

    files = []
    for lut_id, b in develops.items():
        files.append({"install_name": b["install_name"], "store_path": b["store_path"],
                      "dir": "input_dir", "sha256": b["sha256"]})
    if look_block:
        files.append({"install_name": look_block["install_name"],
                      "store_path": look_block["store_path"],
                      "dir": "creative_dir", "sha256": look_block["sha256"]})

    return {
        "schema": SCHEMA,
        "_note": "Раскладка по клипам: что панель кладёт на таймлайн. Файл "
                 "ПРОИЗВОДНЫЙ — собирается из {CODE}_color_choice.json (выбор "
                 "человека) и YTs/{КАНАЛ}/color_profile.json (ДНК канала). Руками "
                 "не править: следующий --apply перезапишет. ⚠️ Ключ plan — "
                 "'сцена/клип.MP4', панель пере-ключует его по basename. Формат "
                 "ключа не менять.",
        "project": code,
        "channel": profile.get("channel"),
        "doc_version": 1,
        "generated": PL.now_iso(),
        "generated_ru": PL.when_ru(),
        "tool": "scripts/15_color/1503_color_apply/color_apply.py",
        "approved": approved,
        "lut_generation": 2,
        "model": "pre → проявка (log→Rec.709, по гамме+камере) → экспозиция "
                 "(стопы, ЧИСЛО) → покраска (ДНК канала)",
        "exposure_units": "stops_lumetri",
        "exposure_source_units": "stops_preview",
        "exposure_multiplier": PL.LUMETRI_GAMMA,
        "exposure_limit": PL.LUMETRI_EXPOSURE_LIMIT,
        "exposure_verified_against_premiere": False,
        "_exposure_note": "⚠️ Число в стопах Lumetri = 2,4 × стопы витрины. Превью "
                          "считает экспозицию фильтром ffmpeg поверх гамма-кодированного "
                          "Rec.709, Lumetri линеаризует ДО экспозиции (Gamma 2.4 to "
                          "Linear). Множитель ВЫВЕДЕН из блоба шаблона, а не замерен на "
                          "живой программе: пока exposure_verified_against_premiere "
                          "равно false, утверждать перенос один в один нельзя.",
        "sources": {
            "choice": str(ing / f"{code}_color_choice.json"),
            "choice_saved": choice.get("saved"),
            "choice_doc_version": choice.get("doc_version"),
            "profile": str(PL.profile_path(project, code)),
            "profile_updated": profile.get("updated"),
            "gamma_cache": str(PL.gamma_cache_path(project, code)),
            "legacy_lut_plan": str(ing / f"{code}_lut_plan.json") if legacy else None,
        },
        "look": ({"id": look, **look_block} if look_block else None),
        "develops": develops,
        "install": {
            "_why": "Откуда панель берёт кубы, чтобы Premiere их увидел. ⚠️ Общая "
                    "папка Adobe читается ПРИ СТАРТЕ Premiere — копировать нужно "
                    "до запуска, панель изнутри программы уже опоздала.",
            # ⚠️ Папки называются Creative / Input / Output — «Technical» у Adobe НЕТ.
            # Сверено с диском: рядом уже лежат Input/peresvet.cube и Input/nedosvet.cube
            # прошлого поколения. Ошибиться здесь значит выписать план, указывающий
            # в несуществующую папку, и обнаружить это только в Premiere.
            "creative_dir": str(CREATIVE_DIR),
            "input_dir": str(INPUT_DIR),
            "files": files,
        },
        "plan": plan,
        "clips": meta,
        "skipped": skipped,
        "refused": refused,
        "_gamma_records": gamma_rec,
        "stats": {
            "clips": len(clips), "planned": len(plan),
            "skipped": len(skipped), "refused": len(refused),
            "by_develop": used_develops,
            "by_stop_preview": dict(sorted(by_stop.items())),
        },
    }


def report(doc: dict):
    st = doc["stats"]
    print(f"\nРАСКЛАДКА {doc['project']}  ·  канал {doc.get('channel')}")
    print(f"  клипов {st['clips']} · в плане {st['planned']} · "
          f"пропущено {st['skipped']} · отказов {st['refused']}")
    if doc.get("approved"):
        print(f"  выбор утверждён: {doc['approved']}")
    else:
        print("  ⚠️ выбор НЕ утверждён — панель такой план класть не должна")
    for lut_id, b in (doc.get("develops") or {}).items():
        print(f"  проявка  {lut_id}  → {b['clips']} клипов")
    if doc.get("look"):
        print(f"  покраска {doc['look']['id']}")
    print(f"  экспозиция: стопы витрины × {doc['exposure_multiplier']} = стопы Lumetri "
          f"(предел ±{doc['exposure_limit']:.0f}, проверено: "
          f"{'НЕТ' if not doc['exposure_verified_against_premiere'] else 'да'})")
    if st["by_stop_preview"]:
        line = " · ".join(f"{k}→{float(k)*doc['exposure_multiplier']:+.1f}: {v}"
                          for k, v in st["by_stop_preview"].items())
        print(f"  по стопам: {line}")
    for k, why in (doc.get("skipped") or {}).items():
        print(f"  пропуск  {k} — {why}")
    for k, why in (doc.get("refused") or {}).items():
        print(f"  ✗ ОТКАЗ  {k} — {why}")


def install_cubes(doc: dict, apply: bool) -> int:
    """Разложить кубы плана по папкам Adobe. Проблемных — вернуть числом.

    ⚠️ Общая папка Adobe читается ПРИ СТАРТЕ Premiere. Поэтому раскладка кубов —
    шаг ДО запуска программы, и панель изнутри Premiere сделать его не может: она
    уже опоздала. Если кубы скопированы при запущенной программе, Premiere надо
    перезапустить, иначе выпадающий список их не увидит.

    Копия сверяется по sha256 с манифестом: одинаковое имя при разном содержимом —
    ровно тот класс ошибки, на котором слой уже обжёгся (`eastman` и `eastmanrm`
    схлопывались обрезкой id, и кадр молча показывал не тот куб, что подписан).
    """
    import hashlib
    import shutil
    bad = 0
    for f in doc["install"]["files"]:
        src = Path(f["store_path"])
        dst = Path(f["dir"] == "creative_dir" and CREATIVE_DIR or INPUT_DIR) / f["install_name"]
        if not src.exists():
            print(f"  ✗ нет в store: {f['install_name']}")
            bad += 1
            continue
        if dst.exists():
            have = hashlib.sha256(dst.read_bytes()).hexdigest()
            if have == f["sha256"]:
                print(f"  = на месте   {f['install_name']}")
                continue
            print(f"  ≠ РАЗОШЁЛСЯ  {f['install_name']} — то же имя, другое содержимое")
        if not apply:
            print(f"  + поставил БЫ {f['install_name']} → {dst.parent}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        got = hashlib.sha256(dst.read_bytes()).hexdigest()
        if got != f["sha256"]:
            print(f"  ✗ копия не сошлась по sha256: {f['install_name']}")
            bad += 1
        else:
            print(f"  + поставил   {f['install_name']} → {dst.parent}")
    return bad


def main():
    ap = argparse.ArgumentParser(description="Раскладка цвета по клипам")
    ap.add_argument("--project", required=True)
    ap.add_argument("--apply", action="store_true",
                    help="записать {CODE}_color_plan.json (без флага — сухой прогон)")
    ap.add_argument("--verify", action="store_true",
                    help="сверить кубы плана со store по sha256")
    ap.add_argument("--allow-refused", action="store_true",
                    help="записать план, даже если часть клипов отказная")
    ap.add_argument("--install", action="store_true",
                    help="разложить кубы плана по папкам Adobe (до запуска Premiere)")
    a = ap.parse_args()

    project = Path(a.project).expanduser()
    if not project.is_dir():
        die(f"нет такой папки: {project}")
    code = project_code(project)
    doc = build(project, code)
    report(doc)

    if doc["refused"] and not a.allow_refused:
        die(f"отказов {len(doc['refused'])} — план НЕ записан. Клип без слоя в "
            f"Premiere выглядит как обычный клип, поэтому молча пропустить его "
            f"нельзя. Разобрать причины выше или запустить с --allow-refused.", 3)

    if a.verify:
        bad = 0
        for f in doc["install"]["files"]:
            p = Path(f["store_path"])
            mark = "ok" if p.exists() else "НЕТ ФАЙЛА"
            if not p.exists():
                bad += 1
            print(f"  {mark:10} {f['install_name']}")
        print(f"\n  кубов {len(doc['install']['files'])}, проблемных {bad}")

    if a.install:
        print("\n  РАСКЛАДКА КУБОВ В ПАПКИ ADOBE")
        bad = install_cubes(doc, a.apply)
        if not a.apply:
            print("  (сухой прогон — ничего не скопировано; повтори с --apply)")
        elif bad:
            die(f"кубов с проблемой: {bad}", 4)
        else:
            print("  ⚠️ если Premiere был открыт — перезапусти его: список лутов "
                  "читается при СТАРТЕ программы")

    out = project / "00_Setup" / "01_Ingest" / f"{code}_color_plan.json"
    gamma_rec = doc.pop("_gamma_records", {})
    if a.apply:
        # ⚠️ Кэш гамм пишем ВСЕГДА при --apply. Пока он не лёг на диск, единственный
        # источник гамм этого дня — старый {CODE}_lut_plan.json, написанный
        # инструментом, который уже в архиве. После первой записи зависимость мертва.
        if gamma_rec:
            gp = PL.save_gamma_cache(project, code, gamma_rec)
            live = sum(1 for r in gamma_rec.values() if r["source"] in ("sidecar_m01xml", "dji_tag"))
            print(f"  кэш гамм: {len(gamma_rec)} записей "
                  f"({live} живых замеров, {len(gamma_rec)-live} из прошлого плана) → {gp.name}")
        if out.exists():
            PL.backup(out)
            prev = PL.load_json_safe(out) or {}
            doc["doc_version"] = int(prev.get("doc_version") or 0) + 1
        PL.save_json_atomic(out, doc)
        print(f"\n  → {out}  (v{doc['doc_version']})\n")
    else:
        print(f"\n  сухой прогон: ничего не записано. Записать — --apply\n"
              f"  цель: {out}\n")


if __name__ == "__main__":
    main()
