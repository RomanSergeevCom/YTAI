/* index.js — Main controller: rendering, events, hotkeys
   UXP: uses globals APP, BUS, appLog, getColorHex, getColorDark, COLOR_MAP
   IO, REVIEW, NAV, BUILD from earlier scripts */

console.log('[YTAI] index.js loading...');
console.log('[YTAI] index.js: checking globals...');
console.log('[YTAI]   APP =', typeof APP);
console.log('[YTAI]   BUS =', typeof BUS);
console.log('[YTAI]   IO  =', typeof IO);
console.log('[YTAI]   REVIEW =', typeof REVIEW);
console.log('[YTAI]   NAV =', typeof NAV);
console.log('[YTAI]   BUILD =', typeof BUILD);
console.log('[YTAI]   appLog =', typeof appLog);
console.log('[YTAI]   COLOR_MAP =', typeof COLOR_MAP);

/* ── DOM refs ── */
function $(id) { return document.getElementById(id); }

var segListEl, emptyEl, statsBar, chapterBar, searchFilters, settingsPanel, buildPanel, logPanel, debugOverlay;

function initDomRefs() {
  segListEl     = $('segment-list');
  emptyEl       = $('empty-state');
  statsBar      = $('stats-bar');
  chapterBar    = $('chapter-bar');
  searchFilters = $('search-filters');
  settingsPanel = $('settings-panel');
  buildPanel    = $('build-panel');
  logPanel      = $('log-panel');
  debugOverlay  = $('debug-overlay');
}

/* ══════════════════════════════
   RENDERING
   ══════════════════════════════ */

function renderAll() {
  if (APP.segments.length === 0) {
    emptyEl.style.display = 'flex';
    statsBar.style.display = 'none';
    chapterBar.style.display = 'none';
    searchFilters.style.display = 'none';
    segListEl.innerHTML = '';
    segListEl.appendChild(emptyEl);
    return;
  }

  emptyEl.style.display = 'none';
  statsBar.style.display = 'flex';
  chapterBar.style.display = 'flex';
  searchFilters.style.display = 'flex';

  $('btn-save').disabled = false;
  $('btn-reload').disabled = false;
  $('btn-build').disabled = false;
  $('btn-transcripts').disabled = false;

  renderStats();
  renderChapterBar();

  if (APP.viewMode === 'text') {
    renderTextView();
  } else {
    renderBlocks();
  }
}

function renderStats() {
  var p = REVIEW.getProgress();
  $('stat-selected').textContent  = IO.formatDuration(p.selectedDuration);
  $('stat-total').textContent     = IO.formatDuration(p.totalDuration);
  $('stat-segments').textContent  = (p.use + p.shorts) + '/' + p.total;
  $('stat-blocks').textContent    = String(APP.blocks.length);
  $('stat-chapters').textContent  = String(REVIEW.getChapters().length);
  $('stat-progress-pct').textContent = String(p.pct);
  $('progress-fill').style.width  = p.pct + '%';
}

function renderChapterBar() {
  var totalDur = 0;
  APP.segments.forEach(function (s) { totalDur += s.duration; });
  if (totalDur === 0) { chapterBar.innerHTML = ''; return; }

  var html = '';
  APP.blocks.forEach(function (block) {
    var pct = (block.totalDuration / totalDur * 100).toFixed(1);
    var color = getColorDark(block.color);
    html += '<div class="chapter-block" data-block="' + block.id + '" style="width:' + pct + '%; background:' + color + ';" title="' + esc(block.name) + ' (' + IO.formatDuration(block.totalDuration) + ')">' + esc(block.name) + '</div>';
  });
  chapterBar.innerHTML = html;
}

/* ── Card View (default) ── */

function renderBlocks() {
  var filtered = REVIEW.getFilteredSegments();
  var filteredIds = {};
  filtered.forEach(function (s) { filteredIds[s.id] = true; });
  var html = '';

  APP.blocks.forEach(function (block) {
    var visibleSegs = block.segments.filter(function (s) { return filteredIds[s.id]; });
    if (visibleSegs.length === 0 && APP.filter !== 'all') return;

    var color = getColorDark(block.color);
    var usedCount = 0;
    block.segments.forEach(function (s) {
      var d = APP.decisions[s.id];
      if (d === 'use' || d === 'shorts') usedCount++;
    });

    html += '<div class="block" data-block="' + block.id + '">';
    html += '<div class="block-header" data-block-toggle="' + block.id + '" style="background:' + color + ';">';
    html += '<span class="block-arrow">\u25BC</span> ';
    html += 'Block ' + block.id + ': ' + esc(block.name);
    html += '<span class="block-meta">' + usedCount + '/' + block.segments.length + ' \u00B7 ' + IO.formatDuration(block.usedDuration) + '</span>';
    html += '</div>';
    html += '<div class="block-segments">';

    var segsToRender = APP.filter === 'all' ? block.segments : visibleSegs;
    segsToRender.forEach(function (seg) {
      html += renderSegment(seg);
    });

    html += '</div></div>';
  });

  segListEl.innerHTML = html;
}

