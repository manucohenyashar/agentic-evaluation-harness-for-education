"""Issue #639 — the SPA in a real browser (E6): the hub, the seven lifecycle screens, the design
tokens and accessibility, the confirmations, degradation, and the CT-UI clause suites.

Operator test plan §5.6 (`TC-UI-02` … `TC-UI-05`, `TC-UI-07`, `PERF-19`), §6.11 (`TC-UI-C01` …
`TC-UI-C05`, runtime halves) and §5.0 (`TC-CONSOLE-40`/`41` re-pointed at the React app). Rung 3:
the real console server (`serve_console`) over a seeded real store, a Chromium-family browser
through Playwright, loopback only.

**Written ahead of implementation: yes.** The SPA does not exist; every case here is red until its
story lands, and the `writtenahead` marker on each is keyed in `WRITTEN_AHEAD_BLOCKERS`:

* **#634** (the foundation: bundle, tokens, hub) — `TC-UI-02`, `TC-UI-C01`, the re-pointed
  `TC-CONSOLE-40`/`41`;
* **#635** (the lifecycle screens, confirmations, degradation) — `TC-UI-03` (with ADV-15's SPA
  arm), `TC-UI-04` (it needs three screens), `TC-UI-05`, `TC-UI-07`, `TC-UI-C02` … `C05`, `PERF-19`.

Every case calls `_require_bundle()` first, so a red case fails in milliseconds with
`NotImplementedYet` naming #634 — never a navigation timeout that reads like a broken server.

**The DOM contract** these cases read is declared, with its reasons, in `tests/support/spa.py`:
hub cards are links named for FR-UI-02's destinations; a loaded screen's `main` carries one
level-1 heading; confirmations are dialogs. Rename there, not here.

**Markers.** `browser` (E6) and `integration`: the fast tier excludes `integration`, which keeps a
machine without E6 — or a red case — out of the Stop-hook gate (TS-49's rule).

**`TC-CONSOLE-42`** is the English/LTR declared limitation (test plan §2.3 Q-11, `TS-49`'s
docstring); operator plan §5.0 groups it with 40/41 as "re-pointed", but nothing about the
limitation changes with the SPA and nothing is asserted for it. The service-worker arm §5.0 adds
("no registration anywhere in the bundle") lives under `TC-CONSOLE-40` here and statically in
`tests/artifact/test_spa_bundle_gate.py`.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest

from tests.support import spa
from tests.support.console_security_vocabulary import (
    editable_band_controls,
    numeric_score_entry_fields,
)
from tests.support.impl import require_path

pytestmark = [pytest.mark.browser, pytest.mark.integration]

#: Student text no page would render by accident, planted in the narrative the results / student
#: screens read (the TS-49 sentinel, a different value so a cross-suite leak is attributable).
SENTINEL_TEXT = "Ngozi-Sentinel-8842 argued that evaporation outpaces rainfall in July"


def _require_bundle() -> None:
    require_path(spa.BUNDLE_INDEX, "the committed SPA bundle (FR-UI-01)", issue="#634")


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)


@dataclass
class Served:
    data_dir: Path
    store: Any
    server: Any
    origin: str
    world: Any
    run_status: str
    engine: str
    setup_package_id: str | None = None


def _plant_sentinel(store: Any, world: Any) -> None:
    student = world.submissions[0]
    # Disclosed M-SYNTH stand-in, as in TS-49: the narrative row a student / results view reads.
    with store.cohort(world.cohort_id).transaction() as tx:
        tx.execute(
            "INSERT INTO narrative (narrative_id, submission_id, run_id, level, question_id, "
            "text, score_claim_flag) VALUES (:n, :s, :r, 'l1_question', 'Q1', :t, 0)",
            n=f"nar-{student}-Q1", s=student, r=world.run_id, t=SENTINEL_TEXT,
        )


@contextmanager
def served(tmp_data_dir: Path, *, setup: str | None = None) -> Iterator[Served]:
    """A real store with a scored, unfinalized run (two submissions, the sentinel narrative),
    optionally beside an `M-SETUP` draft — `setup="blocked"` stops before the inventory is
    confirmed (gate 1 of 2 blocking), `setup="ready"` confirms it and keys every deterministic
    criterion (both gates satisfied, publishable) — served for real on loopback."""
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.console import serve_console
    from tests.support.conf_builders import edge_cfg
    from tests.support.console_world import rows, seed_scored_run
    from tests.support.setup_harness import ingest_document, stage_chain

    _require_bundle()
    chain = stage_chain(tmp_data_dir)
    store = chain.store
    setup_package_id = None
    if setup is not None:
        assessment = ingest_document(store)
        proposal = chain.service.propose_inventory(assessment)
        if setup == "ready":
            chain.service.confirm_inventory(proposal.proposal_id)
            chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
        setup_package_id = chain.package_id
    world = seed_scored_run(store, submissions=2)
    _plant_sentinel(store, world)
    (status,) = [r["status"] for r in rows(
        store.cohort(world.cohort_id), "SELECT status FROM run WHERE run_id = :r", r=world.run_id)]
    resolved = resolve_run_config(edge_cfg(), CohortRef(cohort_id=world.cohort_id,
                                                        consent_class="synthetic"))
    engine = "off" if resolved.decision_engine is None else "jev"
    server = serve_console(store=store, run_id=world.run_id)
    host, port = server.socket.getsockname()[:2]
    try:
        yield Served(tmp_data_dir, store, server, f"http://{host}:{port}", world, str(status),
                     engine, setup_package_id)
    finally:
        server.terminate()
        store.close()


def _health(page: Any, log: spa.SpaLog, where: str) -> list[str]:
    """CT-UI-04's floor, checked after every step: no uncaught error, no unhandled rejection, no
    raw stack trace in what the teacher sees."""
    problems = [f"{where}: uncaught page error {e!r}" for e in log.page_errors]
    problems += [f"{where}: unhandled Promise rejection {r!r}" for r in spa.rejections(page)]
    try:
        text = page.locator("body").inner_text()
    except Exception as error:  # a page without a body is itself the failure
        return problems + [f"{where}: no body to read ({error})"]
    problems += [f"{where}: a raw error reached the page ({p})" for p in spa.raw_errors_in(text)]
    log.page_errors.clear()
    return problems


def _screen_problems(page: Any, log: spa.SpaLog, destination: str) -> tuple[str, list[str]]:
    try:
        heading = spa.go_to(page, log.origin, destination)
    except Exception as error:
        return "", [f"{destination}: one click on its hub card did not load a screen with a "
                    f"level-1 heading in `main` ({str(error).splitlines()[0]})"]
    return heading, _health(page, log, destination)


# --- TC-UI-02 — the hub ---------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ui_02_the_hub_shows_every_destination_with_live_state_and_no_dead_link(tmp_data_dir):
    """`TC-UI-02` / FR-UI-02 (P0) — the hub renders one card per destination (nine), the cards
    show live state read from the store (the package version, the last run's status, the engine
    in use), every card loads its screen in one click, and no link on the hub is dead.

    Live, not static: the three facts are the seeded store's own values, the hub must have
    fetched them through `/api/`, and each is checked against the store, never the console."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        response = spa.open_hub(page, s.origin)
        problems = []
        if response is None or response.status != 200:
            problems.append(f"GET / answered {getattr(response, 'status', None)}, not the hub")
        for destination in spa.HUB_DESTINATIONS:
            n = spa.hub_card(page, destination).count()
            if n != 1:
                problems.append(f"the hub has {n} card link(s) for {destination!r} "
                                f"({spa.HUB_DESTINATIONS[destination].pattern}); FR-UI-02 wants one")
        text = spa.main_text(page)
        if s.world.package_version_id not in text:
            problems.append(f"the hub does not show the current package version "
                            f"{s.world.package_version_id!r}")
        if not re.search(rf"\b{re.escape(s.run_status)}\b", text, re.I):
            problems.append(f"the hub does not show the last run's status {s.run_status!r}")
        engine_cards = [d for d in spa.HUB_DESTINATIONS
                        if spa.hub_card(page, d).count()
                        and re.search(r"engine", spa.hub_card(page, d).first.inner_text(), re.I)
                        and re.search(rf"\b{s.engine}\b", spa.hub_card(page, d).first.inner_text(), re.I)]
        if not engine_cards:
            problems.append(f"no hub card names the engine in use ({s.engine!r}) beside the word "
                            f"'engine'")
        if not log.api_requests():
            problems.append("the hub made no /api/ request: its state cannot be live")
        problems += _health(page, log, "hub")

        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        for href in hrefs:
            if not href.startswith(s.origin):
                problems.append(f"the hub links off-origin: {href}")
        for destination in spa.HUB_DESTINATIONS:
            _, found = _screen_problems(page, log, destination)
            problems += found
        for href in sorted(set(h for h in hrefs if h.startswith(s.origin))):
            reply = page.goto(href, wait_until="networkidle")
            try:
                spa.wait_for_screen(page)
            except Exception:
                problems.append(f"dead link on the hub: {href} (status "
                                f"{getattr(reply, 'status', None)}, no screen heading)")
        _fail_with(problems)


