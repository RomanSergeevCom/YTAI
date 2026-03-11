# Edit Brief Schema

Detailed specification for the `edit_brief.xlsx` file format.

## Sheet 1: `segments`

### Required Columns

#### `segment_id`
- **Type:** string
- **Auto-generated:** Yes
- **Format:** `seg_001`, `seg_002`, `seg_003`...
- **Description:** Unique identifier for each segment. If empty, script auto-generates based on row number.
- **Example:** `seg_014`

#### `source_file`
- **Type:** string
- **Required:** ✅ Yes
- **Description:** Filename of the source video. Must match actual file name.
- **Example:** `RYA-ZVE1-1358.MP4`
- **Note:** Extension is optional, script will try to match without extension if not found.

#### `tc_in`
- **Type:** string
- **Required:** ✅ Yes
- **Description:** Start timecode of the segment.
- **Accepted formats:**
  - `MM:SS` → `06:34`
  - `MM:SS.ms` → `06:34.500`
  - `HH:MM:SS` → `00:06:34`
  - `HH:MM:SS:FF` → `00:06:34:15` (frames at project fps)
  - `seconds` → `394.5`
- **Example:** `17:40.5`

#### `tc_out`
- **Type:** string
- **Required:** ✅ Yes
- **Description:** End timecode of the segment.
- **Format:** Same as `tc_in`
- **Example:** `17:52.0`
- **Validation:** Must be greater than `tc_in`

#### `block`
- **Type:** integer
- **Required:** ✅ Yes
- **Description:** Block/chapter number. Segments are grouped by block.
- **Range:** 1-99
- **Example:** `4`
- **Note:** Block 99 is conventionally used for "Extra/B-roll" material.

#### `block_name`
- **Type:** string
- **Required:** ✅ Yes
- **Description:** Human-readable name for the block. Used in bin names and markers.
- **Max length:** 50 characters
- **Example:** `What is GERD`
- **Note:** Keep concise for Premiere UI readability.

---

### Optional Columns

#### `segment_name`
- **Type:** string
- **Required:** No
- **Default:** Auto-generated from block_name + sequence
- **Description:** Specific name for this segment within the block.
- **Max length:** 100 characters
- **Example:** `Sphincter mechanism explanation`
- **Usage:** Appears as clip name in Premiere.

#### `speaker`
- **Type:** string
- **Required:** No
- **Description:** Who is speaking in this segment.
- **Example:** `Artem`, `Interviewer`, `Doctor`
- **Usage:** Can filter by speaker, helps editor identify content.

#### `transcript`
- **Type:** string
- **Required:** No
- **Max length:** 500 characters (truncated if longer)
- **Description:** Text content of the segment.
- **Example:** `The problem is that this valve doesn't close completely...`
- **Usage:** Appears in marker comments for quick reference.

#### `track`
- **Type:** string
- **Required:** No
- **Default:** `V1`
- **Options:** `V1`, `V2`, `V3`
- **Description:** Which video track to place the clip on.
- **Example:** `V2`
- **Usage:**
  - `V1` = Main speaker/interview
  - `V2` = B-roll, cutaways
  - `V3` = Graphics, titles, overlays

#### `color`
- **Type:** string
- **Required:** No
- **Default:** Inherited from block
- **Options:** `Cyan`, `Blue`, `Green`, `Yellow`, `Red`, `Magenta`, `Orange`, `Purple`
- **Description:** Clip label color in Premiere timeline.
- **Example:** `Blue`

#### `use`
- **Type:** boolean
- **Required:** No
- **Default:** `TRUE`
- **Options:** `TRUE`, `FALSE`, `1`, `0`, `YES`, `NO`
- **Description:** Whether to include this segment in the main sequence.
- **Example:** `FALSE`
- **Usage:** FALSE segments go to "Unused" bin but are still imported.

#### `priority`
- **Type:** integer
- **Required:** No
- **Default:** `1`
- **Range:** 1-9
- **Description:** Priority when multiple takes exist. 1 = best/primary take.
- **Example:** `2`
- **Usage:**
  - Priority 1 goes on main timeline
  - Priority 2+ goes to "Alternatives" bin
  - Useful for interview re-takes

#### `is_chapter`
- **Type:** boolean
- **Required:** No
- **Default:** `FALSE`
- **Description:** Mark this segment's start as a YouTube chapter point.
- **Example:** `TRUE`
- **Usage:** Creates special chapter marker at segment start. Only first segment of each block typically needs this.

#### `broll_note`
- **Type:** string
- **Required:** No
- **Max length:** 200 characters
- **Description:** Suggestion for B-roll to overlay on this segment.
- **Example:** `Add stomach anatomy animation`
- **Usage:**
  - Creates placeholder on V2 with this note as clip name
  - Helps editor know what visual to add

