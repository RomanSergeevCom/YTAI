# Draper — YouTube packaging agent

Mad Men creative director, packed up the office and moved to Dubai. Takes a
finished video (post-Review stage) and produces all publication artefacts:
titles, description, chapters, thumbnail concepts, tags, end-screen recs.

**Telegram:** `@rya_draper_bot` (channel dir `~/.claude/channels/telegram-rya-draper/`)
**Agent definition:** `~/.claude/agents/rya-draper.md`
**Code:** `~/YTAI/scripts/10_agents/draper/`

## Two execution modes

### 1. Telegram-agent mode (primary)

Roman writes to `@rya_draper_bot`:

```
упакуй YTCR01
```

The Mad Draper agent (running in tmux session `draper`) reads everything,
generates the 4 artefacts via Claude tools, writes them directly to the
project, and replies in Telegram with a summary + file paths.

### 2. Headless prompt-pack mode (script)

```bash
python ~/YTAI/scripts/10_agents/draper/draper_run.py --id YTCR01 --channel YTCR
```

Produces 4 ready-to-paste prompt files in `{youtube_dir}/_prompts/`:
- `step_01_titles.md` — voice + formulas + channel + Review data
- `step_02_description.md` — same + description template
- `step_03_thumbnail.md` — same + thumbnail concept brief
- `step_04_tags_endscreen.md` — same + tags + end-screen instructions

Roman pastes each into any LLM and saves replies to `titles.txt`,
`description.txt`, etc.

Also writes `draper_report.json` capturing run metadata.

## Input data (per project)

Draper requires:
- `{project_root}/**/Review/{prefix}_review_analysis.json` (chapters with verdict KEEP, key quotes, synopsis, themes)
- `{project_root}/**/Review/{prefix}_review_transcript.json` (Whisper word-level timestamps)
- `~/YTAI/YTs/{CHANNEL}/{CHANNEL}.md` (DNA — Target Audience, Style, Content Pillars)
- `~/YTAI/scripts/10_agents/draper/prompts/{CHANNEL}.md` (per-channel overrides)

If any of these is missing — Draper fails fast with a clear message.

## Output artefacts (written to project)

```
{project_root}/
├── 06_YouTube/  (or wherever resolver finds *YouTube*)
│   ├── titles.txt              # 5 titles × formula × rationale
│   ├── description.txt         # hook → bullets → chapters → CTA → hashtags
│   ├── chapters.txt            # M:SS Title — promise
│   ├── tags.txt                # 15-20 YouTube tags
│   ├── end_screen.md           # 2 episode recommendations
│   ├── draper_report.json      # structured metadata for downstream agents
│   └── _prompts/               # (headless mode only) prompt-packs
│       ├── step_01_titles.md
│       ├── step_02_description.md
│       ├── step_03_thumbnail.md
│       └── step_04_tags_endscreen.md
└── 05_Thumbnail/  (or *Thumbnail* — resolver auto-detects)
    └── concepts/
        ├── concept_1.md        # text overlay + AI prompt + ref frame
        ├── concept_2.md
        └── concept_3.md
```

## Channels supported

| Code | Brand | Language |
|---|---|---|
| YTCR | Core Realty Dubai | EN |
| YTCG | Connect Group Dubai | EN |
| YTRF | Рефлюкс Контроль / Технодело | RU |
| YTFP | Фонд Правмир — Ассистент Здоровья | RU |
| YTUVI | UVI — Gems & High Jewellery | RU |

Each has a `prompts/{CHANNEL}.md` file with: audience voice, hook patterns
that work / fail, CTA links, hashtags, brand-specific forbidden phrases,
tone notes.

## Adding a new channel

1. Create `~/YTAI/YTs/{NEW_CHANNEL}/{NEW_CHANNEL}.md` from `_template.md`.
2. Fill: Overview, Target Audience (with Pain Points), Content Format,
   Style & Tone, Unique Patterns, Content Pillars, Key Metrics.
3. Create `~/YTAI/scripts/10_agents/draper/prompts/{NEW_CHANNEL}.md` from any
   existing channel prompt (YTCR.md is a clean template for EN, YTRF.md for RU).
4. Add the channel to `CORE FACTS` table in `~/.claude/agents/rya-draper.md`.
5. Test on a real project: `python draper_run.py --id NEW01 --channel NEW`.

## Iterating on Draper voice

The single highest-leverage file is `prompts/_shared/draper_voice.md`.
If titles or descriptions feel weak:

1. Pick the worst artefact from a recent run.
2. Identify the specific failure pattern (too clinical / too clickbait /
   wrong audience register).
3. Add a one-line rule to `draper_voice.md` capturing the lesson.
4. If a channel-specific failure — add to `prompts/{CHANNEL}.md` instead.
5. Run on the same project + 2 others; compare side-by-side.

NPS goal: 7/10 from Roman on each artefact before locking the voice.

## Risks & known issues

- **YTCR04 has no Review stage on disk** (only raw shoots + Archive).
  First real test must be YTCR01.
- **Filename ≠ folder form** (folder `YTCR01_Arty_Dzis/`, files `YTCR1_*`).
  `project_resolver.py` handles this — tries both forms.
- **`published.md` per channel doesn't exist yet.** End-screen
  recommendations use placeholders until Seldon populates this from
  YouTube Analytics.
- **Archive folders can match exports glob** (e.g., YTCR04 resolver finds
  `Archive/02_Exports/`). For now resolver warns via `warnings` array but
  doesn't filter Archive — TODO for v1.1.

## File map

```
draper/
├── README.md                            # this file
├── draper_run.py                        # orchestrator
├── generate_titles.py
├── generate_description.py
├── generate_thumbnail_concepts.py
├── generate_tags.py
├── prompts/
│   ├── _shared/
│   │   ├── draper_voice.md              # ⭐ highest leverage
│   │   ├── title_formulas.md
│   │   └── description_template.md
│   ├── YTCR.md
│   ├── YTCG.md
│   ├── YTRF.md
│   ├── YTFP.md
│   └── YTUVI.md
└── tests/
    └── fixtures/                        # YTCR01 review snapshots (TODO)
```