# --- TC-UI-03 — the seven lifecycle screens over real store data ---------------------------------


@pytest.mark.writtenahead
def test_tc_ui_03_the_seven_lifecycle_screens_render_the_seeded_store(tmp_data_dir):
    """`TC-UI-03` / FR-UI-03 (P0) — walk package setup, class setup, papers, run start, monitor,
    review and results against a seeded store. Each shows the store's own data (ids read back from
    the seeding, never from the console); package setup over a draft whose inventory is not
    confirmed shows its blocking gate as blocking — the publish action is not offered enabled."""
    with served(tmp_data_dir, setup="blocked") as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        w = s.world
        refs = [f"ref-{sub}" for sub in w.submissions]
        expected: dict[str, list[str]] = {
            "package": [s.setup_package_id or "", w.package_version_id],
            "class": [w.cohort_id, *refs],
            "papers": [w.cohort_id, *refs],
            "run_start": [w.cohort_id, w.package_version_id],
            "monitor": [w.run_id, s.run_status],
            "review": [w.run_id],
            "results": refs,
        }
        problems = []
        for destination in spa.LIFECYCLE_SCREENS:
            heading, found = _screen_problems(page, log, destination)
            problems += found
            if not heading:
                continue
            text = spa.main_text(page)
            if spa.RECOVERY_TEXT in text.lower():
                problems.append(f"{destination}: shows the unreachable-API recovery message over a "
                                f"running server")
            for value in expected[destination]:
                if value and value.lower() not in text.lower():
                    problems.append(f"{destination} ({heading!r}) does not show the store's "
                                    f"{value!r}")
            if destination == "package":
                if not re.search(r"block", text, re.I):
                    problems.append("package setup: the unconfirmed inventory's gate is not "
                                    "rendered as blocking")
                publish = page.locator("main").get_by_role("button", name=re.compile("publish", re.I))
                for i in range(publish.count()):
                    if publish.nth(i).is_enabled():
                        problems.append("package setup: publish is enabled while gate 1 of 2 "
                                        "(the confirmed inventory) blocks")
            if destination == "papers" and not page.locator("main input[type=file]").count():
                problems.append("papers: no per-student upload control")
            if destination == "run_start" and not page.locator("main").get_by_role(
                    "button", name=re.compile(r"start", re.I)).count():
                problems.append("run start: no start control")
            if destination == "results":
                for ref in refs:
                    row = page.locator("main").locator("tr, li, article").filter(has_text=ref)
                    if not row.count() or not re.search(r"\d", row.first.inner_text()):
                        problems.append(f"results: no row for {ref} carrying its grade")
        _fail_with(problems)


