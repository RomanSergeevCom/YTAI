# RYA.AE Video Downloader — native messaging host

Bridges the **RYA.AE — Video Downloader** Chrome extension (v2.0+) to local
**yt-dlp + ffmpeg**, so the popup's **Video** tab can download a video at true
source quality (up to 4K/8K) — separate video/audio streams muxed automatically
by ffmpeg.

**Supported sites: YouTube · VK / VK Video · Rutube · OK (Odnoklassniki).**
The popup detects the site from the active tab's URL and passes the page URL to
the host; the host validates it (https + domain whitelist) and hands it to yt-dlp.

A browser extension alone cannot reliably do this: YouTube serves combined
audio+video only up to 720p; everything above is split streams behind
`n`-throttling / `signatureCipher`, and VK/Rutube/OK top qualities live in
HLS/DASH manifests. yt-dlp solves all of that and stays updated, so we delegate
the actual download to it.

## v2.6 — the popup follows the page: one video, or a whole channel

The popup now reads what kind of YouTube page you are on and shows a different
set of tabs.

**On a video** — `Video` · `Subtitles` · `Comments`

| Tab | Does |
|-----|------|
| Video | the v2.5 download: max quality + the full package (unchanged) |
| Subtitles | the fast innertube JSON of one track, **plus** "All tracks → SRT + transcript.json" through yt-dlp |
| Comments | Top 100 / Top 500 / all comments → `<video>.comments.csv`, ranked by likes |

**On a channel or playlist** — `All videos` · `Stats · CSV`

| Tab | Does |
|-----|------|
| All videos | downloads N videos into `<Channel>_<id>/`, each its own package folder |
| Stats · CSV | `<Channel>_videos.csv` + optionally `<Channel>_comments.csv` and `<Channel>_top_comments.csv` |

