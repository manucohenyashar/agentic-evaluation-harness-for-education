"""Issue #639 — the SPA bundle gate, rung 0 (fast tier): `TC-UI-01 (a)`/`(b)`, the static halves
of `TC-UI-C01` (one origin), `TC-UI-C06` (the reproducible bundle's committed inputs) and the
re-pointed `TC-CONSOLE-40` (no service-worker registration anywhere in the bundle, operator plan
§5.0), plus the declared token set of `TC-UI-04`.

**Why a full-text sweep.** FR-UI-01 / RISK-108: an external origin is green in development and
fatal offline — the school has no internet, and a CDN font renders a blank console there. An
attribute parser (the server-rendered console's `external_origins`) misses a URL built in
JavaScript or a CSS `@font-face` inside a hashed asset, so this gate reads **every text byte** of
the bundle (`spa.external_origins_in_bundle`). The closed exceptions are loopback hosts and the
XML namespace identifiers React DOM carries as constants (`spa.NAMESPACE_URIS`); nothing else,
including `https://react.dev/errors/…`, passes.

**Why "ships" and not just "exists".** `pyproject.toml` declares `aeh = ["console_assets/*"]`,
one path level deep: a nested `assets/` directory exists in `src/` and is absent from the wheel.
`TC-UI-01 (a)` therefore also asserts every bundle file is matched by a declared package-data glob.

The bundle cases were **written ahead of #634** and joined the gate when it landed: the marker
is off and the entry is out of `WRITTEN_AHEAD_BLOCKERS`, the cases re-checked green unmarked.
The **controls** — the sweep, the diff and the glob matcher proven against planted bundles in
both directions — need no bundle: a sweep that cannot fail is a gate that cannot close.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import spa
from tests.support.impl import require_path


def _require_bundle() -> Path:
    return require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")


def _plant(root: Path, files: dict[str, str | bytes]) -> Path:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            path.write_bytes(body)
        else:
            path.write_text(body, encoding="utf-8")
    return root


# --- the cases over the real bundle (red until #634) ---------------------------------------------


def test_tc_ui_01_a_the_committed_bundle_is_present_non_empty_and_ships_as_package_data():
    """`TC-UI-01 (a)` / FR-UI-01 (P0) — the bundle is at the package-data path, its `index.html`
    is a non-empty HTML document that loads at least one script, it carries HTML, JS and CSS, and
    every one of its files is declared package data (so `pip install .` ships it)."""
    _require_bundle()
    problems = []
    index = spa.BUNDLE_INDEX.read_text(encoding="utf-8", errors="replace")
    if "<html" not in index.lower() or "<script" not in index.lower():
        problems.append("index.html is not an HTML document that loads the app's script")
    files = spa.bundle_files(spa.BUNDLE_DIR)
    empty = [p.relative_to(spa.BUNDLE_DIR).as_posix() for p in files if p.stat().st_size == 0]
    problems += [f"empty bundle file: {name}" for name in empty]
    for suffix in (".js", ".css"):
        if not any(p.suffix == suffix for p in files):
            problems.append(f"the bundle carries no {suffix} file")
    uncovered = spa.files_outside_package_data(spa.BUNDLE_DIR, spa.declared_package_data_globs())
    problems += [f"not declared package data, so absent from the wheel: {name}"
                 for name in uncovered]
    assert not problems, "\n".join(problems)


def test_tc_ui_01_b_tc_ui_c01_the_bundle_names_no_external_origin():
    """`TC-UI-01 (b)` / `TC-UI-C01` static half / CT-UI-01 (P0) — a full-text sweep of every text
    file of the built bundle finds no `http(s)://` or `ws(s)://` origin other than loopback —
    fonts included. Anchored: the sweep read real HTML, JS and CSS bytes."""
    _require_bundle()
    swept = [p for p in spa.bundle_files(spa.BUNDLE_DIR) if p.suffix in (".html", ".js", ".css")]
    assert swept, "the sweep found no HTML/JS/CSS to read: it would pass vacuously"
    found = spa.external_origins_in_bundle(spa.BUNDLE_DIR)
    assert not found, (
        "the bundle names external origins — green in development, a blank console at a school "
        "with no internet (RISK-108, FR-CONSOLE-18):\n  "
        + "\n  ".join(f"{name}: {url}" for name, url in found[:40]))


def test_tc_console_40_spa_arm_no_service_worker_registration_anywhere_in_the_bundle():
    """`TC-CONSOLE-40` re-pointed, the SPA arm operator plan §5.0 adds (P0, FR-UI-08) — no file of
    the bundle can register a service worker (`navigator.serviceWorker` / `.register`). The
    runtime half (no registration in a live session) is in `tests/browser/spa/`."""
    _require_bundle()
    found = spa.service_worker_registrations_in_bundle(spa.BUNDLE_DIR)
    assert not found, f"service-worker code in the bundle (FR-UI-08 forbids one): {found}"


def test_tc_ui_c06_the_bundle_has_committed_source_a_pinned_toolchain_and_one_token_file():
    """`TC-UI-C06` (rung-0 half) / NFR-UI-02 / `TC-UI-04`'s declared set (P1) — the inputs the
    reproducible build needs are committed: the TypeScript source, the lockfile that pins the
    toolchain (Q-O3), and the single design-token file declaring all five FR-UI-04 scales
    (palette, type scale, spacing, radius, elevation), each non-empty. The byte-identical rebuild
    itself needs Node and runs in E6 (`tests/browser/spa/test_spa_rebuild.py`)."""
    _require_bundle()
    problems = []
    if not spa.SPA_LOCKFILE.is_file():
        problems.append(f"no toolchain lockfile at {spa.SPA_LOCKFILE}: the build is not pinned")
    # Committed source only: `ui/node_modules` (after any `npm ci`) is full of `.d.ts` files.
    source = [p for p in spa.SPA_SOURCE_DIR.rglob("*") if p.suffix in (".ts", ".tsx")
              and "node_modules" not in p.relative_to(spa.SPA_SOURCE_DIR).parts
              and not p.name.endswith(".d.ts")] if spa.SPA_SOURCE_DIR.is_dir() else []
    if not source:
        problems.append(f"no TypeScript source under {spa.SPA_SOURCE_DIR} (NFR-UI-02)")
    if not spa.TOKENS_FILE.is_file():
        problems.append(f"no design-token file at {spa.TOKENS_FILE}")
    else:
        tokens = spa.load_tokens()
        problems += [f"the token file declares no {category!r} scale"
                     for category in spa.TOKEN_CATEGORIES if not tokens.get(category)]
    assert not problems, "\n".join(problems)


# --- the controls: the gate's own detectors, proven both ways (green today) ------------------------


def test_tc_ui_01_b_control_the_sweep_catches_every_planted_external_origin(tmp_path):
    """The failure path #634's acceptance names — "an external origin anywhere in the bundle fails
    the gate test" — demonstrated over a planted bundle: a CDN font in a hashed CSS asset, a URL
    assembled in JS, a JSON manifest, a websocket and a non-namespace w3.org address are each
    caught; loopback, relative paths and the exact namespace constants are not."""
    root = _plant(tmp_path / "bundle", {
        "index.html": '<html><script src="/assets/app.js"></script>'
                      '<a href="http://127.0.0.1:8765/api/">x</a></html>',
        "assets/app-1a2b.css": "@font-face{src:url(https://fonts.gstatic.com/s/inter.woff2)}",
        "assets/app-1a2b.js": 'const ns="http://www.w3.org/2000/svg";'
                              'fetch("https://telemetry.example.org/"+id);'
                              'const x="http://www.w3.org/TR/css";'
                              'new WebSocket("wss://push.example.net/s");'
                              'const local="http://localhost:9000/api";',
        "manifest.json": '{"icons":[{"src":"https://cdn.example.com/i.png"}]}',
        "assets/b.css": "@font-face{src:url(//fonts.googleapis.com/css2)}",
        "assets/inter.woff2": b"wOF2\x00https://fonts.example.com binary license text",
    })
    found = {url for _, url in spa.external_origins_in_bundle(root)}
    assert found == {
        "https://fonts.gstatic.com/s/inter.woff2",
        "https://telemetry.example.org/",
        "http://www.w3.org/TR/css",
        "wss://push.example.net/s",
        "https://cdn.example.com/i.png",
        "//fonts.googleapis.com/css2",
    }, found


def test_tc_ui_01_b_control_a_clean_bundle_passes_the_sweep(tmp_path):
    root = _plant(tmp_path / "bundle", {
        "index.html": '<html><link rel="stylesheet" href="/assets/a.css"></html>',
        "assets/a.css": "@font-face{src:url(/assets/inter.woff2)}",
        "assets/a.js": 'document.createElementNS("http://www.w3.org/1999/xhtml","div");'
                       'fetch("/api/hub")',
    })
    assert spa.external_origins_in_bundle(root) == []


def test_tc_ui_c06_control_the_diff_fails_a_stale_bundle_and_passes_an_identical_one(tmp_path):
    """A stale bundle fails (CT-UI-06): changed bytes, a file the rebuild no longer produces, and
    a file only the rebuild produces are each reported; an identical tree reports nothing."""
    files = {"index.html": "<html>v1</html>", "assets/a.js": "console.log(1)"}
    committed = _plant(tmp_path / "committed", files)
    identical = _plant(tmp_path / "identical", files)
    assert spa.bundle_diff(committed, identical) == []
    stale = _plant(tmp_path / "rebuilt", {"index.html": "<html>v2</html>",
                                          "assets/b.js": "console.log(2)"})
    assert spa.bundle_diff(committed, stale) == [
        "missing from the rebuild: assets/a.js",
        "not in the committed bundle: assets/b.js",
        "bytes differ: index.html",
    ]


def test_tc_ui_01_a_control_a_one_level_glob_does_not_ship_a_nested_asset():
    """The package-data check: `console_assets/*` covers `console_assets/x` but not
    `console_assets/spa/assets/x`; an explicit or `**` glob does."""
    match = spa._glob_matches
    assert match("console_assets/console.css", "console_assets/*")
    assert not match("console_assets/spa/assets/app.js", "console_assets/*")
    assert match("console_assets/spa/assets/app.js", "console_assets/spa/assets/*")
    assert match("console_assets/spa/assets/app.js", "console_assets/**/*")


def test_tc_console_40_control_the_service_worker_detector_both_ways(tmp_path):
    with_worker = _plant(tmp_path / "a", {"a.js": "navigator.serviceWorker.register('/sw.js')"})
    without = _plant(tmp_path / "b", {"a.js": "fetch('/api/hub')"})
    assert spa.service_worker_registrations_in_bundle(with_worker) == ["a.js"]
    assert spa.service_worker_registrations_in_bundle(without) == []


def test_blocker_probe_is_unresolved_without_a_bundle_and_reads_the_phrase(tmp_path, monkeypatch):
    """The `#635`/`#638` registry probe: exit 1 while no bundle exists (so the entries stay
    unresolved and the gate stays quiet), exit 0 only when a bundle carries the phrase."""
    root = _plant(tmp_path / "bundle", {"index.html": "<html></html>",
                                        "assets/a.js": 'x="Check that the console service is running"'})
    monkeypatch.setattr(spa, "BUNDLE_DIR", tmp_path / "absent")
    monkeypatch.setattr(spa, "BUNDLE_INDEX", tmp_path / "absent" / "index.html")
    assert spa._probe_main(["contains", spa.RECOVERY_TEXT]) == 1
    monkeypatch.setattr(spa, "BUNDLE_DIR", root)
    monkeypatch.setattr(spa, "BUNDLE_INDEX", root / "index.html")
    assert spa._probe_main(["contains", spa.RECOVERY_TEXT]) == 0
    assert spa._probe_main(["contains", "does not operate the system"]) == 1
