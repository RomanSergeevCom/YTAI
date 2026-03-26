#!/opt/homebrew/opt/python@3.11/libexec/bin/python3
"""
Describe screenshots from a lesson project using an Ollama vision model.

Two-pass approach:
1. CLASSIFY each frame as CONTENT (slide, graphic, text overlay, diagram) or TALKING_HEAD.
2. DESCRIBE only CONTENT frames in detail (TYPE, TEXT, TOPIC, VISUAL).

Can be used standalone or imported by download_thinkific.py / process_docx_thinkific.py.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import download_thinkific as dl

OLLAMA_URL = "http://localhost:11434"
DEFAULT_VISION_MODEL = "minicpm-v"
VISION_TIMEOUT_SEC = 120

CLASSIFY_PROMPT = (
    "Is there ANY visible text, title, slide, graphic, diagram, chart, overlay, "
    "screen recording, or visual information on this frame — besides just a person "
    "sitting at a desk with a microphone and laptop?\n\n"
    "If you see ONLY a person talking (with desk, microphone, laptop, lights as background), "
    "answer: TALKING_HEAD\n"
    "If you see ANY text, graphics, overlays, slides, diagrams, or screen content, "
    "answer: CONTENT\n\n"
    "Answer with exactly one word: CONTENT or TALKING_HEAD"
)

DESCRIBE_PROMPT = (
    "You are analyzing a screenshot from an online educational course. Be concise and factual.\n\n"
    "Report:\n"
    "1. TYPE: What is this? (text slide, bullet points, diagram, talking head with overlay, "
    "screen demo, table, transition, intro/outro, etc.)\n"
    "2. TEXT: List ALL visible text on screen (titles, headings, bullet points, labels, numbers).\n"
    "3. TOPIC: The key idea or concept being shown.\n"
    "4. VISUAL: Charts, diagrams, icons, highlights, or other notable visual elements.\n"
)


def check_ollama_available(model: str = DEFAULT_VISION_MODEL) -> bool:
    """Check if Ollama is running and the requested model is available."""
    try:
        request = Request(f"{OLLAMA_URL}/api/tags")
        with urlopen(request, timeout=5) as response:
            data = json.loads(response.read())
        available = [m.get("name", "") for m in data.get("models", [])]
        base_names = [name.split(":")[0] for name in available]
        if model in available or model in base_names:
            return True
        print(f"Model '{model}' not found. Available: {', '.join(available)}")
        print(f"Run: ollama pull {model}")
        return False
    except (URLError, OSError) as exc:
        print(f"Ollama not reachable at {OLLAMA_URL}: {exc}")
        print("Start Ollama with: ollama serve")
        return False


def _ollama_chat(image_path: Path, prompt: str, model: str) -> str:
    """Send an image + prompt to Ollama and return the text response."""
    with open(image_path, "rb") as handle:
        img_b64 = base64.b64encode(handle.read()).decode("utf-8")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [img_b64]}],
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=VISION_TIMEOUT_SEC) as response:
        result = json.loads(response.read())
    return result.get("message", {}).get("content", "").strip()


def classify_screenshot(image_path: Path, model: str = DEFAULT_VISION_MODEL) -> str:
    """Classify a screenshot as CONTENT or TALKING_HEAD."""
    response = _ollama_chat(image_path, CLASSIFY_PROMPT, model)
    upper = response.upper().strip()
    if "CONTENT" in upper:
        return "CONTENT"
    if "TALKING" in upper:
        return "TALKING_HEAD"
    # If unclear, treat as content to be safe
    return "CONTENT"


def describe_screenshot(
    image_path: Path,
    model: str = DEFAULT_VISION_MODEL,
    prev_description: str = "",
) -> str:
    """Get a full description of a content screenshot."""
    prompt = DESCRIBE_PROMPT
    if prev_description:
        prompt += (
            f"\nPrevious frame showed: {prev_description[:300]}\n"
            "Note what changed from the previous frame.\n"
        )
    return _ollama_chat(image_path, prompt, model)


def describe_all_screenshots(
    manifest_path: Path,
    output_path: Path,
    model: str = DEFAULT_VISION_MODEL,
    logger: dl.RunLogger | None = None,
) -> dict:
    """Two-pass: classify all frames, then describe only CONTENT frames."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    screenshots = manifest.get("screenshots", [])

    if not screenshots:
        dl.log_and_print(logger, "No screenshots found in manifest.")
        payload = {
            "created_at": dl.utc_now_iso(),
            "source_manifest": str(manifest_path),
            "model": model,
            "count": 0,
            "content_count": 0,
            "talking_head_count": 0,
            "errors_count": 0,
            "descriptions": [],
        }
        dl.write_json(output_path, payload)
        return payload

    total = len(screenshots)
    descriptions: list[dict] = []
    errors_count = 0

    # --- Pass 1: classify ---
    dl.log_and_print(logger, f"\n  Pass 1: classifying {total} frames...")
    classifications: list[str] = []
    for entry in screenshots:
        index = entry.get("index", len(classifications) + 1)
        image_path = Path(entry["path"])

        if not image_path.exists():
            classifications.append("MISSING")
            msg = f"  [{index:03d}/{total}] MISSING: {image_path.name}"
            dl.log_and_print(logger, msg)
            continue

        print(f"  [{index:03d}/{total}] classifying {entry.get('file', '')} ...", end=" ", flush=True)
        try:
            cls = classify_screenshot(image_path, model)
            classifications.append(cls)
            tag = "CONTENT" if cls == "CONTENT" else "skip"
            print(tag)
            if logger:
                logger.log(f"  [{index:03d}/{total}] {entry.get('file', '')} -> {cls}")
        except Exception as exc:
            classifications.append("ERROR")
            print(f"ERROR: {exc}")
            if logger:
                logger.log(f"  [{index:03d}/{total}] classify ERROR: {exc}")

    content_indices = [i for i, c in enumerate(classifications) if c == "CONTENT"]
    content_count = len(content_indices)
    talking_count = sum(1 for c in classifications if c == "TALKING_HEAD")
    dl.log_and_print(logger, f"  Classification done: {content_count} content, {talking_count} talking_head, {total - content_count - talking_count} other")

    # --- Pass 2: describe CONTENT frames ---
    dl.log_and_print(logger, f"\n  Pass 2: describing {content_count} content frames...")
    prev_description = ""

    for i, entry in enumerate(screenshots):
        index = entry.get("index", i + 1)
        image_path = Path(entry["path"])
        timestamp = entry.get("timestamp_seconds")
        cls = classifications[i] if i < len(classifications) else "ERROR"

        if cls == "MISSING":
            descriptions.append({
                "index": index,
                "file": entry.get("file", image_path.name),
                "path": str(image_path),
                "timestamp_seconds": timestamp,
                "classification": "MISSING",
                "description": f"ERROR: File not found: {image_path}",
                "model": model,
            })
            errors_count += 1
            continue

        if cls == "TALKING_HEAD":
            descriptions.append({
                "index": index,
                "file": entry.get("file", image_path.name),
                "path": str(image_path),
                "timestamp_seconds": timestamp,
                "classification": "TALKING_HEAD",
                "description": "",
                "model": model,
            })
            continue

        # CONTENT or ERROR during classification — describe it
        print(f"  [{index:03d}/{total}] describing {entry.get('file', '')} ...", end=" ", flush=True)
        try:
            description = describe_screenshot(image_path, model, prev_description)
            descriptions.append({
                "index": index,
                "file": entry.get("file", image_path.name),
                "path": str(image_path),
                "timestamp_seconds": timestamp,
                "classification": "CONTENT",
                "description": description,
                "model": model,
            })
            prev_description = description[:300]
            print("ok")
            if logger:
                logger.log(f"  [{index:03d}/{total}] described {entry.get('file', '')} ok")
        except Exception as exc:
            print(f"ERROR: {exc}")
            if logger:
                logger.log(f"  [{index:03d}/{total}] describe ERROR: {exc}")
            descriptions.append({
                "index": index,
                "file": entry.get("file", image_path.name),
                "path": str(image_path),
                "timestamp_seconds": timestamp,
                "classification": "CONTENT",
                "description": f"ERROR: {exc}",
                "model": model,
            })
            errors_count += 1

    payload = {
        "created_at": dl.utc_now_iso(),
        "source_manifest": str(manifest_path),
        "model": model,
        "count": len(descriptions),
        "content_count": content_count,
        "talking_head_count": talking_count,
        "errors_count": errors_count,
        "descriptions": descriptions,
    }
    dl.write_json(output_path, payload)
    return payload


