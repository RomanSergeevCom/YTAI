#!/bin/bash
# 0500_uxp pre-commit gate — the panel's rules, enforced at commit time.
#
# Why: the gates (lint + tests + contracts) only help if they actually run.
# Before this, `npm test` was a thing one had to remember (TICKET_uxp_audit,
# completeness review 25.09.2026). Acts ONLY when the commit touches
# scripts/05_editing/0500_uxp/; every other commit passes untouched.
#
#   1. panel code changed (index.js, index.html, src/**) → src/shared/version.js
#      must change in the same commit (Roman sees the loaded code by the header);
#   2. `npm test` must be green (eslint --max-warnings 0 + tests + contracts).
#
# Note: npm test runs on the working tree, not on the staged snapshot.
# Install (once per clone):   bash scripts/05_editing/0500_uxp/tools/pre-commit.sh --install
# Bypass (deliberate only):   git commit --no-verify

P=scripts/05_editing/0500_uxp
ROOT=$(git rev-parse --show-toplevel) || exit 1
cd "$ROOT" || exit 1

if [ "$1" = "--install" ]; then
  HOOK="$ROOT/.git/hooks/pre-commit"
  if [ -e "$HOOK" ] && ! grep -q "0500_uxp/tools/pre-commit.sh" "$HOOK"; then
    echo "A different pre-commit hook already exists at $HOOK — not overwriting."; exit 1
  fi
  printf '#!/bin/bash\nexec bash "$(git rev-parse --show-toplevel)/%s/tools/pre-commit.sh"\n' "$P" > "$HOOK"
  chmod +x "$HOOK"
  echo "Installed: $HOOK → $P/tools/pre-commit.sh"
  exit 0
fi

STAGED=$(git diff --cached --name-only --diff-filter=ACMRD)
echo "$STAGED" | grep -q "^$P/" || exit 0

CODE=$(echo "$STAGED" | grep -E "^$P/(index\.js|index\.html|src/)" | grep -v "^$P/src/shared/version\.js$")
if [ -n "$CODE" ] && ! echo "$STAGED" | grep -q "^$P/src/shared/version\.js$"; then
  echo "✗ 0500_uxp: panel code changed without a PANEL_VERSION bump in $P/src/shared/version.js:"
  echo "$CODE" | sed 's/^/    /'
  echo "  Every edit to index.js / index.html / src/ bumps the version — otherwise Roman's"
  echo "  next run is indistinguishable from the previous one."
  exit 1
fi

if [ ! -d "$P/node_modules" ]; then
  echo "✗ 0500_uxp: $P/node_modules is missing — run: (cd $P && npm ci)"
  exit 1
fi

LOG=$(mktemp -t 0500_uxp_precommit)
if ! (cd "$P" && npm test --silent >"$LOG" 2>&1); then
  echo "✗ 0500_uxp: npm test failed (lint + tests + contracts). Last lines:"
  tail -30 "$LOG"
  exit 1
fi
echo "✓ 0500_uxp: npm test green ($(grep -E '^ℹ (pass|fail) ' "$LOG" | sed 's/^ℹ //' | tr '\n' ' ' | sed 's/ $//'))"
exit 0
