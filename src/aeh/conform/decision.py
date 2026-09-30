"""Decision-engine conformance: the F-JEV fixtures through the decision path on each backend."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from harness.corpora.manifest import CORPUS_ROOT, read_manifest

from .reports import ValidationRecord


# --- decision-engine conformance (Jev design delta §3.9, FR-CONFORM-10/11) ----------------------

#: CT-CONFORM-15: the four names every backend's decision report carries.
DECISION_REPORT_KEYS: tuple[str, ...] = (
    "decision_accepted_rate", "decision_band_exact_agreement",
    "decision_band_adjacent_agreement", "decision_llm_median_divergence",
)


F_JEV_CORPUS = "F-JEV"


#: Gate-confidence histogram bin width (FR-CONFORM-10's "gate-confidence distribution").
DECISION_GATE_BIN = 0.05


@dataclasses.dataclass(frozen=True)
class DecisionCell:
    """One F-JEV cell: the scoring request and the recorded LLM-panel median band ordinal."""

    cell_id: str
    request: Any
    llm_panel_median_ordinal: int


@dataclasses.dataclass(frozen=True)
class DecisionConformanceReport:
    """Per decision backend: the four CT-CONFORM-15 figures plus the gate histogram and the
    ineligibility reasons, and one backend-scoped validation record each. No pass/fail: Q-J5
    sets no threshold, so nothing here is a verdict."""

    per_backend: Mapping[str, Mapping[str, Any]]
    validation_records: tuple[ValidationRecord, ...]
    cells: int
    fixture_set_version: str


def load_f_jev_cells(corpus_root: Path | None = None) -> tuple[DecisionCell, ...]:
    """F-JEV's cells as `DecisionCell`s, in manifest order (FR-CONFORM-10)."""
    from aeh.judge import ScoringRequest

    root = (corpus_root or CORPUS_ROOT) / F_JEV_CORPUS
    manifest = read_manifest(root / "manifest.json")
    criteria = manifest["criteria"]
    cells = []
    for entry in manifest["submissions"]:
        cell = json.loads((root / entry["path"]).read_text(encoding="utf-8"))
        crit = criteria[cell["criterion_id"]]
        request = ScoringRequest(
            work_id=cell["cell_id"],
            criterion={"criterion_id": cell["criterion_id"], "text": crit["text"],
                       "bands": [{"band": b, "ordinal": i, "descriptor": d}
                                 for i, (b, d) in enumerate(crit["bands"])],
                       "exemplars": []},
            question={"prompt_text": "A crate rests on a ramp. Explain why it does not slide.",
                      "reference_solution": "Friction balances the component of weight."},
            evidence=cell["spans"], dependency_evidence=[],
            submission={"submission_id": cell["cell_id"], "student_ref": "ref-" + cell["cell_id"]},
            submission_text=cell["submission_text"])
        cells.append(DecisionCell(cell["cell_id"], request, int(cell["llm_panel_median_ordinal"])))
    return tuple(cells)


def _decide_cell(cell: DecisionCell, provider: Any, engine: Any) -> dict[str, Any]:
    """One cell through the decision path: eligibility, the one `decide`, the gate. A request
    the engine refuses or answers malformed is an outcome; a missing fixture is not. It
    propagates, so the E1 arm fails loudly rather than reporting a hole as a fallback."""
    from aeh.judge import Accepted, Ineligible, decision_eligibility, decision_request, gate_decision
    from aeh.prov import DecisionRequestRejectedError, MalformedResponseError

    eligibility = decision_eligibility(cell.request, engine, provider.decision_capabilities(engine.model))
    if isinstance(eligibility, Ineligible):
        return {"outcome": "ineligible", "reason": eligibility.reason, "gate": None}
    try:
        decision = provider.decide(decision_request(cell.request, engine), engine.model)
    except DecisionRequestRejectedError:
        return {"outcome": "rejected", "reason": "rejected", "gate": None}
    except MalformedResponseError:
        return {"outcome": "malformed", "reason": "malformed", "gate": None}
    # The engine's band for FR-CONFORM-11 is its argmax, whether or not the gate passed; a
    # tied top has no band.
    probabilities = list(decision.answers["band"].probabilities)
    top = max(probabilities)
    argmax = probabilities.index(top) if probabilities.count(top) == 1 else None
    gated = gate_decision(decision, cell.request, engine)
    if isinstance(gated, Accepted):
        return {"outcome": "accepted", "band_ordinal": gated.result.band_ordinal,
                "argmax_ordinal": argmax, "gate": float(gated.gate)}
    return {"outcome": "below_gate", "reason": gated.reason, "argmax_ordinal": argmax,
            "gate": None if gated.gate is None else float(gated.gate)}


