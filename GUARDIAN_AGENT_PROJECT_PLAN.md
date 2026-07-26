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

## 30. Free-Resource Operating Plan

Guardian must minimize primary-model usage by treating Ollama, optional
high-resource local runtimes such as Colibri, OmniRoute, FreeBuff, and optional
coding harnesses such as JCode as complementary resources rather than
interchangeable chat interfaces.

### 30.1 Routing order

```text
User request
  -> Guardian deterministic intake, risk, profiles, skills, memory retrieval
  -> user confirms the exact orchestration ID
  -> Ollama for private analysis, summaries, repository maps, and first drafts
  -> optional Colibri for a difficult compact one-shot local analysis
  -> FreeBuff or JCode for a bounded coding package when repository edits are needed
  -> OmniRoute only for a missing specialty, failed/weak local result, or independent review
  -> primary Codex/Claude/Gemini reviews compact evidence and gives the final green signal
```

1. **Zero-model Guardian first.** Use deterministic classification, retrieval,
   policy checks, route health, quota state, and compact-context generation.
2. **Ollama second.** Prefer local models for private requirements analysis,
   decomposition, research summarization, test triage, code explanation,
   skill drafting, and ordinary planning/coding. Send only the selected files
   and compact project context.
3. **Colibri as an optional high-resource local specialist.** Route only a
   difficult compact one-shot reasoning, architecture, review, council, or
   skill-evaluation task after deterministic hardware/readiness checks and
   explicit user enablement. Ollama remains the default local route.
4. **FreeBuff for bounded implementation.** Give it one confirmed task, the
   minimum relevant files, acceptance criteria, constraints, and test command.
   Do not send `.env`, vault data, credentials, account identifiers, raw logs,
   or unrelated files. Use one continuing FreeBuff session per task where
   possible; do not evade its daily/session limits.
5. **JCode as an optional bounded coding/swarm worker.** Use it only after
   capability discovery and explicit local configuration. Guardian supplies
   the compact task, exact writable paths, verification commands, worker/time
   limits, and provider budget. Guardian retains policy, approval, memory
   governance, final verification, and the final green signal.
6. **OmniRoute for specialist fallback and review.** Choose a healthy,
   capability-matched free-limited combo only when Ollama is insufficient.
   Use redacted log health, quota/capacity evidence, provider diversity, and a
   maximum of five attempts. Never call all combos merely to obtain more
   opinions. Keep the GPT-5.5 combo last as the final-review reserve.
7. **Primary model as authority.** Codex, Claude, Gemini, or another user-chosen
   primary model reviews the compact requirement, patch/diff, test evidence,
   unresolved risks, and conflicting worker findings. It handles high-risk
   judgment and gives the final green signal; it should not repeat successful
   repository mapping, routine terminal checks, or background research.

### 30.2 Escalation and conservation rules

- Stay deterministic when no generation is needed.
- Use cached project memory and reusable lessons before any model request.
- One task gets one compact handoff; workers do not receive the full chat.
- Reuse a live FreeBuff conversation instead of starting another session.
- Prefer Ollama when expected quality is adequate, even if a remote route is free,
  because remote pools showed much higher prompt-token overhead.
- Escalate from Ollama only after a concrete failure, low-confidence result,
  missing capability, or required independent review.
- Recheck OmniRoute health before dispatch; skip penalized, exhausted, blocked,
  or newly changed combos.
- Reserve at least one healthy high-quality route for final review instead of
  spending every quota during drafting.
- Stop after the bounded attempt limit and return evidence to the primary model;
  never create retry loops that silently consume daily quotas.
- Run focused tests first, then the full local suite once. Send only the result,
  failure excerpt, changed-file list, and unresolved risks to the final reviewer.

### 30.3 Resource responsibilities

