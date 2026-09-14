# ytai_load — флаг нагрузки для мониторинга

Роман (14.09.2026): «когда Memex грузится, он должен подавать знаки, что идёт рендер». Мониторинг
(`memex-temp-check.sh`, Engelbart) читает `~/.cache/ytai/LOAD.json` и подписывает тревоги температуры
«🎬 идёт {job}: … нагрузка штатная». `review.py` (стадия 0509_review_cycle) ставит флаг сам на тяжёлых
стадиях; любой другой локальный прогон ставит его этим помощником.

```bash
ytai_load start "RSC004 проверка иллюстраций (Qwen2.5-VL)" 60   # заявить нагрузку на ~60 минут
ytai_load stop                                                 # снять
ytai_load status
ytai_load run "RSC004 VLM" 60 -- python3 vlm_pass.py …         # обёртка: поставить → выполнить → снять
```

Флаг устаревает сам: мониторинг игнорирует его через `expected_min + 60` минут после `started`.
На Memex скрипт лежит в `~/YTAI/scripts/999_extra/bin/` (rsync из репо, `review.py memex push`).
