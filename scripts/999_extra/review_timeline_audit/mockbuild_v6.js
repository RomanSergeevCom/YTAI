// Прогон YTUVI01_review_v6.json через реальный partsBuilder на mock-ppro (как smoke-тесты панели):
// ловит ошибки схемы/раскладки ДО сборки в Premiere. usage: node mockbuild_v6.js [path-to-json]
const path = require('path');
const fs = require('fs');
const UXP = path.join(process.env.HOME, 'YTAI/scripts/05_editing/0500_uxp');
const ppro = require(path.join(UXP, 'tests/mocks/premierepro'));
const { buildPartSequence } = require(path.join(UXP, 'src/parts/partsBuilder'));

const jsonPath = process.argv[2] || '/Volumes/T7-Blue-2-RYA/YTUVI-Projects/YTUVI01_Corundum_Ruby/00_Setup/05_Review/YTUVI01_review_v6.json';
const doc = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
const part = doc.part;
const segs = doc.segments;

function mkClip(name, dur, still) {
  const c = new ppro._MockClipProjectItem(name, '/abs/' + name);
  c._durationSec = dur || 60;
  if (still) c._isStill = true;
  return c;
}
const project = new ppro._MockProject(part.code);
const base = mkClip(part.base_clip, 2440.48);
project._rootItem._items.push(base);
const clipMap = { [part.base_clip]: base };
for (const s of segs) {
  if (clipMap[s.source_file]) continue;
  const still = /\.(png|jpe?g)$/i.test(s.source_file);
  const c = mkClip(s.source_file, still ? 5 : 600, still);
  project._rootItem._items.push(c);
  clipMap[s.source_file] = c;
  clipMap[s.clip_id] = c;
}
const logs = { info: [], warn: [], error: [], debug: [] };
const LOG = { info: (m) => logs.info.push(m), warn: (m) => logs.warn.push(m), error: (m) => logs.error.push(m), debug: (m) => logs.debug.push(m) };

(async () => {
  const t0 = Date.now();
  const result = await buildPartSequence(project, clipMap, part, segs, LOG, {});
  const dt = Date.now() - t0;
  console.log(`built: sequence=${result && result.sequence ? result.sequence.name : null} placed=${result.placed} skipped=${result.skipped} in ${dt} ms`);
  console.log(`log: info ${logs.info.length} · warn ${logs.warn.length} · error ${logs.error.length}`);
  logs.error.slice(0, 20).forEach((m) => console.log('  ERROR', m));
  logs.warn.slice(0, 20).forEach((m) => console.log('  WARN ', m));
  const im = logs.debug.filter((m) => /item_marker/.test(m)).length + logs.info.filter((m) => /item_marker/.test(m)).length + logs.warn.filter((m) => /item_marker/.test(m)).length;
  console.log(`item_marker log lines: ${im} (segments with item_marker: ${segs.filter((s) => s.item_marker).length})`);
  const bad = segs.filter((s) => s.timeline_out_sec <= s.timeline_in_sec || s.source_out_sec <= s.source_in_sec);
  console.log(`degenerate segments: ${bad.length}`);
  process.exit(result && result.sequence && result.placed === segs.length && logs.error.length === 0 ? 0 : 1);
})().catch((e) => { console.error('THROW', e); process.exit(2); });
