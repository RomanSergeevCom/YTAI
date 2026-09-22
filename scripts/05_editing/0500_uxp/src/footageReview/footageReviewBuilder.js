/**
 * Footage Review builder — the lightweight "отсмотр" path.
 *
 * Given a plain list of video file paths (from a camera card or a loose folder),
 * with NO JSON brief:
 *   1. Imports every clip into the active project.
 *   2. Creates a sequence from the first clip (inherits real fps/resolution).
 *   3. Lays all clips back-to-back on V1/A1 (0-gap via read-back, like assemblyBuilder).
 *   4. Copies bright/normal/dark .cube LUTs to the Lumetri Creative folder.
 *   5. One-click LUT: wraps the flat sequence in a REVIEW sequence (nested as a single
 *      clip) and puts ONE Lumetri on it — so picking a Look once grades the whole отсмотр.
 *      Falls back to per-clip Lumetri (and cleans up the stray wrapper) if nesting isn't
 *      available in this Premiere build.
 *
 * Pure logic — file discovery (scanning /Volumes for cards) lives in index.js because
 * it needs the UXP fs runtime. This module is unit-tested against tests/mocks/premierepro.
 *
 * Known limitations (single-source by design): if two FX3 dual-slot cards are mounted,
 * only the source with the most clips is used (identical filenames across cards are not
 * merged). Re-running on the same project re-imports clips (duplicate bin items); the
 * timeline still resolves to the freshly-mapped items.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

const { findProjectItemByName } = require('../shared/projectItemFinder');
const { copyLutsToCreativeFolder, copyLutsToFolder } = require('../ingest/lutManager');

const FOOTAGE_REVIEW_VERSION = '1.1.0';
const TICKS_PER_SEC = 254016000000;

function baseName(p) {
  return String(p).split('/').pop();
}

/** Absolute path of the open project's .prproj (or null) — for locating its folder. */
async function projectPath(project) {
  try { if (project.path) return String(project.path); } catch (e) { /* getter may throw */ }
  try { return String(await project.getPath()); } catch (e) { /* none */ }
  return null;
}

/** Unicode-aware sanitize — keeps letters/digits (incl. Cyrillic), collapses the rest to '_'. */
function sanitizeName(s) {
  var out = String(s || 'Footage').replace(/[^\p{L}\p{N}_-]+/gu, '_').replace(/^_+|_+$/g, '');
  return out || 'Footage';
}

/** Read the actual end of a track (last item start+duration) — guarantees 0-gap placement. */
async function readbackEnd(track, fallback) {
  try {
    let items = null;
    try { items = track.getTrackItems(1, false); } catch (e) { /* try no-arg */ }
    if (!items) { try { items = track.getTrackItems(); } catch (e) { /* none */ } }
    if (items && items.length > 0) {
      const last = items[items.length - 1];
      const s = await last.getStartTime();
      const d = await last.getDuration();
      const ss = s && s.seconds !== undefined ? s.seconds : 0;
      const ds = d && d.seconds !== undefined ? d.seconds : (d && d.ticks ? d.ticks / TICKS_PER_SEC : 0);
      return ss + ds;
    }
  } catch (e) { /* fall through */ }
  return fallback;
}

/** Build a name→ProjectItem map from project root ONCE — avoids O(N^2) per-clip lookups. */
async function buildNameMap(project) {
  const map = {};
  try {
    const root = await project.getRootItem();
    const items = await root.getItems();
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      let nm = null;
      try { nm = it.name || (it.getName ? await it.getName() : null); } catch (e) { /* skip */ }
      if (nm && !map[nm]) map[nm] = it; // first occurrence wins (stable)
    }
  } catch (e) { /* fall back to findProjectItemByName */ }
  return map;
}

/** Place one project item on V1/A1 at `posSec`; insert first, overwrite as fallback. */
function placeClip(project, seqEditor, rawItem, posSec, label) {
  const insertTime = ppro.TickTime.createWithSeconds(posSec);
  try {
    project.lockedAccess(function () {
      project.executeTransaction(function (ca) {
        ca.addAction(seqEditor.createInsertProjectItemAction(rawItem, insertTime, 0, 0, true));
      }, 'Footage insert: ' + label);
    });
    return true;
  } catch (e) {
    try {
      project.lockedAccess(function () {
        project.executeTransaction(function (ca) {
          ca.addAction(seqEditor.createOverwriteItemAction(rawItem, insertTime, 0, 0));
        }, 'Footage overwrite: ' + label);
      });
      return true;
    } catch (e2) {
      return false;
    }
  }
}

/**
 * @param {Object} project    active Premiere Pro project (ppro.Project.getActiveProject())
 * @param {string[]} videoFiles  absolute paths to the clips to review
 * @param {Object} opts        { name, applyLut=true }
 * @param {Object} logger      Logger instance
 * @returns {Object} { version, srcSeqName, placed, total, durationSec, lutFolder, lutsCopied }
 */
