# Export Audio Map — формат 1.3

Кнопка **Export Audio Map** (вкладка Ingest) пишет снимок **активной секвенции
как она есть**. Карта нужна, чтобы показать расхождение, поэтому в ней весь
таймлайн: каждый айтем каждой дорожки, ничего не отброшено, особые помечены.
Позиции перечитываются из Premiere при каждом нажатии — ручные сдвиги после
Build в карте видны.

Код: `src/ingest/audioMap.js` · тесты: `tests/ingest/audioMap.test.js`.

## Файл

```
{project}/00_Setup/01_Ingest/{CODE}_audio_map.json
```

`{CODE}` — из имени папки проекта (`YTCR02_Kamran_Sharaf` → `YTCR02`).
Один файл на проект, внутри — карта **каждой** выгруженной секвенции.
Повторная выгрузка секвенции заменяет только её запись. Файл старого
формата (1.0–1.2, одна секвенция наверху) при первой выгрузке переносится
внутрь `sequences` под своим именем с пометкой `format`. Файл, который не
читается как JSON, откладывается в `{CODE}_audio_map.unreadable.json`.

```json
{
  "version": "1.3",
  "type": "audio_map",
  "project_code": "YTUVIE01",
  "project_folder": "/Volumes/…/YTUVIE01_Kickoff_Setup",
  "updated_at": "2026-09-25T18:40:00.000Z",
  "last_sequence": "YTUVIE01_01_zachem_nuzhen",
  "sequences": {
    "YTUVIE01_01_zachem_nuzhen": { "…карта секвенции…" }
  }
}
```

## Карта секвенции

| поле | что |
|---|---|
| `fps` | из таймбейза секвенции (`254016000000 / ticks_per_frame`) |
| `video_tracks`, `audio_tracks` | число дорожек |
| `track_state` | `{V1: {muted}, …}` — `null`, если сборка Premiere не отдаёт |
| `tracks` | **весь таймлайн**: `{V1: [айтем…], A1: [айтем…]}` |
| `scenes` | сопоставление видео → звук по середине клипа (формула ниже) |
| `summary` | счётчики: всего, по дорожкам, disabled, strays, nested, audio_without_video, unreadable |

### Айтем в `tracks`

| поле | что |
|---|---|
| `filename`, `media_path` | имя и путь исходника (`getMediaFilePath`) |
| `timeline_start_sec`, `timeline_end_sec`, `duration_sec` | позиция на таймлайне, 6 знаков |
| `source_in_sec`, `source_out_sec` | с какого места исходника играет кусок |
| `*_ticks` | те же точки в тиках Premiere — точная правда |
| `disabled` | Clip → Enable снят (`null` — сборка не отдаёт) |
| `stray` | короче 0,2 с — однокадровый мусор преднагрева |
| `nested` | айтем — вложенная секвенция |
| `kind` (только звук) | `dji` (+`tx`, `mic`) · `camera_embed` (+`of_track`) · `external` |
| `error` | айтем не прочитался — карта неполная, статус красный |

### `scenes` и формула 0103

Для каждого видеоклипа (кроме `stray`) — звук каждой A-дорожки под его
серединой: `camera_embed` · `other_camera_embed` (+`of_track`) · `dji` · `external`.
У клипа есть `source_in_sec` / `source_out_sec` и пометка `disabled`.

```
position_in_wav = audio_source_in + (video_timeline_start - audio_timeline_start)
```

Звук, над которым нет видео, в `scenes` не попадает — он есть в `tracks` и
посчитан в `summary.audio_without_video`.

## Строка статуса

```
YTUVIE01_01_zachem_nuzhen: V3/A6 · 31 items · 2 disabled · 1 one-frame strays → YTUVIE01_audio_map.json (path copied)
```

Если хоть один айтем не прочитался — статус красный («Audio Map INCOMPLETE»)
и попадает в «Err».
