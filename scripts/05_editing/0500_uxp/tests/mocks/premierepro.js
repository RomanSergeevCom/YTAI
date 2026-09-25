/**
 * Mock of the Premiere Pro UXP API for testing outside of Premiere Pro.
 * Records all API calls for verification in tests.
 */

class CallRecorder {
  constructor() {
    this.calls = [];
  }

  record(method, args) {
    this.calls.push({ method, args: [...args] });
  }

  getCalls(method) {
    return this.calls.filter(c => c.method === method);
  }

  reset() {
    this.calls = [];
  }
}

const recorder = new CallRecorder();

// --- Measured Premiere time quantization (YTCH10 + YTCH13 dumps, 16.08.2026) ---
//
// Real Premiere 25.6 is NOT sub-frame-transparent. Measured with tick-level
// sequence dumps against known requested values:
//   - ClipProjectItem.createSetInOutPointsAction FLOORS source in/out to the
//     sequence video-frame grid, even for audio-only WAV items
//     (YTCH10: planned in=324.512 → landed 324.480).
//   - SequenceEditor.createInsertProjectItemAction ROUNDS the timeline position
//     to the NEAREST frame (YTCH13: 28/28 TX slices consistent, fractions
//     4.8–16.3 ms floored, 20.1–36.3 ms ceiled).
//   - createOverwriteItemAction passes exact on-grid values through; off-grid
//     behaviour is UNPROVEN (all real requests were on-grid) — modelled here as
//     nearest, the weakest reasonable assumption.
// The mock reproduces this so unit tests exercise the truth: a builder that
// sends sub-frame values SHOULD see them quantized, like in the real app.
const QUANT = { fps: 25 };
// Live 25.6: SequenceEditor action factories require an active lockedAccess
// scope. Tracked here so the mock can throw exactly like the real app.
const LOCK = { depth: 0 };
function _requireLock(what) {
  if (LOCK.depth <= 0) throw new Error('Requires locked access');
}
function _frameSec() { return 1 / QUANT.fps; }
function _floorToFrame(sec) { if (!QUANT.fps) return sec; return Math.floor(sec / _frameSec() + 1e-9) * _frameSec(); }
function _nearestFrame(sec) { if (!QUANT.fps) return sec; return Math.round(sec / _frameSec()) * _frameSec(); }

// --- TickTime ---

class MockTickTime {
  constructor(seconds) {
    this.seconds = seconds;
    this.ticks = String(Math.round(seconds * 254016000000));
    this.ticksNumber = Math.round(seconds * 254016000000);
  }

  equals(other) {
    return this.seconds === other.seconds;
  }

  add(other) {
    return new MockTickTime(this.seconds + other.seconds);
  }

  subtract(other) {
    return new MockTickTime(this.seconds - other.seconds);
  }

  multiply(factor) {
    return new MockTickTime(this.seconds * factor);
  }

  divide(divisor) {
    return new MockTickTime(this.seconds / divisor);
  }
}

const TickTimeStatic = {
  TIME_ZERO: new MockTickTime(0),
  TIME_ONE_SECOND: new MockTickTime(1),
  createWithSeconds(seconds) {
    recorder.record('TickTime.createWithSeconds', [seconds]);
    return new MockTickTime(seconds);
  },
  createWithTicks(ticks) {
    const seconds = Number(ticks) / 254016000000;
    recorder.record('TickTime.createWithTicks', [ticks]);
    return new MockTickTime(seconds);
  },
  createWithFrameAndFrameRate(frame, frameRate) {
    const seconds = frame / frameRate.value;
    return new MockTickTime(seconds);
  }
};

// --- Action ---

class MockAction {
  constructor(type, params) {
    this.type = type;
    this.params = params;
  }
}

// --- CompoundAction ---

class MockCompoundAction {
  constructor() {
    this.actions = [];
  }

  addAction(action) {
    this.actions.push(action);
    recorder.record('CompoundAction.addAction', [action]);
  }
}

// --- ProjectItem ids (ProjectItem.getId(), 25.6+) ---
// Kept in a WeakMap, not as own properties, so structural asserts on items are unaffected.
const _itemIds = new WeakMap();
let _itemIdCounter = 0;
function _idOf(obj) {
  if (!_itemIds.has(obj)) _itemIds.set(obj, 'pi-' + (++_itemIdCounter));
  return _itemIds.get(obj);
}

// --- FolderItem ---

class MockFolderItem {
  constructor(name, items = []) {
    this.name = name;
    this.type = 2; // TYPE_BIN
    this._items = items;
  }

  async getItems() {
    return this._items;
  }

  getId() { return _idOf(this); }
  getParentBin() { return this._parent || null; }

  createBinAction(name, makeUnique) {
    recorder.record('FolderItem.createBinAction', [name, makeUnique]);
    const newBin = new MockFolderItem(name);
    newBin._parent = this;
    this._items.push(newBin);
    return new MockAction('createBin', { name, makeUnique });
  }

  // Real 25.6+ signature: FolderItem.createMoveItemAction(item, newParent) — TWO args,
  // called on the project ROOT in every Adobe example; the item lands in NEWPARENT.
  // A missing newParent throws here so the old one-arg bin.createMoveItemAction(item)
  // (a silent no-op in live Premiere, YTUVI02 auto-save 15.09) can never pass a test.
  // apply() moves the item out of its current container (tolerates items pushed
  // directly by tests with no _parent: then it is removed from `this` if present).
  createMoveItemAction(item, newParent) {
    recorder.record('FolderItem.createMoveItemAction', [item, newParent]);
    if (!item || !newParent) throw new Error('Not Enough Parameters');
    const self = this;
    const action = new MockAction('moveItem', { item, newParent });
    action.apply = function () {
      const from = (item._parent && Array.isArray(item._parent._items)) ? item._parent : self;
      const idx = from._items.indexOf(item);
      if (idx >= 0) from._items.splice(idx, 1);
      newParent._items.push(item);
      item._parent = newParent;
    };
    return action;
  }

