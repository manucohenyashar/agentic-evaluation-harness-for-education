"""The rung-3 world for Validity T4 (issue #897). A completed F-DEV-PIPE run, served by a real
console on a loopback port. The world also carries the label-identity oracle that TC-REVIEW-100
and TC-REG-24 share.

**Why the console API, not `ReviewService`.** SV-12 lived on the console's path: the console's
effect handed M-REVIEW the cohort as the run and the submission as the student. A case that
called the review service directly would stay green over that defect (test plan §2.1, RSV-06).
So every label in these cases is written by an HTTP request to `serve_console()`. There is one
disclosed exception. The console's own `blind-sample finish` action is S12's (#882). Until it
lands, the green cases close the draw through the console's own review service
(`server.app._review_service(run_id).finish_blind`). That is the same service, actor and
scope the console's blind-sample submission and review action use. The written-ahead
TC-REVIEW-100 drives Finish over HTTP.

**The world.** `pipe_world.replay_world` replays the F-DEV-PIPE recordings through the composed
pipeline: three students (roster refs `P-0001`..`P-0003`), judged criteria C1 and C2 routed
`queued`, deterministic C3 routed `auto`, and scoring units with `base` and `escalation`
origins. Each submission id (`sub-<hash>`) differs from its roster ref, and the run id
(`run-dev-pipe`) differs from the cohort id (`coh-dev-pipe`). Those are the distinctions
SV-12 erased.
"""

from __future__ import annotations

import http.client
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tests.support import pipe_world

#: The label origins FR-REVIEW-25 admits, in precedence order (random_arm > escalation > base).
LABEL_ORIGINS = ("random_arm", "escalation", "base")


@dataclass
class ServedRun:
    """A completed run behind a live console."""

    world: Any
    server: Any
    port: int
    root: Path

    @property
    def run_id(self) -> str:
        return self.world.run_id

    @property
    def cohort_id(self) -> str:
        return self.world.cohort_id

    # -- HTTP -------------------------------------------------------------------------------

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            headers = {"Content-Type": "application/json"} if payload is not None else {}
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        try:
            return response.status, json.loads(raw) if raw else None
        except ValueError:
            return response.status, raw.decode("utf-8", errors="replace")

    def action(self, action: str, **params: Any) -> tuple[int, Any]:
        """One control action over HTTP, `(status, outcome)`. The slug is spelled here by the
        server's lowercase/hyphen rule, so the request reads as the action's own words."""
        slug = action.lower().replace(" ", "-").replace("/", "-")
        return self.request("POST", f"/api/v1/actions/{slug}", params)

    def dispatched(self, action: str, **params: Any) -> dict:
        status, outcome = self.action(action, **params)
        assert status == 200 and isinstance(outcome, dict) and outcome.get("dispatched"), (
            f"{action} {params} was not dispatched: {status} {outcome!r}")
        return outcome

    def get(self, path: str, **query: Any) -> tuple[int, Any]:
        from urllib.parse import urlencode

        return self.request("GET", path + ("?" + urlencode(query) if query else ""))

    # -- the stored rows ---------------------------------------------------------------------

    def rows(self, sql: str, *params: Any, tier: str = "cohort") -> list[dict]:
        path = (self.root / "cohorts" / f"{self.cohort_id}.sqlite" if tier == "cohort"
                else self.root / "durable.sqlite")
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def execute(self, sql: str, *params: Any) -> None:
        with sqlite3.connect(self.root / "cohorts" / f"{self.cohort_id}.sqlite") as connection:
            connection.execute(sql, params)

    def labels(self) -> list[dict]:
        return self.rows("SELECT * FROM label ORDER BY timestamp, label_id", tier="durable")

    def run_row(self) -> dict:
        found = self.rows("SELECT * FROM run WHERE run_id = ?", self.run_id)
        assert found, f"fixture: no run row for {self.run_id}"
        return found[0]

    def roster_refs(self) -> dict[str, str]:
        """submission id -> the student's roster ref."""
        return {row["submission_id"]: row["student_ref"]
                for row in self.rows("SELECT submission_id, student_ref FROM submission")}

    def cells(self, criterion_id: str, routing: str = "queued") -> list[tuple[str, str]]:
        return [(row["submission_id"], row["criterion_id"]) for row in self.rows(
            "SELECT submission_id, criterion_id FROM criterion_score WHERE run_id = ? "
            "AND criterion_id = ? AND routing = ? ORDER BY submission_id",
            self.run_id, criterion_id, routing)]

    def unit_origins(self, submission_id: str, criterion_id: str) -> set[str]:
        return {row["origin"] for row in self.rows(
            "SELECT origin FROM work_unit WHERE run_id = ? AND submission_id = ? "
            "AND criterion_id = ? AND stage = 'score'", self.run_id, submission_id, criterion_id)}

    def finish_through_the_consoles_service(self) -> Any:
        """Close the draw through the console's own review service. This is the disclosed
        stand-in for S12's `blind-sample finish` action (#882): the same service, actor and
        scope the console's blind-sample submission and review action use."""
        return self.server.app._review_service(self.run_id).finish_blind(self.run_id)


