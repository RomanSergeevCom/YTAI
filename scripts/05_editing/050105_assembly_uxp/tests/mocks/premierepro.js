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

  createBinAction(name, makeUnique) {
    recorder.record('FolderItem.createBinAction', [name, makeUnique]);
    const newBin = new MockFolderItem(name);
    this._items.push(newBin);
    return new MockAction('createBin', { name, makeUnique });
  }

  createMoveItemAction(item, newParent) {
    recorder.record('FolderItem.createMoveItemAction', [item, newParent]);
    return new MockAction('moveItem', { item, newParent });
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

  async getContentType() {
    return 0; // MEDIA
  }

  async isSequence() {
    return false;
  }

  createSetInOutPointsAction(inPoint, outPoint) {
    recorder.record('ClipProjectItem.createSetInOutPointsAction', [inPoint, outPoint]);
    this._inPoint = inPoint;
    this._outPoint = outPoint;
    return new MockAction('setInOutPoints', { inPoint, outPoint });
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

  async getProjectItem() {
    return this._projectItem || new MockClipProjectItem(this.name);
  }
}

// --- VideoTrack ---

class MockVideoTrack {
  constructor(name, index) {
    this.name = name;
    this.id = index;
    this._items = [];
  }

  async getIndex() {
    return this.id;
  }

  getTrackItems(type, includeEmpty) {
    return this._items;
  }

  async getMediaType() {
    return 'video';
  }
}

// --- Sequence ---

class MockSequence {
  constructor(name) {
    this.name = name;
    this.guid = 'seq-' + Math.random().toString(36).substr(2, 9);
    this._videoTracks = [new MockVideoTrack('V1', 0), new MockVideoTrack('V2', 1), new MockVideoTrack('V3', 2)];
    this._audioTracks = [];
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

  async getEndTime() {
    return new MockTickTime(0);
  }

  async getFrameSize() {
    return { width: 3840, height: 2160 };
  }

  async getTimebase() {
    // 254016000000 / 25 = 10160640000
    return '10160640000';
  }

  async getZeroPoint() {
    return new MockTickTime(0);
  }

  async getSettings() {
    return new MockSequenceSettings();
  }

  async getSelection() {
    return new MockTrackItemSelection();
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

  addItem(item) {
    this._items.push(item);
    return true;
  }

  async getTrackItems() {
    return this._items;
  }
}

// --- SequenceEditor ---

class MockSequenceEditor {
  constructor(sequence) {
    this._sequence = sequence;
  }

  createInsertProjectItemAction(projectItem, time, videoTrackIndex, audioTrackIndex, limitShift) {
    recorder.record('SequenceEditor.createInsertProjectItemAction', [
      projectItem, time, videoTrackIndex, audioTrackIndex, limitShift
    ]);
    return new MockAction('insertProjectItem', {
      projectItem, time, videoTrackIndex, audioTrackIndex, limitShift
    });
  }

  createOverwriteItemAction(projectItem, time, videoTrackIndex, audioTrackIndex) {
    recorder.record('SequenceEditor.createOverwriteItemAction', [
      projectItem, time, videoTrackIndex, audioTrackIndex
    ]);
    return new MockAction('overwriteItem', {
      projectItem, time, videoTrackIndex, audioTrackIndex
    });
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

  async createSequence(name) {
    recorder.record('Project.createSequence', [name]);
    const seq = new MockSequence(name);
    this._sequences.push(seq);
    return seq;
  }

  async createSequenceFromMedia(name, clipProjectItems, targetBin) {
    recorder.record('Project.createSequenceFromMedia', [name, clipProjectItems, targetBin]);
    const seq = new MockSequence(name);
    this._sequences.push(seq);
    return seq;
  }

  async getSequences() {
    return this._sequences;
  }

  async importFiles(filePaths, suppressUI, targetBin, asNumberedStills) {
    recorder.record('Project.importFiles', [filePaths, suppressUI, targetBin, asNumberedStills]);
    // Simulate: add ClipProjectItems for each file
    for (const fp of filePaths) {
      const name = fp.split('/').pop();
      const clip = new MockClipProjectItem(name, fp);
      if (targetBin) {
        targetBin._items.push(clip);
      } else {
        this._rootItem._items.push(clip);
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
    return callback();
  }

  executeTransaction(callback, undoString) {
    recorder.record('Project.executeTransaction', [undoString]);
    const compoundAction = new MockCompoundAction();
    callback(compoundAction);
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
  MARKER_TYPE_WEBLINK: 'WebLink',
  MARKER_TYPE_FLVCUEPOINT: 'FlashCuePoint'
};

// --- Static accessors ---

const SequenceEditorStatic = {
  getEditor(sequence) {
    return new MockSequenceEditor(sequence);
  }
};

const MarkersStatic = {
  async getMarkers(owner) {
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
  cast(trackItem) {
    if (trackItem) {
      return new MockVideoClipTrackItem(trackItem);
    }
    return null;
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
  VideoFilterFactory: VideoFilterFactoryStatic,
  Constants,
  // Test helpers
  _recorder: recorder,
  _MockProject: MockProject,
  _MockSequence: MockSequence,
  _MockFolderItem: MockFolderItem,
  _MockClipProjectItem: MockClipProjectItem,
  _MockMarkersOwner: MockMarkersOwner,
  _MockTrackItem: MockTrackItem,
  _MockVideoClipTrackItem: MockVideoClipTrackItem,
  _MockVideoComponentChain: MockVideoComponentChain,
  _MockVideoComponent: MockVideoComponent
};

module.exports = premierepro;