function renderSegment(seg) {
  var dec = APP.decisions[seg.id];
  var isActive = seg.id === APP.activeSegmentId;
  var isSkip = dec === 'cut' || (!dec && !seg.use);
  var colorHex = getColorHex(seg.color);

  var cls = 'segment-card';
  if (isActive) cls += ' active';
  if (isSkip) cls += ' seg-skip';

  var h = '<div class="' + cls + '" data-seg="' + seg.id + '">';
  h += '<div class="seg-stripe" style="background:' + colorHex + ';"></div>';
  h += '<div class="seg-body">';

  /* Header row */
  h += '<div class="seg-header">';
  h += '<span class="seg-id">' + esc(seg.id) + '</span>';
  if (seg.segmentName) h += '<span class="seg-name">' + esc(truncate(seg.segmentName, 40)) + '</span>';
  if (seg.speaker) h += '<span class="seg-speaker">' + esc(seg.speaker) + '</span>';
  h += '<span class="seg-timecode" data-tc="' + seg.id + '" title="Jump to ' + seg.tcIn + '">' + esc(seg.tcIn) + ' \u2192 ' + esc(seg.tcOut) + '</span>';
  h += '<span class="seg-duration">' + Math.round(seg.duration) + 's</span>';
  if (seg.isChapter) h += '<span class="badge badge-chapter">CH</span>';
  if (seg.priority > 1) h += '<span class="badge badge-alt">ALT ' + seg.priority + '</span>';
  h += '</div>';

  /* Transcript */
  if (seg.transcript) {
    h += '<div class="seg-text">' + esc(truncate(seg.transcript, 200)) + '</div>';
  }

  /* Decision buttons */
  h += '<div class="seg-decisions">';
  h += decBtn(seg.id, 'use',    'U', dec);
  h += decBtn(seg.id, 'cut',    'C', dec);
  h += decBtn(seg.id, 'maybe',  '?', dec);
  h += decBtn(seg.id, 'shorts', 'S', dec);
  h += '</div>';

  /* Meta */
  if (seg.brollNote || seg.notes) {
    h += '<div class="seg-meta">';
    if (seg.brollNote) h += '<span class="meta-broll">B-roll: ' + esc(truncate(seg.brollNote, 80)) + '</span>';
    if (seg.notes) h += '<span class="meta-notes">' + esc(truncate(seg.notes, 100)) + '</span>';
    h += '</div>';
  }

  h += '</div></div>';
  return h;
}

/* ── Text-Based Editing View ── */

function renderTextView() {
  var filtered = REVIEW.getFilteredSegments();
  var filteredIds = {};
  filtered.forEach(function (s) { filteredIds[s.id] = true; });

  var html = '<div class="text-view">';

  APP.blocks.forEach(function (block) {
    var visibleSegs = block.segments.filter(function (s) { return filteredIds[s.id]; });
    if (visibleSegs.length === 0 && APP.filter !== 'all') return;

    var color = getColorHex(block.color);
    var colorDark = getColorDark(block.color);

    /* Block header */
    html += '<div class="text-block" data-block="' + block.id + '">';
    html += '<div class="text-block-header" style="border-left-color:' + color + '; background:' + colorDark + ';">';
    html += '<span class="text-block-name">' + esc(block.name) + '</span>';
    html += '<span class="text-block-meta">' + block.segments.length + ' segments \u00B7 ' + IO.formatDuration(block.totalDuration) + '</span>';
    html += '</div>';

    /* Text segments */
    var segsToRender = APP.filter === 'all' ? block.segments : visibleSegs;
    segsToRender.forEach(function (seg) {
      html += renderTextSegment(seg, color);
    });

    html += '</div>';
  });

  html += '</div>';
  segListEl.innerHTML = html;
}

function renderTextSegment(seg, blockColor) {
  var dec = APP.decisions[seg.id];
  var isActive = seg.id === APP.activeSegmentId;
  var isSkip = dec === 'cut' || (!dec && !seg.use);
  /* In FULL timeline mode, CUT segments are valid — don't mute them */
  var isFull = APP.activeTimeline === 'full';

  var cls = 'text-segment';
  if (isActive) cls += ' active';
  if (dec === 'use')    cls += ' text-seg-use';
  if (dec === 'cut')    cls += (isFull ? ' text-seg-cut-full' : ' text-seg-cut');
  if (dec === 'maybe')  cls += ' text-seg-maybe';
  if (dec === 'shorts') cls += ' text-seg-shorts';
  if (isSkip && !dec)   cls += (isFull ? ' text-seg-cut-full' : ' text-seg-unreviewed');

  var h = '<div class="' + cls + '" data-seg="' + seg.id + '" style="--seg-color:' + blockColor + ';">';

  /* Speaker + timecode header */
  h += '<div class="text-seg-header">';
  h += '<span class="text-seg-speaker">' + esc(seg.speaker || 'Speaker') + '</span>';
  h += '<span class="text-seg-tc" data-tc="' + seg.id + '">' + esc(seg.tcIn) + '</span>';
  h += '<span class="text-seg-dur">' + Math.round(seg.duration) + 's</span>';

  /* Inline decision pills */
  h += '<span class="text-seg-decisions">';
  h += textDecPill(seg.id, 'use', 'U', dec);
  h += textDecPill(seg.id, 'cut', 'C', dec);
  h += textDecPill(seg.id, 'maybe', '?', dec);
  h += textDecPill(seg.id, 'shorts', 'S', dec);
  h += '</span>';
  h += '</div>';

  /* Segment name if any */
  if (seg.segmentName) {
    h += '<div class="text-seg-name">' + esc(seg.segmentName) + '</div>';
  }

  /* Word-level transcript (text-based editing) */
  var showStrike = isSkip && !isFull;
  var wordsHtml = _renderWordsForSegment(seg);
  if (wordsHtml) {
    h += '<div class="text-seg-body text-words' + (showStrike ? ' strikethrough' : '') + '" data-seg-words="' + seg.id + '">' + wordsHtml + '</div>';
  } else if (seg.transcript) {
    h += '<div class="text-seg-body' + (showStrike ? ' strikethrough' : '') + '">' + esc(seg.transcript) + '</div>';
  } else {
    h += '<div class="text-seg-body text-seg-empty">[No transcript]</div>';
  }

  /* Notes and B-roll */
  if (seg.brollNote) {
    h += '<div class="text-seg-note broll">\uD83C\uDFA5 ' + esc(seg.brollNote) + '</div>';
  }
  if (seg.notes) {
    h += '<div class="text-seg-note">\uD83D\uDCDD ' + esc(seg.notes) + '</div>';
  }

  h += '</div>';
  return h;
}

/* ── Word-level data extraction + rendering for text-based editing ── */

/**
 * Extract words array for a segment from transcript data.
 * Returns array of { text, start, duration, type, confidence } or null.
 */
function _getWordsForSegment(seg) {
  if (!APP._transcriptData) return null;

  var clipId = seg.sourceFile ? seg.sourceFile.replace(/\.[^.]+$/, '') : '';
  var tData = APP._transcriptData[clipId];
  if (!tData || !tData.segments) return null;

  var words = [];
  for (var si = 0; si < tData.segments.length; si++) {
    var tSeg = tData.segments[si];
    if (!tSeg.words) continue;
    for (var wi = 0; wi < tSeg.words.length; wi++) {
      var w = tSeg.words[wi];
      var wStart = w.start > 100 ? w.start / 1000.0 : w.start;
      var wDur   = w.start > 100 ? w.duration / 1000.0 : w.duration;
      var wEnd   = wStart + wDur;

      if (wEnd >= seg.inSec && wStart <= seg.outSec) {
        words.push({
          text: w.text || '',
          start: wStart,
          duration: wDur,
          type: w.type || 'word',
          confidence: w.confidence || 1,
        });
      }
    }
  }

  if (words.length === 0) return null;
  words.sort(function (a, b) { return a.start - b.start; });
  return words;
}