| Resource | Default responsibility | Must not do |
|---|---|---|
| Guardian | Intake, confirmation, policy, memory, routing, budgets, recovery, compact handoffs | Spend a model call on deterministic work |
| Ollama | Private/local reasoning, summaries, triage, first drafts, lightweight review | Decide external approvals or final high-risk acceptance |
| Colibri (optional) | Slow high-quality local one-shot architecture, review, council, synthesis, and skill evaluation on eligible hardware | Replace Ollama for routine work, receive large agent preambles, run interactive loops, download hundreds of GB without consent, or control tools/external actions |
| FreeBuff | Confirmed bounded repository implementation and focused tests | Receive secrets/unrelated files, commit, push, or perform unapproved external actions |
| JCode (optional) | Bounded coding sessions, persistent worker sessions, compact repository inspection, and Guardian-limited swarms | Replace Guardian policy, import credentials automatically, enter self-development mode, spawn unbounded workers, or perform external actions directly |
| OmniRoute | Capability fallback, diverse second opinion, difficult specialist work, reserved final review | Fan out to every combo or bypass model/member policy |
| Primary model | Resolve ambiguity/conflicts, inspect evidence, high-risk review, final green signal | Re-read the entire journey or redo verified routine work |

### 30.4 Review checkpoints

- Before dispatch: exact requirement confirmation, risk profile, selected
  profiles/skills, route order, quota reserve, and allowed files.
- During delegated work: revisit only on a worker question, policy boundary,
  failure, or timed completion checkpoint.
- After delegated work: inspect the diff, reject unrelated changes, run focused
  and full tests, check prohibited models/secrets, then request the primary
  model's compact final review.
- Persist the result, mistakes, and reusable prevention lesson so the next
  project begins with the improved routing decision.

### 30.5 Planned JCode integration

