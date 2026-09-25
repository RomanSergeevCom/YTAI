/**
 * LUT Manager — copies .cube LUTs to Creative folder and applies Lumetri Color to V1 clips.
 *
 * .cube files are copied to /Library/Application Support/Adobe/Common/LUTs/Creative/YTAI/
 * so they appear in Lumetri > Creative > Look dropdown.
 *
 * Lumetri Color effect is applied to each V1 clip via VideoFilterFactory API.
 * User selects the desired LUT manually in Lumetri panel.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

// LUTs are bundled with the plugin in ./LUTs/
// At runtime in UXP, we resolve via pluginFolder; in tests, use relative path
let DEFAULT_LUTS_SOURCE;
try {
  const uxpForPath = require('uxp');
  // Will be resolved at runtime when copyLutsToCreativeFolder is called
  DEFAULT_LUTS_SOURCE = null; // Set dynamically from plugin folder
} catch (e) {
  // Node.js test environment — use relative path from this file
  const path = require('path');
  DEFAULT_LUTS_SOURCE = path.resolve(__dirname, '../../LUTs');
}
// User-level path (writable without admin). System-level /Library/... requires root.
const HOME = typeof require !== 'undefined' && (() => { try { return require('os').homedir(); } catch(e) { return ''; } })() || '';
const CREATIVE_LUTS_DEST_USER = `${HOME}/Library/Application Support/Adobe/Common/LUTs/Creative/YTAI`;
const CREATIVE_LUTS_DEST_SYSTEM = '/Library/Application Support/Adobe/Common/LUTs/Creative/YTAI';

/**
 * Copy .cube LUT files to Adobe Creative LUTs folder.
 * Creates YTAI/ subfolder if it doesn't exist.
 * After copy, LUTs appear in Lumetri > Creative > Look dropdown (requires Premiere restart).
 *
 * @param {Object} ingest - Ingest data (may contain luts_folder field)
 * @param {Object} logger - Logger instance
 * @returns {string[]} Names of copied .cube files
 */
async function copyLutsToCreativeFolder(ingest, logger) {
  const uxp = require('uxp');
  const fs = uxp.storage.localFileSystem;

  let lutsSource = (ingest && ingest.luts_folder) || DEFAULT_LUTS_SOURCE;
  // In UXP: resolve from plugin folder
  if (!lutsSource) {
    try {
      const uxpLuts = require('uxp');
      const pluginFolder = await uxpLuts.storage.localFileSystem.getPluginFolder();
      lutsSource = pluginFolder.nativePath + '/LUTs';
    } catch (e) {
      lutsSource = './LUTs';
    }
  }
  logger.info(`LUTs source: ${lutsSource}`);

  const copied = [];

  try {
    // Open source folder
    const srcFolder = await fs.getEntryWithUrl('file://' + lutsSource);
    const entries = await srcFolder.getEntries();
    const cubeFiles = entries.filter(e => e.name.endsWith('.cube'));

    if (cubeFiles.length === 0) {
      logger.warn(`No .cube files found in ${lutsSource}`);
      return copied;
    }
    logger.debug(`Found ${cubeFiles.length} .cube file(s): ${cubeFiles.map(f => f.name).join(', ')}`);

    // Ensure destination folder exists — try user-level first, then system-level
    let destFolder;
    const destPaths = [CREATIVE_LUTS_DEST_USER, CREATIVE_LUTS_DEST_SYSTEM];
    for (const destPath of destPaths) {
      try {
        destFolder = await fs.getEntryWithUrl('file://' + destPath);
        logger.debug(`Found LUTs folder: ${destPath}`);
        break;
      } catch (e) {
        // Try to create it
        try {
          const parentPath = destPath.replace(/\/YTAI$/, '');
          const parent = await fs.getEntryWithUrl('file://' + parentPath);
          destFolder = await parent.createFolder('YTAI');
          logger.debug(`Created LUTs folder: ${destPath}`);
          break;
        } catch (createErr) {
          logger.debug(`Cannot use ${destPath}: ${createErr.message}`);
        }
      }
    }

    if (!destFolder) {
      logger.warn(`Cannot access LUTs Creative folder`);
      logger.info(`Tried: ${destPaths.join(' | ')}`);
      logger.info(`Run in Terminal: mkdir -p "${CREATIVE_LUTS_DEST_USER}" && cp "${lutsSource}"/*.cube "${CREATIVE_LUTS_DEST_USER}/"`);
      logger.info(`Then restart Premiere. LUTs appear in: Lumetri > Creative > Look`);
      return copied;
    }

    // Copy each .cube file
    for (const cube of cubeFiles) {
      try {
        await cube.copyTo(destFolder, { overwrite: true });
        copied.push(cube.name);
        logger.debug(`Copied: ${cube.name}`);
      } catch (copyErr) {
        logger.warn(`Cannot copy ${cube.name}: ${copyErr.message}`);
      }
    }

    if (copied.length > 0) {
      logger.info(`LUTs copied to Creative folder: ${copied.join(', ')}`);
    }
  } catch (err) {
    logger.warn(`LUT copy failed: ${err.message}`);
    logger.info(`Manual copy: mkdir -p "${CREATIVE_LUTS_DEST_USER}" && cp ${lutsSource}/*.cube "${CREATIVE_LUTS_DEST_USER}/"`);
  }

  return copied;
}

