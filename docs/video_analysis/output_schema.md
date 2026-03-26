# Output Schema — Полный JSON-формат результата анализа

## Файл на проект

```
{project}/01_Media/Source/Setup/visual_metadata.json
```

Создаётся рядом с `ingest.json` и `Claude4_assembly.json`.

## Полная структура

```json
{
  "version": "1.0",
  "project_id": "YTCR01",
  "project_name": "YTCR01_Arty_Dzis",
  "channel_code": "YTCR",
  "analyzed_at": "2026-03-26T14:30:00",
  "analysis_modules": ["shot_detection", "shot_classification", "object_detection",
                        "person_analysis", "scene_classification", "color_analysis",
                        "camera_motion", "audio_analysis", "av_sync"],
  "stats": {
    "total_clips": 5,
    "total_scenes": 235,
    "total_broll_scenes": 82,
    "total_interview_scenes": 140,
    "total_duration_sec": 2715.4,
    "unique_locations": 8,
    "unique_shot_types": 11
  },
  "clips": [
    {
      "clip_id": "C5402",
      "filename": "C5402.MP4",
      "scene_folder": "al_qudra_lake",
      "duration_sec": 905.2,
      "fps": 29.97,
      "resolution": "3840x2160",

      "density": {
        "total_scenes": 47,
        "cuts_per_minute": 3.1,
        "tempo_label": "normal",
        "broll_ratio": 0.35,
        "interview_ratio": 0.60,
        "avg_scene_duration_sec": 19.3,
        "energy_curve": [
          {"time_sec": 0, "energy": 0.80},
          {"time_sec": 30, "energy": 0.20}
        ]
      },

      "scenes": [
        {
          "scene_idx": 0,
          "start_sec": 0.0,
          "end_sec": 12.5,
          "duration_sec": 12.5,
          "keyframe_path": "Frames/C5402/scene_000.jpg",

          "shot_type": "nature_landscape",
          "shot_type_full": "B-roll nature landscape desert or lake",
          "shot_confidence": 0.85,
          "shot_top3": [
            ["nature_landscape", 0.85],
            ["city_skyline", 0.07],
            ["aerial_drone", 0.04]
          ],

          "objects": ["tree", "boat"],
          "objects_unique": ["boat", "tree"],
          "person_count": 0,

          "face_count": 0,
          "dominant_emotion": null,
          "body_pose": null,

          "location": "lake_waterfront",
          "location_confidence": 0.82,
          "mood": "calm_peaceful",
          "mood_confidence": 0.77,
          "time_of_day": "daylight",

          "color_palette": ["#E67E22", "#2C3E50", "#ECF0F1", "#8E6B3D", "#1A5276"],
          "brightness": 0.58,
          "saturation": 0.45,
          "color_temperature": "warm",

          "camera_motion": "static",
          "motion_magnitude": 0.02,
          "motion_stability": 0.95,

          "ocr_text": "",
          "has_text": false,

          "speech_ratio": 0.0,
          "audio_type": "music",
          "has_speech": false,
          "has_music": true,

          "final_classification": "broll",
          "final_confidence": 0.95,
          "is_broll": true,
          "is_interview": false,

          "face_framing": null,
          "quality": {
            "sharpness": 178.5,
            "quality_score": 0.85,
            "quality_label": "good"
          }
        },

        {
          "scene_idx": 1,
          "start_sec": 12.5,
          "end_sec": 165.0,
          "duration_sec": 152.5,
          "keyframe_path": "Frames/C5402/scene_001.jpg",

          "shot_type": "interview_closeup",
          "shot_type_full": "interview talking head close-up of one person speaking",
          "shot_confidence": 0.92,
          "shot_top3": [
            ["interview_closeup", 0.92],
            ["interview_two_people", 0.04],
            ["interior_tour", 0.02]
          ],

          "objects": ["person", "chair"],
          "objects_unique": ["chair", "person"],
          "person_count": 1,

          "face_count": 1,
          "dominant_emotion": "neutral",
          "body_pose": "sitting",

          "location": "office",
          "location_confidence": 0.85,
          "mood": "formal",
          "mood_confidence": 0.80,
          "time_of_day": "indoor",

          "color_palette": ["#D5D5D5", "#4A4A4A", "#8B7355", "#FFFFFF", "#2C2C2C"],
          "brightness": 0.65,
          "saturation": 0.15,
          "color_temperature": "neutral",

          "camera_motion": "static",
          "motion_magnitude": 0.01,
          "motion_stability": 0.98,

          "ocr_text": "",
          "has_text": false,

          "speech_ratio": 0.85,
          "audio_type": "speech",
          "has_speech": true,
          "has_music": false,

          "final_classification": "interview",
          "final_confidence": 0.95,
          "is_broll": false,
          "is_interview": true,

          "face_framing": {
            "eye_y_ratio": 0.31,
            "looking_at": "camera",
            "thirds_score": 0.92
          },
          "quality": {
            "sharpness": 210.3,
            "quality_score": 0.90,
            "quality_label": "excellent"
          }
        }
      ]
    }
  ]
}
```

## Минимальная версия (только Core модули)

Если запущены только модули 1-5:

```json
{
  "version": "1.0",
  "project_id": "YTCR01",
  "analyzed_at": "2026-03-26T14:30:00",
  "analysis_modules": ["shot_detection", "shot_classification", "object_detection",
                        "person_analysis", "scene_classification"],
  "clips": [
    {
      "clip_id": "C5402",
      "scenes": [
        {
          "scene_idx": 0,
          "start_sec": 0.0,
          "end_sec": 12.5,
          "duration_sec": 12.5,
          "keyframe_path": "Frames/C5402/scene_000.jpg",

          "shot_type": "nature_landscape",
          "shot_confidence": 0.85,
          "objects": ["tree", "boat"],
          "person_count": 0,
          "face_count": 0,
          "location": "lake_waterfront",
          "mood": "calm_peaceful",
          "is_broll": true
        }
      ]
    }
  ]
}
```

## Связь с существующими JSON

### ingest.json → visual_metadata.json

Поля `clip_id`, `filename`, `scene_folder`, `duration_sec`, `fps` берутся из `ingest.json`. Visual_metadata дополняет ingest визуальным анализом.

### Claude4_assembly.json → visual_metadata.json

Транскрипт содержит таймкоды речи. Visual_metadata содержит визуальные таймкоды сцен. Вместе они покрывают полную картину: **что сказано** + **что показано**.

### Assembly brief → visual_metadata.json

Brief `broll_note` (ручные рекомендации) может быть автоматически обогащён из visual_metadata: "для этого сегмента есть B-roll в YTCR01/al_qudra_lake: driving_pov + city_skyline".
