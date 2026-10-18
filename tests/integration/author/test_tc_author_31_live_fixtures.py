"""`TC-AUTHOR-31` — all thirteen fixtures against real OpenRouter (`@live`, nightly).

Case: test plan §5.6 (`TC-AUTHOR-31`, `FR-AUTHOR-01`, `FR-AUTHOR-05`, `FR-AUTHOR-08`, P0,
rung 4, live tier); design delta §5.2 (tier policy). Issue #702 (TS-169). This file also
carries `PERF-20`'s live limb — the p95 wall-clock assumption (NFR-AUTHOR-02, RISK-129) —
because a wall clock over real models can only be read where the network is; the recorded
half of `PERF-20` lives in `tests/perf/test_perf_20_authoring_recorded_ceilings.py`.

**What is asserted, and what is not.** The live arm asserts **outcome classes** from each
fixture's `expected.toml` — which items resolve, which placeholder, whether the drafted draft
is refused — **never exact wording**: two runs of a real model agree on structure, not prose
(`CT-AUTHOR-17`'s non-promise). The recorded tier (and the corpus census) own the exact
content; this tier exists to re-prove nightly that the classes the corpus pinned still hold
against the real endpoint.

**Gate order, the TS-142 rule.** Each case checks `OPENROUTER_API_KEY` *first* and skips,
naming the tier, when it is unset — a box with no key spends nothing. Only then does it
`require()` the unbuilt surface (`NotImplementedYet` naming #690), and only after that does it
resolve a config or open a socket. The key is never logged, echoed, or asserted on — its
*absence* is the only fact about it any line here states.

**The models.** Read from `docs/live-tests/config/live-test.dev-ci.toml`, never hard-coded
(commit 473c23c's rule): the chain resolves through the production path (`panel_for_profile`,
#687) over the operator's file, and the expected names are cross-checked against
`tests/support/live_test_config.py`'s `configured_models` — so an operator editing the file's
model pins re-points this suite without an edit here, and a chain that names a model the file
does not fails loudly before anything is spent.

**`models_used` equals the configured chain — read as containment.** `DraftResult.models_used`
is "in first-use order — a subset of the chain" (§3.1's own field contract): a run whose
fallback never fired names only the head, so literal equality would fail the nightly exactly
when the chain works. The oracle this suite asserts is the issue's own technical note — *the
suite must fail if `models_used` names a model outside the configured chain* — plus first-use
order: every name is a chain member and the names appear in chain order, never reordered.

**The build class.** `build = "refused"` (AF-09, AF-11) is asserted from the draft itself: the
placeholder sentinel the draft carries *is* FR-PKG-28's refusal trigger (a one-line check at
the build gate), so a refused fixture's draft must carry a graded sentinel. `build =
"publishes"` publishes **after review** for the partial fixtures — that draft → review → build
→ grade flow is `TC-AUTHOR-31`'s live-workflow extension (#704), not this file's; for the
resolved fixtures the zero-placeholder draft is exactly what the gate accepts.

**One run per fixture.** The runs are memoised module-level (the TS-142 pattern, started
inside the first test body that needs them, failures cached too), so the outcome-class cases
and the p95 case read the same thirteen live runs — thirteen fixtures against real models is
the nightly's spend, not fourteen or fifteen.
"""

from __future__ import annotations

import math
import os
import re
import time
import tomllib
from pathlib import Path

import pytest

from aeh.conf import parse_config_document
from aeh.conf.panel_profile import panel_for_profile
from tests.support.author_vocabulary import AUTHOR_MODULE, af, make_service
from tests.support.author_vocabulary import LIVE_DEV_CI_CONFIG as DEV_CI_CONFIG
from tests.support.impl import require, require_path
from tests.support.live_test_config import configured_models, openrouter_slug

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.slow,
]

CASE = "TC-AUTHOR-31"
SURFACE_ISSUE = "#690"
CORPUS_ISSUE = "#686"
KEY_ENV = "OPENROUTER_API_KEY"

#: The stated load: the whole corpus (design delta §5.1: AF-01..AF-13).
AF_IDS = tuple(f"AF-{i:02d}" for i in range(1, 14))

#: `PERF-20`'s live limb: the p95 wall-clock assumption (NFR-AUTHOR-02, RISK-129) — under ten
#: minutes. *Assumption, not requirement*: it fails openly on the first nightly run that breaks
#: it, and the knob `HARNESS_AUTHOR_TIMEOUT_S` is re-pinned then — the failure must never be
#: silenced by loosening it in place without saying so (RISK-33).
LIVE_P95_LIMIT_S = 600.0

