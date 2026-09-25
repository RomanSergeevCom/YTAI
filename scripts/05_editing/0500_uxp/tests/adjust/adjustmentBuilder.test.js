const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('../mocks/premierepro');
const {
  selectionBounds,
  ensureDonorAdjustment,
  addAdjustmentOverSelection,
  addAdjustmentOverRanges,
  setEffectParam,
  probeDonorClone,
  DONOR_NAMES,
  LUT_DONOR_SEQUENCE,
} = require('../../src/adjust/adjustmentBuilder');
const { Logger } = require('../../src/shared/logger');

/** Selection fixture via the real static (createEmptySelection callback form). */
function makeSelection(items) {
  let sel = null;
  ppro.TrackItemSelection.createEmptySelection(function (s) { sel = s; });
  for (const it of items) sel.addItem(it, true);
  return sel;
}

/** Clip on a given mock video track. */
function placeClip(seq, vIdx, name, startSec, durSec) {
  const track = seq._ensureVideoTrack(vIdx);
  const ti = new ppro._MockTrackItem(name, startSec, durSec);
  ti._track = track;
  track._items.push(ti);
  return ti;
}

function makeDonor(project, name) {
  const donor = new ppro._MockClipProjectItem(name || 'YTAI_ADJ');
  donor._durationSec = 3600; // long synthetic source, like a real Adj item
  project._rootItem._items.push(donor);
  return donor;
}

describe('selectionBounds', () => {
  let project, seq, logger;
  beforeEach(async () => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    seq = new ppro._MockSequence('Seq', { videoTracks: 2, audioTracks: 1 });
    await project.setActiveSequence(seq);
    logger = new Logger();
  });

  it('returns null when nothing is selected', async () => {
    seq.getSelection = async () => makeSelection([]);
    assert.equal(await selectionBounds(seq, logger), null);
  });

  it('computes min-start / max-end across the selection', async () => {
    const a = placeClip(seq, 0, 'A', 10, 2);
    const b = placeClip(seq, 0, 'B', 14, 3);
    seq.getSelection = async () => makeSelection([a, b]);
    const bounds = await selectionBounds(seq, logger);
    assert.equal(bounds.startSec, 10);
    assert.equal(bounds.endSec, 17);
    assert.equal(bounds.count, 2);
    assert.equal(bounds.topTrackIndex, 0);
  });

  it('reports the topmost video track holding a selected item', async () => {
    const a = placeClip(seq, 0, 'A', 5, 2);
    const b = placeClip(seq, 1, 'B', 6, 2);
    seq.getSelection = async () => makeSelection([a, b]);
    const bounds = await selectionBounds(seq, logger);
    assert.equal(bounds.topTrackIndex, 1);
  });
});

describe('ensureDonorAdjustment', () => {
  let project, logger;
  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    logger = new Logger();
  });

  it('finds the donor by any of the default names', async () => {
    makeDonor(project, DONOR_NAMES[1]); // plain "Adjustment Layer"
    const item = await ensureDonorAdjustment(project, {}, logger);
    assert.ok(item);
    assert.equal(item.name, 'Adjustment Layer');
  });

  it('imports the donor .prproj when the item is missing', async () => {
    project.importFiles = async function (paths) {
      ppro._recorder.record('Project.importFiles', [paths]);
      makeDonor(project, 'YTAI_ADJ'); // import materialises the item
      return true;
    };
    const item = await ensureDonorAdjustment(
      project, { donorPrproj: '/tpl/YTAI_ADJ_DONOR.prproj' }, logger);
    assert.ok(item);
    const calls = ppro._recorder.getCalls('Project.importFiles');
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args[0], ['/tpl/YTAI_ADJ_DONOR.prproj']);
  });

  it('returns null when no donor and no donorPrproj', async () => {
    assert.equal(await ensureDonorAdjustment(project, {}, logger), null);
  });
});