/**
 * Render words as clickable spans with data-widx for selection.
 */
function _renderWordsForSegment(seg) {
  var words = _getWordsForSegment(seg);
  if (!words) return null;

  var sel = APP._wordSelection;
  var isThisSeg = sel.segId === seg.id;

  var html = '';
  for (var i = 0; i < words.length; i++) {
    var word = words[i];
    var isPunct = word.type === 'punctuation';
    var cls = isPunct ? 'tw tw-punct' : 'tw';
    if (!isPunct && word.confidence < 0.5) cls += ' tw-low';

    /* Word selection highlighting */
    if (isThisSeg && !isPunct && sel.startIdx !== null) {
      var lo = sel.endIdx !== null ? Math.min(sel.startIdx, sel.endIdx) : sel.startIdx;
      var hi = sel.endIdx !== null ? Math.max(sel.startIdx, sel.endIdx) : sel.startIdx;
      if (i >= lo && i <= hi) cls += ' tw-selected';
      if (i === lo) cls += ' tw-range-start';
      if (i === hi) cls += ' tw-range-end';
    }

    var tStr = word.start.toFixed(3);

    if (isPunct) {
      html += '<span class="' + cls + '" data-widx="' + i + '">' + esc(word.text) + '</span>';
    } else {
      if (i > 0 && words[i - 1].type !== 'punctuation') html += ' ';
      html += '<span class="' + cls + '" data-t="' + tStr + '" data-src="' + esc(seg.sourceFile) + '" data-widx="' + i + '">' + esc(word.text) + '</span>';
    }
  }

  return html;
}

/* ── Word Selection UI + Trim Operations ── */

function _updateWordSelectionUI() {
  var sel = APP._wordSelection;
  var bar = $('word-trim-bar');
  if (!bar) return;

  if (!sel.segId || sel.startIdx === null) {
    bar.classList.remove('visible');
    return;
  }

  var seg = APP.segments.find(function (s) { return s.id === sel.segId; });
  if (!seg) { bar.classList.remove('visible'); return; }

  var words = _getWordsForSegment(seg);
  if (!words) { bar.classList.remove('visible'); return; }

  var lo = sel.endIdx !== null ? Math.min(sel.startIdx, sel.endIdx) : sel.startIdx;
  var hi = sel.endIdx !== null ? Math.max(sel.startIdx, sel.endIdx) : sel.startIdx;

  /* Count actual words (not punctuation) in selection */
  var wordCount = 0;
  for (var wi = lo; wi <= hi; wi++) {
    if (wi < words.length && words[wi].type !== 'punctuation') wordCount++;
  }

  $('trim-selection-info').textContent = wordCount + ' word' + (wordCount !== 1 ? 's' : '') + ' in ' + sel.segId;
  bar.classList.add('visible');

  /* Re-render the word spans in the affected segment to show selection highlights */
  var bodyEl = segListEl.querySelector('[data-seg-words="' + sel.segId + '"]');
  if (bodyEl) {
    var newHtml = _renderWordsForSegment(seg);
    if (newHtml) bodyEl.innerHTML = newHtml;
  }
}

function _clearWordSelection() {
  var oldSegId = APP._wordSelection.segId;
  APP._wordSelection = { segId: null, startIdx: null, endIdx: null };
  var bar = $('word-trim-bar');
  if (bar) bar.classList.remove('visible');

  /* Re-render old segment words to remove highlights */
  if (oldSegId) {
    var seg = APP.segments.find(function (s) { return s.id === oldSegId; });
    if (seg) {
      var bodyEl = segListEl.querySelector('[data-seg-words="' + oldSegId + '"]');
      if (bodyEl) {
        var newHtml = _renderWordsForSegment(seg);
        if (newHtml) bodyEl.innerHTML = newHtml;
      }
    }
  }
}

function _trimToSelection() {
  var sel = APP._wordSelection;
  if (!sel.segId || sel.startIdx === null) return;

  var seg = APP.segments.find(function (s) { return s.id === sel.segId; });
  if (!seg) return;

  var words = _getWordsForSegment(seg);
  if (!words) return;

  var lo = sel.endIdx !== null ? Math.min(sel.startIdx, sel.endIdx) : sel.startIdx;
  var hi = sel.endIdx !== null ? Math.max(sel.startIdx, sel.endIdx) : sel.startIdx;

  /* Find first and last non-punctuation words in range */
  var firstWord = null, lastWord = null;
  for (var i = lo; i <= hi; i++) {
    if (i < words.length && words[i].type !== 'punctuation') {
      if (!firstWord) firstWord = words[i];
      lastWord = words[i];
    }
  }
  if (!firstWord || !lastWord) return;

  var newIn = firstWord.start;
  var newOut = lastWord.start + lastWord.duration;

  appLog('Trim ' + seg.id + ': in=' + seg.inSec.toFixed(1) + '->' + newIn.toFixed(1) +
         ', out=' + seg.outSec.toFixed(1) + '->' + newOut.toFixed(1));

  seg.inSec = newIn;
  seg.outSec = newOut;
  seg.tcIn = IO.formatTimecode(newIn);
  seg.tcOut = IO.formatTimecode(newOut);
  seg.duration = newOut - newIn;

  _clearWordSelection();
  renderAll();
}

