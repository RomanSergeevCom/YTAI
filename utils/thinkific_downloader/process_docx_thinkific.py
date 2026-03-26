#!/opt/homebrew/opt/python@3.11/libexec/bin/python3
"""
Batch-process a DOCX workbook of Thinkific lessons.

For each lesson block in the document, the script:
1. Detects the main Thinkific lesson link.
2. Creates a local project folder via the same layout as download_thinkific.py.
3. Downloads the lesson video.
4. Saves the text, tables, embedded images, and extra links from the DOCX block.
5. Attempts to download linked resources into the same project folder.
6. Optionally runs transcription and scene-change screenshots.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import download_thinkific as dl


DOC_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
HYPERLINK_FIELD_RE = re.compile(r'HYPERLINK\s+"([^"]+)"', re.IGNORECASE)
DOC_MEDIA_PREFIX = "word/"
THINKIFIC_HOST_TOKEN = "thinkific.com"


@dataclass
class DocElement:
    kind: str
    text: str = ""
    links: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)


@dataclass
class LessonBlock:
    lesson_index: int
    title: str
    lesson_url: str
    elements: list[DocElement] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse a DOCX workbook of Thinkific lessons and build per-lesson local projects "
            "with video, document notes, images, extra downloads, transcription, and screenshots."
        )
    )
    parser.add_argument("docx_path", nargs="?", default=None, help="Path to the DOCX workbook (optional if --from-manifest is used).")
    parser.add_argument(
        "--from-manifest",
        help="Resume from a batch manifest JSON (skips DOCX parsing, uses saved URLs).",
    )
    parser.add_argument(
        "--output-dir",
        default="downloads",
        help="Root directory where lesson project folders will be created. Default: %(default)s",
    )
    parser.add_argument(
        "--cookie-header",
        help="Raw Cookie header for Thinkific pages that require authentication.",
    )
    parser.add_argument(
        "--cookie-file",
        help="Path to a Netscape cookies.txt file to convert into a Cookie header.",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "ffmpeg", "yt-dlp"),
        default="auto",
        help="Video download backend. Default: %(default)s",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Only download the main lesson video. Skip transcription, screenshots, and extra links.",
    )
    parser.add_argument(
        "--no-transcribe",
        action="store_true",
        help="Skip transcription for lesson videos.",
    )
    parser.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Skip scene-change screenshots for lesson videos.",
    )
    parser.add_argument(
        "--no-extra-links",
        action="store_true",
        help="Skip downloads of extra links found below each lesson.",
    )
    parser.add_argument(
        "--no-descriptions",
        action="store_true",
        help="Skip AI-generated screenshot descriptions.",
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
        help="Whisper model for transcription. Default: %(default)s",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional language code for transcription.",
    )
    parser.add_argument(
        "--transcribe-python",
        help=f"Python executable for transcription. Default: {dl.DEFAULT_TRANSCRIBE_PYTHON}",
    )
    parser.add_argument(
        "--transcribe-script",
        help=f"Path to transcribe_project.py. Default: {dl.DEFAULT_TRANSCRIBE_SCRIPT}",
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
        help="ffmpeg scene threshold (scene mode only). Default: %(default)s",
    )
    parser.add_argument(
        "--scene-max-width",
        type=int,
        default=1600,
        help="Max screenshot width in pixels. Use 0 to keep original width. Default: %(default)s",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N lessons from the document.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip lessons whose project_manifest.json already exists. Default: True.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Force re-processing of all lessons even if already completed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse the DOCX and show what would be created, without downloading.",
    )
    args = parser.parse_args()

    if args.no_resume:
        args.resume = False

    if args.download_only:
        args.no_transcribe = True
        args.no_screenshots = True
        args.no_extra_links = True
        args.no_descriptions = True

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer")
    if args.speakers is not None and args.speakers < 1:
        parser.error("--speakers must be a positive integer")
    if not 0.0 < args.scene_threshold < 1.0:
        parser.error("--scene-threshold must be between 0 and 1")
    if args.scene_max_width < 0:
        parser.error("--scene-max-width must be 0 or greater")

    return args


def paragraph_text(node: ET.Element) -> str:
    return "".join(text.text or "" for text in node.findall(".//w:t", DOC_NS)).strip()


def extract_field_links(node: ET.Element) -> list[str]:
    links: list[str] = []
    for instr in node.findall(".//w:instrText", DOC_NS):
        text = instr.text or ""
        links.extend(match.group(1) for match in HYPERLINK_FIELD_RE.finditer(text))
    return dl.unique_preserving_order(links)


def extract_blip_targets(node: ET.Element, relmap: dict[str, str]) -> list[str]:
    images: list[str] = []
    for blip in node.findall(".//a:blip", DOC_NS):
        rid = blip.attrib.get(R_EMBED)
        if rid and rid in relmap:
            images.append(relmap[rid])
    return dl.unique_preserving_order(images)


def extract_table_rows(tbl: ET.Element) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in tbl.findall("./w:tr", DOC_NS):
        row: list[str] = []
        for tc in tr.findall("./w:tc", DOC_NS):
            cell_parts: list[str] = []
            for p in tc.findall(".//w:p", DOC_NS):
                text = paragraph_text(p)
                if text:
                    cell_parts.append(text)
            row.append(" ".join(cell_parts).strip())
        if any(cell for cell in row):
            rows.append(row)
    return rows


def is_lesson_start(element: DocElement) -> bool:
    if element.kind != "paragraph":
        return False
    text = element.text.strip()
    if not text.lower().endswith(".mp4"):
        return False
    return any(THINKIFIC_HOST_TOKEN in link for link in element.links)


def build_relmap(docx_path: Path) -> dict[str, str]:
    with ZipFile(docx_path) as archive:
        rels_root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    return {rel.attrib["Id"]: rel.attrib.get("Target", "") for rel in rels_root}


def collect_doc_elements(docx_path: Path) -> list[DocElement]:
    relmap = build_relmap(docx_path)
    with ZipFile(docx_path) as archive:
        document_root = ET.fromstring(archive.read("word/document.xml"))
    body = document_root.find("w:body", DOC_NS)
    if body is None:
        return []

    elements: list[DocElement] = []
    for child in body:
        tag = child.tag.split("}")[-1]
        if tag == "p":
            text = paragraph_text(child)
            links = extract_field_links(child)
            images = extract_blip_targets(child, relmap)
            if text or links or images:
                elements.append(DocElement(kind="paragraph", text=text, links=links, images=images))
        elif tag == "tbl":
            rows = extract_table_rows(child)
            links = extract_field_links(child)
            images = extract_blip_targets(child, relmap)
            table_text = "\n".join(" | ".join(cell for cell in row) for row in rows).strip()
            if rows or links or images:
                elements.append(
                    DocElement(
                        kind="table",
                        text=table_text,
                        links=links,
                        images=images,
                        table_rows=rows,
                    )
                )
    return elements


def build_lesson_blocks(elements: list[DocElement]) -> list[LessonBlock]:
    lessons: list[LessonBlock] = []
    current: LessonBlock | None = None
    lesson_count = 0

    for element in elements:
        if is_lesson_start(element):
            lesson_count += 1
            lesson_url = next(link for link in element.links if THINKIFIC_HOST_TOKEN in link)
            current = LessonBlock(
                lesson_index=lesson_count,
                title=element.text.strip(),
                lesson_url=lesson_url,
            )
            lessons.append(current)
            continue
        if current is not None:
            current.elements.append(element)

    return lessons


def normalize_url_identity(url: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    return parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/")


def build_doc_assets_paths(project_dir: Path) -> dict[str, Path]:
    return {
        "notes": project_dir / "document_notes.md",
        "images_dir": project_dir / "doc_images",
        "document_manifest": project_dir / "document_manifest.json",
        "extra_dir": project_dir / "linked_resources",
        "extra_manifest": project_dir / "extra_links_manifest.json",
    }


def _preload_docx_images(docx_path: Path) -> dict[str, bytes]:
    """Read all images from DOCX into memory once at startup.

    This prevents repeated ZipFile opens and makes the pipeline
    resilient to the DOCX file being moved or deleted after startup.
    """
    cache: dict[str, bytes] = {}
    with ZipFile(docx_path) as archive:
        for name in archive.namelist():
            if name.startswith("word/media/"):
                cache[name] = archive.read(name)
    return cache


def save_doc_images(
    block: LessonBlock,
    image_cache: dict[str, bytes],
    images_dir: Path,
) -> dict[str, Path]:
    images_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, Path] = {}
    counter = 1
    image_targets = []
    for element in block.elements:
        image_targets.extend(element.images)
    image_targets = dl.unique_preserving_order(image_targets)

    for target in image_targets:
        target_path = target if target.startswith(DOC_MEDIA_PREFIX) else f"{DOC_MEDIA_PREFIX}{target}"
        data = image_cache.get(target_path)
        if data is None:
            continue
        ext = Path(target_path).suffix or ".bin"
        output_name = f"doc_image_{counter:03d}{ext}"
        output_path = images_dir / output_name
        output_path.write_bytes(data)
        saved[target] = Path(images_dir.name) / output_name
        counter += 1
    return saved


def markdown_escape(text: str) -> str:
    return text.replace("|", "\\|").strip()


def render_table_markdown(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    divider = ["---"] * width
    lines = [
        "| " + " | ".join(markdown_escape(cell) for cell in header) + " |",
        "| " + " | ".join(divider) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(markdown_escape(cell) for cell in row) + " |")
    return lines


def render_block_markdown(
    block: LessonBlock,
    image_map: dict[str, Path],
    extra_link_urls: Iterable[str],
    docx_path: Path,
) -> str:
    lines = [
        f"# {block.title}",
        "",
        f"- Source DOCX: `{docx_path}`",
        f"- Main lesson URL: {block.lesson_url}",
    ]
    extra_link_urls = list(extra_link_urls)
    if extra_link_urls:
        lines.append(f"- Extra links in block: {len(extra_link_urls)}")
    lines.append("")

    for element in block.elements:
        if element.kind == "paragraph":
            if element.text:
                lines.append(element.text)
                lines.append("")
            for link in element.links:
                lines.append(f"- Link: {link}")
            if element.links:
                lines.append("")
            for target in element.images:
                rel_path = image_map.get(target)
                if rel_path:
                    lines.append(f"![{rel_path.name}]({rel_path.as_posix()})")
                    lines.append("")
        elif element.kind == "table":
            if element.table_rows:
                lines.extend(render_table_markdown(element.table_rows))
                lines.append("")
            for link in element.links:
                lines.append(f"- Table link: {link}")
            if element.links:
                lines.append("")
            for target in element.images:
                rel_path = image_map.get(target)
                if rel_path:
                    lines.append(f"![{rel_path.name}]({rel_path.as_posix()})")
                    lines.append("")

    return "\n".join(lines).strip() + "\n"


def collect_extra_links(block: LessonBlock) -> list[str]:
    links: list[str] = []
    main_identity = normalize_url_identity(block.lesson_url)
    for element in block.elements:
        for link in element.links:
            if normalize_url_identity(link) == main_identity:
                continue
            links.append(link)
    return dl.unique_preserving_order(links)


def google_export_candidates(url: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if "docs.google.com/document/d/" in url:
        doc_id = re.search(r"/document/d/([^/]+)", url)
        if doc_id:
            candidates.append((f"https://docs.google.com/document/d/{doc_id.group(1)}/export?format=docx", ".docx"))
            candidates.append((f"https://docs.google.com/document/d/{doc_id.group(1)}/export?format=pdf", ".pdf"))
    if "docs.google.com/spreadsheets/d/" in url:
        sheet_id = re.search(r"/spreadsheets/d/([^/]+)", url)
        if sheet_id:
            gid = parse_qs(urlparse(url).query).get("gid", ["0"])[0]
            candidates.append(
                (f"https://docs.google.com/spreadsheets/d/{sheet_id.group(1)}/export?format=xlsx&gid={gid}", ".xlsx")
            )
            candidates.append(
                (f"https://docs.google.com/spreadsheets/d/{sheet_id.group(1)}/export?format=pdf&gid={gid}", ".pdf")
            )
    return candidates


def filename_from_disposition(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, re.IGNORECASE)
    if not match:
        return None
    return unquote(match.group(1)).strip().strip('"')


def guess_extension(url: str, content_type: str | None, filename_hint: str | None) -> str:
    if filename_hint:
        suffix = Path(filename_hint).suffix
        if suffix:
            return suffix
    path_suffix = Path(urlparse(url).path).suffix
    if path_suffix:
        return path_suffix
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip(), strict=False)
        if ext:
            return ext
    return ".bin"


def unique_output_path(directory: Path, stem: str, ext: str) -> Path:
    candidate = directory / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        candidate = directory / f"{stem}_{index:02d}{ext}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate a unique file name in {directory}")


def request_bytes(url: str, headers: dict[str, str]) -> tuple[bytes, str, str | None, str | None]:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read()
            return (
                payload,
                response.geturl(),
                response.headers.get_content_type(),
                response.headers.get("Content-Disposition"),
            )
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while requesting {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error while requesting {url}: {exc.reason}") from exc


def save_generic_resource(
    url: str,
    output_dir: Path,
    name_hint: str | None,
    headers: dict[str, str],
    forced_ext: str | None = None,
) -> dict:
    payload, final_url, content_type, content_disposition = request_bytes(url, headers)
    filename_hint = filename_from_disposition(content_disposition)
    stem = dl.sanitize_filename(dl.strip_known_video_suffix(name_hint or Path(urlparse(final_url).path).stem or "resource"))
    ext = forced_ext or guess_extension(final_url, content_type, filename_hint)
    output_path = unique_output_path(output_dir, stem, ext)
    output_path.write_bytes(payload)
    return {
        "status": "downloaded",
        "source_url": url,
        "final_url": final_url,
        "saved_path": str(output_path),
        "content_type": content_type,
    }


def try_google_export(url: str, output_dir: Path, name_hint: str | None, headers: dict[str, str]) -> dict | None:
    for candidate_url, forced_ext in google_export_candidates(url):
        try:
            result = save_generic_resource(candidate_url, output_dir, name_hint, headers, forced_ext=forced_ext)
            result["source_url"] = url
            result["download_url"] = candidate_url
            return result
        except Exception:
            continue
    return None


def save_youtube_reference(url: str, output_dir: Path, name_hint: str | None) -> dict:
    stem = dl.sanitize_filename(name_hint or "youtube_link")
    output_path = unique_output_path(output_dir, stem, ".url.txt")
    output_path.write_text(url + "\n", encoding="utf-8")
    return {
        "status": "saved_reference",
        "source_url": url,
        "saved_path": str(output_path),
        "content_type": "text/plain",
    }


def download_extra_thinkific_resource(
    url: str,
    output_dir: Path,
    name_hint: str | None,
    engine: str,
    cookie_header: str | None,
) -> dict:
    headers = dl.build_headers(url, cookie_header)
    target = dl.extract_target(url, headers, name_hint)
    stem = dl.sanitize_filename(dl.strip_known_video_suffix(name_hint or target.title))
    output_path = unique_output_path(output_dir, stem, dl.media_extension(target.media_url))
    if engine == "yt-dlp":
        dl.run_ytdlp(target.media_url, output_path, headers)
    else:
        dl.run_ffmpeg(target.media_url, output_path, headers)
    info_path = output_path.with_suffix(".info.json")
    dl.write_json(
        info_path,
        {
            "created_at": dl.utc_now_iso(),
            "source_url": url,
            "media_url": target.media_url,
            "title": target.title,
            "engine": engine,
            "saved_path": str(output_path),
        },
    )
    return {
        "status": "downloaded",
        "source_url": url,
        "media_url": target.media_url,
        "saved_path": str(output_path),
        "info_path": str(info_path),
        "content_type": "video/mp4",
    }


def download_extra_link(
    url: str,
    output_dir: Path,
    name_hint: str | None,
    main_lesson_url: str,
    cookie_header: str | None,
    engine: str,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    link_identity = normalize_url_identity(url)
    main_identity = normalize_url_identity(main_lesson_url)
    if link_identity == main_identity:
        return {"status": "skipped_same_lesson", "source_url": url}

    if THINKIFIC_HOST_TOKEN in urlparse(url).netloc.lower():
        return download_extra_thinkific_resource(url, output_dir, name_hint, engine, cookie_header)

    if "docs.google.com" in urlparse(url).netloc.lower():
        headers = dl.build_headers(main_lesson_url, cookie_header)
        export_result = try_google_export(url, output_dir, name_hint, headers)
        if export_result:
            return export_result
        return save_generic_resource(url, output_dir, name_hint, headers)

    if urlparse(url).netloc.lower() in {"www.youtube.com", "youtube.com", "youtu.be"}:
        if shutil.which("yt-dlp"):
            stem = dl.sanitize_filename(name_hint or "youtube_video")
            output_template = str(output_dir / f"{stem}.%(ext)s")
            command = ["yt-dlp", "--no-part", "-o", output_template, url]
            subprocess.run(command, check=True)
            return {"status": "downloaded", "source_url": url, "saved_path": output_template}
        return save_youtube_reference(url, output_dir, name_hint)

    headers = dl.build_headers(main_lesson_url, cookie_header)
    return save_generic_resource(url, output_dir, name_hint, headers)


def build_block_manifest(
    block: LessonBlock,
    docx_path: Path,
    layout: dl.ProjectLayout,
    image_map: dict[str, Path],
    extra_links: list[str],
) -> dict:
    return {
        "created_at": dl.utc_now_iso(),
        "docx_path": str(docx_path),
        "lesson_index": block.lesson_index,
        "title": block.title,
        "lesson_url": block.lesson_url,
        "project_dir": str(layout.project_dir),
        "elements": len(block.elements),
        "embedded_images": [str(path) for path in image_map.values()],
        "extra_links": extra_links,
    }


def _resolve_layout(
    block: LessonBlock,
    output_root: Path,
    resume: bool,
) -> tuple[dl.ProjectLayout, bool]:
    """Resolve project layout, reusing existing directory in resume mode.

    Returns (layout, is_existing).
    """
    stem = dl.sanitize_filename(dl.strip_known_video_suffix(block.title))
    if resume:
        existing = dl.find_existing_project_dir(output_root, stem)
        if existing:
            return dl.build_project_layout_from_dir(existing, stem), True
    synthetic_target = dl.DownloadTarget(
        page_url=block.lesson_url, media_url=block.lesson_url, title=block.title
    )
    return dl.build_project_layout(output_root, synthetic_target), False


def _video_ready(layout: dl.ProjectLayout) -> bool:
    """Check if video file exists and has non-zero size."""
    return layout.video_file.exists() and layout.video_file.stat().st_size > 0


def _ffprobe_duration(video_file: Path) -> float | None:
    """Get video duration in seconds via ffprobe.

    Returns None if the file is corrupted or cannot be read.
    A valid duration confirms the file has a complete moov atom.
    """
    if not video_file.exists() or video_file.stat().st_size == 0:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_file),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        return None
    except Exception:
        return None


def _format_video_dur(seconds: float) -> str:
    """Format seconds as M:SS for display."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _video_valid(video_file: Path) -> bool:
    """Check if video file exists and is a valid MP4 (has moov atom)."""
    return _ffprobe_duration(video_file) is not None


