const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { versionTimestamp } = require('../../src/shared/archiver');

// Only test pure functions — UXP-dependent functions (archiveFiles, saveVersion, etc.)
// require the UXP runtime and are tested via manual integration testing in Premiere.

describe('archiver versionTimestamp', () => {
  it('returns string in YYYY-MM-DD_HHMM format', () => {
    var ts = versionTimestamp();
    assert.ok(/^\d{4}-\d{2}-\d{2}_\d{4}$/.test(ts), 'Should match YYYY-MM-DD_HHMM pattern: ' + ts);
  });

  it('uses current date', () => {
    var ts = versionTimestamp();
    var now = new Date();
    var year = String(now.getFullYear());
    assert.ok(ts.startsWith(year), 'Should start with current year');
  });

  it('pads month and day with zeros', () => {
    var ts = versionTimestamp();
    // Format: YYYY-MM-DD_HHMM — month and day are 2 chars
    var parts = ts.split('-');
    assert.equal(parts[1].length, 2, 'Month should be 2 digits');
    assert.equal(parts[2].split('_')[0].length, 2, 'Day should be 2 digits');
  });

  it('pads hours and minutes with zeros', () => {
    var ts = versionTimestamp();
    var timePart = ts.split('_')[1];
    assert.equal(timePart.length, 4, 'Time part should be 4 digits (HHMM)');
  });
});
