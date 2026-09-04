"""`CT-STATS-10`, `-11`, `-15`, `-18` — the checks behind the number, and the boundary around them.

Test plan §6.11.16, `TC-STATS-C10`, `-C11`, `-C15`, `-C18`.

`-10` and `-11` are the two checks that exist because a good agreement figure is not evidence of a
good system: a panel and a teacher who both compress to the middle agree beautifully, and a routing
policy that escalates the wrong judgments looks identical to one that escalates the right ones
until somebody compares the two arms on blind labels. Both clauses fix an *interpretation* — the
limitation is in the return value, similar rates are **failing** — and both interpretations are the
part a reasonable implementer would soften.

`-15` and `-18` are the boundary: what this module may write, and what it may read. The write
clause is about **indirection** rather than absence, so its oracle is an attributed write log
rather than a no-writes assertion.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.guards import recording_write_audit
from tests.support.impl import PKG_MODULE, REVIEW_MODULE, STATS_MODULE, STORE_MODULE, require, require_path

pytestmark = pytest.mark.contract


#: Four bands, ten labels each from the teacher and all forty from the panel in the two interior
#: bands. Hand-computed, which is `NFR-STATS-01`'s standing requirement and this case's Oracle:
#:
#:   gold   band_entropy  = log2(4) = 2.0     interior_rate = 20/40 = 0.50
#:   panel  band_entropy  = log2(2) = 1.0     interior_rate = 40/40 = 1.00
#:
#: A uniform teacher against a panel that only ever says "3 or 4 out of 6" is compression in its
#: textbook form, and the numbers are exact rather than approximate because both distributions are
#: uniform over their support.
COMPRESSION_LABELS = [
    broken.Label(label_id=f"cmp-{i}", band=2 + (i % 2), teacher_band=1 + (i % 4))
    for i in range(40)
]
GOLD_BAND_ENTROPY = 2.0
PANEL_BAND_ENTROPY = 1.0
GOLD_INTERIOR_RATE = 0.5
PANEL_INTERIOR_RATE = 1.0


@contextmanager
def sql_trace():
    """Record the SQL a real store actually executes.

    `TC-STATS-C18` asks for the read boundary *"asserted over its actual queries, so a convenience
    join to Tier C fails"* — and at rung 2 the store is real SQLite, so the queries are only
    visible from the connection. `set_trace_callback` is SQLite's own hook for exactly this, which
    keeps the rung the plan names instead of dropping to a spy: a fake store would answer whatever
    the module asked it, and the join this case exists to catch is one a fake would happily serve.
    """
    statements: list[str] = []
    real_connect = sqlite3.connect

    def _connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    sqlite3.connect = _connect  # type: ignore[assignment]
    try:
        yield statements
    finally:
        sqlite3.connect = real_connect  # type: ignore[assignment]


# --- CT-STATS-10 — compression, and the blind spot it must declare ---------------------------


@pytest.mark.writtenahead
def test_tc_stats_c10_compares_panel_against_gold_bands_on_hand_computed_constants():
    """The Oracle the plan names: *"hand-computed constants"*, not a plausibility range.

    Both statistics on both distributions — four numbers — because the check's finding is a
    *comparison* and either half being wrong produces a wrong comparison that still looks like a
    measurement. A test asserting only that the panel entropy is lower would pass for a module
    computing both numbers wrongly in the same direction.

    Gold means the **blind** labels' distribution: comparing the panel against operational
    teacher bands compares it against teachers who saw its own output, and R44's finding
    disappears.
    """
    require(STATS_MODULE, "compression_check", issue="#117")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=COMPRESSION_LABELS)

    report = stats.compression_check(cohort_id="coh-1", criterion_id="C-01")

    assert report.gold.band_entropy == pytest.approx(GOLD_BAND_ENTROPY), (
        f"gold band entropy {report.gold.band_entropy} != {GOLD_BAND_ENTROPY} — the teacher's "
        "bands are uniform over four bands, so the entropy is exactly log2(4)"
    )
    assert report.panel.band_entropy == pytest.approx(PANEL_BAND_ENTROPY)
    assert report.gold.interior_rate == pytest.approx(GOLD_INTERIOR_RATE)
    assert report.panel.interior_rate == pytest.approx(PANEL_INTERIOR_RATE)
    assert report.panel_narrower is True, (
        "the panel's distribution is strictly narrower than the teacher's and the report does not "
        "say so. FR-STATS-06 reports **relative** compression — panel narrower than teacher — "
        "which is the only direction this check can see."
    )


@pytest.mark.writtenahead
def test_tc_stats_c10_states_its_co_compression_blind_spot_inside_the_return_value():
    """*"The stated limitation is part of the return value, not a footnote."*

    The unusual requirement in this suite, and the one worth defending. The check compares panel
    against teacher, so a panel and a teacher compressing **together** produce a clean result —
    and a consumer receiving that result without the caveat reads a null finding as evidence of no
    compression, which is the opposite of what the check measured (HLD `R44`).

    A docstring cannot travel with the value, and a footnote in the console is a different module's
    decision. So the assertion is on the report's own content.
    """
    require(STATS_MODULE, "compression_check", issue="#117")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=COMPRESSION_LABELS)

    report = stats.compression_check(cohort_id="coh-1", criterion_id="C-01")
    stated = str(report.stated_limitation).lower()

    assert vocab.CO_COMPRESSION_LIMITATION in stated, (
        f"the compression report's stated limitation is {stated!r}; FR-STATS-06 requires it to "
        f"state that it {vocab.CO_COMPRESSION_LIMITATION!r}"
    )


# --- CT-STATS-11 — routing-policy validity ---------------------------------------------------


@pytest.mark.writtenahead
def test_tc_stats_c11_compares_both_arms_using_blind_labels_only():
    """*"Asserted on the label population, since using operational labels on either side would
    compare the review to itself."*

    The failure is circular rather than numerical: an escalated-and-reviewed judgment whose
    "error" is measured against the reviewing teacher's own label is being compared with itself,
    and the escalated arm's error rate goes to zero. The policy then looks excellent precisely
    where it is doing the most work.

    Both arms are seeded with operational labels the filter must drop, and the assertion is on the
    `n` of each arm — the count is the population, and a report that names its population without
    counting it can name anything.
    """
    require(STATS_MODULE, "routing_policy_validity", issue="#117")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    arms = []
    for arm in vocab.ROUTING_POLICY_ARMS:
        arms += [broken.Label(label_id=f"{arm}-blind-{i}", routing=arm) for i in range(10)]
        arms += [
            broken.Label(
                label_id=f"{arm}-op-{i}", label_type="operational", routing=arm
            )
            for i in range(10)
        ]

    stats = build_stats(labels=arms)
    report = stats.routing_policy_validity(cohort_id="coh-1")

    for arm in vocab.ROUTING_POLICY_ARMS:
        assert report.label_population[arm].n == 10, (
            f"the {arm} arm was computed over n={report.label_population[arm].n}; ten blind and "
            "ten operational labels were seeded, so anything above ten means operational labels "
            "entered the comparison and the review is being compared with itself (FR-STATS-08)"
        )


@pytest.mark.writtenahead
def test_tc_stats_c11_similar_error_rates_in_both_arms_are_reported_as_failing():
    """The interpretation the clause fixes, and it is not the natural one.

    *"Reports **similar rates in both as failing** rather than as merely uninformative."* An
    implementer looking at two indistinguishable error rates reaches for "inconclusive" — it is
    the honest-sounding word and it is wrong here. If escalated judgments are no more error-prone
    than auto-accepted ones, the policy is escalating the wrong things, and that is a finding
    about `M-AGG`'s declared constants rather than an absence of one (`CT-AGG-14`, HLD `R22`).

    The fixture is constructed to sit exactly there: both arms at the same error rate.
    """
    require(STATS_MODULE, "routing_policy_validity", issue="#117")  # the member this story delivers
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    labels = []
    for arm in vocab.ROUTING_POLICY_ARMS:
        # Same error rate in both arms: three of ten disagree with the teacher.
        labels += [
            broken.Label(
                label_id=f"{arm}-{i}",
                routing=arm,
                band=3,
                teacher_band=3 if i >= 3 else 5,
            )
            for i in range(10)
        ]

    report = build_stats(labels=labels).routing_policy_validity(cohort_id="coh-1")

    assert report.verdict == vocab.ROUTING_POLICY_FAILING_VERDICT, (
        f"the report returned {report.verdict!r} for two arms at the same error rate. "
        f"FR-STATS-08 fixes the interpretation: similar rates are "
        f"{vocab.ROUTING_POLICY_FAILING_VERDICT!r}, not "
        f"{vocab.ROUTING_POLICY_FORBIDDEN_VERDICT_ON_SIMILAR_RATES!r} — the policy is escalating "
        "the wrong judgments."
    )


# --- CT-STATS-15 — the write scope, and the indirection ---------------------------------------


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c15_the_validation_record_is_written_through_m_pkg(tmp_data_dir):
    """*"Writes are limited to `package_validation` (**through `M-PKG`**, asserted as an
    indirection under a write audit)."*

    An **indirection** assertion, not an absence one. `M-STATS` must write the validation record —
    that is `FR-STATS-10` — and the clause is about the route it takes: `CT-PKG-12` makes the
    catalog the sole writer of Tier P, so a direct write here is a second writer to a tier whose
    single-writer property everything else depends on.

    `recording_write_audit()` supplies the oracle the plan asks for. Its attribution is per stack
    frame, so a write performed by `M-PKG` and initiated by `M-STATS` is exactly the shape the
    clause requires, and a write performed by `M-STATS` into the package tier is the violation.
    """
    require(STATS_MODULE, "promote", issue="#118")  # the member this story delivers
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    require(PKG_MODULE, "validation_for", issue="#29")

    for label in [broken.Label(label_id=f"bl-{i}") for i in range(40)]:
        record_label(data_dir=tmp_data_dir, label=label)

    stats = open_stats(data_dir=tmp_data_dir)
    with recording_write_audit() as writes:
        stats.promote(cohort_id="coh-spring")

    by_stats = [w for w in writes if w.initiated_by == "M-STATS"]
    assert by_stats, (
        "promote wrote nothing at all, so the indirection assertion below is vacuous — "
        "FR-STATS-10 requires the validation record to be updated after each administration"
    )

    direct = [
        w
        for w in by_stats
        if "packages" in str(w.target) and w.attributed_to != "M-PKG"
    ]
    assert direct == [], (
        f"{[(w.api, str(w.target)) for w in direct]} reached Tier P without going through the "
        "catalog. CT-STATS-15 writes package_validation *through* M-PKG, and CT-PKG-12 makes "
        "M-PKG the sole writer of Tier P."
    )


@pytest.mark.writtenahead
def test_tc_stats_c15_no_statement_in_the_source_writes_a_score_grade_or_package_row(repo_root):
    """*"Asserted statically so it covers unexercised paths."*

    A write audit sees the paths a test drove. This sees the ones it did not — the backfill on an
    error branch, the convenience update in a migration helper — which is where a write of this
    kind actually lives, because nobody adds one to the main path.

    Reads are untouched and deliberately so: the clause **grants** reads of labels, grades and
    metrics, and a scanner that flagged `SELECT … FROM grade` would condemn the module's whole
    reason for existing. The rule is controlled in both directions in the vocabulary file.
    """
    source_path = require_path(
        repo_root / "src" / "aeh" / "stats.py",
        "the M-STATS implementation module",
        issue="#115",
    )
    problems = vocab.forbidden_write_statements(source_path.read_text(encoding="utf-8"))

    assert problems == [], (
        f"the module writes {problems}. CT-STATS-15: no score, no grade, no narrative, no package "
        "content — the measurement has to be independent of the thing measured (HLD §0.8)."
    )


# --- CT-STATS-18 — the read boundary --------------------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c18_reads_only_tier_d_and_the_current_cohorts_labels(tmp_data_dir):
    """*"Asserted over its actual queries, so a convenience join to Tier C fails."*

    The queries, not the intention. A module that reads a view someone else defined over Tier C is
    reading Tier C, and nothing in its own source says so — which is why the assertion is on the
    SQL a real connection executed rather than on the source or on a spy's record of what it was
    asked for.

    "The current cohort's" is the operative scope: a second cohort's labels are as much a
    boundary crossing as another tier, and the join that produces them is the convenient one —
    more labels make every figure look better resolved.
    """
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")

    for label in [broken.Label(label_id=f"bl-{i}") for i in range(40)]:
        record_label(data_dir=tmp_data_dir, label=label, cohort_id="coh-current")
        record_label(data_dir=tmp_data_dir, label=label, cohort_id="coh-other")

    stats = open_stats(data_dir=tmp_data_dir, cohort_id="coh-current")
    with sql_trace() as statements:
        stats.agreement(**vocab.EMPTY_DATA_CALL["agreement"])

    assert statements, "no SQL was traced, so this asserts nothing about the read boundary"

    crossing = [s for s in statements if "coh-other" in s]
    assert crossing == [], (
        f"{crossing} read a cohort other than the current one (CT-STATS-18)"
    )

    identifying = [
        s
        for s in statements
        if any(term in s.lower() for term in ("student_name", "pupil_name", "family_name"))
    ]
    assert identifying == [], (
        f"{identifying} name a student-identifying column. CT-STATS-18 reads only pseudonymized "
        "Tier D plus the current cohort's labels."
    )


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_stats_c18_tier_d_holds_no_student_name_column_reachable_from_here(tmp_data_dir):
    """The pairing with `CT-STORE-C09`, asserted from this side.

    `FR-STORE-12` makes Tier D reject an insert carrying a student-name column, and this module is
    the consumer entitled to rely on it — *"a caller may rely on Tier D being pseudonymized"*. The
    reliance is worth a test of its own because the guarantee is what makes the whole statistics
    tier permanent: Tier C is purged and Tier D is not, so a name that reaches Tier D outlives
    every mechanism designed to remove it.

    Keyed on **#10**, which creates the tiers and their migrations — the column's absence is a
    schema fact, and it is checkable the moment the schema exists.
    """
    open_store = require(STORE_MODULE, "open_store", issue="#10")

    store = open_store(data_dir=tmp_data_dir)
    durable = store.durable()

    tables = [row[0] for row in durable.query("SELECT name FROM sqlite_master WHERE type='table'")]
    assert tables, "Tier D has no tables, so the column sweep below is vacuous"

    named = []
    for table in tables:
        columns = [row[1] for row in durable.query(f"PRAGMA table_info({table})")]
        named += [
            f"{table}.{column}"
            for column in columns
            if any(term in column.lower() for term in ("student_name", "pupil_name", "family_name"))
        ]

    assert named == [], (
        f"Tier D exposes {named}. It is permanent and survives the cohort purge, so a name here "
        "outlives every mechanism built to remove it (CT-STORE-09, FR-STORE-12)."
    )


@pytest.mark.writtenahead
def test_tc_stats_c18_subgroup_analysis_is_off_by_default_and_refuses_when_disabled():
    """*"A default value plus a refusal when disabled."*

    Two assertions because the default alone is not the protection. A knob defaulting to `false`
    that nothing reads is a comment; the refusal is what makes it a control. And the reverse — a
    module that refuses only when the knob is explicitly `false` — leaves the analysis running
    wherever the knob is absent, which is every installation that never heard of it.

    *"A subgroup analysis running by default is a regulatory exposure nobody chose"*, and
    `NFR-STATS-05` gates it on **local lawfulness**, which is not a thing this module can decide.
    """
    knob_default = require(STATS_MODULE, vocab.SUBGROUP_ANALYSIS_KNOB, issue="#117")
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")

    assert knob_default is vocab.SUBGROUP_ANALYSIS_DEFAULT, (
        f"{vocab.SUBGROUP_ANALYSIS_KNOB} defaults to {knob_default!r}; §3.16's Configuration "
        f"block declares {vocab.SUBGROUP_ANALYSIS_DEFAULT!r}"
    )

    stats = build_stats(labels=[broken.ADMISSIBLE_LABEL] * 40)
    with pytest.raises(Exception) as raised:  # noqa: PT011 - the refusal type is the module's
        stats.surface_proxies(cohort_id="coh-1", criterion_id="C-01", subgroup="declared_group")

    assert not isinstance(raised.value, AttributeError), (
        "surface_proxies raised AttributeError, which is what a module with no surface-proxy "
        "analysis raises — that is an absence, not a refusal"
    )
