"""`TC-JUDGE-C04` — the declared band set is the only answerable vocabulary (§6.11.10).

`CT-JUDGE-04`: *"Bands are supplied as an ordered list of `{band, descriptor}` pairs
from `criterion_band`, even in number. A returned `band` not in that set is rejected
as a contract violation — retried, then quarantined — and never mapped, rounded, or
defaulted."* The case's three steps, as implemented here:

1. **the supplied set** — the bands a fully-assembled request carries are the
   package's declared rows in ordinal order, even in number, each descriptor
   riding beside its own label; the rendered `bands` field presents exactly
   those label+descriptor pairs and carries NO digit and no points token
   (`FR-JUDGE-04`'s presentation surface: "a band's points render nowhere" —
   the points scale is the package tier's alone);
2. **the three tempting repairs, individually, refused** through the real
   dispatch boundary over a real store-backed request: nearest-match mapping
   (`"emergng"`, one keystroke from a declared label), ordinal coercion (a bare
   `2` as the reply's band), and defaulting (`"excellent"`, a band the set
   never declared). Each is retried to the strike budget and then
   `JudgmentError`; the refusal message NAMES the declared set (or, for the
   non-string reply, the type gate that refused the coercion), so the failure
   diagnoses itself;
3. **nothing persisted, nothing repaired** — no verdict row exists for the
   refused work, and the same broken reply came back unchanged on every
   attempt (the transport's call count IS the retry contract); while over a
   judged drive every persisted verdict names a declared band with its
   declared ordinal beside it — the rows a consumer reads are always inside
   the set.

Cross-references, not duplicates: the shipped rung-2 file
`tests/artifact/test_judge_band_forcing.py` (ADV-02) drives the band-forcing
ATTACK — a reply forced toward an undeclared band; this file is the clause's
contract form: the set's shape on the request, the three repair strategies swept
individually with the persisted-store aftermath, and the rows' membership.

Isolation: rung 0/2 — the shape half reads the real store; the repair sweep
drives the real worker against a transport double at the model boundary, and
the socket guard is autouse.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.contract.judge._drive import (
    PANEL_REFS,
    RecordingTransport,
    drive_extract,
    drive_judged_run,
    lease_score_units,
    seed_world,
    spans,
    verdict_rows,
)
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import fields_of
from tests.support.extract_vocabulary import verdict_completion

pytestmark = [pytest.mark.contract]

#: The story that owns the band contract (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: ORCH_MAX_ATTEMPTS — the strike budget a contract violation is retried to before
#: quarantine. Asserted as the transport's call count, never weakened.
_BUDGET = 3


def _catalog_bands(store: Any, criterion_id: str) -> tuple[tuple[str, int, str], ...]:
    """The criterion's declared band set as the PACKAGE holds it — the real catalog
    read, in ordinal order, not the test's own tuple."""
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    return tuple(
        (str(row["band"]), int(row["ordinal"]), str(row["descriptor"]))
        for row in catalog.bands(criterion_id)
    )


def _broken_reply(band: Any) -> Any:
    """A `Completion` whose reply's `band` is the injected value — built by hand
    because `verdict_completion` types the band as a string. Every other field is
    the canonical shape with a VALID cited span, so the only contract failure under
    test is the band's."""
    Completion = require("aeh.prov", "Completion", issue="#78")
    reply = {
        "cited_spans": spans(),
        "evidence_assessment": "the cited spans support the band",
        "evidence_sufficient": True,
        "band": band,
        "self_confidence": 0.9,
    }
    return Completion(
        text=json.dumps(reply),
        tokens_in=0, tokens_out=0, latency_ms=0,
        resolved_build="build-judge-contract",
        cached_prefix_tokens=0, cost=None,
    )


