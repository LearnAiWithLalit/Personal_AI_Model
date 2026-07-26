# Guardian Agent — End-to-End Project Plan

## 1. Purpose

Build a local-first, persistent **Guardian Agent** that manages a project from requirement discovery through delivery.

The Guardian is the permanent brain. Coding models and tools (Codex, Claude, Gemini, local models, VS Code, browser automation, Canva, Adobe, Lovable, and future services) are replaceable workers.

The product must:

- Understand and confirm the user’s goal before expensive implementation begins.
- Keep a durable, human-readable record of the project journey.
- Reuse validated skills and lessons across future projects.
- Route tasks to the lowest-cost capable model or deterministic tool.
- Work with a user’s own accounts, models, subscriptions, and local machine.
- Allow users to watch, modify, pause, or take over work at any time.
- Remain independent of the developer’s personal OmniRoute instance and credentials.

## 2. Product Model

```text
User
  <-> Guardian Agent (persistent brain)
        |- Project Brain: requirements, plans, decisions, lessons, audit
        |- Model Gateway: local/Codex/Claude/Gemini/other providers
        |- Research & Planning: web and repository analysis
        |- Skill Factory: creates, tests, and versions reusable skills
        |- Computer Operator: browser, desktop apps, terminal, files
        |- Specialist Workers: coding, testing, design, review, deployment
        `- Verification & Policy: permission, testing, security, final report
```

The user sees one agent. The Guardian decides whether it should work itself, call a tool, or delegate a bounded task to a worker.

## 3. Principles and Non-Negotiable Rules

1. **Local-first and portable.** Each user owns their own installation, project brain, accounts, and provider configuration.
2. **Models are replaceable.** No core workflow is coupled to one vendor or subscription.
3. **Memory is compact and useful.** Reuse summaries, decisions, lessons, and artifacts—not full historic conversations.
4. **Skills are earned.** New skills begin as drafts, must be validated, and are versioned.
5. **Use the cheapest capable resource.** Use deterministic tools and local/low-cost models where possible; reserve stronger models for difficult work.
6. **The user remains in control.** The system always has a visible activity log, pause/stop control, and manual takeover path.
7. **Credentials are secrets.** Never write passwords, cookies, API keys, or tokens into Markdown, Git, logs, or model prompts.
8. **No deceptive automation.** The Computer Operator may use authorized accounts and permitted service identities; it does not impersonate people, evade CAPTCHAs/MFA, bypass terms, or evade quotas.
9. **No cross-user data sharing by default.** Personal provider keys, account sessions, project memory, and browser profiles are isolated.
10. **Verify before completion.** A task is not complete merely because a model says so; use tests, browser checks, reviews, and acceptance criteria.

## 4. User Experience

### 4.1 Primary workflow

```text
User request
  -> Guardian analyzes existing project and relevant memory
  -> Guardian researches options and makes a concise proposal
  -> User confirms/revises requirements
  -> Guardian records scope and creates phased plan
  -> Guardian delegates compact work packages
  -> Guardian validates results and records journey/lessons
  -> User receives result, evidence, costs, and next steps
```

### 4.2 Action modes

| Mode | What the Guardian may do |
| --- | --- |
| Observe | Read files, inspect code, browse, research, summarize. |
| Assist | Prepare plans, code, forms, designs, and messages without submitting. |
| Authorized action | Perform pre-approved browser, app, terminal, and file actions. |
| Autopilot by policy | Continue approved repetitive workflows without per-action prompts. |
| Human checkpoint | Stop for payment, MFA, CAPTCHA, identity verification, legal acceptance, irreversible deletion, or new unapproved services. |

## 5. Project Brain Specification

Every managed project gets a durable `.agent/` directory:

```text
.agent/
  PROJECT.md              # mission, stack, owners, constraints
  REQUIREMENTS.md         # confirmed requirements and acceptance criteria
  PLAN.md                 # phases, tasks, dependencies, current status
  DECISIONS.md            # architecture and product decisions with reasons
  JOURNEY.md              # chronological development/change history
  CONTEXT.md              # compact current handoff context
  LESSONS.md              # reusable mistakes, fixes, and proven patterns
  TASKS.md                # task board and task artifacts
  COSTS.md                # model/tool/cost/time telemetry
  SKILLS.md               # enabled skills and versions
  research/               # source notes and comparison reports
  artifacts/              # designs, reports, screenshots, generated outputs
  audit/                  # action logs and evidence references