#### `notes`
- **Type:** string
- **Required:** No
- **Max length:** 500 characters
- **Description:** General notes for the editor.
- **Example:** `Best take - good energy. Watch for audio pop at 06:45`
- **Usage:** Appears in marker comment, not visible on timeline.

---

## Sheet 2: `project`

Key-value pairs for project settings. Column A = Key, Column B = Value.

### Required Settings

| Key | Type | Description | Example |
|-----|------|-------------|---------|
| `project_name` | string | Sequence name in Premiere | `YT RF - Artem GERD Story` |
| `fps` | float | Frame rate | `29.97` |

### Video Settings

| Key | Type | Default | Description | Example |
|-----|------|---------|-------------|---------|
| `width` | int | 3840 | Frame width | `3840` |
| `height` | int | 2160 | Frame height | `2160` |
| `pixel_aspect` | float | 1.0 | Pixel aspect ratio | `1.0` |
| `field_order` | string | progressive | `progressive`, `upper`, `lower` | `progressive` |

### Audio Settings

| Key | Type | Default | Description | Example |
|-----|------|---------|-------------|---------|
| `sample_rate` | int | 48000 | Audio sample rate | `48000` |
| `audio_channels` | int | 2 | Channels per track | `2` |

### Track Configuration

| Key | Type | Default | Description | Example |
|-----|------|---------|-------------|---------|
| `video_tracks` | int | 3 | Number of video tracks | `3` |
| `audio_tracks` | int | 4 | Number of audio tracks | `4` |

### File Paths

| Key | Type | Default | Description | Example |
|-----|------|---------|-------------|---------|
| `source_folder` | string | (current) | Path to source video files | `/Volumes/RYA/Footage` |
| `output_folder` | string | (current) | Path for output XML | `/Volumes/RYA/Project` |

### Generation Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `create_subclips` | bool | TRUE | Create subclips in bins |
| `create_bins` | bool | TRUE | Organize clips into block bins |
| `create_chapter_markers` | bool | TRUE | Generate YouTube chapter markers |
| `include_unused` | bool | TRUE | Include use=FALSE segments in Unused bin |
| `nested_sequences` | bool | FALSE | Create nested sequence per block |
| `link_audio` | bool | TRUE | Link audio to video clips |
| `add_handles` | bool | FALSE | Add frame handles to clips |
| `handle_frames` | int | 12 | Number of handle frames (if enabled) |

---

## Color Reference

| Color Name | Premiere Index | Suggested Usage |
|------------|----------------|-----------------|
| `Cyan` | 0 | Timeline events, current state |
| `Blue` | 1 | Explanations, educational content |
| `Green` | 2 | Introduction, solution, positive content |
| `Yellow` | 3 | Diagnosis, procedures, caution |
| `Red` | 4 | Danger, risks, critical warnings |
| `Magenta` | 5 | Surgery, medical procedures |
| `Orange` | 6 | Symptoms, personal examples |
| `Purple` | 7 | Treatment, medication |

---

## Validation Rules

The script validates the following:

### Errors (will not generate)
- Missing required columns
- Empty `source_file`, `tc_in`, `tc_out`, `block`, or `block_name`
- Invalid timecode format
- `tc_out` <= `tc_in`
- Invalid color name
- Invalid track name

### Warnings (will generate with warnings)
- Source file not found at specified path
- Overlapping segments on same track
- Non-sequential block numbers
- Duplicate segment_id values
- Very short segments (< 1 second)
- Very long transcript (> 500 chars, will truncate)

---

## Example Row

```
| segment_id | source_file       | tc_in   | tc_out  | block | block_name    | segment_name           | speaker | transcript                          | track | color | use  | priority | is_chapter | broll_note                    | notes                    |
|------------|-------------------|---------|---------|-------|---------------|------------------------|---------|-------------------------------------|-------|-------|------|----------|------------|-------------------------------|--------------------------|
| seg_010    | RYA-ZVE1-1358.MP4 | 06:06.0 | 06:34.0 | 4     | What is GERD  | Valve mechanism        | Artem   | Between esophagus and stomach...    | V1    | Blue  | TRUE | 1        | TRUE       | Add sphincter animation       | Good explanation, clear  |
```

This segment:
- Comes from file RYA-ZVE1-1358.MP4
- Starts at 6:06.0, ends at 6:34.0 (28 seconds)
- Is part of Block 4 "What is GERD"
- Will be placed on track V1 with Blue label
- Is marked as a YouTube chapter point
- Has a note suggesting B-roll animation
- Will appear on main timeline (use=TRUE, priority=1)
