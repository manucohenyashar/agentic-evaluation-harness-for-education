#!/bin/bash
# Stop hook: enforce "don't stop until the tests pass" — but only when
# there's actually code to verify, so ordinary Q&A/planning turns aren't
# blocked by an unrelated failing test suite.
#
# Exit 2  -> Claude Code feeds stderr back to Claude and keeps the turn going
# Exit 0  -> the turn is allowed to end
# (Claude Code caps this at 8 consecutive blocks, so a genuinely stuck loop
# can't run forever.)

set -uo pipefail

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if [ -z "$(git status --porcelain)" ]; then
    # Nothing changed since the last commit — nothing to verify.
    exit 0
  fi
fi

TEST_CMD="${TEST_CMD:-}"
if [ -z "$TEST_CMD" ]; then
  echo "No TEST_CMD set in .claude/settings.json 'env'. Skipping the verification gate — set it to enable this check." >&2
  exit 0
fi

OUTPUT=$(eval "$TEST_CMD" 2>&1)
STATUS=$?

if [ $STATUS -ne 0 ]; then
  echo "Verification failed: '$TEST_CMD' exited $STATUS. Fix the failures below before finishing:" >&2
  echo "$OUTPUT" | tail -n 100 >&2
  exit 2
fi

exit 0