  createRemoveItemAction(item) {
    recorder.record('FolderItem.createRemoveItemAction', [item]);
    return new MockAction('removeItem', { item });
  }
}

// --- ClipProjectItem ---

class MockClipProjectItem {
  constructor(name, filePath) {
    this.name = name;
    this.type = 1; // TYPE_CLIP
    this._filePath = filePath;
    this._inPoint = null;
    this._outPoint = null;
  }

  async getMediaFilePath() {
    return this._filePath;
  }

  getId() { return _idOf(this); }
  getParentBin() { return this._parent || null; }

  async getContentType() {
    return 0; // MEDIA
  }

  async isSequence() {
    return false;
  }

  createSetInOutPointsAction(inPoint, outPoint) {
    recorder.record('ClipProjectItem.createSetInOutPointsAction', [inPoint, outPoint]);
    // Real Premiere FLOORS source in/out to the video frame grid, even for
    // audio-only items (measured YTCH10 16.08.2026) — model it.
    const inQ = inPoint && typeof inPoint.seconds === 'number'
      ? new MockTickTime(_floorToFrame(inPoint.seconds)) : inPoint;
    const outQ = outPoint && typeof outPoint.seconds === 'number'
      ? new MockTickTime(_floorToFrame(outPoint.seconds)) : outPoint;
    this._inPoint = inQ;
    this._outPoint = outQ;
    return new MockAction('setInOutPoints', { inPoint: inQ, outPoint: outQ });
  }

  createClearInOutPointsAction() {
    recorder.record('ClipProjectItem.createClearInOutPointsAction', []);
    this._inPoint = null;
    this._outPoint = null;
    return new MockAction('clearInOutPoints', {});
  }

  createSetNameAction(name) {
    recorder.record('ClipProjectItem.createSetNameAction', [name]);
    return new MockAction('setName', { name });
  }

  createSetColorLabelAction(colorIndex) {
    recorder.record('ClipProjectItem.createSetColorLabelAction', [colorIndex]);
    return new MockAction('setColorLabel', { colorIndex });
  }

  async getColorLabelIndex() {
    return 0;
  }
}

// --- TrackItem ---

class MockTrackItem {
  constructor(name, startTimeSec, durationSec) {
    this.name = name;
    this.type = 1;
    this._projectItem = null;
    this._startTimeSec = startTimeSec || 0;
    this._durationSec = durationSec || 10;
    this._track = null; // back-ref set when placed, for createRemoveAction
  }

  async getName() {
    return this.name;
  }

  async getStartTime() {
    return new MockTickTime(this._startTimeSec);
  }

  async getDuration() {
    return new MockTickTime(this._durationSec);
  }

  createSetNameAction(name) {
    recorder.record('TrackItem.createSetNameAction', [name]);
    this.name = name;
    return new MockAction('setName', { name });
  }

  // 25.0+: VideoClipTrackItem/AudioClipTrackItem.createSetDisabledAction(disabled) + isDisabled()
  // (Clip → Enable в GUI; в .prproj — ClipTrackItem/IsMuted).
  createSetDisabledAction(disabled) {
    recorder.record('TrackItem.createSetDisabledAction', [disabled]);
    const self = this;
    const action = new MockAction('setDisabled', { disabled: !!disabled });
    action.apply = function () { self._disabled = !!disabled; };
    return action;
  }

  async isDisabled() {
    return !!this._disabled;
  }

  // 26.x trackItem trim: absolute sequence end time, start stays (models the
  // typings' createSetEndAction; extension beyond the source length is legal
  // for synthetic items like adjustment layers).
  createSetEndAction(tickTime) {
    recorder.record('TrackItem.createSetEndAction', [tickTime]);
    const self = this;
    const endSec = tickTime && typeof tickTime.seconds === 'number' ? tickTime.seconds : 0;
    const action = new MockAction('setEnd', { endSec });
    action.apply = function () { self._durationSec = Math.max(0, endSec - self._startTimeSec); };
    return action;
  }

  // ⚠️ LIVE 25.6 DOES NOT HAVE THIS METHOD (verified against Adobe docs 2026-07-12;
  // it is why partsBuilder/sequenceFactory removal goes through TrackItemSelection +
  // createRemoveItemsAction). Kept in the mock ONLY because legacy assemblyBuilder
  // tests exercise the old ghost-clip path — do NOT write new code against it.
  createRemoveAction() {
    recorder.record('TrackItem.createRemoveAction', []);
    const self = this;
    const action = new MockAction('removeTrackItem', {});
    action.apply = function () {
      if (self._track && Array.isArray(self._track._items)) {
        const idx = self._track._items.indexOf(self);
        if (idx >= 0) self._track._items.splice(idx, 1);
      }
    };
    return action;
  }

  async getProjectItem() {
    return this._projectItem || new MockClipProjectItem(this.name);
  }
}

// --- VideoTrack / AudioTrack ---

class MockVideoTrack {
  constructor(name, index) {
    this.name = name;
    this.id = index;
    this._items = [];
  }
  async getIndex() { return this.id; }
  getTrackItems(type, includeEmpty) { return this._items; }
  async getMediaType() { return 'video'; }
  /** Тестовый помощник: положить айтем и проставить обратную ссылку. */
  _addItem(name, startSec, durSec) {
    const ti = new MockTrackItem(name, startSec, durSec);
    ti._track = this;
    this._items.push(ti);
    return ti;
  }
}

