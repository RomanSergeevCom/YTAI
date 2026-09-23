#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Доукомплектование прокси-набора: петличные WAV, транскрипты, луты сцен.

Комплект монтажёру должен быть самодостаточным: открыл `.prproj`, указал на
`01_Source_Proxy` — и всё слинковалось. Значит рядом с прокси-видео обязаны
лежать звук петличек, расшифровки и луты сцен.

⚠️ В комплект идут только сведённые `*_timeline.wav`. Оригиналы рекордера
(`*_orig*.wav`) — это −4.7 ГБ на проект и монтажёру не нужны: они живут на
Drive в `99_Pipeline/DJI_Audio/{сцена}/`, а если понадобятся — пересобираются
`0113_frame_align.py` с SSD.

Луты приводятся к каноническим именам (см. scripts/15_color/):
`bright/normal/dark.cube` → `01_bright_scene/02_normal_scene/03_dark_scene.cube`.
Старое имя рядом с новым и БАЙТ В БАЙТ тем же содержимым — дубль, убираем; всё
остальное не трогаем и говорим об этом вслух.
"""
import os
import shutil

LUT_CANON = {
    "bright.cube": "01_bright_scene.cube",
    "normal.cube": "02_normal_scene.cube",
    "dark.cube": "03_dark_scene.cube",
}
LUT_DIR = "00_LUT"
#: кухня выбора лутов внутри дома лутов — в комплект монтажёру не едет
LUT_BUILD_DIR = "_build"
TRANSCRIPTION_DIR = "Transcription"

#: что из звука кладём рядом с прокси
WAV_KEEP = "_timeline.wav"
WAV_SKIP_MARK = "_orig"


def _copy_if_new(src, dst):
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    tmp = dst + ".part"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)
    return True


def copy_scene_audio(src_root, dst_root, log=print):
    """Петличные WAV сцен → в те же сцены комплекта."""
    copied = skipped = 0
    for scene in sorted(os.listdir(src_root)):
        sdir = os.path.join(src_root, scene)
        if not os.path.isdir(sdir) or scene in (LUT_DIR, TRANSCRIPTION_DIR):
            continue
        if scene.startswith("."):
            continue
        wavs = [f for f in sorted(os.listdir(sdir))
                if f.lower().endswith(".wav") and not f.startswith("._")]
        timeline = [f for f in wavs if WAV_KEEP in f]
        take = timeline or [f for f in wavs if WAV_SKIP_MARK not in f]
        skipped += len(wavs) - len(take)
        for f in take:
            if _copy_if_new(os.path.join(sdir, f), os.path.join(dst_root, scene, f)):
                copied += 1
    log(f"  звук сцен: добавлено {copied}, пропущено оригиналов рекордера {skipped}")
    return copied


def copy_tree(src_root, dst_root, name, log=print, skip_dirs=()):
    """Транскрипты и прочие папки-спутники целиком.

    `skip_dirs` — что в комплект не едет. Нужен из-за `00_LUT/_build`: там
    лежит доска выбора с кадрами (на съёмочном дне это ~50 МБ jpeg), монтажёру
    она не нужна, а в комплекте это лишние мегабайты и лишние вопросы.
    """
    src = os.path.join(src_root, name)
    if not os.path.isdir(src):
        return 0
    copied = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip_dirs]
        for f in files:
            if f.startswith("._"):
                continue
            rel = os.path.relpath(os.path.join(root, f), src_root)
            if _copy_if_new(os.path.join(root, f), os.path.join(dst_root, rel)):
                copied += 1
    log(f"  {name}: добавлено {copied} файлов")
    return copied


def _same_bytes(a, b, chunk=1 << 20):
    """Совпадают ли файлы побайтно. Не прочиталось — считаем, что НЕ совпали.

    ⚠️ Размера для решения «это дубль» НЕ хватает. `.cube` пишется числами
    фиксированной ширины, поэтому два РАЗНЫХ лута одной сетки весят одинаково
    до байта: удаление по совпадению размера однажды сотрёт чужую покраску, и
    узнать об этом будет уже не по чему. Осторожность односторонняя намеренно —
    ошибка чтения обязана вести к «оставляю оба», а не к удалению вслепую.
    """
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            while True:
                ca, cb = fa.read(chunk), fb.read(chunk)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def canon_luts(lut_dir, apply=True, log=print):
    """Привести имена лутов к канону. Возвращает список сделанного."""
    if not os.path.isdir(lut_dir):
        return []
    have = set(os.listdir(lut_dir))
    actions = []
    # в сухом прогоне говорим в будущем времени: «переименован» там, где ничего
    # не тронуто, — это ложный отчёт, по которому потом не поймёшь, что сделано
    done, todo = (("дубль убран", "переименован") if apply
                  else ("дубль будет убран", "будет переименован"))
    for old, new in LUT_CANON.items():
        if old not in have:
            continue
        old_p, new_p = os.path.join(lut_dir, old), os.path.join(lut_dir, new)
        if new in have:
            if os.path.getsize(old_p) != os.path.getsize(new_p):
                actions.append(("РАЗНЫЕ размеры — не трогаю", old, new))
            elif _same_bytes(old_p, new_p):
                actions.append((done, old, new))
                if apply:
                    os.remove(old_p)
            else:
                actions.append(("размер тот же, СОДЕРЖИМОЕ разное — не трогаю",
                                old, new))
        else:
            actions.append((todo, old, new))
            if apply:
                os.rename(old_p, new_p)
    for what, old, new in actions:
        log(f"  лут {old} → {new}: {what}")
    return actions


def complete_kit(src_root, dst_root, log=print):
    """Полное доукомплектование: звук + транскрипты + луты."""
    log("доукомплектование комплекта:")
    copy_scene_audio(src_root, dst_root, log)
    copy_tree(src_root, dst_root, TRANSCRIPTION_DIR, log)
    copy_tree(src_root, dst_root, LUT_DIR, log, skip_dirs=(LUT_BUILD_DIR,))
    canon_luts(os.path.join(src_root, LUT_DIR), log=log)
    canon_luts(os.path.join(dst_root, LUT_DIR), log=log)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="доукомплектование прокси-набора")
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--luts-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.luts_only:
        canon_luts(os.path.join(a.src, LUT_DIR), apply=not a.dry_run)
        canon_luts(os.path.join(a.dst, LUT_DIR), apply=not a.dry_run)
    else:
        complete_kit(a.src, a.dst)