```

The Guardian updates these files after every material decision, requirement change, implementation phase, test result, or external action.

### 5.1 Required journey entry format

```md
## YYYY-MM-DD — Short change title

- User request/change:
- Reason:
- Affected plan/tasks/files:
- Decision made:
- Validation required/result:
- Reusable lesson, if any:
```

## 6. Model Gateway and Capacity Manager

### 6.1 Adapter architecture

```text
ModelGateway
  |- LocalModelAdapter
  |- OpenAI/CodexAdapter
  |- AnthropicAdapter
  |- GoogleAdapter
  |- OpenRouterAdapter
  |- NvidiaAdapter
  |- CustomOpenAICompatibleAdapter
  `- OmniRouteAdapter (development/testing adapter only)
```

Your local OmniRoute installation may be used during development. It must never be required by another user’s installation.

### 6.2 Provider modes

1. Local-only: models run on the user’s own machine.
2. Bring-your-own-key: each user supplies their own approved provider credentials.
3. Self-hosted gateway: a company operates its own provider router.
4. Optional managed service: possible future feature, but not a prerequisite.

### 6.3 Automatic capacity policy

```text
Simple routing, logging, summarization -> local/free model
Research and documentation -> local/low-cost approved model
Complex architecture or implementation -> strongest approved model
Formatting/tests/indexing -> deterministic tools whenever possible
Quota warning -> pre-approved fallback model/provider
No approved capacity -> concise user notification
```

The capacity manager records reliability, task quality, cost, rate-limit events, and useful fallbacks. It may research official provider documentation and legitimate free tiers, but must not seek leaked keys, create accounts to evade limits, or bypass provider rules.

## 7. Research and Requirement Confirmation

Before a major coding task, the Guardian creates a concise work proposal:

```text
Goal
Confirmed constraints
Relevant current-project context
Options researched
Recommended option and rationale
Files/components likely affected
Implementation phases
Risks and tradeoffs
Validation plan
Estimated model/tool use
Decision requested from user
```

The user may revise the request. Only the confirmed version is handed to coding workers.

## 8. Skill Factory and Learning Loop

### 8.1 Skill lifecycle

```text
Repeated/new workflow detected
  -> draft skill generated
  -> workflow, templates, tools, guardrails, and tests added
  -> evaluation on safe/relevant tasks
  -> promoted to trusted skill when criteria pass
  -> reused and measured in future projects
```

### 8.2 Skill structure

```text
skills/
  trusted/<skill-name>/
    SKILL.md
    metadata.json
    templates/
    checklists/
    tests/
  drafts/
  deprecated/
```

### 8.3 Learning boundaries

- Save lessons as concise patterns, causes, fixes, and prevention checks.
- Do not automatically rewrite the Guardian core or grant new permissions.
- Draft skills that require new access remain disabled until approved.
- Version every skill; support rollback and deprecation.
- Evaluate whether a lesson is relevant before injecting it into a new task.

## 9. Coding and IDE Integrations

### Initial targets

- VS Code extension.
- Local CLI.
- Codex adapter.
- Claude Code adapter.
- Gemini/Antigravity adapter where available.
- MCP server for compatible tools.
- Git, GitHub, and GitLab integration.
- Sandboxed terminal execution.

### Handoff package

Workers receive only relevant information:

```text
confirmed goal
acceptance criteria
relevant files and repository context
architecture decisions and constraints
current plan step
relevant trusted skills/lessons
validation commands
expected deliverable
```

This avoids repeatedly sending full chat/project history and is the primary token-saving mechanism.

## 10. Computer Operator

### Responsibilities

- Operate authorized browser sessions, desktop applications, terminal, and files.
- Open pages/apps, click, type, scroll, upload, download, and navigate.
- Test rendered web experiences with screenshots and evidence.
- Use separate project/account browser profiles.
- Enable user observation and instant manual takeover.
- Record actions and results in the audit log.

### Security model

