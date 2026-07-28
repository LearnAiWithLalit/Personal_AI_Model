# Guardian Agent — Daily Handoff for 2026-07-28 (Updated)

Prepared: 2026-07-28 (Asia/Kolkata)
Repository: `https://github.com/LearnAiWithLalit/Personal_AI_Model`
Workspace: `/media/lalit/HIKVISION1/AI agent model`
Branch: `main`
Committed base at handoff: `4f02e4b` (Phase 1-6 + Priority 2 + Priority 3 all committed)

## 1. Start here tomorrow

The user may make code changes after this note is written. Treat every
uncommitted change as user-owned. Do not overwrite, discard, reset, or
automatically reformat it.

Begin with read-only inspection:

```bash
git status --short
git log -5 --oneline --decorate
git diff --check
git diff --stat
```

Then inspect the actual diff before deciding which tests apply. Run focused
tests first and the full suite only after the focused failures are resolved:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_connectors.py' -q
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_browser.py' -q
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_supervisor.py' -q
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_executor_worker.py' -q
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 -m compileall -q src tests
git diff --check
```

Do not accept a passing legacy suite as proof that the new security boundaries
work. Re-run or convert the adversarial checks in Section 4 into regression
tests.

## 2. Verified baseline today

- Full local suite: **548 tests passed** (385 baseline + Phase 1/2/3/4 + Phase 5/6 + Phase 7 + Priority additions).
- New focused tests added:
  - **20 WorkerRouter tests** (Phase 7: availability, selection, integration, execute, and route classification)
  - **8 CLI integration tests** (Phase 7: end-to-end route/execute CLI commands)
  - **31 Aider tests** (+7 from previous: Colibri backend detection, availability, colibri in backends dict)
  - **52 JCode tests** (+5 from previous: capability probe, required/recommended flag checks, dangerous command detection)
  - **35 Hermes tests** (+1 from previous: Hermes execution fail-closed, now with isolated library_path)
  - **50 browser tests** (28 original + 22 new: overlay detection, page settlement, stale-element checks, submission fingerprints, reconciliation, page-context takeover)
  - **42 connector tests** (existing + expanded for Canva/Adobe/Lovable real API calls)
  - **39 supervisor tests**
  - **11 executor worker tests**
- Source and tests compiled.
- `git diff --check` passed.
- New source files: `src/guardian_agent/jcode.py`, `tests/test_jcode.py`, `src/guardian_agent/hermes.py`, `tests/test_hermes.py`, `src/guardian_agent/worker_router.py`, `tests/test_worker_router.py`, `tests/test_cli_integration.py`
- Modified source files: `src/guardian_agent/browser_operator.py`, `src/guardian_agent/cli.py`, `src/guardian_agent/connectors.py`, `src/guardian_agent/aider.py`, `src/guardian_agent/executor_worker.py`, `src/guardian_agent/jcode.py`, `src/guardian_agent/hermes.py`
- Modified test files: `tests/test_browser.py`, `tests/test_connectors.py`, `tests/test_aider.py`, `tests/test_supervisor.py`, `tests/test_executor_worker.py`, `tests/test_jcode.py`, `tests/test_hermes.py`

## 3. Honest current status

### Implemented foundation

- Project brain, confirmed requirements, journey, decisions, lessons, and
  compact handoffs.
- 150 deterministic specialist profiles and compact skill selection.
- Ollama and OmniRoute discovery/routing/budget evidence.
- Aider and FreeBuff bounded handoff adapters.
- Execution stages, claim leases, recovery, final-review reserve, and manual
  primary-review stage.
- Exact approval action/target/scope checks and one-time browser approval
  reservation tokens.
- Encrypted local vault, account registry, allowed domains, revocation, and
  backup/restore.
- Learning drafts, revision rollback, evaluation history/alerts, and
  approval-gated sanitized cross-project lessons.

### Partial, not production-complete

- Connector idempotency owner tokens.
- Browser selector actionability checks.
- Manual browser takeover.
- Supervisor/worker daemon loop.
- Canva, Adobe, and Lovable connectors.
- Background worker concurrency and capacity reporting.

### Now implemented (Phase 5B reliability batch)

- Browser preflight abort: `reserved -> preflight_aborted` with owner-token
  enforcement, never marks unknown_outcome, allows clean retry.
- Crash-safe WAL reconciliation: 3-phase protocol with reconciling_started
  intermediate state, recovery in all four ledger mutation methods.
- Supervisor graceful drain/shutdown: `DrainCoordinator` with inflight
  tracking, shutdown hooks, and signal handler management.
- Full browser unknown-outcome reconciliation with real approval validation,
  evidence fields, account/connector/action/key matching.
- 11-test end-to-end smoke test covering connector, browser, cross-domain,
  and WAL recovery lifecycles.

### Now implemented (Phase 1 — Aider routing improvements)

- **Task-size routing**: `classify_task_size()` classifies tasks as small
  (→ Aider), large (→ JCode when available), or research (→ Hermes when
  available), with worker availability detection via `shutil.which()`.
- **Enhanced Aider handoff**: `create_aider_handoff()` now accepts acceptance
  criteria, exact writable paths (with protected-path filtering), test command,
  known risks, and stop conditions. All parameters are optional — backward
  compatible with existing callers.
- **Execution evidence**: `collect_aider_execution_evidence()` gathers changed
  files via git diff (with +/− counts), test results via bounded subprocess,
  token/provider usage from Aider LLM history, and remaining risks.
- **Safety guardrails verified**: dry-run default, no analytics/auto-commits,
  no credentials in handoff, prohibited models blocked, backend reachability
  check before launch.
- **CLI commands**: `guardian aider classify`, `guardian aider prepare`,
  `guardian aider evidence` — all enhanced with the new parameters.
- **18 new tests** covering classification, handoff content, evidence collection,
  and path filtering. 24 total aider tests pass.

### Now implemented (Phase 2 — JCode safe adapter)

- **Binary detection**: `jcode_status()` detects the JCode binary, reads
  version with 15s timeout, and reports unavailable state safely.
- **Dry-run prepare**: `create_jcode_handoff()` builds a compact handoff
  document with the task, writable paths, restrictions, and project context.
  Never executes JCode — dry-run by design.
- **Command preview**: `build_jcode_command()` constructs a safe command with
  `--dry-run` default, `JCODE_NO_TELEMETRY=1`, and filtered writable paths.
- **11 restrictions enforced and documented**: no-install, no-login, no-oauth,
  no-provider-setup, no-credential-import, no-browser, no-mcp, no-swarm,
  no-self-development, no-direct-commit, no-direct-push.
- **Protected path filtering**: reuses `_safe_writable_paths()` from aider
  module — rejects `.env`, `.git`, `.agent`, `../outside`, etc.
- **CLI commands**: `guardian jcode status`, `guardian jcode prepare`,
  `guardian jcode command`.
- **19 tests** across 3 test classes (StatusTests, HandoffTests, CommandTests).

### Now implemented (Priority 3 — True per-ticket concurrency)

- **`process_ready_tickets` parallelized**: Upgraded from sequential for-loop
  to `ThreadPoolExecutor` with `max_workers` parameter (default 4, range 1-16).
  Each ticket is submitted as an individual future for true concurrent execution.
- **CLI `--max-workers`**: Added to `guardian executor run` command.
- **Timing-based concurrency test**: `test_process_ready_tickets_concurrency_timing`
  proves overlapping execution with 4 mock tickets × 0.2s sleep in 4 workers
  completing in < 1.0s.
- **Daemon structural test**: `test_parallel_ticket_execution` verifies the
  daemon submits individual futures per ticket.

### Now implemented (Phase 3 — JCode controlled execution)

- **Explicit user opt-in**: `jcode_opt_in()` / `jcode_is_opted_in()` — stores
  consent in `.agent/jcode_consent.json`. Execution blocked without opt-in.
- **Sandbox/worktree execution**: Uses `create_worktree_sandbox()` — isolated
  git worktree (or copy fallback). JCode runs inside the sandbox with its own
  copy of the handoff and approved files.
- **Approved paths only**: `_safe_writable_paths()` filters protected paths.
  JCode only sees approved files. `.env`, `.git`, `.agent`, and `../outside`
  paths are automatically rejected.
- **Timeout**: Configurable (10-3600s, default 300s/5min).
  `subprocess.TimeoutExpired` handled gracefully with elapsed time in result.
- **Output capture**: Captures stdout, stderr, exit code, and elapsed time.
- **Diff evidence**: `_git_diff_in_sandbox()` — git diff for worktrees, file
  content comparison for copy-fallback. Reports files with +/− change counts.
- **Test results**: Runs the specified test command after JCode completes,
  captures stdout/stderr and exit code for evidence.
- **Out-of-scope rejection**: `_validate_out_of_scope()` — compares changed
  files against allowed writable paths. Any change outside is flagged in the
  structured result with the list of unauthorized files.
- **Requires final approval**: `result["approved"]` is always `False` —
  model/user must make the final call by inspecting the diff, test results,
  and out-of-scope report.
- **CLI commands**: `guardian jcode opt-in` (enables per-project execution),
  `guardian jcode run` (executes a bounded task with sandbox, timeout,
  capture).
- **10 new tests** covering opt-in, sandbox execution, timeout, out-of-scope
  rejection, stdout/stderr capture, structured output format. 29 total JCode
  tests pass.

### Now implemented (Phase 4 — JCode bounded parallel work)

- **Max 2 workers**: `jcode_parallel_run()` limits to `max_workers=2` by default,
  rejects >2 task packages. Runs workers via `ThreadPoolExecutor`.
- **Independent tasks only**: `_check_path_conflicts()` validates no overlapping
  writable paths between task packages before any execution begins.
- **Path locking before dispatch**: `_lock_writable_paths()` / `_unlock_writable_paths()`
  — JSON lock files in `.agent/locks/` with 1-hour TTL, stale release, and
  per-worker conflict detection.
- **Change notifications**: `_notify_workers()` copies diff info into pending
  workers' sandboxes as notification JSON files and `peer_diff.txt`.
- **Stop conditions**: Checks after each worker completes — timeout, exit code,
  out-of-scope changes, test failure, and emergency stop (`is_kill_switch_active`).
  Remaining workers are notified before stopping.
- **One worker for implementation, one for tests**: Architecture supports two
  independent task packages with different writable paths and test commands.
- **Guardian final gate**: `result["approved"]` is always `False` — model/user
  reviews combined evidence from all workers.
- **CLI command**: `guardian jcode parallel-run --task "..." --task "..."`
  (repeatable `--task`, max 2).
- **18 new tests** covering path overlap, lock acquisition, lock conflicts,
  lock release, conflict detection between packages, change notifications,
  opt-in enforcement, binary check, empty packages, max workers enforcement,
  and path conflict rejection. 47 total JCode tests pass.

### Now implemented (Priority 2 — Browser reliability)

- **Overlay detection** (`_check_overlay_blocking`): JS `elementFromPoint()` check
  for modal/banner/popup coverage. Integrated into `execute_browser_action()`
  preflight — raises GuardianError if overlay detected.
- **Page settlement** (`_wait_for_page_settled`): `networkidle` wait + MutationObserver
  DOM stability check. Called after navigation and redirects.
- **Stale-element check** (`_check_element_stable`): Verifies element count,
  visibility, and enabled state before interaction.
- **Submission fingerprints** (`_create_submission_fingerprint`): Captures URL,
  title, success/error keywords, visible text for before/after comparison.
- **Page-state reconciliation** (`_reconcile_submission_state`): Compares
  before/after fingerprints with confidence scoring (0.3-0.9); stored in
  ledger receipt for sensitive actions.
- **Page-context takeover**: `pause_for_takeover()` accepts `current_page_url`
  and `current_page_title`. Stored in takeover metadata. Playwright navigates
  to the exact page before showing the takeover banner. Backward compatible.
- **CLI commands**: `guardian browser reconcile list` (list unknown outcomes),
  `guardian browser reconcile resolve` (resolve with evidence and approval).
- **22 new tests** covering all reliability functions (50 total browser tests).

### Now implemented (Priority 3 — Real connectors)

- **Canva**: Real Canva Connect API (`api.canva.com/rest/v1/`) — OAuth Bearer
  auth, list designs via `GET /designs`, create via `POST /designs`, export via
  `POST /exports` with async polling and download. Browser fallback when no
  API token configured. Remote auth verification via `users/me` endpoint.
- **Adobe**: Real Adobe Express API + IMS OAuth — `client_id`/`client_secret`
  exchanged via `client_credentials` grant, `X-API-KEY` header set to actual
  `client_id`, list/create tagged documents, PDF Services export. Browser
  fallback when no credentials configured.
- **Lovable**: Honest browser-first approach (no fake REST claims) —
  "Build with URL" generation (`lovable.dev/?autosubmit=true#prompt=...`),
  MCP server URL exposure (`mcp.lovable.dev`), `browser_fallback: true` on
  all operations.
