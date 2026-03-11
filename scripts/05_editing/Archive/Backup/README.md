# 05_editing — Подготовка к монтажу

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `01_build_master_doc.py` | Полная транскрипция с именами → DOCX |
| `02_chapters.py` | Главы/маркеры для Premiere |
| `03_highlights.py` | Яркие моменты (из video_analysis + транскрипт) |
| `04_export_premiere_xml.py` | XML для импорта в Premiere |
| `05_export_markers.py` | CSV маркеры для timeline |
| `06_generate_edit_brief.py` | Итоговое ТЗ для монтажёра |

## Вход
- `03_speaker_id/` — транскрипт с именами
- `04_video_analysis/` — эмоции, B-roll, сцены

## Выход
- `04_Briefs/MasterTranscript.docx`
- `04_Briefs/04_01_Edit/EditBrief.docx`
- `06_Exports/premiere_markers.xml`