#: The one placeholder no fixture's outcome class counts: `approved_by` is emitted as a
#: placeholder on **every** draft (FR-AUTHOR-09 — it names the human who approved the work and
#: is never model-generated), and it is filled at review, so it is not a resolution outcome.
#: The sentinel's field name is normalised (`-`/space fold to `_`) before the comparison so a
#: wording variant of the same field does not masquerade as a graded placeholder.
APPROVED_BY_FIELD = "approved_by"

_RUNS: dict[str, dict] = {}


def _require_live_key() -> None:
    """The key gate, first in every case. Skips naming the tier when the key is unset."""
    key = os.environ.get(KEY_ENV, "")
    if not key.strip():
        pytest.skip(
            f"{KEY_ENV} is unset. {CASE} drafts all thirteen authoring fixtures against the "
            f"real OpenRouter endpoint and is nightly-only (E2/E3, test plan §4.7); set the "
            f"key from .env-dev on the nightly box to run it. Nothing here reads or logs the "
            f"key itself."
        )


def _live_chain():
    """The reasoning chain and transcriber, from the operator's file, cross-checked.

    The chain resolves through the production path (`panel_for_profile` over the file, the
    same resolution `aeh author draft` runs — TC-REQ-134's pair); the expected names come from
    `tests/support/live_test_config.py` (`configured_models`), so the two readers of the
    operator's file must agree — a file edit that moves the panel or the transcriber re-points
    both together or fails here, before anything is spent.
    """
    document = parse_config_document(DEV_CI_CONFIG.read_text(encoding="utf-8"), "toml")
    chain = panel_for_profile(document, "dev-ci")
    assert chain, f"{CASE}: {DEV_CI_CONFIG.name} resolves no authoring chain"
    transcriber_slug, judge_slug = configured_models(DEV_CI_CONFIG)
    assert openrouter_slug(chain[0].build_id) == judge_slug, (
        f"{CASE}: the resolved chain's head {chain[0].build_id!r} is not the panel judge "
        f"{judge_slug!r} that {DEV_CI_CONFIG.name} names via "
        f"tests/support/live_test_config.py — the two readers of the operator's file disagree"
    )
    return chain


def _live_provider():
    """The live transport the profile names — the production resolution seam.

    `HARNESS_FIXTURE_DIR` must be unset: a recorded binding here would replay recordings
    against the real endpoint's assertion and call it live (the TS-142 posture).
    """
    assert not os.environ.get("HARNESS_FIXTURE_DIR"), (
        f"{CASE}: HARNESS_FIXTURE_DIR is set, so the provider would replay recordings. The "
        f"live tier binds no recorded fixture (design delta §5.2); unset it on the nightly box."
    )
    from aeh.pipeline.runtime import _provider_for

    return _provider_for({"backend_profile": "dev-ci"})


def _live_draft(af_id: str, tmp_path_factory) -> dict:
    """One live draft per fixture, memoised. Key first, then the blocker, then the network."""
    _require_live_key()
    require(AUTHOR_MODULE, issue=SURFACE_ISSUE)
    require(AUTHOR_MODULE, "AuthoringService", "DraftResult", "AuthoringSettings",
            issue=SURFACE_ISSUE)
    require(AUTHOR_MODULE, "validate_draft", issue="#693")
    require_path(af(af_id), f"the {af_id} authored fixture", issue=CORPUS_ISSUE)

    if af_id in _RUNS:
        entry = _RUNS[af_id]
        if "error" in entry:
            raise entry["error"]
        return entry

    chain = _live_chain()
    provider = _live_provider()
    service = make_service(require(AUTHOR_MODULE, issue=SURFACE_ISSUE), chain, provider)
    started = time.perf_counter()
    try:
        result = service.draft(
            documents=sorted(af(af_id).glob("*.pdf")),
            output_dir=tmp_path_factory.mktemp(f"live-{af_id}"),
        )
    except Exception as error:
        _RUNS[af_id] = {"error": error}
        raise
    elapsed = time.perf_counter() - started
    entry = {
        "result": result,
        "draft_text": result.draft_path.read_text(encoding="utf-8"),
        "elapsed": elapsed,
    }
    _RUNS[af_id] = entry
    return entry


def _normalised(field: str) -> str:
    """A sentinel field name with every non-alphanumeric folded out, for class comparison."""
    return re.sub(r"[^a-z0-9]", "", field.strip().lower())