describe('addAdjustmentOverSelection', () => {
  let project, seq, logger;
  beforeEach(async () => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    seq = new ppro._MockSequence('Seq', { videoTracks: 2, audioTracks: 1 });
    await project.setActiveSequence(seq);
    logger = new Logger();
  });

  it('fails with no-sequence when no active sequence', async () => {
    await project.setActiveSequence(null);
    const r = await addAdjustmentOverSelection(project, {}, logger);
    assert.deepEqual(r, { ok: false, reason: 'no-sequence' });
  });

  it('fails with no-selection when nothing is selected', async () => {
    seq.getSelection = async () => makeSelection([]);
    const r = await addAdjustmentOverSelection(project, {}, logger);
    assert.deepEqual(r, { ok: false, reason: 'no-selection' });
  });

  it('fails with no-donor when the project has no ADJ item', async () => {
    const a = placeClip(seq, 0, 'A', 10, 2);
    seq.getSelection = async () => makeSelection([a]);
    const r = await addAdjustmentOverSelection(project, {}, logger);
    assert.deepEqual(r, { ok: false, reason: 'no-donor' });
  });

  it('places one trimmed layer over the selection, one track above the top clip', async () => {
    makeDonor(project, 'YTAI_ADJ');
    const a = placeClip(seq, 0, 'A', 10, 2);
    const b = placeClip(seq, 1, 'B', 14, 3.5);
    seq.getSelection = async () => makeSelection([a, b]);

    const r = await addAdjustmentOverSelection(project, {}, logger);
    assert.equal(r.ok, true);
    assert.equal(r.startSec, 10);
    assert.equal(r.endSec, 17.5);
    assert.equal(r.vIdx, 2); // above topmost selected (V2 → index 1)
    assert.equal(r.count, 2);

    // Donor source was trimmed to the range LENGTH, then cleared.
    const trims = ppro._recorder.getCalls('ClipProjectItem.createSetInOutPointsAction');
    assert.equal(trims.length >= 1, true);
    const lastTrim = trims[trims.length - 1];
    assert.equal(lastTrim.args[0].seconds, 0);
    assert.equal(Math.abs(lastTrim.args[1].seconds - 7.5) < 0.05, true);
    assert.equal(ppro._recorder.getCalls('ClipProjectItem.createClearInOutPointsAction').length >= 1, true);

    // Overwrite went to V3 (index 2) at the selection start, audio -1.
    const ows = ppro._recorder.getCalls('SequenceEditor.createOverwriteItemAction');
    const own = ows[ows.length - 1];
    assert.equal(own.args[1].seconds, 10);
    assert.equal(own.args[2], 2);
    assert.equal(own.args[3], -1);

    // The layer actually landed on the sequence.
    const v3 = seq._videoTracks[2];
    assert.ok(v3, 'V3 must exist (ensureTracks)');
    const placedItems = v3._items.filter((ti) => ti.name === 'YTAI_ADJ');
    assert.equal(placedItems.length, 1);
    assert.equal(placedItems[0]._startTimeSec, 10);
    assert.equal(Math.abs(placedItems[0]._durationSec - 7.5) < 0.05, true);
  });
});

describe('addAdjustmentOverRanges', () => {
  let project, seq, logger;
  beforeEach(async () => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    seq = new ppro._MockSequence('Seq', { videoTracks: 2, audioTracks: 1 });
    await project.setActiveSequence(seq);
    logger = new Logger();
  });

  it('places one layer per range on the requested track', async () => {
    makeDonor(project, 'YTAI_ADJ');
    const ranges = [
      { startSec: 0, endSec: 5 },
      { startSec: 10, endSec: 12.5 },
    ];
    const r = await addAdjustmentOverRanges(project, seq, ranges, { vIdx: 3 }, logger);
    assert.equal(r.ok, true);
    assert.equal(r.placed, 2);
    const v4 = seq._videoTracks[3];
    const placedItems = v4._items.filter((ti) => ti.name === 'YTAI_ADJ');
    assert.equal(placedItems.length, 2);
    assert.equal(placedItems[0]._startTimeSec, 0);
    assert.equal(placedItems[1]._startTimeSec, 10);
  });

  it('fails with no-donor on an empty project', async () => {
    const r = await addAdjustmentOverRanges(project, seq, [{ startSec: 0, endSec: 1 }], {}, logger);
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'no-donor');
  });
});

const { addAdjustmentPerClipFromPlan, collectVideoClipEntries } = require('../../src/adjust/adjustmentBuilder');

