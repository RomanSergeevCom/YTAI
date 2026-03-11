#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".MP4", ".MOV", ".M4V"}


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def ffmpeg_exists() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def next_free_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem = p.stem
    suffix = p.suffix
    for i in range(2, 1000):
        candidate = p.with_name(f"{stem}_v{i:02d}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Too many versions, cannot find free output name")


def tee_print(log_f, msg: str) -> None:
    print(msg)
    log_f.write(msg + "\n")
    log_f.flush()


def run_ffmpeg_with_tee(cmd: list[str], log_f) -> int:
    # Пишем и в терминал, и в файл. Объединяем stderr->stdout, чтобы не потерять прогресс/ошибки.
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert p.stdout is not None
    for line in p.stdout:
        line = line.rstrip("\n")
        tee_print(log_f, line)
    return p.wait()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Concatenate raw video clips without re-encoding (ffmpeg concat demuxer, -c copy)."
    )
    ap.add_argument(
        "--project",
        required=True,
        help='Project folder, e.g. "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"',
    )
    ap.add_argument(
        "--video-subdir",
        default="01_Raw/01_01_Video",
        help='Relative path inside project with clips (default: "01_Raw/01_01_Video")',
    )
    ap.add_argument(
        "--out-subdir",
        default="01_Raw",
        help='Relative output folder inside project (default: "01_Raw")',
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it exists (otherwise creates _v02, _v03...)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without running ffmpeg",
    )
    args = ap.parse_args()

    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        raise SystemExit(f"Project folder not found: {project_dir}")

    if not ffmpeg_exists():
        raise SystemExit("ffmpeg not found. Install: brew install ffmpeg")

    # Логи
    logs_dir = (project_dir / "08_Logs").resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"concat_raw_videos_copy_{ts}.log"

    video_dir = (project_dir / args.video_subdir).resolve()
    if not video_dir.exists():
        raise SystemExit(f"Video folder not found: {video_dir}")

    clips = [p for p in video_dir.iterdir() if p.is_file() and p.suffix in VIDEO_EXTS]
    clips.sort(key=lambda p: natural_key(p.name))
    if not clips:
        raise SystemExit(f"No video files found in: {video_dir}")

    out_dir = (project_dir / args.out_subdir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    project_name = project_dir.name
    out_path = out_dir / f"{project_name}.mp4"
    if not args.overwrite:
        out_path = next_free_path(out_path)

    tmp_dir = (project_dir / "09_Tmp").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    concat_file = tmp_dir / "concat_list.txt"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, f"Project : {project_dir}")
        tee_print(log_f, f"Input   : {video_dir}")
        tee_print(log_f, f"Clips   : {len(clips)}")
        tee_print(log_f, f"Output  : {out_path}")
        tee_print(log_f, f"Log     : {log_path}")
        tee_print(log_f, "")

        tee_print(log_f, "Clip list (sorted):")
        for c in clips:
            tee_print(log_f, f"  {c.name}")
        tee_print(log_f, "")

        # Пишем абсолютные пути для ffmpeg concat.
        # Важно: в именах файлов не должно быть одинарных кавычек.
        with concat_file.open("w", encoding="utf-8") as f:
            for clip in clips:
                f.write(f"file '{clip.as_posix()}'\n")

        tee_print(log_f, f"Concat list file: {concat_file}")
        tee_print(log_f, "")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-stats",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(out_path),
        ]

        if args.overwrite:
            cmd.insert(1, "-y")

        tee_print(log_f, "ffmpeg command:")
        tee_print(log_f, " ".join(cmd))
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "DRY RUN: no ffmpeg execution.")
            tee_print(log_f, "OK")
            return

        rc = run_ffmpeg_with_tee(cmd, log_f)

        if rc != 0:
            tee_print(log_f, "")
            tee_print(log_f, "ffmpeg failed. Usually it means clips differ in codec/fps/resolution/audio.")
            tee_print(log_f, "For this set, you may need a re-encode merge.")
            raise SystemExit(rc)

        tee_print(log_f, "")
        tee_print(log_f, "OK")


if __name__ == "__main__":
    main()