JCode is an MIT-licensed coding-agent harness and may be integrated as an
optional replaceable worker, never as Guardian's policy authority or mandatory
runtime dependency. Reference:
[1jehuang/jcode](https://github.com/1jehuang/jcode).

The first integration milestone is a `JCodeAdapter` with:

- Binary/version detection and capability discovery without a model call.
- Dry-run-by-default compact handoff containing only the confirmed task,
  acceptance criteria, selected files, exact writable paths, and test command.
- Sandboxed worktree execution, timeouts, cancellation, bounded concurrency,
  structured result capture, and diff/artifact validation.
- Optional persistent-session reuse and a Guardian-controlled swarm limit.
- Local/Ollama or explicitly user-authorized provider selection; no automatic
  credential scanning, importing, account switching, or quota evasion.
- Telemetry disabled by default (`JCODE_NO_TELEMETRY=1`) for Guardian-launched
  sessions, with any opt-in recorded as an explicit user setting.
- JCode self-development disabled. JCode workers may not modify Guardian,
  its policy, project brain, vault, approval records, or worker configuration.
- Browser tooling treated as an untrusted execution backend behind Guardian's
  URL policy, account scope, one-time approvals, idempotency, evidence, and
  manual-takeover controls.
- Primary-model review of the compact diff, tests, risks, and worker evidence
  before completion.

Useful JCode design ideas to implement independently in Guardian:

- Semantic local memory retrieval with project/session/global scope,
  provenance, correction/negative memories, confidence decay, and conflict or
  supersession handling.
- Lazy skill/profile injection so only relevant instructions consume context.
- Structure-aware repository search and adaptive output truncation.
- Persistent worker sessions, crash recovery, inter-worker change
  notifications, and bounded messaging.

**Done when:** Guardian can dispatch one confirmed coding task to JCode with no
secrets or unrelated context, constrain all writes, cancel/recover it, collect
structured evidence, reject an out-of-scope change, and obtain final
primary-model approval. Tests must also prove that telemetry, self-development,
automatic credential import, unbounded swarm spawning, and direct external
actions remain disabled.

### 30.6 Planned Colibri integration

Colibri is an Apache-2.0 local inference engine that can expose large
Mixture-of-Experts models through OpenAI- and Anthropic-compatible localhost
APIs. It is an optional provider for capable user machines, never a required
Guardian dependency. Reference:
[JustVugg/colibri](https://github.com/JustVugg/colibri).

The first integration milestone is a `ColibriAdapter` layered over Guardian's
existing OpenAI-compatible gateway:

- Opt-in feature flag; absent or ineligible installations remain unaffected.
- Binary/version detection followed by read-only `coli doctor`, `coli plan`,
  `/health`, and `/v1/models` capability checks.
- Eligibility policy: at least 24 GB RAM as the recommended user tier,
  approximately 400 GB free local storage, a suitable fast SSD/NVMe, and a
  passing Colibri readiness/placement plan. Capability evidence overrides
  assumptions based only on advertised RAM.
- Explicit informed approval before downloading, converting, moving, or
  deleting model weights. Guardian must show expected download size, target
  directory, free space, and estimated setup implications.
- Localhost-only default (`127.0.0.1`), locally generated API authentication,
  no public/LAN binding by Guardian, and no secrets persisted in project files.
- Registration as a zero-API-cost local route with measured startup, prefill,
  decode, queue, token, memory, and failure evidence.
- One generation at a time initially, bounded queueing, long but finite
  timeouts, cancellation, health-based fallback, and crash-safe accounting.
- Compact one-shot prompts and bounded outputs. Never send the full journey,
  full repository, large coding-agent system prompt, or repeated multi-turn
  tool loop to a disk-streaming configuration.
- Initial capability limited to text reasoning: architecture analysis,
  difficult code/security review, council membership, research synthesis, and
  skill evaluation. Guardian retains all tools, approvals, file writes,
  browser actions, and external side effects.
- Ollama remains the preferred local route for ordinary interactive work.
  Colibri is selected only when its expected quality gain justifies its
  measured latency and the task can wait.

Colibri availability must be determined by capability rather than RAM alone.
The current upstream guidance recommends 24 GB or more RAM and roughly 380 GB
of model storage, while low-memory disk-streaming inference can be extremely
slow. Guardian must therefore estimate completion time from live prefill and
decode measurements and request confirmation before dispatching a task whose
estimate exceeds the user's configured waiting threshold.

**Done when:** on an explicitly configured eligible machine, Guardian can
discover a localhost Colibri server, run a bounded smoke test, route one compact
review task, record latency and usage, cancel or time out safely, and fall back
without losing task state. Tests must prove that an ineligible machine is
skipped, no model download starts without approval, no non-loopback endpoint is
auto-configured, no tool/external action is delegated, and Ollama remains the
ordinary local default.

## 31. Implementation Status — 2026-07-27

### Implemented foundation

- Local project brain with requirements, confirmation, decisions, lessons, journey records, and compact handoff exports.
- Provider registry and low-cost routing; provider calls now resolve an environment or `vault://` credential only at request time.
- Authenticated encrypted local vault using a passphrase-derived Fernet key. Legacy obfuscated vault records are read only for one-time migration.
- Skill draft/promotion records, specialist-role handoff packages, task queue, locks, crash recovery, and a persistent emergency stop whose resume path requires exact one-time approval.
- Approval queue with exact action/target, one-time approval consumption, coding verification without a shell, and sandbox-copy rollback support.
- Browser inspection plus bounded Playwright navigate/click/fill/screenshot/submit actions. Submission is visible by default and policy-gated.
- Opt-in LLM Council protocol for safe analysis: independent model opinions, anonymized peer review, chairman synthesis, and retained deliberation artifacts. It is never a path to autonomous external action.
- Optional Freebuff interactive coding-worker adapter that builds a compact project handoff and launches/continues only user-controlled terminal sessions; it does not collect Freebuff credentials or evade service limits.
- Unified persistent orchestration lifecycle with deterministic task/risk classification, at most five specialist profiles and five compact routes, exact-ID confirmation, collision-safe requirement recording, local/free-limited ordering, a last-position final-review reserve, compact dispatch, show/list/recovery commands, and no model or external call during orchestration.
- Secure MCP stdio foundation with untrusted-by-default server registration, exact command trust approval, dynamic tool discovery, explicit read/write allowlisting, schema pinning, one-time approval for write calls, and audited results.
- Adaptive engineering workflow with fast/standard/high-assurance profiles, design/final approval gates, automatic built-in skill selection, specification and quality review stages, fresh verification evidence, and completion-state enforcement.
- Packaged brainstorming, planning, TDD, systematic debugging, two-stage review, fresh verification, and real-worktree skills with compact trigger metadata and deterministic selection evaluation.
- Persistent debugging evidence ledger with reproduction, hypotheses, minimal attempts, and mandatory architecture review after three failed fixes.
- Real git worktree creation for git projects, bounded rollback paths, fresh-context worker packages, and non-destructive bootstrap exports for Codex, Claude, Gemini, Antigravity, Cursor, and VS Code.
- Complete original 150-profile specialist catalog across 10 domains, with local deterministic selection, compact/full inspection, schema and model-policy validation, bounded handoff generation, journey logging, and estimated context-savings telemetry.
- Live Ollama discovery and conservative capability routing for every allowed model installed on the user's machine; verified local completion keeps ordinary planning, research, documentation, and coding assistance off paid APIs.
- Live OmniRoute combo discovery on `http://localhost:3000`, conservative free/paid classification, transitive prohibited-model checks over combo members, exact-route testing, bounded failover, and execution-time combo re-auditing to prevent unsafe membership changes.
- User-confirmed `free-limited` funding classification for exact audited OmniRoute combos, with persistent rediscovery-safe policy, zero incremental billed-cost accounting, retained equivalent-cost analytics, capacity tracking, and diversified fallback ordering. Eight requested combos were live audited and exercised; all reached the provider, seven returned exact `OK`, and the NVIDIA pool responded but exhausted the initial eight-token cap. GPT-5.5 is reserved as a final-review route, while local Ollama remains preferred because successful combo smoke checks consumed 20,804 reported tokens.
- Redacted local OmniRoute usage-log auditing with strict loopback-only access, bounded response/event sizes, discarded raw lines and account/connection identifiers, combo-member correlation, persistent health evidence, and bounded routing penalties. A zero-completion 15-minute maintenance job now refreshes this evidence; the first 100-event audit demoted three unstable pools while leaving five healthy requested pools unpenalized.
- Persistent concurrency-safe UTC-day token/cost budgeting with conservative preflight reservation, actual-usage settlement, conservative failed-call charging, configurable output caps, and fail-closed pricing requirements for paid routes.
- Versioned `guardian-eval-v1` evidence covering catalog integrity, representative specialist routing, prohibited-model aliases, context savings, and optional live model-quality rubrics. The local `qwen2.5:14b` run passed all three live scenarios using 609 reported tokens at zero API cost.
- Budget-aware OpenAI-compatible SSE streaming with chunk callbacks, provider-usage settlement, conservative interrupted-stream charging, and an explicit prohibition on unsafe partial-stream failover.
- Secret-safe provider capacity telemetry with allowlisted quota/rate-limit/backend headers, latency and retry-window tracking, pre-call exhaustion blocking, bounded history, observed prompt-inflation measurement, learned reservation multipliers, and efficiency-based route penalties. Live evidence measured roughly 25 prompt tokens on Ollama versus 2,032 on the audited free OmniRoute route for tiny requests; local routing remains preferred.
- Zero-completion `/models` capacity probes with credential isolation, catalog size bounds, advertised-model verification, allowlisted response telemetry, and preservation of prior usage evidence. Live probes advertised 4 Ollama models and 2,273 OmniRoute routes without consuming completion tokens.
- Longitudinal `guardian-evaluation-history-v1` aggregation across versioned evaluation artifacts, reporting runs, scenario pass rate, quality, tokens per scenario, and cost per provider/model. Measured local results currently show 100% on both `qwen2.5:14b` (203 tokens/scenario) and `qwen2.5-coder:14b` (245 tokens/scenario); bounded quality adjustments now complement task affinity and efficiency penalties.
- Secure external-skill registry for six researched ecosystems, with metadata-only search, registered HTTPS/raw-prefix enforcement, size/encoding/frontmatter checks, prompt-injection and dangerous-pattern inspection, SHA-256 provenance, quarantine, integrity recheck, and one-time approval before draft acceptance.
- Local-model skill factory that creates up to ten reusable skills in one bounded call, validates the complete batch before writing, blocks unsafe output, records generation provenance and examples, runs a static quality gate, and requires exact one-time user approval before generated content can become trusted. A real `qwen2.5:14b` generation produced and passed static evaluation for `audit-citations-minimal-handoff`; it remains an untrusted draft.
- Semantic skill learning loop with declared capability contracts, bounded local-model scoring, findings-driven revision, versioned rollback copies, evaluation invalidation after changes, and user-controlled promotion. The real citation skill progressed from 4/10 with an invented database dependency to a grounded version 0.5.0 scoring 10/10 with `qwen2.5-coder:14b`; it remains a draft awaiting human review.
- Citation-grounded research ledger with public-HTTPS/SSRF controls, redirect rejection, source size limits, source-aware stable fingerprints, transport hashes, change detection, instruction-risk signals, discarded remote bodies, and compact `citation-handoff-v1` packages. GitHub repository sources use official stable metadata and generic HTML excludes dynamic script/style markup. Live repeat verification passed for Orchestra Research, Addy Osmani Web Quality, and VoltAgent with zero false change alerts.
- Bounded Aider adapter for local Ollama or OmniRoute with profile-routed context, shared prohibited-model enforcement, dry-run default, analytics/auto-commit/repo-map disabled, and history isolated under `.agent/audit/`.
- Persistent zero-completion maintenance coordinator with safe local defaults, opt-in provider/citation probes, non-blocking project locking, bounded work per run, exponential failure backoff, portable scheduler instructions, emergency-stop enforcement, and hard-disabled scheduled model completions. A real six-job pass completed with all jobs passing and zero completion tokens.
- Longitudinal evaluation regression alerts detect pass-to-fail changes, material quality drops, and token growth, with stable alert IDs and a persistent audit artifact.
- Consent-aware cross-project learning library with private project candidates, exact one-time export/delete approvals, mandatory user-supplied sanitized abstractions, secret/private-material rejection, 0600 local storage, deterministic compact search, future-project context injection, and bootstrap guidance. Raw lesson details and project identity are never exported.
- Execution governor with persistent ordered stages (Ollama, FreeBuff, OmniRoute, final-review, primary-review), slot reservation for final-review routes, durable asynchronous dispatch IDs, authenticated verified-result recording, idempotent replay, timeout fallback, skip-cascade on ordinary-stage pass, failure-continues-fallback on fail/skip, claim-time model-policy/provider-health/capacity revalidation, bounded evidence, safe artifact paths, stale lease recovery, and no secret fields persisted. 37 focused tests verify the lifecycle.
- Connector idempotency foundation with owner tokens, stale-reservation transition to `unknown_outcome`, blocked blind retry, and explicit reconciliation records.
- Browser selector preflight checks visibility and disabled state before approval reservation; sensitive actions retain before/after evidence. Manual-takeover status, resume, cancel, timeout, persistent-profile locking, and optional headful-browser controls exist.
- Supervisor/executor foundation with stale-lease recovery, bounded durable tickets, sequential ticket processing, Ollama/OmniRoute completion dispatch, FreeBuff/Aider handoff generation, emergency-stop enforcement, and a manual primary-review inbox.
- Full local regression evidence: 294 unit tests pass, the complete source/test tree compiles, and `git diff --check` reports no whitespace errors.

### Validation of the `b37f601` follow-up roadmap

| Roadmap area | Status | Verified boundary |
|---|---|---|
| Connector owner tokens and stale-operation blocking | Partial | Reservation and first completion use owner tokens, and stale reservations become `unknown_outcome`; failure marking, repeated completion, and reconciliation still need stricter ownership/state enforcement. |
| Browser selector preflight and evidence | Partial | Visibility/disabled checks and before/after screenshots exist; overlay/navigation verification and duplicate-submission reconciliation are not complete. |
| Manual browser takeover | Partial | Persistent-profile headful launch plus status/resume/cancel/timeout controls exist; it opens a takeover page in a new context rather than attaching to and preserving the exact in-flight page. Live end-to-end takeover is not covered by the unit tests. |
| Browser unknown-outcome recovery | Pending | Interrupted sensitive actions become `unknown_outcome`, but page/transaction/activity evidence is not reconciled before retry. |
| Canva, Adobe, and Lovable connectors | Scaffold only | Credential presence is detected, but the current non-mock methods return locally synthesized assets/receipts and placeholder files; they do not call an official remote API or browser fallback. |
| VS Code, Claude Code, Gemini/Antigravity, Codex, and GitHub/PR connectors | Partial/Pending | Bootstrap exports, model routes, and bounded handoffs exist; official authorized application/PR connectors do not. |
| Account registry, encrypted vault, domains, revocation, backup/restore | Implemented foundation | Local controls exist; OS-keychain storage, rotation/expiry, and production session lifecycle remain pending. |
| Background supervisor and worker dispatch | Partial | A daemon loop and sequential ticket executor exist; `max_workers` is currently a ticket-count limit rather than real parallel execution, provider-capacity reporting is not wired to the returned `routes` schema, and processed totals read the wrong result key. |
| Learning, rollback, evaluation, and cross-project consent | Partial | Draft/revision rollback, evaluation history/alerts, quality scoring, and consent-aware sanitized export exist; cryptographic signing and isolated real-task forward evaluation remain pending. |
| Production readiness | Pending | Multi-user isolation, release packaging, installer/upgrade hardening, incident telemetry, end-to-end security evaluation, dependency/supply-chain review, and production threat modelling remain. |

### Still required before production readiness

- Provider-specific account/quota endpoints where officially available and broader calibrated semantic/code benchmarks.
- Require the exact connector owner token for every reserved-operation failure transition; reject repeated completion, restrict reconciliation to `unknown_outcome`, bind reconciliation to an authorized approval/operator, and add concurrency/crash tests.
- Complete browser actionability and recovery: overlay/navigation checks, durable submission fingerprints/receipts, page or transaction reconciliation, and no blind retry after an unknown outcome.
- Attach manual takeover to the exact in-flight authenticated page/session and add a real headful end-to-end takeover test with pause, user action, resume, cancel, timeout, and state preservation.
- Replace Canva, Adobe, and Lovable placeholder results with official authorized API calls or Guardian-policy-gated visible browser workflows. Never report credential presence as remote authentication success.
- Add real bounded worker concurrency, correct provider-capacity schema handling and processed accounting, safe shutdown/drain, worker health/heartbeat evidence, and production service installation/upgrade controls.
- OS-keychain integration, credential rotation/expiry, multiple account/session lifecycle validation, and recovery testing.
- Cryptographic signing for trusted skills, isolated forward-testing on real tasks, and calibrated multi-model semantic evaluation.
- Review/commit/PR adapters and structured telemetry/incident tooling.
- Optional hardened JCode adapter, semantic lazy-skill retrieval, and structure-aware compact repository search.
- Optional hardware-gated Colibri local-provider adapter with explicit large-download consent, live latency qualification, and compact one-shot routing.
- Official or authorized connectors for VS Code, Antigravity, Claude Code, Canva, Adobe, Lovable, and any other subscription service.
- Multi-user isolation, installer/release flow, end-to-end evaluation suite, and production security review.