def describe_from_directory(
    project_dir: Path,
    model: str = DEFAULT_VISION_MODEL,
    force: bool = False,
    logger: dl.RunLogger | None = None,
) -> dict | None:
    """Describe screenshots in a project directory. Returns the descriptions payload or None."""
    manifest_path = project_dir / dl.SCREENSHOTS_MANIFEST_NAME
    output_path = project_dir / dl.SCREENSHOT_DESCRIPTIONS_MANIFEST_NAME

    if not manifest_path.exists():
        dl.log_and_print(logger, f"No screenshots manifest found: {manifest_path}")
        return None

    if output_path.exists() and not force:
        dl.log_and_print(logger, f"Descriptions already exist: {output_path}")
        dl.log_and_print(logger, "Use --force to re-describe.")
        return None

    return describe_all_screenshots(manifest_path, output_path, model, logger=logger)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Describe screenshots from a lesson project using an Ollama vision model. "
            "Two-pass: classify frames as CONTENT/TALKING_HEAD, then describe CONTENT frames."
        )
    )
    parser.add_argument(
        "project_dir",
        help="Path to a lesson project directory containing screenshots_manifest.json.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_VISION_MODEL,
        help=f"Ollama vision model to use. Default: {DEFAULT_VISION_MODEL}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-describe even if screenshots_descriptions.json already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which screenshots would be described, without calling Ollama.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logger = dl.create_run_logger("describe_screenshots")
    project_dir = Path(args.project_dir).expanduser().resolve()

    if not project_dir.is_dir():
        dl.log_and_print(logger, f"Error: Not a directory: {project_dir}")
        return 1

    manifest_path = project_dir / dl.SCREENSHOTS_MANIFEST_NAME
    if not manifest_path.exists():
        dl.log_and_print(logger, f"Error: No screenshots manifest found: {manifest_path}")
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    screenshots = manifest.get("screenshots", [])

    logger.section("Configuration")
    dl.log_and_print(logger, f"Project dir       : {project_dir}")
    dl.log_and_print(logger, f"Screenshots found : {len(screenshots)}")
    dl.log_and_print(logger, f"Vision model      : {args.model}")
    dl.log_and_print(logger, f"Log file          : {logger.path}")

    if args.dry_run:
        for entry in screenshots:
            exists = Path(entry["path"]).exists()
            status = "ok" if exists else "MISSING"
            dl.log_and_print(logger, f"  [{entry.get('index', '?'):03d}] {entry.get('file', '?')}  [{status}]")
        return 0

    if not check_ollama_available(args.model):
        return 1

    logger.section("Processing")
    dl.log_and_print(logger, f"\nProcessing {len(screenshots)} screenshots (classify + describe)...")
    result = describe_from_directory(project_dir, args.model, args.force, logger=logger)
    if result is None:
        return 1

    logger.section("Result")
    dl.log_and_print(logger, f"\nTotal frames       : {result['count']}")
    dl.log_and_print(logger, f"Content frames     : {result['content_count']}")
    dl.log_and_print(logger, f"Talking head       : {result['talking_head_count']}")
    if result["errors_count"]:
        dl.log_and_print(logger, f"Errors             : {result['errors_count']}")
    dl.log_and_print(logger, f"Output file        : {project_dir / dl.SCREENSHOT_DESCRIPTIONS_MANIFEST_NAME}")
    dl.log_and_print(logger, f"Log file           : {logger.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
