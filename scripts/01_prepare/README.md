# 01_prepare — Подготовка сырья

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `01_concat_clips.py` | Склейка видеоклипов → MKV master |
| `02_extract_audio.py` | Извлечение WAV для транскрипции |

## Использование

```bash
python 01_concat_clips.py --project "/Volumes/RYA Blue/YT_Project"
python 02_extract_audio.py --project "/Volumes/RYA Blue/YT_Project"
```

## Вход → Выход
- `01_Raw/01_01_Video/*.MP4` → `01_Raw/ProjectName.mkv`
- `01_Raw/01_01_Video/*.MP4` → `01_Raw/01_02_Audio/FULL_AUDIO.wav`
