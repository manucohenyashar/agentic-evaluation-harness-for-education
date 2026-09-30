"""Answer keys, the grade policy, the prompt-prefix budget and calibration papers."""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from aeh.ingest import DocumentId
from aeh.pkg import GradePolicy, default_grade_policy

from .settings import _estimate_tokens, LOGGER, _now, _prefix_ceiling
from .errors import SetupError, SetupOrderError
from .records import PrefixBudgetReport


class KeysAndPolicyMixin:
    """Answer keys (gate 2), the grade policy, the prefix budget check and calibration papers."""

    def set_answer_keys(self, keys: Mapping[str, Sequence[str]]) -> None:
        """The teacher's answer keys — BLOCKING gate 2 (`§4.2.1`), with `FR-SETUP-03`'s
        full semantics since #53.

        The confirmed inventory's deterministic criteria are staged first (idempotent
        — `confirm_inventory` already ran the same staging, so this is a top-up for a
        draft that resumed mid-setup). Every named criterion must exist — the staging
        convention is `CRIT-<question id>` — and every key element is validated
        against the option vocabulary the criterion's question declares: a key naming
        an option the teacher never offered is refused HERE, before anything is
        written. A question with no option set (an open criterion keyed by its band
        ids) has no vocabulary to validate against and accepts the key as given —
        there is no default, no skip and no inference (`FR-SETUP-03`): publication
        stays refused while any deterministic criterion is unkeyed. The write itself
        is `PackageCatalog.set_answer_key` (`FR-PKG-17`'s single canonical
        representation)."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "answer keys come after the confirmed inventory (S3 blocks S4, "
                "§4.2.1): confirm_inventory first — the keys name criteria the "
                "confirmed questions become."
            )
        if not keys:
            raise SetupError(
                "set_answer_keys with an empty mapping keys nothing — name at least "
                "one criterion and its acceptable option ids."
            )
        self._stage_deterministic_criteria(v)
        criteria = {row["criterion_id"]: row for row in self._catalog.criteria(v)}
        unknown = [criterion_id for criterion_id in keys
                   if criterion_id not in criteria]
        if unknown:
            raise SetupError(
                f"set_answer_keys names criterion(s) {', '.join(unknown)} that do "
                f"not exist in version {v!r} — the confirmed inventory's "
                "deterministic criteria are staged as CRIT-<question id>; key those, "
                "or author a criterion through M-PKG first."
            )
        # Validate EVERY key before writing ANY (`FR-SETUP-03`): a refused call
        # must leave the stored keys exactly as they were — a blocking gate that
        # half-applies would make its refusal indistinguishable from a partial
        # save, and the docstring's "refused HERE, before anything is written"
        # would be a lie on the second key.
        validated: list[tuple[str, list[str]]] = []
        for criterion_id, key in keys.items():
            question_id = criteria[criterion_id]["question_id"]
            allowed = {row["option_id"] for row in (
                self._catalog.question_options(v, question_id)
                if question_id else ())}
            if allowed:
                bad = [option for option in key if option not in allowed]
                if bad:
                    raise SetupError(
                        f"the key for {criterion_id!r} names option(s) "
                        f"{', '.join(bad)} that question {question_id!r} does not "
                        "offer — a key is a choice among the options the teacher "
                        "declared (FR-SETUP-03: no inference from the reference "
                        "solution, no default key). Nothing was written."
                    )
            validated.append((criterion_id, list(key)))
        for criterion_id, key in validated:
            self._catalog.set_answer_key(v, criterion_id, key)
        LOGGER.info(
            "set %d answer key(s) for version %s — blocking step S4, each validated "
            "against its question's option vocabulary (FR-SETUP-03)", len(keys), v,
        )

    # -- Stage A: grade policy, prefix budget, calibration papers (#53, skippable) ----------

    def set_grade_policy(self, policy: GradePolicy | None) -> GradePolicy:
        """Capture the teacher's grade policy — or take the default explicitly
        (`FR-SETUP-12`, #53). Returns the policy that APPLIES: the declared one, or
        `default_grade_policy()` when `policy` is None.

        Either way the step records WHICH it was (`policy_declared` vs
        `default_taken`), so M-CALIB and M-STATS can tell a teacher's judgment from
        the system's (R62); publication later writes the default for a teacher who
        never spoke, but a step that ran here is never overwritten. The policy object
        itself is validated by `PackageCatalog.set_grade_policy` against the closed
        rule vocabulary (FR-PKG-14) — a free-text formula is refused there, and an
        invalid policy writes nothing.

        Requires the confirmed inventory first (the policy is S5 in §4.2.1's
        sequence — captured after the criteria exist)."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "the grade policy comes after the confirmed inventory (§4.2.1's S5): "
                "confirm_inventory first — the policy grades criteria that must "
                "already exist."
            )
        if policy is None:
            applied = default_grade_policy()
            status = "default_taken"
        else:
            applied = policy
            status = "policy_declared"
        self._catalog.set_grade_policy(v, applied)
        self._catalog.record_step(
            v, step_id="grade_policy", status=status,
            payload=json.dumps({
                "source": "declared" if policy is not None else "default",
                "policy": applied.to_dict(),
            }, sort_keys=True),
            recorded_at=_now(),
        )
        LOGGER.info(
            "grade policy %s for version %s (%s) — recorded as %s (FR-SETUP-12, "
            "R62)", "declared" if policy is not None else "defaulted", v,
            applied.combination, status,
        )
        return applied

    def check_prefix_budget(self) -> PrefixBudgetReport:
        """Count each (question, criterion) prefix against the configured ceiling
        and remediate the overage by dropping the lowest-value exemplars
        (`FR-SETUP-11`, `CT-SETUP-09`, #53).

        A pair's prefix is what a judge prompt would assemble: the question's prompt
        and reference solution, the criterion's construct, its band descriptors, and
        every exemplar's material — counted with the documented estimate
        (`_estimate_tokens`; the exact token seam is `TC-SETUP-14`'s deferred story)
        against `RunConfig.prefix_token_ceiling` — the per-profile ceiling
        (`FR-CONF-06`/`-10`; the fallback for a service without a resolved run
        config is `SETUP_PREFIX_TOKEN_CEILING_DEFAULT`). Where a
        pair is over, the drop policy runs BEFORE publication, so the overage is
        still fixable: exemplars leave lowest-value first (value is the points of
        the band the exemplar anchors), and the remediation NEVER touches the
        reference solution or the criterion text. A band's LAST remaining exemplar
        is never dropped — the calibration floor: stripping a band's last example
        would leave the judge nothing to calibrate that band against, a cure worse
        than the overage. What still does not fit is reported as the residual, not
        hidden; the drops are recorded in a `prefix_budget` step record and on the
        report itself.

        Requires the confirmed inventory (the pairs are the inventory's questions
        with the criteria that exist for them)."""
        v = self._require_draft_version()
        stored = self._catalog.proposal(v)
        if stored is None or stored["confirmed_at"] is None:
            raise SetupOrderError(
                "the prefix budget is checked against the confirmed inventory's own "
                "criteria (§4.2.1): confirm_inventory first."
            )
        ceiling = _prefix_ceiling(self._run_config)
        questions = {row["question_id"]: row for row in self._catalog.questions(v)}
        exemplar_reader = getattr(self._catalog, "exemplars", None)
        all_exemplars = exemplar_reader(v) if exemplar_reader is not None else ()
        blob_reader = getattr(self._catalog, "blob_text", None)
        by_pair: dict[str, list[dict]] = {}
        for row in all_exemplars:
            by_pair.setdefault(row.get("criterion_id", ""), []).append(row)
        per_pair: list[dict] = []
        dropped: list[str] = []
        for criterion in self._catalog.criteria(v):
            question = questions.get(criterion["question_id"])
            if question is None:
                # A criterion anchored to nothing has no question half to assemble —
                # the criterion's own text is still the judge's material.
                question = {"prompt_text": "", "reference_solution": ""}
            bands = self._catalog.bands(criterion["criterion_id"])
            static_text = "\n".join(filter(None, (
                question["prompt_text"], question["reference_solution"],
                criterion.get("construct_tag"),
                *(band["descriptor"] for band in bands),
            )))
            static_tokens = _estimate_tokens(static_text)
            pair_exemplars = by_pair.pop(criterion["criterion_id"], [])
            if not pair_exemplars:
                per_pair.append({
                    "question_id": criterion["question_id"],
                    "criterion_id": criterion["criterion_id"],
                    "assembled_tokens": static_tokens,
                    "ceiling_tokens": ceiling,
                    "exemplars_before": 0, "exemplars_after": 0,
                    "over_by_tokens": max(0, static_tokens - ceiling),
                    "dropped": (),
                })
                continue
            # Each exemplar's own material, counted once, so a drop's subtraction is
            # the estimate's arithmetic and not a re-read. The band→points value is
            # `points_for_band`'s alone (TC-PKG-C05/CT-PKG-05: the mapping is
            # single-canonical, RISK-05) — this module never maps a stored band row
            # to a score itself.
            points_for_band = getattr(self._catalog, "points_for_band", None)
            band_points: dict[str, float] = {}
            scored = []
            for row in pair_exemplars:
                text = (blob_reader(row["blob_hash"])
                        if blob_reader is not None else "")
                band = row["band"]
                if band not in band_points:
                    band_points[band] = (
                        float(points_for_band(criterion["criterion_id"], band))
                        if points_for_band is not None else 0.0)
                scored.append({
                    "exemplar_id": row["exemplar_id"],
                    "band": band,
                    "band_points": band_points[band],
                    "tokens": _estimate_tokens(text),
                })
            assembled = static_tokens + sum(item["tokens"] for item in scored)
            pair_dropped: list[str] = []
            if assembled > ceiling:
                # Lowest value first: band points, then the id (a stable, stated
                # order — RISK-33's answer to "which exemplar left" is not a coin
                # flip). The calibration floor: an exemplar whose band carries no
                # other survivor is never dropped.
                survivors = list(scored)
                while assembled > ceiling:
                    droppable = [
                        item for item in survivors
                        if sum(1 for other in survivors
                               if other["band"] == item["band"]) > 1
                    ]
                    if not droppable:
                        break  # the floor holds: report the residual honestly
                    victim = min(droppable,
                                 key=lambda item: (item["band_points"],
                                                   item["exemplar_id"]))
                    survivors.remove(victim)
                    self._catalog.remove_exemplar(v, victim["exemplar_id"])
                    assembled -= victim["tokens"]
                    dropped.append(victim["exemplar_id"])
                    pair_dropped.append(victim["exemplar_id"])
                LOGGER.warning(
                    "prefix over the %d-token ceiling for (%s, %s) in version %s — "
                    "dropped %d exemplar(s), %d token(s) residual",
                    ceiling, criterion["question_id"], criterion["criterion_id"],
                    v, len(pair_dropped), max(0, assembled - ceiling),
                )
            per_pair.append({
                "question_id": criterion["question_id"],
                "criterion_id": criterion["criterion_id"],
                "assembled_tokens": assembled,
                "ceiling_tokens": ceiling,
                "exemplars_before": len(scored),
                "exemplars_after": len(survivors),
                "over_by_tokens": max(0, assembled - ceiling),
                "dropped": tuple(pair_dropped),
            })
        residual = sum(entry["over_by_tokens"] for entry in per_pair)
        report = PrefixBudgetReport(
            package_version_id=v, ceiling_tokens=ceiling,
            over_budget=residual > 0, dropped_exemplars=tuple(dropped),
            per_pair=tuple(per_pair), residual_tokens=residual,
            note=("the token count is the documented estimate; the exact counting "
                  "seam is TC-SETUP-14's deferred story"),
        )
        # The check's own provenance row: what was compared, what left, what is
        # still over — readable without this process (the state-is-the-database
        # rule), and NOT a member of the enumerated steps (the enumeration is the
        # five the design names; the budget check is the grade_policy step's other
        # half). The row is keyed (version, step_id) and UPSERTED, so a second
        # check — a resumed service re-running the step — would otherwise overwrite
        # the first one's `dropped_exemplars` with its own (empty) list, and the
        # dropped rows are gone from `exemplar`: nothing in the database would name
        # what left the prefix (FR-SETUP-11's record clause). The durable record
        # therefore carries the UNION of what every check on this version removed;
        # the report object stays per-call.
        record_step = getattr(self._catalog, "record_step", None)
        if record_step is not None:
            prior_dropped: list[str] = []
            read_record = getattr(self._catalog, "step_record", None)
            if read_record is not None:
                prior = read_record(v, "prefix_budget")
                if prior and prior.get("payload"):
                    try:
                        prior_dropped = list(
                            json.loads(prior["payload"]).get("dropped_exemplars", ()))
                    except (TypeError, ValueError):
                        prior_dropped = []
            merged_dropped = sorted({*dropped, *prior_dropped})
            record_step(
                v, step_id="prefix_budget",
                status=("within_budget" if residual == 0 and not merged_dropped
                        else "over_budget_remediated" if residual == 0
                        else "over_budget_residual"),
                payload=json.dumps({
                    "ceiling_tokens": ceiling,
                    "dropped_exemplars": merged_dropped,
                    "residual_tokens": residual,
                    "pairs": per_pair,
                    "estimate": "chars/4 (TC-SETUP-14's exact seam deferred)",
                }, sort_keys=True),
                recorded_at=_now(),
            )
        LOGGER.info(
            "prefix budget checked for version %s: ceiling %d, %d exemplar(s) "
            "dropped, %d token(s) residual (FR-SETUP-11)",
            v, ceiling, len(dropped), residual,
        )
        return report

    def store_calibration_papers(self, document_ids: Sequence[DocumentId]) -> None:
        """Accept the teacher-marked calibration papers and record that they were
        stored — and that nothing was derived from them (`FR-SETUP-15`, #53).

        The papers travel with the package version as a step record naming every
        uploaded document; no ambiguity discovery runs over them here, and the
        record says so explicitly: the ambiguity-discovery claim cannot exist until
        M-CALIB ships (`TC-SETUP-18`'s intake test is deferred with it). Nothing is
        read, judged or scored — storage of the fact, not use of the papers."""
        v = self._require_draft_version()
        ids = [str(document_id) for document_id in document_ids]
        if not ids:
            raise SetupError(
                "store_calibration_papers with an empty list stores nothing — name "
                "at least one uploaded document id."
            )
        self._catalog.record_step(
            v, step_id="calibration_papers", status="stored_not_used",
            payload=json.dumps({
                "document_ids": ids,
                "used": False,
                "note": "no ambiguity discovery ran and none can claim to until "
                        "M-CALIB ships (FR-SETUP-15)",
            }, sort_keys=True),
            recorded_at=_now(),
        )
        LOGGER.info(
            "stored %d calibration paper(s) for version %s — unused, pending "
            "M-CALIB (FR-SETUP-15)", len(ids), v,
        )
