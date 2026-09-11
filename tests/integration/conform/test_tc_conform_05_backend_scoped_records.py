"""`TC-CONFORM-05` — the results land in *the package's* validation record, scoped per backend.

Case: test plan §5.18, `FR-CONFORM-05`, R30. Oracle: **exact scoping**.

    | TC-CONFORM-05 | Integration / 2 | A completed conformance run on two backends | Results
    | written into the package validation record scoped to each backend profile and panel build
    | ref, **never merged across them** |

**Written ahead of implementation** (§8.2). Correctly red: the run machinery that produces the
records is `ConformanceSuite.run`, which raises `NotImplementedError` naming #134 after the
consent gate. The blocker is #134 and the test is registered there in `WRITTEN_AHEAD_BLOCKERS`;
remove the marker — never the test — when #134 closes. Rung 2, and not `live`: the scoping this
case asserts is a property of where the results are *written and read back*, and the read side
(`aeh.pkg.validation_for`) is landed and real — the transport plays no part in it.

**How this differs from TS-75's `CT-CONFORM-06`.** Those two cases assert the *write side*: every
written record carries its backend profile and panel build ref, and a write merging two backends
into one record is refused (`MergeRefused`). This file asserts the **read side against the landed
`M-PKG` read** (`FR-PKG-09`): a record that only lives on the report object — never written into
the package registry — passes every shape check and is the exact failure the case names, because
*"the package validation record"* is where a consumer goes to read the figures back. So the
keyed read is driven at each record's own key, and the two refusals that make the scoping exact
are asserted **in type**: the crossed key (`edge` profile asked for under `hosted`'s panel build
ref) answers `NoValidationData`, and the profileless key — the read a pooled record would
satisfy — answers `NoValidationData` too, because no cross-backend aggregate exists to read.
The merge refusal itself is TS-75's `CT-CONFORM-06` case and is not repeated here; the overlap
is reported on the PR.
"""

from __future__ import annotations

import pytest

from aeh.conf import compute_panel_build_ref
from aeh.pkg import NoValidationData, validation_for

from tests.support.conf_builders import EDGE_PANEL_3, HOSTED_PANEL_3, edge_cfg, hosted_cfg
from tests.support.impl import CONFORM_MODULE, require

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

ISSUE = "#134"
CASE = "TC-CONFORM-05"


def _two_backends():
    return [edge_cfg(panel=EDGE_PANEL_3), hosted_cfg(panel=HOSTED_PANEL_3)]


def _synthetic_cohort():
    from aeh.conf import CohortRef

    return CohortRef(cohort_id="c-conform-fixtures", consent_class="synthetic")


