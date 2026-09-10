#!/usr/bin/env python3
"""
RYA.AE Video Downloader — Chrome native messaging host.

Bridges the "RYA.AE — Video Downloader" extension to a local yt-dlp + ffmpeg so
the popup can download a video at true source quality (up to 4K/8K), with
ffmpeg muxing the separate video/audio streams automatically.

Supported sites: YouTube, VK / VK Video, Rutube, OK (Odnoklassniki).

Protocol (Chrome native messaging, stdio):
  in/out frame = 4-byte length (native byte order) + UTF-8 JSON payload.

Accepted request messages (one per connection from background.js):
  {"action": "ping"}
      -> {"type": "pong", "ytdlp": "<version|null>", "ffmpeg": <bool>,
          "outdir": "<path>", "host_version": "2.5"}
  {"action": "formats", "url": "<page url>"}          (or legacy "videoId")
      -> {"type": "formats", title, duration, maxHeight, heights[], ...}
  {"action": "download", "url": "<page url>",         (or legacy "videoId")
   "format": "max|2160|1440|1080|720|mp4|mkv|audio",
   "bundle": true, "comments": false, "outdir": "<optional abs path>"}
      -> stream of {"type":"progress", percent, speed, eta, stage}
      -> {"type":"done", "path":"<final file>", "folder": "...", files[]}
       | {"type":"error","message":"..."}

YouTube-only jobs on one video:
  {"action": "video_subs", "url": ...}       every subtitle track + transcript.json
  {"action": "video_comments", "url": ..., "commentCap": "100|500|all"}
                                             comments -> CSV sorted by likes

YouTube-only jobs on a channel / playlist (url must be a /videos|/shorts|
/streams tab or a /playlist?list=… page — the popup normalizes it):
  {"action": "channel_info", "url": ...}
      -> {"type":"channel", channel, channelId, count, totalViews, sample[]}
  {"action": "channel_download", "url": ..., "limit": N, "format", "bundle"}
      -> every video as its own package under <Channel>_<id>/, resumable via a
         --download-archive, plus a channel-level videos.csv
  {"action": "channel_csv", "url": ..., "limit": N, "commentCap": "none|100|…"}
      -> <Channel>_videos.csv (views/likes/comments/engagement per video),
         <Channel>_comments.csv, <Channel>_top_comments.csv, raw _info/*.json

Full-package mode ("bundle", default on) puts everything for one video in its
own folder under the output dir:

    <Title>_<id>/
        <Title>_<id>.mp4|mkv      video at max quality (4K when it exists)
        <Title>_<id>.webp/.jpg    cover / thumbnail (original + JPG copy)
        <Title>_<id>.description  description as plain text
        <Title>_<id>.info.json    full yt-dlp metadata (incl. comments if asked)
        <Title>_<id>.<lang>.srt   subtitles (all manual + auto orig/en/ru)
        <Title>_<id>.transcript.json   YTAI-shaped transcript (tc_in/tc_out)
        <Title>_<id>.md           human-readable card: chapters, tags, stats

The subtitles are fetched in a SEPARATE yt-dlp pass on purpose: yt-dlp treats a
subtitle HTTP error (YouTube answers 429 after a handful of timedtext requests)
as fatal, and subtitles are written BEFORE the thumbnail, the info.json and the
video itself — one 429 inside the main pass would abort the whole download.

Fallbacks built into "download":
  - VK/OK/YouTube: if the plain attempt fails on a login/age/bot wall, retry
    once with --cookies-from-browser chrome (the logged-in browser session).
  - Rutube: if the attempt fails with a geo-block signature (the api/play/
    options endpoint answers HTTP 244 for non-RU IPs), fetch the signed
    info JSON through an SSH SOCKS tunnel to the RU exit (silent-sphygmograph,
    Yandex Cloud), then download the segments DIRECTLY from the CDN (no proxy —
    *.rtbcdn.ru has no geo check and direct is ~6x faster than the tunnel).

A background stdin-watcher thread lets the extension cancel a running download
(by sending {"action":"cancel"} or just disconnecting the port -> EOF).
"""

import sys
import os
import re
import csv
import json
import time
import fcntl
import glob
import socket
import struct
import shutil
import signal
import tempfile
import threading
import subprocess
from urllib.parse import urlparse

HOST_VERSION = "2.6"

# ----------------------------------------------------------------------------
# Debug log (answers "есть дебаг?") — append to native-host/ytdl_host.log
# Tail it with:  tail -f ~/YTAI/utils/video_downloader/native-host/ytdl_host.log
# ----------------------------------------------------------------------------
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ytdl_host.log")


def dlog(msg):
    # flock: several hosts run at once (ping + formats + a download) and the
    # trim below rewrites the file — serialize so lines can't be lost mid-trim.
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _trim_log():
    """Keep the log from growing unbounded (cap ~1 MB). Called only from the
    short-lived ping host — never while this process streams a download."""
    try:
        if not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) <= 1_000_000:
            return
        with open(LOG_PATH, "r+b") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            if os.fstat(f.fileno()).st_size <= 1_000_000:
                return  # another host already trimmed while we waited
            f.seek(-200_000, os.SEEK_END)
            tail = f.read()
            f.seek(0)
            f.truncate()
            f.write(b"...[trimmed]...\n" + tail)
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Native messaging stdio framing
# ----------------------------------------------------------------------------

_stdin = sys.stdin.buffer
_stdout = sys.stdout.buffer


def read_message():
    raw_len = _stdin.read(4)
    if len(raw_len) < 4:
        return None  # EOF / port closed
    msg_len = struct.unpack("=I", raw_len)[0]
    if msg_len == 0:
        return None
    data = _stdin.read(msg_len)
    if len(data) < msg_len:
        return None
    return json.loads(data.decode("utf-8"))


_write_lock = threading.Lock()


