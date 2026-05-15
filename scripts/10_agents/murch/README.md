# Murch — YouTube story-editor agent

Walter Murch — 3-time Oscar film editor, переехал в Дубай ради YouTube.
Покрывает весь story-цикл: pre-shoot prep → Assembly brief → Pre-Edit
review → Final Review → Premiere push.

**Telegram:** `@rya_murch_bot`
**Channel dir:** `~/.claude/channels/telegram-rya-murch/`
**Agent definition:** `~/.claude/agents/rya-murch.md`
**Code:** `~/YTAI/scripts/10_agents/murch/`

## Philosophy

> **«What is the emotion of this moment? If I can't name it, the cut is wrong.»**

Every editorial decision answers this first. Read `prompts/_shared/murch_voice.md`
for full editorial philosophy and `prompts/_shared/edit_patterns.md` for
tactical fixes by problem.

## Five workflows

Murch detects intent from message and routes accordingly.

| Trigger | Workflow | Output |
|---|---|---|
| `подготовь вопросы YTCR05` / `/prep YTCR05` | **1. Prep** (pre-shoot) | `00_PreProduction/murch_prep_v1.md` — 7-block interview structure |
| `собери brief YTCR04` / `/brief YTCR04` | **2. Assembly Brief** | `00_Setup/02_Assembly/{CODE}_Assembly_v{N}_in.json` + HTML (existing 0501 workflow) |
| `pre-edit YTCR04` / `/pre_edit YTCR04` | **3. Pre-Edit Review** | `_v{N+1}_in.json` + diff HTML after Premiere markers round-trip |
| `review YTCR04` / `/review YTCR04` | **4. Review** (post-draft) | `_review_analysis.json` (via 0508) + `murch_executive_summary.md` |
| `push YTCR04` / `/push YTCR04` | **5. Premiere Push** | `_premiere_import_v{N}.csv` with colored markers, ready for File→Import |

## What Murch is NOT

- **Not a Python orchestrator.** Murch is an agent that uses Bash + Read to
  invoke existing pipeline scripts (`scripts/05_editing/0501_brief`,
  `0508_review`, `0506_marker_export`, `0500_uxp`). No duplication.
- **Not Draper.** Story decisions stop at finished cut. Packaging
  (titles/thumbnails/description) is Draper.
- **Not Seldon.** No metrics, no comments, no algorithm-tuning. Murch
  optimizes for the human eye/ear, not for views.
- **Not a video editor.** Roman has Кирилл (human editor) for cuts.
  Murch writes briefs and review notes. The editor cuts. Premiere push
  generates markers, not direct timeline edits.

## Existing pipeline scripts Murch orchestrates

Murch reads INSTRUCTIONS.md and follows them. Do not modify these from
within Murch — they belong to the pipeline:

- `~/YTAI/scripts/05_editing/0501_brief/INSTRUCTIONS.md` — Assembly brief format
- `~/YTAI/scripts/05_editing/0501_brief/project_knowledge/editing_rules.md`
- `~/YTAI/scripts/05_editing/0501_brief/project_knowledge/output_format.md`
- `~/YTAI/scripts/05_editing/0506_marker_export/export_markers_from_prproj.py`
- `~/YTAI/scripts/05_editing/0508_review/` — Final review (`_review_analysis.json`)
- `~/YTAI/scripts/05_editing/0500_uxp/` — UXP panel schema for Premiere push

## Shared infrastructure (uses `_lib/`)

| Module | Purpose |
|---|---|
| `_lib/project_resolver.py` | Find project on disks by ID; handles 02/03_Exports + filename mismatches |
| `_lib/dna_loader.py` | Read `YTs/{CH}/{CH}.md` |
| `_lib/review_loader.py` | Load `review_analysis.json` / `review_transcript.json` |
| `_lib/report_writer.py` | Write `murch_report.json` (unified schema with Draper/Seldon) |
| `_lib/telegram_reply.py` | Compact summary formatter for Telegram |

## Per-channel data

Murch reads:
- `YTs/{CHANNEL}/{CHANNEL}.md` — Target Audience, Style, Content Pillars
- `~/YTAI/scripts/10_agents/draper/prompts/{CHANNEL}.md` — Draper's per-channel
  notes (audience voice, brand-specific forbidden phrases — Murch reuses for
  pre-prep interview question tone)
- `YTs/{CHANNEL}/murch_lessons.md` (auto-created on first lesson)

If a channel lacks DNA — Murch fails fast, doesn't guess.

## File map

```
murch/
├── README.md                                # this file
├── prompts/
│   └── _shared/
│       ├── murch_voice.md                   # editorial philosophy (highest leverage)
│       └── edit_patterns.md                 # problem → fix lookup
└── (no Python orchestrator)                 # Murch uses Bash + Read; existing
                                             # 0501/0508/0506 scripts are the
                                             # operational layer
```

## When to add code here

Add a Python helper to `murch/` only when:
- The same logic recurs across all 5 workflows (e.g., specific format
  conversion the existing pipeline doesn't already do)
- The agent finds itself running the same Bash chain 3+ times — refactor
  into one CLI helper
- A new step in the story arc emerges that doesn't fit any existing
  pipeline stage

Most additions should go into `_lib/` (shared with Draper / future Seldon),
not Murch-only.

## Risks & known issues

- **YTCR04 has no Review stage on disk.** First real test of Workflow 4
  needs YTCR01 (Arty Dzis).
- **0501_brief and 0508_review are sequential dependent on transcript.**
  Murch can't start brief without `{CODE}_Claude4_assembly.json` existing.
  Workflow 1 (Prep) is the only pre-transcript entry point.
- **Premiere push (Workflow 5) depends on UXP panel.** If panel isn't
  installed/active, marker-CSV is the fallback. Both paths supported in
  `rya-murch.md` but require user-side Premiere setup.
- **Editor markers format must match `0501_brief/INSTRUCTIONS.md`** —
  `Speaker: X | text | B-roll: Y | Notes: Z. EDITOR NOTES`. If the human
  editor uses a different format — flag, don't try to parse loosely.
