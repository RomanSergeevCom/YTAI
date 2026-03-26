# Database Schema — SQLite + FTS5

## Расположение

```
~/.ytai/broll.db
```

На внутреннем диске Mac, не на внешних. Поиск работает когда диски отключены.

## Таблицы

### drives — внешние диски

```sql
CREATE TABLE drives (
    drive_id TEXT PRIMARY KEY,            -- "RYA T7 Black", "RYA Blue"
    volume_path TEXT NOT NULL,            -- "/Volumes/RYA T7 Black"
    last_seen TEXT,                       -- ISO timestamp последнего подключения
    is_connected INTEGER DEFAULT 0        -- 1/0, обновляется при сканировании
);
```

### projects — видеопроекты

```sql
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,          -- "YTCR01"
    project_name TEXT NOT NULL,           -- "YTCR01_Arty_Dzis"
    channel_code TEXT NOT NULL,           -- "YTCR"
    drive_id TEXT,                        -- FK → drives
    project_path TEXT NOT NULL,           -- полный путь
    language TEXT,                        -- "en", "ru"
    fps REAL,                            -- 29.97, 25.0
    resolution TEXT,                      -- "3840x2160"
    total_clips INTEGER DEFAULT 0,
    total_scenes INTEGER DEFAULT 0,
    total_duration_sec REAL DEFAULT 0,
    indexed_at TEXT,                      -- ISO timestamp
    analysis_version INTEGER DEFAULT 1,   -- для перезапуска при обновлении модулей
    FOREIGN KEY (drive_id) REFERENCES drives(drive_id)
);
```

### clips — видеоклипы

```sql
CREATE TABLE clips (
    clip_id TEXT NOT NULL,                -- "C5402"
    project_id TEXT NOT NULL,             -- FK → projects
    filename TEXT NOT NULL,               -- "C5402.MP4"
    file_path TEXT,                       -- полный путь к файлу
    scene_folder TEXT,                    -- "al_qudra_lake"
    duration_sec REAL,
    total_scenes INTEGER DEFAULT 0,
    PRIMARY KEY (clip_id, project_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);
```

### scenes — основная единица поиска

```sql
CREATE TABLE scenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    clip_id TEXT NOT NULL,
    scene_idx INTEGER NOT NULL,

    -- Temporal
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    duration_sec REAL NOT NULL,

    -- Keyframe
    keyframe_path TEXT,                   -- "Frames/C5402/scene_000.jpg"

    -- Module 02: Shot Classification (CLIP)
    shot_type TEXT,                       -- "driving_pov", "interview_closeup"
    shot_type_full TEXT,                  -- "B-roll driving POV from inside a car"
    shot_confidence REAL,
    shot_top3 TEXT,                       -- JSON array

    -- Module 03: Object Detection (YOLO)
    objects TEXT,                         -- JSON: ["person", "car", "building"]
    objects_unique TEXT,                  -- JSON: ["building", "car", "person"]
    person_count INTEGER DEFAULT 0,

    -- Module 04: Person Analysis
    face_count INTEGER DEFAULT 0,
    dominant_emotion TEXT,                -- "happy", "neutral", "surprise"
    body_pose TEXT,                       -- "sitting", "standing"

    -- Module 05: Scene Classification
    location TEXT,                        -- "office", "city_street", "desert"
    location_confidence REAL,
    mood TEXT,                            -- "formal", "casual", "luxury"
    time_of_day TEXT,                     -- "daylight", "golden_hour", "night"

    -- Module 06: Color Analysis
    color_palette TEXT,                   -- JSON: ["#E67E22", "#2C3E50", ...]
    brightness REAL,
    saturation REAL,
    color_temperature TEXT,               -- "warm", "cool", "neutral"

    -- Module 07: Camera Motion
    camera_motion TEXT,                   -- "static", "pan_right", "tracking"
    motion_magnitude REAL,
    motion_stability REAL,

    -- Module 08: OCR
    ocr_text TEXT,                        -- combined text found on screen
    has_text INTEGER DEFAULT 0,

    -- Module 09: Audio
    speech_ratio REAL,
    audio_type TEXT,                      -- "speech", "music", "silence"
    has_speech INTEGER DEFAULT 0,
    has_music INTEGER DEFAULT 0,

    -- Module 10: AV Sync (final classification)
    final_classification TEXT,            -- "interview", "broll", "voiceover_broll"
    final_confidence REAL,
    is_broll INTEGER DEFAULT 0,
    is_interview INTEGER DEFAULT 0,

    -- Module 11: Face Framing
    thirds_score REAL,
    looking_at TEXT,                      -- "camera", "left", "right"

    -- Module 12: Quality
    sharpness REAL,
    quality_score REAL,
    quality_label TEXT,                   -- "excellent", "good", "poor"

    -- Scene folder for grouping
    scene_folder TEXT,

    -- Timestamps
    analyzed_at TEXT,

    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);
```

