#!/opt/homebrew/opt/python@3.11/libexec/bin/python3
"""
Download a Thinkific lesson into its own local project folder.

Pipeline:
1. Resolve the lesson URL or direct media URL.
2. Download the video into a dedicated project folder.
3. Run the existing YTAI transcription pipeline on the downloaded file.
4. Extract screenshots on scene changes into a sibling screenshots folder.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)

DEFAULT_TRANSCRIBE_SCRIPT = Path(
    "/Users/romansergeev/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py"
)
DEFAULT_TRANSCRIBE_PYTHON = Path(
    "/Users/romansergeev/YTAI/environment/.venv_transcribe/bin/python3"
)

SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR / "logs"
PROJECT_MANIFEST_NAME = "project_manifest.json"
SCREENSHOTS_MANIFEST_NAME = "screenshots_manifest.json"
SCREENSHOT_DESCRIPTIONS_MANIFEST_NAME = "screenshots_descriptions.json"

M3U8_REGEX = re.compile(r"https://[^\s\"'<>\\]+\.m3u8[^\s\"'<>\\]*", re.IGNORECASE)
MP4_REGEX = re.compile(r"https://[^\s\"'<>\\]+\.mp4[^\s\"'<>\\]*", re.IGNORECASE)
MUX_REGEX = re.compile(r"https://stream\.mux\.com/[A-Za-z0-9_\-]+\.m3u8[^\s\"'<>\\]*")
SHOWINFO_PTS_REGEX = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")

WISTIA_ID_REGEXES = [
    re.compile(r"wistia_async_([a-z0-9]{8,})", re.IGNORECASE),
    re.compile(r"hashedId[\"']?\s*[:=]\s*[\"']([a-z0-9]{8,})[\"']", re.IGNORECASE),
    re.compile(r"wistiaId[\"']?\s*[:=]\s*[\"']([a-z0-9]{8,})[\"']", re.IGNORECASE),
    re.compile(r"embed/iframe/([a-z0-9]{8,})", re.IGNORECASE),
]
TITLE_REGEXES = [
    re.compile(r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)", re.IGNORECASE),
    re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL),
]


@dataclass
class DownloadTarget:
    page_url: str
    media_url: str
    title: str


@dataclass
class ProjectLayout:
    project_dir: Path
    video_file: Path
    video_info_file: Path
    transcription_dir: Path
    transcript_xlsx: Path
    transcript_json: Path
    transcript_srt: Path
    captions_srt: Path
    screenshots_dir: Path
    screenshots_manifest: Path
    screenshot_descriptions_manifest: Path
    project_manifest: Path


@dataclass
class RunLogger:
    path: Path

    def log(self, message: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(message.rstrip("\n") + "\n")

    def section(self, title: str) -> None:
        self.log("")
        self.log(f"=== {title} ===")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download a Thinkific lesson into its own project folder, then optionally "
            "run transcription and scene-change screenshots."
        )
    )
    parser.add_argument("source", help="Thinkific lesson URL or direct media URL.")
    parser.add_argument(
        "--output-dir",
        default="downloads",
        help="Root directory where per-video project folders will be created. Default: %(default)s",
    )
    parser.add_argument("--title", help="Override the lesson title used for the project and video file names.")
    parser.add_argument("--referer", help="Override the Referer header. Defaults to the source URL.")
    parser.add_argument(
        "--cookie-header",
        help="Raw Cookie header, for example: 'sessionid=...; _thinkific_session=...'",
    )
    parser.add_argument(
        "--cookie-file",
        help="Path to a Netscape cookies.txt file to convert into a Cookie header.",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "ffmpeg", "yt-dlp"),
        default="auto",
        help="Download backend. Default: %(default)s",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Only download the video and metadata, without transcription or screenshots.",
    )
    parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help="Skip transcription after download.",
    )
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Skip scene-change screenshots after download.",
    )
    parser.add_argument(
        "--no-descriptions",
        action="store_true",
        help="Skip AI-generated screenshot descriptions after screenshot extraction.",
    )
    parser.add_argument(
        "--vision-model",
        default=None,
        help="Ollama vision model for screenshot descriptions. Default: minicpm-v",
    )
    parser.add_argument(
        "-n",
        "--speakers",
        type=int,
        default=None,
        help="Number of speakers for the transcription pipeline. Omit to auto-detect.",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="large-v3",
        help="Whisper model passed to the transcription pipeline. Default: %(default)s",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional Whisper language code passed to the transcription pipeline.",
    )
    parser.add_argument(
        "--transcribe-python",
        help=f"Python executable for transcription. Default: {DEFAULT_TRANSCRIBE_PYTHON}",
    )
    parser.add_argument(
        "--transcribe-script",
        help=f"Path to transcribe_project.py. Default: {DEFAULT_TRANSCRIBE_SCRIPT}",
    )
    parser.add_argument(
        "--screenshot-mode",
        choices=("interval", "scene"),
        default="interval",
        help="Screenshot extraction mode. 'interval' captures every N seconds, 'scene' uses scene detection. Default: %(default)s",
    )
    parser.add_argument(
        "--screenshot-interval",
        type=float,
        default=2.0,
        help="Seconds between frames in interval mode. Default: %(default)s",
    )
    parser.add_argument(
        "--scene-threshold",
        type=float,
        default=0.18,
        help="ffmpeg scene score threshold (scene mode only). Higher = fewer screenshots. Default: %(default)s",
    )
    parser.add_argument(
        "--scene-max-width",
        type=int,
        default=1600,
        help="Max screenshot width in pixels. Use 0 to keep original width. Default: %(default)s",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the media URL and show the project layout, but do not start downloading.",
    )
    args = parser.parse_args()

    if args.download_only:
        args.no_transcribe = True
        args.no_screenshots = True
        args.no_descriptions = True

    if args.speakers is not None and args.speakers < 1:
        parser.error("--speakers must be a positive integer")
    if not 0.0 < args.scene_threshold < 1.0:
        parser.error("--scene-threshold must be between 0 and 1")
    if args.scene_max_width < 0:
        parser.error("--scene-max-width must be 0 or greater")

    return args


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def create_run_logger(script_name: str) -> RunLogger:
    return RunLogger(LOGS_DIR / f"{script_name}_{now_stamp()}.log")


def log_and_print(logger: RunLogger | None, message: str) -> None:
    print(message)
    if logger:
        logger.log(message)


def format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def run_command(command: list[str], logger: RunLogger | None, print_output: bool = True) -> str:
    if logger:
        logger.log(f"$ {format_command(command)}")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    combined: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        combined.append(line)
        clean = line.rstrip("\n")
        if logger:
            logger.log(clean)
        if print_output:
            print(line, end="")
    return_code = process.wait()
    output_text = "".join(combined)
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command, output=output_text)
    return output_text


def load_cookie_header(cookie_header: str | None, cookie_file: str | None) -> str | None:
    if cookie_header:
        return cookie_header.strip()

    if not cookie_file:
        return None

    cookies: list[str] = []
    with open(cookie_file, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 7:
                continue
            name = parts[5].strip()
            value = parts[6].strip()
            if name:
                cookies.append(f"{name}={value}")

    if not cookies:
        raise ValueError(f"Could not parse cookies from {cookie_file}")
    return "; ".join(cookies)


def build_headers(referer: str | None, cookie_header: str | None) -> dict[str, str]:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if referer:
        headers["Referer"] = referer
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def fetch_text(url: str, headers: dict[str, str]) -> str:
    request = Request(url, headers=headers)
    try:
        with urlopen(request) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while requesting {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error while requesting {url}: {exc.reason}") from exc


def fetch_json(url: str, headers: dict[str, str]) -> dict:
    content = fetch_text(url, headers)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Expected JSON from {url}, but parsing failed") from exc


def strip_known_video_suffix(name: str) -> str:
    return re.sub(r"\.(mp4|mov|m4v|mkv|avi)$", "", name, flags=re.IGNORECASE).strip()


def title_from_page_url(page_url: str) -> str:
    segment = Path(urlparse(page_url).path).name or "thinkific_video"
    segment = re.sub(r"^\d+-", "", segment)
    segment = segment.replace("-", " ").replace("_", " ")
    segment = re.sub(r"\s+", " ", segment).strip()
    return segment or "thinkific_video"


def looks_like_machine_name(value: str) -> bool:
    normalized = strip_known_video_suffix(value)
    return bool(re.fullmatch(r"[a-z0-9]{10,}", normalized))


def guess_title(html: str, fallback: str) -> str:
    for pattern in TITLE_REGEXES:
        match = pattern.search(html)
        if match:
            value = unescape(re.sub(r"\s+", " ", match.group(1))).strip()
            if value:
                return value
    return fallback


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:180] or "thinkific_video"


def unique_preserving_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def extract_wistia_ids(text: str) -> list[str]:
    ids: list[str] = []
    for pattern in WISTIA_ID_REGEXES:
        ids.extend(match.group(1) for match in pattern.finditer(text))
    return unique_preserving_order(ids)


def collect_media_candidates(text: str) -> list[str]:
    candidates = M3U8_REGEX.findall(text)
    candidates.extend(MP4_REGEX.findall(text))
    candidates.extend(MUX_REGEX.findall(text))
    return unique_preserving_order(candidates)


def recursive_find_media_urls(payload) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            found.extend(recursive_find_media_urls(value))
    elif isinstance(payload, list):
        for value in payload:
            found.extend(recursive_find_media_urls(value))
    elif isinstance(payload, str):
        found.extend(collect_media_candidates(payload))
    return unique_preserving_order(found)


def extract_wistia_id_from_source(source: str) -> str | None:
    parsed = urlparse(source)
    query_id = parse_qs(parsed.query).get("wvideo", [None])[0]
    if query_id:
        return query_id

    patterns = [
        re.compile(r"(?:wistia\.com/medias|fast\.wistia\.(?:com|net)/embed/medias)/([a-z0-9]{8,})", re.IGNORECASE),
        re.compile(r"wvideo=([a-z0-9]{8,})", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(source)
        if match:
            return match.group(1)
    return None


def select_best_wistia_asset(payload: dict, wistia_id: str) -> tuple[str, str]:
    media = payload.get("media") or {}
    title = strip_known_video_suffix(media.get("name") or media.get("seoDescription") or wistia_id)
    assets = media.get("assets") or []

    mp4_assets = [
        asset
        for asset in assets
        if asset.get("public")
        and asset.get("status") == 2
        and asset.get("container") == "mp4"
        and asset.get("url")
    ]
    if mp4_assets:
        best_asset = max(
            mp4_assets,
            key=lambda asset: (
                int(asset.get("height") or 0),
                int(asset.get("bitrate") or 0),
                int(asset.get("size") or 0),
            ),
        )
        return best_asset["url"], title

    if media.get("hls_enabled"):
        return f"https://fast.wistia.net/embed/medias/{wistia_id}.m3u8", title

    matches = recursive_find_media_urls(payload)
    if matches:
        return matches[0], title

    raise RuntimeError(f"Wistia media {wistia_id} does not expose a downloadable mp4 or HLS manifest.")


def resolve_wistia_media_url(wistia_id: str, headers: dict[str, str]) -> str | None:
    json_urls = [
        f"https://fast.wistia.com/embed/medias/{wistia_id}.json",
        f"https://fast.wistia.net/embed/medias/{wistia_id}.json",
    ]

    for json_url in json_urls:
        try:
            payload = fetch_json(json_url, headers)
        except RuntimeError:
            continue
        matches = recursive_find_media_urls(payload)
        if matches:
            return matches[0]

    return f"https://fast.wistia.net/embed/medias/{wistia_id}.m3u8"


def resolve_wistia_target(
    wistia_id: str,
    page_url: str,
    headers: dict[str, str],
    title_override: str | None,
) -> DownloadTarget:
    json_urls = [
        f"https://fast.wistia.com/embed/medias/{wistia_id}.json",
        f"https://fast.wistia.net/embed/medias/{wistia_id}.json",
    ]
    for json_url in json_urls:
        try:
            payload = fetch_json(json_url, headers)
        except RuntimeError:
            continue
        media_url, title = select_best_wistia_asset(payload, wistia_id)
        if looks_like_machine_name(title):
            title = title_from_page_url(page_url)
        return DownloadTarget(page_url=page_url, media_url=media_url, title=title_override or title)

    media_url = resolve_wistia_media_url(wistia_id, headers)
    if media_url:
        title = title_override or title_from_page_url(page_url)
        return DownloadTarget(page_url=page_url, media_url=media_url, title=title)

    raise RuntimeError(f"Could not resolve Wistia media for id {wistia_id}")


def source_looks_like_direct_media(source: str) -> bool:
    lowered = source.lower()
    return ".m3u8" in lowered or ".mp4" in lowered


def extract_target(source: str, headers: dict[str, str], title_override: str | None) -> DownloadTarget:
    if source_looks_like_direct_media(source):
        title = title_override or Path(urlparse(source).path).stem or "thinkific_video"
        return DownloadTarget(page_url=source, media_url=source, title=title)

    wistia_id = extract_wistia_id_from_source(source)
    if wistia_id:
        return resolve_wistia_target(wistia_id, source, headers, title_override)

    html = fetch_text(source, headers)
    title = title_override or guess_title(html, Path(urlparse(source).path).name or "thinkific_video")

    candidates = collect_media_candidates(html)
    if candidates:
        return DownloadTarget(page_url=source, media_url=candidates[0], title=title)

    wistia_ids = extract_wistia_ids(html)
    for wistia_id in wistia_ids:
        media_url = resolve_wistia_media_url(wistia_id, headers)
        if media_url:
            return DownloadTarget(page_url=source, media_url=media_url, title=title)

    raise RuntimeError(
        "Could not find a downloadable media URL on the page. "
        "Try supplying a fresh Cookie header or pass the direct .m3u8 URL."
    )


def choose_engine(requested: str) -> str:
    if requested == "auto":
        return "yt-dlp" if shutil.which("yt-dlp") else "ffmpeg"
    if requested == "yt-dlp" and not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp is not installed or not found in PATH.")
    if requested == "ffmpeg" and not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not found in PATH.")
    return requested


def media_extension(media_url: str) -> str:
    parsed = urlparse(media_url)
    if ".mp4" in parsed.path.lower():
        return ".mp4"
    return ".mp4"


def find_existing_project_dir(parent: Path, name: str) -> Path | None:
    """Find an existing project directory by name (base or with _02, _03 suffix)."""
    candidate = parent / name
    if candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = parent / f"{name}_{index:02d}"
        if candidate.exists():
            return candidate
    return None


def build_project_layout_from_dir(project_dir: Path, stem: str) -> ProjectLayout:
    """Build a ProjectLayout from an existing project directory (for resume mode)."""
    video_file = project_dir / f"{stem}.mp4"
    transcription_dir = project_dir / f"{video_file.stem}_transcription"
    return ProjectLayout(
        project_dir=project_dir,
        video_file=video_file,
        video_info_file=project_dir / f"{video_file.stem}.info.json",
        transcription_dir=transcription_dir,
        transcript_xlsx=project_dir / f"{video_file.stem}_transcript.xlsx",
        transcript_json=transcription_dir / f"{video_file.stem}_transcript.json",
        transcript_srt=transcription_dir / f"{video_file.stem}_transcript.srt",
        captions_srt=transcription_dir / f"{video_file.stem}_1_Ingest_captions.srt",
        screenshots_dir=project_dir / "screenshots",
        screenshots_manifest=project_dir / SCREENSHOTS_MANIFEST_NAME,
        screenshot_descriptions_manifest=project_dir / SCREENSHOT_DESCRIPTIONS_MANIFEST_NAME,
        project_manifest=project_dir / PROJECT_MANIFEST_NAME,
    )


def ensure_unique_directory(parent: Path, name: str) -> Path:
    candidate = parent / name
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = parent / f"{name}_{index:02d}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate a unique project directory in {parent}")


def build_project_layout(output_root: Path, target: DownloadTarget) -> ProjectLayout:
    stem = sanitize_filename(strip_known_video_suffix(target.title))
    project_dir = ensure_unique_directory(output_root, stem)
    video_file = project_dir / f"{stem}{media_extension(target.media_url)}"
    transcription_dir = project_dir / f"{video_file.stem}_transcription"
    return ProjectLayout(
        project_dir=project_dir,
        video_file=video_file,
        video_info_file=project_dir / f"{video_file.stem}.info.json",
        transcription_dir=transcription_dir,
        transcript_xlsx=project_dir / f"{video_file.stem}_transcript.xlsx",
        transcript_json=transcription_dir / f"{video_file.stem}_transcript.json",
        transcript_srt=transcription_dir / f"{video_file.stem}_transcript.srt",
        captions_srt=transcription_dir / f"{video_file.stem}_1_Ingest_captions.srt",
        screenshots_dir=project_dir / "screenshots",
        screenshots_manifest=project_dir / SCREENSHOTS_MANIFEST_NAME,
        screenshot_descriptions_manifest=project_dir / SCREENSHOT_DESCRIPTIONS_MANIFEST_NAME,
        project_manifest=project_dir / PROJECT_MANIFEST_NAME,
    )


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_video_info(layout: ProjectLayout, target: DownloadTarget, engine: str) -> None:
    payload = {
        "created_at": utc_now_iso(),
        "page_url": target.page_url,
        "media_url": target.media_url,
        "title": target.title,
        "engine": engine,
        "video_file": str(layout.video_file),
    }
    write_json(layout.video_info_file, payload)


def ffmpeg_headers_arg(headers: dict[str, str]) -> str:
    ordered_keys = ("User-Agent", "Referer", "Cookie")
    header_lines = [f"{key}: {headers[key]}" for key in ordered_keys if headers.get(key)]
    return "\r\n".join(header_lines) + ("\r\n" if header_lines else "")


def _subprocess_io_kwargs() -> dict:
    """Return subprocess kwargs to avoid TTY writes in background mode."""
    if sys.stderr.isatty():
        return {}
    # start_new_session detaches from controlling terminal completely,
    # preventing SIGTTOU from subprocess TTY title escape sequences
    return {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "start_new_session": True}


def run_ffmpeg(media_url: str, output_file: Path, headers: dict[str, str]) -> None:
    is_interactive = sys.stderr.isatty()
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "warning",
    ]
    if is_interactive:
        command.append("-stats")
    else:
        command.extend(["-nostats", "-loglevel", "error"])
    header_blob = ffmpeg_headers_arg(headers)
    if header_blob:
        command.extend(["-headers", header_blob])
    command.extend(
        [
            "-i",
            media_url,
            "-map",
            "0:v:0?",
            "-map",
            "0:a?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_file),
        ]
    )
    subprocess.run(command, check=True, timeout=300, **_subprocess_io_kwargs())


def run_ytdlp(media_url: str, output_file: Path, headers: dict[str, str]) -> None:
    command = [
        "yt-dlp",
        "--no-part",
        "--output",
        str(output_file),
    ]
    if headers.get("Referer"):
        command.extend(["--referer", headers["Referer"]])
    if headers.get("User-Agent"):
        command.extend(["--add-header", f"User-Agent:{headers['User-Agent']}"])
    if headers.get("Cookie"):
        command.extend(["--add-header", f"Cookie:{headers['Cookie']}"])
    command.append(media_url)
    subprocess.run(command, check=True, **_subprocess_io_kwargs())


def resolve_transcribe_python(path_override: str | None) -> Path:
    if path_override:
        path = Path(path_override).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"Transcription python not found: {path}")
        return path
    if DEFAULT_TRANSCRIBE_PYTHON.exists():
        return DEFAULT_TRANSCRIBE_PYTHON
    current = Path(sys.executable).resolve()
    if current.exists():
        return current
    raise RuntimeError("Could not locate a Python executable for transcription.")


def resolve_transcribe_script(path_override: str | None) -> Path:
    if path_override:
        path = Path(path_override).expanduser().resolve()
        if not path.exists():
            raise RuntimeError(f"Transcription script not found: {path}")
        return path
    if DEFAULT_TRANSCRIBE_SCRIPT.exists():
        return DEFAULT_TRANSCRIBE_SCRIPT
    raise RuntimeError(f"Default transcription script not found: {DEFAULT_TRANSCRIBE_SCRIPT}")


def build_transcribe_command(layout: ProjectLayout, args: argparse.Namespace) -> list[str]:
    python_path = resolve_transcribe_python(args.transcribe_python)
    script_path = resolve_transcribe_script(args.transcribe_script)
    command = [
        str(python_path),
        str(script_path),
        "--project",
        str(layout.video_file),
        "-y",
        "-m",
        args.model,
    ]
    if args.speakers is not None:
        command.extend(["-n", str(args.speakers)])
    if args.language:
        command.extend(["--language", args.language])
    return command


def run_transcription(command: list[str], log_path: Path | None = None) -> None:
    """Run transcription subprocess, redirecting output to log file when not interactive."""
    if sys.stderr.isatty():
        # Interactive — show live output
        subprocess.run(command, check=True)
    elif log_path:
        # Background — redirect to log + detach from TTY
        with open(log_path, "a", encoding="utf-8") as log_fh:
            subprocess.run(command, check=True, stdout=log_fh, stderr=log_fh,
                           start_new_session=True)
    else:
        # Background, no log — suppress output + detach from TTY
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True)


def build_scene_filter(threshold: float, max_width: int) -> str:
    filters = [f"select='gt(scene,{threshold:.4f})'", "showinfo"]
    if max_width > 0:
        filters.append(f"scale='if(gt(iw,{max_width}),{max_width},iw)':-1")
    return ",".join(filters)


def format_timestamp_for_name(seconds: float) -> str:
    total_millis = int(round(seconds * 1000))
    total_seconds, millis = divmod(total_millis, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}-{minutes:02d}-{secs:02d}.{millis:03d}"


def parse_showinfo_timestamps(stderr_text: str) -> list[float]:
    return [float(match.group(1)) for match in SHOWINFO_PTS_REGEX.finditer(stderr_text)]


def extract_screenshots(
    video_file: Path,
    screenshots_dir: Path,
    manifest_path: Path,
    threshold: float,
    max_width: int,
    mode: str = "scene",
    interval: float = 2.0,
) -> dict:
    """Extract screenshots from video. mode='scene' for scene detection, 'interval' for fixed interval."""
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = screenshots_dir / "frame_%05d.jpg"

    if mode == "interval":
        vf_parts = [f"fps=1/{interval}", "showinfo"]
        if max_width > 0:
            vf_parts.append(f"scale='if(gt(iw,{max_width}),{max_width},iw)':-1")
        vf = ",".join(vf_parts)
    else:
        output_pattern = screenshots_dir / "scene_%05d.jpg"
        vf = build_scene_filter(threshold, max_width)

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(video_file),
        "-vf",
        vf,
        "-q:v",
        "2",
        "-vsync",
        "vfr",
        str(output_pattern),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)

    timestamps = parse_showinfo_timestamps(result.stderr)
    prefix = "frame_" if mode == "interval" else "scene_"
    raw_files = sorted(screenshots_dir.glob(f"{prefix}*.jpg"))
    screenshots: list[dict] = []

    for index, raw_file in enumerate(raw_files, start=1):
        timestamp = timestamps[index - 1] if index - 1 < len(timestamps) else None
        suffix = f"_t{format_timestamp_for_name(timestamp)}" if timestamp is not None else ""
        final_name = f"frame_{index:04d}{suffix}.jpg"
        final_path = screenshots_dir / final_name
        if raw_file != final_path:
            raw_file.rename(final_path)
        screenshots.append(
            {
                "index": index,
                "file": final_name,
                "path": str(final_path),
                "timestamp_seconds": timestamp,
            }
        )

    payload = {
        "created_at": utc_now_iso(),
        "source_video": str(video_file),
        "extraction_mode": mode,
        "interval_seconds": interval if mode == "interval" else None,
        "scene_threshold": threshold if mode == "scene" else None,
        "scene_max_width": max_width,
        "count": len(screenshots),
        "screenshots": screenshots,
    }
    write_json(manifest_path, payload)
    return payload


def build_project_manifest(
    layout: ProjectLayout,
    target: DownloadTarget,
    engine: str,
    args: argparse.Namespace,
    transcribe_command: list[str] | None,
    screenshots_result: dict | None,
    transcription_completed: bool,
    descriptions_completed: bool,
    errors: list[str],
) -> dict:
    no_descriptions = getattr(args, "no_descriptions", True)
    no_screenshots = getattr(args, "no_screenshots", False)
    return {
        "created_at": utc_now_iso(),
        "source": {
            "page_url": target.page_url,
            "media_url": target.media_url,
            "title": target.title,
        },
        "project": {
            "project_dir": str(layout.project_dir),
            "video_file": str(layout.video_file),
            "video_info_file": str(layout.video_info_file),
        },
        "download": {
            "engine": engine,
            "completed": layout.video_file.exists(),
        },
        "transcription": {
            "enabled": not args.no_transcribe,
            "completed": transcription_completed,
            "command": transcribe_command,
            "transcript_xlsx": str(layout.transcript_xlsx),
            "transcription_dir": str(layout.transcription_dir),
            "transcript_json": str(layout.transcript_json),
            "transcript_srt": str(layout.transcript_srt),
            "captions_srt": str(layout.captions_srt),
        },
        "screenshots": {
            "enabled": not no_screenshots,
            "dir": str(layout.screenshots_dir),
            "manifest": str(layout.screenshots_manifest),
            "count": (screenshots_result or {}).get("count", 0),
        },
        "screenshot_descriptions": {
            "enabled": not no_descriptions and not no_screenshots,
            "completed": descriptions_completed,
            "manifest": str(layout.screenshot_descriptions_manifest),
        },
        "settings": {
            "screenshot_mode": getattr(args, "screenshot_mode", "interval"),
            "screenshot_interval": getattr(args, "screenshot_interval", 2.0),
            "scene_threshold": args.scene_threshold,
            "scene_max_width": args.scene_max_width,
            "whisper_model": args.model,
            "speakers": args.speakers,
            "language": args.language,
        },
        "errors": errors,
    }


def format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def main() -> int:
    args = parse_args()
    logger = create_run_logger("download_thinkific")

    try:
        cookie_header = load_cookie_header(args.cookie_header, args.cookie_file)
        referer = args.referer or (None if source_looks_like_direct_media(args.source) else args.source)
        headers = build_headers(referer, cookie_header)
        engine = choose_engine(args.engine)
        target = extract_target(args.source, headers, args.title)
        output_root = Path(args.output_dir).expanduser().resolve()
        layout = build_project_layout(output_root, target)
        transcribe_command = None if args.no_transcribe else build_transcribe_command(layout, args)
    except Exception as exc:
        log_and_print(logger, f"Error: {exc}")
        return 1

    logger.section("Configuration")
    log_and_print(logger, f"Source page      : {target.page_url}")
    log_and_print(logger, f"Media URL        : {target.media_url}")
    log_and_print(logger, f"Download engine  : {engine}")
    log_and_print(logger, f"Project dir      : {layout.project_dir}")
    log_and_print(logger, f"Video file       : {layout.video_file}")
    if not args.no_transcribe:
        log_and_print(logger, f"Transcript xlsx  : {layout.transcript_xlsx}")
        log_and_print(logger, f"Transcript dir   : {layout.transcription_dir}")
        log_and_print(logger, f"Transcribe cmd   : {format_command(transcribe_command)}")
    if not args.no_screenshots:
        log_and_print(logger, f"Screenshots dir  : {layout.screenshots_dir}")
        log_and_print(logger, f"Scene threshold  : {args.scene_threshold}")
    log_and_print(logger, f"Log file         : {logger.path}")

    if args.dry_run:
        return 0

    layout.project_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    screenshots_result: dict | None = None
    transcription_completed = False

    logger.section("Download")
    try:
        if engine == "yt-dlp":
            run_ytdlp(target.media_url, layout.video_file, headers)
        else:
            run_ffmpeg(target.media_url, layout.video_file, headers)
        write_video_info(layout, target, engine)
        logger.log(f"Download complete: {layout.video_file}")
    except subprocess.CalledProcessError as exc:
        errors.append(f"Download failed with exit code {exc.returncode}")
    except Exception as exc:
        errors.append(f"Download failed: {exc}")

    if not errors and not args.no_screenshots:
        logger.section("Screenshots")
        try:
            log_and_print(logger, "\nExtracting screenshots...")
            screenshot_mode = getattr(args, "screenshot_mode", "interval")
            screenshot_interval = getattr(args, "screenshot_interval", 2.0)
            screenshots_result = extract_screenshots(
                layout.video_file,
                layout.screenshots_dir,
                layout.screenshots_manifest,
                args.scene_threshold,
                args.scene_max_width,
                mode=screenshot_mode,
                interval=screenshot_interval,
            )
            log_and_print(logger, f"Screenshots saved: {screenshots_result['count']}")
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "").strip().splitlines()[-8:]
            tail_text = " | ".join(stderr_tail) if stderr_tail else f"exit code {exc.returncode}"
            errors.append(f"Screenshot extraction failed: {tail_text}")
        except Exception as exc:
            errors.append(f"Screenshot extraction failed: {exc}")

    descriptions_completed = False
    if not errors and not args.no_screenshots and not args.no_descriptions and screenshots_result:
        logger.section("Screenshot Descriptions")
        try:
            log_and_print(logger, "\nDescribing screenshots with vision model...")
            import describe_screenshots as desc

            vision_model = args.vision_model or desc.DEFAULT_VISION_MODEL
            if desc.check_ollama_available(vision_model):
                desc_result = desc.describe_all_screenshots(
                    layout.screenshots_manifest,
                    layout.screenshot_descriptions_manifest,
                    model=vision_model,
                    logger=logger,
                )
                descriptions_completed = True
                log_and_print(logger, f"Descriptions saved: {desc_result['count']}")
                if desc_result["errors_count"]:
                    log_and_print(logger, f"Description errors: {desc_result['errors_count']}")
            else:
                errors.append("Screenshot descriptions skipped: Ollama not available")
        except Exception as exc:
            errors.append(f"Screenshot descriptions failed: {exc}")

    if not errors and not args.no_transcribe and transcribe_command:
        logger.section("Transcription")
        try:
            log_and_print(logger, "\nRunning transcription pipeline...")
            run_transcription(transcribe_command, log_path=logger.path if logger else None)
            transcription_completed = True
            logger.log("Transcription complete")
        except subprocess.CalledProcessError as exc:
            errors.append(f"Transcription failed with exit code {exc.returncode}")
        except Exception as exc:
            errors.append(f"Transcription failed: {exc}")

    manifest = build_project_manifest(
        layout=layout,
        target=target,
        engine=engine,
        args=args,
        transcribe_command=transcribe_command,
        screenshots_result=screenshots_result,
        transcription_completed=transcription_completed,
        descriptions_completed=descriptions_completed,
        errors=errors,
    )
    write_json(layout.project_manifest, manifest)

    logger.section("Result")
    if errors:
        for error in errors:
            log_and_print(logger, f"Error: {error}")
        log_and_print(logger, f"Project manifest: {layout.project_manifest}")
        return 1

    log_and_print(logger, "\nPipeline complete.")
    log_and_print(logger, f"Project manifest : {layout.project_manifest}")
    log_and_print(logger, f"Log file         : {logger.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