class MockAudioTrack {
  constructor(name, index) {
    this.name = name;
    this.id = index;
    this._items = [];
  }
  async getIndex() { return this.id; }
  getTrackItems(type, includeEmpty) { return this._items; }
  async getMediaType() { return 'audio'; }
  /** Тестовый помощник: положить айтем и проставить обратную ссылку. */
  _addItem(name, startSec, durSec) {
    const ti = new MockTrackItem(name, startSec, durSec);
    ti._track = this;
    this._items.push(ti);
    return ti;
  }
}

// --- Sequence ---

let _seqGuidCounter = 0;

class MockSequence {
  // opts.videoTracks / opts.audioTracks = initial track counts.
  // Default (no opts) preserves legacy behaviour (3 V-tracks) for
  // createSequenceFromMedia and existing suites. The empty createSequence
  // path passes {videoTracks:1, audioTracks:1} to model a realistic empty
  // sequence so the wall-clock track auto-create / pre-warm path is exercised.
  constructor(name, opts) {
    this.name = name;
    this.guid = 'seq-' + (++_seqGuidCounter);
    const nv = opts && typeof opts.videoTracks === 'number' ? opts.videoTracks : 3;
    const na = opts && typeof opts.audioTracks === 'number' ? opts.audioTracks : 0;
    this._videoTracks = [];
    for (let i = 0; i < nv; i++) this._videoTracks.push(new MockVideoTrack('V' + (i + 1), i));
    this._audioTracks = [];
    for (let i = 0; i < na; i++) this._audioTracks.push(new MockAudioTrack('A' + (i + 1), i));
  }

  async getVideoTrackCount() {
    return this._videoTracks.length;
  }

  async getAudioTrackCount() {
    return this._audioTracks.length;
  }

  async getVideoTrack(index) {
    return this._videoTracks[index];
  }

  async getAudioTrack(index) {
    return this._audioTracks[index];
  }

  // Grow track arrays up to (and including) the requested index — models
  // Adobe's documented createInsertProjectItemAction auto-create behaviour
  // ("If you pass a track index greater than the number of existing tracks,
  //  a new track will be created.").
  _ensureVideoTrack(index) {
    while (this._videoTracks.length <= index) {
      const i = this._videoTracks.length;
      this._videoTracks.push(new MockVideoTrack('V' + (i + 1), i));
    }
    return this._videoTracks[index];
  }

  _ensureAudioTrack(index) {
    while (this._audioTracks.length <= index) {
      const i = this._audioTracks.length;
      this._audioTracks.push(new MockAudioTrack('A' + (i + 1), i));
    }
    return this._audioTracks[index];
  }

  async getEndTime() {
    return new MockTickTime(0);
  }

  async getFrameSize() {
    return { width: 3840, height: 2160 };
  }

  async getTimebase() {
    // Default: unavailable (null) — the mock cannot know the seed's real fps,
    // and a hardcoded 25p value falsely trips the builder's grid assert on
    // 50p fixtures. Tests exercising the assert set _timebaseTicks explicitly.
    return this._timebaseTicks || null;
  }

  async getZeroPoint() {
    return new MockTickTime(0);
  }

  async getSettings() {
    return new MockSequenceSettings();
  }

  async getSelection() {
    return this._selection || new MockTrackItemSelection();
  }

  // ⚠️ Живой API: setSelection стала СИНХРОННОЙ в 26.3, до этого возвращала
  // Promise<boolean>. Мок умеет обе формы — переключатель _setSelectionAsync,
  // чтобы компат-шим в коде был проверен и так, и так.
  setSelection(sel) {
    recorder.record('Sequence.setSelection', [sel]);
    this._selection = sel;
    return this._setSelectionAsync ? Promise.resolve(true) : true;
  }

  clearSelection() {
    recorder.record('Sequence.clearSelection', []);
    this._selection = null;
    return true;
  }

  createSetInPointAction(tickTime) {
    return new MockAction('setSequenceInPoint', { tickTime });
  }

  createSetOutPointAction(tickTime) {
    return new MockAction('setSequenceOutPoint', { tickTime });
  }

  createSetSettingsAction(settings) {
    recorder.record('Sequence.createSetSettingsAction', [settings]);
    return new MockAction('setSettings', { settings });
  }

  // Sequence.getProjectItem() (25.6+): the Project-panel item of this sequence,
  // wherever it lives (root or any bin). Set by MockProject._registerSequenceItem.
  async getProjectItem() {
    return this._projectItem || null;
  }

  // Instance method for marker access (original working API)
  async getMarkers() {
    if (!this._markersOwner) {
      this._markersOwner = new MockMarkersOwner();
    }
    return this._markersOwner;
  }
}

// --- SequenceSettings ---

class MockSequenceSettings {
  constructor() {
    this._frameRate = { value: 23.976, ticksPerFrame: 0 };
    this._frameRect = { width: 1920, height: 1080 };
    this._pixelAspectRatio = '1.0';
    this._audioSampleRate = { value: 48000 };
    this._fieldType = 0;
  }

  getVideoFrameRate() { return this._frameRate; }
  setVideoFrameRate(fr) { this._frameRate = fr; return true; }

  async getVideoFrameRect() { return this._frameRect; }
  async setVideoFrameRect(rect) { this._frameRect = rect; return true; }

  async getVideoPixelAspectRatio() { return this._pixelAspectRatio; }
  async setVideoPixelAspectRatio(par) { this._pixelAspectRatio = par; return true; }

  async getAudioSampleRate() { return this._audioSampleRate; }
  async setAudioSampleRate(rate) { this._audioSampleRate = rate; return true; }

  async getVideoFieldType() { return this._fieldType; }
  async setVideoFieldType(ft) { this._fieldType = ft; return true; }

  async getEditingMode() { return 'Custom'; }
  async setEditingMode(mode) { return true; }

  async getMaximumBitDepth() { return false; }
  async setMaximumBitDepth(v) { return true; }

  async getMaxRenderQuality() { return false; }
  async setMaxRenderQuality(v) { return true; }
}

