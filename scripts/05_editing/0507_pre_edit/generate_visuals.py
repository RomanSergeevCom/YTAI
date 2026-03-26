#!/usr/bin/env python3
"""
YTAI 0507 Pre-Edit: Generate visual PNGs from pre_edit.json annotations

Reads pre_edit.json (from parse_gdoc.py) and generates PNG files for each
visual annotation:
  - schema → diagram PNG (Pillow, brand fonts/colors)
  - overlay → screen overlay PNG (reuses 0504_screen_cues renderer)
  - broll → placeholder PNG with text description
  - structure → structured info PNG
  - find_frame → text reference (no PNG)
  - image → already extracted by parse_gdoc.py
  - talking_head → skip (no visual)

Usage:
    python generate_visuals.py --input Setup/Pre-Edit/v1/YTCR01_pre_edit_v1.json
    python generate_visuals.py --input pre_edit.json --style style_config.json
"""

import argparse
import json
import sys
import os
import textwrap
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants — Brand style (YTCR defaults, overridden by style_config.json)
# ---------------------------------------------------------------------------

DEFAULT_STYLE = {
    "width": 3840,
    "height": 2160,
    "bg_dark": [10, 22, 40, 240],        # Navy #0A1628
    "bg_accent": [200, 230, 74, 220],     # Lime #C8E64A
    "bg_panel": [55, 94, 157, 230],       # Blue #375E9D
    "text_white": [255, 255, 255, 255],
    "text_light": [220, 220, 220, 255],
    "text_subtle": [180, 180, 180, 230],
    "gradient_start": [10, 22, 40, 240],
    "gradient_end": [10, 22, 40, 0],
}

# Font paths — reuse from 0504_screen_cues
SCRIPT_DIR = Path(__file__).parent
FONT_DIR = SCRIPT_DIR.parent / '0504_screen_cues' / 'fonts'
FONT_TITLE = FONT_DIR / 'Orbitron-Bold.ttf'
FONT_BODY = FONT_DIR / 'Montserrat-Light.ttf'

# Gradient backgrounds from 0504_screen_cues
GRADIENT_DIR = SCRIPT_DIR.parent / '0504_screen_cues'


def load_style(style_path=None):
    """Load style config, falling back to defaults."""
    style = DEFAULT_STYLE.copy()
    if style_path and Path(style_path).exists():
        with open(style_path, 'r') as f:
            custom = json.load(f)
        style.update(custom)
    return style


def get_font(size, bold=False):
    """Get a font at the given size."""
    font_path = FONT_TITLE if bold else FONT_BODY
    try:
        return ImageFont.truetype(str(font_path), size)
    except (OSError, IOError):
        return ImageFont.load_default()


def draw_gradient(draw, width, height, start_rgba, end_rgba, direction='left_to_right', extent=0.6):
    """Draw a gradient overlay."""
    grad_width = int(width * extent)
    for x in range(grad_width):
        ratio = x / grad_width
        r = int(start_rgba[0] + (end_rgba[0] - start_rgba[0]) * ratio)
        g = int(start_rgba[1] + (end_rgba[1] - start_rgba[1]) * ratio)
        b = int(start_rgba[2] + (end_rgba[2] - start_rgba[2]) * ratio)
        a = int(start_rgba[3] + (end_rgba[3] - start_rgba[3]) * ratio)
        draw.line([(x, 0), (x, height)], fill=(r, g, b, a))


def wrap_text(text, font, max_width, draw):
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]

    if current_line:
        lines.append(' '.join(current_line))

    return lines


# ---------------------------------------------------------------------------
# Visual generators
# ---------------------------------------------------------------------------

