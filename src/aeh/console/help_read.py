"""The manuals page's reads and the grounded ask, as the JSON API answers them (M-HELP).

Pure functions of the packaged manuals — a read creates and touches no stored byte — plus the
one piece the ask needs beyond them: the model the exchange is answered with, resolved from the
console's effective configuration by the FR-CONF-30 rule (`resolve_qa_model`), and built through
`M-PROV` (`provider_for`), the only egress point.

`resolve_help_model` deliberately does **not** invent a resolution rule of its own: it takes the
panel the configuration declares (the config file's, already `ModelRef`s through
`parse_config_document`) and hands it to `resolve_qa_model`. A console whose configuration
declares no panel has no model the rule can fall back to — on `edge-local` the assistant is the
first grading judge, and without a declared panel there is no judge to name — so the ask refuses
with a sentence naming the missing key rather than guessing a transport (`CT-HELP-03`: the
endpoint never invents, it answers from the manuals or says it cannot).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aeh.conf import ConfigurationError, ModelRef
from aeh.conf.qa_model import QA_KNOB_PROFILES, QA_MODEL_KEY, resolve_qa_model
from aeh.help import HelpAssistant, load_manuals, manuals_manifest
from aeh.prov import provider_for

#: The path parameter the manual read template names (`MANUAL_ROUTE`).
MANUAL_ID_PARAM = "manual_id"


def manuals_payload() -> dict[str, Any]:
    """The manuals page's listing: every packaged manual, in page order."""
    return {
        "manuals": [
            {"manual_id": record.manual_id, "title": record.title}
            for record in manuals_manifest()
        ],
    }


def manual_payload(manual_id: str) -> dict[str, Any] | None:
    """One manual as the page renders it, or `None` when no packaged manual carries the id —
    the handler answers the unknown id with a 404, never a guessed manual."""
    for manual in load_manuals():
        if manual.manual_id != manual_id:
            continue
        return {
            "manual_id": manual.manual_id,
            "title": manual.title,
            "toc": [{"anchor": entry.anchor, "heading": entry.heading} for entry in manual.toc],
            "sections": [
                {"anchor": section.anchor, "heading": section.heading, "text": section.text}
                for section in manual.sections
            ],
        }
    return None


def resolve_help_model(cfg: Mapping[str, Any]) -> ModelRef:
    """The ask endpoint's model, resolved by the FR-CONF-30 rule from the effective
    configuration.

    With a declared panel the rule is `resolve_qa_model`'s verbatim. Without one, only the
    `HARNESS_QA_MODEL` knob can name a model, and only on the cloud profiles; everywhere else
    the configuration names no model at all, and the refusal says so at the ask.
    """
    profile = str(cfg.get("HARNESS_PROFILE") or "")
    panel = tuple(cfg.get("panel") or ())
    if panel:
        return resolve_qa_model(cfg, profile, panel)
    knob = cfg.get(QA_MODEL_KEY)
    if profile in QA_KNOB_PROFILES and knob is not None and not isinstance(knob, str):
        # Present but not a string: delegate anyway. `resolve_qa_model` raises its own
        # precise refusal before it would read the panel ("must be an OpenRouter build
        # string, got int"), which is more truthful than this helper's unset wording.
        return resolve_qa_model(cfg, profile, panel)
    if profile in QA_KNOB_PROFILES and isinstance(knob, str) and knob.strip():
        # The knob arm of `resolve_qa_model` never falls back to `panel[0]`, so the empty
        # panel is never read; this is its rule, not a second one.
        return resolve_qa_model(cfg, profile, panel)
    raise ConfigurationError(
        f"the help assistant has no model to ask: the effective configuration declares no "
        f"panel and {QA_MODEL_KEY} is unset (FR-CONF-30). Declare the models in the config "
        "file, or set the knob on a cloud profile."
    )


def build_help_assistant(store: Any, cfg: Mapping[str, Any]) -> HelpAssistant:
    """The console's manuals assistant: the resolved QA model, through `M-PROV` for its
    transport (`FR-HELP-05`), writing its Q&A log on the console's own stores."""
    model_ref = resolve_help_model(cfg)
    return HelpAssistant(store=store, provider=provider_for(model_ref), model_ref=model_ref)


def ask_payload(assistant: Any, question: str) -> dict[str, Any]:
    """One ask, answered and logged: the prose answer and the sections it was grounded on."""
    answer = assistant.ask(question)
    return {
        "answer": answer.answer,
        "citations": [
            {"manual_id": citation.manual_id, "anchor": citation.anchor}
            for citation in answer.citations
        ],
    }


__all__ = [
    "MANUAL_ID_PARAM",
    "ask_payload",
    "build_help_assistant",
    "manual_payload",
    "manuals_payload",
    "resolve_help_model",
]
