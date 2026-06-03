# civ_recon_html.py

Генератор страницы разведки домена **civilizatia.com** для портала yt.rya.ae/civ
(референс-материал под стратегию канала **YTCIV**).

## Что делает
Собирает все находки доменной разведки в один отчёт и пишет 3 файла:

| Выход | Назначение |
|---|---|
| `~/RYA/yt-rya-ae/web/civ/index.html` | страница портала → **yt.rya.ae/civ** |
| `/Volumes/RYA Beige/YTCIV/00_Reference_Analysis/_domain_recon/findings.md` | markdown-отчёт |
| `…/_domain_recon/civ_domain_findings.json` | машинно-читаемые данные |

Данные **вшиты в скрипт** (DOWNLOADABLE / AUDIO / YOUTUBE / SUBDOMAINS / PEOPLE).
Палитра и типографика — Command Center портала (navy #0A1029 + lime #E4FF6E,
Inter + Space Grotesk). Страница статичная, работает по file://.

## Как были получены данные
1. Прямой обход `/file/`-страницы (видео «Интродакция», 5 mp4-вариантов) — `/tmp/crawl_civ.py`.
2. Перечисление поддоменов через CT-логи crt.sh + DNS — `/tmp/crawl_civ2.py`.
3. Детерминированный многохостовый обход всех 12 живых поддоменов — `/tmp/civ_sweep.py`
   (sitemap/BFS + извлечение `/uploads`,`<video>`,плееров,JSON-src + HEAD-верификация).
4. Независимая кросс-проверка — 12-агентный Workflow `wf_1a6b9685-e80`
   (по агенту на поддомен + стадия верификации видео). Результат →
   `/tmp/civ_workflow_result.json`.

Все медиа-ссылки HEAD-проверены (HTTP 200). Открытых PDF/книг по домену — 0.

## Регенерация
```bash
python3 ~/YTAI/scripts/999_extra/civ_recon_html.py
```
Правишь данные в DICT-секциях скрипта → перезапуск.

**Деплой портала** (НЕ GitHub Pages): источник — отдельный репозиторий
`RomanSergeevCom/yt-rya-ae`, локальный клон `~/RYA/yt-rya-ae`, раздаётся папка
`web/`. Push в `main` по путям `web/**` запускает GitHub Actions `deploy.yml`:
`rsync web/ → forgotten-cable:/root/rya/yt-content/` (Hetzner CCX23, docker
`rya-caddy`, Cloudflare фронтом, без `--delete`). После push страница живая
за ~30–60 c. Делается через Winston.
