"""CT-AUTHOR-09, CT-AUTHOR-10 and CT-AUTHOR-11 — fail fast, never raise after extraction, two artifacts and no store (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C09 | CT-AUTHOR-09 error | `AuthoringInputError` (unreadable document, or zero text with `HARNESS_AUTHOR_TRANSCRIBE=off`) and `ConfigurationError` (empty chain) raise BEFORE any provider call, write nothing, and name the failing document |
| TC-AUTHOR-C10 | CT-AUTHOR-10 error | once at least one document yields text, `draft()` never raises — every downstream failure becomes an unresolved item, a placeholder and a populated result (injected here as a provider that fails every call) |
| TC-AUTHOR-C11 | CT-AUTHOR-11 state | `draft()` writes exactly two files into the output directory, touches no store tier and mints no version — checked at runtime (no new file under a pointed-at data dir) and in the source (no `aeh.store`/`sqlite3` import anywhere in `aeh.author`) |

Rung 1, guards first (#689 then #686). AF-10 is the scan-style fixture with no text layer, so
the transcribe-`off` limb has a real page to fail on; the garbage PDF is written in the test's
own tmp so no corpus artifact depends on a broken file.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aeh.conf import ConfigurationError
from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    CountingProvider,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    author_input_error = require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    af10 = require_path(af("AF-10"), "the AF-10 authored fixture", issue=CORPUS_ISSUE)
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, author_input_error, af10, corpus, recordings


# --- TC-AUTHOR-C09 ----------------------------------------------------------------------------


def test_tc_author_c09_input_errors_raise_before_any_call_and_write_nothing(
        tmp_path, make_fixture_provider, monkeypatch):
    """Three fail-fast conditions, each with a zero call count and an empty output directory,
    each naming what failed: an unreadable document, zero extractable text with transcribe
    `off`, and an empty chain."""
    author, input_error, af10, corpus, recordings = _guards(make_fixture_provider)
    provider = CountingProvider(make_fixture_provider(recordings))
    chain = chain_from_config()

    garbage = tmp_path / "garbage.pdf"
    garbage.write_bytes(b"this is not a pdf, whatever the extension says\n")

    # (a) No document is readable.
    out_a = tmp_path / "out-a"
    with pytest.raises(input_error) as exc:
        make_service(author, chain, provider).draft(
            documents=[garbage], output_dir=out_a)
    assert "garbage.pdf" in str(exc.value), "the error must name the failing document"
    assert provider.calls == [], "a model call was made before the inputs were validated"
    assert not out_a.exists() or not list(out_a.iterdir()), (
        "an input error left artifacts behind")

    # (b) A scan-style page with the transcriber refused: same fail-fast, same naming.
    monkeypatch.setenv("HARNESS_AUTHOR_TRANSCRIBE", "off")
    out_b = tmp_path / "out-b"
    with pytest.raises(input_error) as exc:
        make_service(author, chain, provider).draft(
            documents=sorted(af10.glob("*.pdf")), output_dir=out_b)
    assert any(p.name in str(exc.value) for p in af10.glob("*.pdf")), (
        f"the error must name the failing document, got: {exc.value}")
    assert provider.calls == []
    assert not out_b.exists() or not list(out_b.iterdir())

    # (c) An empty chain is a ConfigurationError from M-CONF, also before any call — with a
    # readable document, so the chain check is the fail-fast that fires, not an input error
    # racing it (the design does not order the two checks, so the case must not make them
    # compete).
    out_c = tmp_path / "out-c"
    with pytest.raises(ConfigurationError):
        make_service(author, [], provider).draft(
            documents=sorted(corpus.glob("*.pdf")), output_dir=out_c)
    assert provider.calls == []
    assert not out_c.exists() or not list(out_c.iterdir())


# --- TC-AUTHOR-C10 ----------------------------------------------------------------------------


def test_tc_author_c10_after_extraction_draft_never_raises(
        tmp_path, network_guard, make_fixture_provider):
    """Every model call fails, hard — and `draft()` still returns a populated result with the
    report written and the failures absorbed into unresolved items and placeholders."""
    author, _input_error, _af10, corpus, recordings = _guards(make_fixture_provider)
    from aeh.prov.errors import ProviderUnavailableError

    real = make_fixture_provider(recordings)

    class _EveryCallFails(CountingProvider):
        """Failure injection at the model boundary (§4.2's one permitted double)."""

        def complete(self, prompt, model_ref, params):  # noqa: ANN001
            self.calls.append((prompt, model_ref, params))
            raise ProviderUnavailableError("injected: every model call fails")

    provider = _EveryCallFails(real)
    result = make_service(author, chain_from_config(), provider).draft(
        documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path / "out")

    assert provider.calls, "the failure injection never reached the module"
    assert isinstance(result, author.DraftResult)
    assert result.outcomes, "the populated result carries no per-stage trace"
    assert result.placeholders + result.unresolved >= 1, (
        "every failing step must surface as a placeholder or an unresolved item")
    assert result.report_path.exists(), (
        "the report is written even when every reasoning step failed (FR-AUTHOR-12)")
    network_guard.assert_no_network()


# --- TC-AUTHOR-C11 ----------------------------------------------------------------------------


def test_tc_author_c11_exactly_two_artifacts_and_no_store_anywhere(
        tmp_path, tmp_data_dir, make_fixture_provider, monkeypatch):
    """The output directory holds exactly the draft and the report; a pointed-at data dir
    gains no file; and no `aeh.author` source imports a store client."""
    author, _input_error, _af10, corpus, recordings = _guards(make_fixture_provider)
    provider = CountingProvider(make_fixture_provider(recordings))
    service = make_service(author, chain_from_config(), provider)

    monkeypatch.setenv("HARNESS_DATA_DIR", str(tmp_data_dir))
    before = {str(p.relative_to(tmp_data_dir)) for p in tmp_data_dir.rglob("*")}
    result = service.draft(documents=sorted(corpus.glob("*.pdf")),
                           output_dir=tmp_path / "out")
    after = {str(p.relative_to(tmp_data_dir)) for p in tmp_data_dir.rglob("*")}

    assert after == before, f"the draft touched the store tier: {after - before}"
    assert {p.name for p in (tmp_path / "out").iterdir()} == {
        result.draft_path.name, result.report_path.name}

    # And the source agrees: no `aeh.author` file imports a store client, so no tier can be
    # written no matter how a caller points the environment (ADR-43).
    init = Path(author.__file__)
    package_dir = init.parent if init.name == "__init__.py" else None
    sources = (sorted(package_dir.rglob("*.py")) if package_dir else [init])
    assert sources, "no aeh.author source found to sweep"
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "sqlite3" and not alias.name.startswith("aeh.store"), (
                        f"{source.name} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 0:
                    assert module != "sqlite3" and not module.startswith("aeh.store"), (
                        f"{source.name} imports {module}")
                    if module == "aeh":
                        assert not any(a.name == "store" for a in node.names), (
                            f"{source.name} imports store from aeh")
                elif node.level >= 1:
                    # A relative import inside aeh.author: `store` would resolve to aeh.store
                    # only from aeh.author's own directory — refuse it anyway and let a real
                    # failure teach the layout.
                    assert module != "store", f"{source.name} relative-imports {module!r}"