describe('addAdjustmentPerClipFromPlan', () => {
  let project, seq, logger;
  beforeEach(async () => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    seq = new ppro._MockSequence('YTCH13_90_CTA', { videoTracks: 1, audioTracks: 2 });
    await project.setActiveSequence(seq);
    logger = new Logger();
  });

  function placeClip2(vIdx, name, startSec, durSec) {
    const track = seq._ensureVideoTrack(vIdx);
    const ti = new ppro._MockTrackItem(name, startSec, durSec);
    ti._track = track;
    track._items.push(ti);
    return ti;
  }

  it('collects clips across video tracks with times', async () => {
    placeClip2(0, 'A.MP4', 0, 5);
    placeClip2(0, 'B.MP4', 5, 3);
    const items = await collectVideoClipEntries(seq, logger);
    assert.equal(items.length, 2);
    assert.equal(items[1].endSec, 8);
  });

  it('returns entries whose raw item is .trackItem — never an ambiguous .item', async () => {
    placeClip2(0, 'A.MP4', 0, 5);
    const [entry] = await collectVideoClipEntries(seq, logger);
    assert.deepEqual(Object.keys(entry).sort(), ['endSec', 'name', 'startSec', 'trackIdx', 'trackItem']);
    assert.equal(typeof entry.trackItem.getStartTime, 'function', 'trackItem is the Premiere item');
    assert.equal(typeof entry.getComponentChain, 'undefined', 'the entry itself is not an item');
  });

  it('places one named layer per matched clip on the track above', async () => {
    makeDonor(project, 'YTAI_ADJ');
    placeClip2(0, 'RYA-FX3-1108.MP4', 0, 10);
    placeClip2(0, 'RYA-FX3-1109.MP4', 10, 8);
    const plan = { 'RYA-FX3-1108.MP4': 'normal_scene', 'RYA-FX3-1109.MP4': 'dark_scene' };
    const r = await addAdjustmentPerClipFromPlan(project, seq, plan, { applyLumetri: false }, logger);
    assert.equal(r.ok, true);
    assert.equal(r.placed, 2);
    const v2 = seq._videoTracks[1];
    assert.ok(v2, 'V2 created');
    // Both layers land on V2 (no overlap), renamed to their LUTs
    const names = v2._items.map((ti) => ti.name).sort();
    assert.deepEqual(names, ['02_normal_scene', '03_dark_scene']); // plan values canonicalised
    const starts = v2._items.map((ti) => ti._startTimeSec).sort((a, b) => a - b);
    assert.deepEqual(starts, [0, 10]);
  });

  it('lane-stacks overlapping matched clips one track higher', async () => {
    makeDonor(project, 'YTAI_ADJ');
    placeClip2(0, 'CAM-A.MP4', 0, 10);
    placeClip2(1, 'CAM-B.MP4', 4, 10); // overlaps CAM-A, lives on V2
    const plan = { 'CAM-A.MP4': 'normal_scene', 'CAM-B.MP4': 'dark_scene' };
    const r = await addAdjustmentPerClipFromPlan(project, seq, plan, { applyLumetri: false }, logger);
    assert.equal(r.placed, 2);
    // base = above V2 → V3; overlap pushes second to V4
    assert.equal(seq._videoTracks[2]._items.length, 1);
    assert.equal(seq._videoTracks[3]._items.length, 1);
  });

  it('rerun places nothing when every layer already stands (idempotency)', async () => {
    makeDonor(project, 'YTAI_ADJ');
    placeClip2(0, 'RYA-FX3-1108.MP4', 0, 10);
    const plan = { 'RYA-FX3-1108.MP4': 'dark_scene' };
    const r1 = await addAdjustmentPerClipFromPlan(project, seq, plan, { applyLumetri: false }, logger);
    assert.equal(r1.placed, 1);
    const r2 = await addAdjustmentPerClipFromPlan(project, seq, plan, { applyLumetri: false }, logger);
    assert.equal(r2.ok, true);
    assert.equal(r2.placed, 0);
    assert.equal(r2.already, 1);
    const lutItems = [];
    for (const t of seq._videoTracks) for (const ti of t._items) if (ti.name === '03_dark_scene') lutItems.push(ti);
    assert.equal(lutItems.length, 1); // no duplicates
  });

  it('rerun restores only the deleted layer (repair mode)', async () => {
    makeDonor(project, 'YTAI_ADJ');
    placeClip2(0, 'RYA-FX3-1108.MP4', 0, 10);
    placeClip2(0, 'RYA-FX3-1109.MP4', 10, 8);
    const plan = { 'RYA-FX3-1108.MP4': 'normal_scene', 'RYA-FX3-1109.MP4': 'dark_scene' };
    await addAdjustmentPerClipFromPlan(project, seq, plan, { applyLumetri: false }, logger);
    // User accidentally deletes the second layer
    const v2 = seq._videoTracks[1];
    const idx = v2._items.findIndex((ti) => ti.name === '03_dark_scene');
    assert.ok(idx >= 0);
    v2._items.splice(idx, 1);
    const r2 = await addAdjustmentPerClipFromPlan(project, seq, plan, { applyLumetri: false }, logger);
    assert.equal(r2.placed, 1);   // only the missing one
    assert.equal(r2.already, 1);  // the surviving one untouched
    const names = [];
    for (const t of seq._videoTracks) for (const ti of t._items)
      if (ti.name === '02_normal_scene' || ti.name === '03_dark_scene') names.push(ti.name);
    names.sort();
    assert.deepEqual(names, ['02_normal_scene', '03_dark_scene']); // plan values canonicalised
  });

  it('reports no-plan-match when timeline clips are not in the plan', async () => {
    makeDonor(project, 'YTAI_ADJ');
    placeClip2(0, 'UNKNOWN.MP4', 0, 5);
    const r = await addAdjustmentPerClipFromPlan(project, seq, { 'X.MP4': 'dark_scene' }, {}, logger);
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'no-plan-match');
  });
});

// --- setEffectParam: value-set paths + step-tagged diagnostics (18.08 blocker) ---

