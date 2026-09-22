/**
 * TX resolver — validates tx_strips for wall-clock placement.
 *
 * Pure module. Run before sceneLayout.plan() consumes the strips.
 * Hard errors out on sample_rate mismatch (would cause silent time-stretch in Premiere).
 *
 * Public API:
 *   - validateTxStrip(tx, mediaSampleRate, opts) → { ok: bool, reason: string }
 *   - prepareTxStrips(txStrips, mediaSampleRate, opts) → { valid: [...], warnings: [...] }
 */

/**
 * Validate a single TX strip against media config.
 *
 * @param {Object} tx - { tx, filename, path, creation_time, duration, sample_rate, wall_offset? }
 * @param {number} mediaSampleRate - expected sample rate from ingest.media
 * @param {Object} [opts]  { strict?: boolean, sampleRateTolerance?: number }
 * @returns {{ ok: boolean, reason?: string }}
 */
function validateTxStrip(tx, mediaSampleRate, opts = {}) {
  if (!tx || typeof tx !== 'object') {
    return { ok: false, reason: 'tx is not an object' };
  }
  if (!tx.filename) return { ok: false, reason: 'missing filename' };
  if (!tx.path) return { ok: false, reason: 'missing path' };
  if (!tx.creation_time) return { ok: false, reason: 'missing creation_time' };
  if (typeof tx.duration !== 'number' || tx.duration <= 0) {
    return { ok: false, reason: `invalid duration: ${tx.duration}` };
  }

  // Sample rate check — Premiere silently time-stretches mismatched audio
  if (typeof tx.sample_rate === 'number' && typeof mediaSampleRate === 'number') {
    const tolerance = opts.sampleRateTolerance || 0;
    if (Math.abs(tx.sample_rate - mediaSampleRate) > tolerance) {
      return {
        ok: false,
        reason: `sample_rate mismatch: tx=${tx.sample_rate} vs media=${mediaSampleRate} (would cause silent time-stretch)`,
      };
    }
  } else if (opts.strict && typeof tx.sample_rate !== 'number') {
    return { ok: false, reason: 'missing sample_rate (required in strict mode)' };
  }

  return { ok: true };
}

/**
 * Filter TX strips through validation, return valid ones + warnings for invalid.
 *
 * @param {Array<Object>} txStrips
 * @param {number} mediaSampleRate
 * @param {Object} [opts]
 * @returns {{ valid: Array<Object>, warnings: Array<Object> }}
 */
function prepareTxStrips(txStrips, mediaSampleRate, opts = {}) {
  const valid = [];
  const warnings = [];

  if (!txStrips || !Array.isArray(txStrips)) {
    return { valid, warnings };
  }

  for (const tx of txStrips) {
    const result = validateTxStrip(tx, mediaSampleRate, opts);
    if (result.ok) {
      valid.push(tx);
    } else {
      warnings.push({
        type: 'tx_invalid',
        tx: tx?.tx || tx?.filename || '?',
        reason: result.reason,
      });
    }
  }

  return { valid, warnings };
}

module.exports = {
  validateTxStrip,
  prepareTxStrips,
};
