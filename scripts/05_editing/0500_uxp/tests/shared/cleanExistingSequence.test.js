// cleanExistingSequence (2026-09-15): a same-name sequence filed in 00_Source_Timelines
// must still be archived (rename _v{N} + verified move to 03_Assembly) — otherwise a
// rebuild of a scene-named part (YTUVI02_18_SSEF_Commentary) duplicates the name.
const test = require('node:test');
const assert = require('node:assert');
const ppro = require('../mocks/premierepro');
const { cleanExistingSequence } = require('../../src/shared/clipActions');
const binMove = require('../../src/shared/binMove');

const LOG = { info() {}, warn() {}, error() {}, debug() {} };
const NAME = 'YTUVI02_18_SSEF_Commentary';

async function projectWithFiledSequence() {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence(NAME);
  const bin = await binMove.ensureRootBin(project, '00_Source_Timelines', null);
  assert.strictEqual(await binMove.moveItemToBin(project, seq._projectItem, bin, null), true);
  return { project, seq, bin, item: seq._projectItem };
}

function rootBin(project, name) {
  return project._rootItem._items.find(i => i && i.type === 2 && i.name === name);
}

test('cleanExistingSequence finds a same-name sequence inside 00_Source_Timelines (no extraBin)', async () => {
  const { project, bin, item } = await projectWithFiledSequence();
  await cleanExistingSequence(project, NAME, LOG);   // NO extraBin passed
  assert.strictEqual(item.name, NAME + '_v1', 'renamed to _v1');
  const archive = rootBin(project, '03_Assembly');
  assert.ok(archive && archive._items.indexOf(item) >= 0, 'moved into 03_Assembly');
  assert.ok(bin._items.indexOf(item) < 0, 'gone from 00_Source_Timelines');
  const moves = ppro._recorder.getCalls('FolderItem.createMoveItemAction').filter(c => c.args[0] === item);
  assert.ok(moves.every(c => c.args[1]), 'every move passes the destination (two-arg form)');
});

test('cleanExistingSequence: bin scan alone finds it when Sequence.getProjectItem is unavailable', async () => {
  const { project, seq, item } = await projectWithFiledSequence();
  seq.getProjectItem = undefined;   // older build — only the container scan can see it
  await cleanExistingSequence(project, NAME, LOG);
  assert.strictEqual(item.name, NAME + '_v1');
  assert.ok(rootBin(project, '03_Assembly')._items.indexOf(item) >= 0);
});

test('cleanExistingSequence: _v{N} numbering counts versions living in any bin', async () => {
  const { project, item } = await projectWithFiledSequence();
  const old = await project.createSequence(NAME + '_v4');
  const review = await binMove.ensureRootBin(project, '05_Review', null);
  await binMove.moveItemToBin(project, old._projectItem, review, null);
  await cleanExistingSequence(project, NAME, LOG);
  assert.strictEqual(item.name, NAME + '_v5', 'next after _v4 found via getSequences names');
});

test('cleanExistingSequence: rename failure on a sequence filed in ANOTHER bin never deletes it', async () => {
  // Hand-edited timeline filed in 05_Review, reached only via Sequence.getProjectItem.
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence('YTUVI02_5_Review_v3');
  const review = await binMove.ensureRootBin(project, '05_Review', null);
  assert.strictEqual(await binMove.moveItemToBin(project, seq._projectItem, review, null), true);
  const item = seq._projectItem;
  item.createSetNameAction = function () { throw new Error('The script object is no longer valid'); };
  const before = ppro._recorder.getCalls('Project.deleteSequence').length;
  await cleanExistingSequence(project, 'YTUVI02_5_Review_v3', LOG);
  assert.strictEqual(ppro._recorder.getCalls('Project.deleteSequence').length, before, 'deleteSequence not called');
  assert.ok((await project.getSequences()).indexOf(seq) >= 0, 'sequence still exists');
  assert.ok(review._items.indexOf(item) >= 0, 'left in 05_Review');
});

test('cleanExistingSequence: rename failure on a sequence inside 00_Source_Timelines never deletes it', async () => {
  const { project, seq, bin, item } = await projectWithFiledSequence();
  item.createSetNameAction = function () { throw new Error('locked'); };
  await cleanExistingSequence(project, NAME, LOG);
  assert.ok((await project.getSequences()).indexOf(seq) >= 0, 'not deleted');
  assert.ok(bin._items.indexOf(item) >= 0, 'left in 00_Source_Timelines');
});

test('cleanExistingSequence: root last-resort delete passes the Sequence object, not the ProjectItem', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence(NAME);
  seq.getProjectItem = undefined;   // root scan path only
  seq._projectItem.createSetNameAction = function () { throw new Error('locked'); };
  await cleanExistingSequence(project, NAME, LOG);
  const calls = ppro._recorder.getCalls('Project.deleteSequence').filter(c => c.args[0] === seq || c.args[0] === seq._projectItem);
  assert.ok(calls.length >= 1, 'deleteSequence called for the root confirmed sequence');
  assert.ok(calls.every(c => c.args[0] === seq), 'receives the Sequence, never the ProjectItem');
  assert.ok((await project.getSequences()).indexOf(seq) < 0, 'deleted');
});

test('cleanExistingSequence: unverified archive move keeps the rename, never deletes', async () => {
  const { project, seq, bin, item } = await projectWithFiledSequence();
  project._rootItem.createMoveItemAction = function () { return { type: 'noop' }; };
  if (item.getParentBin) item.getParentBin = function () { return bin; };
  bin.createMoveItemAction = function () { return { type: 'noop' }; };
  await cleanExistingSequence(project, NAME, LOG);
  assert.strictEqual(item.name, NAME + '_v1', 'renamed');
  assert.ok(bin._items.indexOf(item) >= 0, 'left in its bin');
  assert.ok((await project.getSequences()).indexOf(seq) >= 0, 'not deleted');
});
