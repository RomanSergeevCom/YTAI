#!/usr/bin/env python3
"""
YTAI Utils: Paths
Пути проекта, поиск файлов, backup.
"""

import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List


# ============================================================================
# Константы структуры проекта
# ============================================================================

VIDEO_DIR = "01_Media/Source/Video"
AUDIO_DIR = "01_Media/Source/Audio"
TRANSCRIPTION_DIR = "01_Media/Source/Transcription"
SETUP_DIR = "01_Media/Source/Setup"
DJI_PIPELINE_DIR = "99_Pipeline/DJI_Audio"
LOGS_DIR = "01_Media/Source/Setup/logs"

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}


# ============================================================================
# Пути проекта
# ============================================================================

def get_project_paths(project_dir: str) -> dict:
    """
    Получить все пути проекта.
    
    Args:
        project_dir: Путь к папке проекта
        
    Returns:
        Dict со всеми путями
        
    Raises:
        FileNotFoundError: Если папка проекта не существует
    """
    project_root = Path(project_dir).expanduser().resolve()
    
    if not project_root.exists():
        raise FileNotFoundError(f"Папка проекта не найдена: {project_root}")
    
    return {
        "project_root": project_root,
        "project_name": project_root.name,
        "video_dir": project_root / VIDEO_DIR,
        "audio_dir": project_root / AUDIO_DIR,
        "transcription_dir": project_root / TRANSCRIPTION_DIR,
        "setup_dir": project_root / SETUP_DIR,
        "dji_pipeline_dir": project_root / DJI_PIPELINE_DIR,
        "logs_dir": project_root / LOGS_DIR,
    }


def ensure_dirs(paths: dict) -> None:
    """Создать все необходимые директории."""
    for key in ["transcription_dir", "setup_dir", "logs_dir"]:
        if key in paths:
            paths[key].mkdir(parents=True, exist_ok=True)


# ============================================================================
# Поиск файлов
# ============================================================================

def find_latest_file(directory: Path, pattern: str, exclude: Optional[List[str]] = None) -> Optional[Path]:
    """
    Найти последний файл по паттерну (по дате модификации).
    
    Args:
        directory: Директория для поиска
        pattern: Glob паттерн (например "*_transcript_*.json")
        exclude: Список подстрок для исключения
        
    Returns:
        Path к последнему файлу или None
    """
    if not directory.exists():
        return None
    
    files = list(directory.glob(pattern))
    
    # Исключить файлы с определёнными подстроками
    if exclude:
        files = [f for f in files if not any(ex in f.name for ex in exclude)]
    
    # Исключить backup/
    files = [f for f in files if "backup" not in str(f)]
    
    if not files:
        return None
    
    # Сортировка по дате модификации (последний первый)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0]


def find_latest_dir(directory: Path, pattern: str) -> Optional[Path]:
    """
    Найти последнюю папку по паттерну.
    
    Args:
        directory: Директория для поиска
        pattern: Glob паттерн (например "*_extract_speakers_*")
        
    Returns:
        Path к последней папке или None
    """
    if not directory.exists():
        return None
    
    dirs = [d for d in directory.glob(pattern) if d.is_dir() and "backup" not in str(d)]
    
    if not dirs:
        return None
    
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0]


# ============================================================================
# Backup
# ============================================================================

def move_to_backup(path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Переместить файл/папку в backup/.
    
    Args:
        path: Файл или папка для перемещения
        backup_dir: Папка backup (по умолчанию: рядом с path)
        
    Returns:
        Новый путь в backup или None если path не существует
    """
    if not path.exists():
        return None
    
    if backup_dir is None:
        backup_dir = path.parent / "backup"
    
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Если файл с таким именем уже есть в backup - добавить timestamp
    dest = backup_dir / path.name
    if dest.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if path.is_dir():
            dest = backup_dir / f"{path.name}_{timestamp}"
        else:
            dest = backup_dir / f"{path.stem}_{timestamp}{path.suffix}"
    
    shutil.move(str(path), str(dest))
    return dest


def cleanup_old_files(directory: Path, pattern: str, backup_dir: Optional[Path] = None) -> int:
    """
    Найти файлы по паттерну и переместить в backup/.
    
    Args:
        directory: Директория для поиска
        pattern: Glob паттерн
        backup_dir: Папка backup (по умолчанию: directory/backup)
        
    Returns:
        Количество перемещённых файлов/папок
    """
    if not directory.exists():
        return 0
    
    if backup_dir is None:
        backup_dir = directory / "backup"
    
    items = list(directory.glob(pattern))
    # Исключить саму папку backup
    items = [i for i in items if i.name != "backup" and "backup" not in str(i)]
    
    count = 0
    for item in items:
        if move_to_backup(item, backup_dir):
            count += 1
    
    return count


# ============================================================================
# Channel Profile
# ============================================================================

def find_channel_profile(project_root: Path) -> Optional[Path]:
    """
    Найти файл Channel Profile в проекте или родительской папке.
    
    Ищет: *_Channel_Profile.txt, Channel_Profile.txt
    """
    patterns = ["*_Channel_Profile.txt", "Channel_Profile.txt", "channel_profile.txt"]
    
    # Сначала в проекте
    for pattern in patterns:
        files = list(project_root.glob(pattern))
        if files:
            return files[0]
    
    # Потом в родительской папке
    parent = project_root.parent
    for pattern in patterns:
        files = list(parent.glob(pattern))
        if files:
            return files[0]
    
    return None


def load_channel_profile(project_root: Path) -> Optional[str]:
    """Загрузить содержимое Channel Profile."""
    profile_path = find_channel_profile(project_root)
    
    if profile_path and profile_path.exists():
        try:
            return profile_path.read_text(encoding="utf-8")
        except Exception:
            pass
    
    return None


# ============================================================================
# Извлечение имени гостя из названия проекта
# ============================================================================

def extract_guest_hint(project_name: str) -> Optional[str]:
    """
    Извлечь имя гостя из названия проекта.
    
    Примеры:
        "YTCG37_Hadi_Dawani" → "Hadi Dawani"
        "YTDemo_Ahmed_AlMutawa" → "Ahmed AlMutawa"
        "YT_Interview_John_Smith" → "John Smith"
        "YTPODCAST15_Maria_Garcia" → "Maria Garcia"
    """
    # Убрать префикс YT с любыми буквами/цифрами до первого _
    # YT, YTCG37, YTDemo, YTPODCAST15 и т.д.
    cleaned = re.sub(r'^YT[A-Za-z]*\d*_?', '', project_name)
    
    # Убрать даты в конце (YYYYMMDD или YYMMDD)
    cleaned = re.sub(r'_?\d{6,8}$', '', cleaned)
    
    # Заменить подчёркивания на пробелы
    cleaned = cleaned.replace('_', ' ').strip()
    
    # Проверить что похоже на имя (1-4 слова)
    words = cleaned.split()
    if 1 <= len(words) <= 4:
        skip_words = {'interview', 'project', 'video', 'raw', 'edit', 'final', 'draft'}
        name_words = [w for w in words if w.lower() not in skip_words]
        if name_words:
            return ' '.join(name_words)
    
    return None
