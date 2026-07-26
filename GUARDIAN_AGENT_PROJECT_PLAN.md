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

