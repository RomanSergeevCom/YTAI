const loadingEl = document.getElementById('loading');
const errorEl = document.getElementById('error');
const contentEl = document.getElementById('content');
const titleEl = document.getElementById('videoTitle');
const langSelect = document.getElementById('langSelect');
const downloadBtn = document.getElementById('downloadBtn');
const statusEl = document.getElementById('status');
const debugEl = document.getElementById('debug');
const debugLogEl = document.getElementById('debugLog');
const brandToggle = document.getElementById('brandToggle');
const pageMetaEl = document.getElementById('pageMeta');

let captionTracks = [];
let site = '';        // 'youtube' | 'vk' | 'rutube' | 'ok'
let videoUrl = '';    // canonical page URL passed to yt-dlp
let videoId = '';     // YouTube only (subtitles flow)
let videoTitle = '';
let videoMeta = {};
let tabId = null;

// What the current tab is: one video, a whole channel/playlist, or neither.
// The popup shows a different set of tabs for each.
let pageMode = 'none';   // 'video' | 'channel' | 'none'
let collection = null;   // detectYouTubeCollection() result on a channel page
let channelInfo = null;  // host's flat probe of that channel

// detectSite() / detectYouTubeCollection() live in common.js (shared with
// background.js for the context-menu path) — loaded before this file.

// Strip site-name suffixes from document.title for a first-guess video title
// (the formats probe replaces it with yt-dlp's exact title when it lands).
function cleanTabTitle(t) {
  return (t || '')
    .replace(/\s*-\s*YouTube$/, '')
    .replace(/\s*[|—–-]\s*VK\s*(Видео|Video)?\s*$/i, '')
    .replace(/\s*[|—–-]\s*(смотреть\s+)?(онлайн\s+)?видео\s+(от|в)\s+.*$/i, '')
    .replace(/\s*[|—–-]\s*RUTUBE\s*$/i, '')
    .replace(/\s*[|—–-]\s*OK(\.RU)?\s*$/i, '')
    .trim();
}

// --- Debug ---
function log(msg) {
  const ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
  debugLogEl.textContent += `[${ts}] ${msg}\n`;
  debugLogEl.scrollTop = debugLogEl.scrollHeight;
  console.log('[RYA DL]', msg);
}

brandToggle.addEventListener('click', () => debugEl.classList.toggle('hidden'));

// ============================================================
// Content script functions — run IN youtube.com page context
// ============================================================

// 1) Get caption tracks via innertube + title from DOM
async function getVideoData(videoId) {
  try {
    // Title from DOM (always correct encoding)
    const titleEl = document.querySelector('yt-formatted-string.style-scope.ytd-watch-metadata')
      || document.querySelector('h1.ytd-watch-metadata yt-formatted-string')
      || document.querySelector('#title h1 yt-formatted-string')
      || document.querySelector('title');
    const title = titleEl ? titleEl.textContent.replace(/ - YouTube$/, '').trim() : '';

    // Get API key
    let apiKey = '';
    try {
      if (typeof ytcfg !== 'undefined' && ytcfg.get) {
        apiKey = ytcfg.get('INNERTUBE_API_KEY') || '';
      }
    } catch (e) { /* ignore */ }

    const url = apiKey
      ? `https://www.youtube.com/youtubei/v1/player?key=${apiKey}&prettyPrint=false`
      : 'https://www.youtube.com/youtubei/v1/player?prettyPrint=false';

    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        videoId: videoId,
        context: {
          client: {
            clientName: 'ANDROID',
            clientVersion: '20.10.38'
          }
        }
      })
    });

    if (!resp.ok) {
      return { error: `Innertube HTTP ${resp.status}` };
    }

    const data = await resp.json();
    const status = data.playabilityStatus?.status;

    if (status && status !== 'OK') {
      return { error: `Video: ${status} — ${data.playabilityStatus?.reason || ''}` };
    }

    const tracks = data.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    const vd = data.videoDetails || {};
    const mf = data.microformat?.playerMicroformatRenderer || {};

    // Likes from DOM (not available in innertube ANDROID response)
    let likes = 0;
    try {
      const likeBtn = document.querySelector('like-button-view-model button[aria-label]')
        || document.querySelector('#top-level-buttons-computed ytd-toggle-button-renderer button[aria-label]');
      const likesMatch = likeBtn?.getAttribute('aria-label')?.match(/[\d,.\s]+/);
      if (likesMatch) {
        likes = parseInt(likesMatch[0].replace(/[,.\s]/g, '')) || 0;
      }
    } catch (e) { /* ignore */ }

    return {
      title,
      channel: vd.author || '',
      channelId: vd.channelId || '',
      publishedDate: mf.publishDate || '',
      duration: parseInt(vd.lengthSeconds || '0'),
      views: parseInt(vd.viewCount || '0'),
      likes,
      description: vd.shortDescription || '',
      tracks: tracks.map(t => ({
        baseUrl: t.baseUrl,
        languageCode: t.languageCode,
        name: t.name?.runs?.[0]?.text || t.name?.simpleText || t.languageCode,
        kind: t.kind || ''
      })),
      apiKey: apiKey ? 'yes' : 'no',
      trackCount: tracks.length
    };

  } catch (e) {
    return { error: 'getVideoData: ' + e.message };
  }
}

