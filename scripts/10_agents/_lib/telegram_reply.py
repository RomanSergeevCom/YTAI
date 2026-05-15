"""Format Draper/Sorkin/Seldon results for Telegram replies.

Telegram has a 4096-char limit per message. Long artefacts go in files;
the chat gets a compact summary with absolute file paths.
"""

from __future__ import annotations

from pathlib import Path

MAX_MSG_LEN = 4000  # safety margin under 4096


def format_packaging_summary(
    *,
    project_code: str,
    channel_code: str,
    youtube_dir: str,
    thumbnail_dir: str | None,
    top_title: str,
    titles_count: int,
    chapters_count: int,
    description_first_line: str,
    top_thumbnail_concept: str,
    top_thumbnail_overlay: str,
    top_thumbnail_ref_tc: str | None,
    tags_count: int,
    warnings: list[str] | None = None,
) -> str:
    parts = []
    parts.append(f"📦 *{project_code}* упакован.")
    parts.append("")
    parts.append(f"*{titles_count} названий* → `{youtube_dir}/titles.txt`")
    parts.append(f"Топ: «{top_title}»")
    parts.append("")
    parts.append(f"*Description + {chapters_count} chapters* → `{youtube_dir}/description.txt`, `{youtube_dir}/chapters.txt`")
    parts.append(f"Hook: «{description_first_line}»")
    parts.append("")
    thumb_loc = thumbnail_dir if thumbnail_dir else f"{youtube_dir}/../05_Thumbnail"
    parts.append(f"*3 thumbnail concepts* → `{thumb_loc}/concepts/`")
    parts.append(f"Лучший — {top_thumbnail_concept}: overlay «{top_thumbnail_overlay}»" + (f", ref at {top_thumbnail_ref_tc}" if top_thumbnail_ref_tc else ""))
    parts.append("")
    parts.append(f"*{tags_count} tags + end-screen recs* → `{youtube_dir}/tags.txt`, `{youtube_dir}/end_screen.md`")
    parts.append("")
    parts.append(f"`draper_report.json` — структурированный итог в `{youtube_dir}/`.")

    if warnings:
        parts.append("")
        parts.append("⚠️ *Предупреждения:*")
        for w in warnings:
            parts.append(f"• {w}")

    parts.append("")
    parts.append("Что переделать — скажи: «новые названия», «другой thumbnail», «жёстче description».")

    return "\n".join(parts)


def format_error(error: str, hint: str | None = None) -> str:
    out = [f"❌ {error}"]
    if hint:
        out.append("")
        out.append(hint)
    return "\n".join(out)


def truncate(text: str, max_len: int = MAX_MSG_LEN) -> str:
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 30].rsplit("\n", 1)[0]
    return cut + "\n\n[…обрезано — см. файлы]"