@pytest.fixture(scope="module")
def jev_world(tmp_path_factory):
    """ADV-15's engine-on world (TS-129's `jev_synth`): a composed overnight run whose verdicts
    include decision-seat cells with their own confidences."""
    from tests.support import pipe_world

    root = tmp_path_factory.mktemp("ui03adv15") / "w"
    mp = pytest.MonkeyPatch()
    world = pipe_world.jev_synth_replay_world(root, monkeypatch=mp)
    try:
        world.build_run()
        world.start_run()
        pipe_world.drive_composed(world)
    finally:
        mp.undo()
    yield world, root
    world.store.close()


@pytest.mark.writtenahead
def test_tc_ui_03_adv_15_the_spa_blind_sample_shows_no_decision_band_or_confidence(request):
    """`TC-UI-03`'s review/blind arm — ADV-15 re-run against the SPA (operator plan §5.0): over an
    engine-on run, the blind-sample screen carries no decision band, no decision confidence and no
    engine marker, and pre-selects no band (FR-CONSOLE-16/19/20 unchanged)."""
    _require_bundle()  # first: the composed engine-on run is not built for a case that is red
    from aeh.console import serve_console

    world, root = request.getfixturevalue("jev_world")
    confidences = {f"{float(r[0]):g}" for r in world.handle.query(
        "SELECT DISTINCT self_confidence FROM verdict WHERE scoring_engine = 'decision'")}
    assert confidences, "fixture: the engine-on run produced no decision verdict"
    seats = {str(r[0]) for r in world.handle.query(
        "SELECT DISTINCT u.submission_id FROM verdict v JOIN work_unit u ON u.work_id = v.work_id "
        "WHERE v.scoring_engine = 'decision'")}
    seat_refs = {str(r["student_ref"]) for r in world.handle.query(
        "SELECT submission_id, student_ref FROM submission") if str(r["submission_id"]) in seats}
    server = serve_console(store=world.store, run_id=world.run_id)
    host, port = server.socket.getsockname()[:2]
    origin = f"http://{host}:{port}"
    try:
        with spa.spa_page(origin) as (page, log):
            problems = []
            bodies: list[str] = []

            def keep(response: Any) -> None:
                if response.url.startswith(origin + "/api/"):
                    try:
                        bodies.append(response.text())
                    except Exception:
                        pass

            page.on("response", keep)
            _, found = _screen_problems(page, log, "review")
            problems += found
            blind = page.locator("main").get_by_role("link", name=re.compile("blind", re.I)).or_(
                page.locator("main").get_by_role("button", name=re.compile("blind", re.I)))
            if not blind.count():
                _fail_with(problems + ["review: no way into the blind sample"])
            bodies.clear()
            blind.first.click()
            heading = spa.wait_for_screen(page)
            text = spa.main_text(page)
            html = page.content()
            if not text.replace(heading, "").strip():
                problems.append("the blind sample rendered nothing beyond its heading")
            shown = " ".join([text, *bodies])
            if not any(x in shown for x in seats | seat_refs):
                problems.append("the blind sample drew no decision-seat cell (ADV-15's anchor: "
                                "without one, every 'carries no X' check below is vacuous)")
            api_keys = set(re.findall(r'"([a-z_]+)"\s*:', " ".join(bodies)))
            leaked = api_keys & {"band", "system_band", "proposed_band", "decision_band",
                                 "self_confidence", "confidence", "scoring_engine"}
            if leaked:
                problems.append(f"the blind screen's API data carries system output: "
                                f"{sorted(leaked)}")
            for token in ("scoring_engine", "decision engine", "openrouter-jev", "self_confidence",
                          "confidence"):
                if token in text.lower() or token in html.lower():
                    problems.append(f"the blind sample carries {token!r}")
            for value in confidences:
                if value in shown or f"{float(value) * 100:g}%" in shown:
                    problems.append(f"the blind sample shows a decision confidence {value}")
            checked = page.locator("main input:checked, main option:checked[value]:not([value=''])")
            if checked.count():
                problems.append("the blind sample pre-selects a band")
            problems += _health(page, log, "blind sample")
            _fail_with(problems)
    finally:
        server.terminate()


# --- TC-UI-04 — tokens, focus, contrast, fonts ------------------------------------------------------

