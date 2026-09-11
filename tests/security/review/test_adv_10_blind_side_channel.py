"""`ADV-10` — the attack on blind-sample integrity (`M-REVIEW`, TS-41, security).

**Attacker goal:** learn the system's answer before submitting a blind label (the
plan's named goal, fed verbatim). The inputs are the four the row lists — **direct URL
probing**, **link-graph traversal**, **response-timing correlation** and
**item-ordering correlation** — all exercised *from inside the blind flow*: the flow's
own pages, the URLs derivable from the flow's own URLs, and the flow's own observable
work. Typing another screen's address from scratch is leaving the flow, not attacking
it — the flow's guarantee is that nothing *on* the flow leads to the output.

**Pass = system output unreachable; no correlation between blind item order and stored
confidence.** Three instruments, one per attack surface:

- `TC-REVIEW-11` step 4 — the reachability half: the one step of the block form the
  contract file does not carry (§6.11.15's *"Attempt to reach system output by direct
  URL manipulation from within the flow and assert it is not reachable — unreachable,
  not merely absent from the default view"*). A battery of manipulated flow URLs, every
  response scanned twice — bytes for the stored sentinels, query trace for the
  forbidden tables — plus a link-graph walk of whatever the flow's pages link to.
  Unreachable is the pair, not either half alone: a page that fetched the answer and
  hid it fails the trace scan, which is exactly the failure a byte check alone passes.
  The plan's oracle is *"exact 404 or refusal"*; the shipped console's declared
  resolution for an unknown route is the packages home (`_resolve`'s fallthrough) — a
  refusal by irrelevance rather than a 404, and the case asserts the guarantee the
  oracle exists for: no output-carrying row is queried and no output byte is served, so
  the probe never reaches the output either way. The 404-vs-fallthrough disposition is
  a finding on the PR, not a silent substitution (`#124` owns the route surface).
- `TC-REVIEW-24` — the ordering half (§6.11's own wording): *item order in the blind
  flow carries no information about system confidence*, asserted by correlating blind
  item order against stored confidence over `RANDOMNESS_TRIALS` seeded draws and
  requiring no association. The discriminating fixture is a population whose confidence
  rises with pool position — the shape where an order-preserving draw ("first N") leaks
  the answer perfectly — and the control draw fires the detector, so the all-clear is
  over an instrument proven to fire.
- `ADV-10`'s response-timing half — the flow's observable work (the rendered response
  bytes, whose size and shape a timing side channel reads) is identical under a maximal
  confidence difference at a fixed seed. The query-plan half of the same guarantee is
  `CT-CONSOLE-14`'s sweep; this is the byte half.

Isolation: rung 3 for the reachability half — a real store, real output-carrying rows,
the real console read path, so the scans' silence means "not rendered" over output that
is demonstrably in the ledger (asserted before the sweep, against the store itself).
Rungs 0-2 for the statistical halves — the leak would live in `blind_sample`'s draw
order and the flow's render, both the service's own, and the fixtures are the shared
`broken_review_fixtures` sentinels (reconcile, don't rename). The socket guard is
autouse. Two scope disclosures: (1) the flow's pages carry no hyperlinks today (a
stylesheet link aside, which the traversal sweeps too), so the link-graph half walks
the URL closure the flow's own URLs derive — and stands ready over any link the
console ever grows: a flow page that gains a link to an output-carrying screen fails
the same scans without a URL being typed. (2) The console reads the cohort ledger
through its own handles and the flow's pages read the durable tier, so the seeded
output sits one read-path away from every probed page — the assertion is that no probed
render queries a table that carries it and none renders it, which is the clause's
guarantee at the surface the probe attacks.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from aeh.store import open_store
from tests.support import broken_review_fixtures as broken
from tests.support import review_vocabulary as vocab
from tests.support.impl import CONSOLE_MODULE, REVIEW_MODULE, require
from tests.support.orch_run import seed_cohort, seed_document

pytestmark = [pytest.mark.integration]

_COHORT = "c-blind-adv"
_SUBMISSION = "S-ADV-0001"
_CRITERION = "C-ADV"
_RUN = "run-blind-adv"

#: The verbatim student work the submission carries, as the blob store's own copy of
#: it — the data the views under attack are *about*, so the sweeps below run against a
#: world where the work exists.
_STUDENT_WORK = (
    "verbatim student work sentinel 4471: the candidate's own answer, written by "
    "nobody else, in their own words."
)

#: The one criterion_score insert this file needs — the fourteen columns the shipped
#: table carries after the aggregation migration, in the shape the `M-AGG` contract
#: cases seed. The system output lands in recognisable values — the band, confidence,
#: points and routing reason are `broken.SYSTEM_OUTPUT_SENTINELS`'s own — so a probe
#: that leaks the answer is caught by value, not by name.
_INSERT_SCORE = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing, confidence, confidence_base, "
    "spans_verified, evidence_present, sufficiency_flag, ocr_overlap_risk) "
    "VALUES (:sid, :cid, :band, :points, :judge_count, :agreement, :state, "
    ":routing, :confidence, :confidence_base, :spans_verified, "
    ":evidence_present, :sufficiency_flag, :ocr_overlap_risk)"
)
_INSERT_NARRATIVE = (
    "INSERT INTO narrative (narrative_id, submission_id, criterion_id, run_id, "
    "level, question_id, text, citations, score_claim_flag) "
    "VALUES (:nid, :sid, :cid, :rid, 'l1_question', :qid, :text, '[]', 0)"
)
_INSERT_QUEUE = (
    "INSERT INTO review_queue (queue_id, submission_id, criterion_id, reason) "
    "VALUES (:qid, :sid, :cid, :reason)"
)


def _seed_output_bearing_store(tmp_data_dir):
    """A real store whose cohort ledger carries every value `FR-REVIEW-11` forbids the
    flow to show — for the one submission a probe would try to read. The non-vacuity
    anchors read them back, so the scans' silence below is over output that is
    demonstrably there."""
    store = open_store(tmp_data_dir)
    seed_cohort(store, (_SUBMISSION,), cohort_id=_COHORT)
    content_hash = seed_document(store, _SUBMISSION, text=_STUDENT_WORK, cohort_id=_COHORT)
    cohort = store.cohort(_COHORT)
    sentinels = broken.SYSTEM_OUTPUT_SENTINELS
    with cohort.transaction() as tx:
        tx.execute(
            _INSERT_SCORE,
            sid=_SUBMISSION, cid=_CRITERION,
            band=sentinels["system_band"],
            points=sentinels["points"],
            judge_count=3, agreement=0.95, state="provisional_unreviewed",
            routing="queued", confidence=sentinels["confidence"],
            confidence_base=0.95, spans_verified=1, evidence_present=1,
            sufficiency_flag=1, ocr_overlap_risk=0,
        )
        tx.execute(
            _INSERT_NARRATIVE,
            nid="nar-adv-1", sid=_SUBMISSION, cid=_CRITERION, rid=_RUN, qid="Q1",
            text=sentinels["narrative"],
        )
        tx.execute(
            _INSERT_QUEUE,
            qid="q-adv-1", sid=_SUBMISSION, cid=_CRITERION,
            reason=sentinels["routing_reason"],
        )
    return store, content_hash


def _output_is_in_the_ledger(store) -> None:
    """The non-vacuity anchors, asserted against the store before the scans: the
    system's answer is in the ledger, so silence from the pages below is evidence."""
    cohort = store.cohort(_COHORT)
    sentinels = broken.SYSTEM_OUTPUT_SENTINELS
    rows = cohort.query(
        "SELECT band, points, confidence FROM criterion_score WHERE submission_id = :s",
        s=_SUBMISSION,
    )
    assert rows, "the seeded score row is missing, so the scans below would pass over air"
    assert str(rows[0]["band"]) == str(sentinels["system_band"]), (
        "the seeded band is not the sentinel, so the byte scan would not be sweeping "
        "the system's answer"
    )
    assert float(rows[0]["confidence"]) == float(sentinels["confidence"]), (
        "the seeded confidence is not the sentinel, so the byte scan would not be "
        "sweeping the system's answer"
    )
    narratives = cohort.query(
        "SELECT text FROM narrative WHERE submission_id = :s", s=_SUBMISSION
    )
    assert any(
        sentinels["narrative"] in str(row["text"]) for row in narratives
    ), "the seeded narrative is missing, so the byte scan below would pass over nothing"