def _transcription_ready(layout: dl.ProjectLayout) -> bool:
    """Check if transcription output already exists."""
    return layout.transcript_xlsx.exists() or layout.transcript_json.exists()


def _screenshots_ready(layout: dl.ProjectLayout) -> bool:
    """Check if screenshots manifest already exists."""
    return layout.screenshots_manifest.exists()


def _descriptions_ready(layout: dl.ProjectLayout) -> bool:
    """Check if screenshot descriptions already exist."""
    return layout.screenshot_descriptions_manifest.exists()


# ── Threadsafe logging ──────────────────────────────────────────

_log_lock = threading.Lock()


def _ts_log(logger: dl.RunLogger | None, msg: str) -> None:
    """Threadsafe timestamped log line."""
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with _log_lock:
        dl.log_and_print(logger, line)


@dataclass
class _LessonDownloadResult:
    """Result from download_one_lesson, passed to transcribe_one_lesson."""
    block: LessonBlock
    layout: dl.ProjectLayout
    doc_assets: dict
    target: dl.DownloadTarget
    extra_links: list[str]
    extra_results: list[dict]
    errors: list[str]
    steps: dict[str, str]
    video_ok: bool
    skipped: bool = False
    dry_run: bool = False


def download_one_lesson(
    block: LessonBlock,
    image_cache: dict[str, bytes],
    docx_path: Path,
    args: argparse.Namespace,
    cookie_header: str | None,
    engine: str,
    output_root: Path,
    logger: dl.RunLogger | None = None,
) -> _LessonDownloadResult:
    """Phase A: download video + save doc notes + extra links."""
    resume = getattr(args, "resume", False)
    total = getattr(args, "_total_lessons", "?")
    layout, is_existing = _resolve_layout(block, output_root, resume)
    doc_assets = build_doc_assets_paths(layout.project_dir)
    extra_links = [] if args.no_extra_links else collect_extra_links(block)
    errors: list[str] = []
    steps: dict[str, str] = {}
    extra_results: list[dict] = []
    target = dl.DownloadTarget(page_url=block.lesson_url, media_url=block.lesson_url, title=block.title)
    video_ok = False

    _ts_log(logger, f"📥 [{block.lesson_index:02d}/{total}] {block.title}")
    _ts_log(logger, f"  URL: {block.lesson_url}")

    if args.dry_run:
        _ts_log(logger, f"  ~ Dry run — would create: {layout.project_dir}")
        return _LessonDownloadResult(
            block=block, layout=layout, doc_assets=doc_assets, target=target,
            extra_links=extra_links, extra_results=[], errors=[], steps={},
            video_ok=False, skipped=False, dry_run=True,
        )

    # --- Check if fully completed (resume) ---
    if resume and is_existing and layout.project_manifest.exists():
        _ts_log(logger, f"  ⏭  Skipped (already completed)")
        return _LessonDownloadResult(
            block=block, layout=layout, doc_assets=doc_assets, target=target,
            extra_links=extra_links, extra_results=[], errors=[], steps={},
            video_ok=False, skipped=True,
        )

    layout.project_dir.mkdir(parents=True, exist_ok=True)

    # --- Save document notes & images (from cache, fast) ---
    image_map = save_doc_images(block, image_cache, doc_assets["images_dir"])
    notes_markdown = render_block_markdown(block, image_map, extra_links, docx_path)
    doc_assets["notes"].write_text(notes_markdown, encoding="utf-8")
    dl.write_json(
        doc_assets["document_manifest"],
        build_block_manifest(block, docx_path, layout, image_map, extra_links),
    )

    # --- Step 1: Download video ---
    if _video_ready(layout) and resume:
        # Validate existing video with ffprobe
        dur = _ffprobe_duration(layout.video_file)
        if dur is not None:
            size_mb = layout.video_file.stat().st_size / 1e6
            _ts_log(logger, f"  ↳ Video exists and valid ({size_mb:.0f} MB, {_format_video_dur(dur)}), skipping download")
            steps["download"] = "skipped"
            video_ok = True
            if layout.video_info_file.exists():
                try:
                    info = json.loads(layout.video_info_file.read_text(encoding="utf-8"))
                    target = dl.DownloadTarget(
                        page_url=info.get("source_url", block.lesson_url),
                        media_url=info.get("media_url", block.lesson_url),
                        title=info.get("title", block.title),
                    )
                except Exception:
                    pass
        else:
            # Corrupted video — delete and re-download
            _ts_log(logger, f"  ⚠ Video corrupted (ffprobe failed), re-downloading...")
            layout.video_file.unlink(missing_ok=True)

    if not video_ok and "download" not in steps:
        try:
            t0 = time.perf_counter()
            headers = dl.build_headers(block.lesson_url, cookie_header)
            target = dl.extract_target(block.lesson_url, headers, block.title)
            if engine == "yt-dlp":
                dl.run_ytdlp(target.media_url, layout.video_file, headers)
            else:
                dl.run_ffmpeg(target.media_url, layout.video_file, headers)
            dl.write_video_info(layout, target, engine)
            elapsed = time.perf_counter() - t0
            size_mb = layout.video_file.stat().st_size / 1e6 if layout.video_file.exists() else 0
            dur = _ffprobe_duration(layout.video_file)
            if dur is not None:
                dur_str = _format_video_dur(dur)
                _ts_log(logger, f"  ↳ Downloaded ({size_mb:.0f} MB, video={dur_str}, {elapsed:.0f}s)")
                steps["download"] = f"ok ({size_mb:.0f}MB, {dur_str}, {elapsed:.0f}s)"
                video_ok = True
            else:
                _ts_log(logger, f"  ↳ Downloaded ({size_mb:.0f} MB, {elapsed:.0f}s) ⚠ ffprobe INVALID")
                steps["download"] = f"ok but invalid ({size_mb:.0f}MB, {elapsed:.0f}s)"
                video_ok = False
        except Exception as exc:
            errors.append(f"Video download failed: {exc}")
            _ts_log(logger, f"  ✗ Download error: {exc}")
            steps["download"] = f"error: {exc}"

    # --- Step 2: Extra links ---
    if not args.no_extra_links:
        for link_index, url in enumerate(extra_links, start=1):
            name_hint = f"resource_{link_index:02d}"
            try:
                extra_results.append(
                    download_extra_link(
                        url=url,
                        output_dir=doc_assets["extra_dir"],
                        name_hint=name_hint,
                        main_lesson_url=block.lesson_url,
                        cookie_header=cookie_header,
                        engine=engine,
                    )
                )
            except Exception as exc:
                extra_results.append({"status": "error", "source_url": url, "error": str(exc)})
        dl.write_json(
            doc_assets["extra_manifest"],
            {
                "created_at": dl.utc_now_iso(),
                "lesson_title": block.title,
                "lesson_url": block.lesson_url,
                "count": len(extra_results),
                "items": extra_results,
            },
        )

    return _LessonDownloadResult(
        block=block, layout=layout, doc_assets=doc_assets, target=target,
        extra_links=extra_links, extra_results=extra_results,
        errors=errors, steps=steps, video_ok=video_ok,
    )


