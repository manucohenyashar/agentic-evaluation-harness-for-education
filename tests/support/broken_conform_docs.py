"""Positive controls for `conform_vocabulary`'s two configuration rules.

`TC-CONFORM-C08` and `TC-CONFORM-C11` assert against test plan §4.7's suite table, and
`TC-CONFORM-C14` asserts across three passages in two documents. All of those assertions are
green today, which is the dangerous kind of green: a rule that stopped firing — a reworded row, a
locator that no longer matches, a substring that is now always present for an unrelated reason —
looks exactly like a rule that is passing.

TS-57 measured that failure directly. Its SQL scan asserted only that a planted row was flagged;
stubbing `_looks_like_sql` to `False` disabled four of six rules and every row stayed green,
because containment is satisfied by any single rule firing.

So each document below is the real one with **one specific thing wrong**, and the control asserts
the rule fires by **name**. `BROKEN_PLAN_TIER_TABLE` gets every tier-wiring rule at once and the
per-rule variants isolate them, so a rule can neither pass by accident nor be silently deleted.
"""

from __future__ import annotations

# --- §4.7's suite table ------------------------------------------------------------------------
#
# The shape of the real table, trimmed to the two rows the rule reads. Cells are transcribed from
# test plan §4.7 so the control is a realistic near-miss rather than a strawman: a rule that only
# rejects nonsense proves nothing about a table someone edited in good faith.

_GOOD_FAST_TIER_ROW = (
    '| Unit + artifact assertion | `pytest -q -m "not integration and not live and not slow"` '
    "| every push | < 90 s |"
)
_GOOD_CONFORMANCE_ROW = (
    "| Conformance (`M-CONFORM`, per backend) "
    "| `python -m harness.conform --fixture-set <v> --backends <a,b>` "
    "| on any panel/model/template change (`FR-CONFORM-07`) | < 60 min per backend |"
)

_HEADER = "| Suite | Command | Runs in | Duration budget |\n|---|---|---|---|"


def _table(*rows: str) -> str:
    return "\n".join([_HEADER, *rows]) + "\n"


#: The control the case asserts against: every tier-wiring rule violated at once.
#:
#: The conformance suite has been wired to **every push** — which is the exact thing
#: `FR-CONFORM-07` forbids and the reason `CT-CONFORM-08` makes the tier distinction contract —
#: its trigger no longer cites the requirement, its duration budget is gone, and the fast tier now
#: admits the live tier so it needs a live model.
BROKEN_PLAN_TIER_TABLE = _table(
    '| Unit + artifact assertion | `pytest -q -m "not integration and not slow"` '
    "| every push | < 90 s |",
    "| Conformance (`M-CONFORM`, per backend) "
    "| `python -m harness.conform --fixture-set <v> --backends <a,b>` "
    "| every push | advisory |",
)

#: `scripts/test.sh` with the fast tier's live exclusion dropped and the conformance entry point
#: wired into it — the two halves of `CT-CONFORM-08` that live in the script rather than the table.
BROKEN_TEST_SH = (
    "DEFAULT_MARKERS='not integration and not slow and not writtenahead'\n"
    'exec "$PY" -m pytest -q -m "$DEFAULT_MARKERS" && "$PY" -m harness.conform\n'
)

#: The **near-miss**, and the one that mattered: the live exclusion is gone from the marker string
#: that is actually executed, but the comment above it still quotes §4.7's string verbatim — which
#: is how the real `scripts/test.sh` is written. Review measured a whole-file substring check
#: staying green on exactly this, and the comment is precisely the text nobody updates when they
#: change the markers.
TEST_SH_WITH_LIVE_ONLY_IN_A_COMMENT = (
    "# The fast tier, from test-plan §4.7, plus `not writtenahead`.\n"
    "#\n"
    '# §4.7\'s string is `pytest -q -m "not integration and not live and not slow"`. The extra\n'
    "# clause is this repo's answer to a real conflict.\n"
    "DEFAULT_MARKERS='not integration and not slow and not writtenahead'\n"
    'exec "$PY" -m pytest -q -m "$DEFAULT_MARKERS"\n'
)

#: The table with the conformance row deleted outright. Separated from the row above because the
#: two failures are different findings: a row wired wrongly is a configuration defect, a row that
#: is gone means the locator is asserting about nothing and every rule built on it is vacuous.
PLAN_TABLE_WITHOUT_CONFORMANCE = _table(_GOOD_FAST_TIER_ROW)

