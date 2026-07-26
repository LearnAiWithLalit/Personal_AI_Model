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
    discover_free_providers,
    provider_summary,
    setup_ollama_provider,
)
from guardian_agent.skills import create_skill_draft, list_skills, promote_skill
from guardian_agent.research import build_handoff_package, inspect_repository
from guardian_agent.coding import run_coding_loop, run_verification
from guardian_agent.operator import audit_log_action
from guardian_agent.creative import list_creative_artifacts, record_creative_artifact
from guardian_agent.workers import dispatch_worker, list_worker_roles
from guardian_agent.export import export_handoff
from guardian_agent.browser_operator import execute_browser_action, inspect_web_page
from guardian_agent.council import configure_council, load_council, run_council
from guardian_agent.freebuff import create_freebuff_handoff, freebuff_status, launch_freebuff

# Phase G0 Imports
from guardian_agent.runtime import enqueue_task, get_task_status, kill_switch, list_queued_tasks, recover_interrupted_tasks
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

    # Provider Gateway
    provider = subparsers.add_parser("provider", help="Configure or inspect independent model providers")
    provider_subparsers = provider.add_subparsers(dest="provider_command", required=True)
    provider_add = provider_subparsers.add_parser("add", help="Add or update a provider model")
    provider_add.add_argument("--project", default=".", type=_project_path)
    provider_add.add_argument("--id", required=True, dest="provider_id")
    provider_add.add_argument("--kind", default="openai-compatible")
    provider_add.add_argument("--model", required=True, dest="model_id")
    provider_add.add_argument("--capability", action="append", dest="capabilities", default=[])
    provider_add.add_argument("--cost-tier", choices=["local", "free", "low", "paid"], default="free")
    provider_add.add_argument("--priority", type=int, default=100)
    provider_add.add_argument("--base-url")
    provider_add.add_argument("--credential-env")
    
    provider_disc = provider_subparsers.add_parser("discover-free", help="Discover legitimate free tier providers")
    provider_disc.add_argument("--project", default=".", type=_project_path)
    
    provider_ollama = provider_subparsers.add_parser("setup-ollama", help="Register local Ollama provider endpoint")
    provider_ollama.add_argument("--project", default=".", type=_project_path)
    provider_ollama.add_argument("--model", default="qwen2.5-coder")
    
    provider_list = provider_subparsers.add_parser("list", help="List configured providers")
    provider_list.add_argument("--project", default=".", type=_project_path)
    provider_route = provider_subparsers.add_parser("route", help="Select the lowest-cost capable model")
    provider_route.add_argument("--project", default=".", type=_project_path)
    provider_route.add_argument("--task", choices=["routing", "research", "planning", "coding", "review", "documentation"], required=True)

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
    b_action = browser_sub.add_parser("action", help="Run one policy-gated visible browser action")
    b_action.add_argument("--project", default=".", type=_project_path)
    b_action.add_argument("--url", required=True)
    b_action.add_argument("--action", choices=["navigate", "click", "fill", "screenshot", "submit"], required=True)
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

    # Run completion
    run_parser = subparsers.add_parser("run", help="Execute task completion using routed model")
    run_parser.add_argument("--project", default=".", type=_project_path)
    run_parser.add_argument("--task", choices=["routing", "research", "planning", "coding", "review", "documentation"], required=True)
    run_parser.add_argument("--prompt", required=True)

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
    s_list = skill_sub.add_parser("list", help="List all skills")
    s_list.add_argument("--project", default=".", type=_project_path)

    # Research
    res_parser = subparsers.add_parser("research", help="Repository research and work packages")
    res_sub = res_parser.add_subparsers(dest="research_command", required=True)
    r_insp = res_sub.add_parser("inspect", help="Inspect repository structure")
    r_insp.add_argument("--project", default=".", type=_project_path)
    r_pkg = res_sub.add_parser("package", help="Build compact handoff package")
    r_pkg.add_argument("--project", default=".", type=_project_path)
    r_pkg.add_argument("--task", required=True)
    r_pkg.add_argument("--target", action="append", dest="targets", default=[])

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
                )
                print(f"Configured provider {provider.id}.")
            elif args.provider_command == "discover-free":
                print(json.dumps(discover_free_providers(brain), indent=2))
            elif args.provider_command == "setup-ollama":
                print(json.dumps(setup_ollama_provider(brain, args.model), indent=2))
            elif args.provider_command == "list":
                print(json.dumps(provider_summary(brain), indent=2))
            elif args.provider_command == "route":
                print(json.dumps(choose_model(brain, args.task), indent=2))
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
            return 0

        if args.command == "policy":
            if args.policy_command == "check":
                print(json.dumps({"action": args.action, "permission": check_policy_permission(brain, args.action, args.target)}, indent=2))
            elif args.policy_command == "request":
                print(json.dumps(request_action_approval(brain, args.action, args.target, args.reason), indent=2))
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
                print(json.dumps(inspect_web_page(brain, args.url), indent=2))
            elif args.browser_command == "action":
                print(json.dumps(execute_browser_action(
                    brain, url=args.url, action=args.action, selector=args.selector,
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

        if args.command == "run":
            res = complete_task_with_model(brain, args.task, args.prompt)
            print(json.dumps(res, indent=2))
            return 0

        if args.command == "skill":
            if args.skill_command == "draft":
                res = create_skill_draft(brain, args.name, args.description, args.instructions)
                print(json.dumps(res, indent=2))
            elif args.skill_command == "promote":
                res = promote_skill(brain, args.name)
                print(json.dumps(res, indent=2))
            elif args.skill_command == "list":
                print(json.dumps(list_skills(brain), indent=2))
            return 0

        if args.command == "research":
            if args.research_command == "inspect":
                print(json.dumps(inspect_repository(brain.root), indent=2))
            elif args.research_command == "package":
                res = build_handoff_package(brain, args.task, args.targets)
                print(json.dumps(res, indent=2))
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