- Store credentials only in an encrypted vault or OS keychain.
- Store only `vault://` references in project memory.
- Use domain/service allowlists and least-privilege permissions.
- Redact secrets from screenshots, logs, and model context.
- Keep browser profiles and task sandboxes isolated.

The operator may manage project-owned, policy-approved service identities after one-time setup. It pauses for payment, identity verification, CAPTCHA, MFA, legal acceptance, and unsupported/high-impact actions.

## 11. Creative Subscription Integrations

The Guardian can use accounts the user already owns, such as Canva, Adobe, Lovable, and future creative/design subscriptions.

### Creative workflow

```text
User asks for a landing page, brand assets, or design
  -> Guardian selects approved Canva/Adobe/Lovable profile
  -> uses official API/plugin where available, otherwise visible browser/app session
  -> creates draft assets or projects within subscription permissions
  -> records artifact links/screenshots in project brain
  -> user may open the same account/session and modify work manually
  -> Guardian observes the updated state and continues
```

Requirements:

- Use only access/features already provided by the user’s subscription.
- Do not bypass licensing, usage limits, safeguards, or access control.
- Support shared visibility, user edits, pause, and takeover.
- Keep account/session data private to that user profile.

## 12. Specialist Workers

Workers are added only after the Guardian core is stable. Initial worker set:

```text
Research Worker
Specification/Product Worker
Frontend Worker
Backend Worker
Database Worker
Test Worker
Browser/UI Test Worker
Security Review Worker
DevOps/Deployment Worker
Documentation Worker
Creative Worker
```

Workers return structured artifacts rather than lengthy agent-to-agent chats:

```text
research-summary.md
implementation-plan.md
patch.diff
test-results.json
security-review.md
design-assets/
```

## 13. Verification, Audit, and Completion

Every material task follows the quality gate:

```text
requirements confirmed
  -> plan approved
  -> implementation/artifact created
  -> tests/lint/build executed where applicable
  -> browser/UI checks run where applicable
  -> security/policy review applied
  -> user-facing summary and evidence produced
  -> journey and lessons saved
```

The completion report should include what changed, validation evidence, unresolved risks, next steps, tool/model usage, and whether user approval is required.

## 14. Security and Data Isolation

Required features:

- Encrypted credential vault integration.
- Per-user and per-project isolation.
- Per-service allowlists and permission scopes.
- Secret redaction.
- Action audit trail with time, target, result, and evidence reference.
- Pause/kill switch.
- Sandbox for terminal/browser work.
- Backup/recovery plus user memory export/delete controls.
- No sharing of personal provider configuration, browser sessions, cookies, or lessons unless a user explicitly exports a sanitized reusable skill.

## 15. Metrics and Evaluation

Track the following to prove the product improves over time:

- Requirement-confirmation accuracy.
- Task completion rate and validation pass rate.
- Repeated mistakes prevented by lessons.
- Skill draft-to-trusted promotion success rate.
- Token/cost saved compared with direct coding-agent use.
- Provider/model quality, cost, availability, and fallback success.
- Browser/desktop workflow success rate.
- User takeovers, policy blocks, and security incidents.

## 16. Implementation Phases and Acceptance Criteria

### Phase A — Foundation

Build product contracts, policies, data schemas, local configuration, and repository structure.

**Done when:** project policies are versioned and a local profile can be initialized safely.

### Phase B — Guardian and Project Brain

Build requirement intake, confirmation, plan tracking, `.agent/` files, context compaction, and journey logging.

**Done when:** a project can be created, changed, resumed, and understood without replaying chat history.

### Phase C — Independent Model Gateway

Build provider interface, local model support, development OmniRoute adapter, routing policy, quotas, fallback, and telemetry.

**Done when:** the Guardian completes representative tasks through local and at least two configurable provider adapters without coupling to OmniRoute.

### Phase D — Research and Compact Handoff

Build repository/web research, source comparison, user confirmation, and model-worker work packages.

**Done when:** a confirmed plan is consistently shorter and more actionable than raw user prompts while preserving requirements.

### Phase E — Skill Factory and Lessons

Build lesson extraction, skill drafts, validation, trusted-skill promotion, and versioning.

**Done when:** a repeated workflow becomes a tested reusable skill and prevents a documented past mistake.