describe('setEffectParam', () => {
  let project, seq, logger;
  beforeEach(async () => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    seq = new ppro._MockSequence('Seq', { videoTracks: 1, audioTracks: 0 });
    await project.setActiveSequence(seq);
    logger = new Logger();
  });

  function clipWithLumetri(params) {
    const clip = placeClip(seq, 0, 'C.MP4', 0, 10);
    const v = ppro.VideoClipTrackItem.cast(clip); // cached wrapper — stable chain
    const comp = new ppro._MockVideoComponent('AE.ADBE Lumetri', 'Lumetri Color');
    comp._params = params;
    v._componentChain._components.push(comp);
    return clip;
  }

  function logText() { return logger.getBuffer().join('\n'); }

  it('sets a string param via the start-keyframe path (no createKeyframe)', async () => {
    const look = new ppro._MockComponentParam('Look', 'none');
    const clip = clipWithLumetri([look]);
    const ok = await setEffectParam(project, clip, 'Lumetri', 'Look', 'dark_scene', logger);
    assert.equal(ok, true);
    assert.equal(look._value, 'dark_scene');
    assert.equal(ppro._recorder.getCalls('ComponentParam.createKeyframe').length, 0);
    assert.match(logText(), /current: type=string/); // type-probe = human diagnosis contract
  });

  it('falls back to createKeyframe when getStartValue is unavailable', async () => {
    const look = new ppro._MockComponentParam('Look', 'none', { noStartValue: true });
    const clip = clipWithLumetri([look]);
    const ok = await setEffectParam(project, clip, 'Lumetri', 'Look', 'bright_scene', logger);
    assert.equal(ok, true);
    assert.equal(look._value, 'bright_scene');
    assert.equal(ppro._recorder.getCalls('ComponentParam.createKeyframe').length, 1);
  });

  it('reports failure when the commit succeeds but the value does not stick (menu-index Look)', async () => {
    // Measured YTCH13 18.08 16:30: Look is a NUMERIC menu index; the string
    // «set» commits without throwing and readback stays 0. The old code
    // counted that as success («Look auto 26» while the timeline shows None).
    const look = new ppro._MockComponentParam('Look', 0, { ignoreSet: true });
    const clip = clipWithLumetri([look]);
    const ok = await setEffectParam(project, clip, 'Lumetri', 'Look', 'dark_scene', logger);
    assert.equal(ok, false);
    assert.equal(look._value, 0); // untouched, as on live
    assert.match(logText(), /current: type=number/);
    assert.match(logText(), /did NOT stick/);
    // Terminal: no pointless createKeyframe throw after a proven type mismatch
    assert.equal(ppro._recorder.getCalls('ComponentParam.createKeyframe').length, 0);
  });

  it('never throws on a type-mismatched param and logs the exact step', async () => {
    // Worst case: Look is secretly a menu INDEX (number) and the API validates
    // on both paths — the blocker scenario («Illegal Parameter type»).
    const look = new ppro._MockComponentParam('Look', 3, { strictSet: true });
    const clip = clipWithLumetri([look]);
    const ok = await setEffectParam(project, clip, 'Lumetri', 'Look', 'dark_scene', logger);
    assert.equal(ok, false);
    assert.equal(look._value, 3); // untouched
    assert.match(logText(), /current: type=number/);           // probe reveals the real type
    assert.match(logText(), /start-keyframe set failed/);      // path A tagged
    assert.match(logText(), /failed @ createKeyframe\(Look\)/); // path B step-tagged
  });

  it('enumerates all param names when the target param is absent', async () => {
    const clip = clipWithLumetri([
      new ppro._MockComponentParam('Basic Correction', 1),
      new ppro._MockComponentParam('Exposure', 0.5),
    ]);
    const ok = await setEffectParam(project, clip, 'Lumetri', 'Look', 'dark_scene', logger);
    assert.equal(ok, false);
    assert.match(logText(), /not found among \[Basic Correction, Exposure\]/);
  });
});

// --- setEffectParam on the LIVE 26.x surface (no cast, count/atIndex chain) ---

describe('setEffectParam live-26.x surface', () => {
  let project, logger;
  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    logger = new Logger();
  });

  // Models the measured Beta 26 world: NO VideoClipTrackItem.cast static, the
  // raw track item exposes getComponentChain directly, the chain has ONLY
  // getComponentCount()/getComponentAtIndex(i), components expose ASYNC
  // getDisplayName() — the branches the standard mock never exercises.
  function liveRawClip(params) {
    const comp = {
      getDisplayName: async () => 'Lumetri Color',
      getParamCount: async () => params.length,
      getParam: async (i) => params[i],
    };
    const chain = {
      getComponentCount: async () => 1,
      getComponentAtIndex: async () => comp,
    };
    return { getComponentChain: async () => chain };
  }

  it('sets the param through the count/atIndex chain on a cast-less raw item', async () => {
    const savedCast = ppro.VideoClipTrackItem.cast;
    try {
      delete ppro.VideoClipTrackItem.cast; // live: no cast static at all
      const look = new ppro._MockComponentParam('Look', 'none');
      const ok = await setEffectParam(project, liveRawClip([look]), 'Lumetri', 'Look', 'dark_scene', logger);
      assert.equal(ok, true);
      assert.equal(look._value, 'dark_scene');
    } finally {
      ppro.VideoClipTrackItem.cast = savedCast;
    }
  });

  it('matches the component via matchName when displayName is unreadable', async () => {
    const savedCast = ppro.VideoClipTrackItem.cast;
    try {
      delete ppro.VideoClipTrackItem.cast;
      const look = new ppro._MockComponentParam('Look', 'none');
      const comp = {
        getMatchName: async () => 'AE.ADBE Lumetri', // no getDisplayName at all
        getParamCount: async () => 1,
        getParam: async () => look,
      };
      const chain = {
        getComponentCount: async () => 1,
        getComponentAtIndex: async () => comp,
      };
      const clip = { getComponentChain: async () => chain };
      const ok = await setEffectParam(project, clip, 'Lumetri', 'Look', 'bright_scene', logger);
      assert.equal(ok, true);
      assert.equal(look._value, 'bright_scene');
    } finally {
      ppro.VideoClipTrackItem.cast = savedCast;
    }
  });
});

// --- probeDonorClone: PLAN-B cross-sequence clone probe ---

