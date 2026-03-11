# 01_prepare — Подготовка сырья

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `01_concat_clips.py` | Склейка видеоклипов → MKV master |
| `02_extract_audio.py` | Извлечение WAV для транскрипции |
| `03_sync_dji_audio.py` | Синхронизация DJI WAV с видеоклипами камеры |

## Использование

```bash
export PROJECT="/Volumes/RYA Blue/YTCG37_Hadi_Dawani"

python 01_concat_clips.py --project "$PROJECT"
python 02_extract_audio.py --project "$PROJECT"
python 03_sync_dji_audio.py --project "$PROJECT" --tz-offset 4
```

## Вход → Выход

### 01_concat_clips.py
```
Вход:  01_Media/Source/Video/*.MP4
Выход: 01_Media/Source/Transcription/YTCG37_Hadi_Dawani.mkv
Лог:   01_Media/Source/Setup/logs/YTCG37_Hadi_Dawani_concat_*.log
```

### 02_extract_audio.py
```
Вход:  01_Media/Source/Video/*.MP4
Выход: 01_Media/Source/Transcription/
       ├── RYA-FX3-0099_AUDIO.wav              (аудио каждого клипа)
       ├── RYA-FX3-0100_AUDIO.wav
       └── YTCG37_Hadi_Dawani_FULL_AUDIO.wav   (склеенный для Whisper)
Лог:   01_Media/Source/Setup/logs/YTCG37_Hadi_Dawani_extract_audio_*.log
```

### 03_sync_dji_audio.py
```
Вход:  01_Media/Source/Video/*.MP4
     + 99_Pipeline/DJI_Audio/*.wav
Выход: 01_Media/Source/Audio/
       ├── RYA-FX3-0099_TX02.wav               (DJI синхр. под клип)
       ├── RYA-FX3-0100_TX02.wav
       └── ...
Лог:   01_Media/Source/Setup/logs/YTCG37_Hadi_Dawani_sync_dji_audio_*.log
```