def _graded_placeholders(draft_text: str) -> list[str]:
    """The sentinel fields a draft carries, minus the always-present `approved_by` one."""
    from tests.support.author_vocabulary import placeholder_fields

    return [
        field
        for field in placeholder_fields(draft_text)
        if _normalised(field) != _normalised(APPROVED_BY_FIELD)
    ]


def _covers_class(observed: list[str], entry: str) -> bool:
    """Whether the observed placeholder fields cover one expected placeholder class.

    The expected entries are the corpus's own naming ("criterion Q4", "model_answer",
    "grades"); the live run's sentinel field is the module's naming of the same gap. The
    oracle is therefore the entry's most specific token (its last), matched over the
    alphanumeric-normalised fields — "which placeholder", not the wording around it
    (`CT-AUTHOR-17`: structure, not prose).
    """
    needle = _normalised(entry.split()[-1])
    return any(needle in _normalised(field) for field in observed)


def _assert_placeholder_classes(expected: dict, observed: list[str], af_id: str) -> None:
    missing = [
        entry for entry in expected.get("placeholders", [])
        if not _covers_class(observed, entry)
    ]
    assert not missing, (
        f"{CASE}: {af_id}'s live draft carries the graded placeholders {observed}, which do "
        f"not cover the outcome class's expected placeholders {missing}. The corpus's "
        f"expected.toml is the oracle — which placeholder — and a live run that leaves a "
        f"different set is a changed outcome class (RISK-122), never silent."
    )


def _assert_models_used_within_chain(models_used, chain, af_id: str) -> None:
    """Every name is a chain member, and the names appear in first-use = chain order."""
    ids = [ref.build_id for ref in chain]
    known = set(ids)
    position = 0
    for model in models_used:
        assert model in known, (
            f"{CASE}: {af_id}'s models_used names {model!r}, which is not in the configured "
            f"chain {ids}. The chain is the run configuration's (FR-AUTHOR-04) — a model "
            f"outside it must fail the nightly, never pass (CT-AUTHOR-06)."
        )
        while position < len(ids) and ids[position] != model:
            position += 1
        assert position < len(ids), (
            f"{CASE}: {af_id}'s models_used {list(models_used)} is not in first-use = chain "
            f"order {ids} — the fallback walks the chain in order or not at all "
            f"(FR-AUTHOR-04/05, CT-AUTHOR-06)."
        )
        position += 1


def _expected(af_id: str) -> dict:
    return tomllib.loads((af(af_id) / "expected.toml").read_text(encoding="utf-8"))


# --- TC-AUTHOR-31: the outcome classes, per fixture -------------------------------------------


