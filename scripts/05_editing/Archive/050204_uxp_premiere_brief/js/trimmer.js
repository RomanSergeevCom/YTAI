/* trimmer.js — Trim clips to tc_in/tc_out using 3-action pattern */

// Trim all clips on a sequence's V1 track
// segments must be in the same order they were inserted
async function trimSequence(project, sequence, segments, posKey) {
  var track = await sequence.getVideoTrack(0);
  var items = await getCleanTrackItems(track);

  if (items.length === 0) {
    appLog('No track items to trim', 'warn');
    return;
  }

  // Remove ghosts if more items than expected
  if (items.length > segments.length) {
    await removeGhosts(project, track, segments.length);
    items = await getCleanTrackItems(track);
  }

  var trimCount = Math.min(items.length, segments.length);
  appLog('Trimming ' + trimCount + ' clips...');

  for (var i = 0; i < trimCount; i++) {
    var seg = segments[i];
    var item = items[i];
    var targetPos = seg[posKey] || 0;

    try {
      await trimClip(project, item, seg.inSec, seg.outSec, targetPos);
    } catch (ex) {
      appLog('  Trim failed ' + seg.id + ': ' + ex.message, 'error');
    }
  }

  appLog('Trimmed ' + trimCount + ' clips', 'ok');
}

// Trim a single clip: 3-action transaction
// 1. Set OUT point (shrink from right)
// 2. Set IN point (move left edge)
// 3. Move to target position (RELATIVE delta)
async function trimClip(project, item, inSec, outSec, targetPos) {
  var srcIn = bppro.TickTime.createWithSeconds(inSec);
  var srcOut = bppro.TickTime.createWithSeconds(outSec);

  // Step 1+2: Set in/out points in one transaction
  project.lockedAccess(function () {
    project.executeTransaction(function (ca) {
      ca.addAction(item.createSetOutPointAction(srcOut));
      ca.addAction(item.createSetInPointAction(srcIn));
    }, 'Trim in/out');
  });

  // Step 3: Reposition (RELATIVE move — critical: must compute delta)
  var curStart = tickSec(await item.getStartTime());
  if (curStart < 0) {
    appLog('  Cannot read start time, skip reposition', 'warn');
    return;
  }

  var moveDelta = targetPos - curStart;
  if (Math.abs(moveDelta) < 0.001) return; // Already in position

  var deltaTime = bppro.TickTime.createWithSeconds(moveDelta);
  project.lockedAccess(function () {
    project.executeTransaction(function (ca) {
      ca.addAction(item.createMoveAction(deltaTime));
    }, 'Reposition');
  });
}

// Trim and reposition both FULL and EDIT sequences
async function trimAllSequences(project, fullResult, editResult) {
  if (fullResult) {
    appLog('--- Trimming FULL sequence ---', 'step');
    await trimSequence(project, fullResult.sequence, fullResult.segments, '_fullTargetPos');
  }

  if (editResult) {
    appLog('--- Trimming EDIT sequence ---', 'step');
    await trimSequence(project, editResult.sequence, editResult.segments, '_editTargetPos');
  }
}
