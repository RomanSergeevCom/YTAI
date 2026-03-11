/* sequence-builder.js — Create FULL + EDIT sequences, insert clips */

// Sort segments: by block number (99 last), then by tc_in within block
function sortSegments(segments) {
  return segments.slice().sort(function (a, b) {
    if (a.block !== b.block) {
      if (a.block === 99) return 1;
      if (b.block === 99) return -1;
      return a.block - b.block;
    }
    return a.inSec - b.inSec;
  });
}

// Get max source clip duration (for wide spacing)
function getMaxDuration(segments) {
  var max = 0;
  segments.forEach(function (s) {
    if (s.duration > max) max = s.duration;
  });
  return max || 60;
}

// Clear auto-inserted clips from V1 after createSequenceFromMedia
async function clearAutoInserted(project, sequence) {
  try {
    var v0 = await sequence.getVideoTrack(0);
    var rawItems = null;
    try { rawItems = v0.getTrackItems(1, false); } catch (ex) { }
    if (!rawItems) try { rawItems = v0.getTrackItems(); } catch (ex) { }
    if (!rawItems || rawItems.length === 0) return;

    // Try remove action first
    var hasRemove = typeof rawItems[0].createRemoveAction === 'function';
    if (hasRemove) {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          for (var i = 0; i < rawItems.length; i++) {
            ca.addAction(rawItems[i].createRemoveAction());
          }
        }, 'Clear auto-inserted');
      });
    } else {
      // Fallback: disable + rename
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          for (var i = 0; i < rawItems.length; i++) {
            if (typeof rawItems[i].createSetDisabledAction === 'function')
              ca.addAction(rawItems[i].createSetDisabledAction(true));
            if (typeof rawItems[i].createSetNameAction === 'function')
              ca.addAction(rawItems[i].createSetNameAction('[AUTO-SKIP]'));
          }
        }, 'Disable auto-inserted');
      });
    }
  } catch (ex) {
    appLog('Clear auto-inserted: ' + ex.message, 'warn');
  }
}

// Build FULL sequence: all segments (USE + CUT) in block order
async function buildFullSequence(project, clipMap) {
  var seqName = APP.projectName + '_FULL';
  var allSegs = sortSegments(APP.segments);
  appLog('Building FULL sequence: ' + allSegs.length + ' segments');

  // Find first clip for sequence creation (inherits resolution/fps)
  var firstClipItem = null;
  for (var i = 0; i < allSegs.length; i++) {
    if (clipMap[allSegs[i].sourceFile]) {
      firstClipItem = clipMap[allSegs[i].sourceFile];
      break;
    }
  }

  if (!firstClipItem) {
    throw new Error('No clips found in project for FULL sequence');
  }

  // Create sequence from first clip (inherits media settings)
  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClipItem]);
  } catch (ex) {
    appLog('createSequenceFromMedia failed, using createSequence', 'warn');
    seq = await project.createSequence(seqName);
  }

  if (!seq) throw new Error('Failed to create FULL sequence');
  appLog('FULL sequence created: ' + seqName, 'ok');

  // Clear auto-inserted clip
  await clearAutoInserted(project, seq);

  // Insert all segments with wide spacing
  var maxDur = getMaxDuration(allSegs);
  var editor = bppro.SequenceEditor.getEditor(seq);
  var insertPos = 0;
  var targetPos = 0;

  for (var s = 0; s < allSegs.length; s++) {
    var seg = allSegs[s];
    var clip = clipMap[seg.sourceFile];
    if (!clip) {
      appLog('  Skip ' + seg.id + ': no clip for ' + seg.sourceFile, 'warn');
      continue;
    }

    var insertTime = bppro.TickTime.createWithSeconds(insertPos);
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(editor.createInsertProjectItemAction(clip, insertTime, 0, 0, false));
        }, 'FULL insert: ' + seg.id);
      });
    } catch (ex) {
      appLog('  Insert failed ' + seg.id + ': ' + ex.message, 'error');
      continue;
    }

    // Track target position for later tight repositioning
    seg._fullTargetPos = targetPos;
    targetPos += seg.duration;
    insertPos += maxDur + 5;
  }

  appLog('FULL: ' + allSegs.length + ' clips inserted', 'ok');
  return { sequence: seq, segments: allSegs };
}