#: The table with the fast-tier row deleted. Same reasoning from the other side.
PLAN_TABLE_WITHOUT_FAST_TIER = _table(_GOOD_CONFORMANCE_ROW)

#: A table with **two** conformance rows — the ambiguity `find_row` refuses rather than resolving.
#: Silently taking the first would make the assertion about whichever row sorted first, and a
#: reader of the failure could not tell which one it meant.
PLAN_TABLE_WITH_DUPLICATE_CONFORMANCE = _table(
    _GOOD_FAST_TIER_ROW, _GOOD_CONFORMANCE_ROW, _GOOD_CONFORMANCE_ROW
)

#: The correct table, so the control can show the rule stays silent on a good document. Without
#: this half the rule could be `return ALL_PROBLEMS` and both other assertions would pass.
GOOD_PLAN_TIER_TABLE = _table(_GOOD_FAST_TIER_ROW, _GOOD_CONFORMANCE_ROW)

GOOD_TEST_SH = (
    "DEFAULT_MARKERS='not integration and not live and not slow and not writtenahead'\n"
    'exec "$PY" -m pytest -q -m "$DEFAULT_MARKERS"\n'
)


# --- CT-CONFORM-14's hole ----------------------------------------------------------------------
#
# The day the statistic is declared, this case is supposed to be **deleted** (§6.11.18). These
# controls are what makes that day visible: each is the document as it would read once the hole
# was closed, and the rule must name which of the three passages moved.

#: Both design passages as they read today.
GOOD_DESIGN_HOLE = (
    "| CT-CONFORM-14 | behaviour | **Not promised, and it is currently a hole:** \"material\" "
    "divergence in a score distribution has no declared statistic or threshold (`TBD`, §4.6 item "
    "2). CT-CONFORM-05's first gate is therefore **not computable as written**. |\n"
    "2. **What counts as a \"material\" divergence between backends.** FR-CONFORM-06 declares a "
    "gate with no statistic and no threshold.\n"
)

#: The clause rewritten as though the statistic had been declared — the gate now fires, so the
#: case has outlived its subject.
DESIGN_HOLE_CLOSED = (
    "| CT-CONFORM-14 | behaviour | A score-distribution divergence exceeding the declared "
    "threshold blocks sharing a validation record. |\n"
    "2. **What counts as a \"material\" divergence between backends.** Resolved in v1.5: the "
    "declared statistic is the two-sample Kolmogorov-Smirnov D at 0.15.\n"
)

#: The clause kept but its uncomputability claim dropped — the subtler half, and the one a
#: substring check on `CT-CONFORM-14` alone would miss.
DESIGN_CLAUSE_NO_LONGER_UNCOMPUTABLE = (
    "| CT-CONFORM-14 | behaviour | **Not promised:** consumers must not assume equivalence. |\n"
    "2. **What counts as a \"material\" divergence between backends.** FR-CONFORM-06 declares a "
    "gate with no statistic and no threshold.\n"
)

#: Both plan passages as they read today: §7.4's gap row and §4.8's release-gate exclusion.
GOOD_PLAN_HOLE = (
    "| `FR-CONFORM-06` — the divergence gate (Q-02) | No statistic and no threshold are "
    "declared, so the gate is not computable | The evidence-integrity-rate half **is** computable "
    "and is gated; **Accepted risk** until a statistic and threshold are declared |\n"
    "**What explicitly does not gate a release**: `NFR-SYS-08`, any absolute κ value, and "
    "`FR-CONFORM-06`'s divergence gate (Q-02, not computable as written).\n"
)

#: §7.4's row rewritten as managed rather than accepted — the gap register no longer says the
#: gate cannot fire.
PLAN_GAP_ROW_CLOSED = (
    "| `FR-CONFORM-06` — the divergence gate (Q-02) | Resolved in plan v1.6 | The declared "
    "statistic is gated on both halves. **Managed** |\n"
    "**What explicitly does not gate a release**: `NFR-SYS-08`, any absolute κ value, and "
    "`FR-CONFORM-06`'s divergence gate (Q-02, not computable as written).\n"
)

