#!/usr/bin/env python3
"""
YTAI Stage 05: Generate Screen Cues PNG Overlays

Reads edit_brief.json (screens[] + segments[] + project{}) and generates
transparent PNG overlays for each screen cue using Pillow.

Each PNG is sized to project resolution (default 3840×2160) with:
  - Transparent background (RGBA)
  - Type-specific layout (chapter_title, lower_third, half_overlay, etc.)
  - Title, subtitle, body text rendered in white on semi-transparent backgrounds

Output: {briefDir}/screen_cues/scr_XXX_{type}.png

Usage:
    python generate_screen_cues_png.py --brief YTAI_Edit_edit_brief.json
    python generate_screen_cues_png.py --brief path/to/edit_brief.json --output-dir custom/path
"""

import argparse
import json
import sys
import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCREEN_TYPES = [
    'full_overlay',          # Full-screen gradient — text centered
    'half_overlay',          # 1/2 screen gradient left — text on left
    'three_fifths_overlay',  # 3/5 screen gradient left — text on left
    'chapter_bar',           # Bottom center bar for chapter names
    'lower_third'            # Centered rounded bar — speaker name
]

SCREEN_REQUIRED_FIELDS = {
    'full_overlay':         ['title'],
    'half_overlay':         ['title'],
    'three_fifths_overlay': ['title'],
    'chapter_bar':          ['title'],
    'lower_third':          ['title'],
}

# Default resolution (overridden by project settings in brief)
DEFAULT_WIDTH = 3840
DEFAULT_HEIGHT = 2160

# Colors (RGBA) — Brand: navy background, lime accent
BG_DARK = (10, 22, 40, 240)          # Navy #0a1628, high opacity
BG_ACCENT = (200, 230, 74, 220)      # Lime #c8e64a (brand accent)
BG_PANEL = (55, 94, 157, 230)        # Blue #375E9D (panels, lower_third)
TEXT_WHITE = (255, 255, 255, 255)
TEXT_LIGHT = (220, 220, 220, 255)
TEXT_SUBTLE = (180, 180, 180, 230)
GRADIENT_START = (10, 22, 40, 240)   # Navy, high opacity
GRADIENT_END = (10, 22, 40, 0)       # Navy, fade to transparent


# ---------------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------------

