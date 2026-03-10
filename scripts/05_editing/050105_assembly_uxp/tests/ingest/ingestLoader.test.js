const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { parseIngest, getUniqueSourceFiles, generateSummary } = require('../../src/ingest/ingestLoader');

const FIXTURE_PATH = path.join(__dirname, '..', 'fixtures', 'sample_ingest.json');
const sampleJSON = JSON.parse(fs.readFileSync(FIXTURE_PATH, 'utf8'));

describe('parseIngest', () => {
  it('parses valid JSON and returns ingest object', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    assert.ok(ingest);
    assert.ok(ingest.project_name);
    assert.ok(ingest.clips);
    assert.ok(ingest.media);
    assert.ok(ingest.files);
  });

  it('returns correct number of clips', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    assert.equal(ingest.clips.length, 3);
  });

  it('preserves clip fields', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    const clip = ingest.clips[0];
    assert.equal(clip.clip_id, 'C5402');
    assert.equal(clip.filename, 'C5402.MP4');
    assert.equal(clip.path, '/abs/Interview/C5402.MP4');
    assert.equal(clip.duration, 156.0);
    assert.equal(clip.offset, 0.0);
  });

  it('preserves media settings', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    assert.equal(ingest.media.width, 3840);
    assert.equal(ingest.media.height, 2160);
    assert.equal(ingest.media.fps, 25.0);
    assert.equal(ingest.media.sample_rate, 48000);
  });

  it('preserves file paths', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    assert.ok(ingest.files.transcript_json.includes('Interview_transcript.json'));
    assert.ok(ingest.files.transcript_srt.includes('Interview_transcript.srt'));
    assert.ok(ingest.files.transcript_xlsx.includes('Interview_transcript.xlsx'));
  });

  it('preserves premiere_transcript paths per clip', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    for (const clip of ingest.clips) {
      assert.ok(clip.premiere_transcript);
      assert.ok(clip.premiere_transcript.includes('premiere_transcript.json'));
    }
  });

  it('throws on invalid JSON', () => {
    assert.throws(() => parseIngest('not json'), /Failed to parse/);
  });

  it('throws when project_name is missing', () => {
    const data = { ...sampleJSON };
    delete data.project_name;
    assert.throws(() => parseIngest(JSON.stringify(data)), /missing "project_name"/);
  });

  it('throws when clips array is missing', () => {
    const data = { ...sampleJSON };
    delete data.clips;
    assert.throws(() => parseIngest(JSON.stringify(data)), /missing "clips"/);
  });

  it('throws when media object is missing', () => {
    const data = { ...sampleJSON };
    delete data.media;
    assert.throws(() => parseIngest(JSON.stringify(data)), /missing "media"/);
  });

  it('throws when files object is missing', () => {
    const data = { ...sampleJSON };
    delete data.files;
    assert.throws(() => parseIngest(JSON.stringify(data)), /missing "files"/);
  });

  it('throws when a clip is missing clip_id', () => {
    const data = JSON.parse(JSON.stringify(sampleJSON));
    delete data.clips[0].clip_id;
    assert.throws(() => parseIngest(JSON.stringify(data)), /clip\[0\] missing "clip_id"/);
  });

  it('throws when a clip is missing filename', () => {
    const data = JSON.parse(JSON.stringify(sampleJSON));
    delete data.clips[1].filename;
    assert.throws(() => parseIngest(JSON.stringify(data)), /clip\[1\] missing "filename"/);
  });

  it('throws when a clip has invalid duration', () => {
    const data = JSON.parse(JSON.stringify(sampleJSON));
    data.clips[0].duration = 'not a number';
    assert.throws(() => parseIngest(JSON.stringify(data)), /clip\[0\] missing or invalid "duration"/);
  });
});

describe('getUniqueSourceFiles', () => {
  it('returns all unique source file paths', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    const files = getUniqueSourceFiles(ingest);

    assert.equal(files.length, 3);
    assert.ok(files.includes('/abs/Interview/C5402.MP4'));
    assert.ok(files.includes('/abs/Interview/C5403.MP4'));
    assert.ok(files.includes('/abs/Interview/C5404.MP4'));
  });

  it('deduplicates source file paths', () => {
    const data = JSON.parse(JSON.stringify(sampleJSON));
    data.clips.push({
      clip_id: 'C5402_dup',
      filename: 'C5402.MP4',
      path: '/abs/Interview/C5402.MP4',
      duration: 50.0,
      offset: 0
    });
    const ingest = parseIngest(JSON.stringify(data));
    const files = getUniqueSourceFiles(ingest);
    assert.equal(files.length, 3);
  });
});

describe('generateSummary', () => {
  it('returns a non-empty summary string', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    const summary = generateSummary(ingest);
    assert.ok(typeof summary === 'string');
    assert.ok(summary.length > 0);
  });

  it('includes project name', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    const summary = generateSummary(ingest);
    assert.ok(summary.includes('Interview'));
  });

  it('includes resolution info', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    const summary = generateSummary(ingest);
    assert.ok(summary.includes('3840'));
    assert.ok(summary.includes('2160'));
  });

  it('includes SRT status', () => {
    const ingest = parseIngest(JSON.stringify(sampleJSON));
    const summary = generateSummary(ingest);
    assert.ok(summary.includes('SRT: yes'));
  });
});
