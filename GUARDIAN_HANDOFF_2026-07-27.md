# Guardian Agent — Daily Handoff for 2026-07-28

Prepared: 2026-07-27 (Asia/Kolkata)  
Repository: `https://github.com/LearnAiWithLalit/Personal_AI_Model`  
Workspace: `/media/lalit/HIKVISION1/AI agent model`  
Branch: `main`  
Committed base at handoff: `08dbceb`  
Remote state at handoff: `main` matched `origin/main` before the uncommitted
plan/handoff documentation changes.

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

- Full local suite: **294 tests passed**.
- Source and tests compiled.
- `git diff --check` passed.
- The 150-profile catalog remained valid.
- The committed post-`b37f601` work consists of:
  - `2d1d299`: connector owner-token and unknown-outcome foundation;
  - `a0932af`: browser selector preflight and takeover-control foundation;
  - `4c7ea3c`: Canva/Adobe/Lovable connector scaffolding plus the JCode plan;
  - `08dbceb`: supervisor daemon-loop foundation.
- `GUARDIAN_AGENT_PROJECT_PLAN.md` was updated locally today with:
  - an accurate post-`b37f601` completed/partial/pending audit;
  - the verified 294-test count;
  - the optional Colibri next-phase plan.
- This dated handoff and the plan changes are uncommitted at the time this note
  is written.

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

### Still pending

- Genuine browser unknown-outcome reconciliation and duplicate-submission
  prevention.
- Official authorized remote connectors and GitHub/PR workflows.
- OS-keychain integration and production credential/session lifecycle.
- Cryptographic skill signing and isolated real-task forward evaluation.
- Multi-user isolation, release packaging, production telemetry/incidents,
  supply-chain review, and production threat modelling.

## 4. Blocking findings to reproduce first

Today’s direct adversarial checks produced these results even though all 294
existing tests passed:

```text
mark_unknown_without_owner_token = accepted
completed_receipt_overwritten = {'receipt': 2}
live_reserved_reconciled_without_owner = cancelled
daemon_total_processed = 0 after two mocked executed results
active_providers = [] with a healthy mocked capacity route
```

The connector audit also verified:

```text
authenticated = False
remote_authenticated = True
```

when only a local credential was present. The Canva non-mock list operation
returned a hard-coded local design. Adobe and Lovable also return synthesized
records or placeholder files. No official remote API or browser fallback is
called by these connector methods.

Convert the following into permanent tests before or with the fixes:

1. A reserved connector operation cannot be marked `unknown_outcome` without
   its exact owner token.
2. `complete()` accepts only the `reserved` state and cannot overwrite a
   completed receipt.
3. Reconciliation accepts only `unknown_outcome`, requires an authorized
   approval/operator and owner/reconciliation token, and cannot cancel a live
   reservation without proof.
4. A stale reservation becomes `unknown_outcome` and is never blindly retried.
5. Supervisor processed totals use the executor’s actual `executed` result.
6. Supervisor capacity reporting consumes the `routes` schema returned by
   `provider_capacity_status()`.
7. `max_workers` either provides real bounded concurrency or is renamed so it
   does not claim concurrency.
8. Credential availability is never reported as successful remote
   authentication.
9. Non-mock connectors either perform a verified authorized remote/browser
   operation or fail with `ConnectorNotConfigured`; they never return
   fabricated success.

## 5. Tomorrow’s implementation order

### Priority 1 — connector lifecycle correctness

- Require the exact owner token for `mark_unknown`.
- Require state `reserved` for first completion.
- Make completed receipts immutable and replay-safe.
- Restrict reconciliation to `unknown_outcome`.
- Bind reconciliation to exact account, connector, operation, authorized
  approval/operator, reason, and reconciliation evidence.
- Add concurrent reservation/completion/crash tests.

### Priority 2 — supervisor correctness

- Fix `processed` versus `executed` accounting.
- Read capacity from the returned `routes` list.
- Implement real bounded concurrent ticket execution or rename the setting to
  `max_tickets_per_cycle`.
- Add worker heartbeat, safe drain/shutdown, crash recovery, and concurrency
  tests.
- Keep emergency stop and manual primary review fail-closed.

### Priority 3 — browser reliability

- Add overlay, navigation, stale-element, and final-actionability checks.
- Create durable submission fingerprints and receipts.
- Reconcile page state, transaction IDs, activity history, or service receipts
  before retrying an unknown action.
- Attach manual takeover to the exact in-flight authenticated context/page
  rather than replacing it with a standalone takeover page.
- Add a real headful end-to-end takeover test when the environment permits.

### Priority 4 — real connectors

- Remove “real API” claims until a connector actually calls an official
  authorized endpoint.
- Implement official capability/authentication checks for Canva, Adobe, and
  Lovable where supported.
- Otherwise use a Guardian-policy-gated visible browser session.
- Preserve exact allowed domains, account scope, approvals, idempotency,
  evidence, revocation, and user takeover.
- Continue later with VS Code, Claude Code, Gemini/Antigravity, Codex, and
  GitHub/PR connectors.

### Priority 5 — learning and production hardening

- OS keychain, credential rotation/expiry, session recovery.
- Cryptographically signed trusted skills.
- Isolated real-task forward evaluation.
- Multi-user/tenant isolation.
- Installer/upgrader, release packaging, incident telemetry, end-to-end
  security evaluation, dependency/SBOM review, backup drills, and threat model.

## 6. JCode next-phase plan

JCode is optional and must remain a replaceable bounded worker, not Guardian’s
policy authority or mandatory dependency.

Planned `JCodeAdapter` boundaries:

- detect binary/version/capabilities without a model call;
- dry-run by default;
- send only confirmed compact context and exact writable paths;
- sandbox/worktree execution, timeout, cancellation, structured result and
  diff validation;
- Guardian-controlled concurrency/swarm cap;
- no automatic credential scanning/importing/account switching;
- set `JCODE_NO_TELEMETRY=1` for Guardian-launched sessions unless the user
  explicitly opts in;
- disable JCode self-development;
- never allow JCode to modify Guardian policy, vault, brain, approvals, or
  worker configuration;
- keep browser actions behind Guardian URL/account/approval/idempotency policy;
- require primary-model review before completion.

Do not install, authenticate, or run JCode tomorrow unless it is part of the
confirmed task and the user has approved any required setup.

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

## 8. Completion gate for tomorrow

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

