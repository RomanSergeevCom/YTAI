"""Generate thumbnail concepts prompt-pack — 3 concepts (overlay + AI prompt + ref frame)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LIB_PARENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB_PARENT))

from _lib import dna_loader, review_loader  # noqa: E402

DRAPER_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = DRAPER_DIR / "prompts"


def build_prompt(resolved: dict) -> str:
    channel_code = resolved["channel_code"]
    project_id = resolved["project_id"]

    voice = (PROMPTS_DIR / "_shared" / "draper_voice.md").read_text(encoding="utf-8")
    channel_prompt = (PROMPTS_DIR / f"{channel_code}.md").read_text(encoding="utf-8")

    analysis = review_loader.load_analysis(resolved["review_analysis_json"])
    dna = dna_loader.load(channel_code)
    quotes = review_loader.key_quotes(analysis)
    keep = review_loader.keep_chapters(analysis)

    user_block = f"""# Project: {project_id}  ·  Channel: {channel_code}

## Synopsis
{analysis.get('synopsis', '<missing>')}

## Story arc
{analysis.get('story_arc', '<missing>')}

## Key strengths (with timestamps — use these for ref frames)
{chr(10).join(f"- {s}" for s in (analysis.get('key_strengths') or [])[:8])}

## Strongest key quotes (with chapter and timestamp)
{chr(10).join(f"- [{q.get('tc_in', '?')}] {q.get('title', '')}: {q.get('quote', '')}" for q in quotes[:6])}

## Channel DNA — Unique Patterns
{dna_loader.section(dna, 'Unique Patterns') or ''}

## Channel DNA — Style & Tone
{dna_loader.section(dna, 'Style & Tone') or ''}
"""

    thumbnail_dir = resolved.get("thumbnail_dir") or f"{resolved['project_root']}/05_Thumbnail"

    return f"""# SYSTEM (Draper voice)

{voice}

---

# SYSTEM (Channel overrides — {channel_code})

{channel_prompt}

---

# USER

Сделай 3 thumbnail concepts. Каждый — отдельный markdown-файл. Имена файлов
сохрани с пометками concept_1.md / concept_2.md / concept_3.md.

Для каждого концепта 4 блока:

### Concept N: [Краткое название концепта]

**Text overlay (3-5 слов)**
[Что напишется ПОВЕРХ кадра. Большим шрифтом. Никаких объяснительных
длинных фраз. 3-5 слов max.]

**Visual prompt (для Firefly / Midjourney / Sora)**
[Детальный prompt: composition, lighting, mood, subject framing,
background. Английский язык prompt — даже для русскоязычных каналов
(AI tools работают лучше на английском).]

**Reference frame**
[Timestamp из видео (M:SS), где зафиксировать выражение лица / жест /
момент. Должен быть из KEEP chapter, желательно из best key_quote.]

**Why this works**
[Одна строка: на какой emotional trigger опирается этот концепт —
FOMO / pattern interrupt / authority / contradiction / curiosity gap.]

Output language для overlay: {'en' if channel_code in ('YTCR', 'YTCG') else 'ru'}.
Visual prompt — английский в любом случае (AI tools).

Концепты должны быть РАЗНЫМИ по подходу — не вариации одного. Например:
1 — крупный план лица героя с эмоциональным overlay.
2 — split-screen "до/после" или "конфликт идей".
3 — окружение/контекст с heroем в кадре (location-driven).

Конечная папка: `{thumbnail_dir}/concepts/concept_{{1,2,3}}.md`

{user_block}
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolved-json", required=True)
    parser.add_argument("--step-name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    resolved = json.loads(args.resolved_json)
    prompt = build_prompt(resolved)

    youtube_dir = Path(resolved["youtube_dir"])
    prompts_dir = youtube_dir / "_prompts"
    out_path = prompts_dir / f"step_{args.step_name}.md"
    if not args.dry_run:
        prompts_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(prompt, encoding="utf-8")

    print(json.dumps({
        "step": args.step_name,
        "status": "ok",
        "prompt_path": str(out_path),
        "prompt_chars": len(prompt),
        "dry_run": args.dry_run,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