describe('probeDonorClone', () => {
  let project, target, donorSeq, logger;
  beforeEach(async () => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    target = new ppro._MockSequence('YTCH13_scene1', { videoTracks: 1, audioTracks: 0 });
    project._sequences.push(target);
    await project.setActiveSequence(target);
    logger = new Logger();
  });

  function addDonorSequence() {
    donorSeq = new ppro._MockSequence(LUT_DONOR_SEQUENCE, { videoTracks: 1, audioTracks: 0 });
    project._sequences.push(donorSeq);
    const al = placeClip(donorSeq, 0, 'dark_scene', 0, 5);
    const v = ppro.VideoClipTrackItem.cast(al);
    v._componentChain._components.push(
      new ppro._MockVideoComponent('AE.ADBE Lumetri', 'Lumetri Color'));
    return al;
  }

  it('reports no-donor-sequence when the template sequence is missing', async () => {
    const r = await probeDonorClone(project, {}, logger);
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'no-donor-sequence');
  });

  it('imports the master template when the donor sequence is missing, then clones', async () => {
    // Existing projects were cloned from the template BEFORE the donor
    // sequence was added — the probe must pull it in via importFiles.
    makeDonor(project, 'YTAI_ADJ');
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    project.importFiles = async function (paths) {
      ppro._recorder.record('Project.importFiles', [paths]);
      addDonorSequence(); // import materialises the template's sequence
      return true;
    };
    const r = await probeDonorClone(
      project, { donorPrproj: '/tpl/RYA_example.prproj' }, logger);
    assert.equal(r.ok, true, 'probe should succeed: ' + (r.reason || ''));
    assert.equal(r.lumetriKept, true);
    const calls = ppro._recorder.getCalls('Project.importFiles');
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args[0], ['/tpl/RYA_example.prproj']);
  });

  it('refuses to clone into the donor sequence itself', async () => {
    addDonorSequence();
    await project.setActiveSequence(donorSeq);
    const r = await probeDonorClone(project, {}, logger);
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'donor-is-active');
  });

  it('clones the donor AL onto a fresh track above content, Lumetri intact', async () => {
    addDonorSequence();
    makeDonor(project, 'YTAI_ADJ'); // for growVideoTracks
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const r = await probeDonorClone(project, {}, logger);
    assert.equal(r.ok, true, 'probe should succeed: ' + (r.reason || ''));
    assert.equal(r.landedTrack, 1); // fresh track above V1 content
    assert.equal(r.offTarget, false);
    assert.equal(r.lumetriKept, true);
    // Existing content untouched; donor sequence untouched
    assert.equal(target._videoTracks[0]._items.length, 1);
    assert.equal(target._videoTracks[0]._items[0].name, 'RYA-FX3-1108.MP4');
    assert.equal(donorSeq._videoTracks[0]._items.length, 1);
    // The clone is on the fresh track and named after the donor AL
    const cloned = target._videoTracks[1]._items.filter((ti) => ti.name === 'dark_scene');
    assert.equal(cloned.length, 1);
  });

  it('CLOBBER GATE: detects and reports content eaten by divergent offset semantics', async () => {
    // Model the exact unproven-live scenario the reviewers flagged: the
    // vertical offset is IGNORED (clone lands on the donor's own track index),
    // so the overwrite-mode clone eats the head of a real content clip.
    addDonorSequence();
    makeDonor(project, 'YTAI_ADJ');
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const realGetEditor = ppro.SequenceEditor.getEditor;
    ppro.SequenceEditor.getEditor = function (s) {
      const ed = realGetEditor.call(ppro.SequenceEditor, s);
      const orig = ed.createCloneTrackItemAction.bind(ed);
      ed.createCloneTrackItemAction = function (ti, t, vOff, aOff, align, ins) {
        return orig(ti, t, 0, aOff, align, ins); // live "clamps" the vertical offset
      };
      return ed;
    };
    try {
      const r = await probeDonorClone(project, {}, logger);
      assert.equal(r.ok, false);
      assert.equal(r.reason, 'clobbered-content');
      assert.ok(r.clobbered >= 1);
      assert.match(logger.getBuffer().join('\n'), /CLOBBER/);
    } finally {
      ppro.SequenceEditor.getEditor = realGetEditor;
    }
  });
});

// --- buildLutDonorSequence: programmatic donor construction ---