# --- the reachability half: probing and traversal ---------------------------------------------


#: `CT-CONSOLE-14`'s declared forbidden set, restated verbatim (the contract file owns
#: the declaration; reconcile, don't rename) — the tables and columns whose presence in
#: a flow response's query trace is a reach, rendered or not.
_FORBIDDEN_QUERY_TOKENS = (
    "verdict",
    "self_confidence",
    "aggregated_band",
    "predicted_band",
    "submission_grade",
    "review_queue",
    "narrative",
    "criterion_score",
)

#: Query-string switches a "reveal" mode would ride, and path extensions naming the
#: forbidden fields — manipulations of the flow's own URL shape. The screens that
#: legitimately carry system output (`/runs/{id}/review`, `/students/{ref}`) are not in
#: the battery: typing their addresses is leaving the flow, not attacking it.
_PROBE_QUERIES = (
    "reveal=1",
    "debug=1",
    "include=score",
    "fields=band,points,confidence",
    "format=json",
    "full=1",
)
_PROBE_SUFFIXES = (
    "system",
    "answer",
    "score",
    "band",
    "narrative",
    "confidence",
    "verdict",
)

_LINK_PATTERN = re.compile(r'(?:href|action)="([^"]+)"')


def _probe_battery() -> list[str]:
    """The flow's own URLs and the manipulations a determined teacher types at them:
    query-string variants of the flow's unit page, field-naming path suffixes, and
    sibling routes a link-graph guess would try."""
    base = f"/runs/{_RUN}/blind"
    unit = f"{base}/units/1"
    return [
        base,
        unit,
        *[f"{unit}?{query}" for query in _PROBE_QUERIES],
        *[f"{unit}/{suffix}" for suffix in _PROBE_SUFFIXES],
        f"{base}/answers",
        f"{base}/system",
        f"/runs/{_RUN}/scores",
        f"/scores/{_SUBMISSION}",
        f"/submissions/{_SUBMISSION}/score",
    ]