def transcribe_one_lesson(
    dl_result: _LessonDownloadResult,
    args: argparse.Namespace,
    engine: str,
    logger: dl.RunLogger | None = None,
) -> dict:
    """Phase B: transcribe a downloaded lesson. Returns batch result dict."""
    block = dl_result.block
    layout = dl_result.layout
    errors = list(dl_result.errors)  # copy
    steps = dict(dl_result.steps)    # copy
    target = dl_result.target
    extra_results = dl_result.extra_results
    extra_links = dl_result.extra_links
    doc_assets = dl_result.doc_assets
    transcription_completed = False
    transcribe_command: list[str] | None = None
    resume = getattr(args, "resume", False)
    total = getattr(args, "_total_lessons", "?")

    # --- Transcription ---
    if args.no_transcribe:
        steps["transcription"] = "disabled"
    elif _transcription_ready(layout) and resume:
        _ts_log(logger, f"  🔊 [{block.lesson_index:02d}/{total}] Transcription exists, skipping")
        steps["transcription"] = "skipped"
        transcription_completed = True
    elif not dl_result.video_ok:
        _ts_log(logger, f"  🔊 [{block.lesson_index:02d}/{total}] No valid video, skipping transcription")
        steps["transcription"] = "no_video"
    else:
        try:
            t0 = time.perf_counter()
            _ts_log(logger, f"  🔊 [{block.lesson_index:02d}/{total}] Transcribing {block.title[:40]}...")
            transcribe_command = dl.build_transcribe_command(layout, args)
            log_path = logger.path if logger else None
            dl.run_transcription(transcribe_command, log_path=log_path)
            transcription_completed = True
            elapsed = time.perf_counter() - t0
            _ts_log(logger, f"  🔊 [{block.lesson_index:02d}/{total}] Transcribed ({elapsed:.0f}s)")
            steps["transcription"] = f"ok ({elapsed:.0f}s)"
        except Exception as exc:
            errors.append(f"Transcription failed: {exc}")
            _ts_log(logger, f"  🔊 ✗ [{block.lesson_index:02d}/{total}] Transcription error: {exc}")
            steps["transcription"] = f"error: {exc}"

    # Screenshots and descriptions disabled in pipeline mode
    steps.setdefault("screenshots", "disabled")
    steps.setdefault("descriptions", "disabled")

    # --- Write project manifest ---
    project_manifest = dl.build_project_manifest(
        layout=layout,
        target=target,
        engine=engine,
        args=args,
        transcribe_command=transcribe_command if not args.no_transcribe else None,
        screenshots_result=None,
        transcription_completed=transcription_completed,
        descriptions_completed=False,
        errors=errors,
    )
    project_manifest["document"] = {
        "notes_path": str(doc_assets["notes"]),
        "document_manifest": str(doc_assets["document_manifest"]),
        "doc_images_dir": str(doc_assets["images_dir"]),
        "extra_links_manifest": str(doc_assets["extra_manifest"]) if not args.no_extra_links else "",
        "extra_links_count": len(extra_links),
    }
    project_manifest["extra_links"] = extra_results
    dl.write_json(layout.project_manifest, project_manifest)

    status = "ok" if not errors else "error"
    return {
        "lesson_index": block.lesson_index,
        "title": block.title,
        "lesson_url": block.lesson_url,
        "project_dir": str(layout.project_dir),
        "status": status,
        "errors": errors,
        "extra_links": len(extra_links),
        "steps": steps,
    }