// --- TrackItemSelection ---

class MockTrackItemSelection {
  constructor() {
    this._items = [];
  }

  addItem(item, skipDuplicateCheck) {
    // Accept either a raw track item or a cast wrapper (unwrap to the real item
    // so createRemoveItemsAction can find its _track).
    const real = (item && item._trackItem) ? item._trackItem : item;
    this._items.push(real);
    return true;
  }

  removeItem(item) {
    const real = (item && item._trackItem) ? item._trackItem : item;
    const i = this._items.indexOf(real);
    if (i >= 0) this._items.splice(i, 1);
    return true;
  }

  async getTrackItems() {
    return this._items;
  }
}

// Static accessor. LIVE 25.6 signature: createEmptySelection(callback) — the
// selection arrives via the callback and a NO-ARG call throws "Not Enough
// Parameters" (diagnosed on YTUVI05 MCAM build 2026-07-12). Mock mirrors that
// so code taking the legacy no-arg path fails here exactly like in Premiere.
const TrackItemSelectionStatic = {
  createEmptySelection(callback) {
    if (typeof callback !== 'function') throw new Error('Not Enough Parameters');
    callback(new MockTrackItemSelection());
    return true;
  },
};

// --- SequenceEditor ---

// Snapshot the duration a placement will have, reading the ProjectItem's
// CURRENT source in/out (set just before via createSetInOutPointsAction).
// If no in/out is set, fall back to the item's natural duration. This is
// evaluated at action APPLY time (transaction commit) — so a separate-
// transaction set->place->clear sequence captures the trimmed range, while
// a batched build that clears in/out before commit captures the full range.
function _placementDuration(projectItem) {
  const ip = projectItem && projectItem._inPoint;
  const op = projectItem && projectItem._outPoint;
  if (ip && op && typeof ip.seconds === 'number' && typeof op.seconds === 'number') {
    return op.seconds - ip.seconds;
  }
  if (projectItem && typeof projectItem._durationSec === 'number') return projectItem._durationSec;
  return 10;
}

function _makeTrackItem(projectItem, startSec, durSec, track) {
  const ti = new MockTrackItem(projectItem ? projectItem.name : 'item', startSec, durSec);
  ti._projectItem = projectItem;
  ti._sourceInSec = (projectItem && projectItem._inPoint
    && typeof projectItem._inPoint.seconds === 'number') ? projectItem._inPoint.seconds : 0;
  ti._track = track;
  track._items.push(ti);
  return ti;
}

// Model real track-item interactions (adversarial review 17.08.2026: a mock
// where items never interact cannot catch ordering/ripple regressions).
//
// OVERWRITE semantics: the new range replaces whatever it covers — trim the
// incumbent's tail, trim its head (advancing source-in), or remove it whole.
function _overwriteRange(track, startSec, endSec) {
  const EPS = 1e-9;
  for (let i = track._items.length - 1; i >= 0; i--) {
    const it = track._items[i];
    const itStart = it._startTimeSec;
    const itEnd = itStart + it._durationSec;
    if (itEnd <= startSec + EPS || itStart >= endSec - EPS) continue; // no overlap
    if (itStart < startSec - EPS && itEnd > endSec + EPS) {
      // covered middle — split: left part keeps head, right part keeps tail
      const right = _makeTrackItem(it._projectItem, endSec, itEnd - endSec, track);
      right._sourceInSec = (it._sourceInSec || 0) + (endSec - itStart);
      it._durationSec = startSec - itStart;
    } else if (itStart >= startSec - EPS && itEnd <= endSec + EPS) {
      track._items.splice(i, 1);                    // fully covered — remove
    } else if (itStart < startSec) {
      it._durationSec = startSec - itStart;         // tail trimmed
    } else {
      const cut = endSec - itStart;                 // head trimmed
      it._startTimeSec = endSec;
      it._durationSec = itEnd - endSec;
      it._sourceInSec = (it._sourceInSec || 0) + cut;
      if (it._durationSec <= EPS) track._items.splice(i, 1);
    }
  }
}

// INSERT semantics: items at/after the insert point shift right by the new
// clip's duration; an item SPANNING the point is split and its tail shifts.
function _rippleForInsert(track, atSec, durSec) {
  const EPS = 1e-9;
  const toAdd = [];
  for (const it of track._items) {
    const itStart = it._startTimeSec;
    const itEnd = itStart + it._durationSec;
    if (itStart >= atSec - EPS) {
      it._startTimeSec += durSec;                   // wholly after — shift
    } else if (itEnd > atSec + EPS) {
      // spans the insert point — split, tail shifts right
      const tailDur = itEnd - atSec;
      const tail = new MockTrackItem(it.name, atSec + durSec, tailDur);
      tail._projectItem = it._projectItem;
      tail._sourceInSec = (it._sourceInSec || 0) + (atSec - itStart);
      tail._track = track;
      toAdd.push(tail);
      it._durationSec = atSec - itStart;
    }
  }
  track._items.push(...toAdd);
}

class MockSequenceEditor {
  constructor(sequence) {
    this._sequence = sequence;
  }

