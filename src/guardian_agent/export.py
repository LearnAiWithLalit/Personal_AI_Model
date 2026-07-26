"""Token-Saving Handoff Exporters for Antigravity, Codex, and Claude Code.

Generates concise, context-minimized handoff packages formatted specifically for:
- Antigravity (AGY slash commands and subagent context)
- OpenAI Codex CLI / IDE extensions
- Claude Code CLI / Anthropic agents

Eliminates repetitive full-trajectory chat replays to minimize token consumption.
"""

from __future__ import annotations

from pathlib import Path
from guardian_agent.core import GuardianError, ProjectBrain, render_context, append_journey, markdown_escape


def export_handoff(brain: ProjectBrain, target: str = "antigravity") -> dict:
    clean_target = markdown_escape(target).lower()
    if clean_target not in {"antigravity", "codex", "claude"}:
        raise GuardianError(f"Unknown target exporter {clean_target!r}. Allowed: antigravity, codex, claude")
        
    context_text = render_context(brain)
    output_dir = brain.directory / "research"
    output_dir.mkdir(exist_ok=True)
    
    if clean_target == "antigravity":
        filename = "handoff_antigravity.md"
        header = (
            "# Antigravity Handoff Package\n\n"
            "> Token-optimized context package for Google Antigravity (AGY).\n"
            "> Use with slash commands (/goal, /subagent, /executing-plans).\n\n"
        )
    elif clean_target == "codex":
        filename = "handoff_codex.md"
        header = (
            "# Codex Handoff Package\n\n"
            "> Compact system prompt & task state for OpenAI Codex.\n\n"
        )
    else:
        filename = "handoff_claude.md"
        header = (
            "# Claude Code Handoff Package\n\n"
            "> Concise surgical task context for Claude Code / Anthropic models.\n\n"
        )
        
    full_content = f"{header}{context_text}\n"
    out_path = output_dir / filename
    out_path.write_text(full_content, encoding="utf-8")
    
    append_journey(
        brain,
        f"Exported Handoff Package: {clean_target}",
        [f"Saved to: {out_path}", "Token usage minimized."],
    )
    
    return {
        "target": clean_target,
        "path": str(out_path),
        "content_length": len(full_content),
    }
