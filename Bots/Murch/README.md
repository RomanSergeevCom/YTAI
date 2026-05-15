# Murch — story-editor agent

**Role:** Walter Murch (3x Oscar film editor, *In the Blink of an Eye*
author). Отвечает за СМЫСЛ видео от сценария до финального cut'а: вопросы
гостю, Assembly brief, Pre-Edit review, Review финального draft'а, push
в Premiere через marker import.
**Telegram:** `@rya_murch_bot`
**Activated:** 2026-05-14

> **«What is the emotion of this moment? If I can't name it, the cut is wrong.»**

## File locations

| Artefact | Path |
|---|---|
| Persona (Claude agent definition) | `~/.claude/agents/rya-murch.md` |
| Telegram channel state | `~/.claude/channels/telegram-rya-murch/` |
| Channel `.env` (token + greeting) | `~/.claude/channels/telegram-rya-murch/.env` |
| Channel ACL | `~/.claude/channels/telegram-rya-murch/access.json` |
| launchd: autostart | `~/Library/LaunchAgents/com.romansergeev.murch-start.plist` |
| launchd: health watchdog | `~/Library/LaunchAgents/com.romansergeev.murch-health.plist` |
| launchd: inbound watchdog | `~/Library/LaunchAgents/com.romansergeev.murch-inbound-watchdog.plist` |
| Shell: start | `~/murch_start.sh` |
| Shell: health watchdog | `~/murch_health_watchdog.sh` |
| Shell: inbound watchdog | `~/murch_inbound_watchdog.sh` |
| **Workdir** (cwd of tmux session) | `~/YTAI/Bots/Murch/` (after Phase B migration) |
| Prompts (no Python orchestrator) | `~/YTAI/scripts/10_agents/murch/prompts/_shared/{murch_voice.md, edit_patterns.md}` |
| Existing pipeline orchestrated | `~/YTAI/scripts/05_editing/{0501_brief, 0506_marker_export, 0508_review, 0500_uxp}/` |
| Shared lib | `~/YTAI/scripts/10_agents/_lib/` |
| Per-channel lessons | `~/YTAI/YTs/{CHANNEL}/murch_lessons.md` (создаются по мере опыта) |
| Bot state (MCP plugin) | `~/.bot_state/telegram-rya-murch/` |
| Auto-memory (Claude Code, after Phase B) | `~/.claude/projects/-Users-romansergeev-YTAI-Bots-Murch/memory/` |
| tmux session name | `murch` |

## Five workflows (trigger → action)

| Trigger | Workflow | Output |
|---|---|---|
| `подготовь вопросы YTCR05` / `/prep YTCR05` | Prep (pre-shoot) | `{project}/00_PreProduction/murch_prep_v1.md` (7-block interview structure) |
| `собери brief YTCR04` / `/brief YTCR04` | Assembly Brief | `{project}/00_Setup/02_Assembly/{CODE}_Assembly_v{N}_in.json` + HTML (via existing 0501) |
| `pre-edit YTCR04` / `/pre_edit YTCR04` | Pre-Edit Review | `_v{N+1}_in.json` + diff HTML после Premiere markers round-trip |
| `review YTCR04` / `/review YTCR04` | Review (post-draft) | `{project}/00_Setup/05_Review/murch_executive_summary_v{N}.md` |
| `push YTCR04` / `/push YTCR04` | Premiere Push | `_premiere_import_v{N}.csv` с цветными markers |

## Quick commands

```bash
# Status
launchctl list | grep "com.romansergeev.murch"
tmux has-session -t murch && echo "tmux: alive" || echo "tmux: missing"
tmux display-message -t murch -p '#{session_path}'   # должен показать .../Bots/Murch

# Logs
tail -n 50 /tmp/murch-start.log

# Restart
tmux kill-session -t murch
launchctl unload ~/Library/LaunchAgents/com.romansergeev.murch-start.plist
launchctl load ~/Library/LaunchAgents/com.romansergeev.murch-start.plist
```

## Documentation

- Persona prompt: `~/.claude/agents/rya-murch.md` (Walter Murch voice, 5 workflows).
- Editorial philosophy: `~/YTAI/scripts/10_agents/murch/prompts/_shared/murch_voice.md`.
- Edit patterns library (problem → fix): `~/YTAI/scripts/10_agents/murch/prompts/_shared/edit_patterns.md`.
- Code README: `~/YTAI/scripts/10_agents/murch/README.md` (orchestration approach — no Python, only Bash + Read).
- Fleet roster: `~/YTAI/scripts/10_agents/README.md`.

## Data in this folder

Сейчас пусто. По мере накопления:
- Cross-channel editorial patterns (что работает в любых talking-head, какие
  cut'ы виновны в drop в retention).
- Decisions log про methodology (например, когда L-cut выбран vs hard sync).
- NPS journal — оценки Романа по executive summaries.

Per-channel editorial lessons → `YTAI/YTs/{CHANNEL}/murch_lessons.md`.