  // Adobe docs: "If you pass a track index greater than the number of existing
  // tracks, a new track will be created." → model auto-create for INSERT.
  createInsertProjectItemAction(projectItem, time, videoTrackIndex, audioTrackIndex, limitShift) {
    _requireLock('createInsertProjectItemAction');
    recorder.record('SequenceEditor.createInsertProjectItemAction', [
      projectItem, time, videoTrackIndex, audioTrackIndex, limitShift
    ]);
    const seq = this._sequence;
    const action = new MockAction('insertProjectItem', {
      projectItem, time, videoTrackIndex, audioTrackIndex, limitShift
    });
    action.apply = function () {
      // Real Premiere rounds the INSERT position to the NEAREST frame
      // (measured YTCH13 16.08.2026, 28/28 slices) — model it. Insert RIPPLES:
      // items at/after the point shift right; a spanning item is split
      // (limitShift=true confines the ripple to the target track — modelled).
      const startSec = _nearestFrame(time && typeof time.seconds === 'number' ? time.seconds : 0);
      const durSec = _placementDuration(projectItem);
      if (videoTrackIndex >= 0) {
        const t = seq._ensureVideoTrack(videoTrackIndex);
        _rippleForInsert(t, startSec, durSec);
        _makeTrackItem(projectItem, startSec, durSec, t);
      }
      if (audioTrackIndex >= 0) {
        const t = seq._ensureAudioTrack(audioTrackIndex);
        _rippleForInsert(t, startSec, durSec);
        _makeTrackItem(projectItem, startSec, durSec, t);
      }
    };
    return action;
  }

  // Overwrite does NOT auto-create tracks in the Adobe docs — model that gap:
  // placement onto a non-existent track index is dropped (no track grown).
  // This makes the wall-clock track pre-warm load-bearing in tests.
  createOverwriteItemAction(projectItem, time, videoTrackIndex, audioTrackIndex) {
    _requireLock('createOverwriteItemAction');
    recorder.record('SequenceEditor.createOverwriteItemAction', [
      projectItem, time, videoTrackIndex, audioTrackIndex
    ]);
    const seq = this._sequence;
    const action = new MockAction('overwriteItem', {
      projectItem, time, videoTrackIndex, audioTrackIndex
    });
    action.apply = function () {
      // On-grid positions pass through exactly (measured); off-grid behaviour
      // unproven in the real app — modelled as nearest-frame. Overwrite REPLACES
      // whatever the new range covers: incumbents are tail-trimmed, head-trimmed
      // (source-in advances) or removed — so a compound executed in reverse
      // order visibly eats successors' heads, like real Premiere did on YTCH13.
      const startSec = _nearestFrame(time && typeof time.seconds === 'number' ? time.seconds : 0);
      const durSec = _placementDuration(projectItem);
      if (videoTrackIndex >= 0 && videoTrackIndex < seq._videoTracks.length) {
        const t = seq._videoTracks[videoTrackIndex];
        _overwriteRange(t, startSec, startSec + durSec);
        _makeTrackItem(projectItem, startSec, durSec, t);
      }
      if (audioTrackIndex >= 0 && audioTrackIndex < seq._audioTracks.length) {
        const t = seq._audioTracks[audioTrackIndex];
        _overwriteRange(t, startSec, startSec + durSec);
        _makeTrackItem(projectItem, startSec, durSec, t);
      }
    };
    return action;
  }

  // SequenceEditor.createCloneTrackItemAction(trackItem, timeOffset,
  //   videoTrackVerticalOffset, audioTrackVerticalOffset, alignToVideo, isInsert)
  // 25.6+ typings. CROSS-SEQUENCE semantics UNPROVEN on live 26.x — the panel's
  // probeDonorClone exists to measure them; the mock models the optimistic
  // reading: clone lands in THIS editor's sequence at donor.start + timeOffset,
  // on donorTrack + verticalOffset, carrying the donor's component chain.
  createCloneTrackItemAction(trackItem, timeOffset, videoTrackVerticalOffset,
    audioTrackVerticalOffset, alignToVideo, isInsert) {
    _requireLock('createCloneTrackItemAction');
    recorder.record('SequenceEditor.createCloneTrackItemAction', [
      trackItem, timeOffset, videoTrackVerticalOffset, audioTrackVerticalOffset,
      alignToVideo, isInsert
    ]);
    const seq = this._sequence;
    const action = new MockAction('cloneTrackItem', { trackItem });
    action.apply = function () {
      const offSec = timeOffset && typeof timeOffset.seconds === 'number' ? timeOffset.seconds : 0;
      const startSec = (trackItem._startTimeSec || 0) + offSec;
      const durSec = trackItem._durationSec || 0;
      const srcIdx = trackItem._track ? trackItem._track.id : 0;
      const vIdx = srcIdx + (videoTrackVerticalOffset || 0);
      if (vIdx < 0 || vIdx >= seq._videoTracks.length) return; // no auto-grow
      const t = seq._videoTracks[vIdx];
      if (!isInsert) _overwriteRange(t, startSec, startSec + durSec);
      const clone = new MockTrackItem(trackItem.name, startSec, durSec);
      clone._track = t;
      // Effects travel with the clone as a COPY, not an alias — live clones
      // are distinct trackItems whose chains diverge after the clone.
      if (trackItem._vclip) {
        const w = new MockVideoClipTrackItem(clone);
        w._componentChain._components = trackItem._vclip._componentChain._components.slice();
        clone._vclip = w;
      }
      t._items.push(clone);
    };
    return action;
  }

  // SequenceEditor.createRemoveItemsAction(selection, ripple, mediaType, shiftOverlapping)
  createRemoveItemsAction(trackItemSelection, ripple, mediaType, shiftOverlapping) {
    recorder.record('SequenceEditor.createRemoveItemsAction', [
      trackItemSelection, ripple, mediaType, shiftOverlapping
    ]);
    const items = (trackItemSelection && trackItemSelection._items) || [];
    const action = new MockAction('removeItems', {});
    action.apply = function () {
      for (const ti of items) {
        if (ti._track && Array.isArray(ti._track._items)) {
          const idx = ti._track._items.indexOf(ti);
          if (idx >= 0) ti._track._items.splice(idx, 1);
        }
      }
    };
    return action;
  }
}

// --- Markers ---

class MockMarker {
  constructor(name, type, startTime, duration, comments) {
    this._name = name;
    this._type = type;
    this._startTime = startTime;
    this._duration = duration;
    this._comments = comments;
    this._color = 5; // default WHITE
    this._colorIndex = 5;
  }

