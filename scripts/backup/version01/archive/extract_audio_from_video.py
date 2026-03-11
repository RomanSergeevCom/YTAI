#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path


DEFAULT_AUDIO_SUBDIR = Path("01_Raw/01_02_Audio")
DEFAULT_LOGS_DIRNAME = "08_Logs"

# WAV header ~44 bytes, у тебя было 78 bytes. Это "пусто".
# Поставим минимальный порог 1 MB, чтобы точно отсечь пустые/битые выходы.
MIN_OK_BYTES = 1_000_000


def ffmpeg_exists() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def tee_print(log_f, msg: str) -> None:
    print(msg)
    log_f.write(msg + "\n")
    log_f.flush()


def run_ffmpeg_with_tee(cmd: list[str], log_f) -> int:
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert p.stdout is not None
    for line in p.stdout:
        tee_print(log_f, line.rstrip("\n"))
    return p.wait()


def next_free_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    for i in range(2, 1000):
        cand = p.with_name(f"{stem}_v{i:02d}{suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError("Too many versions, cannot find free output name")


def infer_project(video_path: Path) -> Path:
    # Ищем <PROJECT>/01_Raw/.../file
    parts = list(video_path.parts)
    if "01_Raw" in parts:
        idx = parts.index("01_Raw")
        if idx > 0:
            return Path(*parts[:idx]).resolve()
    raise SystemExit('Cannot infer project folder from path. Pass --project explicitly.')


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract audio from a video file to WAV 48kHz stereo 16-bit PCM. Logs to <PROJECT>/08_Logs."
    )
    ap.add_argument("--video", required=True, help="Path to input video file")
    ap.add_argument("--project", default=None, help="Project folder path (optional)")
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_AUDIO_SUBDIR),
        help='Relative output folder inside project (default: "01_Raw/01_02_Audio")',
    )
    ap.add_argument("--overwrite", action="store_true", help="Overwrite output if exists")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without running ffmpeg")
    ap.add_argument("--min-bytes", type=int, default=MIN_OK_BYTES, help="Minimum output size to treat as success")
    args = ap.parse_args()

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise SystemExit(f"Video file not found: {video_path}")
    if not ffmpeg_exists():
        raise SystemExit("ffmpeg not found. Install: brew install ffmpeg")

    project_dir = Path(args.project).expanduser().resolve() if args.project else infer_project(video_path)
    if not project_dir.exists():
        raise SystemExit(f"Project folder not found: {project_dir}")

    logs_dir = (project_dir / DEFAULT_LOGS_DIRNAME).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"extract_audio_wav48k16_{ts}.log"

    out_dir = (project_dir / Path(args.out_dir)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{video_path.stem}_AUDIO.wav"
    if not args.overwrite:
        out_path = next_free_path(out_path)

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, f"Project : {project_dir}")
        tee_print(log_f, f"Input   : {video_path}")
        tee_print(log_f, f"Output  : {out_path}")
        tee_print(log_f, "Spec    : WAV, 48000 Hz, stereo, 16-bit PCM (pcm_s16le)")
        tee_print(log_f, f"MinBytes: {args.min_bytes}")
        tee_print(log_f, f"Log     : {log_path}")
        tee_print(log_f, "")

        # Входные флаги для проблемных MP4:
        # -ignore_editlist 1        часто спасает файлы с edit list
        # -fflags +genpts+igndts    игнорируем плохие DTS и генерируем PTS
        # -probesize/-analyzeduration увеличиваем "анализ" для больших файлов
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-stats",
            "-ignore_editlist", "1",
            "-fflags", "+genpts+igndts",
            "-probesize", "200M",
            "-analyzeduration", "200M",
            "-i", str(video_path),
            "-map", "0:a:0",
            "-vn", "-sn", "-dn",
            "-ar", "48000",
            "-ac", "2",
            "-c:a", "pcm_s16le",
            str(out_path),
        ]
        if args.overwrite:
            cmd.insert(1, "-y")

        tee_print(log_f, "ffmpeg command:")
        tee_print(log_f, " ".join(cmd))
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "DRY RUN: no ffmpeg execution.")
            raise SystemExit(0)

        rc = run_ffmpeg_with_tee(cmd, log_f)

        size = out_path.stat().st_size if out_path.exists() else 0
        tee_print(log_f, "")
        tee_print(log_f, f"Return code: {rc}")
        tee_print(log_f, f"Output size: {size} bytes")

        # Если пусто или почти пусто, это ошибка, даже если rc==0
        if rc != 0 or size < args.min_bytes:
            # чтобы не оставлять мусор
            if out_path.exists():
                try:
                    out_path.unlink()
                except Exception:
                    pass
            tee_print(log_f, "ERROR: extraction failed (empty/too small WAV).")
            tee_print(log_f, "This indicates the source MP4 is not being read correctly by ffmpeg.")
            raise SystemExit(2)

        tee_print(log_f, "OK")


if __name__ == "__main__":
    main()
