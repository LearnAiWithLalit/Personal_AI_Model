# Guardian Agent — Persistent Project Brain & Model Router

**Guardian Agent** is a local-first, persistent project brain and secret-free model gateway. It manages projects from requirement discovery through delivery, preserving requirements, decisions, plans, development journeys, and skills.

---

## 🚀 Quick Start (Git Clone & Setup)

To integrate Guardian Agent into your system or project repository:

```bash
# 1. Clone the repository
git clone https://github.com/your-username/guardian-agent.git
cd guardian-agent

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
```

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

## Current implementation boundary

The repository is a working local foundation, not yet a finished universal autonomous agent. It includes durable project memory, compact handoff exports, provider routing, authenticated provider calls, encrypted local secret storage, task recovery, approvals, code verification, and bounded browser actions.

It deliberately does not bypass CAPTCHA/MFA, identity checks, payments, legal acceptance, or provider limits. Real Canva, Adobe, Lovable, VS Code, and Antigravity integrations still need their official connector/API or an authenticated user-visible browser session.
