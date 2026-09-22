// shared/sourceTimelines (2026-09-15): scene timelines {CODE}_{NN}_{Scene} → 00_Source_Timelines.
const test = require('node:test');
const assert = require('node:assert');
const ppro = require('../mocks/premierepro');
const st = require('../../src/shared/sourceTimelines');
const { SOURCE_TIMELINES_BIN } = require('../../src/shared/constants');

const LOG = { info() {}, warn() {}, error() {}, debug() {} };

function binOf(project) {
  return project._rootItem._items.find(i => i && i.type === 2 && i.name === SOURCE_TIMELINES_BIN);
}
function rootNames(project) {
  return project._rootItem._items.filter(i => i && i.type !== 2).map(i => i.name);
}

test('constant: bin name is 00_Source_Timelines', () => {
  assert.strictEqual(SOURCE_TIMELINES_BIN, '00_Source_Timelines');
});

test('scene regex: two-digit scene index only', () => {
  const code = 'YTUVI02';
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_01_Studio', code), true, '01_Studio yes');
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_17_UviStore_Showcase_Broll', code), true);
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_18_SSEF_Commentary', code), true, 'SSEF scene 18 yes');
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_5_Review_v6_tz_v1', code), false, '5_Review_v6 no');
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_part_x', code), false, 'part_x no');
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_1_Ingest', code), false, 'single-digit stage no');
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_SSEF_sources_v1', code), false);
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_S01_short', code), false, 'shorts no');
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_A01_Studio', code), false, 'A-timeline no');
  assert.strictEqual(st.isSceneSequenceName('YTUVI02_100_Scene', code), false, 'three digits no');
  assert.strictEqual(st.isSceneSequenceName('YTUVI05_01_Studio', code), false, 'other project code no');
  assert.strictEqual(st.isSceneSequenceName('YTUVI05_01_Studio'), true, 'no code → generic YT prefix');
});

test('selectSceneSequences: picks 01_Studio, skips 5_Review_v6 and part_x', () => {
  const list = ['YTUVI02_01_Studio', 'YTUVI02_5_Review_v6_tz_v1', 'YTUVI02_part_x', 'YTUVI02_03_Cafe_Gem_Expert_Talk']
    .map(n => ({ name: n, seq: { name: n } }));
  const picked = st.selectSceneSequences(list, 'YTUVI02').map(e => e.name);
  assert.deepStrictEqual(picked, ['YTUVI02_01_Studio', 'YTUVI02_03_Cafe_Gem_Expert_Talk']);
});

test('hideSourceTimelines: moves root scene timelines, leaves stage ones, idempotent', async () => {
  const project = new ppro._MockProject('YTUVI02');
  for (const n of ['YTUVI02_01_Studio', 'YTUVI02_03_Cafe_Gem_Expert_Talk', 'YTUVI02_17_UviStore_Showcase_Broll',
    'YTUVI02_5_Review_v6_tz_v1', 'YTUVI02_part_Hook']) {
    await project.createSequence(n);
  }
  const r = await st.hideSourceTimelines(project, 'YTUVI02', LOG);
  assert.strictEqual(r.total, 3);
  assert.strictEqual(r.moved, 3);
  assert.strictEqual(r.already, 0);
  assert.strictEqual(r.failed, 0);
  assert.strictEqual(r.stopped, null);
  const bin = binOf(project);
  assert.ok(bin, 'bin at project root');
  assert.deepStrictEqual(bin._items.map(i => i.name).sort(),
    ['YTUVI02_01_Studio', 'YTUVI02_03_Cafe_Gem_Expert_Talk', 'YTUVI02_17_UviStore_Showcase_Broll']);
  assert.deepStrictEqual(rootNames(project).sort(), ['YTUVI02_5_Review_v6_tz_v1', 'YTUVI02_part_Hook'], 'stage timelines stay at root');
  assert.strictEqual((await project.getSequences()).length, 5, 'no copies, nothing deleted');
  assert.strictEqual(st.formatHideReport(r), 'moved 3 · already in bin 0 · failed 0');

  // second run: nothing to move, counts as already in bin, no new bin
  ppro._recorder.reset();
  const r2 = await st.hideSourceTimelines(project, 'YTUVI02', LOG);
  assert.strictEqual(r2.moved, 0);
  assert.strictEqual(r2.already, 3);
  assert.strictEqual(ppro._recorder.getCalls('FolderItem.createBinAction').length, 0, 'bin not re-created');
  assert.strictEqual(ppro._recorder.getCalls('FolderItem.createMoveItemAction').length, 0);
});

test('hideSourceTimelines: probe-first — an unverified first move stops the batch', async () => {
  const project = new ppro._MockProject('YTUVI02');
  for (const n of ['YTUVI02_01_Studio', 'YTUVI02_02_Street', 'YTUVI02_03_Cafe']) await project.createSequence(n);
  project._rootItem.createMoveItemAction = function () { return { type: 'noop' }; };   // silent no-op
  const r = await st.hideSourceTimelines(project, 'YTUVI02', LOG);
  assert.strictEqual(r.moved, 0);
  assert.strictEqual(r.failed, 1, 'only the probe was attempted');
  assert.match(r.stopped, /first move not verified/);
  assert.strictEqual(rootNames(project).length, 3, 'all still at root');
});

test('hideSourceTimelines: a sequence already filed in another bin is skipped, not moved', async () => {
  const project = new ppro._MockProject('YTUVI02');
  const seq = await project.createSequence('YTUVI02_01_Studio');
  const other = new ppro._MockFolderItem('My_Bin');
  project._rootItem._items.push(other);
  const pi = seq._projectItem;
  project._rootItem._items.splice(project._rootItem._items.indexOf(pi), 1);
  other._items.push(pi); pi._parent = other;
  const r = await st.hideSourceTimelines(project, 'YTUVI02', LOG);
  assert.strictEqual(r.skipped, 1);
  assert.strictEqual(r.moved, 0);
  assert.ok(other._items.indexOf(pi) >= 0, 'left in the user bin');
});

test('fileBuiltSceneSequences: only scene timelines of the build are filed', async () => {
  const project = new ppro._MockProject('YTCR03');
  const s1 = await project.createSequence('YTCR03_03_developer_meeting');
  const s2 = await project.createSequence('YTCR03_1_Ingest');
  const res = await st.fileBuiltSceneSequences(project, [
    { name: s1.name, seq: s1 }, { name: s2.name, seq: s2 }
  ], 'YTCR03', LOG);
  assert.deepStrictEqual(res, { moved: 1, failed: 0, considered: 1 });
  assert.deepStrictEqual(binOf(project)._items.map(i => i.name), ['YTCR03_03_developer_meeting']);
  assert.deepStrictEqual(rootNames(project), ['YTCR03_1_Ingest']);
});
