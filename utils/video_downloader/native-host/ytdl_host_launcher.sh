#!/bin/bash
# Launcher for the RYA.AE YT Downloader native messaging host.
#
# Chrome starts native hosts with a minimal environment (PATH is typically just
# /usr/bin:/bin:/usr/sbin:/sbin), so Homebrew-installed yt-dlp / ffmpeg / python3
# are NOT on PATH. We restore a sane PATH here, then exec the Python host.

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="$(command -v python3 || echo /opt/homebrew/bin/python3)"

exec "$PYTHON" "$DIR/ytdl_host.py"
