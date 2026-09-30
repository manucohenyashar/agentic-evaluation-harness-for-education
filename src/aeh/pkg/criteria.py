"""Editing a version's criteria, bands and exemplars, with the band-set rules enforced."""

from __future__ import annotations

from typing import Any, Sequence

from .vocabulary import (
    default_evaluation_mode,
    EVALUATION_MODES,
    PackageVersionId,
    PROVENANCE_VOCABULARY,
)
from .errors import BandSetError, CyclicDependencyError, PackageError
from .statements import PKG_STATEMENTS


class CriterionEditsMixin:
    """Adds, removes and edits criteria, bands and exemplars on a draft version."""

    def add_criterion(self, v: PackageVersionId, criterion_id: str) -> None:
        """Add a criterion in place — refused on published versions (`TC-PKG-03` case 2);
        the sanctioned vehicle is a revision (`FR-PKG-04`)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")

    def remove_criterion(self, v: PackageVersionId, criterion_id: str) -> None:
        """Remove a criterion in place — refused on published versions (case 3)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.remove")

    def set_dependencies(
        self, v: PackageVersionId, edges: Sequence[tuple[str, str]]
    ) -> None:
        """Declare the version's dependency edges in one write (`FR-PKG-05`): each edge
        is (before, after) — `after` depends on `before`, i.e. `before` is extracted
        first. Replaces the version's edge set; a cycle raises
        `CyclicDependencyError` INSIDE the transaction, so the write rolls back and the
        refusal is a no-op (`CT-PKG-11`) — a published version whose graph cannot be
        ordered must never exist, not merely fail later at read time."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion_dependency.alter")
            tx.execute(PKG_STATEMENTS["delete_dependencies"], v=v)
            for before, after in edges:
                if before == after:
                    # The self-edge is refused HERE, with the graph error, before the
                    # INSERT: the DDL's CHECK (criterion_id <> depends_on) would refuse
                    # the raw write, but FR-PKG-05 promises the caller
                    # CyclicDependencyError, and a caller branching on the exact type
                    # would otherwise see sqlite3.IntegrityError for this one cell.
                    raise CyclicDependencyError(
                        f"the dependency edge ({before!r}, {after!r}) is a self-edge "
                        f"(FR-PKG-05): a criterion cannot depend on itself. The "
                        "database's CHECK (criterion_id <> depends_on) backstops the "
                        "same rule for writes that route around the catalog."
                    )
                tx.execute(PKG_STATEMENTS["insert_dependency"],
                           v=v, criterion_id=after, depends_on=before)
            graph = {row["criterion_id"]: set() for row in tx.execute(
                PKG_STATEMENTS["select_criteria"], v=v)}
            for row in tx.execute(PKG_STATEMENTS["select_dependencies"], v=v):
                graph.setdefault(row["criterion_id"], set()).add(row["depends_on"])
                graph.setdefault(row["depends_on"], set())
            self._assert_acyclic(graph)
        self._invalidate()

    def update_criterion_dependency(self, v: PackageVersionId) -> None:
        """Add/remove/alter a dependency row in place — refused on published versions
        (cases 11-13). The row-level shape is #28's; the lock fires here first."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion_dependency.alter")

    # -- structure, graph and the per-run cache (#28) ------------------------------------------

    def add_criterion(
        self, v: PackageVersionId, criterion_id: str, *, question_id: str = "",
        kind: str = "open", max_points: float = 0.0, scoring_model: str = "atomic",
        construct_tag: str = "", dependencies: Sequence[str] = (),
        band_count: int | None = None, evidence_type: str | None = None,
        evaluation_mode: str | None = None,
    ) -> None:
        """Add a criterion with its dependency edges, refusing a cycle (`FR-PKG-05`) —
        the guard's add-refusal applies to published versions; drafts add freely. The
        content arguments default so a published version's refusal fires before any
        content is needed (TC-PKG-03 row 2 passes only the id).

        `evidence_type` (`FR-SETUP-09`, #232) declares what kind of textual evidence
        satisfies a JUDGED criterion — the declaration M-INTEG routes on
        (`FR-INTEG-03`). The read back attaches it for every criterion it commits;
        a criterion entered through THIS surface (the degraded read back routes the
        teacher here) carries the declaration from its write or stays NULL — and
        M-SETUP's publish gate refuses a draft holding a judged criterion without
        one. `mcq` criteria are keyed, not judged, and legitimately carry NULL.

        `band_count` is the DECLARED band-set size (`FR-PKG-06`): odd or outside 2..6
        fails at the declare — a set that can never satisfy the even-count rule should
        not exist even as a draft. `add_band` refuses past the declared count."""
        if band_count is not None and (band_count < 2 or band_count > 6
                                       or band_count % 2 != 0):
            raise BandSetError(
                f"a band_count of {band_count} is odd or outside 2..6 (FR-PKG-06). The "
                "even count removes the safe middle band a hesitant judge retreats to "
                "(design §5.10, R40) — declared at the criterion, not discovered after "
                "the bands are written."
            )
        # `FR-PKG-22`: declared when the caller declares it, shape default otherwise —
        # and refused here, by name, rather than left for the column's CHECK to answer
        # with a bare IntegrityError that names no requirement.
        mode = (
            default_evaluation_mode(kind) if evaluation_mode is None
            else str(evaluation_mode)
        )
        if mode not in EVALUATION_MODES:
            raise PackageError(
                f"criterion evaluation_mode {evaluation_mode!r} is not one of "
                f"{EVALUATION_MODES} (FR-PKG-22). The mode is a declared vocabulary "
                "member, not free text."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            tx.execute(PKG_STATEMENTS["insert_criterion"],
                       v=v, criterion_id=criterion_id, question_id=question_id,
                       kind=kind, max_points=max_points, scoring_model=scoring_model,
                       construct_tag=construct_tag, band_count=band_count,
                       evidence_type=evidence_type,
                       evaluation_mode=mode)
            for depends_on in dependencies:
                if depends_on == criterion_id:
                    # Same self-edge refusal as set_dependencies: the graph error the
                    # design promises, raised before the DDL's CHECK can answer with a
                    # bare IntegrityError (FR-PKG-05).
                    raise CyclicDependencyError(
                        f"criterion {criterion_id!r} cannot depend on itself "
                        f"(FR-PKG-05). The database's CHECK (criterion_id <> "
                        "depends_on) backstops the same rule for raw writes."
                    )
                tx.execute(PKG_STATEMENTS["insert_dependency"],
                           v=v, criterion_id=criterion_id, depends_on=depends_on)
            graph = {row["criterion_id"]: set() for row in tx.execute(
                PKG_STATEMENTS["select_criteria"], v=v)}
            for row in tx.execute(PKG_STATEMENTS["select_dependencies"], v=v):
                graph.setdefault(row["criterion_id"], set()).add(row["depends_on"])
                graph.setdefault(row["depends_on"], set())
            self._assert_acyclic(graph)
        self._invalidate()

    def add_band(
        self, v: PackageVersionId, criterion_id: str, ordinal: int,
        band: str, points: float, descriptor: str = "",
    ) -> None:
        """Add one band, enforcing the structural rules on the whole set (`FR-PKG-06`).

        The validation runs INSIDE the transaction, so a refused band is a no-op
        (`CT-PKG-11`): the whole-set rules (contiguity, monotone points, the declared
        count) can only be checked after the row is inserted, and checking after the
        commit would leave the invalid set on disk behind the raised error. The set is
        read version-scoped — a criterion id is shared with every revision that copied
        it, and the parent's bands are not this version's set."""
        declared = self._band_count(v, criterion_id)
        with self._handle.transaction() as tx:
            self._guard(tx, v, "band.add-unpublished")
            if declared is not None and ordinal >= declared:
                raise BandSetError(
                    f"band ordinal {ordinal} exceeds the criterion's declared "
                    f"band_count of {declared} (FR-PKG-06)."
                )
            existing = [row for row in tx.execute(
                PKG_STATEMENTS["select_bands"], v=v)
                if row["criterion_id"] == criterion_id]
            if any(row["ordinal"] == ordinal for row in existing):
                # Refused here, with the structural error, before the INSERT: the
                # ordinal is half of the primary key, so the database would refuse the
                # duplicate anyway — but with a bare IntegrityError, not the
                # BandSetError the band rules' error taxonomy promises.
                raise BandSetError(
                    f"criterion {criterion_id!r} already declares band ordinal "
                    f"{ordinal} (FR-PKG-06): ordinals are contiguous from 0, so a "
                    "duplicate is a gap wearing another ordinal's name."
                )
            tx.execute(PKG_STATEMENTS["insert_band"],
                       v=v, criterion_id=criterion_id, ordinal=ordinal,
                       band=band, points=points, descriptor=descriptor)
            rows = [row for row in tx.execute(PKG_STATEMENTS["select_bands"], v=v)
                    if row["criterion_id"] == criterion_id]
            self._validate_band_order(rows)
            if declared is not None and len(rows) == declared:
                self._validate_band_count(len(rows))
        self._invalidate()

    def add_exemplar(
        self, v: PackageVersionId, exemplar_id: str, criterion_id: str, band: str,
        provenance: str = "synthetic", blob_hash: str | None = None,
    ) -> None:
        """Add an exemplar, refusing a band that does not name a band declared for the
        criterion (`FR-PKG-07`).

        `provenance` is ADR-4's closed vocabulary (synthetic | paraphrased |
        real_verbatim); anything else — including the superseded `real_consented` — is
        refused, because two names for one state is the drift the gate exists to
        prevent. `blob_hash` references the content-addressed blob carrying the
        exemplar's material (CT-STORE-07). The `contains_real_student_text` flag is
        DERIVED (`ADR-4`): the same transaction refreshes it from the rows, so flag and
        exemplars cannot disagree (TC-PKG-24's invariant)."""
        if provenance not in PROVENANCE_VOCABULARY:
            raise PackageError(
                f"exemplar provenance {provenance!r} is not in the vocabulary "
                f"{PROVENANCE_VOCABULARY} (ADR-4). 'real_consented' is the superseded "
                "name for 'real_verbatim' — the canonical value is the only one the "
                "export gate tests."
            )
        declared = {row["band"] for row in self._handle.query(
            PKG_STATEMENTS["select_bands"], v=v)
            if row["criterion_id"] == criterion_id}
        if band not in declared:
            raise BandSetError(
                f"exemplar names band {band!r}, which criterion {criterion_id!r} does "
                f"not declare (declared: {sorted(declared)}). An exemplar anchored to an "
                "undeclared band would train judges toward a level the scoring pipeline "
                "cannot produce."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "exemplar.add-unpublished")
            tx.execute(PKG_STATEMENTS["insert_exemplar"],
                       v=v, exemplar_id=exemplar_id, criterion_id=criterion_id,
                       band=band, provenance=provenance, blob_hash=blob_hash)
            tx.execute(PKG_STATEMENTS["refresh_package_flag"], p=self._package_id)
        self._invalidate()

    def set_exemplar_provenance(
        self, v: PackageVersionId, exemplar_id: str, provenance: str
    ) -> None:
        """Record the paraphrase-and-approval outcome on a draft exemplar
        (`FR-PKG-11`'s remediation half): 'real_verbatim' → 'paraphrased' clears the
        gate once every such row is through it. Drafts only — a published version's
        exemplars are history (the sanctioned vehicle is a revision)."""
        if provenance not in PROVENANCE_VOCABULARY:
            raise PackageError(
                f"exemplar provenance {provenance!r} is not in the vocabulary "
                f"{PROVENANCE_VOCABULARY} (ADR-4)."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "exemplar.provenance")
            if not tx.execute(PKG_STATEMENTS["select_exemplar_by_id"], v=v,
                              exemplar_id=exemplar_id):
                raise PackageError(
                    f"exemplar {exemplar_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["update_exemplar_provenance"],
                       v=v, exemplar_id=exemplar_id, value=provenance)
            tx.execute(PKG_STATEMENTS["refresh_package_flag"], p=self._package_id)
        self._invalidate()

    def remove_exemplar(self, v: PackageVersionId, exemplar_id: str) -> None:
        """Drop a draft exemplar (`FR-PKG-11`'s other remediation half); the derived
        flag refreshes in the same transaction. Drafts only, like every content
        edit."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "exemplar.remove")
            if not tx.execute(PKG_STATEMENTS["select_exemplar_by_id"], v=v,
                              exemplar_id=exemplar_id):
                raise PackageError(
                    f"exemplar {exemplar_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["delete_exemplar"], v=v,
                       exemplar_id=exemplar_id)
            tx.execute(PKG_STATEMENTS["refresh_package_flag"], p=self._package_id)
        self._invalidate()

    def exemplars(self, v: PackageVersionId) -> tuple[dict, ...]:
        """The version's exemplar rows, ordered by exemplar id (`#53`): the read
        the prefix budget's per-pair assembly consumes (`FR-SETUP-11` — a
        (question, criterion) prefix includes its exemplars' material)."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_exemplars"], v=v)
        )

    def blob_text(self, blob_hash: str | None) -> str:
        """One blob's content as text, by hash — the exemplar material a judge
        prompt would carry, which the prefix budget counts (`#53`, `FR-SETUP-11`).

        None (a text-only exemplar) answers the empty string. A hash with NO blob
        store attached to this catalog refuses: silently under-counting the
        prefix is the opposite of the check's purpose. Missing content answers
        the empty string — a dangling hash is a storage inconsistency the budget
        report cannot fix, and the exemplar's absence of material is the honest
        count."""
        if blob_hash is None:
            return ""
        if self._blobs is None:
            raise PackageError(
                f"exemplar blob {blob_hash!r} cannot be read: this catalog was "
                "opened without a blob store, so the prefix budget would "
                "under-count the assembled prompt (FR-SETUP-11). Reopen the "
                "catalog with blobs=store.blobs()."
            )
        data = self._blobs.get(blob_hash)
        if not data:
            return ""
        return data.decode("utf-8", errors="replace")

    def _read_bands(self, criterion_id: str) -> list:
        """Bands read straight from the database — the validators and the exemplar guard
        run against the truth, not against the cache."""
        return self._handle.query(PKG_STATEMENTS["select_bands_by_criterion"],
                                  criterion_id=criterion_id)

    def _band_count(self, v: PackageVersionId, criterion_id: str) -> int | None:
        for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v):
            if row["criterion_id"] == criterion_id:
                return row["band_count"]
        return None

    def _validate_band_order(self, rows) -> None:
        """`FR-PKG-06`'s order half: ordinals contiguous from 0, points non-decreasing
        in ordinal — the monotone mapping M-AGG and M-GRADE assume."""
        ordinals = sorted(row["ordinal"] for row in rows)
        points = [float(row["points"]) for row in sorted(rows, key=lambda r: r["ordinal"])]
        if ordinals != list(range(len(ordinals))):
            raise BandSetError(
                f"the band ordinals {ordinals} are not contiguous from 0 (FR-PKG-06). "
                "Gaps would leave an unreachable band in the middle of the mapping."
            )
        if any(later < earlier for earlier, later in zip(points, points[1:])):
            raise BandSetError(
                f"the band points {points} are not non-decreasing in ordinal (FR-PKG-06). "
                "M-AGG and M-GRADE assume the monotone band-to-points mapping."
            )

    def _validate_band_count(self, count: int) -> None:
        """`FR-PKG-06`'s count half: even, within 2..6 — the even count removes the safe
        middle band a hesitant judge retreats to (design §5.10, R40)."""
        if count < 2 or count > 6 or count % 2 != 0:
            raise BandSetError(
                f"a band set of {count} bands is outside 2..6 or odd (FR-PKG-06). The "
                "even count removes the safe middle band a hesitant judge retreats to."
            )

    def _validate_band_sets(self, rows_of, *, boundary: str) -> None:
        """`FR-PKG-06`'s count half over ONE version's rows: every declared
        `band_count` fully populated and even/2..6. `rows_of` resolves a statement name
        to that version's rows — through the handle at the publish boundary, through
        the open transaction at the revision copy (#230) — so what is validated is
        exactly that version's own rows, never another revision's copied ids.

        At the copy the failure refuses the revision: a parent whose declared band set
        was never completed would otherwise ship the half set as the child's
        inheritance — a half-copied child is mutation by omission (`CT-PKG-02`)."""
        populated: dict[str, int] = {}
        for row in rows_of("select_bands"):
            populated[row["criterion_id"]] = populated.get(row["criterion_id"], 0) + 1
        for row in rows_of("select_criteria"):
            declared = row["band_count"]
            if declared is not None:
                count = populated.get(row["criterion_id"], 0)
                if count != declared:
                    raise BandSetError(
                        f"criterion {row['criterion_id']!r} declares a band_count of "
                        f"{declared} but carries {count} band(s) (FR-PKG-06): a "
                        f"partially populated band set must not be {boundary} — the "
                        "judge would see fewer bands than the declared mapping."
                    )
                self._validate_band_count(count)

    def update_criterion_field(
        self, v: PackageVersionId, criterion_id: str, field: str, value: Any
    ) -> None:
        """Set one criterion column — the guarded mutation surface `M-CALIB` writes
        through (`FR-CALIB-07`). Refuses locked fields on published versions with
        `SchemaLockViolation` naming the field; permits everything on drafts.

        `answer_key` is refused here regardless of lock state: the key has exactly one
        write door, `set_answer_key` (ADR-1's single canonical representation) — this
        generic path stores the raw value, and an unvalidated one would poison every
        later read of the version."""
        if field == "answer_key":
            raise PackageError(
                "answer_key is written through set_answer_key (FR-PKG-17, ADR-1) — "
                "the canonical setter validates and serializes the key; this generic "
                "field path would store it raw."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, f"criterion.{field}")
            tx.execute(
                PKG_STATEMENTS[f"update_criterion_{field}"],
                v=v, criterion_id=criterion_id, value=value,
            )
        self._invalidate()

    def update_band_field(
        self, v: PackageVersionId, criterion_id: str, ordinal: int,
        field: str, value: Any,
    ) -> None:
        """Set one band column, under the same guard (`TC-PKG-03` cases 7-10)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, f"band.{field}")
            tx.execute(
                PKG_STATEMENTS[f"update_band_{field}"],
                v=v, criterion_id=criterion_id, ordinal=ordinal, value=value,
            )
        self._invalidate()