function _splitAtWord() {
  var sel = APP._wordSelection;
  if (!sel.segId || sel.startIdx === null) return;

  var seg = APP.segments.find(function (s) { return s.id === sel.segId; });
  if (!seg) return;

  var words = _getWordsForSegment(seg);
  if (!words) return;

  var splitIdx = sel.endIdx !== null ? Math.max(sel.startIdx, sel.endIdx) : sel.startIdx;
  if (splitIdx >= words.length - 1) return; /* Can't split at the last word */

  /* Find the split point — end of selection word */
  var splitWord = words[splitIdx];
  if (!splitWord) return;

  var splitTime = splitWord.start + splitWord.duration;

  /* Create second half segment */
  var newId = seg.id + '_b';
  var segIdx = APP.segments.indexOf(seg);

  var newSeg = {
    id: newId,
    sourceFile: seg.sourceFile,
    inSec: splitTime,
    outSec: seg.outSec,
    tcIn: IO.formatTimecode(splitTime),
    tcOut: seg.tcOut,
    duration: seg.outSec - splitTime,
    block: seg.block,
    blockName: seg.blockName,
    segmentName: (seg.segmentName || '') + ' (split)',
    speaker: seg.speaker,
    transcript: '',
    track: seg.track,
    color: seg.color,
    use: seg.use,
    priority: seg.priority,
    isChapter: false,
    brollNote: '',
    notes: 'Split from ' + seg.id,
  };

  /* Update first half */
  seg.outSec = splitTime;
  seg.tcOut = IO.formatTimecode(splitTime);
  seg.duration = splitTime - seg.inSec;

  /* Insert new segment after original */
  APP.segments.splice(segIdx + 1, 0, newSeg);

  /* Copy decision */
  var dec = APP.decisions[seg.id];
  if (dec) APP.decisions[newId] = dec;

  /* Update blocks */
  var block = APP.blocks.find(function (b) { return b.id === seg.block; });
  if (block) {
    var bsIdx = block.segments.indexOf(seg);
    if (bsIdx >= 0) block.segments.splice(bsIdx + 1, 0, newSeg);
    /* Recalc block durations */
    block.totalDuration = 0;
    block.usedDuration = 0;
    block.segments.forEach(function (s) {
      block.totalDuration += s.duration;
      var d = APP.decisions[s.id];
      if (d === 'use' || d === 'shorts' || (!d && s.use)) block.usedDuration += s.duration;
    });
  }

  appLog('Split ' + seg.id + ' at ' + splitTime.toFixed(1) + 's -> ' + seg.id + ' + ' + newId);

  _clearWordSelection();
  renderAll();
}

function _excludeWords() {
  var sel = APP._wordSelection;
  if (!sel.segId || sel.startIdx === null) return;

  var seg = APP.segments.find(function (s) { return s.id === sel.segId; });
  if (!seg) return;

  var words = _getWordsForSegment(seg);
  if (!words) return;

  var lo = sel.endIdx !== null ? Math.min(sel.startIdx, sel.endIdx) : sel.startIdx;
  var hi = sel.endIdx !== null ? Math.max(sel.startIdx, sel.endIdx) : sel.startIdx;

  /* Determine if selection is at start, end, or middle */
  var atStart = (lo === 0);
  var atEnd = (hi >= words.length - 1);

  if (atStart && !atEnd) {
    /* Selection at start → shift inSec forward past selection */
    var afterWord = words[hi];
    var newIn = afterWord.start + afterWord.duration;
    appLog('Exclude start of ' + seg.id + ': in=' + seg.inSec.toFixed(1) + '->' + newIn.toFixed(1));
    seg.inSec = newIn;
    seg.tcIn = IO.formatTimecode(newIn);
    seg.duration = seg.outSec - seg.inSec;
  } else if (atEnd && !atStart) {
    /* Selection at end → shift outSec backward before selection */
    var beforeWord = words[lo];
    var newOut = beforeWord.start;
    appLog('Exclude end of ' + seg.id + ': out=' + seg.outSec.toFixed(1) + '->' + newOut.toFixed(1));
    seg.outSec = newOut;
    seg.tcOut = IO.formatTimecode(newOut);
    seg.duration = seg.outSec - seg.inSec;
  } else if (!atStart && !atEnd) {
    /* Middle → split into two, removing the middle */
    _splitAtWord(); /* This will split at the selection boundary */
    return;
  } else {
    /* Entire segment selected — mark as cut */
    appLog('Exclude all of ' + seg.id + ': marking as CUT');
    REVIEW.decide(seg.id, 'cut');
  }

  _clearWordSelection();
  renderAll();
}

function textDecPill(segId, type, label, current) {
  var chosen = current === type ? ' chosen' : '';
  return '<button class="text-dec-pill' + chosen + '" data-dec="' + type + '" data-seg-dec="' + segId + '">' + label + '</button>';
}

/* ── Common ── */

function decBtn(segId, type, label, current) {
  var chosen = current === type ? ' chosen' : '';
  return '<button class="dec-btn' + chosen + '" data-dec="' + type + '" data-seg-dec="' + segId + '">' + label + '</button>';
}

/* ── Log rendering ── */
function renderLogEntry(entry) {
  if (!logPanel) return;
  var cls = 'log-entry';
  if (entry.level === 'error') cls += ' error';
  var div = document.createElement('div');
  div.className = cls;
  div.innerHTML = '<span class="log-time">' + entry.ts + '</span> ' + esc(entry.msg);
  logPanel.appendChild(div);
  logPanel.scrollTop = logPanel.scrollHeight;
  var countEl = $('debug-count');
  if (countEl) countEl.textContent = String(APP.logEntries.length);
}

function renderBuildProgress(data) {
  if (!data || !buildPanel) return;
  buildPanel.classList.add('visible');
  var pct = data.total > 0 ? Math.round(data.step / data.total * 100) : 0;
  $('build-progress-fill').style.width = pct + '%';
  $('build-status').textContent = data.label + ' (' + data.step + '/' + data.total + ')';
}

/* ══════════════════════════════
   DEBUG PANEL
   ══════════════════════════════ */

function toggleDebugPanel() {
  if (debugOverlay) debugOverlay.classList.toggle('visible');
}

function closeDebugPanel() {
  if (debugOverlay) debugOverlay.classList.remove('visible');
}

function _buildDebugText() {
  var lines = APP.logEntries.map(function (e) {
    return e.ts + ' [' + e.level + '] ' + e.msg;
  });
  return '=== YTAI Brief Debug Log ===\n'
    + 'Version: 1.0.19\n'
    + 'Date: ' + new Date().toISOString() + '\n'
    + 'Segments: ' + APP.segments.length + '\n'
    + 'Blocks: ' + APP.blocks.length + '\n'
    + '===========================\n\n'
    + lines.join('\n');
}

