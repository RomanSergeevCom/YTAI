/**
 * Shared constants for YTAI Assembly UXP plugin.
 * Used by both INGEST and ASSEMBLY modules.
 *
 * Color indices from REAL Premiere Pro API (confirmed via debug log 15-27-04):
 *   ppro.Constants.ProjectItemColorLabel: clip label colors in bin/timeline (0-15)
 *   ppro.Constants.MarkerColor: marker-specific colors (0-7, no WHITE=5)
 *
 * IMPORTANT: Marker type URIs are Adobe internal identifiers for CREATING markers.
 * ppro.Marker.MARKER_TYPE_CHAPTER = "Chapter" is a DISPLAY name, NOT for creation!
 */

// Premiere Pro clip label color indices (ppro.Constants.ProjectItemColorLabel)
// Real API dump: VIOLET=0, IRIS=1, LAVENDER=3, CERULEAN=4, FOREST=5,
//                ROSE=6, MANGO=7, PURPLE=8, BLUE=9, TEAL=10,
//                MAGENTA=11, TAN=12, GREEN=13, BROWN=14, YELLOW=15
// Note: index 2 is missing in real API!
const LABEL_COLOR_INDEX = {
  Green: 13,    // Confirmed: ppro GREEN=13
  Blue: 9,      // Confirmed: ppro BLUE=9
  Orange: 7,    // Confirmed: ppro MANGO=7
  Cyan: 10,     // Confirmed: ppro TEAL=10
  Yellow: 15,   // Confirmed: ppro YELLOW=15
  Red: 6,       // Confirmed: ppro ROSE=6 (closest to red)
  Magenta: 11,  // Confirmed: ppro MAGENTA=11
  Purple: 8     // Confirmed: ppro PURPLE=8
};

// Premiere Pro marker color indices (ppro.Constants.MarkerColor)
// Real API dump: GREEN=0, RED=1, MAGNETA=2, ORANGE=3, YELLOW=4, BLUE=6, CYAN=7
// Note: no WHITE (index 5 missing), and typo "MAGNETA" in Premiere API
const MARKER_COLOR_INDEX = {
  Green: 0,     // Confirmed: ppro GREEN=0
  Red: 1,       // Confirmed: ppro RED=1
  Magenta: 2,   // Confirmed: ppro MAGNETA=2 (Premiere typo)
  Purple: 2,    // Same as Magenta — Premiere has no separate Purple marker color
  Orange: 3,    // Confirmed: ppro ORANGE=3
  Yellow: 4,    // Confirmed: ppro YELLOW=4
  Blue: 6,      // Confirmed: ppro BLUE=6
  Cyan: 7       // Confirmed: ppro CYAN=7
};

const VALID_COLORS = Object.keys(LABEL_COLOR_INDEX);

// Block-assignable colors (all except Orange, which is reserved for Screen Cues)
const BLOCK_VALID_COLORS = ['Green', 'Blue', 'Cyan', 'Yellow', 'Red', 'Magenta', 'Purple'];

// Adobe marker type URIs — used for CREATING markers via seq.getMarkers() + createMarker()
// NOTE: ppro.Marker.MARKER_TYPE_CHAPTER = "Chapter" is a DISPLAY name, NOT for creation!
const MARKER_TYPE_CHAPTER = 'com.adobe.premiereMarkers.chapter';
const MARKER_TYPE_COMMENT = 'com.adobe.premiereMarkers.comment';
const MARKER_TYPE_SEGMENTATION = 'com.adobe.premiereMarkers.segmentation';

// Review sequence color scheme — by exclusion category
// Used by reviewBuilder.js for _3_Review sequence
const REVIEW_COLOR_MAP = {
  cut:  { label: 'Red',    labelIdx: 6,  markerIdx: 1 },  // block=99, explicitly cut
  alt:  { label: 'Yellow', labelIdx: 15, markerIdx: 4 },  // priority=2, alternative take
  skip: { label: 'Purple', labelIdx: 8,  markerIdx: 2 }   // use=FALSE, review candidate
};

// Review producer color — segments where producer/interviewer speaks (context only)
// Lavender (label index 3) — visually distinct, not used by any block color
const REVIEW_PRODUCER_COLOR = { label: 'Lavender', labelIdx: 3 };

// Review expert color — segments where expert/talent on camera speaks
// Teal (label index 10) — vivid, easy to find on timeline
const REVIEW_EXPERT_COLOR = { label: 'Teal', labelIdx: 10 };

// Screen Cues color scheme — V2 track + Comment markers
// Used by screenBuilder.js for Production Cues on Assembly sequence
const SCREEN_CUE_COLOR = {
  label: 'Orange', labelIdx: 7, markerIdx: 3   // Orange = MANGO=7 (label), ORANGE=3 (marker)
};

// Screen types — valid screen_type values for screens[] in pre_edit_brief.json
const SCREEN_TYPES = [
  'full_overlay',           // Full-screen gradient overlay — text centered
  'half_overlay',           // 1/2 screen gradient left — text on left
  'three_fifths_overlay',   // 3/5 screen gradient left — text on left
  'chapter_bar',            // Bottom center bar for chapter names
  'lower_third'             // Centered rounded bar — speaker name
];

// Required fields per screen type (title is always required)
const SCREEN_REQUIRED_FIELDS = {
  full_overlay:          ['title'],
  half_overlay:          ['title'],
  three_fifths_overlay:  ['title'],
  chapter_bar:           ['title'],
  lower_third:           ['title']
};

// Tick conversion
const TICKS_PER_SECOND = 254016000000;

module.exports = {
  LABEL_COLOR_INDEX,
  MARKER_COLOR_INDEX,
  VALID_COLORS,
  BLOCK_VALID_COLORS,
  MARKER_TYPE_CHAPTER,
  MARKER_TYPE_COMMENT,
  MARKER_TYPE_SEGMENTATION,
  TICKS_PER_SECOND,
  REVIEW_COLOR_MAP,
  REVIEW_PRODUCER_COLOR,
  REVIEW_EXPERT_COLOR,
  SCREEN_CUE_COLOR,
  SCREEN_TYPES,
  SCREEN_REQUIRED_FIELDS
};
