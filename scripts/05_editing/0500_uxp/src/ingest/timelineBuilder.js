/**
 * Timeline builder — public API dispatcher for ingest sequence building.
 *
 * After Phase 4 of wall-clock refactor (2026-05-31), this file is a thin
 * dispatcher (~80 LoC) that routes to either:
 *   - placement/wallClockBuilder.js  (when ingest.layout_mode === 'wallclock'
 *                                      OR all clips have creation_time)
 *   - placement/linearBuilder.js     (legacy back-to-back behaviour)
 *
 * Back-compat: re-exports findProjectItemByName, applyMediaSettings,
 * logSequenceSettings, listBinItems so callers (transcriptImporter.js, index.js)
 * keep working unchanged.
 *
 * See docs/wallclock/WALLCLOCK_DESIGN.md for the design rationale.
 */

const linearBuilder = require('./placement/linearBuilder');
const wallClockBuilder = require('./placement/wallClockBuilder');
const { findProjectItemByName, listBinItems } = require('../shared/projectItemFinder');
const { applyMediaSettings, logSequenceSettings, SEQUENCE_DEFAULTS } = require('../shared/mediaSettings');

/**
 * Resolve which layout mode to use.
 *
 * Priority:
 *   1. explicit `ingest.layout_mode` field (`"wallclock"` | `"linear"`)
 *   2. auto-detect wallclock ONLY for a fully-prepared v2.0 ingest:
 *      version === "2.0" AND every clip has a numeric `wall_offset`.
 *   3. otherwise linear.
 *
 * IMPORTANT (regression guard): a v1.x ingest where clips merely carry
 * `creation_time` is NOT yet prepared for wall-clock — it has no `wall_offset`
 * and no `tx_strips`. Auto-selecting wallclock there would silently produce
 * video-only sequences with zero lavalier audio. Such files route to linear
 * (their original builder) unless 0111+0112 have run to finalise v2.0.
 *
 * @param {Object} ingest
 * @returns {'wallclock' | 'linear'}
 */
function resolveLayoutMode(ingest) {
  if (ingest && ingest.layout_mode) {
    const m = String(ingest.layout_mode).toLowerCase();
    if (m === 'wallclock' || m === 'linear') return m;
  }
  const clips = ingest && Array.isArray(ingest.clips) ? ingest.clips : [];
  const isV2 = ingest && String(ingest.version) === '2.0';
  const allHaveWallOffset = clips.length > 0 && clips.every(c => typeof c.wall_offset === 'number');
  if (isV2 && allHaveWallOffset) {
    return 'wallclock';
  }
  return 'linear';
}

/**
 * Build multi-scene ingest — dispatches to wall-clock or linear builder.
 *
 * Public API. Signature unchanged from pre-refactor for back-compat.
 *
 * @param {Object} project - Premiere Pro project
 * @param {Object} ingest - Parsed ingest JSON
 * @param {Object|null} sourceBin - Target bin for imported media (00_Source)
 * @param {Object} logger
 * @returns {Promise<{ sequences: Array<Object>, totalClipCount: number, totalDjiCount?: number, totalTxPlaced?: number }>}
 */
async function buildMultiSceneIngest(project, ingest, sourceBin, logger) {
  const mode = resolveLayoutMode(ingest);
  logger.info(`Layout mode: ${mode}`);

  if (mode === 'wallclock') {
    return wallClockBuilder.build(project, ingest, sourceBin, logger);
  }
  return linearBuilder.buildMultiSceneIngest(project, ingest, sourceBin, logger);
}

/**
 * Build single-scene ingest (legacy entry point used by index.js).
 *
 * Always routes to linearBuilder — wall-clock layout is multi-scene only.
 *
 * @param {Object} project
 * @param {Object} ingest
 * @param {Object|null} sourceBin
 * @param {Object|null} sequenceBin - unused, kept for back-compat
 * @param {Object} logger
 */
async function buildIngestSequence(project, ingest, sourceBin, sequenceBin, logger) {
  return linearBuilder.buildIngestSequence(project, ingest, sourceBin, sequenceBin, logger);
}

module.exports = {
  // Public API
  buildIngestSequence,
  buildMultiSceneIngest,
  resolveLayoutMode,

  // Back-compat re-exports
  findProjectItemByName,
  applyMediaSettings,
  logSequenceSettings,
  listBinItems,
  SEQUENCE_DEFAULTS,
};
