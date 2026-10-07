"""The SQL statements M-HELP runs, and the Q&A log's declared schema (FR-HELP-04).

The Q&A log is the module's only write surface (`CT-HELP-04`): one table in Tier D
(`durable.sqlite`), appended once per exchange, never updated or deleted. Tier D because the
log is accountability surface that must survive a cohort purge (`FR-STORE-12`'s reading of
"permanent"), and safe there **by construction**: no column carries cohort, roster,
submission or grade data — the question is the teacher's own words and the anchors name
manual headings (`CT-HELP-03`; the sweep `TC-HELP-04`/`SEC-25` hold the requests to).

The table's migration (`help_qa_log`, Durable 13) is declared in `aeh.store.migrations`
alongside migration 11, not here — the same ruling that moved the calib table into the store:
the module a tier-chain link names must be imported before every durable open, and the
store-opening worlds that never import a console feature module import only the eleven
contributors. Only this module's *statements* live here.
"""

from __future__ import annotations

from aeh.store import Statement


# --- the declared statements (FR-STORE-08: one literal each, keyword parameters) -----------------

HELP_STATEMENTS: dict[str, Statement] = {
    "insert_qa_exchange": Statement(
        "INSERT INTO qa_exchange (question, cited_anchors, model_ref, tokens_in, "
        "tokens_out, latency_ms, outcome, recorded_at) VALUES (:question, :cited_anchors, "
        ":model_ref, :tokens_in, :tokens_out, :latency_ms, :outcome, :recorded_at)"
    ),
    "read_qa_log": Statement(
        "SELECT exchange_id, question, cited_anchors, model_ref, tokens_in, tokens_out, "
        "latency_ms, outcome, recorded_at FROM qa_exchange ORDER BY exchange_id"
    ),
}
