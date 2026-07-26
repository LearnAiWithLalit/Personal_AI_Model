# Guardian Specialist Profile Catalog

## Outcome

Guardian packages the original 150 planned specialist roles as a local,
validated catalog. Profiles are searchable work contracts; they are not 150
continuously running agents. A task normally expands one to five relevant
profiles, then the configured primary model or user retains final authority.

## Why the catalog is compact

Loading every role definition into every prompt would defeat Guardian's
token-saving purpose. The implementation therefore uses progressive
disclosure:

1. Keep the full catalog as local Python metadata.
2. Tokenize and score the task without an LLM call.
3. Expand only profiles with positive trigger matches.
4. Save those contracts with compact project context in one handoff.
5. Report a transparent four-characters-per-token estimate comparing the full
   serialized catalog with the selected payload.

Each expanded contract includes identity, domain, mission, triggers,
capabilities, tool classes, skill hints, risk, approval actions, input/output
contracts, verification, provenance, model tier, and prohibited models.

## Source research and adopted patterns

- [Orchestra Research AI Research Skills](https://github.com/Orchestra-Research/AI-research-SKILLs)
  demonstrates a central orchestration layer routing to deep domain skills,
  cross-harness installation, and broad AI-research lifecycle coverage.
  Guardian adopts orchestration plus on-demand domain specialization, without
  copying third-party skill text.
- [Addy Osmani's Web Quality Skills](https://github.com/addyosmani/web-quality-skills)
  groups focused, stack-agnostic skills by clear trigger phrases and quality
  outcomes. Guardian profiles use explicit triggers and verification contracts.
- [VoltAgent Awesome Agent Skills](https://github.com/VoltAgent/awesome-agent-skills)
  documents cross-tool skill paths and recommends short discovery metadata,
  on-demand resource loading, scoped tools, and explicit dependencies. Guardian
  follows those progressive-disclosure and least-privilege principles.
- [Thinking Partner](https://skillsllm.com/skill/thinking-partner) uses a
  deterministic process to choose among many mental models instead of dumping
  the complete library into every response. Guardian likewise performs local,
  deterministic first-stage selection.
- [Awesome Agent Skills MCP](https://mcpservers.org/servers/shadowrootdev/awesome-agent-skills-mcp)
  exposes list, get, invoke, and refresh operations over a cached skill
  registry. Guardian's profile list, show, select, validate, and dispatch
  commands provide the safe local analogue. Third-party MCP imports remain
  untrusted until they pass Guardian's existing MCP trust and allowlist gates.
- [AGNT's 100 Best AI Agent Skills](https://agnt.gg/articles/100-best-ai-agent-skills)
  provides an editorial taxonomy across development, design, data, documents,
  content, security, business, automation, collaboration, DevOps, creative, and
  enterprise work. Guardian uses it as a discovery signal only because licenses
  and trust vary across the linked upstream projects.

## Boundaries

- A role does not imply that a model, account, subscription, or tool is
  available.
- Profiles cannot bypass approval gates, CAPTCHA, identity checks, payments,
  legal acceptance, provider terms, or website policies.
- Imported skills require provenance, licensing review, prompt-injection
  inspection, validation, and explicit trust before activation.
- The local prohibited-model policy is included in every expanded contract.
- Catalog token estimates are directional, not tokenizer-specific billing
  guarantees.

## Extension path

The skill factory may create future task-specific skills. New specialist
profiles should be added only when they represent a distinct work contract,
not merely a synonym. Every addition must preserve unique IDs/slugs, include
verification and approval metadata, document provenance, and pass catalog
validation and routing tests.
