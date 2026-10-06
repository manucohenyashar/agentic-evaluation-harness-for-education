"""The vocabulary `M-UI`'s cases (issue #639, TC-UI-01..07, TC-UI-C01..C06, PERF-19, and the
re-pointed TC-CONSOLE-40/41) are written against.

Design 1.10-delta §3.4.3 declares `M-UI`'s requirements and contract but **no interface**: no
bundle path, no source layout, no token-file format, no build command, no DOM shape. Every name
below is therefore *invented*, in the `console_vocabulary` precedent — and isolated here so the
implementing stories (#634 the foundation, #635 the screens, #638 the Q&A panel) can rename any
of them with a one-line change instead of an edit to every test. Checked: none of
`console_assets/spa`, `ui/src/design/tokens.json`, `npm run build -- --outDir` or the hub label
patterns appears in `docs/design/detailed-design.md`, `operator_requirements_design_delta.md`,
`operator_requirements_test_plan.md` or `test-plan.md`.

What is *not* invented, and is quoted from the design:

* the nine hub destinations (FR-UI-02) — matched as accessible link names, case-insensitively;
* the recovery wording "check that the console service is running" (FR-UI-07);
* the answers-only affordance "this assistant answers questions; it does not operate the system"
  (FR-UI-06, user decision 2);
* the five token categories — color palette, type scale, spacing scale, radius, elevation
  (FR-UI-04).

The DOM conventions are deliberately the accessible ones rather than `data-testid` hooks: a hub
card is a **link** whose accessible name names its destination; a screen is loaded when its
`main` landmark carries a level-1 heading; a confirmation is a `dialog`/`alertdialog`. A screen
built to WCAG (FR-UI-04 requires AA) has these anyway.

The bundle-sweep and bundle-diff helpers are pure functions over a directory so their
controls (`tests/artifact/test_spa_bundle_gate.py`) can prove them against planted bundles today,
before any real bundle exists.

Run as a module, this file is also the cheap probe the `#635`/`#638` entries in
`WRITTEN_AHEAD_BLOCKERS` use: ``python -m tests.support.spa contains "<phrase>"`` exits 0 only
when the committed bundle exists and some text file in it carries the phrase.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- the invented layout (one line each to rename) -------------------------------------------

#: The committed, prebuilt bundle, inside the package's data (`aeh/console_assets/...`, which is
#: where operator test plan §5.0's TC-STORE-26 arm expects it: "`console_assets/*` covers the SPA
#: bundle directory too").
BUNDLE_DIR = REPO_ROOT / "src" / "aeh" / "console_assets" / "spa"
BUNDLE_INDEX = BUNDLE_DIR / "index.html"
#: The package-relative prefix the bundle files are declared under in `[tool.setuptools.package-data]`.
PACKAGE_DATA_PREFIX = "console_assets/spa"

#: The TypeScript source and its pinned toolchain (Q-O3: "the dev toolchain is pinned in
#: requirements-dev.txt-adjacent tool config") — a lockfile is the pin.
SPA_SOURCE_DIR = REPO_ROOT / "ui"
SPA_LOCKFILE = SPA_SOURCE_DIR / "package-lock.json"
#: The design tokens, the single source of truth (NFR-UI-02). A JSON object of five categories,
#: each a mapping of token name -> CSS value.
TOKENS_FILE = SPA_SOURCE_DIR / "src" / "design" / "tokens.json"
TOKEN_CATEGORIES = ("color", "fontSize", "space", "radius", "shadow")

#: The rebuild, into an out-of-tree directory (never in place: rebuilding over the committed
#: bundle dirties the tree and races every case that reads it). `{out}` is substituted.
INSTALL_COMMAND = ("npm", "ci", "--no-audit", "--no-fund")
BUILD_COMMAND = ("npm", "run", "build", "--", "--outDir", "{out}", "--emptyOutDir")

# --- the quoted design vocabulary ------------------------------------------------------------

#: FR-UI-02's nine destinations, as accessible-name patterns for the hub's card links.
HUB_DESTINATIONS: dict[str, re.Pattern[str]] = {
    "package": re.compile(r"set ?up (a )?(test|package)", re.I),
    "class": re.compile(r"set ?up (a )?class", re.I),
    "papers": re.compile(r"load(ing)? papers", re.I),
    "run_start": re.compile(r"start (a |the )?run", re.I),
    "monitor": re.compile(r"monitor", re.I),
    "review": re.compile(r"\breview\b", re.I),
    "results": re.compile(r"\bresults\b", re.I),
    "help": re.compile(r"manuals|help", re.I),
    "status": re.compile(r"system status", re.I),
}
#: The seven lifecycle screens of FR-UI-03, by hub destination.
LIFECYCLE_SCREENS = ("package", "class", "papers", "run_start", "monitor", "review", "results")

RECOVERY_TEXT = "check that the console service is running"
#: A manuals question the recorded QA double (operator plan §4 rule 7) answers grounded. Invented;
#: #636/#638 align the double's grounded transcript with it (or this constant with the double).
QA_MANUALS_QUESTION = "What is the blind sample in the review queue for?"
AFFORDANCE_PATTERNS = (re.compile(r"answers questions", re.I),
                       re.compile(r"does not operate the system", re.I))

#: What a raw error looks like when it reaches the teacher (CT-UI-04).
STACK_TRACE_PATTERNS = (
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"^\s+at \S+ \(?\S+:\d+:\d+\)?", re.M),
    re.compile(r"\b(TypeError|ReferenceError|SyntaxError|RangeError|Uncaught|Unhandled Rejection)\b"),
    re.compile(r"Minified React error"),
)

# --- TC-UI-01 (b): the full-text external-origin sweep ---------------------------------------

#: XML namespace identifiers React DOM carries as string constants. They are names, not
#: addresses: nothing fetches them. An exact, closed list — anything else on w3.org fails.
NAMESPACE_URIS = frozenset({
    "http://www.w3.org/1999/xhtml",
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1998/Math/MathML",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/XML/1998/namespace",
    "http://www.w3.org/2000/xmlns/",
})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: Files whose bytes are not text a browser resolves URLs from. Everything else is swept —
#: HTML, CSS, JS, maps, JSON manifests, SVG, text — because a font URL or a manifest is the
#: likely leak, not the obvious `<script src>`.
BINARY_SUFFIXES = frozenset({".woff", ".woff2", ".ttf", ".otf", ".eot", ".png", ".jpg", ".jpeg",
                             ".gif", ".webp", ".avif", ".ico", ".bmp"})
_URL = re.compile(r"""(?:https?|wss?)://[^\s"'`)<>\\,;]+""", re.I)
_PROTOCOL_RELATIVE = re.compile(
    r"""(?:url\(\s*['"]?|@import\s+['"]|(?:src|href|action)\s*=\s*['"]?)(//[^\s"'`)<>\\,;]+)""",
    re.I)


