# Guardian Agent — Complete Project Handoff

Last refreshed: 2026-07-26  
Repository: `https://github.com/LearnAiWithLalit/Personal_AI_Model`  
Local workspace: `/media/lalit/HIKVISION1/AI agent model`  
Branch: `main`  
Last committed base inspected: `47b2470 Add secure allowlisted MCP integration`  
Package: `guardian-agent` version `0.1.0`

## 1. Purpose of this note

This is the restart document for the entire Guardian project. A user, Codex,
Claude, Gemini, Aider, FreeBuff, Ollama worker, or another coding agent should
be able to read this file and continue without rereading the original chat.

This file records:

- the product goal and non-negotiable safety rules;
- the intended end-to-end architecture;
- what is implemented and freshly verified;
- what is only a foundation and is not production-ready;
- the local/free resource strategy;
- the exact current worktree state;
- the recommended next implementation phases;
- validation and restart commands.

The long-form product specification remains in
`GUARDIAN_AGENT_PROJECT_PLAN.md`. User-facing commands and examples remain in
`README.md`.

## 2. Product goal

Guardian is a local-first coordination layer that sits before a user's chosen
primary coding model or IDE assistant. It should work with Codex, Claude Code,
Gemini, Antigravity, VS Code, Cursor, Aider, FreeBuff, Ollama, OmniRoute, and
future adapters without making the project depend on one model vendor.

Guardian should:

1. understand and confirm the user's real requirement;
2. classify risk and decompose the task;
3. retrieve only relevant project memory, lessons, profiles, and skills;
4. perform deterministic work without a model where possible;
5. route bounded work to the cheapest adequate local/free worker;
6. persist compact handoffs, execution state, evidence, and the development
   journey;
7. ask the primary model or user only for ambiguity, approval, high-risk
   judgment, conflict resolution, and the final green signal;
8. learn reusable, sanitized lessons so later projects do not repeat verified
   mistakes;
9. save tokens by avoiding full-chat replay, full-catalog injection, repeated
   repository mapping, and duplicate research.

The product is one coordinator with many selectable role/skill profiles. It is
not intended to keep 150 models or 150 processes continuously running.

## 3. End-to-end target workflow

```text
User request in IDE/CLI
  -> Guardian intake and compact project-memory retrieval
  -> deterministic intent, risk, dependency, profile, and skill selection
  -> requirement preview and exact user confirmation
  -> durable orchestration and execution plan
  -> cheapest adequate worker:
       deterministic code / Ollama / FreeBuff / Aider / OmniRoute
  -> bounded executor ticket
  -> isolated implementation and focused tests
  -> independent review when risk requires it
  -> primary Codex/Claude/Gemini or user gives final green signal
  -> fresh verification
  -> journey, decision, lesson, evaluation, and cost evidence persisted
  -> compact handoff available for the next session or project
```

The primary model remains the authority. Workers may propose or implement
bounded changes, but they do not silently approve policy gates, legal actions,
payments, releases, or final acceptance.

## 4. Core architecture

### 4.1 Project brain

Each initialized project receives a local `.agent/` brain containing confirmed
requirements, plan state, decisions, lessons, journey entries, research
records, task/execution records, audit artifacts, and compact handoffs.

Important behavior:

- requirement changes are appended to the journey instead of replacing project
  history;
- compact context is selected for the current task;
- reusable lessons remain private to the project unless the user explicitly
  approves a sanitized cross-project export;
- secrets and raw private artifacts must not be copied into handoffs.

### 4.2 Orchestration and 150 profiles

The repository packages the planned 150 specialist profiles across 10 domains:

1. intake and orchestration;
2. product and UX;
3. software architecture;
4. coding;
5. specialized engineering;
6. quality and debugging;
7. DevOps and operations;
8. security and governance;
9. data, research, and knowledge;
10. business and communication.

Profiles are role metadata selected deterministically for a task. Guardian
expands only the relevant profiles into a handoff. Current evaluation evidence
reports an estimated 98.6% context reduction for a representative selection
compared with loading the complete catalog.

### 4.3 Skill system

Guardian currently includes:

- built-in compact engineering skills for brainstorming, planning, TDD,
  systematic debugging, two-stage review, verification, and worktrees;
- a local-model skill factory for bounded draft generation;
- static and semantic evaluation;
- revision history and rollback copies;
- quarantined external-skill import with provenance and risk scanning;
- explicit one-time approval before a draft becomes trusted;
- private learning candidates and approval-gated sanitized cross-project
  lessons.

