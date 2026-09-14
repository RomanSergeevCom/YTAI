#!/bin/bash
# stop.sh <project_root> — stop прогона на Memex (флаг в ~/.cache/<project>/, стадии читают его на границе экрана).
source "$(dirname "$0")/common.sh"
mx "python3 ~/YTAI/$REL_STAGE/review.py stage --project $MX_ROOT download stop"