// 2) Fetch raw XML — return as string, parse in popup
async function fetchRawXml(baseUrl) {
  try {
    let url = baseUrl
      .replace(/&fmt=srv3/g, '')
      .replace(/&fmt=json3/g, '')
      .replace(/&fmt=vtt/g, '');

    const resp = await fetch(url);
    if (!resp.ok) {
      return { error: `Timedtext HTTP ${resp.status}` };
    }

    const text = await resp.text();
    if (!text || text.length < 10) {
      return { error: `Empty response (${text.length} chars)` };
    }

    return { xml: text };

  } catch (e) {
    return { error: 'fetchRawXml: ' + e.message };
  }
}

// ============================================================
// Popup logic
// ============================================================

async function init() {
  const ver = chrome.runtime.getManifest().version;
  const verEl = document.getElementById('brandVer');
  if (verEl) verEl.textContent = 'v' + ver;
  log(`Init v${ver}`);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    tabId = tab.id;

    const det = detectSite(tab.url || '');

    // A YouTube channel / playlist page: whole-channel jobs instead of one video.
    if (!det) {
      collection = detectYouTubeCollection(tab.url || '');
      if (collection) {
        log(`Channel: ${collection.kind} — ${collection.url}`);
        titleEl.textContent = decodeURIComponent(collection.handle || '') || 'Channel';
        loadingEl.classList.add('hidden');
        contentEl.classList.remove('hidden');
        setMode('channel');
        paintChannelHints();  // placeholder text until the probe lands
        restoreActiveDownload();
        return;
      }
    }

    if (!det) {
      // Neither a video nor a channel. A job may still be running (the host is
      // independent of the popup) — surface it so it stays watchable and
      // cancellable instead of hiding it behind the hint.
      chrome.runtime.sendMessage({ action: 'getDownloadState' }, st => {
        loadingEl.classList.add('hidden');
        if (!chrome.runtime.lastError && st) {
          log(`Job state on an unrelated page (${st.status}) — restore view`);
          contentEl.classList.remove('hidden');
          setMode('none');
          if (st.status === 'downloading') applyRestoredState(st);
          else paintTerminalState(st);
          setControlsEnabled(false);
          hostHint.textContent =
            'Open a video or a channel page to start a new job.';
          hostHint.classList.remove('hidden');
        } else {
          showError('Open a video or a channel page first — YouTube · VK · Rutube · OK');
        }
      });
      return;
    }
    site = det.site;
    videoUrl = det.url;
    videoId = det.videoId || '';
    log(`Site: ${site} — ${videoUrl}`);

    // Show the UI immediately. Video download only needs the page URL, so it
    // must NOT wait for — or depend on — subtitles being available.
    videoTitle = cleanTabTitle(tab.title) || videoId || videoUrl;
    titleEl.textContent = videoTitle;
    loadingEl.classList.add('hidden');
    contentEl.classList.remove('hidden');
    setMode('video');   // Video · Subtitles · Comments
    log('UI ready');

    if (site === 'youtube') {
      // Load subtitles in the background — failure must not block video download.
      loadSubtitles();
    } else {
      // The Subtitles tab reads YouTube's innertube captions and the Comments
      // tab is a YouTube API; on VK/Rutube/OK only the media download applies.
      ['subs', 'comments'].forEach(t => {
        const el = document.querySelector(`.tab[data-tab="${t}"]`);
        if (el) el.classList.add('hidden');
      });
    }

    // If a job is already running (popup was reopened), restore its status.
    restoreActiveDownload();

    // Cleanup old files
    try {
      chrome.runtime.sendMessage({ action: 'cleanup' }, r => {
        if (r?.total > 0) log(`Cleanup: ${r.removed}/${r.total} old files`);
      });
    } catch (e) { /* ignore */ }

  } catch (err) {
    log('INIT ERROR: ' + err.message);
    showError(err.message);
  }
}

// Best-effort subtitle discovery (independent of the video-download flow).
async function loadSubtitles() {
  try {
    log('Innertube POST (ANDROID)...');
    // A slow page/network can stall this well past 8s. Show an interim note
    // then, but DON'T abandon the request — on slow links (VPN, hotel Wi-Fi)
    // the innertube call routinely succeeds after 8s and must still populate.
    const slowTimer = setTimeout(() => {
      statusEl.textContent = 'Still scanning subtitles… (slow page or network)';
      statusEl.className = 'note';
    }, 8000);
    let results;
    try {
      results = await chrome.scripting.executeScript({
        target: { tabId },
        func: getVideoData,
        args: [videoId]
      });
    } finally {
      clearTimeout(slowTimer);
      statusEl.className = 'hidden';
    }

    const vd = results?.[0]?.result;
    if (!vd) { markNoSubtitles('Could not read page — refresh'); return; }

    log(`API key: ${vd.apiKey}, tracks: ${vd.trackCount}, error: ${vd.error || 'none'}`);
    if (vd.error) { markNoSubtitles(vd.error); return; }

    // Precise title + metadata (used for the subtitle JSON output).
    if (vd.title) { videoTitle = vd.title; titleEl.textContent = videoTitle; }
    videoMeta = {
      channel: vd.channel,
      channel_id: vd.channelId,
      published_date: vd.publishedDate,
      duration: formatDuration(vd.duration),
      duration_seconds: vd.duration,
      views: vd.views,
      likes: vd.likes,
      description: vd.description
    };

    if (!vd.tracks || vd.tracks.length === 0) {
      markNoSubtitles('No subtitles for this video');
      return;
    }

    captionTracks = vd.tracks;
    captionTracks.sort((a, b) => {
      if ((a.kind === 'asr') !== (b.kind === 'asr')) return a.kind === 'asr' ? 1 : -1;
      return 0;
    });

    langSelect.innerHTML = '';
    captionTracks.forEach((track, i) => {
      const opt = document.createElement('option');
      opt.value = i;
      const suffix = track.kind === 'asr' ? ' (auto)' : '';
      opt.textContent = `${track.name}${suffix}`;
      langSelect.appendChild(opt);
      log(`  [${i}] ${track.name}${suffix} — ${track.languageCode}`);
    });
    langSelect.value = 0;
    langSelect.disabled = false;
    downloadBtn.disabled = false;
    log('Subtitles ready');

  } catch (e) {
    markNoSubtitles(e.message);
  }
}

