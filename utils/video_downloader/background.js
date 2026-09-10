// ============================================================
// Video download via native messaging host (yt-dlp + ffmpeg)
// ============================================================
importScripts('common.js'); // detectSite() — shared with the popup

const NATIVE_HOST = 'ae.rya.ytdl';
const EXT_TITLE = 'RYA.AE — Video Downloader';
let videoPort = null; // active download port (for cancel)
let currentDownload = null; // snapshot so a reopened popup can restore status

// --- Toolbar badge: download progress visible without opening the popup ---
// NB: don't reset the background color at worker start — badge text AND color
// persist across worker restarts, and repainting lime here would strip the
// red off a persisted '!' error badge. setBadge() sets the color per call.
const BADGE_BG = '#D4E44B';
chrome.action.setBadgeTextColor?.({ color: '#0D1526' });

function setBadge(text, bg) {
  chrome.action.setBadgeText({ text: text || '' });
  chrome.action.setBadgeBackgroundColor({ color: bg || BADGE_BG });
}

function notify(title, message) {
  try {
    chrome.notifications.create({
      type: 'basic', iconUrl: 'icon128.png',
      title, message: message || ''
    }, () => void chrome.runtime.lastError);
  } catch (e) { /* noop */ }
}

// Keep a finished/detached snapshot visible to the popup for this long, so a
// download that ended while the popup was closed still reports its result.
const TERMINAL_TTL_MS = 10 * 60 * 1000;

// The service worker can be torn down mid-download (extension reload, Chrome
// quit, crash) while the native host deliberately keeps downloading. Mirror
// the snapshot so a restarted worker still knows. storage.local, NOT
// storage.session: session storage is wiped on exactly the events we need to
// survive (extension reload, browser quit) — it only covers a worker crash.
function saveSnapshot() {
  chrome.storage.local.set({ currentDownload }).catch(() => { /* noop */ });
}

// On worker start, rehydrate. A snapshot stuck in 'downloading' means the
// worker died while the host was running — the download continued (or
// finished) unattached; mark it so the popup can say so instead of lying.
chrome.storage.local.get('currentDownload').then((stored) => {
  const saved = stored && stored.currentDownload;
  if (!saved || currentDownload) return;
  if (saved.status === 'downloading') {
    saved.status = 'detached';
    saved.finishedAt = Date.now();
    setBadge(''); // stale % from before the restart would lie
  }
  currentDownload = saved;
  saveSnapshot();
}).catch(() => { /* noop */ });

// What the popup should see: an active download, or a recently finished /
// detached one (results and errors must survive a closed popup).
function presentableSnapshot(snap) {
  if (!snap) return null;
  if (snap.status === 'downloading') return snap;
  if (snap.finishedAt && Date.now() - snap.finishedAt < TERMINAL_TTL_MS) return snap;
  return null;
}

// presentableSnapshot + housekeeping: a terminal snapshot past its TTL was
// never acknowledged (popup stayed closed) — drop it and clear the ✓ / !
// badge, which would otherwise stick for the rest of the browser session.
function presentAndExpire() {
  const snap = presentableSnapshot(currentDownload);
  if (!snap && currentDownload) {
    currentDownload = null;
    saveSnapshot();
    setBadge('');
  }
  return snap;
}

// Relay an event to the popup; ignore if popup is closed.
function toPopup(payload) {
  chrome.runtime.sendMessage(payload).catch(() => { /* popup closed */ });
}

// Generic one-shot request to the native host (ping / formats). Connects,
// sends one message, resolves with the first reply, then disconnects.
function hostOneShot(message, sendResponse) {
  let port;
  try {
    port = chrome.runtime.connectNative(NATIVE_HOST);
  } catch (e) {
    sendResponse({ ok: false, error: e.message });
    return;
  }
  let answered = false;
  port.onMessage.addListener((msg) => {
    answered = true;
    sendResponse({ ok: true, ...msg });
    try { port.disconnect(); } catch (e) { /* noop */ }
  });
  port.onDisconnect.addListener(() => {
    if (!answered) {
      const err = chrome.runtime.lastError?.message || 'Native host not installed';
      sendResponse({ ok: false, error: err });
    }
  });
  port.postMessage(message);
}

