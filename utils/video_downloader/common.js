// Shared between popup.js (via <script>) and background.js (via importScripts).
// ============================================================
// Collection detection — is this URL a YouTube channel or playlist, i.e. a
// LIST of videos rather than one video?
//
// Returns { kind, url, tab, handle } where `url` is normalized to a tab yt-dlp
// can enumerate. A bare /@handle is deliberately rewritten to /@handle/videos:
// handed the bare URL, yt-dlp expands the channel into every tab at once
// (Videos + Shorts + Live + Playlists) and the job stops being predictable.
// ============================================================
function detectYouTubeCollection(rawUrl) {
  let u;
  try { u = new URL(rawUrl); } catch (e) { return null; }
  const h = u.hostname.replace(/^(www|m)\./, '');
  if (h !== 'youtube.com' && !h.endsWith('.youtube.com')) return null;
  const path = u.pathname.replace(/\/+$/, '') || '/';

  // A watch/shorts/embed page is a single video even when it carries &list=.
  if (path === '/watch' || /^\/(shorts|live|embed)\//.test(path)) return null;

  if (path === '/playlist') {
    const list = u.searchParams.get('list');
    if (!list) return null;
    return {
      kind: 'playlist', tab: '',
      url: `https://www.youtube.com/playlist?list=${encodeURIComponent(list)}`,
      handle: list
    };
  }

  const m = path.match(
    /^\/(?:(@[^/]+)|channel\/([^/]+)|c\/([^/]+)|user\/([^/]+))(?:\/([^/]+))?$/);
  if (!m) return null;
  const base = m[1] || (m[2] ? `channel/${m[2]}` : m[3] ? `c/${m[3]}` : `user/${m[4]}`);
  // Tabs yt-dlp can enumerate as a video list. Everything else on a channel
  // (featured/community/playlists/about/search…) means "the channel" → Videos.
  const LISTABLE = ['videos', 'shorts', 'streams'];
  const KNOWN = LISTABLE.concat(
    ['featured', 'community', 'playlists', 'about', 'search', 'podcasts',
     'releases', 'store', 'channels']);
  const raw = (m[5] || '').toLowerCase();
  if (raw && !KNOWN.includes(raw)) return null;
  const tab = LISTABLE.includes(raw) ? raw : 'videos';
  return {
    kind: 'channel', tab,
    url: `https://www.youtube.com/${base}/${tab}`,
    handle: m[1] || base
  };
}

// ============================================================
// Site detection — is this URL a concrete downloadable video?
// ============================================================
function detectSite(rawUrl) {
  let u;
  try { u = new URL(rawUrl); } catch (e) { return null; }
  const h = u.hostname.replace(/^(www|m)\./, '');

  if (h === 'youtube.com' || h.endsWith('.youtube.com')) {
    if (u.pathname === '/watch' && u.searchParams.get('v')) {
      return { site: 'youtube', videoId: u.searchParams.get('v'), url: rawUrl };
    }
    // Shorts / live / embed carry the id in the path.
    const m = u.pathname.match(/^\/(?:shorts|live|embed)\/([\w-]{6,20})/);
    if (m) return { site: 'youtube', videoId: m[1], url: rawUrl };
    return null;
  }
  if (h === 'youtu.be' && u.pathname.length > 1) {
    return { site: 'youtube', videoId: u.pathname.slice(1).split('/')[0], url: rawUrl };
  }
  if (h === 'vk.com' || h === 'vk.ru' || h === 'vkvideo.ru') {
    // Require a concrete video/clip id (owner_video). Canonicalize to
    // vk.com/video-123_456 — works for feed/modal (?z=video…) and vkvideo.ru
    // player URLs alike. A bare /video or /clips LIST page must NOT match:
    // yt-dlp treats it as a playlist and --no-playlist can't stop a pure
    // playlist, so one click would bulk-download the whole list.
    const m = rawUrl.match(/(video|clip)(-?\d+_\d+)/);
    if (m) return { site: 'vk', url: `https://vk.com/${m[1]}${m[2]}` };
    return null;
  }
  if (h === 'ok.ru' || h === 'odnoklassniki.ru') {
    // Require a numeric id — reject album/channel pages (e.g. /video/c123…).
    if (/\/(?:video|live)\/\d+/.test(u.pathname)) return { site: 'ok', url: rawUrl };
    return null;
  }
  if (h === 'rutube.ru') {
    // Require an id segment after the section — reject channel/category pages.
    if (/^\/(?:video|shorts|play|embed)\/[0-9a-zA-Z]+/.test(u.pathname)) {
      return { site: 'rutube', url: rawUrl };
    }
    return null;
  }
  return null;
}