function copyDebugLog() {
  var text = _buildDebugText();

  try {
    var uxpClip = require('uxp').clipboard;
    if (uxpClip && uxpClip.copyText) {
      uxpClip.copyText(text);
      showDebugToast('Copied!');
      appLog('Log copied (' + APP.logEntries.length + ' entries)');
      return;
    }
  } catch (ex) { /* fallback */ }

  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        showDebugToast('Copied!');
      }).catch(function () { showDebugToast('Copy failed'); });
      return;
    }
  } catch (ex) { /* fallback */ }

  try {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    showDebugToast('Copied!');
  } catch (ex) {
    showDebugToast('Copy failed');
  }
}

/* ── Writable folder chain: brief folder → data folder → temp folder → plugin folder ── */
async function _getWritableFolder() {
  var uxpMod = require('uxp');
  var fs = uxpMod.storage.localFileSystem;

  /* 1. Brief folder (next to edit_brief.json — user can see it) */
  if (APP.briefFileEntry) {
    try {
      var bf = await APP.briefFileEntry.getParent();
      if (bf) return { folder: bf, label: 'brief' };
    } catch (e) { /* skip */ }
  }
  /* 2. Data folder (writable persistent UXP storage) */
  try {
    var df = await fs.getDataFolder();
    if (df) return { folder: df, label: 'data' };
  } catch (e) { /* skip */ }
  /* 3. Temp folder */
  try {
    var tf = await fs.getTemporaryFolder();
    if (tf) return { folder: tf, label: 'temp' };
  } catch (e) { /* skip */ }
  /* 4. Plugin folder (may be read-only in UXP Manifest v6) */
  try {
    var pf = await fs.getPluginFolder();
    if (pf) return { folder: pf, label: 'plugin' };
  } catch (e) { /* skip */ }

  return null;
}

/* ── Auto-save debug log ──
   Tries writable folder chain: brief → data → temp → plugin.
   Overwrites debug_log.txt each time — always fresh. */
async function saveDebugToFile() {
  var text = _buildDebugText();
  try {
    var uxpMod = require('uxp');
    var loc = await _getWritableFolder();
    if (!loc) { console.error('[YTAI] No writable folder found'); return; }
    var file = await loc.folder.createFile('debug_log.txt', { overwrite: true });
    await file.write(text, { format: uxpMod.storage.formats.utf8 });
    showDebugToast('Log saved (' + loc.label + ')');
    console.log('[YTAI] Debug log saved to ' + loc.label + ' folder (' + APP.logEntries.length + ' entries)');
  } catch (ex) {
    console.error('[YTAI] saveDebugToFile failed:', ex.message);
    showDebugToast('Save failed: ' + ex.message);
  }
}

/* ── Snapshot: save log + project state with timestamp ──
   Creates timestamped snapshot for debugging history. */
async function saveSnapshot() {
  var text = _buildDebugText();

  /* Append current brief JSON state if available */
  if (APP.segments.length > 0) {
    text += '\n\n=== BRIEF STATE ===\n';
    text += 'Segments: ' + APP.segments.length + '\n';
    APP.segments.forEach(function (s) {
      var dec = APP.decisions[s.id] || (s.use ? 'use' : 'cut');
      text += '  ' + s.id + ' | ' + s.sourceFile + ' | ' + s.tcIn + '-' + s.tcOut
            + ' | block=' + s.block + ' ' + (s.blockName || '')
            + ' | ' + dec + ' | ' + (s.color || '?') + '\n';
    });
  }

  try {
    var uxpMod = require('uxp');
    var loc = await _getWritableFolder();
    if (!loc) { showDebugToast('No writable folder'); return; }
    var now = new Date();
    var stamp = String(now.getFullYear())
      + String(now.getMonth() + 1).padStart(2, '0')
      + String(now.getDate()).padStart(2, '0')
      + '_' + String(now.getHours()).padStart(2, '0')
      + String(now.getMinutes()).padStart(2, '0')
      + String(now.getSeconds()).padStart(2, '0');
    var snapName = 'snapshot_' + stamp + '.txt';
    var file = await loc.folder.createFile(snapName, { overwrite: true });
    await file.write(text, { format: uxpMod.storage.formats.utf8 });
    showDebugToast('Snapshot: ' + snapName + ' (' + loc.label + ')');
    appLog('Snapshot saved: ' + snapName + ' (' + loc.label + ')');
    console.log('[YTAI] Snapshot saved: ' + snapName);
  } catch (ex) {
    console.error('[YTAI] saveSnapshot failed:', ex.message);
    showDebugToast('Snapshot failed: ' + ex.message);
  }
}

function clearDebugLog() {
  APP.logEntries = [];
  if (logPanel) logPanel.innerHTML = '';
  var countEl = $('debug-count');
  if (countEl) countEl.textContent = '0';
  appLog('Log cleared');
}

function showDebugToast(msg) {
  var existing = document.querySelector('.debug-toast');
  if (existing) existing.remove();
  var toast = document.createElement('div');
  toast.className = 'debug-toast';
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(function () { toast.remove(); }, 1600);
}

/* ══════════════════════════════
   UTILITIES
   ══════════════════════════════ */

function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function truncate(str, max) {
  if (!str) return '';
  return str.length > max ? str.slice(0, max) + '...' : str;
}

/* ══════════════════════════════
   TIMELINE TOGGLE (FULL / ROUGH)
   ══════════════════════════════ */

function switchTimeline(mode) {
  APP.activeTimeline = mode;
  APP._timelinePositions = (mode === 'full')
    ? APP._fullTimelinePositions
    : APP._roughTimelinePositions;

  /* Update toggle buttons */
  document.querySelectorAll('.tl-btn').forEach(function (btn) {
    btn.classList.toggle('active', btn.getAttribute('data-tl') === mode);
  });

  appLog('Timeline: ' + mode.toUpperCase() + ' (' + Object.keys(APP._timelinePositions).length + ' positions)');

  /* Re-render text view to show correct segments */
  if (APP.viewMode === 'text' && APP.segments.length > 0) renderTextView();
}

/* ══════════════════════════════
   VIEW MODE SWITCHING
   ══════════════════════════════ */