@contextmanager
def served_run(root: Path, monkeypatch: Any, network_guard: Any) -> Iterator[ServedRun]:
    """Replay the F-DEV-PIPE run into `root`, then serve a console over its store."""
    from aeh.console import serve_console

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    status = pipe_world.drive_composed(world).status
    assert status == "complete", f"fixture: the F-DEV-PIPE run ended {status!r}"
    network_guard.uninstall()
    server = None
    try:
        server = serve_console(store=world.store)
        _host, port = server.socket.getsockname()[:2]
        yield ServedRun(world=world, server=server, port=port, root=root)
    finally:
        try:
            if server is not None:
                server.terminate()
        finally:
            network_guard.install()
            try:
                world.store.close()
            except Exception as error:  # noqa: BLE001 — teardown after the assertions
                if "can only be used in that same thread" not in str(error):
                    raise


# --- the label-identity oracle (TC-REVIEW-100, TC-REG-24) ----------------------------------------


def expected_origin(unit_origins: set[str]) -> str | None:
    """The origin FR-REVIEW-25 derives from a cell's scoring units, worked independently of
    `aeh.review`: random_arm over escalation over base. None when no unit exists."""
    return next((origin for origin in LABEL_ORIGINS if origin in unit_origins), None)


def assert_label_identity(served: ServedRun, labels: list[dict]) -> None:
    """Every label row carries its real run, student, scope and origin (FR-REVIEW-25,
    CT-REVIEW-26).

    - `run_id` is the run's id and differs from the cohort id.
    - `student_ref` is the roster ref of the cell's student and differs from the submission id.
    - `cohort_id`, `score_id`, `package_version_id`, `backend_profile` and `panel_config` are
      non-null and equal the run's frozen values.
    - `origin` is one of {base, escalation, random_arm} and equals the origin the cell's
      scoring units derive.
    """
    assert labels, "fixture: no label was written, so nothing about identity was asserted"
    run = served.run_row()
    refs = served.roster_refs()
    assert served.run_id != served.cohort_id, "fixture: the run id equals the cohort id"
    problems: list[str] = []
    for label in labels:
        name = f"{label['label_type']} label {label['label_id']}"
        if label["run_id"] != served.run_id:
            problems.append(f"{name}: run_id {label['run_id']!r}, not the run's {served.run_id!r}"
                            + (" (the cohort id: SV-12)" if label["run_id"] == served.cohort_id
                               else ""))
        score_id = label["score_id"]
        if not score_id or ":" not in str(score_id):
            problems.append(f"{name}: score_id {score_id!r} names no cell")
            continue
        submission_id, criterion_id = str(score_id).rsplit(":", 1)
        if criterion_id != label["criterion_id"]:
            problems.append(f"{name}: score_id {score_id!r} is not its criterion's cell")
        if submission_id not in refs:
            problems.append(f"{name}: score_id {score_id!r} names no submission of the cohort")
            continue
        if label["student_ref"] != refs[submission_id]:
            problems.append(
                f"{name}: student_ref {label['student_ref']!r}, not the roster ref "
                f"{refs[submission_id]!r}"
                + (" (the submission id: SV-12)" if label["student_ref"] == submission_id
                   else ""))
        if label["student_ref"] == submission_id:
            problems.append(f"{name}: student_ref equals the submission id {submission_id!r}")
        if label["cohort_id"] != served.cohort_id:
            problems.append(f"{name}: cohort_id {label['cohort_id']!r}")
        for column in ("package_version_id", "backend_profile", "panel_config"):
            if label[column] is None or label[column] != run[column]:
                problems.append(f"{name}: {column} {label[column]!r}, not the run's frozen "
                                f"{run[column]!r}")
        if label["origin"] not in LABEL_ORIGINS:
            problems.append(f"{name}: origin {label['origin']!r} is not one of {LABEL_ORIGINS}")
        derived = expected_origin(served.unit_origins(submission_id, criterion_id))
        if label["origin"] != derived:
            problems.append(f"{name}: origin {label['origin']!r}, but the cell's scoring units "
                            f"derive {derived!r}")
    assert not problems, "labels without their real identity (FR-REVIEW-25):\n  " + \
        "\n  ".join(problems)


def assert_agreement_scope_is_accepted(served: ServedRun, criterion_id: str,
                                       blind_count: int) -> None:
    """`agreement()` over the blind labels gives a figure the console's scope rule accepts:
    an `AgreementFigure`, not an absence, scoped to the run's backend. The console's agreement
    block renders its kappa, not the absence sentence and not the "names no population"
    refusal. A label without its backend (an unscoped label) falls out of the backend-scoped
    population, and the figure becomes an absence."""
    from aeh.console import render_agreement_block
    from aeh.stats import AgreementFigure, open_stats

    backend = served.run_row()["backend_profile"]
    stats = open_stats(served.root, cohort_id=served.cohort_id)
    figure = stats.agreement(criterion_id=criterion_id, backend_profile=backend)
    assert isinstance(figure, AgreementFigure), (
        f"agreement over the console's blind labels on {criterion_id} is an absence "
        f"({getattr(figure, 'reason', figure)!r}): the labels are not readable as evidence "
        "for the run's scope")
    assert figure.n == blind_count, (figure.n, blind_count)
    assert figure.backend_profile == backend
    rendered = render_agreement_block(figure=figure)
    assert "not shown" not in rendered and "kappa" in rendered, (
        f"the console's agreement block refused the figure: {rendered!r}")
