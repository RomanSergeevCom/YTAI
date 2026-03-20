# YTAI

## What This Is

YTAI is an AI-assisted YouTube production pipeline for a solo creator shooting with Sony FX3 and GoPro. It automates the path from raw footage → transcription → Adobe Premiere Pro edit → published video. The pipeline handles audio sync (DJI wireless mics), Whisper transcription, speaker diarization, and a UXP plugin that drives word-based editing inside Premiere Pro.

## Core Value

Every word in the transcript has a timecode — the editor selects quotes, the timeline builds itself.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ Flat project workflow: audio extraction, DJI wireless mic sync, Whisper transcription, UXP INGEST/ASSEMBLY/REVIEW/SCREENS — v1.0

### Active

<!-- Current scope. Building toward these. -->

See REQUIREMENTS.md for full list with REQ-IDs.

### Out of Scope

- Cloud storage / remote rendering — local-only pipeline
- Multi-camera sync between FX3 and GoPro (B-roll only, no sync needed)
- Real-time monitoring or live preview

## Context

- Camera: Sony FX3 (clips named C5XXX.MP4), sometimes GoPro alongside
- Wireless mics: DJI-style TX01 / TX02 lavalier mics, each recording to a dedicated WAV folder with timestamp in filename
- Current flat-project pipeline handles single-scene projects well
- Nested projects (multi-scene) require per-scene organize + sync + transcription, then cross-scene brief assembly
- Reference project: `/Volumes/RYA T7 Black/YTCR01_Arty_Dzis` — 7 scenes, 3 TX folders (TX01, TX02, TX02_2)

## Constraints

- **Platform**: macOS with Apple Silicon — MPS inference, no Windows support
- **Host app**: Adobe Premiere Pro 25.6+ for UXP plugin
- **Sync precision**: TX WAV sync must be ≤1 frame (waveform match, same method as 0103_sync_dji_audio)
- **Non-destructive**: organize step must never delete source files, only move/copy

## Key Decisions

| Decision | Rationale | Outcome |
|---|---|---|
| Waveform match for TX sync | Timestamp in WAV filename pre-filters candidates; waveform confirms exact frame | — Pending |
| Per-scene ingest.json + global merged_transcript.json | UXP needs per-scene timeline; brief needs cross-scene word search | — Pending |
| TX folder naming convention (TX01/, TX02/, TX02_2/) | Multiple sessions of same mic stored in numbered variants | — Pending |

---
*Last updated: 2026-03-17 — Milestone v1.0 started*
