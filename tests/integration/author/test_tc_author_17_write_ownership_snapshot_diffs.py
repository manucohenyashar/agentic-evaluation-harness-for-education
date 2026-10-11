"""`TC-AUTHOR-17` (FR-AUTHOR-14, CT-AUTHOR-11, CT-AUTHOR-12, P0) — the write-ownership
snapshot diff (#715, the package-authoring test plan §5.1; design delta §3.1, ADR-43).

Written ahead of #698: `aeh.author` does not exist yet, so the cases are red until the
service lands. The file carries `writtenahead`, keyed `#698 determinism snapshots` in
`WRITTEN_AHEAD_BLOCKERS` (`symbol`, `aeh.author:AuthoringService`); the marker comes off —
never the test — when the blocker's unmark re-check passes (the registry entry's comment
holds the landing-timing disclosure and the re-key path).

Rung 1, and the oracle is deliberately **not** "no exception": ADR-43's write-ownership
clause is asserted over **state** (the issue's own technical note — "the write-ownership
clause is asserted over row counts, not over absence of error"). Around the draft and
around the review the case snapshots:

- every store tier's **row counts** — a real store, pre-seeded through
  `tests/support/orch_run.seed_run` so all three tiers (package, cohort, durable) hold rows
  and a delta is meaningful; a snapshot over an empty store is the decorative zero the
  TC-CONF-C08 docstring warns about. `HARNESS_DATA_DIR` points at it for the duration, so
  an implementation that resolves a store through the environment lands in the same
  snapshot (RISK-125: authoring writing store rows would contaminate a store opened for a
  cohort run);
- the data directory's **file-name set** (WAL sidecars excluded — they are connection
  state, not store state): a version minted on a *new* package id, a second cohort
  database, or a stray blob is a write the seeded tiers' row counts cannot see;
- the output directory's **file set**: exactly the two artifacts `DraftResult` names, no
  third file, ever.

`package_version`'s count is asserted **by name** on top of the per-table delta: "no
version minted" (FR-AUTHOR-14) is the one row the story's reviewer asked for by name, and
an anonymous equality over every table would let a reader miss that it is covered.

The review arm rides AF-07 (the corpus's review fixture — its `expected.toml` class says
the scripted review completes to *ready*), so the review has real items to answer and the
"review mutates only the draft and its report" half (CT-AUTHOR-12) is exercised over a
rewrite, not over a no-op.

The guards name their issues: the module surface (#698 — the story whose closure removes
this file's marker; the class itself lands with #690, the first service story, which is the
disclosure the registry entry carries), the corpus paths (#686), and the recordings'
`coverage.json` — the same marker the `#686` registry entry holds outside the gate, because
an unrecorded corpus would make the run's replay vacuous.
"""

from __future__ import annotations

import pytest

from aeh.prov.errors import ProviderUnavailableError
from aeh.store import open_store
from tests.support.author_vocabulary import (
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    CountingProvider,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
    scripted_answers,
    sha256_of,
)
from tests.support.impl import require, require_path
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

#: The story whose closure removes this file's marker (`#698 determinism snapshots` in
#: `tests/support/impl.py`). The `aeh.author` surface itself lands with #690; the registry
#: entry's comment carries that disclosure.
ISSUE = "#698"

#: The seeded package the snapshot reads row counts from (`seed_run`'s default id).
PACKAGE_ID = "pkg-orch"

#: One criterion, so the seeded package version's tables hold rows (`seed_package`'s spec
#: form — `PackageCatalog.add_criterion` kwargs minus the version).
CRITERIA = [{"criterion_id": "C1", "question_id": "Q1", "kind": "mcq",
             "scoring_model": "atomic", "band_count": 2}]

WAL_SIDECARS = ("-wal", "-shm")


