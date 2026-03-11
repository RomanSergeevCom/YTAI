#!/usr/bin/env python3
"""
YTAI: Process All
Master скрипт - запуск всех этапов обработки транскрипта.

Использование:
    python process_all.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python process_all.py --project "/path/to/project" --no-pause
    python process_all.py --project "/path/to/project" --start-from 3

Этапы:
    1. 01_extract_speakers.py  - Извлечение реплик спикеров
    2. 02_analyze_speakers.py  - LLM анализ имён
    3. 03_apply_names.py       - Применение имён к транскрипту
    4. 04_split_clips.py       - Разбивка по видео клипам
"""

import argparse
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    get_project_paths,
    ensure_dirs,
    generate_timestamp,
    format_duration,
    setup_logging,
    print_header,
    print_section,
)


# ============================================================================
# Запуск этапов
# ============================================================================

def run_stage(
    stage_num: int,
    script_name: str,
    project_path: str,
    extra_args: list = None,
    logger = None
) -> bool:
    """
    Запустить один этап.
    
    Returns:
        True если успешно
    """
    scripts_dir = Path(__file__).parent
    script_path = scripts_dir / script_name
    
    if not script_path.exists():
        if logger:
            logger.error(f"Скрипт не найден: {script_path}")
        return False
    
    cmd = [
        sys.executable,
        str(script_path),
        "--project", project_path
    ]
    
    if extra_args:
        cmd.extend(extra_args)
    
    if logger:
        logger.debug(f"Запуск: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,  # Показывать вывод в реальном времени
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        if logger:
            logger.error(f"Ошибка запуска {script_name}: {e}")
        return False


def ask_continue(prompt: str = "Продолжить?") -> bool:
    """Спросить пользователя о продолжении."""
    try:
        response = input(f"\n{prompt} [Y/n]: ").strip().lower()
        return response != "n"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI: Запуск всех этапов обработки транскрипта",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    # Полный цикл с паузами для проверки
    python process_all.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    
    # Автоматом без пауз
    python process_all.py --project "/path/to/project" --no-pause
    
    # Начать с этапа 3 (спикеры уже проанализированы)
    python process_all.py --project "/path/to/project" --start-from 3
    
    # Только этапы 1-2
    python process_all.py --project "/path/to/project" --stop-after 2
        """
    )
    
    parser.add_argument("--project", required=True, help="Путь к папке проекта")
    parser.add_argument("--no-pause", action="store_true", help="Не останавливаться для проверки")
    parser.add_argument("--start-from", type=int, choices=[1, 2, 3, 4], default=1,
                        help="Начать с этапа N (по умолчанию: 1)")
    parser.add_argument("--stop-after", type=int, choices=[1, 2, 3, 4], default=4,
                        help="Остановиться после этапа N (по умолчанию: 4)")
    parser.add_argument("--force", action="store_true", 
                        help="Передать --force в 02_analyze_speakers.py")
    
    args = parser.parse_args()
    
    # Проверить пути
    try:
        paths = get_project_paths(args.project)
    except FileNotFoundError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        sys.exit(1)
    
    ensure_dirs(paths)
    
    project_name = paths["project_name"]
    
    # Настроить логирование
    logger = setup_logging(paths["logs_dir"], project_name, "process_all")
    
    # ================================================================
    # Заголовок
    # ================================================================
    print_header("YTAI: ПОЛНАЯ ОБРАБОТКА ТРАНСКРИПТА")
    logger.info(f"Проект: {project_name}")
    logger.info(f"Путь: {paths['project_root']}")
    logger.info(f"Этапы: {args.start_from} - {args.stop_after}")
    if args.no_pause:
        logger.info("Режим: автоматический (без пауз)")
    else:
        logger.info("Режим: интерактивный (с паузами для проверки)")
    logger.info("")
    
    start_time = time.time()
    stages_completed = 0
    
    # ================================================================
    # ЭТАП 1: Extract Speakers
    # ================================================================
    if args.start_from <= 1 <= args.stop_after:
        print_section("[1/4] ИЗВЛЕЧЕНИЕ РЕПЛИК СПИКЕРОВ")
        logger.info("Запуск 01_extract_speakers.py...")
        logger.info("")
        
        success = run_stage(1, "01_extract_speakers.py", str(paths["project_root"]), logger=logger)
        
        if not success:
            logger.error("Этап 1 завершился с ошибкой")
            sys.exit(1)
        
        stages_completed += 1
        
        if not args.no_pause and args.stop_after > 1:
            logger.info("")
            logger.info("→ Проверьте файлы в 02_02_Speakers/")
            logger.info("→ Загрузите SRT на мастер-видео для проверки разделения спикеров")
            
            if not ask_continue():
                logger.info("Остановлено пользователем")
                sys.exit(0)
    
    # ================================================================
    # ЭТАП 2: Analyze Speakers
    # ================================================================
    if args.start_from <= 2 <= args.stop_after:
        print_section("[2/4] АНАЛИЗ СПИКЕРОВ (LLM)")
        logger.info("Запуск 02_analyze_speakers.py...")
        logger.info("")
        
        extra_args = []
        if args.force:
            extra_args.append("--force")
        
        success = run_stage(2, "02_analyze_speakers.py", str(paths["project_root"]), 
                           extra_args=extra_args, logger=logger)
        
        if not success:
            logger.error("Этап 2 завершился с ошибкой")
            sys.exit(1)
        
        stages_completed += 1
        
        if not args.no_pause and args.stop_after > 2:
            logger.info("")
            logger.info("→ Проверьте *_analyze_speakers_*_report.txt")
            logger.info("→ При необходимости отредактируйте *_analyze_speakers_*.json")
            
            if not ask_continue():
                logger.info("Остановлено пользователем")
                sys.exit(0)
    
    # ================================================================
    # ЭТАП 3: Apply Names
    # ================================================================
    if args.start_from <= 3 <= args.stop_after:
        print_section("[3/4] ПРИМЕНЕНИЕ ИМЁН")
        logger.info("Запуск 03_apply_names.py...")
        logger.info("")
        
        success = run_stage(3, "03_apply_names.py", str(paths["project_root"]), logger=logger)
        
        if not success:
            logger.error("Этап 3 завершился с ошибкой")
            sys.exit(1)
        
        stages_completed += 1
        
        if not args.no_pause and args.stop_after > 3:
            logger.info("")
            logger.info("→ Проверьте *_apply_names_*.txt - прочитайте диалог")
            
            if not ask_continue():
                logger.info("Остановлено пользователем")
                sys.exit(0)
    
    # ================================================================
    # ЭТАП 4: Split Clips
    # ================================================================
    if args.start_from <= 4 <= args.stop_after:
        print_section("[4/4] РАЗБИВКА ПО КЛИПАМ")
        logger.info("Запуск 04_split_clips.py...")
        logger.info("")
        
        success = run_stage(4, "04_split_clips.py", str(paths["project_root"]), logger=logger)
        
        if not success:
            logger.error("Этап 4 завершился с ошибкой")
            sys.exit(1)
        
        stages_completed += 1
    
    # ================================================================
    # Итог
    # ================================================================
    elapsed = time.time() - start_time
    
    print()
    print_header("ОБРАБОТКА ЗАВЕРШЕНА", char="=")
    logger.info(f"Выполнено этапов: {stages_completed}")
    logger.info(f"Время: {format_duration(elapsed)}")
    logger.info("")
    logger.info("Результаты:")
    logger.info(f"  02_03_Named/     - Транскрипт с именами (.json, .txt, .srt)")
    logger.info(f"  02_04_ByClips/   - XLSX таблица + SRT для каждого клипа")
    logger.info("")
    logger.info("Для проверки в Premiere Pro:")
    logger.info("  1. Импортируйте клип и соответствующий SRT")
    logger.info("  2. Убедитесь что субтитры совпадают с речью")


if __name__ == "__main__":
    main()
