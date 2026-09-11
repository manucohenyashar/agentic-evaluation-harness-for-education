"""`SEC-15` — the store-interface boundary. Test plan §6.5, TS-57 (issue #150).

*"Attempt free-text and similarity queries against every tier reachable from the scoring path.
No such interface exists; parameterized declared statements only."* — `FR-STORE-08`, Injection /
OWASP A03.

**Two halves, and only one of them is the plan's stated probe.**

The probe §6.5 names is *behavioural*: call into a real `Store` and assert the method is not
there. That needs `M-STORE`, which does not exist, so it lands behind `writtenahead` at the bottom
of this file.

The other half is an **addition**, not a substitute: a source-level scan asserting no module
assembles SQL from anything but a declared statement. It is worth having because it catches the
defect the behavioural probe structurally cannot see — a store with a perfectly clean surface can
still build a `WHERE` clause with an f-string *inside* a declared statement, and every
absence-assertion over the public interface passes while it does.

Design §3.3 is what makes the source half assertable rather than a matter of taste:

    class TierHandle(Protocol):
        def query(self, stmt: Statement, **params) -> Sequence[Row]: ...

A `Statement`, not a `str`; parameters as keywords, not interpolated text. There is no place to
put an injection because there is no place to put free text — a *shape* defence, and a shape is
something a parser can check.

**Why the positive control below is not decoration.** `src/` holds `aeh.conf` and `aeh.prov`, and
neither issues a single SQL statement. "Zero assembled-SQL sites in the source tree" is therefore
true of the tree, true of a scanner that returns `[]` unconditionally, and true of a scanner with
a typo in every pattern — three claims a green result cannot tell apart. The control makes them
distinguishable, and it has already earned its keep: it caught a chain assembled across three
lines that every text-shape rule in the walker walked straight past, which is why `sql_scan` now
asserts on what reaches `execute()` rather than only on what looks like SQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.impl import STORE_MODULE, require
from tests.support.sql_scan import (
    EXECUTE_METHODS,
    execute_call_sites,
    is_search_name,
    scan_module,
    scan_tree,
)

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The deliberately-bad module the walker is proved against. Outside `src/`, so `scan_tree` does
#: not walk it — a control that failed the assertion it supports would be useless.
BROKEN_SQL_FIXTURE = REPO_ROOT / "tests" / "support" / "broken_sql_fixture.py"


# --- the source-level half (an addition to the plan's probe) ----------------------------------


def test_sec_15_no_module_assembles_a_sql_statement():
    """No module under `src/` or `harness/` builds SQL from anything but a declared statement.

    The oracle is an **artifact assertion over the source tree**: zero sites, each violation
    naming module, file, line and the form it took, so the failure is actionable without opening
    the walker.

    Green today because no module issues SQL at all. That is a real state of the system, not a
    vacuous pass — the control below is what proves the scanner would speak up — and this case
    is the one that fires on the first `M-STORE` commit that reaches for an f-string.
    """
    violations = scan_tree(REPO_ROOT)

    assert not violations, (
        "SEC-15: SQL is being assembled rather than declared. `FR-STORE-08` offers keyed lookup "
        "and declared statements only, and design §3.3 types the argument as `Statement` "
        "precisely so free text has nowhere to go:\n  "
        + "\n  ".join(str(v) for v in violations)
    )


@pytest.mark.parametrize(
    "function, form, kind",
    [
        ("by_name", "f-string", "fstring"),
        ("by_cohort", "concatenation", "concat"),
        ("by_status", "percent formatting", "percent"),
        ("ordered_by", ".format()", "format-call"),
        ("migrate", "executescript", "executescript"),
        ("split_across_lines", "a chain assembled across statements", "computed-statement"),
    ],
)
def test_sec_15_the_walker_catches_every_form_of_assembly(function, form, kind):
    """The positive control, one row per **rule** the walker claims to enforce.

    The `kind` column is the whole assertion, and its absence was a blocker. The first draft
    checked only that *some* violation fell inside the function's line range — and every one of
    these functions is caught twice, once by the rule it is named after and once by the
    execute-argument rule. So disabling four of the six rules outright (review did it, by
    stubbing `_looks_like_sql` to return `False`) left all six rows green. Six assertions
    collapsed to two.

    Asserting the kind pins each rule to the row that exists for it, so a regression names the
    form that stopped being caught rather than reporting nothing at all.
    """
    import ast

    source = BROKEN_SQL_FIXTURE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BROKEN_SQL_FIXTURE))
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function
    )

    within = {
        v.kind for v in scan_module("broken_sql_fixture", BROKEN_SQL_FIXTURE, REPO_ROOT)
        if target.lineno <= v.line <= (target.end_lineno or target.lineno)
    }

    assert kind in within, (
        f"SEC-15: the walker no longer catches {function}() ({form}) by its own rule. It "
        f"reported {sorted(within) or 'nothing'}, and {kind!r} is missing. The control exists "
        "because the real tree issues no SQL, so a silent rule and a clean tree look identical."
    )


#: The legitimate ways a store names a statement. Every one of these must scan clean.
#:
#: One negative control was not enough, and review proved it with measurement: four of these five
#: were flagged by the first draft, including the shape the single control itself wrote. `sql`,
#: `stmt` and `query` are the commonest identifiers in a store module, so a walker that
#: false-positives here reds the build on the first ordinary `M-STORE` commit — a *false* finding,
#: which against this issue's Goal ("fail the build on a finding") is worse than a miss.
DECLARED_FORMS: dict[str, str] = {
    "a module constant, used directly": '''
SELECT_BY_ID = "SELECT id, status FROM work_unit WHERE id = ?"

def fetch(connection, unit_id):
    return connection.execute(SELECT_BY_ID, (unit_id,))
''',
    "a local literal, while an unrelated helper binds the same name": '''
def unrelated_helper(raw):
    stmt = raw.strip()
    return stmt

def fetch(connection, unit_id):
    stmt = "SELECT id, status FROM work_unit WHERE id = ?"
    return connection.execute(stmt, (unit_id,))
''',
    "textwrap.dedent over a multi-line literal": '''
import textwrap

SELECT_BY_ID = textwrap.dedent("""
    SELECT id, status
    FROM work_unit
    WHERE id = ?