#: §4.8's exclusion dropped while §7.4 still carries the gap — the two documents disagreeing, which
#: is the state in which a release decision could reasonably reach for a gate that cannot fire.
#:
#: **Carries a decoy**, because the real document always does: `not computable as written` occurs
#: five times in `test-plan.md`, and one of them is `TC-CONFORM-C14`'s own row in §6.11.18 — this
#: suite's own specification, which survives exactly the edit the rule is meant to detect. Review
#: measured the unscoped rule never firing against the real plan. The row below is that decoy, so
#: this control now proves the rule reads §4.8's own sentence rather than the whole document.
PLAN_RELEASE_GATE_EXCLUSION_DROPPED = (
    "| TC-CONFORM-C14 | CT-CONFORM-14 | behaviour | The gate is **not computable as written**, so "
    "the case asserts the hole rather than concealing it. |\n"
    "| `FR-CONFORM-06` — the divergence gate (Q-02) | No statistic and no threshold are "
    "declared, so the gate is not computable | The evidence-integrity-rate half **is** computable "
    "and is gated; **Accepted risk** until a statistic and threshold are declared |\n"
    "**What explicitly does not gate a release**: `NFR-SYS-08` and any absolute κ value.\n"
)


# --- CT-CONFORM-10's enforcement-location controls ----------------------------------------------
#
# `consent_reimplementation_sites` scans `aeh.conform`'s source for a second consent check. Until
# #133 lands there is no source to scan, so without these two the rule would sit unexercised for
# two phases and nobody would know whether it worked. Both are module sources, parsed by the same
# function the case uses.

#: A conformance module that **delegates**: it reads `consent_class`, hands the cohort to `M-CONF`
#: and lets `ConsentGateError` propagate. This is the shape the clause requires, and the scan must
#: stay silent on it — a rule that flagged this would fail every correct implementation.
#:
#: Deliberately mentions `consent_class` four times and imports `CONSENTED_CLASSES` by name, since
#: a naive scan keyed on the *word* rather than on the *decision* would condemn all of that.
DELEGATING_CONFORM_SOURCE = '''
from aeh.conf import CONSENTED_CLASSES, ConsentGateError, resolve_run_config


def run(fixture_set_v, backends, cohort):
    """Consent is M-CONF's decision; this module only records what it was told."""
    report = {"consent_class": cohort.consent_class, "allowed": sorted(CONSENTED_CLASSES)}
    for backend in backends:
        # No check here. `resolve_run_config` refuses, and `ConsentGateError` is not caught.
        report[backend] = resolve_run_config(backend, cohort)
    return report


def describe_consent(cohort):
    return f"cohort {cohort.cohort_id} is flagged {cohort.consent_class}"
'''

#: The same module with the gate copied in — the drift `CT-CONFORM-10` forbids. Three shapes,
#: because an implementer reaches for whichever reads best and a scan that caught only `==` would
#: pass the other two.
REIMPLEMENTING_CONFORM_SOURCE = '''
from aeh.conf import resolve_run_config


def run(fixture_set_v, backends, cohort):
    if cohort.consent_class == "real":
        raise RuntimeError("refusing to run against unconsented work")
    return [resolve_run_config(b, cohort) for b in backends]


def _eligible(cohort):
    return cohort.consent_class in ("synthetic", "consented")


def _reversed(cohort):
    return "synthetic" == cohort.consent_class
'''

#: **The shapes the first version of the scan walked straight through.**
#:
#: Review measured five realistic re-implementations against a rule that inspected only `Compare`
#: nodes holding a string literal; all five returned no sites. Each is kept here as its own named
#: control, because a control fitted to the rule — three shapes the rule already handled — reads as
#: thorough and measures nothing. The first entry is the one that matters most: it is the shape a
#: careful implementer writes, since importing `M-CONF`'s own constant *looks* like delegation.
EVASIVE_REIMPLEMENTATIONS: dict[str, str] = {
    "imported constant": '''
from aeh.conf import CONSENTED_CLASSES


def run(fixture_set_v, backends, cohort):
    if cohort.consent_class not in CONSENTED_CLASSES:
        raise RuntimeError("refusing")
''',
    "locally bound set": '''
_OK = {"synthetic", "consented"}


def run(fixture_set_v, backends, cohort):
    if cohort.consent_class not in _OK:
        raise RuntimeError("refusing")
''',
    "match statement": '''
def run(fixture_set_v, backends, cohort):
    match cohort.consent_class:
        case "real":
            raise RuntimeError("refusing")
        case _:
            return True
''',
    "decision table": '''
def run(fixture_set_v, backends, cohort):
    allowed = {"real": False, "synthetic": True, "consented": True}
    if not allowed[cohort.consent_class]:
        raise RuntimeError("refusing")
''',
    "string predicate": '''
def run(fixture_set_v, backends, cohort):
    if cohort.consent_class.startswith("real"):
        raise RuntimeError("refusing")
''',
}