### Phase F — VS Code/CLI and Coding Workers

Build the first user surfaces, selected coding-agent adapters, git workflow, execution sandbox, and verification loop.

**Done when:** a user can complete an end-to-end coding task from VS Code or CLI with project memory preserved.

### Phase G — Computer Operator

Build controlled browser/desktop/file operation, encrypted account profiles, visual evidence, action policy, and manual takeover.

**Done when:** the agent safely completes an approved web workflow and produces an auditable record.

### Phase H — Creative Subscriptions

Integrate Canva, Adobe, Lovable, and selected future tools through official integrations or user-visible sessions.

**Done when:** the user and Guardian can collaboratively create, edit, and preserve a design/project using an approved subscription.

### Phase I — Specialist Teams, Hardening, and Packaging

Add bounded workers, evaluations, security hardening, installer, documentation, profile export/import, and multi-user deployment modes.

**Done when:** another user can install the product, configure only their own providers/accounts, and run an isolated project successfully.

## 17. Recommended Build Order

1. Phase A: Foundation.
2. Phase B: Guardian + project brain.
3. Phase C: Independent model gateway; OmniRoute only as developer adapter.
4. Phase D: Research/confirmation and compact handoff.
5. Phase F: VS Code/CLI and coding loop.
6. Phase E: Skill factory and learning loop.
7. Phase G: Computer Operator.
8. Phase H: Canva/Adobe/Lovable integrations.
9. Phase I: worker teams, hardening, and distribution.

## 18. Scope Control

Do not start by implementing hundreds of agents. The first release should prove one complete loop:

```text
user requirement -> confirmation -> plan -> coding handoff -> validation
-> journey/lesson saved -> successful resume or reuse in next project
```

Once this loop is dependable, the system can add skills, models, providers, browser workflows, creative apps, and specialist workers without losing coherence.

## 19. Runtime, Trust, and Recovery Layer (Phase G0)

This phase is mandatory before browser, account, or background autonomy. It turns a CLI demonstration into a durable system that can safely continue work across crashes, restarts, provider failures, and user interruptions.

### 19.1 Durable task runtime

Build a local task engine with:

- Persistent task records, states, inputs, outputs, ownership, and timestamps.
- Queue priorities: interactive user work, normal project work, and low-priority background learning.
- Explicit task states: `draft`, `awaiting_confirmation`, `queued`, `running`, `awaiting_approval`, `blocked`, `failed`, `cancelled`, and `completed`.
- Idempotency keys so a retry cannot accidentally submit a form, deploy, or send a message twice.
- Checkpoints, pause/resume, cancellation, retry limits, exponential backoff, and timeout budgets.
- Scheduler support for health checks, capacity checks, skill evaluations, backups, and user-approved recurring tasks.
- Per-project locks and browser/profile locks so two workers cannot conflict over the same files or account session.
- Crash recovery: unfinished tasks resume only after their checkpoint and policy are revalidated.

### 19.2 Policy and approval engine

Replace ad-hoc permissions with versioned, machine-readable policy files.

```text
policy/
  default-policy.json
  project-policy.json
  service-policy.json
  approval-queue.jsonl
```

Policies must define:

- Allowed tools, domains, applications, accounts, file paths, commands, and networks.
- Cost/spend/token/time limits.
- Which actions are silent, user-visible, one-time approved, or always require approval.
- Escalation rules for new services, changed permissions, failed verification, and risky content.
- A user-visible emergency stop/kill switch that immediately stops queued and running work.
- Immutable audit references for every policy decision.

### 19.3 Recovery and continuity

- Encrypted backup of project brain, policies, task state, skill registry, and audit metadata.
- Restore drills that prove a project can be resumed on a fresh machine.
- Provider-failure fallback with a clear record of which work can safely retry.
- Versioned migrations for every persistent data format.
- Configurable retention periods and secure deletion/export for user data.

## 20. Identity, Accounts, Credentials, and Consent

### 20.1 Encrypted credential vault

Replace environment-variable-only secret resolution with a vault abstraction supporting:

- Operating-system keychain for personal/local deployments.
- Approved encrypted password managers or enterprise secret managers.
- OAuth authorization, refresh-token lifecycle, revocation, expiry detection, and rotation.
- `vault://` references in project files; never secret values.
- Per-project and per-service scopes, least privilege, and secret redaction from prompts/logs/screenshots.
- A secret-access audit that records the reference and purpose, never the value.

### 20.2 Account lifecycle

Define agent-managed identities clearly:

- User-owned accounts: the user authorizes access to their existing subscription/profile.
- Project-owned service accounts: allowed only for pre-approved services and purposes.
- Test identities: clearly labeled test users for the project’s own staging/test environments.
- Each account registry entry records service, owner, purpose, vault reference, permitted actions, creation date, recovery owner, expiry, and revocation status.
- Account creation is allowed only under standing authorization and service policy; stop for payment, identity verification, CAPTCHA, MFA, terms acceptance, or unsupported sites.
- Never create identities to evade free-tier limits, impersonate people, or conceal automated activity.

### 20.3 Consent and handoff UX

- First-run consent screen for provider, browser, account, data-retention, and background-learning permissions.
- Approval queue with clear description, impact, target, reversibility, and expected cost.
- User can approve once for a scoped recurring workflow, deny, edit policy, or take manual control.
- Every approval is linked to the task and policy version that consumed it.

## 21. Provider Health, Discovery, and Cost Control

### 21.1 Verified provider catalog

Provider discovery must use official websites, documentation, APIs, model registries, and explicitly authorized connectors. Each catalog record needs:

- Source URL and retrieval date.
- Terms/free-tier status, auth method, region restrictions, and official model identifiers.
- Capability, context limit, modality, tool support, price/quota, and provider status.
- Validation result, expiry/recheck date, and risk classification.

Hardcoded free model names are only development fixtures, never production discovery. The current `provider discover-free` command installs labelled development seeds; it must be replaced by verified catalog adapters before a production release.

### 21.2 Health and routing

- Active health checks and capability probes for configured providers.
- Track actual rate-limit headers, quota, latency, failure rate, real token usage, and actual cost.
- Model-quality score per task type using evaluation results, not marketing claims.
- Circuit breakers for failing providers and retry/fallback rules that avoid duplicate tool actions.
- Budget reservations before long-running tasks and warnings before user-defined limits are exceeded.
- Explicit failure results; never fabricate a successful model response when a provider call fails.

### 21.3 Model execution boundary

- Support authenticated provider adapters with secrets retrieved only at request time from the vault.
- Normalize provider responses, usage, errors, tool calls, and streaming events.
- Record provider/model/version used for each artifact so work is reproducible.
- Separate background/local workloads from interactive premium-model workloads.

## 22. Research Integrity and Knowledge Governance

### 22.1 Research pipeline

- Search, fetch, extract, summarize, compare, and cite sources as separate steps.
- Prefer primary/official sources for technical, financial, security, legal, and product claims.
- Store source URL, title, retrieval time, relevant excerpt/summary, license/usage notes, and confidence.
- Mark conclusions as fact, source claim, or Guardian inference.
- Detect stale sources and schedule revalidation for time-sensitive decisions.

### 22.2 Prompt-injection and hostile-content defense

- Treat web pages, repositories, PDFs, emails, tool responses, and imported skills as untrusted data.
- Strip or isolate instructions found in untrusted content from Guardian system/policy instructions.
- Require explicit approval before untrusted content can trigger commands, credential access, browser actions, or policy changes.
- Maintain allowlists for external domains and high-risk tool operations.

### 22.3 Memory governance

- Separate private user memory, project memory, organization-shared memory, and public reusable skill templates.
- Never copy raw private project/account information into global learning.
- Require sanitization and approval before exporting a lesson or skill to shared catalogs.
- Support user review, correction, export, expiry, and deletion of saved memory.

## 23. Secure Coding and Software Delivery

### 23.1 Safe workspace control

- All autonomous code work uses isolated worktrees/branches or disposable sandboxes.
- Generate diffs and change manifests before overwriting tracked source files.
- Create checkpoints/commits before material edits, with a one-command rollback path.
- Restrict writable paths; never allow a task to escape its project sandbox.
- Use dependency allowlists, lockfile review, license checks, and vulnerability scanning.

