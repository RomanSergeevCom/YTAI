#!/usr/bin/env python3
"""
YTAI Этап 1: Extract Speakers
Извлечение реплик каждого спикера в отдельные файлы.

Использование:
    python extract_speakers.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"

Выход:
    02_Transcripts/02_02_Speakers/
    ├── {project}_extract_speakers_{timestamp}/
    │   ├── _SUMMARY.txt
    │   ├── SPEAKER_00.txt
    │   └── ...
    └── {project}_extract_speakers_{timestamp}_srt/
        ├── SPEAKER_00.srt
        └── ...
"""

import argparse
import sys
import json
from pathlib import Path
from typing import Dict, List

# Добавить utils в путь
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
# Извлечение реплик
# ============================================================================

def extract_utterances_by_speaker(segments: List[dict]) -> Dict[str, List[dict]]:
    """
    Сгруппировать сегменты транскрипта по спикерам.
    
    Returns:
        {
            "SPEAKER_00": [
                {"text": "...", "start": 0.0, "end": 1.5, "index": 0},
                ...
            ]
        }
    """
    speaker_utterances: Dict[str, List[dict]] = {}
    
    for idx, seg in enumerate(segments):
        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "").strip()
        
        if not text:
            continue
        
        if speaker not in speaker_utterances:
            speaker_utterances[speaker] = []
        
        speaker_utterances[speaker].append({
            "text": text,
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "index": idx
        })
    
    return speaker_utterances


def get_speaker_stats(speaker_utterances: Dict[str, List[dict]]) -> List[dict]:
    """
    Получить статистику по спикерам.
    
    Returns:
        Список отсортированный по количеству реплик (убывание):
        [{"speaker": "SPEAKER_05", "count": 470, "words": 15000, "duration": 1800}, ...]
    """
    stats = []
    
    for speaker, utterances in speaker_utterances.items():
        words = sum(len(u["text"].split()) for u in utterances)
        duration = sum(u["end"] - u["start"] for u in utterances)
        
        stats.append({
            "speaker": speaker,
            "count": len(utterances),
            "words": words,
            "duration": duration
        })
    
    stats.sort(key=lambda x: x["count"], reverse=True)
    return stats


# ============================================================================
# Запись файлов
# ============================================================================

def save_utterances_file(
    speaker_id: str,
    utterances: List[dict],
    output_dir: Path,
    project_name: str
) -> Path:
    """Сохранить все реплики спикера в текстовый файл."""
    filepath = output_dir / f"{speaker_id}.txt"
    
    total_words = sum(len(u["text"].split()) for u in utterances)
    
    lines = [
        "=" * 70,
        f"SPEAKER: {speaker_id}",
        f"PROJECT: {project_name}",
        f"TOTAL UTTERANCES: {len(utterances)}",
        f"TOTAL WORDS: {total_words}",
        "=" * 70,
        "",
        "Для анализа этого спикера проверьте:",
        "1. Это ОДИН человек или несколько смешались?",
        "2. Есть ли самопредставление: 'My name is...', 'I am...'?",
        "3. Какая роль: ведущий (вопросы) / гость (ответы) / другое?",
        "",
        "-" * 70,
        "ВСЕ РЕПЛИКИ:",
        "-" * 70,
        ""
    ]
    
    for i, utt in enumerate(utterances, 1):
        ts = format_timestamp(utt["start"])
        lines.append(f"[{i:04d}] [{ts}] {utt['text']}")
        lines.append("")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return filepath


def save_speaker_srt(
    speaker_id: str,
    utterances: List[dict],
    output_dir: Path
) -> Path:
    """Сохранить реплики спикера в SRT формате."""
    filepath = output_dir / f"{speaker_id}.srt"
    
    lines = []
    for i, utt in enumerate(utterances, 1):
        lines.append(str(i))
        lines.append(f"{format_srt_timestamp(utt['start'])} --> {format_srt_timestamp(utt['end'])}")
        lines.append(utt["text"])
        lines.append("")
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return filepath