_STYLE_PROBE = """(tokens) => {
  const probe = document.createElement('div');
  document.body.appendChild(probe);
  const norm = (prop, value) => { probe.style.cssText = ''; probe.style[prop] = value;
                                   return getComputedStyle(probe)[prop]; };
  const allowed = {
    color: new Set(Object.values(tokens.color).map(v => norm('color', v))),
    fontSize: new Set(Object.values(tokens.fontSize).map(v => norm('fontSize', v))),
    space: new Set(Object.values(tokens.space).map(v => norm('paddingTop', v))),
    radius: new Set(Object.values(tokens.radius).map(v => norm('borderTopLeftRadius', v))),
    shadow: new Set(Object.values(tokens.shadow).map(v => norm('boxShadow', v))),
  };
  probe.remove();
  const clear = new Set(['rgba(0, 0, 0, 0)', 'transparent']);
  const out = [];
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
                            return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden'; };
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el) || ['SCRIPT', 'STYLE', 'svg', 'path'].includes(el.tagName)) continue;
    const cs = getComputedStyle(el);
    const where = el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
                  (el.className && el.className.baseVal === undefined ? '.' + String(el.className).split(' ').join('.') : '');
    const check = (cat, prop, value, extra) => {
      if (!allowed[cat].has(value) && !(extra || []).includes(value) && !clear.has(value))
        out.push(`${where} ${prop}: ${value} is not a ${cat} token`);
    };
    check('color', 'color', cs.color);
    check('color', 'background-color', cs.backgroundColor);
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (parseFloat(cs['border' + side + 'Width']) > 0)
        check('color', 'border-' + side.toLowerCase() + '-color', cs['border' + side + 'Color']);
      check('space', 'padding-' + side.toLowerCase(), cs['padding' + side], ['0px']);
    }
    for (const gap of ['rowGap', 'columnGap']) check('space', gap, cs[gap], ['0px', 'normal']);
    check('fontSize', 'font-size', cs.fontSize);
    for (const corner of ['TopLeft', 'TopRight', 'BottomLeft', 'BottomRight'])
      check('radius', 'border-radius', cs['border' + corner + 'Radius'], ['0px']);
    check('shadow', 'box-shadow', cs.boxShadow, ['none']);
  }
  return out;
}"""

_CONTRAST_PROBE = """() => {
  const parse = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return [255,255,255,1];
                         const p = m[1].split(',').map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const blend = (top, bottom) => { const a = top[3];
    return [0,1,2].map(i => top[i] * a + bottom[i] * (1 - a)).concat([1]); };
  const background = (el) => { const layers = [];
    for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    let bg = [255,255,255,1]; for (const layer of layers.reverse()) bg = blend(layer, bg); return bg; };
  const lum = (c) => { const ch = c.slice(0,3).map(v => { v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]; };
  const out = []; let checked = 0;
  for (const el of document.body.querySelectorAll('*')) {
    const own = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
    const r = el.getBoundingClientRect();
    if (!own || r.width === 0 || r.height === 0 || getComputedStyle(el).visibility === 'hidden') continue;
    const bg = background(el); const fg = blend(parse(getComputedStyle(el).color), bg);
    const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    const ratio = (a + 0.05) / (b + 0.05); checked++;
    if (ratio < 4.5) out.push(`${el.tagName.toLowerCase()} "${el.textContent.trim().slice(0, 40)}": ${ratio.toFixed(2)}:1`);
  }
  return {out, checked};
}"""

_FOCUS_SNAPSHOT = """() => {
  const sel = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  const els = Array.from(document.querySelectorAll(sel)).filter(e => { const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0; });
  els.forEach((e, i) => e.setAttribute('data-aeh-focus-index', String(i)));
  const style = (e) => { const cs = getComputedStyle(e);
    return [cs.outlineStyle, cs.outlineWidth, cs.outlineColor, cs.boxShadow, cs.borderColor, cs.backgroundColor].join('|'); };
  return els.map(style);
}"""

_FOCUSED_STYLE = """() => { const e = document.activeElement;
  if (!e || !e.hasAttribute('data-aeh-focus-index')) return null;
  const cs = getComputedStyle(e);
  return [Number(e.getAttribute('data-aeh-focus-index')),
          [cs.outlineStyle, cs.outlineWidth, cs.outlineColor, cs.boxShadow, cs.borderColor, cs.backgroundColor].join('|'),
          cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0]; }"""


def _focus_problems(page: Any, where: str) -> list[str]:
    # Blur first: an element already focused would otherwise record its focus ring as baseline.
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    unfocused = page.evaluate(_FOCUS_SNAPSHOT)
    if not unfocused:
        return [f"{where}: no interactive element to focus"]
    seen: dict[int, bool] = {}
    for _ in range(len(unfocused) + 3):
        page.keyboard.press("Tab")
        state = page.evaluate(_FOCUSED_STYLE)
        if state is None:
            continue
        index, style, has_outline = state
        seen[index] = has_outline or style != unfocused[index]
    problems = [f"{where}: interactive element #{i} is never reached by Tab"
                for i in range(len(unfocused)) if i not in seen]
    problems += [f"{where}: interactive element #{i} shows no visible focus state"
                 for i, visible in seen.items() if not visible]
    return problems