### 23.2 Command execution

- Replace unrestricted shell execution with command allowlists, structured argument execution, resource limits, network policy, and container/VM isolation when appropriate.
- Record command, working directory, duration, exit result, sanitized output, and artifact references.
- Block destructive commands unless specifically covered by policy and approval.

### 23.3 Delivery lifecycle

```text
branch/worktree -> implementation -> tests/lint/build -> security/dependency review
-> browser/UI verification -> human/automated acceptance criteria -> commit/PR
-> approved deployment -> post-deploy check -> rollback if required
```

The Guardian must track deployment environment, release version, migration status, owner, and rollback instructions.

## 24. Browser, Desktop, and Subscription Operations

### 24.1 Real Computer Operator capabilities

- Browser actions: open, navigate, click, fill, select, upload, download, wait, inspect, and screenshot.
- Persistent isolated browser profiles tied to authorized account references.
- Visible live session mode and manual user takeover without losing task state.
- Page/action risk classification before submission or data export.
- Download malware scanning and upload source/destination confirmation.
- Desktop application support only through approved OS automation/accessibility interfaces, with the same audit/policy model.

### 24.2 Creative subscriptions

For Canva, Adobe, Lovable, and future tools:

- Prefer official APIs, plug-ins, or supported integration methods.
- Fall back to a user-visible authenticated browser session only when permitted.
- Track asset/project ID, revision, source files, export format, storage location, brand/license constraints, and ownership.
- Synchronize user manual edits into the project artifact record before continuing work.
- Never bypass subscription limits, licensing, terms, or account controls.

### 24.3 Operator evaluation scenarios

- Login to a pre-authorized test account and complete a reversible workflow.
- Allow the user to take over mid-task and resume safely.
- Detect and stop on CAPTCHA/MFA/payment/legal acceptance.
- Verify screenshots/logs redact secrets and sensitive form values.
- Recover safely after browser crash, session expiry, or duplicate submission risk.

## 25. Skills, Plugins, and Supply-Chain Security

Every skill/plugin requires a signed or attributable manifest:

```text
name, version, author/source, description, permissions, tools, dependencies,
network domains, data classification, tests, evaluation results, trust status,
created date, updated date, rollback version
```

Rules:

- Generated skills are drafts and cannot gain new permissions automatically.
- Trusted skills run only after tests and policy checks pass.
- Imported skills/plugins are quarantined and inspected before activation.
- Skill execution uses least privilege and records version/provenance in task output.
- Support revoke, disable, pin, update, and rollback actions.

## 26. Multi-User, Organization, and Distribution Design

### 26.1 Identity and tenancy

- Local personal mode requires no central account by default.
- Team/organization mode needs user authentication, roles, project membership, service-account ownership, and tenant isolation.
- Define roles: owner, admin, member, reviewer, operator, and read-only auditor.
- Enforce per-user project paths, vault scopes, browser profiles, provider budgets, and audit visibility.

### 26.2 Deployment modes

- Personal local desktop/CLI installation.
- Team self-hosted service with company-managed providers and secrets.
- Optional future managed cloud control plane, with end-to-end isolation and explicit data residency policy.
- Import/export tooling for sanitized skills, project templates, and user-owned project brain backups.

### 26.3 Product updates

- Signed, versioned application and skill updates.
- Compatibility/migration checks before upgrade.
- Release notes that state changed permissions, data handling, and provider behavior.
- Safe rollback to the previous application/skill version.

## 27. Observability, Evaluation, and Incident Response

### 27.1 Observability

- Structured logs with task ID, project ID, user/actor, policy decision, model/provider, tool call, duration, and outcome.
- Trace a task through Guardian planning, model calls, worker handoffs, browser actions, tests, and deployment.
- Metrics: completion, quality, verification pass rate, user takeover rate, token/cost savings, provider health, policy blocks, and retry rate.
- Privacy-aware telemetry: no secret values or private content in central metrics.

### 27.2 Evaluation suite

Create versioned, reproducible end-to-end scenarios for:

- Requirement understanding and change tracking.
- Token-efficient handoff quality.
- Safe provider failover and cost limits.
- Skill generation/promotion/rollback.
- Coding, testing, review, and rollback.
- Browser workflow, human takeover, and policy checkpoints.
- Canva/Adobe/Lovable artifact collaboration where supported.
- Memory relevance and prevention of a documented repeated mistake.