Generated or imported content is not trusted merely because a model produced
it. Future work should add cryptographic signing, stronger isolated execution,
and calibrated forward-task evaluation.

### 4.4 Provider and budget layer

The gateway supports local Ollama and OpenAI-compatible providers, including
the user's local OmniRoute. It includes:

- live model/combo discovery;
- prohibited-model checks, including transitive combo-member checks;
- free, free-limited, subscription, and paid access policy;
- persistent daily token/cost budgets;
- preflight reservation and actual-usage settlement;
- bounded failover;
- streaming with explicit partial-stream safety restrictions;
- provider capacity, latency, retry, prompt-inflation, and redacted log
  telemetry;
- zero-completion model-catalog probes;
- versioned routing and quality evaluation history.

Never route to `claude-sonnet-4.6`, directly or as a combo member.

### 4.5 Execution governor and supervisor

The execution governor persists ordered fallback stages such as Ollama,
FreeBuff, OmniRoute, final review, and primary review. Executors must use
explicit claim leases and record bounded results/evidence.

The new supervisor is deliberately smaller than an autonomous worker. It:

- inspects nonterminal execution records;
- recovers expired claim leases;
- writes or updates one deduplicated ticket for the current pending stage;
- marks prohibited routes blocked;
- marks primary review as `awaiting_primary_review`;
- maintains a bounded state history;
- supports one cycle, read-only status, or a bounded foreground loop;
- respects the persistent emergency stop and a non-blocking single-instance
  lock.

It never calls models, networks, FreeBuff, Aider, browsers, MCP tools, or shell
commands. It never claims stages, records results, or approves primary review.

Commands:

```bash
guardian supervisor once --project /path/to/project
guardian supervisor status --project /path/to/project
guardian supervisor run --project /path/to/project \
  --interval-seconds 600 \
  --max-cycles 6
```

### 4.6 Tools and integrations

Implemented foundations include:

- Aider adapter for local Ollama or local OmniRoute, with dry-run default,
  analytics disabled, auto-commit disabled, and compact profile handoffs;
- FreeBuff adapter for user-controlled interactive sessions and compact
  handoffs;
- secure local stdio MCP registration, trust, tool discovery, schema pinning,
  read/write allowlisting, and approval-gated writes;
- bounded visible-browser navigate/click/fill/screenshot/submit actions;
- real git worktrees, rollback controls, and cross-tool bootstrap files;
- citation-grounded compact research with public-HTTPS/SSRF controls and
  prompt-injection indicators;
- opt-in multi-model council deliberation;
- deterministic zero-completion maintenance jobs;
- debugging evidence ledgers and adaptive engineering workflows.

These are foundations, not permission for unrestricted autonomous activity.

## 5. Identity, browser, and subscription boundary

The long-term product may use accounts and subscriptions the user owns, such
as Canva, Adobe, Lovable, development services, or approved APIs, but only
within the account's actual permissions and the service's rules.

Required safety boundary:

- login/logout may use a user-authorized account and approved local credential
  storage;
- the user may grant a one-time setup or consent that can be recorded with a
  narrow scope and revocation path;
- account creation, payment, identity verification, CAPTCHA, legal acceptance,
  publishing, deletion, or a new unapproved site requires explicit user
  involvement or approval as appropriate;
- the agent must not evade CAPTCHA, fabricate identity, abuse free tiers, create
  deceptive accounts, or disguise automation as a human;
- credentials belong in an encrypted vault or OS keychain, never Markdown,
  logs, source control, or model prompts;
- every other installation must use that user's own accounts, subscriptions,
  browser profiles, credentials, and provider configuration;
- this project may use the developer's local OmniRoute for development, but
  the distributed product must not depend on it.

When a free quota is nearly exhausted, Guardian may discover legitimate
alternatives and prepare setup instructions. It must not evade provider limits,
silently enroll in unrelated services, or accept terms on the user's behalf.

## 6. Free-resource operating strategy

### 6.1 Default routing order

1. Deterministic Guardian functions.
2. Local Ollama.
3. FreeBuff for a bounded repository job when its service is usable.
4. Aider using Ollama or an audited local OmniRoute combo.
5. OmniRoute specialist/fallback or independent reviewer.
6. Primary Codex, Claude, Gemini, or user for final authority.

### 6.2 Intended responsibilities

