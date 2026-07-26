"""Command line interface for Guardian Agent across Phases A through I."""

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
from guardian_agent.browser_operator import inspect_web_page


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

        if args.command == "export":
            print(json.dumps(export_handoff(brain, args.target), indent=2))
            return 0

        if args.command == "browser":
            if args.browser_command == "test":
                print(json.dumps(inspect_web_page(brain, args.url), indent=2))
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