// No subtitles available — disable only the Subtitles tab; video still works.
// If the user is still on the Subtitles tab, jump them to Video.
function markNoSubtitles(reason) {
  log('No subtitles: ' + reason);
  captionTracks = [];
  langSelect.innerHTML = '';
  const opt = document.createElement('option');
  opt.textContent = 'No subtitles';
  langSelect.appendChild(opt);
  langSelect.disabled = true;
  downloadBtn.disabled = true;
  statusEl.textContent = reason;
  statusEl.className = 'note';
  statusEl.classList.remove('hidden');

  const subsTab = document.querySelector('.tab[data-tab="subs"]');
  const videoTab = document.querySelector('.tab[data-tab="video"]');
  if (videoTab && subsTab && subsTab.classList.contains('active')) {
    videoTab.click(); // auto-switch to the working tab
  }
}

function showError(msg) {
  log('ERROR: ' + msg);
  loadingEl.classList.add('hidden');
  errorEl.textContent = msg;
  errorEl.classList.remove('hidden');
}

function showStatus(msg, type) {
  statusEl.textContent = msg;
  statusEl.className = type;
}

function formatTC(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toFixed(3).padStart(6, '0')}`;
}

function formatDuration(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function sanitizeFilename(str) {
  const cleaned = str
    .replace(/[<>:"/\\|?*]/g, '')
    .replace(/\s+/g, '_')
    .replace(/^[.\s_]+/, ''); // leading dot = hidden file → chrome.downloads rejects it
  // Truncate on code points so an emoji isn't split into a lone surrogate.
  return Array.from(cleaned).slice(0, 80).join('') || 'video';
}

// Parse XML in popup context (proper UTF-8 handling)
function parseTranscriptXml(xmlStr) {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmlStr, 'text/xml');

  const parseError = doc.querySelector('parsererror');
  if (parseError) {
    return { error: 'XML parse error' };
  }

  const textEls = doc.querySelectorAll('text');
  if (textEls.length === 0) {
    return { error: 'No <text> elements' };
  }

  const segments = Array.from(textEls).map(el => ({
    text: el.textContent || '',
    start: parseFloat(el.getAttribute('start') || '0'),
    dur: parseFloat(el.getAttribute('dur') || '0')
  }));

  return { segments };
}

// --- Download ---
downloadBtn.addEventListener('click', async () => {
  const track = captionTracks[parseInt(langSelect.value)];
  downloadBtn.disabled = true;
  downloadBtn.textContent = '...';
  statusEl.className = 'hidden';

  try {
    log('Fetching raw XML...');

    // Get raw XML from content script
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: fetchRawXml,
      args: [track.baseUrl]
    });

    const res = results?.[0]?.result;
    if (!res) {
      showStatus('Content script returned null', 'error');
      resetBtn();
      return;
    }

    if (res.error) {
      log('Fetch error: ' + res.error);
      showStatus(res.error, 'error');
      resetBtn();
      return;
    }

    log(`Raw XML: ${res.xml.length} chars`);

    // Parse XML in popup context (proper UTF-8)
    const parsed = parseTranscriptXml(res.xml);
    if (parsed.error) {
      log('Parse error: ' + parsed.error);
      showStatus(parsed.error, 'error');
      resetBtn();
      return;
    }

    log(`Parsed: ${parsed.segments.length} segments`);

    // Convert to our JSON format
    const segments = parsed.segments
      .filter(s => s.text && s.text.trim())
      .map(s => ({
        text: s.text.trim(),
        tc_in: formatTC(s.start),
        tc_out: formatTC(s.start + s.dur)
      }));

    log(`Output: ${segments.length} segments`);

    const output = {
      video_id: videoId,
      video_url: `https://www.youtube.com/watch?v=${videoId}`,
      title: videoTitle,
      channel: videoMeta.channel,
      channel_id: videoMeta.channel_id,
      channel_url: videoMeta.channel_id
        ? `https://www.youtube.com/channel/${videoMeta.channel_id}`
        : '',
      published_date: videoMeta.published_date,
      duration: videoMeta.duration,
      duration_seconds: videoMeta.duration_seconds,
      views: videoMeta.views,
      likes: videoMeta.likes,
      description: videoMeta.description,
      language: track.languageCode,
      auto_generated: track.kind === 'asr',
      segments
    };

    const jsonStr = JSON.stringify(output, null, 2);

    // Filename: sanitized title + video ID
    const safeName = sanitizeFilename(videoTitle);
    const filename = `${safeName}_${videoId}_${track.languageCode}.json`;

    log(`Download: ${filename}`);

    // Download straight from the popup via a blob URL. A base64 data URI
    // through the background hits Chromium's ~2MB URL cap on long (especially
    // Russian) transcripts; a blob URL has no such limit and needs no relay.
    const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8' });
    const blobUrl = URL.createObjectURL(blob);
    chrome.downloads.download({ url: blobUrl, filename, saveAs: false }, (downloadId) => {
      if (chrome.runtime.lastError) {
        log('Download error: ' + chrome.runtime.lastError.message);
        showStatus('Download failed: ' + chrome.runtime.lastError.message, 'error');
        URL.revokeObjectURL(blobUrl);
        return;
      }
      log('Download started, id: ' + downloadId);

      // Record the id so background cleanup only ever deletes OUR files.
      chrome.storage.local.get({ subsDownloads: [] }, ({ subsDownloads }) => {
        subsDownloads.push({ id: downloadId, t: Date.now() });
        chrome.storage.local.set({ subsDownloads });
      });

      // Completion → copy path to clipboard.
      const onChanged = (delta) => {
        if (delta.id !== downloadId || !delta.state) return;
        if (delta.state.current === 'complete') {
          chrome.downloads.onChanged.removeListener(onChanged);
          URL.revokeObjectURL(blobUrl);
          chrome.downloads.search({ id: downloadId }, (results) => {
            const path = results && results[0] && results[0].filename;
            if (!path) { showStatus('Downloaded', 'success'); return; }
            log('File: ' + path);
            navigator.clipboard.writeText(path)
              .then(() => {
                showStatus('Path copied', 'success');
                log('Clipboard OK');
              })
              .catch(() => {
                showStatus('Downloaded: ' + path, 'success');
              });
          });
        } else if (delta.state.current === 'interrupted') {
          chrome.downloads.onChanged.removeListener(onChanged);
          URL.revokeObjectURL(blobUrl);
          showStatus('Download failed', 'error');
        }
      };
      chrome.downloads.onChanged.addListener(onChanged);
    });

    resetBtn();

  } catch (err) {
    log('ERROR: ' + err.message);
    showStatus(err.message, 'error');
    resetBtn();
  }
});

