#!/usr/bin/env python3
"""
YTAI Этап 2: Analyze Speakers
LLM анализ для определения имён и ролей спикеров.

Использование:
    python analyze_speakers.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python analyze_speakers.py --project "/path/to/project" --force

Выход:
    01_Media/Source/Transcription/
    ├── {project}_analyze_speakers_{timestamp}.json
    └── {project}_analyze_speakers_{timestamp}_report.txt
"""

import argparse
import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    get_project_paths,
    ensure_dirs,
    find_latest_file,
    find_latest_dir,
    cleanup_old_files,
    load_channel_profile,
    extract_guest_hint,
    generate_timestamp,
    format_timestamp,
    format_duration,
    setup_logging,
    print_header,
    check_ollama_server,
    call_ollama,
    parse_json_response,
    build_speaker_analysis_prompt,
    DEFAULT_LLM_MODEL,
)


# ============================================================================
# Загрузка реплик
# ============================================================================

def load_utterances_from_dir(utterances_dir: Path) -> Dict[str, List[dict]]:
    """
    Загрузить реплики спикеров из папки extract_speakers.
    
    Returns:
        {"SPEAKER_00": [{"text": "...", "start": 0.0}, ...], ...}
    """
    import re
    
    speaker_utterances = {}
    
    for txt_file in utterances_dir.glob("SPEAKER_*.txt"):
        speaker_id = txt_file.stem  # SPEAKER_00
        utterances = []
        
        with open(txt_file, encoding="utf-8") as f:
            content = f.read()
        
        # Парсим реплики из файла
        # Формат: [0001] [00:00:30] Text here\n\n
        # Используем более надёжный подход - ищем начало каждой реплики
        # и берём текст до следующей реплики или конца файла
        
        # Найти все начала реплик
        pattern = r'\[(\d+)\]\s+\[(\d+):(\d+):(\d+)\]\s+'
        matches = list(re.finditer(pattern, content))
        
        for i, match in enumerate(matches):
            idx = int(match.group(1))
            hours = int(match.group(2))
            minutes = int(match.group(3))
            secs = int(match.group(4))
            seconds = hours * 3600 + minutes * 60 + secs
            
            # Текст начинается после match и заканчивается перед следующим match
            text_start = match.end()
            if i + 1 < len(matches):
                text_end = matches[i + 1].start()
            else:
                text_end = len(content)
            
            text = content[text_start:text_end].strip()
            
            if text:
                utterances.append({
                    "text": text,
                    "start": float(seconds),
                    "index": idx
                })
        
        if utterances:
            speaker_utterances[speaker_id] = utterances
    
    return speaker_utterances


# ============================================================================
# Анализ спикера через LLM
# ============================================================================

def analyze_speaker(
    speaker_id: str,
    utterances: List[dict],
    model: str,
    channel_context: Optional[str],
    guest_hint: Optional[str],
    logger
) -> dict:
    """
    Проанализировать одного спикера через LLM.
    
    Returns:
        {
            "assigned_name": "Hadi",
            "found_in_text": true,
            "name_evidence": "My name is Hadi...",
            "role": "guest",
            "confidence": "high",
            "reasoning": "...",
            "utterance_count": 470,
            "word_count": 15000
        }
    """
    # Статистика
    word_count = sum(len(u["text"].split()) for u in utterances)
    
    # Построить промпт
    prompt = build_speaker_analysis_prompt(
        speaker_id,
        utterances,
        channel_context=channel_context,
        guest_hint=guest_hint
    )
    
    # Вызвать LLM
    response = call_ollama(prompt, model=model, logger=logger, timeout=600)
    
    if not response:
        logger.warning(f"  LLM не ответил для {speaker_id}")
        return {
            "assigned_name": speaker_id,
            "found_in_text": False,
            "name_evidence": "",
            "role": "unknown",
            "confidence": "low",
            "reasoning": "LLM не ответил",
            "utterance_count": len(utterances),
            "word_count": word_count
        }
    
    # Распарсить JSON
    parsed = parse_json_response(response, logger)
    
    if not parsed:
        logger.warning(f"  Не удалось распарсить ответ для {speaker_id}")
        return {
            "assigned_name": speaker_id,
            "found_in_text": False,
            "name_evidence": "",
            "role": "unknown",
            "confidence": "low",
            "reasoning": "Ошибка парсинга ответа LLM",
            "utterance_count": len(utterances),
            "word_count": word_count
        }
    
    # Извлечь данные
    result = {
        "assigned_name": parsed.get("assigned_name", speaker_id),
        "found_in_text": parsed.get("found_in_text", False),
        "name_evidence": parsed.get("name_evidence", ""),
        "role": parsed.get("role", "unknown").lower(),
        "confidence": parsed.get("confidence", "low").lower(),
        "reasoning": parsed.get("reasoning", ""),
        "utterance_count": len(utterances),
        "word_count": word_count
    }
    
    # Если host без имени — использовать Roman
    if result["role"] == "host" and not result["found_in_text"]:
        if result["assigned_name"].lower() in ["host", "interviewer", speaker_id.lower()]:
            result["assigned_name"] = "Roman"
    
    return result


