#!/bin/bash
# Computes which open type:story / type:test issues are unblocked (every issue named in
# their "Depends on: #N, #M" line is closed) and not already claimed or parked.
#
# Deliberately stateless: readiness is recomputed from GitHub's own issue state on every
# run rather than tracked in a separate "blocked"/"ready" label, so there's nothing to keep
# in sync.
#
# Usage:   ./ready-issues.sh [max_count]
# Output:  stdout — JSON array like [{"number":12,"type":"story"},...]
#          stderr — warnings about issues that were skipped and why
# Requires: gh (authenticated), jq

set -euo pipefail

MAX_COUNT="${1:-999}"

# All open story/test issues, with body+labels so we can read their dependency line and
# current claim status.
ISSUES_JSON=$(gh issue list --state open --limit 500 \
  --json number,title,body,labels)

# number -> state for every issue (open or closed), so dependency checks don't need one gh
# call per reference.
STATE_JSON=$(gh issue list --state all --limit 1000 --json number,state)

CLASSIFIED=$(echo "$ISSUES_JSON" | jq -c --argjson states "$STATE_JSON" '
  def is_closed($n):
    ($states | map(select(.number == $n)) | first // {}) as $s
    | ($s.state // "OPEN") == "CLOSED";

  # Pull the issue numbers out of a "Depends on: #12, #34" line, if present.
  def dep_lines($body): ($body // "") | [scan("(?i)depends on:[^\n]*")];
  def deps($body): dep_lines($body) | join(" ") | [scan("#([0-9]+)")] | map(.[0] | tonumber);

  [ .[]
    | select(.labels | map(.name) | any(. == "type:story" or . == "type:test"))
    | {
        number: .number,
        title: .title,
        type: (if (.labels | map(.name) | any(. == "type:test")) then "test" else "story" end),
        claimed: (.labels | map(.name) | any(. == "status:in-progress" or . == "status:in-review")),
        parked:  (.labels | map(.name) | any(. == "status:needs-attention")),
        dep_line: ((dep_lines(.body) | length) > 0),
        deps: deps(.body)
      }
    | . + { malformed: (.dep_line and (.deps | length) == 0) }
  ]
  | map(. + { unblocked: (.deps | map(is_closed(.)) | all) })
')

# An unparseable "Depends on:" line used to read as "no dependencies", which started work
# that was still blocked. Skip those and say so, rather than guessing either way.
echo "$CLASSIFIED" | jq -r '
  .[] | select(.malformed)
      | "skipped #\(.number) \(.title): \"Depends on:\" line has no #issue-numbers. Use \"Depends on: #12, #34\" or remove the line."' >&2

# A run that failed gets status:needs-attention. Without this filter the dispatcher would
# re-claim it on the very next event and loop on the same failure indefinitely.
echo "$CLASSIFIED" | jq -r '
  .[] | select(.parked and (.claimed | not))
      | "skipped #\(.number) \(.title): status:needs-attention. Remove the label once a human has looked at it."' >&2

echo "$CLASSIFIED" | jq -c --argjson max "$MAX_COUNT" '
  [ .[]
    | select(.claimed | not)
    | select(.parked | not)
    | select(.malformed | not)
    | select(.unblocked)
  ]
  | .[:$max]
  | map({number, type})
'