def bundle_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def external_origins_in_bundle(root: Path) -> list[tuple[str, str]]:
    """Every `(relative path, url)` in the bundle's text naming a non-loopback origin."""
    found: list[tuple[str, str]] = []
    for path in bundle_files(root):
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        for match in _URL.finditer(text):
            url = match.group(0).rstrip(".")
            if url in NAMESPACE_URIS or url.rstrip("/") in {u.rstrip("/") for u in NAMESPACE_URIS}:
                continue
            host = (urlsplit(url).hostname or "").strip("[]").lower()
            if host in LOOPBACK_HOSTS:
                continue
            found.append((path.relative_to(root).as_posix(), url))
        # Protocol-relative references (`url(//fonts.example/x)`, `src="//cdn/x"`) carry no
        # scheme, so the sweep above cannot see them; CT-UI-01 forbids them just the same.
        for match in _PROTOCOL_RELATIVE.finditer(text):
            host = (urlsplit("http:" + match.group(1)).hostname or "").lower()
            if host not in LOOPBACK_HOSTS:
                found.append((path.relative_to(root).as_posix(), match.group(1)))
    return found


def text_in_bundle(root: Path, phrase: str) -> list[str]:
    """The bundle's text files carrying `phrase` (case-insensitive)."""
    needle = phrase.lower()
    return [
        p.relative_to(root).as_posix() for p in bundle_files(root)
        if p.suffix.lower() not in BINARY_SUFFIXES
        and needle in p.read_bytes().decode("utf-8", errors="replace").lower()
    ]


def service_worker_registrations_in_bundle(root: Path) -> list[str]:
    """Files whose code could register a service worker (TC-CONSOLE-40's SPA arm)."""
    pattern = re.compile(r"serviceWorker\s*\.\s*register|navigator\s*\.\s*serviceWorker", re.I)
    return [
        p.relative_to(root).as_posix() for p in bundle_files(root)
        if p.suffix.lower() not in BINARY_SUFFIXES
        and pattern.search(p.read_bytes().decode("utf-8", errors="replace"))
    ]


# --- TC-UI-01 (c) / TC-UI-C06: the rebuild diff ----------------------------------------------


