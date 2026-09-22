/**
 * Media settings helpers — apply ingest.media config to a Premiere sequence,
 * read sequence settings for validation.
 *
 * Extracted from src/ingest/timelineBuilder.js (Phase 1.2 of wall-clock refactor).
 * Used by both legacy linearBuilder and new wallClockBuilder.
 */

let ppro;
try {
  ppro = require('premierepro');
} catch (e) {
  ppro = require('../../tests/mocks/premierepro');
}

/**
 * Default sequence settings.
 * Used as fallback when createSequenceFromMedia fails.
 */
const SEQUENCE_DEFAULTS = {
  width: 3840,
  height: 2160,
  fps: 25,
  audioSampleRate: 48000,
  // System preset for UHD 4K 25fps (Mac path)
  presetPath: '/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app/Contents/Settings/SequencePresets/UHD (4K)/UHD (4K) 2160p 25 fps.sqpreset'
};

/**
 * Apply media settings to a sequence from ingest JSON data.
 * Used when createSequenceFromMedia is not available (clip not found),
 * and always when creating empty sequence in wall-clock mode.
 *
 * @param {Object} project - Premiere project
 * @param {Object} sequence - Sequence to modify
 * @param {Object} media - { width, height, fps, sample_rate }
 * @param {Object} logger - Logger
 */
async function applyMediaSettings(project, sequence, media, logger) {
  try {
    const settings = await sequence.getSettings();

    // Frame size — the real UXP DOM API is setVideoFrameRect(RectF), NOT
    // setVideoFrameSize(w,h) (which does not exist and threw in live Premiere).
    // Mutate the existing RectF in place (preserves its real type) and set both
    // edge- and width/height-style fields for robustness across the mock + real PP.
    try {
      let rect = null;
      try { rect = await settings.getVideoFrameRect(); } catch (e) { rect = null; }
      if (!rect || typeof rect !== 'object') rect = {};
      rect.left = 0; rect.top = 0;
      rect.right = media.width; rect.bottom = media.height;
      rect.width = media.width; rect.height = media.height;
      if (typeof settings.setVideoFrameRect === 'function') {
        await settings.setVideoFrameRect(rect);
      } else {
        logger.debug('setVideoFrameRect not available on settings');
      }
    } catch (e) {
      logger.debug(`setVideoFrameRect failed: ${e.message}`);
    }

    // Frame rate (independent try so a frame-size failure can't block it)
    try {
      const frameRate = ppro.FrameRate.createWithValue(media.fps);
      await settings.setVideoFrameRate(frameRate);
    } catch (e) {
      logger.debug(`setVideoFrameRate failed: ${e.message}`);
    }

    // Pixel aspect ratio (square)
    try {
      await settings.setVideoPixelAspectRatio(
        ppro.Constants.PixelAspectRatio.SQUARE.toString()
      );
    } catch (e) {
      logger.debug(`setVideoPixelAspectRatio not available: ${e.message}`);
    }

    // Fields (progressive)
    try {
      await settings.setVideoFieldType(ppro.Constants.FieldType.PROGRESSIVE);
    } catch (e) {
      logger.debug(`setVideoFieldType not available: ${e.message}`);
    }

    // Audio sample rate
    if (media.sample_rate) {
      try {
        const audioRate = ppro.FrameRate.createWithValue(media.sample_rate);
        await settings.setAudioSampleRate(audioRate);
      } catch (e) {
        logger.debug(`setAudioSampleRate not available: ${e.message}`);
      }
    }

    // Commit settings
    project.lockedAccess(() => {
      project.executeTransaction((compoundAction) => {
        const action = sequence.createSetSettingsAction(settings);
        compoundAction.addAction(action);
      }, 'Apply media settings');
    });

    logger.info(`Applied settings: ${media.width}x${media.height} @ ${media.fps}fps, audio ${media.sample_rate || 'default'}Hz`);
  } catch (e) {
    logger.warn(`Could not apply media settings: ${e.message}`);
  }
}

/**
 * Read and log sequence settings. Returns settings for validation.
 * Uses fallback chain for FPS since API methods vary across Premiere versions.
 *
 * @param {Object} sequence - Sequence to inspect
 * @param {Object} logger - Logger
 * @returns {{ width: number, height: number, fps: number, vTracks: number, aTracks: number }|null}
 */
async function logSequenceSettings(sequence, logger) {
  try {
    let width = 0, height = 0, fps = 0;

    // Resolution: sequence.getFrameSize() (discovered via API introspection)
    try {
      const frameSize = await sequence.getFrameSize();
      // UXP objects may not serialize — log individual properties
      logger.debug(`getFrameSize raw: JSON=${JSON.stringify(frameSize)}, .width=${frameSize.width}, .height=${frameSize.height}, .right=${frameSize.right}`);
      if (frameSize && frameSize.width !== undefined) {
        width = frameSize.width;
        height = frameSize.height;
      } else if (frameSize && frameSize.right !== undefined) {
        width = Math.round(frameSize.right - (frameSize.left || 0));
        height = Math.round(frameSize.bottom - (frameSize.top || 0));
      } else if (typeof frameSize === 'string') {
        const parts = frameSize.split(/[x,]/);
        if (parts.length >= 2) { width = parseInt(parts[0]); height = parseInt(parts[1]); }
      }
    } catch (e) {
      logger.debug(`getFrameSize failed: ${e.message}`);
      // Fallback: settings.getVideoFrameRect()
      try {
        const settings = await sequence.getSettings();
        const rect = await settings.getVideoFrameRect();
        logger.debug(`getVideoFrameRect raw: ${JSON.stringify(rect)}`);
        if (rect && rect.right !== undefined) {
          width = Math.round(rect.right - (rect.left || 0));
          height = Math.round(rect.bottom - (rect.top || 0));
        }
      } catch (e2) {
        logger.debug(`getVideoFrameRect also failed: ${e2.message}`);
      }
    }

    // FPS: sequence.getTimebase() (discovered via API introspection)
    try {
      const timebase = await sequence.getTimebase();
      logger.debug(`getTimebase raw: ${JSON.stringify(timebase)}, type=${typeof timebase}`);
      if (typeof timebase === 'string') {
        const tbNum = parseInt(timebase);
        if (tbNum > 1000) fps = Math.round(254016000000 / tbNum * 100) / 100;
        else fps = parseFloat(timebase);
      } else if (typeof timebase === 'number') {
        if (timebase > 1000) fps = Math.round(254016000000 / timebase * 100) / 100;
        else fps = timebase;
      } else if (timebase && timebase.value !== undefined) {
        fps = timebase.value;
      }
    } catch (e) {
      logger.debug(`getTimebase failed: ${e.message}`);
    }

    const vTracks = await sequence.getVideoTrackCount();
    const aTracks = await sequence.getAudioTrackCount();

    logger.info(`Sequence: ${width}x${height}${fps ? ` @ ${fps}fps` : ' (FPS unknown)'}, V=${vTracks} A=${aTracks} tracks`);
    return { width, height, fps, vTracks, aTracks };
  } catch (e) {
    logger.debug(`logSequenceSettings failed: ${e.message}`);
    return null;
  }
}

module.exports = {
  SEQUENCE_DEFAULTS,
  applyMediaSettings,
  logSequenceSettings,
};