/**
 * Apply Lumetri Color effect to all V1 clips.
 * Uses VideoFilterFactory to discover and create the effect,
 * then appends it to each clip's component chain.
 *
 * Also logs Lumetri parameter names for future automation.
 *
 * @param {Object} project - Premiere Pro project
 * @param {Object} sequence - Active sequence
 * @param {Object} logger - Logger instance
 * @returns {number} Number of clips with Lumetri applied
 */
async function applyLumetriToClips(project, sequence, logger) {
  let appliedCount = 0;

  try {
    // Step 1: Find Lumetri Color match name
    // await required — UXP API returns Promise<string[]>
    // Array.from() for safety — UXP may return non-Array collections
    const rawMatchNames = await ppro.VideoFilterFactory.getMatchNames();
    const rawDisplayNames = await ppro.VideoFilterFactory.getDisplayNames();
    logger.debug(`VideoFilterFactory raw: matchNames type=${typeof rawMatchNames}, isArray=${Array.isArray(rawMatchNames)}, length=${rawMatchNames && rawMatchNames.length}`);
    const matchNames = Array.from(rawMatchNames);
    const displayNames = Array.from(rawDisplayNames);
    logger.debug(`VideoFilter matchNames (${matchNames.length}): ${matchNames.slice(0, 10).join(', ')}${matchNames.length > 10 ? '...' : ''}`);

    let lumetriMatchName = null;
    for (let i = 0; i < displayNames.length; i++) {
      const disp = String(displayNames[i] || '');
      const mn = String(matchNames[i] || '');
      // Match by display name OR by match name (e.g. 'AE.ADBE Lumetri') — display
      // names can vary/localise between Premiere builds, match names are stable.
      if (disp === 'Lumetri Color' || disp.toLowerCase().includes('lumetri') || mn.toLowerCase().includes('lumetri')) {
        lumetriMatchName = matchNames[i];
        logger.info(`Found Lumetri: matchName="${lumetriMatchName}", display="${disp}"`);
        break;
      }
    }

    if (!lumetriMatchName) {
      logger.warn(`Lumetri Color effect not found in VideoFilterFactory`);
      logger.warn(`Display names (${displayNames.length}): ${displayNames.join(' | ')}`);
      logger.warn(`Match names (${matchNames.length}): ${matchNames.join(' | ')}`);
      return 0;
    }

    // Step 2: Get V1 track items
    const v1Track = await sequence.getVideoTrack(0);
    const trackItems = await v1Track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    logger.info(`Applying Lumetri Color to ${trackItems.length} V1 clip(s)`);

    // Step 3: Apply to each clip
    for (let i = 0; i < trackItems.length; i++) {
      const ti = trackItems[i];
      let name = `clip #${i + 1}`;

      try {
        try { name = String(await ti.getName()); } catch (nameErr) { /* keep placeholder */ }
        // Live 26.x has NO VideoClipTrackItem.cast — items from
        // getTrackItems(CLIP) already expose getComponentChain directly
        // (measured YTCH13 18.08.2026; the dead cast was why ingest logged
        // «Lumetri: not applied» forever). Try the cast for older builds/mock,
        // fall back to the raw item.
        let videoClip = ti;
        try {
          if (ppro.VideoClipTrackItem && typeof ppro.VideoClipTrackItem.cast === 'function') {
            videoClip = ppro.VideoClipTrackItem.cast(ti) || ti;
          }
        } catch (castErr) { videoClip = ti; }

        // Create Lumetri component (async in UXP)
        const lumetriComponent = await ppro.VideoFilterFactory.createComponent(lumetriMatchName);
        if (!lumetriComponent) {
          logger.warn(`Failed to create Lumetri component for "${name}"`);
          continue;
        }

        // Get component chain and append
        const chain = await videoClip.getComponentChain();
        await project.lockedAccess(() => {
          return project.executeTransaction((compoundAction) => {
            const appendAction = chain.createAppendComponentAction(lumetriComponent);
            compoundAction.addAction(appendAction);
          }, `Apply Lumetri to ${name}`);
        });

        appliedCount++;
        logger.info(`[${i + 1}/${trackItems.length}] Lumetri applied: "${name}"`);

        // Log params of first clip for debugging (to find LUT param index)
        if (i === 0) {
          try {
            const updatedChain = await videoClip.getComponentChain();
            // Live 26.x: getComponentCount()/getComponentAtIndex(i); the mock
            // (and possibly older builds) expose getComponents().
            let components;
            if (typeof updatedChain.getComponents === 'function') {
              components = (await updatedChain.getComponents()) || [];
            } else {
              components = [];
              const compCount = await updatedChain.getComponentCount();
              for (let ci = 0; ci < compCount; ci++) {
                try { components.push(await updatedChain.getComponentAtIndex(ci)); } catch (e) { /* skip */ }
              }
            }
            const lastComp = components[components.length - 1];
            if (lastComp) {
              const paramCount = await lastComp.getParamCount();
              const paramNames = [];
              const limit = Math.min(paramCount, 15);
              for (let p = 0; p < limit; p++) {
                try {
                  const param = await lastComp.getParam(p);
                  paramNames.push(`[${p}] ${param.displayName || param.name || '?'}`);
                } catch (e) { /* ignore */ }
              }
              logger.debug(`Lumetri params (first ${limit}): ${paramNames.join(', ')}`);
            }
          } catch (paramErr) {
            logger.debug(`Cannot read Lumetri params: ${paramErr.message}`);
          }
        }
      } catch (clipErr) {
        logger.warn(`Lumetri failed for "${name}": ${clipErr.message}`);
      }
    }

    logger.info(`Lumetri Color applied: ${appliedCount}/${trackItems.length} clips`);
  } catch (err) {
    logger.error(`applyLumetriToClips failed: ${err.message}`);
    if (err.stack) logger.debug(err.stack);
  }

  return appliedCount;
}