function setViewMode(mode) {
  appLog('View: ' + mode);
  APP.viewMode = mode;

  /* Update body class */
  document.body.classList.remove('compact', 'text-mode');
  if (mode === 'compact') document.body.classList.add('compact');
  if (mode === 'text')    document.body.classList.add('text-mode');

  /* Update view switcher buttons */
  document.querySelectorAll('.view-btn').forEach(function (btn) {
    btn.classList.toggle('active', btn.getAttribute('data-view') === mode);
  });

  /* Re-render */
  if (APP.segments.length > 0) {
    if (mode === 'text') {
      renderTextView();
    } else {
      renderBlocks();
    }
  }
}

/* ══════════════════════════════
   EVENT DELEGATION
   ══════════════════════════════ */

function setupEventDelegation() {
  document.addEventListener('click', function (e) {
    var t = e.target;

    /* Timeline toggle (FULL / ROUGH) */
    var tlBtn = t.closest ? t.closest('.tl-btn') : null;
    if (tlBtn) {
      var tl = tlBtn.getAttribute('data-tl');
      if (tl) switchTimeline(tl);
      return;
    }

    /* View switcher */
    var viewBtn = t.closest ? t.closest('.view-btn') : null;
    if (viewBtn) {
      var mode = viewBtn.getAttribute('data-view');
      if (mode) setViewMode(mode);
      return;
    }

    /* Decision button (card view + text view) */
    var decBtnEl = t.closest ? t.closest('[data-seg-dec]') : null;
    if (decBtnEl) {
      var segId = decBtnEl.getAttribute('data-seg-dec');
      var decType = decBtnEl.getAttribute('data-dec');
      appLog('Decision: ' + segId + ' → ' + decType);
      REVIEW.decide(segId, decType);
      return;
    }

    /* Timecode click */
    var tcEl = t.closest ? t.closest('[data-tc]') : null;
    if (tcEl) {
      var tcSegId = tcEl.getAttribute('data-tc');
      var seg = APP.segments.find(function (s) { return s.id === tcSegId; });
      if (seg) {
        APP.activeSegmentId = tcSegId;
        NAV.jumpToTime(seg.sourceFile, seg.inSec);
        BUS.emit('active-changed', { segId: tcSegId });
      }
      return;
    }

    /* Segment card click (card view) */
    var card = t.closest ? t.closest('.segment-card') : null;
    if (card && !(t.closest('.dec-btn')) && !(t.closest('.seg-timecode'))) {
      var cardSegId = card.getAttribute('data-seg');
      APP.activeSegmentId = cardSegId;
      BUS.emit('active-changed', { segId: cardSegId });
      return;
    }

    /* Word click → jump to time + selection (text-based editing) */
    var wordEl = t.closest ? t.closest('.tw[data-t]') : null;
    if (wordEl) {
      var wordTime = parseFloat(wordEl.getAttribute('data-t'));
      var wordSrc = wordEl.getAttribute('data-src') || '';
      var widx = parseInt(wordEl.getAttribute('data-widx'), 10);
      var parentSeg = wordEl.closest('.text-segment');
      var wSegId = parentSeg ? parentSeg.getAttribute('data-seg') : null;

      if (!isNaN(wordTime) && wordSrc) {
        /* Highlight active word */
        document.querySelectorAll('.tw-active').forEach(function (el) { el.classList.remove('tw-active'); });
        wordEl.classList.add('tw-active');
        appLog('Word jump: ' + (wSegId || '?') + ' src=' + wordSrc + ' t=' + wordTime.toFixed(1));
        NAV.jumpToTime(wordSrc, wordTime);
      }

      /* Word selection: Shift+Click = range, Click = new start */
      if (wSegId && !isNaN(widx)) {
        if (e.shiftKey && APP._wordSelection.segId === wSegId && APP._wordSelection.startIdx !== null) {
          /* Extend selection range */
          APP._wordSelection.endIdx = widx;
        } else {
          /* New selection start */
          APP._wordSelection.segId = wSegId;
          APP._wordSelection.startIdx = widx;
          APP._wordSelection.endIdx = null;
        }
        _updateWordSelectionUI();
        var _s = APP._wordSelection;
        appLog('Word select: ' + _s.segId + ' [' + _s.startIdx + (_s.endIdx !== null ? '-' + _s.endIdx : '') + ']');
      }

      /* Set active segment */
      if (parentSeg) {
        APP.activeSegmentId = wSegId;
        BUS.emit('active-changed', { segId: wSegId });
      }
      return;
    }

    /* Text segment click (text view) */
    var textSeg = t.closest ? t.closest('.text-segment') : null;
    if (textSeg && !(t.closest('.text-dec-pill')) && !(t.closest('.text-seg-tc'))) {
      var textSegId = textSeg.getAttribute('data-seg');
      APP.activeSegmentId = textSegId;
      BUS.emit('active-changed', { segId: textSegId });
      return;
    }

    /* Block header toggle */
    var blockToggle = t.closest ? t.closest('[data-block-toggle]') : null;
    if (blockToggle) {
      var blockEl = blockToggle.closest('.block');
      if (blockEl) blockEl.classList.toggle('block-collapsed');
      return;
    }

    /* Chapter bar click */
    var chBlock = t.closest ? t.closest('.chapter-block') : null;
    if (chBlock) {
      var blockId = chBlock.getAttribute('data-block');
      var selector = APP.viewMode === 'text' ? '.text-block[data-block="' + blockId + '"]' : '.block[data-block="' + blockId + '"]';
      var targetBlock = segListEl.querySelector(selector);
      if (targetBlock) targetBlock.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }

    /* Filter pills */
    var pill = t.closest ? t.closest('.filter-pill') : null;
    if (pill) {
      var filter = pill.getAttribute('data-filter');
      appLog('Filter: ' + filter);
      APP.filter = filter;
      document.querySelectorAll('.filter-pill').forEach(function (p) { p.classList.remove('active'); });
      pill.classList.add('active');
      if (APP.viewMode === 'text') {
        renderTextView();
      } else {
        renderBlocks();
      }
      return;
    }
  });
}

/* ══════════════════════════════
   TOOLBAR BUTTONS
   ══════════════════════════════ */

