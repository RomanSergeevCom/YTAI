/**
 * Clip placer — places one video clip or one TX audio strip on the timeline.
 *
 * Two placement paths, matching how real Premiere behaves:
 *
 *  VIDEO  → createOverwriteItemAction (exact wall-clock position, never shifts
 *           other tracks). Caller batches these into one transaction. Requires
 *           the target V-track to already exist (overwrite does NOT auto-create
 *           tracks per Adobe docs) — sequenceFactory.ensureTracks pre-warms them.
 *
 *  TX     → mirror the proven clipActions.insertDjiAudio pattern: THREE separate
 *           transactions executed sequentially —
 *             1. setSourceInOut  (trim the source WAV to this video-bounded range)
 *             2. createInsertProjectItemAction(item, t, -1, aIdx, limitShift=true)
 *                (audio-only; Adobe docs: insert AUTO-CREATES the A-track when the
 *                 index exceeds the current count)
 *             3. clearSourceInOut (so the same WAV can be re-trimmed for the next
 *                video-bounded slice)
 *           This is the load-bearing fix: the old code batched set→overwrite→clear
 *           into ONE compoundAction against a shared, reused ProjectItem, which
 *           risks the overwrite capturing a stale/cleared in/out and placing the
 *           full-duration WAV. Every other builder (assembly/screens/deletedScene)
 *           uses the 3-separate-transaction pattern; this now matches.
 *
 * TX placements MUST be applied in ascending offsetSec order per A-track so that
 * each insert lands after all previously-placed items on that track (nothing to
 * shift → behaves like an exact-position placement).
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../../tests/mocks/premierepro');
}

const clipActions = require('../../shared/clipActions');

/**
 * TickTime from a placement time. Prefers exact integer ticks (offsetTicks /
 * sourceInTicks / durationTicks strings emitted by sceneLayout.gridAlignPlan) —
 * float seconds like 109.44 sit 1 ulp off the frame grid and Premiere's own
 * rounding (insert: nearest; overwrite: measured +1-frame flips) then bites.
 */
function tickTimeOf(ticksStr, seconds) {
  if (ticksStr !== undefined && ticksStr !== null && ticksStr !== ''
      && typeof ppro.TickTime.createWithTicks === 'function') {
    return ppro.TickTime.createWithTicks(String(ticksStr));
  }
  return ppro.TickTime.createWithSeconds(seconds);
}

/**
 * Build the overwrite action for one VIDEO placement (caller batches it).
 *
 * @param {Object} seqEditor
 * @param {Object} projectItem
 * @param {Object} placement - { offsetSec, offsetTicks?, vIdx, aIdx }
 * @returns {Object|null} action
 */
function buildVideoAction(seqEditor, projectItem, placement, logger) {
  if (!projectItem) {
    if (logger) logger.error(`clipPlacer: video projectItem null for ${placement.filename}`);
    return null;
  }
  const t = tickTimeOf(placement.offsetTicks, placement.offsetSec);
  if (logger) logger.debug(`  V ${placement.filename} @ ticks=${placement.offsetTicks || '(float)'} sec=${placement.offsetSec}`);
  try {
    return seqEditor.createOverwriteItemAction(projectItem, t, placement.vIdx, placement.aIdx);
  } catch (err) {
    if (logger) logger.error(`clipPlacer: overwrite action failed for ${placement.filename}: ${err.message}`);
    return null;
  }
}

/**
 * Place ONE TX audio strip via the proven 3-transaction set→insert→clear
 * sequence (mirrors clipActions.insertDjiAudio).
 *
 * @param {Object} project
 * @param {Object} seqEditor
 * @param {Object} projectItem - the unsplit TX WAV ProjectItem
 * @param {Object} placement - { offsetSec, duration, sourceInPoint, aIdx, txId }
 * @param {Object} logger
 * @returns {boolean} true if the insert transaction succeeded
 */
function placeTxStrip(project, seqEditor, projectItem, placement, logger) {
  if (!projectItem) {
    if (logger) logger.error(`clipPlacer: TX projectItem null for ${placement.filename}`);
    return false;
  }

  const inSec = placement.sourceInPoint || 0;
  const outSec = inSec + placement.duration;
  const outTicksStr = (placement.sourceInTicks !== undefined && placement.durationTicks !== undefined)
    ? String(Number(placement.sourceInTicks) + Number(placement.durationTicks))
    : undefined;
  const inTick = tickTimeOf(placement.sourceInTicks, inSec);
  const outTick = tickTimeOf(outTicksStr, outSec);
  const insertTime = tickTimeOf(placement.offsetTicks, placement.offsetSec);
  const label = `${placement.txId || placement.filename}@${placement.offsetSec.toFixed(1)}s→A${placement.aIdx + 1}`;
  if (logger) logger.debug(`  TX req ${label}: pos=${placement.offsetTicks || '(float)'} in=${placement.sourceInTicks || '(float)'} dur=${placement.durationTicks || '(float)'} ticks`);

  // Cast for trim (insert uses the raw item, like insertDjiAudio)
  const cast = ppro.ClipProjectItem.cast(projectItem);
  const itemForTrim = cast || projectItem;

  // 1. Trim source to the video-bounded range (own transaction)
  clipActions.setSourceInOut(project, itemForTrim, inTick, outTick, label, logger);

  // 2. Insert audio-only on its A-track (own transaction). Insert auto-creates
  //    the track if aIdx >= current audio-track count (Adobe docs).
  let ok = false;
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(seqEditor.createInsertProjectItemAction(
          projectItem,    // raw item
          insertTime,
          -1,             // no video track (audio-only)
          placement.aIdx,
          true            // limitShift — confine ripple to the target track
        ));
      }, `TX ${label}`);
    });
    ok = true;
    if (logger) logger.debug(`  TX ${label}: ${placement.duration.toFixed(1)}s @ in=${inSec.toFixed(1)}s`);
  } catch (err) {
    if (logger) logger.error(`  TX insert failed ${label}: ${err.message}`);
  }

  // 3. Clear source in/out so the same WAV can be re-trimmed for the next slice
  clipActions.clearSourceInOut(project, itemForTrim, label, logger);

  return ok;
}

module.exports = {
  buildVideoAction,
  placeTxStrip,
};
