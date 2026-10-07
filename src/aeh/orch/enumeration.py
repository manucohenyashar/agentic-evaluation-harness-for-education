"""Enumerating a run's work units, and tracing a unit back to its source document."""

from __future__ import annotations

from typing import Any

from .constants import (
    IDENTITY_TRIAGE_V3_OUTCOMES,
    SCORING_MODEL_BASE_DEPTH,
    STAGE_DETERMINISTIC,
    STAGE_EXTRACT,
    STAGE_SCORE,
    SWEEP1_ADMITTED_INGEST_STATUSES,
)
from .work_units import _row_evaluation_mode, UnitProvenance
from .errors import BrokenLineageError
from .statements import ORCH_STATEMENTS
from .settings import (
    ENUM_COMMIT_BATCH_DEFAULT,
    ENUM_COMMIT_BATCH_ENV,
    _env_float,
    _env_int,
    ORCH_RANDOM_ARM_RATE,
    RANDOM_ARM_RATE_ENV,
)
from .escalation_policy import escalation_plan, random_arm_selection, run_random_arm_seed
from .reports import EnumerationReport


class EnumerationMixin:
    """Creates a run's work units and traces each unit back to its source."""

    # -- enumeration ----------------------------------------------------------------------------

    def enumerate_units(self, run_id: str) -> EnumerationReport:
        """Compute and insert the run's base work units. Safe to call more than once.

        More detail: `docs/code-notes/orch.md`, section `enumeration.py: EnumerationMixin.enumerate_units`.
        """
        # The claim pass's order caches hold rows read before this pass may insert new
        # ones — drop the run's entries, or a cached order would keep the new units
        # undiscoverable until an unrelated exhaustion.
        self._invalidate_order_cache(run_id)
        row = self._run_row(run_id)
        gates: dict[str, str] = {
            "run_row": f"found (status={row['status']}, cohort={row['cohort_id']})",
        }
        arms = self._panel_arms(row["panel_config"])
        gates["panel_config"] = f"{len(arms)} arm(s) in panel order"
        prompt_template_version = row["prompt_template_v"]

        catalog = self._catalog(row)
        # Imported here, as `_catalog` imports `aeh.pkg`: the import adds Tier P migrations.
        from aeh.pkg import is_composite

        declared = catalog.criteria(row["package_version_id"])
        # `FR-JUDGE-38`: a composite (`evidence_sum`) criterion is a grouping record, never a
        # unit of any stage — only its aspect criteria are extracted and judged. Dropped here,
        # before the mode branch and the random-arm draw, so nothing downstream sees it.
        composites = sorted(c["criterion_id"] for c in declared if is_composite(c))
        criteria = sorted(
            (c for c in declared if not is_composite(c)),
            key=lambda c: c["criterion_id"],
        )
        gates["catalog"] = (
            f"package {row['package_id']} version {row['package_version_id']}: "
            f"{len(criteria)} criterion(a)"
        )
        gates["composites"] = (
            f"{len(composites)} composite criterion(a) withheld from enumeration "
            f"(FR-JUDGE-38): {composites}" if composites else "none declared"
        )

        cohort = self._store.cohort(row["cohort_id"])
        submissions = cohort.query(
            ORCH_STATEMENTS["select_submissions"], cohort_id=row["cohort_id"]
        )
        gates["submissions"] = f"{len(submissions)} submission(s) in the cohort"

        # The admission filter (`FR-ORCH-22`): Sweep 1 work is enumerated for admitted
        # submissions only; a quarantined (or otherwise refused) submission generates no
        # scoring work until it is re-ingested — re-ingestion flips the row's status, and
        # the next enumeration inserts its units into the SAME run (`INSERT OR IGNORE`
        # keeps everything already there). **The `deterministic` stage admits every
        # submission**: a deterministic criterion has no extraction unit for admission to
        # gate (`FR-ORCH-08` — none exists to wait for), and M-DET scores the structured
        # answer data ingest validated, not the extracted evidence the refused statuses
        # describe. The sweep-ordering tests' `units_inserted == 2` on re-ingest pins
        # this shape: had the deterministic unit waited for admission, three units would
        # arrive, not two.
        admitted = [
            s for s in submissions
            if s["ingest_status"] is None
            or s["ingest_status"] in SWEEP1_ADMITTED_INGEST_STATUSES
        ]
        admitted_ids = {s["submission_id"] for s in admitted}
        withheld = len(submissions) - len(admitted)
        refused = sorted(
            {
                s["ingest_status"] for s in submissions
                if s["ingest_status"] is not None
                and s["ingest_status"] not in SWEEP1_ADMITTED_INGEST_STATUSES
            }
        )
        gates["admission"] = (
            f"{len(admitted)} of {len(submissions)} admitted to Sweep 1 "
            f"(rule: {sorted(SWEEP1_ADMITTED_INGEST_STATUSES)} or unjudged); "
            f"{withheld} withheld"
            + (f" (statuses: {refused})" if refused else "")
        )

        # Identity triage (#620, CT-INGEST-23): a paper V3 could not match to one student
        # gets no unit of any stage until a re-ingest resolves it.
        identity_held = {
            s["submission_id"] for s in submissions
            if s["v3_identity"] in IDENTITY_TRIAGE_V3_OUTCOMES
        }
        gates["identity_triage"] = (
            f"{len(identity_held)} submission(s) held for identity triage get no units"
        )

        batch = _env_int(ENUM_COMMIT_BATCH_ENV, ENUM_COMMIT_BATCH_DEFAULT)
        random_arm_rate = _env_float(
            RANDOM_ARM_RATE_ENV, ORCH_RANDOM_ARM_RATE, low=0.0, high=1.0
        )
        run_seed = run_random_arm_seed(run_id)

        computed: list[tuple[str, dict[str, Any]]] = []
        random_arm_pairs = 0
        random_arm_units = 0
        for submission in submissions:
            if submission["submission_id"] in identity_held:
                continue
            for criterion in criteria:
                # `FR-ORCH-35`: the criterion's DECLARED mode, not its shape. A package
                # may declare a judged multiple-choice criterion — one whose options a
                # panel must weigh — and enumerating it as deterministic would skip the
                # extract and score units it is entitled to.
                if _row_evaluation_mode(criterion) == "deterministic":
                    computed.append(self._unit(
                        row, STAGE_DETERMINISTIC, submission, criterion, None,
                    ))
                    continue
                if submission["submission_id"] not in admitted_ids:
                    continue
                computed.append(self._unit(
                    row, STAGE_EXTRACT, submission, criterion, None,
                ))
                depth = min(
                    SCORING_MODEL_BASE_DEPTH.get(criterion["scoring_model"], 1),
                    len(arms),
                )
                for arm in arms[:depth]:
                    computed.append(self._unit(
                        row, STAGE_SCORE, submission, criterion, arm,
                    ))
                # The random arm (`FR-ORCH-11`, `CT-ORCH-15`): the pair draws at the
                # configured rate, independent of confidence — the draw takes the
                # pair's identities and the rate and nothing else — and a drawn pair
                # gets the widened panel an escalation would build, marked
                # `origin = 'random_arm'` so the sample stays statistically separable
                # (`M-STATS`/`M-REVIEW` read the mark). **Nothing suppresses it**: the
                # draw runs before any escalation exists to gate and consults neither
                # the budget nor a breaker — the arm measures the routing policy
                # itself (`FR-STATS-08`), and a budget that could silence it would
                # make the policy unfalsifiable. It spends compute, never teacher
                # minutes, and produces no review item (`FR-REVIEW-07`).
                if random_arm_selection(
                    (submission["submission_id"], criterion["criterion_id"]),
                    run_seed,
                    random_arm_rate,
                ):
                    widened = escalation_plan(arms[:depth], panel_arms=arms)
                    for judge in widened[depth:]:
                        computed.append(self._unit(
                            row, STAGE_SCORE, submission, criterion, judge,
                            origin="random_arm",
                        ))
                    random_arm_pairs += 1
                    random_arm_units += len(widened) - depth

        work_ids = sorted(work_id for work_id, _ in computed)
        existing = {
            r["work_id"] for r in cohort.query(
                ORCH_STATEMENTS["select_run_work_ids"], run_id=run_id
            )
        }
        gates["ledger_read"] = (
            f"{len(existing)} unit(s) already in the ledger for this run"
        )

        pending = [
            (work_id, params) for work_id, params in computed
            if work_id not in existing
        ]
        inserted = 0
        for start in range(0, len(pending), batch):
            with cohort.transaction() as tx:
                for _, params in pending[start:start + batch]:
                    # The existing-set read and this write are separated by design —
                    # the single-writer queue serializes them — and INSERT OR IGNORE is
                    # the idempotent form regardless: a row that appeared between read
                    # and write is left exactly as the ledger holds it, never rewritten.
                    tx.execute(ORCH_STATEMENTS["insert_work_unit"], **params)
                    # `OR IGNORE` cannot report what it did: an ignored row is either a
                    # duplicate that raced in between the read and this write, or a row
                    # a constraint refused — and `OR IGNORE` swallows both silently.
                    # Counting the loop's iterations would report the ledger as having
                    # taken rows it does not hold, so the count comes from the ledger:
                    # `changes()` read in the same transaction, of the write that
                    # transaction itself just made.
                    inserted += int(
                        tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"]
                    )

        counts: dict[tuple[str, str], int] = {}
        for r in cohort.query(ORCH_STATEMENTS["select_run_counts"], run_id=run_id):
            counts[(r["stage"], r["status"])] = r["n"]
        by_stage: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for (stage, status), n in counts.items():
            by_stage[stage] = by_stage.get(stage, 0) + n
            by_status[status] = by_status.get(status, 0) + n
        gates["ledger_write"] = (
            f"{inserted} inserted, {len(computed) - inserted} already present"
        )
        gates["ledger_counts"] = ", ".join(
            f"{status}={by_status[status]}" for status in sorted(by_status)
        ) or "ledger empty for this run"
        # `CT-ORCH-15`'s observability: the arm's sample size is visible next to the
        # enumeration's status, and the gate names its independence — a reader of the
        # report can tell drawn units from suppressed ones without re-deriving the
        # draw.
        gates["random_arm"] = (
            f"{random_arm_pairs} pair(s) drawn at rate {random_arm_rate} "
            f"({random_arm_units} unit(s), origin='random_arm'); independent of "
            "confidence — never suppressed by the escalation budget or a breaker"
        )

        return EnumerationReport(
            run_id=run_id,
            status="enumerated" if inserted else "no-op",
            work_ids=tuple(work_ids),
            units_enumerated=len(computed),
            units_inserted=inserted,
            units_already_present=len(computed) - inserted,
            by_stage=by_stage,
            by_status=by_status,
            gates=gates,
        )

    def provenance(self, work_id: str) -> UnitProvenance:
        """Trace one unit back to its source document: work unit, then submission, then document.

        Raises `BrokenLineageError` naming the broken hop when the unit has no submission,
        its submission is absent from the cohort, the submission has no document, or the
        unit's evidence names a document that is ambiguous or not the submission's — no
        imputation, never a NULL `document_id` (#223). Raises `WorkLedgerError` for a
        work id no cohort holds, as `_find_unit` does.
        """
        cohort, _row = self._find_unit(work_id)
        rows = cohort.query(ORCH_STATEMENTS["select_unit_provenance"], work_id=work_id)
        first = rows[0]
        short = work_id[:12]
        if first["submission_id"] is None:
            raise BrokenLineageError(
                f"work unit {short}… carries no submission_id, so it cannot be traced to a "
                "source document; the unit is refused rather than joined to NULL."
            )
        if first["joined_submission_id"] is None:
            raise BrokenLineageError(
                f"work unit {short}… names submission {first['submission_id']!r}, which "
                "this cohort does not hold; its lineage is broken at the submission hop."
            )
        documents = [row for row in rows if row["document_id"] is not None]
        if not documents:
            raise BrokenLineageError(
                f"work unit {short}… belongs to submission {first['submission_id']!r}, "
                "which has no document row; its lineage is broken at the document hop."
            )
        head = documents[-1]
        by_id = {row["document_id"]: row for row in documents}
        read = [
            row["document_id"]
            for row in cohort.query(
                ORCH_STATEMENTS["select_unit_evidence_documents"], work_id=work_id
            )
        ]
        if len(read) > 1:
            raise BrokenLineageError(
                f"work unit {short}…'s evidence names {len(read)} documents ({read}); one "
                "unit reads one document, so its source is ambiguous and is not guessed."
            )
        if read and read[0] not in by_id:
            raise BrokenLineageError(
                f"work unit {short}…'s evidence names document {read[0]!r}, which is not a "
                f"document of submission {first['submission_id']!r}."
            )
        source = by_id[read[0]] if read else head
        hops = [f"work_unit:{work_id}", f"submission:{first['submission_id']}"]
        if read:
            hops.append(f"evidence:{work_id}")
        hops.append(f"document:{source['document_id']}")
        return UnitProvenance(
            work_id=work_id,
            run_id=first["run_id"],
            stage=first["stage"],
            submission_id=first["submission_id"],
            document_id=source["document_id"],
            content_hash=source["content_hash"],
            current_document_id=head["document_id"],
            read_from_evidence=bool(read),
            document_ids=tuple(row["document_id"] for row in documents),
            hops=tuple(hops),
        )

    def _runs_missing_units(self) -> tuple[str, ...]:
        """Unfinished runs whose ledger has no work units at all, ordered by run id.

        The gate behind lease()'s enumerate-on-empty fallback: enumerating is a full
        pass over catalog, roster and computed ids, and a drained poll late in a large
        run must not pay it (NFR-ORCH-01). A run with rows — even partially populated
        by a crash mid-enumeration — is `resume()`'s repair, not lease's; the
        existence probe is one indexed query per open run.

        **The admissible-submission gate (#59 review).** A run can hold no units
        *legitimately*, and forever: a cohort whose submissions are all refused — or
        which has none yet — enumerates to the empty set, and re-deriving that empty
        set on every drained poll is precisely the full pass this gate exists to
        prevent ("never enumerated" and "legitimately empty" must not cost the same).
        A run whose cohort holds no admissible submission — none with a NULL
        `ingest_status` (pre-ingest, admits per `SWEEP1_ADMITTED_INGEST_STATUSES`'s
        recorded reading) and none in the admitted set — is therefore skipped. The
        gate re-opens by itself: a submission re-ingested into an admissible status
        makes the cohort admissible again on the next poll, which is the self-heal
        path. A cohort that stays admissible while the package yields no units for
        another reason (a version with zero criteria — `M-PKG` refuses the shape, so
        this helper does not defend against it) would still re-enumerate per poll.
        """
        found: list[str] = []
        admissible_by_cohort: dict[str, bool] = {}
        for key in self._cohort_keys():
            cohort = self._store.cohort(key)
            for row in cohort.query(ORCH_STATEMENTS["select_open_runs"]):
                cohort_id = row["cohort_id"]
                if cohort_id not in admissible_by_cohort:
                    admissible_by_cohort[cohort_id] = any(
                        s["ingest_status"] is None
                        or s["ingest_status"] in SWEEP1_ADMITTED_INGEST_STATUSES
                        for s in cohort.query(
                            ORCH_STATEMENTS["select_submissions"],
                            cohort_id=cohort_id,
                        )
                    )
                if not admissible_by_cohort[cohort_id]:
                    continue
                if not cohort.query(
                    ORCH_STATEMENTS["select_any_work_unit"], run_id=row["run_id"]
                ):
                    found.append(row["run_id"])
        return tuple(sorted(found))

    def _open_run_ids(self) -> tuple[str, ...]:
        """Every unfinished run in every cohort ledger, ordered by run id."""
        found: list[str] = []
        for key in self._cohort_keys():
            for row in self._store.cohort(key).query(ORCH_STATEMENTS["select_open_runs"]):
                found.append(row["run_id"])
        return tuple(sorted(found))