**Which N** — both tabs have a sort next to the count: **Most viewed** (default)
or **Newest first**, so "Top 25 by views" pulls a channel's actual hits of all
time rather than whatever it published last month. Ranking is done locally from
the flat probe (which already carries every entry's view count) and mapped back
to playlist positions (`-I 14,26`), so the run stays a single playlist job —
that is what keeps the download archive and the `item N of M` progress working,
and it works on playlists too, without depending on YouTube honouring `?sort=p`.
A "top by views" CSV is written in rank order: row `n=1` is the most-viewed video.

⚠️ **`--print` implies `--quiet` as well as `--simulate`.** Quiet silences
`[download] Downloading item N of M` — the only between-videos progress a channel
job has — plus `[Merger] Merging formats into…` and `has already been
downloaded`. Every command here that uses `--print` therefore passes
`--no-simulate --no-quiet`.

Channel URLs are normalized before anything runs: `/@handle`, `/featured`,
`/community`, `/playlists` all mean "this channel" → `/@handle/videos`, while
`/@handle/shorts` and `/streams` are kept as-is. A **bare** `/@handle` is refused
by the host on purpose — handed that, yt-dlp expands the channel into every tab
at once (Videos + Shorts + Live + Playlists) and the job stops being predictable.

**Channel downloads are resumable.** Each channel folder carries a
`_archive.txt` (`--download-archive`), so re-running "All videos" costs only what
is new — this is how you top a channel up. `--ignore-errors` keeps one private or
deleted video from ending the run, and (usefully) also demotes subtitle errors to
warnings, which is why subtitle flags can live inline here instead of needing the
separate pass a single-video download uses. Subtitle languages are taken from the
channel's first video, never from an `en.*`-style pattern: against the live
extractor those patterns match YouTube's machine-translated `en-de-DE` keys and
explode into dozens of requests per video.

**CSV columns.** `*_videos.csv`: views, likes, comment count, likes/comments/
engagement **per 1K views** (the comparable numbers), duration, published date,
resolution, language, tags, categories, full description.
`*_comments.csv`: likes, author, root-vs-reply, pinned, hearted-by-owner, date,
text, and a direct `&lc=` link to the comment.
`*_top_comments.csv`: the channel's most-liked comments, ranked, with the video
each came from. Files are UTF-8 **with BOM** (Excel renders Cyrillic correctly)
and cells starting with `=`/`+`/`-word` get a leading apostrophe so Sheets does
not eat them as formulas — `@handles` are deliberately left alone.

⚠️ **yt-dlp overwrites `comment_count` with the number of comments it actually
extracted**, so a capped run would report "100 comments" for a video with 4000.
The host mines the true figure out of yt-dlp's own log line (`Downloading ~4103
comments`) and exports both: `comments` (real) and `comments_exported`.

Rough cost: ~1.5 s per video for stats alone, ~5 s per video once comments are
pulled. The popup states the estimate before you start, the progress bar tracks
the queue (`Video 7/79`), the toolbar badge shows `7/79`, and Cancel keeps
whatever was already collected — a cancelled CSV export still writes the CSVs for
the videos it got through.

## v2.5 — max quality by default + the full package in one folder

**Quality.** The default preset is now `max`: the highest resolution the site
serves, any codec — so a 4K title downloads as 4K instead of quietly stepping
down to 1080p. The container follows the codec (`--merge-output-format mp4/mkv`):
AV1/H.264 + AAC land in **MP4**, and only a VP9-at-max title falls back to MKV.
Audio is sorted with `acodec:m4a` on purpose — YouTube's best audio is Opus, and
Opus is not a legal MP4 codec for yt-dlp's container table, so preferring AAC is
what keeps a 4K AV1 download inside an editable MP4.

The popup's dropdown is now built from the probe: every entry names the
resolution, codec, container and approximate size it will really produce
(`Max · 2160p · AV1 · MP4 · ≈244 MB`), plus each lower rung the site offers.

**Full package (default).** One folder per video, holding the media *and* its
context:

```
<Title>_<id>/
    <Title>_<id>.mp4            video at max quality (or .mkv if VP9-only)
    <Title>_<id>.webp + .jpg    cover: original + a JPG copy (q2, ffmpeg)
    <Title>_<id>.description    description as plain text
    <Title>_<id>.info.json      full yt-dlp metadata (+ comments if asked)
    <Title>_<id>.<lang>.srt     subtitles: every manual track + auto orig/en/ru
    <Title>_<id>.transcript.json  YTAI-shaped transcript (tc_in/tc_out, M:SS.sss)
    <Title>_<id>.md             readable card: channel, stats, chapters, tags, description
```

Uncheck **Full package → folder** in the popup for the old behaviour (a bare
file straight into `~/Downloads`). **+ comments** adds `--write-comments` (the
comment tree goes into the `.info.json`); it is opt-in because it is slow on
videos with tens of thousands of comments.

**Why subtitles are a separate yt-dlp pass.** yt-dlp writes subtitles *before*
the thumbnail, the info.json and the video, and treats a subtitle HTTP error as
fatal. YouTube answers `429 Too Many Requests` after roughly a dozen timedtext
requests — so one unlucky track inside the main pass would abort the entire
multi-GB download. The subtitle pass therefore runs afterwards with
`--ignore-errors` (a 429 on track 12 becomes a warning), `--no-overwrites`
(re-runs don't re-fetch) and `--sleep-subtitles 0.4`.

Subtitle languages are chosen explicitly, never `all`: YouTube advertises ~160
machine-translated caption languages per video. The host takes every *manual*
track plus the automatic captions for the video's own language, English and
Russian, capped at 24 tracks.

## Automatic fallbacks (v2.0+)

- **Login / age / bot walls** — if the plain attempt fails with something the
  browser session can fix (VK/OK login, YouTube's "sign in to confirm you're not
  a bot", members-only, age gate), the host retries once with
  `--cookies-from-browser chrome`. The trigger is a specific error signature, not
  any failure — reading Chrome's cookie jar pops a macOS Keychain prompt ("access
  Chrome Safe Storage"; click Always Allow), so it stays a last resort. The same
  cookies are reused for the subtitle pass.
- **Rutube geo-block** — for videos blocked outside RU (`api/play/options`
  answers HTTP 244), the host fetches the signed info JSON through an SSH SOCKS
  tunnel to the RU exit (`silent-sphygmograph`, Yandex Cloud, key auth from
  `~/.ssh/config`), then downloads the segments **directly** from the CDN
  (`*.rtbcdn.ru` has no geo check; direct is ~6× faster than the tunnel).
  The popup shows "Geo bypass via RU proxy (1–3 min)…" during this.

## v2.4 — badge, notifications, context menu

- **Toolbar badge** shows live download progress (`42%` → `✓` / `!`) — the
  popup doesn't need to stay open. Cleared once the outcome is seen in the
  popup (or on the next download).
- **System notifications** on done ("Saved · 2160p · MP4 · 1.2 GB") and on
  failure (with the error text). User-initiated cancels stay silent.
- **Context menu** — right-click any YouTube/VK/Rutube/OK video link →
  "Download video — RYA.AE" downloads it via the `best` preset without opening
  the page. List/channel links are declined with a notification (playlist
  protection), and a second download while one runs is refused (single-slot).
- Folder renamed `utils/yt_subtitles` → `utils/video_downloader`; shared
  `common.js` (site detection) used by both the popup and the service worker.

## Hardening (host v2.2 / extension v2.3)

- **Cancel kills the whole process tree** — children run in their own process
  group (`start_new_session`) and cancel `killpg`s it with a 5 s SIGKILL
  escalation, so yt-dlp's ffmpeg subprocesses can't survive as orphans and
  finish the mux after "Cancelled".
- **Cancel reaches every stage** — the SSH tunnel setup and the proxied
  metadata probe are registered as cancellable, not just the main yt-dlp run.
- **SSH tunnel can't leak** — per-pid control sockets (concurrent geo
  downloads don't kill each other's tunnel); masters whose owning host died
  uncleanly are reaped — and their dead socket files unlinked — before each
  connect; port picked by binding :0; `ServerAliveInterval` so a dead peer
  self-terminates the master.
- **Stale-`.part` sweep is anchored** — the media id must sit in the stem
  position and parts touched in the last 60 s are skipped (a concurrent
  same-video download rewrites its part every few seconds; a cancelled
  attempt's part goes cold immediately).
- **Snapshot survives a service-worker restart** — the extension mirrors the
  download state into `chrome.storage.local`; a download that finished (or
  errored, or kept running detached after an extension reload / browser quit)
  while the popup was closed still reports its outcome once (acknowledged
  after display, 10-minute TTL).
- **Subtitle cleanup deletes only its own files** — the popup records every
  subtitle downloadId in `chrome.storage.local`; the weekly cleanup removes
  only those ids (the old substring match could delete unrelated `*_en*/*_ru*`
  JSONs from Downloads).
- **Log writes are flock-serialized**, and trimming runs only in the one-shot
  ping host — a live download's trail can't be truncated.

```
popup → background.js → chrome.runtime.connectNative("ae.rya.ytdl")
                            → ytdl_host_launcher.sh (fixes PATH)
                            → ytdl_host.py  → yt-dlp + ffmpeg
                            ← streamed {progress|done|error}
```

Host actions: `ping`, `formats`, `channel_info` (one-shot) · `download`,
`video_subs`, `video_comments`, `channel_download`, `channel_csv` (streaming,
cancellable). The background service worker keeps a **single job slot** — a
second start is refused rather than orphaning the first.

## Files

| File | Purpose |
|------|---------|
| `ytdl_host.py` | The native messaging host. Speaks Chrome's length-prefixed stdio protocol, runs yt-dlp, streams progress, returns the final file path. |
| `ytdl_host_launcher.sh` | Wrapper that restores a sane `PATH` (Chrome launches hosts with a minimal env → Homebrew yt-dlp/ffmpeg/python3 are otherwise invisible), then execs the host. |
| `ae.rya.ytdl.json` | Native host manifest template (name, launcher path, `allowed_origins` = the extension ID). |
| `install.sh` | Copies the manifest into every Chromium browser's `NativeMessagingHosts/` dir, chmods, checks deps, pings the host. |

## Setup (one-time)

```bash
# dependencies (already present on this Mac):
brew install yt-dlp ffmpeg

# register the host with all installed Chromium browsers + self-test:
bash ~/YTAI/utils/video_downloader/native-host/install.sh
```

Then load/reload the extension at `chrome://extensions` (Developer mode →
Load unpacked → `~/YTAI/utils/video_downloader`). The pinned `key` in `manifest.json`
fixes the extension ID to:

```
ijmcfiafjlppldgcaldgdeffeanhnbgf
```

If Chrome ever shows a **different** ID, re-run the installer with it:

```bash
bash install.sh <the-id-from-chrome>
```

## Format presets (popup → host)

| Preset | yt-dlp format | Container | Use |
|--------|---------------|-----------|-----|
| `max` (default) | `bv*+ba/b -S res,fps,hdr:12,vcodec:av01,acodec:m4a` | MP4, MKV if VP9 | **Highest resolution the site has** — real 4K/8K. AV1 preferred at equal resolution so the file stays an MP4 Premiere 2023+ edits; a VP9-only top rung lands in MKV rather than being downgraded. |
| `2160` / `1440` / `1080` / `720` / … | `bv*[height<=N]+ba/b[height<=N]/b -S res:N,…` | MP4, MKV if VP9 | A specific rung. The popup only offers the ones the site actually serves. |
| `mp4` | `bv*[vcodec!^=vp]+ba/b[vcodec!^=vp]/b` | MP4 | VP9 excluded, always MP4. Offered only when `max` would produce an MKV. |
| `mkv` | `bv*+ba/b` | MKV | Absolute maximum forced into MKV. Archive grade; Premiere won't import .mkv directly. |
| `audio` | `ba[ext=m4a]/ba` | M4A | Audio only. |
| `best` | — | — | Legacy value from ≤ v2.4; now an alias for `max`. |

YouTube 4K is **only** AV1 or VP9 (H.264 caps at 1080p) — that is why the sort
prefers AV1 rather than filtering VP9 out: filtering silently costs you the 4K.

Output → `~/Downloads/<Title>_<mediaId>/…` in package mode, or
`~/Downloads/<Title>_<mediaId>.<ext>` with the package switch off. Unicode titles
are kept (`--windows-filenames` only strips illegal characters). On success the
folder path is copied to the clipboard and the file is revealed in Finder.

## Re-test the host manually

```bash
printf '' | python3 - <<'PY'
import json, struct, subprocess
L="/Users/romansergeev/YTAI/utils/video_downloader/native-host/ytdl_host_launcher.sh"
m=json.dumps({"action":"ping"}).encode()
o=subprocess.run([L], input=struct.pack("=I",len(m))+m, capture_output=True).stdout
print(json.loads(o[4:4+struct.unpack("=I",o[:4])[0]]))
PY
```

Expected: `{'type': 'pong', 'ytdlp': '<version>', 'ffmpeg': True, 'outdir': '.../Downloads', 'host_version': '2.6'}`

## Debug log

The host appends everything to **`native-host/ytdl_host.log`** (command, progress
milestones, raw yt-dlp lines, exit code, final path). Watch it live:

```bash
tail -f ~/YTAI/utils/video_downloader/native-host/ytdl_host.log
```

Popup-side debug: click the **RYA.AE** logo in the popup header to toggle the log panel.

## Troubleshooting

- **Popup says "Native helper not connected"** → run `install.sh`, then reopen the popup. Confirm the ID in `chrome://extensions` matches `allowed_origins` in the installed manifest.
- **"yt-dlp not found"** → `brew install yt-dlp` (the launcher already adds `/opt/homebrew/bin` to PATH).
- **Some videos fail with "Video unavailable"** → that specific video is region-locked/removed; unrelated to the host.
- **Slow downloads / 403** → bump yt-dlp: `brew upgrade yt-dlp`. It's the component that tracks YouTube's changes.