def _get_video_size_mb(layout: dl.ProjectLayout) -> float:
    """Return video file size in MB, or 0 if not found."""
    if layout.video_file.exists():
        return layout.video_file.stat().st_size / (1024 * 1024)
    return 0.0


def _get_transcript_word_count(layout: dl.ProjectLayout) -> int:
    """Attempt to read word count from transcript JSON."""
    for path in [layout.transcript_json, layout.transcript_xlsx]:
        if path.exists() and path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                text = data.get("text", "")
                if text:
                    return len(text.split())
                segments = data.get("segments", [])
                words = sum(len(seg.get("text", "").split()) for seg in segments)
                if words:
                    return words
            except Exception:
                pass
    return 0


def _get_video_duration(layout: dl.ProjectLayout) -> float:
    """Try to read video duration from video_info or screenshots_manifest."""
    if layout.video_info_file.exists():
        try:
            info = json.loads(layout.video_info_file.read_text(encoding="utf-8"))
            dur = info.get("duration_seconds") or info.get("duration")
            if dur:
                return float(dur)
        except Exception:
            pass
    if layout.screenshots_manifest.exists():
        try:
            manifest = json.loads(layout.screenshots_manifest.read_text(encoding="utf-8"))
            dur = manifest.get("video_duration_seconds")
            if dur:
                return float(dur)
        except Exception:
            pass
    return 0.0


