# Renewals calendar — даты продлений subscriptions

> Sliding window: что продлевается в ближайшие 60 дней. Owned by **Galt**
> (часть corporate opex tracking — связь с WIO outflows + CT deductible
> classification).
>
> NB: Gear warranties / camera sales / shoot prep — это Deakins
> `~/YTAI/Bots/Deakins/proactive_calendar.md`. Здесь только subscription
> renewals (Adobe, Frame.io, hosting, AI tools).
>
> Galt также трекает corporate licence renewals (UAQ Free Zone, NMA
> permit, Trade Licence) в `Companies/RYA/RYA_Media_Lab_FZE/_Knowledge/RENEWALS.md`
> — это связано но отдельно (corp renewals не subscriptions).
>
> Galt проверяет 1 раз в неделю. За 30 дней до renewal — flag Roman'у:
> «продолжаем X или меняем на Y?». За 7 дней — final reminder.

**Last updated:** 2026-05-15 (initial — empty)

---

## Within 7 days (immediate)

> _Empty._

## Within 30 days (review now)

> _Empty._

## Within 60 days (heads-up)

> _Empty._

## Beyond 60 days (long-term tracking)

> _Empty._

---

## Format per entry

```markdown
### YYYY-MM-DD — Tool name renewal

- **Tool:** (ссылка на subscriptions.md)
- **Cost:** $X
- **Auto-renew:** yes / no
- **Decision needed by:** YYYY-MM-DD (за 7-30 дней до renewal)
- **Action options:**
  - Continue (default if no objection)
  - Downgrade to (cheaper tier)
  - Cancel + alternative (specific replacement)
- **Notes:**
```

---

## Annual review pattern (recurring — Galt reads this)

| When | Action |
|---|---|
| 1-го числа каждого месяца | Scan all subscriptions due в next 60 days, populate этот файл |
| 7 дней до renewal | Final reminder в Telegram, suggest decision |
| 30 дней до renewal | Heads-up: "X продлевается через 30 дней, использовали в последние 2 месяца?" |
| После renewal | Mark entry как closed, перенести в historical log (TBD — будет в `Companies/RYA/_Knowledge/SUBSCRIPTION_HISTORY.md`) |
| Q4 каждого года | Cross-check со списком expenses для CT filing — все ли business subscriptions учтены как deductible |

---

## To fill

Заполняется в паре с `tools/subscriptions.md` — каждая subscription с
renewal date переезжает сюда автоматически (Deakins при первой scope —
пройдёт через все entry'и subscriptions и составит calendar).