  getName() { return this._name; }
  getType() { return this._type; }
  getColor() { return this._color; }
  getColorIndex() { return this._colorIndex; }
  getComments() { return this._comments || ''; }
  getDuration() { return this._duration; }
  getStart() { return this._startTime; }
  getUrl() { return ''; }
  getTarget() { return ''; }

  // Real API method name (confirmed via API discovery 2026-03-09)
  createSetColorByIndexAction(colorIndex) {
    recorder.record('Marker.createSetColorByIndexAction', [colorIndex]);
    this._color = colorIndex;
    this._colorIndex = colorIndex;
    return new MockAction('setMarkerColor', { colorIndex });
  }

  createSetNameAction(name) {
    recorder.record('Marker.createSetNameAction', [name]);
    this._name = name;
    return new MockAction('setMarkerName', { name });
  }

  createSetDurationAction(duration) {
    recorder.record('Marker.createSetDurationAction', [duration]);
    this._duration = duration;
    return new MockAction('setMarkerDuration', { duration });
  }

  createSetTypeAction(type) {
    recorder.record('Marker.createSetTypeAction', [type]);
    this._type = type;
    return new MockAction('setMarkerType', { type });
  }

  createSetCommentsAction(comments) {
    recorder.record('Marker.createSetCommentsAction', [comments]);
    this._comments = comments;
    return new MockAction('setMarkerComments', { comments });
  }
}

class MockMarkersOwner {
  constructor() {
    this._markers = [];
  }

  getMarkers() {
    return this._markers;
  }

  // Direct async marker creation (original working API: seq.getMarkers() → createMarker)
  async createMarker(startTime, markerType, name, comments) {
    recorder.record('Markers.createMarker', [startTime, markerType, name, comments]);
    const marker = new MockMarker(name, markerType, startTime, TickTimeStatic.TIME_ZERO, comments);
    this._markers.push(marker);
    return marker;
  }

  createAddMarkerAction(name, markerType, startTime, duration, comments) {
    recorder.record('Markers.createAddMarkerAction', [name, markerType, startTime, duration, comments]);
    const marker = new MockMarker(name, markerType, startTime, duration, comments);
    this._markers.push(marker);
    return new MockAction('addMarker', { name, markerType, startTime, duration, comments });
  }

  createRemoveMarkerAction(marker) {
    recorder.record('Markers.createRemoveMarkerAction', [marker]);
    const i = this._markers.indexOf(marker);
    if (i >= 0) this._markers.splice(i, 1);
    return new MockAction('removeMarker', { marker });
  }
}

// --- Project ---

class MockProject {
  constructor(name = 'TestProject') {
    this.name = name;
    this.path = '/tmp/TestProject.prproj';
    this.guid = 'proj-123';
    this._rootItem = new MockFolderItem('root');
    this._sequences = [];
    this._activeSequence = null;
  }

  async getRootItem() {
    return this._rootItem;
  }

  async getActiveSequence() {
    return this._activeSequence;
  }

  async setActiveSequence(sequence) {
    this._activeSequence = sequence;
    return true;
  }

  // Real Premiere puts a ProjectItem for every new sequence at the project root
  // (same guid as the Sequence) — the bin-move path locates the sequence there.
  _registerSequenceItem(seq) {
    const stub = {
      name: seq.name,
      guid: seq.guid,
      type: 1,
      _parent: this._rootItem,
      getId() { return _idOf(this); },
      getParentBin() { return this._parent || null; },
      createSetNameAction(newName) {
        recorder.record('ProjectItem.createSetNameAction', [newName]);
        const self = this;
        const action = new MockAction('setName', { name: newName });
        action.apply = function () { self.name = newName; };
        return action;
      }
    };
    this._rootItem._items.push(stub);
    seq._projectItem = stub;   // Sequence.getProjectItem() back-reference
    return stub;
  }

  // Empty sequence — models a realistic minimal sequence (1 V / 1 A track) so
  // the wall-clock track auto-create / pre-warm path is genuinely exercised.
  async createSequence(name) {
    recorder.record('Project.createSequence', [name]);
    const seq = new MockSequence(name, { videoTracks: 1, audioTracks: 1 });
    this._sequences.push(seq);
    this._registerSequenceItem(seq);
    return seq;
  }

  // From-media creates a sequence sized to the media with the first clip seeded
  // on V1+A1 — models real Premiere (1 video + 1 audio track, clip at t=0).
  async createSequenceFromMedia(name, clipProjectItems, targetBin) {
    recorder.record('Project.createSequenceFromMedia', [name, clipProjectItems, targetBin]);
    const seq = new MockSequence(name, { videoTracks: 1, audioTracks: 1 });
    // Seed the first clip on V1 + A1 at t=0 (as real createSequenceFromMedia does).
    const seed = Array.isArray(clipProjectItems) ? clipProjectItems[0] : clipProjectItems;
    if (seed) {
      const dur = (typeof seed._durationSec === 'number') ? seed._durationSec : 10;
      _makeTrackItem(seed, 0, dur, seq._videoTracks[0]);
      _makeTrackItem(seed, 0, dur, seq._audioTracks[0]);
    }
    this._sequences.push(seq);
    this._registerSequenceItem(seq);
    return seq;
  }

  async getSequences() {
    return this._sequences;
  }

  async deleteSequence(sequence) {
    recorder.record('Project.deleteSequence', [sequence]);
    const i = this._sequences.indexOf(sequence);
    if (i >= 0) this._sequences.splice(i, 1);
    // The sequence's project item may have been moved into a bin — remove it from there.
    const pi = sequence && sequence._projectItem;
    if (pi && pi._parent && Array.isArray(pi._parent._items) && pi._parent._items.indexOf(pi) >= 0) {
      pi._parent._items.splice(pi._parent._items.indexOf(pi), 1);
    } else {
      const stub = this._rootItem._items.findIndex((it) => it && it.guid === sequence.guid);
      if (stub >= 0) this._rootItem._items.splice(stub, 1);
    }
    return true;
  }