// Jobs the native host accepts. The popup can only ask for one of these — an
// unknown value would otherwise be forwarded verbatim to the host.
const HOST_JOBS = ['download', 'video_subs', 'video_comments',
                   'channel_download', 'channel_csv'];

// Start a host job (a video download, a subtitle/comment export, or a whole
// channel). Streams events to the popup via toPopup() AND keeps a background
// snapshot (currentDownload) so a reopened popup can restore the live status —
// the popup window is destroyed every time it closes.
// `url` is the page URL (video) or the normalized channel/playlist URL.
// Returns false (without touching state) when a job is already running — the
// port/snapshot are single-slot, a second start would orphan the first.
function startVideoDownload({ job, url, videoId, site, format, title, bundle,
                              comments, commentCap, limit, sort }) {
  if (currentDownload && currentDownload.status === 'downloading') return false;
  if (!HOST_JOBS.includes(job || 'download')) return false;
  const key = url || videoId;
  currentDownload = {
    key, job: job || 'download', url, videoId, site, format, title: title || '',
    bundle: bundle !== false, comments: !!comments,
    commentCap: commentCap || '', limit: limit || 0, sort: sort || '',
    percent: 0, stage: 'starting', speed: '', eta: '', status: 'downloading'
  };
  saveSnapshot();
  setBadge('0%');

  try {
    videoPort = chrome.runtime.connectNative(NATIVE_HOST);
  } catch (e) {
    currentDownload.status = 'error';
    currentDownload.message = e.message;
    currentDownload.finishedAt = Date.now();
    saveSnapshot();
    setBadge('!', '#FF5252');
    toPopup({ action: 'videoEvent', event: { type: 'error', message: e.message } });
    return true;
  }

  let finished = false;
  const thisPort = videoPort;
  const dlId = key;

  thisPort.onMessage.addListener((msg) => {
    if (msg.type === 'done' || msg.type === 'error') finished = true;

    // Keep the snapshot in sync (only for this download).
    if (currentDownload && currentDownload.key === dlId) {
      if (msg.type === 'started') {
        currentDownload.stage = 'connecting';
      } else if (msg.type === 'progress') {
        if (typeof msg.percent === 'number') currentDownload.percent = msg.percent;
        currentDownload.stage = msg.stage || 'downloading';
        currentDownload.speed = msg.speed || '';
        currentDownload.eta = msg.eta || '';
        currentDownload.item = msg.item || 0;
        currentDownload.total = msg.total || 0;
        // On a channel job the badge tracks the queue (3/25), not one file's
        // bytes — that is the number worth glancing at from another tab.
        setBadge(msg.total > 1
          ? `${msg.item}/${msg.total}`
          : Math.min(100, Math.round(currentDownload.percent || 0)) + '%');
      } else if (msg.type === 'done') {
        currentDownload.status = 'done';
        currentDownload.percent = 100;
        currentDownload.finishedAt = Date.now();
        Object.assign(currentDownload, {
          ext: msg.ext, size_mb: msg.size_mb, size_bytes: msg.size_bytes,
          codec: msg.codec, height: msg.height, already: msg.already,
          path: msg.path, folder: msg.folder, fileCount: msg.fileCount,
          note: msg.note, partial: msg.partial
        });
        setBadge('✓');
        const bytes = msg.size_bytes || (msg.size_mb ? msg.size_mb * 1e6 : 0);
        const desc = [
          msg.height ? msg.height + 'p' : '',
          msg.codec || '',
          msg.ext ? String(msg.ext).toUpperCase() : '',
          // Decimal units, like Finder.
          bytes >= 1e9 ? (bytes / 1e9).toFixed(1) + ' GB'
            : bytes ? Math.round(bytes / 1e6) + ' MB' : '',
          msg.note || (msg.fileCount > 1 ? msg.fileCount + ' files' : '')
        ].filter(Boolean).join(' · ');
        // In package mode the folder is what the user goes looking for.
        const base = String(msg.folder || msg.path || '').split('/').pop();
        notify(msg.already ? 'Already downloaded' : 'Saved' + (desc ? ' · ' + desc : ''),
          base);
      } else if (msg.type === 'error') {
        currentDownload.status = 'error';
        currentDownload.message = msg.message;
        currentDownload.finishedAt = Date.now();
        if (msg.message === 'Cancelled') {
          setBadge(''); // user asked for this — not an alert
        } else {
          setBadge('!', '#FF5252');
          notify('Download failed', String(msg.message || '').slice(0, 140));
        }
      }
      saveSnapshot();
    }

    toPopup({ action: 'videoEvent', event: msg });
  });

  thisPort.onDisconnect.addListener(() => {
    const err = chrome.runtime.lastError?.message;
    // Only surface an error if the host died BEFORE reporting done/error.
    // A normal close right after 'done' is expected and must stay silent.
    if (!finished) {
      if (currentDownload && currentDownload.key === dlId) {
        currentDownload.status = 'error';
        currentDownload.message = 'Downloader disconnected before finishing';
        currentDownload.finishedAt = Date.now();
        saveSnapshot();
        setBadge('!', '#FF5252');
        notify('Download failed', 'Downloader disconnected before finishing');
      }
      toPopup({
        action: 'videoEvent',
        event: {
          type: 'error',
          message: err
            ? `Downloader connection lost: ${err}`
            : 'Downloader disconnected before finishing. If the file is missing, run native-host/install.sh'
        }
      });
    }
    if (videoPort === thisPort) videoPort = null;
  });

  thisPort.postMessage({
    action: currentDownload.job, url, videoId, format,
    bundle: currentDownload.bundle, comments: currentDownload.comments,
    commentCap: currentDownload.commentCap, limit: currentDownload.limit,
    sort: currentDownload.sort
  });
  return true;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // --- Video: check native host availability ---
  if (msg.action === 'pingHost') {
    hostOneShot({ action: 'ping' }, sendResponse);
    return true; // async
  }

  // --- Video: probe available formats/resolutions for the dropdown ---
  if (msg.action === 'getFormats') {
    hostOneShot({ action: 'formats', url: msg.url, videoId: msg.videoId },
      sendResponse);
    return true; // async
  }

  // --- Channel: enumerate it (flat probe) so the popup can size the job ---
  if (msg.action === 'getChannelInfo') {
    hostOneShot({ action: 'channel_info', url: msg.url }, sendResponse);
    return true; // async
  }

  // --- Video: current download status (so a reopened popup can restore it) ---
  if (msg.action === 'getDownloadState') {
    if (currentDownload) {
      sendResponse(presentAndExpire());
    } else {
      // Worker may have just restarted; the rehydrate above races this
      // message, so read storage directly rather than answering null.
      chrome.storage.local.get('currentDownload').then((stored) => {
        const saved = stored && stored.currentDownload;
        if (saved && saved.status === 'downloading') {
          saved.status = 'detached';
          saved.finishedAt = Date.now();
        }
        if (!currentDownload && saved) {
          currentDownload = saved;
          saveSnapshot();
        }
        sendResponse(presentAndExpire());
      }).catch(() => sendResponse(null));
    }
    return true; // async
  }

  // --- Start any host job (download / subs / comments / channel) ---
  if (msg.action === 'runJob' || msg.action === 'downloadVideo') {
    const job = msg.action === 'downloadVideo' ? 'download' : msg.job;
    const started = startVideoDownload({
      job, url: msg.url, videoId: msg.videoId, site: msg.site,
      format: msg.format || 'max', title: msg.title,
      bundle: msg.bundle !== false, comments: !!msg.comments,
      commentCap: msg.commentCap, limit: msg.limit, sort: msg.sort
    });
    sendResponse({ started });
    if (!started) {
      // The popup's own UI guard can't see a job started from another window /
      // the context menu — bounce it back as a normal error event.
      toPopup({
        action: 'videoEvent',
        event: {
          type: 'error',
          message: HOST_JOBS.includes(job || 'download')
            ? 'Another job is already running'
            : `Unknown job: ${job}`
        }
      });
    }
    return true;
  }

  // --- Video: popup displayed the terminal outcome — show it only once.
  // Without this ack a cancelled/failed download would hijack the popup with
  // a stale red status on every open until the 10-min TTL expires. ---
  if (msg.action === 'ackDownloadState') {
    if (currentDownload && currentDownload.status !== 'downloading') {
      currentDownload = null;
      saveSnapshot();
      setBadge(''); // outcome acknowledged — clear ✓ / !
    }
    sendResponse({ ok: true });
    return true;
  }

  // --- Video: cancel running download ---
  if (msg.action === 'cancelVideo') {
    if (videoPort) {
      try { videoPort.postMessage({ action: 'cancel' }); } catch (e) { /* noop */ }
    }
    sendResponse({ cancelled: true });
    return true;
  }

  // Cleanup subtitle JSONs (>7 days). ONLY download ids the popup recorded in
  // storage.local are ever touched — never pattern-matched filenames: a
  // substring match here used to delete unrelated user files from Downloads.
  if (msg.action === 'cleanup') {
    chrome.storage.local.get({ subsDownloads: [] }).then(async (stored) => {
      const list = stored.subsDownloads || [];
      const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
      const keep = [];
      let removed = 0, expired = 0;
      for (const rec of list) {
        if (!rec || typeof rec.id !== 'number') continue;
        if (!rec.t || rec.t > weekAgo) { keep.push(rec); continue; }
        expired++;
        const item = await new Promise(res =>
          chrome.downloads.search({ id: rec.id }, r => res(r && r[0])));
        if (item && item.exists && item.state === 'complete') {
          const ok = await new Promise(res =>
            chrome.downloads.removeFile(rec.id, () =>
              res(!chrome.runtime.lastError)));
          if (ok) removed++;
        }
        chrome.downloads.erase({ id: rec.id });
      }
      await chrome.storage.local.set({ subsDownloads: keep });
      sendResponse({ removed, total: expired });
    }).catch(e => sendResponse({ removed: 0, total: 0, error: e.message }));
    return true;
  }
});