# Bundled brand fonts (Google Fonts, OFL license)
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
_FONT_ORBITRON_BOLD = os.path.join(_FONT_DIR, 'Orbitron-Bold.ttf')
_FONT_MONTSERRAT_LIGHT = os.path.join(_FONT_DIR, 'Montserrat-Light.ttf')


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font at the given size.

    Brand fonts: Orbitron Bold (titles), Montserrat Light (body/subtitles).
    Falls back to system fonts if bundled fonts are unavailable.
    """
    if bold:
        candidates = [
            _FONT_ORBITRON_BOLD,                                    # Brand: Orbitron Bold
            "/System/Library/Fonts/Helvetica.ttc",                  # macOS fallback
            "/System/Library/Fonts/SFNSDisplay-Bold.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", # Linux fallback
            "C:/Windows/Fonts/arialbd.ttf",                         # Windows fallback
        ]
    else:
        candidates = [
            _FONT_MONTSERRAT_LIGHT,                                 # Brand: Montserrat Light
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSDisplay-Regular.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]

    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except (OSError, IOError):
            continue

    # Fallback to default
    try:
        return ImageFont.truetype("Arial", size)
    except (OSError, IOError):
        return ImageFont.load_default()


def draw_text_with_shadow(draw, xy, text, font, fill=TEXT_WHITE, shadow_offset=3):
    """Draw text with a subtle drop shadow for readability."""
    x, y = xy
    shadow_color = (0, 0, 0, 150)
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=fill)


def draw_rounded_rect(draw, bbox, radius, fill):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = bbox
    draw.rounded_rectangle(bbox, radius=radius, fill=fill)


def draw_gradient_left(img, x_start, x_end, y_start, y_end, color_start, color_end):
    """Draw a horizontal gradient from left to right."""
    width = x_end - x_start
    if width <= 0:
        return
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for x in range(width):
        ratio = x / width
        r = int(color_start[0] + (color_end[0] - color_start[0]) * ratio)
        g = int(color_start[1] + (color_end[1] - color_start[1]) * ratio)
        b = int(color_start[2] + (color_end[2] - color_start[2]) * ratio)
        a = int(color_start[3] + (color_end[3] - color_start[3]) * ratio)
        draw.line([(x_start + x, y_start), (x_start + x, y_end)], fill=(r, g, b, a))
    img.paste(Image.alpha_composite(Image.new('RGBA', img.size, (0, 0, 0, 0)), overlay), (0, 0), overlay)


# ---------------------------------------------------------------------------
# Layout renderers per screen type
# ---------------------------------------------------------------------------

def render_full_overlay(img, draw, screen, w, h):
    """Full-screen gradient overlay — uniform navy tint, text centered."""
    # Uniform navy gradient across full screen
    draw.rectangle([(0, 0), (w, h)], fill=(10, 22, 40, 120))

    # Title — large, centered
    font_title = get_font(int(h * 0.06), bold=True)
    title = screen.get("title", "")
    bbox = draw.textbbox((0, 0), title, font=font_title)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    subtitle = screen.get("subtitle", "")
    body = screen.get("body", "")
    y_cursor = int(h * 0.35)

    tx = (w - tw) // 2
    draw_text_with_shadow(draw, (tx, y_cursor), title, font_title, TEXT_WHITE)
    y_cursor += th + int(h * 0.02)

    if subtitle:
        font_sub = get_font(int(h * 0.03))
        bbox_s = draw.textbbox((0, 0), subtitle, font=font_sub)
        sx = (w - (bbox_s[2] - bbox_s[0])) // 2
        draw_text_with_shadow(draw, (sx, y_cursor), subtitle, font_sub, TEXT_LIGHT)
        y_cursor += (bbox_s[3] - bbox_s[1]) + int(h * 0.02)

    if body:
        font_body = get_font(int(h * 0.022))
        for line in body.split('\n'):
            bbox_b = draw.textbbox((0, 0), line, font=font_body)
            bx = (w - (bbox_b[2] - bbox_b[0])) // 2
            draw_text_with_shadow(draw, (bx, y_cursor), line, font_body, TEXT_LIGHT)
            y_cursor += (bbox_b[3] - bbox_b[1]) + int(h * 0.01)

    # Type label
    font_label = get_font(int(h * 0.02))
    draw_text_with_shadow(draw, (int(w * 0.03), int(h * 0.03)),
                          "[FULL OVERLAY]", font_label, BG_ACCENT)


def render_half_overlay(img, draw, screen, w, h):
    """1/2 screen gradient left — navy fading to transparent, text on left."""
    # Gradient: navy on left 50%, fade to transparent
    fade_start = int(w * 0.45)
    fade_end = int(w * 0.6)
    draw.rectangle([(0, 0), (fade_start, h)], fill=(10, 22, 40, 120))
    draw_gradient_left(img, fade_start, fade_end, 0, h,
                       (10, 22, 40, 120), (10, 22, 40, 0))

    # Text on left side
    x_left = int(w * 0.04)
    y_cursor = int(h * 0.35)

    font_title = get_font(int(h * 0.05), bold=True)
    draw_text_with_shadow(draw, (x_left, y_cursor), screen.get("title", ""), font_title, TEXT_WHITE)
    bbox_t = draw.textbbox((0, 0), screen.get("title", ""), font=font_title)
    y_cursor += (bbox_t[3] - bbox_t[1]) + int(h * 0.02)

    subtitle = screen.get("subtitle", "")
    if subtitle:
        font_sub = get_font(int(h * 0.028))
        draw_text_with_shadow(draw, (x_left, y_cursor), subtitle, font_sub, TEXT_LIGHT)
        bbox_s = draw.textbbox((0, 0), subtitle, font=font_sub)
        y_cursor += (bbox_s[3] - bbox_s[1]) + int(h * 0.02)

    body = screen.get("body", "")
    if body:
        font_body = get_font(int(h * 0.022))
        for line in body.split('\n'):
            draw_text_with_shadow(draw, (x_left, y_cursor), line, font_body, TEXT_LIGHT)
            bbox_b = draw.textbbox((0, 0), line, font=font_body)
            y_cursor += (bbox_b[3] - bbox_b[1]) + int(h * 0.01)

    font_label = get_font(int(h * 0.018))
    draw_text_with_shadow(draw, (x_left, int(h * 0.03)),
                          "[1/2 OVERLAY]", font_label, BG_ACCENT)


def render_three_fifths_overlay(img, draw, screen, w, h):
    """3/5 screen gradient left — navy fading to transparent, text on left."""
    # Gradient: navy on left 60%, fade to transparent
    fade_start = int(w * 0.55)
    fade_end = int(w * 0.72)
    draw.rectangle([(0, 0), (fade_start, h)], fill=(10, 22, 40, 120))
    draw_gradient_left(img, fade_start, fade_end, 0, h,
                       (10, 22, 40, 120), (10, 22, 40, 0))

    # Text on left side
    x_left = int(w * 0.04)
    y_cursor = int(h * 0.35)

    font_title = get_font(int(h * 0.05), bold=True)
    draw_text_with_shadow(draw, (x_left, y_cursor), screen.get("title", ""), font_title, TEXT_WHITE)
    bbox_t = draw.textbbox((0, 0), screen.get("title", ""), font=font_title)
    y_cursor += (bbox_t[3] - bbox_t[1]) + int(h * 0.02)

    subtitle = screen.get("subtitle", "")
    if subtitle:
        font_sub = get_font(int(h * 0.028))
        draw_text_with_shadow(draw, (x_left, y_cursor), subtitle, font_sub, TEXT_LIGHT)
        bbox_s = draw.textbbox((0, 0), subtitle, font=font_sub)
        y_cursor += (bbox_s[3] - bbox_s[1]) + int(h * 0.02)

    body = screen.get("body", "")
    if body:
        font_body = get_font(int(h * 0.022))
        for line in body.split('\n'):
            draw_text_with_shadow(draw, (x_left, y_cursor), line, font_body, TEXT_LIGHT)
            bbox_b = draw.textbbox((0, 0), line, font=font_body)
            y_cursor += (bbox_b[3] - bbox_b[1]) + int(h * 0.01)

    font_label = get_font(int(h * 0.018))
    draw_text_with_shadow(draw, (x_left, int(h * 0.03)),
                          "[3/5 OVERLAY]", font_label, BG_ACCENT)


def render_lower_third(img, draw, screen, w, h):
    """Lower third bar — centered at bottom with rounded corners.

    Layout (reference: production screenshot):
      - Rounded navy/blue bar, ~70% width, centered horizontally
      - Positioned at bottom with ~5% margin
      - Name: large bold text, centered
      - Subtitle: smaller text below name, centered
    """
    bar_w = int(w * 0.55)
    bar_h = int(h * 0.12)
    bar_x = (w - bar_w) // 2
    bar_y = h - bar_h - int(h * 0.05)
    radius = int(h * 0.015)

    # Centered rounded dark navy panel (same color as chapter_bar)
    draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                      radius=radius, fill=BG_DARK)

    # Title (name) — centered
    font_title = get_font(int(h * 0.04), bold=True)
    title = screen.get("title", "")
    bbox_t = draw.textbbox((0, 0), title, font=font_title)
    tw = bbox_t[2] - bbox_t[0]
    th = bbox_t[3] - bbox_t[1]

    subtitle = screen.get("subtitle", "")
    if subtitle:
        font_sub = get_font(int(h * 0.022))
        bbox_s = draw.textbbox((0, 0), subtitle, font=font_sub)
        sh = bbox_s[3] - bbox_s[1]
        sw = bbox_s[2] - bbox_s[0]
        gap = int(h * 0.01)
        total_h = th + gap + sh
        ty = bar_y + (bar_h - total_h) // 2
        sy = ty + th + gap
        tx = bar_x + (bar_w - tw) // 2
        sx = bar_x + (bar_w - sw) // 2
        draw_text_with_shadow(draw, (tx, ty), title, font_title, TEXT_WHITE)
        draw_text_with_shadow(draw, (sx, sy), subtitle, font_sub, TEXT_LIGHT)
    else:
        tx = bar_x + (bar_w - tw) // 2
        ty = bar_y + (bar_h - th) // 2
        draw_text_with_shadow(draw, (tx, ty), title, font_title, TEXT_WHITE)

    # Type label above bar
    font_label = get_font(int(h * 0.018))
    draw_text_with_shadow(draw, (bar_x, bar_y - int(h * 0.03)),
                          "[LOWER THIRD]", font_label, BG_ACCENT)


def render_chapter_bar(img, draw, screen, w, h):
    """Bottom center bar for chapter names (like 'MYTH BUSTING').
    Dark bar across bottom ~18% of screen, large bold centered title."""
    bar_h = int(h * 0.18)
    bar_y = h - bar_h

    # Dark navy bar across full width at bottom
    draw.rectangle([(0, bar_y), (w, h)], fill=BG_DARK)

    # Lime accent line at top of bar
    draw.rectangle([(0, bar_y), (w, bar_y + 4)], fill=BG_ACCENT)

    # Title — large, bold, centered
    font_title = get_font(int(h * 0.055), bold=True)
    title = screen.get("title", "")
    bbox = draw.textbbox((0, 0), title, font=font_title)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (w - tw) // 2
    ty = bar_y + (bar_h - th) // 2
    draw_text_with_shadow(draw, (tx, ty), title, font_title, TEXT_WHITE)

    # Type label top-left of bar
    font_label = get_font(int(h * 0.018))
    draw_text_with_shadow(draw, (int(w * 0.03), bar_y + int(h * 0.015)),
                          "[CHAPTER]", font_label, BG_ACCENT)


# Type → renderer mapping (5 types: 3 gradient overlays + chapter bar + lower third)
RENDERERS = {
    'full_overlay': render_full_overlay,
    'half_overlay': render_half_overlay,
    'three_fifths_overlay': render_three_fifths_overlay,
    'chapter_bar': render_chapter_bar,
    'lower_third': render_lower_third,
}


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def generate_screen_pngs(brief_path: str, output_dir: str = None) -> dict:
    """Generate transparent PNG overlays for each screen cue in the brief.

    Returns: stats dict with counts and file paths.
    """
    # Load brief
    with open(brief_path, "r", encoding="utf-8") as f:
        brief = json.load(f)

    segments = brief.get("segments", [])
    screens_raw = brief.get("screens", [])
    project = brief.get("project", {})

    width = project.get("width", DEFAULT_WIDTH)
    height = project.get("height", DEFAULT_HEIGHT)

    if not screens_raw:
        return {"generated": 0, "skipped": 0, "files": [], "errors": []}

    # Build segment lookup
    seg_map = {}
    for seg in segments:
        seg_id = seg.get("segment_id", "")
        if seg_id:
            seg_map[seg_id] = seg

    # Determine output directory
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(brief_path)), "screen_cues")
    os.makedirs(output_dir, exist_ok=True)

    stats = {"generated": 0, "skipped": 0, "files": [], "errors": []}

    for i, raw in enumerate(screens_raw):
        if not isinstance(raw, dict):
            stats["skipped"] += 1
            continue

        screen_id = raw.get("screen_id", f"scr_{i+1:03d}")
        screen_type = str(raw.get("type", "")).lower().strip()

        if screen_type not in SCREEN_TYPES:
            print(f"  WARN: {screen_id}: invalid type '{raw.get('type')}', skipped")
            stats["skipped"] += 1
            continue

        segment_id = raw.get("segment_id", "")
        if segment_id not in seg_map:
            print(f"  WARN: {screen_id}: segment '{segment_id}' not found, skipped")
            stats["skipped"] += 1
            continue

        # Check required fields
        required = SCREEN_REQUIRED_FIELDS.get(screen_type, ['title'])
        missing = [f for f in required if not str(raw.get(f, "")).strip()]
        if missing:
            print(f"  WARN: {screen_id}: missing [{', '.join(missing)}], skipped")
            stats["skipped"] += 1
            continue

        # Prepare screen data
        screen_data = {
            "title": str(raw.get("title", "")).strip()[:100],
            "subtitle": str(raw.get("subtitle", "")).strip()[:100],
            "body": str(raw.get("body", "")).strip()[:500],
        }

        # Create transparent PNG
        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        renderer = RENDERERS.get(screen_type)
        if renderer:
            try:
                renderer(img, draw, screen_data, width, height)
            except Exception as e:
                err_msg = f"{screen_id}: render error: {e}"
                print(f"  ERROR: {err_msg}")
                stats["errors"].append(err_msg)
                stats["skipped"] += 1
                continue

        # Save PNG
        filename = f"{screen_id}_{screen_type}.png"
        filepath = os.path.join(output_dir, filename)
        img.save(filepath, "PNG")

        stats["generated"] += 1
        stats["files"].append(filepath)
        print(f"  [{stats['generated']}] {filename} ({width}x{height})")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate Screen Cues PNG overlays from edit brief"
    )
    parser.add_argument(
        "--brief", required=True,
        help="Path to {project}_edit_brief.json"
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for PNGs (default: {briefDir}/screen_cues/)"
    )
    args = parser.parse_args()

    brief_path = os.path.abspath(args.brief)
    if not os.path.isfile(brief_path):
        print(f"ERROR: Brief file not found: {brief_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Screen Cues PNG Generator")
    print(f"  Brief: {brief_path}")

    stats = generate_screen_pngs(brief_path, args.output_dir)

    print(f"\nSummary:")
    print(f"  Generated: {stats['generated']} PNGs")
    if stats["skipped"]:
        print(f"  Skipped: {stats['skipped']}")
    if stats["errors"]:
        print(f"  Errors: {len(stats['errors'])}")
        for err in stats["errors"]:
            print(f"    - {err}")
    if stats["files"]:
        print(f"  Output: {os.path.dirname(stats['files'][0])}/")


if __name__ == "__main__":
    main()