@pytest.mark.writtenahead
def test_tc_ui_04_styles_resolve_to_tokens_focus_is_visible_contrast_is_aa_fonts_are_local(
    tmp_data_dir,
):
    """`TC-UI-04` / FR-UI-04, NFR-UI-02/03 (P1) — on the hub and three screens (package setup,
    review, results):

    * every visible element's color, background, border color, padding, gap, font size, radius
      and shadow resolves to a value of the token file's palette / spacing / type / radius /
      elevation scales (token values normalized by the browser itself, so `#1a1a1a` and
      `rgb(26, 26, 26)` compare equal) — no per-screen override;
    * every interactive element is reached by Tab and shows a visible focus state;
    * every text element's contrast against its composited background is ≥ 4.5:1 (AA, as the
      plan states it);
    * a self-hosted font is loaded and every font request is same-origin."""
    _require_bundle()
    require_path(spa.TOKENS_FILE, "the design-token file (NFR-UI-02)", issue="#634")
    tokens = spa.load_tokens()
    problems = [f"the token file declares no {c!r} scale" for c in spa.TOKEN_CATEGORIES
                if not tokens.get(c)]
    if problems:
        _fail_with(problems)
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        for where in ("hub", "package", "review", "results"):
            if where != "hub":
                _, found = _screen_problems(page, log, where)
                problems += found
            problems += [f"{where}: {v}" for v in page.evaluate(_STYLE_PROBE, tokens)[:25]]
            contrast = page.evaluate(_CONTRAST_PROBE)
            if not contrast["checked"]:
                problems.append(f"{where}: no text to measure contrast on")
            problems += [f"{where}: contrast below 4.5:1 — {v}" for v in contrast["out"][:25]]
            problems += _focus_problems(page, where)
        fonts = page.evaluate(
            "async () => { await document.fonts.ready; return Array.from(document.fonts)"
            ".filter(f => f.status === 'loaded').map(f => f.family); }")
        if not fonts:
            problems.append("no bundled font face is loaded: FR-UI-04 wants a self-hosted font")
        font_requests = [u for u in log.requests
                         if re.search(r"\.(woff2?|ttf|otf|eot)(\?|$)", u, re.I)]
        if fonts and not font_requests:
            problems.append("a font is loaded but no font file was requested from the console")
        problems += [f"a font was requested off-origin: {u}" for u in font_requests
                     if not u.startswith(s.origin)]
        _fail_with(problems)


# --- TC-UI-05 — confirmations ----------------------------------------------------------------------

#: (hub destination, the action button, what the confirmation must name, the tables whose change
#: IS the action). Read from the shipped writers: publish flips M-PKG's `package_version` lock,
#: run start writes `run_control` / the `run` row, finalize settles `submission_grade`. A write
#: only elsewhere is not "the row lands".
_ACTIONS = (
    ("package", re.compile(r"publish", re.I), re.compile(r"publish", re.I),
     {"package_version"}),
    ("run_start", re.compile(r"^\s*start", re.I), re.compile(r"start", re.I),
     {"run", "run_control"}),
    ("results", re.compile(r"finali[sz]e", re.I), re.compile(r"finali[sz]e", re.I),
     {"submission_grade"}),
)
_CANCEL = re.compile(r"cancel|back|no\b|keep|close|dismiss|^\s*[x×]\s*$", re.I)


def _dialog(page: Any) -> Any:
    return page.get_by_role("dialog").or_(page.get_by_role("alertdialog"))


@pytest.mark.writtenahead
def test_tc_ui_05_publish_start_and_finalize_are_no_ops_until_confirmed(tmp_data_dir):
    """`TC-UI-05` / FR-UI-05 (P1) — for publish (a setup-ready draft), run start (the seeded
    pending run) and finalize (its computed, unfinalized grades): the action opens a confirmation
    that names what it does; while it is open, and after it is cancelled, **no table in any tier
    changed** (counts and contents); confirming it writes. The all-tier digest is the oracle, not
    one table, so a write to an unexpected tier is caught too."""
    with served(tmp_data_dir, setup="ready") as s, spa.spa_page(s.origin) as (page, log):
        problems = []
        for destination, action, names, owned in _ACTIONS:
            _, found = _screen_problems(page, log, destination)
            problems += found
            buttons = page.locator("main").get_by_role("button", name=action)
            enabled = [buttons.nth(i) for i in range(buttons.count()) if buttons.nth(i).is_enabled()]
            if not enabled:
                problems.append(f"{destination}: no enabled {action.pattern!r} action over a world "
                                f"where it is possible")
                continue
            before = spa.store_digest(s.data_dir)
            enabled[0].click()
            dialog = _dialog(page)
            try:
                dialog.first.wait_for(state="visible")
            except Exception:
                after = spa.store_digest(s.data_dir)
                problems.append(f"{destination}: {action.pattern!r} opened no confirmation"
                                + (f" and wrote {spa.changed_tables(before, after)}" if before != after else ""))
                continue
            if not names.search(dialog.first.inner_text()):
                problems.append(f"{destination}: the confirmation does not name what it does "
                                f"({dialog.first.inner_text()[:120]!r})")
            page.wait_for_load_state("networkidle")
            if spa.store_digest(s.data_dir) != before:
                problems.append(f"{destination}: the store changed with the confirmation still "
                                f"open: {spa.changed_tables(before, spa.store_digest(s.data_dir))}")
            cancel = dialog.first.get_by_role("button", name=_CANCEL)
            if cancel.count():
                cancel.first.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_load_state("networkidle")
            if spa.store_digest(s.data_dir) != before:
                problems.append(f"{destination}: cancelling the confirmation wrote "
                                f"{spa.changed_tables(before, spa.store_digest(s.data_dir))}")
            enabled[0].click()
            dialog.first.wait_for(state="visible")
            # The confirming button is the one naming the action — never a header close/x.
            named = dialog.first.get_by_role("button", name=names)
            confirm = [named.nth(i) for i in range(named.count())
                       if not _CANCEL.search(named.nth(i).inner_text())]
            if not confirm:
                problems.append(f"{destination}: the confirmation has no button naming the action")
                continue
            confirm[0].click()
            deadline = time.monotonic() + spa.STEP_TIMEOUT_MS / 1000
            while spa.store_digest(s.data_dir) == before and time.monotonic() < deadline:
                page.wait_for_timeout(100)
            landed = spa.changed_tables(before, spa.store_digest(s.data_dir))
            if not landed:
                problems.append(f"{destination}: confirming wrote nothing — the row did not land")
            elif not any(table.split(":")[-1] in owned for table in landed):
                problems.append(f"{destination}: confirming wrote {landed}, none of the tables "
                                f"the action owns ({sorted(owned)})")
            problems += _health(page, log, f"{destination} after confirm")
        _fail_with(problems)