// ============================================================
// Context menu: right-click a video link → download at max quality without
// opening the page. Match patterns are host-wide (they can't express
// "has a concrete video id"), so the click handler re-validates with
// detectSite() and declines politely on list/channel links.
// ============================================================
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: 'rya-download-link',
      title: 'Download video — RYA.AE',
      contexts: ['link'],
      targetUrlPatterns: [
        '*://*.youtube.com/*', '*://youtu.be/*',
        '*://vk.com/*', '*://*.vk.com/*', '*://vk.ru/*', '*://*.vk.ru/*',
        '*://vkvideo.ru/*', '*://*.vkvideo.ru/*',
        '*://ok.ru/*', '*://*.ok.ru/*',
        '*://odnoklassniki.ru/*', '*://*.odnoklassniki.ru/*',
        '*://rutube.ru/*', '*://*.rutube.ru/*'
      ]
    });
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== 'rya-download-link') return;
  const det = detectSite(info.linkUrl || '');
  if (!det) {
    notify(EXT_TITLE, 'Not a single-video link (list/channel pages are ignored)');
    return;
  }
  // Honour the popup's package switches — the context menu has no UI of its
  // own, and silently downloading a bare file when the popup is set to
  // "full package" would be a surprise.
  chrome.storage.local.get({ bundle: true, comments: false }).then((o) => {
    const started = startVideoDownload({
      job: 'download', url: det.url, videoId: det.videoId || '', site: det.site,
      format: 'max', title: '', bundle: o.bundle !== false,
      comments: o.bundle !== false && !!o.comments
    });
    if (!started) notify(EXT_TITLE, 'Another job is already running');
  });
});