def test_tc_judge_c04_bands_supplied_as_ordered_pairs_even_in_number(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C04` step 1 (`CT-JUDGE-04`, surface assertion, rung 2, P0) — over a
    real seeded package, the request's bands are the catalog's rows in ordinal
    order, EVEN in number; and the rendered bands field is the label+descriptor
    presentation the clause pins — no digit, no points token (a band's points
    render nowhere)."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        orchestrator, _run_id, _version = seed_world(store)
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        unit = units[0]
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, PANEL_REFS[0]
        )
        request = worker.assemble(unit)

        declared = _catalog_bands(store, "C1")
        assert len(declared) % 2 == 0, (
            f"the package declared {len(declared)} bands — the declared set is EVEN "
            "in number, which removes the safe middle band a hesitant judge "
            "retreats to (CT-JUDGE-04)"
        )
        supplied = [
            (view.band, view.ordinal, view.descriptor)
            for view in request.criterion.bands
        ]
        assert supplied == list(declared), (
            f"the assembled bands are {supplied}, the package declared {list(declared)} "
            "— bands are supplied as an ORDERED list of `{band, descriptor}` pairs "
            "from criterion_band, not resorted, not stripped of descriptors "
            "(CT-JUDGE-04, FR-JUDGE-04)"
        )

        rendered = dict(fields_of(require(JUDGE_MODULE, "prompt_fields", issue=ISSUE), request))
        bands_field = rendered["bands"]
        for band, _ordinal, descriptor in declared:
            assert band in bands_field, (
                f"the rendered bands field omits the declared label {band!r} — "
                "the judge can only answer in a vocabulary it was shown (CT-JUDGE-04)"
            )
            assert descriptor in bands_field, (
                f"the rendered bands field omits {band!r}'s descriptor — each "
                "descriptor rides beside its own label (CT-JUDGE-04, FR-JUDGE-04)"
            )
        digits = [ch for ch in bands_field if ch.isdigit()]
        assert digits == [], (
            f"the rendered bands field carries digit(s) {digits} — no digit ordinal "
            "renders into a rubric surface, and a band's points render nowhere "
            "(CT-JUDGE-04, FR-JUDGE-04)"
        )
        assert "points" not in bands_field.lower(), (
            "the rendered bands field names a points scale — bands are supplied as "
            "`{band, descriptor}` pairs, not points (CT-JUDGE-04)"
        )
    finally:
        store.close()


def test_tc_judge_c04_a_band_outside_the_set_is_retried_then_refused(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C04` step 2 (`CT-JUDGE-04`, exact rejection per repair strategy,
    rung 2, P0) — the three tempting repairs swept individually through the real
    dispatch boundary: nearest-match mapping, ordinal coercion, and defaulting.
    Each is retried to the strike budget, then `JudgmentError` — and the refusal
    names the declared set (or the type gate), so the failure diagnoses itself."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        orchestrator, run_id, _version = seed_world(store)
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        unit = units[0]
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, PANEL_REFS[0]
        )
        request = worker.assemble(unit)
        declared = sorted(view.band for view in request.criterion.bands)

        JudgmentError = require(JUDGE_MODULE, "JudgmentError", issue=ISSUE)
        repairs = (
            ("nearest-match mapping", "emergng", "outside the criterion's declared set"),
            ("ordinal coercion", 2, "must be a non-empty string"),
            ("defaulting to an undeclared band", "excellent",
             "outside the criterion's declared set"),
        )
        for label, band, refused_by in repairs:
            transport = RecordingTransport(_broken_reply(band))
            bound = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, transport, PANEL_REFS[0]
            )
            with pytest.raises(JudgmentError) as raised:
                bound.dispatch(request, PANEL_REFS[0])
            message = str(raised.value)
            assert "refused after 3 attempt(s)" in message, (
                f"the {label} refusal ({band!r}) surfaced {message!r} — a contract "
                "violation is retried to the strike budget, then quarantined "
                "(CT-JUDGE-04)"
            )
            assert refused_by in message, (
                f"the {label} refusal for {band!r} does not carry the expected "
                f"refusal ({refused_by!r}): {message!r} — a contract refusal must "
                "diagnose itself (CT-JUDGE-04)"
            )
            if isinstance(band, str):
                for name in declared:
                    assert name in message, (
                        f"the refusal for {band!r} does not name the declared set "
                        f"member {name!r}: {message!r} — the message carries the "
                        "declared set so the reply can be corrected against it "
                        "(CT-JUDGE-04)"
                    )
            assert len(transport.calls) == _BUDGET, (
                f"the {label} repair was retried {len(transport.calls)} time(s), not "
                f"the strike budget {_BUDGET} (CT-JUDGE-04)"
            )
            rows = verdict_rows(store, run_id, unit.submission_id, unit.criterion_id)
            assert rows == [], (
                f"the {label} repair ({band!r}) left {len(rows)} persisted verdict "
                "row(s) — a band outside the declared set is refused, never mapped, "
                "rounded, or defaulted (CT-JUDGE-04)"
            )
    finally:
        store.close()


def test_tc_judge_c04_every_persisted_verdict_names_a_declared_band(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C04` step 3 (`CT-JUDGE-04`, the consumer's right, rung 2, P0) — over
    a judged drive, every persisted verdict names a band from the criterion's
    declared set with its declared ordinal beside it: the rows a consumer reads
    are always inside the vocabulary the package declared."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        _orchestrator, run_id, _version = drive_judged_run(store, provider)
        declared = _catalog_bands(store, "C1")
        assert len(declared) % 2 == 0, (
            "fixture bug: the judged drive's criterion does not carry an even band "
            "set (CT-JUDGE-04)"
        )
        rows = verdict_rows(store, run_id, "SYN-001", "C1")
        assert rows, "fixture bug: the judged drive persisted no verdicts"
        for row in rows:
            assert (row["band"], row["band_ordinal"]) in [
                (band, ordinal) for band, ordinal, _d in declared
            ], (
                f"persisted verdict {row['verdict_id'][:12]} names "
                f"({row['band']!r}, {row['band_ordinal']}) — not a declared "
                f"(band, ordinal) pair {declared}: a consumer's right is to read "
                "only declared bands (CT-JUDGE-04)"
            )
    finally:
        store.close()