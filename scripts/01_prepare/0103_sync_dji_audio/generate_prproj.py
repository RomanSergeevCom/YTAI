#!/usr/bin/env python3
"""
Generate Premiere Pro project + FCP XML for DJI sync verification.

Two files are created:
  1. .prproj  — copy of RYA_example.prproj template (opens natively in Premiere)
  2. .xml     — FCP 7 XML (xmeml) with sync sequence (V1 + A1 + A2)

Workflow:
  1. Open .prproj in Premiere Pro
  2. File > Import > select .xml
  3. Sequence "DJI Sync Check" appears with aligned tracks
"""
from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import quote


FPS = 25

# ── Locate template ──────────────────────────────────────────
_TEMPLATE_SEARCH_PATHS = [
    # Relative to this script (inside 0103_sync_dji_audio/)
    Path(__file__).parent.parent / "0101_init_folders" / "RYA_example.prproj",
    # Absolute fallback
    Path.home() / "YTAI" / "scripts" / "01_prepare"
    / "0101_init_folders" / "RYA_example.prproj",
]


def _find_template(explicit: Path | None = None) -> Path | None:
    """Return the first existing template path."""
    if explicit and explicit.exists():
        return explicit
    for p in _TEMPLATE_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _sec_to_frames(seconds: float) -> int:
    return int(round(seconds * FPS))


def _path_to_url(p: Path) -> str:
    """Convert absolute path to file:// URL."""
    return "file:///" + quote(str(p.resolve()), safe="/:")