function setupToolbarButtons() {
  console.log('[YTAI] setupToolbarButtons: attaching handlers...');

  var btnLoad = $('btn-load');
  if (!btnLoad) {
    console.error('[YTAI] btn-load NOT FOUND in DOM!');
    appLog('FATAL: btn-load not found', 'error');
    return;
  }

  var loadingBrief = false;
  btnLoad.addEventListener('click', async function () {
    if (loadingBrief) { appLog('Load already in progress...'); return; }
    loadingBrief = true;
    btnLoad.disabled = true;
    appLog('Load Brief clicked');

    if (typeof IO === 'undefined') {
      appLog('FATAL: IO is undefined', 'error');
      loadingBrief = false;
      btnLoad.disabled = false;
      return;
    }

    try { await IO.pickAndLoadBrief(); }
    catch (ex) { appLog('Load error: ' + ex.message, 'error'); }

    loadingBrief = false;
    btnLoad.disabled = false;
  });

  $('btn-save').addEventListener('click', function () { IO.saveReviewed(); });

  $('btn-reload').addEventListener('click', async function () {
    try { await IO.reloadBrief(); }
    catch (ex) { appLog('Reload error: ' + ex.message, 'error'); }
  });

  $('btn-settings').addEventListener('click', function () {
    settingsPanel.classList.toggle('visible');
  });

  /* Debug panel buttons */
  $('btn-log').addEventListener('click', toggleDebugPanel);
  $('btn-log-save').addEventListener('click', saveDebugToFile);
  $('btn-log-snapshot').addEventListener('click', saveSnapshot);
  $('btn-log-copy').addEventListener('click', copyDebugLog);
  $('btn-log-clear').addEventListener('click', clearDebugLog);
  $('btn-log-close').addEventListener('click', closeDebugPanel);

  $('debug-overlay').addEventListener('click', function (e) {
    if (e.target === debugOverlay) closeDebugPanel();
  });

  var btnBuild = $('btn-build');
  btnBuild.addEventListener('click', async function () {
    if (APP.buildStatus === 'running') return;
    btnBuild.disabled = true;
    try { await BUILD.runBuild(); }
    catch (ex) { appLog('Build failed: ' + ex.message, 'error'); }
    btnBuild.disabled = false;
  });

  $('btn-transcripts').addEventListener('click', async function () {
    try {
      await BUILD.loadTranscripts();
      /* Re-render to show word-level transcript in Text view */
      if (APP.viewMode === 'text') {
        renderTextView();
      }
      appLog('Transcripts loaded. Switch to Text view to see word-level editing.');
      saveDebugToFile();
    }
    catch (ex) { appLog('Transcripts error: ' + ex.message, 'error'); }
  });

  $('btn-browse-source').addEventListener('click', function () { IO.pickSourceFolder(); });

  /* Word trim bar buttons */
  $('btn-trim-to-selection').addEventListener('click', function () { _trimToSelection(); });
  $('btn-split-at-word').addEventListener('click', function () { _splitAtWord(); });
  $('btn-exclude-words').addEventListener('click', function () { _excludeWords(); });
  $('btn-clear-selection').addEventListener('click', function () { _clearWordSelection(); });

  $('btn-api-test').addEventListener('click', async function () {
    var results = await BUILD.testAPIs();
    var el = $('api-results');
    el.innerHTML = results.map(function (r) {
      return '<div class="api-result"><span class="api-dot ' + (r.ok ? 'ok' : 'fail') + '"></span>' + esc(r.name) + (r.err ? ' \u2014 ' + esc(r.err) : '') + '</div>';
    }).join('');
  });

  $('search-input').addEventListener('input', function (e) {
    APP.searchQuery = e.target.value;
    if (APP.viewMode === 'text') {
      renderTextView();
    } else {
      renderBlocks();
    }
  });
}

/* ══════════════════════════════
   HOTKEYS
   ══════════════════════════════ */

function setupHotkeys() {
  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.key === 'Escape') {
      /* Clear word selection first if active */
      if (APP._wordSelection.segId) {
        _clearWordSelection();
        return;
      }
      if (debugOverlay && debugOverlay.classList.contains('visible')) {
        closeDebugPanel();
        return;
      }
    }

    /* X / D / Delete / Backspace → exclude selected words (same as Exclude button)
       NOTE: Premiere Pro often intercepts Delete/Backspace before UXP panel receives them.
       'x' and 'd' keys are reliable alternatives that always reach the panel. */
    if (e.key === 'x' || e.key === 'X' || e.key === 'd' || e.key === 'D' ||
        e.key === 'Delete' || e.key === 'Backspace') {
      if (APP._wordSelection.segId && APP._wordSelection.startIdx !== null) {
        e.preventDefault();
        _excludeWords();
        return;
      }
    }

    var key = e.key;

    if (REVIEW.handleReviewHotkey(key)) return;

    if (key === 'ArrowRight' || key === 'ArrowDown') {
      e.preventDefault(); REVIEW.navigateSegment('next'); return;
    }
    if (key === 'ArrowLeft' || key === 'ArrowUp') {
      e.preventDefault(); REVIEW.navigateSegment('prev'); return;
    }
    if (key === 'Enter') {
      e.preventDefault(); NAV.playActiveSegment(); return;
    }
    if (key === ' ') {
      e.preventDefault(); NAV.jumpToActiveSegment(); return;
    }

    /* View mode shortcuts: 1=Cards, 2=Text, 3=Compact */
    if (key === '1') { setViewMode('normal'); return; }
    if (key === '2') { setViewMode('text'); return; }
    if (key === '3') { setViewMode('compact'); return; }
  });
}

/* ══════════════════════════════
   BUS SUBSCRIPTIONS
   ══════════════════════════════ */

