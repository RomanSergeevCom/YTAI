# 10_agents — YouTube production agent fleet

Telegram-агенты вокруг RYA-бота (центрального AI-продюсера). Каждый покрывает
свою стадию жизненного цикла видео.

## Roster

| Agent | Stage | Status | Telegram |
|---|---|---|---|
| **Deakins** | Production / gear specialist — inventory, decisions, purchase advice, per-channel setup guides | ✅ implemented | `@rya_deakins_bot` |
| **Murch** | Story-editing: prep → assembly brief → pre-edit → review → push в Premiere | ✅ implemented | `@rya_murch_bot` |
| **Draper** | Упаковка готового видео (title/description/thumbnail/tags) | ✅ implemented | `@rya_draper_bot` |
| **Seldon** | Аналитика, комментарии, recommendations | 📋 planned | `@rya_seldon_bot` |

RYA (`@ryaae_bot`) — центральный продюсер: запускает pipeline, координирует
команду, форвардит между агентами.

**Sorkin** (pre-shoot scripts only) был запланирован отдельно, но его scope
поглощён Murch'ем — story-decisions сквозная функция от сценария до
финального cut'а, разделять её на 2 ботов искусственно.

## Shared infrastructure — `_lib/`

| Module | Purpose | Used by |
|---|---|---|
| `project_resolver.py` | Glob path discovery (02_/03_Exports, YTCR1/YTCR01 mismatches, mount-name variations) | all 3 |
| `dna_loader.py` | Read `YTs/{CHANNEL}/{CHANNEL}.md` + parse sections | all 3 |
| `review_loader.py` | Load `review_analysis.json` + `review_transcript.json`, filter KEEP chapters | Draper, Sorkin |
| `report_writer.py` | Unified `{agent}_report.json` schema v1.0 | all 3 |
| `telegram_reply.py` | Compact Telegram summary formatter (chunking, file-link rendering) | all 3 |

## Report schema (v1.0)

All three agents write `{youtube_dir}/{agent}_report.json` after every run.
RYA-бот scans these to build a project timeline:

```json
{
  "agent": "draper" | "sorkin" | "seldon",
  "version": "1.0",
  "project_code": "YTCR01",
  "channel_code": "YTCR",
  "timestamp": "ISO-8601 UTC",
  "inputs": {"review_analysis_sha256": "...", "dna_sha256": "..."},
  "artifacts": {"titles": "path", "description": "path", ...},
  "summary": {"top_title": "...", "top_thumbnail": "concept_1", ...},
  "warnings": []
}
```

## Roadmap

- **Seldon** — YouTube Data API + Analytics API. Daily digest, comment
  triage, trending themes mining. Updates `YTs/{CHANNEL}/published.md` so
  Draper has data for end-screen cross-recommendations and Murch has
  retention data for editorial review.

## Data root

Agent data (inventory, lessons, decision logs, history) lives in
`~/YTAI/Bots/{Draper,Murch,Deakins,Seldon}/` — separate from code.

## Conventions

- All Telegram commands start with `/`. Per-agent verbs:
  - Deakins: `/inventory`, `/buy`, `/setup`, `/wishlist`, `/decision`, `/fix`
  - Murch: `/prep`, `/brief`, `/pre_edit`, `/review`, `/push`
  - Draper: `/pack`, `/титулы`, `/обложка`
  - Seldon: `/report`, `/комменты`
- All scripts accept the same CLI flags: `--id YTCR01`, `--channel YTCR`,
  `--root /abs/path`, `--dry-run`, `--out PATH`.
- All prompts are versioned markdown with YAML frontmatter declaring
  `inputs:` and `outputs:` contracts.