def _build_fcp_xml(
    video_clips: list[dict],
    dji_audio_clips: list[dict],
    sequence_name: str,
) -> str:
    """Build FCP 7 XML (xmeml version 5) string."""
    dji_map: dict[str, dict] = {}
    for ac in dji_audio_clips:
        dji_map[ac["clip_id"]] = ac

    total_dur = sum(vc["duration"] for vc in video_clips)
    total_frames = _sec_to_frames(total_dur)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE xmeml>",
        '<xmeml version="5">',
        "  <sequence>",
        f"    <name>{sequence_name}</name>",
        f"    <duration>{total_frames}</duration>",
        "    <rate>",
        f"      <timebase>{FPS}</timebase>",
        "      <ntsc>FALSE</ntsc>",
        "    </rate>",
        "    <timecode>",
        f"      <rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>",
        "      <string>00:00:00:00</string>",
        "      <frame>0</frame>",
        "      <displayformat>NDF</displayformat>",
        "    </timecode>",
        "    <media>",
    ]

    # ── Video track (V1) ──
    lines += [
        "      <video>",
        "        <format>",
        "          <samplecharacteristics>",
        "            <width>3840</width>",
        "            <height>2160</height>",
        "            <anamorphic>FALSE</anamorphic>",
        "            <pixelaspectratio>square</pixelaspectratio>",
        "            <fielddominance>none</fielddominance>",
        f"            <rate><timebase>{FPS}</timebase>"
        "<ntsc>FALSE</ntsc></rate>",
        "          </samplecharacteristics>",
        "        </format>",
        "        <track>",
    ]

    pos = 0
    for i, vc in enumerate(video_clips):
        frames = _sec_to_frames(vc["duration"])
        fid = f"file-v{i}"
        vid = f"v1-{i}"
        aid = f"a1-{i}"
        url = _path_to_url(vc["path"])
        name = vc["path"].name

        lines += [
            f'          <clipitem id="{vid}">',
            f"            <name>{name}</name>",
            f"            <duration>{frames}</duration>",
            f"            <rate><timebase>{FPS}</timebase>"
            f"<ntsc>FALSE</ntsc></rate>",
            f"            <start>{pos}</start>",
            f"            <end>{pos + frames}</end>",
            "            <in>0</in>",
            f"            <out>{frames}</out>",
            f'            <file id="{fid}">',
            f"              <name>{name}</name>",
            f"              <pathurl>{url}</pathurl>",
            f"              <duration>{frames}</duration>",
            f"              <rate><timebase>{FPS}</timebase>"
            f"<ntsc>FALSE</ntsc></rate>",
            "              <media>",
            "                <video>",
            "                  <samplecharacteristics>",
            "                    <width>3840</width>",
            "                    <height>2160</height>",
            "                  </samplecharacteristics>",
            "                </video>",
            "                <audio>",
            "                  <samplecharacteristics>",
            "                    <samplerate>48000</samplerate>",
            "                    <depth>24</depth>",
            "                    <samplesize>24</samplesize>",
            "                  </samplecharacteristics>",
            "                </audio>",
            "              </media>",
            "            </file>",
            "            <link>",
            f"              <linkclipref>{aid}</linkclipref>",
            "              <mediatype>audio</mediatype>",
            "              <trackindex>1</trackindex>",
            "              <clipindex>1</clipindex>",
            "            </link>",
            "          </clipitem>",
        ]
        pos += frames

    lines += [
        "        </track>",
        "      </video>",
    ]

    # ── Audio tracks ──
    lines.append("      <audio>")
    lines += [
        "        <format>",
        "          <samplecharacteristics>",
        "            <samplerate>48000</samplerate>",
        "            <depth>24</depth>",
        "            <samplesize>24</samplesize>",
        "          </samplecharacteristics>",
        "        </format>",
    ]

    # A1: Camera audio (linked to video)
    lines.append("        <track>")
    pos = 0
    for i, vc in enumerate(video_clips):
        frames = _sec_to_frames(vc["duration"])
        fid = f"file-v{i}"
        vid = f"v1-{i}"
        aid = f"a1-{i}"

        lines += [
            f'          <clipitem id="{aid}">',
            f"            <name>{vc['path'].name}</name>",
            f"            <duration>{frames}</duration>",
            f"            <rate><timebase>{FPS}</timebase>"
            f"<ntsc>FALSE</ntsc></rate>",
            f"            <start>{pos}</start>",
            f"            <end>{pos + frames}</end>",
            "            <in>0</in>",
            f"            <out>{frames}</out>",
            f'            <file id="{fid}"/>',
            "            <link>",
            f"              <linkclipref>{vid}</linkclipref>",
            "              <mediatype>video</mediatype>",
            "            </link>",
            "          </clipitem>",
        ]
        pos += frames
    lines.append("        </track>")

    # A2: DJI audio
    lines.append("        <track>")
    pos = 0
    for i, vc in enumerate(video_clips):
        clip_id = vc.get("clip_id", vc["path"].stem)
        frames = _sec_to_frames(vc["duration"])

        if clip_id in dji_map:
            ac = dji_map[clip_id]
            did = f"a2-{i}"
            dfid = f"file-d{i}"
            durl = _path_to_url(ac["path"])
            dname = ac["path"].name
            dframes = frames  # match video length

            lines += [
                f'          <clipitem id="{did}">',
                f"            <name>{dname}</name>",
                f"            <duration>{dframes}</duration>",
                f"            <rate><timebase>{FPS}</timebase>"
                f"<ntsc>FALSE</ntsc></rate>",
                f"            <start>{pos}</start>",
                f"            <end>{pos + dframes}</end>",
                "            <in>0</in>",
                f"            <out>{dframes}</out>",
                f'            <file id="{dfid}">',
                f"              <name>{dname}</name>",
                f"              <pathurl>{durl}</pathurl>",
                f"              <duration>{dframes}</duration>",
                f"              <rate><timebase>{FPS}</timebase>"
                f"<ntsc>FALSE</ntsc></rate>",
                "              <media>",
                "                <audio>",
                "                  <samplecharacteristics>",
                "                    <samplerate>48000</samplerate>",
                "                    <depth>24</depth>",
                "                    <samplesize>24</samplesize>",
                "                  </samplecharacteristics>",
                "                </audio>",
                "              </media>",
                "            </file>",
                "          </clipitem>",
            ]
        pos += frames
    lines.append("        </track>")

    lines += [
        "      </audio>",
        "    </media>",
        "  </sequence>",
        "</xmeml>",
    ]

    return "\n".join(lines)


def generate_prproj(
    video_clips: list[dict],
    dji_audio_clips: list[dict],
    output_path: Path,
    sequence_name: str = "DJI Sync Check",
    template_path: Path | None = None,
) -> bool:
    """Generate .prproj (template copy) + .xml (FCP sequence).

    Args:
        video_clips: [{path, duration, clip_id}, ...]
        dji_audio_clips: [{path, duration, clip_id}, ...]
        output_path: Base path (.prproj extension expected).
        sequence_name: Name of the sequence inside XML.
        template_path: Explicit template path (optional).

    Returns:
        True if at least the XML was written successfully.
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        prproj_path = output_path.with_suffix(".prproj")
        xml_path = output_path.with_suffix(".xml")

        # 1. Copy template → .prproj
        template = _find_template(template_path)
        if template:
            shutil.copy2(template, prproj_path)

        # 2. Generate FCP XML → .xml
        xml_content = _build_fcp_xml(
            video_clips, dji_audio_clips, sequence_name)
        xml_path.write_text(xml_content, encoding="utf-8")

        return True
    except Exception:
        return False