function resetBtn() {
  downloadBtn.textContent = 'Download';
  downloadBtn.disabled = false;
}

// ============================================================
// Video download (yt-dlp via native host)
// ============================================================
const qualitySelect = document.getElementById('qualitySelect');
const downloadVideoBtn = document.getElementById('downloadVideoBtn');
const subsPackBtn = document.getElementById('subsPackBtn');
const commentCap = document.getElementById('commentCap');
const commentsBtn = document.getElementById('commentsBtn');
const chanLimit = document.getElementById('chanLimit');
const chanQuality = document.getElementById('chanQuality');
const chanSort = document.getElementById('chanSort');
const chanBundle = document.getElementById('chanBundle');
const chanDownloadBtn = document.getElementById('chanDownloadBtn');
const chanHint = document.getElementById('chanHint');
const chanCsvLimit = document.getElementById('chanCsvLimit');
const chanCsvComments = document.getElementById('chanCsvComments');
const chanCsvSort = document.getElementById('chanCsvSort');
const chanCsvBtn = document.getElementById('chanCsvBtn');
const chanCsvHint = document.getElementById('chanCsvHint');
const videoProgress = document.getElementById('videoProgress');
const barFill = document.getElementById('barFill');
const barStage = document.getElementById('barStage');
const barInfo = document.getElementById('barInfo');
const cancelBtn = document.getElementById('cancelBtn');
const videoStatus = document.getElementById('videoStatus');
const hostHint = document.getElementById('hostHint');
const optBundle = document.getElementById('optBundle');
const optComments = document.getElementById('optComments');
const pkgHint = document.getElementById('pkgHint');

let hostChecked = false;
let jobRunning = false;
let jobDone = false;  // ignore stray events arriving after a finished job
let queueBar = 0;     // monotonic queue progress for multi-video jobs

// Every button that starts a host job. While one runs they all go dead and the
// single Cancel under the progress bar is the only live control — a second job
// would be refused by the background's single-slot guard anyway.
const JOB_BUTTONS = [downloadVideoBtn, subsPackBtn, commentsBtn,
                     chanDownloadBtn, chanCsvBtn];

// --- Package options (remembered between popups) ---
const PKG_DEFAULTS = { bundle: true, comments: false };

function paintPkgHint() {
  pkgHint.textContent = optBundle.checked
    ? 'Folder per video: media + cover (JPG/WebP) + description + subtitles (SRT) '
      + '+ info.json + transcript.json + a readable .md card'
      + (optComments.checked ? ' + comments' : '')
    : 'Single file straight into Downloads — no cover, description or subtitles.';
  optComments.parentElement.classList.toggle('hidden', !optBundle.checked);
}

chrome.storage.local.get(PKG_DEFAULTS).then(o => {
  optBundle.checked = o.bundle !== false;
  optComments.checked = !!o.comments;
  paintPkgHint();
}).catch(() => paintPkgHint());