### scenes_fts — полнотекстовый поиск

```sql
CREATE VIRTUAL TABLE scenes_fts USING fts5(
    shot_type,
    shot_type_full,
    objects,
    location,
    mood,
    color_temperature,
    camera_motion,
    ocr_text,
    scene_folder,
    final_classification,
    content='scenes',
    content_rowid='id',
    tokenize='unicode61'
);
```

### content_density — метрики на уровне клипа

```sql
CREATE TABLE content_density (
    clip_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    cuts_per_minute REAL,
    tempo_label TEXT,                     -- "slow", "normal", "fast"
    broll_ratio REAL,
    interview_ratio REAL,
    avg_scene_duration_sec REAL,
    energy_curve TEXT,                    -- JSON array
    peak_energy_sec REAL,
    PRIMARY KEY (clip_id, project_id)
);
```

## Индексы

```sql
CREATE INDEX idx_scenes_project ON scenes(project_id);
CREATE INDEX idx_scenes_clip ON scenes(clip_id, project_id);
CREATE INDEX idx_scenes_shot_type ON scenes(shot_type);
CREATE INDEX idx_scenes_is_broll ON scenes(is_broll);
CREATE INDEX idx_scenes_location ON scenes(location);
CREATE INDEX idx_scenes_final ON scenes(final_classification);
CREATE INDEX idx_scenes_channel ON scenes(project_id);  -- filter by channel via JOIN
CREATE INDEX idx_clips_scene_folder ON clips(scene_folder);
```

## Примеры запросов

### Поиск B-roll по типу
```sql
SELECT s.*, p.project_name, p.channel_code, d.volume_path, d.is_connected
FROM scenes s
JOIN projects p ON s.project_id = p.project_id
JOIN drives d ON p.drive_id = d.drive_id
WHERE s.is_broll = 1
  AND s.shot_type = 'driving_pov'
ORDER BY s.shot_confidence DESC;
```

### Полнотекстовый поиск
```sql
SELECT s.*, p.project_name
FROM scenes_fts fts
JOIN scenes s ON fts.rowid = s.id
JOIN projects p ON s.project_id = p.project_id
WHERE scenes_fts MATCH 'skyline OR aerial'
ORDER BY rank;
```

### B-roll по каналу + локации
```sql
SELECT s.*, p.project_name
FROM scenes s
JOIN projects p ON s.project_id = p.project_id
WHERE p.channel_code = 'YTCR'
  AND s.is_broll = 1
  AND s.location = 'city_street'
  AND s.quality_label != 'poor'
ORDER BY s.quality_score DESC;
```

### Статистика по проекту
```sql
SELECT
    p.project_name,
    COUNT(*) as total_scenes,
    SUM(CASE WHEN s.is_broll = 1 THEN 1 ELSE 0 END) as broll_scenes,
    SUM(CASE WHEN s.is_interview = 1 THEN 1 ELSE 0 END) as interview_scenes,
    ROUND(AVG(s.duration_sec), 1) as avg_scene_sec,
    GROUP_CONCAT(DISTINCT s.shot_type) as shot_types
FROM scenes s
JOIN projects p ON s.project_id = p.project_id
GROUP BY p.project_id;
```

### Найти похожий B-roll (по цветовой температуре + shot type)
```sql
-- "Найди warm driving footage как в YTCR01"
SELECT s.*, p.project_name
FROM scenes s
JOIN projects p ON s.project_id = p.project_id
WHERE s.shot_type = 'driving_pov'
  AND s.color_temperature = 'warm'
  AND s.project_id != 'YTCR01'  -- исключить источник
  AND s.quality_label IN ('good', 'excellent')
ORDER BY s.shot_confidence DESC
LIMIT 10;
```

## Миграции

При обновлении модулей (добавление новых полей):

```sql
-- Проверка существования колонки перед ALTER TABLE
-- SQLite не поддерживает IF NOT EXISTS для ALTER TABLE,
-- поэтому используем PRAGMA table_info()

-- Пример: добавление поля из нового модуля
ALTER TABLE scenes ADD COLUMN new_field TEXT;
```

Версионирование через `projects.analysis_version` — при запуске нового анализа с обновлёнными модулями, перезаписываем данные и инкрементируем версию.

## Размер базы (оценка)

| Компонент | Строк | Размер |
|-----------|-------|--------|
| projects | ~40 | <1 KB |
| clips | ~200 | <10 KB |
| scenes | ~8,000 | ~5 MB |
| scenes_fts | ~8,000 | ~2 MB |
| content_density | ~200 | <50 KB |
| **Итого** | | **~7-10 MB** |

Компактная база — легко бэкапить, переносить, синхронизировать.
