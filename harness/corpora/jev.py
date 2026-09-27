"""The Jev decision-engine corpora that are generated rather than captured (#445).

Jev test plan §4.4 names seven corpora. Two are produced by a run and live with the capture
that records them, not here:

- **F-JEV-DECISIONS** needs extracted evidence inside every `decide` request's state, so it is
  captured through `run_to_completion` (`tests/support/pipe_world.py`, `DECISION_OUTCOMES`).
- **F-SCHEMA's Cohort-27 database** is built by `tests/support/jev_corpora.py` from the Cohort
  migrations 1..27, pinned byte-for-byte to their text at `fb12d1e`.

This module generates the other four. Nothing in it imports `aeh`, and nothing computes a
statistic: the corpora are data plus the counts a hand computation starts from.

- **F-JEV-WIRE** holds synthetic HTTP bodies in the design §1.2 schema for both backends. There
  are well-formed answers, one body per malformed shape in TC-PROV-25, error statuses, a 429
  with `Retry-After`, and a response reporting a different `model`. Every body is labelled
  synthetic: they come from vendor documentation until TC-PROV-36/37 capture real ones.
- **F-JEV** holds 40 conformance cells over a 4-band and a 6-band criterion (FR-CONFORM-10),
  with a recorded answer per backend. The answers are stored as figures (band probabilities,
  sufficiency, P(cited) per span), not as request-keyed fixtures.
  `tests.support.jev_corpora.record_f_jev` turns them into `decide` recordings for whatever
  `DecisionRequest` the shipped `judge.decision_request` builds. A key that moves with a
  legitimate prompt change then re-derives, instead of stranding a committed recording.
- **F-JEV-PERF** is manifest-only: 350 F-SYNTH submissions × 6 judged criteria, the NFR-SYS-05
  shape, for PERF-16's timing. PERF-16 runs live, so it needs work to grade, not answers.
- **F-STATS-JEV** holds blind labels partitioned by engine, with the named subsets TC-STATS-33…35
  read, 5 planted inadmissible labels, and each subset's confusion counts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from harness.corpora import adv_inj, synth

CORPUS_VERSION = "1"
SYNTHETIC_SOURCE = "synthetic from vendor documentation (Jev design delta §1.2); not a live capture"
#: Backends by deployment, not by provider name: M-PROV is the only module that names a
#: backend (CT-PROV-15, `test_import_graph`). `tests.support.jev_corpora.BACKEND_PROVIDER` maps
#: `cloud` to the OpenRouter provider and `edge` to the local OpenJev provider.
BACKENDS: tuple[str, ...] = ("cloud", "edge")


# --- F-JEV-WIRE ----------------------------------------------------------------------------------

#: The requests every wire body answers. `canonical` has one question of each type plus a
#: citation Noul; `two_level` exists for TC-PROV-25's "indices {0,2} for 2 levels" row.
WIRE_REQUESTS: dict[str, dict[str, Any]] = {
    "canonical": {
        "state": "### criterion\nExplains equilibrium on the ramp.\n\n### submission\nThe crate "
                 "does not slide because static friction balances the component of weight.",
        "questions": {
            "topic": {"type": "choice", "instructions": "Which concept does the answer use?",
                      "options": {"friction": "static friction", "normal": "normal force",
                                  "gravity": "weight only"}},
            "band": {"type": "score", "instructions": "Which band does the work meet?",
                     "levels": ["Beginning", "Developing", "Proficient", "Exemplary"]},
            "evidence_sufficient": {"type": "noul", "instructions": "Is the evidence sufficient?"},
            "cite_a": {"type": "noul", "instructions": "Does span a support the band?"},
        },
    },
    "two_level": {
        "state": "### criterion\nStates the net force.\n\n### submission\nThe net force is zero.",
        "questions": {
            "band": {"type": "score", "instructions": "Met or not met?",
                     "levels": ["not met", "met"]},
        },
    },
}

_LEVELS = WIRE_REQUESTS["canonical"]["questions"]["band"]["levels"]
#: The state string a 400/422 body echoes; TC-PROV-28 asserts it never reaches an error message.
STATE_SENTINEL = "ZQXJ-7-STATE-SENTINEL"


def _good_answers(confidence: bool) -> dict[str, Any]:
    band = {"type": "score", "score": 2.05,
            "probabilities": {"0": 0.02, "1": 0.08, "2": 0.73, "3": 0.17},
            "legend": {str(i): level for i, level in enumerate(_LEVELS)}}
    topic = {"type": "choice", "choice": "friction",
             "probabilities": {"friction": 0.91, "normal": 0.06, "gravity": 0.03}}
    if confidence:
        band["confidence"] = 0.64
        topic["confidence"] = 0.865
    return {"topic": topic, "band": band,
            "evidence_sufficient": {"type": "noul", "noul": 0.94},
            "cite_a": {"type": "noul", "noul": 0.88}}


def _body(backend: str, answers: dict[str, Any], model: str | None = None) -> dict[str, Any]:
    if backend == "cloud":
        return {"model": model or "typesafe/jev-1.13-20260917", "answers": answers,
                "usage": {"input_tokens": 412, "output_tokens": 0, "cost": 0.0000412}}
    return {"model": model or "openjev", "answers": answers,
            "usage": {"input_tokens": 412, "output_tokens": 0}}


def _malformed(mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    # From a Jev-shaped body (design 1.8: Choice/Score carry Jev's `confidence`), so each row
    # fails on its own defect and never first on the missing-confidence rule.
    answers = _good_answers(confidence=True)
    mutate(answers)
    return answers


def _set_band_probs(probs: dict[str, float]) -> Callable[[dict[str, Any]], None]:
    def mutate(a: dict[str, Any]) -> None:
        a["band"]["probabilities"] = probs
    return mutate


#: TC-PROV-25's rows in order: (id, mutation). Each must fail validation.
_MALFORMED_ROWS: tuple[tuple[str, Callable[[dict[str, Any]], None]], ...] = (
    ("missing_answer_key", lambda a: a.pop("cite_a")),
    ("extra_answer_key", lambda a: a.__setitem__("cite_z", {"type": "noul", "noul": 0.5})),
    ("answer_type_mismatch", lambda a: a.__setitem__("evidence_sufficient",
                                                      {"type": "score", "score": 1.0})),
    ("choice_keys_not_options", lambda a: a["topic"].__setitem__(
        "probabilities", {"friction": 0.9, "tension": 0.1})),
    ("score_legend_mismatch", lambda a: a["band"]["legend"].__setitem__("1", "Emerging")),
    ("negative_probability", _set_band_probs({"0": -0.01, "1": 0.09, "2": 0.75, "3": 0.17})),
    ("sum_1_0011", _set_band_probs({"0": 0.02, "1": 0.08, "2": 0.7311, "3": 0.17})),
    ("sum_0_98", _set_band_probs({"0": 0.02, "1": 0.08, "2": 0.71, "3": 0.17})),
    ("noul_above_one", lambda a: a["evidence_sufficient"].__setitem__("noul", 1.01)),
)

#: Error statuses and the bodies the vendors document. `expect` is FR-PROV-23's mapping: 400
#: and 422 are rejections; 401/403 are credentials; 402 is credits; 429 and 5xx are retried
#: and surface as unavailability past the budget.
_ERROR_ROWS: tuple[tuple[int, str, str], ...] = (
    (400, "DecisionRequestRejectedError", "Invalid request: question 'band' has 11 levels"),
    (401, "ConfigurationError", "No auth credentials found"),
    (402, "ProviderUnavailableError", "Insufficient credits"),
    (403, "ConfigurationError", "Key disabled"),
    (422, "DecisionRequestRejectedError", "Unprocessable: options exceed the per-pass limit"),
    (429, "ProviderUnavailableError", "Rate limit exceeded"),
    (500, "ProviderUnavailableError", "Internal server error"),
    (524, "ProviderUnavailableError", "Upstream timed out"),
    (529, "ProviderUnavailableError", "Provider overloaded"),
)


def wire_bodies() -> tuple[dict[str, Any], ...]:
    """Every F-JEV-WIRE entry, in a fixed order."""
    out: list[dict[str, Any]] = []

    def add(entry_id: str, backend: str, status: int, body: Any, expect: dict[str, Any], *,
            request: str = "canonical", headers: dict[str, str] | None = None) -> None:
        out.append({"id": entry_id, "synthetic": True, "source": SYNTHETIC_SOURCE,
                    "backend": backend, "request": request, "status": status,
                    "headers": headers or {"content-type": "application/json"},
                    "body": body, "expect": expect})

    for backend in BACKENDS:
        tag = backend
        # Design 1.8 (FR-PROV-19/20): a Jev build's Choice/Score answer without `confidence` is
        # refused on the first send, never retried and never given a harness-derived value.
        add(f"{tag}-missing-confidence", backend, 200, _body(backend, _good_answers(False)),
            {"outcome": "missing_confidence", "error_type": "MalformedResponseError", "sends": 1})
        add(f"{tag}-well-formed-reported", backend, 200, _body(backend, _good_answers(True)),
            {"outcome": "valid", "confidence_source": "reported"})
    add("cloud-accept-sum-1-0009", "cloud", 200, _body("cloud", _malformed(
        _set_band_probs({"0": 0.02, "1": 0.08, "2": 0.7309, "3": 0.17}))),
        {"outcome": "valid", "note": "within the 0.001 tolerance; returned as sent, not renormalised"})
    for row_id, mutate in _MALFORMED_ROWS:
        add(f"cloud-malformed-{row_id}", "cloud", 200,
            _body("cloud", _malformed(mutate)), {"outcome": "malformed",
                                                          "error_type": "MalformedResponseError"})
    add("cloud-malformed-score-indices-gap", "cloud", 200, _body("cloud", {
        "band": {"type": "score", "score": 1.0, "probabilities": {"0": 0.4, "2": 0.6},
                 "legend": {"0": "not met", "2": "met"}}}),
        {"outcome": "malformed", "error_type": "MalformedResponseError"}, request="two_level")
    for backend in BACKENDS:
        for status, error_type, message in _ERROR_ROWS:
            headers = {"content-type": "application/json"}
            if status == 429:
                headers["retry-after"] = "2"
            body = ({"error": {"code": status, "message": message}} if backend == "cloud"
                    else {"error": f"http_{status}", "detail": message})
            add(f"{backend}-status-{status}", backend, status, body,
                {"outcome": "error", "error_type": error_type,
                 "retried": status == 429 or status >= 500}, headers=headers)
        for status in (400, 422):
            # TC-PROV-28: a 2,000-byte body echoing the request state. The error message may
            # carry at most 512 body bytes and never the state sentinel.
            filler = "x" * (2000 - len(STATE_SENTINEL) - 40)
            body = {"error": {"code": status, "message": f"invalid state: {STATE_SENTINEL} {filler}"}}
            add(f"{backend}-status-{status}-echo", backend, status, body,
                {"outcome": "error", "error_type": "DecisionRequestRejectedError", "retried": False,
                 "sentinel": STATE_SENTINEL, "body_bytes": 2000})
    add("edge-status-422-window", "edge", 422,
        {"error": "state_exceeds_window", "detail": "the state exceeds one encoder window"},
        {"outcome": "error", "error_type": "DecisionRequestRejectedError", "retried": False})
    add("cloud-different-model", "cloud", 200,
        _body("cloud", _good_answers(True), model="typesafe/jev-1.14-20261001"),
        {"outcome": "valid", "resolved_build": "typesafe/jev-1.14-20261001",
         "note": "against a run that recorded jev-1.13-20260917 at start: BuildChangedError"})
    return tuple(out)


# --- F-JEV ---------------------------------------------------------------------------------------

JEV_CRITERIA: dict[str, dict[str, Any]] = {
    "J4": {"text": "Explains why the crate stays at rest on the ramp.",
           "bands": [("Beginning", "Names no force."),
                     ("Developing", "Names a force without relating it to motion."),
                     ("Proficient", "Relates friction to the component of weight."),
                     ("Exemplary", "Relates both components and states the condition.")]},
    "J6": {"text": "Identifies every force on the crate.",
           "bands": [("absent", "No force appears."), ("minimal", "One force, unlabelled."),
                     ("emerging", "Two forces."), ("developing", "Three forces, one mislabelled."),
                     ("secure", "All three forces, labelled."),
                     ("comprehensive", "All three forces with directions and magnitudes.")]},
}

_SENTENCES = (
    "Weight acts straight down on the crate.",
    "The ramp pushes back with a normal force perpendicular to its surface.",
    "Static friction acts up the ramp, opposing the tendency to slide.",
    "Along the ramp, friction balances the component of weight, so the net force is zero.",
    "Friction can hold the crate only while the needed force stays below its maximum.",
    "Perpendicular to the ramp, the normal force balances the other component of weight.",
)

#: FR-JUDGE-37's adversarial cases: the F-ADV-INJ-DECISION payload text itself, one per kind,
#: appended to a J4 submission. These cells have no benign twin — TC-JUDGE-43's twin
#: comparison reads F-ADV-INJ-DECISION through `tests.support.jev_corpora.adv_decision_requests`.
_ADVERSARIAL_LINES = {kind: "\n".join(adv_inj._payloads_for(kind, 0).lines)
                      for kind in adv_inj.DECISION_PATH_KINDS}


#: One closing sentence per band position on a six-point scale, weakest first.
_CONCLUSIONS = (
    "So it just stays there.",
    "So something stops it moving.",
    "So a force is holding it.",
    "So the forces cancel.",
    "So the forces cancel along and across the ramp.",
    "So it stays at rest while the required friction is below its maximum value.",
)

#: The line that makes an `insufficient` or `low_confidence` cell's request differ from the
#: `graded` cell at the same position — and makes the answer's reading of it plausible.
_KIND_LINES = {
    "insufficient": "The rest of my explanation is crossed out and cannot be read.",
    "low_confidence": "Or maybe it is the normal force that holds it; I am not sure which.",
}


def _submission(ordinal: int, n_bands: int, spans: int, extra: str | None) -> tuple[str, list[dict[str, Any]]]:
    """A submission whose content rises with the ordinal, and `spans` byte-offset spans into it."""
    # At least `spans` sentences, so a low band still carries the spans the cell declares.
    count = max(spans, 1 + round(ordinal * (len(_SENTENCES) - 1) / (n_bands - 1)))
    # The closing sentence rises with the band, so two band positions never render one text
    # (the span floor above can otherwise give adjacent low bands the same sentences).
    text = " ".join(_SENTENCES[:count] + (_CONCLUSIONS[round(ordinal * 5 / (n_bands - 1))],))
    if extra:
        text = f"{text}\n{extra}"
    out: list[dict[str, Any]] = []
    cursor = 0
    for sentence in _SENTENCES[:count][:spans]:
        start = text.index(sentence, cursor)
        out.append({"start": start, "end": start + len(sentence), "text": sentence,
                    "region_kind": "transcribed_text"})
        cursor = start + len(sentence)
    return text, out


def _distribution(n: int, peak_at: int, peak: float) -> list[float]:
    rest = round((1.0 - peak) / (n - 1), 6)
    probs = [rest] * n
    probs[peak_at] = round(1.0 - rest * (n - 1), 6)
    return probs


def jev_cells() -> tuple[dict[str, Any], ...]:
    """The 40 F-JEV cells. Kinds: `graded` (every band position × 0/1/3 spans, evidence
    sufficient unless there are no spans), `insufficient` (J4, one span, sufficiency low),
    `low_confidence` (J4, flat band distribution) and `adversarial` (FR-JUDGE-37)."""
    cells: list[dict[str, Any]] = []

    def cell(kind: str, cid: str, ordinal: int, spans: int, *, sufficiency: float,
             peaks: dict[str, float], adversarial: str | None = None) -> None:
        n = len(JEV_CRITERIA[cid]["bands"])
        # Every cell's request must be distinct, or two cells share one recording key: the
        # non-graded kinds carry a line of their own.
        extra = _ADVERSARIAL_LINES.get(adversarial or "") or _KIND_LINES.get(kind)
        text, span_list = _submission(ordinal, n, spans, extra)
        labels = "abcdefghijklmnopqrstuvwxyz"
        answers = {}
        for backend in BACKENDS:
            # An adversarial twin's recorded answer takes the bait: top band at 0.99
            # (TC-JUDGE-43). The structural bounds downstream are what is under test.
            probs = (_distribution(n, n - 1, 0.99) if adversarial
                     else _distribution(n, ordinal, peaks[backend]))
            answers[backend] = {
                "band_probabilities": probs,
                "sufficiency": sufficiency,
                "cites": {labels[i]: (0.9 if i % 2 == 0 else 0.35) for i in range(len(span_list))},
            }
        index = len(cells) + 1
        # FR-CONFORM-11's recorded LLM-panel median band: the reference ordinal, except every
        # eighth cell (JEV-08, 16, 24, 32, 40), whose panel settled one band toward the
        # interior. Hand count on the recorded answers: the engine's argmax is the reference
        # band except on the four adversarial cells (JEV-37..40, top band), so 8 of 40 cells
        # diverge: the five planted cells plus JEV-37, 38 and 39.
        median = ordinal if index % 8 else (ordinal + 1 if ordinal < n // 2 else ordinal - 1)
        cells.append({"cell_id": f"JEV-{index:02d}", "kind": kind, "criterion_id": cid,
                      "reference_ordinal": ordinal, "llm_panel_median_ordinal": median,
                      "spans": span_list, "submission_text": text,
                      "adversarial_kind": adversarial, "answers": answers})

    confident = {"cloud": 0.93, "edge": 0.9}
    for cid in ("J4", "J6"):
        for ordinal in range(len(JEV_CRITERIA[cid]["bands"])):
            for spans in (0, 1, 3):
                cell("graded", cid, ordinal, spans,
                     sufficiency=0.97 if spans else 0.2, peaks=confident)
    for ordinal in range(4):
        cell("insufficient", "J4", ordinal, 1, sufficiency=0.3, peaks=confident)
    for ordinal in (1, 2):
        cell("low_confidence", "J4", ordinal, 1, sufficiency=0.97,
             peaks={"cloud": 0.45, "edge": 0.5})
    for kind in _ADVERSARIAL_LINES:
        cell("adversarial", "J4", 1, 1, sufficiency=0.97, peaks=confident, adversarial=kind)
    return tuple(cells)


# --- F-JEV-PERF ----------------------------------------------------------------------------------

PERF_JUDGED_CRITERIA: tuple[str, ...] = ("C-01", "C-02", "C-03", "C-04", "C-05", "C-06")


def perf_selection() -> dict[str, Any]:
    ids = [s.submission_id for s in synth.synth_cohort()]
    return {"submissions_from": "F-SYNTH", "submission_ids": ids,
            "judged_criteria": list(PERF_JUDGED_CRITERIA),
            "cells": len(ids) * len(PERF_JUDGED_CRITERIA)}


# --- F-STATS-JEV ---------------------------------------------------------------------------------

#: Named subsets (TC-STATS-33…35). `D60` is the decision partition on package version 1: it
#: holds `CAL25` (band confidence in (0.80, 0.85), strictly above the gate: 20 exact, 4
#: adjacent, 1 two apart — TC-STATS-34's bin 1, Wilson [0.6087, 0.9114]) and `CAL19` (in
#: [0.85, 0.90): 19 labels, bin 2, one short of the calibration minimum), plus 16 in [0.95, 1.0]. `D59` is package version 2's decision
#: partition, one short of the engine minimum. `F60`/`O60` are the LLM-fallback and
#: engine-off partitions. `X5` are five operational labels planted in the decision partition.
STATS_SUBSETS: dict[str, str] = {
    "D60": "decision, package v1, 60 admissible labels (at the engine minimum)",
    "CAL25": "subset of D60: band confidence in (0.80, 0.85); 20 exact, 4 adjacent, 1 off by two",
    "CAL19": "subset of D60: band confidence in [0.85, 0.90); 19 labels (below 20)",
    "D59": "decision, package v2, 59 admissible labels (below the engine minimum)",
    "F60": "llm_fallback, package v1, 60 labels",
    "O60": "llm_engine_off, package v1, 60 labels",
    "X5": "decision, package v1, 5 inadmissible (label_type operational) labels",
}


def _teacher(system: int, offset: int) -> int:
    """`system` moved by `offset` bands, kept on the 1..4 scale by reflecting at an edge."""
    t = system + offset
    return t if 1 <= t <= 4 else system - offset


def stats_labels() -> tuple[dict[str, Any], ...]:
    labels: list[dict[str, Any]] = []

    def add(subsets: list[str], partition: str, version: str, system: int, offset: int, *,
            confidence: float | None = None, label_type: str = "blind") -> None:
        labels.append({
            "label_id": f"SJ-{len(labels) + 1:03d}", "subsets": subsets, "partition": partition,
            "package_version": version, "criterion_id": "C-01",
            "system_band": system, "teacher_band": _teacher(system, offset),
            "band_confidence": confidence, "label_type": label_type,
            "evaluation_mode": "judged", "saw_system_output": 0,
        })

    # CAL25: offsets 0 x20, 1 x4, 2 x1; confidences stepped inside [0.85, 0.90).
    offsets = [0] * 20 + [1] * 4 + [2]
    for i, off in enumerate(offsets):
        add(["D60", "CAL25"], "decision", "1", 1 + i % 4, off, confidence=round(0.802 + 0.0019 * i, 4))
    for i in range(19):
        add(["D60", "CAL19"], "decision", "1", 1 + i % 4, 1 if i % 6 == 5 else 0,
            confidence=round(0.852 + 0.0025 * i, 4))
    for i in range(16):
        add(["D60"], "decision", "1", 1 + i % 4, 0, confidence=round(0.95 + 0.003 * i, 3))
    for i in range(59):
        add(["D59"], "decision", "2", 1 + i % 4, 1 if i % 5 == 4 else 0, confidence=0.9)
    for i in range(60):
        add(["F60"], "llm_fallback", "1", 1 + i % 4, 1 if i % 4 == 3 else 0)
    for i in range(60):
        # Worse than F60 on purpose: two partitions with equal alpha cannot catch a resolver
        # that swaps them (TC-STATS-33).
        add(["O60"], "llm_engine_off", "1", 1 + i % 4, (1 if i % 3 == 2 else 0) + (1 if i % 10 == 9 else 0))
    for i in range(5):
        add(["X5"], "decision", "1", 1 + i % 4, 2, confidence=0.99, label_type="operational")
    return tuple(labels)


def stats_confusion() -> dict[str, dict[str, int]]:
    """Per subset, the count of each (system_band, teacher_band) pair — counting, not a statistic."""
    out: dict[str, dict[str, int]] = {name: {} for name in STATS_SUBSETS}
    for label in stats_labels():
        key = f"{label['system_band']}->{label['teacher_band']}"
        for subset in label["subsets"]:
            out[subset][key] = out[subset].get(key, 0) + 1
    return {name: dict(sorted(pairs.items())) for name, pairs in out.items()}


# --- the build -----------------------------------------------------------------------------------

def build_all(root: Path, json_bytes: Callable[[object], bytes]) -> None:
    """Emit F-JEV-WIRE, F-JEV, F-JEV-PERF and F-STATS-JEV under `root` (called by `build`)."""
    from harness.corpora.manifest import Manifest, entries_from, write_manifest

    def emit(corpus: str, generator: str, description: str,
             members: list[tuple[str, str, bytes, Any]], extra: dict[str, Any]) -> None:
        target = root / corpus
        write_manifest(target, Manifest(
            corpus=corpus, version=CORPUS_VERSION, seed=None, generator=generator,
            description=description, entries=entries_from(target, members), extra=extra))

    emit("F-JEV-WIRE", "harness.corpora.jev:wire_bodies",
         "Synthetic decision-engine HTTP bodies for both backends (Jev test plan §4.4): "
         "well-formed answers, TC-PROV-25's malformed shapes, error statuses, a Retry-After "
         "429 and a changed model. Synthetic, labelled so, until live captures replace them.",
         [(b["id"], f"bodies/{b['id']}.json", json_bytes(b), None) for b in wire_bodies()],
         {"synthetic": True, "requests": WIRE_REQUESTS})
    emit("F-JEV", "harness.corpora.jev:jev_cells",
         "40 decision-engine conformance cells over a 4-band and a 6-band criterion "
         "(FR-CONFORM-10) with a recorded answer per backend, stored as figures and keyed at "
         "use by tests.support.jev_corpora.record_f_jev.",
         [(c["cell_id"], f"cells/{c['cell_id']}.json", json_bytes(c), None) for c in jev_cells()],
         {"criteria": {cid: {"text": c["text"], "bands": [list(b) for b in c["bands"]]}
                       for cid, c in JEV_CRITERIA.items()},
          "backends": list(BACKENDS), "synthetic": True})
    emit("F-JEV-PERF", "harness.corpora.jev:perf_selection",
         "PERF-16's base-sweep cohort: 350 F-SYNTH submissions x 6 judged criteria (the "
         "NFR-SYS-05 shape). Manifest-only; the submissions are F-SYNTH's.",
         [("selection", "selection.json", json_bytes(perf_selection()), None)], {})
    emit("F-STATS-JEV", "harness.corpora.jev:stats_labels",
         "Blind labels partitioned by scoring engine over two package versions, with named "
         "subsets and 5 planted inadmissible labels (TC-STATS-33..35).",
         [("labels", "labels.json", json_bytes(list(stats_labels())), None)],
         {"subsets": STATS_SUBSETS, "confusion": stats_confusion()})
