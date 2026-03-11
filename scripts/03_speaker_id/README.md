# 03_speaker_id — Идентификация спикеров ✓ ГОТОВО

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `00_process_all.py` | Мастер-скрипт (запускает всё) |
| `01_extract_speakers.py` | Группировка реплик по спикерам |
| `02_analyze_speakers.py` | LLM анализ → определение имён |
| `03_apply_names.py` | Замена SPEAKER_XX → реальные имена |
| `04_split_clips.py` | Разбивка по клипам → SRT + XLSX |

## Использование

```bash
export PROJECT="/Volumes/RYA Blue/YTCG37_Hadi_Dawani"

python 00_process_all.py --project "$PROJECT"
python 00_process_all.py --project "$PROJECT" --no-pause
```

## Вход → Выход

```
Вход:  01_Media/Source/Transcription/YTCG37_Hadi_Dawani_transcript_*.json

Выход: 01_Media/Source/Transcription/
       ├── YTCG37_Hadi_Dawani_extract_speakers_*/    (реплики по спикерам)
       ├── YTCG37_Hadi_Dawani_analyze_speakers_*.json (LLM анализ)
       ├── YTCG37_Hadi_Dawani_apply_names_*.json      (с именами)
       ├── YTCG37_Hadi_Dawani_apply_names_*.srt
       ├── YTCG37_Hadi_Dawani_split_clips_*.xlsx      (таблица по клипам)
       ├── RYA-FX3-0099.srt                           (SRT для клипа)
       └── ...

Лог:   01_Media/Source/Setup/logs/YTCG37_Hadi_Dawani_*.log
```