def bundle_diff(committed: Path, rebuilt: Path) -> list[str]:
    """Every difference between two bundle trees: missing, extra, or changed bytes."""
    a = {p.relative_to(committed).as_posix(): p for p in bundle_files(committed)}
    b = {p.relative_to(rebuilt).as_posix(): p for p in bundle_files(rebuilt)}
    problems = [f"missing from the rebuild: {name}" for name in sorted(a.keys() - b.keys())]
    problems += [f"not in the committed bundle: {name}" for name in sorted(b.keys() - a.keys())]
    problems += [f"bytes differ: {name}" for name in sorted(a.keys() & b.keys())
                 if a[name].read_bytes() != b[name].read_bytes()]
    return problems


# --- TC-UI-01 (a): the bundle ships ----------------------------------------------------------


def declared_package_data_globs(pyproject: Path = REPO_ROOT / "pyproject.toml") -> list[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return list(data.get("tool", {}).get("setuptools", {}).get("package-data", {}).get("aeh", []))


def files_outside_package_data(root: Path, globs: list[str]) -> list[str]:
    """Bundle files no declared `aeh` package-data glob matches — present in `src/`, absent from
    the wheel. setuptools globs match one path level per `*` unless `**` is used."""
    package_root = REPO_ROOT / "src" / "aeh"
    uncovered = []
    for path in bundle_files(root):
        rel = path.relative_to(package_root).as_posix()
        if not any(_glob_matches(rel, g) for g in globs):
            uncovered.append(rel)
    return uncovered


def _glob_matches(rel: str, glob: str) -> bool:
    if "**" in glob:
        return fnmatch(rel, glob.replace("**/", "*").replace("**", "*"))
    return len(rel.split("/")) == len(glob.split("/")) and all(
        fnmatch(part, pat) for part, pat in zip(rel.split("/"), glob.split("/")))


# --- the store, read from outside -------------------------------------------------------------


def store_digest(data_dir: Path) -> dict[str, tuple[int, str]]:
    """Every table in every tier file under `data_dir`: its row count and a hash of its rows —
    the all-tier snapshot a "no-op until confirmed" or "a reload writes nothing" oracle compares
    (TC-UI-05, TC-UI-C02). Contents, not just counts, so an UPDATE (a run's status) is a write."""
    import hashlib

    out: dict[str, tuple[int, str]] = {}
    for db in sorted(Path(data_dir).rglob("*.sqlite")):
        connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            for (table,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
                rows = sorted(repr(r) for r in connection.execute(f'SELECT * FROM "{table}"'))
                out[f"{db.relative_to(data_dir).as_posix()}:{table}"] = (
                    len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())
        finally:
            connection.close()
    return out


def changed_tables(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


# --- the E6 session ----------------------------------------------------------------------------

#: Per-step budget, env-gated (seam 3): the E6 navigation knob TS-49 already declared.
STEP_TIMEOUT_MS = int(os.environ.get("HARNESS_E6_NAVIGATION_TIMEOUT_MS", "5000"))
#: PERF-19's thresholds — NFR-UI-01's figures, measured on the reference hardware. Knobs so a
#: slower box is visible as a deliberate override, never a silent pass.
FCP_BUDGET_MS = float(os.environ.get("HARNESS_UI_FCP_BUDGET_MS", "2000"))
TRANSITION_BUDGET_MS = float(os.environ.get("HARNESS_UI_TRANSITION_BUDGET_MS", "300"))

_INIT_SCRIPT = """
window.__aehRejections = [];
window.addEventListener('unhandledrejection', (e) => {
  window.__aehRejections.push(String(e.reason && (e.reason.stack || e.reason)));
});
"""


@dataclass
class SpaLog:
    origin: str
    requests: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    console: list[tuple[str, str]] = field(default_factory=list)

    def foreign_requests(self) -> list[str]:
        own = urlsplit(self.origin)
        return [u for u in self.requests
                if urlsplit(u).scheme in ("http", "https", "ws", "wss")
                and (urlsplit(u).hostname, urlsplit(u).port) != (own.hostname, own.port)]

    def api_requests(self) -> list[str]:
        return [u for u in self.requests if u.startswith(self.origin + "/api/")]


@contextmanager
def spa_page(origin: str) -> Iterator[tuple[Any, SpaLog]]:
    """One browser context on the console's origin, recording requests, page errors, console
    messages and unhandled rejections. Skips naming the missing piece when E6 is unavailable —
    the TS-49 rule: a visibly skipped browser case, never a silently passing one."""
    import pytest

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        pytest.skip(f"E6 unavailable: the Playwright driver is not installed ({error})")
    from tests.support.console_browser import BROWSER_CHANNELS

    with sync_playwright() as driver:
        browser, reasons = None, []
        for channel in BROWSER_CHANNELS:
            try:
                browser = driver.chromium.launch(channel=channel, headless=True)
                break
            except PlaywrightError as error:
                reasons.append(f"{channel}: {str(error).splitlines()[0]}")
        if browser is None:
            pytest.skip("E6 unavailable: no Chromium-family browser launched: " + "; ".join(reasons))
        try:
            context = browser.new_context()
            context.add_init_script(_INIT_SCRIPT)
            log = SpaLog(origin=origin)
            context.on("request", lambda request: log.requests.append(request.url))
            page = context.new_page()
            page.set_default_timeout(STEP_TIMEOUT_MS)
            page.on("pageerror", lambda error: log.page_errors.append(str(error)))
            page.on("console", lambda message: log.console.append((message.type, message.text)))
            yield page, log
        finally:
            browser.close()


def open_hub(page: Any, origin: str) -> Any:
    response = page.goto(origin + "/", wait_until="networkidle")
    return response


def hub_card(page: Any, destination: str) -> Any:
    return page.get_by_role("link", name=HUB_DESTINATIONS[destination])


def screen_heading(page: Any) -> Any:
    return page.locator("main").get_by_role("heading", level=1)


def wait_for_screen(page: Any) -> str:
    """Wait until the current screen's `main` carries its level-1 heading; return its text."""
    heading = screen_heading(page).first
    heading.wait_for(state="visible")
    page.wait_for_load_state("networkidle")
    return heading.inner_text()


def go_to(page: Any, origin: str, destination: str) -> str:
    """Hub -> one click on the destination's card -> the screen's heading text."""
    if urlsplit(page.url).path not in ("", "/") or not page.url.startswith(origin):
        open_hub(page, origin)
    hub_card(page, destination).first.click()
    return wait_for_screen(page)


def main_text(page: Any) -> str:
    """The `main` landmark's text, or "" when the page has none (a red case reports what is
    missing; it does not die on a locator timeout)."""
    main = page.locator("main")
    return main.first.inner_text() if main.count() else ""


def rejections(page: Any) -> list[str]:
    try:
        return list(page.evaluate("() => window.__aehRejections || []"))
    except Exception as error:  # a page that cannot evaluate is reported, not hidden
        return [f"(could not read rejections: {error})"]


def raw_errors_in(text: str) -> list[str]:
    return [p.pattern for p in STACK_TRACE_PATTERNS if p.search(text)]


STORAGE_PROBE = """async () => {
  const entries = (s) => Array.from({length: s.length}, (_, i) => [s.key(i), s.getItem(s.key(i))]);
  const workers = navigator.serviceWorker
      ? (await navigator.serviceWorker.getRegistrations()).length : 0;
  const cached = [];
  if (self.caches) {
    for (const name of await caches.keys()) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) {
        const response = await cache.match(request);
        cached.push([request.url, response ? await response.text() : ""]);
      }
    }
  }
  const idb = indexedDB.databases ? (await indexedDB.databases()).map((d) => d.name) : [];
  return {local: entries(localStorage), session: entries(sessionStorage), workers, cached, idb,
          cookie: document.cookie};
}"""


def storage_problems(page: Any, sentinel: str | None = None) -> list[str]:
    """What the browser holds on this origin after a session (FR-UI-08, CT-UI-03)."""
    facts = page.evaluate(STORAGE_PROBE)
    problems = []
    if facts["local"]:
        problems.append(f"localStorage holds {facts['local']!r}")
    if facts["session"]:
        problems.append(f"sessionStorage holds {facts['session']!r}")
    if facts["workers"]:
        problems.append(f"{facts['workers']} service worker(s) registered")
    if facts["cached"]:
        problems.append(f"Cache Storage holds {[u for u, _ in facts['cached']]!r}")
    if facts["idb"]:
        problems.append(f"IndexedDB holds databases {facts['idb']!r}")
    if sentinel and any(sentinel in body for _, body in facts["cached"]):
        problems.append("a Cache Storage entry holds the sentinel student text")
    if sentinel and sentinel in (facts["cookie"] or ""):
        problems.append("a cookie holds the sentinel student text")
    return problems


def load_tokens() -> dict[str, dict[str, str]]:
    return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))


def _probe_main(argv: list[str]) -> int:
    """`python -m tests.support.spa contains "<phrase>"` — the cheap blocker probe."""
    if len(argv) != 2 or argv[0] != "contains":
        print('usage: python -m tests.support.spa contains "<phrase>"', file=sys.stderr)
        return 2
    if not BUNDLE_INDEX.is_file():
        return 1
    return 0 if text_in_bundle(BUNDLE_DIR, argv[1]) else 1


if __name__ == "__main__":
    raise SystemExit(_probe_main(sys.argv[1:]))
