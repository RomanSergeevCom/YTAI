#!/bin/sh
# Wait until 07/13 uploads to Drive finish, then rebuild the page with full
# per-file links and re-upload it (same Drive file ID -> same link).
SP="/private/tmp/claude-501/-Users-romansergeev-YTAI/d7b9b780-4b1e-4455-994c-f2087542beb7/scratchpad"
while pgrep -f "upload_07_20260820\|upload_13_20260820" > /dev/null; do sleep 300; done
sleep 60
cd "$SP" || exit 1
python3 fetch_ids.py >> refresher.log 2>&1
python3 gen_html_v2.py >> refresher.log 2>&1
cp YTFP_structure.html /Volumes/T7-Beige-RYA/YTFP/YTFP_structure.html
rclone copy /Volumes/T7-Beige-RYA/YTFP/YTFP_structure.html \
  --drive-root-folder-id 1ArawQAkQSbxiO6ghDmIiu9-6F0h81KxP gdrive: >> refresher.log 2>&1
echo "refreshed $(date)" >> refresher.log
