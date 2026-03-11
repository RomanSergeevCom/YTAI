/* review.js — Decision handling, progress, segment navigation
   UXP: uses globals APP, BUS, appLog from state.js */

console.log('[YTAI] review.js loading...');

var HOTKEY_MAP = { u: 'use', c: 'cut', m: 'maybe', s: 'shorts' };

/* ── Decide ── */
function decide(segId, decision) {
  if (!segId) return;
  var prev = APP.decisions[segId];
  if (prev === decision) {
    delete APP.decisions[segId];
    appLog(segId + ': cleared');
  } else {
    APP.decisions[segId] = decision;
    appLog(segId + ': ' + decision);
  }
  BUS.emit('decision-changed', { segId: segId, decision: APP.decisions[segId] || null });
}

/* ── Progress ── */
function getProgress() {
  var total = APP.segments.length;
  var use = 0, cut = 0, maybe = 0, shorts = 0;
  var vals = Object.values(APP.decisions);
  for (var i = 0; i < vals.length; i++) {
    if (vals[i] === 'use')    use++;
    else if (vals[i] === 'cut')    cut++;
    else if (vals[i] === 'maybe')  maybe++;
    else if (vals[i] === 'shorts') shorts++;
  }
  var decided = use + cut + maybe + shorts;
  var pct = total > 0 ? Math.round(decided / total * 100) : 0;

  var totalDuration = 0, selectedDuration = 0;
  for (var j = 0; j < APP.segments.length; j++) {
    var seg = APP.segments[j];
    totalDuration += seg.duration;
    var dec = APP.decisions[seg.id];
    if (dec === 'use' || dec === 'shorts') selectedDuration += seg.duration;
  }

  return {
    total: total, decided: decided,
    use: use, cut: cut, maybe: maybe, shorts: shorts,
    pct: pct,
    totalDuration: totalDuration, selectedDuration: selectedDuration
  };
}

/* ── Hotkeys ── */
function handleReviewHotkey(key) {
  var k = key.toLowerCase();
  if (HOTKEY_MAP[k] && APP.activeSegmentId) {
    decide(APP.activeSegmentId, HOTKEY_MAP[k]);
    return true;
  }
  return false;
}

/* ── Navigation ── */
function navigateSegment(direction) {
  var filtered = getFilteredSegments();
  if (filtered.length === 0) return;

  var idx = -1;
  for (var i = 0; i < filtered.length; i++) {
    if (filtered[i].id === APP.activeSegmentId) { idx = i; break; }
  }

  var next;
  if (direction === 'next') {
    next = idx < filtered.length - 1 ? idx + 1 : 0;
  } else {
    next = idx > 0 ? idx - 1 : filtered.length - 1;
  }

  APP.activeSegmentId = filtered[next].id;
  BUS.emit('active-changed', { segId: APP.activeSegmentId });
}

/* ── Filter ── */
function getFilteredSegments() {
  var segs = APP.segments;

  if (APP.filter !== 'all') {
    segs = segs.filter(function (s) {
      return APP.decisions[s.id] === APP.filter;
    });
  }

  if (APP.searchQuery) {
    var q = APP.searchQuery.toLowerCase();
    segs = segs.filter(function (s) {
      return (s.transcript && s.transcript.toLowerCase().indexOf(q) >= 0) ||
             (s.speaker && s.speaker.toLowerCase().indexOf(q) >= 0) ||
             (s.segmentName && s.segmentName.toLowerCase().indexOf(q) >= 0) ||
             (s.id && s.id.toLowerCase().indexOf(q) >= 0) ||
             (s.notes && s.notes.toLowerCase().indexOf(q) >= 0);
    });
  }

  return segs;
}

/* ── Chapters ── */
function getChapters() {
  var chapters = [];
  var pos = 0;
  for (var i = 0; i < APP.segments.length; i++) {
    var seg = APP.segments[i];
    var dec = APP.decisions[seg.id];
    var isUsed = dec === 'use' || dec === 'shorts';
    if (seg.isChapter && isUsed) {
      chapters.push({ time: formatDuration(pos), name: seg.blockName, segId: seg.id });
    }
    if (isUsed) pos += seg.duration;
  }
  return chapters;
}

/* Global namespace */
var REVIEW = {
  decide: decide,
  getProgress: getProgress,
  handleReviewHotkey: handleReviewHotkey,
  navigateSegment: navigateSegment,
  getFilteredSegments: getFilteredSegments,
  getChapters: getChapters,
};

console.log('[YTAI] review.js loaded OK. REVIEW =', typeof REVIEW);
