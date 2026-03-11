#!/usr/bin/env python3
"""
YTAI Utils: Video
FFprobe, работа с видео клипами.
"""

import re
import subprocess
import logging
from pathlib import Path
from typing import List, Tuple, Optional

from .paths import VIDEO_EXTS
from .formatting import format_timestamp


# ============================================================================
# Natural Sort
# ============================================================================

def natural_sort_key(s: str):
    """
    Ключ для естественной сортировки строк с числами.
    
    Пример: clip1, clip2, clip10 (а не clip1, clip10, clip2)
    """
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


# ============================================================================
# FFprobe
# ============================================================================

def get_video_duration(video_path: Path) -> float:
    """
    Получить длительность видео через ffprobe.
    
    Args:
        video_path: Путь к видео файлу
        
    Returns:
        Длительность в секундах или 0.0 при ошибке
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    
    return 0.0


# ============================================================================
# Работа с клипами
# ============================================================================

def get_video_clips(
    video_dir: Path, 
    logger: Optional[logging.Logger] = None
) -> List[dict]:
    """
    Получить список видео клипов с длительностями и offset'ами.
    
    Args:
        video_dir: Папка с видео файлами
        logger: Опциональный логгер
        
    Returns:
        Список словарей:
        [
            {
                "file": "RYA-ZVE1-1146.MP4",
                "path": Path(...),
                "duration": 150.5,
                "start": 0.0,
                "end": 150.5
            },
            ...
        ]
    """
    def log(msg):
        if logger:
            logger.info(msg)
    
    def log_debug(msg):
        if logger:
            logger.debug(msg)
    
    if not video_dir.exists():
        log(f"Папка с видео не найдена: {video_dir}")
        return []
    
    # Найти все видео файлы (исключая Archive)
    clips = []
    for f in video_dir.iterdir():
        if (f.is_file() and 
            f.suffix in VIDEO_EXTS and 
            not f.name.startswith(".") and
            "Archive" not in str(f)):
            clips.append(f)
    
    # Естественная сортировка
    clips.sort(key=lambda p: natural_sort_key(p.name))
    
    if not clips:
        log(f"Видео клипы не найдены в {video_dir}")
        return []
    
    log(f"Найдено {len(clips)} видео клипов")
    
    # Получить длительности и вычислить offset'ы
    result = []
    current_offset = 0.0
    
    for clip_path in clips:
        duration = get_video_duration(clip_path)
        
        if duration <= 0:
            log(f"  ⚠ Не удалось получить длительность: {clip_path.name}")
            continue
        
        result.append({
            "file": clip_path.name,
            "path": clip_path,
            "duration": duration,
            "start": current_offset,
            "end": current_offset + duration
        })
        
        log_debug(f"  {clip_path.name}: {format_timestamp(duration)} "
                  f"({current_offset:.1f}s - {current_offset + duration:.1f}s)")
        
        current_offset += duration
    
    log(f"Общая длительность: {format_timestamp(current_offset)}")
    
    return result


def find_clip_for_timestamp(
    clips: List[dict], 
    timestamp: float
) -> Tuple[Optional[dict], float]:
    """
    Найти клип для заданного глобального timestamp.
    
    Args:
        clips: Список клипов из get_video_clips()
        timestamp: Глобальный timestamp в секундах
        
    Returns:
        Кортеж (clip_dict, local_timestamp) или (None, 0.0)
    """
    if not clips:
        return None, 0.0
    
    for clip in clips:
        if clip["start"] <= timestamp < clip["end"]:
            local_ts = timestamp - clip["start"]
            return clip, local_ts
    
    # Edge case: timestamp в самом конце последнего клипа (в пределах 0.5 сек)
    last_clip = clips[-1]
    if last_clip["end"] - 0.5 <= timestamp <= last_clip["end"] + 0.5:
        local_ts = min(timestamp - last_clip["start"], last_clip["duration"])
        return last_clip, local_ts
    
    return None, 0.0


def get_total_duration(clips: List[dict]) -> float:
    """Получить общую длительность всех клипов."""
    if not clips:
        return 0.0
    return clips[-1]["end"]
