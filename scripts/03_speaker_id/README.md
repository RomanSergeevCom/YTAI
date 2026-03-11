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
python 00_process_all.py --project "/Volumes/RYA Blue/YT_Project"
python 00_process_all.py --project "..." --no-pause
```

## Вход → Выход
- `02_Transcripts/02_01_Runs/*_transcript_*.json`
- ↓
- `02_Transcripts/02_02_Clean/speaker_analysis.json`
- `02_Transcripts/02_02_Clean/*_named.json`
- `02_Transcripts/02_02_Clean/*.srt` (по клипам)
- `02_Transcripts/02_02_Clean/*_by_clips.xlsx`
