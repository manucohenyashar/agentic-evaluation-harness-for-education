"""`TC-CONF-47` (issue #896, FR-CONF-39) — the shipped live profiles: one that can show agreement,
and the smoke profile saying it cannot.

Statistical-validity test plan §3.5 (story T3). Parse `live-test.panel.toml`. Expected:

- three judges from three distinct families;
- three escalation judges;
- `orch_random_arm_rate == 0.07`, with the ~40-cell comment directly above it;
- `live-test.dev-ci.toml`'s header contains "smoke" and "cannot show agreement";
- `docs/live-tests/README.md` and the deployment tutorial name both files.

**Reading the file.** The profile is the one the file's own top-level `HARNESS_PROFILE` selects
(`[profiles.<name>]`), as `effective_config` reads it. A judge's *family* is the vendor segment
of its pinned OpenRouter build (`openrouter/<vendor>/<model>@<date>` → `<vendor>`), the same
reduction `tests/support/live_test_config.openrouter_slug` applies. The header is the leading
comment block of `live-test.dev-ci.toml`, up to its first non-comment line. "The deployment
tutorial" is `docs/tutorials/deployment-tutorial.md` (the plan names one; the help copy under
`src/aeh/help_assets/manuals/` is not asserted).

**Isolation: rung 0** — static parse of shipped files.
**Written ahead of implementation: yes** — S5 (#866) ships `live-test.panel.toml` and the
header; keyed in `WRITTEN_AHEAD_BLOCKERS` on that file's path. Remove the marker (and the entry)
when #866 lands.

Markers. `writtenahead`.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from tests.support.live_test_config import openrouter_slug

pytestmark = pytest.mark.writtenahead

REPO = Path(__file__).resolve().parents[3]
CONFIG_DIR = REPO / "docs" / "live-tests" / "config"
PANEL = CONFIG_DIR / "live-test.panel.toml"
DEV_CI = CONFIG_DIR / "live-test.dev-ci.toml"
NAMING_DOCS = (REPO / "docs" / "live-tests" / "README.md",
               REPO / "docs" / "tutorials" / "deployment-tutorial.md")


def _profile(path: Path) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    name = data.get("HARNESS_PROFILE")
    assert name in data.get("profiles", {}), (
        f"{path.name}: HARNESS_PROFILE {name!r} selects no [profiles.<name>] section")
    return data["profiles"][name]


def _family(build_id: str) -> str:
    return openrouter_slug(build_id).split("/", 1)[0]


def test_tc_conf_47_the_panel_profile_has_three_families_and_three_escalation_judges():
    assert PANEL.is_file(), f"{PANEL.relative_to(REPO)} is not shipped"
    section = _profile(PANEL)

    panel = [judge["build_id"] for judge in section.get("panel", [])]
    assert len(panel) == 3, f"the panel profile has {len(panel)} judge(s): {panel}"
    families = {_family(build) for build in panel}
    assert len(families) == 3, f"three judges, but families {sorted(families)}: {panel}"

    escalation = [judge["build_id"] for judge in section.get("escalation_judge", [])]
    assert len(escalation) == 3, f"{len(escalation)} escalation judge(s): {escalation}"
    assert len(set(escalation)) == 3 and not set(escalation) & set(panel), (
        f"escalation judges must be distinct models, none on the panel: {escalation} / {panel}")


def test_tc_conf_47_the_random_arm_rate_is_0_07_with_the_40_cell_comment_above_it():
    text = PANEL.read_text(encoding="utf-8")
    section = _profile(PANEL)
    rate = section.get("orch_random_arm_rate")
    assert rate == 0.07 and not isinstance(rate, bool), f"orch_random_arm_rate = {rate!r}"

    lines = text.splitlines()
    at = [i for i, line in enumerate(lines) if re.match(r"\s*orch_random_arm_rate\s*=", line)]
    assert len(at) == 1, f"orch_random_arm_rate is set {len(at)} times"
    comment: list[str] = []
    i = at[0] - 1
    while i >= 0 and lines[i].lstrip().startswith("#"):
        comment.insert(0, lines[i])
        i -= 1
    block = " ".join(comment)
    assert comment, "orch_random_arm_rate has no comment directly above it"
    assert re.search(r"\b40\b", block) and "cell" in block.lower(), (
        f"the comment above orch_random_arm_rate does not explain the ~40-cell floor: {block!r}")


def test_tc_conf_47_the_dev_ci_header_calls_it_a_smoke_profile_that_cannot_show_agreement():
    header: list[str] = []
    for line in DEV_CI.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            break
        header.append(line.lstrip("# ").rstrip())
    text = " ".join(part for part in header if part)
    assert "smoke" in text.lower(), f"the dev-ci header does not say smoke: {text[:400]!r}"
    assert "cannot show agreement" in text, (
        f"the dev-ci header does not say it cannot show agreement: {text[:400]!r}")


@pytest.mark.parametrize("doc", NAMING_DOCS, ids=lambda p: p.name)
def test_tc_conf_47_the_readme_and_the_deployment_tutorial_name_both_profiles(doc):
    text = doc.read_text(encoding="utf-8")
    for name in (PANEL.name, DEV_CI.name):
        assert name in text, f"{doc.relative_to(REPO)} does not name {name}"
