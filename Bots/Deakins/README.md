# Deakins — production / gear specialist

**Role:** Roger Deakins (2x Oscar cinematographer — 1917, Blade Runner 2049,
Sicario). Знает оборудование Романа, помнит решения, советует покупки в
рамках бюджета, ставит свет/звук per channel. Проактивно поднимает темы:
sales, апгрейды, sezonные work-arounds.
**Telegram:** `@rya_deakins_bot`
**Activated:** 2026-05-15 (13-й бот в личном fleet'е Романа)

> **«The right tool for the story, not the trophy.»**

## File locations

| Artefact | Path |
|---|---|
| Persona (Claude agent definition) | `~/.claude/agents/rya-deakins.md` |
| Telegram channel state | `~/.claude/channels/telegram-rya-deakins/` |
| Channel `.env` (token + greeting) | `~/.claude/channels/telegram-rya-deakins/.env` |
| Channel ACL | `~/.claude/channels/telegram-rya-deakins/access.json` |
| launchd: autostart | `~/Library/LaunchAgents/com.romansergeev.deakins-start.plist` |
| launchd: health watchdog | `~/Library/LaunchAgents/com.romansergeev.deakins-health.plist` |
| launchd: inbound watchdog | `~/Library/LaunchAgents/com.romansergeev.deakins-inbound-watchdog.plist` |
| Shell: start | `~/deakins_start.sh` |
| Shell: health watchdog | `~/deakins_health_watchdog.sh` |
| Shell: inbound watchdog | `~/deakins_inbound_watchdog.sh` |
| **Workdir** (cwd of tmux session) | `~/YTAI/Bots/Deakins/` (after Phase B migration) |
| Code | _none — Deakins работает напрямую через persona + Bash, без Python_ |
| Per-bot data | _**в этой папке** — см. ниже_ |
| Bot state (MCP plugin) | `~/.bot_state/telegram-rya-deakins/` |
| Auto-memory (Claude Code, after Phase B) | `~/.claude/projects/-Users-romansergeev-YTAI-Bots-Deakins/memory/` |
| tmux session name | `deakins` |

## Quick commands

```bash
# Status
launchctl list | grep "com.romansergeev.deakins"
tmux has-session -t deakins && echo "tmux: alive" || echo "tmux: missing"
tmux display-message -t deakins -p '#{session_path}'   # должен показать .../Bots/Deakins

# Logs
tail -n 50 /tmp/deakins-start.log

# Restart
tmux kill-session -t deakins
launchctl unload ~/Library/LaunchAgents/com.romansergeev.deakins-start.plist
launchctl load ~/Library/LaunchAgents/com.romansergeev.deakins-start.plist
```

## Documentation

- Persona prompt: `~/.claude/agents/rya-deakins.md` (Roger Deakins voice,
  proactive behaviour, 6 workflows: inventory / decisions / purchase / setups
  / troubleshooting / proactive).
- Fleet roster: `~/YTAI/scripts/10_agents/README.md`.

## Data in this folder

Deakins хранит ВСЁ persistent knowledge здесь — это его cwd и source of
truth. Перед каждым ответом он читает эти файлы:

| File | What's in it | Updated by |
|---|---|---|
| `inventory.md` | Что Роман имеет: камеры, объективы, audio, light, computer, storage | Deakins (после покупок), Roman (для начального наполнения) |
| `decisions.md` | Append-only журнал решений (date, context, considered, chose, reasoning, outcome) | Deakins на каждом значимом выборе |
| `wishlist.md` | Items to consider buying (priority, budget, target sale date) | Deakins (рекомендации), Roman (approvals/strikes) |
| `philosophy.md` | Roman's production approach (что оптимизируем, что избегаем) | Roman fills, Deakins references |
| `proactive_calendar.md` | Sales, warranty deadlines, planned shoots, renewals | Deakins watches, nudges 7 дней до date |
| `lifehacks.md` | Приёмы и workarounds — audio, camera, lighting, post | Both — пополняется при открытии |
| `setups/{YTCR,YTCG,YTRF,YTFP,YTUVI}.md` | Per-channel production setup (cameras, audio, lighting, pre-shoot checklist) | Roman fills, Deakins references per shoot |

**Workflow:** при первой beседе Deakins спросит inventory / philosophy
выясняющими вопросами и заполнит файлы. Дальше — incremental updates по
мере событий.