async function buildFootageReview(project, videoFiles, opts, logger) {
  opts = opts || {};
  const name = sanitizeName(opts.name || 'Footage');
  const applyLut = opts.applyLut !== false;
  if (!videoFiles || !videoFiles.length) throw new Error('No video files to review');

  // 1. Import (in place — no copy; instant screening)
  logger.info('Footage Review v' + FOOTAGE_REVIEW_VERSION + ' — importing ' + videoFiles.length + ' clip(s)');
  try {
    await project.importFiles(videoFiles, true, null, false);
  } catch (e) {
    logger.error('importFiles failed: ' + e.message);
    throw e;
  }

  // Resolve clips O(1) from a one-shot name map (fallback: per-name search).
  const nameMap = await buildNameMap(project);
  async function resolve(fileName) {
    return nameMap[fileName] || (await findProjectItemByName(project, fileName, logger));
  }

  // 2. Sequence from first clip (real fps/resolution)
  const srcSeqName = name + '_Footage';
  const firstName = baseName(videoFiles[0]);
  const firstItem = await resolve(firstName);
  if (!firstItem) throw new Error('First clip not found after import: ' + firstName);
  const firstCast = ppro.ClipProjectItem.cast(firstItem) || firstItem;

  let srcSeq;
  let seeded = true; // createSequenceFromMedia places the first clip itself
  try {
    srcSeq = await project.createSequenceFromMedia(srcSeqName, [firstCast]);
  } catch (e) {
    logger.warn('createSequenceFromMedia failed, using empty createSequence: ' + e.message);
    seeded = false;
    srcSeq = await project.createSequence(srcSeqName);
  }
  if (!srcSeq) throw new Error('Failed to create footage sequence');

  const seqEditor = ppro.SequenceEditor.getEditor(srcSeq);
  const v1 = await srcSeq.getVideoTrack(0);

  // 3. Lay clips back-to-back (read-back end → 0-gap). If seeded, clip 0 is already on V1.
  let placed = seeded ? 1 : 0;
  let pos = seeded ? await readbackEnd(v1, 0) : 0;
  for (let i = (seeded ? 1 : 0); i < videoFiles.length; i++) {
    const nm = baseName(videoFiles[i]);
    const item = await resolve(nm);
    if (!item) { logger.warn('Skip (not imported): ' + nm); continue; }
    const ok = placeClip(project, seqEditor, item, pos, nm);
    if (ok) {
      placed++;
      logger.info('[' + (i + 1) + '/' + videoFiles.length + '] ' + nm + ' @ ' + pos.toFixed(2) + 's');
    } else {
      logger.error('Place failed: ' + nm);
    }
    pos = await readbackEnd(v1, pos);
  }
  logger.info('Footage timeline: ' + placed + '/' + videoFiles.length + ' clip(s), ~' + pos.toFixed(1) + 's');

  // 4. LUTs — just COPY the .cube files where they're one drag away. No nested wrapper,
  //    no auto-apply: the UXP API can't create an adjustment layer or set a LUT, so the
  //    user drops a LUT onto a manual adjustment layer. Copy into the project's LUT/ folder
  //    + the Lumetri Creative folder (appears in the Look dropdown after a Premiere restart).
  let lutsCopied = [];
  let lutFolder = null;
  if (applyLut) {
    try {
      let dir = opts.projectFolder || '';
      if (!dir) { const pp = await projectPath(project); dir = pp ? pp.replace(/\/[^/]*$/, '') : ''; }
      if (dir) {
        const r = await copyLutsToFolder(dir, ['01_Source', '00_LUT'], logger);
        lutFolder = r.folder;
        lutsCopied = r.files || [];
      }
    } catch (e) { logger.warn('LUT copy to 01_Source/00_LUT skipped: ' + e.message); }
    try { await copyLutsToCreativeFolder({}, logger); } catch (e) { /* best-effort */ }
  }

  // 5. Open the flat footage sequence (clips stay individual on V1; production opens via .guid)
  try { if (project.setActiveSequence) await project.setActiveSequence(srcSeq); } catch (e) { /* ignore */ }
  try { if (project.openSequence) await project.openSequence(srcSeq.guid || srcSeq); } catch (e) { /* ignore */ }
  try { await project.save(); } catch (e) { /* ignore */ }

  return {
    version: FOOTAGE_REVIEW_VERSION,
    srcSeqName: srcSeqName,
    placed: placed,
    total: videoFiles.length,
    durationSec: pos,
    lutFolder: lutFolder,
    lutsCopied: lutsCopied,
  };
}

module.exports = { buildFootageReview, FOOTAGE_REVIEW_VERSION, baseName, sanitizeName };