| Resource | Use for | Do not use for |
|---|---|---|
| Guardian | intake, policy, retrieval, routing, budgets, durable state | generative calls when deterministic work is enough |
| Ollama | private summaries, repository maps, triage, first drafts, ordinary local work | final high-risk approval |
| FreeBuff | one confirmed bounded coding task and focused tests | secrets, unrelated files, commits, pushes, or approval bypass |
| Aider | bounded local edits with explicit editable/read-only files | uncontrolled whole-repository changes |
| OmniRoute | a missing specialty, stronger fallback, or independent review | unbounded fan-out across every combo |
| Primary model/user | ambiguity, conflict, high-risk review, final green signal | repeating already verified routine work |

### 6.3 Current local resource observations

- Ollama was reachable during the latest host-level check and advertised:
  `Mythos-nano:Q8_0`, `qwen2.5-coder:14b`, `gemma3:12b`, and `qwen2.5:14b`.
- The local OmniRoute dashboard/API was reachable at `localhost:3000`.
- Immediately before the latest delegated job, the
  `claude-3.5-sonnet` combo contained 13 Gemini/GPT-OSS members and no
  prohibited model.
- Aider `0.86.2` successfully completed the supervisor CLI/documentation job
  through that local combo.
- FreeBuff `0.0.128` launched but its selected remote sessions remained stuck
  during connection/startup. It did not create the requested supervisor files.
  Two bounded connection attempts were stopped instead of consuming more
  sessions. Do not report FreeBuff as a working coding worker until a real task
  produces a patch or evidence.

Local services and background scripts must be rechecked in every new terminal
or session. Do not assume a process is still running because an earlier note
said it was started.

Helper scripts currently exist at:

- `scripts/background_ollama_tracker.sh`
- `scripts/background_omniroute_assistants.sh`

Review their configuration before running them. They cannot wake or reactivate
a chat model by themselves; they can only write evidence for the next session.

## 7. Fresh verification evidence

Latest verification was run after Phase 4 Hardening and Phase 5A Control Plane Complete Closure on 2026-07-27:

```text
Phase 4 & 5A Hardening suite: 8 tests passed
Focused execution suite: 37 tests passed
Ticket executor worker suite: 10 tests passed
Supervisor suite: 20 tests passed
Local service & backup suite: 23 tests passed
Bootstrap harness suite: 3 tests passed
IDE adapter hardened suite: 24 tests passed
Phase 5 security, account & connector suite: 20 tests passed  (URL security: 10, Accounts: 7, Connectors: 3)
Runtime multi-process suite: 7 tests passed
Complete repository suite: 288 tests passed
Python compileall: passed
git diff --check: passed
```












Commands:

```bash
cd "/media/lalit/HIKVISION1/AI agent model"
PYTHONPATH=src python3 -m unittest discover -s tests -q
python3 -m compileall -q src tests
git diff --check
```

The suite emits some intentional JSON from existing CLI tests. That output is
not a failure when the command exits successfully and reports `OK`.

## 8. Current worktree state


The worktree contains a large intended, uncommitted implementation built after
commit `47b2470`. It has both modified tracked files and many new untracked
source/test files.

Important rules:

- do not reset, checkout, clean, or overwrite the dirty worktree;
- preserve unrelated untracked `"test folder/"`;
- do not commit or push unless the user explicitly requests it;
- inspect staged/unstaged/untracked changes before any delivery;
- `.aider.chat.history.md` and `.aider.input.history` are local worker artifacts
  and should be reviewed before deciding whether to keep, ignore, or remove
  them.

Major new implementation modules include:

```text
src/guardian_agent/aider.py
src/guardian_agent/bootstrap.py
src/guardian_agent/browser_operator.py
src/guardian_agent/budget.py
src/guardian_agent/citations.py
src/guardian_agent/debugging.py
src/guardian_agent/evaluation.py
src/guardian_agent/execution.py
src/guardian_agent/executor_worker.py
src/guardian_agent/external_skills.py
src/guardian_agent/learning.py
src/guardian_agent/maintenance.py
src/guardian_agent/model_policy.py
src/guardian_agent/omniroute_logs.py
src/guardian_agent/orchestration.py
src/guardian_agent/profiles.py
src/guardian_agent/provider_capacity.py
src/guardian_agent/runtime.py
src/guardian_agent/service.py
src/guardian_agent/supervisor.py
src/guardian_agent/workflow.py
src/guardian_agent/builtin_skills/
```

New tests exist for each major module, including
`tests/test_runtime.py`, `tests/test_supervisor.py`, `tests/test_execution.py`,
`tests/test_executor_worker.py`, and `tests/test_service.py`.