def build_summary(
    blocks: list[LessonBlock],
    batch_results: list[dict],
    output_root: Path,
    docx_stem: str,
) -> dict:
    """Build summary JSON and ASCII table from batch results."""
    lessons_data: list[dict] = []

    for result in batch_results:
        index = result.get("lesson_index", 0)
        title = result.get("title", "")
        status = result.get("status", "unknown")
        project_dir_str = result.get("project_dir", "")

        lesson_entry: dict = {
            "index": index,
            "title": title,
            "url": result.get("lesson_url", ""),
            "project_dir": project_dir_str,
            "video_file": "",
            "video_size_mb": 0,
            "duration_seconds": 0,
            "transcription": {"status": "unknown", "word_count": 0},
            "screenshots": {"status": "pending", "count": 0},
            "status": status,
        }

        if project_dir_str:
            project_dir = Path(project_dir_str)
            stem = dl.sanitize_filename(dl.strip_known_video_suffix(title))
            layout = dl.build_project_layout_from_dir(project_dir, stem)

            if _video_ready(layout):
                lesson_entry["video_file"] = layout.video_file.name
                lesson_entry["video_size_mb"] = round(_get_video_size_mb(layout), 1)
                lesson_entry["duration_seconds"] = round(_get_video_duration(layout))

            if _transcription_ready(layout):
                wc = _get_transcript_word_count(layout)
                lesson_entry["transcription"] = {
                    "status": "ok",
                    "word_count": wc,
                }
            elif status == "ok":
                steps = result.get("steps", {})
                tr_step = steps.get("transcription", "")
                if "disabled" in tr_step:
                    lesson_entry["transcription"]["status"] = "disabled"
                elif "error" in tr_step:
                    lesson_entry["transcription"]["status"] = "error"
                else:
                    lesson_entry["transcription"]["status"] = "pending"

            if _screenshots_ready(layout):
                try:
                    sm = json.loads(layout.screenshots_manifest.read_text(encoding="utf-8"))
                    lesson_entry["screenshots"] = {
                        "status": "ok",
                        "count": sm.get("count", len(sm.get("screenshots", []))),
                    }
                except Exception:
                    lesson_entry["screenshots"] = {"status": "ok", "count": 0}
            else:
                lesson_entry["screenshots"] = {"status": "pending", "count": 0}

        lessons_data.append(lesson_entry)

    summary = {
        "created_at": dl.utc_now_iso(),
        "lessons_total": len(lessons_data),
        "lessons": lessons_data,
    }

    # Write JSON
    summary_json_path = output_root / f"{docx_stem}_summary.json"
    dl.write_json(summary_json_path, summary)

    # Write ASCII table
    lines: list[str] = []
    lines.append(f" {'#':>3} | {'Title':<40} | {'Video':>8} | {'Transcription':>15} | {'Screenshots':>12} | Status")
    lines.append("-" * 4 + "+" + "-" * 42 + "+" + "-" * 10 + "+" + "-" * 17 + "+" + "-" * 14 + "+" + "-" * 10)

    for entry in lessons_data:
        idx = f"{entry['index']:3d}"
        title = entry["title"][:40]
        video_mb = f"{entry['video_size_mb']:.0f} MB" if entry["video_size_mb"] > 0 else "—"
        tr = entry["transcription"]
        if tr["status"] == "ok" and tr["word_count"] > 0:
            transcription = f"{tr['word_count']} words"
        elif tr["status"] == "ok":
            transcription = "ok"
        elif tr["status"] == "disabled":
            transcription = "disabled"
        else:
            transcription = "—"
        sc = entry["screenshots"]
        screenshots = f"{sc['count']} frames" if sc["status"] == "ok" else sc["status"]
        status_icon = {"ok": "✓", "skipped": "⏭", "error": "✗", "dry_run": "~"}.get(entry["status"], "?")
        status = f"{status_icon} {entry['status']}"
        lines.append(f" {idx} | {title:<40} | {video_mb:>8} | {transcription:>15} | {screenshots:>12} | {status}")

    table_text = "\n".join(lines) + "\n"
    table_path = output_root / f"{docx_stem}_summary_table.txt"
    table_path.write_text(table_text, encoding="utf-8")

    return summary


