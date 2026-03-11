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
  ppro = require('../tests/mocks/premierepro');
}

const DEFAULT_LUTS_SOURCE = '/Users/romansergeev/YTAI/scripts/02_transcribe/LUTs';
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

  const lutsSource = (ingest && ingest.luts_folder) || DEFAULT_LUTS_SOURCE;
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
      if (displayNames[i] === 'Lumetri Color' || displayNames[i].toLowerCase().includes('lumetri')) {
        lumetriMatchName = matchNames[i];
        logger.info(`Found Lumetri Color: matchName="${lumetriMatchName}", display="${displayNames[i]}"`);
        break;
      }
    }

    if (!lumetriMatchName) {
      logger.warn(`Lumetri Color effect not found in VideoFilterFactory`);
      logger.debug(`All display names: ${displayNames.join(', ')}`);
      return 0;
    }

    // Step 2: Get V1 track items
    const v1Track = await sequence.getVideoTrack(0);
    const trackItems = await v1Track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
    logger.info(`Applying Lumetri Color to ${trackItems.length} V1 clip(s)`);

    // Step 3: Apply to each clip
    for (let i = 0; i < trackItems.length; i++) {
      const ti = trackItems[i];
      const name = await ti.getName();

      try {
        // Cast to VideoClipTrackItem for component chain access
        const videoClip = ppro.VideoClipTrackItem.cast(ti);
        if (!videoClip) {
          logger.warn(`Cannot cast "${name}" to VideoClipTrackItem`);
          continue;
        }

        // Create Lumetri component (async in UXP)
        const lumetriComponent = await ppro.VideoFilterFactory.createComponent(lumetriMatchName);
        if (!lumetriComponent) {
          logger.warn(`Failed to create Lumetri component for "${name}"`);
          continue;
        }

        // Get component chain and append
        const chain = await videoClip.getComponentChain();
        project.lockedAccess(() => {
          project.executeTransaction((compoundAction) => {
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
            const components = await updatedChain.getComponents();
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

module.exports = { copyLutsToCreativeFolder, applyLumetriToClips };
