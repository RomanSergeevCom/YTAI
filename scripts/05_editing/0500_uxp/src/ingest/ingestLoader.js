/**
 * Parse and analyze ingest JSON files.
 *
 * Ingest JSON contract:
 * {
 *   "version": "1.0",
 *   "type": "ingest",
 *   "project_name": "Interview",
 *   "created_at": "2026-03-08T12:00:00Z",
 *   "media": { "width": 3840, "height": 2160, "fps": 25.0, "sample_rate": 48000 },
 *   "clips": [
 *     {
 *       "clip_id": "C5402",
 *       "filename": "C5402.MP4",
 *       "path": "/abs/Interview/C5402.MP4",
 *       "duration": 156.0,
 *       "offset": 0.0,
 *       "premiere_transcript": "/abs/.../C5402_premiere_transcript.json"
 *     }
 *   ],
 *   "files": {
 *     "transcript_json": "/abs/.../Interview_transcript.json",
 *     "transcript_srt": "/abs/.../Interview_transcript.srt",
 *     "transcript_xlsx": "/abs/Interview_transcript.xlsx"
 *   },
 *   "source_folder": "/abs/Interview"
 * }
 */

/**
 * Parse an ingest JSON string into a structured object.
 * Validates required fields.
 * @param {string} jsonString - Raw JSON string
 * @returns {Object} Parsed ingest object
 */
function parseIngest(jsonString) {
  let data;
  try {
    data = JSON.parse(jsonString);
  } catch (e) {
    throw new Error(`Failed to parse ingest JSON: ${e.message}`);
  }

  // Validate required top-level fields
  if (!data.project_name || typeof data.project_name !== 'string') {
    throw new Error('Invalid ingest JSON: missing "project_name"');
  }

  if (!data.clips || !Array.isArray(data.clips)) {
    throw new Error('Invalid ingest JSON: missing "clips" array');
  }

  if (!data.media || typeof data.media !== 'object') {
    throw new Error('Invalid ingest JSON: missing "media" object');
  }

  if (!data.files || typeof data.files !== 'object') {
    throw new Error('Invalid ingest JSON: missing "files" object');
  }

  // Validate each clip has required fields
  for (let i = 0; i < data.clips.length; i++) {
    const clip = data.clips[i];
    if (!clip.clip_id) {
      throw new Error(`Invalid ingest JSON: clip[${i}] missing "clip_id"`);
    }
    if (!clip.filename) {
      throw new Error(`Invalid ingest JSON: clip[${i}] missing "filename"`);
    }
    if (!clip.path) {
      throw new Error(`Invalid ingest JSON: clip[${i}] missing "path"`);
    }
    if (typeof clip.duration !== 'number') {
      throw new Error(`Invalid ingest JSON: clip[${i}] missing or invalid "duration"`);
    }
  }

  return data;
}

/**
 * Get unique source file paths from all clips.
 * Returns absolute paths from clip.path.
 * @param {Object} ingest - Parsed ingest object
 * @returns {string[]} Array of absolute file paths
 */
function getUniqueSourceFiles(ingest) {
  const files = new Set();
  for (const clip of ingest.clips) {
    if (clip.path) files.add(clip.path);
  }
  return [...files];
}

/**
 * Generate a human-readable summary of the ingest data.
 * @param {Object} ingest - Parsed ingest object
 * @returns {string} Summary text
 */
function generateSummary(ingest) {
  const totalDuration = ingest.clips.reduce((sum, c) => sum + (c.duration || 0), 0);
  const durationMin = Math.floor(totalDuration / 60);
  const durationSec = Math.round(totalDuration % 60);

  const transcriptCount = ingest.clips.filter(c => c.premiere_transcript).length;

  const lines = [
    `Project: ${ingest.project_name}`,
    `Resolution: ${ingest.media.width}x${ingest.media.height} @ ${ingest.media.fps}fps`,
    `Clips: ${ingest.clips.length}`,
    `Total duration: ${durationMin}m ${durationSec}s`,
    `Premiere transcripts: ${transcriptCount}/${ingest.clips.length}`,
    `SRT: ${ingest.files.transcript_srt ? 'yes' : 'no'}`,
    `Source: ${ingest.source_folder || 'N/A'}`
  ];

  return lines.join('\n');
}

module.exports = {
  parseIngest,
  getUniqueSourceFiles,
  generateSummary
};
