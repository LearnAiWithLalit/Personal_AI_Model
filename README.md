# Guardian Agent — Persistent Project Brain & Model Router

**Guardian Agent** is a local-first, persistent project brain and model gateway. It sits in front of coding models and tools, preserves the project journey, routes work to an appropriate configured provider, and creates compact handoff context for Codex, Claude Code, Antigravity, and future workers.

Guardian is designed to be the durable coordinator—not another model subscription. Your preferred coding model remains the final worker; Guardian reduces repeated explanation, keeps decisions and lessons close to the project, and applies policy before sensitive actions.

## What it can do today

| Area | Current capability |
| --- | --- |
| Project memory | Creates a per-project `.agent/` brain with requirements, plans, decisions, lessons, task records, costs, skills, and chronological journey logs. |
| Requirement control | Records incoming requests as pending, requires confirmation, and keeps confirmed scope in the project plan. |
| Token-efficient handoffs | Produces compact project context and exports for Codex, Claude Code, and Antigravity. |
| Provider routing | Registers local or OpenAI-compatible providers, selects the lowest-cost capable configured model, and can call it with an environment or vault credential. |
| Secrets | Stores encrypted local secrets behind `vault://` references; values are redacted from provider error messages. |
| Skills and workers | Creates skill drafts, promotes trusted skills, captures reusable lessons, and prepares bounded specialist-worker handoff packages. |
| Safe coding flow | Applies scoped file edits, runs verification without a shell, records outcomes, and supports isolated sandbox-copy preview/rollback. |
| Durable runtime | Stores queued tasks, task locks, recovery state, health records, and an emergency stop. Interrupted tasks with external side effects wait for review. |
| Browser operator | Inspects pages with Playwright or HTTP fallback; Playwright can perform visible, bounded navigate/click/fill/screenshot/submit actions. |
| Sensitive actions | Uses policy checks and a one-time approval queue for browser submission, payments, deletion, irreversible pushes, account creation, legal acceptance, and identity checks. |
| LLM Council | Optional multi-model deliberation: independent opinions, anonymized peer reviews, and a chairman synthesis for difficult analysis. |
| Freebuff worker | Prepares compact coding handoffs and launches user-controlled Freebuff CLI sessions, helping reserve paid models for final review or difficult work. |
| Aider worker | Routes a task to compact specialist profiles and runs Aider against local Ollama or the user's OmniRoute; dry-run, no analytics, no auto-commit, and no repo-map cache are defaults. |
| Secure MCP tools | Registers local stdio MCP servers as untrusted, discovers tools after server approval, pins tool schemas, and gates write-capable calls with one-time approval. |
| Adaptive development workflow | Selects fast, standard, or high-assurance gates based on task risk; enforces design approval, planning, two-stage review, fresh verification, and final approval where needed. |
| Built-in engineering skills | Ships concise brainstorming, planning, TDD, debugging, review, verification, and worktree skills with deterministic trigger evaluation. |
| 150 specialist profiles | Packages all 150 planned roles across 10 domains as searchable metadata. Guardian expands only relevant profiles into a bounded handoff and reports estimated context savings. |
| External skill quarantine | Searches six researched source catalogs without loading bodies, restricts imports to registered raw URLs, records hashes/licenses, scans risk patterns, and requires approval before an import becomes a draft. |
| Skill learning loop | Generates bounded local-model skill drafts, evaluates and revises them against declared capabilities, keeps rollback versions, and requires one-time human approval before trust. |
| Cross-project learning | Keeps project lessons private by default, exports only approved sanitized patterns to a user-owned local library, and retrieves relevant lessons deterministically for future projects. |
| Research provenance | Stores compact, injection-resistant citation records and source-aware change fingerprints while discarding fetched page bodies. |
| Budget and capacity | Reserves daily token/cost budgets before calls, learns provider overhead, probes model catalogs without completions, and prefers efficient local/free routes. |
| Zero-completion maintenance | Runs deterministic evaluation, skill audits, regression checks, provider probes, and citation verification with persistent schedules, locking, backoff, and an approval-gated emergency stop. |
| Cross-tool bootstraps | Generates non-destructive Guardian entry-point instructions for Codex, Claude, Gemini, Antigravity, Cursor, and VS Code. |

## How Guardian fits into a workflow

```text
User request
  -> Guardian records and confirms scope
  -> profile router selects a few roles from the 150-profile catalog
  -> project brain supplies only relevant context and lessons
  -> router selects a configured local/free/paid worker by policy
  -> worker produces code, research, or a handoff package
  -> Guardian runs verification, records evidence, and updates journey memory
  -> sensitive browser/external actions pause for approval
```

