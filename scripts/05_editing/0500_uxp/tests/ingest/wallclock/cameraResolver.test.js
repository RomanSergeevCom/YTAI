const { test } = require('node:test');
const assert = require('node:assert');
const {
  CAM_PRIORITY,
  camFromPath,
  deriveCamLayers,
  invertCamLayers,
} = require('../../../src/ingest/layout/cameraResolver');

test('cameraResolver: CAM_PRIORITY order', () => {
  assert.deepStrictEqual(CAM_PRIORITY, ['FX3', 'DJI', 'FX3A', 'iPhone', 'screen_recording']);
});

test('camFromPath: extracts parent folder name', () => {
  assert.strictEqual(
    camFromPath('/Volumes/T9/YTCR03/01_Source/Video/03_developer_meeting/DJI/file.MP4'),
    'DJI'
  );
  assert.strictEqual(
    camFromPath('/a/b/04_with_wife/iPhone/IMG_2868.MOV'),
    'iPhone'
  );
  assert.strictEqual(camFromPath(''), '');
  assert.strictEqual(camFromPath('/single'), '');
});

test('camFromPath: handles trailing slash and Windows separators', () => {
  assert.strictEqual(camFromPath('/a/b/FX3/file.MP4/'), 'FX3');
  assert.strictEqual(camFromPath('C:\\a\\b\\FX3A\\file.MP4'), 'FX3A');
});

test('deriveCamLayers: explicit override wins', () => {
  const layers = deriveCamLayers(
    [{ path: '/a/FX3/x.MP4' }, { path: '/a/iPhone/y.MOV' }],
    ['iPhone', 'FX3']  // intentionally reverse priority
  );
  assert.deepStrictEqual(layers, { iPhone: 0, FX3: 1 });
});

test('deriveCamLayers: 1-cam scene', () => {
  const clips = [
    { path: '/a/05_property_tour/FX3A/clip1.MP4' },
    { path: '/a/05_property_tour/FX3A/clip2.MP4' },
  ];
  assert.deepStrictEqual(deriveCamLayers(clips), { FX3A: 0 });
});

test('deriveCamLayers: 2-cam scene (DJI+iPhone) → DJI on V1, iPhone on V2', () => {
  const clips = [
    { path: '/a/03_developer_meeting/DJI/d1.MP4' },
    { path: '/a/03_developer_meeting/DJI/d2.MP4' },
    { path: '/a/03_developer_meeting/iPhone/i1.MOV' },
  ];
  // Priority: DJI (idx 1) before iPhone (idx 3) in CAM_PRIORITY
  assert.deepStrictEqual(deriveCamLayers(clips), { DJI: 0, iPhone: 1 });
});

test('deriveCamLayers: 3-cam scene (FX3+FX3A+iPhone) — S04 case', () => {
  const clips = [
    ...Array(23).fill({ path: '/a/04_with_wife/FX3/x.MP4' }),
    ...Array(17).fill({ path: '/a/04_with_wife/FX3A/y.MP4' }),
    ...Array(7).fill({ path: '/a/04_with_wife/iPhone/z.MOV' }),
  ];
  assert.deepStrictEqual(deriveCamLayers(clips), { FX3: 0, FX3A: 1, iPhone: 2 });
});

test('deriveCamLayers: unknown cam falls to end alphabetically', () => {
  const clips = [
    { path: '/a/scene/FX3/x.MP4' },
    { path: '/a/scene/UnknownCamA/y.MP4' },
    { path: '/a/scene/UnknownCamB/z.MP4' },
  ];
  const layers = deriveCamLayers(clips);
  assert.strictEqual(layers.FX3, 0);
  assert.strictEqual(layers.UnknownCamA, 1);
  assert.strictEqual(layers.UnknownCamB, 2);
});

test('deriveCamLayers: empty clips → empty map', () => {
  assert.deepStrictEqual(deriveCamLayers([]), {});
  assert.deepStrictEqual(deriveCamLayers(null), {});
});

test('invertCamLayers: round-trip', () => {
  const layers = { FX3: 0, FX3A: 1, iPhone: 2 };
  assert.deepStrictEqual(invertCamLayers(layers), { 0: 'FX3', 1: 'FX3A', 2: 'iPhone' });
});
