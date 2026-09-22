// shared/binMove (2026-09-15): the ONE move path — two-arg createMoveItemAction on the
// project ROOT, verified read-back, duplicate guard, never deletes.
const test = require('node:test');
const assert = require('node:assert');
const ppro = require('../mocks/premierepro');
const binMove = require('../../src/shared/binMove');

function mkLog() {
  const log = { infos: [], warns: [], info(m) { this.infos.push(m); }, warn(m) { this.warns.push(m); }, error() {}, debug() {} };
  return log;
}
function inRoot(project, item) { return project._rootItem._items.indexOf(item) >= 0; }

test('mock contract: one-arg createMoveItemAction throws (the old silent no-op can never pass)', () => {
  const root = new ppro._MockFolderItem('root');
  const item = { name: 'X', type: 1 };
  assert.throws(() => root.createMoveItemAction(item), /Not Enough Parameters/);
});

test('moveItemToBin: sequence moves root → bin via ROOT.createMoveItemAction(item, bin), verified', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence('YTUVI02_01_Studio');
  const bin = await binMove.ensureRootBin(project, '00_Source_Timelines', null);
  assert.ok(bin, 'bin created');
  const item = await binMove.findSequenceProjectItem(project, seq, seq.name);
  assert.ok(item && inRoot(project, item), 'fresh sequence item at root');

  ppro._recorder.reset();
  const log = mkLog();
  const ok = await binMove.moveItemToBin(project, item, bin, log);
  assert.strictEqual(ok, true, 'verified move returns true');
  const calls = ppro._recorder.getCalls('FolderItem.createMoveItemAction');
  assert.strictEqual(calls.length, 1, 'exactly one move action');
  assert.strictEqual(calls[0].args[0], item, 'arg 1 = item');
  assert.strictEqual(calls[0].args[1], bin, 'arg 2 = destination bin');
  assert.ok(bin._items.indexOf(item) >= 0, 'item inside the bin');
  assert.ok(!inRoot(project, item), 'item gone from root');
  assert.strictEqual((await project.getSequences()).length, 1, 'no copy made');
  assert.ok(log.infos.some(m => /verified/.test(m)), 'success logged as verified');

  // idempotent: already in the bin → true, no second action
  ppro._recorder.reset();
  assert.strictEqual(await binMove.moveItemToBin(project, item, bin, log), true);
  assert.strictEqual(ppro._recorder.getCalls('FolderItem.createMoveItemAction').length, 0, 'no action when already in bin');
});

test('moveItemToBin: silent no-op transaction (live one-arg symptom) → false + warn, item stays at root', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence('YTUVI02_03_Cafe');
  const bin = await binMove.ensureRootBin(project, '05_Review', null);
  const item = await binMove.findSequenceProjectItem(project, seq, seq.name);
  // action is created and the transaction "succeeds", but nothing moves
  project._rootItem.createMoveItemAction = function (it, np) { return { type: 'noop' }; };
  const log = mkLog();
  const ok = await binMove.moveItemToBin(project, item, bin, log);
  assert.strictEqual(ok, false, 'unverified move is NOT reported as success');
  assert.ok(inRoot(project, item), 'item still at root');
  assert.strictEqual(bin._items.length, 0, 'bin still empty');
  assert.ok(log.warns.some(m => /NOT verified/.test(m) && /nothing deleted/.test(m)), 'clear warn');
  assert.strictEqual((await project.getSequences()).length, 1, 'nothing deleted');
});

test('moveItemToBin: executeTransaction returns false → false; throwing action → false', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence('YTUVI02_04_Lab');
  const bin = await binMove.ensureRootBin(project, '00_Source_Timelines', null);
  const item = await binMove.findSequenceProjectItem(project, seq, seq.name);

  const realTx = project.executeTransaction.bind(project);
  project.executeTransaction = function () { return false; };
  const r1 = await binMove.moveItemToBinDetailed(project, item, bin, mkLog());
  assert.strictEqual(r1.ok, false);
  assert.match(r1.reason, /returned false/);
  project.executeTransaction = realTx;

  project._rootItem.createMoveItemAction = function () { throw new Error('move denied'); };
  const r2 = await binMove.moveItemToBinDetailed(project, item, bin, mkLog());
  assert.strictEqual(r2.ok, false);
  assert.match(r2.reason, /move denied/);
  assert.ok(inRoot(project, item), 'still at root after both failures');
});

test('moveItemToBin: duplicate guard — a COPY (sequence count grows) is a failure, nothing deleted', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence('YTUVI02_05_Street');
  const bin = await binMove.ensureRootBin(project, '00_Source_Timelines', null);
  const item = await binMove.findSequenceProjectItem(project, seq, seq.name);
  const origMove = project._rootItem.createMoveItemAction.bind(project._rootItem);
  project._rootItem.createMoveItemAction = function (it, np) {
    const a = origMove(it, np);
    const apply = a.apply;
    a.apply = function () { apply(); project._sequences.push(new ppro._MockSequence(it.name)); };
    return a;
  };
  const r = await binMove.moveItemToBinDetailed(project, item, bin, mkLog());
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.duplicate, true, 'duplicate flagged');
  assert.strictEqual((await project.getSequences()).length, 2, 'the copy is left alone (never deletes)');
});

test('moveItemToBin: items without getId/guid are verified by name counts', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const bin = new ppro._MockFolderItem('00_Source_Timelines');
  const root = project._rootItem;
  const plain = { name: 'YTUVI02_06_Park', type: 1, _parent: root };
  root._items.push(bin, plain);
  const ok = await binMove.moveItemToBin(project, plain, bin, mkLog(), { guardSequences: false });
  assert.strictEqual(ok, true);
  assert.ok(bin._items.indexOf(plain) >= 0 && root._items.indexOf(plain) < 0);
});

test('ensureRootBin: existing bin reused, no duplicate createBinAction', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const existing = new ppro._MockFolderItem('00_Source_Timelines');
  project._rootItem._items.push(existing);
  ppro._recorder.reset();
  const bin = await binMove.ensureRootBin(project, '00_Source_Timelines', null);
  assert.strictEqual(bin, existing);
  assert.strictEqual(ppro._recorder.getCalls('FolderItem.createBinAction').length, 0);
});

test('collectTakenNames: sees sequences inside bins, not only root', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence('YTUVI02_5_Review_v6_tz_v1');
  const bin = await binMove.ensureRootBin(project, '05_Review', null);
  await binMove.moveItemToBin(project, seq._projectItem, bin, null);
  const taken = await binMove.collectTakenNames(project);
  assert.ok(taken['YTUVI02_5_Review_v6_tz_v1'], 'binned sequence name is taken');
});