[optBundle, optComments].forEach(el => el.addEventListener('change', () => {
  paintPkgHint();
  chrome.storage.local.set({ bundle: optBundle.checked, comments: optComments.checked })
    .catch(() => { /* noop */ });
}));

// Finder-style decimal sizes: 1.4 GB means 1.4·10^9 bytes (memory: sizes-gb).
function fmtSize(bytes) {
  if (!bytes) return '';
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return Math.round(bytes / 1e6) + ' MB';
  return Math.round(bytes / 1e3) + ' KB';
}

function fmtCount(n) {
  if (!n) return '0';
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'K';
  return String(n);
}

function fmtHours(seconds) {
  if (!seconds) return '';
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}

// ============================================================
// Page mode — one video vs a whole channel
// ============================================================

// Show only the tabs belonging to this mode and activate the first of them.
function setMode(mode) {
  pageMode = mode;
  let first = null;
  document.querySelectorAll('.tab').forEach(t => {
    const mine = t.dataset.mode === mode;
    t.classList.toggle('hidden', !mine);
    t.classList.remove('active');
    if (mine && !first) first = t;
  });
  document.querySelectorAll('.panel').forEach(p => p.classList.add('hidden'));
  if (first) activateTab(first);
}

function activateTab(tab) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  tab.classList.add('active');
  const which = tab.dataset.tab;
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('hidden', p.id !== 'panel-' + which);
  });
  if (!hostChecked && which !== 'subs') checkHost();
}

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => activateTab(tab));
});

// Reveal a specific tab (used when restoring a running job, or when subtitles
// turn out to be unavailable and the Subtitles tab is pointless).
function showTab(which, runHostCheck) {
  const tab = document.querySelector(`.tab[data-tab="${which}"]`);
  if (!tab || tab.classList.contains('hidden')) return;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  tab.classList.add('active');
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.toggle('hidden', p.id !== 'panel-' + which);
  });
  if (runHostCheck && !hostChecked) checkHost();
}

// ============================================================
// Channel mode
// ============================================================

// The count dropdowns say what the current sort actually selects: "Top 25 by
// views" is a different promise from "Latest 25", and a playlist has no
// "latest" at all — it is in whatever order its author put it.
function relabelLimits() {
  const label = (n, sort) => !n ? 'All videos'
    : sort === 'popular' ? `Top ${n} by views`
    : collection && collection.kind === 'playlist' ? `First ${n}` : `Latest ${n}`;
  [[chanLimit, chanSort], [chanCsvLimit, chanCsvSort]].forEach(([sel, sortSel]) => {
    Array.from(sel.options).forEach(o => {
      o.textContent = label(parseInt(o.value, 10) || 0, sortSel.value);
    });
  });
}

function paintChannelHints() {
  relabelLimits();
  const n = channelInfo && channelInfo.count;
  const pick = parseInt(chanLimit.value, 10);
  const planned = !pick ? (n || 0) : Math.min(pick, n || pick);
  const ranked = chanSort.value === 'popular' && pick;
  chanHint.textContent = n
    ? `${ranked ? 'The ' + planned + ' most viewed' : planned} of ${n} videos`
      + `${chanBundle.checked
        ? ' — each into its own folder with cover, description, subtitles and metadata'
        : ' — media files only'}.`
      + ' Re-running tops the folder up: what is already there is skipped.'
    : 'Reading the channel…';

  const csvPick = parseInt(chanCsvLimit.value, 10);
  const csvPlanned = !csvPick ? (n || 0) : Math.min(csvPick, n || csvPick);
  const csvRanked = chanCsvSort.value === 'popular' && csvPick;
  const withComments = chanCsvComments.value !== 'none';
  // ~1.5 s per video for stats alone, ~4-6 s once comments are pulled.
  const secs = csvPlanned * (withComments ? 5 : 1.5);
  chanCsvHint.textContent = n
    ? `${csvRanked ? 'The ' + csvPlanned + ' most viewed' : csvPlanned} videos → `
      + 'views, likes, comment counts, engagement per 1K views'
      + (withComments ? ', plus every comment with its likes' : '')
      + `. Roughly ${secs < 90 ? Math.round(secs) + ' s' : Math.round(secs / 60) + ' min'}.`
    : 'Reading the channel…';
}

[chanLimit, chanSort, chanBundle, chanCsvLimit, chanCsvSort, chanCsvComments].forEach(
  el => el.addEventListener('change', paintChannelHints));

function loadChannelInfo() {
  paintChannelHints();
  chrome.runtime.sendMessage({ action: 'getChannelInfo', url: collection.url }, resp => {
    if (chrome.runtime.lastError || !resp || !resp.ok || resp.error) {
      const err = resp?.error || chrome.runtime.lastError?.message || 'unknown error';
      log('Channel probe failed: ' + err);
      pageMetaEl.textContent = 'Could not read this channel — ' + err;
      pageMetaEl.classList.remove('hidden');
      return;
    }
    channelInfo = resp;
    log(`Channel: ${resp.channel} — ${resp.count} videos, ${resp.totalViews} views`);
    if (resp.channel) titleEl.textContent = resp.channel;
    pageMetaEl.textContent = [
      `${resp.count} video${resp.count === 1 ? '' : 's'}`,
      resp.totalViews ? fmtCount(resp.totalViews) + ' views' : '',
      fmtHours(resp.totalDuration),
      collection.tab && collection.tab !== 'videos' ? collection.tab : ''
    ].filter(Boolean).join(' · ');
    pageMetaEl.classList.remove('hidden');
    paintChannelHints();
  });
}