def test_tc_conform_05_a_two_backend_run_writes_one_record_per_backend_scope():
    """Two backends, two records, each carrying the full `FR-PKG-08` key — and the right one.

    The count first: two records for two backends, and one record for two backends is the merge
    the requirement refuses. Then the scoping is asserted **against the config**, not against the
    record's own word for itself: a record whose `backend_profile` echoed whatever the report
    carried would pass a self-consistency check while naming no backend at all. So each record's
    profile is compared to the `RunConfig`'s declared profile and its `panel_build_ref` to
    `aeh.conf.compute_panel_build_ref` over that backend's panel — the resolved value, since
    `CT-CONF-07` makes the panel build ref a primary-key component and two runs on one profile
    with different panels are different measurements (R30).
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    records = list(report.validation_records)
    assert len(records) == 2, (
        f"two backends wrote {len(records)} validation record(s). FR-CONFORM-05 scopes the "
        f"result to each backend profile and panel build ref — one record per backend."
    )

    expected = {cfg["HARNESS_PROFILE"]: compute_panel_build_ref(cfg["panel"]) for cfg in _two_backends()}
    seen_scopes = set()
    for record in records:
        # The seven fields of `FR-PKG-08`'s key plus the administration (#118's dimension). A
        # record missing any one of them cannot be read back under `FR-PKG-09`'s declared read,
        # so "written into the package validation record" would be unassertable by construction.
        key_fields = (
            "package_version",
            "criterion",
            "population_scope",
            "backend_profile",
            "panel_build_ref",
            "scoring_model",
            "administration",
        )
        blank = [f for f in key_fields if not getattr(record, f, None)]
        assert not blank, (
            f"a conformance validation record is missing {blank}. FR-PKG-08's key is what makes "
            f"the record readable per backend scope; a record missing part of the key is not "
            f"written into the package record, it is only on the report."
        )
        profile = record.backend_profile
        assert profile in expected, f"a record names {profile!r}, which this run did not run"
        assert record.panel_build_ref == expected[profile], (
            f"the record for {profile!r} names panel build ref {record.panel_build_ref!r}; the "
            f"config's panel resolves to {expected[profile]!r} (CT-CONF-07: the ref is a "
            f"primary-key component, so a wrong value merges two different measurements)"
        )
        seen_scopes.add((profile, record.panel_build_ref))
    assert len(seen_scopes) == 2, (
        f"both records claim the same (backend_profile, panel_build_ref) scope ({seen_scopes}); "
        f"the scoping is nominal and two backends are one record's figures twice."
    )


def test_tc_conform_05_the_keyed_read_answers_per_scope_and_refuses_to_pool():
    """The figures read back under `FR-PKG-09` — per scope, and never as one pooled answer.

    Written into *the package* validation record is the claim; `aeh.pkg.validation_for` is the
    declared read, and the three answers are distinguishable **in type** (`CT-PKG-07`). Three
    assertions, in the order a consumer would hit them:

    * the exact key answers with that record's figures — the figures landed in the package
      registry, not only on the report;
    * the crossed key — one backend's profile asked for under the other's panel build ref —
      answers `NoValidationData`, because no measurement exists at a scope nobody ran;
    * the profileless key — the read a merged record would satisfy — answers `NoValidationData`
      too. There is no cross-backend aggregate to read, which is *"never merged"* from the read
      side: not forbidden at the write, simply absent.
    """
    build_suite = require(CONFORM_MODULE, "build_conformance_suite", issue=ISSUE)
    report = build_suite().run("v1", _two_backends(), cohort=_synthetic_cohort())

    records = list(report.validation_records)
    assert len(records) == 2, "the scoping assertions below need one record per backend"

    exact_answers = {}
    for record in records:
        answer = validation_for(
            package_version=record.package_version,
            population_scope=record.population_scope,
            backend_profile=record.backend_profile,
            panel_build_ref=record.panel_build_ref,
            criterion=record.criterion,
            scoring_model=record.scoring_model,
            administration=record.administration,
        )
        assert isinstance(answer, dict), (
            f"the keyed read at ({record.backend_profile}, {record.panel_build_ref}) answered "
            f"{type(answer).__name__}, not the record's figures. FR-CONFORM-05: the results are "
            f"written into the package validation record — a consumer reads them back there."
        )
        assert answer == dict(record.figure), (
            f"the keyed read at ({record.backend_profile}, {record.panel_build_ref}) returned "
            f"figures that are not the record's own ({answer} vs {dict(record.figure)}). A "
            f"record whose read-back disagrees with its write is not a record, it is a rumour."
        )
        exact_answers[record.backend_profile] = answer

    assert len(exact_answers) == 2, (
        f"both exact keys answered from the same record ({exact_answers}); the scoping has "
        f"collapsed"
    )

    first, second = records
    crossed = validation_for(
        package_version=first.package_version,
        population_scope=first.population_scope,
        backend_profile=first.backend_profile,
        panel_build_ref=second.panel_build_ref,
        criterion=first.criterion,
        scoring_model=first.scoring_model,
        administration=first.administration,
    )
    assert isinstance(crossed, NoValidationData), (
        f"the crossed scope ({first.backend_profile} under {second.panel_build_ref}) answered "
        f"{type(crossed).__name__}. No run measured that scope; only a merged or mis-keyed write "
        f"could answer it, and FR-CONFORM-05 forbids both."
    )

    pooled_read = validation_for(
        package_version=first.package_version,
        population_scope=first.population_scope,
        criterion=first.criterion,
        scoring_model=first.scoring_model,
        administration=first.administration,
    )
    assert isinstance(pooled_read, NoValidationData), (
        f"reading without a backend scope answered {type(pooled_read).__name__}. 'Never merged "
        f"across them' means no record answers for two backends — the profileless read is the "
        f"one a merged record would satisfy, and it must have nothing to say."
    )