  async importFiles(filePaths, suppressUI, targetBin, asNumberedStills) {
    recorder.record('Project.importFiles', [filePaths, suppressUI, targetBin, asNumberedStills]);
    // Simulate: add ClipProjectItems for each file
    for (const fp of filePaths) {
      const name = fp.split('/').pop();
      const clip = new MockClipProjectItem(name, fp);
      if (targetBin) {
        targetBin._items.push(clip);
        clip._parent = targetBin;
      } else {
        this._rootItem._items.push(clip);
        clip._parent = this._rootItem;
      }
    }
    return true;
  }

  async save() {
    recorder.record('Project.save', []);
    return true;
  }

  lockedAccess(callback) {
    recorder.record('Project.lockedAccess', []);
    // Model real 25.6 locking: SequenceEditor action factories THROW
    // "Requires locked access" outside this scope (measured 17.08.2026 —
    // a build that created overwrite actions before lockedAccess placed
    // ZERO video clips on a live timeline).
    LOCK.depth++;
    try {
      const res = callback();
      if (res && typeof res.then === 'function') {
        return res.finally(() => { LOCK.depth--; });
      }
      LOCK.depth--;
      return res;
    } catch (e) {
      LOCK.depth--;
      throw e;
    }
  }

  executeTransaction(callback, undoString) {
    recorder.record('Project.executeTransaction', [undoString]);
    const compoundAction = new MockCompoundAction();
    callback(compoundAction);
    // Apply queued actions at commit time IN REVERSE ORDER — measured Premiere
    // behaviour (YTCH13 16.08.2026: in a batched compound the overwrite of
    // RYA-FX3-1052 executed after 1053's and ate its head frame; see also
    // memory feedback_uxp_insert_order "реверс same-tc"). Builders must NOT
    // rely on insertion order inside one compound — wallClockBuilder places
    // video via per-clip transactions for exactly this reason.
    for (let i = compoundAction.actions.length - 1; i >= 0; i--) {
      const action = compoundAction.actions[i];
      if (action && typeof action.apply === 'function') {
        try { action.apply(); } catch (e) { /* mock apply best-effort */ }
      }
    }
    return true;
  }
}

// --- VideoComponentChain ---

class MockVideoComponentChain {
  constructor() {
    this._components = [];
  }

  async getComponents() {
    return this._components;
  }

  createAppendComponentAction(component) {
    recorder.record('VideoComponentChain.createAppendComponentAction', [component]);
    this._components.push(component);
    return new MockAction('appendComponent', { component });
  }
}

// --- VideoComponent ---

class MockVideoComponent {
  constructor(matchName, displayName) {
    this.matchName = matchName;
    this.displayName = displayName;
    this._params = [];
  }

  async getParamCount() {
    return this._params.length;
  }

  async getParam(index) {
    return this._params[index] || { displayName: `Param_${index}`, name: `param_${index}` };
  }
}

// --- ComponentParam ---
//
// Models the 26.x ComponentParam surface used by setEffectParam:
//   displayName (readonly PROPERTY — the live type has NO getDisplayName()),
//   getStartValue() → Keyframe {value:{value}}, createKeyframe(v) — THROWS
//   «Illegal Parameter type» on a value/param type mismatch (typings-documented,
//   the 18.08 YTCH13 blocker wording), createSetValueAction(kf, safe).
// opts: { type: 'string'|'number'|..  — native param type (default typeof value),
//         noStartValue: true         — build without getStartValue,
//         strictSet: true            — createSetValueAction also type-checks,
//         ignoreSet: true            — commit succeeds but the value silently
//                                      stays (measured live Lumetri Look 18.08:
//                                      numeric menu index ignores a string) }
class MockComponentParam {
  constructor(displayName, value, opts) {
    opts = opts || {};
    this.displayName = displayName;
    this._value = value;
    this._type = opts.type || typeof value;
    this._strictSet = !!opts.strictSet;
    this._ignoreSet = !!opts.ignoreSet;
    // Live Premiere 26 (25.09.2026, 10 of 10 clips): a MUTATED getStartValue()
    // keyframe commits without an exception and does not apply; a keyframe from
    // createKeyframe() applies. mutateNoop reproduces exactly that.
    this._mutateNoop = !!opts.mutateNoop;
    this._fresh = new WeakSet();
    // Premiere stores float32: write 1.2, read 1.2000000476837158.
    this._fround = !!opts.fround;
    if (opts.noStartValue) this.getStartValue = undefined;
  }

  async getStartValue() {
    return { value: { value: this._value } };
  }

  createKeyframe(v) {
    recorder.record('ComponentParam.createKeyframe', [v]);
    if (typeof v !== this._type) throw new Error('Illegal Parameter type');
    const kf = { value: { value: v } };
    this._fresh.add(kf);
    return kf;
  }

  createSetValueAction(kf, inSafeForPlayback) {
    recorder.record('ComponentParam.createSetValueAction', [kf, inSafeForPlayback]);
    const self = this;
    const v = kf && kf.value;
    const landed = (v && typeof v === 'object' && 'value' in v) ? v.value : v;
    if (this._strictSet && typeof landed !== this._type) throw new Error('Illegal Parameter type');
    const action = new MockAction('setParamValue', { value: landed });
    const fresh = this._fresh.has(kf);
    action.apply = function () {
      if (self._ignoreSet) return;
      if (self._mutateNoop && !fresh) return;
      self._value = (self._fround && typeof landed === 'number') ? Math.fround(landed) : landed;
    };
    return action;
  }
}

// --- VideoClipTrackItem ---