def _scan(url: str, html: str, queries) -> list[str]:
    """The two-sided oracle for one response: the stored sentinels must appear on no
    probed page's bytes, and no probed render may even query a table that carries them.
    A page that fetched the answer and hid it fails the second half — the failure a
    byte check alone passes."""
    found = [
        f"{url} renders {field} = {sentinel!r}"
        for field, sentinel in broken.SYSTEM_OUTPUT_SENTINELS.items()
        if str(sentinel) in html
    ]
    reached = sorted(
        {
            token
            for token in _FORBIDDEN_QUERY_TOKENS
            for query in queries
            if token in str(query).lower()
        }
    )
    if reached:
        found.append(f"{url} queried {reached}")
    return found


def test_adv_10_output_is_unreachable_by_direct_url_probing_and_link_traversal(
    tmp_data_dir,
):
    """`TC-REVIEW-11` step 4 / `ADV-10`'s reachability half — the blind flow's URL
    surface, attacked. Every probed response is asserted twice (bytes and query trace);
    the link-graph half walks whatever the flow's pages link to, two hops deep, and
    applies both scans to every page in the closure — a flow that linked to a page
    carrying the drawn items' output would fail here without any URL being typed."""
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    store, content_hash = _seed_output_bearing_store(tmp_data_dir)
    try:
        _output_is_in_the_ledger(store)
        assert store.blobs().get(content_hash).decode("utf-8") == _STUDENT_WORK, (
            "the seeded student work is missing, so the pages below were swept with "
            "nothing in the data to leak"
        )

        # Positive control: the two-sided oracle catches the leak it exists to catch —
        # a page that renders the band's value, and one that queried the score table
        # without rendering it.
        controlled = _scan(
            "/controlled-leak",
            f"<p>the band is {broken.SYSTEM_OUTPUT_SENTINELS['system_band']}</p>",
            ["SELECT * FROM criterion_score"],
        )
        assert len(controlled) == 2, (
            f"fixture bug: the two-sided scan detected {controlled} — it must flag "
            "both the rendered sentinel and the forbidden-table query, or the "
            "all-clear below proves nothing"
        )

        app = build_console(store=store)
        violations: list[str] = []
        battery = _probe_battery()
        seen: set[str] = set()
        frontier = list(battery)
        for _hop in range(2):
            following: list[str] = []
            for url in frontier:
                if url in seen:
                    continue
                seen.add(url)
                page = app.render(url)
                violations.extend(_scan(url, page.html, page.queries))
                following.extend(_LINK_PATTERN.findall(page.html))
            frontier = following

        assert all(url in seen for url in battery), (
            "the probe battery was not fully swept — the all-clear would cover fewer "
            "URLs than the attacker typed"
        )
        flow_html = app.render(f"/runs/{_RUN}/blind").html
        assert "Blind-sample" in flow_html, (
            "the flow's own screen rendered nothing recognisable, so the probe battery "
            "would be scanning pages with no blind flow in them"
        )
        assert violations == [], (
            f"the blind flow's URL surface leaked system output: {violations}. ADV-10's "
            "attacker is a teacher who wants the answer before giving one; a probe that "
            "renders it — or a render that merely fetched it — is RISK-13: the system's "
            "only unbiased validity instrument silently becoming an acceptance-rate "
            "measure."
        )
    finally:
        store.close()


