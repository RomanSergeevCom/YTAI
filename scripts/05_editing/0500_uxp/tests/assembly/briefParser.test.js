const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { parseBrief, parseTimecode, formatTimecode, buildBlocks, fixAdjacentColors } = require('../../src/assembly/briefParser');
const { MARKER_COLOR_INDEX } = require('../../src/shared/constants');

const FIXTURE_PATH = path.join(__dirname, '..', 'fixtures', 'sample_brief.json');
const sampleJSON = fs.readFileSync(FIXTURE_PATH, 'utf8');

// --- parseTimecode ---

describe('parseTimecode', () => {
  it('parses MM:SS.s format', () => {
    assert.equal(parseTimecode('01:28.8'), 88.8);
  });

  it('parses MM:SS.s with zero minutes', () => {
    assert.equal(parseTimecode('00:01.5'), 1.5);
  });

  it('parses HH:MM:SS.s format', () => {
    assert.equal(parseTimecode('01:02:30.5'), 3750.5);
  });

  it('returns number if already a number', () => {
    assert.equal(parseTimecode(42.5), 42.5);
  });

  it('returns 0 for null/empty', () => {
    assert.equal(parseTimecode(null), 0);
    assert.equal(parseTimecode(''), 0);
    assert.equal(parseTimecode(undefined), 0);
  });

  it('handles comma as decimal separator', () => {
    assert.equal(parseTimecode('01:28,8'), 88.8);
  });
});

// --- formatTimecode ---

describe('formatTimecode', () => {
  it('formats seconds to MM:SS.s', () => {
    const result = formatTimecode(88.8);
    assert.ok(result.startsWith('01:'));
    assert.ok(result.includes('28'));
  });

  it('returns 00:00.0 for zero', () => {
    assert.equal(formatTimecode(0), '00:00.0');
  });

  it('returns 00:00.0 for negative', () => {
    assert.equal(formatTimecode(-5), '00:00.0');
  });
});

// --- parseBrief (Format A: segments[]) ---

describe('parseBrief — Format A (segments array)', () => {
  it('parses valid brief JSON', () => {
    const result = parseBrief(sampleJSON);
    assert.ok(result);
    assert.ok(result.segments);
    assert.ok(result.blocks);
    assert.ok(result.projectName);
  });

  it('returns correct number of segments', () => {
    const result = parseBrief(sampleJSON);
    assert.equal(result.segments.length, 6);
  });

  it('returns project name from project section', () => {
    const result = parseBrief(sampleJSON);
    assert.equal(result.projectName, 'YTCG37_Setup_UAE_Company_Remotely');
  });

  it('returns producerSpeaker from project.producer_speaker', () => {
    // Add producer_speaker to the fixture
    const json = JSON.parse(sampleJSON);
    json.project.producer_speaker = 'Speaker 2';
    const result = parseBrief(JSON.stringify(json));
    assert.equal(result.producerSpeaker, 'Speaker 2');
  });

  it('returns empty producerSpeaker when not set', () => {
    const result = parseBrief(sampleJSON);
    assert.equal(result.producerSpeaker, '');
  });

  it('returns project settings', () => {
    const result = parseBrief(sampleJSON);
    assert.equal(result.projectSettings.fps, 25);
    assert.equal(result.projectSettings.width, 3840);
    assert.equal(result.projectSettings.height, 2160);
  });

  it('returns transcription dir', () => {
    const result = parseBrief(sampleJSON);
    assert.equal(result.transcriptionDir, 'Transcription');
  });

  it('normalizes segment fields correctly', () => {
    const result = parseBrief(sampleJSON);
    const seg = result.segments[0];

    assert.equal(seg.id, 'seg_001');
    assert.equal(seg.sourceFile, 'RYA-FX3-0100.MP4');
    assert.equal(seg.inSec, 0);
    assert.equal(seg.block, 1);
    assert.equal(seg.blockName, 'Hook');
    assert.equal(seg.color, 'Green');
    assert.equal(seg.use, true);
    assert.equal(seg.isChapter, true);
    assert.equal(seg.speaker, 'Speaker 1');
  });

  it('parses use="FALSE" as boolean false', () => {
    const result = parseBrief(sampleJSON);
    const seg = result.segments[1]; // seg_002 has use=FALSE
    assert.equal(seg.use, false);
  });

  it('computes duration from tc_in/tc_out', () => {
    const result = parseBrief(sampleJSON);
    const seg = result.segments[0]; // 00:00.0 — 01:11.6
    assert.ok(seg.duration > 70 && seg.duration < 72);
  });

  it('handles block 99 (cut) segments', () => {
    const result = parseBrief(sampleJSON);
    const cutSeg = result.segments.find(s => s.block === 99);
    assert.ok(cutSeg);
    assert.equal(cutSeg.use, false);
    assert.equal(cutSeg.color, 'Red');
    assert.equal(cutSeg.priority, 9);
  });
});

// --- buildBlocks ---

describe('buildBlocks', () => {
  it('groups segments into blocks', () => {
    const result = parseBrief(sampleJSON);
    assert.ok(result.blocks.length > 0);
  });

  it('blocks are sorted by block number', () => {
    const result = parseBrief(sampleJSON);
    for (let i = 1; i < result.blocks.length; i++) {
      assert.ok(result.blocks[i].id >= result.blocks[i - 1].id);
    }
  });

  it('block 99 (cut) is last', () => {
    const result = parseBrief(sampleJSON);
    const lastBlock = result.blocks[result.blocks.length - 1];
    assert.equal(lastBlock.id, 99);
  });

  it('computes used segment count per block', () => {
    const result = parseBrief(sampleJSON);
    const hookBlock = result.blocks.find(b => b.id === 1);
    assert.ok(hookBlock);
    // Block 1 (Hook): seg_001 (use=TRUE), seg_002 (use=FALSE)
    assert.equal(hookBlock.usedCount, 1);
    assert.equal(hookBlock.segments.length, 2);
  });

  it('computes total and used duration per block', () => {
    const result = parseBrief(sampleJSON);
    const hookBlock = result.blocks.find(b => b.id === 1);
    assert.ok(hookBlock.totalDuration > 0);
    assert.ok(hookBlock.usedDuration > 0);
    assert.ok(hookBlock.usedDuration <= hookBlock.totalDuration);
  });
});

