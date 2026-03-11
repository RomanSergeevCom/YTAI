#!/usr/bin/env python3
"""
YTAI: Извлечение аудио из видео клипов

Извлекает WAV файлы для транскрипции:
1. Индивидуальные WAV для каждого клипа
2. Один склеенный FULL_AUDIO.wav для транскрипции

Использование:
    python 02_extract_audio.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python 02_extract_audio.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --dry-run

Результат:
    01_Raw/01_02_Audio/
    ├── RYA-ZVE1-1146_AUDIO.wav      (индивидуальный)
    ├── RYA-ZVE1-1147_AUDIO.wav      (индивидуальный)
    ├── ...
    └── YTCG37_Hadi_Dawani_FULL_AUDIO.wav  (склеенный для транскрипции)

    08_Logs/
    └── YTCG37_Hadi_Dawani_extract_audio_20260113_120000.log
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ============================================================================
# Конфигурация
# ============================================================================

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}

CLIPS_SUBDIR = "01_Raw/01_01_Video"
AUDIO_SUBDIR = "01_Raw/01_02_Audio"
TMP_SUBDIR = "09_Tmp"
LOGS_SUBDIR = "08_Logs"

MIN_OK_BYTES = 100_000  # 100KB минимум для валидного WAV


# ============================================================================
# Утилиты
# ============================================================================

def natural_key(s: str):
    """Сортировка строк с числами: clip1, clip2, clip10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def ffmpeg_exists() -> bool:
    """Проверить наличие ffmpeg."""
    try:
        subprocess.run(["ffmpeg", "-version"], check=True,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def tee_print(log_f, msg: str) -> None:
    """Вывод в консоль и лог файл."""
    print(msg)
    if log_f:
        log_f.write(msg + "\n")
        log_f.flush()


def run_ffmpeg(cmd: list[str], log_f, verbose: bool = False) -> int:
    """Запуск ffmpeg команды с логированием."""
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert p.stdout is not None
    
    output_lines = []
    for line in p.stdout:
        output_lines.append(line.rstrip("\n"))
        if verbose:
            tee_print(log_f, f"    {line.rstrip()}")
    
    rc = p.wait()
    
    # При ошибке показать последние строки
    if rc != 0 and not verbose:
        tee_print(log_f, "    FFmpeg output:")
        for line in output_lines[-5:]:
            tee_print(log_f, f"    {line}")
    
    return rc


def format_size(size_bytes: int) -> str:
    """Форматирование размера файла."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024**3):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024**2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"


def format_duration(seconds: float) -> str:
    """Форматирование длительности как HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def escape_for_concat(path: Path) -> str:
    """Экранирование пути для ffmpeg concat demuxer."""
    s = str(path)
    s = s.replace("'", "'\\''")
    return f"file '{s}'"


# ============================================================================
# Основная логика
# ============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="YTAI: Извлечение аудио из видео клипов",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --skip-concat
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --dry-run
        """
    )
    ap.add_argument("--project", required=True, 
                   help="Путь к папке проекта")
    ap.add_argument("--clips-dir", default=CLIPS_SUBDIR,
                   help=f'Папка с клипами (по умолчанию: "{CLIPS_SUBDIR}")')
    ap.add_argument("--out-dir", default=AUDIO_SUBDIR,
                   help=f'Папка для аудио (по умолчанию: "{AUDIO_SUBDIR}")')
    ap.add_argument("--skip-concat", action="store_true",
                   help="Пропустить создание склеенного аудио")
    ap.add_argument("--overwrite", action="store_true",
                   help="Перезаписать существующие WAV файлы")
    ap.add_argument("--dry-run", action="store_true",
                   help="Показать что будет сделано без выполнения")
    ap.add_argument("--verbose", action="store_true",
                   help="Показывать вывод ffmpeg")
    args = ap.parse_args()

    # Проверка путей
    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ОШИБКА: Папка проекта не найдена: {project_dir}", file=sys.stderr)
        sys.exit(1)

    if not ffmpeg_exists():
        print("ОШИБКА: ffmpeg не найден. Установите: brew install ffmpeg", file=sys.stderr)
        sys.exit(1)

    clips_dir = (project_dir / args.clips_dir).resolve()
    if not clips_dir.exists():
        print(f"ОШИБКА: Папка с клипами не найдена: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    # Создание директорий
    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    tmp_dir = (project_dir / TMP_SUBDIR).resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    logs_dir = (project_dir / LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Поиск клипов
    clips = [
        p for p in clips_dir.iterdir()
        if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")
    ]
    clips.sort(key=lambda p: natural_key(p.name))

    if not clips:
        print(f"ОШИБКА: Видео клипы не найдены в: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    # Генерация путей
    project_name = project_dir.name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{project_name}_extract_audio_{ts}.log"
    
    # Путь к склеенному аудио
    concat_wav = out_dir / f"{project_name}_FULL_AUDIO.wav"
    concat_list_file = tmp_dir / "audio_concat_list.txt"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "YTAI: ИЗВЛЕЧЕНИЕ АУДИО ИЗ КЛИПОВ")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Время      : {ts}")
        tee_print(log_f, f"Проект     : {project_name}")
        tee_print(log_f, f"Путь       : {project_dir}")
        tee_print(log_f, f"Клипы      : {clips_dir}")
        tee_print(log_f, f"Выход      : {out_dir}")
        tee_print(log_f, f"Кол-во     : {len(clips)} клипов")
        tee_print(log_f, f"Формат     : WAV 48000Hz stereo 16-bit PCM")
        tee_print(log_f, f"Лог        : {log_path}")
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "*** ТЕСТОВЫЙ РЕЖИМ (dry-run) ***")
            tee_print(log_f, "")

        # ============================================================
        # ФАЗА 1: Извлечение индивидуальных аудио файлов
        # ============================================================
        tee_print(log_f, "ФАЗА 1: Извлечение аудио из каждого клипа")
        tee_print(log_f, "-" * 40)
        
        success_count = 0
        skip_count = 0
        fail_count = 0
        total_size = 0
        wav_files = []  # Для склейки
        
        for i, clip in enumerate(clips, 1):
            # Имя выхода: clip_name_AUDIO.wav
            wav_name = f"{clip.stem}_AUDIO.wav"
            wav_path = out_dir / wav_name
            
            # Пропустить если существует
            if wav_path.exists() and not args.overwrite:
                size = wav_path.stat().st_size
                if size >= MIN_OK_BYTES:
                    tee_print(log_f, f"[{i:3d}/{len(clips)}] {clip.name}")
                    tee_print(log_f, f"           → ПРОПУСК (уже существует)")
                    skip_count += 1
                    total_size += size
                    wav_files.append(wav_path)
                    continue
            
            tee_print(log_f, f"[{i:3d}/{len(clips)}] {clip.name}")
            tee_print(log_f, f"           → {wav_name}")
            
            if args.dry_run:
                wav_files.append(wav_path)
                success_count += 1
                continue
            
            # FFmpeg команда
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
                "-i", str(clip),
                "-map", "0:a:0",        # Первый аудио поток
                "-vn", "-sn", "-dn",    # Без видео, субтитров, данных
                "-ar", "48000",         # Sample rate
                "-ac", "2",             # Stereo
                "-c:a", "pcm_s16le",    # 16-bit PCM
                str(wav_path),
            ]
            
            rc = run_ffmpeg(cmd, log_f, verbose=args.verbose)
            
            # Проверка результата
            if rc != 0 or not wav_path.exists() or wav_path.stat().st_size < MIN_OK_BYTES:
                tee_print(log_f, f"           ✗ ОШИБКА!")
                fail_count += 1
                if wav_path.exists():
                    wav_path.unlink()
            else:
                size = wav_path.stat().st_size
                total_size += size
                tee_print(log_f, f"           ✓ OK ({format_size(size)})")
                success_count += 1
                wav_files.append(wav_path)

        tee_print(log_f, "-" * 40)
        tee_print(log_f, "")
        tee_print(log_f, "Итог Фазы 1:")
        tee_print(log_f, f"  Успешно   : {success_count}")
        tee_print(log_f, f"  Пропущено : {skip_count}")
        tee_print(log_f, f"  Ошибок    : {fail_count}")
        if not args.dry_run:
            tee_print(log_f, f"  Размер    : {format_size(total_size)}")
        tee_print(log_f, "")

        # ============================================================
        # ФАЗА 2: Склейка всего аудио для транскрипции
        # ============================================================
        if args.skip_concat:
            tee_print(log_f, "ФАЗА 2: Пропущено (--skip-concat)")
        elif not wav_files:
            tee_print(log_f, "ФАЗА 2: Пропущено (нет аудио файлов)")
        else:
            tee_print(log_f, "ФАЗА 2: Склейка аудио для транскрипции")
            tee_print(log_f, "-" * 40)
            tee_print(log_f, f"Выход  : {concat_wav}")
            tee_print(log_f, f"Файлов : {len(wav_files)}")
            tee_print(log_f, "")

            if args.dry_run:
                tee_print(log_f, "Будет создан:")
                tee_print(log_f, f"  {concat_wav}")
            else:
                # Проверить существует ли
                if concat_wav.exists() and not args.overwrite:
                    tee_print(log_f, f"ПРОПУСК: {concat_wav.name} уже существует")
                else:
                    # Записать список файлов
                    with concat_list_file.open("w", encoding="utf-8") as f:
                        for wav in wav_files:
                            f.write(escape_for_concat(wav) + "\n")
                    
                    # FFmpeg склейка
                    cmd_concat = [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel", "warning",
                        "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(concat_list_file),
                        "-c", "copy",
                        str(concat_wav),
                    ]
                    
                    tee_print(log_f, "FFmpeg команда:")
                    tee_print(log_f, " ".join(shlex.quote(arg) for arg in cmd_concat))
                    tee_print(log_f, "")

                    rc = run_ffmpeg(cmd_concat, log_f, verbose=True)

                    if rc != 0 or not concat_wav.exists():
                        tee_print(log_f, "✗ ОШИБКА: Склейка не удалась!")
                    else:
                        concat_size = concat_wav.stat().st_size
                        # WAV: 48000 Hz * 2 channels * 2 bytes = 192000 bytes/sec
                        duration_sec = (concat_size - 44) / 192000
                        tee_print(log_f, "")
                        tee_print(log_f, "✓ Склеенное аудио создано:")
                        tee_print(log_f, f"  Файл       : {concat_wav.name}")
                        tee_print(log_f, f"  Размер     : {format_size(concat_size)}")
                        tee_print(log_f, f"  Длительность: ~{format_duration(duration_sec)}")
                    
                    # Удалить временный файл
                    try:
                        concat_list_file.unlink()
                    except Exception:
                        pass

        # ============================================================
        # Итог
        # ============================================================
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "РЕЗУЛЬТАТ")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "")
        tee_print(log_f, f"Индивидуальные аудио: {out_dir}/")
        tee_print(log_f, f"  {len(wav_files)} файлов: <clip_name>_AUDIO.wav")
        
        if not args.skip_concat and wav_files:
            tee_print(log_f, "")
            tee_print(log_f, f"Полное аудио (для транскрипции):")
            tee_print(log_f, f"  {concat_wav}")
        
        tee_print(log_f, "")
        tee_print(log_f, f"Лог: {log_path}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "ГОТОВО")
        tee_print(log_f, "=" * 60)

    print(f"\nЛог сохранён: {log_path}")


if __name__ == "__main__":
    main()
