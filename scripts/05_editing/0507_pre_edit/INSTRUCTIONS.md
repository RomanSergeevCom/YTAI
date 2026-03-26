# 0507 Pre-Edit — Visual Brief for Editor

## What is Pre-Edit?

Pre-Edit is the stage between finalized Assembly brief and Premiere montage.
It produces a visual ТЗ (technical specification) that tells the editor exactly what should appear on screen for each segment — overlays, schemas, B-roll, images.

## Pipeline Position

```
Assembly brief → Review cycles → ★ PRE-EDIT → Premiere montage → Screen Cues
```

## Workflow

### 1. Export from Premiere (UXP)

In Premiere UXP panel → PRE-EDIT section → click **"Export Doc"**.

This reads the active sequence (V1 clips, markers, transcript) and writes:
```
Setup/Pre-Edit/{SEQUENCE}_pre_edit_export.json
```

### 2. Convert to Google Doc

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate
python ~/YTAI/scripts/05_editing/0507_pre_edit/export_to_gdoc.py \
  --input "{project}/01_Media/Source/Setup/Pre-Edit/{CODE}_pre_edit_export.json"
```

Output: `Setup/Pre-Edit/{CODE}_pre_edit_template.docx`

Open this `.docx` in Google Docs.

### 3. Fill "визуализация" column

The document has one continuous table with colored chapter separators.
- **транскрипт** — clean text only (no B-roll notes)
- **визуализация** — all visual ideas, B-roll, prompts

For each segment, fill the "визуализация" area with one or more of:

| Annotation | What Claude does |
|-----------|-----------------|
| `/схема: ROI calculation 12%→60%` | Generate PNG diagram/schema |
| `/оверлей: Table of Contents` | Generate screen overlay PNG (full/half/lower_third) |
| `/найди кадр Dubai skyline morning` | Find matching frame in source footage, write timecode |
| `/структурируй: 5 шагов покупки` | Structure info into visual format |
| `B-roll: город vs пустыня, контраст` | Text ТЗ for editor + schematic placeholder |
| `[вставленная картинка]` | Image goes directly into frame |
| `ссылка на видео` | Mark: "show this video here" |
| `Gemini: промпт для генерации` | Prompt for Gemini image/diagram generation |
| `Claude анимация: ...` | Claude HTML/SVG animation (interactive visualization) |
| _(пусто)_ | Talking head, no visual treatment |

### 4. Send to Claude

In a new Claude Code chat:

```
Pre-Edit обработка:
- Channel: YTCR
- Project: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis
- Doc: {path to filled .docx}
- Style: ~/YTAI/scripts/05_editing/0507_pre_edit/style_config.json
- Rules: ~/YTAI/scripts/05_editing/0501_brief/project_knowledge/editing_rules.md
```

Claude will:
1. Parse the filled `.docx` (via `parse_gdoc.py`)
2. Classify each annotation
3. Generate visuals (via `generate_visuals.py` + existing `0504_screen_cues`)
4. Write everything to `Setup/Pre-Edit/v{N}/`

### 5. Output

```
Setup/Pre-Edit/
├── v1/
│   ├── {CODE}_pre_edit_v1.json      # structured visual specs per segment
│   ├── {CODE}_pre_edit_v1.html      # visual review (open in browser)
│   └── visuals/
│       ├── seg_007_overlay_roi.png   # generated overlay
│       ├── seg_012_schema_career.png # generated diagram
│       ├── seg_029_broll_ref.png     # B-roll placeholder
│       └── seg_041_user_image.png    # extracted from Doc
├── v2/
│   └── ...  (next iteration)
```

## For Claude: Processing Rules

When processing a filled Pre-Edit document:

1. **Read the .docx** — parse each segment's "Визуализация" section
2. **Classify annotations** by prefix:
   - `/схема:` → type: `schema`
   - `/оверлей:` → type: `overlay` (determine subtype: full_overlay, half_overlay, etc.)
   - `/найди кадр` → type: `find_frame`
   - `/структурируй:` → type: `structure`
   - `B-roll:` → type: `broll`
   - Contains image → type: `image`
   - URL/link → type: `video_ref`
   - Empty → type: `talking_head`

3. **Generate visuals**:
   - `schema` → Pillow PNG using brand fonts (Orbitron Bold titles, Montserrat Light body), navy/lime colors
   - `overlay` → reuse `0504_screen_cues/generate_screen_cues_png.py` renderer
   - `broll` → placeholder PNG with text description in frame
   - `image` → extract from .docx, save as PNG
   - `find_frame` → search transcript for matching content, return clip + timecode
   - `structure` → generate structured info PNG

4. **Resolution**: 3840×2160 (4K UHD) — match project settings

5. **Brand colors** (from `style_config.json`):
   - Navy background: `#0A1628`
   - Lime accent: `#C8E64A`
   - Blue panel: `#375E9D`
   - White text: `#FFFFFF`

6. **Fonts** (from `0504_screen_cues/fonts/`):
   - Titles: `Orbitron-Bold.ttf`
   - Body: `Montserrat-Light.ttf`