def _format_duration(seconds: float) -> str:
    """Format seconds as Xh Ym Zs."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _dir_size_gb(path: Path) -> float:
    """Calculate total size of a directory in GB."""
    total = 0
    if path.is_dir():
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    return total / (1024 ** 3)


def _print_progress(
    logger: dl.RunLogger | None,
    downloaded: int,
    transcribed: int,
    total: int,
    ok: int,
    skipped: int,
    failed: int,
    elapsed: float,
    output_root: Path,
) -> None:
    """Print periodic progress summary."""
    disk_gb = _dir_size_gb(output_root)
    remaining = total - ok - skipped - failed
    rate = (ok + skipped) / elapsed if elapsed > 0 else 0
    eta = remaining / rate if rate > 0 else 0
    border = "─" * 50
    _ts_log(logger, f"\n{border}")
    _ts_log(logger, f"  Progress: {ok + skipped + failed}/{total}")
    _ts_log(logger, f"  Downloaded: {downloaded}  |  Transcribed: {transcribed}")
    _ts_log(logger, f"  ✓ OK: {ok}  |  ⏭ Skip: {skipped}  |  ✗ Fail: {failed}")
    _ts_log(logger, f"  Elapsed: {_format_duration(elapsed)}  |  Disk: {disk_gb:.1f} GB")
    if eta > 0:
        _ts_log(logger, f"  ETA: ~{_format_duration(eta)}")
    _ts_log(logger, border + "\n")


def _blocks_from_manifest(manifest_path: Path) -> list[LessonBlock]:
    """Build LessonBlock list from a previous batch manifest JSON."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    blocks: list[LessonBlock] = []
    for result in data.get("results", []):
        idx = result.get("lesson_index", 0)
        title = result.get("title", f"lesson_{idx}")
        url = result.get("lesson_url", "")
        if not url:
            continue
        blocks.append(LessonBlock(
            lesson_index=idx,
            title=title,
            lesson_url=url,
            elements=[],  # no doc elements available
        ))
    return blocks