""")

def fetch(connection, unit_id):
    return connection.execute(SELECT_BY_ID, (unit_id,))
''',
    "implicit concatenation across lines": '''
def fetch(connection, unit_id):
    return connection.execute(
        "SELECT id, status "
        "FROM work_unit "
        "WHERE id = ?",
        (unit_id,),
    )
''',
    "a table of declared statements": '''
STATEMENTS = {"by_id": "SELECT id, status FROM work_unit WHERE id = ?"}

def fetch(connection, unit_id):
    return connection.execute(STATEMENTS["by_id"], (unit_id,))
''',
}


@pytest.mark.parametrize("form", sorted(DECLARED_FORMS), ids=lambda f: f[:38])
def test_sec_15_the_walker_reports_nothing_against_a_declared_statement(form, tmp_path):
    """The negative controls — the walker must not flag the *correct* forms.

    A scanner that flags everything passes every positive control above and is worthless: the
    first `M-STORE` commit turns it off. So each shape `FR-STORE-08` sanctions gets its own row,
    and the row names the shape so a false positive says which one broke.

    Written into `tmp_path`, not the repository. The first draft wrote its probe into
    `tests/support/` and unlinked it in a `finally` — a killed process left an untracked file
    behind in the tree the sibling case scans.
    """
    probe = tmp_path / "declared_probe.py"
    probe.write_text(DECLARED_FORMS[form], encoding="utf-8")

    violations = scan_module("declared_probe", probe, tmp_path)

    assert not violations, (
        f"SEC-15: the walker flagged a correctly declared statement ({form}). A scanner with "
        "false positives on the sanctioned form is one somebody switches off:\n  "
        + "\n  ".join(str(v) for v in violations)
    )


#: Every place in `src/` or `harness/` that hands a statement to SQLite, as `module:line`.
#:
#: Transcribed rather than computed, for the reason `SEC-14` transcribes the dependency set — the
#: value of the constant is that changing it is a diff somebody reads.
#:
#: **Two entries, and one place SQL actually reaches SQLite.** `M-STORE` routes every statement
#: through a single `_run()` helper, so this list stays something a reviewer reads rather than
#: scrolls. #10 built that helper; #11 added the write queue, its batch `BEGIN`/`COMMIT`/
#: `ROLLBACK` and `Tx.execute`, all of them through `_run`; #12 added the blob store and the
#: lease clock; #13 added the Tier D guard, the purge machinery and the name vocabulary. The
#: line number has moved as each story declared constants above it (710 -> 778 -> 916 -> 1488
#: on this line), which is the re-read this constant exists to force.
#:
#: **The second entry is not a second place SQL reaches SQLite.**
#: `aeh.store:2248` is `LeaseClock._persist`, and the `aeh.pkg` entries are `PackageCatalog`'s writes, reads, guards, validators and the validation surface, each calling `tx.execute(PKG_STATEMENTS[...],
#: ...)` — `Tx.execute` is the module's own declared-statement API and delegates to `_run`, which
#: is still the only site that touches a `sqlite3` cursor. The walker cannot see that, and
#: shouldn't: it flags every `execute()` and asks a human whether the argument is a declared
#: statement with keyword parameters. It is — from the registry, which is the shape
#: `sql_scan._statement_problem` names as sanctioned. `aeh.store:1513` is `_run` itself, moved
#: again by #12's and #13's own declarations. What is passed there is `declared.sql` — an attribute of a declared
#: `Statement`, which is the shape `sql_scan._statement_problem` sanctions — never the parameter,
#: which would mean "whatever the caller passed reaches SQLite unchecked".
#:
#: The line number is part of the entry, so an edit above the site fails this case. That is
#: annoying and it is the point: the constant exists to be re-read, and a site that moved is a
#: site somebody should look at again.
KNOWN_EXECUTE_SITES: frozenset[str] = frozenset({
    # aeh.orch's sites: #57's four (the run-row insert, the ledger's batched
    # unit insert with the `SELECT changes()` read in that same
    # transaction — the insert is `OR IGNORE`, so the ledger's own count of what the
    # write did is the only honest one — and the audit-record insert), plus
    # #58's leasing and failure taxonomy (every one from ORCH_STATEMENTS,
    # keyword-parameterized): the guarded lease claim with its changes() read,
    # the heartbeat's lease extension with its changes() read, the sweeper's guarded
    # requeue with its changes() read, the completion with its changes() read, and
    # the failure record with its changes() read. Lines moved with #59's sweep-plan
    # additions, #60's random-arm block in enumerate_units, #60's escalation
    # restructure, #62's residency-gate rewrite (the batch boundary's
    # leased-only check) and #62's report-index migration (Cohort 13) with the
    # statement reshapes it carried (first_open's schedule-ordered probe, the
    # criteria axis folded into by_unit's aggregate), and #62's review fix for
    # the dropped-judges restart hole (the durable `_dropped_judges` read in the
    # claim walk); the sites are the same statements as #57/#58's.
    "aeh.orch:2185",
    "aeh.orch:2406",
    "aeh.orch:2415",
    # #61's lifecycle sites (every one from ORCH_STATEMENTS, keyword-parameterized):
    # start's displayed-estimate write and its guarded pending→running transition with
    # its changes() read; pause's control-row insert and its already-paused satisfied-
    # request arm; the explicit resume's own control-row insert (the reviewer's F4 —
    # the explicit form writes the row too, retiring its old direct supersede write);
    # the control-read pass's bounded supersede (`mark_pauses_applied_before`, the
    # reviewer's F2) and applied marker; the shared guarded run transition with its
    # changes() read. Lines moved with #61's lifecycle block and the reviewer fixes
    # swapped the two resume sites noted above; the #57/#58 statements are the same
    # as ever.
    "aeh.orch:2497",
    "aeh.orch:2503",
    "aeh.orch:2508",
    "aeh.orch:2551",
    "aeh.orch:2563",
    "aeh.orch:2623",
    "aeh.orch:2725",
    "aeh.orch:2743",
    "aeh.orch:2767",
    "aeh.orch:2775",
    # #61's ceiling block in the claim pass: the in-transaction spend read, the
    # remaining-units count and the sensed pause write (the refusal arm), the guarded
    # claim with its changes() read, the in-transaction accrual, and the at-ceiling
    # arm's count and sensed pause — spend and lease commit in one transaction
    # (FR-ORCH-15), so the sites live inside the same `with`.
    "aeh.orch:3261",
    "aeh.orch:3276",
    "aeh.orch:3280",
    "aeh.orch:3300",
    "aeh.orch:3309",
    "aeh.orch:3292",
    "aeh.orch:3328",
    "aeh.orch:3332",
    "aeh.orch:3537",
    "aeh.orch:3544",
    "aeh.orch:3595",
    "aeh.orch:3599",
    "aeh.orch:3649",
    "aeh.orch:3654",
    "aeh.orch:3705",
    "aeh.orch:3711",
    # #60's escalation, breaker and budget sites (every one from ORCH_STATEMENTS,
    # keyword-parameterized, all inside one transaction — the caller's per CT-ORCH-08
    # or the method's own): the enqueue's key-to-runs resolution, the pair's prior
    # panel read, the idempotence probe, the breaker's latch and window and
    # escalated-set reads, the breaker's latch write, the request row's insert and
    # its admit flip, the queue-depth read behind the enqueue's gate, the unit
    # insertion helper's per-judge inserts with their changes() reads (the same
    # honest count the enumerate pass gives), and the report assembler's
    # queue-depth read. The restructure moved the queue's drain into the claim
    # pass's dispatch gate, so the drain's reads are gone and the key's run
    # resolution arrived.
    "aeh.orch:3817",
    "aeh.orch:3875",
    "aeh.orch:3891",
    "aeh.orch:3911",
    "aeh.orch:3925",
    "aeh.orch:3931",
    "aeh.orch:3949",
    "aeh.orch:3986",
    "aeh.orch:4002",
    "aeh.orch:4024",
    # The lines moved again with #61's lifecycle and ceiling blocks and #62's
    # report-index migration (the #60 statements are the same as ever).
    "aeh.orch:4071",
    "aeh.orch:4075",
    "aeh.orch:4154",
    # #62's dispatch additions (every one from ORCH_STATEMENTS, keyword-
    # parameterized, inside the method's own durable transaction): the OOM
    # remedy's reduced-panel write (`record_reduced_panel`, the panel_config
    # RES-13 requires recorded), the requeue helper's guarded pending-restore
    # (`requeue_expired`, #58's sweeper statement at its second call site, with
    # its changes() read — the 429/OOM ladders requeue through it), and the
    # metrics flush's `insert_run_metric` upsert (the EAV write CT-ORCH-20
    # makes contract). The report's own reads go through the tier's declared
    # `query`, not `execute`, so they are not sites here.
    "aeh.orch:4903",
    "aeh.orch:4935",
    "aeh.orch:4937",
    "aeh.orch:5117",
    # #57's audit-record insert (record_run_start), moved by #62's dispatch
    # block above it; same statement.
    "aeh.orch:5149",
    # aeh.det's eight sites (#86's six, #87's two): the single-row score upsert in
    # `evaluate`, the batched score upsert in `evaluate_cohort`'s one Tier C
    # transaction, #87's re-derivation upsert in `rederive_for_key_change` (only
    # the rows whose value moved under the corrected key), and #87's audit-record
    # insert in `_append_audit_records` — one site shared by all three grading
    # paths (`evaluate`, `evaluate_cohort`, `rederive_for_key_change`), so the
    # FR-DET-10 column set is written in exactly one place. The four Tier D
    # stat writes rewrite `mcq_item_stats`/`mcq_item_summary` per criterion
    # (delete + insert pairs, so a redelivery is idempotent — CT-DET-08).
    # Every one from DET_STATEMENTS, keyword-parameterized. Lines moved with #60's
    # sorted-merge comment on the cohort registry append; same statements.
    "aeh.det:970",
    "aeh.det:1086",
    "aeh.det:1271",
    "aeh.det:1414",
    "aeh.det:1645",
    "aeh.det:1653",
    "aeh.det:1661",
    "aeh.det:1667",
    # The extract sites are #68's line numbers (shifted by #69's second-family pass
    # above the transaction): the one write transaction in
    # `ExtractionWorker.process` — the guarded done-marking, its changes() read, and
    # the evidence row that commits together with it (CT-STORE-03's commit-together;
    # every statement a declared constant in `EXTRACT_STATEMENTS`/`ORCH_STATEMENTS`).
    "aeh.extract:891",
    "aeh.extract:896",
    "aeh.extract:898",
    # The judge sites are #80's line numbers (moved from #79's 1453/1458/1460 by the
    # response-contract work above them: the v17 migration block, the prose-assessment
    # gate, the amendment payload, the extended dispatch loop — then re-pinned once
    # more when the review fix wrapped the reply span parsing in
    # `MalformedResponseError`, which added nine lines above `persist`), and now once
    # more by #81 (the FR-JUDGE-17 composition section in the module docstring, the
    # extended directive, the canonical-document resolver and the citation-grounding
    # gate above `persist`): the one write transaction in `ScoringWorker.persist` — the
    # guarded done-marking, its changes() read, and the verdict row that commits
    # together with it (the extract shape: every statement a declared constant in
    # `JUDGE_STATEMENTS`/`ORCH_STATEMENTS`, keyword-parameterized) — the verdict row's
    # VALUES list now carrying the #80 response columns (cited_spans JSON,
    # evidence_sufficient, uncited), still one declared statement. Re-pinned from the
    # walker's own output: the statements are verified unchanged against the prior
    # baseline, the tripwire diff being the line move alone.
    "aeh.judge:1825",
    "aeh.judge:1830",
    "aeh.judge:1840",
    # The ingest sites are #220's line numbers (the transcription strike loop
    # and the honest-quarantine catch shifted the module; every statement
    # verified unchanged against the prior baseline, the tripwire diff being
    # the line move alone).
    "aeh.ingest:2792",
    "aeh.ingest:2803",
    "aeh.ingest:2825",
    "aeh.ingest:3386",
    "aeh.ingest:3421",
    "aeh.ingest:3453",
    "aeh.ingest:3528",
    "aeh.ingest:3531",
    "aeh.ingest:3532",
    "aeh.ingest:3642",
    "aeh.ingest:3870",
    "aeh.ingest:3882",
    "aeh.ingest:4418",
    "aeh.ingest:4441",
    "aeh.ingest:3399",
    # The pkg sites are #230's line numbers (the verbatim revision copy and the
    # copied-counts statement shifted the module; the tripwire diff being the
    # line move plus one net-new site). Lines moved again with #91's module-level
    # `points_for_band` (the __all__ entry and the delegating method shifted the
    # module); the tripwire diff being the line move alone — the mapping itself
    # reads no SQL, it reads the catalog cache.
    # (#118's re-pin: `record_promotion` joined at the head — the one net-new
    # site, the record row's `INSERT OR REPLACE INTO package_validation` as a
    # declared literal with keyword parameters, the same shape the catalog's
    # own writes ride; #118's validation surface above the module's first site
    # moved every site, and the reference export's tail six moved again under
    # it. Re-read from the walker, never hand-unioned.)
    "aeh.pkg:1997",
    "aeh.pkg:2104",
    "aeh.pkg:2146",
    "aeh.pkg:2160",
    "aeh.pkg:2162",
    "aeh.pkg:2164",
    "aeh.pkg:2187",
    "aeh.pkg:2195",
    "aeh.pkg:2282",
    "aeh.pkg:2297",
    "aeh.pkg:2299",
    "aeh.pkg:2301",
    "aeh.pkg:2327",
    "aeh.pkg:2340",
    "aeh.pkg:2343",
    "aeh.pkg:2383",
    "aeh.pkg:2386",
    "aeh.pkg:2403",
    "aeh.pkg:2408",
    "aeh.pkg:2410",
    "aeh.pkg:2419",
    "aeh.pkg:2424",
    "aeh.pkg:2426",
    "aeh.pkg:2684",
    "aeh.pkg:2697",
    "aeh.pkg:2721",
    "aeh.pkg:2722",
    "aeh.pkg:2789",
    "aeh.pkg:2791",
    "aeh.pkg:2841",
    "aeh.pkg:2846",
    "aeh.pkg:2882",
    "aeh.pkg:2887",
    "aeh.pkg:2890",
    "aeh.pkg:2914",
    "aeh.pkg:2999",
    "aeh.pkg:3165",
    "aeh.pkg:3171",
    "aeh.pkg:3179",
    "aeh.pkg:3186",
    "aeh.pkg:3254",
    "aeh.pkg:3262",
    "aeh.pkg:3263",
    "aeh.pkg:3267",
    "aeh.pkg:3274",
    "aeh.pkg:3278",
    "aeh.pkg:3315",
    "aeh.pkg:3352",
    "aeh.pkg:3400",
    "aeh.pkg:3403",
    "aeh.pkg:3456",
    "aeh.pkg:3464",
    "aeh.pkg:3468",
    "aeh.pkg:3531",
    "aeh.pkg:3562",
    "aeh.pkg:3594",
    "aeh.pkg:3615",
    "aeh.pkg:3639",
    "aeh.pkg:3640",
    "aeh.pkg:3694",
    "aeh.pkg:3702",
    "aeh.pkg:3710",
    "aeh.pkg:3721",
    "aeh.pkg:3725",
    "aeh.pkg:3729",
    "aeh.pkg:4002",
    "aeh.pkg:4011",
    "aeh.pkg:4058",
    "aeh.pkg:4147",
    "aeh.pkg:4378",
    "aeh.pkg:4382",
    "aeh.pkg:4386",
    "aeh.pkg:4389",
    "aeh.pkg:4395",
    "aeh.pkg:4403",
    # Lines moved with #234's chain-completeness guard (the IncompleteMigrationChainError
    # class and the COMPLETE_SCHEMA_VERSIONS pin, both above the first site), again with
    # #269's _VersionOrderedRegistry, again with #61's run-lifecycle statements landing
    # in store.py, and again with #97's and #78's contributions named in the refusal's
    # text, and again with #62's pin bump (Cohort 14→15 for the report-index
    # migration) adding a line above each; the sites are the same statements as before.
    # (#92's re-pin: the 15→16 pin bump and the refusal text's eighth contributor added
    # three lines above each site — re-read from the walker, never hand-unioned.)
    # (#101's re-pin: the 17→18 pin bump after #80 took Cohort 17 — the refusal text's
    # ninth and tenth contributors (`aeh.grade`, then `aeh.integ` at the merge) and the
    # class docstring's contributor list moved each site; re-read from the walker,
    # never hand-unioned.)
    # (#110's re-pin: Durable's pin bump to 6 and the refusal text's eleventh
    # contributor (`aeh.review`) moved each site two lines; the sites are the same
    # statements as before. Re-read from the walker, never hand-unioned.)
    # (#103's re-pin, twice: the pin table's history note grew two lines and each
    # site moved with it, then the purge's pure-refusal-trigger carve-out (the
    # helper and its comment above `_SELECT_COHORT_TRIGGERS_VIEWS`) moved them
    # again; the sites are the same statements as before. Re-read from the walker,
    # never hand-unioned.)
    # (#118's re-pin: the validation-record wording and the append-only-audit
    # note landed in the refusal's contributor text and the durable tier's
    # migration registration moved both sites; the statements are the same
    # two. Re-read from the walker, never hand-unioned.)
    "aeh.store:1895",
    "aeh.store:2681",
    # The #118 stats sites: `promote`'s Tier D record — the unclaimed-audits
    # sourcing read, the label claim (the record's own declared statement),
    # the two post-claim cohort reads — plus the per-criterion figures write
    # and `criterion_figures`' fixture seed in `cohort_with_mixed_revisions`.
    # Every one a declared `STATS_STATEMENTS` statement with keyword
    # parameters (FR-STORE-08); the module's other reads go through tier
    # handles, which are not census sites. Pinned from the walker.
    "aeh.stats:3026",
    "aeh.stats:3033",
    "aeh.stats:3038",
    "aeh.stats:3042",
    "aeh.stats:3082",
    "aeh.stats:3453",
    # The synth site is #97's line number: the single narrative INSERT, declared in
    # SYNTH_STATEMENTS with keyword parameters — the write the ADR-8 primary key
    # conflicts a duplicate on. The module's reads go through `store.cohort(...).query()`,
    # which is not a census site (FR-STORE-08). (Line moved once with the reviewer's
    # isolation check on the payload-less document fallback, again with #98's
    # score-claim ladder and pattern list landing above the write, again with the
    # reviewer's pattern-tightening disclosures expanding the comments above it;
    # same statement, re-pinned from the walker each time.)
    "aeh.synth:778",
    # The grade sites are #104's line numbers (the module's own write surface, every
    # one from GRADE_STATEMENTS or a raw fixture DDL string, keyword-parameterized):
    # `compute_all`'s five pass writes (demote/insert/settle/queue-row/queue-clear),
    # `_grade_one`'s five single-submission writes (the same statements on the
    # per-submission path), `finalize_batch`'s settlement write, `amend`'s
    # demote-and-reinsert pair, and the two cohort-fixture seams' three writes each —
    # a cohort INSERT, a submission INSERT and the module's own `insert_grade` — in
    # `cohort_with_mixed_revisions` and #104's `_reference_export_cohort` (the golden
    # export's reproducible reference cohort; the rows are the rows the service
    # writes). The v18 migration's rebuild statements are a `Migration(...)` object
    # the store's runner executes, not call sites here; the module's reads go through
    # `store.cohort(...).query()` / the package handle's `query()`, which are not
    # census sites (FR-STORE-08) — the #104 rollup and export accessors
    # (`criterion_band_figures`, `separated_rollup`, `rollup_findings`) are reads and
    # added none. (Moved once as a block,
    # +21: the `panel_refused` presentation field the CT-AGG-07 consumer
    # differential demanded — `GradeComputation`'s disclosure of the
    # breaker-refused criteria — landing above every site; moved again, the six
    # sites after the service's coverage helper, +45: the derived
    # `_grades_by_state` the CT-SYNTH-05 consumer differential demanded — the
    # class's states as they stand, not the stored rows alone; and once more, the
    # same six, +5: the `_row_value` idiom inside the derivation, which keeps the
    # CT-PKG-05 single-reader gate from reading `["points"]` outside `aeh.pkg`;
    # and once more as a block, +9: `_settlement_state`'s docstring and
    # `input_missing` parameter — the recovered-incomplete defect fix reads this
    # pass's verdict, not the prior revision's counters; and once more as a block,
    # +17: #102's degenerate-range fix (the pinned-reading bullet and the
    # `boundary_risk` docstring's positive-width disclosure above every site —
    # the sites are the same statements as #101's; re-pinned from the walker,
    # never hand-unioned.) TS-39's re-pin, once more as a block, +6: the
    # `select_current_grade` statement gained its `policy_version`/`answer_key_ref`
    # projection (the statement had omitted columns `_as_submission_grade` reads,
    # crashing every `compute_one` — TC-GRADE-13 step 7 is the regression case);
    # five disclosure lines above every site below the statements dict. #104's
    # re-pin, once more as a block: the rollup/export surfaces landed between the
    # statements dict and the service, and `_reference_export_cohort` added its
    # three fixture writes at the tail. Same statements plus three; re-read from
    # the walker, never hand-unioned. #103's re-pin: +4 sites (the no-op
    # amendment's in-place settlement, the amendment's durable `audit_record`
    # append, `finalize_batch`'s finalization-path metric, and
    # `record_grade_signals`' durable signal flush — every one a declared
    # GRADE_STATEMENTS statement with keyword parameters, the FR-STORE-08
    # discipline), the rest moved with the docstring and statement edits above
    # them. Re-read from the walker, never hand-unioned.
    "aeh.grade:1482",
    "aeh.grade:1489",
    "aeh.grade:1491",
    "aeh.grade:1499",
    "aeh.grade:1509",
    "aeh.grade:1582",
    "aeh.grade:1607",
    "aeh.grade:1613",
    "aeh.grade:1644",
    "aeh.grade:1652",
    "aeh.grade:1744",
    "aeh.grade:1757",
    "aeh.grade:1866",
    "aeh.grade:1892",
    "aeh.grade:1898",
    "aeh.grade:1973",
    "aeh.grade:2243",
    "aeh.grade:2254",
    "aeh.grade:2259",
    "aeh.grade:2621",
    "aeh.grade:2627",
    "aeh.grade:2632",
    "aeh.grade:3115",
    # The #73/#74 integ sites: the routing ladder's ledger writes (the four
    # `insert_unit` routes, the escalation pair, the review unit, `mark_extract_done`)
    # plus the shared `_bump_retries` / `_enqueue_review` helpers and the two rate
    # emissions (`upsert_metric` in its six-signal loop, `upsert_alert` above
    # threshold). All are INTEG_STATEMENTS with keyword parameters — the module writes
    # only the declared signals-plus-routing surface (CT-INTEG-04's audit); its reads
    # go through `store.cohort(...).query()`, which is not a census site (FR-STORE-08).
    "aeh.integ:831",
    "aeh.integ:840",
    "aeh.integ:856",
    "aeh.integ:867",
    "aeh.integ:913",
    "aeh.integ:931",
    "aeh.integ:945",
    "aeh.integ:962",
    "aeh.integ:979",
    "aeh.integ:989",
    "aeh.integ:999",
    # The conform site is #133's: the fixture cohort's INSERT OR IGNORE on the
    # ephemeral store `ingest_one` opens, keyword-parameterized -- the same
    # bootstrap insert the security suite's fixture surface makes before its
    # ingests (`tests/security/ingest/test_active_content.py`), now riding the
    # submission's declared consent class. (Re-pinned from the walker on any
    # line move.)
    "aeh.conform:471",
    # The review site is #110's: the label store's one durable write, a single
    # `tx.execute` inside `_persist_label`'s transaction body, passing
    # `REVIEW_STATEMENTS["insert_label"]` — a declared statement with keyword
    # parameters (FR-STORE-08, design §3.3) — the same label the service holds
    # in memory. (Re-pinned from the walker on any line move.)
    # (#111's re-pin: the blind-sample/whole-grade methods inserted before
    # `_persist_label` moved the site; the statement is the same one. Re-read
    # from the walker, never hand-unioned.)
    # (#115's re-pin: the `upsert_label` Statement added to REVIEW_STATEMENTS
    # moved the site again; the statement is the same one.)
    "aeh.review:2432",
    # #115's collection route: the second durable write this module owns —
    # `_write_collected_label`'s single `tx.execute` in its transaction body,
    # passing `REVIEW_STATEMENTS["upsert_label"]`, a declared statement with
    # keyword parameters (FR-STORE-08, design §3.3). The same 19 columns
    # `insert_label` carries, upserted so a collected label can be re-keyed
    # into another cohort's administration. Pinned from the walker.
    "aeh.review:2974",
    # The #122/#126 console sites: one — the control row `perform` writes into the
    # run's cohort ledger (`_INSERT_RUN_CONTROL`, keyword-parameterized, the row the
    # orchestrator reads on its own schedule per CT-ORCH-13; re-pinned when the
    # reviewer's real-store findings were fixed — the control row now writes in the
    # cohort tier's own transaction, never nested inside a durable one), the quarantine
    # resolution the S8 close writes (`_UPDATE_QUARANTINE_RESOLUTION`, the operator's
    # decision, never an automatic one) — and the headless driver's six fixture seed
    # inserts (the pinned rubric version's package and package_version rows, then the
    # cohort, submission, document and document_region seeds). All keyword-parameterized
    # literals; the driver's disclosure notes cover why it pins ids the catalog would
    # otherwise mint.
    # (#124's re-pin: the review-queue rendering, the blind-flow plan and the request
    # assembler were inserted above these sites and moved every one of them; the
    # statements are the same eight. Re-read from the walker, never hand-unioned.
    # Second re-pin, still #124's: the reviewer's fixes to the queue header's item
    # arithmetic and the app-path flagged count moved the driver's six again.
    # #125's re-pin: the invariants 15-21 work — the band-control helpers, the
    # amendment ledger, the export gate and the review-window state — was inserted
    # above the two quarantine-resolution sites and the driver's six again; the
    # statements are the same eight.
    # (#118's re-pin: the headless driver's idempotent package seed — the C17
    # world re-runs baseline and live against one data directory, so the seed
    # probes for the version row before inserting — and the per-cohort run ids
    # moved the driver's six again; the statements are the same eight. Re-read
    # from the walker, never hand-unioned.)
    "aeh.console:1718",
    "aeh.console:1795",
    "aeh.console:3459",
    "aeh.console:3464",
    "aeh.console:3487",
    "aeh.console:3495",
    "aeh.console:3503",
    "aeh.console:3516",
})

def test_sec_15_every_database_execute_site_is_one_somebody_has_looked_at():
    """The set of execute sites, asserted as an exact set rather than reported.

    This is what tells "clean tree" apart from "clean store". The scan above returns zero
    violations today because nothing in `src/` issues SQL at all — a true result that says
    nothing about `M-STORE`, and a reader has no way to know which of the two they are seeing.

    A `pytest.skip` here was the first draft and it was worse than nothing: a test that always
    skips is a line in the output nobody reads, and it would have gone on skipping after the
    store landed. As a **set equality** it is a tripwire instead — the first `execute()` in the
    source tree fails this case and puts the site in front of a reviewer, next to the walker that
    has to be right about it.
    """
    sites = set(execute_call_sites(REPO_ROOT))

    assert EXECUTE_METHODS, "the walker recognizes no execute method, so it inspects nothing"
    assert sites == KNOWN_EXECUTE_SITES, (
        "SEC-15: the set of database execute sites changed.\n"
        f"  new:     {sorted(sites - KNOWN_EXECUTE_SITES)}\n"
        f"  gone:    {sorted(KNOWN_EXECUTE_SITES - sites)}\n"
        "Each new site is a place a statement reaches SQLite. Confirm it passes a declared "
        "statement with keyword parameters (FR-STORE-08, design §3.3), then add it here."
    )


# --- the behavioural half: the plan's own probe, blocked on M-STORE ---------------------------


def test_sec_15_no_tier_exposes_a_free_text_or_similarity_query():
    """`SEC-15`'s stated probe — *"attempt free-text and similarity queries against every tier
    reachable from the scoring path"*.

    An **absence assertion over the real interface**, which is the only form that answers the
    threat. `FR-STORE-08`: *"no method that performs similarity, embedding, or free-text search
    over any tier reachable from the scoring path; the store interface offers keyed lookup and
    declared queries only."*

    **What this checks, precisely.** `Store` and `TierHandle` are `Protocol`s, so the assertion
    is reflective — every public member of both, plus the module surface — rather than a call
    against a live tier. §6.5's probe says *"every tier reachable from the scoring path"*, and
    `package()`, `cohort()` and `durable()` all return a `TierHandle`, so checking the protocol
    covers all three *as far as the protocol goes*. It does **not** reach a concrete class that
    implements `TierHandle` and adds an off-protocol `search()`. Closing that needs a real
    instance, which needs the tiers to be constructible; it belongs with `TS-08`/`TS-09` (#14,
    #15), and is recorded here rather than implied by a green tick.

    The second half is what makes it more than a name check: `TierHandle.query` must take a
    `Statement`, not a `str`. A store that grew `query(sql: str)` exposes no method *named*
    search and is an arbitrary-SQL passthrough, which is exactly A03.

    **Registered on #10, not #13.** `FR-STORE-08` belongs to #13, but the discriminating question
    is *which single blocker, resolved, makes this test runnable and non-vacuous* — and that is
    #10, which creates `aeh.store` and the `Store`/`TierHandle` protocols. An absence assertion
    over a class becomes real the moment the class exists; keying on #13 would leave it red for
    two stories after it could have been catching things. Same reasoning that moved `TC-CONF-17`
    to #57 and `TC-CONF-C14` step 3 to #122.
    """
    import inspect

    store_module = require(STORE_MODULE, issue="#10")
    Store = require(STORE_MODULE, "Store", issue="#10")
    TierHandle = require(STORE_MODULE, "TierHandle", issue="#10")

    offenders: list[str] = []

    for owner in (Store, TierHandle):
        for name in dir(owner):
            if name.startswith("_"):
                continue
            if is_search_name(name):
                offenders.append(f"{owner.__name__}.{name}() is a search surface")

    # `query` takes a declared `Statement`, never a raw string.
    #
    # The first draft read `parameters.get("stmt", "").annotation`, which had three faults review
    # found by simulating four candidate signatures: it raised `AttributeError` on a differently
    # named parameter (`sql`, `statement`) rather than reporting a finding, and — the real hole —
    # an **unannotated** `stmt` stringified to `<class 'inspect._empty'>`, containing neither
    # "str" nor "Statement", so a raw-SQL passthrough with no type hint passed silently. That is
    # the exact A03 shape this limb exists to catch.
    query = getattr(TierHandle, "query", None)
    assert query is not None, "TierHandle exposes no query() at all — design §3.3 declares one"

    parameters = [
        parameter for name, parameter in inspect.signature(query).parameters.items()
        if name != "self" and parameter.kind not in (
            inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
        )
    ]
    assert parameters, "TierHandle.query takes no statement argument at all"
    statement_parameter = parameters[0]

    if statement_parameter.annotation is inspect.Parameter.empty:
        offenders.append(
            f"TierHandle.query({statement_parameter.name}) is unannotated, so nothing stops a "
            "raw SQL string being passed — design §3.3 types it `Statement` precisely to close "
            "that door"
        )
    else:
        annotation = str(statement_parameter.annotation)
        if "Statement" not in annotation:
            offenders.append(
                f"TierHandle.query({statement_parameter.name}: {annotation}) does not take a "
                "declared Statement — a raw-SQL passthrough is A03 whatever the method is called"
            )

    # And nothing at module level either: a free function taking a tier and a search string is
    # the same surface one indirection away.
    for name in dir(store_module):
        if not name.startswith("_") and is_search_name(name):
            offenders.append(f"{STORE_MODULE}.{name}() is a module-level search surface")

    assert not offenders, (
        "SEC-15: the store exposes a free-text or similarity surface. FR-STORE-08 offers keyed "
        "lookup and declared queries only:\n  " + "\n  ".join(offenders)
    )
