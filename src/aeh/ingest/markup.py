"""The markers the transcript uses (regions, struck text, untrusted content) and the prompt."""

from __future__ import annotations


#: The region-marker protocol the pinned prompt asks the model to emit: page content
#: wrapped in HTML comments the parser owns. Declared here, version-pinned with the
#: prompt — the parser and the prompt move together or not at all.
REGION_OPEN = "<!-- region:"


REGION_CLOSE = "<!-- /region -->"


STRUCK_OPEN = "<s>"


STRUCK_CLOSE = "</s>"


#: The escalation fence (`FR-INGEST-35` at `_v4_escalate`'s prompt-assembly site):
#: the markers the instruction names as the untrusted block's boundary, byte-exact —
#: the template that extracts the block splits on this exact string, so the fence
#: writer (`_fence_untrusted_content`) guarantees it: the content can never carry
#: the closing marker (issue #224).
UNTRUSTED_OPEN = "<untrusted_student_content>"


UNTRUSTED_CLOSE = "</untrusted_student_content>"


#: The supersession note the pinned prompt asks the model to write before the
#: correcting content: the region it names (or the immediately preceding one) is
#: the earlier version, and BOTH stay (`FR-INGEST-12`).
SUPERSEDED_PREFIX = "~~superseded-by"


#: The transcription prompt (v4): v2's region-marker protocol, per-kind description
#: fields (`FR-INGEST-10`) and retraction markup (`FR-INGEST-12` — BOTH versions of a
#: struck-through/corrected line are kept); v3's per-region confidence, content-state
#: and unresolved-token attributes; v4 adds the verbatim header carry-over — the
#: 'Assessment:' and 'Student:' lines the ladder's V3/V4 gates parse (`FR-INGEST-24`,
#: `FR-INGEST-25`). A prompt change alters every subsequent transcript, so this is a
#: deliberate, PR-recorded bump (`NFR-INGEST-05`). Descriptive-only: the model is told
#: the evaluative bar in the prompt too, though the module enforces it mechanically.
TRANSCRIPTION_PROMPT = (
    "Transcribe this examination page verbatim into Markdown. Carry the page's header "
    "lines over verbatim first, each on its own line: any 'Assessment: <name>' line "
    "naming the assessment and any 'Student: <name>' line naming the candidate. Wrap "
    "every region in "
    "region comments: '<!-- region: kind=transcribed_text -->' for text, "
    "'<!-- region: kind=described_graphic element_kind=free_body_diagram -->' for a "
    "graphic, '<!-- region: kind=selection_mark question_id=Q1 -->' for a mark; close "
    "each with '<!-- /region -->'. Tag every region with its reading confidence "
    "('conf=0.87'), an answer region's content state ('state=present', 'state=blank' "
    "when the answer space is empty), and a mark region with its selection state "
    "('selection_state=resolved' or 'ambiguous' or 'multiple_marks'). Where a "
    "handwritten token cannot be read, transcribe it as <unresolved>token</"
    "unresolved> — never guess it. Describe graphics with the element kind's named "
    "fields: a free-body diagram names per arrow its label, origin point and "
    "direction (an angle or a relation to a named surface or axis); a geometry "
    "construction names its points and every marked relation; a graph names its axis "
    "labels, units, intercepts and turning points; a table is emitted as a Markdown "
    "table, never prose; a label or annotation names the object it attaches to and by "
    "what means; a spatial relation is stated explicitly. Retain struck-through "
    "content inside <s>...</s> and write a correction above an earlier line as "
    "'~~superseded-by' beside it — BOTH versions stay in the transcription. Do not "
    "evaluate: the words correct, valid, appropriate, properly, as expected and "
    "should be must not appear in any description."
)