# --- TC-UI-07 — the server is gone ------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ui_07_with_the_server_stopped_every_destination_names_the_recovery(tmp_data_dir):
    """`TC-UI-07` / FR-UI-07 (P1) — load the hub, **stop the real server** (not an intercepted
    route: "unreachable" is the case), then follow each hub card. Each destination renders the
    named recovery message ("check that the console service is running"); none is blank, none
    shows a stack trace, and no unhandled rejection or uncaught error fires."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        problems = _health(page, log, "hub (server up)")
        s.server.terminate()
        for destination in spa.HUB_DESTINATIONS:
            if urlsplit_path(page.url) not in ("", "/"):
                page.go_back()
            card = spa.hub_card(page, destination)
            if not card.count():
                problems.append(f"{destination}: the hub card is gone once the server stopped")
                continue
            card.first.click()
            # Per destination, inside the screen itself: one global banner left over from the
            # hub would otherwise satisfy all nine, and a blank screen under it would pass.
            recovery = page.locator("main").get_by_text(
                re.compile(re.escape(spa.RECOVERY_TEXT), re.I))
            try:
                recovery.first.wait_for(state="visible")
            except Exception:
                body = page.locator("body").inner_text() if page.locator("body").count() else ""
                problems.append(f"{destination}: no recovery message in its screen with the "
                                f"server stopped (page text: {body.strip()[:120]!r})")
            else:
                if not spa.screen_heading(page).count():
                    problems.append(f"{destination}: the recovery message stands on a screen with "
                                    f"no heading — the teacher cannot tell which screen failed")
            problems += _health(page, log, destination)
        _fail_with(problems)


def urlsplit_path(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).path


# --- TC-UI-C01 — one origin -------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ui_c01_a_session_over_the_hub_and_every_destination_requests_one_origin(tmp_data_dir):
    """`TC-UI-C01` / CT-UI-01 (P0, runtime half; the static half is the bundle sweep) — every
    request the browser context issues while the hub and every destination load is to the
    console's own origin. Anchored: the log must hold the hub's navigation, its assets and at
    least one `/api/` call, so a session that recorded nothing cannot pass."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        for destination in spa.HUB_DESTINATIONS:
            try:
                spa.go_to(page, s.origin, destination)
            except Exception:
                pass  # TC-UI-02 owns reachability; this case owns the origin set
        problems = []
        own = [u for u in log.requests if u.startswith(s.origin)]
        if len(own) < 2 or not log.api_requests():
            problems.append(f"the session recorded {len(own)} own-origin request(s) and "
                            f"{len(log.api_requests())} API call(s): it is not observing the SPA")
        if log.foreign_requests():
            problems.append(f"requests to other origins: {log.foreign_requests()} (CT-UI-01)")
        _fail_with(problems)