Every release must pass the relevant safety, functional, and regression evaluations.

### 27.3 Incident handling

- Detect/report provider misuse, suspicious tool actions, secret exposure, failed policy enforcement, and corrupted task state.
- Immediate task pause, credential revocation workflow, evidence preservation, user notification, and recovery steps.
- Post-incident lesson and regression test before re-enabling affected skill/tool workflow.

## 28. Revised Implementation Order

1. Phase A — Foundation and versioned product/policy schemas.
2. Phase B — Guardian, project brain, confirmation, journey, and compact context.
3. Phase C — Independent model gateway with real provider execution boundaries.
4. Phase D — Research integrity, source citations, and compact handoff.
5. Phase E — Skill factory, memory governance, and evaluation/promotion flow.
6. Phase F — VS Code/CLI, secure coding worktrees, verification, and rollback.
7. **Phase G0 — Runtime, approvals, encrypted vault, provider health, observability, and recovery.**
8. Phase G — Real Computer Operator with browser/session/user-takeover controls.
9. Phase H — Canva/Adobe/Lovable and other subscription integrations.
10. Phase I — Specialist teams, organization deployment, hardening, installers, and release evaluation.

## 29. Production Readiness Gate

The system is not production-ready until it can demonstrate all of the following:

- Resume a paused project after restart without losing decisions, task state, or user control.
- Route work to a healthy, authorized provider and surface provider failure honestly.
- Keep secrets out of project files, logs, model context, screenshots, and exports.
- Prevent untrusted web/repository content from changing policy or triggering sensitive actions.
- Make/review/rollback code changes in an isolated workspace.
- Run an approved browser workflow with visible user takeover and no duplicate submissions.
- Respect account/subscription policy and stop at MFA, CAPTCHA, payment, legal acceptance, or new unapproved services.
- Create, test, promote, disable, and roll back a skill with full provenance.
- Prove token/cost savings and task-quality gains on the evaluation suite.
- Let a separate user install the product and use only their own accounts, providers, browser profiles, and project memory.

## 30. Implementation Status — 2026-07-26

### Implemented foundation

- Local project brain with requirements, confirmation, decisions, lessons, journey records, and compact handoff exports.
- Provider registry and low-cost routing; provider calls now resolve an environment or `vault://` credential only at request time.
- Authenticated encrypted local vault using a passphrase-derived Fernet key. Legacy obfuscated vault records are read only for one-time migration.
- Skill draft/promotion records, specialist-role handoff packages, task queue, locks, crash recovery, and emergency stop.
- Approval queue with exact action/target, one-time approval consumption, coding verification without a shell, and sandbox-copy rollback support.
- Browser inspection plus bounded Playwright navigate/click/fill/screenshot/submit actions. Submission is visible by default and policy-gated.
- Opt-in LLM Council protocol for safe analysis: independent model opinions, anonymized peer review, chairman synthesis, and retained deliberation artifacts. It is never a path to autonomous external action.
- Optional Freebuff interactive coding-worker adapter that builds a compact project handoff and launches/continues only user-controlled terminal sessions; it does not collect Freebuff credentials or evade service limits.
- Secure MCP stdio foundation with untrusted-by-default server registration, exact command trust approval, dynamic tool discovery, explicit read/write allowlisting, schema pinning, one-time approval for write calls, and audited results.

### Still required before production readiness

- Verified live provider catalog/discovery, quota/budget enforcement, streaming/failover, and real provider quality evaluation.
- OS-keychain integrations, profile/account registry, full browser session persistence/manual takeover, and duplicate-submission recovery.
- Research citations and prompt-injection defenses; trusted skill signing/provenance and a real evaluator/promotion workflow.
- Proper git worktree isolation, review/commit/PR adapters, background scheduler/worker daemon, and structured telemetry/incident tooling.
- Official or authorized connectors for VS Code, Antigravity, Claude Code, Canva, Adobe, Lovable, and any other subscription service.
- Multi-user isolation, installer/release flow, end-to-end evaluation suite, and production security review.
