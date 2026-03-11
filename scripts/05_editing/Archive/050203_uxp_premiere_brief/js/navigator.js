/* navigator.js — Premiere Pro timeline navigation
   UXP: uses globals APP, BUS, appLog from state.js

   PREMIERE PRO UXP API (correct):
   ─────────────────────────────────
   seq.getVideoTrackCount() → number
   seq.getVideoTrack(index) → Track
   track.getTrackItems(mediaType, includeEmpty) → TrackItem[]
   trackItem.name, .start, .end, .inPoint, .outPoint, .projectItem
   seq.setPlayerPosition(tickTime) — set CTI
   TickTime: createWithSeconds, .seconds, .add, .subtract
*/

console.log('[YTAI] navigator.js loading...');

var ppro = null;
try {
  ppro = require('premierepro');
  console.log('[YTAI] navigator.js: premierepro loaded OK');
} catch (ex) {
  console.log('[YTAI] navigator.js: premierepro not available:', ex.message);
}

/* ── Jump to time in active sequence ── */
async function jumpToTime(sourceFile, inSec) {
  if (!ppro) { appLog('Premiere API not available', 'error'); return; }

  try {
    var project = await ppro.Project.getActiveProject();
    if (!project) { appLog('No active project', 'error'); return; }

    var seq = await project.getActiveSequence();
    if (!seq) { appLog('No active sequence', 'error'); return; }

    /* Strategy 1: Use cached timeline positions from build.
       Find segment that CONTAINS this time point (not just segment start).
       Then compute: timelinePos = segStart + (wordTime - segInSec) */
    var seg = APP.segments.find(function (s) {
      return s.sourceFile === sourceFile && inSec >= s.inSec - 0.1 && inSec <= s.outSec + 0.1;
    });

    if (seg && APP._timelinePositions && APP._timelinePositions[seg.id] !== undefined) {
      var segStart = APP._timelinePositions[seg.id];
      var offset = inSec - seg.inSec;
      var calcPos = segStart + Math.max(0, offset);
      var calcTime = ppro.TickTime.createWithSeconds(calcPos);
      seq.setPlayerPosition(calcTime);
      appLog('Jump (calc): ' + seg.id + ' +' + offset.toFixed(1) + 's → ' + calcPos.toFixed(1) + 's [' + APP.activeTimeline + ']');
      return;
    }

    /* Strategy 2: Scan timeline tracks for matching clip */
    var found = false;
    try {
      var trackCount = seq.getVideoTrackCount();
      for (var ti = 0; ti < trackCount && !found; ti++) {
        try {
          var track = seq.getVideoTrack(ti);
          if (!track) continue;

          var trackItems = null;
          try { trackItems = track.getTrackItems(); } catch (ex) {
            try { trackItems = track.getTrackItems(1, false); } catch (ex2) { continue; }
          }
          if (!trackItems || !trackItems.length) continue;

          for (var ci = 0; ci < trackItems.length; ci++) {
            var item = trackItems[ci];
            try {
              var itemName = '';
              /* Try various ways to get clip name */
              if (item.name) {
                itemName = item.name;
              } else if (item.projectItem && item.projectItem.name) {
                itemName = item.projectItem.name;
              }

              var baseName = sourceFile.replace(/\.[^.]+$/, '');
              if (itemName === sourceFile || itemName === baseName ||
                  itemName.indexOf(baseName) >= 0) {

                /* Found the clip — calculate position */
                var clipStart = item.start;
                if (clipStart && clipStart.seconds !== undefined) {
                  var clipInPoint = item.inPoint;
                  var offset = inSec;
                  if (clipInPoint && clipInPoint.seconds !== undefined) {
                    offset = inSec - clipInPoint.seconds;
                  }
                  var absSeconds = clipStart.seconds + offset;
                  var absTime = ppro.TickTime.createWithSeconds(absSeconds);
                  seq.setPlayerPosition(absTime);
                  appLog('Jump (track): ' + sourceFile + ' @ ' + absSeconds.toFixed(1) + 's');
                  found = true;
                  break;
                }
              }
            } catch (ex) { /* skip individual item */ }
          }
        } catch (ex) { /* skip track */ }
      }
    } catch (ex) {
      console.log('[YTAI] Track scan error:', ex.message);
    }

    /* Strategy 3: Fallback — use inSec as absolute position */
    if (!found) {
      var fallbackTime = ppro.TickTime.createWithSeconds(inSec);
      seq.setPlayerPosition(fallbackTime);
      appLog('Jump (fallback): ' + sourceFile + ' @ ' + inSec.toFixed(1) + 's');
    }
  } catch (e) {
    appLog('Jump error: ' + e.message, 'error');
  }
}

/* ── Play segment (jump + set in/out on sequence) ── */
async function playSegment(sourceFile, inSec, outSec) {
  await jumpToTime(sourceFile, inSec);
  /* Premiere UXP doesn't have a direct play command,
     but jumping to the position is the main functionality needed */
}

/* ── Jump/Play active segment ── */
async function jumpToActiveSegment() {
  if (!APP.activeSegmentId) return;
  var seg = APP.segments.find(function (s) { return s.id === APP.activeSegmentId; });
  if (seg) await jumpToTime(seg.sourceFile, seg.inSec);
}

async function playActiveSegment() {
  if (!APP.activeSegmentId) return;
  var seg = APP.segments.find(function (s) { return s.id === APP.activeSegmentId; });
  if (seg) await playSegment(seg.sourceFile, seg.inSec, seg.outSec);
}

/* Global namespace */
var NAV = {
  jumpToTime: jumpToTime,
  playSegment: playSegment,
  jumpToActiveSegment: jumpToActiveSegment,
  playActiveSegment: playActiveSegment,
};

console.log('[YTAI] navigator.js loaded OK. NAV =', typeof NAV);