# ============================================================================
# Сохранение результатов
# ============================================================================

def compute_checksum(data: dict) -> str:
    """Вычислить контрольную сумму для определения ручных правок."""
    # Исключить _meta из подсчёта
    data_copy = {k: v for k, v in data.items() if k != "_meta"}
    json_str = json.dumps(data_copy, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(json_str.encode()).hexdigest()[:16]


def save_analysis_json(
    speakers: Dict[str, dict],
    output_path: Path,
    project_name: str,
    guest_hint: Optional[str],
    model: str,
    source_dir: str
) -> Path:
    """Сохранить результаты анализа в JSON."""
    data = {
        "speakers": speakers
    }
    
    # Добавить метаданные
    data["_meta"] = {
        "generated": datetime.now().isoformat(),
        "generator": "analyze_speakers.py",
        "project_name": project_name,
        "guest_hint": guest_hint,
        "llm_model": model,
        "source": source_dir,
        "checksum": compute_checksum(data)
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return output_path


def save_analysis_report(
    speakers: Dict[str, dict],
    output_path: Path,
    project_name: str,
    guest_hint: Optional[str]
) -> Path:
    """Сохранить человекочитаемый отчёт."""
    lines = [
        "=" * 70,
        "ОТЧЁТ ПО АНАЛИЗУ СПИКЕРОВ",
        "=" * 70,
        "",
        f"Проект: {project_name}",
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    
    if guest_hint:
        lines.append(f"Подсказка из названия проекта: \"{guest_hint}\"")
    
    lines.extend([
        "",
        "ОБОЗНАЧЕНИЯ:",
        "  [✓] HIGH — имя найдено в тексте или роль очевидна",
        "  [~] MEDIUM — роль понятна, но имя не подтверждено",
        "  [?] LOW — требуется ручная проверка",
        "",
    ])
    
    # Сортировать по количеству реплик
    sorted_speakers = sorted(
        speakers.items(),
        key=lambda x: x[1].get("utterance_count", 0),
        reverse=True
    )
    
    high_count = 0
    medium_count = 0
    low_count = 0
    
    for speaker_id, data in sorted_speakers:
        confidence = data.get("confidence", "low")
        
        if confidence == "high":
            status = "[✓]"
            high_count += 1
        elif confidence == "medium":
            status = "[~]"
            medium_count += 1
        else:
            status = "[?]"
            low_count += 1
        
        lines.append("-" * 70)
        lines.append(f"{status} {speaker_id} → {data.get('assigned_name', speaker_id)}")
        lines.append(f"    Уверенность: {confidence.upper()}")
        lines.append(f"    Роль: {data.get('role', 'unknown')}")
        lines.append(f"    Имя в тексте: {'Да' if data.get('found_in_text') else 'Нет'}")
        lines.append(f"    Реплик: {data.get('utterance_count', 0)} | Слов: {data.get('word_count', 0)}")
        
        if data.get("name_evidence"):
            evidence = data["name_evidence"][:100]
            lines.append(f"    Доказательство: \"{evidence}\"")
        
        if data.get("reasoning"):
            reasoning = data["reasoning"][:150]
            lines.append(f"    Обоснование: {reasoning}")
        
        # Предупреждения
        if confidence == "low" and data.get("utterance_count", 0) > 20:
            lines.append("")
            lines.append(f"    ⚠️ ТРЕБУЕТСЯ ПРОВЕРКА: много реплик, но низкая уверенность")
        
        lines.append("")
    
    # Итог
    lines.extend([
        "=" * 70,
        "ИТОГ",
        "=" * 70,
        "",
        f"  ✓ Высокая уверенность: {high_count}",
        f"  ~ Средняя уверенность: {medium_count}",
        f"  ? Низкая уверенность: {low_count}",
        "",
    ])
    
    if low_count > 0:
        lines.extend([
            "РЕКОМЕНДАЦИЯ:",
            "  Проверьте спикеров с низкой уверенностью.",
            "  Отредактируйте *_analyze_speakers_*.json если нужно исправить имена.",
            "",
        ])
    
    lines.extend([
        "-" * 70,
        "СЛЕДУЮЩИЙ ШАГ:",
        "-" * 70,
        "",
        "Если имена правильные:",
        f"  python apply_names.py --project \"<путь к проекту>\"",
        "",
        "Если нужно исправить:",
        "  1. Откройте *_analyze_speakers_*.json",
        '  2. Измените "assigned_name" для нужного спикера',
        "  3. Сохраните файл",
        "  4. Запустите apply_names.py",
        ""
    ])
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return output_path


# ============================================================================
# Проверка существующего файла
# ============================================================================

def check_existing_analysis(transcription_dir: Path, project_name: str, logger) -> Optional[Path]:
    """
    Проверить наличие существующего анализа.
    
    Returns:
        Path к существующему файлу или None
    """
    existing = find_latest_file(
        transcription_dir,
        f"{project_name}_analyze_speakers_*.json"
    )
    
    if not existing:
        return None
    
    # Проверить был ли файл изменён вручную
    try:
        with open(existing, encoding="utf-8") as f:
            data = json.load(f)
        
        meta = data.get("_meta", {})
        stored_checksum = meta.get("checksum", "")
        
        # Пересчитать checksum
        current_checksum = compute_checksum(data)
        
        if stored_checksum and stored_checksum != current_checksum:
            logger.warning(f"⚠️ Файл был изменён вручную: {existing.name}")
            return existing
        else:
            logger.info(f"Найден существующий анализ: {existing.name}")
            return existing
            
    except Exception as e:
        logger.warning(f"Ошибка чтения {existing}: {e}")
        return None


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI Этап 2: Анализ спикеров через LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
    python analyze_speakers.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python analyze_speakers.py --project "/path/to/project" --force
    python analyze_speakers.py --project "/path/to/project" --model llama3.3:70b
        """
    )
    
    parser.add_argument("--project", required=True, help="Путь к папке проекта")
    parser.add_argument("--force", action="store_true", help="Принудительно перезапустить анализ")
    parser.add_argument("--model", default=DEFAULT_LLM_MODEL, help=f"Модель LLM (по умолчанию: {DEFAULT_LLM_MODEL})")
    parser.add_argument("--min-utterances", type=int, default=5, help="Минимум реплик для анализа (по умолчанию: 5)")
    
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
    
    logger = setup_logging(paths["logs_dir"], project_name, "analyze_speakers")
    
    # Найти папку с репликами
    utterances_dir = find_latest_dir(
        paths["transcription_dir"],
        f"{project_name}_extract_speakers_*"
    )
    
    # Исключить папки _srt
    if utterances_dir and "_srt" in utterances_dir.name:
        # Найти папку без _srt
        all_dirs = list(paths["transcription_dir"].glob(f"{project_name}_extract_speakers_*"))
        utterances_dir = None
        for d in sorted(all_dirs, key=lambda x: x.stat().st_mtime, reverse=True):
            if d.is_dir() and "_srt" not in d.name and "backup" not in str(d):
                utterances_dir = d
                break
    
    if not utterances_dir or not utterances_dir.exists():
        logger.error("Папка с репликами не найдена. Сначала запустите extract_speakers.py")
        sys.exit(1)
    
    # ================================================================
    # Заголовок
    # ================================================================
    print_header("YTAI ЭТАП 2: АНАЛИЗ СПИКЕРОВ")
    logger.info(f"Проект: {project_name}")
    logger.info(f"Реплики: {utterances_dir.name}")
    logger.info(f"Модель: {args.model}")
    logger.info("")
    
    # ================================================================
    # Проверка существующего анализа
    # ================================================================
    if not args.force:
        existing = check_existing_analysis(paths["transcription_dir"], project_name, logger)
        
        if existing:
            # Спросить пользователя
            logger.info("")
            response = input("Использовать существующий анализ? [Y/n]: ").strip().lower()
            
            if response != "n":
                logger.info("Используем существующий файл")
                logger.info(f"Для принудительного перезапуска используйте --force")
                sys.exit(0)
            else:
                logger.info("Перезапускаем анализ...")
    
    # ================================================================
    # Проверка Ollama
    # ================================================================
    if not check_ollama_server(logger):
        logger.error("Ollama сервер не запущен!")
        logger.error("Запустите: ollama serve")
        sys.exit(1)
    
    # ================================================================
    # Загрузка данных
    # ================================================================
    logger.info("Загрузка реплик...")
    
    speaker_utterances = load_utterances_from_dir(utterances_dir)
    
    if not speaker_utterances:
        logger.error("Реплики не найдены")
        sys.exit(1)
    
    logger.info(f"Загружено {len(speaker_utterances)} спикеров")
    
    # Загрузить контекст канала
    channel_context = load_channel_profile(paths["project_root"])
    if channel_context:
        logger.info("Загружен профиль канала")
    
    # Подсказка имени гостя
    guest_hint = extract_guest_hint(project_name)
    if guest_hint:
        logger.info(f"Подсказка из названия: \"{guest_hint}\"")
    
    # ================================================================
    # Анализ спикеров
    # ================================================================
    logger.info("")
    logger.info("Анализ спикеров через LLM...")
    logger.info("-" * 40)
    
    # Сортировать по количеству реплик
    sorted_speakers = sorted(
        speaker_utterances.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )
    
    speakers_result = {}
    used_names = set()
    
    for i, (speaker_id, utterances) in enumerate(sorted_speakers, 1):
        count = len(utterances)
        
        logger.info(f"[{i}/{len(sorted_speakers)}] {speaker_id} ({count} реплик)")
        
        # Пропустить спикеров с малым количеством реплик
        if count < args.min_utterances:
            logger.info(f"  → Minor (меньше {args.min_utterances} реплик)")
            speakers_result[speaker_id] = {
                "assigned_name": "Minor",
                "found_in_text": False,
                "name_evidence": "",
                "role": "minor",
                "confidence": "low",
                "reasoning": f"Только {count} реплик — недостаточно для анализа",
                "utterance_count": count,
                "word_count": sum(len(u["text"].split()) for u in utterances)
            }
            # НЕ добавляем "minor" в used_names - может быть несколько Minor спикеров
            continue
        
        # Анализировать
        result = analyze_speaker(
            speaker_id,
            utterances,
            args.model,
            channel_context,
            guest_hint,
            logger
        )
        
        # Проверить дубликаты имён (кроме Minor)
        name = result["assigned_name"]
        name_lower = name.lower()
        
        if name_lower != "minor" and name_lower in used_names:
            counter = 2
            while f"{name_lower} {counter}" in used_names:
                counter += 1
            name = f"{name} {counter}"
            result["assigned_name"] = name
            result["reasoning"] += f" (переименовано во избежание дубликата)"
            logger.info(f"  → {name} (переименовано)")
        else:
            logger.info(f"  → {name} ({result['confidence']})")
        
        if name_lower != "minor":
            used_names.add(name.lower())
        speakers_result[speaker_id] = result
    
    # ================================================================
    # Сохранение результатов
    # ================================================================
    logger.info("")
    logger.info("Сохранение результатов...")
    
    # Очистить старые файлы
    cleanup_old_files(
        paths["transcription_dir"],
        f"{project_name}_analyze_speakers_*"
    )
    
    # JSON
    json_path = paths["transcription_dir"] / f"{project_name}_analyze_speakers_{timestamp}.json"
    save_analysis_json(
        speakers_result,
        json_path,
        project_name,
        guest_hint,
        args.model,
        utterances_dir.name
    )
    logger.info(f"JSON: {json_path.name}")
    
    # Отчёт
    report_path = paths["transcription_dir"] / f"{project_name}_analyze_speakers_{timestamp}_report.txt"
    save_analysis_report(speakers_result, report_path, project_name, guest_hint)
    logger.info(f"Отчёт: {report_path.name}")
    
    # ================================================================
    # Итог
    # ================================================================
    print_header("ГОТОВО", char="=")
    
    high = sum(1 for s in speakers_result.values() if s.get("confidence") == "high")
    medium = sum(1 for s in speakers_result.values() if s.get("confidence") == "medium")
    low = sum(1 for s in speakers_result.values() if s.get("confidence") == "low")
    
    logger.info(f"Уверенность: {high} высокая, {medium} средняя, {low} низкая")
    logger.info("")
    
    if low > 0:
        logger.info("⚠️ Проверьте спикеров с низкой уверенностью в отчёте")
        logger.info("")
    
    logger.info("СЛЕДУЮЩИЙ ШАГ:")
    logger.info(f"  1. Проверьте {report_path.name}")
    logger.info(f"  2. При необходимости отредактируйте {json_path.name}")
    logger.info(f"  3. Запустите: python apply_names.py --project \"{paths['project_root']}\"")


if __name__ == "__main__":
    main()