This makes it useful with a local model, Ollama, an OpenAI-compatible gateway, or a preferred cloud coding tool. Each installation owns its own `.agent/` memory, provider configuration, credentials, and browser sessions.

## 150 specialist profiles without 150 running agents

Guardian now includes the complete original catalog: 150 role profiles across
intake/orchestration, product/UX, architecture, coding, specialized engineering,
quality/debugging, DevOps/operations, security/governance,
data/research/knowledge, and business/communication.

A profile is a compact work contract—not a permanent process or a separate paid
model call. Each profile defines triggers, capabilities, allowed tool classes,
suggested skills, risk, approval boundaries, inputs, outputs, verification, and
model policy. The deterministic router searches metadata locally and expands
only matching profiles.

```bash
# Validate all 150 profiles, unique IDs, contracts, domains, and model policy
guardian profile validate

# Browse compact metadata or inspect one full role contract
guardian profile list --domain security-governance
guardian profile show --id frontend-developer

# Preview routing and measured context reduction
guardian profile select \
  --task "Build an accessible React login form and test it" \
  --limit 5

# Save a bounded handoff under .agent/research/ and log the journey
guardian profile dispatch \
  --task "Design and implement a secure REST API" \
  --limit 5
```

The handoff keeps the user or configured primary model as final authority. The
catalog never launches 150 agents, and a zero-match request falls back to the
intent classifier rather than loading unrelated roles. See
[`docs/PROFILE_CATALOG_ARCHITECTURE.md`](docs/PROFILE_CATALOG_ARCHITECTURE.md)
for the design and source research.

---

## 🚀 Quick Start (Git Clone & Setup)

To integrate Guardian Agent into your system or project repository:

```bash
# 1. Clone the repository
git clone https://github.com/LearnAiWithLalit/Personal_AI_Model.git
cd Personal_AI_Model

# 2. Run the interactive installer
./install.sh
```

During `./install.sh`, you will be prompted with optional setup choices:

```text
[?] Do you want to install Playwright browser binaries (~300MB) for visual UI testing? [y/N]:
```
- Selecting `y` installs Playwright and downloads full browser binaries.
- Selecting `N` skips the ~300MB download and runs Guardian Agent in lightweight HTTP inspection fallback mode.

---

## 🛠️ Usage & Integration

### Initialize a Project Brain

```bash
guardian init . --name "My Project" --purpose "Build a local dashboard agent"
```

### Requirement Discovery & Confirmation

```bash
guardian intake --request "Add user login with JWT tokens"
guardian confirm --summary "Implement JWT authentication in HTTP-only cookies"
guardian decision --title "Auth Stack" --detail "Use standard library pyjwt with zero external DB dependencies"
guardian lesson --title "Cookie Scope" --detail "Always set Secure and HttpOnly flags on auth cookies"
guardian context
guardian status
```

Guardian writes these records into `.agent/` inside the project. This folder is the project-specific memory that can be handed to a coding model without sending an entire chat history.

### Reuse lessons safely across projects

Private project lessons never enter global learning automatically. Guardian
first lists them as private candidates. The user supplies a sanitized pattern
and prevention check, then approves that exact export once. Raw lesson detail,
the project name, and the project path are not copied.

```bash
# Point every local project at the same user-owned library.
export GUARDIAN_LEARNING_LIBRARY="/path/to/user-owned/guardian-learning.json"

guardian learning candidates

guardian policy request \
  --action learning_export \
  --target lesson-xxxxxxxxxxxx \
  --reason "Reviewed the sanitized reusable pattern"
guardian policy approve --id req-xxxxxxxx

guardian learning promote \
  --lesson-id lesson-xxxxxxxxxxxx \
  --pattern "Time-sensitive authentication fixtures can expire" \
  --prevention "Generate timestamps relative to the controlled test clock" \
  --tag authentication \
  --tag testing \
  --approval-id req-xxxxxxxx

# A future project retrieves only relevant compact lessons, without a model call.
guardian learning search --query "authentication tests and token fixtures"
guardian learning apply --query "authentication tests and token fixtures"
guardian context
```

`learning apply` writes the selected sanitized entries to
`.agent/research/REUSABLE_LESSONS.md`; the normal compact context renderer then
includes them. Generated bootstrap instructions remind Codex, Claude, Gemini,
Antigravity, Cursor, and VS Code workflows to run this retrieval step. Deleting
a shared lesson requires a separate exact `learning_delete` approval.

