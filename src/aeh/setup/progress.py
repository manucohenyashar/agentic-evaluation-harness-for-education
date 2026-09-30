"""The setup steps, what each recorded, and what remains."""

from __future__ import annotations

import json

from aeh.pkg import PackageVersionId, default_grade_policy

from .settings import LOGGER, _now, SETUP_MAX_CONFIRMATIONS
from .records import SetupProgress, SetupStep
from .readback import _stored_readback_status


class ProgressMixin:
    """The step list for the console, and the defaults recorded for skipped steps."""

    def steps(self) -> SetupProgress:
        """The enumerated setup steps and what remains (`TC-SETUP-03`'s shape,
        `NFR-SETUP-04`'s honest count).

        With no draft version the package is in one of two states, told apart by
        `has_version`: NOT STARTED (no version at all — the inventory step is
        available, because proposing mints the initial version) or FINISHED (a
        published version, no draft — every step unavailable and the count 0: no step
        can be acted on, and a count that says otherwise is the console lying).

        `answer_keys`' done state is the structural fact `publish` enforces — every
        deterministic criterion keyed. Since #53 stages the confirmed inventory's
        deterministic criteria (`CRIT-<question id>`, `FR-SETUP-03`), a confirmed
        inventory with mcq/mixed questions carries unkeyed criteria until the teacher
        keys them and the count says so; an inventory with none is vacuously keyed,
        which the console says too rather than demanding a step whose work does not
        exist."""
        v = self._catalog.draft_version()
        if v is None:
            # No draft. Two states, told apart (`has_version`): a package with NO
            # version has not started — the inventory step is available (its first
            # move mints the draft); a package whose versions are all published has
            # FINISHED — no step can be acted on, and the remaining count is 0
            # because a count that says otherwise is the console lying.
            started = self._catalog.has_version()
            # The finished package's grade-policy record still tells the truth about
            # what was taken (#53): the draft is gone, but the step records the
            # published version carries are read through `latest_version` — a catalog
            # without the surface (a rung-0 double, or a version published without
            # M-SETUP) reads as "no record", never as a console crash.
            latest_reader = getattr(self._catalog, "latest_version", None)
            latest = latest_reader() if latest_reader is not None else None
            grade_record = (self._grade_policy_record(latest)
                            if latest is not None else None)
            if grade_record is not None:
                grade_note = (
                    f"recorded: {grade_record['status']} at "
                    f"{grade_record['recorded_at']} (FR-SETUP-14); the applied "
                    "policy is stored on the published version (FR-SETUP-12)")
            elif started:
                grade_note = (
                    "setup has finished; the published version carries no recorded "
                    "grade-policy step — it may not have been set up through "
                    "M-SETUP (FR-SETUP-12)")
            else:
                grade_note = (
                    "setup has not started — the policy is captured (or the default "
                    "taken and recorded) once a draft exists (FR-SETUP-12)")
            later_steps = (
                SetupStep(
                    step_id="rubric_readback",
                    name="Rubric read-back against the stored rubric",
                    blocking=False, available=False, done=False,
                    note="needs a draft version and a confirmed inventory — the read "
                    "back anchors criteria to confirmed questions (FR-SETUP-02)",
                ),
                SetupStep(
                    step_id="decomposability",
                    name="Criterion decomposability and dependencies",
                    blocking=False, available=False, done=False,
                    note="non-blocking — the §5.3 classification runs once the read "
                    "back has staged the criteria; skipped steps record their "
                    "default (FR-SETUP-14)",
                ),
                SetupStep(
                    step_id="grade_policy",
                    name="Grade policy, boundaries and the prefix budget",
                    blocking=False, available=False, done=grade_record is not None,
                    note=grade_note,
                ),
            )
            return SetupProgress(
                package_version_id=None,
                steps=(
                    SetupStep(
                        step_id="inventory",
                        name="Question inventory: propose, correct, confirm",
                        blocking=True, available=not started, done=False,
                        note="setup has not started — proposing mints the package's "
                        "initial version" if not started else
                        "setup has finished (its version is published); a new "
                        "instrument is a new package or a revision (FR-PKG-02)",
                    ),
                    SetupStep(
                        step_id="answer_keys",
                        name="Answer keys for the deterministic criteria",
                        blocking=True, available=False, done=False,
                        note="needs a draft version and a confirmed inventory",
                    ),
                ) + later_steps,
                remaining_steps=1 if not started else 0,
                ready_to_publish=False,
            )
        stored = self._catalog.proposal(v)
        confirmed = bool(stored and stored["confirmed_at"])
        criteria = self._catalog.criteria(v)
        unkeyed = [
            row["criterion_id"] for row in criteria
            if row.get("scoring_model") == "atomic" and not row.get("answer_key")
        ]
        keys_done = not unkeyed
        keys_note = ""
        if not confirmed:
            keys_note = "unlocks when the question inventory is confirmed (§4.2.1)"
        elif unkeyed:
            keys_note = f"answer keys missing for: {', '.join(unkeyed)}"
        elif not any(row.get("scoring_model") == "atomic" for row in criteria):
            keys_note = ("no deterministic criteria in this inventory — nothing to "
                         "key, and gate 2 does not hold this publish")
        # The rubric read-back went live with #51: available once gate 1 is met, done
        # when the stored read-back row reads `proposed` (the degraded row is a fact
        # the note carries, not a done). The status lives in the row's PAYLOAD — the
        # row's own columns are provenance only. The getattr guard keeps the
        # enumeration honest over rung-0 doubles that do not model the write surface —
        # a missing member reads as "not done", never as a console crash.
        readback_member = getattr(self._catalog, "readback", None)
        stored_readback = readback_member(v) if readback_member is not None else None
        readback_status = _stored_readback_status(stored_readback)
        readback_note = ""
        if not confirmed:
            readback_note = "unlocks when the question inventory is confirmed (§4.2.1)"
        elif readback_status == "needs_manual_entry":
            readback_note = ("the read back degraded to needs_manual_entry after its "
                             "attempt budget — enter criteria through M-PKG, or a new "
                             "version re-reads the rubric (FR-SETUP-04)")
        # The decomposability step's record (#52): the provenance row the step's own
        # writes leave (confirmations, dependency proposals, approvals), read back
        # through the same getattr guard the other write surfaces use — a catalog
        # without the recording surface reads as "not done", never as a crash.
        step_reader = getattr(self._catalog, "step_record", None)
        decomposability_record = (step_reader(v, "decomposability")
                                  if step_reader is not None else None)
        decomposability_note = ""
        if not confirmed:
            decomposability_note = (
                "unlocks when the question inventory is confirmed (§4.2.1)")
        elif readback_status != "proposed":
            decomposability_note = (
                "unlocks when the rubric read-back has staged the criteria — the "
                "§5.3 table judges criteria that exist (FR-SETUP-06)")
        elif decomposability_record is not None:
            decomposability_note = (
                f"recorded: {decomposability_record['status']} at "
                f"{decomposability_record['recorded_at']} (FR-SETUP-14)")
        else:
            decomposability_note = (
                "surfaced confirmations await the teacher; dependencies stay at "
                "zero until explicitly approved (FR-SETUP-07, FR-SETUP-10)")
        # The grade-policy step's record (#53): written by `set_grade_policy` (the
        # teacher's declared policy, or the default taken explicitly) or by publish's
        # default recording — read through the same getattr guard, so a catalog
        # without the recording surface reads as "not done", never as a crash.
        grade_policy_record = (step_reader(v, "grade_policy")
                               if step_reader is not None else None)
        if not confirmed:
            grade_policy_note = (
                "unlocks when the question inventory is confirmed (§4.2.1)")
        elif readback_status != "proposed":
            grade_policy_note = (
                "unlocks once the rubric read-back has run — the policy is captured "
                "after the criteria exist (§4.2.1's S5)")
        elif grade_policy_record is not None:
            grade_policy_note = (
                f"recorded: {grade_policy_record['status']} at "
                f"{grade_policy_record['recorded_at']} (FR-SETUP-14)")
        else:
            grade_policy_note = (
                "the default weighted-sum policy applies when this step is skipped — "
                "taken and recorded at publication (FR-SETUP-12, FR-SETUP-14)")
        later = (
            SetupStep(
                step_id="rubric_readback",
                name="Rubric read-back against the stored rubric",
                blocking=False, available=confirmed,
                done=readback_status == "proposed",
                note=readback_note,
            ),
            SetupStep(
                step_id="decomposability",
                name="Criterion decomposability and dependencies",
                blocking=False,
                # Available once criteria EXIST for the table to judge — the read
                # back is what stages them. Hand-authored criteria alone do not
                # unlock the step: the §5.3 classification is the read-back
                # population's step (§4.2.1's S5), and an unlocked-but-empty step
                # would be the console offering an operation with no work behind it.
                available=confirmed and readback_status == "proposed",
                done=decomposability_record is not None,
                note=decomposability_note,
            ),
            SetupStep(
                step_id="grade_policy",
                name="Grade policy, boundaries and the prefix budget",
                blocking=False,
                # The policy is captured after the criteria exist (§4.2.1's S5): the
                # same unlock the decomposability step carries. An unlocked-but-
                # unrecorded step's note states the default the skip takes, so the
                # console can say what WILL happen if the teacher moves on.
                available=confirmed and readback_status == "proposed",
                done=grade_policy_record is not None,
                note=grade_policy_note,
            ),
        )
        steps = (
            SetupStep(
                step_id="inventory",
                name="Question inventory: propose, correct, confirm",
                blocking=True, available=True, done=confirmed,
                note="" if confirmed else "the teacher's confirmation is blocking "
                "gate 1 of 2 (FR-SETUP-02)",
            ),
            SetupStep(
                step_id="answer_keys",
                name="Answer keys for the deterministic criteria",
                blocking=True, available=confirmed, done=keys_done,
                note=keys_note,
            ),
        ) + later
        remaining = sum(1 for step in steps if step.available and not step.done)
        ready = confirmed and keys_done
        return SetupProgress(
            package_version_id=v, steps=steps, remaining_steps=remaining,
            ready_to_publish=ready,
        )

    def _grade_policy_record(self, v: PackageVersionId | None) -> dict | None:
        """The grade_policy step's provenance row, or None — read through the same
        getattr guard the other step reads use: a catalog without the recording
        surface reads as "no record", never as a console crash."""
        if v is None:
            return None
        reader = getattr(self._catalog, "step_record", None)
        return reader(v, "grade_policy") if reader is not None else None

    def _record_uncompleted_step_default(self, v: PackageVersionId) -> None:
        """Record each skipped step's default where the step never recorded itself
        (`FR-SETUP-14`, `#52`/`#53`): completing setup by skipping a step leaves
        stored provenance naming it, so the default is never indistinguishable from
        an explicit choice (`R62`, `CT-SETUP-01`). A step that DID record — the read
        back ran, the teacher confirmed classifications, the policy was set — is
        never overwritten. The gate checks have already passed, so these writes are
        on the publish path's happy tail, immediately before the lock flip."""
        record = getattr(self._catalog, "record_default_step", None)
        if record is None:
            return
        # The rubric read-back: skipped when NO read-back row exists — the row is
        # that step's own record (proposed or degraded), so its absence is the skip.
        readback_reader = getattr(self._catalog, "readback", None)
        if readback_reader is not None and readback_reader(v) is None:
            if record(
                v, step_id="rubric_readback", status="default_taken",
                payload=json.dumps({
                    "default": (
                        "the rubric read-back was skipped: no criteria were read "
                        "from the rubric, so no derived default band set was "
                        "applied and the package carries only the staged and "
                        "hand-authored criteria (FR-SETUP-04)."
                    ),
                }, sort_keys=True),
                recorded_at=_now(),
            ):
                LOGGER.info(
                    "recorded the rubric read-back's default for version %s — the "
                    "skip is stored provenance, not silence (FR-SETUP-14)", v,
                )
        written = record(
            v, step_id="decomposability", status="default_taken",
            payload=json.dumps({
                "default": (
                    "the decomposability step was skipped: the §5.3 table's "
                    "verdicts stand as recorded (source 'default', holistic on any "
                    "unclear case) and dependencies stay at zero — no approval was "
                    "recorded (FR-SETUP-10)."
                ),
                "confirmations_requested":
                    self._confirmations_requested.get(v, 0),
                "confirmation_cap": SETUP_MAX_CONFIRMATIONS,
            }, sort_keys=True),
            recorded_at=_now(),
        )
        if written:
            LOGGER.info(
                "recorded the decomposability step's default for version %s — the "
                "skip is stored provenance, not silence (FR-SETUP-14)", v,
            )
        # The grade policy: the default is APPLIED — written as the stored row,
        # because the recording obligation is discharged by storing the policy
        # (FR-SETUP-12, C10's distinction between a stored default and the read-side
        # fallback) — and recorded as taken, but only where the teacher never
        # spoke: a policy row already present (declared here, or set through M-PKG
        # directly) is never overwritten. The guard-outside write
        # (`set_default_grade_policy`, pkg.py) keeps the publish path's audited
        # window to one lock-carrying statement, exactly as `record_default_step`
        # does for the skip records.
        default_setter = getattr(self._catalog, "set_default_grade_policy", None)
        setter = getattr(self._catalog, "set_grade_policy", None)
        if default_setter is not None:
            applied = default_setter(v, default_grade_policy())
        elif setter is not None:
            declared = getattr(self._catalog, "grade_policy_declared", None)
            applied = (declared is None or not declared(v))
            if applied:
                setter(v, default_grade_policy())
        else:
            applied = False
        if applied and record(
            v, step_id="grade_policy", status="default_taken",
            payload=json.dumps({
                "default": (
                    "the grade-policy step was skipped: the default policy "
                    "(unweighted sum of criteria, raw points, no boundary "
                    "table) applies and is stored on the version "
                    "(FR-SETUP-12)."
                ),
                "policy": default_grade_policy().to_dict(),
            }, sort_keys=True),
            recorded_at=_now(),
        ):
            LOGGER.info(
                "recorded the grade policy's default for version %s — applied "
                "and stored as a default, never silent (FR-SETUP-12, "
                "FR-SETUP-14)", v,
            )
