#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def apply_template(template_dir: Path, target_dir: Path) -> None:
    if not template_dir.exists() or not template_dir.is_dir():
        raise SystemExit(f"Template not found: {template_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)

    # копируем содержимое шаблона внутрь target_dir, без удаления существующих файлов
    for item in template_dir.iterdir():
        src = item
        dst = target_dir / item.name

        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)


def main() -> None:
    ap = argparse.ArgumentParser(description="Apply ~/YTAI/YTDEMO folder tree into a project folder.")
    ap.add_argument(
        "--template",
        default=str(Path.home() / "YTAI" / "YTDEMO"),
        help="Template folder path (default: ~/YTAI/YTDEMO)",
    )
    ap.add_argument(
        "--target",
        required=True,
        help='Project folder path, e.g. "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"',
    )
    args = ap.parse_args()

    template_dir = Path(args.template).expanduser().resolve()
    target_dir = Path(args.target).expanduser().resolve()

    apply_template(template_dir, target_dir)
    print(f"OK: template applied -> {target_dir}")


if __name__ == "__main__":
    main()