// ============================================================
// Quality dropdown (single video) — built from the real format ladder
// ============================================================

// Resolution rungs worth offering explicitly (below the max, which is its own
// "Max" entry). Anything smaller is noise for an editing workflow.
const QUALITY_LADDER = [4320, 2160, 1440, 1080, 720, 480];

// Build the quality dropdown from what the site ACTUALLY serves, so every entry
// promises the resolution, codec, container and size it will really produce.
// Called with null before/without a probe → generic entries that still work.
function setQualityLabels(info) {
  const want = qualitySelect.value || 'max';
  const rungs = (info && info.heights) || [];
  const opts = [];

  if (rungs.length) {
    const top = rungs[0];
    const spec = r => [
      `${r.height}p${r.fps >= 50 ? r.fps : ''}`,
      r.codec,
      (r.ext || 'mp4').toUpperCase(),
      r.size ? '≈' + fmtSize(r.size) : ''
    ].filter(Boolean).join(' · ');
    opts.push({ value: 'max', label: 'Max · ' + spec(top) });
    rungs.filter(r => r.height !== top.height && QUALITY_LADDER.includes(r.height))
      .forEach(r => opts.push({ value: String(r.height), label: spec(r) }));
    // Only worth offering when "Max" would land in MKV (VP9-only top rung):
    // this preset drops VP9 to keep the file an MP4 Premiere can import.
    if (top.ext !== 'mp4' && info.mp4Height) {
      opts.push({
        value: 'mp4',
        label: `MP4 only · ${info.mp4Height}p${info.mp4Codec ? ' · ' + info.mp4Codec : ''}`
      });
    }
  } else {
    opts.push({ value: 'max', label: 'Max quality (4K if available)' });
    opts.push({ value: '1080', label: '1080p' });
    opts.push({ value: '720', label: '720p' });
  }
  opts.push({ value: 'audio', label: 'Audio only · M4A' });

  qualitySelect.innerHTML = '';
  opts.forEach(o => {
    const el = document.createElement('option');
    el.value = o.value;
    el.textContent = o.label;
    qualitySelect.appendChild(el);
  });
  // Keep the user's pick across a re-probe; fall back to Max.
  qualitySelect.value = opts.some(o => o.value === want) ? want : 'max';
}

function scanFormats() {
  // Show a scanning hint on the dropdown without blocking download.
  setQualityLabels(null);
  qualitySelect.options[0].textContent = 'Detecting quality…';
  chrome.runtime.sendMessage({ action: 'getFormats', url: videoUrl, videoId }, resp => {
    if (chrome.runtime.lastError || !resp || !resp.ok || resp.error) {
      log('Format scan failed: ' + (resp?.error || chrome.runtime.lastError?.message || '?'));
      setQualityLabels(null); // fall back to generic labels
      return;
    }
    log(`Formats: max ${resp.maxHeight}p, ${(resp.heights || []).length} rungs, `
      + `${resp.subCount || 0} subtitle tracks, ${resp.chapterCount || 0} chapters`);
    setQualityLabels(resp);
    // yt-dlp's title beats the tab-title guess (exact filename source).
    if (resp.title) {
      videoTitle = resp.title;
      titleEl.textContent = videoTitle;
    }
    const bits = [];
    if (resp.duration) bits.push(formatDuration(resp.duration));
    if (resp.subCount) bits.push(`${resp.subCount} subtitle track${resp.subCount === 1 ? '' : 's'}`);
    if (resp.chapterCount) bits.push(`${resp.chapterCount} chapters`);
    if (bits.length) {
      pageMetaEl.textContent = bits.join(' · ');
      pageMetaEl.classList.remove('hidden');
    }
  });
}

function checkHost() {
  hostChecked = true;
  log('Pinging native host...');
  chrome.runtime.sendMessage({ action: 'pingHost' }, resp => {
    if (chrome.runtime.lastError) return showHostHint(chrome.runtime.lastError.message);
    if (!resp || !resp.ok) return showHostHint(resp?.error || 'unknown error');
    if (!resp.ytdlp) return showHostHint('yt-dlp not found — run: brew install yt-dlp');
    hostHint.classList.add('hidden');
    log(`Host ready — yt-dlp ${resp.ytdlp}, ffmpeg ${resp.ffmpeg ? 'yes' : 'no'} → ${resp.outdir}`);
    if (pageMode === 'video') scanFormats();
    else if (pageMode === 'channel' && !channelInfo) loadChannelInfo();
  });
}

function showHostHint(err) {
  log('Host unavailable: ' + err);
  hostHint.innerHTML =
    'Native helper not connected.<br>Run once in Terminal:<br>' +
    '<code>bash ~/YTAI/utils/video_downloader/native-host/install.sh</code>' +
    '<br>then reopen this popup.';
  hostHint.classList.remove('hidden');
  JOB_BUTTONS.forEach(b => { b.disabled = true; });
}

// ============================================================
// Jobs — one entry point for every host operation
// ============================================================

