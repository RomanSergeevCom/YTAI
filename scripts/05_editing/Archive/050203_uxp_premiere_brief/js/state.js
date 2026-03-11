/* state.js — Global state, event bus, color mappings
   UXP: NO require/module.exports — all globals via window */

console.log('[YTAI] state.js loading...');

/* ── Application state ── */
var APP = {
  brief: null,
  segments: [],
  blocks: [],
  decisions: {},
  activeSegmentId: null,
  filter: 'all',
  searchQuery: '',
  viewMode: 'text',
  buildStatus: 'idle',
  sourceFolderEntry: null,
  sourceFolderToken: null,
  briefFileToken: null,
  briefFileEntry: null,
  projectName: '',
  projectSettings: null,
  transcriptionDir: '',
  logEntries: [],
  _timelinePositions: {},
  _transcriptData: {},
  _wordCuts: {},
  _wordSelection: { segId: null, startIdx: null, endIdx: null },
  activeTimeline: 'rough',
  _fullTimelinePositions: {},
  _roughTimelinePositions: {},
};

/* ── Color map matching Premiere Pro label colors ── */
var COLOR_MAP = {
  Green:   { hex: '#4CAF50', dark: '#2E7D32', premiereIndex: 2, label: 'Hook / Intro / CTA' },
  Blue:    { hex: '#4A90D9', dark: '#2A5A8A', premiereIndex: 1, label: 'Education' },
  Cyan:    { hex: '#00CED1', dark: '#00807E', premiereIndex: 0, label: 'Context' },
  Yellow:  { hex: '#E6C619', dark: '#9E8A00', premiereIndex: 3, label: 'Warnings' },
  Orange:  { hex: '#EDA63B', dark: '#B87A20', premiereIndex: 6, label: 'Stories' },
  Red:     { hex: '#E34850', dark: '#A3282E', premiereIndex: 4, label: 'Risks' },
  Magenta: { hex: '#E732E7', dark: '#8E1E8E', premiereIndex: 5, label: 'Technical' },
  Purple:  { hex: '#9B59B6', dark: '#6A3D7D', premiereIndex: 7, label: 'Solutions' },
};

function getColorHex(name)  { return (COLOR_MAP[name] || COLOR_MAP.Cyan).hex; }
function getColorDark(name) { return (COLOR_MAP[name] || COLOR_MAP.Cyan).dark; }

console.log('[YTAI] state.js: APP created, COLOR_MAP ready');

/* ── Event bus ── */
var BUS = {
  _l: {},
  on(ev, fn) { (this._l[ev] = this._l[ev] || []).push(fn); },
  off(ev, fn) { if (this._l[ev]) this._l[ev] = this._l[ev].filter(f => f !== fn); },
  emit(ev, data) {
    (this._l[ev] || []).forEach(fn => {
      try { fn(data); } catch (e) { console.error('[BUS ' + ev + ']', e); }
    });
  },
};

/* ── Logger ── */
function appLog(msg, level) {
  level = level || 'info';
  var ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
  var entry = { ts: ts, msg: msg, level: level };
  APP.logEntries.push(entry);
  if (APP.logEntries.length > 300) APP.logEntries.shift();
  BUS.emit('log', entry);
  if (level === 'error') { console.error('[YTAI] ' + msg); }
  else { console.log('[YTAI] ' + msg); }
}
