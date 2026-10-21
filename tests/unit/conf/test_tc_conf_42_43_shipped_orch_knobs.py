"""TC-CONF-42 and TC-CONF-43 (issue #818) — the shipped files carry the orchestration knobs, and
`HARNESS_KEYS` stays six.

Console-clarity test plan §3.1 (story T5).

- **TC-CONF-42** (FR-CONF-37): `docs/live-tests/config/live-test.dev-ci.toml` and
  `config/harness.example.toml`'s dev-ci section set `orch_escalation_budget = 1.0` and
  `orch_random_arm_rate = 0`, each with a comment line directly above it; and the deployment and
  operating tutorials (in `docs/tutorials` and `src/aeh/help_assets/manuals`) carry no
  `$env:HARNESS_ORCH_ESCALATION_BUDGET` / `$env:HARNESS_ORCH_RANDOM_ARM_RATE` line. The knob
  tables in the deployment tutorials still list `HARNESS_ORCH_ESCALATION_BUDGET` as a name, which
  is legitimate; only a `$env:` line telling a teacher to set it is refused.
- **TC-CONF-43** (FR-CONF-36): `len(HARNESS_KEYS) == 6`, and neither knob — by its file key or
  its environment name — is in it (guards the base plan's six-key sweep).

Rung 0, static.

Markers. None (fast tier).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from aeh.conf import HARNESS_KEYS
from aeh.conf.orch_knobs import (
    ESCALATION_BUDGET_ENV_KEY,
    ESCALATION_BUDGET_FILE_KEY,
    ORCH_KEYS,
    RANDOM_ARM_RATE_ENV_KEY,
    RANDOM_ARM_RATE_FILE_KEY,
)

REPO = Path(__file__).resolve().parents[3]
SHIPPED = {
    "live-test.dev-ci.toml": REPO / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml",
    "harness.example.toml": REPO / "config" / "harness.example.toml",
}
TUTORIALS = (
    REPO / "docs" / "tutorials" / "deployment-tutorial.md",
    REPO / "docs" / "tutorials" / "operating-tutorial.md",
    REPO / "src" / "aeh" / "help_assets" / "manuals" / "deployment-tutorial.md",
    REPO / "src" / "aeh" / "help_assets" / "manuals" / "console-operating-tutorial.md",
)
EXPECTED = {ESCALATION_BUDGET_FILE_KEY: 1.0, RANDOM_ARM_RATE_FILE_KEY: 0}
ENV_LINE = re.compile(r"\$env:(HARNESS_ORCH_ESCALATION_BUDGET|HARNESS_ORCH_RANDOM_ARM_RATE)\b")


def _dev_ci_lines(text: str) -> list[str]:
    """The lines of the `[profiles.dev-ci]` table itself, up to the next table header."""
    lines = text.splitlines()
    start = lines.index("[profiles.dev-ci]")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    return lines[start + 1:end]


@pytest.mark.parametrize("name", sorted(SHIPPED))
def test_tc_conf_42_shipped_dev_ci_sets_the_knobs_with_a_comment(name):
    text = SHIPPED[name].read_text(encoding="utf-8")
    section = tomllib.loads(text)["profiles"]["dev-ci"]
    for key, value in EXPECTED.items():
        assert key in section, f"{name}'s dev-ci section does not set {key}"
        assert section[key] == value and not isinstance(section[key], bool), (
            f"{name}: {key} = {section[key]!r}, expected {value!r}")

    lines = _dev_ci_lines(text)
    for key in EXPECTED:
        at = [i for i, line in enumerate(lines) if re.match(rf"{key}\s*=", line)]
        assert len(at) == 1, f"{name}: {key} appears {len(at)} times in the dev-ci table"
        assert at[0] > 0 and lines[at[0] - 1].lstrip().startswith("#"), (
            f"{name}: {key} has no comment line directly above it")


@pytest.mark.parametrize("path", TUTORIALS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_tc_conf_42_tutorials_have_no_orch_env_line(path):
    hits = [line for line in path.read_text(encoding="utf-8").splitlines() if ENV_LINE.search(line)]
    assert hits == [], f"{path.name} still tells the operator to set an orchestration knob: {hits}"


def test_tc_conf_43_harness_keys_stays_six():
    assert len(HARNESS_KEYS) == 6, HARNESS_KEYS
    for name in (ESCALATION_BUDGET_FILE_KEY, RANDOM_ARM_RATE_FILE_KEY,
                 ESCALATION_BUDGET_ENV_KEY, RANDOM_ARM_RATE_ENV_KEY, *ORCH_KEYS):
        assert name not in HARNESS_KEYS, f"{name} was added to HARNESS_KEYS"