# --- TC-UI-C02 — no authoritative client state -------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ui_c02_a_reload_shows_exactly_what_the_api_reports_and_writes_nothing(tmp_data_dir):
    """`TC-UI-C02` / CT-UI-02 (P1) — (1) a full reload of every destination writes nothing to any
    tier and leaves no browser storage behind; (2) after an out-of-band change the browser could
    not have seen (a third submission written straight into the cohort tier), reloading the class
    screen shows it — the screen's state is the API's, not a cache that survived the reload."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        problems = []
        before = spa.store_digest(s.data_dir)
        for destination in spa.HUB_DESTINATIONS:
            try:
                spa.go_to(page, s.origin, destination)
                page.reload(wait_until="networkidle")
                spa.wait_for_screen(page)
            except Exception as error:
                problems.append(f"{destination}: did not survive a reload "
                                f"({str(error).splitlines()[0]})")
            problems += _health(page, log, f"{destination} reloaded")
        if spa.store_digest(s.data_dir) != before:
            problems.append(f"reloading the screens wrote: {spa.changed_tables(before, spa.store_digest(s.data_dir))}")
        problems += spa.storage_problems(page)

        late = f"sub-{s.world.cohort_id}-late"
        try:
            spa.go_to(page, s.origin, "class")
        except Exception as error:
            _fail_with(problems + [f"class: unreachable ({error})"])
        if f"ref-{late}" in spa.main_text(page):
            problems.append("fixture: the late submission is visible before it was written")
        with s.store.cohort(s.world.cohort_id).transaction() as tx:
            tx.execute("INSERT INTO submission (submission_id, cohort_id, student_ref) "
                       "VALUES (:s, :c, :r)", s=late, c=s.world.cohort_id, r=f"ref-{late}")
        page.reload(wait_until="networkidle")
        spa.wait_for_screen(page)
        if f"ref-{late}" not in spa.main_text(page):
            problems.append("class: after a reload the screen does not show the submission the "
                            "store now holds — it is serving state that outlived the reload")
        _fail_with(problems)


# --- TC-UI-C03 — no student text in the browser ------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ui_c03_no_student_text_in_storage_urls_or_logs_and_no_service_worker(tmp_data_dir):
    """`TC-UI-C03` / CT-UI-03, FR-UI-08 (P0) — a session that **did** render the sentinel student
    text (anchored: some screen shows it) leaves nothing in localStorage, sessionStorage, Cache
    Storage, IndexedDB or cookies; registers no service worker; and the sentinel appears in no
    URL the browser requested and no console message the SPA logged."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        saw = False
        for destination in spa.HUB_DESTINATIONS:
            try:
                spa.go_to(page, s.origin, destination)
            except Exception:
                continue
            if SENTINEL_TEXT in spa.main_text(page):
                saw = True
            # A student's own detail, one click further, where results link to one.
            student = page.locator("main").get_by_role(
                "link", name=re.compile(re.escape(f"ref-{s.world.submissions[0]}")))
            if destination == "results" and student.count():
                student.first.click()
                spa.wait_for_screen(page)
                saw = saw or SENTINEL_TEXT in spa.main_text(page)
        problems = [] if saw else [
            "no screen rendered the sentinel student text, so 'no student text in storage' would "
            "be a statement about a session that never held any (results / student detail must "
            "show the narrative)"]
        problems += spa.storage_problems(page, SENTINEL_TEXT)
        fragments = ("Ngozi-Sentinel-8842", "evaporation outpaces rainfall")
        problems += [f"a requested URL carries student text: {u}" for u in log.requests
                     if any(f.replace(" ", "%20") in u or f.replace(" ", "+") in u or f in u
                            for f in fragments)]
        problems += [f"a console message carries student text: {t[:120]!r}" for _, t in log.console
                     if any(f in t for f in fragments)]
        _fail_with(problems)


