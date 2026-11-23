"""Validity T12 (issue #909): TC-UI-35 (FR-UI-37) — the package review screen names each
judged rubric line's scoring model in teacher words. Browser tier (E6), 1280x720.

**World.** The shipped ENG7 spec (`docs/live-tests/config/eng7-read-01.package.toml`) written
as an authoring draft (`<data>/authoring/<package>.package.draft.toml`, the file the draft
job writes and the draft read answers from), with one change: C3 *declares*
`scoring = "holistic"`. So C1a (a two-band checklist aspect) takes FR-PKG-29's default
`atomic`, C2 (four bands) the default `holistic`, and C3 is declared. The C1 composite
(`evidence_sum`) is marked through its aspects and carries no label.

Each line is asserted inside its own outline entry, so one line rendering the text cannot
satisfy another's arm.

**Written ahead: no** (S14 #884 merged).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.support import spa
from tests.support.clarity_browser import ensure_draft_ledger
from tests.support.validity_browser import VIEWPORT, assert_clean

pytestmark = [pytest.mark.browser, pytest.mark.integration]

REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"
PACKAGE = "eng7-draft"


def _write_draft(data_dir: Path) -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert 'package = "ENG7-READ-01"' in text and 'score_method = "general"\n' in text
    assert "scoring =" not in text, "fixture: the ENG7 spec now declares a model itself"
    text = text.replace('package = "ENG7-READ-01"', f'package = "{PACKAGE}"')
    text = text.replace('score_method = "general"\n',
                        'score_method = "general"\nscoring = "holistic"\n')
    folder = data_dir / "authoring"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{PACKAGE}.package.draft.toml").write_text(text, encoding="utf-8")


def _entry(page: Any, heading: str) -> Any:
    return page.locator(".outline-entry").filter(
        has=page.get_by_role("heading", level=3, name=heading, exact=True))


def test_tc_ui_35_the_scoring_model_in_teacher_words(tmp_path, monkeypatch):
    """TC-UI-35: C1a "Marked as a simple check (chosen automatically)", C2 "Marked as an
    overall judgement (chosen automatically)", the declared C3 without "(chosen
    automatically)", the composite C1 without a label."""
    from aeh.console import serve_console
    from aeh.store import open_store

    data = tmp_path / "data"
    store = open_store(data)
    try:
        _write_draft(data)
        ensure_draft_ledger(store, PACKAGE)
        for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
            monkeypatch.delenv(name, raising=False)
        server = serve_console(store=store)
        origin = f"http://127.0.0.1:{server.socket.getsockname()[1]}"
        try:
            with spa.spa_page(origin, viewport=VIEWPORT) as (page, log):
                page.goto(f"{origin}/#/package/review?package={PACKAGE}")
                assert spa.wait_for_screen(page) == "Review the draft"
                page.locator(".scoring-model").first.wait_for()
                # C1 is "Grading point 1", C2 "Grading point 2", C3 "Grading point 3"; the
                # aspects keep their ids as headings.
                expected = {
                    "C1a": "Marked as a simple check (chosen automatically)",
                    "C1b": "Marked as a simple check (chosen automatically)",
                    "Grading point 2": "Marked as an overall judgement (chosen automatically)",
                    "Grading point 3": "Marked as an overall judgement",
                }
                for heading, label in expected.items():
                    entry = _entry(page, heading)
                    assert entry.count() == 1, f"no single outline entry headed {heading!r}"
                    texts = entry.locator(".scoring-model").all_inner_texts()
                    assert texts == [label], f"{heading}: {texts!r} != [{label!r}]"
                composite = _entry(page, "Grading point 1")
                assert composite.count() == 1
                assert composite.locator(".scoring-model").count() == 0, (
                    "the evidence_sum composite carries a scoring label")
                assert page.locator(".scoring-model").count() == len(expected)
                assert "(chosen automatically)" not in \
                    _entry(page, "Grading point 3").inner_text()
                assert_clean(page, log)
        finally:
            server.terminate()
    finally:
        store.close()