function setupBusListeners() {
  BUS.on('brief-loaded', async function () {
    renderAll();

    /* Auto-load transcripts if transcription dir is configured */
    if (APP.transcriptionDir && typeof BUILD !== 'undefined' && BUILD.loadTranscripts) {
      appLog('Auto-loading transcripts...');
      try {
        await BUILD.loadTranscripts();
        if (APP.viewMode === 'text') renderTextView();
        appLog('Transcripts auto-loaded.');
      } catch (ex) {
        appLog('Auto-load transcripts: ' + ex.message);
      }
    }

    /* Auto-build: run full pipeline (import → FULL → ROUGH → trim → color → markers) */
    if (typeof BUILD !== 'undefined' && BUILD.runBuild) {
      appLog('Auto-build starting...');
      var btnBuild = $('btn-build');
      if (btnBuild) btnBuild.disabled = true;
      try {
        await BUILD.runBuild();
        appLog('Auto-build complete!');
      } catch (ex) {
        appLog('Auto-build failed: ' + ex.message, 'error');
      }
      if (btnBuild) btnBuild.disabled = false;
    }

    saveDebugToFile();
  });

  BUS.on('decision-changed', function (data) {
    renderStats();

    if (APP.viewMode === 'text') {
      /* In text view, update the text segment */
      var textSeg = segListEl.querySelector('.text-segment[data-seg="' + data.segId + '"]');
      if (textSeg) {
        var currentDec = APP.decisions[data.segId];
        var isFull = APP.activeTimeline === 'full';
        textSeg.className = 'text-segment';
        if (data.segId === APP.activeSegmentId) textSeg.className += ' active';
        if (currentDec === 'use')    textSeg.className += ' text-seg-use';
        if (currentDec === 'cut')    textSeg.className += (isFull ? ' text-seg-cut-full' : ' text-seg-cut');
        if (currentDec === 'maybe')  textSeg.className += ' text-seg-maybe';
        if (currentDec === 'shorts') textSeg.className += ' text-seg-shorts';
        if (!currentDec) {
          var seg = APP.segments.find(function (s) { return s.id === data.segId; });
          if (seg && !seg.use) textSeg.className += (isFull ? ' text-seg-cut-full' : ' text-seg-unreviewed');
        }

        /* Update decision pills */
        textSeg.querySelectorAll('.text-dec-pill').forEach(function (btn) {
          btn.classList.toggle('chosen', btn.getAttribute('data-dec') === currentDec);
        });

        /* Toggle strikethrough on body */
        var body = textSeg.querySelector('.text-seg-body');
        if (body) {
          body.classList.toggle('strikethrough', currentDec === 'cut');
        }
      }
    } else {
      /* Card view update */
      var card = segListEl.querySelector('.segment-card[data-seg="' + data.segId + '"]');
      if (card) {
        var currentDec = APP.decisions[data.segId];
        card.querySelectorAll('.dec-btn').forEach(function (btn) {
          btn.classList.toggle('chosen', btn.getAttribute('data-dec') === currentDec);
        });
        card.classList.toggle('seg-skip', currentDec === 'cut');
      }
    }
  });

  BUS.on('active-changed', function (data) {
    /* Remove old active */
    segListEl.querySelectorAll('.active').forEach(function (el) {
      el.classList.remove('active');
    });

    /* Add new active */
    var selector = APP.viewMode === 'text'
      ? '.text-segment[data-seg="' + data.segId + '"]'
      : '.segment-card[data-seg="' + data.segId + '"]';
    var el = segListEl.querySelector(selector);
    if (el) {
      el.classList.add('active');
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });

  BUS.on('log', function (entry) { renderLogEntry(entry); });
  BUS.on('build-progress', function (data) { renderBuildProgress(data); });
  BUS.on('build-done', function () {
    buildPanel.classList.remove('visible');
    $('btn-build').disabled = false;
    /* Show timeline toggle after build */
    var tlToggle = $('timeline-toggle');
    if (tlToggle) tlToggle.style.display = '';
    /* Auto-save debug log to plugin folder after each build */
    saveDebugToFile();
  });
  BUS.on('build-error', function () {
    $('build-status').textContent = 'Error \u2014 click Build to retry';
    $('build-progress-fill').style.background = '#E34850';
    $('btn-build').disabled = false;
  });
  BUS.on('source-folder-changed', function () {
    $('source-folder-path').textContent = APP.sourceFolderEntry ? APP.sourceFolderEntry.name : 'Not set';
  });
}

/* ══════════════════════════════
   COMMAND ENTRYPOINTS (Premiere Pro menu)
   ══════════════════════════════ */

function setupCommandEntrypoints() {
  try {
    var uxpEntrypoints = require('uxp').entrypoints;
    if (!uxpEntrypoints || !uxpEntrypoints.setup) return;

    uxpEntrypoints.setup({
      commands: {
        'com.ytai.brief.loadBrief': {
          run: function () {
            if (typeof IO !== 'undefined' && IO.pickAndLoadBrief) {
              IO.pickAndLoadBrief().catch(function (e) {
                appLog('Menu load error: ' + e.message, 'error');
              });
            }
          }
        },
        'com.ytai.brief.buildSequence': {
          run: function () {
            if (typeof BUILD !== 'undefined' && BUILD.runBuild) {
              BUILD.runBuild().catch(function (e) {
                appLog('Menu build error: ' + e.message, 'error');
              });
            }
          }
        }
      },
      panels: {
        'com.ytai.brief.mainPanel': {
          show: function () { console.log('[YTAI] Panel shown'); }
        }
      }
    });

    appLog('Menu commands registered');
  } catch (ex) {
    console.log('[YTAI] Command entrypoints:', ex.message);
  }
}

/* ══════════════════════════════
   INIT
   ══════════════════════════════ */

function initApp() {
  console.log('[YTAI] initApp()');
  appLog('initApp: starting...');

  try { initDomRefs(); } catch (e) {
    console.error('[YTAI] initDomRefs FAILED:', e);
    appLog('DOM refs FAILED: ' + e.message, 'error');
  }

  try { setupBusListeners(); } catch (e) {
    appLog('BUS listeners FAILED: ' + e.message, 'error');
  }

  try { setupEventDelegation(); } catch (e) {
    appLog('Event delegation FAILED: ' + e.message, 'error');
  }

  try { setupToolbarButtons(); } catch (e) {
    appLog('Toolbar buttons FAILED: ' + e.message, 'error');
  }

  try { setupHotkeys(); } catch (e) {
    appLog('Hotkeys FAILED: ' + e.message, 'error');
  }

  /* Set default body class for text-mode since viewMode defaults to 'text' */
  if (APP.viewMode === 'text') document.body.classList.add('text-mode');

  try { setupCommandEntrypoints(); } catch (ex) { /* ok */ }

  appLog('YTAI Brief v1.0.19 ready');
  console.log('[YTAI] ====== initApp() COMPLETE ======');
}

/* Run init when DOM is ready */
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