function startJob(job, params, label) {
  if (jobRunning) return;
  jobRunning = true;
  jobDone = false;
  queueBar = 0;
  videoStatus.className = 'hidden';
  videoStatus.classList.add('hidden');
  videoProgress.classList.remove('hidden');
  barFill.style.width = '0%';
  barStage.textContent = label || 'Starting…';
  barInfo.textContent = '';
  cancelBtn.disabled = false;
  cancelBtn.textContent = 'Cancel';
  setControlsEnabled(false);
  log(`Job ${job}: ${JSON.stringify(params)}`);
  chrome.runtime.sendMessage({ action: 'runJob', job, ...params });
}

function setControlsEnabled(on) {
  const noTarget = pageMode === 'none';
  JOB_BUTTONS.forEach(b => { b.disabled = !on || noTarget; });
  [qualitySelect, optBundle, optComments, commentCap, chanLimit, chanQuality,
   chanSort, chanBundle, chanCsvLimit, chanCsvSort, chanCsvComments].forEach(el => {
    el.disabled = !on || noTarget;
  });
  // The Subtitles tab's own JSON button has its own enable rule (tracks loaded).
  if (on && pageMode === 'video' && !captionTracks.length) downloadBtn.disabled = true;
}

function endJob() {
  jobRunning = false;
  setControlsEnabled(true);
}

cancelBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ action: 'cancelVideo' });
  barStage.textContent = 'Cancelling…';
  cancelBtn.disabled = true;
});

downloadVideoBtn.addEventListener('click', () => {
  const bundle = optBundle.checked;
  startJob('download', {
    url: videoUrl, videoId, site, title: videoTitle,
    format: qualitySelect.value, bundle,
    comments: bundle && optComments.checked
  }, 'Starting…');
});

subsPackBtn.addEventListener('click', () => {
  startJob('video_subs', { url: videoUrl, videoId, site, title: videoTitle },
    'Reading the video…');
});

commentsBtn.addEventListener('click', () => {
  startJob('video_comments', {
    url: videoUrl, videoId, site, title: videoTitle,
    commentCap: commentCap.value
  }, 'Fetching comments…');
});

chanDownloadBtn.addEventListener('click', () => {
  startJob('channel_download', {
    url: collection.url, title: (channelInfo && channelInfo.channel) || '',
    limit: parseInt(chanLimit.value, 10) || 0,
    sort: chanSort.value,
    format: chanQuality.value, bundle: chanBundle.checked
  }, 'Listing the channel…');
});

chanCsvBtn.addEventListener('click', () => {
  startJob('channel_csv', {
    url: collection.url, title: (channelInfo && channelInfo.channel) || '',
    limit: parseInt(chanCsvLimit.value, 10) || 0,
    sort: chanCsvSort.value,
    commentCap: chanCsvComments.value
  }, 'Listing the channel…');
});

// ============================================================
// Job state: live events + restoring after the popup was closed
// ============================================================

// On popup (re)open, ask the background for the job state and restore it — a
// running job shows live progress; one that finished or failed while the popup
// was closed still reports its outcome instead of silently vanishing.
function restoreActiveDownload() {
  chrome.runtime.sendMessage({ action: 'getDownloadState' }, st => {
    if (chrome.runtime.lastError || !st) return;
    if (st.status === 'downloading') {
      log(`Restoring active job: ${st.job || 'download'} ${Math.round(st.percent || 0)}%`);
      applyRestoredState(st);
    } else {
      log(`Restoring finished job: ${st.status}`);
      paintTerminalState(st);
    }
  });
}

// Tell the background the outcome was displayed — it clears the terminal
// snapshot so a cancelled/failed job doesn't hijack every popup open for the
// whole 10-min TTL.
function ackDownloadState() {
  chrome.runtime.sendMessage({ action: 'ackDownloadState' }, () => {
    void chrome.runtime.lastError; // worker may be mid-restart — fine
  });
}

// Paint the outcome of a job that ended while the popup was closed.
function paintTerminalState(st) {
  videoProgress.classList.add('hidden');
  if (st.status === 'done') {
    const desc = describeFile(st);
    const where = st.folder ? String(st.folder).split('/').pop()
      : (st.path ? String(st.path).split('/').pop() : '');
    showVideoStatus(
      `Saved${desc ? ' · ' + desc : ''}${where ? ' · ' + where : ''}`, 'success');
  } else if (st.status === 'error') {
    showVideoStatus(st.message || 'Job failed', 'error');
  } else if (st.status === 'detached') {
    showVideoStatus(
      'A job kept running after the extension reloaded — check Downloads'
      + (st.title ? ': ' + st.title : ''), 'note');
  }
  ackDownloadState(); // outcome shown once — don't re-restore it
}

// Paint the progress UI from a background job snapshot.
function applyRestoredState(st) {
  jobRunning = true;
  jobDone = false;
  setControlsEnabled(false);
  cancelBtn.disabled = false;
  videoStatus.classList.add('hidden');
  videoProgress.classList.remove('hidden');

  const pct = Math.min(100, Math.round(st.percent || 0));
  barFill.style.width = pct + '%';
  barStage.textContent = stageLabel(st.stage, pct, st);

  const otherTarget = st.key && st.key !== (videoUrl || collection?.url || videoId);
  barInfo.textContent = [
    st.speed || '',
    st.eta ? 'ETA ' + st.eta : '',
    otherTarget && st.title ? '· ' + st.title : ''
  ].filter(Boolean).join('  ');

  // On a page with no title of its own, show the job's own title so the popup
  // isn't blank.
  if (st.title && titleEl && !titleEl.textContent) titleEl.textContent = st.title;
}

