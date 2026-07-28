# Guardian Agent — Autonomous AI Co-Pilot & Zero-Trust Governance Framework

[![Unit Tests](https://img.shields.io/badge/tests-555%20passed-brightgreen.svg)](file:///media/lalit/HIKVISION1/AI%20agent%20model/tests)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://python.org)
[![Security Policy](https://img.shields.io/badge/security-fail--closed-red.svg)](#zero-trust-security-model)

**Guardian Agent** is a local-first, privacy-respecting, zero-trust AI co-pilot governor designed for safe autonomous software development, multi-model routing, and subscription application orchestration.

It acts as a strict governance layer over AI coding agents, browser automation, and subscription connectors (Canva, Adobe, Lovable), preventing runaway token costs, unsafe file modifications, silent side effects, and unauthorized remote calls.

---

## 🎯 What Guardian Agent Achieves

1. **Zero-Trust Security & Path Control Locks**:
   - **Path Locks**: Stages with empty allowlists (`allowed_paths=[]`) strictly prohibit file writes. Writable coding tasks require explicit orchestration path approval.
   - **Secret Reservation Tokens**: Sensitive actions require secret `reservation_token`s and exact scope matching (`user_id`, `account_id`, `connector_scope`).
   - **Owner Tokens & Idempotency**: Connector operations generate secret `owner_token`s (`otok-...`). Interrupted operations fail closed to `"unknown_outcome"` requiring explicit reconciliation before retrying.

2. **Cost & Token Optimization**:
   - **FreeBuff-First Priority**: Coding tasks attempt **FreeBuff** *first*, eliminating remote API token costs.
   - **Local GPU Acceleration**: On-device Ollama execution powered by **`qwen3-coder:30b`** on AMD RX 7900 XTX at `priority=0`.
   - **Two-Layer QA Escalation**: QA1 (free Gemini/Nemotron route) evaluates compact diffs and tests. `clear` QA1 outcomes skip expensive QA2 routes entirely.
   - **Fresh Bounded Handoffs**: Every coding task starts a fresh, isolated session with bounded context, eliminating prompt token inflation and context pollution.

3. **Autonomous Daemon & Concurrency**:
   - Background worker daemon (`supervisor_daemon_run`) coordinates stale lease recoveries, ticket dispatches, and parallel worker execution (`max_workers=4`) with emergency kill-switch safeguards.

---

## 🏗️ End-to-End System Architecture

```mermaid
flowchart TD
    User([User / CLI Command]) --> Intake[Intake & Orchestration]
    Intake --> PathCheck{Path Control Locks & Access Mode}
    PathCheck -- Rejected --> Deny[Fail-Closed Refusal]
    PathCheck -- Approved --> ExecPlan[Execution Governor]

    subgraph Implementation Phase
        ExecPlan --> FB[Stage 1: FreeBuff-First Coding]
        FB -- Failure / Timeout / Unavail --> Fallback[Stage 2: Aider + Ollama qwen3-coder:30b]
    end

    subgraph Two-Layer QA Pipeline
        FB & Fallback --> QA1[QA1: Gemini / Nemotron Free Route]
        QA1 -- status: clear --> FinalApp[Mandatory Primary / Human Approval]
        QA1 -- status: flagged / uncertain / failed_tests / security_sensitive --> QA2[QA2: Strong OmniRoute Route]
        QA2 --> FinalApp
    end

    FinalApp --> Audit[Durable Audit Ledger & Artifacts]
```

---

## 🚀 Complete Project Architecture & Development Phases (Phases 1–8)

Guardian Agent was engineered across 8 focused development phases, each adding specialized governance, security, or routing capabilities:

### Phase 1 — Gateway & Model Policy Foundation
- **Catalog & Provider Scoring (`src/guardian_agent/gateway.py`)**: Unified model provider registry supporting `local`, `free`, `subscription`, and `paid` cost tiers with capability matching.
- **Model Allowlist Policy (`src/guardian_agent/model_policy.py`)**: `require_model_allowed()` enforces strict allowlist checks, rejecting prohibited model aliases (e.g. `claude-sonnet-4.6`).
- **Aider Worker Adapter (`src/guardian_agent/aider.py`)**: Bounded Aider execution with dry-run defaults, isolated history files (`.agent/audit/`), and secret redaction.

### Phase 2 — Multi-Stage Execution Governor & Ticket Dispatch
- **Execution Planning (`src/guardian_agent/execution.py`)**: Generates multi-stage plans (`plan_execution()`) with ordered model stages and terminal primary review.
- **Supervisor Ticket Lifecycle (`src/guardian_agent/supervisor.py`)**: Ticket state machine (`dispatched`, `processed`, `blocked`, `ready`, `awaiting_primary_review`).
- **Lease Timeout & Primary Review Inbox**: Stale execution leases auto-expire; processed tasks route to the primary review inbox for human verification.

### Phase 3 — Local Coordination Service & Brain Persistence
- **Daemon Service (`src/guardian_agent/service.py`)**: Systemd and launchd service generation for continuous background operation (`guardian service install/run`).
- **Schema Migration Engine (`src/guardian_agent/migrations.py`)**: Versioned database migrations for ProjectBrain schemas.
- **Automated Brain Backups**: Brain state tarball compression (`brain_backup_*.tar.gz`) on service initialization.

### Phase 4 — Path Control Locks & Stage Access Modes
- **Stage Path Control Locks (`src/guardian_agent/execution.py`)**: Execution stages declare `allowed_paths`. Stages with empty allowlists cannot modify repository files.
- **Stage Access Modes**: Configurable `access_mode` (`read-only`, `workspace-write`, `full-write`) per orchestration ticket.
- **Secondary Fallback Removal**: Removed ambiguous auto-fallbacks in favor of deterministic stage transitions.

### Phase 5 — Encrypted Accounts, Vault & Subscription Connectors
- **Account Vault (`src/guardian_agent/vault.py`)**: AES-GCM encrypted credential vault (`.agent/vault/`) with profile lock manager preventing concurrent account collision.
- **Subscription Connectors (`src/guardian_agent/connectors.py`)**: Native connectors for **Canva**, **Adobe**, and **Lovable** subscription applications.
- **Owner Tokens & Reconciliation**: Actions issue secret owner tokens (`otok-...`). Interrupted calls record `"unknown_outcome"` requiring explicit reconciliation (`connector reconcile`).

### Phase 6 — Browser Preflight & Visual Manual Takeover
- **Actionability Preflight (`src/guardian_agent/browser_operator.py`)**: `browser_actionability_check` verifies element visibility, enablement, and bounding boxes before executing actions.
- **Visual Manual Takeover (`src/guardian_agent/takeover_manager.py`)**: Attaches headful Playwright browser session with non-destructive DOM banner overlay (`"Guardian Agent Manual Takeover Active"`).
- **Session Control**: Full takeover lifecycle commands (`takeover status`, `takeover resume`, `takeover cancel`).

### Phase 7 — Autonomous Worker Daemon & Concurrency
- **Autonomous Supervisor Daemon (`src/guardian_agent/supervisor_daemon.py`)**: `supervisor_daemon_run()` runs background ticket dispatches, stale lease recoveries, and capacity re-audits.
- **Bounded Concurrency**: `ThreadPoolExecutor(max_workers=4)` caps parallel ticket processing.
- **Emergency Control**: Immediate kill-switch detection (`is_kill_switch_active()`) blocks execution upon safety triggers.

### Phase 8 — FreeBuff-First & Two-Layer QA Pipeline
- **FreeBuff-First Implementation (`src/guardian_agent/execution.py`)**: Stage 1 places **FreeBuff** as primary coding executor. Stage 2 falls back to local Ollama **`qwen3-coder:30b`** + Aider.
- **Fresh Session Isolation (`src/guardian_agent/freebuff.py`)**: Automated FreeBuff session continuation is strictly prohibited (`allow_interactive_resume=False`), creating fresh bounded handoffs per task.
- **Two-Layer QA Engine (`src/guardian_agent/qa_pipeline.py`)**:
  - **QA1**: Gemini/Nemotron free route evaluates compact diffs, test outputs, criteria, and risks. Returns status in `{"clear", "flagged", "uncertain", "failed_tests", "security_sensitive"}`.
  - **QA2 Escalation**: `clear` QA1 outcome skips QA2. Non-`clear` status escalates to QA2 (strong OmniRoute).
  - **Final Approval**: Mandatory primary review / human green-light gate before completion.

---

## 🛠️ Skill Ecosystem & 150 Specialist Agent Profiles

Guardian Agent includes a three-tier skill system designed to guide tasks safely through adaptive workflows, specialized domain roles, and custom skill generation:

### 1. 7 Built-in Core Workflow Skills

Packaged inside `src/guardian_agent/builtin_skills/` and auto-selected via `guardian skill select --task "<task>"`:

1. **`guardian-brainstorm`**: Intent, constraints, trade-off design before coding.
2. **`guardian-debug`**: Evidence-backed root cause diagnosis & falsifiable hypotheses.
3. **`guardian-plan`**: Ordered, verifiable implementation task decomposition.
4. **`guardian-review`**: Independent two-stage review (Stage 1 Specification, Stage 2 Code Quality).
5. **`guardian-tdd`**: Red-Green-Refactor test cycle with command exit code proof.
6. **`guardian-verify`**: Fresh empirical verification before task completion or git push.
7. **`guardian-worktree`**: Isolated git worktrees for safe experimental changes.

### 2. 150 Specialist Role Profiles Across 10 Domains

Defined in `src/guardian_agent/profiles.py` (lines 40–115). Rather than running 150 continuous daemon background agents, Guardian performs a deterministic metadata search over this compact index to select only the top 2 matching profiles per task (saving up to **98.6% of prompt tokens**):

| Domain (15 Roles Each) | Specialist Agent Profiles |
| :--- | :--- |
| **Intake & Orchestration** | Intent classifier, Task decomposer, Requirements interviewer, Planner, Dependency planner, Model router, Tool router, Budget manager, Context selector, Memory retriever, Delegation manager, Parallel-work coordinator, Conflict resolver, Progress reporter, Human-approval gate |
| **Product & UX** | Product manager, User-story writer, Acceptance-criteria writer, Feature prioritizer, Roadmap agent, User researcher, Persona builder, UX researcher, Information architect, UX writer, UI designer, Design-system agent, Accessibility designer, Wireframe agent, Usability-test analyst |
| **Software Architecture** | Solution architect, Repository mapper, Codebase archaeologist, API architect, Database architect, Event-driven architect, Microservice architect, Monolith-modularization agent, Cloud architect, Integration architect, Performance architect, Security architect, Data architect, Migration architect, Technical decision-record writer |
| **Coding** | Frontend developer, Backend developer, Full-stack developer, Mobile developer, Desktop-app developer, CLI developer, Browser-extension developer, API developer, Database developer, Python developer, JavaScript/TypeScript developer, Java/Kotlin developer, C#/.NET developer, Go developer, Rust/C/C++ developer |
| **Specialized Engineering** | Game developer, Embedded/IoT developer, Robotics developer, Blockchain developer, Data-engineering developer, ML engineer, LLM/RAG engineer, Computer-vision engineer, Speech/audio engineer, GIS developer, ERP/CRM developer, Shopify/e-commerce developer, WordPress/CMS developer, Low-code automation developer, Legacy-code modernization agent |
| **Quality & Debugging** | Bug triager, Root-cause investigator, Unit-test writer, Integration-test writer, End-to-end test agent, Regression-test agent, Test-data generator, QA explorer, Visual-regression tester, Load-test engineer, Reliability-test engineer, Fuzzer, Static-analysis agent, Code-review agent, PR-review response agent |
| **DevOps & Operations** | CI/CD engineer, Docker/container engineer, Kubernetes engineer, Terraform/IaC engineer, Cloud deployment agent, Release manager, Dependency-upgrade agent, Package/security-update agent, Observability engineer, Log analyst, Incident commander, SRE agent, Cost-optimization agent, Backup/recovery agent, Environment/configuration agent |
| **Security & Governance** | Threat-model agent, Secure-code reviewer, Vulnerability scanner, Pen-test assistant, Secrets detector, IAM/permissions reviewer, Privacy reviewer, Compliance mapper, License-compliance agent, Data-classification agent, Prompt-injection defender, MCP/tool-permission reviewer, Supply-chain security agent, Audit-evidence collector, Policy-enforcement agent |
| **Data, Research & Knowledge** | Web researcher, Source verifier, Citation manager, Competitive-intelligence agent, Market researcher, Data analyst, SQL analyst, Spreadsheet analyst, Dashboard builder, Data-cleaning agent, Data-labeling agent, Document/PDF extractor, Knowledge-base curator, RAG index manager, Report writer |
| **Business & Communication** | Technical writer, API-doc writer, README agent, Proposal writer, Sales-research agent, Lead-qualification agent, Customer-support agent, Email-drafting agent, Meeting-notes agent, Project-manager agent, Hiring/recruiting agent, Finance-analysis agent, Legal-contract reviewer, Marketing-content agent, Translation/localization agent |

### 3. Local Skill Factory, Drafts & Quarantine Management

- **1 Generated Draft Skill**: `audit-citations-minimal-handoff` (untrusted draft requiring explicit evaluation & promotion).
- **0 Trusted Custom Skills**: Ready for user promotion when required.
- **1 Quarantined Imported Skill**: `performance` (isolated external skill awaiting security hash verification).

```bash
# Generate custom skill draft batch locally using qwen3-coder:30b
guardian skill generate \
  --requirement "Create API verification and test-triage workflows" \
  --count 2 \
  --provider-id local-ollama \
  --model-id qwen3-coder:30b

# Run static quality check on skill draft
guardian skill evaluate-draft --name verify-api-contract

# Run bounded semantic evaluation grounded in declared capabilities
guardian skill evaluate-semantic \
  --name verify-api-contract \
  --provider-id local-ollama \
  --model-id qwen3-coder:30b

# Request and approve explicit policy request to promote skill to trusted
guardian policy request --action skill_generated_promote --target verify-api-contract --reason "Reviewed workflow"
guardian policy approve --id req-xxxxxxxx
guardian skill promote --name verify-api-contract --approval-id req-xxxxxxxx

# Re-scan imported external skills for security & file hash integrity
guardian skill audit-external
```

---

## 💻 Local GPU Setup (`qwen3-coder:30b` on RX 7900 XTX)

To configure Guardian for local GPU execution with highest coding priority (`priority=0`):

```bash
# Register local Ollama with qwen3-coder:30b at priority 0
guardian provider setup-ollama --model qwen3-coder:30b

# Verify coding route selects qwen3-coder:30b
guardian provider route --task coding
```

Expected output:
```json
{
  "provider": "local-ollama",
  "model": "qwen3-coder:30b",
  "cost_tier": "local",
  "priority": 0
}
```

---

## 📖 Comprehensive CLI Reference

### 1. Provider & Gateway Management
```bash
# Register local Ollama provider endpoint
guardian provider setup-ollama --model qwen3-coder:30b

# Discover installed local Ollama models
guardian provider discover-ollama

# Route task to optimal model
guardian provider route --task "Refactor authentication layer"

# Test streaming route execution
guardian provider test --id local-ollama --model qwen3-coder:30b --prompt "Return OK"

# Inspect provider capacity and rate-limit headers
guardian provider capacity
```

### 2. Orchestration & Execution Planning
```bash
# Start task intake
guardian orchestrate start --task "Implement OAuth login" --approved-path "src/"

# Confirm orchestration requirement
guardian orchestrate confirm --id orch-xxxxxxxx --task "Implement OAuth login"

# Dispatch orchestration for execution
guardian orchestrate dispatch --id orch-xxxxxxxx

# Create multi-stage execution plan
guardian execution plan --id orch-xxxxxxxx

# Run foreground supervisor cycle
guardian supervisor run --interval-seconds 60 --max-cycles 1
```

### 3. Skill Management & Skill Factory
```bash
# List all trusted, draft, and builtin skills
guardian skill list
guardian skill builtins

# Select relevant skills for a specific task
guardian skill select --task "Fix SQL injection vulnerability"

# Evaluate built-in skill triggers
guardian skill evaluate
```

### 4. Local Coordination Service
```bash
# Generate systemd or launchd service unit
guardian service install --interval-seconds 600

# Run continuous local coordination service
guardian service run --interval-seconds 600 --indefinite
```

### 5. Account Vault & Subscription Connectors
```bash
# Store encrypted credential in vault
guardian vault set --key CANVA_API_KEY --value "secret_token_123"

# Authenticate account via connector
guardian connector auth --connector canva --account-id canva_main

# List assets from subscription connector
guardian connector list --connector canva --account-id canva_main

# Reconcile interrupted or unknown connector outcome
guardian connector reconcile \
  --connector canva \
  --action create_asset \
  --idempotency-key key-xxxxxxxx \
  --resolution cancelled \
  --reason "Verified design was not created on Canva"
```

### 6. Browser Operator & Visual Manual Takeover
```bash
# Test web page inspection
guardian browser test --url https://canva.com --account-id canva_main

# Perform preflight-validated browser action
guardian browser action --url https://canva.com --action click --selector "button#submit" --account-id canva_main --approval-id app-xxxxxxxx

# Control visual manual browser takeover
guardian browser takeover status --account-id canva_main
guardian browser takeover resume --account-id canva_main
guardian browser takeover cancel --account-id canva_main
```

---

## 🧪 Testing & Verification Metrics

Guardian Agent contains 555 automated unit tests covering all 8 development phases:

```bash
# Run full unit test suite (555 tests)
PYTHONPATH=src python3 -m unittest discover -s tests -q

# Run Phase 8 FreeBuff and QA test suite
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_phase8_freebuff_qa.py' -v

# Run code hygiene checks
git diff --check && python3 -m compileall -q src tests
```

---

## 🔒 Zero-Trust Security Model

- **Fail-Closed Default**: Any unhandled exception, missing permission, or invalid token causes immediate execution refusal.
- **Secret Redaction**: Environment variables, API keys, and vault references (`vault:...`) are automatically redacted from error traces and journey logs.
- **Non-Destructive Takeover**: Visual manual browser takeover injects a floating DOM banner overlay without wiping active page state.
- **Audit Ledger**: All operations, policy decisions, and receipts are recorded in durable JSON audit ledgers under `.agent/audit/`.

---

## 📜 License

Licensed under the MIT License. See [LICENSE](LICENSE) for details.
