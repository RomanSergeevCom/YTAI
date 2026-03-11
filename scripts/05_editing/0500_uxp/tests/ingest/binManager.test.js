const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('../mocks/premierepro');
const { createBinStructure, BIN_NAMES } = require('../../src/ingest/binManager');
const { Logger } = require('../../src/shared/logger');

describe('BIN_NAMES', () => {
  it('defines expected bin names', () => {
    assert.equal(BIN_NAMES.SOURCE, '00_Source');
    assert.equal(BIN_NAMES.TRANSCRIPTS, '02_Transcripts');
  });

  it('has exactly 2 bins', () => {
    assert.equal(Object.keys(BIN_NAMES).length, 2);
  });
});

describe('createBinStructure', () => {
  let project;
  let logger;

  beforeEach(() => {
    ppro._recorder.reset();
    project = new ppro._MockProject('TestProject');
    logger = new Logger();
  });

  it('creates all required bins', async () => {
    const bins = await createBinStructure(project, logger);

    assert.ok(bins[BIN_NAMES.SOURCE]);
    assert.ok(bins[BIN_NAMES.TRANSCRIPTS]);
  });

  it('calls createBinAction for each bin', async () => {
    await createBinStructure(project, logger);

    const binCalls = ppro._recorder.getCalls('FolderItem.createBinAction');
    assert.equal(binCalls.length, 2);

    const binNames = binCalls.map(c => c.args[0]);
    assert.ok(binNames.includes('00_Source'));
    assert.ok(binNames.includes('02_Transcripts'));
  });

  it('wraps in lockedAccess and executeTransaction', async () => {
    await createBinStructure(project, logger);

    const lockCalls = ppro._recorder.getCalls('Project.lockedAccess');
    const txCalls = ppro._recorder.getCalls('Project.executeTransaction');

    assert.ok(lockCalls.length > 0, 'Should use lockedAccess');
    assert.ok(txCalls.length > 0, 'Should use executeTransaction');
  });

  it('returns bin references by name', async () => {
    const bins = await createBinStructure(project, logger);
    assert.equal(Object.keys(bins).length, 2);
  });

  it('bins are added to project root', async () => {
    await createBinStructure(project, logger);
    const rootItem = await project.getRootItem();
    const items = await rootItem.getItems();

    const binNames = items.map(i => i.name);
    assert.ok(binNames.includes('00_Source'));
    assert.ok(binNames.includes('02_Transcripts'));
  });
});