---

## 🔌 Model Providers & Free API Discovery

Guardian Agent supports bringing your own API keys via environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `OMNIROUTE_API_KEY`):

```bash
# Register a custom model provider endpoint
guardian provider add \
  --id my-local \
  --kind local \
  --model qwen3-coder:30b \
  --capability coding \
  --cost-tier local \
  --base-url http://localhost:11434/v1

# Install optional, unverified development seeds (OpenRouter / local OmniRoute).
# This is not live provider discovery; validate each provider before use.
guardian provider discover-free

# Setup local Ollama provider endpoint
guardian provider setup-ollama --model qwen3-coder:30b


# Or discover every installed local model and infer conservative capabilities
guardian provider discover-ollama

# Register this machine's OmniRoute endpoint with an explicit allowed
# combo/model ID. Guardian rejects prohibited model IDs before saving or calling.
guardian provider setup-omniroute --model <allowed-combo-or-model-id>

# Inspect live combo membership and reject any combo containing a prohibited model
guardian provider discover-omniroute

# For an exact audited combo that the account owner confirms uses finite free
# quota, persist that funding classification. This never weakens model blocking.
guardian provider mark-free-limited --model claude-opus

# Prepaid subscription pools are opt-in; metered paid routes remain separate.
guardian provider access --allow-subscription --no-allow-paid

# Read local usage logs, discard account/connection identifiers, and update
# bounded route-health penalties.
guardian provider logs --limit 100

# Verify one exact policy-approved route with a tiny prompt
guardian provider test \
  --id local-omniroute \
  --model claude-3-opus \
  --task documentation \
  --prompt "Return exactly: ROUTE_OK"

# Use bounded healthy-route failover; paid routes remain disabled by policy
guardian run \
  --task coding \
  --prompt "Implement the confirmed bounded task" \
  --failover \
  --max-attempts 3

# Inspect the persistent UTC-day budget
guardian provider budget

# Set hard limits. A call reserves its worst-case capacity before execution.
guardian provider budget \
  --daily-tokens 250000 \
  --daily-cost-usd 0 \
  --max-completion-tokens 256

# Stream one exact route while retaining budget and usage settlement
guardian provider test \
  --id local-ollama \
  --model qwen3-coder:30b \
  --task documentation \
  --prompt "Return exactly: STREAM_OK" \
  --stream

# Inspect allowlisted latency, retry, quota, backend, and efficiency evidence
guardian provider capacity

# Probe model availability and headers without spending completion tokens
guardian provider probe \
  --id local-ollama \
  --model qwen3-coder:30b

# Run deterministic catalog/routing/policy evaluation
guardian evaluate

# Add three small quality checks using an installed local model
guardian evaluate \
  --provider-id local-ollama \
  --model-id qwen3-coder:30b


# Compare all retained live evaluations
guardian evaluate --history
```

The current machine has eight user-confirmed free-limited OmniRoute fallback
combos. All eight were audited and smoke-tested; see
[`docs/OMNIROUTE_COMBO_VALIDATION.md`](docs/OMNIROUTE_COMBO_VALIDATION.md).
Guardian prefers Ollama for routine work because tiny OmniRoute calls still
reported roughly 2,000–6,000 prompt tokens. Bounded failover moves from the
best local route to independent combo pools, while GPT-5.5 remains a
final-review reserve.

The verified local OmniRoute dashboard is at
`http://localhost:3000/dashboard/combos`; its OpenAI-compatible base URL is
`http://localhost:3000/v1`. If that installation requires authentication, set
`OMNIROUTE_API_KEY` (or the corresponding `vault://` reference) locally.
Guardian never copies a dashboard credential into the repository. Discovered
combos are re-audited immediately before execution, so changed membership
cannot silently introduce a prohibited model.

Model usage is governed by a concurrency-safe daily ledger under
`.agent/audit/`. Guardian reserves a conservative UTF-8-byte upper bound plus
the maximum output allowance before a request. Successful calls settle against
provider-reported usage; uncertain failed calls retain the reserved charge.
Paid routes without verified per-million-token pricing fail closed.

OpenAI-compatible SSE streaming is supported without weakening budgets:
Guardian reserves capacity before opening the stream, accumulates chunks,
settles provider-reported usage, and conservatively charges an interrupted
stream. Partial streaming is intentionally incompatible with failover because
replaying on another route could duplicate output or side effects.