// Build EDIT sequence: only USE=TRUE segments in block order
async function buildEditSequence(project, clipMap) {
  var seqName = APP.projectName + '_EDIT';
  var useSegs = sortSegments(APP.segments.filter(function (s) {
    return s.use && s.block !== 99;
  }));
  appLog('Building EDIT sequence: ' + useSegs.length + ' segments');

  if (useSegs.length === 0) {
    appLog('No USE segments — skipping EDIT sequence', 'warn');
    return null;
  }

  // Find first clip
  var firstClipItem = null;
  for (var i = 0; i < useSegs.length; i++) {
    if (clipMap[useSegs[i].sourceFile]) {
      firstClipItem = clipMap[useSegs[i].sourceFile];
      break;
    }
  }

  if (!firstClipItem) {
    throw new Error('No clips found for EDIT sequence');
  }

  var seq = null;
  try {
    seq = await project.createSequenceFromMedia(seqName, [firstClipItem]);
  } catch (ex) {
    appLog('createSequenceFromMedia failed, using createSequence', 'warn');
    seq = await project.createSequence(seqName);
  }

  if (!seq) throw new Error('Failed to create EDIT sequence');
  appLog('EDIT sequence created: ' + seqName, 'ok');

  // Clear auto-inserted clip
  await clearAutoInserted(project, seq);

  // Insert USE segments with wide spacing
  var maxDur = getMaxDuration(useSegs);
  var editor = bppro.SequenceEditor.getEditor(seq);
  var insertPos = 0;
  var targetPos = 0;

  for (var s = 0; s < useSegs.length; s++) {
    var seg = useSegs[s];
    var clip = clipMap[seg.sourceFile];
    if (!clip) {
      appLog('  Skip ' + seg.id + ': no clip', 'warn');
      continue;
    }

    var insertTime = bppro.TickTime.createWithSeconds(insertPos);
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(editor.createInsertProjectItemAction(clip, insertTime, 0, 0, false));
        }, 'EDIT insert: ' + seg.id);
      });
    } catch (ex) {
      appLog('  Insert failed ' + seg.id + ': ' + ex.message, 'error');
      continue;
    }

    seg._editTargetPos = targetPos;
    targetPos += seg.duration;
    insertPos += maxDur + 5;
  }

  appLog('EDIT: ' + useSegs.length + ' clips inserted', 'ok');
  return { sequence: seq, segments: useSegs };
}

// Get filtered track items (skip fillers, gaps, disabled)
async function getCleanTrackItems(track) {
  var CLIP_TYPE = 1;
  try { CLIP_TYPE = bppro.Constants.TrackItemType.CLIP || 1; } catch (ex) { }

  var rawItems = null;

  // Multi-strategy retrieval
  try { rawItems = track.getTrackItems(CLIP_TYPE, false); } catch (ex) { }
  if (!rawItems || rawItems.length === 0) {
    var combos = [[1, true], [0, false], [0, true]];
    for (var c = 0; c < combos.length; c++) {
      try {
        rawItems = track.getTrackItems(combos[c][0], combos[c][1]);
        if (rawItems && rawItems.length > 0) break;
      } catch (ex) { }
    }
  }
  if (!rawItems || rawItems.length === 0) {
    try { rawItems = track.getTrackItems(); } catch (ex) { }
  }
  if (!rawItems) return [];

  // Filter out fillers/gaps
  var filtered = [];
  for (var i = 0; i < rawItems.length; i++) {
    var item = rawItems[i];

    // Skip disabled
    try {
      if (typeof item.isDisabled === 'function' && await item.isDisabled()) continue;
    } catch (ex) { }

    // Skip auto-skip / ghost items
    try {
      if (typeof item.getName === 'function') {
        var name = await item.getName();
        if (name && (name.indexOf('[AUTO-SKIP]') === 0 || name.indexOf('[GHOST]') === 0)) continue;
      }
    } catch (ex) { }

    // Skip non-clip types
    try {
      if (typeof item.getType === 'function') {
        var itemType = await item.getType();
        if (itemType !== CLIP_TYPE && itemType !== 1) continue;
      }
    } catch (ex) { }

    // Skip items without project item (fillers/gaps)
    try {
      if (typeof item.getProjectItem === 'function') {
        var pi = await item.getProjectItem();
        if (!pi) continue;
      }
    } catch (ex) { }

    filtered.push(item);
  }

  return filtered.length > 0 ? filtered : rawItems;
}

// Remove ghost clips beyond expected count
async function removeGhosts(project, track, expectedCount) {
  var items = await getCleanTrackItems(track);
  if (items.length <= expectedCount) return;

  appLog('Removing ' + (items.length - expectedCount) + ' ghost clips', 'warn');

  for (var i = expectedCount; i < items.length; i++) {
    try {
      var ghostItem = items[i];
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          if (typeof ghostItem.createSetDisabledAction === 'function')
            ca.addAction(ghostItem.createSetDisabledAction(true));
          if (typeof ghostItem.createSetNameAction === 'function')
            ca.addAction(ghostItem.createSetNameAction('[GHOST]'));
        }, 'Ghost: ' + i);
      });
    } catch (ex) { }
  }
}
