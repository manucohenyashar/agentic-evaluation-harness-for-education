"""The vocabulary the redesign's exhaustive scan (TC-CONSOLE-74) and its synchronization
meta-test (TC-REQ-138) are written against.

`docs/design/console_redesign_test_plan.md` §3.6/§3.7 (issue #774, tracing `CT-CONSOLE-31`
/ `NFR-CONSOLE-10` / `RS-08`): visit **every** teacher screen — not a sample, because the
RS-08 failure mode is the teacher meeting jargon exactly once, on the one screen the sample
missed — and scan the rendered text for the forbidden-term list. The list lives here, once,
because two cases consume it and they must not drift apart:

- `TC-CONSOLE-74` walks the screens and asserts **zero** in-scope hits against
  `SCAN_FAMILIES` (the plan's six families, calibrated against the rendered screens);
- `TC-REQ-138` parses the design delta's §3.3.3 table itself and asserts
  `FORBIDDEN_TERMS` equals its left column — the map cannot drift from the scan silently.

**What this module is not.** It is not `console_vocabulary`'s second half: that module
transcribes the *old* console's HLD §7.9 vocabulary (touchpoints, control actions), which
the redesign keeps; this one transcribes the *redesign delta's* vocabulary map (§3.3.3),
which governs the new SPA copy. Read them side by side, never merged.

Design delta §3.3.3: *"Every teacher-visible string uses the right column. The left column
is forbidden on teacher-facing surfaces (CT-CONSOLE-31 makes it a text-scannable rule).
This table is the single source both the SPA copy and the test-plan's vocabulary scan
import."* The scan is therefore a **screen-instantiated** census by the plan's own stated
limit (§7): a future screen must be added to the walk below by convention — the census
cannot catch a screen it was never taught.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- §3.3.3's left column, verbatim (TC-REQ-138's oracle) -----------------------------------------
#
# Transcribed in the document's order, one entry per table row. TC-REQ-138 parses the design
# delta itself and asserts equality in **both directions**: containment alone would stay green
# when a row is dropped from *this* constant, and the point of the case is that neither side
# can move without the other noticing. `TC-CONSOLE-74`'s scan families below are the
# text-scannable operationalization of these rows — the rows that name syntax, paths,
# identifiers, codes and key names; the rows that are plain words are the copy discipline the
# SPA's own copy already implements (the wizard's shipped strings say "grading run", "parked",
# "grading point", "score level", never their left-column counterparts).
FORBIDDEN_TERMS: tuple[str, ...] = (
    "package",
    "cohort",
    "class ledger",
    "run",
    "submission / submission_id",
    "ingest, ingestion",
    "ingest gate",
    "quarantine, quarantined",
    "unmatched_assessment",
    "criterion / criterion_id",
    "band",
    "placeholder",
    "authoring draft",
    "authoring report",
    "transcriber",
    "judge / panel",
    "escalation",
    "decision engine",
    "review window",
    "blind sample",
    "finalize / final",
    "provisional",
    "amend",
    "override",
    "narrative",
    "evidence_sum / general / bands",
    "TOML / config file / run_config",
    "blob store / content-addressed",
    "job",
    "state enums (queued/running/succeeded/failed/cancelled)",
    "HTTP status codes, module names, store paths",
)


# --- The plan's six scan families (TC-CONSOLE-74's list) -------------------------------------------
#
# `TC-CONSOLE-74`: "scan rendered text for: TOML/JSON/YAML syntax tokens, store path
# fragments, `pkg-`/`ref-sub-`/`CRIT-`/`Q\d` raw id patterns, HTTP status codes, module names
# (`M-`-prefixed), config key names." Each family below is that item made checkable, in the
# order the plan lists them.
#
# **Why regexes and not the word list.** A word-level scan of the left column would condemn
# the design's own copy: the wizard says "Start the run", "The run finished", "Create the
# package" — the map's right column governs how a concept is *labelled* ("Grading run",
# "Test package"), and the shipped copy implements that, but the bare words are English. The
# scannable rows are the ones where a violation has a *shape*: syntax tokens, path fragments,
# identifier spellings, status codes, module names, key names. That is also exactly what
# `CT-CONSOLE-31` clauses: "No teacher-facing surface … contains configuration-file syntax or
# identifiers (TOML/JSON/YAML fragments, key names, store paths, HTTP status codes, module
# names)".
SCAN_FAMILIES: dict[str, tuple[str, ...]] = {
    # | TOML / config file / run_config | — configuration syntax in any of the three shapes
    # the console could leak: a `[table]` header, a `key = value` assignment, a JSON
    # `"key":`, a YAML `---` document separator, or a config file extension named in prose.
    "toml_json_yaml": (
        r"(?m)^\s*\[[\w.\"'-]+\]\s*$",
        r"\b[a-z_][a-z0-9_]*\s*=\s*(\"|\d|\[|\{)",
        r"\"\w[\w.]*\"\s*:",
        r"(?m)^\s*---\s*$",
        r"\.(toml|yaml|yml|json)\b",
    ),
    # | blob store / content-addressed | — store path fragments: the tier directories and
    # database files no teacher sentence has a reason to name.
    "store_paths": (
        r"\b(?:stores?|packages?|authoring|artifacts|blobs|uploads)/",
        r"\.(?:sqlite3?|db)\b",
        r"\bcohort\.db\b",
    ),
    # The raw ids the plan names verbatim: `pkg-`, `ref-sub-`, `CRIT-`, `Q\d`. These are the
    # pipeline's internal identifier spellings; a teacher's copy names things by their
    # teacher label, and an id surfacing in copy is the leak RS-08 describes.
    "raw_ids": (
        r"\bpkg-[\w-]+",
        r"\bref-sub-[\w-]+",
        r"\bCRIT-[\w-]+",
        r"\bQ\d+\b",
    ),
    # | HTTP status codes, module names, store paths | — the codes half. A bare "404" is a
    # legitimate figure; the leak is the status-code *spelling* ("HTTP 403") or the
    # reason-phrase form ("403 Forbidden").
    "http_codes": (
        r"\bHTTP\s*\d{3}",
        r"\b\d{3}\s+(?:Bad Request|Unauthorized|Forbidden|Not Found|Conflict|Internal "
        r"Server Error|Service Unavailable|Gateway Timeout)\b",
    ),
    # Module names (`M-`-prefixed): the harness's own architecture leaking onto a screen.
    "modules": (r"\bM-[A-Z]{2,}\b",),
    # | TOML / config file / run_config | — the key-name half: environment knobs, config
    # keys, the settings file's identifiers. `HARNESS_*` and `CONSOLE_*` cover the declared
    # knob prefixes; the three literals are the settings document's own keys.
    "config_keys": (
        r"\bHARNESS_[A-Z0-9_]+\b",
        r"\bCONSOLE_[A-Z_]+\b",
        r"\bprompt_template[a-z0-9_]*\b",
        r"\brun_config\b",
        r"\bbuild_id\b",
    ),
}


# --- The walk: every teacher screen, enumerated (the documented enumeration mechanism) -------------
#
# `TC-CONSOLE-74` visits every route below and scans its rendered text. The plan says
# "16 SPA routes + the teacher-reachable server-rendered screens"; the shipped SPA routes
# twenty (the redesign's later stories added the authoring, secondary and status screens the
# count predates), and the walk covers the shipped truth — a superset of the plan's sixteen,
# never a sample of it.
#
# Placeholders in braces are filled per walk from the seeded world (see `WALK_IDS`); the
# `{package_version}` stays the pipeline-generated published version id, because the export
# gate's address must name the real version the teacher is about to export.
SPA_WALK_ROUTES: tuple[str, ...] = (
    "/",
    "/class",
    "/package",
    "/package/author",
    "/package/review",
    "/package/edit",
    "/papers",
    "/run",
    "/monitor",
    "/review",
    "/results",
    "/results/students/{submission_id}",
    "/issues",
    "/logs",
    "/parked",
    "/jobs",
    "/settings",
    "/help",
    "/status",
    "/review/blind",
)

#: The server-rendered teacher screens, from the design delta's route table (§3.3.2): the
#: package screens, the three setup screens, the four run screens, the student's page and
#: the export gate. The SPA links to these as "Open the detailed view"; a teacher reaches
#: every one, so the scan must cover them.
SERVER_WALK_SCREENS: tuple[str, ...] = (
    "/packages",
    "/packages/new",
    "/setup/inventory",
    "/setup/answer-keys",
    "/setup/optional",
    "/runs/{run_id}/review",
    "/runs/{run_id}/blind",
    "/runs/{run_id}/sample",
    "/runs/{run_id}/rollup",
    "/students/{student_ref}",
    "/packages/{package_version}/export-gate",
)

#: The walk world's ids, chosen so the ids **the test controls** do not themselves match the
#: raw-id families — otherwise every screen carrying a seeded id fails for the seed's
#: spelling rather than for the console's copy, and the census's signal drowns in its own
#: fixture. The ids the *pipeline* generates (the published version id, the submission ids
#: derived from the cohort id) are left to the pipeline, and any hit they produce is
#: adjudicated per-hit in the walk test, with the reason written next to it.
WALK_IDS: dict[str, str] = {
    "cohort_id": "cls-r-9k3m2p",
    "package_id": "pap-r-7fj34l",
    "run_id": "run-r-7fj34l",
    "student_ref": "stu-r-9k3m2p-01",
}


# --- The shipped screens' own placeholder sentinels (TC-CONSOLE-74's adjudication) ------------------
#
# The spelling a server screen shows when the address names no entity: `surfaces.py`'s
# package card ("Package pkg-unaddressed" for a bare `/packages`), documented verbatim in
# the help manual's page map ("With no `?package_version=` it shows a placeholder card —
# 'Package pkg-unaddressed'"), so this is shipped, teacher-visible copy — a sentinel for
# "nothing is named here", not an identifier of anything. The census adjudicates a hit
# whose matched string is **exactly** `pkg-unaddressed` and nothing else: any other
# `pkg-`-shaped string on any screen is still a leak, and a sentinel rendering where the
# design names a real entity is a finding the walk's own scoping catches.
#
# (`pkg-unaddressed` is the only sibling the scan families can actually hit — the
# raw-id family's `pkg-` pattern matches it. The other screens' sentinel spellings,
# `c-unaddressed` and `r-unaddressed`, match no family; listing them here would be
# adjudication entries that can never fire, so they live in this comment and nowhere
# else.)
SHIPPED_SENTINELS: tuple[str, ...] = (
    "pkg-unaddressed",
)


@dataclass(frozen=True)
class ScanHit:
    """One forbidden-term hit, with enough context to adjudicate it."""

    family: str
    pattern: str
    matched: str
    #: The hit with some surrounding text, newlines flattened — a failure message a human
    #: can act on without re-running anything.
    context: str


def _context(text: str, start: int, end: int) -> str:
    window = text[max(0, start - 45) : end + 45]
    return " ".join(window.split())


def scan_text(text: str) -> list[ScanHit]:
    """Every forbidden-term hit in `text`, across all six families.

    Ordered by family then position, so a failure message reads as an inventory of one
    screen rather than a shuffle. Each hit carries its pattern and its context; the caller
    decides in-scope (failure) from out-of-scope (documented adjudication).
    """
    hits: list[ScanHit] = []
    for family in SCAN_FAMILIES:
        for pattern in SCAN_FAMILIES[family]:
            for match in re.finditer(pattern, text):
                hits.append(
                    ScanHit(
                        family=family,
                        pattern=pattern,
                        matched=match.group(0),
                        context=_context(text, match.start(), match.end()),
                    )
                )
    return hits


def server_screen_text(html: str) -> str:
    """The rendered text of a server-rendered screen's HTML.

    The claim is about what a **teacher reads**. Tags and attributes are stripped (the
    server screens are templated HTML, not a DOM a browser resolves), whitespace is
    collapsed, and the result is what the scan runs over — the same text a browser would
    paint, without class names or `data-` attributes that could trip a pattern the reader
    never sees.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    return " ".join(text.split())


def fill_screens(templates: tuple[str, ...], values: dict[str, str]) -> list[str]:
    """Fill the walk templates with the world's ids, skipping templates whose value is
    still its own placeholder.

    Every template must be filled or skipped explicitly — a route silently left carrying
    `{run_id}` would be visited as a literal and render the not-found screen, which scans
    clean and proves nothing. The caller asserts the count instead.
    """
    filled = []
    for template in templates:
        route = template
        for key, value in values.items():
            route = route.replace("{" + key + "}", value)
        if "{" in route:
            continue
        filled.append(route)
    return filled
