#!/usr/bin/env bash
# The fast tier. This is what `TEST_CMD` in .claude/settings.json points at, so it is also
# what the Stop-hook verification gate runs.
#
#   ./scripts/test.sh              # the fast tier (test-plan §4.7)
#   ./scripts/test.sh -m contract  # any other tier — arguments pass straight through
#
# Exists so TEST_CMD stays one portable string: the venv interpreter lives at
# .venv/Scripts/python on Windows and .venv/bin/python everywhere else.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 2

if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "error: no Python found. Create the dev environment first:" >&2
  echo "  python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt" >&2
  exit 2
fi

if ! "$PY" -c "import pytest" >/dev/null 2>&1; then
  echo "error: pytest is not installed in $PY. Run:" >&2
  echo "  $PY -m pip install -r requirements-dev.txt" >&2
  exit 2
fi

# The fast tier, from test-plan §4.7, plus `not writtenahead`.
#
# §4.7's string is `pytest -q -m "not integration and not live and not slow and not perf"`.
# The one extra clause here is this repo's answer to a real conflict: §8.2 says every test story lands RED
# (written ahead of its implementation), and the Stop hook blocks the turn whenever TEST_CMD
# fails — so the unmodified string would block every turn from the first test story until the
# last implementation story.
#
# `writtenahead` resolves it without weakening anything: the gate runs everything that should
# be green today, and each written-ahead test drops its marker — never the test — when its
# implementing issue closes. That is what makes this gate tighten over time instead of
# quietly staying narrow. `pytest -q` with no marker filter is the honest full picture and is
# what a PR reports.
DEFAULT_MARKERS='not integration and not live and not slow and not perf and not writtenahead'

if [ "$#" -gt 0 ]; then
  exec "$PY" -m pytest -q "$@"
fi
exec "$PY" -m pytest -q -m "$DEFAULT_MARKERS"