def _share(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def run_decision_conformance(
    backends: Mapping[str, tuple[Any, Any, str]],
    cells: Sequence[DecisionCell] | None = None,
    *,
    fixture_set_version: str = "1",
    fixture_set_id: str | None = None,
) -> DecisionConformanceReport:
    """FR-CONFORM-10/11: F-JEV through the decision path on each configured backend.

    `backends` maps a decision provider name (`openrouter-jev`, `openjev`) to
    `(provider, DecisionEngine, backend_profile)`. The E1 arm passes the fixture double and the
    live arm passes the live providers. It is one function, and neither arm has a pass/fail
    threshold (design Q-J5).

    Per backend:

    - `decision_accepted_rate`: accepted cells / all cells.
    - `decision_band_exact_agreement` / `decision_band_adjacent_agreement`: on cells this
      backend AND another accepted (pooled over every other backend when there are more than
      two), the share with the same band / within one band. `None` when no cell is accepted
      by both.
    - `decision_llm_median_divergence`: the share of F-JEV cells whose engine band (the
      argmax, gate passed or not) differs from the recorded LLM-panel median (FR-CONFORM-11;
      a diagnostic only). Cells with no engine band (ineligible, rejected, malformed, or a
      tied top) are outside the denominator.
    - `decision_gate_histogram`: gate confidence in `DECISION_GATE_BIN` bins over every cell
      the gate saw. `decision_ineligible_reasons`: counts by reason.

    Each backend's figures are written as their own validation record (`CT-CONFORM-06`), keyed
    on the backend profile and the engine build and never merged across backends.
    """
    from aeh import pkg as pkg_module
    from aeh.orch import JUDGE_DECISION_TEMPLATE_V as decision_template_v

    cell_list = tuple(cells if cells is not None else load_f_jev_cells())
    if fixture_set_id is None and cells is None:
        # The record names the exact F-JEV content, so a regenerated corpus writes a new key
        # rather than overwriting the old record under the same one.
        fixture_set_id = read_manifest(CORPUS_ROOT / F_JEV_CORPUS / "manifest.json").get("fixture_set_id")
    set_tag = fixture_set_id or fixture_set_version
    outcomes: dict[str, dict[str, dict[str, Any]]] = {
        name: {cell.cell_id: _decide_cell(cell, provider, engine) for cell in cell_list}
        for name, (provider, engine, _profile) in backends.items()
    }
    medians = {cell.cell_id: cell.llm_panel_median_ordinal for cell in cell_list}
    bins = int(round(1 / DECISION_GATE_BIN))
    per_backend: dict[str, dict[str, Any]] = {}
    records: list[ValidationRecord] = []
    for name, (_provider, engine, profile) in backends.items():
        mine = outcomes[name]
        accepted = {cid: o["band_ordinal"] for cid, o in mine.items() if o["outcome"] == "accepted"}
        banded = {cid: o["argmax_ordinal"] for cid, o in mine.items()
                  if o.get("argmax_ordinal") is not None}
        pairs = [(band, outcomes[other][cid]["band_ordinal"])
                 for other in backends if other != name
                 for cid, band in accepted.items()
                 if outcomes[other][cid]["outcome"] == "accepted"]
        histogram: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for outcome in mine.values():
            if outcome["gate"] is not None:
                low = min(int(outcome["gate"] / DECISION_GATE_BIN + 1e-9), bins - 1)
                key = f"{low * DECISION_GATE_BIN:.2f}"
                histogram[key] = histogram.get(key, 0) + 1
            if outcome["outcome"] == "ineligible":
                reasons[outcome["reason"]] = reasons.get(outcome["reason"], 0) + 1
        figures = {
            "decision_accepted_rate": _share(len(accepted), len(cell_list)),
            "decision_band_exact_agreement": _share(sum(1 for a, b in pairs if a == b), len(pairs)),
            "decision_band_adjacent_agreement": _share(sum(1 for a, b in pairs if abs(a - b) <= 1), len(pairs)),
            "decision_llm_median_divergence": _share(
                sum(1 for cid, band in banded.items() if band != medians[cid]), len(banded)),
            "decision_gate_histogram": dict(sorted(histogram.items())),
            "decision_ineligible_reasons": dict(sorted(reasons.items())),
            "decision_outcomes": {k: sum(1 for o in mine.values() if o["outcome"] == k)
                                  for k in ("accepted", "below_gate", "ineligible", "rejected", "malformed")},
            "cells": len(cell_list),
            "fixture_set_id": set_tag,
        }
        per_backend[name] = figures
        record = ValidationRecord(
            package_version=f"{F_JEV_CORPUS}@{fixture_set_version}",
            criterion=F_JEV_CORPUS,
            population_scope=F_JEV_CORPUS,
            backend_profile=profile,
            panel_build_ref=f"decision:{name}:{engine.model.build_id}",
            scoring_model=decision_template_v,
            administration=f"{F_JEV_CORPUS}@{name}:{set_tag}",
            figure=dict(figures),
        )
        pkg_module.record_validation(
            package_version=record.package_version, population_scope=record.population_scope,
            criterion=record.criterion, backend_profile=record.backend_profile,
            panel_build_ref=record.panel_build_ref, scoring_model=record.scoring_model,
            administration=record.administration, figure=dict(record.figure))
        records.append(record)
    return DecisionConformanceReport(per_backend=per_backend, validation_records=tuple(records),
                                     cells=len(cell_list), fixture_set_version=fixture_set_version)