# --- TC-UI-C04 — named, recoverable API errors -------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ui_c04_an_api_error_renders_a_named_recoverable_message_on_every_screen(tmp_data_dir):
    """`TC-UI-C04` / CT-UI-04 (P1) — every `/api/` call answers 500 (route interception: an API
    *error*, the server is up). The hub and each destination render a named message (`role=alert`
    or `role=status` with text) and a retry; never a stack trace, an uncaught error or an
    unhandled rejection. Recoverable: once the API answers again, the retry renders the screen."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        failing = {"on": True}

        def handler(route: Any) -> None:
            if failing["on"]:
                route.fulfill(status=500, content_type="application/json",
                              body='{"error": "induced by TC-UI-C04"}')
            else:
                route.continue_()

        page.route(f"{s.origin}/api/**", handler)
        w = s.world
        recovered_data = {"class": f"ref-{w.submissions[0]}", "papers": f"ref-{w.submissions[0]}",
                          "results": f"ref-{w.submissions[0]}", "monitor": w.run_id,
                          "run_start": w.cohort_id, "package": w.package_version_id}
        spa.open_hub(page, s.origin)
        problems = _health(page, log, "hub (API failing)")
        for destination in spa.HUB_DESTINATIONS:
            failing["on"] = True
            if urlsplit_path(page.url) not in ("", "/"):
                spa.open_hub(page, s.origin)
            card = spa.hub_card(page, destination)
            if not card.count():
                problems.append(f"{destination}: no hub card while the API fails")
                continue
            card.first.click()
            page.wait_for_load_state("networkidle")
            # `role=alert` only: a polling `role=status` region exists on a healthy screen too, and
            # would count as the "named message" whether or not the error was named.
            alert = page.locator("main").get_by_role("alert")
            named = [alert.nth(i).inner_text().strip() for i in range(alert.count())]
            if not any(named):
                problems.append(f"{destination}: the API error renders no named message")
            problems += _health(page, log, destination)
            retry = page.get_by_role("button", name=re.compile(r"retry|try again|reload", re.I))
            if not retry.count():
                problems.append(f"{destination}: the error offers no recovery action")
                continue
            failing["on"] = False
            retry.first.click()
            page.wait_for_load_state("networkidle")
            try:
                spa.wait_for_screen(page)
            except Exception:
                problems.append(f"{destination}: retry did not recover once the API answered")
                continue
            # Recovered means the error is gone AND the store's data is back — a screen that keeps
            # its heading beside the alert is the normal shape of NOT recovering.
            if page.locator("main").get_by_role("alert").count():
                problems.append(f"{destination}: the error message stays after a successful retry")
            if destination in recovered_data and recovered_data[destination] not in \
                    spa.main_text(page):
                problems.append(f"{destination}: after retry the screen does not show the store's "
                                f"{recovered_data[destination]!r}")
        _fail_with(problems)


# --- TC-UI-C05 — band-only editing -------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ui_c05_bands_are_editable_band_controls_and_no_screen_takes_a_numeric_score(
    tmp_data_dir,
):
    """`TC-UI-C05` / CT-UI-05 (P1) — on every destination's rendered DOM, no form control accepts
    a hand-typed numeric score (the vetted `numeric_score_entry_fields` detector, which leaves the
    review budget's minutes alone); and where a screen displays one of the package's bands as a
    value ("correct", "incorrect" as an element's whole text), it displays it as an editable band
    control (`editable_band_controls`). Stricter than CT-UI-05's "wherever editing is offered" by
    design: FR-CONSOLE-20 (invariant 16), which CT-UI-05 cites, says *no view shows a grade and
    cannot change it*. Anchored: at least one screen must display a band."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        problems, displayed = [], []
        for destination in spa.HUB_DESTINATIONS:
            try:
                spa.go_to(page, s.origin, destination)
            except Exception:
                continue
            html = page.content()
            problems += [f"{destination}: numeric score entry {f!r}"
                         for f in numeric_score_entry_fields(html)]
            # A band *display* is an element whose whole text is a band label — not the word
            # "correct" in a sentence, which a correct SPA may well print.
            band_display = page.locator("main").get_by_text(
                re.compile(r"^\s*(in)?correct\s*$", re.I), exact=False)
            if band_display.count():
                displayed.append(destination)
                if not editable_band_controls(html):
                    problems.append(f"{destination}: shows a band but offers no editable band "
                                    f"control")
        if not displayed:
            problems.append("no screen displayed a band, so 'bands are editable' was never tested "
                            "(results should show each student's band per criterion)")
        _fail_with(problems)


# --- PERF-19 ------------------------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_perf_19_hub_first_contentful_paint_under_2s_and_transitions_under_300ms(tmp_data_dir):
    """`PERF-19` / NFR-UI-01 (P2) — first contentful paint of the hub (the browser's own
    `first-contentful-paint` entry) under `HARNESS_UI_FCP_BUDGET_MS` (2000, NFR-UI-01's figure) and
    each hub-to-screen transition across the seven screens, click to heading visible, under
    `HARNESS_UI_TRANSITION_BUDGET_MS` (300). Assumption: the figures are the reference hardware's,
    measured not derived — on a slower box this fails openly; the knob is the visible override."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        fcp = page.evaluate(
            "() => { const e = performance.getEntriesByName('first-contentful-paint')[0];"
            " return e ? e.startTime : null; }")
        problems = []
        if fcp is None:
            problems.append("the hub recorded no first contentful paint")
        elif fcp >= spa.FCP_BUDGET_MS:
            problems.append(f"hub FCP {fcp:.0f} ms >= {spa.FCP_BUDGET_MS:.0f} ms (NFR-UI-01)")
        for destination in spa.LIFECYCLE_SCREENS:
            spa.open_hub(page, s.origin)
            card = spa.hub_card(page, destination)
            if not card.count():
                problems.append(f"{destination}: no hub card to time")
                continue
            start = time.perf_counter()
            card.first.click()
            try:
                spa.screen_heading(page).first.wait_for(state="visible")
            except Exception:
                problems.append(f"{destination}: the transition never completed")
                continue
            elapsed = (time.perf_counter() - start) * 1000
            if elapsed >= spa.TRANSITION_BUDGET_MS:
                problems.append(f"{destination}: transition {elapsed:.0f} ms >= "
                                f"{spa.TRANSITION_BUDGET_MS:.0f} ms (NFR-UI-01)")
        _fail_with(problems)


# --- TC-CONSOLE-40 / 41, re-pointed at the SPA --------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_40_spa_a_session_over_the_react_app_leaves_no_storage_or_worker(tmp_data_dir):
    """`TC-CONSOLE-40` re-pointed (operator plan §5.0; FR-CONSOLE-17, FR-UI-08) — the same oracle
    as TS-49's, over the React app: after the hub and every destination load, localStorage,
    sessionStorage, Cache Storage and IndexedDB on the console's origin are empty and no service
    worker is registered. The §5.0 SPA arm — no registration *anywhere in the bundle* — is checked
    here too (and statically in the bundle gate). Anchored: the hub rendered and called the API."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        for destination in spa.HUB_DESTINATIONS:
            try:
                spa.go_to(page, s.origin, destination)
            except Exception:
                pass
        problems = []
        if not log.api_requests():
            problems.append("the session made no /api/ call: it never exercised the SPA")
        problems += spa.storage_problems(page)
        problems += [f"the bundle can register a service worker: {f}"
                     for f in spa.service_worker_registrations_in_bundle(spa.BUNDLE_DIR)]
        _fail_with(problems)


@pytest.mark.writtenahead
def test_tc_console_41_spa_the_react_app_requests_nothing_from_another_origin(tmp_data_dir):
    """`TC-CONSOLE-41` / SEC-12 re-pointed (FR-CONSOLE-18, CT-UI-01) — the network log of a hub
    session plus every destination holds only the console's origin, fonts and assets included.
    Anchored on the hub's own navigation and an API call."""
    with served(tmp_data_dir) as s, spa.spa_page(s.origin) as (page, log):
        spa.open_hub(page, s.origin)
        for destination in spa.HUB_DESTINATIONS:
            try:
                spa.go_to(page, s.origin, destination)
            except Exception:
                pass
        problems = []
        if not any(u.rstrip("/") == s.origin for u in log.requests) or not log.api_requests():
            problems.append("the log holds no hub navigation or no API call: not recording the SPA")
        if log.foreign_requests():
            problems.append(f"the React app requested other origins: {log.foreign_requests()}")
        _fail_with(problems)