@pytest.mark.parametrize("af_id", AF_IDS)
def test_tc_author_31_outcome_classes_hold_on_live_openrouter(af_id, tmp_path_factory):
    """`TC-AUTHOR-31` (P0): the fixture's live draft classifies as `expected.toml` states.

    Per fixture, three class limbs — resolution, placeholders, build:

    * `outcome = "resolved"` — no graded placeholder and no unresolved item: the draft is
      complete, zero sentinels besides `approved_by`.
    * `outcome = "partial"` — no unresolved item, and the named placeholder classes are
      present (AF-13's partial is the carry-over state, which declares no classes, so the
      limb is vacuous there by the corpus's own schema).
    * `outcome = "unresolved"` — at least one item did not converge, and the classes it left
      behind are the corpus's.

    `build = "refused"` — the draft carries a graded sentinel, which is the whole of
    FR-PKG-28's refusal trigger; `build = "publishes"` — a fixture expecting no placeholders
    (resolved ones, and AF-13's partial) must draft sentinel-free, the zero-placeholder draft
    the gate accepts (partial fixtures WITH named placeholders publish after review, which is
    #704's live-workflow extension).
    """
    entry = _live_draft(af_id, tmp_path_factory)
    result = entry["result"]
    expected = _expected(af_id)
    graded = _graded_placeholders(entry["draft_text"])
    unresolved = getattr(result, "unresolved", None)
    assert unresolved is not None, (
        f"{CASE}: DraftResult carries no unresolved count — the outcome class is read off it "
        f"(design delta §3.1's data contract)"
    )
    outcome = expected["outcome"]
    assert outcome in {"resolved", "partial", "unresolved"}, (
        f"{CASE}: {af_id}'s expected.toml outcome {outcome!r} is outside the corpus domain"
    )

    if outcome == "resolved":
        assert not graded and unresolved == 0, (
            f"{CASE}: {af_id} is expected fully resolved — no graded placeholder and no "
            f"unresolved item — but the live draft carries {graded} and "
            f"unresolved={unresolved}. A resolved fixture that no longer resolves is a "
            f"changed outcome class (RISK-122), never silent."
        )
    elif outcome == "partial":
        assert unresolved == 0, (
            f"{CASE}: {af_id} is expected partial — placeholders, nothing unresolved — but "
            f"the live draft recorded unresolved={unresolved}."
        )
        _assert_placeholder_classes(expected, graded, af_id)
    else:  # unresolved
        assert unresolved > 0, (
            f"{CASE}: {af_id} is expected unresolved — the reasoning does not converge "
            f"(AF-09's contradictory grading) — but the live draft recorded "
            f"unresolved={unresolved}. A contradiction the model now 'resolves' is a changed "
            f"outcome class, and the corpus's recording of it is then stale."
        )
        _assert_placeholder_classes(expected, graded, af_id)

    if expected["build"] == "refused":
        assert graded, (
            f"{CASE}: {af_id} is expected refused by the build gate (FR-PKG-28) — the draft "
            f"as drafted must carry a graded placeholder sentinel, and it carries none. A "
            f"sentinel-free draft would publish, which is exactly the incomplete-package "
            f"failure RISK-121 names."
        )
    elif expected["build"] == "publishes" and not expected.get("placeholders"):
        # The buildable-as-drafted class: a fixture whose outcome expects no placeholders
        # (AF-13's partial) must draft sentinel-free — the gate accepts the zero-placeholder
        # draft, so a graded sentinel here means the live run left a gap the corpus's class
        # says does not exist (a changed outcome class, RISK-122, never silent). Partial
        # fixtures WITH named placeholders publish after review (#704's extension) and are
        # exempt — their drafted draft legitimately carries sentinels.
        assert not graded, (
            f"{CASE}: {af_id} is expected to build as drafted (build=publishes, no expected "
            f"placeholders) — the gate accepts a zero-placeholder draft — but the live draft "
            f"carries the graded placeholders {graded}. A sentinel on a class that should be "
            f"sentinel-free is a changed outcome class."
        )
    if outcome == "resolved":
        models_used = tuple(getattr(result, "models_used", None) or ())
        assert models_used, (
            f"{CASE}: {af_id} resolved but models_used is empty — a complete draft was "
            f"produced by some model, and the report must say which (FR-AUTHOR-18)."
        )
    _assert_models_used_within_chain(tuple(getattr(result, "models_used", None) or ()),
                                     _live_chain(), af_id)


# --- PERF-20: the live p95 assumption ---------------------------------------------------------


def test_perf_20_live_p95_wall_clock_fails_openly_if_the_assumption_breaks(tmp_path_factory):
    """`PERF-20` (P0), live limb: the p95 wall clock over the thirteen live drafts is under
    ten minutes — **marked Assumption** (NFR-AUTHOR-02, RISK-129).

    This is the number the design says to verify on the first live run, not a requirement
    someone sourced: a frontier-class reasoning step is *assumed* to be seconds, not minutes.
    The case fails openly — a red nightly naming RISK-129 and the knob to re-pin
    (`HARNESS_AUTHOR_TIMEOUT_S`) — and that open failure is the contract; a silent slowdown
    past the assumption is the trap. Loosening this bound is RISK-33's most-missed breaking
    change and must be an edit to this case, visible in review.
    """
    per_fixture = {af_id: _live_draft(af_id, tmp_path_factory)["elapsed"] for af_id in AF_IDS}
    times = sorted(per_fixture.values())
    # Nearest-rank p95 over the fixture set; with thirteen samples the rank is the maximum.
    p95 = times[max(0, math.ceil(0.95 * len(times)) - 1)]
    assert p95 < LIVE_P95_LIMIT_S, (
        f"{CASE}/PERF-20: the live drafts' p95 wall clock is {p95:.0f}s — the assumption "
        f"(NFR-AUTHOR-02, RISK-129) was under {LIVE_P95_LIMIT_S:.0f}s. The assumption failed "
        f"openly, as designed: re-pin HARNESS_AUTHOR_TIMEOUT_S and re-state the bound in this "
        f"case with the measured figure — never silence the failure. Per-fixture seconds: "
        f"{ {af_id: round(entry, 1) for af_id, entry in per_fixture.items()} }"
    )