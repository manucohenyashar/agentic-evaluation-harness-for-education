"""Recover work lost with a deleted worktree: mine the session transcript."""
import json
import sys

TRANSCRIPT = r"C:\Users\mcohenyashar\.claude\projects\C--Users-mcohenyashar-Documents-Projects-agentic-evaluation-harness-for-education-Code\651a13ff-8684-43e4-ab63-f07e95fad253\subagents\agent-a3f8f99c9ad7046a7.jsonl"
OUT = r"C:\Users\mcohenyashar\Documents\Projects\agentic-evaluation-harness-for-education\Code\recovered"


def main() -> None:
    import os
    os.makedirs(OUT, exist_ok=True)
    writes = []  # (line_no, file_path, content)
    edits = []   # (line_no, file_path, old, new)
    bash = []    # (line_no, command)
    with open(TRANSCRIPT, encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, 1):
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            message = entry.get("message") or {}
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name")
                payload = block.get("input") or {}
                if name == "Write":
                    writes.append((line_no, payload.get("file_path", "?"), payload.get("content", "")))
                elif name == "Edit":
                    edits.append((line_no, payload.get("file_path", "?"), payload.get("old_string", ""), payload.get("new_string", "")))
                elif name == "Bash":
                    bash.append((line_no, payload.get("command", "")))

    print(f"writes: {len(writes)}  edits: {len(edits)}  bash: {len(bash)}")
    print("\n=== Write file paths (in order) ===")
    for line_no, path, _ in writes:
        print(f"  L{line_no}  {path}")
    print("\n=== Edit file paths (in order) ===")
    for line_no, path, _, _ in edits:
        print(f"  L{line_no}  {path}")
    print("\n=== Bash commands mentioning capture/run_capture/pytest/gh ===")
    for line_no, command in bash:
        low = command.lower()
        if any(k in low for k in ("capture", "run_capture", "pytest", "gh pr", "gh issue", "git ", "test.sh")):
            first = command.splitlines()[0][:160]
            print(f"  L{line_no}  {first}")


if __name__ == "__main__":
    main()