Always begin a resumed session with:

```bash
git status --short
git diff --check
```


## 9. Implemented status

The following system core is present and fully verified:

- project brain, requirement confirmation, journey, lessons, and compact
  exports;
- encrypted vault and approval/policy engine;
- provider registry, discovery, routing, failover, streaming, budgets,
  capacity, log health, and evaluation;
- Ollama and OmniRoute integration adapters;
- FreeBuff and Aider worker adapters;
- 150 specialist profiles and compact deterministic routing;
- built-in skills, skill generation/evaluation/revision, and external skill
  quarantine;
- orchestration, adaptive workflow, debugging ledger, execution governor, and
  bounded supervisor;
- **process-safe task runtime** with `fcntl` file locking, `os.replace` atomic write replacement, `os.fsync`, and corrupted JSON recovery (Phase 1);
- **ticket executor worker** (`executor_worker.py`) that claims stage leases, checks model policies, runs bounded tasks, and records results (Phase 2);
- **local service & brain backup/restore** (`service.py`) with `systemd`/`launchd` config generator and tarball archive backup/restore (Phase 3);
- **cross-tool bootstraps** (`bootstrap.py`) supporting root harness files for 6 target IDEs (Phase 4);
- citations, learning library, maintenance, worktrees, MCP, browser action
  foundations, and LLM Council deliberation protocol.

“Implemented status” means core functionality is built and backed by 239 passing tests, though full multi-user production deployment remains to be packaged.

## 10. Known gaps and risks

### 10.1 Resolved engineering items

- **[RESOLVED] Concurrency & State Integrity Hardening:** `runtime.py` now uses `fcntl` file locks and atomic temp file `os.replace` for process-safe writes.
- **[RESOLVED] Production Ticket Executor Worker:** Built `executor_worker.py` to consume tickets, claim stage leases, check policies, and execute tasks.
- **[RESOLVED] Local Service & Backup:** Built `service.py` for local service runs, daemon config generation, and archive backup/restore.

### 10.2 Production gaps (Remaining)

- provider-specific official quota endpoints and broader calibrated model/code
  benchmarks;
- OS-keychain integration and complete account/profile lifecycle;
- persistent browser sessions, visible manual user takeover mid-task, and duplicate-submit recovery;
- official Canva, Adobe, Lovable, and creative subscription connectors;
- cryptographic trusted-skill signing and isolated forward-task evaluation;
- review/commit/PR adapters;
- multi-user/tenant isolation and administrator controls;
- installer, upgrades, migration compatibility, packaging, release signing, and
  rollback;
- full end-to-end adversarial/security evaluation and independent security review.

## 11. Implementation plan status

### Phase 1 — Concurrency and state-integrity hardening `[COMPLETED & VERIFIED]`
Goal: Process-safe runtime queue and lock state under multiple local processes.
Status: Implemented in `runtime.py` with process-safe lock upgrades and atomic file replacement; verified with multi-process `ProcessPoolExecutor` tests in `test_runtime.py`.

### Phase 2 — Ticket executor worker `[COMPLETED & VERIFIED]`
Goal: Consume supervisor tickets, re-validate against canonical current stages, claim stage leases, execute via adapters, redact provider errors, and record results safely.
Status: `executor_worker.py` now uses a durable `dispatched` stage state instead of treating handoffs/model text as terminal `skipped` results. The current stage remains fixed while awaiting verification, and the returned lease plus random dispatch ID are required by `guardian execution record`. Exact replays are idempotent, stale or mismatched results are rejected, timed-out dispatches fail safely into the next fallback, and persisted tickets leave `ready` so the service cannot dispatch them twice. Together with fail-closed route resolution, canonical ticket revalidation, bounded discovery, secret redaction, and safe dry-run behavior, this completes the local verification lifecycle. Verified by 37 execution tests and 10 executor-worker tests.


### Phase 3 — Installable local service `[COMPLETED & LOCALLY VERIFIED]`
Goal: Local foreground service loop, heartbeat health tracking, daemon configs, isolated multi-project naming, service lifecycle control, logging with rotation, schema migration with rollback, and transactional brain backup/restore.
Status: `service.py` provides daemon lifecycle control (`install`, `start`, `stop`, `uninstall`), multi-project unique service naming (`guardian-agent-<slug>-<hash>.service`), systemd specifier escaping (`%%`), launchd single XML escaping, daemon enablement (`systemctl enable`), executable-path resolution with a portable Python fallback, heartbeat tracking (`interval * 2.5` dynamic TTL), single-instance locking (`.service.pid.lock`), log rotation (`service.log`), explicit schema v1-to-v2 migration with pre-upgrade backup and tested rollback, and transactional brain restore with move-failure rollback. The migration CLI defaults to the latest supported schema. The end-to-end governance test records an authenticated asynchronous worker result and reaches the final-review gate, while a simulated process crash proves the service lock is released for daemon restart. Verified with 23 tests in `test_service.py`. Actual systemd/launchd startup and reboot behavior remain an installation-environment validation item because the current sandbox has no user systemd bus; this is not represented as locally verified evidence.





