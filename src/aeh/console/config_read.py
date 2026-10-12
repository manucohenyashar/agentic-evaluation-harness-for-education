"""The configuration projection (`FR-CONF-35`, FR-CONSOLE-60, #755): the `config` read's
view model for the SPA's settings form.

Every setting projects with its teacher label, its current value from the **resolved**
configuration (the environment's decisions included — the file is never read here, and
never served: `CT-CONF-19`), a type tag the form renders from, and an `editable` flag that
is true only inside `FR-CONF-34`'s teacher-editable subset — the model per action role,
the spending ceiling, and the second-opinion checker's choice. Everything else projects
read-only, which is the truth: the write path (`update configuration`, #756) refuses them.

Two hard rules this module exists to keep:

* **No key name from the configuration file ever appears in the projection.** Each row
  carries a stable `field` slug and a teacher label; the key the value actually lives
  under is the write path's business, not the teacher's (`CT-CONF-19` extended to the
  projection, `CT-CONSOLE-31`'s scan).
* **A secret projects as a configured boolean, never a value** (`CT-CONF-19`): the model
  service key's row says whether one is set, and nothing else.

When the M-CONF story lands its own projection module (#756), this read should delegate to
it; the payload shape below is what the SPA builds against, and the swap must keep it.
"""

from __future__ import annotations

import os
from typing import Any

from aeh.conf import effective_config
from aeh.conf.decision_engine import DECISION_ENGINES
from aeh.prov import OPENROUTER_API_KEY_ENV


#: The declared rows: `(field slug, teacher label, config key, type tag, editable)`. The
#: key is looked up only to read the value — it never travels. Editability is `FR-CONF-34`'s
#: subset, verbatim; the second-opinion checker's choice is editable, its technical
#: thresholds are not (they are the decision engine's own calibration, not a teacher's).
_DECLARED_ROWS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("operating-profile", "Operating profile", "HARNESS_PROFILE", "text", False),
    ("hardware-profile", "Hardware profile", "HARNESS_HARDWARE_PROFILE", "text", False),
    ("spending-ceiling", "Spending ceiling", "HARNESS_COST_CEILING", "number", True),
    ("currency", "Currency", "HARNESS_COST_CURRENCY", "text", False),
    ("parallel-grading", "How many papers are graded at once", "HARNESS_CONCURRENCY",
     "number", False),
    ("allow-real-model-calls", "Allow real model calls", "HARNESS_ALLOW_REMOTE_REAL_WORK",
     "boolean", False),
    ("second-opinion-checker", "Second-opinion checker", "HARNESS_DECISION_ENGINE",
     "choice", True),
    ("second-opinion-service", "Second-opinion service", "HARNESS_DECISION_PROVIDER",
     "text", False),
    ("second-opinion-build", "Second-opinion model build", "HARNESS_JEV_BUILD", "text", False),
    ("second-opinion-model-size", "Second-opinion model size", "HARNESS_JEV_QUANTIZATION",
     "text", False),
    ("second-opinion-certainty-threshold",
     "Second-opinion certainty threshold", "HARNESS_JEV_CONFIDENCE_THRESHOLD", "number", False),
    ("second-opinion-citing-threshold",
     "Second-opinion citing threshold", "HARNESS_JEV_CITE_THRESHOLD", "number", False),
    ("second-opinion-question-cap",
     "Second-opinion question cap", "HARNESS_JEV_MAX_CITATION_QUESTIONS", "number", False),
    ("second-opinion-length-ratio",
     "Second-opinion length ratio", "HARNESS_JEV_TOKEN_BYTES_RATIO", "number", False),
    ("helper-assistant-model", "Helper assistant model", "HARNESS_QA_MODEL", "text", False),
    ("console-address", "Console address", "CONSOLE_BIND", "text", False),
    ("console-port", "Console port", "CONSOLE_PORT", "number", False),
)


def _ref_value(ref: Any) -> dict[str, Any]:
    """One model reference as the form renders it, credential-free by construction
    (`ModelRef` carries no credential). Accepts a `ModelRef` or the dict form."""
    if isinstance(ref, dict):
        return {
            "provider": str(ref.get("provider") or ""),
            "build": str(ref.get("build_id") or ""),
            "quantization": ref.get("quantization"),
        }
    return {
        "provider": str(getattr(ref, "provider", "") or ""),
        "build": str(getattr(ref, "build_id", "") or ""),
        "quantization": getattr(ref, "quantization", None),
    }


def _model_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    """The model-per-action-role rows (FR-CONF-34's editable subset): one per panel role,
    plus the paper reader and the off-panel checker when configured."""
    rows: list[dict[str, Any]] = []
    panel = config.get("panel") or ()
    if isinstance(panel, (str, bytes, dict)):
        panel = ()
    for ref in panel:
        role = str(getattr(ref, "role", None) or (ref.get("role") if isinstance(ref, dict) else ""))
        slug = "grader-" + role.lower().replace(" ", "-").replace("/", "-") if role else "grader"
        rows.append({
            "field": slug,
            "label": f"Grading model — {role}" if role else "Grading model",
            "value": _ref_value(ref),
            "type": "model",
            "editable": True,
        })
    for slug, label, key in (
        ("paper-reader", "Paper reader model", "transcriber"),
        ("off-panel-checker", "Off-panel checker model", "off_panel_checker"),
    ):
        ref = config.get(key)
        if ref is None:
            continue
        rows.append({
            "field": slug, "label": label, "value": _ref_value(ref),
            "type": "model", "editable": True,
        })
    return rows


def _secret_row() -> dict[str, Any]:
    """The model service key's row: a configured boolean and nothing else (`CT-CONF-19`)."""
    return {
        "field": "model-service-key",
        "label": "Model service key",
        "value": None,
        "configured": bool(os.environ.get(OPENROUTER_API_KEY_ENV)),
        "type": "secret",
        "editable": False,
    }


def config_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The configuration projection (FR-CONF-35, FR-CONSOLE-60): every declared setting
    with its teacher label, current value from the resolved configuration, type tag and
    `editable` flag. The resolved configuration is the console's own — the one the server
    resolved at start-up — or the environment composed over the console's file when the
    server did not set one. Writes nothing."""
    del console, query
    resolved = getattr(app, "run_config", None)
    if not isinstance(resolved, dict) or not resolved:
        resolved = effective_config(getattr(app, "file_config", None))
    rows: list[dict[str, Any]] = []
    for slug, label, key, type_tag, editable in _DECLARED_ROWS:
        row: dict[str, Any] = {
            "field": slug, "label": label, "value": resolved.get(key),
            "type": type_tag, "editable": editable,
        }
        if type_tag == "choice":
            row["choices"] = list(DECISION_ENGINES)
        rows.append(row)
    rows.extend(_model_rows(resolved))
    rows.append(_secret_row())
    unlisted = sum(
        1 for key in resolved
        if key not in {entry[2] for entry in _DECLARED_ROWS}
        and key not in ("panel", "transcriber", "off_panel_checker")
    )
    return {
        "settings": rows,
        "projected": {
            "settings": len(rows),
            "editable": sum(1 for row in rows if row["editable"]),
            "unlisted_settings": unlisted,
        },
    }
