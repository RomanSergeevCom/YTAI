#!/bin/bash
# Install the RYA.AE YT Downloader native messaging host for all Chromium-based
# browsers found on this Mac. Idempotent — safe to re-run after edits.
set -euo pipefail

HOST_NAME="ae.rya.ytdl"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="$DIR/ytdl_host_launcher.sh"
HOSTPY="$DIR/ytdl_host.py"
SRC_MANIFEST="$DIR/$HOST_NAME.json"
OVERRIDE_ID="${1:-}"  # optional: pass the ID shown in chrome://extensions

echo "▸ Native host dir: $DIR"
[ -n "$OVERRIDE_ID" ] && echo "▸ Overriding extension ID: $OVERRIDE_ID"

# 1) Make host + launcher executable
chmod +x "$LAUNCHER" "$HOSTPY"

# 2) Write a manifest with the correct absolute launcher path (in case the
#    folder was moved). The allowed_origins / name are taken from the template.
TMP_MANIFEST="$(mktemp)"
python3 - "$SRC_MANIFEST" "$LAUNCHER" "$TMP_MANIFEST" "$OVERRIDE_ID" <<'PY'
import json, sys
src, launcher, out, override = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(src) as f:
    m = json.load(f)
m["path"] = launcher
if override:
    m["allowed_origins"] = [f"chrome-extension://{override}/"]
with open(out, "w") as f:
    json.dump(m, f, indent=2)
PY

# 3) Target browser NativeMessagingHosts dirs (only those that exist)
APP="$HOME/Library/Application Support"
BROWSERS=(
  "Google/Chrome"
  "Google/Chrome Beta"
  "Google/Chrome Canary"
  "Chromium"
  "BraveSoftware/Brave-Browser"
  "Microsoft Edge"
  "Arc"
  "Arc/User Data"
  "Vivaldi"
)

installed=0
for b in "${BROWSERS[@]}"; do
  base="$APP/$b"
  [ -d "$base" ] || continue
  dest="$base/NativeMessagingHosts"
  mkdir -p "$dest"
  cp "$TMP_MANIFEST" "$dest/$HOST_NAME.json"
  echo "  ✓ installed → $b"
  installed=$((installed+1))
done
rm -f "$TMP_MANIFEST"

echo "▸ Installed into $installed browser profile dir(s)."

# 4) Dependency check
echo "▸ Dependency check:"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$HOME/.local/bin:$PATH"
if command -v yt-dlp >/dev/null; then
  echo "  ✓ yt-dlp $(yt-dlp --version)"
else
  echo "  ✗ yt-dlp NOT found — run: brew install yt-dlp"
fi
if command -v ffmpeg >/dev/null; then
  echo "  ✓ ffmpeg $(ffmpeg -version | head -1 | awk '{print $3}')"
else
  echo "  ✗ ffmpeg NOT found — run: brew install ffmpeg"
fi

# 5) Self-test: ping the host through its real launcher (native-message framed)
echo "▸ Self-test (ping host):"
python3 - "$LAUNCHER" <<'PY'
import json, struct, subprocess, sys
launcher = sys.argv[1]
msg = json.dumps({"action": "ping"}).encode()
payload = struct.pack("=I", len(msg)) + msg
p = subprocess.run([launcher], input=payload, capture_output=True, timeout=30)
out = p.stdout
if len(out) < 4:
    print("  ✗ no response from host"); print(p.stderr.decode()[:500]); sys.exit(1)
n = struct.unpack("=I", out[:4])[0]
resp = json.loads(out[4:4+n].decode())
print("  ✓ host responded:", json.dumps(resp, ensure_ascii=False))
PY

echo ""
echo "Done. Extension ID expected: ijmcfiafjlppldgcaldgdeffeanhnbgf"
echo "If the extension shows a different ID in chrome://extensions, re-run with that"
echo "ID, or keep the pinned 'key' in manifest.json (recommended)."
