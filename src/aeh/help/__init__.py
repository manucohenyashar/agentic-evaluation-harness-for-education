"""M-HELP: the manuals library and the grounded, answers-only QA assistant.

Public surface (1.10-delta §3.4.4): ``MANUALS_DIR``, ``manuals_manifest``,
``load_manuals``, ``build_index``, ``HelpAssistant`` and ``qa_log``. The Q&A log table's
Tier D migration is declared in `aeh.store.migrations` (migration 11's ruling: a chain link
cannot be owned by a module store-openers needn't import), so this package carries no
registration duty — store opens never require importing it.
"""

from aeh.help.assistant import Answer, Citation, HelpAssistant
from aeh.help.log import qa_log
from aeh.help.manuals import (
    MANIFEST,
    MANUALS_DIR,
    ManualRecord,
    load_manuals,
    manuals_manifest,
)
from aeh.help.retrieval import Passage, RetrievalIndex, build_index
from aeh.help.schema import HELP_STATEMENTS  # noqa: F401  (the module's declared statements)

__all__ = [
    "MANUALS_DIR",
    "MANIFEST",
    "Answer",
    "Citation",
    "HelpAssistant",
    "ManualRecord",
    "Passage",
    "RetrievalIndex",
    "build_index",
    "load_manuals",
    "manuals_manifest",
    "qa_log",
]