/**
 * Copy the bundled .cube LUTs into an arbitrary destination folder (by native path),
 * creating it if missing. Used by Footage Review to drop LUTs right next to the project
 * so they can be added manually (drag onto an adjustment layer / Lumetri Input LUT) —
 * the UXP API can't create an adjustment layer or set a LUT, so this is the reliable path.
 *
 * @param {string} destNativePath - absolute folder path (e.g. /Volumes/.../Proj/LUT)
 * @param {Object} logger
 * @returns {string[]} names of copied .cube files
 */
// Resolve a folder entry from a native path, trying multiple URL forms — different UXP
// builds accept raw paths vs encoded ones. Raw first (matches the rest of the panel).
async function lutResolveFolder(fs, nativePath) {
  var p = String(nativePath);
  var forms = [
    'file://' + p,
    'file://' + encodeURI(p),
    'file://' + p.split('/').map(function (s) { return encodeURIComponent(s); }).join('/')
  ];
  var lastErr = null;
  for (var i = 0; i < forms.length; i++) {
    try { return await fs.getEntryWithUrl(forms[i]); } catch (e) { lastErr = e; }
  }
  throw lastErr || new Error('cannot resolve folder: ' + p);
}

/**
 * Copy the bundled .cube LUTs into baseNativePath + subParts (created if missing).
 * @param {string} baseNativePath - absolute folder (e.g. the project folder)
 * @param {string[]} subParts - nested subfolders to ensure, e.g. ['01_Source','LUT']
 * @param {Object} logger
 * @returns {{ folder: string|null, files: string[] }}
 */
async function copyLutsToFolder(baseNativePath, subParts, logger) {
  const uxp = require('uxp');
  const fs = uxp.storage.localFileSystem;

  let lutsSource = DEFAULT_LUTS_SOURCE;
  if (!lutsSource) {
    try {
      const pf = await fs.getPluginFolder();
      lutsSource = pf.nativePath + '/LUTs';
    } catch (e) { lutsSource = './LUTs'; }
  }

  const srcFolder = await lutResolveFolder(fs, lutsSource);
  const cubes = (await srcFolder.getEntries()).filter(e => e.name.endsWith('.cube'));
  if (cubes.length === 0) { if (logger) logger.warn('No .cube files in ' + lutsSource); return { folder: null, files: [] }; }

  // Resolve base, then ensure each nested subfolder (getEntry or createFolder).
  let dest = await lutResolveFolder(fs, baseNativePath);
  for (const part of (subParts || [])) {
    try { dest = await dest.getEntry(part); }
    catch (e) { dest = await dest.createFolder(part); }
  }

  const copied = [];
  for (const c of cubes) {
    try { await c.copyTo(dest, { overwrite: true }); copied.push(c.name); }
    catch (e) { if (logger) logger.warn('LUT copy ' + c.name + ': ' + e.message); }
  }
  const folder = dest.nativePath || (baseNativePath + '/' + (subParts || []).join('/'));
  if (logger && copied.length) logger.info('LUTs → ' + folder + ': ' + copied.join(', '));
  return { folder: folder, files: copied };
}

module.exports = { copyLutsToCreativeFolder, applyLumetriToClips, copyLutsToFolder };
