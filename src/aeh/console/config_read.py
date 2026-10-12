"""The configuration read behind the SPA's settings page (`FR-CONF-35`, FR-CONSOLE-60, #755).

This read delegates its whole view model to `configuration_projection` — the projection
M-CONF (#756) owns, reached through `aeh.conf`'s own package surface (the declared console
edge, `TC-CONSOLE-36`'s frozen set) — as the #755 docstring said it should. There is one
reading of each setting: the projection and the guided write path (`update configuration`)
share the same setting ids, so what the settings page shows as editable is exactly what the
write path accepts, and a row can never render as editable and then be refused.

The payload the SPA builds against keeps the shape this read has always had —
`{"settings": [row...], "projected": {...}}`, each row carrying `field`, `label`, `value`,
`type`, `editable` and, when they apply, `choices` and `configured`. Two things the
delegation changes, both deliberate:

* `field` is now the projection's setting id — the same id `update profile edits` accepts
  — so the settings page posts its edits keyed by what the form rendered.
* `value` is always a string (the value in force, empty when the setting does not apply),
  and model settings arrive already in the `provider|build_id[|quantization]` form the
  guided form accepts back.

The secret's row stays a configured boolean and nothing else (`CT-CONF-19`), answered from
the one credential the harness reads, and no key name from the configuration file appears
in any string here (`CT-CONSOLE-31`'s scan): the projection's labels are the words, and a
configuration that cannot project refuses in teacher language.
"""

from __future__ import annotations

import os
from typing import Any

from aeh.conf import ConfigurationError, configuration_projection, effective_config
from aeh.prov import OPENROUTER_API_KEY_ENV

#: The id the projection uses for the model provider's credential; the read answers it from
#: the live environment, which the projection itself never touches (it is pure).
_SECRET_ID = "model_provider_key"


def config_read(console: Any, app: Any, query: Any) -> dict[str, Any]:
    """The configuration projection as the `config` read's answer: every setting with its
    teacher label, current value from the configuration in force, type tag and `editable`
    flag. The configuration in force is the console's own resolved one — the one the server
    resolved at start-up — or the environment composed over the console's file when the
    server did not set one. Writes nothing."""
    del console, query
    resolved = getattr(app, "run_config", None)
    if not isinstance(resolved, dict) or not resolved:
        resolved = effective_config(getattr(app, "file_config", None))
    try:
        views = configuration_projection(
            resolved,
            secrets_configured={_SECRET_ID: bool(os.environ.get(OPENROUTER_API_KEY_ENV))},
        )
    except ConfigurationError:
        raise ValueError(
            "The console cannot describe the settings for the configuration it is running."
            " Fix the configuration first, then load this page again."
        ) from None
    rows: list[dict[str, Any]] = []
    for view in views:
        row: dict[str, Any] = {
            "field": view.setting,
            "label": view.label,
            "value": view.value,
            "type": view.type,
            "editable": view.editable,
        }
        if view.choices:
            row["choices"] = list(view.choices)
        if view.type == "secret":
            row["configured"] = bool(view.configured)
        rows.append(row)
    return {
        "settings": rows,
        "projected": {
            "settings": len(rows),
            "editable": sum(1 for row in rows if row["editable"]),
        },
    }
