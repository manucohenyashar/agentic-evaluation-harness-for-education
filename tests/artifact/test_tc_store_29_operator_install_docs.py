"""`TC-STORE-29` (`FR-STORE-21`, operator-requirements test plan §5.1; issue #613): no
operator-facing document names an extra or a manual `Pillow` install, and the air-gap wheelhouse
paragraph is present.

| ID | Input | Expected | Oracle |
|---|---|---|---|
| `TC-STORE-29` | Static scan over `docs/tutorials/`, `docs/live-tests/`, and `README.md`'s install sections for `".[live-ingest]"`, `".[jev-cloud]"`, `pip install` adjacent to `Pillow` | Zero matches; the deployment tutorial names the wheelhouse pattern (`pip download` off-machine, `pip install --no-index --find-links` at the school) | Exact + presence |

**Written ahead of #614** (`writtenahead`, keyed there): today the deployment tutorial and the
live-test guides tell the operator to run `pip install ".[live-ingest]" Pillow` and
`pip install ".[jev-cloud]"`, and the wheelhouse paragraph does not exist. #614 reduces those
instructions to `pip install .` in the same change as the packaging flip (FR-STORE-21).

**Scope of the scan, and why it is a little wider than the three literal strings.**

* *Every text file* under `docs/tutorials/` and `docs/live-tests/` — Markdown, but also the
  sample-material scripts and configs, whose docstrings an operator reads when a script tells them
  what to install. A PDF or an image is not text and is skipped.
* `README.md` only in its install sections — a heading containing *setup* or *install*. The rest
  of the README is design narrative and may legitimately mention the retired extras as history.
  The scan asserts at least one such section exists, so a renamed heading cannot empty it.
* An extra is matched as `.[name]` with or without quotes and inside a combined
  `.[a,b]` — `pip install .[jev-cloud]` is the same instruction as the quoted form. Beyond the two
  retired names, **any** `pip install` line naming an extra (`.[…]`) fails: ADR-36 retires every
  extra, and a newly invented one is the same manual step under another name.
* "Adjacent to `Pillow`" is a `pip install` and the word `Pillow` (any case — pip accepts
  `pillow`) on the same line or on consecutive lines. That catches `pip install . Pillow`, a
  two-line code block, and the prose line that follows a command telling the operator to add it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OPERATOR_DOC_DIRS = (REPO_ROOT / "docs" / "tutorials", REPO_ROOT / "docs" / "live-tests")
README = REPO_ROOT / "README.md"
DEPLOYMENT_TUTORIAL = REPO_ROOT / "docs" / "tutorials" / "deployment-tutorial.md"

#: Suffixes read as text. Anything else (PDF, PNG) is binary sample material.
TEXT_SUFFIXES = {".md", ".txt", ".py", ".toml", ".ps1", ".sh", ".bat", ".cfg", ".ini", ".yaml", ".yml"}

#: The two retired extras, quoted or bare, alone or in a combined bracket.
RETIRED_EXTRA = re.compile(r"\.\[[^\]\n]*\b(?:live-ingest|jev-cloud)\b[^\]\n]*\]")
#: Any extra on a `pip install` line: `.[x]`, `<path>[x]`, `"…[x]"`.
PIP_INSTALL = re.compile(r"\bpip\s+install\b", re.I)
EXTRA_ON_INSTALL = re.compile(r"\bpip\s+install\b[^\n]*?[.\w/\\\"']\[[A-Za-z0-9_,\- ]+\]", re.I)
PILLOW = re.compile(r"\bpillow\b", re.I)
README_INSTALL_HEADING = re.compile(r"^(#{1,6})\s+.*\b(?:setup|install\w*)\b", re.I)


def _operator_files() -> list[Path]:
    files = sorted(p for d in OPERATOR_DOC_DIRS for p in d.rglob("*")
                   if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
    assert files, f"no operator documents under {[str(d) for d in OPERATOR_DOC_DIRS]}"
    return files


def _readme_install_sections() -> list[tuple[int, str]]:
    """`(line number, line)` for every line inside a README section whose heading names setup or
    installation, up to the next heading of the same or a higher level."""
    lines = README.read_text(encoding="utf-8").splitlines()
    picked: list[tuple[int, str]] = []
    level: int | None = None
    in_fence = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        heading = None if in_fence else re.match(r"^(#{1,6})\s", line)
        if heading:
            depth = len(heading.group(1))
            if level is not None and depth <= level:
                level = None
            if level is None and README_INSTALL_HEADING.match(line):
                level = depth
        if level is not None:
            picked.append((number, line))
    assert picked, "README.md has no setup/install section to scan; the sweep would be vacuous"
    return picked


def _scanned() -> list[tuple[str, list[tuple[int, str]]]]:
    sources = [(p.relative_to(REPO_ROOT).as_posix(),
                list(enumerate(p.read_text(encoding="utf-8").splitlines(), 1)))
               for p in _operator_files()]
    sources.append(("README.md (install sections)", _readme_install_sections()))
    return sources


def _violations(name: str, numbered: list[tuple[int, str]]) -> list[str]:
    found: list[str] = []
    for index, (number, line) in enumerate(numbered):
        if RETIRED_EXTRA.search(line):
            found.append(f"{name}:{number}: names a retired extra: {line.strip()}")
        elif EXTRA_ON_INSTALL.search(line):
            found.append(f"{name}:{number}: `pip install` names an extra: {line.strip()}")
        if PIP_INSTALL.search(line):
            window = [numbered[j] for j in (index - 1, index, index + 1)
                      if 0 <= j < len(numbered) and numbered[j][0] - number in (-1, 0, 1)]
            if any(PILLOW.search(text) for _, text in window):
                found.append(f"{name}:{number}: `pip install` adjacent to Pillow: {line.strip()}")
    return found


@pytest.mark.writtenahead
def test_tc_store_29_no_operator_document_names_an_extra_or_a_manual_pillow_install() -> None:
    """Zero matches across the whole operator-facing set (FR-STORE-21)."""
    violations = [v for name, numbered in _scanned() for v in _violations(name, numbered)]
    assert violations == [], (
        "operator documents still name an extra or a hand-installed Pillow; ADR-36 makes "
        "`pip install .` the only install command:\n  " + "\n  ".join(violations)
    )


@pytest.mark.writtenahead
def test_tc_store_29_the_deployment_tutorial_carries_the_air_gap_wheelhouse_paragraph() -> None:
    """Presence: one section of the deployment tutorial names both halves of the wheelhouse
    pattern — `pip download` on a connected machine, `pip install --no-index --find-links` at the
    school. One section, not anywhere in the file: the two commands are one procedure, and an
    operator who finds one without the other has half an install."""
    text = DEPLOYMENT_TUTORIAL.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^#{1,6}\s", text)
    download = re.compile(r"\bpip\s+download\b")
    offline = re.compile(r"\bpip\s+install\b[^\n]*--no-index\b[^\n]*--find-links\b"
                         r"|\bpip\s+install\b[^\n]*--find-links\b[^\n]*--no-index\b")
    assert any(download.search(s) and offline.search(s) for s in sections), (
        f"{DEPLOYMENT_TUTORIAL.relative_to(REPO_ROOT).as_posix()} has no section naming both "
        "`pip download` and `pip install --no-index --find-links` (FR-STORE-21's air-gap paragraph)"
    )


def test_tc_store_29_the_scanner_flags_each_removed_instruction_and_passes_the_reduced_one() -> None:
    """Green self-check of the sweep's sensitivity, so the two cases above cannot go green by the
    scanner going blind. Each removed instruction shape is flagged; the reduced instructions
    FR-STORE-21 asks for, and a README-style dev install, are not."""
    flagged = [
        'pip install ".[live-ingest]" Pillow',
        "pip install .[jev-cloud]",
        "pip install '.[live-ingest,jev-cloud]'",
        'pip install ".[ui]"',
        "pip install .\npip install pillow",
        "`Pillow` is not pulled in, so add it: `pip install Pillow`",
    ]
    clean = [
        "pip install .",
        "python -m venv .venv\npip install .",
        ".venv/Scripts/python -m pip install -r requirements-dev.txt",
        "pip download . -d wheelhouse\npip install --no-index --find-links wheelhouse .",
        "Pillow decodes the page pictures; it installs with the system.",
    ]
    for text in flagged:
        assert _violations("t", list(enumerate(text.splitlines(), 1))), f"missed: {text!r}"
    for text in clean:
        assert _violations("t", list(enumerate(text.splitlines(), 1))) == [], f"false hit: {text!r}"