function showVideoStatus(msg, type) {
  videoStatus.textContent = msg;
  videoStatus.className = type;
}

// One place that turns a host stage into words — shared by the live event
// stream and the restore-from-snapshot path so they can't drift apart.
function stageLabel(stage, pct, ev) {
  const pos = ev && ev.total > 1 ? `Video ${ev.item}/${ev.total} · ` : '';
  switch (stage) {
    case 'listing': return 'Listing the channel…';
    case 'metadata': return pos + 'Reading metadata…';
    case 'comments': return 'Fetching comments…';
    case 'csv': return 'Building the CSV…';
    case 'merging': return pos + 'Merging video+audio (ffmpeg)…';
    case 'processing': return 'Processing…';
    case 'cookies': return 'Retrying with Chrome cookies…';
    case 'proxy': return 'Geo bypass via RU proxy (1–3 min)…';
    case 'subtitles': return pos + 'Fetching subtitles…';
    case 'extras': return 'Building the package…';
    case 'exists': return 'Already downloaded';
    case 'connecting':
    case 'starting': return 'Connecting…';
    default: return pos + (pct ? `Downloading ${pct}%` : 'Downloading…');
  }
}

// Build "2160p · AV1 · MP4 · 1.2 GB · 13 files" from the done event details.
function describeFile(ev) {
  const parts = [];
  if (ev.height) parts.push(ev.height + 'p');
  if (ev.codec) parts.push(ev.codec);
  if (ev.ext) parts.push(String(ev.ext).toUpperCase());
  const size = ev.size_bytes || (ev.size_mb ? ev.size_mb * 1e6 : 0);
  if (size) parts.push(fmtSize(size));
  if (ev.note) parts.push(ev.note);
  else if (ev.fileCount > 1) parts.push(ev.fileCount + ' files');
  return parts.join(' · ');
}

// Receive streamed events from background (native host)
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action !== 'videoEvent') return;
  const ev = msg.event;

  // Ignore any stray progress/error/done that arrives after a finished job
  // (e.g. the host's port closing right after 'done').
  if (jobDone && ev.type !== 'started') return;

  if (ev.type === 'started') {
    barStage.textContent = ev.count
      ? `Starting — ${ev.count} video${ev.count === 1 ? '' : 's'}…` : 'Connecting…';
    log(`Started ${ev.job || 'download'}${ev.channel ? ' · ' + ev.channel : ''}`
      + `${ev.count ? ' · ' + ev.count + ' videos' : ''} → ${ev.outdir}`);

  } else if (ev.type === 'progress') {
    const pct = Math.min(100, Math.round(ev.percent || 0));
    if (ev.total > 1) {
      // On a channel job the bar tracks the QUEUE, not the current file — one
      // video's bytes say nothing about how far the whole job is. It is also
      // clamped monotonic: every video downloads two streams (video, then
      // audio), each running 0→100%, so a raw reading would slide backwards
      // twice per video.
      const target = Math.round(
        (((ev.item || 1) - 1) + pct / 100) / ev.total * 100);
      queueBar = Math.max(queueBar, target);
      barFill.style.width = queueBar + '%';
    } else {
      barFill.style.width = pct + '%';
    }
    barStage.textContent = stageLabel(ev.stage, pct, ev);
    barInfo.textContent = (ev.stage && ev.stage !== 'downloading') ? ''
      : [ev.speed, ev.eta ? 'ETA ' + ev.eta : ''].filter(Boolean).join('  ');

  } else if (ev.type === 'done') {
    jobDone = true;
    barFill.style.width = '100%';
    const desc = describeFile(ev);
    barStage.textContent = ev.already ? 'Already downloaded'
      : ev.partial ? 'Stopped — partial result kept' : 'Done ✓';
    barInfo.textContent = desc;
    log((ev.already ? 'Already saved: ' : 'Saved: ') + ev.path);
    if (ev.files && ev.files.length) log('Files: ' + ev.files.join(', '));
    const head = ev.already ? 'Already downloaded' : ev.partial ? 'Partial' : 'Saved';
    const where = ev.folder ? String(ev.folder).split('/').pop() : 'Downloads';
    const note = `${head}${desc ? ' · ' + desc : ''} → ${where} (revealed in Finder)`;
    const target = ev.folder || ev.path;
    if (target) {
      navigator.clipboard.writeText(target)
        .then(() => showVideoStatus(note + ' · path copied', 'success'))
        // Clipboard can reject when the popup isn't focused — still show WHERE
        // it was saved, not just that it was.
        .catch(() => showVideoStatus(note, 'success'));
    } else {
      showVideoStatus(note, 'success');
    }
    endJob();
    ackDownloadState(); // outcome seen live — don't re-restore it later

  } else if (ev.type === 'error') {
    videoProgress.classList.add('hidden');
    showVideoStatus(ev.message || 'Job failed', 'error');
    log('Job error: ' + ev.message);
    endJob();
    ackDownloadState(); // outcome seen live — don't re-restore it later
  }
});

init();