### Phase 4 — IDE and coding-tool adapters `[COMPLETED & VERIFIED]`
Goal: Portable bootstraps, root harness generation, tool discovery, fresh bounded handoffs, lease callbacks, tool launching, and clean uninstall for 6 target IDE/coding tool environments (VS Code, Codex, Claude Code, Gemini, Antigravity, Cursor).
Status: `adapters.py` implements the Phase 4 Unified Adapter Contract across all 6 targets with complete production hardening. All functional blockers are fully resolved:

1. **Rich Task & Scoped Context** — Handoff packages include `task`, confirmed `requirements`, `acceptance_criteria`, `allowed_paths`, and `review_required`. Protected files (`.env`, `.env.*`, `vault*`, `.agent/vault*`, credentials) are strictly excluded. Allowed paths are explicitly bound to `ExecutionStage` (fail-closed if unapproved).
2. **Durable Crash-Safe Dispatch & Startup Reconciliation** — `_execute_handoff_transaction()` performs stage dispatch and atomic package file creation. If package creation or file write fails, `revert_execution_dispatch()` rolls back stage state. `reconcile_dispatched_handoffs(brain)` runs at startup to safely restore any stage left in `dispatched` state without a valid package file (e.g. process kill / power failure).
3. **CLI Verification Evidence Input** — `guardian adapter record` accepts `--verification-results` as a JSON string, JSON file path, or `check:result` key-value list.
4. **Persistent Identity & Target Binding** — `ExecutionStage` permanently binds `adapter_target` and a 256-bit `adapter_token` during dispatch. Result submission validates target, token, and artifact paths against `allowed_paths`.
5. **Strict Verification Evidence Validation** — `outcome='passed'` strictly validates `verification_results`, correctly accepting `0 errors` and `12 passed`, while rejecting empty checks, missing results, `not passed`, `skipped`, or failing status keywords.
6. **Robust JSONC Settings Parser** — `_strip_jsonc_comments()` correctly handles block comments inside string literals and strips JSONC trailing commas **only outside string literals**, preserving strings like `"val": "keep,}"`.
7. **Tool Launching & Environment Status Verification** — `guardian adapter launch --target <target> --run` and `launch_adapter_tool(execute=True)` return binary paths, commands, and execution status. Codex & Claude Code are verified with exit 0. VS Code & Antigravity report `installed: True`, `verified: False`, `unavailable_in_environment: True` under headless Snap confinement.
8. **Clean Uninstall & Protection** — Root harnesses are distinctly mapped (`.vscode/GUARDIAN.md` vs `GUARDIAN.md`), user-owned files are protected, and uninstall cleanly cleans up generated entry points.

Supported by CLI subcommands `guardian adapter detect|generate|handoff|record|launch|uninstall`. Verified by **23 adapter unit tests** in `test_adapters.py` and **262 total unit tests** across the entire repository.





### Phase 5 — Browser and subscription connectors `[IN PROGRESS — FOUNDATION & SECURITY IMPLEMENTED]`
Goal: Safely use user-owned web and creative subscriptions (Canva/Adobe/Lovable).

Status: Core security foundation, account registry with path traversal prevention, persistent browser profile locks, typed browser action policies, URL SSRF/DNS security layer, durable idempotency ledger, and mock/unconfigured connector scaffolding for Canva, Adobe, and Lovable are implemented:

1. **URL & SSRF Security Layer** — `security_url.py` validates URL schemes (`https://` default), performs DNS IP resolution (failing closed on DNS lookup errors), blocks private networks (`localhost`, `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local metadata (`169.254.169.254`), embedded credentials (`user:pass@host`), and unsupported schemes (`file://`, `data:`, `javascript:`). Integrated into `inspect_web_page()` and `execute_browser_action()` in `browser_operator.py`.
2. **Typed Browser Action Policy & Approval Hardening** — `policy.py` classifies typed browser actions (`navigate`, `read`, `fill_nonsecret`, `fill_credential`, `publish`, `purchase`, `delete`, `create_account`, `accept_terms`, `identity_verification`, `submit`). Enforces atomic file locking, user ID tracking, canonical target, evidence fields, and `unknown_outcome` state handling.
3. **Account Registry & Path Traversal Security** — `accounts.py` enforces strict `_validate_account_id()` preventing path traversal (`../..`), manages vault references (`vault:<key>`), isolated persistent Playwright profile directories (`.agent/browser_profiles/<account_id>/`), profile-level process locks (`ProfileLockManager`), and session revocation controls.
4. **Connector Scaffolding & Durable Idempotency Ledger** — `connectors.py` defines standard `BaseConnector` contract, enforces vault authentication resolution (returning `status="authentication_required"` when missing), tracks operations in `IdempotencyLedger` to return cached receipts on duplicate requests, and explicitly reports connector status as `mock` or `not_configured`. Real API / visible browser integrations for Canva, Adobe, and Lovable remain pending.


Acceptance:
- No CAPTCHA bypass, deceptive identity, silent legal acceptance, or unauthorized account creation;
- Payment/publish/delete actions require appropriate explicit approval;
- User can see, modify, stop, and revoke the agent's access.

### Phase 6 — Packaging, evaluation, and production gate
Goal: Produce a secure open-source release candidate.

## 12. How to assign the next bounded worker task

Every worker handoff should contain:

- one exact goal;
- allowed editable files;
- read-only reference files;
- acceptance criteria;
- focused test command;
- prohibited actions and models;
- token/time/retry bounds;
- requirement to report changed files, evidence, assumptions, and risks.

Recommended next task:

```text
Complete one bounded Phase 4 production-hardening item.
Allowed editable files: define narrowly for the selected item
Read-only reference:    GUARDIAN_AGENT_PROJECT_PLAN.md, GUARDIAN_PROJECT_HANDOFF.md
Prohibited models:      claude-sonnet-4.6 (directly or transitively)
Validation:
  PYTHONPATH=src python3 -m unittest discover -s tests -q
  python3 -m compileall -q src tests
  git diff --check
```

Before using an OmniRoute combo:

1. query the live combo definition;
2. inspect every member transitively;
3. reject the route if any prohibited member appears;
4. check recent redacted failures/capacity;
5. reserve final-review capacity;
6. dispatch only compact context and allowed files.

## 13. Restart checklist

1. Read this file, `GUARDIAN_AGENT_PROJECT_PLAN.md`, and the relevant README
   section.
2. Run `git status --short`; preserve all unrelated work.
3. Run the 214-test baseline before making broad changes.
4. Check local Ollama/OmniRoute/FreeBuff status; do not rely on stale process
   notes.
5. Select one bounded phase/task.
6. Record the goal and allowed files in a handoff.
7. Delegate routine work to a free/local resource when suitable.
8. Review the patch rather than trusting a worker's completion claim.
9. Run focused tests, full tests, compileall, and `git diff --check`.
10. Update this handoff, the project plan, README, and development journey.
11. Commit or push only after explicit user instruction.


## 14. Current resume point

Phase 1 (Concurrency Hardening) is complete & verified with multi-process tests.
Phases 2-4 have foundations implemented and hardened:
1. **Phase 1 Concurrency & State Integrity Hardening:** `runtime.py` implemented with `fcntl` file locking, lock upgrade on corruption recovery, atomic temp replacement, `os.fsync`, and multi-process tests.
2. **Phase 2 Ticket Executor Worker:** completed with fail-closed exact route resolution, canonical metadata revalidation, durable asynchronous dispatch IDs, authenticated verified-result recording, idempotency, timeout fallback, consumed-ticket persistence, safe dry-run behavior, and CLI integration (`guardian executor ready/run`, `guardian execution record --dispatch-id ...`).
3. **Phase 3 Installable Local Service & Backup:** completed locally with daemon lifecycle control, isolated per-project units, enablement, dynamic heartbeat TTL tracking (`interval * 2.5`), bounded history, indefinite loop, safe systemd/launchd path handling, schema v2 migration and rollback, crash/restart recovery coverage, verified-result progression to final review, backup overwrite protection, and transactional restore rollback.
4. **Phase 4 Cross-Tool Harness & Root Bootstraps:** `bootstrap.py` enhanced with root harness generation (`--root`) for 6 target IDE environments.

Fresh evidence: 243 total unit tests passing, compileall clean, `git diff --check` clean.