Capacity telemetry stores only an explicit non-secret response-header allowlist.
Observed `Retry-After` or exhausted request/token windows block new calls before
network access. Guardian compares reported prompt usage with visible prompt
size, learns a conservative reservation multiplier, and adds a routing penalty
for high-overhead routes. In live testing, local Ollama reported 25 prompt
tokens for a tiny stream, while the audited free OmniRoute combo reported about
2,000; Guardian now retains that evidence and prefers the lower-overhead route.

`provider probe` calls the OpenAI-compatible `/models` endpoint rather than a
completion endpoint, verifies that the configured model is advertised, captures
allowlisted capacity headers, and spends zero completion tokens. A successful
probe preserves earlier completion usage and prompt-inflation evidence.

`guardian-eval-v1` produces versioned JSON evidence covering the 150-profile
catalog, representative routing tasks, prohibited-model aliases, compact
context savings, and optional live planning/review/documentation rubrics.
`guardian evaluate --history` aggregates pass rate, quality score, tokens per
scenario, and cost by provider/model. Routes with at least three measured
scenarios receive a bounded quality adjustment; high quality never overrides
cost tier, prohibited-model policy, capability matching, or observed overhead.

---

## ⚡ Token-Saving Exports (Antigravity / Codex / Claude Code)

Export compact, context-minimized handoff packages designed specifically to save token usage when integrating with coding tools:

```bash
# Export for Google Antigravity (AGY) subagents and slash commands
guardian export --target antigravity

# Export compact handoff for OpenAI Codex
guardian export --target codex

# Export compact handoff for Claude Code
guardian export --target claude
```

## Task runtime, recovery, and approvals

Guardian has a persistent local queue for work that must survive a restart. It does not automatically repeat an interrupted action that might have changed an external system.

```bash
# Queue and inspect a task
guardian runtime enqueue --type coding --summary "Add unit tests for authentication"
guardian runtime list

# Recover an interrupted session safely, or stop all active queued work
guardian runtime recover
guardian runtime kill
guardian runtime stop-status

# Resuming after an emergency stop requires exact one-time approval
guardian policy request \
  --action runtime_resume \
  --target guardian-runtime \
  --reason "Reviewed the stopped jobs and recovery state"
guardian policy approve --id req-xxxxxxxx
guardian runtime resume --approval-id req-xxxxxxxx

# Request and approve one sensitive external action
guardian policy request \
  --action browser_submit \
  --target https://example.com/form \
  --reason "Submit the already-reviewed application"
guardian policy approve --id req-xxxxxxxx
```

For an approved browser form submission, use the returned request ID:

```bash
guardian browser action \
  --url https://example.com/form \
  --action submit \
  --selector 'button[type=submit]' \
  --approval-id req-xxxxxxxx
```

Browser actions are visible by default. Add `--headless` only when that is appropriate for a non-sensitive, authorized workflow.

## LLM Council for difficult decisions

