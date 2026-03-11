#!/usr/bin/env python3
"""
YTAI Utils
Общие утилиты для скриптов обработки транскриптов.
"""

# Paths
from .paths import (
    # Константы
    VIDEO_DIR,
    AUDIO_DIR,
    TRANSCRIPTION_DIR,
    SETUP_DIR,
    DJI_PIPELINE_DIR,
    LOGS_DIR,
    VIDEO_EXTS,
    # Функции
    get_project_paths,
    ensure_dirs,
    find_latest_file,
    find_latest_dir,
    move_to_backup,
    cleanup_old_files,
    find_channel_profile,
    load_channel_profile,
    extract_guest_hint,
)

# Formatting
from .formatting import (
    generate_timestamp,
    format_timestamp,
    format_srt_timestamp,
    format_duration,
    setup_logging,
    print_header,
    print_section,
)

# Video
from .video import (
    natural_sort_key,
    get_video_duration,
    get_video_clips,
    find_clip_for_timestamp,
    get_total_duration,
)

# LLM
from .llm import (
    OLLAMA_API_URL,
    DEFAULT_LLM_MODEL,
    OLLAMA_TIMEOUT,
    check_ollama_server,
    get_available_models,
    call_ollama,
    parse_json_response,
    build_speaker_analysis_prompt,
)


__version__ = "2.0.0"
__all__ = [
    # Paths
    "VIDEO_DIR",
    "AUDIO_DIR",
    "TRANSCRIPTION_DIR",
    "SETUP_DIR",
    "DJI_PIPELINE_DIR",
    "LOGS_DIR",
    "VIDEO_EXTS",
    "get_project_paths",
    "ensure_dirs",
    "find_latest_file",
    "find_latest_dir",
    "move_to_backup",
    "cleanup_old_files",
    "find_channel_profile",
    "load_channel_profile",
    "extract_guest_hint",
    # Formatting
    "generate_timestamp",
    "format_timestamp",
    "format_srt_timestamp",
    "format_duration",
    "setup_logging",
    "print_header",
    "print_section",
    # Video
    "natural_sort_key",
    "get_video_duration",
    "get_video_clips",
    "find_clip_for_timestamp",
    "get_total_duration",
    # LLM
    "OLLAMA_API_URL",
    "DEFAULT_LLM_MODEL",
    "OLLAMA_TIMEOUT",
    "check_ollama_server",
    "get_available_models",
    "call_ollama",
    "parse_json_response",
    "build_speaker_analysis_prompt",
]