- **Infrastructure**: `_connector_http_request()` / `_connector_api_call()`
  via stdlib `urllib.request`, rate limit handling (HTTP 429), consolidated
  `_require_auth()` pattern that always checks credentials then decides mock
  vs real API.
- **42 connector tests** pass.

### Now implemented (Phase 5 — Hermes optional learning/research worker)

- **Binary detection**: `hermes_status()` — `shutil.which("hermes")` for PATH
  detection, version with 15s timeout, reports unavailable state safely.
- **Tools-disabled handoff**: `create_hermes_handoff()` — generates a handoff
  document with 13 enforced restrictions (`no-browser`, `no-mcp`,
  `no-messaging-gateway`, `no-credential-import`, `no-self-development`, etc.)
  and explicit "Tools-disabled profile" section.
- **Task-type restrictions**: Only `research`, `planning`, `skill-evaluation`,
  and `summary` types allowed. Other types rejected with clear error.
- **Explicit user opt-in**: `hermes_opt_in()` / `hermes_is_opted_in()` — stores
  consent in `.agent/hermes_consent.json`. Execution blocked without opt-in.
- **Bounded execution**: `execute_hermes_task()` — configurable timeout
  (10-3600s), stdout/stderr/exit-code capture, isolated memory output.
- **Memory isolation**: Separate `hermes_memory/` directory under `.agent/`.
  `import_hermes_lesson()` is the ONLY import path into Guardian's learning
  library — requires sanitized, user-approved content; raw Hermes output is
  never automatically imported.
