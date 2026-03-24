/**
 * frameSnap.js — Snap timecodes to frame boundaries.
 *
 * Prevents 1-frame gaps between clips by ensuring all tc_in/tc_out
 * and timeline positions align to exact frame boundaries.
 *
 * Supports any framerate: 25fps, 29.97fps, 23.976fps, 50fps, etc.
 */

/**
 * Snap seconds to nearest frame boundary.
 *
 * @param {number} seconds - Time in seconds (float)
 * @param {number} fps - Framerate (e.g. 25, 29.97, 23.976)
 * @param {string} [mode='round'] - 'floor' (tc_in), 'ceil' (tc_out), 'round' (position)
 * @returns {number} Frame-aligned time in seconds
 */
function snapToFrame(seconds, fps, mode) {
  if (!fps || fps <= 0) fps = 25;
  var frameDuration = 1.0 / fps;
  var frameIndex;

  if (mode === 'floor') {
    frameIndex = Math.floor(seconds / frameDuration);
  } else if (mode === 'ceil') {
    frameIndex = Math.ceil(seconds / frameDuration - 1e-9); // epsilon to avoid rounding exact values up
  } else {
    frameIndex = Math.round(seconds / frameDuration);
  }

  return frameIndex * frameDuration;
}

/**
 * Get fps from brief project settings or fallback.
 *
 * @param {Object} projectSettings - brief.project object
 * @param {number} [fallback=25] - Default fps if not found
 * @returns {number} fps value
 */
function getFps(projectSettings, fallback) {
  if (!fallback) fallback = 25;
  if (!projectSettings) return fallback;
  var fps = projectSettings.fps || fallback;
  return (typeof fps === 'number' && fps > 0) ? fps : fallback;
}

module.exports = { snapToFrame, getFps };
