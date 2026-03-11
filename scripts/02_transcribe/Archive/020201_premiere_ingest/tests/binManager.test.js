const { describe, it, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const ppro = require('./mocks/premierepro');
const { createBinStructure, BIN_NAMES } = require('../src/binManager');
const { Logger } = require('../src/logger');

describe('BIN_NAMES', () => {
  it('defines expected bin names', () => {
    assert.equal(BIN_NAMES.SOURCE, '00_Source');
    assert.equal(BIN_NAMES.SEQUENCE, '01_Sequence');
    assert.equal(BIN_NAMES.TRANSCRIPTS, '02_Transcripts');
  });

  it('has exactly 3 bins', () => {
    assert.equal(Object.keys(BIN_NAMES).length, 3);
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
    assert.ok(bins[BIN_NAMES.SEQUENCE]);
    assert.ok(bins[BIN_NAMES.TRANSCRIPTS]);
  });

  it('calls createBinAction for each bin', async () => {
    await createBinStructure(project, logger);

    const binCalls = ppro._recorder.getCalls('FolderItem.createBinAction');
    assert.equal(binCalls.length, 3);

    const binNames = binCalls.map(c => c.args[0]);
    assert.ok(binNames.includes('00_Source'));
    assert.ok(binNames.includes('01_Sequence'));
    assert.ok(binNames.includes('02_Transcripts'));
  });

  it('wraps in lockedAccess and executeTransaction', async () => {
    await createBinStructure(project, logger);

    const lockCalls = ppro._recorder.getCalls('Project.lockedAccess');
    const txCalls = ppro._recorder.getCalls('Project.executeTransaction');

    assert.ok(lockCalls.length > 0, 'Should use lockedAccess');
    assert.ok(txCalls.length > 0, 'Should use executeTransaction');
  });

  it('logs bin creation', async () => {
    await createBinStructure(project, logger);
    const logEntries = logger.getBuffer();
    assert.ok(logEntries.some(e => e.includes('00_Source')));
    assert.ok(logEntries.some(e => e.includes('01_Sequence')));
    assert.ok(logEntries.some(e => e.includes('02_Transcripts')));
  });

  it('returns bin references by name', async () => {
    const bins = await createBinStructure(project, logger);
    assert.equal(Object.keys(bins).length, 3);
  });

  it('bins are added to project root', async () => {
    await createBinStructure(project, logger);
    const rootItem = await project.getRootItem();
    const items = await rootItem.getItems();

    const binNames = items.map(i => i.name);
    assert.ok(binNames.includes('00_Source'));
    assert.ok(binNames.includes('01_Sequence'));
    assert.ok(binNames.includes('02_Transcripts'));
  });
});