def generate_schema(segment, style, output_path):
    """Generate a schema/diagram PNG."""
    w, h = style['width'], style['height']
    img = Image.new('RGBA', (w, h), tuple(style['bg_dark']))
    draw = ImageDraw.Draw(img)

    content = segment.get('visual_content', '')

    # Title area
    title_font = get_font(72, bold=True)
    body_font = get_font(48)
    label_font = get_font(36)

    # Draw accent bar at top
    bar_h = 8
    draw.rectangle([0, 0, w, bar_h], fill=tuple(style['bg_accent']))

    # Title: "СХЕМА" label
    label_y = 80
    draw.text((120, label_y), 'СХЕМА', font=label_font, fill=tuple(style['bg_accent']))

    # Main content
    title_y = label_y + 80
    lines = wrap_text(content, title_font, w - 240, draw)
    y = title_y
    for line in lines[:3]:  # Max 3 title lines
        draw.text((120, y), line, font=title_font, fill=tuple(style['text_white']))
        y += 100

    # Separator line
    sep_y = y + 40
    draw.line([(120, sep_y), (w - 120, sep_y)], fill=tuple(style['bg_accent']), width=3)

    # Content area — placeholder for actual diagram
    content_y = sep_y + 60
    placeholder = f"[Визуальная схема: {content}]"
    ph_lines = wrap_text(placeholder, body_font, w - 240, draw)
    for line in ph_lines:
        draw.text((120, content_y), line, font=body_font, fill=tuple(style['text_light']))
        content_y += 70

    # Segment ID watermark
    seg_id = segment.get('segment_id', '')
    draw.text((w - 300, h - 80), seg_id, font=label_font, fill=tuple(style['text_subtle']))

    img.save(output_path)