describe('buildLutDonorSequence', () => {
  const { buildLutDonorSequence, LUT_DONOR_CLIPS } = require('../../src/adjust/adjustmentBuilder');
  let project, logger;
  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('P');
    logger = new Logger();
  });

  function donorSeqClipsByTrack(project) {
    const seq = project._sequences.find((s) => s.name === 'YTAI_LUT_DONOR');
    assert.ok(seq, 'sequence must exist');
    const perTrack = seq._videoTracks.map((t) => t._items.map((ti) => ({ name: ti.name, start: ti._startTimeSec })));
    return { seq, perTrack };
  }

  it('creates the v2 layout — each named AL clip @0 on its OWN track, Lumetri on each', async () => {
    makeDonor(project, 'YTAI_ADJ');
    const r = await buildLutDonorSequence(project, {}, logger);
    assert.equal(r.ok, true, 'build should succeed: ' + (r.reason || ''));
    assert.equal(r.created, true);
    assert.equal(r.placed, 3);
    assert.equal(r.lumetri, 3);
    // Mock Lumetri component has no Look param → API cannot set it → all by hand
    assert.deepEqual(r.needLook, LUT_DONOR_CLIPS);
    const { perTrack } = donorSeqClipsByTrack(project);
    LUT_DONOR_CLIPS.forEach((name, i) => {
      assert.equal(perTrack[i].length, 1, 'V' + (i + 1) + ' must hold exactly one clip');
      assert.equal(perTrack[i][0].name, name);
      assert.equal(perTrack[i][0].start, 0);
    });
  });

  it('is idempotent — second run places nothing, no rebuild', async () => {
    makeDonor(project, 'YTAI_ADJ');
    await buildLutDonorSequence(project, {}, logger);
    const r2 = await buildLutDonorSequence(project, {}, logger);
    assert.equal(r2.ok, true);
    assert.equal(r2.created, false);
    assert.equal(r2.rebuilt, false);
    assert.equal(r2.placed, 0);
    const { perTrack } = donorSeqClipsByTrack(project);
    assert.equal(perTrack.reduce((n, t) => n + t.length, 0), 3);
  });

  it('REBUILDS an old sequential layout (clips at 0/5/10 on V1) into per-track@0', async () => {
    makeDonor(project, 'YTAI_ADJ');
    const dseq = new ppro._MockSequence('YTAI_LUT_DONOR', { videoTracks: 1, audioTracks: 0 });
    project._sequences.push(dseq);
    placeClip(dseq, 0, 'bright_scene', 0, 5);
    placeClip(dseq, 0, 'normal_scene', 5, 5);
    placeClip(dseq, 0, 'dark_scene', 10, 5);
    const r = await buildLutDonorSequence(project, {}, logger);
    assert.equal(r.ok, true);
    assert.equal(r.rebuilt, true);
    assert.equal(r.placed, 3);
    assert.deepEqual(r.needLook, LUT_DONOR_CLIPS); // Looks lost — re-pick
    const { perTrack } = donorSeqClipsByTrack(project);
    LUT_DONOR_CLIPS.forEach((name, i) => {
      assert.equal(perTrack[i].length, 1, 'V' + (i + 1) + ' must hold exactly one clip');
      assert.equal(perTrack[i][0].name, name);
      assert.equal(perTrack[i][0].start, 0);
    });
  });

  it('replaces alias-named clips in a conforming layout (their Looks are broken by the rename)', async () => {
    makeDonor(project, 'YTAI_ADJ');
    const dseq = new ppro._MockSequence('YTAI_LUT_DONOR', { videoTracks: 3, audioTracks: 0 });
    project._sequences.push(dseq);
    ['bright_scene', 'normal_scene', 'dark_scene'].forEach((name, i) => placeClip(dseq, i, name, 0, 5));
    const r = await buildLutDonorSequence(project, {}, logger);
    assert.equal(r.ok, true);
    assert.equal(r.placed, 3); // all three re-placed under canonical 01_/02_/03_ names
    assert.deepEqual(r.needLook, LUT_DONOR_CLIPS);
    const { perTrack } = donorSeqClipsByTrack(project);
    LUT_DONOR_CLIPS.forEach((name, i) => {
      assert.equal(perTrack[i].length, 1, 'V' + (i + 1) + ' must hold exactly one clip');
      assert.equal(perTrack[i][0].name, name);
    });
  });

  it('reports no hand-work when the Look param is settable and set', async () => {
    makeDonor(project, 'YTAI_ADJ');
    const savedCreate = ppro.VideoFilterFactory.createComponent;
    ppro.VideoFilterFactory.createComponent = async function (matchName) {
      const comp = new ppro._MockVideoComponent(matchName, 'Lumetri Color');
      comp._params = [new ppro._MockComponentParam('Look', 'none')];
      return comp;
    };
    try {
      const r = await buildLutDonorSequence(project, {}, logger);
      assert.equal(r.ok, true);
      assert.deepEqual(r.needLook, []);
    } finally {
      ppro.VideoFilterFactory.createComponent = savedCreate;
    }
  });

  it('reports no-donor when the YTAI_ADJ item is missing', async () => {
    const r = await buildLutDonorSequence(project, {}, logger);
    assert.equal(r.ok, false);
    assert.equal(r.reason, 'no-donor');
  });
});

// --- clone-mode addAdjustmentPerClipFromPlan (Plan B in production) ---