- **Environment sandboxing**: `HERMES_TOOLS_DISABLED=1`, `HERMES_NO_TELEMETRY=1`,
  `HERMES_API_KEY`, `HERMES_AUTH_TOKEN`, and `HERMES_MESSAGING_TOKEN` stripped
  from child environment.
- **13 restrictions enforced**: no-install, no-login, no-oauth, no-provider-setup,
  no-credential-import, no-browser, no-mcp, no-swarm, no-self-development,
  no-commit-push, no-messaging-gateway, no-scheduling, no-external-actions.
- **CLI commands**: `guardian hermes status`, `guardian hermes opt-in`,
  `guardian hermes prepare`, `guardian hermes run`, `guardian hermes memory`,
  `guardian hermes import-lesson`.
- **12 tests** covering status, handoff, opt-in, execution, memory isolation.

### Now implemented (Phase 6 — Controlled background work)

- **Scheduled task types**: Only `health-check`, `research-summary`,
  `skill-evaluation`, and `maintenance-proposal` are allowed.
- **Approval-gated scheduling**: `hermes_schedule_task()` consumes a real
  approval via `consume_action_approval()` before adding any task. Approval
  must target `hermes:<task-type>`.
- **Interval enforcement**: Minimum 300s (5 minutes), maximum 7 days.
  `hermes_list_scheduled()` shows due/not-due status with epoch timestamps.
