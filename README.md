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
| Secure MCP tools | Registers local stdio MCP servers as untrusted, discovers tools after server approval, pins tool schemas, and gates write-capable calls with one-time approval. |

## How Guardian fits into a workflow

```text
User request
  -> Guardian records and confirms scope
  -> project brain supplies only relevant context and lessons
  -> router selects a configured local/free/paid worker by policy
  -> worker produces code, research, or a handoff package
  -> Guardian runs verification, records evidence, and updates journey memory
  -> sensitive browser/external actions pause for approval
```

This makes it useful with a local model, Ollama, an OpenAI-compatible gateway, or a preferred cloud coding tool. Each installation owns its own `.agent/` memory, provider configuration, credentials, and browser sessions.

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

---

## 🔌 Model Providers & Free API Discovery

Guardian Agent supports bringing your own API keys via environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `NVIDIA_API_KEY`, `OMNIROUTE_API_KEY`):

```bash
# Register a custom model provider endpoint
guardian provider add \
  --id my-local \
  --kind local \
  --model qwen2.5-coder \
  --capability coding \
  --cost-tier local \
  --base-url http://localhost:11434/v1

# Install optional, unverified development seeds (OpenRouter / local OmniRoute).
# This is not live provider discovery; validate each provider before use.
guardian provider discover-free

# Setup local Ollama provider endpoint
guardian provider setup-ollama --model qwen2.5-coder
```

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

The roadmap also includes verified live provider discovery, quota and budget controls, full browser-profile management/manual takeover, citation-aware research, signed skill provenance, a worker daemon, multi-user isolation, and production evaluation/security hardening. See [GUARDIAN_AGENT_PROJECT_PLAN.md](GUARDIAN_AGENT_PROJECT_PLAN.md) for the full phased plan.