// --- Error handling ---

describe('parseBrief — errors', () => {
  it('throws on invalid JSON', () => {
    assert.throws(() => parseBrief('not json'), /JSON/);
  });

  it('throws on unknown format', () => {
    assert.throws(() => parseBrief('{"foo": "bar"}'), /Unknown brief format/);
  });

  it('throws on empty segments array', () => {
    // Should not throw — just returns empty blocks
    const result = parseBrief('{"segments": [], "project": {"project_name": "Test"}}');
    assert.equal(result.segments.length, 0);
    assert.equal(result.blocks.length, 0);
  });
});

// --- Format B (clips array) ---

describe('parseBrief — Format B (clips array)', () => {
  it('parses clips-based format', () => {
    const formatB = {
      project: 'TestProject',
      clips: [{
        filename: 'RYA-FX3-0099.MP4',
        clip_id: 'RYA-FX3-0099',
        segments: [{
          start: 0,
          end: 30,
          speaker: 'Host',
          text: 'Hello world',
          block: 1,
          block_name: 'Intro',
          use: true
        }]
      }]
    };

    const result = parseBrief(JSON.stringify(formatB));
    assert.equal(result.projectName, 'TestProject');
    assert.equal(result.segments.length, 1);
    assert.equal(result.segments[0].sourceFile, 'RYA-FX3-0099.MP4');
    assert.equal(result.segments[0].speaker, 'Host');
    assert.equal(result.segments[0].inSec, 0);
    assert.equal(result.segments[0].outSec, 30);
  });
});

// --- fixAdjacentColors ---

describe('fixAdjacentColors', () => {
  it('swaps second block when adjacent blocks have same marker index (Purple+Magenta)', () => {
    var blocks = [
      { id: 1, color: 'Purple', segments: [{ color: 'Purple' }] },
      { id: 2, color: 'Magenta', segments: [{ color: 'Magenta' }] }
    ];
    fixAdjacentColors(blocks);
    // Second block should no longer share marker index 2
    assert.notEqual(MARKER_COLOR_INDEX[blocks[1].color], MARKER_COLOR_INDEX[blocks[0].color]);
    // Color propagated to segments
    assert.equal(blocks[1].segments[0].color, blocks[1].color);
  });

  it('does not change non-colliding adjacent blocks', () => {
    var blocks = [
      { id: 1, color: 'Green', segments: [{ color: 'Green' }] },
      { id: 2, color: 'Blue', segments: [{ color: 'Blue' }] }
    ];
    fixAdjacentColors(blocks);
    assert.equal(blocks[0].color, 'Green');
    assert.equal(blocks[1].color, 'Blue');
  });

  it('avoids right neighbor marker index when selecting replacement', () => {
    var blocks = [
      { id: 1, color: 'Purple', segments: [{ color: 'Purple' }] },
      { id: 2, color: 'Magenta', segments: [{ color: 'Magenta' }] },
      { id: 3, color: 'Green', segments: [{ color: 'Green' }] }
    ];
    fixAdjacentColors(blocks);
    // Block 2 should avoid both Purple's marker index (2) and Green's (0)
    assert.notEqual(MARKER_COLOR_INDEX[blocks[1].color], MARKER_COLOR_INDEX['Purple']);
    assert.notEqual(MARKER_COLOR_INDEX[blocks[1].color], MARKER_COLOR_INDEX['Green']);
  });

  it('handles single block without error', () => {
    var blocks = [{ id: 1, color: 'Purple', segments: [] }];
    fixAdjacentColors(blocks);
    assert.equal(blocks[0].color, 'Purple');
  });

  it('handles empty array without error', () => {
    fixAdjacentColors([]);
  });

  it('replaces Orange block with valid block color', () => {
    var blocks = [
      { id: 1, color: 'Green', segments: [{ color: 'Green' }] },
      { id: 2, color: 'Orange', segments: [{ color: 'Orange' }, { color: 'Orange' }] }
    ];
    fixAdjacentColors(blocks);
    assert.notEqual(blocks[1].color, 'Orange', 'Orange should be replaced');
    // Propagated to all segments
    assert.equal(blocks[1].segments[0].color, blocks[1].color);
    assert.equal(blocks[1].segments[1].color, blocks[1].color);
  });

  it('replaces Orange avoiding neighbor marker indices', () => {
    var blocks = [
      { id: 1, color: 'Green', segments: [{ color: 'Green' }] },
      { id: 2, color: 'Orange', segments: [{ color: 'Orange' }] },
      { id: 3, color: 'Blue', segments: [{ color: 'Blue' }] }
    ];
    fixAdjacentColors(blocks);
    assert.notEqual(blocks[1].color, 'Orange', 'Orange should be replaced');
    assert.notEqual(MARKER_COLOR_INDEX[blocks[1].color], MARKER_COLOR_INDEX['Green'], 'Should avoid left neighbor');
    assert.notEqual(MARKER_COLOR_INDEX[blocks[1].color], MARKER_COLOR_INDEX['Blue'], 'Should avoid right neighbor');
  });
});
