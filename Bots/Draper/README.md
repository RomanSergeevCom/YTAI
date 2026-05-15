# Draper — packaging agent

**Role:** Don Draper (Mad Men creative director). Упаковывает готовое
видео для публикации: 5 названий, description + chapters, 3 thumbnail-
концепта, 15-20 теги, end-screen recommendations.
**Telegram:** `@rya_draper_bot`
**Activated:** 2026-05-14 (12-й бот в личном fleet'е Романа)

## File locations

| Artefact | Path |
|---|---|
| Persona (Claude agent definition) | `~/.claude/agents/rya-draper.md` |
| Telegram channel state | `~/.claude/channels/telegram-rya-draper/` |
| Channel `.env` (token + greeting) | `~/.claude/channels/telegram-rya-draper/.env` |
| Channel ACL | `~/.claude/channels/telegram-rya-draper/access.json` |
| launchd: autostart | `~/Library/LaunchAgents/com.romansergeev.draper-start.plist` |
| launchd: health watchdog | `~/Library/LaunchAgents/com.romansergeev.draper-health.plist` |
| launchd: inbound watchdog | `~/Library/LaunchAgents/com.romansergeev.draper-inbound-watchdog.plist` |
| Shell: start | `~/draper_start.sh` |
| Shell: health watchdog | `~/draper_health_watchdog.sh` |
| Shell: inbound watchdog | `~/draper_inbound_watchdog.sh` |
| **Workdir** (cwd of tmux session) | `~/YTAI/Bots/Draper/` (after Phase B migration) |
| Code (Python orchestrator + prompts) | `~/YTAI/scripts/10_agents/draper/` |
| Shared lib (used by code) | `~/YTAI/scripts/10_agents/_lib/` |
| Per-channel lessons | `~/YTAI/YTs/{CHANNEL}/draper_lessons.md` (создаются по мере накопления опыта) |
| Bot state (MCP plugin) | `~/.bot_state/telegram-rya-draper/` |
| Auto-memory (Claude Code, after Phase B) | `~/.claude/projects/-Users-romansergeev-YTAI-Bots-Draper/memory/` |
| tmux session name | `draper` |

## Quick commands

```bash
# Status
launchctl list | grep "com.romansergeev.draper"
tmux has-session -t draper && echo "tmux: alive" || echo "tmux: missing"
tmux display-message -t draper -p '#{session_path}'   # должен показать .../Bots/Draper

# Logs
tail -n 50 /tmp/draper-start.log
tail -n 50 /tmp/draper-health.log
tail -n 50 /tmp/draper-inbound-watchdog.log

# Headless run (без Telegram, generates prompt-packs)
python3 ~/YTAI/scripts/10_agents/draper/draper_run.py --id YTCR01 --channel YTCR

# Restart
tmux kill-session -t draper
launchctl unload ~/Library/LaunchAgents/com.romansergeev.draper-start.plist
launchctl load ~/Library/LaunchAgents/com.romansergeev.draper-start.plist
```

## Documentation

- Persona prompt: `~/.claude/agents/rya-draper.md` (Don Draper voice,
  4 workflows: titles / description+chapters / thumbnail concepts / tags+endscreen).
- Code README: `~/YTAI/scripts/10_agents/draper/README.md` (две модели запуска,
  data flow, channels supported).
- Voice + formulas: `~/YTAI/scripts/10_agents/draper/prompts/_shared/{draper_voice.md, title_formulas.md, description_template.md}`.
- Per-channel overrides: `~/YTAI/scripts/10_agents/draper/prompts/{YTCR,YTCG,YTRF,YTFP,YTUVI}.md`.
- Fleet roster: `~/YTAI/scripts/10_agents/README.md`.

## Data in this folder

Сейчас пусто. По мере накопления опыта здесь будут:
- Cross-channel packaging insights (что работает на любой broker-аудитории,
  что универсально fails) — не per-channel.
- Title NPS history — оценки Романа по результатам реальных видео.
- Decisions log про style adjustments.

Per-channel lessons всё ещё в `YTAI/YTs/{CHANNEL}/draper_lessons.md` —
там Draper их и пишет.
