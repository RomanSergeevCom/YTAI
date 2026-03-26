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

let captionTracks = [];
let videoId = '';
let videoTitle = '';
let videoMeta = {};
let tabId = null;

// --- Debug ---
function log(msg) {
  const ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
  debugLogEl.textContent += `[${ts}] ${msg}\n`;
  debugLogEl.scrollTop = debugLogEl.scrollHeight;
  console.log('[YT Subs]', msg);
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
  log('Init');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    tabId = tab.id;

    if (!tab.url || !tab.url.includes('youtube.com/watch')) {
      showError('Open a YouTube video first');
      return;
    }

    videoId = new URL(tab.url).searchParams.get('v');
    if (!videoId) {
      showError('No video ID in URL');
      return;
    }
    log(`Video: ${videoId}`);

    log('Innertube POST (ANDROID)...');
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: getVideoData,
      args: [videoId]
    });

    const vd = results?.[0]?.result;
    if (!vd) {
      showError('Content script returned null. Refresh page.');
      return;
    }

    log(`API key: ${vd.apiKey}, tracks: ${vd.trackCount}, error: ${vd.error || 'none'}`);

    if (vd.error) {
      showError(vd.error);
      return;
    }

    if (!vd.tracks || vd.tracks.length === 0) {
      showError('No subtitles available');
      return;
    }

    videoTitle = vd.title || 'Unknown';
    captionTracks = vd.tracks;
    // Store metadata for JSON output
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
    log(`Title: ${videoTitle}`);
    log(`Channel: ${vd.channel} | Views: ${vd.views} | Likes: ${vd.likes} | Duration: ${formatDuration(vd.duration)}`);

    // Sort: manual first
    captionTracks.sort((a, b) => {
      if ((a.kind === 'asr') !== (b.kind === 'asr')) return a.kind === 'asr' ? 1 : -1;
      return 0;
    });

    captionTracks.forEach((track, i) => {
      const opt = document.createElement('option');
      opt.value = i;
      const suffix = track.kind === 'asr' ? ' (auto)' : '';
      opt.textContent = `${track.name}${suffix}`;
      langSelect.appendChild(opt);
      log(`  [${i}] ${track.name}${suffix} — ${track.languageCode}`);
    });

    langSelect.value = 0;
    titleEl.textContent = videoTitle;
    loadingEl.classList.add('hidden');
    contentEl.classList.remove('hidden');
    log('Ready');

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
  return str
    .replace(/[<>:"/\\|?*]/g, '')
    .replace(/\s+/g, '_')
    .substring(0, 80);
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
      title: videoTitle,
      channel: videoMeta.channel,
      channel_id: videoMeta.channel_id,
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

    // Create Blob in popup (has Blob API), convert to data URI, send to background for download + path
    const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8' });
    const reader = new FileReader();
    reader.onload = () => {
      const dataUri = reader.result; // data:application/json;charset=utf-8;base64,...

      chrome.runtime.sendMessage(
        { action: 'download', url: dataUri, filename },
        resp => {
          if (resp?.error) {
            log('Download error: ' + resp.error);
            showStatus('Download failed: ' + resp.error, 'error');
          } else {
            log('Download started, id: ' + resp?.downloadId);
          }
        }
      );
    };
    reader.readAsDataURL(blob);

    // Listen for completion → copy path to clipboard
    const onMsg = msg => {
      if (msg.action === 'downloadComplete') {
        chrome.runtime.onMessage.removeListener(onMsg);
        log('File: ' + msg.path);
        navigator.clipboard.writeText(msg.path)
          .then(() => {
            showStatus('Path copied', 'success');
            log('Clipboard OK');
          })
          .catch(() => {
            showStatus('Downloaded: ' + msg.path, 'success');
          });
      } else if (msg.action === 'downloadFailed') {
        chrome.runtime.onMessage.removeListener(onMsg);
        showStatus('Download failed', 'error');
      }
    };
    chrome.runtime.onMessage.addListener(onMsg);

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

init();