- **Run due tasks**: `hermes_run_due_tasks()` — max 5 tasks per run (configurable
  1-10), force option to skip schedule timing, optional task-type filter.
- **External actions blocked**: All results have `change_proposed: False`.
  Results are stored in Hermes isolated memory for human/primary-model review.
- **Exponential backoff on failure**: Failed tasks back off with `60 * 2^failures`
  (capped at 86400s/1 day). Failure count and last error persisted.
- **CLI commands**: `guardian hermes schedule`, `guardian hermes list-scheduled`,
  `guardian hermes unschedule`, `guardian hermes run-due`.
- **22 tests** covering scheduling, listing, unscheduling, run-due execution,
  interval validation, approval consumption, failure handling.

### Still pending

- Official authorized remote connectors and GitHub/PR workflows.
- OS-keychain integration and production credential/session lifecycle.
- Cryptographic skill signing and isolated real-task forward evaluation.
- Multi-user isolation, release packaging, production telemetry/incidents,
  supply-chain review, and production threat modelling.

## 4. Previous blocking findings — resolution status

All connector lifecycle adversarial findings from the 294-test baseline have
been resolved and are now covered by permanent regression tests:

| Finding | Resolution | Test coverage |
|---|---|---|
| mark_unknown without owner token accepted | `mark_unknown()` now requires exact owner token; mismatch raises GuardianError. | `test_mark_unknown_requires_matching_owner_token` + `test_fail_browser_operation_with_wrong_token_rejected` |
| completed receipt overwritten | `complete()` rejects `completed` and `reconciled_completed` states as immutable. | `test_idempotency_owner_token_completion_enforcement` + `test_completion_from_non_reserved_state_rejected` |
| live reserved reconciled without owner | `reconcile()` rejects non-`unknown_outcome` states. Requires real approved approval, exact evidence, owner token. | `test_live_reserved_operation_cannot_be_reconciled` + all integration reconcile tests |
| stale reservation blindly retried | Stale TTL transitions to `unknown_outcome` fail-closed. | `test_idempotency_stale_ttl_expiration_transitions_to_unknown_outcome` |
| daemon processed totals wrong | Executor accounting updated. DrainCoordinator added. | DrainCoordinatorTests (39 supervisor tests) |

