#!/usr/bin/env bash
set -euo pipefail

# Bounded local progress tracker for a delegated FreeBuff session.
# It sends only repository metadata and test summaries to local Ollama.

project_root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
interval_seconds="${GUARDIAN_TRACK_INTERVAL_SECONDS:-600}"
max_cycles="${GUARDIAN_TRACK_MAX_CYCLES:-6}"
ollama_model="${GUARDIAN_TRACK_MODEL:-qwen2.5-coder:14b}"
status_file="$project_root/.agent/research/OLLAMA_BACKGROUND_STATUS.md"
lock_dir="$project_root/.agent/tasks/ollama-background-tracker.lock"

case "$interval_seconds" in
  ''|*[!0-9]*) echo "Interval must be an integer." >&2; exit 2 ;;
esac
case "$max_cycles" in
  ''|*[!0-9]*) echo "Cycle count must be an integer." >&2; exit 2 ;;
esac
if (( interval_seconds < 60 || interval_seconds > 3600 )); then
  echo "Interval must be between 60 and 3600 seconds." >&2
  exit 2
fi
if (( max_cycles < 1 || max_cycles > 12 )); then
  echo "Cycle count must be between 1 and 12." >&2
  exit 2
fi

mkdir -p "$project_root/.agent/research" "$project_root/.agent/tasks"
if ! mkdir "$lock_dir" 2>/dev/null; then
  echo "An Ollama background tracker is already active." >&2
  exit 3
fi
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT INT TERM

for ((cycle = 1; cycle <= max_cycles; cycle++)); do
  checked_at="$(date --iso-8601=seconds)"
  worktree_status="$(git -C "$project_root" status --short 2>&1 | head -n 120)"
  diff_stat="$(git -C "$project_root" diff --stat 2>&1 | tail -n 80)"

  if PYTHONPATH="$project_root/src" python3 -m unittest discover \
      -s "$project_root/tests" -p 'test_execution.py' -q \
      >"$project_root/.agent/tasks/ollama-tracker-tests.tmp" 2>&1; then
    test_result="PASS: $(tail -n 2 "$project_root/.agent/tasks/ollama-tracker-tests.tmp" | tr '\n' ' ')"
  else
    test_result="FAIL: $(tail -n 12 "$project_root/.agent/tasks/ollama-tracker-tests.tmp" | tr '\n' ' ')"
  fi
  rm -f "$project_root/.agent/tasks/ollama-tracker-tests.tmp"

  prompt="$(
    printf '%s\n' \
      "Act as a local progress tracker, not an implementer." \
      "Summarize the delegated FreeBuff project state from metadata only." \
      "Do not invent completion. Do not request secrets. Do not recommend claude-sonnet-4.6." \
      "Return four short sections: Progress, Verification, Risks, Primary review needed." \
      "Checked at: $checked_at" \
      "Cycle: $cycle/$max_cycles" \
      "Focused tests: $test_result" \
      "Git status (filenames/status only):" \
      "$worktree_status" \
      "Tracked diff statistics:" \
      "$diff_stat"
  )"

  response="$(
    jq -n \
      --arg model "$ollama_model" \
      --arg prompt "$prompt" \
      '{model:$model,stream:false,keep_alive:"2m",options:{temperature:0,num_predict:500},prompt:$prompt}' |
      curl -fsS --max-time 180 \
        -H 'Content-Type: application/json' \
        --data-binary @- \
        http://127.0.0.1:11434/api/generate |
      jq -r '.response // empty'
  )" || response="Ollama status review failed at $checked_at. FreeBuff was not interrupted."

  tmp_status="${status_file}.tmp"
  {
    printf '# Ollama Background Status\n\n'
    printf -- '- Checked: %s\n' "$checked_at"
    printf -- '- Cycle: %s/%s\n' "$cycle" "$max_cycles"
    printf -- '- Model: `%s`\n' "$ollama_model"
    printf -- '- Focused verification: %s\n\n' "$test_result"
    printf '%s\n' "$response"
    printf '\n> This local file cannot wake or reactivate Codex. It is a bounded handoff for the next user-requested review.\n'
  } >"$tmp_status"
  mv "$tmp_status" "$status_file"

  if (( cycle < max_cycles )); then
    sleep "$interval_seconds"
  fi
done
