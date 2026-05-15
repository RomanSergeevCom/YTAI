# YTAI Bots — fleet single point of entry

Папка для всех YouTube-fleet агентов вокруг RYA-бота. Каждая подпапка =
один бот, и её `README.md` это его INDEX: где живут persona, channel,
launchd, shell scripts, code, data — все absolute paths в одном месте.

**Кодовая часть** агентов в `~/YTAI/scripts/10_agents/`.
**Persona** в `~/.claude/agents/rya-*.md`.
**Channels** в `~/.claude/channels/telegram-rya-*/`.
**launchd plists** в `~/Library/LaunchAgents/com.romansergeev.*.plist`.
**Shell scripts** в `~/{name}_*.sh`.
**Per-bot data** (inventory, decisions, lessons, history) — **здесь**, в
`Bots/{Name}/`.
**Auto-memory** — `~/.claude/projects/-Users-romansergeev-YTAI-Bots-{Name}/memory/`
для fleet-агентов (Draper / Murch / Deakins), и
`~/.claude/projects/-Users-romansergeev-RYA/memory/` для центрального RYA.

## Convention

Each `Bots/{Name}/` is the single point of entry for that bot:

- `README.md` — INDEX с absolute paths ко ВСЕМ артефактам бота, которые
  живут вне этой папки (persona, channel, launchd plists, shell scripts, code).
- Любые per-bot data файлы (inventory, lessons, history) живут в этой
  папке напрямую или в её subdirectories.
- tmux session бота имеет cwd = эта папка. Это значит Claude Code
  auto-memory создаётся в `~/.claude/projects/-Users-romansergeev-YTAI-Bots-{Name}/memory/`
  — изолировано от других ботов и от Roman'овской YTAI dev session.

При debug бота или onboarding нового агента — открой `Bots/{Name}/README.md`
первым. Он скажет, где каждая часть этого бота лежит на диске.

## Структура

```
~/YTAI/Bots/
├── RYA/         # Central producer — INDEX-only (workdir остаётся ~/RYA/)
├── Draper/      # Packaging — INDEX + cross-channel patterns
├── Murch/       # Story-editor — INDEX + cross-channel editorial lessons
├── Deakins/     # Gear specialist — INDEX + inventory/decisions/wishlist/setups/...
├── Seldon/      # (future) Analytics — placeholder
└── Team/        # SHARED knowledge base — people/projects/tools (cross-bot)
```

## Team — shared knowledge

`Bots/Team/` отличается от других подпапок: это НЕ один бот, это **общая
база команды RYA** read/write по разделам:

| Section | Owner bot | Reads |
|---|---|---|
| `Team/people/team.md` | RYA | All |
| `Team/people/clients.md` | RYA | All + Galt |
| `Team/people/vendors.md` | Deakins | All |
| `Team/people/experts.md` | Murch | All |
| `Team/projects/active.md` | RYA | All |
| `Team/projects/archive.md` | RYA | All |
| `Team/tools/subscriptions.md` | Galt | All |
| `Team/tools/renewals.md` | Galt | All |

Каждый бот читает релевантные секции при first action и обновляет свои
секции по мере появления info. См. `Team/README.md` для ownership matrix
и conventions.

## Что куда

| Бот | Что туда писать |
|---|---|
| **Draper** | Не channel-specific — те живут в `YTs/{CH}/draper_lessons.md`. Сюда — общие cross-channel выводы (что работает на любой broker-аудитории, что универсально fails). |
| **Murch** | Editorial lessons cross-channel + общие patterns. Per-channel lessons всё ещё в `YTs/{CH}/murch_lessons.md`. |
| **Deakins** | Полное inventory оборудования, decisions log, wishlist, setup guides per channel, lifehacks, proactive calendar. |
| **Seldon** | Algorithm-level data: что работает в comments, viral patterns, retention insights cross-channel. |

## Conventions

- Markdown only (нужно человеку читать и боту парсить).
- Date prefixes на journal'ы: `2026-05-15_decision_xxx.md` или в одном файле с datestamps.
- Per-channel файлы — в `setups/{CHANNEL}.md` или в `YTs/{CHANNEL}/{bot}_lessons.md`.
- НЕ хранить секреты / токены / API keys — они в `~/.claude/channels/{channel}/.env`.

## Git tracking

Эти файлы — часть YTAI repo. Commit'ить как обычно. Семантика commit messages:
- `feat(deakins): add Sony A7iv inventory entry`
- `docs(murch): cross-channel pacing lesson from YTCR04`
- `chore(bots): rotate decision log archives`
