#!/usr/bin/env python3
"""
YTAI Utils: Formatting
Форматирование timestamps, логирование.
"""

import logging
from pathlib import Path
from datetime import datetime


# ============================================================================
# Timestamps
# ============================================================================

def generate_timestamp() -> str:
    """
    Сгенерировать timestamp для имён файлов.
    
    Returns:
        Строка вида "20260112_171500"
    """
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_timestamp(seconds: float) -> str:
    """
    Форматировать секунды как HH:MM:SS.
    
    Args:
        seconds: Время в секундах
        
    Returns:
        Строка "01:23:45"
    """
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_srt_timestamp(seconds: float) -> str:
    """
    Форматировать секунды для SRT (HH:MM:SS,mmm).
    
    Args:
        seconds: Время в секундах
        
    Returns:
        Строка "01:23:45,678"
    """
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_secs = total_ms // 1000
    h, r = divmod(total_secs, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_duration(seconds: float) -> str:
    """
    Форматировать длительность человекочитаемо.
    
    Args:
        seconds: Время в секундах
        
    Returns:
        Строка "1h 23m 45s" или "23m 45s" или "45s"
    """
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


# ============================================================================
# Логирование
# ============================================================================

def setup_logging(
    logs_dir: Path, 
    project_name: str, 
    script_name: str
) -> logging.Logger:
    """
    Настроить логгер с выводом в файл и консоль.
    
    Args:
        logs_dir: Папка для логов
        project_name: Название проекта
        script_name: Название скрипта (без .py)
        
    Returns:
        Настроенный logger
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = generate_timestamp()
    log_file = logs_dir / f"{project_name}_{script_name}_{timestamp}.log"
    
    # Создать новый logger с уникальным именем
    logger_name = f"{project_name}_{script_name}_{timestamp}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    
    # Очистить handlers если есть
    logger.handlers.clear()
    
    # File handler - всё
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    
    # Console handler - INFO и выше
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    logger.info(f"Log: {log_file}")
    
    return logger


# ============================================================================
# Вспомогательные функции вывода
# ============================================================================

def print_header(title: str, char: str = "=", width: int = 70) -> None:
    """Напечатать заголовок."""
    print(char * width)
    print(title)
    print(char * width)


def print_section(title: str, char: str = "-", width: int = 70) -> None:
    """Напечатать заголовок секции."""
    print()
    print(title)
    print(char * width)