def main() -> int:
    args = parse_args()
    logger = dl.create_run_logger("process_docx")

    # --- Determine source: DOCX or manifest ---
    from_manifest = args.from_manifest
    docx_path: Path | None = None
    image_cache: dict[str, bytes] = {}

    if from_manifest:
        manifest_path = Path(from_manifest).expanduser().resolve()
        if not manifest_path.exists():
            dl.log_and_print(logger, f"Error: Manifest not found: {manifest_path}")
            return 1
        _ts_log(logger, f"Loading lessons from manifest: {manifest_path}")
        try:
            cookie_header = dl.load_cookie_header(args.cookie_header, args.cookie_file)
            engine = dl.choose_engine(args.engine)
            blocks = _blocks_from_manifest(manifest_path)
        except Exception as exc:
            dl.log_and_print(logger, f"Error: {exc}")
            return 1
        docx_path = manifest_path  # used for string display only
        _ts_log(logger, f"Loaded {len(blocks)} lessons from manifest")
    else:
        if not args.docx_path:
            dl.log_and_print(logger, "Error: provide docx_path or --from-manifest")
            return 1
        docx_path = Path(args.docx_path).expanduser().resolve()
        if not docx_path.exists():
            dl.log_and_print(logger, f"Error: DOCX not found: {docx_path}")
            return 1
        try:
            cookie_header = dl.load_cookie_header(args.cookie_header, args.cookie_file)
            engine = dl.choose_engine(args.engine)
            elements = collect_doc_elements(docx_path)
            blocks = build_lesson_blocks(elements)
        except Exception as exc:
            dl.log_and_print(logger, f"Error: {exc}")
            return 1
        # Cache all DOCX images in memory (prevents crash if file is moved)
        _ts_log(logger, f"Loading DOCX images into memory...")
        image_cache = _preload_docx_images(docx_path)
        _ts_log(logger, f"Cached {len(image_cache)} images from DOCX")

    total_lessons = len(blocks)
    if args.limit is not None:
        blocks = blocks[: args.limit]

    # Store total for logging
    args._total_lessons = len(blocks)

    output_root = Path(args.output_dir).expanduser().resolve()

    logger.section("Configuration")
    dl.log_and_print(logger, f"Source          : {docx_path}" + (" (manifest)" if from_manifest else " (DOCX)"))
    dl.log_and_print(logger, f"Lessons in DOCX : {total_lessons}")
    dl.log_and_print(logger, f"Processing      : {len(blocks)}")
    dl.log_and_print(logger, f"Output root     : {output_root}")
    dl.log_and_print(logger, f"Download engine : {engine}")
    dl.log_and_print(logger, f"Resume mode     : {getattr(args, 'resume', False)}")
    dl.log_and_print(logger, f"Transcription   : {'off' if args.no_transcribe else f'on (model={args.model}, speakers={args.speakers}, lang={args.language})'}")
    dl.log_and_print(logger, f"Screenshots     : {'off' if args.no_screenshots else f'on (mode={args.screenshot_mode}, interval={args.screenshot_interval}s)'}")
    dl.log_and_print(logger, f"AI Descriptions : {'off' if args.no_descriptions else 'on'}")
    dl.log_and_print(logger, f"Pipeline mode   : {'sequential' if args.no_transcribe else 'parallel (download + transcribe)'}")
    dl.log_and_print(logger, f"Dry run         : {args.dry_run}")
    dl.log_and_print(logger, f"Log file        : {logger.path}")
    dl.log_and_print(logger, "")

    batch_results: list[dict] = []
    ok_count = 0
    skipped_count = 0
    failed_count = 0
    downloaded_count = 0
    transcribed_count = 0
    batch_t0 = time.perf_counter()
    results_lock = threading.Lock()

    # ── Pipeline mode: download and transcribe in parallel ──
    use_pipeline = not args.no_transcribe and not args.dry_run
    transcribe_queue: queue.Queue[_LessonDownloadResult | None] = queue.Queue(maxsize=2)

    def _record_result(result: dict) -> None:
        """Threadsafe result recording."""
        nonlocal ok_count, skipped_count, failed_count
        with results_lock:
            batch_results.append(result)
            status = result.get("status", "unknown")
            if status == "ok":
                ok_count += 1
            elif status == "skipped":
                skipped_count += 1
            elif status in ("error", "dry_run"):
                if status == "error":
                    failed_count += 1

    def download_worker() -> None:
        """Download all videos sequentially, push to transcribe queue."""
        nonlocal downloaded_count
        for block in blocks:
            try:
                dl_result = download_one_lesson(
                    block=block,
                    image_cache=image_cache,
                    docx_path=docx_path,
                    args=args,
                    cookie_header=cookie_header,
                    engine=engine,
                    output_root=output_root,
                    logger=logger,
                )
                if not dl_result.skipped:
                    downloaded_count += 1
                if use_pipeline:
                    transcribe_queue.put(dl_result)
                else:
                    # No transcription — record result directly
                    if dl_result.skipped:
                        _record_result({
                            "lesson_index": block.lesson_index,
                            "title": block.title,
                            "lesson_url": block.lesson_url,
                            "project_dir": str(dl_result.layout.project_dir),
                            "status": "skipped", "errors": [], "extra_links": 0,
                            "steps": {"download": "skipped", "transcription": "disabled"},
                        })
                    else:
                        _record_result({
                            "lesson_index": block.lesson_index,
                            "title": block.title,
                            "lesson_url": block.lesson_url,
                            "project_dir": str(dl_result.layout.project_dir),
                            "status": "ok" if not dl_result.errors else "error",
                            "errors": dl_result.errors,
                            "extra_links": len(dl_result.extra_links),
                            "steps": dl_result.steps,
                        })
            except Exception as exc:
                _ts_log(logger, f"  ✗ FATAL download [{block.lesson_index:02d}]: {exc}")
                if use_pipeline:
                    # Still need to put something in queue to not block transcriber
                    dummy = _LessonDownloadResult(
                        block=block,
                        layout=dl.build_project_layout(output_root,
                            dl.DownloadTarget(page_url=block.lesson_url, media_url="", title=block.title)),
                        doc_assets={}, target=dl.DownloadTarget(page_url="", media_url="", title=""),
                        extra_links=[], extra_results=[], errors=[str(exc)],
                        steps={"download": f"fatal: {exc}"}, video_ok=False,
                    )
                    transcribe_queue.put(dummy)
                else:
                    _record_result({
                        "lesson_index": block.lesson_index,
                        "title": block.title,
                        "lesson_url": block.lesson_url,
                        "status": "error", "errors": [str(exc)],
                    })

            # Periodic progress (every 5 lessons)
            if block.lesson_index % 5 == 0:
                elapsed = time.perf_counter() - batch_t0
                _print_progress(logger, downloaded_count, transcribed_count,
                                len(blocks), ok_count, skipped_count, failed_count,
                                elapsed, output_root)

        if use_pipeline:
            transcribe_queue.put(None)  # sentinel

    def transcribe_worker() -> None:
        """Transcribe lessons as they arrive from download worker."""
        nonlocal transcribed_count
        while True:
            item = transcribe_queue.get()
            if item is None:
                break  # sentinel — all downloads done
            try:
                if item.skipped:
                    _record_result({
                        "lesson_index": item.block.lesson_index,
                        "title": item.block.title,
                        "lesson_url": item.block.lesson_url,
                        "project_dir": str(item.layout.project_dir),
                        "status": "skipped", "errors": [], "extra_links": 0,
                        "steps": {"download": "skipped", "transcription": "skipped"},
                    })
                elif item.dry_run:
                    _record_result({
                        "lesson_index": item.block.lesson_index,
                        "title": item.block.title,
                        "lesson_url": item.block.lesson_url,
                        "project_dir": str(item.layout.project_dir),
                        "status": "dry_run", "errors": [], "extra_links": 0,
                        "steps": {},
                    })
                else:
                    result = transcribe_one_lesson(item, args, engine, logger)
                    _record_result(result)
                    if result.get("status") == "ok":
                        transcribed_count += 1
                    elif "transcription" in result.get("steps", {}):
                        tr = result["steps"]["transcription"]
                        if tr.startswith("ok") or tr == "skipped":
                            transcribed_count += 1
            except Exception as exc:
                _ts_log(logger, f"  🔊 ✗ FATAL transcribe [{item.block.lesson_index:02d}]: {exc}")
                _record_result({
                    "lesson_index": item.block.lesson_index,
                    "title": item.block.title,
                    "lesson_url": item.block.lesson_url,
                    "status": "error", "errors": [str(exc)],
                })
            transcribe_queue.task_done()

    # ── Launch pipeline ──
    if use_pipeline:
        _ts_log(logger, "Starting pipeline: download + transcribe in parallel\n")
        dl_thread = threading.Thread(target=download_worker, name="downloader", daemon=True)
        tr_thread = threading.Thread(target=transcribe_worker, name="transcriber", daemon=True)
        dl_thread.start()
        tr_thread.start()
        dl_thread.join()
        tr_thread.join()
    else:
        _ts_log(logger, "Starting sequential processing\n")
        download_worker()

    batch_elapsed = time.perf_counter() - batch_t0

    # --- Write batch manifest ---
    if not args.dry_run:
        output_root.mkdir(parents=True, exist_ok=True)
        batch_manifest_path = output_root / f"{docx_path.stem}_batch_manifest.json"
        dl.write_json(
            batch_manifest_path,
            {
                "created_at": dl.utc_now_iso(),
                "docx_path": str(docx_path),
                "lessons_total": len(blocks),
                "ok": ok_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "total_time_seconds": round(batch_elapsed, 1),
                "results": batch_results,
            },
        )

        # --- Build summary table ---
        build_summary(blocks, batch_results, output_root, docx_path.stem)

    # --- Final report ---
    disk_gb = _dir_size_gb(output_root)
    logger.section("Result")
    border = "═" * 55
    report = f"""
{border}
  Batch complete: {len(blocks)} lessons
  ✓ OK: {ok_count}  |  ⏭ Skipped: {skipped_count}  |  ✗ Failed: {failed_count}
  Downloaded: {downloaded_count}  |  Transcribed: {transcribed_count}
  Total time: {_format_duration(batch_elapsed)}  |  Disk: {disk_gb:.1f} GB
  Log: {logger.path}"""

    if not args.dry_run:
        summary_json = output_root / f"{docx_path.stem}_summary.json"
        summary_table = output_root / f"{docx_path.stem}_summary_table.txt"
        report += f"""
  Summary JSON : {summary_json}
  Summary Table: {summary_table}"""

    report += f"\n{border}"

    dl.log_and_print(logger, report)

    return 1 if failed_count and not ok_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