Council mode is inspired by the [LLM Council pattern](https://github.com/karpathy/llm-council): Guardian asks multiple configured providers for independent answers, anonymizes those answers for peer review, and then asks a configured chairman route to synthesize a final recommendation. This is useful for architecture choices, research, risk review, and ambiguous plans.

It is **opt-in** because it uses multiple model calls. It supports only analysis tasks (`research`, `planning`, `review`, `documentation`, and `routing`) and cannot be used to trigger coding, browser, account, payment, or other external actions.

```bash
# Use up to three eligible configured models; the lowest-cost eligible model
# becomes chairman unless you explicitly configure another route.
guardian council configure --members 3 --chairman local-ollama

guardian council ask \
  --task planning \
  --prompt "Compare a monolith and modular architecture for this project. Include risks and validation steps."

# Inspect the current council policy
guardian council show
```

Guardian writes the full deliberation record to `.agent/artifacts/` and a concise completion entry to the project journey. Failed council members are shown honestly; Guardian does not fabricate a consensus or a final answer when every member fails.

## Freebuff token-saving coding worker

[Freebuff](https://freebuff.com/) is an interactive coding CLI that currently advertises free coding sessions without user-supplied API keys. Guardian integrates it as an optional user-controlled worker—not as a hidden background provider. This lets Guardian preserve the project plan and give Freebuff a small, focused handoff instead of repeatedly spending tokens reconstructing context.

```bash
# Confirm that Freebuff is installed and available
guardian freebuff status

# Build a compact task and project-context file
guardian freebuff prepare --task "Add tests for the model router"

# Start Freebuff in the current project; ask it to read
# .agent/research/FREEBUFF_HANDOFF.md
guardian freebuff start

# Continue a known Freebuff conversation later
guardian freebuff start --continue <conversation-id>
```

Guardian does not log into Freebuff, collect its credentials, or bypass its usage limits. If Freebuff asks for login, complete that step directly in its visible terminal session. Its availability, model selection, limits, and terms are controlled by Freebuff and can change over time. [Freebuff’s site](https://freebuff.com/) describes its CLI as a free terminal coding agent; validate it against your own security and project requirements before using it for sensitive code.

## Aider with local Ollama or OmniRoute

Guardian detects the installed Aider CLI and can prepare a small, profile-routed
handoff. Aider runs in dry-run mode unless `--allow-edits` is explicitly added.
Analytics, automatic commits, `.gitignore` modification, and repo-map caching
are disabled. History stays in `.agent/audit/`.

```bash
guardian aider status
guardian aider prepare --task "Review the authentication implementation"

# Preview the exact dry-run command
guardian aider command \
  --task "Review the authentication implementation" \
  --backend ollama \
  --model qwen3-coder:30b

# Launch against an on-device model
guardian aider start \
  --task "Review the authentication implementation" \
  --backend ollama \
  --model qwen3-coder:30b


# Edits require an explicit flag
guardian aider start \
  --task "Implement the confirmed authentication plan" \
  --backend omniroute \
  --model <allowed-combo-or-model-id> \
  --allow-edits
```

If OmniRoute requires authentication, set `OMNIROUTE_API_KEY` in the local
environment. Guardian maps it only into the child process and never writes it
into the command preview or repository. Local installations that allow
unauthenticated loopback access use a non-secret placeholder required by
Aider's OpenAI-compatible client. The shared prohibited-model policy applies
to both backends.

## External skill discovery and quarantine

Guardian's source registry covers Orchestra Research, Addy Osmani Web Quality,
VoltAgent Awesome Agent Skills, Thinking Partner, Awesome Agent Skills MCP, and
the AGNT top-100 editorial catalog. Search operates only on compact source
metadata. Remote content never becomes trusted automatically.

```bash
guardian skill sources
guardian skill search-external --query "web accessibility performance"

# Only registered raw-content prefixes can be fetched
guardian skill import-external \
  --source addy-web-quality \
  --url https://raw.githubusercontent.com/addyosmani/web-quality-skills/main/skills/performance/SKILL.md

guardian skill inspect-quarantine --name performance
guardian skill audit-external

# Review the source, license, hash, and findings first
guardian policy request \
  --action skill_import_accept \
  --target performance \
  --reason "Reviewed provenance and inspection evidence"
guardian policy approve --id req-xxxxxxxx
guardian skill accept-import --name performance --approval-id req-xxxxxxxx

# Acceptance creates a draft, never a trusted skill
guardian skill promote --name performance
```

Imports enforce HTTPS, exact registered repository prefixes, `SKILL.md` paths,
UTF-8, a 512 KB limit, SHA-256 integrity, valid trigger metadata, and static
checks for instruction override, secret exfiltration, destructive shell
patterns, safety bypasses, hidden Unicode controls, elevated commands, dynamic
execution, hard-coded user paths, and wildcard tool permissions.

## Local skill factory

Guardian can create up to ten related skills in one bounded local-model call,
avoiding repeated requirement discussions. Generation validates the complete
JSON batch, names, trigger-rich descriptions, examples, length, and dangerous
instruction patterns before writing anything.

```bash
guardian skill generate \
  --requirement "Create API verification and test-triage workflows" \
  --count 2 \
  --provider-id local-ollama \
  --model-id qwen3-coder:30b

guardian skill evaluate-draft --name verify-api-contract
guardian skill evaluate-semantic \
  --name verify-api-contract \
  --provider-id local-ollama \
  --model-id qwen3-coder:30b

# If semantic evaluation fails, revise from findings and retain rollback history.
guardian skill revise-generated \
  --name verify-api-contract \
  --provider-id local-ollama \
  --model-id qwen3-coder:30b \
  --available-capability "Read the supplied API contract and repository files"

# A generated skill cannot self-promote. Request and approve it explicitly.
guardian policy request \
  --action skill_generated_promote \
  --target verify-api-contract \
  --reason "Reviewed generated workflow and examples"
guardian policy approve --id req-xxxxxxxx
guardian skill promote \
  --name verify-api-contract \
  --approval-id req-xxxxxxxx
```

Generated skills remain untrusted drafts. Promotion requires static validation,
a bounded semantic evaluation grounded in declared capabilities, and an exact
one-time user approval. Failed revisions preserve earlier `SKILL.md` versions
for rollback and invalidate prior evaluations. Metadata-first triggering keeps
unused skill bodies out of context.

## Citation-grounded compact research

Guardian records claims separately from source verification. Public source
bodies are size-limited, hashed, scanned for instruction-like content, and
discarded. The project brain retains only compact provenance and evidence
metadata.

```bash
guardian research citation-add \
  --url https://github.com/Orchestra-Research/AI-research-SKILLs \
  --title "Orchestra Research AI Research Skills" \
  --claim "Registered discovery source for AI research workflows" \
  --fetch

guardian research citation-list
guardian research citation-verify --id cite-xxxxxxxxxxxx
guardian research citation-handoff \
  --query "agent skills research evaluation" \
  --limit 5
```

Fetching permits only public HTTPS destinations, rejects embedded credentials,
private/link-local addresses and redirects, and never places fetched page bodies
in a model prompt. `citation-handoff-v1` explicitly labels titles, claims, and
excerpts as untrusted evidence data.

## Zero-completion maintenance

Guardian can perform routine health and regression work without spending model
completion tokens. Default jobs are deterministic evaluation, external-skill
audit, and evaluation-regression checks. Network jobs must be explicitly added.

```bash
guardian maintenance init

# Optional metadata-only checks; these do not request a model completion.
guardian maintenance add \
  --type provider-probe \
  --provider-id local-ollama \
  --model-id qwen3-coder:30b \
  --interval-seconds 3600

guardian maintenance add \
  --type citation-verify \
  --interval-seconds 86400
guardian maintenance add \
  --type omniroute-log-audit \
  --interval-seconds 900

guardian maintenance status
guardian maintenance run

# Print portable argv for cron/systemd/Task Scheduler; Guardian does not install it.
guardian maintenance scheduler
```

The runner uses a non-blocking project lock, bounded jobs per pass, exponential
failure backoff, and the persistent emergency stop. Scheduled model completions
are hard-disabled. GitHub repository citations use stable official repository
metadata, while ordinary HTML uses normalized visible content; raw response
hashes remain diagnostic and dynamic scripts do not create false change alerts.

## Secure MCP tool integration

Guardian can act as a restricted host for local MCP servers using the stdio transport. Registration does not imply trust: a server command must receive a one-time approval before it can start, and every tool must be discovered and explicitly allowlisted as `read` or `write`. Guardian pins the discovered tool schema so a server cannot silently change an approved tool contract.

```bash
# Register only; this does not execute the server
guardian mcp add \
  --id my-server \
  --command /absolute/path/to/server \
  --arg first-server-argument

# Approve and consume trust for this exact server ID
guardian policy request \
  --action mcp_trust_server \
  --target my-server \
  --reason "Reviewed this local MCP server command and source"
guardian policy approve --id req-xxxxxxxx
guardian mcp trust --id my-server --approval-id req-xxxxxxxx

# Start the trusted server temporarily and inspect its tools
guardian mcp discover --id my-server
guardian mcp allow --id my-server --tool exact_tool_name --mode read
guardian mcp call --id my-server --tool exact_tool_name --arguments '{"key":"value"}'
```

Write-capable tools require a separate one-time approval for the exact `server:tool` target:

```bash
guardian policy request \
  --action mcp_write_tool \
  --target my-server:write_tool \
  --reason "Approve this single state-changing tool call"
guardian policy approve --id req-yyyyyyyy
guardian mcp call \
  --id my-server \
  --tool write_tool \
  --arguments '{"key":"value"}' \
  --approval-id req-yyyyyyyy
```

This first MCP layer supports local stdio servers and `tools/list` plus `tools/call`. Remote Streamable HTTP, OAuth, resources, prompts, notifications, and long-running MCP tasks remain planned. A trusted local MCP command runs with the operating-system permissions of the Guardian user, so review its source and arguments before approval.

## Bounded supervisor

Guardian provides a durable coordination layer via the supervisor. It strictly recovers stale leases and creates bounded executor tickets for pending stages. **It never executes tasks, calls models, claims stages, or approves access requests.**

```bash
# Run one bounded supervisor cycle
guardian supervisor once

# Inspect current supervisor state and execution tickets
guardian supervisor status

# Run a foreground supervisor loop (defaults: 600s interval, 6 cycles)
guardian supervisor run \
  --interval-seconds 600 \
  --max-cycles 6
```

## Unified orchestration and execution governor

Start with one request. Guardian classifies it deterministically, selects no more
than five relevant profiles and the minimum built-in skills, previews a compact
local/free-limited route chain, and asks for confirmation. No model or external
action runs during this control-plane lifecycle.

```bash
guardian orchestrate start \
  --task "Implement an authenticated reporting API with tests" \
  --limit 5

guardian orchestrate confirm \
  --id orch-xxxxxxxxxxxx \
  --summary "Implement the confirmed reporting API scope and tests"

guardian orchestrate dispatch --id orch-xxxxxxxxxxxx
guardian orchestrate show --id orch-xxxxxxxxxxxx
guardian orchestrate list
guardian orchestrate recover --id orch-xxxxxxxxxxxx
```

After dispatch, the **execution governor** converts the orchestration into an
ordered, recoverable execution plan across local Ollama, FreeBuff, safe
free/free-limited OmniRoute specialist routes, one final-review-reserve route,
and a manual primary-model final-green-signal stage.

```bash
# Plan execution from a dispatched orchestration (idempotent)
guardian execution plan --orchestration-id orch-xxxxxxxxxxxx

# Inspect the execution plan and next stage
guardian execution show --id exec-xxxxxxxxxxxx
guardian execution next --id exec-xxxxxxxxxxxx

# Claim a synchronous stage with a lease, then record its result
guardian execution claim --id exec-xxxxxxxxxxxx --stage-id stage-1 --lease-seconds 900
guardian execution record --id exec-xxxxxxxxxxxx --stage-id stage-1 \
  --lease-id <lease> --outcome passed --evidence "Tests passed"

# For an external handoff, executor run returns both a lease ID and dispatch ID.
# The worker/result bridge must return both after independently verifying its work.
guardian executor run --max-tickets 1
guardian execution record --id exec-xxxxxxxxxxxx --stage-id stage-1 \
  --lease-id <lease> --dispatch-id <dispatch-id> \
  --outcome passed --evidence "Changes inspected; focused and full tests passed"

# List or recover a stopped execution
guardian execution list
guardian execution recover --id exec-xxxxxxxxxxxx
```

Key behaviors:

- **Slot reservation:** If a healthy final-review route exists, one of the five
  maximum automated slots is reserved for it so ordinary fallback stages cannot
  crowd it out.
- **Skip cascade:** A successful ordinary stage skips all remaining unused
  ordinary fallback stages and jumps directly to the terminal final-review or
  primary-review stage. Unused fallbacks are marked as skipped with a
  `stage_skip` event.
- **Failure continues:** A failed/skipped ordinary stage advances one step to
  the next fallback, preserving the fallback chain.
- **Durable external dispatch:** FreeBuff, Aider, model, and deterministic
  handoffs remain on the same `dispatched` stage until a verified result returns
  with the exact lease and random dispatch ID. Duplicate dispatches and
  stale/mismatched results are refused; timeouts fail safely to the next
  fallback instead of silently passing.
- **Claim-time revalidation:** Model policy, provider health, and observed
  quota/capacity windows are rechecked at claim time. If a route becomes
  prohibited, unhealthy, or temporarily exhausted after planning, the claim
  is refused before any request is sent.

The intended execution order is deterministic Guardian logic, local Ollama,
one bounded FreeBuff coding handoff when edits are needed, then a healthy
OmniRoute specialist only when local work is insufficient. GPT-5.5 remains the
last final-review reserve. The user's Codex, Claude, Gemini, or other primary
model reviews the compact diff/test/risk evidence and gives the final green
signal.

## Adaptive software-development workflow

Guardian uses the smallest safe process for each request:

- `fast`: reversible documentation or similarly small tasks; implementation and fresh verification.
- `standard`: design approval, plan, implementation, specification review, quality review, and fresh verification.
- `high_assurance`: the standard gates plus final explicit approval for security-sensitive, production, payment, identity, account, credential, deletion, deployment, or migration work.

```bash
guardian workflow start --request "Add a reporting dashboard" --risk auto
guardian skill select --task "Add a reporting dashboard" --profile standard

# Approval target is the returned workflow ID.
guardian policy request \
  --action workflow_design_approval \
  --target wf-xxxxxxxx \
  --reason "Approve the reviewed design"
guardian policy approve --id req-xxxxxxxx
guardian workflow advance \
  --id wf-xxxxxxxx \
  --evidence "Design document reviewed by user" \
  --approval-id req-xxxxxxxx

guardian workflow review --id wf-xxxxxxxx --type specification --status pass
guardian workflow review --id wf-xxxxxxxx --type quality --status pass
guardian workflow verify --id wf-xxxxxxxx --cmd "python3 -m unittest discover -s tests"
```

Review and verification stages cannot be skipped with a generic advance command. Verification runs a fresh command and retains its exit code and timestamp.

## Evidence-driven debugging

```bash
guardian debug start \
  --symptom "Authentication test fails with a 401" \
  --reproduction "Run the focused authentication test"
guardian debug hypothesis \
  --id dbg-xxxxxxxx \
  --hypothesis "The test token uses an expired timestamp" \
  --evidence "Decoded fixture expiration predates the test clock"
guardian debug attempt \
  --id dbg-xxxxxxxx \
  --change "Generate the fixture relative to the test clock" \
  --cmd "python3 -m unittest tests.test_auth" \
  --status pass \
  --evidence "Focused test and regression suite passed"
```

Guardian blocks a fourth guessed fix after three failures and requires architecture review.

## Real worktrees and cross-tool bootstraps

For git repositories, `guardian sandbox create` now creates a real git worktree. Non-git projects use an explicitly labelled copy fallback. Existing paths and branches are never overwritten.

```bash
guardian sandbox create --branch guardian/feature-reporting
guardian sandbox diff --path .agent/worktrees/guardian/feature-reporting

# Generate isolated integration files; existing files are preserved.
guardian bootstrap --target all
```

Bootstrap files are written under `.agent/integrations/` for Codex, Claude, Gemini, Antigravity, Cursor, and VS Code. They do not silently modify a user's repository-level agent instructions.

## Skills and specialist handoffs

```bash
# Keep a new capability in review until it is trusted
guardian skill draft \
  --name api-review \
  --description "Review API changes for compatibility and security" \
  --instructions "Inspect API contracts, tests, authentication, and error handling."
guardian skill promote --name api-review

# Prepare a compact handoff for a specialist worker
guardian worker dispatch --role security --task "Review the authentication change"
```

The present worker system creates structured handoff packages. Running a multi-agent team or a background worker daemon is still planned work, not a claim of current autonomous execution.

---

## 🧪 Running Tests

Run the full unit test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

---

## 🔒 Security Boundary

The `.agent/` project brain contains **only human-readable Markdown project records**. Credentials are referenced via environment variables or `vault://` secret references, ensuring API keys, passwords, and tokens are never included in plans, journey logs, or handoff packages.

For the encrypted local vault, set a passphrase in the current shell before storing or reading secrets. The passphrase itself is never saved by Guardian:

```bash
export GUARDIAN_VAULT_PASSPHRASE='use-a-unique-long-passphrase'
guardian vault store --key OPENROUTER_API_KEY --value '...'
```

The passphrase is required again after a restart. Existing legacy vault files are migrated when a secret is next stored.

Guardian intentionally will not bypass CAPTCHA or MFA, create fake identities, evade a provider quota/free-tier rule, accept legal terms, complete identity verification, submit payment, or use an unapproved external website. Those operations either stop or require a defined user approval path.

## Current implementation boundary

The repository is a working local foundation, not yet a finished universal autonomous agent. It includes durable project memory, compact handoff exports, provider routing, authenticated provider calls, encrypted local secret storage, task recovery, approvals, code verification, and bounded browser actions.

It deliberately does not bypass CAPTCHA/MFA, identity checks, payments, legal acceptance, or provider limits. Real Canva, Adobe, Lovable, VS Code, and Antigravity integrations still need their official connector/API or an authenticated user-visible browser session.

The roadmap still includes provider-specific account/quota polling, full
browser-profile management/manual takeover, signed skill provenance, an
always-on worker service, multi-user isolation, official subscription-service
connectors, and broader production evaluation/security hardening. See
[GUARDIAN_AGENT_PROJECT_PLAN.md](GUARDIAN_AGENT_PROJECT_PLAN.md) for the full
phased plan.

The adaptive engineering workflow is Guardian's own implementation, informed by established agent-development practices including the MIT-licensed [Superpowers](https://github.com/obra/superpowers) methodology. Guardian keeps the process risk-adaptive to avoid spending extra tokens on unnecessary agents or reviews.