Previous unresolved findings resolution status:

| Finding | Resolution | Test coverage |
|---|---|---|
| `max_workers` ticket-count rather than true concurrency | **Resolved** — `process_ready_tickets()` upgraded to `ThreadPoolExecutor` with `max_workers` parameter (1-16). True parallel execution verified with timing-based tests. | `test_process_ready_tickets_concurrency_timing` + `test_parallel_ticket_execution` |

Remaining unresolved findings (not yet addressed):

- `active_providers = []` with a healthy mocked capacity route.
- Credential availability reported as remote authentication success.
- Non-mock connectors returning fabricated success.

These are tracked in the "Still pending" section of this handoff.

## 5. Next implementation order

### ✅ Completed

- ~~Phase 1 — Aider routing improvements~~
- ~~Phase 2 — JCode safe adapter (first milestone)~~
- ~~Phase 3 — JCode controlled execution (sandbox, timeout, cancellation, capture)~~
- ~~Phase 4 — JCode bounded parallel work (max 2 workers, path locking, conflict detection, change notifications, stop conditions)~~
- ~~Phase 5 — Hermes optional learning/research worker~~
- ~~Phase 6 — Controlled background work~~
- ~~Phase 7 — WorkerRouter: auto-select the best worker (Aider/JCode/Hermes) for a confirmed task~~
- ~~Priority 3 — True per-ticket concurrency timing test~~
- ~~Priority 1 — Browser reliability (overlay/navigation checks, submission fingerprints, page-state reconciliation, page-context takeover, CLI reconcile)~~
- ~~Priority 2 — Real connectors (Canva, Adobe, Lovable real API implementations)~~

### Priority 3 — Learning and production hardening

- OS keychain, credential rotation/expiry, session recovery.
- Cryptographic skill signing, isolated real-task evaluation.
- Multi-user isolation, release packaging, security review.
- Colibri optional high-resource local inference adapter (pending user approval on eligible hardware).

## 6. JCode current state (Phase 4 complete)

Phases 2, 3, and 4 are **implemented**. The `JCodeAdapter` now provides:

- Binary/version detection via `jcode_status()` with 15s timeout.
- Dry-run handoff preparation via `create_jcode_handoff()` — never executes JCode.
- Command preview via `build_jcode_command()` with `--dry-run` default.
- 11 enforced restrictions documented in the handoff document.
- **Explicit user opt-in** per project via `jcode_opt_in()` / `jcode_is_opted_in()`.
- **Sandbox/worktree execution** via `execute_jcode_in_sandbox()` with configurable
  timeout (10-3600s), stdout/stderr/exit-code capture, and process cleanup.
- **Diff evidence** via `_git_diff_in_sandbox()` — git diff for worktrees or file
  comparison for copy-fallback, with +/− change counts.
- **Test result capture** — runs the specified test command after JCode completes.
- **Out-of-scope rejection** via `_validate_out_of_scope()` — flags any changed
  file outside the allowed writable paths.
- **Bounded parallel work** via `jcode_parallel_run()` — up to 2 workers with
  path locking (`_lock_writable_paths()`/`_unlock_writable_paths()`),
  conflict detection (`_check_path_conflicts()`), change notifications
  (`_notify_workers()`), and stop conditions (timeout, exit code,
  out-of-scope changes, test failure, emergency stop).
- **Final approval required** — `result["approved"]` is always `False`.
- 47 tests covering all phases.
- CLI commands: `guardian jcode status`, `guardian jcode prepare`,
  `guardian jcode command`, **`guardian jcode opt-in`**, **`guardian jcode run`**,
  **`guardian jcode parallel-run`**.

No remaining JCode work — all phases implemented.

## 7. Colibri next-phase plan — ask the user first

