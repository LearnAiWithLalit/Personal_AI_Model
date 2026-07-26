"""Command line interface for Guardian Agent across Phases A through I, including Phase G0."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from guardian_agent.core import (
    GuardianError,
    confirm,
    initialize,
    intake,
    record_decision,
    record_lesson,
    render_context,
    require_brain,
    status,
)
from guardian_agent.gateway import (
    add_provider,
    choose_model,
    complete_task_with_model,
    complete_task_with_failover,
    configure_budget,
    configure_provider_access,
    discover_free_providers,
    discover_ollama_models,
    discover_omniroute_combos,
    provider_summary,
    probe_provider_capacity,
    get_budget_status,
    mark_omniroute_combo_free_limited,
    resolve_configured_route,
    setup_ollama_provider,
    setup_omniroute_provider,
)
from guardian_agent.skills import (
    create_skill_draft,
    evaluate_skill_draft,
    evaluate_skill_semantic,
    generate_skill_drafts,
    revise_generated_skill,
    list_builtin_skills,
    list_skills,
    promote_skill,
    select_builtin_skills,
    evaluate_builtin_skills,
)
from guardian_agent.research import build_handoff_package, inspect_repository
from guardian_agent.citations import (
    add_citation,
    build_citation_handoff,
    list_citations,
    verify_citation,
)
from guardian_agent.provider_capacity import provider_capacity_status
from guardian_agent.maintenance import (
    add_maintenance_job,
    initialize_maintenance,
    maintenance_status,
    run_due_maintenance,
    scheduler_instructions,
)
from guardian_agent.omniroute_logs import audit_omniroute_logs
from guardian_agent.learning import (
    apply_reusable_lessons,
    delete_reusable_lesson,
    list_lesson_candidates,
    promote_reusable_lesson,
    search_reusable_lessons,
)
from guardian_agent.coding import run_coding_loop, run_verification
from guardian_agent.operator import audit_log_action
from guardian_agent.creative import list_creative_artifacts, record_creative_artifact
from guardian_agent.workers import dispatch_worker, list_worker_roles
from guardian_agent.export import export_handoff
from guardian_agent.browser_operator import execute_browser_action, inspect_web_page
from guardian_agent.council import configure_council, load_council, run_council
from guardian_agent.freebuff import create_freebuff_handoff, freebuff_status, launch_freebuff
from guardian_agent.mcp import (
    allow_mcp_tool,
    call_mcp_tool,
    discover_mcp_tools,
    list_mcp_servers,
    register_mcp_server,
    trust_mcp_server,
)
from guardian_agent.bootstrap import generate_bootstrap
from guardian_agent.workflow import (
    advance_workflow,
    load_workflow,
    record_workflow_review,
    start_workflow,
    verify_workflow,
)
from guardian_agent.debugging import (
    add_debug_hypothesis,
    load_debug_case,
    record_debug_attempt,
    start_debug_case,
)
from guardian_agent.evaluation import evaluation_history, run_evaluation
from guardian_agent.profiles import (
    get_profile,
    list_profiles,
    prepare_profile_handoff,
    select_profiles,
    validate_catalog,
)
from guardian_agent.external_skills import (
    accept_quarantined_skill,
    audit_external_skills,
    inspect_quarantined_skill,
    list_external_sources,
    quarantine_external_skill,
    search_external_sources,
)
from guardian_agent.aider import (
    aider_status,
    build_aider_command,
    create_aider_handoff,
    launch_aider,
)

from guardian_agent.orchestration import (
    orchestrate_confirm,
    orchestrate_dispatch,
    orchestrate_list,
    orchestrate_recover,
    orchestrate_show,
    orchestrate_start,
)
from guardian_agent.execution import (
    claim_execution_stage,
    list_executions,
    next_execution_stage,
    plan_execution,
    record_execution_result,
    recover_execution,
    show_execution,
)
from guardian_agent.supervisor import (
    supervisor_run,
    supervisor_run_once,
    supervisor_status,
)
from guardian_agent.executor_worker import (
    list_ready_tickets,
    process_ready_tickets,
)
from guardian_agent.service import (
    backup_brain,
    generate_service_config,
    restore_brain,
    service_run,
    service_run_once,
    service_status,
)




# Phase G0 Imports
from guardian_agent.runtime import (
    enqueue_task,
    get_task_status,
    is_kill_switch_active,
    kill_switch,
    list_queued_tasks,
    recover_interrupted_tasks,
    resume_after_kill_switch,
)
from guardian_agent.policy import check_policy_permission, get_policy, load_approval_queue, request_action_approval, approve_action_request
from guardian_agent.vault import get_secret, has_secret, store_secret
from guardian_agent.sandbox import create_worktree_sandbox, generate_diff_preview, rollback_sandbox
from guardian_agent.health import check_provider_health


def _project_path(value: str) -> Path:
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guardian", description="Local-first project brain for Guardian Agent"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a project's .agent/ brain")
    init_parser.add_argument("project", nargs="?", default=".", type=_project_path)
    init_parser.add_argument("--name", default="")
    init_parser.add_argument("--purpose", default="")

    for command, help_text in (("intake", "Record a pending requirement"), ("confirm", "Confirm a requirement")):
        item = subparsers.add_parser(command, help=help_text)
        item.add_argument("--project", default=".", type=_project_path)
        item.add_argument("--request" if command == "intake" else "--summary", required=True)

    for command, help_text in (("decision", "Record a project decision"), ("lesson", "Record a reusable lesson")):
        item = subparsers.add_parser(command, help=help_text)
        item.add_argument("--project", default=".", type=_project_path)
        item.add_argument("--title", required=True)
        item.add_argument("--detail", required=True)

    for command, help_text in (("status", "Show project-brain status"), ("context", "Render compact model handoff context")):
        item = subparsers.add_parser(command, help=help_text)
        item.add_argument("--project", default=".", type=_project_path)

    learning = subparsers.add_parser(
        "learning", help="Manage approved reusable lessons across local projects"
    )
    learning_sub = learning.add_subparsers(dest="learning_command", required=True)
    learning_candidates = learning_sub.add_parser(
        "candidates", help="List private project lessons eligible for sanitization"
    )
    learning_candidates.add_argument("--project", default=".", type=_project_path)
    learning_promote = learning_sub.add_parser(
        "promote", help="Export an approved sanitized lesson to the local library"
    )
    learning_promote.add_argument("--project", default=".", type=_project_path)
    learning_promote.add_argument("--lesson-id", required=True)
    learning_promote.add_argument("--pattern", required=True)
    learning_promote.add_argument("--prevention", required=True)
    learning_promote.add_argument("--tag", action="append", required=True)
    learning_promote.add_argument("--approval-id", required=True)
    learning_promote.add_argument("--library", type=Path)
    learning_search = learning_sub.add_parser(
        "search", help="Search compact sanitized lessons without a model call"
    )
    learning_search.add_argument("--project", default=".", type=_project_path)
    learning_search.add_argument("--query", required=True)
    learning_search.add_argument("--limit", type=int, default=5)
    learning_search.add_argument("--library", type=Path)
    learning_apply = learning_sub.add_parser(
        "apply", help="Add relevant approved lessons to compact project context"
    )
    learning_apply.add_argument("--project", default=".", type=_project_path)
    learning_apply.add_argument("--query", required=True)
    learning_apply.add_argument("--limit", type=int, default=5)
    learning_apply.add_argument("--library", type=Path)
    learning_delete = learning_sub.add_parser(
        "delete", help="Delete one reusable lesson after exact approval"
    )
    learning_delete.add_argument("--project", default=".", type=_project_path)
    learning_delete.add_argument("--id", required=True, dest="lesson_id")
    learning_delete.add_argument("--approval-id", required=True)
    learning_delete.add_argument("--library", type=Path)

    # Provider Gateway
    provider = subparsers.add_parser("provider", help="Configure or inspect independent model providers")
    provider_subparsers = provider.add_subparsers(dest="provider_command", required=True)
    provider_add = provider_subparsers.add_parser("add", help="Add or update a provider model")
    provider_add.add_argument("--project", default=".", type=_project_path)
    provider_add.add_argument("--id", required=True, dest="provider_id")
    provider_add.add_argument("--kind", default="openai-compatible")
    provider_add.add_argument("--model", required=True, dest="model_id")
    provider_add.add_argument("--capability", action="append", dest="capabilities", default=[])
    provider_add.add_argument(
        "--cost-tier",
        choices=["local", "free", "free-limited", "subscription", "low", "paid"],
        default="free",
    )
    provider_add.add_argument("--priority", type=int, default=100)
    provider_add.add_argument("--base-url")
    provider_add.add_argument("--credential-env")
    provider_add.add_argument("--input-cost-per-million", type=float)
    provider_add.add_argument("--output-cost-per-million", type=float)
    
    provider_disc = provider_subparsers.add_parser("discover-free", help="Discover legitimate free tier providers")
    provider_disc.add_argument("--project", default=".", type=_project_path)
    
    provider_ollama = provider_subparsers.add_parser("setup-ollama", help="Register local Ollama provider endpoint")
    provider_ollama.add_argument("--project", default=".", type=_project_path)
    provider_ollama.add_argument("--model", default="qwen2.5-coder")
    provider_discover_ollama = provider_subparsers.add_parser(
        "discover-ollama", help="Discover and register installed local Ollama models"
    )
    provider_discover_ollama.add_argument("--project", default=".", type=_project_path)
    provider_discover_ollama.add_argument("--base-url", default="http://localhost:11434")

    provider_omniroute = provider_subparsers.add_parser(
        "setup-omniroute", help="Register the local OmniRoute endpoint"
    )
    provider_omniroute.add_argument("--project", default=".", type=_project_path)
    provider_omniroute.add_argument(
        "--model", required=True, help="Exact allowed OmniRoute combo or model ID"
    )
    provider_discover_omniroute = provider_subparsers.add_parser(
        "discover-omniroute", help="Audit live OmniRoute combos and register safe routes"
    )
    provider_discover_omniroute.add_argument("--project", default=".", type=_project_path)
    provider_discover_omniroute.add_argument("--base-url", default="http://localhost:3000")
    provider_discover_omniroute.add_argument("--credential-env")
    
    provider_list = provider_subparsers.add_parser("list", help="List configured providers")
    provider_list.add_argument("--project", default=".", type=_project_path)
    provider_route = provider_subparsers.add_parser("route", help="Select the lowest-cost capable model")
    provider_route.add_argument("--project", default=".", type=_project_path)
    provider_route.add_argument("--task", choices=["routing", "research", "planning", "coding", "review", "documentation"], required=True)
    provider_test = provider_subparsers.add_parser(
        "test", help="Run one tiny completion against an exact policy-approved route"
    )
    provider_test.add_argument("--project", default=".", type=_project_path)
    provider_test.add_argument("--id", required=True, dest="provider_id")
    provider_test.add_argument("--model", required=True)
    provider_test.add_argument(
        "--task",
        choices=["routing", "research", "planning", "coding", "review", "documentation"],
        default="routing",
    )
    provider_test.add_argument("--prompt", default="Return exactly: ROUTE_OK")
    provider_test.add_argument("--stream", action="store_true")
    provider_capacity = provider_subparsers.add_parser(
        "capacity", help="Show allowlisted rate-limit, retry, and latency telemetry"
    )
    provider_capacity.add_argument("--project", default=".", type=_project_path)
    provider_capacity.add_argument("--id", dest="provider_id")
    provider_probe = provider_subparsers.add_parser(
        "probe", help="Probe /models and rate-limit headers without a completion"
    )
    provider_probe.add_argument("--project", default=".", type=_project_path)
    provider_probe.add_argument("--id", required=True, dest="provider_id")
    provider_probe.add_argument("--model", required=True)
    provider_budget = provider_subparsers.add_parser(
        "budget", help="Show or configure persistent daily model budgets"
    )
    provider_budget.add_argument("--project", default=".", type=_project_path)
    provider_budget.add_argument("--daily-tokens", type=int)
    provider_budget.add_argument("--daily-cost-usd", type=float)
    provider_budget.add_argument("--max-completion-tokens", type=int)
    provider_access = provider_subparsers.add_parser(
        "access", help="Allow or deny subscription and metered paid routes"
    )
    provider_access.add_argument("--project", default=".", type=_project_path)
    provider_access.add_argument(
        "--allow-subscription",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    provider_access.add_argument(
        "--allow-paid",
        action=argparse.BooleanOptionalAction,
        default=None,
    )
    provider_mark_free = provider_subparsers.add_parser(
        "mark-free-limited",
        help="Record that one audited OmniRoute combo uses user-confirmed finite free quota",
    )
    provider_mark_free.add_argument("--project", default=".", type=_project_path)
    provider_mark_free.add_argument("--model", required=True)
    provider_logs = provider_subparsers.add_parser(
        "logs", help="Audit redacted local OmniRoute usage logs"
    )
    provider_logs.add_argument("--project", default=".", type=_project_path)
    provider_logs.add_argument("--base-url", default="http://localhost:3000")
    provider_logs.add_argument("--limit", type=int, default=100)

    evaluation = subparsers.add_parser(
        "evaluate", help="Run versioned routing and optional live model-quality evaluations"
    )
    evaluation.add_argument("--project", default=".", type=_project_path)
    evaluation.add_argument("--provider-id")
    evaluation.add_argument("--model-id")
    evaluation.add_argument("--history", action="store_true")

    # Phase G0: Runtime
    runtime_p = subparsers.add_parser("runtime", help="Durable task runtime and queue management")
    runtime_sub = runtime_p.add_subparsers(dest="runtime_command", required=True)
    r_enq = runtime_sub.add_parser("enqueue", help="Enqueue background task")
    r_enq.add_argument("--project", default=".", type=_project_path)
    r_enq.add_argument("--type", required=True)
    r_enq.add_argument("--summary", required=True)
    r_enq.add_argument("--priority", default="normal")
    r_lst = runtime_sub.add_parser("list", help="List queued tasks")
    r_lst.add_argument("--project", default=".", type=_project_path)
    r_kill = runtime_sub.add_parser("kill", help="Trigger emergency stop switch")
    r_kill.add_argument("--project", default=".", type=_project_path)
    r_recover = runtime_sub.add_parser("recover", help="Recover interrupted tasks without executing them")
    r_recover.add_argument("--project", default=".", type=_project_path)
    r_stop_status = runtime_sub.add_parser(
        "stop-status", help="Show persistent emergency-stop state"
    )
    r_stop_status.add_argument("--project", default=".", type=_project_path)
    r_resume = runtime_sub.add_parser(
        "resume", help="Resume automation after an approved emergency stop"
    )
    r_resume.add_argument("--project", default=".", type=_project_path)
    r_resume.add_argument("--approval-id", required=True)

    # Phase G0: Policy
    pol_p = subparsers.add_parser("policy", help="Policy-as-code and approval queue")
    pol_sub = pol_p.add_subparsers(dest="policy_command", required=True)
    p_chk = pol_sub.add_parser("check", help="Check action permission")
    p_chk.add_argument("--project", default=".", type=_project_path)
    p_chk.add_argument("--action", required=True)
    p_chk.add_argument("--target", default="")
    p_req = pol_sub.add_parser("request", help="Request action approval")
    p_req.add_argument("--project", default=".", type=_project_path)
    p_req.add_argument("--action", required=True)
    p_req.add_argument("--target", required=True)
    p_req.add_argument("--reason", required=True)
    p_req.add_argument("--user-id", default="user_default")
    p_req.add_argument("--account-id")
    p_req.add_argument("--connector")
    p_req.add_argument("--idempotency-key")
    p_req.add_argument("--expires-at")
    p_req.add_argument("--before-evidence")
    p_app = pol_sub.add_parser("approve", help="Approve action request")
    p_app.add_argument("--project", default=".", type=_project_path)
    p_app.add_argument("--id", required=True)


    # Phase G0: Vault
    vault_p = subparsers.add_parser("vault", help="Encrypted secret vault")
    vault_sub = vault_p.add_subparsers(dest="vault_command", required=True)
    v_str = vault_sub.add_parser("store", help="Store encrypted secret")
    v_str.add_argument("--project", default=".", type=_project_path)
    v_str.add_argument("--key", required=True)
    v_str.add_argument("--value", required=True)

    # Phase G0: Sandbox
    sb_p = subparsers.add_parser("sandbox", help="Git Worktree Sandbox control")
    sb_sub = sb_p.add_subparsers(dest="sandbox_command", required=True)
    s_crt = sb_sub.add_parser("create", help="Create worktree sandbox")
    s_crt.add_argument("--project", default=".", type=_project_path)
    s_crt.add_argument("--branch", required=True)
    s_diff = sb_sub.add_parser("diff", help="Generate worktree diff preview")
    s_diff.add_argument("--project", default=".", type=_project_path)
    s_diff.add_argument("--path", required=True)
    s_rb = sb_sub.add_parser("rollback", help="Rollback worktree sandbox")
    s_rb.add_argument("--project", default=".", type=_project_path)
    s_rb.add_argument("--path", required=True)

    # Phase G0: Health
    health_p = subparsers.add_parser("health", help="Provider health monitoring")
    health_sub = health_p.add_subparsers(dest="health_command", required=True)
    h_chk = health_sub.add_parser("check", help="Check provider health status")
    h_chk.add_argument("--project", default=".", type=_project_path)
    h_chk.add_argument("--provider", required=True)

    # Exporter
    export_p = subparsers.add_parser("export", help="Export token-saving handoff packages")
    export_p.add_argument("--project", default=".", type=_project_path)
    export_p.add_argument("--target", choices=["antigravity", "codex", "claude"], default="antigravity")

    # Browser Operator
    browser_p = subparsers.add_parser("browser", help="Computer Operator browser automation")
    browser_sub = browser_p.add_subparsers(dest="browser_command", required=True)
    b_test = browser_sub.add_parser("test", help="Inspect web page with Playwright/HTTP fallback")
    b_test.add_argument("--project", default=".", type=_project_path)
    b_test.add_argument("--url", required=True)
    b_test.add_argument("--account-id", help="Account ID for persistent profile and domain allowlist")

    b_action = browser_sub.add_parser("action", help="Run one policy-gated visible browser action")
    b_action.add_argument("--project", default=".", type=_project_path)
    b_action.add_argument("--url", required=True)
    b_action.add_argument(
        "--action",
        choices=[
            "navigate", "click_readonly", "fill", "screenshot", "submit",
            "publish", "purchase", "delete", "create_account", "accept_terms",
            "fill_credential", "identity_verification",
        ],
        required=True,
    )
    b_action.add_argument("--account-id", help="Account ID for persistent profile and domain allowlist")
    b_action.add_argument("--selector")
    b_action.add_argument("--value")
    b_action.add_argument("--approval-id", help="One approved request ID, required for sensitive actions such as submit")
    b_action.add_argument("--headless", action="store_true", help="Run hidden; visible browser is the default")


    council_p = subparsers.add_parser("council", help="Run an opt-in multi-model analysis council")
    council_sub = council_p.add_subparsers(dest="council_command", required=True)
    council_ask = council_sub.add_parser("ask", help="Collect opinions, anonymous reviews, and chairman synthesis")
    council_ask.add_argument("--project", default=".", type=_project_path)
    council_ask.add_argument("--task", choices=["research", "planning", "review", "documentation", "routing"], required=True)
    council_ask.add_argument("--prompt", required=True)
    council_ask.add_argument("--members", type=int)
    council_config = council_sub.add_parser("configure", help="Configure council member limit and chairman route")
    council_config.add_argument("--project", default=".", type=_project_path)
    council_config.add_argument("--members", type=int, required=True)
    council_config.add_argument("--chairman", help="Provider ID or provider:model route")
    council_show = council_sub.add_parser("show", help="Show council configuration")
    council_show.add_argument("--project", default=".", type=_project_path)

    freebuff_p = subparsers.add_parser("freebuff", help="Prepare or launch a Freebuff coding session")
    freebuff_sub = freebuff_p.add_subparsers(dest="freebuff_command", required=True)
    freebuff_status_p = freebuff_sub.add_parser("status", help="Check whether the Freebuff CLI is available")
    freebuff_status_p.add_argument("--project", default=".", type=_project_path)
    freebuff_prepare = freebuff_sub.add_parser("prepare", help="Create a compact Freebuff coding handoff")
    freebuff_prepare.add_argument("--project", default=".", type=_project_path)
    freebuff_prepare.add_argument("--task", required=True)
    freebuff_start = freebuff_sub.add_parser("start", help="Launch an interactive Freebuff session")
    freebuff_start.add_argument("--project", default=".", type=_project_path)
    freebuff_start.add_argument("--continue", dest="conversation_id", help="Continue a Freebuff conversation ID")

    aider_p = subparsers.add_parser("aider", help="Prepare or launch a bounded Aider worker")
    aider_sub = aider_p.add_subparsers(dest="aider_command", required=True)
    aider_status_p = aider_sub.add_parser("status", help="Inspect Aider and local backend availability")
    aider_status_p.add_argument("--project", default=".", type=_project_path)
    aider_prepare = aider_sub.add_parser("prepare", help="Create a profile-routed Aider handoff")
    aider_prepare.add_argument("--project", default=".", type=_project_path)
    aider_prepare.add_argument("--task", required=True)
    aider_prepare.add_argument("--limit", type=int, default=5)
    aider_command = aider_sub.add_parser("command", help="Preview the bounded Aider command")
    aider_command.add_argument("--project", default=".", type=_project_path)
    aider_command.add_argument("--task", required=True)
    aider_command.add_argument("--backend", choices=["ollama", "omniroute"], required=True)
    aider_command.add_argument("--model", required=True)
    aider_command.add_argument("--limit", type=int, default=5)
    aider_command.add_argument("--allow-edits", action="store_true")
    aider_start = aider_sub.add_parser("start", help="Launch Aider; dry-run is the default")
    aider_start.add_argument("--project", default=".", type=_project_path)
    aider_start.add_argument("--task", required=True)
    aider_start.add_argument("--backend", choices=["ollama", "omniroute"], required=True)
    aider_start.add_argument("--model", required=True)
    aider_start.add_argument("--limit", type=int, default=5)
    aider_start.add_argument("--allow-edits", action="store_true")

    mcp_p = subparsers.add_parser("mcp", help="Manage allowlisted MCP stdio servers and tools")
    mcp_sub = mcp_p.add_subparsers(dest="mcp_command", required=True)
    mcp_add = mcp_sub.add_parser("add", help="Register an untrusted local stdio server")
    mcp_add.add_argument("--project", default=".", type=_project_path)
    mcp_add.add_argument("--id", required=True)
    mcp_add.add_argument("--command", required=True)
    mcp_add.add_argument("--arg", action="append", default=[])
    mcp_list = mcp_sub.add_parser("list", help="List registered MCP servers")
    mcp_list.add_argument("--project", default=".", type=_project_path)
    mcp_trust = mcp_sub.add_parser("trust", help="Consume approval and trust one registered server command")
    mcp_trust.add_argument("--project", default=".", type=_project_path)
    mcp_trust.add_argument("--id", required=True)
    mcp_trust.add_argument("--approval-id", required=True)
    mcp_discover = mcp_sub.add_parser("discover", help="Discover tools from a trusted server")
    mcp_discover.add_argument("--project", default=".", type=_project_path)
    mcp_discover.add_argument("--id", required=True)
    mcp_allow = mcp_sub.add_parser("allow", help="Allow one discovered tool as read or write")
    mcp_allow.add_argument("--project", default=".", type=_project_path)
    mcp_allow.add_argument("--id", required=True)
    mcp_allow.add_argument("--tool", required=True)
    mcp_allow.add_argument("--mode", choices=["read", "write"], required=True)
    mcp_call = mcp_sub.add_parser("call", help="Call one allowlisted tool")
    mcp_call.add_argument("--project", default=".", type=_project_path)
    mcp_call.add_argument("--id", required=True)
    mcp_call.add_argument("--tool", required=True)
    mcp_call.add_argument("--arguments", default="{}", help="JSON object")
    mcp_call.add_argument("--approval-id", help="Required for write-capable tools")

    workflow_p = subparsers.add_parser("workflow", help="Run Guardian's adaptive development lifecycle")
    workflow_sub = workflow_p.add_subparsers(dest="workflow_command", required=True)
    workflow_start = workflow_sub.add_parser("start", help="Assess risk and start a gated workflow")
    workflow_start.add_argument("--project", default=".", type=_project_path)
    workflow_start.add_argument("--request", required=True)
    workflow_start.add_argument("--risk", choices=["auto", "low", "medium", "high"], default="auto")
    workflow_show = workflow_sub.add_parser("show", help="Show a workflow record")
    workflow_show.add_argument("--project", default=".", type=_project_path)
    workflow_show.add_argument("--id", required=True)
    workflow_advance = workflow_sub.add_parser("advance", help="Advance a non-review stage with evidence")
    workflow_advance.add_argument("--project", default=".", type=_project_path)
    workflow_advance.add_argument("--id", required=True)
    workflow_advance.add_argument("--evidence", required=True)
    workflow_advance.add_argument("--approval-id")
    workflow_review = workflow_sub.add_parser("review", help="Record specification or quality review")
    workflow_review.add_argument("--project", default=".", type=_project_path)
    workflow_review.add_argument("--id", required=True)
    workflow_review.add_argument("--type", choices=["specification", "quality"], required=True)
    workflow_review.add_argument("--status", choices=["pass", "fail"], required=True)
    workflow_review.add_argument("--finding", action="append", default=[])
    workflow_verify = workflow_sub.add_parser("verify", help="Run fresh verification for the active workflow")
    workflow_verify.add_argument("--project", default=".", type=_project_path)
    workflow_verify.add_argument("--id", required=True)
    workflow_verify.add_argument("--cmd", required=True)

    # Execution Governor
    execution_p = subparsers.add_parser(
        "execution", help="Durable execution governor lifecycle"
    )
    execution_sub = execution_p.add_subparsers(
        dest="execution_command", required=True
    )
    execution_plan_p = execution_sub.add_parser(
        "plan",
        help="Plan execution from a dispatched orchestration (idempotent)",
    )
    execution_plan_p.add_argument("--project", default=".", type=_project_path)
    execution_plan_p.add_argument(
        "--orchestration-id", required=True
    )
    execution_plan_p.add_argument("--lease-seconds", type=int, default=900)
    execution_show_p = execution_sub.add_parser(
        "show", help="Show a full execution record"
    )
    execution_show_p.add_argument("--project", default=".", type=_project_path)
    execution_show_p.add_argument("--id", required=True, dest="execution_id")
    execution_list_p = execution_sub.add_parser(
        "list", help="List all execution records"
    )
    execution_list_p.add_argument("--project", default=".", type=_project_path)
    execution_next_p = execution_sub.add_parser(
        "next", help="Show the next pending stage (read-only)"
    )
    execution_next_p.add_argument("--project", default=".", type=_project_path)
    execution_next_p.add_argument("--id", required=True, dest="execution_id")
    execution_claim_p = execution_sub.add_parser(
        "claim", help="Claim the current execution stage"
    )
    execution_claim_p.add_argument("--project", default=".", type=_project_path)
    execution_claim_p.add_argument("--id", required=True, dest="execution_id")
    execution_claim_p.add_argument("--stage-id", required=True)
    execution_claim_p.add_argument("--lease-seconds", type=int, default=900)
    execution_record_p = execution_sub.add_parser(
        "record", help="Record a stage execution result"
    )
    execution_record_p.add_argument("--project", default=".", type=_project_path)
    execution_record_p.add_argument("--id", required=True, dest="execution_id")
    execution_record_p.add_argument("--stage-id", required=True)
    execution_record_p.add_argument("--lease-id", required=True)
    execution_record_p.add_argument(
        "--dispatch-id",
        help="Required when reporting the verified result of an asynchronous dispatch",
    )
    execution_record_p.add_argument(
        "--outcome", required=True,
        choices=["passed", "failed", "skipped"],
    )
    execution_record_p.add_argument("--evidence", required=True)
    execution_record_p.add_argument("--artifact")
    execution_recover_p = execution_sub.add_parser(
        "recover", help="Expire stale claims (idempotent recovery)"
    )
    execution_recover_p.add_argument("--project", default=".", type=_project_path)
    execution_recover_p.add_argument("--id", required=True, dest="execution_id")

    # Supervisor
    supervisor_p = subparsers.add_parser(
        "supervisor", help="Bounded execution record and ticket supervisor"
    )
    supervisor_sub = supervisor_p.add_subparsers(
        dest="supervisor_command", required=True
    )
    supervisor_once_p = supervisor_sub.add_parser(
        "once", help="Run one bounded supervisor cycle"
    )
    supervisor_once_p.add_argument("--project", default=".", type=_project_path)
    supervisor_status_p = supervisor_sub.add_parser(
        "status", help="Return read-only supervisor state and ticket info"
    )
    supervisor_status_p.add_argument("--project", default=".", type=_project_path)
    supervisor_run_p = supervisor_sub.add_parser(
        "run", help="Run a bounded foreground supervisor loop"
    )
    supervisor_run_p.add_argument("--project", default=".", type=_project_path)
    supervisor_run_p.add_argument("--interval-seconds", type=int, default=600)
    supervisor_run_p.add_argument("--max-cycles", type=int, default=6)

    # Executor Worker CLI
    executor_p = subparsers.add_parser(
        "executor", help="Consume supervisor tickets and execute bounded work"
    )
    executor_sub = executor_p.add_subparsers(
        dest="executor_command", required=True
    )
    executor_ready_p = executor_sub.add_parser(
        "ready", help="List all ready supervisor tickets"
    )
    executor_ready_p.add_argument("--project", default=".", type=_project_path)
    executor_run_p = executor_sub.add_parser(
        "run", help="Process ready tickets up to limit"
    )
    executor_run_p.add_argument("--project", default=".", type=_project_path)
    executor_run_p.add_argument("--max-tickets", type=int, default=10)
    executor_run_p.add_argument("--dry-run", action="store_true")

    # Local Service & Brain Backup CLI
    service_p = subparsers.add_parser(
        "service", help="Local Guardian service management and brain backup/restore"
    )
    service_sub = service_p.add_subparsers(
        dest="service_command", required=True
    )
    s_status_p = service_sub.add_parser("status", help="Show local service and inbox status")
    s_status_p.add_argument("--project", default=".", type=_project_path)
    s_run_p = service_sub.add_parser("run", help="Run bounded foreground service loop")
    s_run_p.add_argument("--project", default=".", type=_project_path)
    s_run_p.add_argument("--interval-seconds", type=int, default=600)
    s_run_p.add_argument("--max-cycles", type=int, default=None)
    s_run_p.add_argument("--indefinite", action="store_true")
    s_run_p.add_argument("--max-tickets", type=int, default=5)
    s_run_p.add_argument("--dry-run", action="store_true")


    s_config_p = service_sub.add_parser("config", help="Generate service daemon config")
    s_config_p.add_argument("--project", default=".", type=_project_path)
    s_config_p.add_argument("--system", choices=["systemd", "launchd"], default="systemd")

    s_install_p = service_sub.add_parser("install", help="Install service daemon file into user system directory")
    s_install_p.add_argument("--project", default=".", type=_project_path)
    s_install_p.add_argument("--system", choices=["systemd", "launchd"], default="systemd")

    s_start_p = service_sub.add_parser("start", help="Start background service daemon")
    s_start_p.add_argument("--project", default=".", type=_project_path)
    s_start_p.add_argument("--system", choices=["systemd", "launchd"], default="systemd")

    s_stop_p = service_sub.add_parser("stop", help="Stop background service daemon")
    s_stop_p.add_argument("--project", default=".", type=_project_path)
    s_stop_p.add_argument("--system", choices=["systemd", "launchd"], default="systemd")

    s_uninst_p = service_sub.add_parser("uninstall", help="Uninstall background service daemon")
    s_uninst_p.add_argument("--project", default=".", type=_project_path)
    s_uninst_p.add_argument("--system", choices=["systemd", "launchd"], default="systemd")

    s_backup_p = service_sub.add_parser("backup", help="Archive .agent brain to tar.gz")
    s_backup_p.add_argument("--project", default=".", type=_project_path)
    s_backup_p.add_argument("--dest", type=Path)
    s_restore_p = service_sub.add_parser("restore", help="Restore .agent brain from tar.gz")
    s_restore_p.add_argument("--project", default=".", type=_project_path)
    s_restore_p.add_argument("--archive", type=Path, required=True)

    s_migrate_p = service_sub.add_parser("migrate", help="Migrate brain schema with pre-upgrade rollback")
    s_migrate_p.add_argument("--project", default=".", type=_project_path)
    s_migrate_p.add_argument(
        "--target-version",
        type=int,
        help="Target schema version; defaults to the latest version supported by this installation",
    )

    # Phase 4 — IDE & Coding Tool Adapter Control Plane

    adapter_p = subparsers.add_parser("adapter", help="IDE & coding tool adapter management")
    adapter_sub = adapter_p.add_subparsers(dest="adapter_command", required=True)

    a_detect_p = adapter_sub.add_parser("detect", help="Detect installed coding tools and IDE capabilities")
    a_detect_p.add_argument("--project", default=".", type=_project_path)

    a_config_p = adapter_sub.add_parser("generate", help="Generate IDE & tool configuration/entrypoints")
    a_config_p.add_argument("--project", default=".", type=_project_path)
    a_config_p.add_argument("--target", choices=["vscode", "codex", "claude", "gemini", "antigravity", "cursor", "all"], default="all")
    a_config_p.add_argument("--overwrite", action="store_true")
    # Use store_true/store_false pair so --no-root-harness works correctly
    a_config_root = a_config_p.add_mutually_exclusive_group()
    a_config_root.add_argument("--root-harness", dest="root_harness", action="store_true", default=True,
                               help="Place harness at project root (default)")
    a_config_root.add_argument("--no-root-harness", dest="root_harness", action="store_false",
                               help="Place harness in .agent/integrations/<target>/")

    a_handoff_p = adapter_sub.add_parser("handoff", help="Create fresh bounded handoff package for tool execution")
    a_handoff_p.add_argument("--project", default=".", type=_project_path)
    a_handoff_p.add_argument("--target", choices=["vscode", "codex", "claude", "gemini", "antigravity", "cursor"], required=True)
    a_handoff_p.add_argument("--execution-id", required=True)
    a_handoff_p.add_argument("--stage-index", type=int, default=0)

    a_record_p = adapter_sub.add_parser("record", help="Record verified worker result for execution lease")
    a_record_p.add_argument("--project", default=".", type=_project_path)
    a_record_p.add_argument("--target", choices=["vscode", "codex", "claude", "gemini", "antigravity", "cursor"], required=True)
    a_record_p.add_argument("--execution-id", required=True)
    a_record_p.add_argument("--stage-id", required=True)
    a_record_p.add_argument("--lease-id", required=True)
    a_record_p.add_argument("--dispatch-id", required=True)
    a_record_p.add_argument("--adapter-token", required=True,
                            help="Token from handoff package — binds result to correct adapter")
    a_record_p.add_argument("--outcome", choices=["passed", "failed", "skipped"], required=True)
    a_record_p.add_argument("--summary", required=True)
    a_record_p.add_argument("--verification-results", help="JSON string, JSON file path, or 'check:result' list for passed evidence")

    a_launch_p = adapter_sub.add_parser("launch", help="Launch or generate command for IDE/tool")
    a_launch_p.add_argument("--project", default=".", type=_project_path)
    a_launch_p.add_argument("--target", choices=["vscode", "codex", "claude", "gemini", "antigravity", "cursor"], required=True)
    a_launch_p.add_argument("--run", dest="execute", action="store_true", help="Execute version/capability check on binary")


    a_uninst_p = adapter_sub.add_parser("uninstall", help="Cleanly remove generated IDE entrypoints")
    a_uninst_p.add_argument("--project", default=".", type=_project_path)
    a_uninst_p.add_argument("--target", choices=["vscode", "codex", "claude", "gemini", "antigravity", "cursor", "all"], default="all")




    # Unified Orchestration Control Plane



    orchestrate_p = subparsers.add_parser(
        "orchestrate", help="Unified orchestration control plane lifecycle"
    )
    orchestrate_sub = orchestrate_p.add_subparsers(
        dest="orchestrate_command", required=True
    )
    orchestrate_start_p = orchestrate_sub.add_parser(
        "start",
        help="Classify task, select profiles/skills, preview routes, and create a draft",
    )
    orchestrate_start_p.add_argument("--project", default=".", type=_project_path)
    orchestrate_start_p.add_argument("--task", required=True)
    orchestrate_start_p.add_argument("--limit", type=int, default=5)
    orchestrate_start_p.add_argument(
        "--allowed-path", action="append", default=[], dest="allowed_paths",
        help="Explicit path allowed for writable task stages (e.g. src/auth/)"
    )
    orchestrate_start_p.add_argument(
        "--access-mode", choices=["read-only", "write"], default="read-only",
        help="Explicit access mode: read-only or write"
    )


    orchestrate_show_p = orchestrate_sub.add_parser(
        "show", help="Show a full orchestration record"
    )
    orchestrate_show_p.add_argument("--project", default=".", type=_project_path)
    orchestrate_show_p.add_argument("--id", required=True, dest="orchestration_id")
    orchestrate_list_p = orchestrate_sub.add_parser(
        "list", help="List all orchestration records"
    )
    orchestrate_list_p.add_argument("--project", default=".", type=_project_path)
    orchestrate_confirm_p = orchestrate_sub.add_parser(
        "confirm",
        help="Confirm a draft orchestration to record requirement and start workflow",
    )
    orchestrate_confirm_p.add_argument("--project", default=".", type=_project_path)
    orchestrate_confirm_p.add_argument(
        "--id", required=True, dest="orchestration_id"
    )
    orchestrate_confirm_p.add_argument("--summary", required=True)
    orchestrate_dispatch_p = orchestrate_sub.add_parser(
        "dispatch",
        help="Dispatch a confirmed orchestration: write a compact handoff (idempotent)",
    )
    orchestrate_dispatch_p.add_argument("--project", default=".", type=_project_path)
    orchestrate_dispatch_p.add_argument(
        "--id", required=True, dest="orchestration_id"
    )
    orchestrate_recover_p = orchestrate_sub.add_parser(
        "recover",
        help="Idempotent recovery: return current state without side effects",
    )
    orchestrate_recover_p.add_argument("--project", default=".", type=_project_path)
    orchestrate_recover_p.add_argument(
        "--id", required=True, dest="orchestration_id"
    )

    debug_p = subparsers.add_parser("debug", help="Record evidence-driven root-cause debugging")
    debug_sub = debug_p.add_subparsers(dest="debug_command", required=True)
    debug_start = debug_sub.add_parser("start", help="Start a reproducible debugging case")
    debug_start.add_argument("--project", default=".", type=_project_path)
    debug_start.add_argument("--symptom", required=True)
    debug_start.add_argument("--reproduction", required=True)
    debug_show = debug_sub.add_parser("show", help="Show a debugging evidence ledger")
    debug_show.add_argument("--project", default=".", type=_project_path)
    debug_show.add_argument("--id", required=True)
    debug_hypothesis = debug_sub.add_parser("hypothesis", help="Record one falsifiable root-cause hypothesis")
    debug_hypothesis.add_argument("--project", default=".", type=_project_path)
    debug_hypothesis.add_argument("--id", required=True)
    debug_hypothesis.add_argument("--hypothesis", required=True)
    debug_hypothesis.add_argument("--evidence", required=True)
    debug_attempt = debug_sub.add_parser("attempt", help="Record one minimal fix attempt and result")
    debug_attempt.add_argument("--project", default=".", type=_project_path)
    debug_attempt.add_argument("--id", required=True)
    debug_attempt.add_argument("--change", required=True)
    debug_attempt.add_argument("--cmd", required=True)
    debug_attempt.add_argument("--status", choices=["pass", "fail"], required=True)
    debug_attempt.add_argument("--evidence", required=True)

    bootstrap_p = subparsers.add_parser("bootstrap", help="Generate portable Guardian harness entry points")
    bootstrap_p.add_argument("--project", default=".", type=_project_path)
    bootstrap_p.add_argument(
        "--target",
        choices=["all", "codex", "claude", "gemini", "antigravity", "cursor", "vscode"],
        default="all",
    )
    bootstrap_p.add_argument("--overwrite", action="store_true")
    bootstrap_p.add_argument("--root", action="store_true", dest="root_harness", help="Write root harness files directly in project root")


    # Run completion
    run_parser = subparsers.add_parser("run", help="Execute task completion using routed model")
    run_parser.add_argument("--project", default=".", type=_project_path)
    run_parser.add_argument("--task", choices=["routing", "research", "planning", "coding", "review", "documentation"], required=True)
    run_parser.add_argument("--prompt", required=True)
    run_parser.add_argument("--failover", action="store_true", help="Try bounded healthy routes in cost order")
    run_parser.add_argument("--max-attempts", type=int)
    run_parser.add_argument("--stream", action="store_true")

    maintenance = subparsers.add_parser(
        "maintenance", help="Run zero-completion audits, probes, and regression checks"
    )
    maintenance_sub = maintenance.add_subparsers(
        dest="maintenance_command", required=True
    )
    maintenance_init = maintenance_sub.add_parser(
        "init", help="Install safe local maintenance defaults"
    )
    maintenance_init.add_argument("--project", default=".", type=_project_path)
    maintenance_add = maintenance_sub.add_parser(
        "add", help="Add or update a maintenance job"
    )
    maintenance_add.add_argument("--project", default=".", type=_project_path)
    maintenance_add.add_argument(
        "--type",
        required=True,
        choices=[
            "deterministic-evaluation",
            "external-skill-audit",
            "evaluation-regression-check",
            "provider-probe",
            "citation-verify",
            "omniroute-log-audit",
        ],
    )
    maintenance_add.add_argument("--interval-seconds", type=int, required=True)
    maintenance_add.add_argument("--provider-id")
    maintenance_add.add_argument("--model-id")
    maintenance_show = maintenance_sub.add_parser(
        "status", help="Show jobs, due state, and emergency-stop state"
    )
    maintenance_show.add_argument("--project", default=".", type=_project_path)
    maintenance_run = maintenance_sub.add_parser(
        "run", help="Run due zero-completion maintenance jobs"
    )
    maintenance_run.add_argument("--project", default=".", type=_project_path)
    maintenance_run.add_argument("--max-jobs", type=int, default=10)
    maintenance_run.add_argument("--force", action="store_true")
    maintenance_scheduler = maintenance_sub.add_parser(
        "scheduler", help="Print portable scheduler argv without installing a daemon"
    )
    maintenance_scheduler.add_argument("--project", default=".", type=_project_path)

    # Skill Factory
    skill_parser = subparsers.add_parser("skill", help="Manage skill factory drafts and trusted skills")
    skill_sub = skill_parser.add_subparsers(dest="skill_command", required=True)
    s_draft = skill_sub.add_parser("draft", help="Create a skill draft")
    s_draft.add_argument("--project", default=".", type=_project_path)
    s_draft.add_argument("--name", required=True)
    s_draft.add_argument("--description", required=True)
    s_draft.add_argument("--instructions", required=True)
    s_prom = skill_sub.add_parser("promote", help="Promote skill draft to trusted")
    s_prom.add_argument("--project", default=".", type=_project_path)
    s_prom.add_argument("--name", required=True)
    s_prom.add_argument("--approval-id")
    s_list = skill_sub.add_parser("list", help="List all skills")
    s_list.add_argument("--project", default=".", type=_project_path)
    s_builtins = skill_sub.add_parser("builtins", help="List packaged adaptive workflow skills")
    s_builtins.add_argument("--project", default=".", type=_project_path)
    s_select = skill_sub.add_parser("select", help="Select relevant packaged skills for a task")
    s_select.add_argument("--project", default=".", type=_project_path)
    s_select.add_argument("--task", required=True)
    s_select.add_argument("--profile", choices=["fast", "standard", "high_assurance"], default="standard")
    s_evaluate = skill_sub.add_parser("evaluate", help="Run deterministic built-in skill trigger checks")
    s_evaluate.add_argument("--project", default=".", type=_project_path)
    s_generate = skill_sub.add_parser(
        "generate", help="Generate multiple untrusted skill drafts in one bounded model call"
    )
    s_generate.add_argument("--project", default=".", type=_project_path)
    s_generate.add_argument("--requirement", required=True)
    s_generate.add_argument("--count", type=int, default=1)
    s_generate.add_argument("--provider-id", required=True)
    s_generate.add_argument("--model-id", required=True)
    s_evaluate_draft = skill_sub.add_parser(
        "evaluate-draft", help="Evaluate one model-generated draft before promotion"
    )
    s_evaluate_draft.add_argument("--project", default=".", type=_project_path)
    s_evaluate_draft.add_argument("--name", required=True)
    s_evaluate_semantic = skill_sub.add_parser(
        "evaluate-semantic", help="Run an advisory semantic quality gate on a generated draft"
    )
    s_evaluate_semantic.add_argument("--project", default=".", type=_project_path)
    s_evaluate_semantic.add_argument("--name", required=True)
    s_evaluate_semantic.add_argument("--provider-id", required=True)
    s_evaluate_semantic.add_argument("--model-id", required=True)
    s_revise_generated = skill_sub.add_parser(
        "revise-generated", help="Revise a semantically failed draft and retain rollback history"
    )
    s_revise_generated.add_argument("--project", default=".", type=_project_path)
    s_revise_generated.add_argument("--name", required=True)
    s_revise_generated.add_argument("--provider-id", required=True)
    s_revise_generated.add_argument("--model-id", required=True)
    s_revise_generated.add_argument(
        "--available-capability",
        action="append",
        dest="available_capabilities",
        default=[],
    )
    s_sources = skill_sub.add_parser("sources", help="List researched external skill sources")
    s_sources.add_argument("--project", default=".", type=_project_path)
    s_search_external = skill_sub.add_parser(
        "search-external", help="Search source metadata without loading skill bodies"
    )
    s_search_external.add_argument("--project", default=".", type=_project_path)
    s_search_external.add_argument("--query", required=True)
    s_search_external.add_argument("--limit", type=int, default=10)
    s_import_external = skill_sub.add_parser(
        "import-external", help="Fetch one registered raw SKILL.md into quarantine"
    )
    s_import_external.add_argument("--project", default=".", type=_project_path)
    s_import_external.add_argument("--source", required=True)
    s_import_external.add_argument("--url", required=True)
    s_inspect_external = skill_sub.add_parser(
        "inspect-quarantine", help="Recheck provenance, integrity, and risk findings"
    )
    s_inspect_external.add_argument("--project", default=".", type=_project_path)
    s_inspect_external.add_argument("--name", required=True)
    s_accept_external = skill_sub.add_parser(
        "accept-import", help="Consume approval and move a safe import to drafts"
    )
    s_accept_external.add_argument("--project", default=".", type=_project_path)
    s_accept_external.add_argument("--name", required=True)
    s_accept_external.add_argument("--approval-id", required=True)
    s_audit_external = skill_sub.add_parser(
        "audit-external", help="Re-scan all imported skills and verify their hashes"
    )
    s_audit_external.add_argument("--project", default=".", type=_project_path)

    # Searchable specialist role profiles
    profile_parser = subparsers.add_parser(
        "profile", help="Search and inspect the token-efficient specialist catalog"
    )
    profile_sub = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list", help="List compact profile metadata")
    profile_list.add_argument("--project", default=".", type=_project_path)
    profile_list.add_argument("--domain")
    profile_show = profile_sub.add_parser("show", help="Expand one profile by ID or slug")
    profile_show.add_argument("--project", default=".", type=_project_path)
    profile_show.add_argument("--id", required=True, dest="profile_id")
    profile_select = profile_sub.add_parser(
        "select", help="Select only relevant profiles for a task"
    )
    profile_select.add_argument("--project", default=".", type=_project_path)
    profile_select.add_argument("--task", required=True)
    profile_select.add_argument("--limit", type=int, default=5)
    profile_select.add_argument("--domain")
    profile_validate = profile_sub.add_parser("validate", help="Validate the packaged catalog")
    profile_validate.add_argument("--project", default=".", type=_project_path)
    profile_dispatch = profile_sub.add_parser(
        "dispatch", help="Route a task and save a bounded specialist handoff"
    )
    profile_dispatch.add_argument("--project", default=".", type=_project_path)
    profile_dispatch.add_argument("--task", required=True)
    profile_dispatch.add_argument("--limit", type=int, default=5)

    # Research
    res_parser = subparsers.add_parser("research", help="Repository research and work packages")
    res_sub = res_parser.add_subparsers(dest="research_command", required=True)
    r_insp = res_sub.add_parser("inspect", help="Inspect repository structure")
    r_insp.add_argument("--project", default=".", type=_project_path)
    r_pkg = res_sub.add_parser("package", help="Build compact handoff package")
    r_pkg.add_argument("--project", default=".", type=_project_path)
    r_pkg.add_argument("--task", required=True)
    r_pkg.add_argument("--target", action="append", dest="targets", default=[])
    r_citation_add = res_sub.add_parser(
        "citation-add", help="Record a compact claim/source citation"
    )
    r_citation_add.add_argument("--project", default=".", type=_project_path)
    r_citation_add.add_argument("--url", required=True)
    r_citation_add.add_argument("--claim", required=True)
    r_citation_add.add_argument("--title", default="")
    r_citation_add.add_argument("--publisher", default="")
    r_citation_add.add_argument("--evidence", default="")
    r_citation_add.add_argument("--fetch", action="store_true")
    r_citation_list = res_sub.add_parser(
        "citation-list", help="List compact citation records"
    )
    r_citation_list.add_argument("--project", default=".", type=_project_path)
    r_citation_verify = res_sub.add_parser(
        "citation-verify", help="Re-fetch and compare one citation source"
    )
    r_citation_verify.add_argument("--project", default=".", type=_project_path)
    r_citation_verify.add_argument("--id", required=True, dest="citation_id")
    r_citation_handoff = res_sub.add_parser(
        "citation-handoff", help="Build a compact injection-resistant evidence handoff"
    )
    r_citation_handoff.add_argument("--project", default=".", type=_project_path)
    r_citation_handoff.add_argument("--query", required=True)
    r_citation_handoff.add_argument("--limit", type=int, default=10)

    # Coding & Sandbox
    code_parser = subparsers.add_parser("code", help="Execute coding loops and verifications")
    code_sub = code_parser.add_subparsers(dest="code_command", required=True)
    c_verif = code_sub.add_parser("verify", help="Run test verification")
    c_verif.add_argument("--project", default=".", type=_project_path)
    c_verif.add_argument("--cmd", required=True)

    # Operator Audit
    op_parser = subparsers.add_parser("operator", help="Computer Operator actions")
    op_sub = op_parser.add_subparsers(dest="operator_command", required=True)
    o_aud = op_sub.add_parser("audit", help="Record operator action audit")
    o_aud.add_argument("--project", default=".", type=_project_path)
    o_aud.add_argument("--action", required=True)
    o_aud.add_argument("--target", required=True)
    o_aud.add_argument("--status", default="success")

    # Creative Assets
    crea_parser = subparsers.add_parser("creative", help="Creative subscription assets")
    crea_sub = crea_parser.add_subparsers(dest="creative_command", required=True)
    c_rec = crea_sub.add_parser("record", help="Record creative artifact")
    c_rec.add_argument("--project", default=".", type=_project_path)
    c_rec.add_argument("--tool", required=True)
    c_rec.add_argument("--name", required=True)
    c_rec.add_argument("--url", required=True)
    c_rec.add_argument("--notes")
    c_lst = crea_sub.add_parser("list", help="List creative artifacts")
    c_lst.add_argument("--project", default=".", type=_project_path)

    # Specialist Workers
    work_parser = subparsers.add_parser("worker", help="Specialist worker protocols")
    work_sub = work_parser.add_subparsers(dest="worker_command", required=True)
    w_roles = work_sub.add_parser("roles", help="List specialist worker roles")
    w_roles.add_argument("--project", default=".", type=_project_path)
    w_disp = work_sub.add_parser("dispatch", help="Dispatch task to worker")
    w_disp.add_argument("--project", default=".", type=_project_path)
    w_disp.add_argument("--role", required=True)
    w_disp.add_argument("--task", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            brain = initialize(args.project, args.name, args.purpose)
            print(f"Initialized Guardian project brain: {brain.directory}")
            return 0

        brain = require_brain(args.project)
        
        if args.command == "provider":
            if args.provider_command == "add":
                provider = add_provider(
                    brain,
                    provider_id=args.provider_id,
                    kind=args.kind,
                    model_id=args.model_id,
                    capabilities=args.capabilities,
                    cost_tier=args.cost_tier,
                    priority=args.priority,
                    base_url=args.base_url,
                    credential_env=args.credential_env,
                    input_cost_per_million=args.input_cost_per_million,
                    output_cost_per_million=args.output_cost_per_million,
                )
                print(f"Configured provider {provider.id}.")
            elif args.provider_command == "discover-free":
                print(json.dumps(discover_free_providers(brain), indent=2))
            elif args.provider_command == "setup-ollama":
                print(json.dumps(setup_ollama_provider(brain, args.model), indent=2))
            elif args.provider_command == "discover-ollama":
                print(json.dumps(discover_ollama_models(brain, args.base_url), indent=2))
            elif args.provider_command == "setup-omniroute":
                print(json.dumps(setup_omniroute_provider(brain, args.model), indent=2))
            elif args.provider_command == "discover-omniroute":
                print(json.dumps(discover_omniroute_combos(
                    brain, args.base_url, args.credential_env
                ), indent=2))
            elif args.provider_command == "list":
                print(json.dumps(provider_summary(brain), indent=2))
            elif args.provider_command == "route":
                print(json.dumps(choose_model(brain, args.task), indent=2))
            elif args.provider_command == "test":
                route = resolve_configured_route(
                    brain, args.task, args.provider_id, args.model
                )
                result = complete_task_with_model(
                    brain,
                    args.task,
                    args.prompt,
                    route=route,
                    stream=args.stream,
                    on_chunk=(
                        (lambda chunk: print(chunk, end="", flush=True))
                        if args.stream else None
                    ),
                )
                if args.stream:
                    print()
                    result = {**result, "response": "<streamed above>"}
                print(json.dumps(result, indent=2))
            elif args.provider_command == "budget":
                if any(value is not None for value in (
                    args.daily_tokens,
                    args.daily_cost_usd,
                    args.max_completion_tokens,
                )):
                    result = configure_budget(
                        brain,
                        daily_tokens=args.daily_tokens,
                        daily_cost_usd=args.daily_cost_usd,
                        max_completion_tokens=args.max_completion_tokens,
                    )
                else:
                    result = get_budget_status(brain)
                print(json.dumps(result, indent=2))
            elif args.provider_command == "capacity":
                print(json.dumps(
                    provider_capacity_status(brain, args.provider_id),
                    indent=2,
                ))
            elif args.provider_command == "probe":
                print(json.dumps(
                    probe_provider_capacity(
                        brain,
                        args.provider_id,
                        args.model,
                    ),
                    indent=2,
                ))
            elif args.provider_command == "access":
                print(json.dumps(
                    configure_provider_access(
                        brain,
                        allow_subscription=args.allow_subscription,
                        allow_paid=args.allow_paid,
                    ),
                    indent=2,
                ))
            elif args.provider_command == "mark-free-limited":
                print(json.dumps(
                    mark_omniroute_combo_free_limited(brain, args.model),
                    indent=2,
                ))
            elif args.provider_command == "logs":
                print(json.dumps(
                    audit_omniroute_logs(
                        brain,
                        base_url=args.base_url,
                        limit=args.limit,
                    ),
                    indent=2,
                ))
            return 0

        if args.command == "runtime":
            if args.runtime_command == "enqueue":
                print(json.dumps(enqueue_task(brain, args.type, args.summary, args.priority), indent=2))
            elif args.runtime_command == "list":
                print(json.dumps(list_queued_tasks(brain), indent=2))
            elif args.runtime_command == "kill":
                print(json.dumps(kill_switch(brain), indent=2))
            elif args.runtime_command == "recover":
                print(json.dumps(recover_interrupted_tasks(brain), indent=2))
            elif args.runtime_command == "stop-status":
                print(json.dumps({"active": is_kill_switch_active(brain)}, indent=2))
            elif args.runtime_command == "resume":
                print(json.dumps(
                    resume_after_kill_switch(brain, args.approval_id),
                    indent=2,
                ))
            return 0

        if args.command == "learning":
            if args.learning_command == "candidates":
                result = {"candidates": list_lesson_candidates(brain)}
            elif args.learning_command == "promote":
                result = promote_reusable_lesson(
                    brain,
                    args.lesson_id,
                    pattern=args.pattern,
                    prevention=args.prevention,
                    tags=args.tag,
                    approval_id=args.approval_id,
                    library_path=args.library,
                )
            elif args.learning_command == "search":
                result = search_reusable_lessons(
                    args.query,
                    limit=args.limit,
                    library_path=args.library,
                )
            elif args.learning_command == "apply":
                result = apply_reusable_lessons(
                    brain,
                    args.query,
                    limit=args.limit,
                    library_path=args.library,
                )
            else:
                result = delete_reusable_lesson(
                    brain,
                    args.lesson_id,
                    args.approval_id,
                    library_path=args.library,
                )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "evaluate":
            result = (
                evaluation_history(brain)
                if args.history
                else run_evaluation(
                    brain,
                    provider_id=args.provider_id,
                    model_id=args.model_id,
                )
            )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "policy":
            if args.policy_command == "check":
                print(json.dumps({"action": args.action, "permission": check_policy_permission(brain, args.action, args.target)}, indent=2))
            elif args.policy_command == "request":
                print(json.dumps(request_action_approval(
                    brain,
                    args.action,
                    args.target,
                    args.reason,
                    user_id=args.user_id,
                    account_id=args.account_id,
                    connector_scope=args.connector,
                    idempotency_key=args.idempotency_key,
                    expires_at=args.expires_at,
                    before_evidence=args.before_evidence,
                ), indent=2))

            elif args.policy_command == "approve":
                print(json.dumps(approve_action_request(brain, args.id), indent=2))
            return 0

        if args.command == "vault":
            if args.vault_command == "store":
                print(json.dumps(store_secret(brain, args.key, args.value), indent=2))
            return 0

        if args.command == "sandbox":
            if args.sandbox_command == "create":
                print(json.dumps(create_worktree_sandbox(brain, args.branch), indent=2))
            elif args.sandbox_command == "diff":
                print(json.dumps(generate_diff_preview(brain, args.path), indent=2))
            elif args.sandbox_command == "rollback":
                print(json.dumps(rollback_sandbox(brain, args.path), indent=2))
            return 0

        if args.command == "health":
            if args.health_command == "check":
                print(json.dumps(check_provider_health(brain, args.provider), indent=2))
            return 0

        if args.command == "export":
            print(json.dumps(export_handoff(brain, args.target), indent=2))
            return 0

        if args.command == "browser":
            if args.browser_command == "test":
                print(json.dumps(inspect_web_page(brain, args.url, account_id=args.account_id), indent=2))
            elif args.browser_command == "action":
                print(json.dumps(execute_browser_action(
                    brain, url=args.url, action=args.action, account_id=args.account_id, selector=args.selector,
                    value=args.value, visible=not args.headless, approval_id=args.approval_id,
                ), indent=2))

            return 0

        if args.command == "council":
            if args.council_command == "ask":
                print(json.dumps(run_council(brain, task=args.task, prompt=args.prompt, max_members=args.members), indent=2))
            elif args.council_command == "configure":
                print(json.dumps(configure_council(brain, args.members, args.chairman), indent=2))
            elif args.council_command == "show":
                print(json.dumps(load_council(brain), indent=2))
            return 0

        if args.command == "freebuff":
            if args.freebuff_command == "status":
                print(json.dumps(freebuff_status(), indent=2))
            elif args.freebuff_command == "prepare":
                print(json.dumps(create_freebuff_handoff(brain, args.task), indent=2))
            elif args.freebuff_command == "start":
                return launch_freebuff(brain, args.conversation_id)
            return 0

        if args.command == "aider":
            if args.aider_command == "status":
                print(json.dumps(aider_status(), indent=2))
                return 0
            if args.aider_command == "prepare":
                result = create_aider_handoff(brain, args.task, args.limit)
                print(json.dumps(result, indent=2))
                return 0
            if args.aider_command == "command":
                result = build_aider_command(
                    brain,
                    args.task,
                    args.backend,
                    args.model,
                    dry_run=not args.allow_edits,
                    limit=args.limit,
                )
                print(json.dumps(result, indent=2))
                return 0
            return launch_aider(
                brain,
                args.task,
                args.backend,
                args.model,
                dry_run=not args.allow_edits,
                limit=args.limit,
            )

        if args.command == "mcp":
            if args.mcp_command == "add":
                print(json.dumps(register_mcp_server(brain, args.id, args.command, args.arg), indent=2))
            elif args.mcp_command == "list":
                print(json.dumps(list_mcp_servers(brain), indent=2))
            elif args.mcp_command == "trust":
                print(json.dumps(trust_mcp_server(brain, args.id, args.approval_id), indent=2))
            elif args.mcp_command == "discover":
                print(json.dumps(discover_mcp_tools(brain, args.id), indent=2))
            elif args.mcp_command == "allow":
                print(json.dumps(allow_mcp_tool(brain, args.id, args.tool, args.mode), indent=2))
            elif args.mcp_command == "call":
                try:
                    arguments = json.loads(args.arguments)
                except json.JSONDecodeError as error:
                    raise GuardianError(f"MCP arguments must be valid JSON: {error}") from error
                if not isinstance(arguments, dict):
                    raise GuardianError("MCP arguments must be a JSON object.")
                print(json.dumps(call_mcp_tool(brain, args.id, args.tool, arguments, args.approval_id), indent=2))
            return 0

        if args.command == "supervisor":
            if args.supervisor_command == "once":
                result = supervisor_run_once(brain)
            elif args.supervisor_command == "status":
                result = supervisor_status(brain)
            elif args.supervisor_command == "run":
                result = supervisor_run(
                    brain,
                    interval_seconds=args.interval_seconds,
                    max_cycles=args.max_cycles,
                )
            else:
                raise GuardianError(f"Unknown supervisor command: {args.supervisor_command}")
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "executor":
            if args.executor_command == "ready":
                result = list_ready_tickets(brain)
            elif args.executor_command == "run":
                result = process_ready_tickets(
                    brain,
                    max_tickets=args.max_tickets,
                    dry_run=args.dry_run,
                )
            else:
                raise GuardianError(f"Unknown executor command: {args.executor_command}")
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "service":
            if args.service_command == "status":
                result = service_status(brain)
            elif args.service_command == "run":
                max_cycles = None if args.indefinite else (args.max_cycles if args.max_cycles is not None else 6)
                if max_cycles == 1:
                    result = service_run_once(
                        brain,
                        max_tickets=args.max_tickets,
                        dry_run=args.dry_run,
                    )
                else:
                    result = service_run(
                        brain,
                        interval_seconds=args.interval_seconds,
                        max_cycles=max_cycles,
                        max_tickets=args.max_tickets,
                        dry_run=args.dry_run,
                    )

            elif args.service_command == "config":
                result = generate_service_config(brain.root, system_kind=args.system)
            elif args.service_command == "install":
                from guardian_agent.service import install_service
                result = install_service(brain.root, system_kind=args.system)
            elif args.service_command == "start":
                from guardian_agent.service import start_service
                result = start_service(brain.root, system_kind=args.system)
            elif args.service_command == "stop":
                from guardian_agent.service import stop_service
                result = stop_service(brain.root, system_kind=args.system)
            elif args.service_command == "uninstall":
                from guardian_agent.service import uninstall_service
                result = uninstall_service(brain.root, system_kind=args.system)
            elif args.service_command == "backup":
                result = backup_brain(brain, destination=args.dest)
            elif args.service_command == "restore":
                result = restore_brain(brain.root, archive_path=args.archive)
            elif args.service_command == "migrate":
                from guardian_agent.service import migrate_brain
                result = (
                    migrate_brain(brain)
                    if args.target_version is None
                    else migrate_brain(brain, target_version=args.target_version)
                )
            else:
                raise GuardianError(f"Unknown service command: {args.service_command}")
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "adapter":
            from guardian_agent.adapters import (
                create_bounded_handoff,
                detect_installed_tools,
                generate_adapter_config,
                launch_adapter_tool,
                submit_adapter_result,
                uninstall_adapter_config,
            )
            if args.adapter_command == "detect":
                result = detect_installed_tools()
            elif args.adapter_command == "generate":
                result = generate_adapter_config(
                    brain,
                    target=args.target,
                    overwrite=args.overwrite,
                    root_harness=args.root_harness,
                )
            elif args.adapter_command == "handoff":
                result = create_bounded_handoff(
                    brain,
                    target=args.target,
                    execution_id=args.execution_id,
                    stage_index=args.stage_index,
                )
            elif args.adapter_command == "record":
                ver_results = None
                if args.verification_results:
                    raw = args.verification_results.strip()
                    if raw.startswith("[") or raw.startswith("{"):
                        ver_results = json.loads(raw)
                        if isinstance(ver_results, dict):
                            ver_results = [ver_results]
                    elif Path(raw).is_file():
                        fcontent = Path(raw).read_text(encoding="utf-8")
                        ver_results = json.loads(fcontent)
                        if isinstance(ver_results, dict):
                            ver_results = [ver_results]

                    else:
                        # Parse key:value or check=status comma-separated
                        ver_results = []
                        for item in raw.split(","):
                            if ":" in item:
                                k, v = item.split(":", 1)
                                ver_results.append({"check": k.strip(), "result": v.strip()})
                            elif "=" in item:
                                k, v = item.split("=", 1)
                                ver_results.append({"check": k.strip(), "result": v.strip()})

                result = submit_adapter_result(
                    brain,
                    target=args.target,
                    execution_id=args.execution_id,
                    stage_id=args.stage_id,
                    lease_id=args.lease_id,
                    dispatch_id=args.dispatch_id,
                    adapter_token=args.adapter_token,
                    outcome=args.outcome,
                    summary=args.summary,
                    verification_results=ver_results,
                )
            elif args.adapter_command == "launch":
                result = launch_adapter_tool(brain, target=args.target, execute=args.execute)

            elif args.adapter_command == "uninstall":
                result = uninstall_adapter_config(brain, target=args.target)
            else:
                raise GuardianError(f"Unknown adapter command: {args.adapter_command}")
            print(json.dumps(result, indent=2))
            return 0






        if args.command == "execution":
            if args.execution_command == "plan":
                result = plan_execution(brain, args.orchestration_id, args.lease_seconds)
            elif args.execution_command == "show":
                result = show_execution(brain, args.execution_id)
            elif args.execution_command == "list":
                result = list_executions(brain)
            elif args.execution_command == "next":
                result = next_execution_stage(brain, args.execution_id)
            elif args.execution_command == "claim":
                result = claim_execution_stage(brain, args.execution_id, args.stage_id, args.lease_seconds)
            elif args.execution_command == "record":
                result = record_execution_result(
                    brain, args.execution_id, args.stage_id, args.lease_id,
                    args.outcome, args.evidence, args.artifact, args.dispatch_id,
                )
            elif args.execution_command == "recover":
                result = recover_execution(brain, args.execution_id)
            else:
                raise GuardianError(f"Unknown execution command: {args.execution_command}")
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "orchestrate":
            if args.orchestrate_command == "start":
                result = orchestrate_start(brain, args.task, args.limit, approved_paths=args.allowed_paths, access_mode=args.access_mode)

                # Print the human-readable preview first, then the structured result
                print(result["preview_text"])
                return 0

            elif args.orchestrate_command == "show":
                result = orchestrate_show(brain, args.orchestration_id)
            elif args.orchestrate_command == "list":
                result = orchestrate_list(brain)
            elif args.orchestrate_command == "confirm":
                result = orchestrate_confirm(brain, args.orchestration_id, args.summary)
            elif args.orchestrate_command == "dispatch":
                result = orchestrate_dispatch(brain, args.orchestration_id)
            elif args.orchestrate_command == "recover":
                result = orchestrate_recover(brain, args.orchestration_id)
            else:
                raise GuardianError(f"Unknown orchestrate command: {args.orchestrate_command}")
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "workflow":
            if args.workflow_command == "start":
                result = start_workflow(brain, args.request, args.risk)
            elif args.workflow_command == "show":
                result = load_workflow(brain, args.id)
            elif args.workflow_command == "advance":
                result = advance_workflow(brain, args.id, args.evidence, args.approval_id)
            elif args.workflow_command == "review":
                result = record_workflow_review(
                    brain, args.id, args.type, args.status == "pass", args.finding
                )
            else:
                result = verify_workflow(brain, args.id, args.cmd)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "debug":
            if args.debug_command == "start":
                result = start_debug_case(brain, args.symptom, args.reproduction)
            elif args.debug_command == "show":
                result = load_debug_case(brain, args.id)
            elif args.debug_command == "hypothesis":
                result = add_debug_hypothesis(brain, args.id, args.hypothesis, args.evidence)
            else:
                result = record_debug_attempt(
                    brain, args.id, args.change, args.cmd,
                    args.status == "pass", args.evidence,
                )
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "bootstrap":
            print(json.dumps(generate_bootstrap(brain, args.target, args.overwrite, root_harness=args.root_harness), indent=2))
            return 0


        if args.command == "run":
            if args.stream and args.failover:
                raise GuardianError(
                    "Streaming with failover is not supported because a partial stream "
                    "cannot be safely replayed on another route."
                )
            if args.failover:
                res = complete_task_with_failover(
                    brain, args.task, args.prompt, max_attempts=args.max_attempts
                )
            else:
                res = complete_task_with_model(
                    brain,
                    args.task,
                    args.prompt,
                    stream=args.stream,
                    on_chunk=(
                        (lambda chunk: print(chunk, end="", flush=True))
                        if args.stream else None
                    ),
                )
            if args.stream:
                print()
                res = {**res, "response": "<streamed above>"}
            print(json.dumps(res, indent=2))
            return 0

        if args.command == "maintenance":
            if args.maintenance_command == "init":
                result = initialize_maintenance(brain)
            elif args.maintenance_command == "add":
                result = add_maintenance_job(
                    brain,
                    args.type,
                    args.interval_seconds,
                    provider_id=args.provider_id,
                    model_id=args.model_id,
                )
            elif args.maintenance_command == "status":
                result = maintenance_status(brain)
            elif args.maintenance_command == "run":
                result = run_due_maintenance(
                    brain,
                    max_jobs=args.max_jobs,
                    force=args.force,
                )
            else:
                result = scheduler_instructions(brain)
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "skill":
            if args.skill_command == "draft":
                res = create_skill_draft(brain, args.name, args.description, args.instructions)
                print(json.dumps(res, indent=2))
            elif args.skill_command == "promote":
                res = promote_skill(brain, args.name, args.approval_id)
                print(json.dumps(res, indent=2))
            elif args.skill_command == "list":
                print(json.dumps(list_skills(brain), indent=2))
            elif args.skill_command == "builtins":
                print(json.dumps(list_builtin_skills(), indent=2))
            elif args.skill_command == "select":
                print(json.dumps(select_builtin_skills(args.task, args.profile), indent=2))
            elif args.skill_command == "evaluate":
                print(json.dumps(evaluate_builtin_skills(), indent=2))
            elif args.skill_command == "generate":
                print(json.dumps(generate_skill_drafts(
                    brain,
                    args.requirement,
                    args.count,
                    args.provider_id,
                    args.model_id,
                ), indent=2))
            elif args.skill_command == "evaluate-draft":
                print(json.dumps(evaluate_skill_draft(brain, args.name), indent=2))
            elif args.skill_command == "evaluate-semantic":
                print(json.dumps(evaluate_skill_semantic(
                    brain,
                    args.name,
                    args.provider_id,
                    args.model_id,
                ), indent=2))
            elif args.skill_command == "revise-generated":
                print(json.dumps(revise_generated_skill(
                    brain,
                    args.name,
                    args.provider_id,
                    args.model_id,
                    args.available_capabilities,
                ), indent=2))
            elif args.skill_command == "sources":
                print(json.dumps(list_external_sources(), indent=2))
            elif args.skill_command == "search-external":
                print(json.dumps(search_external_sources(args.query, args.limit), indent=2))
            elif args.skill_command == "import-external":
                print(json.dumps(
                    quarantine_external_skill(brain, args.source, args.url), indent=2
                ))
            elif args.skill_command == "inspect-quarantine":
                print(json.dumps(inspect_quarantined_skill(brain, args.name), indent=2))
            elif args.skill_command == "accept-import":
                print(json.dumps(
                    accept_quarantined_skill(brain, args.name, args.approval_id),
                    indent=2,
                ))
            elif args.skill_command == "audit-external":
                print(json.dumps(audit_external_skills(brain), indent=2))
            return 0

        if args.command == "profile":
            if args.profile_command == "list":
                result = list_profiles(args.domain)
            elif args.profile_command == "show":
                result = get_profile(args.profile_id)
            elif args.profile_command == "select":
                result = select_profiles(args.task, args.limit, args.domain)
            elif args.profile_command == "dispatch":
                result = prepare_profile_handoff(brain, args.task, args.limit)
            else:
                result = validate_catalog()
            print(json.dumps(result, indent=2))
            return 0

        if args.command == "research":
            if args.research_command == "inspect":
                print(json.dumps(inspect_repository(brain.root), indent=2))
            elif args.research_command == "package":
                res = build_handoff_package(brain, args.task, args.targets)
                print(json.dumps(res, indent=2))
            elif args.research_command == "citation-add":
                print(json.dumps(add_citation(
                    brain,
                    url=args.url,
                    claim=args.claim,
                    title=args.title,
                    publisher=args.publisher,
                    evidence=args.evidence,
                    fetch=args.fetch,
                ), indent=2))
            elif args.research_command == "citation-list":
                print(json.dumps(list_citations(brain), indent=2))
            elif args.research_command == "citation-verify":
                print(json.dumps(
                    verify_citation(brain, args.citation_id),
                    indent=2,
                ))
            elif args.research_command == "citation-handoff":
                print(json.dumps(
                    build_citation_handoff(brain, args.query, args.limit),
                    indent=2,
                ))
            return 0

        if args.command == "code":
            if args.code_command == "verify":
                print(json.dumps(run_verification(brain.root, args.cmd), indent=2))
            return 0

        if args.command == "operator":
            if args.operator_command == "audit":
                res = audit_log_action(brain, args.action, args.target, args.status)
                print(json.dumps(res, indent=2))
            return 0

        if args.command == "creative":
            if args.creative_command == "record":
                res = record_creative_artifact(brain, args.tool, args.name, args.url, args.notes)
                print(json.dumps(res, indent=2))
            elif args.creative_command == "list":
                print(json.dumps(list_creative_artifacts(brain), indent=2))
            return 0

        if args.command == "worker":
            if args.worker_command == "roles":
                print(json.dumps(list_worker_roles(), indent=2))
            elif args.worker_command == "dispatch":
                res = dispatch_worker(brain, args.role, args.task)
                print(json.dumps(res, indent=2))
            return 0

        if args.command == "intake":
            intake(brain, args.request)
            print("Requirement recorded as pending confirmation.")
        elif args.command == "confirm":
            confirm(brain, args.summary)
            print("Requirement confirmed and added to the plan.")
        elif args.command == "decision":
            record_decision(brain, args.title, args.detail)
            print("Decision recorded.")
        elif args.command == "lesson":
            record_lesson(brain, args.title, args.detail)
            print("Lesson recorded.")
        elif args.command == "context":
            print(render_context(brain))
        elif args.command == "status":
            print(json.dumps(status(brain), indent=2))
        return 0
    except GuardianError as error:
        parser.error(str(error))
    return 2