class MockVideoClipTrackItem {
  constructor(trackItem) {
    this._trackItem = trackItem;
    this._componentChain = new MockVideoComponentChain();
  }

  async getComponentChain() {
    return this._componentChain;
  }

  async getName() {
    return this._trackItem ? this._trackItem.name : 'unknown';
  }
}

// --- Constants ---

const Constants = {
  MediaType: { VIDEO: 0, AUDIO: 1 },
  TrackItemType: { CLIP: 0, EMPTY: 1 },
  ContentType: { MEDIA: 0, SEQUENCE: 1 },
  VideoFieldType: { LOWER_FIRST: 0, UPPER_FIRST: 1 },
  PixelAspectRatio: { SQUARE: 1.0 },
  // Real Premiere Pro API values (confirmed via debug log 15-27-04)
  // Note: index 2 is missing in real API!
  ProjectItemColorLabel: {
    VIOLET: 0, IRIS: 1, LAVENDER: 3, CERULEAN: 4, FOREST: 5,
    ROSE: 6, MANGO: 7, PURPLE: 8, BLUE: 9, TEAL: 10,
    MAGENTA: 11, TAN: 12, GREEN: 13, BROWN: 14, YELLOW: 15
  },
  // Real API: no WHITE (index 5 missing), typo "MAGNETA" in Premiere
  MarkerColor: {
    GREEN: 0, RED: 1, MAGNETA: 2, ORANGE: 3, YELLOW: 4,
    BLUE: 6, CYAN: 7
  }
};

// --- Marker type constants ---

const MarkerStatic = {
  MARKER_TYPE_COMMENT: 'Comment',
  MARKER_TYPE_CHAPTER: 'Chapter',
  MARKER_TYPE_SEGMENTATION: 'Segmentation',
  MARKER_TYPE_WEBLINK: 'WebLink',
  MARKER_TYPE_FLVCUEPOINT: 'FlashCuePoint'
};

// --- Static accessors ---

const SequenceEditorStatic = {
  getEditor(sequence) {
    return new MockSequenceEditor(sequence);
  }
};

// One owner per sequence object, like the real API — otherwise a second
// getMarkers() call would hand back an empty list and hide duplicate/replace bugs.
const _markerOwners = new WeakMap();

const MarkersStatic = {
  async getMarkers(owner) {
    if (owner && typeof owner === 'object') {
      if (!_markerOwners.has(owner)) _markerOwners.set(owner, new MockMarkersOwner());
      return _markerOwners.get(owner);
    }
    return new MockMarkersOwner();
  }
};

const ClipProjectItemStatic = {
  cast(projectItem) {
    if (projectItem && (projectItem instanceof MockClipProjectItem || projectItem.type === 1)) {
      return projectItem;
    }
    return null;
  }
};

const FolderItemStatic = {
  cast(projectItem) {
    if (projectItem && (projectItem instanceof MockFolderItem || projectItem.type === 2)) {
      return projectItem;
    }
    return null;
  }
};

const ProjectStatic = {
  async getActiveProject() {
    return new MockProject();
  }
};

const ProjectItemStatic = {
  TYPE_CLIP: 1,
  TYPE_BIN: 2,
  TYPE_FILE: 3,
  TYPE_ROOT: 4,
  TYPE_COMPOUND: 5,
  TYPE_STYLE: 6
};

const FrameRateStatic = {
  createWithValue(value) {
    return { value };
  }
};

const VideoClipTrackItemStatic = {
  // Cached per trackItem — live items carry ONE stable component chain, so a
  // repeated cast must not hand out a fresh empty chain (pre-18.08 mock did,
  // which diverged from live: applyEffect's append was invisible to the next
  // hasEffect/setEffectParam).
  cast(trackItem) {
    if (!trackItem) return null;
    if (!trackItem._vclip) trackItem._vclip = new MockVideoClipTrackItem(trackItem);
    return trackItem._vclip;
  }
};

const VideoFilterFactoryStatic = {
  _matchNames: ['AE.ADBE Lumetri', 'AE.ADBE Gaussian Blur 2', 'AE.ADBE Motion'],
  _displayNames: ['Lumetri Color', 'Gaussian Blur', 'Motion'],
  async getMatchNames() {
    return this._matchNames;
  },
  async getDisplayNames() {
    return this._displayNames;
  },
  async createComponent(matchName) {
    recorder.record('VideoFilterFactory.createComponent', [matchName]);
    return new MockVideoComponent(matchName, 'Lumetri Color');
  }
};

// --- Main export (mimics `require("premierepro")`) ---

const premierepro = {
  Project: ProjectStatic,
  ProjectItem: ProjectItemStatic,
  Sequence: { getSequence() { return null; } },
  SequenceEditor: SequenceEditorStatic,
  ClipProjectItem: ClipProjectItemStatic,
  FolderItem: FolderItemStatic,
  Markers: MarkersStatic,
  Marker: MarkerStatic,
  TickTime: TickTimeStatic,
  FrameRate: FrameRateStatic,
  VideoClipTrackItem: VideoClipTrackItemStatic,
  TrackItemSelection: TrackItemSelectionStatic,
  VideoFilterFactory: VideoFilterFactoryStatic,
  Constants,
  // Test helpers
  _recorder: recorder,
  _quant: QUANT, // measured Premiere frame-quantization model (fps of the grid)
  _MockProject: MockProject,
  _MockSequence: MockSequence,
  _MockFolderItem: MockFolderItem,
  _MockClipProjectItem: MockClipProjectItem,
  _MockMarkersOwner: MockMarkersOwner,
  _MockTrackItem: MockTrackItem,
  _MockVideoClipTrackItem: MockVideoClipTrackItem,
  _MockVideoComponentChain: MockVideoComponentChain,
  _MockVideoComponent: MockVideoComponent,
  _MockComponentParam: MockComponentParam
};

module.exports = premierepro;
