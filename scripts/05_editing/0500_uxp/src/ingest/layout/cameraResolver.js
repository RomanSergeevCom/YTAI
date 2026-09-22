/**
 * Camera resolver — derive per-scene cam → V-track index mapping.
 *
 * Pure module: no UXP imports, unit-testable under Node.
 *
 * Priority order matches Python pipeline (0111_inject_multicam_pairs.py:34-42).
 * Used by sceneLayout.js and wallClockBuilder.js.
 */

/**
 * Priority order for camera auto-detection. Earlier = lower V-track index.
 * Cameras not in this list fall to the end (alphabetical).
 *
 * Aligned with Python 0111_inject_multicam_pairs.py PRIMARY_CAM mapping —
 * FX3 wins for outdoor/walking scenes, DJI wins for indoor/static, FX3A is
 * primary for single-cam scenes and secondary otherwise.
 */
const CAM_PRIORITY = [
  'FX3',
  'DJI',
  'FX3A',
  'iPhone',
  'screen_recording',
];

/**
 * Extract camera name from a clip's path. Looks at parent folder basename.
 *
 * Path examples:
 *   /Volumes/.../01_Source/Video/03_developer_meeting/DJI/file.MP4  → "DJI"
 *   /a/b/04_with_wife/iPhone/IMG_2868.MOV                            → "iPhone"
 *
 * @param {string} clipPath
 * @returns {string} camera name (parent folder)
 */
function camFromPath(clipPath) {
  if (!clipPath) return '';
  // Normalize separators, strip trailing slash, take second-to-last component
  const parts = String(clipPath).replace(/\\/g, '/').replace(/\/+$/, '').split('/');
  return parts.length >= 2 ? parts[parts.length - 2] : '';
}

/**
 * Camera of a clip. Prefers the explicit `cam` field in ingest, falls back to the
 * parent-folder heuristic for legacy projects.
 *
 * Why explicit wins: со сцен снята папочная вложенность (правило «имя папки = имя
 * таймлайна»), поэтому родитель клипа — это имя СЦЕНЫ, а не камеры. Без явного поля
 * камера не резолвится и клип молча выпадает из секвенции (unknown_cam).
 *
 * @param {Object} clip - clip record ({cam?, path})
 * @returns {string} camera name
 */
function camOfClip(clip) {
  if (!clip) return '';
  if (clip.cam) return String(clip.cam);
  return camFromPath(clip.path);
}

/**
 * Derive cam → V-track index mapping for a scene.
 *
 * Logic:
 *   1. If `override` is provided (array of camera names in V1..VN order), use it directly.
 *   2. Otherwise auto-detect: group clips by parent folder name, sort by CAM_PRIORITY
 *      (with unknown cams alphabetically at the end), map to vIdx 0, 1, 2, ...
 *
 * @param {Array<Object>} sceneClips - clips of one scene (each has `path`)
 * @param {Array<string>|null} override - optional explicit cam order
 * @returns {Object} map { camName: vIdx }  — vIdx is 0-based (0=V1, 1=V2, ...)
 */
function deriveCamLayers(sceneClips, override = null) {
  if (override && Array.isArray(override) && override.length > 0) {
    const result = {};
    override.forEach((cam, i) => { result[cam] = i; });
    return result;
  }

  // Auto-detect from clip paths
  const camCounts = {};
  for (const clip of sceneClips || []) {
    const cam = camOfClip(clip);
    if (!cam) continue;
    camCounts[cam] = (camCounts[cam] || 0) + 1;
  }

  // Sort cameras: known cams by CAM_PRIORITY order, unknown cams alphabetically at end
  const knownOrdered = CAM_PRIORITY.filter(cam => cam in camCounts);
  const unknownSorted = Object.keys(camCounts)
    .filter(cam => !CAM_PRIORITY.includes(cam))
    .sort();

  const ordered = [...knownOrdered, ...unknownSorted];
  const result = {};
  ordered.forEach((cam, i) => { result[cam] = i; });
  return result;
}

/**
 * Inverse map: vIdx → camName. Convenience for diagnostics.
 *
 * @param {Object} camLayers - { camName: vIdx }
 * @returns {Object} { vIdx: camName }
 */
function invertCamLayers(camLayers) {
  const result = {};
  for (const [cam, vIdx] of Object.entries(camLayers)) {
    result[vIdx] = cam;
  }
  return result;
}

module.exports = {
  CAM_PRIORITY,
  camFromPath,
  camOfClip,
  deriveCamLayers,
  invertCamLayers,
};
