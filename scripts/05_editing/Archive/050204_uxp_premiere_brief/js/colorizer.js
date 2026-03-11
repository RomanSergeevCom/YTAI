/* colorizer.js — Apply label colors + clip naming */

// Apply colors and names to all clips on a sequence
// Process CUT clips first (Red), then USE clips (block color)
// because label color is per-ProjectItem (last write wins)
async function applyColors(project, sequence, segments, posKey) {
  var track = await sequence.getVideoTrack(0);
  var items = await getCleanTrackItems(track);
  var count = Math.min(items.length, segments.length);

  if (count === 0) return;

  // Split into CUT and USE for ordering
  var cutIndices = [];
  var useIndices = [];
  for (var i = 0; i < count; i++) {
    if (!segments[i].use || segments[i].block === 99) {
      cutIndices.push(i);
    } else {
      useIndices.push(i);
    }
  }

  // Process CUT first (so USE color overwrites Red on shared sources)
  var allIndices = cutIndices.concat(useIndices);

  for (var idx = 0; idx < allIndices.length; idx++) {
    var i = allIndices[idx];
    var seg = segments[i];
    var item = items[i];

    // Determine color and name
    var isCut = !seg.use || seg.block === 99;
    var colorName = isCut ? 'Red' : (seg.color || 'Cyan');
    var colorIndex = LABEL_COLOR_INDEX[colorName];
    if (colorIndex == null) colorIndex = LABEL_COLOR_INDEX.Cyan;

    var clipName = isCut
      ? '[CUT] ' + seg.id + ' ' + seg.blockName
      : '[' + colorName + '] ' + seg.id + ' ' + seg.blockName;

    try {
      // Get project item for color label
      var projItem = null;
      if (typeof item.getProjectItem === 'function') {
        projItem = await item.getProjectItem();
      }

      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          // Set clip name
          if (typeof item.createSetNameAction === 'function') {
            ca.addAction(item.createSetNameAction(clipName));
          }
          // Set color label on project item
          if (projItem && typeof projItem.createSetColorLabelAction === 'function') {
            ca.addAction(projItem.createSetColorLabelAction(colorIndex));
          }
          // Disable CUT clips
          if (isCut && typeof item.createSetDisabledAction === 'function') {
            ca.addAction(item.createSetDisabledAction(true));
          }
        }, 'Color: ' + seg.id);
      });
    } catch (ex) {
      appLog('  Color failed ' + seg.id + ': ' + ex.message, 'warn');
    }
  }

  appLog('Colors applied: ' + count + ' clips', 'ok');
}

// Apply colors to both sequences
async function colorAllSequences(project, fullResult, editResult) {
  if (fullResult) {
    appLog('--- Coloring FULL sequence ---', 'step');
    await applyColors(project, fullResult.sequence, fullResult.segments, '_fullTargetPos');
  }

  if (editResult) {
    appLog('--- Coloring EDIT sequence ---', 'step');
    await applyColors(project, editResult.sequence, editResult.segments, '_editTargetPos');
  }
}
