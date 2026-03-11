/* markers.js — Chapter + comment markers with batch fallback */

// Create markers on a sequence
async function createMarkers(project, sequence, segments) {
  var markersObj = null;
  try {
    markersObj = await bppro.Markers.getMarkers(sequence);
  } catch (ex) {
    appLog('Cannot get markers object: ' + ex.message, 'error');
    return;
  }

  if (!markersObj) {
    appLog('Markers object is null', 'error');
    return;
  }

  // Determine marker types
  var chapterType = null;
  try { chapterType = bppro.Marker.MARKER_TYPE_CHAPTER; } catch (ex) { }
  var commentType = null;
  try { commentType = bppro.Marker.MARKER_TYPE_COMMENT; } catch (ex) { }
  var useChapterType = chapterType || commentType || 'Comment';
  var useCommentType = commentType || 'Comment';

  // Build marker list: chapter markers at block boundaries
  var markerList = [];
  var timelinePos = 0;

  // Group segments by block for chapter markers
  var blockMap = {};
  segments.forEach(function (seg) {
    if (!blockMap[seg.block]) {
      blockMap[seg.block] = {
        name: seg.blockName,
        start: timelinePos,
        duration: 0,
        segments: [],
        hasChapter: false
      };
    }
    var block = blockMap[seg.block];
    block.segments.push(seg);
    block.duration += seg.duration;
    if (seg.isChapter) block.hasChapter = true;
    timelinePos += seg.duration;
  });

  // Create chapter markers for blocks
  var blockKeys = Object.keys(blockMap).sort(function (a, b) { return Number(a) - Number(b); });
  var cumTime = 0;
  for (var bi = 0; bi < blockKeys.length; bi++) {
    var bKey = blockKeys[bi];
    var block = blockMap[bKey];
    if (Number(bKey) === 99) continue; // Skip cut block

    // Chapter marker at block start
    if (block.hasChapter || bi === 0) {
      markerList.push({
        name: block.name,
        type: useChapterType,
        start: cumTime,
        duration: Math.max(block.duration, 0.5),
        comment: block.segments.map(function (s) {
          return (s.speaker ? s.speaker + ': ' : '') + (s.transcript || '').slice(0, 50);
        }).join(' | ')
      });
    }

    // Comment markers per segment within block
    var segTime = cumTime;
    for (var si = 0; si < block.segments.length; si++) {
      var seg = block.segments[si];
      var commentText = (seg.speaker ? seg.speaker + ': ' : '') +
        (seg.transcript || '').slice(0, 80);
      if (seg.notes) commentText += ' // ' + seg.notes.slice(0, 80);
      if (seg.brollNote) commentText += ' [B-roll: ' + seg.brollNote.slice(0, 60) + ']';

      markerList.push({
        name: seg.id + ' ' + (seg.segmentName || seg.blockName),
        type: useCommentType,
        start: segTime,
        duration: Math.max(seg.duration, 0.1),
        comment: commentText
      });
      segTime += seg.duration;
    }

    cumTime += block.duration;
  }

  appLog('Creating ' + markerList.length + ' markers...');

  // Try batch creation first
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        for (var m = 0; m < markerList.length; m++) {
          var mk = markerList[m];
          ca.addAction(markersObj.createAddMarkerAction(
            mk.name,
            mk.type,
            bppro.TickTime.createWithSeconds(mk.start),
            bppro.TickTime.createWithSeconds(mk.duration),
            mk.comment
          ));
        }
      }, 'YTAI Markers');
    });
    appLog('Markers created (batch): ' + markerList.length, 'ok');
    return;
  } catch (batchErr) {
    appLog('Batch markers failed, trying individually...', 'warn');
  }

  // Fallback: create one by one
  var created = 0;
  for (var f = 0; f < markerList.length; f++) {
    try {
      var mk = markerList[f];
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(markersObj.createAddMarkerAction(
            mk.name,
            mk.type,
            bppro.TickTime.createWithSeconds(mk.start),
            bppro.TickTime.createWithSeconds(mk.duration),
            mk.comment
          ));
        }, 'Marker: ' + mk.name);
      });
      created++;
    } catch (ex) {
      appLog('  Marker failed: ' + markerList[f].name + ' — ' + ex.message, 'warn');
    }
  }

  appLog('Markers created (individual): ' + created + '/' + markerList.length, 'ok');
}

// Create markers on both sequences
async function createAllMarkers(project, fullResult, editResult) {
  if (fullResult) {
    appLog('--- Markers on FULL ---', 'step');
    await createMarkers(project, fullResult.sequence, fullResult.segments);
  }

  if (editResult) {
    appLog('--- Markers on EDIT ---', 'step');
    await createMarkers(project, editResult.sequence, editResult.segments);
  }
}