def _guards(make_fixture_provider) -> tuple:
    """The require-style gate, and the first thing each test body does.

    A missing module or corpus is `NotImplementedYet` naming its issue — the designed red —
    never a collection error or a bare `FixtureMissingError` from an unrecorded replay.
    """
    author = require(AUTHOR_MODULE, issue=ISSUE)
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=ISSUE)
    af01 = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    af07 = require_path(af("AF-07"), "the AF-07 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    # The #686 registry entry's own marker: a run against an unrecorded corpus replays
    # nothing, and the write-ownership claims below would hold vacuously over a run that
    # produced placeholder-only artifacts from zero recorded replies.
    require_path(RECORDINGS / "coverage.json", "the authoring recordings' coverage marker",
                 issue=CORPUS_ISSUE)
    return author, af01, af07, recordings


def _data_files(data_dir) -> set[str]:
    """Every file the data directory holds, by relative name, WAL sidecars excluded.

    Names, not sizes or mtimes: a `-wal` file grows and shrinks with this test process's
    own connections, and the store's `journal_mode=WAL` makes those sidecars connection
    state rather than store state. A write authoring makes to *any* tier surfaces either
    here (a new package database, a second cohort file, a blob) or in the row counts.
    """
    return {
        str(p.relative_to(data_dir)).replace("\\", "/")
        for p in data_dir.rglob("*")
        if p.is_file() and not p.name.endswith(WAL_SIDECARS)
    }


def _tier_row_counts(store, package_id: str, cohort_id: str) -> dict[str, dict[str, int]]:
    """Every table of every tier the store has opened, with its row count.

    The tiers are enumerated from `sqlite_master`, not from a hand-listed table set —
    "no other tier's rows changed" must survive a schema that grows tomorrow (the
    `TC-DET-C09` write-audit shape).
    """
    counts: dict[str, dict[str, int]] = {}
    for name, handle in (
        ("package", store.package(package_id)),
        ("cohort", store.cohort(cohort_id)),
        ("durable", store.durable()),
    ):
        tables = handle.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        counts[name] = {
            row["name"]: handle.query(f"SELECT COUNT(*) AS n FROM {row['name']}")[0]["n"]
            for row in tables
        }
    return counts


def _snapshot(store, data_dir, package_id: str, cohort_id: str) -> tuple:
    return _tier_row_counts(store, package_id, cohort_id), _data_files(data_dir)


def _row_deltas(before: dict, after: dict) -> dict:
    """Per-tier, per-table row-count deltas, for the failure message only."""
    return {
        tier: {table: after[tier].get(table, 0) - count
               for table, count in before[tier].items()
               if after[tier].get(table, 0) != count}
        for tier in before if after.get(tier) != before[tier]
    }


# --- TC-AUTHOR-17 -------------------------------------------------------------------------------


def test_tc_author_17_the_snapshot_diff_around_draft_and_review_is_empty(
        tmp_path, tmp_data_dir, make_fixture_provider, monkeypatch, network_guard):
    """A real store holds rows on every tier; `draft()` and then `review()` run against it;
    both snapshots come back **equal** — no row count changed on any tier, no new file
    anywhere in the data dir, no version minted — and the output directories hold exactly
    the two artifacts, with the review having rewritten only those two."""
    author, af01, af07, recordings = _guards(make_fixture_provider)
    provider = CountingProvider(make_fixture_provider(recordings))

    store = open_store(tmp_data_dir)
    _orchestrator, _run_id, _version = seed_run(
        store, submissions=("S-1", "S-2"), criteria=CRITERIA, package_id=PACKAGE_ID)

    # RISK-125's scenario: a store opened for a cohort run, with authoring pointed at it
    # through the environment it would resolve.
    monkeypatch.setenv("HARNESS_DATA_DIR", str(tmp_data_dir))
    service = make_service(author, chain_from_config(), provider)

    before = _snapshot(store, tmp_data_dir, PACKAGE_ID, ORCH_COHORT_ID)

    # --- around the draft -------------------------------------------------------------------
    result = service.draft(documents=sorted(af01.glob("*.pdf")), output_dir=tmp_path / "out")
    after = _snapshot(store, tmp_data_dir, PACKAGE_ID, ORCH_COHORT_ID)

    assert after == before, (
        "TC-AUTHOR-17: the draft moved store state (FR-AUTHOR-14, CT-AUTHOR-11, ADR-43) — "
        f"row-count deltas: {_row_deltas(before[0], after[0])} | "
        f"new files: {after[1] - before[1]}")
    assert {p.name for p in (tmp_path / "out").iterdir()} == {
        result.draft_path.name, result.report_path.name}, (
        "TC-AUTHOR-17: the draft writes exactly its two artifacts and nothing else "
        "(FR-AUTHOR-14)")
    # "No version minted", named: the seeded version is the only row `package_version` has
    # before and after (a KeyError here would mean the schema moved under the case).
    assert before[0]["package"]["package_version"] == 1, "the seed did not create one version"
    assert after[0]["package"]["package_version"] == 1, (
        "TC-AUTHOR-17: the draft minted a package version (FR-AUTHOR-14, ADR-43)")

    # --- around the review ------------------------------------------------------------------
    review_out = tmp_path / "review-out"
    reviewed = service.draft(documents=sorted(af07.glob("*.pdf")), output_dir=review_out)
    neighbour = review_out / "keep-me.txt"
    neighbour.write_bytes(b"unrelated file\n")
    before_review = _snapshot(store, tmp_data_dir, PACKAGE_ID, ORCH_COHORT_ID)
    files_before = {p.name: sha256_of(p) for p in review_out.iterdir()}

    draft_text = reviewed.draft_path.read_text(encoding="utf-8")
    assert placeholder_fields(draft_text), (
        "AF-07 must leave placeholders for the review to answer (its expected.toml class)")
    answers = scripted_answers(author, draft_text, {
        field: ("Sample-materials teacher" if "approved" in field.lower()
                else "The teacher's model answer for this question.")
        for field in placeholder_fields(draft_text)})
    review = service.review(draft_path=reviewed.draft_path, answers=answers)
    assert review.ready is True and review.remaining == (), (
        f"AF-07's review must complete to ready (its expected.toml class), got {review}")

    after_review = _snapshot(store, tmp_data_dir, PACKAGE_ID, ORCH_COHORT_ID)
    assert after_review == before_review, (
        "TC-AUTHOR-17: the review moved store state (CT-AUTHOR-12) — "
        f"row-count deltas: {_row_deltas(before_review[0], after_review[0])} | "
        f"new files: {after_review[1] - before_review[1]}")
    files_after = {p.name: sha256_of(p) for p in review_out.iterdir()}
    assert set(files_after) == set(files_before), (
        f"TC-AUTHOR-17: the review created or removed files: "
        f"{set(files_after) ^ set(files_before)} (CT-AUTHOR-12)")
    assert files_after["keep-me.txt"] == files_before["keep-me.txt"], (
        "TC-AUTHOR-17: the review touched a neighbour file (CT-AUTHOR-12)")
    for name in (reviewed.draft_path.name, reviewed.report_path.name):
        assert files_after[name] != files_before[name], (
            f"TC-AUTHOR-17: the review did not rewrite {name} (CT-AUTHOR-12)")

    store.close()  # the TC-DET-C09 shape: release the tier handles before tmp cleanup
    network_guard.assert_no_network()


def test_tc_author_17_a_run_whose_steps_fail_still_writes_exactly_two_artifacts(
        tmp_path, tmp_data_dir, make_fixture_provider, monkeypatch, network_guard):
    """#698's failure-path acceptance criterion: a run whose every reasoning step fails
    still produces the same artifact *set* — two files, report included — and touches no
    store. The determinism claim never becomes an excuse to skip the report (the report
    itself is written, not its absence asserted: that half is TC-AUTHOR-C10's)."""
    author, af01, _af07, recordings = _guards(make_fixture_provider)

    real = make_fixture_provider(recordings)

    class _EveryCallFails(CountingProvider):
        """Failure injection at the model boundary (§4.2's one permitted double)."""

        def complete(self, prompt, model_ref, params):  # noqa: ANN001
            self.calls.append((prompt, model_ref, params))
            raise ProviderUnavailableError("injected: every model call fails")

    provider = _EveryCallFails(real)

    # No store is opened in this arm, so the data dir holds only its three empty
    # directories and a full file diff is stable — the cheap form of the same claim.
    monkeypatch.setenv("HARNESS_DATA_DIR", str(tmp_data_dir))
    before = {str(p.relative_to(tmp_data_dir)) for p in tmp_data_dir.rglob("*")}

    result = make_service(author, chain_from_config(), provider).draft(
        documents=sorted(af01.glob("*.pdf")), output_dir=tmp_path / "out")

    assert provider.calls, "the failure injection never reached the module"
    after = {str(p.relative_to(tmp_data_dir)) for p in tmp_data_dir.rglob("*")}
    assert after == before, f"the failing run wrote into the data dir: {after - before}"
    artifacts = {p.name for p in (tmp_path / "out").iterdir()}
    assert artifacts == {result.draft_path.name, result.report_path.name}, (
        "TC-AUTHOR-17: a run whose steps all fail must still write exactly the two "
        f"artifacts, got {artifacts}")
    assert result.report_path.exists(), "the report is one of the two artifacts"

    network_guard.assert_no_network()