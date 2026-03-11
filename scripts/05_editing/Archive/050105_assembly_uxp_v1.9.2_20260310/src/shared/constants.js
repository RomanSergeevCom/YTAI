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
  Orange: 3,    // Confirmed: ppro ORANGE=3
  Yellow: 4,    // Confirmed: ppro YELLOW=4
  Blue: 6,      // Confirmed: ppro BLUE=6
  Cyan: 7       // Confirmed: ppro CYAN=7
};

const VALID_COLORS = Object.keys(LABEL_COLOR_INDEX);

// Adobe marker type URIs — used for CREATING markers via seq.getMarkers() + createMarker()
// NOTE: ppro.Marker.MARKER_TYPE_CHAPTER = "Chapter" is a DISPLAY name, NOT for creation!
const MARKER_TYPE_CHAPTER = 'com.adobe.premiereMarkers.chapter';
const MARKER_TYPE_COMMENT = 'com.adobe.premiereMarkers.comment';

// Review sequence color scheme — by exclusion category
// Used by reviewBuilder.js for _3_Review sequence
const REVIEW_COLOR_MAP = {
  cut:  { label: 'Red',    labelIdx: 6,  markerIdx: 1 },  // block=99, explicitly cut
  alt:  { label: 'Yellow', labelIdx: 15, markerIdx: 4 },  // priority=2, alternative take
  skip: { label: 'Purple', labelIdx: 8,  markerIdx: 2 }   // use=FALSE, review candidate
};

// Screen Cues color scheme — V2 track + Comment markers
// Used by screenBuilder.js for Production Cues on Assembly sequence
const SCREEN_CUE_COLOR = {
  label: 'Orange', labelIdx: 7, markerIdx: 3   // Orange = MANGO=7 (label), ORANGE=3 (marker)
};

// Screen types — valid screen_type values for screens[] in edit_brief.json
const SCREEN_TYPES = [
  'chapter_title',        // Full-screen title card (centered text on black)
  'half_overlay',         // 2/5 gradient left, speaker right
  'three_fifths_overlay', // 3/5 gradient left, speaker smaller right
  'lower_third',          // Lower third bar (name + title)
  'product_shot',         // Product card
  'list',                 // Bulleted list
  'info_graphic'          // Data visualization / infographic
];

// Required fields per screen type (title is always required)
const SCREEN_REQUIRED_FIELDS = {
  chapter_title:        ['title'],
  half_overlay:         ['title'],
  three_fifths_overlay: ['title'],
  lower_third:          ['title'],
  product_shot:         ['title'],
  list:                 ['title', 'body'],
  info_graphic:         ['title', 'body']
};

// Tick conversion
const TICKS_PER_SECOND = 254016000000;

module.exports = {
  LABEL_COLOR_INDEX,
  MARKER_COLOR_INDEX,
  VALID_COLORS,
  MARKER_TYPE_CHAPTER,
  MARKER_TYPE_COMMENT,
  TICKS_PER_SECOND,
  REVIEW_COLOR_MAP,
  SCREEN_CUE_COLOR,
  SCREEN_TYPES,
  SCREEN_REQUIRED_FIELDS
};