# --- the statistical half: order carries no confidence information -----------------------------


def _ranks(values: list[float]) -> list[float]:
    """Average ranks, ties sharing the mean slot — the rank transform Spearman needs."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman's rho by hand — the rank correlation between two aligned lists."""
    rx, ry = _ranks(xs), _ranks(ys)
    mx = sum(rx) / len(rx)
    my = sum(ry) / len(ry)
    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denominator = (
        sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)
    ) ** 0.5
    return numerator / denominator if denominator else 0.0


def _confidence_ordered_population() -> list:
    """The discriminating fixture: judged rows whose stored confidence rises with the
    pool's order — one row per `(submission, criterion)` ref, so every ref carries its
    own confidence. An order-preserving draw on this pool reads the answer straight out
    of the position, which is exactly why a compliant draw must show no association."""
    rows = broken.flagged_population(120, criteria=1)
    return [
        dataclasses.replace(
            row, self_confidence=round(0.30 + 0.60 * i / (len(rows) - 1), 4)
        )
        for i, row in enumerate(rows)
    ]


def test_tc_review_24_blind_item_order_carries_no_confidence_information():
    """`TC-REVIEW-24` / `ADV-10`'s ordering half — *"Item order in the blind flow
    carries no information about system confidence — asserted by correlating blind item
    order against stored confidence and requiring no association."*

    The association is read as Spearman's rho between a draw's positions and the drawn
    refs' stored confidences, over `RANDOMNESS_TRIALS` seeded draws of the range's top.
    A single draw's |rho| of 0.2 is what chance looks like; the threshold is the mean's:
    the mean over 200 draws of 25 has standard error ≈ 0.015, so 0.08 is five of them —
    deterministic under the service's seeded RNG, with margin.

    The control is the proof the instrument fires: the pool's own first 25 — an
    order-preserving draw — must land at |rho| ≈ 1 on a confidence-ordered pool, or the
    no-association verdict below was rendered by a detector that cannot fire. This is
    the fixture that makes "first N" fail: on a confidence-ordered pool an
    order-preserving draw correlates at 1, which is exactly why the ordering side
    channel survives review on any other population.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    population = _confidence_ordered_population()
    confidences = {
        (row.submission_id, row.criterion_id): row.self_confidence for row in population
    }

    # Control: an order-preserving draw is the pool's first 25. The pool preserves the
    # fixture's row order — the admitted set is a filter over the rows as passed — so
    # its first 25 refs carry the fixture's first 25 confidences, rising with position.
    head = [
        (row.submission_id, row.criterion_id)
        for row in population[: vocab.BLIND_SAMPLE_RANGE[1]]
    ]
    control = _spearman(list(range(len(head))), [confidences[ref] for ref in head])
    assert control > 0.95, (
        f"the control draw correlates at {control:.3f} — the fixture's pool is not "
        "confidence-ordered, so a compliant draw and an order-leaking one would be "
        "indistinguishable and the sweep below would assert nothing"
    )

    drawn_tuples: set[tuple[tuple[str, str], ...]] = set()
    correlations: list[float] = []
    for seed in range(vocab.RANDOMNESS_TRIALS):
        service = build_review(scores=population, seed=seed)
        session = service.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[1])
        refs = tuple((ref.submission_id, ref.criterion_id) for ref in session.items)
        drawn_tuples.add(refs)
        correlations.append(
            _spearman(list(range(len(refs))), [confidences[ref] for ref in refs])
        )

    assert len(drawn_tuples) > 1, (
        "every seed drew the same items, so the correlations below were computed over "
        "one repeated draw and the association test would pass a fixed draw"
    )
    mean = sum(correlations) / len(correlations)
    assert abs(mean) <= 0.08, (
        f"the mean order-vs-confidence correlation over {vocab.RANDOMNESS_TRIALS} "
        f"seeded draws is {mean:+.4f}. TC-REVIEW-24: item order in the blind flow "
        "carries no information about system confidence — a teacher watching which "
        "items come first could infer how confident the system is, and from it the "
        "band it chose (RISK-13's side channel)."
    )


# --- the timing half: the flow's observable work is confidence-blind ---------------------------


def test_adv_10_the_flows_observable_work_is_identical_under_confidence_extremes():
    """`ADV-10`'s response-timing half, as a deterministic byte assertion.

    A timing side channel reads the response's observable work — its size, its shape,
    the work its render did. A flow that shaped its page or prefetched per item by
    stored confidence would be readable from the outside, so the strongest instrument
    this tier can run is identity under a maximal difference: two populations identical
    in every identity field and opposed in confidence (one rising, one falling, item by
    item), the same seed, the same draw — and the rendered flow must be byte-identical.

    The precondition is asserted first and matters: same seed and identical pools must
    draw the same items, or the comparison below would be over different content and
    prove nothing. The query-plan half of the same guarantee is `CT-CONSOLE-14`'s
    sweep; this is the response-body half.
    """
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    base = broken.flagged_population(120, criteria=1)
    rising = [
        dataclasses.replace(
            row, self_confidence=round(0.30 + 0.60 * i / (len(base) - 1), 4)
        )
        for i, row in enumerate(base)
    ]
    falling = [
        dataclasses.replace(
            row, self_confidence=round(0.90 - 0.60 * i / (len(base) - 1), 4)
        )
        for i, row in enumerate(base)
    ]

    first = build_review(scores=rising, seed=7)
    second = build_review(scores=falling, seed=7)
    session_a = first.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[1])
    session_b = second.blind_sample(run_id="run-1", n=vocab.BLIND_SAMPLE_RANGE[1])

    assert [
        ref.submission_id for ref in session_a.items
    ] == [ref.submission_id for ref in session_b.items], (
        "fixture bug: the two services drew different items, so the render comparison "
        "below would be over different content and would prove nothing"
    )

    rendered_a = first.render_blind_flow(session_a.session_id)
    rendered_b = second.render_blind_flow(session_b.session_id)
    assert session_a.items[0].submission_id in rendered_a, (
        "the flow rendered none of its drawn items, so the byte-equality below was "
        "asserted over an empty response"
    )
    assert rendered_a == rendered_b, (
        "the blind flow's rendered response differs with the stored confidence. ADV-10's "
        "response-timing attacker reads exactly this: anything the flow does differently "
        "for a more confident item — a longer payload, an extra section, a prefetch — "
        "correlates the response with the system's answer before the teacher answers "
        "(RISK-13)."
    )