const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const {
  buildPresetXml,
  readPresetTracks,
  ticksPerFrame,
  TICKS_PER_SECOND,
} = require('../../../src/ingest/placement/sequencePreset');

/** Стоковый пресет Premiere — если он на месте, проверяем и на нём тоже. */
const STOCK = '/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app'
  + '/Contents/Settings/SequencePresets/UHD (4K)/UHD (4K) 2160p 25 fps.sqpreset';
const stockXml = fs.existsSync(STOCK) ? fs.readFileSync(STOCK, 'utf8') : null;

test('пресет: рождает ровно столько аудиодорожек, сколько просили', () => {
  const xml = buildPresetXml(null, { aTracks: 12, vTracks: 1 });
  const { audio, videoCount } = readPresetTracks(xml);
  assert.strictEqual(audio.length, 12);
  assert.strictEqual(videoCount, 1);
});

test('пресет: КАЖДАЯ аудиодорожка таргетирована — ради этого он и нужен', () => {
  const xml = buildPresetXml(null, { aTracks: 12 });
  const { audio } = readPresetTracks(xml);
  assert.ok(audio.every(t => t.mTargeted === true), 'цель обязана стоять на всех');
});

test('пресет: sync lock снят, замок снят', () => {
  const xml = buildPresetXml(null, { aTracks: 4 });
  const { audio } = readPresetTracks(xml);
  assert.ok(audio.every(t => t.mSyncLock === false), 'ход Synchronize не должен тянуть соседей');
  assert.ok(audio.every(t => t.mLocked === false));
});

test('пресет: fps и кадр пишутся тиками, а не числом кадров', () => {
  const xml = buildPresetXml(null, { aTracks: 2, fps: 25 });
  const m = xml.match(/<VideoFrameRate>(\d+)<\/VideoFrameRate>/);
  assert.strictEqual(parseInt(m[1], 10), ticksPerFrame(25));
  assert.strictEqual(ticksPerFrame(25), TICKS_PER_SECOND / 25);
});

test('пресет: 29,97 кадра остаётся рациональным, а не 30', () => {
  const tpf = ticksPerFrame(30000 / 1001);
  assert.strictEqual(tpf, Math.round(TICKS_PER_SECOND * 1001 / 30000));
  assert.notStrictEqual(tpf, TICKS_PER_SECOND / 30);
});

test('пресет: размер кадра и частота дискретизации подставляются', () => {
  const xml = buildPresetXml(null, { aTracks: 2, width: 3840, height: 2160, sampleRate: 48000 });
  assert.ok(/<VideoFrameSize>0,0,3840,2160<\/VideoFrameSize>/.test(xml));
  const m = xml.match(/<AudioFrameRate>(\d+)<\/AudioFrameRate>/);
  assert.strictEqual(parseInt(m[1], 10), Math.round(TICKS_PER_SECOND / 48000));
});

test('пресет: мусор на входе не роняет генератор — берётся запасной шаблон', () => {
  const xml = buildPresetXml('это не пресет', { aTracks: 3 });
  const { audio } = readPresetTracks(xml);
  assert.strictEqual(audio.length, 3);
  assert.ok(audio.every(t => t.mTargeted === true));
});

test('пресет: блок VideoTracks остаётся пустым', () => {
  // ⚠️ Подорожечных настроек у видео в пресете нет — если однажды появятся,
  // этот тест упадёт, и решение «стенд живёт на аудио» надо будет пересмотреть.
  const xml = buildPresetXml(stockXml, { aTracks: 5 });
  assert.ok(/<VideoTracks>\[\]<\/VideoTracks>/.test(xml));
});

if (stockXml) {
  test('пресет: на стоковом файле Premiere шаблон дорожки берётся из него', () => {
    const before = JSON.parse(stockXml.match(/<AudioTracks>([\s\S]*?)<\/AudioTracks>/)[1]);
    assert.ok(before.length > 0 && before[0].mTargeted === false,
      'у стокового пресета цели выключены — иначе вся затея не нужна');
    const xml = buildPresetXml(stockXml, { aTracks: 12, vTracks: 1, fps: 25 });
    const { audio, videoCount } = readPresetTracks(xml);
    assert.strictEqual(audio.length, 12);
    assert.strictEqual(videoCount, 1);
    assert.ok(audio.every(t => t.mTargeted === true));
    // поля, которых мы не касались, должны уцелеть байт-в-байт
    for (const key of Object.keys(before[0])) {
      if (['mTargeted', 'mSyncLock', 'mLocked', 'mTrackID'].includes(key)) continue;
      assert.deepStrictEqual(audio[0][key], before[0][key], `поле ${key} потеряно`);
    }
  });

  test('пресет: остальной XML стокового файла не покорёжен', () => {
    const xml = buildPresetXml(stockXml, { aTracks: 4 });
    assert.ok(xml.includes('<EditingModeGUID.Mac>'), 'режим монтажа обязан уцелеть');
    assert.ok(xml.trim().endsWith('</PremiereData>'));
  });
}