describe('addAdjustmentPerClipFromPlan clone mode', () => {
  const { addAdjustmentPerClipFromPlan: perClip, LUT_DONOR_CLIPS: DONOR_CLIPS,
    __resetLutDonorRefreshState } = require('../../src/adjust/adjustmentBuilder');
  let project, target, logger;
  beforeEach(async () => {
    ppro._recorder.reset();
    __resetLutDonorRefreshState();
    project = new ppro._MockProject('P');
    target = new ppro._MockSequence('YTCH13_scene1', { videoTracks: 1, audioTracks: 0 });
    project._sequences.push(target);
    await project.setActiveSequence(target);
    makeDonor(project, 'YTAI_ADJ');
    logger = new Logger();
  });

  /** Canonical v2 donor sequence: each LUT clip @0 on its own track, Lumetri+Look set. */
  function addDonorSequenceV2() {
    const dseq = new ppro._MockSequence(LUT_DONOR_SEQUENCE, { videoTracks: 3, audioTracks: 0 });
    project._sequences.push(dseq);
    DONOR_CLIPS.forEach((name, i) => {
      const al = placeClip(dseq, i, name, 0, 5);
      const v = ppro.VideoClipTrackItem.cast(al);
      const comp = new ppro._MockVideoComponent('AE.ADBE Lumetri', 'Lumetri Color');
      comp._params = [new ppro._MockComponentParam('Look', i + 1)]; // nonzero = Look picked
      v._componentChain._components.push(comp);
    });
    return dseq;
  }

  function laneItems(trackIdx) {
    const t = target._videoTracks[trackIdx];
    return t ? t._items.map((ti) => ({ name: ti.name, start: ti._startTimeSec, dur: ti._durationSec })) : [];
  }

  it('places donor clones at exact clip bounds, Lumetri+Look riding along', async () => {
    addDonorSequenceV2();
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    placeClip(target, 0, 'RYA-FX3-1109.MP4', 10, 8);
    const plan = { 'RYA-FX3-1108.MP4': 'dark_scene', 'RYA-FX3-1109.MP4': 'bright_scene' };
    const r = await perClip(project, target, plan, {}, logger);
    assert.equal(r.mode, 'clone');
    assert.equal(r.ok, true, 'should succeed: ' + JSON.stringify(r));
    assert.equal(r.placed, 2);
    assert.equal(r.lumetriApplied, 2); // clones carry Lumetri
    assert.equal(r.lookSet, 2);        // ...with a real (nonzero) Look
    const lane = laneItems(1).sort((a, b) => a.start - b.start);
    assert.deepEqual(lane, [
      { name: '03_dark_scene', start: 0, dur: 10 },   // extended 5s → 10s
      { name: '01_bright_scene', start: 10, dur: 8 }, // extended 5s → 8s
    ]);
    // Content untouched
    assert.equal(laneItems(0).length, 2);
    assert.equal(laneItems(0)[0].name, 'RYA-FX3-1108.MP4');
  });

  it('is idempotent — rerun with the manifest sees healthy clones, places nothing', async () => {
    addDonorSequenceV2();
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const plan = { 'RYA-FX3-1108.MP4': 'dark_scene' }; // old value → canonicalised
    const r1 = await perClip(project, target, plan, {}, logger);
    assert.ok(r1.layerManifest['RYA-FX3-1108.MP4'], 'manifest records the clone');
    const r2 = await perClip(project, target, plan, { layerManifest: r1.layerManifest }, logger);
    assert.equal(r2.mode, 'clone');
    assert.equal(r2.placed, 0);
    assert.equal(r2.already, 1);
    assert.equal(r2.lookSet, 1); // healthy clone counted
    assert.ok(r2.layerManifest['RYA-FX3-1108.MP4'], 'manifest entry carried forward');
    const clones = target._videoTracks.flatMap((t) => t._items).filter((ti) => ti.name === '03_dark_scene');
    assert.equal(clones.length, 1);
  });

  it('replaces a canonical-named layer NOT in the manifest (legacy leftovers)', async () => {
    // The 18.08 18:43 case: a legacy run placed canonical-named layers WITHOUT
    // a Look; the manifest has no record of them → they must be replaced.
    addDonorSequenceV2();
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const stale = placeClip(target, 1, '03_dark_scene', 0, 10);
    const plan = { 'RYA-FX3-1108.MP4': '03_dark_scene' };
    const r = await perClip(project, target, plan, { layerManifest: {} }, logger);
    assert.equal(r.mode, 'clone');
    assert.equal(r.placed, 1);
    const all = target._videoTracks.flatMap((t) => t._items).filter((ti) => ti.name === '03_dark_scene');
    assert.equal(all.length, 1, 'stale legacy layer replaced, not duplicated');
    assert.notEqual(all[0], stale);
    assert.ok(r.layerManifest['RYA-FX3-1108.MP4']);
  });

  it('replaces an ALIASED layer even when its Look param reads nonzero (broken by rename)', async () => {
    addDonorSequenceV2();
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    // Pre-rename clone: old name, Look=3 (points at the renamed .cube → broken)
    const stale = placeClip(target, 1, 'dark_scene', 0, 10);
    const v = ppro.VideoClipTrackItem.cast(stale);
    const comp = new ppro._MockVideoComponent('AE.ADBE Lumetri', 'Lumetri Color');
    comp._params = [new ppro._MockComponentParam('Look', 3)];
    v._componentChain._components.push(comp);
    const plan = { 'RYA-FX3-1108.MP4': '03_dark_scene' };
    const r = await perClip(project, target, plan, {}, logger);
    assert.equal(r.mode, 'clone');
    assert.equal(r.placed, 1);
    const oldOnes = target._videoTracks.flatMap((t) => t._items).filter((ti) => ti.name === 'dark_scene');
    assert.equal(oldOnes.length, 0, 'pre-rename layer must be gone');
    const fresh = target._videoTracks.flatMap((t) => t._items).filter((ti) => ti.name === '03_dark_scene');
    assert.equal(fresh.length, 1);
  });

  it('replaces a legacy Look-less layer with a donor clone', async () => {
    addDonorSequenceV2();
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    // Legacy layer from the 18.08 runs: right name+bounds, Lumetri with Look=0
    const stale = placeClip(target, 1, 'dark_scene', 0, 10);
    const v = ppro.VideoClipTrackItem.cast(stale);
    const comp = new ppro._MockVideoComponent('AE.ADBE Lumetri', 'Lumetri Color');
    comp._params = [new ppro._MockComponentParam('Look', 0)]; // None
    v._componentChain._components.push(comp);
    const plan = { 'RYA-FX3-1108.MP4': 'dark_scene' };
    const r = await perClip(project, target, plan, {}, logger);
    assert.equal(r.mode, 'clone');
    assert.equal(r.placed, 1);
    const all = target._videoTracks.flatMap((t) => t._items).filter((ti) => ti.name === '03_dark_scene');
    assert.equal(all.length, 1, 'stale layer must be replaced, not duplicated');
    assert.notEqual(all[0], stale);
  });

  it('falls back to legacy mode when no donor sequence anywhere', async () => {
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const plan = { 'RYA-FX3-1108.MP4': 'dark_scene' };
    const r = await perClip(project, target, plan, { applyLumetri: false }, logger);
    assert.equal(r.mode, 'legacy');
    assert.equal(r.placed, 1);
    const lane = laneItems(1);
    assert.equal(lane.length, 1);
    assert.equal(lane[0].name, '03_dark_scene'); // renamed YTAI_ADJ placement, canonical name
  });

  it('BLOCKER GUARD: stale template (alias v2 donor) → legacy mode, alias layers KEPT', async () => {
    // The 18.08 blocker scenario: local donor alias-named, template re-import
    // returns an equally alias-named v2 donor. Layers must survive.
    const local = new ppro._MockSequence(LUT_DONOR_SEQUENCE, { videoTracks: 3, audioTracks: 0 });
    project._sequences.push(local);
    ['bright_scene', 'normal_scene', 'dark_scene'].forEach((n, i) => placeClip(local, i, n, 0, 5));
    project.importFiles = async function () {
      const tpl = new ppro._MockSequence(LUT_DONOR_SEQUENCE, { videoTracks: 3, audioTracks: 0 });
      project._sequences.push(tpl); // template donor is ALSO alias-named (not yet rebuilt)
      ['bright_scene', 'normal_scene', 'dark_scene'].forEach((n, i) => placeClip(tpl, i, n, 0, 5));
      return true;
    };
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const stale = placeClip(target, 1, 'dark_scene', 0, 10); // broken-Look clone
    const plan = { 'RYA-FX3-1108.MP4': '03_dark_scene' };
    const r = await perClip(project, target, plan, { donorPrproj: '/tpl/RYA_example.prproj' }, logger);
    assert.equal(r.mode, 'legacy', 'stale template must NOT enter clone mode');
    const survivors = target._videoTracks.flatMap((t) => t._items)
      .filter((ti) => ti === stale || ti.name === '03_dark_scene');
    assert.ok(survivors.length >= 1, 'the existing layer must survive');
  });

  it('keeps a layer whose plan LUT the donor cannot serve (custom name outside the trio)', async () => {
    addDonorSequenceV2();
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const stale = placeClip(target, 1, 'custom_look', 0, 10); // matches the plan value below
    const plan = { 'RYA-FX3-1108.MP4': 'custom_look' }; // not in the donor set
    const r = await perClip(project, target, plan, {}, logger);
    assert.equal(r.mode, 'clone');
    assert.equal(r.placed, 0, 'nothing must be placed for the unserved LUT');
    const still = target._videoTracks.flatMap((t) => t._items).filter((ti) => ti === stale);
    assert.equal(still.length, 1, 'the layer must be KEPT, not destroyed');
  });

  it('self-heals an outdated imported donor copy from the template (delete + re-import)', async () => {
    // Local copy in the OLD layout (what the 18.08 probe imported)
    const oldSeq = new ppro._MockSequence(LUT_DONOR_SEQUENCE, { videoTracks: 1, audioTracks: 0 });
    project._sequences.push(oldSeq);
    placeClip(oldSeq, 0, 'bright_scene', 0, 5);
    placeClip(oldSeq, 0, 'normal_scene', 5, 5);
    placeClip(oldSeq, 0, 'dark_scene', 10, 5);
    project.importFiles = async function (paths) {
      ppro._recorder.record('Project.importFiles', [paths]);
      addDonorSequenceV2(); // the template now ships the v2 layout
      return true;
    };
    placeClip(target, 0, 'RYA-FX3-1108.MP4', 0, 10);
    const plan = { 'RYA-FX3-1108.MP4': 'dark_scene' };
    const r = await perClip(project, target, plan, { donorPrproj: '/tpl/RYA_example.prproj' }, logger);
    assert.equal(r.mode, 'clone', 'must self-heal into clone mode: ' + JSON.stringify(r));
    assert.equal(r.placed, 1);
    assert.equal(ppro._recorder.getCalls('Project.deleteSequence').length, 1);
    assert.equal(project._sequences.filter((s) => s.name === LUT_DONOR_SEQUENCE).length, 1);
  });
});