def save_summary(
    stats: List[dict],
    output_dir: Path,
    project_name: str,
    transcript_file: str
) -> Path:
    """Сохранить сводку по всем спикерам."""
    filepath = output_dir / "_SUMMARY.txt"
    
    lines = [
        "=" * 70,
        "ИЗВЛЕЧЕНИЕ РЕПЛИК СПИКЕРОВ",
        "=" * 70,
        "",
        f"Проект: {project_name}",
        f"Источник: {transcript_file}",
        f"Всего спикеров: {len(stats)}",
        "",
        "-" * 70,
        "СПИКЕРЫ (по активности):",
        "-" * 70,
        ""
    ]
    
    for i, stat in enumerate(stats, 1):
        duration_str = format_timestamp(stat["duration"])
        avg_words = stat["words"] / stat["count"] if stat["count"] > 0 else 0
        
        lines.append(
            f"{i:2d}. {stat['speaker']:12s} | "
            f"{stat['count']:4d} реплик | "
            f"{stat['words']:5d} слов | "
            f"{duration_str} времени | "
            f"~{avg_words:.1f} сл/реплику"
        )
    
    # Подсказки
    lines.extend([
        "",
        "-" * 70,
        "ПОДСКАЗКИ:",
        "-" * 70,
        ""
    ])
    
    if stats:
        most_active = stats[0]
        lines.append(f"• {most_active['speaker']} — вероятно главный гость (больше всего речи)")
        
        if len(stats) > 1:
            second = stats[1]
            lines.append(f"• {second['speaker']} — вероятно ведущий (второй по активности, задаёт вопросы)")
    
    lines.extend([
        "",
        "-" * 70,
        "КАК ПРОВЕРИТЬ:",
        "-" * 70,
        "",
        "1. Откройте файлы SPEAKER_XX.txt и просмотрите реплики",
        "2. Загрузите SPEAKER_XX.srt на мастер-видео в Premiere Pro",
        "   → Увидите ТОЛЬКО этого спикера, легко проверить разделение",
        "",
        "ЕСЛИ СПИКЕРЫ СМЕШАНЫ:",
        "   Перезапустите transcribe_project.py с параметром --num-speakers N",
        "",
        "-" * 70,
        "СЛЕДУЮЩИЙ ШАГ:",
        "-" * 70,
        "",
        f"python analyze_speakers.py --project \"<путь к проекту>\"",
        ""
    ])
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return filepath


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI Этап 1: Извлечение реплик спикеров",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    python extract_speakers.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python extract_speakers.py --project "/path/to/project" --overwrite
        """
    )
    
    parser.add_argument("--project", required=True, help="Путь к папке проекта")
    parser.add_argument("--transcript", type=Path, help="Конкретный JSON транскрипта (по умолчанию: последний)")
    parser.add_argument("--overwrite", action="store_true", help="Перезаписать без вопросов")
    
    args = parser.parse_args()
    
    # Получить пути проекта
    try:
        paths = get_project_paths(args.project)
    except FileNotFoundError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)
    
    ensure_dirs(paths)
    
    project_name = paths["project_name"]
    timestamp = generate_timestamp()
    
    # Настроить логирование
    logger = setup_logging(paths["logs_dir"], project_name, "extract_speakers")
    
    # Найти транскрипт
    if args.transcript:
        transcript_path = args.transcript
    else:
        transcript_path = find_latest_file(
            paths["runs_dir"],
            f"{project_name}_transcript_*.json"
        )
    
    if not transcript_path or not transcript_path.exists():
        logger.error("Транскрипт не найден. Сначала запустите transcribe_project.py")
        sys.exit(1)
    
    # ================================================================
    # Заголовок
    # ================================================================
    print_header("YTAI ЭТАП 1: ИЗВЛЕЧЕНИЕ РЕПЛИК СПИКЕРОВ")
    logger.info(f"Проект: {project_name}")
    logger.info(f"Транскрипт: {transcript_path.name}")
    logger.info("")
    
    # ================================================================
    # Загрузка транскрипта
    # ================================================================
    logger.info("Загрузка транскрипта...")
    
    with open(transcript_path, encoding="utf-8") as f:
        data = json.load(f)
    
    segments = data.get("segments", [])
    if not segments:
        logger.error("В транскрипте нет сегментов")
        sys.exit(1)
    
    logger.info(f"Загружено {len(segments)} сегментов")
    
    # ================================================================
    # Извлечение реплик
    # ================================================================
    logger.info("")
    logger.info("Извлечение реплик по спикерам...")
    
    speaker_utterances = extract_utterances_by_speaker(segments)
    stats = get_speaker_stats(speaker_utterances)
    
    logger.info(f"Найдено {len(speaker_utterances)} спикеров:")
    for stat in stats:
        logger.info(f"  {stat['speaker']}: {stat['count']} реплик, {stat['words']} слов")
    
    # ================================================================
    # Подготовка выходных папок
    # ================================================================
    logger.info("")
    
    output_dir = paths["clean_dir"] / f"{project_name}_extract_speakers_{timestamp}"
    srt_dir = paths["clean_dir"] / f"{project_name}_extract_speakers_{timestamp}_srt"
    
    # Очистить старые файлы
    old_count = cleanup_old_files(
        paths["clean_dir"],
        f"{project_name}_extract_speakers_*"
    )
    if old_count > 0:
        logger.info(f"Перемещено в backup/: {old_count} старых папок/файлов")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    srt_dir.mkdir(parents=True, exist_ok=True)
    
    # ================================================================
    # Запись файлов
    # ================================================================
    logger.info("Запись файлов...")
    
    for stat in stats:
        speaker = stat["speaker"]
        utterances = speaker_utterances[speaker]
        
        # Текстовый файл
        txt_path = save_utterances_file(speaker, utterances, output_dir, project_name)
        logger.debug(f"  {txt_path.name}")
        
        # SRT файл
        srt_path = save_speaker_srt(speaker, utterances, srt_dir)
        logger.debug(f"  {srt_path.name}")
    
    # Сводка
    summary_path = save_summary(stats, output_dir, project_name, transcript_path.name)
    logger.info(f"  {summary_path.name}")
    
    # ================================================================
    # Итог
    # ================================================================
    print_header("ГОТОВО", char="=")
    logger.info(f"Реплики: {output_dir}")
    logger.info(f"SRT:     {srt_dir}")
    logger.info("")
    logger.info("СЛЕДУЮЩИЙ ШАГ:")
    logger.info(f"  1. Проверьте файлы в {output_dir.name}/")
    logger.info(f"  2. Загрузите SRT на мастер-видео для проверки разделения")
    logger.info(f"  3. Запустите: python analyze_speakers.py --project \"{paths['project_root']}\"")


if __name__ == "__main__":
    main()
