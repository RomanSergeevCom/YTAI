# Team — общая база команды RYA

Общая база знаний команды RYA Media Lab FZE для всего fleet'а ботов.
3 секции — People / Projects / Tools — каждая разбита по ownership на
конкретного fleet-бота. Reads открыты для всех, writes — только владелец
секции.

**Last initialized:** 2026-05-15
**Audience:** Роман + 4 fleet-агента (RYA / Murch / Draper / Deakins) +
центральный Galt (read-only access к clients.md).
**Out of scope:** контракты и legal templates — это домен Galt в
`Companies/RYA/`. Здесь только references на contract IDs.

## Ownership matrix

| File | Owner | Reads | Purpose |
|---|---|---|---|
| `people/team.md` | **RYA** | All | Команда RYA — Роман, Руслан, Кирилл, Наталья, ... |
| `people/clients.md` | **RYA** | All + Galt | Активные клиенты (Core Realty, Technodelo, Pravmir, UVI) |
| `people/vendors.md` | **Deakins** | All | Фрилансеры, locations, rental houses, freelance editors |
| `people/experts.md` | **Murch** | All | История гостей-экспертов по интервью (для interview prep) |
| `projects/active.md` | **RYA** | All | Видео в работе (idea → publish) |
| `projects/archive.md` | **RYA** | All | Завершённые проекты (опубликованы или закрыты) |
| `tools/subscriptions.md` | **Galt** | All | Adobe CC, Frame.io, Claude Max, AI tools, hostings — corporate opex |
| `tools/renewals.md` | **Galt** | All | Calendar subscription renewal'ов (overlap с Galt'ом по corp licence renewal'ам в `_Knowledge/RENEWALS.md`) |

## Когда обновлять

| Trigger event | File | Who writes |
|---|---|---|
| Новый член команды / контактные данные изменились | `people/team.md` | RYA |
| Новый клиент / контракт подписан (запись reference, не текст контракта) | `people/clients.md` | RYA |
| Найден фрилансер для съёмки / монтажа / локации | `people/vendors.md` | Deakins |
| Новый гость записан / появилось lessons про него | `people/experts.md` | Murch (после prep workflow) |
| Запускается новый YT проект | `projects/active.md` | RYA |
| Видео опубликовано → перенос в archive | `projects/archive.md` | RYA |
| Подписка куплена / отменена | `tools/subscriptions.md` | Galt |
| Subscription renewal через ≤ 60 дней → flag | `tools/renewals.md` | Galt |
| Gear warranty / sales / shoot prep | `Bots/Deakins/proactive_calendar.md` | Deakins (отдельно от Team/tools/) |

## Когда читать

| Bot | First action — что читает из Team/ |
|---|---|
| **RYA** | `people/team.md`, `clients.md`, `projects/active.md` — при любой продюсерской задаче |
| **Murch** | `people/experts.md` — перед prep workflow (interview questions) |
| **Draper** | `people/clients.md`, `projects/archive.md` — для cross-references в end-screen |
| **Deakins** | (только `Bots/Deakins/proactive_calendar.md` для gear, не tools/) |
| **Galt** | `people/clients.md` (контракты, invoicing), `tools/subscriptions.md`, `tools/renewals.md` (corporate opex tracking + CT visibility) |

## Convention для записей

- **People:** имя, роль, contact (Telegram / phone / email — что есть),
  notes / context, последний контакт.
- **Projects:** code (YTCR04), name, channel, status (pipeline stage),
  guest reference (link to experts.md), deadline, budget, files location.
- **Tools:** name, plan, cost/month or cost/year, renewal date, owner
  account, notes.
- **Markdown** для всех файлов, никаких таблиц-портянок — структурированный
  human-readable text.
- **Backlinks:** если запись ссылается на другую (например, проект ссылается
  на гостя), писать relative path: `[Khalid Ali](../people/experts.md#khalid-ali)`.