def send_message(obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    with _write_lock:
        try:
            _stdout.write(struct.pack("=I", len(data)))
            _stdout.write(data)
            _stdout.flush()
        except (BrokenPipeError, OSError):
            # Extension/port went away. Don't crash — an in-flight download
            # keeps running to completion (file still lands on disk).
            pass


# ----------------------------------------------------------------------------
# Tooling discovery
# ----------------------------------------------------------------------------

def find_tool(name):
    """Locate a binary, falling back to the common Homebrew / pip-user dirs.

    Native messaging hosts inherit a minimal PATH from Chrome; the launcher
    script fixes PATH, but we double-check here so the host is robust even if
    invoked directly."""
    p = shutil.which(name)
    if p:
        return p
    for cand in (
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
        os.path.expanduser(f"~/.local/bin/{name}"),
        os.path.expanduser(f"~/Library/Python/3.11/bin/{name}"),
    ):
        if os.path.exists(cand):
            return cand
    return None


def default_outdir():
    return os.path.expanduser("~/Downloads")


def last_error(stderr, fallback="failed"):
    """The useful line out of a yt-dlp stderr dump. Slicing the last 200 chars
    tends to cut an ERROR line in half ("…tionPool(host=…"), so prefer whole
    ERROR/WARNING lines and only fall back to a tail slice."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    errs = [ln for ln in lines if ln.startswith(("ERROR", "yt-dlp: error"))]
    if errs:
        return errs[-1][:300]
    return (lines[-1][:300] if lines else fallback)


def reveal(path):
    """Show the result in Finder so it's never "lost" (best-effort, macOS).
    -R on a file opens its folder with the file selected, which is what we want
    for a package folder too."""
    if not path or not os.path.exists(path):
        return
    try:
        subprocess.Popen(["/usr/bin/open", "-R", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def file_details(path):
    """Best-effort size + video height/codec for a finished file.

    Sizes are decimal (Finder-style): size_mb is bytes / 10^6, so a 1.2 GB file
    reads as 1.2 GB here and in Finder, not 1.1."""
    info = {}
    try:
        size = os.path.getsize(path)
    except OSError:
        return info
    info["size_bytes"] = size
    info["size_mb"] = round(size / 1_000_000)
    ff = find_tool("ffprobe")
    if ff:
        try:
            out = subprocess.run(
                [ff, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=height,codec_name", "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=20).stdout.strip()
            if out:
                parts = [p for p in out.splitlines()[0].split(",") if p]
                for p in parts:
                    if p.isdigit():
                        info["height"] = int(p)
                    else:
                        info["codec"] = _codec_name(p)
        except Exception:
            pass
    return info


# ----------------------------------------------------------------------------
# Target resolution — page URL (multi-site) or legacy YouTube videoId
# ----------------------------------------------------------------------------

ALLOWED_SITES = {
    "youtube.com": "youtube", "youtu.be": "youtube",
    "vk.com": "vk", "vk.ru": "vk", "vkvideo.ru": "vk",
    "ok.ru": "ok", "odnoklassniki.ru": "ok",
    "rutube.ru": "rutube",
}


def resolve_target(req):
    """Return (url, site) for a request, or (None, "<error message>")."""
    url = (req.get("url") or "").strip()
    if url:
        try:
            p = urlparse(url)
        except ValueError:
            return None, f"Bad URL: {url[:80]}"
        if p.scheme != "https":
            return None, f"Refusing non-https URL: {url[:80]}"
        host = (p.hostname or "").lower()
        base = re.sub(r"^(www|m)\.", "", host)
        for dom, site in ALLOWED_SITES.items():
            if base == dom or base.endswith("." + dom):
                return url, site
        return None, f"Unsupported site: {host}"
    video_id = (req.get("videoId") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
        return f"https://www.youtube.com/watch?v={video_id}", "youtube"
    return None, f"Bad request: no url, bad video id {video_id!r}"


# Codec preference used both by the yt-dlp sort (-S …vcodec:av01) and by the
# probe when it guesses WHICH stream a preset will land on. Lower = preferred.
_CODEC_RANK = {"av01": 0, "avc1": 1, "h264": 1, "hev1": 2, "hvc1": 2,
               "vp9": 3, "vp09": 3, "vp08": 4, "vp8": 4}
# Codecs an MP4 container can legally hold AND Premiere can decode. VP9 is
# deliberately absent: VP9-in-MP4 imports as an empty clip.
_MP4_CODECS = {"av01", "avc1", "h264", "hev1", "hvc1"}


def _codec_base(vcodec):
    return (vcodec or "").split(".")[0].lower()


def _codec_name(vcodec):
    """Human label for a codec string. Accepts both yt-dlp's fourcc-ish names
    ('av01.0.12M.08') and ffprobe's ('av1', 'hevc')."""
    v = _codec_base(vcodec)
    if v.startswith(("av01", "av1")):
        return "AV1"
    if v.startswith(("avc1", "h264")):
        return "H.264"
    if v.startswith(("hev1", "hvc1", "h265", "hevc")):
        return "HEVC"
    if v.startswith(("vp9", "vp09")):
        return "VP9"
    if v.startswith(("vp8", "vp08")):
        return "VP8"
    return v.upper()


def _fmt_size(f, duration=0):
    """Best-effort byte size of one format (exact, approx, or from bitrate)."""
    for key in ("filesize", "filesize_approx"):
        v = f.get(key)
        if v:
            return int(v)
    br = f.get("tbr") or f.get("vbr") or f.get("abr")
    if br and duration:
        return int(float(br) * 1000 / 8 * duration)
    return 0


def summarize_formats(data):
    """Turn a yt-dlp info dict into the compact shape the popup needs: the full
    resolution ladder with the codec/container/size each rung will actually
    produce, so the quality dropdown can promise exactly what it delivers."""
    fmts = data.get("formats") or []
    dur = data.get("duration") or 0
    vids = [f for f in fmts
            if f.get("vcodec") not in (None, "none") and f.get("height")]
    auds = [f for f in fmts
            if f.get("acodec") not in (None, "none")
            and f.get("vcodec") in (None, "none")]

    # Audio size guess: the track yt-dlp lands on is a normal-bitrate one, not
    # a 400 kbps surround extra — take the loudest at or below 200 kbps.
    audio_size = 0
    if auds:
        by_abr = sorted(auds, key=lambda f: -(f.get("abr") or 0))
        pick = next((f for f in by_abr if (f.get("abr") or 0) <= 200), by_abr[-1])
        audio_size = _fmt_size(pick, dur)

    ladder = []
    for h in sorted({f["height"] for f in vids}, reverse=True):
        at = [f for f in vids if f["height"] == h]
        # Mirror the download sort (-S res,fps,…,vcodec:av01): fps wins over
        # codec, then AV1 > H.264 > VP9, then the fatter stream.
        at.sort(key=lambda f: (-(f.get("fps") or 0),
                               _CODEC_RANK.get(_codec_base(f.get("vcodec")), 9),
                               -_fmt_size(f, dur)))
        pick = at[0]
        mp4_ok = _codec_base(pick.get("vcodec")) in _MP4_CODECS
        vsize = _fmt_size(pick, dur)
        ladder.append({
            "height": h,
            "fps": int(pick.get("fps") or 0),
            "codec": _codec_name(pick.get("vcodec")),
            "ext": "mp4" if mp4_ok else "mkv",
            # Progressive formats already carry audio; don't double-count it.
            "size": vsize + (0 if pick.get("acodec") not in (None, "none") else audio_size),
            "mp4Codecs": sorted({_codec_name(f.get("vcodec")) for f in at
                                 if _codec_base(f.get("vcodec")) in _MP4_CODECS}),
        })

    top = ladder[0] if ladder else {}
    # The Premiere-safe preset draws from the MP4-capable pool only — report the
    # highest rung it can reach (YouTube caps H.264 at 1080p, but VK/Rutube/OK
    # serve H.264 all the way up, so this is NOT always 1080).
    mp4_rungs = [r for r in ladder if r["mp4Codecs"]]
    mp4_top = mp4_rungs[0] if mp4_rungs else {}

    subs = {k: v for k, v in (data.get("subtitles") or {}).items()
            if k != "live_chat"}
    autos = data.get("automatic_captions") or {}
    return {
        "title": data.get("title") or "",
        "duration": dur,
        "maxHeight": top.get("height", 0),
        "heights": ladder,
        "audioSize": audio_size,
        "subCount": len(subs),
        "autoSubs": bool(autos),
        "thumbCount": len(data.get("thumbnails") or []),
        "chapterCount": len(data.get("chapters") or []),
        "language": data.get("language") or "",
        # Premiere-safe preset (`mp4`) — what it will really produce.
        "mp4Height": mp4_top.get("height", 0),
        "mp4Codec": (mp4_top.get("mp4Codecs") or [""])[0],
        # Legacy keys kept so an older popup build still labels itself sanely.
        "bestHeight": mp4_top.get("height", 0),
        "bestCodec": (mp4_top.get("mp4Codecs") or [""])[0],
        "av1Max": max((r["height"] for r in ladder if r["codec"] == "AV1"),
                      default=0),
    }


def probe_info_raw(url, proc_holder=None, timeout=120, extra_args=()):
    """Full yt-dlp info dict for one video, no download. (data, None) or
    (None, error). Registered in proc_holder so a Cancel reaches it."""
    ytdlp = find_tool("yt-dlp")
    if not ytdlp:
        return None, "yt-dlp not found"
    cmd = [ytdlp, "-J", "--no-warnings", "--no-playlist", *extra_args, url]
    dlog("CMD: " + " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
    except Exception as e:
        return None, str(e)
    if proc_holder is not None:
        proc_holder["proc"] = proc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    finally:
        if proc_holder is not None:
            proc_holder["proc"] = None
    if proc.returncode != 0:
        return None, last_error(err, "probe failed")
    try:
        return json.loads(out), None
    except Exception as e:
        return None, f"parse: {e}"


def probe_formats(url):
    """Quick metadata probe (no download) so the popup can label each preset
    with the real resolution it will produce."""
    data, err = probe_info_raw(url)
    if err:
        return {"error": err}
    try:
        return summarize_formats(data)
    except Exception as e:
        return {"error": f"summarize: {e}"}


# ----------------------------------------------------------------------------
# Format presets -> yt-dlp args
# ----------------------------------------------------------------------------

# Sort used by every video preset: resolution first (so 4K always wins), then
# fps, then HDR, then AV1 over H.264 over VP9 at equal resolution.
# `acodec:m4a` matters more than it looks: YouTube's best audio is Opus, and
# Opus is NOT a legal MP4 codec for yt-dlp's container table — picking it would
# push even an AV1 video into MKV. Preferring AAC keeps the pair MP4-able at a
# bitrate difference nobody can hear (129 vs 129 kbps here).
# NOTE: exactly ONE vcodec field is allowed — a second one breaks the preference.
_SORT = "res,fps,hdr:12,vcodec:av01,acodec:m4a"

# Container preference for merges. yt-dlp picks the FIRST container whose codec
# set covers the streams: AV1/H.264 + AAC/Opus -> mp4, VP9/Opus -> mkv. So the
# file is an editable MP4 whenever that is physically possible, and only falls
# back to MKV when the maximum-quality stream is VP9 (which no MP4 can hold in
# a way Premiere reads anyway).
_CONTAINERS = "mp4/mkv"


def build_format_args(preset):
    """Return yt-dlp format/output args for a quality preset.

    Default ("max") = the highest resolution the site offers, any codec — real
    4K/8K when it exists. YouTube's 4K is AV1 or VP9 only (H.264 caps at 1080p);
    AV1 is preferred so the 4K stream fits an MP4 that Premiere 2023+ edits, and
    a VP9-only title lands in MKV rather than being silently downgraded to
    1080p. VK/Rutube/OK serve H.264 at every rung, so the same sort just takes
    their top stream."""
    if preset == "audio":
        # Best audio only, extracted to m4a.
        return [
            "-f", "ba[ext=m4a]/ba/b",
            "-x", "--audio-format", "m4a",
        ]
    if preset == "mkv":
        # Absolute maximum, forced into MKV. Archive grade, any codec.
        return [
            "-f", "bv*+ba/b",
            "-S", _SORT,
            "--merge-output-format", "mkv",
        ]
    if preset in ("mp4", "premiere"):
        # Premiere-safe: EXCLUDE VP9 (`vcodec!^=vp`), always MP4. Gives 4K when
        # AV1 exists, otherwise steps down to the best H.264 rung.
        return [
            "-f", "bv*[vcodec!^=vp]+ba/b[vcodec!^=vp]/b",
            "-S", "res,fps,vcodec:av01,acodec:m4a",
            "--merge-output-format", "mp4",
        ]
    m = re.fullmatch(r"(\d{3,4})p?", (preset or "").strip())
    if m:
        # Explicit resolution cap (the popup offers the rungs the site has).
        h = int(m.group(1))
        return [
            "-f", f"bv*[height<={h}]+ba/b[height<={h}]/b",
            # res:N both caps and sorts, so it replaces the bare `res` field.
            "-S", "res:{},{}".format(h, _SORT.split(",", 1)[1]),
            "--merge-output-format", _CONTAINERS,
        ]
    # "max" (default; also what the legacy "best" value now means).
    return [
        "-f", "bv*+ba/b",
        "-S", _SORT,
        "--merge-output-format", _CONTAINERS,
    ]


# ----------------------------------------------------------------------------
# Progress parsing
# ----------------------------------------------------------------------------

# Primary machine-readable progress: "RYAPROG|<pct>|<speed>|<eta>"
_PROG_RE = re.compile(r"^RYAPROG\|([^|]*)\|([^|]*)\|(.*)$")
# Fallback: parse yt-dlp's human progress line.
_PCT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
_SPEED_RE = re.compile(r"\bat\s+([0-9.]+\s*[KMGT]?i?B/s|Unknown\s*B/s|Unknown)")
_ETA_RE = re.compile(r"\bETA\s+([\d:]+|Unknown)")
_FINAL_RE = re.compile(r"^RYAFINAL:(.+)$")
_ID_RE = re.compile(r"^RYAID:(.+)$")
_STEM_RE = re.compile(r"^RYASTEM:(.+)$")
# Playlist position — the only progress a channel job has between videos.
_ITEM_RE = re.compile(r"^\[download\]\s+Downloading item (\d+) of (\d+)")
_DEST_RE = re.compile(r'\[download\]\s+Destination:\s+(.+)$')
_MERGE_RE = re.compile(r'\[Merger\]\s+Merging formats into "(.+)"')
_ALREADY_RE = re.compile(r'\[download\]\s+(.+?)\s+has already been downloaded')
_EXTRACT_RE = re.compile(r'\[ExtractAudio\]\s+Destination:\s+(.+)$')


def stream_ytdlp(cmd, proc_holder, stage="downloading", on_line=None):
    """Launch yt-dlp and stream its progress to the extension.

    `stage` labels the progress events — the sidecar subtitle pass reports as
    "subtitles" so a 4 KB .srt can't repaint the bar as "Downloading 3%".
    `on_line` gets every raw output line (channel jobs mine it for per-video
    facts yt-dlp only ever prints, never writes).

    Returns {"code", "final_path", "final_paths", "stems", "dest_path",
    "already", "saw_progress", "item", "total", "tail"} — tail is the last
    non-progress output lines (error context)."""
    dlog("CMD: " + " ".join(cmd))

    # PYTHONUNBUFFERED makes yt-dlp (a Python program) flush stdout per line
    # instead of block-buffering into the pipe — otherwise progress only
    # surfaces at EOF and the popup hangs on "Connecting…".
    child_env = dict(os.environ)
    child_env["PYTHONUNBUFFERED"] = "1"

    st = {"code": -1, "final_path": None, "dest_path": None, "media_id": None,
          "already": False, "saw_progress": False, "tail": [],
          # Channel jobs finish many files; keep every one, not just the last.
          "final_paths": [], "stems": [], "item": 0, "total": 0}

    try:
        # start_new_session puts yt-dlp AND its ffmpeg children in their own
        # process group, so cancel can kill the whole tree (a bare SIGTERM to
        # yt-dlp alone leaves ffmpeg orphaned, finishing the mux anyway).
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=child_env,
            start_new_session=True,
        )
    except OSError as e:
        dlog(f"LAUNCH FAILED: {e}")
        st["tail"] = [f"Cannot launch yt-dlp: {e}"]
        return st

    proc_holder["proc"] = proc
    # A cancel may have arrived while proc_holder['proc'] was None (between the
    # previous attempt exiting and this Popen). watch_stdin keeps running, but
    # re-check here so an already-requested cancel kills this attempt at once
    # instead of letting a full retry download run to completion.
    if proc_holder.get("cancelled"):
        try:
            proc.send_signal(signal.SIGTERM)
        except Exception:
            pass
    last_pct = -10.0       # throttle progress spam: only emit on >=1% change
    last_log_pct = -100.0  # log a progress milestone every ~25%

    def emit_progress(value, speed, eta):
        nonlocal last_pct, last_log_pct
        st["saw_progress"] = True
        # Reset the throttle baseline when a new stream starts (pct drops).
        if value + 1.0 < last_pct:
            last_pct = -10.0
        if abs(value - last_pct) >= 1.0 or value >= 100.0:
            last_pct = value
            send_message({"type": "progress", "stage": stage,
                          "percent": value, "speed": speed, "eta": eta,
                          "item": st["item"], "total": st["total"]})
        if value - last_log_pct >= 25.0 or value >= 100.0:
            last_log_pct = value
            dlog(f"  progress {value:.1f}% {speed} {eta}")

    # iter(readline, "") streams each line as it arrives — a plain
    # `for line in proc.stdout` read-ahead buffers and would stall progress.
    for line in iter(proc.stdout.readline, ""):
        line = line.rstrip("\n")
        if not line:
            continue

        # Primary: machine-readable progress template.
        m = _PROG_RE.match(line)
        if m:
            pct_s, speed_s, eta_s = (x.strip() for x in m.groups())
            try:
                value = float(pct_s.replace("%", "").strip())
            except ValueError:
                value = 0.0
            speed = "" if (not speed_s or "Unknown" in speed_s) else speed_s
            eta = "" if eta_s in ("", "NA", "Unknown") or "Unknown" in eta_s else eta_s
            emit_progress(value, speed, eta)
            continue

        # Everything else is interesting → log it.
        if on_line:
            try:
                on_line(line)
            except Exception:
                pass
        st["tail"].append(line)
        if len(st["tail"]) > 12:
            st["tail"].pop(0)
        dlog("  " + line)

        m = _FINAL_RE.match(line)
        if m:
            st["final_path"] = m.group(1).strip()
            st["final_paths"].append(st["final_path"])
            continue

        m = _ID_RE.match(line)
        if m:
            st["media_id"] = m.group(1).strip()
            continue

        m = _STEM_RE.match(line)
        if m:
            st["stems"].append(m.group(1).strip())
            continue

        m = _ITEM_RE.match(line)
        if m:
            st["item"], st["total"] = int(m.group(1)), int(m.group(2))
            # A channel job can spend a minute on one video's metadata with no
            # byte-level progress; announce the position so the bar still moves.
            send_message({"type": "progress", "stage": stage, "percent": 0,
                          "speed": "", "eta": "",
                          "item": st["item"], "total": st["total"]})
            continue

        m = _MERGE_RE.search(line)
        if m:
            st["final_path"] = st["final_path"] or m.group(1).strip()
            send_message({"type": "progress", "stage": "merging",
                          "percent": 100, "speed": "", "eta": "",
                          "item": st["item"], "total": st["total"]})
            continue

        m = _EXTRACT_RE.search(line)
        if m:
            st["dest_path"] = m.group(1).strip()
            send_message({"type": "progress", "stage": "processing",
                          "percent": 100, "speed": "", "eta": "",
                          "item": st["item"], "total": st["total"]})
            continue

        m = _DEST_RE.search(line)
        if m:
            st["dest_path"] = m.group(1).strip()
            continue

        m = _ALREADY_RE.search(line)
        if m:
            st["dest_path"] = m.group(1).strip()
            st["already"] = True
            continue

        # Fallback: human progress line (older yt-dlp / no template support).
        pct = _PCT_RE.search(line)
        if pct:
            value = float(pct.group(1))
            sp = _SPEED_RE.search(line)
            eta = _ETA_RE.search(line)
            emit_progress(value,
                          sp.group(1).strip() if sp else "",
                          eta.group(1) if eta and "Unknown" not in eta.group(1) else "")

    st["code"] = proc.wait()
    proc_holder["proc"] = None
    return st


# ----------------------------------------------------------------------------
# Rutube geo-block fallback (RU exit via SSH SOCKS, segments direct from CDN)
# ----------------------------------------------------------------------------

RU_SSH_HOST = "silent-sphygmograph"  # Yandex Cloud RU egress (~/.ssh/config)

# Only the genuine Rutube geo-block should trigger the RU tunnel — NOT a plain
# 404/403/network error (which would otherwise waste up to ~3 min on the tunnel
# and dilute the real error). The signature is specific: api/play/options
# answers HTTP 244 with a blocking_rule, and the RU wording cites a rights
# holder / regional restriction. Bare "block"/"244"/"geo" are deliberately
# excluded — they false-match byte counts, fragment numbers and unrelated text.
_GEO_RE = re.compile(
    r"(?i)(HTTP Error 244|\bstatus\W?244\b|blocking_rule|"
    r"правообладател|по\s+решению\s+правообладат|"
    r"недоступ\w*\s+(?:в\s+вашем\s+регионе|в\s+вашей\s+стране|по\s+решени)|"
    r"в\s+вашем\s+регионе|geo[\s_-]?block)")


def looks_geo_blocked(tail):
    return bool(_GEO_RE.search("\n".join(tail)))


# A failure that the logged-in browser session can plausibly fix: age gates,
# members-only / private videos, and YouTube's bot wall. Anything else (a dead
# video, a network error) must NOT trigger the cookie retry — reading Chrome's
# cookie jar pops a macOS Keychain prompt, so it stays a targeted last resort.
_GATED_RE = re.compile(
    r"(?i)(sign in to confirm|confirm you'?re not a bot|not a bot|"
    r"age[- ]restricted|age[- ]gated|inappropriate for some users|"
    r"members[- ]only|join this channel|private video|login required|"
    r"requires? (?:a )?(?:login|sign|authent)|cookies|"
    r"only available to (?:music )?premium|"
    r"войдите|авторизу\w*|доступно только (?:авторизованным|после входа))")


def looks_gated(tail):
    return bool(_GATED_RE.search("\n".join(tail)))


def needs_cookies(st, cancelled=False):
    """Should this failure be retried with the logged-in browser session?

    Only for an auth-shaped failure — YouTube's bot wall is the common one on a
    channel job, where it fails EVERY video and yields an empty export. A geo
    block is excluded: cookies cannot lift a regional restriction, and the
    attempt costs a macOS Keychain prompt plus a full retry."""
    return (not cancelled and looks_gated(st["tail"])
            and not looks_geo_blocked(st["tail"]))


COOKIE_ARGS = ["--cookies-from-browser", "chrome"]


def _free_port():
    """Ask the OS for a free localhost port (tiny TOCTOU window, fine here)."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def rutube_proxy_info(url, ytdlp, proc_holder):
    """Fetch the full yt-dlp info JSON for `url` through an RU SOCKS tunnel.

    Returns (info_json_path, None) on success or (None, error_message).
    Only the metadata/API request needs the RU exit; the returned info holds
    signed m3u8/CDN URLs that download fine (and ~6x faster) without a proxy.

    Both the tunnel setup and the metadata probe are registered in proc_holder
    so a mid-fetch Cancel (watch_stdin -> kill_proc) actually stops them
    instead of hanging up to 40s + 180s."""
    if proc_holder.get("cancelled"):
        return None, "Cancelled"
    ssh = find_tool("ssh") or "/usr/bin/ssh"
    port = _free_port()
    # Per-pid control socket (concurrent geo downloads must not kill each
    # other's tunnel), plus a reap of masters whose owning host died uncleanly
    # (SIGKILL mid-probe leaves the -f master alive forever otherwise).
    for old in glob.glob(os.path.join(tempfile.gettempdir(), "ryadl_ru_*")):
        m = re.search(r"ryadl_ru_(\d+)$", old)
        if not m:
            continue
        try:
            os.kill(int(m.group(1)), 0)
            continue  # owning host still alive — a concurrent run, leave it
        except ProcessLookupError:
            pass  # owner dead → its master (if any) is an orphan
        except PermissionError:
            continue  # pid recycled by another user's process — leave it
        try:
            subprocess.run([ssh, "-S", old, "-O", "exit", RU_SSH_HOST],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        # -O exit on a live master unlinks the socket itself; a dead master
        # leaves the file behind — remove it so it can't shadow a new -M bind.
        try:
            os.unlink(old)
        except OSError:
            pass
    sock = os.path.join(tempfile.gettempdir(), f"ryadl_ru_{os.getpid()}")
    dlog(f"RU tunnel: {RU_SSH_HOST} socks5h://127.0.0.1:{port}")
    try:
        tun = subprocess.Popen(
            [ssh, "-M", "-S", sock, "-o", "ExitOnForwardFailure=yes",
             "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
             # Self-terminate if the peer dies — an orphaned master otherwise
             # squats on the port and holds the Yandex Cloud connection forever.
             "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
             "-D", f"127.0.0.1:{port}", "-N", "-f", RU_SSH_HOST],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True)
    except Exception as e:
        return None, f"RU tunnel failed: {e}"
    proc_holder["proc"] = tun  # cancellable while ssh is still connecting
    if proc_holder.get("cancelled"):
        try:
            tun.send_signal(signal.SIGTERM)
        except Exception:
            pass
    try:
        _, tun_err = tun.communicate(timeout=40)
        rc = tun.returncode
    except subprocess.TimeoutExpired:
        tun.kill()
        _, tun_err = tun.communicate()
        rc = -1
    finally:
        proc_holder["proc"] = None

    def _teardown():
        try:
            subprocess.run([ssh, "-S", sock, "-O", "exit", RU_SSH_HOST],
                           capture_output=True, timeout=15)
        except Exception:
            pass
        try:
            if os.path.exists(sock):
                os.unlink(sock)
        except OSError:
            pass

    if proc_holder.get("cancelled"):
        _teardown()
        return None, "Cancelled"
    if rc != 0:
        return None, "RU tunnel failed: " + (tun_err or "ssh error").strip()[-160:]

    # Tunnel is up — nudge the popup's bar off 0% (the probe below can take
    # minutes with no other events; a frozen bar reads as a hang).
    send_message({"type": "progress", "stage": "proxy",
                  "percent": 20, "speed": "", "eta": ""})

    try:
        probe = subprocess.Popen(
            [ytdlp, "--proxy", f"socks5h://127.0.0.1:{port}",
             "-J", "--no-warnings", "--no-playlist", url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True)
    except Exception as e:
        _teardown()
        return None, f"RU probe failed: {e}"
    proc_holder["proc"] = probe  # make the probe cancellable via kill_proc
    # A cancel may have landed between the last check and the registration
    # above — kill_proc would have no-op'd on proc=None; re-check here.
    if proc_holder.get("cancelled"):
        try:
            probe.send_signal(signal.SIGTERM)
        except Exception:
            pass
    try:
        stdout, stderr = probe.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        probe.kill()
        stdout, stderr = probe.communicate()
    finally:
        proc_holder["proc"] = None
        _teardown()

    if proc_holder.get("cancelled"):
        return None, "Cancelled"
    if probe.returncode != 0:
        return None, "RU probe failed: " + (stderr or "?").strip()[-200:]
    try:
        fd, info_path = tempfile.mkstemp(prefix="ryadl_info_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(stdout)
        return info_path, None
    except Exception as e:
        return None, f"RU probe failed: {e}"


# ----------------------------------------------------------------------------
# Full package ("bundle") — the video plus everything around it, in one folder
# ----------------------------------------------------------------------------

# Both the folder and the file inside it use the same stem, so a project folder
# reads as "<Title>_<id>/<Title>_<id>.mp4". .120B truncates on a UTF-8 boundary
# (Cyrillic titles stay readable) and leaves room for "_<id>.<lang>.srt" under
# the 255-byte per-component limit.
BUNDLE_TMPL = "%(title).120B_%(id)s/%(title).120B_%(id)s.%(ext)s"
FLAT_TMPL = "%(title).200B_%(id)s.%(ext)s"

# Never fetch more than this many subtitle tracks — a site that advertises a
# hundred manual languages would otherwise turn one video into 100 HTTP requests
# (and YouTube starts answering 429 after roughly a dozen).
MAX_SUB_TRACKS = 24


def read_info_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def pick_sub_langs(info, limit=MAX_SUB_TRACKS):
    """Which subtitle tracks to fetch: every human-made one, plus the automatic
    captions for the video's own language, English and Russian.

    Deliberately NOT "all": YouTube lists ~160 machine-translated caption
    languages per video, and asking for them means 160 timedtext requests, a
    429 halfway through, and a folder nobody can read."""
    if not info:
        return []
    manual = [k for k in (info.get("subtitles") or {}) if k != "live_chat"]
    autos = info.get("automatic_captions") or {}
    wanted = set(manual)
    bases = [b for b in ((info.get("language") or "").split("-")[0], "en", "ru") if b]
    for base in bases:
        for k in autos:
            if k == base or k.startswith(base + "-"):
                wanted.add(k)
    wanted.discard("live_chat")

    # Order matters because of the cap: the video's OWN language must survive it.
    # Plain "manual first, then alphabetical" silently drops `ru` from a Russian
    # channel that also ships ar/de/en/es/fr/hi translations.
    orig_base = bases[0] if bases else ""

    def rank(k):
        head = k.split("-")[0]
        if orig_base and head == orig_base:
            return 0
        if head == "en":
            return 1
        if head == "ru":
            return 2
        return 3 if k in manual else 4

    ordered = sorted(wanted, key=lambda k: (rank(k), k))
    return ordered[:max(1, limit)]


def make_jpg_thumbnail(base):
    """YouTube's cover comes down as .webp, which Premiere/Photoshop won't open.
    Add a JPG copy next to it and KEEP the original (it's the lossless source)."""
    ff = find_tool("ffmpeg")
    src = next((base + "." + e for e in ("webp", "png", "jpg", "jpeg")
                if os.path.exists(base + "." + e)), None)
    if not src:
        return None
    if src.endswith((".jpg", ".jpeg")):
        return src
    dst = base + ".jpg"
    if os.path.exists(dst) or not ff:
        return dst if os.path.exists(dst) else None
    try:
        r = subprocess.run([ff, "-y", "-v", "error", "-i", src, "-q:v", "2", dst],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and os.path.exists(dst):
            return dst
        dlog(f"  thumbnail jpg failed: {(r.stderr or '').strip()[-160:]}")
    except Exception as e:
        dlog(f"  thumbnail jpg failed: {e}")
    return None


def _hms(seconds):
    """0:00 / 1:02:03 — the timecode style YouTube chapters use."""
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return "0:00"
    h, rem = divmod(max(0, s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _num(n):
    """1234567 -> '1 234 567' (thin-space grouping, readable in any locale)."""
    try:
        return f"{int(n):,}".replace(",", " ")
    except (TypeError, ValueError):
        return ""


def human_size(nbytes):
    """Finder-style decimal units — 1.4 GB means 1.4 * 10^9 bytes."""
    if not nbytes:
        return ""
    if nbytes >= 1_000_000_000:
        return f"{nbytes / 1_000_000_000:.2f} GB"
    if nbytes >= 1_000_000:
        return f"{nbytes / 1_000_000:.0f} MB"
    return f"{nbytes / 1000:.0f} KB"


def write_meta_md(info, base, video_path, details):
    """A one-page card a human (or the next Claude session) can actually read:
    what this video is, who made it, its chapters, tags and full description.
    The .info.json next to it holds everything; this holds the useful part."""
    t = info.get("title") or ""
    lines = [f"# {t}", ""]

    def row(label, value):
        if value:
            lines.append(f"- **{label}:** {value}")

    channel = info.get("channel") or info.get("uploader") or ""
    curl = info.get("channel_url") or info.get("uploader_url") or ""
    row("Channel", f"{channel} — {curl}" if curl else channel)
    row("URL", info.get("webpage_url") or info.get("original_url") or "")
    up = info.get("upload_date") or ""
    row("Published", f"{up[:4]}-{up[4:6]}-{up[6:8]}" if len(up) == 8 else up)
    row("Duration", _hms(info.get("duration")))
    stats = " · ".join(x for x in (
        f"{_num(info.get('view_count'))} views" if info.get("view_count") else "",
        f"{_num(info.get('like_count'))} likes" if info.get("like_count") else "",
        f"{_num(info.get('comment_count'))} comments" if info.get("comment_count") else "",
    ) if x)
    row("Stats", stats)
    if video_path:
        spec = " · ".join(x for x in (
            f"{details.get('height')}p" if details.get("height") else "",
            details.get("codec") or "",
            human_size(details.get("size_bytes")),
        ) if x)
        row("File", f"`{os.path.basename(video_path)}`" + (f" — {spec}" if spec else ""))
    row("Saved", time.strftime("%Y-%m-%d %H:%M"))

    chapters = info.get("chapters") or []
    if chapters:
        lines += ["", "## Chapters", ""]
        for c in chapters:
            lines.append(f"- `{_hms(c.get('start_time'))}` {c.get('title') or ''}")

    tags = info.get("tags") or []
    if tags:
        lines += ["", "## Tags", "", ", ".join(str(x) for x in tags[:60])]

    desc = info.get("description") or ""
    if desc:
        lines += ["", "## Description", "", desc]

    path = base + ".md"
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")
        return path
    except OSError as e:
        dlog(f"  meta md failed: {e}")
        return None


_SRT_TC_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{1,3})")


def _srt_seconds(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000.0


def _tc(seconds):
    """M:SS.sss — the timecode shape the YTAI transcripts/briefs use."""
    m, s = divmod(float(seconds), 60)
    return f"{int(m)}:{s:06.3f}"


def parse_srt(path):
    """SRT -> [{text, tc_in, tc_out}] with the YTAI timecode format."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []
    segments = []
    for block in re.split(r"\r?\n\r?\n+", raw.strip()):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        tc_idx = next((i for i, ln in enumerate(lines) if _SRT_TC_RE.search(ln)), None)
        if tc_idx is None:
            continue
        m = _SRT_TC_RE.search(lines[tc_idx])
        text = " ".join(lines[tc_idx + 1:]).strip()
        # Strip the inline tags YouTube sprinkles into auto-captions.
        text = re.sub(r"</?[a-zA-Z][^>]*>", "", text).strip()
        if not text:
            continue
        segments.append({
            "text": text,
            "tc_in": _tc(_srt_seconds(*m.groups()[:4])),
            "tc_out": _tc(_srt_seconds(*m.groups()[4:])),
        })
    return segments


def write_transcript_json(base, info):
    """Turn the most useful subtitle track into a YTAI-shaped transcript JSON
    (same field names the popup's Subtitles tab produces), so a downloaded
    video drops straight into the brief/pre-edit pipeline."""
    srts = sorted(glob.glob(glob.escape(base) + ".*.srt"))
    if not srts:
        return None
    orig = ((info or {}).get("language") or "").split("-")[0]

    def rank(p):
        lang = os.path.basename(p)[len(os.path.basename(base)) + 1:-4]
        head = lang.split("-")[0]
        return (0 if head == orig else 1 if head == "en" else 2 if head == "ru" else 3,
                len(lang), lang)

    srts.sort(key=rank)
    chosen = srts[0]
    lang = os.path.basename(chosen)[len(os.path.basename(base)) + 1:-4]
    segments = parse_srt(chosen)
    if not segments:
        return None
    info = info or {}
    out = {
        "video_id": info.get("id") or "",
        "video_url": info.get("webpage_url") or info.get("original_url") or "",
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_id": info.get("channel_id") or "",
        "channel_url": info.get("channel_url") or info.get("uploader_url") or "",
        "published_date": info.get("upload_date") or "",
        "duration": _hms(info.get("duration")),
        "duration_seconds": info.get("duration") or 0,
        "views": info.get("view_count") or 0,
        "likes": info.get("like_count") or 0,
        "description": info.get("description") or "",
        "language": lang,
        "auto_generated": lang in ((info.get("automatic_captions") or {}).keys())
                          and lang not in ((info.get("subtitles") or {}).keys()),
        "source_file": os.path.basename(chosen),
        "segments": segments,
    }
    path = base + ".transcript.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        return path
    except OSError as e:
        dlog(f"  transcript json failed: {e}")
        return None


def subtitle_pass(url, outtmpl, langs, ytdlp, ffmpeg, extra_args, proc_holder):
    """Fetch subtitle tracks in their own yt-dlp run.

    Separate from the media download on purpose: yt-dlp writes subtitles BEFORE
    the thumbnail/info.json/video and treats a subtitle HTTP error as fatal, and
    YouTube answers 429 after a handful of timedtext requests — inside the main
    pass one bad track would throw away the whole download."""
    if not langs:
        return None
    dlog(f"SUBS: {','.join(langs)}")
    cmd = [
        ytdlp, "--no-playlist", "--newline", "--windows-filenames",
        "--skip-download", "--ignore-errors",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", ",".join(langs),
        "--sub-format", "srt/vtt/best",
        "--convert-subs", "srt",
        # Keep tracks already on disk: re-downloading a video (or re-running
        # after a cancel) must not re-fetch a dozen timedtext URLs for nothing.
        "--no-overwrites",
        # YouTube starts answering 429 on requests fired back to back.
        "--sleep-subtitles", "0.4",
        "-o", outtmpl,
        *extra_args,
    ]
    if ffmpeg:
        cmd += ["--ffmpeg-location", os.path.dirname(ffmpeg)]
    st = stream_ytdlp(cmd + [url], proc_holder, stage="subtitles")
    if st["code"] != 0:
        dlog(f"  subtitle pass rc={st['code']} (non-fatal)")
    return st


def info_pass(url, outtmpl, ytdlp, ffmpeg, extra_args, proc_holder,
              stage="metadata"):
    """--skip-download run that writes <stem>.info.json and reports the stem.

    `%(filename)s` still resolves with --skip-download (it is the name the media
    WOULD have had), which is how a metadata-only job learns the folder yt-dlp
    picked for a title it sanitized itself."""
    cmd = [
        ytdlp, "--no-playlist", "--newline", "--windows-filenames",
        "--skip-download", "--write-info-json",
        # --print IMPLIES --simulate AND --quiet. Without --no-simulate the pass
        # prints the stem and writes nothing at all (the job then "succeeds"
        # with an empty folder); without --no-quiet yt-dlp's own progress lines
        # never reach the parser.
        "--no-simulate", "--no-quiet",
        "--print", "RYASTEM:%(filename)s",
        "--print", "RYAID:%(id)s",
        "-o", outtmpl,
        *extra_args,
    ]
    if ffmpeg:
        cmd += ["--ffmpeg-location", os.path.dirname(ffmpeg)]
    return stream_ytdlp(cmd + [url], proc_holder, stage=stage)


MEDIA_EXTS = ("mp4", "mkv", "webm", "mov", "m4a", "mp3", "opus")


def find_media(base):
    """The media file of a package, if one has already been downloaded. A
    subtitles-only or comments-only job must not rewrite the .md card as if the
    video were missing when a previous full download already put it there."""
    for ext in MEDIA_EXTS:
        p = f"{base}.{ext}"
        if os.path.exists(p):
            return p
    return ""


def build_sidecars(video_path, info=None, details=None):
    """The local, network-free half of a package: JPG cover, readable .md card,
    YTAI transcript. Safe to re-run — everything is overwritten in place."""
    base = os.path.splitext(video_path)[0]
    if info is None:
        info = read_info_json(base + ".info.json")
    if details is None:
        details = file_details(video_path) if os.path.exists(video_path) else {}
    make_jpg_thumbnail(base)
    if info:
        write_meta_md(info, base, video_path, details)
    write_transcript_json(base, info)
    return info


def folder_contents(folder):
    """(files, total_bytes) for the report back to the popup."""
    files, total = [], 0
    try:
        for name in sorted(os.listdir(folder)):
            p = os.path.join(folder, name)
            if not os.path.isfile(p) or name.startswith("."):
                continue
            size = os.path.getsize(p)
            total += size
            files.append({"name": name, "size": size})
    except OSError:
        pass
    return files, total


def folder_size(folder):
    """Bytes under a folder INCLUDING subfolders — a channel folder holds only
    per-video subfolders, so a top-level-only sum would report a few hundred KB
    of CSVs for a 40 GB download."""
    total = 0
    for root, _dirs, names in os.walk(folder):
        for name in names:
            if name.startswith("."):
                continue
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# ----------------------------------------------------------------------------
# YouTube collections — a channel tab or a playlist
# ----------------------------------------------------------------------------

# The popup normalizes a channel page to one enumerable tab before sending it
# here; the host still re-validates (same rule as resolve_target: never trust
# the page). A bare /@handle is refused on purpose — yt-dlp would expand it into
# every tab at once (videos + shorts + live + playlists).
_YT_TAB_RE = re.compile(
    r"^/(?:@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/(videos|shorts|streams)/?$")


def resolve_collection(req):
    """Return (url, kind) for a channel/playlist request, or (None, error)."""
    url = (req.get("url") or "").strip()
    try:
        p = urlparse(url)
    except ValueError:
        return None, f"Bad URL: {url[:80]}"
    if p.scheme != "https":
        return None, f"Refusing non-https URL: {url[:80]}"
    host = re.sub(r"^(www|m)\.", "", (p.hostname or "").lower())
    if host != "youtube.com" and not host.endswith(".youtube.com"):
        return None, "Channel jobs are YouTube-only"
    if _YT_TAB_RE.match(p.path):
        return url, "channel"
    if p.path.rstrip("/") == "/playlist" and re.search(r"(^|&)list=", p.query or ""):
        return url, "playlist"
    return None, f"Not an enumerable channel tab or playlist: {p.path[:60]}"


def safe_name(text, limit=100):
    """Filesystem-safe folder name (yt-dlp does this for its own templates; the
    channel folder is built in Python, so it needs the same treatment)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text or "").strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.encode("utf-8")[:limit].decode("utf-8", "ignore").strip(" .") or "channel"


def probe_collection(url, proc_holder=None, keep_entries=False):
    """Enumerate a channel/playlist cheaply (--flat-playlist: ids, titles,
    durations and view counts, no per-video extraction). ~1 s for 80 videos.

    keep_entries adds the full entry list — needed to rank by views, but far too
    big to ship to the popup, which only ever needs the counters."""
    ytdlp = find_tool("yt-dlp")
    if not ytdlp:
        return {"error": "yt-dlp not found"}
    cmd = [ytdlp, "--flat-playlist", "-J", "--no-warnings", url]
    dlog("CMD: " + " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, start_new_session=True)
    except Exception as e:
        return {"error": str(e)}
    if proc_holder is not None:
        proc_holder["proc"] = proc
    try:
        out, err = proc.communicate(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    finally:
        if proc_holder is not None:
            proc_holder["proc"] = None
    if proc.returncode != 0:
        return {"error": last_error(err, "probe failed")}
    try:
        data = json.loads(out)
    except Exception as e:
        return {"error": f"parse: {e}"}
    entries = [e for e in (data.get("entries") or []) if e and e.get("id")]
    out = {
        "title": data.get("title") or "",
        "channel": data.get("channel") or data.get("uploader") or data.get("title") or "",
        "channelId": data.get("channel_id") or data.get("playlist_id") or "",
        "channelUrl": data.get("channel_url") or data.get("uploader_url") or "",
        "count": data.get("playlist_count") or len(entries),
        "totalViews": sum(int(e.get("view_count") or 0) for e in entries),
        "totalDuration": sum(int(e.get("duration") or 0) for e in entries),
        "topViews": max((int(e.get("view_count") or 0) for e in entries), default=0),
        "sample": [{"id": e.get("id"), "title": e.get("title") or "",
                    "duration": e.get("duration") or 0,
                    "views": e.get("view_count") or 0} for e in entries[:8]],
    }
    if keep_entries:
        out["entries"] = entries
    return out


def playlist_selection(meta, limit, sort):
    """The --playlist-items spec for the requested slice, or None for "the whole
    thing in playlist order".

    "popular" is resolved here rather than by a YouTube sort parameter: the flat
    probe already carries every entry's view count, so ranking locally works for
    playlists too and does not depend on YouTube honouring `?sort=p`. The rank is
    mapped back to playlist POSITIONS (`-I 3,7,11`) so the run stays one playlist
    job — that is what keeps `Downloading item N of M` progress and the download
    archive working."""
    if not limit:
        return None
    entries = meta.get("entries") or []
    if str(sort) != "popular" or not entries:
        return f"1:{limit}"
    ranked = sorted(range(len(entries)),
                    key=lambda i: -(int(entries[i].get("view_count") or 0)))[:limit]
    # Positions are 1-based, and handed over in playlist order: yt-dlp walks the
    # list once, so asking out of order would gain nothing.
    return ",".join(str(i + 1) for i in sorted(ranked))


def collection_folder(outdir, meta):
    """<outdir>/<Channel>_<channelId>/ — one home per channel, so repeated jobs
    (download, then CSV, then a top-up) all land in the same place."""
    name = safe_name(meta.get("channel") or meta.get("title") or "channel")
    cid = safe_name(meta.get("channelId") or "", 40)
    return os.path.join(outdir, f"{name}_{cid}" if cid else name)


# yt-dlp overwrites comment_count with the number of comments it actually
# extracted, so a capped run reports "100 comments" for a video that has 4000.
# The true figure is only ever printed ("Downloading ~4103 comments"), so mine
# it out of the stream and keep it beside the per-video id.
_CUR_VIDEO_RE = re.compile(r"\[youtube\] Extracting URL: .*[?&]v=([\w-]{6,20})")
_COMMENT_TOTAL_RE = re.compile(r"Downloading ~?([\d,]+) comments")


def comment_total_watcher(totals):
    """Returns an on_line hook that fills {video_id: true_comment_count}."""
    state = {"id": None}

    def hook(line):
        m = _CUR_VIDEO_RE.search(line)
        if m:
            state["id"] = m.group(1)
            return
        m = _COMMENT_TOTAL_RE.search(line)
        if m and state["id"]:
            totals[state["id"]] = int(m.group(1).replace(",", ""))
    return hook


# ----------------------------------------------------------------------------
# CSV export
# ----------------------------------------------------------------------------

# A cell starting with = or + (or a - that isn't a negative number) is executed
# as a formula by Excel and Google Sheets, which turns a comment like "=D" into
# #ERROR! and loses the text. One leading apostrophe keeps it literal.
# `@` is deliberately NOT in this set: every YouTube author handle starts with
# one, so escaping it would mangle the entire author column.
_FORMULA_RE = re.compile(r"^[=+]|^-[^\d.]")


def _csv_text(value):
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "'" + text if _FORMULA_RE.match(text) else text


def _iso_date(yyyymmdd):
    d = str(yyyymmdd or "")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 and d.isdigit() else d


def _iso_epoch(ts):
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(int(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def _per_1k(part, whole):
    return round(part / whole * 1000, 1) if (part and whole) else ""


def video_row(info, n, comment_totals):
    vid = info.get("id") or ""
    url = info.get("webpage_url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
    views = int(info.get("view_count") or 0)
    likes = int(info.get("like_count") or 0)
    # Prefer the true total mined from the log over the capped count.
    total_comments = comment_totals.get(vid)
    if total_comments is None:
        total_comments = int(info.get("comment_count") or 0)
    got = len(info.get("comments") or [])
    dur = int(info.get("duration") or 0)
    h, w = info.get("height") or 0, info.get("width") or 0
    return {
        "n": n,
        "video_id": vid,
        "url": url,
        "title": _csv_text(info.get("title")),
        "published": _iso_date(info.get("upload_date")),
        "duration": _hms(dur),
        "duration_sec": dur,
        "views": views,
        "likes": likes,
        "comments": total_comments,
        "comments_exported": got,
        "likes_per_1k_views": _per_1k(likes, views),
        "comments_per_1k_views": _per_1k(total_comments, views),
        "engagement_per_1k_views": _per_1k(likes + total_comments, views),
        "is_short": "yes" if 0 < dur <= 60 else "",
        "live_status": info.get("live_status") or "",
        "availability": info.get("availability") or "",
        "language": info.get("language") or "",
        "max_resolution": f"{w}x{h}" if (w and h) else (f"{h}p" if h else ""),
        "fps": info.get("fps") or "",
        "channel": _csv_text(info.get("channel") or info.get("uploader")),
        "channel_id": info.get("channel_id") or "",
        "categories": "; ".join(info.get("categories") or []),
        "tags": _csv_text("; ".join(info.get("tags") or [])),
        "thumbnail": info.get("thumbnail") or "",
        "description": _csv_text(info.get("description")),
    }


def comment_rows(info):
    vid = info.get("id") or ""
    vurl = info.get("webpage_url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
    vtitle = info.get("title") or ""
    rows = []
    for c in (info.get("comments") or []):
        cid = c.get("id") or ""
        parent = c.get("parent") or "root"
        rows.append({
            "video_id": vid,
            "video_title": _csv_text(vtitle),
            "video_url": vurl,
            "comment_id": cid,
            "is_reply": "yes" if parent != "root" else "",
            "parent_id": "" if parent == "root" else parent,
            "likes": int(c.get("like_count") or 0),
            "author": _csv_text(c.get("author")),
            "author_id": c.get("author_id") or "",
            "author_url": c.get("author_url") or "",
            "by_channel_owner": "yes" if c.get("author_is_uploader") else "",
            "verified": "yes" if c.get("author_is_verified") else "",
            "pinned": "yes" if c.get("is_pinned") else "",
            "hearted_by_owner": "yes" if c.get("is_favorited") else "",
            "published": _iso_epoch(c.get("timestamp")),
            "published_text": _csv_text(c.get("_time_text")),
            "text": _csv_text(c.get("text")),
            "comment_url": f"{vurl}&lc={cid}" if (vurl and cid) else "",
        })
    return rows


def top_comment_rows(all_rows, limit=200):
    """The most engaged comments of the whole channel, ranked by likes."""
    ranked = sorted(all_rows, key=lambda r: -(r.get("likes") or 0))[:limit]
    out = []
    for i, r in enumerate(ranked, 1):
        if not r.get("likes"):
            break  # everything below here has zero likes — not "engaged"
        out.append({
            "rank": i,
            "likes": r["likes"],
            "author": r["author"],
            "text": r["text"],
            "is_reply": r["is_reply"],
            "by_channel_owner": r["by_channel_owner"],
            "hearted_by_owner": r["hearted_by_owner"],
            "published": r["published"],
            "video_title": r["video_title"],
            "video_url": r["video_url"],
            "comment_url": r["comment_url"],
        })
    return out


def write_csv(path, rows):
    """UTF-8 **with BOM** — without it Excel renders Cyrillic as mojibake."""
    if not rows:
        return None
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()),
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return path
    except OSError as e:
        dlog(f"  csv write failed ({os.path.basename(path)}): {e}")
        return None


def load_infos(info_dir, patterns=("*.info.json",)):
    """Every per-video info.json under a folder. Glob order is alphabetical and
    meaningless, so sort newest-first — the order a channel reads in."""
    infos, seen = [], set()
    paths = []
    for pat in patterns:
        paths += glob.glob(os.path.join(glob.escape(info_dir), pat))
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        d = read_info_json(p)
        # --no-write-playlist-metafiles should prevent this, but a stray
        # playlist-level json would poison every aggregate.
        if not d or d.get("_type") == "playlist" or "entries" in d:
            continue
        if d.get("id"):
            infos.append(d)
    infos.sort(key=lambda d: (str(d.get("upload_date") or ""),
                              int(d.get("timestamp") or 0)), reverse=True)
    return infos


def write_collection_csvs(folder, meta, infos, comment_totals, prefix):
    """videos.csv + comments.csv + top_comments.csv + a readable summary."""
    written = []
    videos = [video_row(d, i, comment_totals) for i, d in enumerate(infos, 1)]
    p = write_csv(os.path.join(folder, f"{prefix}_videos.csv"), videos)
    if p:
        written.append(p)

    all_comments = []
    for d in infos:
        all_comments.extend(comment_rows(d))
    if all_comments:
        p = write_csv(os.path.join(folder, f"{prefix}_comments.csv"), all_comments)
        if p:
            written.append(p)
        p = write_csv(os.path.join(folder, f"{prefix}_top_comments.csv"),
                      top_comment_rows(all_comments))
        if p:
            written.append(p)

    p = write_collection_md(folder, meta, videos, all_comments, prefix)
    if p:
        written.append(p)
    return written, videos, all_comments


def write_collection_md(folder, meta, videos, comments, prefix):
    """The export at a glance: totals, the top videos, the top comments."""
    views = sum(v["views"] for v in videos)
    likes = sum(v["likes"] for v in videos)
    lines = [
        f"# {meta.get('channel') or meta.get('title') or 'Channel'}",
        "",
        f"- **URL:** {meta.get('channelUrl') or ''}",
        f"- **Channel ID:** {meta.get('channelId') or ''}",
        f"- **Videos in export:** {len(videos)}"
        + (f" of {meta.get('count')}" if meta.get("count") else ""),
        f"- **Total views:** {_num(views)} · **likes:** {_num(likes)}"
        + (f" · **comments exported:** {_num(len(comments))}" if comments else ""),
        f"- **Exported:** {time.strftime('%Y-%m-%d %H:%M')}",
    ]
    if views and videos:
        lines.append(f"- **Median views:** "
                     f"{_num(sorted(v['views'] for v in videos)[len(videos) // 2])}")

    top_v = sorted(videos, key=lambda v: -v["views"])[:10]
    if top_v:
        lines += ["", "## Most viewed", ""]
        for v in top_v:
            lines.append(f"- {_num(v['views'])} views · {_num(v['likes'])} likes — "
                         f"[{v['title']}]({v['url']})")
    top_c = top_comment_rows(comments, 10)
    if top_c:
        lines += ["", "## Most liked comments", ""]
        for c in top_c:
            text = " ".join(str(c["text"]).split())[:180]
            lines.append(f"- **{_num(c['likes'])}** · {c['author']} — {text} "
                         f"([{c['video_title'][:40]}]({c['comment_url']}))")
    path = os.path.join(folder, f"{prefix}_export.md")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")
        return path
    except OSError as e:
        dlog(f"  export md failed: {e}")
        return None


# Comment caps offered by the popup -> yt-dlp extractor args. The tuple is
# max-comments, max-parents, max-replies, max-replies-per-thread.
COMMENT_CAPS = {
    "100": "100,all,40,5",
    "500": "500,all,200,10",
    "all": "all",
}


def comment_args(cap):
    spec = COMMENT_CAPS.get(str(cap or "").lower())
    if not spec:
        return []
    # top sorting is what makes a capped export the MOST ENGAGED comments
    # rather than an arbitrary recent slice.
    return ["--write-comments", "--extractor-args",
            f"youtube:comment_sort=top;max_comments={spec}"]


# ----------------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------------

def run_download(req, proc_holder):
    url, site = resolve_target(req)
    if not url:
        send_message({"type": "error", "message": site})
        return

    ytdlp = find_tool("yt-dlp")
    if not ytdlp:
        send_message({"type": "error",
                      "message": "yt-dlp not found. Install: brew install yt-dlp"})
        return

    ffmpeg = find_tool("ffmpeg")
    outdir = req.get("outdir") or default_outdir()
    outdir = os.path.expanduser(outdir)
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError as e:
        send_message({"type": "error", "message": f"Cannot create outdir: {e}"})
        return

    preset = (req.get("format") or "max").strip()
    fmt_args = build_format_args(preset)

    # Full package (default): one folder per video holding the media AND its
    # context. Set bundle=false for the old behaviour (a bare file in Downloads).
    bundle = req.get("bundle", True)
    if isinstance(bundle, str):
        bundle = bundle.lower() not in ("false", "0", "no", "")
    bundle = bool(bundle)

    # NOTE: do NOT use --restrict-filenames — it strips all non-ASCII, so a
    # Cyrillic title collapses to "._._._<id>" (a hidden, unreadable file).
    # yt-dlp's default sanitization keeps Unicode and only fixes illegal chars.
    outtmpl = os.path.join(outdir, BUNDLE_TMPL if bundle else FLAT_TMPL)

    # Sidecars for the main pass. Subtitles are NOT here on purpose — see the
    # module docstring: yt-dlp writes them before the video and treats a
    # subtitle HTTP error as fatal, so a 429 would cost us the whole download.
    package_args = []
    if bundle:
        package_args = ["--write-info-json", "--write-description",
                        "--write-thumbnail"]
        if req.get("comments"):
            # Folded into the .info.json by yt-dlp. Slow on big videos, so the
            # popup keeps this opt-in.
            package_args += ["--write-comments"]

    def build_cmd(extra_args, target_args):
        cmd = [
            ytdlp,
            "--no-playlist",
            "--newline",
            "--windows-filenames",
            "--no-simulate",
            # --print implies BOTH --simulate and --quiet. Undo both: quiet
            # swallows "[Merger] Merging formats into…" and "has already been
            # downloaded", which are exactly the lines the stage parser reads.
            "--no-quiet",
            "--progress",
            "--progress-template",
            "download:RYAPROG|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "--print", "after_move:RYAFINAL:%(filepath)s",
            "--print", "RYAID:%(id)s",
            "-N", "8",
            "-o", outtmpl,
            *fmt_args,
            *package_args,
            *extra_args,
        ]
        if ffmpeg:
            cmd += ["--ffmpeg-location", os.path.dirname(ffmpeg)]
        cmd += target_args
        return cmd

    dlog(f"DOWNLOAD site={site} url={url} format={preset} "
         f"bundle={bundle} comments={bool(req.get('comments'))} outdir={outdir}")
    send_message({"type": "started", "format": preset, "site": site,
                  "outdir": outdir, "bundle": bundle})

    st = stream_ytdlp(build_cmd([], [url]), proc_holder)

    # Fallback 1: the video sits behind the logged-in session — VK/OK login or
    # age walls, YouTube's "sign in to confirm you're not a bot" / members-only.
    # Retry once with the real Chrome cookies. `cookie_args` is reused by the
    # subtitle pass so it doesn't walk into the same wall.
    cookie_args = []
    if (st["code"] != 0 and not proc_holder.get("cancelled")
            and (site in ("vk", "ok")
                 # A Rutube geo-block is fallback 2's job — cookies can't lift a
                 # regional restriction, and trying costs a Keychain prompt plus
                 # a full retry before the tunnel even starts.
                 or (looks_gated(st["tail"]) and not looks_geo_blocked(st["tail"])))):
        dlog("RETRY with Chrome cookies")
        send_message({"type": "progress", "stage": "cookies",
                      "percent": 0, "speed": "", "eta": ""})
        retry_args = ["--cookies-from-browser", "chrome"]
        st2 = stream_ytdlp(build_cmd(retry_args, [url]), proc_holder)
        if st2["code"] == 0:
            cookie_args = retry_args
            st = st2
        else:
            st2["tail"] = (st["tail"][-3:] + ["--- retry with Chrome cookies ---"]
                           + st2["tail"][-3:])
            st = st2

    # Fallback 2: Rutube geo-block (api/play/options answers HTTP 244 for
    # non-RU IPs; the CDN itself has no geo check). Resolve the signed info
    # JSON through the RU tunnel, then download direct from the CDN.
    info_path = None
    geo_used = False
    if (st["code"] != 0 and not proc_holder.get("cancelled")
            and site == "rutube" and looks_geo_blocked(st["tail"])):
        geo_used = True
        dlog("RETRY via RU proxy (geo bypass)")
        send_message({"type": "progress", "stage": "proxy",
                      "percent": 0, "speed": "", "eta": ""})
        info_path, err = rutube_proxy_info(url, ytdlp, proc_holder)
        if info_path and not proc_holder.get("cancelled"):
            st3 = stream_ytdlp(
                build_cmd(["-N", "16"], ["--load-info-json", info_path]),
                proc_holder)
            if st3["code"] != 0:
                st3["tail"] = (st["tail"][-3:] + ["--- retry via RU proxy ---"]
                               + st3["tail"][-3:])
            st = st3
        elif err:
            st["tail"] = st["tail"][-6:] + [err]
    if info_path:
        try:
            os.remove(info_path)
        except OSError:
            pass

    dlog(f"EXIT code={st['code']} final_path={st['final_path'] or st['dest_path']}")

    if proc_holder.get("cancelled"):
        dlog("RESULT: cancelled")
        send_message({"type": "error", "message": "Cancelled"})
        return

    if st["code"] != 0:
        msg = "\n".join(st["tail"][-6:]) or f"yt-dlp exited {st['code']}"
        dlog(f"RESULT: error (code {st['code']})")
        send_message({"type": "error", "message": msg})
        return

    path = st["final_path"] or st["dest_path"]
    if path and not os.path.isabs(path):
        path = os.path.join(outdir, path)

    # If no download progress ever fired, yt-dlp skipped because the file was
    # already on disk (the --progress-template suppresses the "has already been
    # downloaded" line, so we infer it from the absence of progress).
    already = st["already"] or not st["saw_progress"]
    if already:
        send_message({"type": "progress", "stage": "exists",
                      "percent": 100, "speed": "", "eta": ""})

    # Sweep stale .part fragments for THIS video (e.g. a half-downloaded VP9
    # stream from an earlier preset) — yt-dlp only resumes same-format parts,
    # so others just clutter the folder and look like "nothing downloaded".
    # Use the exact id captured from yt-dlp (RYAID). Deriving it from the
    # filename is unsafe for VK/OK: their ids contain underscores (owner_video)
    # so the last "_"-chunk collides across different owners' videos and would
    # delete an unrelated resumable .part.
    vid_key = st.get("media_id") or (req.get("videoId") or "").strip()
    # In bundle mode the parts live in the video's own folder, not in outdir.
    sweep_dir = os.path.dirname(path) if (bundle and path) else outdir
    if vid_key and len(vid_key) >= 4 and not vid_key.isspace() and sweep_dir:
        try:
            now = time.time()
            # Anchor the id to its stem position (outtmpl = "<title>_<id>.<ext>")
            # instead of matching it anywhere, and skip parts touched in the
            # last 60s — a CONCURRENT download of the same video (other preset /
            # second popup) rewrites its .part every few seconds, while a part
            # from a cancelled earlier attempt goes cold immediately.
            for pat in (f"*_{vid_key}.*.part", f"*_{vid_key}.part"):
                for stale in glob.glob(os.path.join(glob.escape(sweep_dir), pat)):
                    try:
                        if now - os.path.getmtime(stale) < 60:
                            continue
                        os.remove(stale)
                        dlog(f"cleaned stale part: {os.path.basename(stale)}")
                    except OSError:
                        pass
        except Exception:
            pass

    details = file_details(path) if (path and os.path.exists(path)) else {}
    ext = os.path.splitext(path)[1].lstrip(".").lower() if path else ""

    # ---- Full package: subtitles, cover as JPG, readable card, transcript ----
    extras = {}
    if bundle and path and os.path.exists(path):
        base = os.path.splitext(path)[0]
        folder = os.path.dirname(path)
        info = read_info_json(base + ".info.json")

        # Error-tolerant subtitle pass (see subtitle_pass for why it is separate).
        langs = [] if geo_used else pick_sub_langs(info)
        if langs and not proc_holder.get("cancelled"):
            send_message({"type": "progress", "stage": "subtitles",
                          "percent": 100, "speed": "", "eta": ""})
            subtitle_pass(url, outtmpl, langs, ytdlp, ffmpeg, cookie_args,
                          proc_holder)

        if not proc_holder.get("cancelled"):
            send_message({"type": "progress", "stage": "extras",
                          "percent": 100, "speed": "", "eta": ""})
            build_sidecars(path, info, details)

        files, total = folder_contents(folder)
        extras = {"folder": folder, "files": [f["name"] for f in files],
                  "fileCount": len(files), "folderSize": total}
        dlog(f"PACKAGE: {len(files)} files, {human_size(total)} in {folder}")

    dlog(f"RESULT: done{' (already existed)' if already else ''} -> {path or outdir} {details}")
    send_message({"type": "done", "job": "download", "path": path or outdir,
                  "already": already, "ext": ext, "bundle": bundle,
                  **details, **extras})
    reveal(path)


# ----------------------------------------------------------------------------
# Single-video jobs: subtitles only / comments only
# ----------------------------------------------------------------------------

def job_setup(req):
    """(ytdlp, ffmpeg, outdir, error) shared by every job."""
    ytdlp = find_tool("yt-dlp")
    if not ytdlp:
        return None, None, None, "yt-dlp not found. Install: brew install yt-dlp"
    outdir = os.path.expanduser(req.get("outdir") or default_outdir())
    try:
        os.makedirs(outdir, exist_ok=True)
    except OSError as e:
        return None, None, None, f"Cannot create outdir: {e}"
    return ytdlp, find_tool("ffmpeg"), outdir, None


def run_video_subs(req, proc_holder):
    """Subtitles only — every track plus the YTAI transcript.json, into the
    video's package folder so a later full download merges with it."""
    url, site = resolve_target(req)
    if not url:
        send_message({"type": "error", "message": site})
        return
    ytdlp, ffmpeg, outdir, err = job_setup(req)
    if err:
        send_message({"type": "error", "message": err})
        return

    outtmpl = os.path.join(outdir, BUNDLE_TMPL)
    dlog(f"SUBS-ONLY site={site} url={url} outdir={outdir}")
    send_message({"type": "started", "job": "video_subs", "site": site,
                  "outdir": outdir})

    cookie_args = []
    st = info_pass(url, outtmpl, ytdlp, ffmpeg, [], proc_holder)
    if not st["stems"] and needs_cookies(st, proc_holder.get("cancelled")):
        dlog("SUBS-ONLY retry with Chrome cookies")
        send_message({"type": "progress", "stage": "cookies", "percent": 0,
                      "speed": "", "eta": ""})
        cookie_args = COOKIE_ARGS
        st = info_pass(url, outtmpl, ytdlp, ffmpeg, cookie_args, proc_holder)
    if proc_holder.get("cancelled"):
        send_message({"type": "error", "message": "Cancelled"})
        return
    if st["code"] != 0 or not st["stems"]:
        send_message({"type": "error",
                      "message": "\n".join(st["tail"][-6:]) or "Could not read the video"})
        return

    base = os.path.splitext(st["stems"][0])[0]
    folder = os.path.dirname(base)
    info = read_info_json(base + ".info.json")
    langs = pick_sub_langs(info)
    if not langs:
        send_message({"type": "error", "message": "This video has no subtitles"})
        return

    subtitle_pass(url, outtmpl, langs, ytdlp, ffmpeg, cookie_args, proc_holder)
    if proc_holder.get("cancelled"):
        send_message({"type": "error", "message": "Cancelled"})
        return

    send_message({"type": "progress", "stage": "extras", "percent": 100,
                  "speed": "", "eta": ""})
    media = find_media(base)
    if info:
        write_meta_md(info, base, media, file_details(media) if media else {})
    transcript = write_transcript_json(base, info)
    srts = sorted(glob.glob(glob.escape(base) + ".*.srt"))
    if not srts:
        send_message({"type": "error",
                      "message": "Subtitles could not be downloaded (YouTube rate limit?)"})
        return

    files, total = folder_contents(folder)
    dlog(f"SUBS-ONLY done: {len(srts)} tracks in {folder}")
    send_message({"type": "done", "job": "video_subs",
                  "path": transcript or srts[0], "folder": folder,
                  "files": [f["name"] for f in files], "fileCount": len(files),
                  "folderSize": total, "subCount": len(srts),
                  "note": f"{len(srts)} subtitle track(s)"})
    reveal(transcript or srts[0])


def run_video_comments(req, proc_holder):
    """Comments of one video -> CSV sorted by likes (most engaged first)."""
    url, site = resolve_target(req)
    if not url:
        send_message({"type": "error", "message": site})
        return
    if site != "youtube":
        send_message({"type": "error", "message": "Comments export is YouTube-only"})
        return
    ytdlp, ffmpeg, outdir, err = job_setup(req)
    if err:
        send_message({"type": "error", "message": err})
        return

    cap = req.get("commentCap") or "500"
    outtmpl = os.path.join(outdir, BUNDLE_TMPL)
    dlog(f"COMMENTS url={url} cap={cap} outdir={outdir}")
    send_message({"type": "started", "job": "video_comments", "site": site,
                  "outdir": outdir})

    totals = {}
    st = info_pass(url, outtmpl, ytdlp, ffmpeg, comment_args(cap), proc_holder,
                   stage="comments")
    if not st["stems"] and needs_cookies(st, proc_holder.get("cancelled")):
        dlog("COMMENTS retry with Chrome cookies")
        send_message({"type": "progress", "stage": "cookies", "percent": 0,
                      "speed": "", "eta": ""})
        st = info_pass(url, outtmpl, ytdlp, ffmpeg,
                       comment_args(cap) + COOKIE_ARGS, proc_holder,
                       stage="comments")
    # A cancel here still leaves nothing useful — comments live in the info.json
    # which is only written at the very end of the extraction.
    if proc_holder.get("cancelled"):
        send_message({"type": "error", "message": "Cancelled"})
        return
    if st["code"] != 0 or not st["stems"]:
        send_message({"type": "error",
                      "message": "\n".join(st["tail"][-6:]) or "Could not read the video"})
        return

    base = os.path.splitext(st["stems"][0])[0]
    folder = os.path.dirname(base)
    info = read_info_json(base + ".info.json")
    rows = comment_rows(info) if info else []
    if not rows:
        send_message({"type": "error",
                      "message": "No comments found (disabled on this video?)"})
        return
    rows.sort(key=lambda r: -(r.get("likes") or 0))
    csv_path = write_csv(base + ".comments.csv", rows)
    media = find_media(base)
    write_meta_md(info, base, media, file_details(media) if media else {})
    write_transcript_json(base, info)  # no-op unless subtitles are already there

    files, total = folder_contents(folder)
    dlog(f"COMMENTS done: {len(rows)} rows -> {csv_path}")
    send_message({"type": "done", "job": "video_comments", "path": csv_path or folder,
                  "folder": folder, "files": [f["name"] for f in files],
                  "fileCount": len(files), "folderSize": total,
                  "commentCount": len(rows),
                  "note": f"{len(rows)} comments"})
    reveal(csv_path)


# ----------------------------------------------------------------------------
# Channel jobs: download everything / export the numbers
# ----------------------------------------------------------------------------

def start_collection(req, proc_holder, job):
    """Shared prologue: validate, enumerate, decide the folder. Returns
    (ytdlp, ffmpeg, meta, folder, limit) or None (error already sent)."""
    url, kind = resolve_collection(req)
    if not url:
        send_message({"type": "error", "message": kind})
        return None
    ytdlp, ffmpeg, outdir, err = job_setup(req)
    if err:
        send_message({"type": "error", "message": err})
        return None

    send_message({"type": "progress", "stage": "listing", "percent": 0,
                  "speed": "", "eta": ""})
    meta = probe_collection(url, proc_holder, keep_entries=True)
    if proc_holder.get("cancelled"):
        send_message({"type": "error", "message": "Cancelled"})
        return None
    if meta.get("error"):
        send_message({"type": "error", "message": meta["error"]})
        return None
    if not meta.get("count"):
        send_message({"type": "error", "message": "This channel tab has no videos"})
        return None

    folder = collection_folder(outdir, meta)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        send_message({"type": "error", "message": f"Cannot create folder: {e}"})
        return None

    limit = max(0, int(req.get("limit") or 0))
    sort = "popular" if str(req.get("sort") or "") == "popular" else "latest"
    items = playlist_selection(meta, limit, sort)
    planned = min(limit, meta["count"]) if limit else meta["count"]
    dlog(f"{job.upper()} {url} kind={kind} channel={meta['channel']!r} "
         f"count={meta['count']} planned={planned} sort={sort} items={items} "
         f"folder={folder}")
    send_message({"type": "started", "job": job, "kind": kind, "url": url,
                  "channel": meta["channel"], "count": planned,
                  "total": meta["count"], "sort": sort, "outdir": folder})
    return ytdlp, ffmpeg, meta, folder, items, url, sort


def run_channel_download(req, proc_holder):
    """Every video of a channel/playlist, each as its own package folder."""
    setup = start_collection(req, proc_holder, "channel_download")
    if not setup:
        return
    ytdlp, ffmpeg, meta, folder, items, url, sort = setup

    preset = (req.get("format") or "max").strip()
    bundle = req.get("bundle", True)
    if isinstance(bundle, str):
        bundle = bundle.lower() not in ("false", "0", "no", "")

    # Subtitle languages come from the FIRST video: a channel is normally one
    # language, and asking yt-dlp for `en.*`-style patterns here would match the
    # live extractor's machine-translated `en-de-DE` keys and explode.
    langs = []
    if bundle and meta.get("sample"):
        first = f"https://www.youtube.com/watch?v={meta['sample'][0]['id']}"
        data, err = probe_info_raw(first, proc_holder)
        # Behind the bot wall this probe is the FIRST thing to fail, and a
        # silent [] here would cost the whole channel its subtitles.
        if not data and err and needs_cookies({"tail": [err]}):
            data, err = probe_info_raw(first, proc_holder, extra_args=COOKIE_ARGS)
        langs = pick_sub_langs(data, limit=6)
        dlog(f"  channel sub langs: {langs}" + (f" (probe: {err})" if err else ""))
    if proc_holder.get("cancelled"):
        send_message({"type": "error", "message": "Cancelled"})
        return

    outtmpl = os.path.join(folder, BUNDLE_TMPL if bundle else FLAT_TMPL)
    cmd = [
        ytdlp, "--newline", "--windows-filenames", "--no-simulate",
        # --print implies --quiet, which silences "[download] Downloading item
        # N of M" — the ONLY between-videos progress a channel job has.
        "--no-quiet",
        "--progress",
        "--progress-template",
        "download:RYAPROG|%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
        "--print", "after_move:RYAFINAL:%(filepath)s",
        # -i: one dead/private video in the middle must not end the run. It also
        # demotes subtitle errors to warnings, which is what lets the subtitle
        # flags live inline here instead of needing a pass per video.
        "--ignore-errors",
        "--no-write-playlist-metafiles",
        "--no-overwrites",
        # Resumable: a re-run skips what is already on disk, so "top up this
        # channel" costs only the new videos.
        "--download-archive", os.path.join(folder, "_archive.txt"),
        "-N", "8",
        "-o", outtmpl,
        *build_format_args(preset),
    ]
    if items:
        cmd += ["-I", items]
    if bundle:
        cmd += ["--write-info-json", "--write-description", "--write-thumbnail"]
        if langs:
            cmd += ["--write-subs", "--write-auto-subs",
                    "--sub-langs", ",".join(langs),
                    "--sub-format", "srt/vtt/best", "--convert-subs", "srt",
                    "--sleep-subtitles", "0.3"]
    if ffmpeg:
        cmd += ["--ffmpeg-location", os.path.dirname(ffmpeg)]

    st = stream_ytdlp(cmd + [url], proc_holder)
    saved = [p for p in st["final_paths"] if p]
    cancelled = proc_holder.get("cancelled")

    # YouTube's bot wall hits every video of a run at once, so a walled channel
    # job ends with nothing at all. Retry once with the browser session — the
    # download archive makes the retry cost only what is still missing.
    if not saved and needs_cookies(st, cancelled):
        dlog("CHANNEL retry with Chrome cookies")
        send_message({"type": "progress", "stage": "cookies", "percent": 0,
                      "speed": "", "eta": ""})
        st2 = stream_ytdlp(cmd + COOKIE_ARGS + [url], proc_holder)
        st2["tail"] = (st["tail"][-3:] + ["--- retry with Chrome cookies ---"]
                       + st2["tail"][-3:])
        st = st2
        saved = [p for p in st["final_paths"] if p]
        cancelled = proc_holder.get("cancelled")
    if cancelled and not saved:
        send_message({"type": "error", "message": "Cancelled"})
        return
    if st["code"] != 0 and not saved:
        send_message({"type": "error",
                      "message": "\n".join(st["tail"][-6:]) or f"yt-dlp exited {st['code']}"})
        return

    # Local sidecars for the videos this run brought in (earlier runs kept theirs).
    if bundle:
        send_message({"type": "progress", "stage": "extras", "percent": 100,
                      "speed": "", "eta": "", "item": st["item"], "total": st["total"]})
        for p in saved:
            try:
                build_sidecars(p)
            except Exception as e:
                dlog(f"  sidecars failed for {os.path.basename(p)}: {e}")

    # A channel download already has every info.json on disk — turning them into
    # the same videos.csv the CSV job produces is free.
    infos = load_infos(folder, ("*.info.json", "*/*.info.json"))
    prefix = safe_name(meta.get("channel") or meta.get("title") or "channel", 60)
    written = []
    if infos:
        written, videos, _ = write_collection_csvs(folder, meta, infos, {}, prefix)

    files, _ = folder_contents(folder)
    total = folder_size(folder)   # the videos live in per-video subfolders
    names = [f["name"] for f in files]
    names += [os.path.basename(p) for p in written if os.path.basename(p) not in names]
    dlog(f"CHANNEL done: +{len(saved)} videos, {len(infos)} known, {human_size(total)}")
    send_message({
        "type": "done", "job": "channel_download", "path": folder, "folder": folder,
        "files": names,
        "fileCount": len(infos) or len(saved), "folderSize": total,
        "videosSaved": len(saved), "videosKnown": len(infos),
        "partial": bool(cancelled),
        "note": (f"{len(saved)} new video(s)" if saved else "nothing new")
                + (f", {len(infos)} in folder" if infos else ""),
    })
    reveal(saved[0] if saved else folder)


def run_channel_csv(req, proc_holder):
    """Stats for every video (+ optionally every comment) as CSV."""
    setup = start_collection(req, proc_holder, "channel_csv")
    if not setup:
        return
    ytdlp, ffmpeg, meta, folder, items, url, sort = setup

    cap = req.get("commentCap") or "none"
    info_dir = os.path.join(folder, "_info")
    try:
        os.makedirs(info_dir, exist_ok=True)
    except OSError as e:
        send_message({"type": "error", "message": f"Cannot create folder: {e}"})
        return

    totals = {}
    cmd = [
        ytdlp, "--newline", "--windows-filenames",
        "--skip-download", "--write-info-json",
        "--ignore-errors", "--no-write-playlist-metafiles",
        # This pass is pure API traffic; pace it so a 200-video channel doesn't
        # trip YouTube's rate limiter halfway through.
        "--sleep-requests", "0.4",
        "-o", os.path.join(info_dir, "%(id)s.%(ext)s"),
        *comment_args(cap),
    ]
    if items:
        cmd += ["-I", items]

    st = stream_ytdlp(cmd + [url], proc_holder, stage="metadata",
                      on_line=comment_total_watcher(totals))
    cancelled = proc_holder.get("cancelled")
    infos = load_infos(info_dir)

    # Same bot wall as the download job — it fails every video, so an export
    # that collected nothing is worth one retry with the browser session.
    if not infos and needs_cookies(st, cancelled):
        dlog("CSV retry with Chrome cookies")
        send_message({"type": "progress", "stage": "cookies", "percent": 0,
                      "speed": "", "eta": ""})
        st2 = stream_ytdlp(cmd + COOKIE_ARGS + [url], proc_holder,
                           stage="metadata",
                           on_line=comment_total_watcher(totals))
        st2["tail"] = (st["tail"][-3:] + ["--- retry with Chrome cookies ---"]
                       + st2["tail"][-3:])
        st = st2
        cancelled = proc_holder.get("cancelled")
        infos = load_infos(info_dir)

    if not infos:
        send_message({"type": "error",
                      "message": "Cancelled" if cancelled else
                      ("\n".join(st["tail"][-6:]) or "No video metadata collected")})
        return

    send_message({"type": "progress", "stage": "csv", "percent": 100,
                  "speed": "", "eta": "", "item": st["item"], "total": st["total"]})
    # Rank the rows the way the export was asked for, so the `n` column means
    # something: #1 is the most-viewed video of a "top by views" export.
    if sort == "popular":
        infos.sort(key=lambda d: -int(d.get("view_count") or 0))
    prefix = safe_name(meta.get("channel") or meta.get("title") or "channel", 60)
    written, videos, comments = write_collection_csvs(
        folder, meta, infos, totals, prefix)

    files, total = folder_contents(folder)
    dlog(f"CSV done: {len(videos)} videos, {len(comments)} comments -> {folder}")
    send_message({
        "type": "done", "job": "channel_csv", "path": written[0] if written else folder,
        "folder": folder, "files": [os.path.basename(p) for p in written],
        "fileCount": len(files), "folderSize": total,
        "videoCount": len(videos), "commentCount": len(comments),
        "partial": bool(cancelled),
        "note": f"{len(videos)} videos"
                + (f", {len(comments)} comments" if comments else "")
                + (" (stopped early)" if cancelled else ""),
    })
    reveal(written[0] if written else folder)


# ----------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------

def main():
    dlog(f"=== host start v{HOST_VERSION} ===")
    proc_holder = {"proc": None, "cancelled": False}

    def kill_proc():
        p = proc_holder.get("proc")
        if not p or p.poll() is not None:
            return
        # Children run with start_new_session=True (pgid == pid) — signal the
        # whole group so yt-dlp's ffmpeg subprocesses die with it.
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                pass

        def _escalate(proc=p):
            time.sleep(5)
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        threading.Thread(target=_escalate, daemon=True).start()

    def watch_stdin():
        """Watch for an explicit cancel. On EOF (port closed) we deliberately
        do NOT kill yt-dlp — the download finishes and the file is saved even
        if the popup/service-worker went away.

        Keeps looping after a cancel (instead of returning): the fallback chain
        can spawn a NEW child (cookie retry / RU-proxy download) after the first
        cancel, and re-reading lets a second cancel click reach that child too.
        Once cancelled, every subsequent read just re-kills whatever is live."""
        while True:
            msg = read_message()
            if msg is None:  # port closed — let the download finish on its own
                return
            if msg.get("action") == "cancel":
                proc_holder["cancelled"] = True
                kill_proc()
                # keep looping — a retry attempt may register a new proc to kill

    # First message determines the job.
    first = read_message()
    if first is None:
        return

    action = first.get("action")
    dlog(f"action={action}")
    if action == "ping":
        # Trim here, in the one-shot ping host: a concurrent download host's
        # trail can't be truncated under it (flock guards the rest).
        _trim_log()
        ytdlp = find_tool("yt-dlp")
        ver = None
        if ytdlp:
            try:
                ver = subprocess.run([ytdlp, "--version"], capture_output=True,
                                     text=True, timeout=10).stdout.strip()
            except Exception:
                ver = None
        send_message({
            "type": "pong",
            "ytdlp": ver,
            "ffmpeg": bool(find_tool("ffmpeg")),
            "outdir": default_outdir(),
            "host_version": HOST_VERSION,
        })
        return

    if action == "formats":
        url, site = resolve_target(first)
        dlog(f"formats url={url} site={site}")
        if not url:
            send_message({"type": "formats", "error": site})
            return
        send_message({"type": "formats", "site": site, **probe_formats(url)})
        return

    if action == "channel_info":
        url, kind = resolve_collection(first)
        dlog(f"channel_info url={url} kind={kind}")
        if not url:
            send_message({"type": "channel", "error": kind})
            return
        send_message({"type": "channel", "kind": kind, "url": url,
                      **probe_collection(url)})
        return

    # Long-running jobs. All of them stream progress and must stay cancellable,
    # so they share the stdin watcher (cancel / port disconnect).
    JOBS = {
        "download": run_download,
        "video_subs": run_video_subs,
        "video_comments": run_video_comments,
        "channel_download": run_channel_download,
        "channel_csv": run_channel_csv,
    }
    if action in JOBS:
        t = threading.Thread(target=watch_stdin, daemon=True)
        t.start()
        JOBS[action](first, proc_holder)
        return

    send_message({"type": "error", "message": f"Unknown action: {action!r}"})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never crash silently — report to the extension
        dlog(f"CRASH: {e}")
        try:
            send_message({"type": "error", "message": f"host crash: {e}"})
        except Exception:
            pass
    finally:
        # Hard-exit. The watch_stdin daemon thread may be blocked in
        # stdin.read() at interpreter shutdown, which triggers a fatal
        # "_enter_buffered_busy ... at interpreter shutdown" SIGABRT (macOS
        # then shows "Python quit unexpectedly"). os._exit skips finalization
        # entirely. All messages are already flushed by send_message().
        try:
            _stdout.flush()
        except Exception:
            pass
        os._exit(0)