def generate_overlay(segment, style, output_path):
    """Generate a screen overlay PNG (transparent with gradient)."""
    w, h = style['width'], style['height']
    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    subtype = segment.get('visual_subtype', 'full_overlay')
    content = segment.get('visual_content', '')

    # Draw gradient background based on subtype
    if subtype == 'full_overlay':
        draw_gradient(draw, w, h, style['gradient_start'], style['gradient_end'], extent=1.0)
    elif subtype == 'half_overlay':
        draw_gradient(draw, w, h, style['gradient_start'], style['gradient_end'], extent=0.5)
    elif subtype == 'three_fifths_overlay':
        draw_gradient(draw, w, h, style['gradient_start'], style['gradient_end'], extent=0.6)
    elif subtype == 'chapter_bar':
        # Bottom bar
        bar_h = 120
        draw.rectangle([w // 4, h - bar_h - 40, w * 3 // 4, h - 40],
                       fill=tuple(style['bg_dark']))
    elif subtype == 'lower_third':
        # Lower third rounded bar
        bar_h = 100
        bar_w = int(w * 0.4)
        x1 = (w - bar_w) // 2
        draw.rounded_rectangle([x1, h - bar_h - 80, x1 + bar_w, h - 80],
                               radius=20, fill=tuple(style['bg_panel']))

    # Text
    title_font = get_font(64 if subtype in ['full_overlay', 'half_overlay', 'three_fifths_overlay'] else 48, bold=True)

    if subtype in ['chapter_bar', 'lower_third']:
        # Centered text
        bbox = draw.textbbox((0, 0), content, font=title_font)
        tw = bbox[2] - bbox[0]
        tx = (w - tw) // 2
        ty = h - 120 if subtype == 'chapter_bar' else h - 140
        draw.text((tx, ty), content, font=title_font, fill=tuple(style['text_white']))
    else:
        # Left-aligned text with wrapping
        max_w = int(w * (0.45 if subtype == 'half_overlay' else 0.55))
        lines = wrap_text(content, title_font, max_w, draw)
        y = h // 3
        for line in lines[:4]:
            draw.text((120, y), line, font=title_font, fill=tuple(style['text_white']))
            y += 90

    img.save(output_path)


def generate_broll_placeholder(segment, style, output_path):
    """Generate a B-roll placeholder PNG with description."""
    w, h = style['width'], style['height']
    img = Image.new('RGBA', (w, h), (30, 30, 30, 200))
    draw = ImageDraw.Draw(img)

    content = segment.get('visual_content', '')

    # Draw diagonal lines pattern (indicates placeholder)
    for i in range(-h, w + h, 80):
        draw.line([(i, 0), (i + h, h)], fill=(60, 60, 60, 150), width=2)

    # Center label
    label_font = get_font(48, bold=True)
    body_font = get_font(36)

    label = 'B-ROLL'
    bbox = draw.textbbox((0, 0), label, font=label_font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, h // 3), label, font=label_font, fill=tuple(style['bg_accent']))

    # Description
    desc_lines = wrap_text(content, body_font, w - 400, draw)
    y = h // 3 + 100
    for line in desc_lines[:4]:
        bbox = draw.textbbox((0, 0), line, font=body_font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2, y), line, font=body_font, fill=tuple(style['text_white']))
        y += 60

    # Segment ID
    seg_id = segment.get('segment_id', '')
    small_font = get_font(28)
    draw.text((w - 250, h - 60), seg_id, font=small_font, fill=tuple(style['text_subtle']))

    img.save(output_path)


def generate_structure(segment, style, output_path):
    """Generate a structured info PNG."""
    w, h = style['width'], style['height']
    img = Image.new('RGBA', (w, h), tuple(style['bg_dark']))
    draw = ImageDraw.Draw(img)

    content = segment.get('visual_content', '')

    title_font = get_font(56, bold=True)
    body_font = get_font(44)
    label_font = get_font(32)

    # Accent bar
    draw.rectangle([0, 0, w, 6], fill=tuple(style['bg_accent']))

    # Label
    draw.text((120, 60), 'СТРУКТУРА', font=label_font, fill=tuple(style['bg_accent']))

    # Content — split by newlines or numbered items
    items = [line.strip() for line in content.replace('. ', '.\n').split('\n') if line.strip()]
    y = 180
    for i, item in enumerate(items[:8]):  # Max 8 items
        # Number circle
        cx, cy = 120, y + 30
        draw.ellipse([cx - 25, cy - 25, cx + 25, cy + 25], fill=tuple(style['bg_accent']))
        num_bbox = draw.textbbox((0, 0), str(i + 1), font=label_font)
        nw = num_bbox[2] - num_bbox[0]
        draw.text((cx - nw // 2, cy - 18), str(i + 1), font=label_font, fill=tuple(style['bg_dark'][:3] + [255]))

        # Text
        lines = wrap_text(item, body_font, w - 300, draw)
        for line in lines[:2]:
            draw.text((180, y), line, font=body_font, fill=tuple(style['text_white']))
            y += 65
        y += 20

    # Segment ID
    seg_id = segment.get('segment_id', '')
    draw.text((w - 250, h - 60), seg_id, font=label_font, fill=tuple(style['text_subtle']))

    img.save(output_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

GENERATORS = {
    'schema': generate_schema,
    'overlay': generate_overlay,
    'broll': generate_broll_placeholder,
    'structure': generate_structure,
}


def main():
    parser = argparse.ArgumentParser(description='Generate visual PNGs from pre_edit.json')
    parser.add_argument('--input', '-i', required=True, help='Path to pre_edit.json')
    parser.add_argument('--style', '-s', help='Path to style_config.json')
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    style = load_style(args.style)
    visuals_dir = input_path.parent / 'visuals'
    visuals_dir.mkdir(exist_ok=True)

    generated = 0
    skipped = 0

    for seg in data.get('segments', []):
        vtype = seg.get('visual_type', 'talking_head')
        seg_id = seg.get('segment_id', 'unknown')

        if vtype in GENERATORS:
            # Generate visual
            suffix = seg.get('visual_subtype', vtype)
            filename = f"{seg_id}_{suffix}.png"
            output_path = visuals_dir / filename
            GENERATORS[vtype](seg, style, str(output_path))
            seg['visual_file'] = str(output_path)
            generated += 1
            print(f"  Generated: {filename}")

        elif vtype == 'image':
            # Already extracted by parse_gdoc.py
            img_path = seg.get('visual_image_path', '')
            if img_path:
                print(f"  Image: {seg_id} → {Path(img_path).name}")
            skipped += 1

        elif vtype in ('find_frame', 'video_ref', 'note'):
            # Text-only annotations — no PNG needed
            print(f"  {vtype}: {seg_id} → {seg.get('visual_content', '')[:60]}")
            skipped += 1

        else:
            # talking_head — skip
            skipped += 1

    # Update JSON with file paths
    with open(input_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nGenerated: {generated} PNGs")
    print(f"Skipped: {skipped} (talking_head / text-only / pre-extracted)")
    print(f"Output: {visuals_dir}")


if __name__ == '__main__':
    main()
