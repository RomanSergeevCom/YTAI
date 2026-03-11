#!/usr/bin/env python3
"""
YTAI Этап 3: Apply Names
Применение имён спикеров к транскрипту.

Использование:
    python apply_names.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"

Выход:
    01_Media/Source/Transcription/
    ├── {project}_apply_names_{timestamp}.json
    ├── {project}_apply_names_{timestamp}.txt
    └── {project}_apply_names_{timestamp}.srt
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set

sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    get_project_paths,
    ensure_dirs,
    find_latest_file,
    cleanup_old_files,
    generate_timestamp,
    format_timestamp,
    format_srt_timestamp,
    setup_logging,
    print_header,
)


# ============================================================================
# Применение имён
# ============================================================================

def load_speaker_map(analysis_path: Path) -> Dict[str, str]:
    """
    Загрузить маппинг SPEAKER_XX → Имя из файла анализа.
    
    Returns:
        {"SPEAKER_00": "Roman", "SPEAKER_05": "Hadi", ...}
    """
    with open(analysis_path, encoding="utf-8") as f:
        data = json.load(f)
    
    speaker_map = {}
    speakers = data.get("speakers", {})
    
    for speaker_id, info in speakers.items():
        name = info.get("assigned_name", speaker_id)
        speaker_map[speaker_id] = name
    
    return speaker_map


def apply_names_to_segments(
    segments: List[dict],
    speaker_map: Dict[str, str]
) -> List[dict]:
    """
    Заменить SPEAKER_XX на имена в сегментах.
    
    Сохраняет original_speaker_id для отладки.
    """
    result = []
    
    for seg in segments:
        new_seg = seg.copy()
        speaker = seg.get("speaker", "UNKNOWN")
        
        # Сохранить оригинальный ID
        new_seg["original_speaker_id"] = speaker
        
        # Заменить на имя
        if speaker in speaker_map:
            new_seg["speaker"] = speaker_map[speaker]
        
        result.append(new_seg)
    
    return result


# ============================================================================
# Сохранение файлов
# ============================================================================

def save_named_json(
    segments: List[dict],
    speakers: Set[str],
    output_path: Path,
    project_name: str,
    source_transcript: str,
    source_analysis: str,
    speaker_map: Dict[str, str]
) -> Path:
    """Сохранить транскрипт с именами в JSON."""
    data = {
        "project_name": project_name,
        "generated": datetime.now().isoformat(),
        "source_transcript": source_transcript,
        "source_analysis": source_analysis,
        "speakers": sorted(list(speakers)),
        "speaker_map": speaker_map,
        "total_segments": len(segments),
        "segments": segments
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return output_path


def save_named_txt(
    segments: List[dict],
    speakers: Set[str],
    output_path: Path,
    project_name: str
) -> Path:
    """Сохранить человекочитаемый транскрипт."""
    lines = [
        "=" * 70,
        "ТРАНСКРИПТ С ИМЕНАМИ СПИКЕРОВ",
        "=" * 70,
        "",
        f"Проект: {project_name}",
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Спикеры ({len(speakers)}): {', '.join(sorted(speakers))}",
        "",
        "-" * 70,
        "ТРАНСКРИПТ",
        "-" * 70,
        ""
    ]
    
    for seg in segments:
        ts = format_timestamp(seg["start"])
        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "")
        
        lines.append(f"[{ts}] {speaker}:")
        lines.append(f"  {text}")
        lines.append("")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return output_path


def save_named_srt(
    segments: List[dict],
    output_path: Path
) -> int:
    """
    Сохранить SRT файл с именами спикеров.
    
    Returns:
        Количество субтитров
    """
    lines = []
    idx = 1
    
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        
        start = seg["start"]
        end = seg["end"]
        speaker = seg.get("speaker", "UNKNOWN")
        
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(f"[{speaker}] {text}")
        lines.append("")
        
        idx += 1
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return idx - 1


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI Этап 3: Применение имён спикеров к транскрипту",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    python apply_names.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
        """
    )
    
    parser.add_argument("--project", required=True, help="Путь к папке проекта")
    parser.add_argument("--transcript", type=Path, help="Конкретный JSON транскрипта")
    parser.add_argument("--analysis", type=Path, help="Конкретный JSON анализа спикеров")
    
    args = parser.parse_args()
    
    # Получить пути
    try:
        paths = get_project_paths(args.project)
    except FileNotFoundError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)
    
    ensure_dirs(paths)
    
    project_name = paths["project_name"]
    timestamp = generate_timestamp()
    
    logger = setup_logging(paths["logs_dir"], project_name, "apply_names")
    
    # Найти транскрипт
    if args.transcript:
        transcript_path = args.transcript
    else:
        transcript_path = find_latest_file(
            paths["transcription_dir"],
            f"{project_name}_transcript_*.json"
        )
    
    if not transcript_path or not transcript_path.exists():
        logger.error("Транскрипт не найден")
        sys.exit(1)
    
    # Найти анализ спикеров
    if args.analysis:
        analysis_path = args.analysis
    else:
        analysis_path = find_latest_file(
            paths["transcription_dir"],
            f"{project_name}_analyze_speakers_*.json",
            exclude=["_report"]
        )
    
    if not analysis_path or not analysis_path.exists():
        logger.error("Файл анализа спикеров не найден. Сначала запустите analyze_speakers.py")
        sys.exit(1)
    
    # ================================================================
    # Заголовок
    # ================================================================
    print_header("YTAI ЭТАП 3: ПРИМЕНЕНИЕ ИМЁН")
    logger.info(f"Проект: {project_name}")
    logger.info(f"Транскрипт: {transcript_path.name}")
    logger.info(f"Анализ: {analysis_path.name}")
    logger.info("")
    
    # ================================================================
    # Загрузка данных
    # ================================================================
    logger.info("Загрузка данных...")
    
    # Транскрипт
    with open(transcript_path, encoding="utf-8") as f:
        transcript_data = json.load(f)
    
    segments = transcript_data.get("segments", [])
    logger.info(f"  Сегментов: {len(segments)}")
    
    # Маппинг спикеров
    speaker_map = load_speaker_map(analysis_path)
    logger.info(f"  Спикеров: {len(speaker_map)}")
    
    for speaker_id, name in speaker_map.items():
        logger.info(f"    {speaker_id} → {name}")
    
    # ================================================================
    # Применение имён
    # ================================================================
    logger.info("")
    logger.info("Применение имён...")
    
    segments = apply_names_to_segments(segments, speaker_map)
    
    # Получить список уникальных имён
    speakers = set(seg.get("speaker", "UNKNOWN") for seg in segments)
    speakers.discard("UNKNOWN")
    
    logger.info(f"Финальные спикеры: {', '.join(sorted(speakers))}")
    
    # ================================================================
    # Сохранение
    # ================================================================
    logger.info("")
    logger.info("Сохранение файлов...")
    
    # Очистить старые файлы
    cleanup_old_files(
        paths["transcription_dir"],
        f"{project_name}_apply_names_*"
    )
    
    # JSON
    json_path = paths["transcription_dir"] / f"{project_name}_apply_names_{timestamp}.json"
    save_named_json(
        segments, speakers, json_path, project_name,
        transcript_path.name, analysis_path.name, speaker_map
    )
    logger.info(f"  JSON: {json_path.name}")
    
    # TXT
    txt_path = paths["transcription_dir"] / f"{project_name}_apply_names_{timestamp}.txt"
    save_named_txt(segments, speakers, txt_path, project_name)
    logger.info(f"  TXT: {txt_path.name}")
    
    # SRT
    srt_path = paths["transcription_dir"] / f"{project_name}_apply_names_{timestamp}.srt"
    srt_count = save_named_srt(segments, srt_path)
    logger.info(f"  SRT: {srt_path.name} ({srt_count} субтитров)")
    
    # ================================================================
    # Итог
    # ================================================================
    print_header("ГОТОВО", char="=")
    logger.info(f"Выходная папка: {paths['transcription_dir']}")
    logger.info("")
    logger.info("Проверка:")
    logger.info(f"  1. Откройте {txt_path.name} и прочитайте диалог")
    logger.info(f"  2. Загрузите {srt_path.name} на мастер-видео в Premiere")
    logger.info("")
    logger.info("СЛЕДУЮЩИЙ ШАГ:")
    logger.info(f"  python split_clips.py --project \"{paths['project_root']}\"")


if __name__ == "__main__":
    main()
