# RYA — central AI producer

**Role:** YouTube production producer / central hub. Координирует pipeline,
форвардит задачи специализированным fleet-агентам (Draper / Murch /
Deakins). 7-й бот личного fleet'а Романа (после Carter, Michurin, Osip,
Bormental, MedhoW, Winston, Carson).
**Telegram:** `@ryaae_bot`
**Persona** (Atlas-Rand style John Galt): R.Y.A Media Lab FZE director —
работает с корпоративными документами, банковскими делами FZE; для YouTube
production выступает как central hub fleet'а.

> **NB:** RYA имеет workdir `~/RYA/` (отдельный от других fleet-ботов).
> Эта папка `Bots/RYA/` — только INDEX, не workdir.

## File locations

| Artefact | Path |
|---|---|
| Persona (Claude agent definition) | `~/.claude/agents/galt-rya.md` |
| Telegram channel state | `~/.claude/channels/telegram-rya/` |
| Channel `.env` (token + greeting) | `~/.claude/channels/telegram-rya/.env` |
| Channel ACL | `~/.claude/channels/telegram-rya/access.json` |
| launchd: autostart | `~/Library/LaunchAgents/com.romansergeev.rya-start.plist` |
| launchd: health watchdog | `~/Library/LaunchAgents/com.romansergeev.rya-health.plist` |
| launchd: reminder dispatcher (unique to RYA) | `~/Library/LaunchAgents/com.romansergeev.rya-reminder-dispatcher.plist` |
| Shell: start | `~/rya_start.sh` |
| Shell: health watchdog | `~/rya_health_watchdog.sh` |
| **Workdir** (cwd of tmux session) | `~/RYA/` |
| Workdir CLAUDE.md | `~/RYA/CLAUDE.md` |
| Workdir knowledge base | `~/RYA/_Knowledge/` |
| Workdir Claude settings | `~/RYA/.claude/` |
| Bot state (MCP plugin) | `~/.bot_state/telegram-rya/` |
| Auto-memory (Claude Code) | `~/.claude/projects/-Users-romansergeev-RYA/memory/` |
| tmux session name | `rya` |

## Quick commands

```bash
# Status
launchctl list | grep "com.romansergeev.rya"
tmux has-session -t rya && echo "tmux: alive" || echo "tmux: missing"
test -f ~/.claude/channels/telegram-rya/bot.pid && echo "bot.pid: present" || echo "bot.pid: missing"

# Logs
tail -n 50 /tmp/rya-start.log
tail -n 50 /tmp/rya-health.log

# Restart
tmux kill-session -t rya
launchctl unload ~/Library/LaunchAgents/com.romansergeev.rya-start.plist
launchctl load ~/Library/LaunchAgents/com.romansergeev.rya-start.plist

# Attach (debug-only)
tmux attach -t rya  # Ctrl+B then D to detach
```

## Documentation

- Persona prompt: see `~/.claude/agents/galt-rya.md` (Atlas-Rand style,
  "A is A", корпоративные документы R.Y.A Media Lab FZE).
- Workdir overview: `~/RYA/CLAUDE.md`.
- Knowledge base: `~/RYA/_Knowledge/`.
- Fleet roster: `~/YTAI/scripts/10_agents/README.md`.

## Why workdir стоит отдельно

RYA — старейший бот fleet'а (создан 11 May 2026, до того как появились
Draper/Murch/Deakins). Workdir `~/RYA/` содержит CLAUDE.md и _Knowledge/
со специфическими RYA Media Lab FZE контекстами (контракты, банковские
данные, корп. история). Не сливаем его с YTAI/Bots/ структурой — другая
семантика и история.

Все per-bot data files (если появятся cross-channel у RYA) — могут жить
здесь, в `Bots/RYA/`. Сейчас таких нет.