Colibri is an optional high-resource local inference provider, not an agent
framework and not a default dependency.

Before any installation, model download, conversion, file movement, or server
startup, ask the user for explicit informed approval. Show:

- detected RAM;
- free space on the exact target disk;
- expected model storage (approximately 380–400 GB for the referenced int4
  setup);
- target directory;
- expected setup/download implications;
- expected speed from a readiness/smoke test;
- the fact that low-memory disk-streaming inference can be extremely slow.

Eligibility/defaults:

- 24 GB+ RAM is the recommended optional tier, but `coli doctor`, `coli plan`,
  disk capacity, and measured performance decide actual eligibility;
- bind only to `127.0.0.1`;
- use local authentication if a server is started;
- never auto-configure LAN/public exposure;
- Ollama remains the ordinary local default;
- Colibri receives only compact one-shot architecture, review, council,
  synthesis, or skill-evaluation prompts;
- no full journey, repository dump, large agent preamble, repeated tool loop,
  browser action, file write, or external side effect;
- record startup, prefill, decode, queue, token, memory, cancellation, and
  fallback evidence.

First Colibri implementation should only add safe detection and mocked adapter
tests. It must not download the model. A real smoke test happens only after the
user approves setup on an eligible machine.

## 8. Phase 7 — WorkerRouter: auto-select the best worker

**Goal:** Auto-classify a confirmed task and route it to the cheapest adequate
worker (Aider for small coding tasks, JCode for large multi-file changes,
Hermes for research/planning/summary).

**Status: Implemented and verified.**

### Worker routing logic (`worker_router.py`)

- **`classify_task()`** — deterministic heuristic: tasks over 300 characters
  or matching large-task patterns ("implement", "refactor", "multi-file") are
  classified as `large` → JCode. Tasks matching research patterns ("research",
  "investigate", "analyze") are `research` → Hermes. Everything else is
  `small` → Aider.
- **Worker availability detection** — checks each binary via `shutil.which()`:
  `aider` for Aider, `jcode` for JCode, `hermes` for Hermes. Falls back to
  the next available worker if the preferred one is missing.
- **`route_task()`** — classifies the task, selects the best available worker,
  builds the handoff (writable paths, test command, backend/model config).
  Returns a structured routing result with `selected_worker`, `reasoning`,
  and `handoff`.
- **`execute_route()`** — takes a routing result and dispatches to the
  selected worker's execution function (Aider `launch_aider`, JCode
  `execute_jcode_in_sandbox`, Hermes `execute_hermes_task`). Respects each
  worker's safety model (dry-run for Aider, sandbox for JCode, fail-closed
  for Hermes).

### CLI commands

```bash
guardian route analyze --task <task> --project .
guardian route execute --task <task> --project . --allow-edits
```

### Backend support for Colibri

- Colibri (`coli serve`) is added as a third Aider backend alongside Ollama
  and OmniRoute, detected via `shutil.which("coli")`.
- `_colibri_path()`, `_colibri_available()` helpers added.
- Backend config at `BACKENDS["colibri"]`: `127.0.0.1:8000`,
  `http://localhost:8000/v1`, no credential required.
- CLI `--backend` choices expanded to include `"colibri"`.

### JCode capability probe (safety hardening)

- `jcode_capability_probe()` runs `jcode --help` to verify that required flags
  (`--read`, `--message`, `--dry-run`) are supported before execution.
- Checks for dangerous subcommands (`login`, `provider`, `server`, `client`,
  `swarm`) and blocks execution if they are detected.
- Refuses execution if any required flag is missing — fail-closed.

### 20 WorkerRouter tests covering

- Availability detection (all/none/single worker scenarios)
- Task classification (small, large, research)
- Routing integration (handoff content, writable paths, worker selection)
- Route execution (dispatching to correct worker, with dry-run behavior)
- 8 end-to-end CLI integration tests

## 9. Completion gate for tomorrow

Do not report completion merely because the legacy suite passes.

Before handoff:

1. focused new adversarial tests pass;
2. the full suite passes;
3. source/tests compile;
4. `git diff --check` passes;
5. no secrets or unrelated user changes are included;
6. implementation claims match actual behavior;
7. update `GUARDIAN_AGENT_PROJECT_PLAN.md`, `README.md`, and this handoff when
   their status statements change;
8. primary model or user reviews the compact diff/evidence before commit/push;
9. commit/push only when requested or explicitly confirmed.

