"""Inline regression: a re-draft whose package id differs from the prior draft's only in letter
case keeps its draft on a case-insensitive file system.

`commit_artifacts` renames the new artifacts into place, then removes the prior artifacts that
would survive under a different spelling of the same case-insensitive package id. On Windows
(and macOS by default) `HIST7-ROME-01.package.draft.toml` and `hist7-rome-01.package.draft.toml`
are ONE file: the rename had already replaced it, and the removal then deleted the draft just
written — the re-draft reported success over an empty folder (TC-AUTHOR-27 / TC-AUTHOR-C20 went
red on exactly this). The prior is now skipped when it is the same file as a written target; on
a case-sensitive file system the prior is a different file and is still removed.
"""

from __future__ import annotations

import os

from aeh.author.progress import commit_artifacts


def _case_insensitive(folder) -> bool:
    probe = folder / "CaseProbe.txt"
    probe.write_text("x", encoding="utf-8")
    try:
        return os.path.exists(folder / "caseprobe.txt")
    finally:
        probe.unlink()


def test_a_case_only_rename_of_the_package_id_keeps_the_new_draft(tmp_path):
    prior = tmp_path / "HIST7-ROME-01.package.draft.toml"
    prior.write_text("old draft", encoding="utf-8")
    new = tmp_path / "hist7-rome-01.package.draft.toml"

    commit_artifacts(tmp_path, [(new, "new draft")], priors=[prior])

    assert new.exists(), "the re-draft's own artifact was deleted after it was written"
    assert new.read_text(encoding="utf-8") == "new draft"
    names = sorted(p.name for p in tmp_path.iterdir())
    if _case_insensitive(tmp_path):
        assert len(names) == 1, names
    else:
        assert names == ["hist7-rome-01.package.draft.toml"], names
