"""Installable Local Guardian Service & Brain Backup/Restore (Phase 3).

Provides foreground service execution cycles, systemd/launchd configuration generators,
install/start/stop/uninstall lifecycle management, heartbeat tracking, primary-review inbox inspection,
service logging with bounded rotation, and brain schema migration with automatic pre-upgrade rollback.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
import xml.sax.saxutils
from pathlib import Path
from typing import Any

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, now_utc
from guardian_agent.execution import reconcile_dispatched_handoffs
from guardian_agent.executor_worker import process_ready_tickets

from guardian_agent.runtime import is_kill_switch_active, tasks_dir
from guardian_agent.supervisor import supervisor_run_once, supervisor_status

_DEFAULT_HISTORY_LIMIT = 100
_CURRENT_BRAIN_SCHEMA_VERSION = 2


def _heartbeat_file(brain: ProjectBrain) -> Path:
    return tasks_dir(brain) / "service_heartbeat.json"


def _service_lock_file(brain: ProjectBrain) -> Path:
    return tasks_dir(brain) / ".service.pid.lock"


def _service_log_file(brain: ProjectBrain) -> Path:
    return tasks_dir(brain) / "service.log"


def _schema_version_file(brain: ProjectBrain) -> Path:
    return brain.directory / "schema_version.json"


def _apply_schema_migration(brain: ProjectBrain, target_version: int) -> None:
    """Apply one explicit, deterministic schema step."""
    if target_version != 2:
        raise GuardianError(f"No migration implementation exists for schema version {target_version}.")

    project_file = brain.directory / "PROJECT.md"
    if not project_file.is_file():
        raise GuardianError("Schema v2 migration requires .agent/PROJECT.md.")

    manifest = {
        "format": "guardian-brain-schema",
        "version": 2,
        "features": [
            "durable-execution-dispatch",
            "isolated-project-service",
            "transactional-brain-restore",
        ],
        "migrated_at": now_utc(),
    }
    manifest_path = brain.directory / "schema_manifest.json"
    temporary = manifest_path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)


def _service_unit_name(project_path: Path, system_kind: str = "systemd") -> tuple[str, str]:
    """Generate isolated unique service name and filename per project to prevent multi-project collisions."""
    abs_p = project_path.resolve()
    path_hash = hashlib.sha256(str(abs_p).encode("utf-8")).hexdigest()[:8]
    import re
    raw_slug = abs_p.name.lower()
    slug = re.sub(r"[^a-z0-9\-]", "-", raw_slug).strip("-") or "project"
    if system_kind == "systemd":
        unit_name = f"guardian-agent-{slug}-{path_hash}.service"
        return unit_name, unit_name
    elif system_kind == "launchd":
        label = f"com.guardian.agent.{slug}-{path_hash}"
        return label, f"{label}.plist"
    else:
        raise GuardianError(f"Unsupported service system kind {system_kind!r}.")


def _rotate_service_log(log_path: Path, max_bytes: int = 5_000_000, backup_count: int = 3) -> None:
    """Bounded log rotation for local service logs."""
    if not log_path.exists() or log_path.stat().st_size < max_bytes:
        return
    for i in range(backup_count - 1, 0, -1):
        s = log_path.with_name(f"{log_path.name}.{i}")
        d = log_path.with_name(f"{log_path.name}.{i+1}")
        if s.exists():
            shutil.move(str(s), str(d))
    shutil.move(str(log_path), str(log_path.with_name(f"{log_path.name}.1")))


def _append_service_log(brain: ProjectBrain, message: str) -> None:
    try:
        path = _service_log_file(brain)
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_service_log(path)
        timestamp = now_utc()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [PID {os.getpid()}] {message}\n")
    except OSError:
        pass


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _record_heartbeat(brain: ProjectBrain, interval_seconds: int = 600, active_loop: bool = False) -> None:
    try:
        path = _heartbeat_file(brain)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "pid": os.getpid(),
            "interval_seconds": interval_seconds,
            "active_loop": active_loop,
            "last_heartbeat": now_utc(),
            "timestamp": time.time(),
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def service_status(brain: ProjectBrain) -> dict[str, Any]:
    """Return local service health, supervisor status, heartbeat, and primary-review inbox."""
    sup_status = supervisor_status(brain)
    inbox = sup_status.get("awaiting_primary_review", [])
    kill_active = is_kill_switch_active(brain)

    # Check service heartbeat freshness and PID liveness
    heartbeat_path = _heartbeat_file(brain)
    heartbeat_active = False
    last_hb = None
    if heartbeat_path.is_file():
        try:
            hb_data = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            last_hb = hb_data.get("last_heartbeat")
            ts = float(hb_data.get("timestamp", 0))
            pid = int(hb_data.get("pid", 0))
            interval = int(hb_data.get("interval_seconds", 600))
            active_loop = bool(hb_data.get("active_loop", False))

            # Dynamic TTL and PID liveness check
            ttl_seconds = max(300, int(interval * 2.5))
            if active_loop and _is_pid_alive(pid) and (time.time() - ts <= ttl_seconds):
                heartbeat_active = True
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    health_status = "stopped" if kill_active else ("active" if heartbeat_active else "ready")

    return {
        "service_health": health_status,
        "emergency_stop_active": kill_active,
        "supervisor_lock_active": sup_status.get("active_lock", False),
        "service_heartbeat_active": heartbeat_active,
        "last_heartbeat": last_hb,
        "ticket_counts": sup_status.get("ticket_counts", {}),
        "primary_review_inbox_count": len(inbox),
        "primary_review_inbox": inbox,
        "last_supervisor_run": sup_status.get("last_run", {}),
        "timestamp": now_utc(),
    }


def service_run_once(
    brain: ProjectBrain,
    max_tickets: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one combined service iteration (supervisor run + executor worker)."""
    if is_kill_switch_active(brain):
        _append_service_log(brain, "Service run blocked: Emergency stop active.")
        raise GuardianError("Emergency stop is active; service run blocked.")

    # Read-only Dry Run: DO NOT mutate supervisor state, heartbeats, or journey records!
    if dry_run:
        exec_summary = process_ready_tickets(brain, max_tickets=max_tickets, dry_run=True)
        status = service_status(brain)
        return {
            "dry_run": True,
            "timestamp": now_utc(),
            "supervisor_summary": {"dry_run": True, "tickets_written": 0},
            "executor_summary": exec_summary,
            "inbox_count": status["primary_review_inbox_count"],
            "inbox": status["primary_review_inbox"],
        }

    _append_service_log(brain, "Starting single service iteration.")

    # Record heartbeat for single run
    _record_heartbeat(brain, interval_seconds=600, active_loop=False)

    # 0. Startup reconciliation for dispatched handoffs
    recon = reconcile_dispatched_handoffs(brain)
    if recon.get("reverted_count", 0) > 0:
        _append_service_log(brain, f"Reconciled startup handoffs: reverted={recon['reverted_count']}")

    # 1. Run supervisor cycle
    sup_summary = supervisor_run_once(brain)


    # 2. Consume ready tickets
    exec_summary = process_ready_tickets(brain, max_tickets=max_tickets, dry_run=False)

    # 3. Check status
    status = service_status(brain)

    append_journey(
        brain,
        "Local Service Cycle Completed",
        [
            f"Tickets written: {sup_summary['tickets_written']}",
            f"Executed count: {exec_summary['executed_count']}",
            f"Primary review inbox: {status['primary_review_inbox_count']}",
        ],
    )

    _append_service_log(
        brain,
        f"Service cycle complete: tickets_written={sup_summary['tickets_written']}, "
        f"executed={exec_summary['executed_count']}, inbox={status['primary_review_inbox_count']}"
    )

    return {
        "timestamp": now_utc(),
        "supervisor_summary": sup_summary,
        "executor_summary": exec_summary,
        "inbox_count": status["primary_review_inbox_count"],
        "inbox": status["primary_review_inbox"],
    }


def service_run(
    brain: ProjectBrain,
    interval_seconds: int = 600,
    max_cycles: int | None = None,
    max_tickets: int = 5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run a foreground service loop over multiple cycles (indefinite if max_cycles is None)."""
    if interval_seconds < 1 or interval_seconds > 3600:
        raise GuardianError("interval_seconds must be between 1 and 3600.")
    if max_cycles is not None and (max_cycles < 1 or max_cycles > 10000):
        raise GuardianError("max_cycles must be positive.")

    cycles: list[dict[str, Any]] = []
    cycle_count = 0
    lock_fd = None

    # Skip process lock file creation in dry-run mode for 100% read-only preview
    if not dry_run:
        lock_path = _service_lock_file(brain)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd.write(f"{os.getpid()}\n")
            lock_fd.flush()
        except (OSError, IOError) as err:
            lock_fd.close()
            _append_service_log(brain, "Process lock collision: Another service process is running.")
            raise GuardianError("Another service process is already running for this project.") from err

        _append_service_log(brain, f"Service loop initialized: interval={interval_seconds}s, max_cycles={max_cycles}")

    try:
        while True:
            if is_kill_switch_active(brain):
                _append_service_log(brain, "Emergency stop detected; terminating service loop.")
                break

            if not dry_run:
                _record_heartbeat(brain, interval_seconds=interval_seconds, active_loop=True)

            cycle_res = service_run_once(brain, max_tickets=max_tickets, dry_run=dry_run)
            cycles.append(cycle_res)
            cycle_count += 1

            # Memory Bounding: Keep only last 100 cycle records in memory
            if len(cycles) > _DEFAULT_HISTORY_LIMIT:
                cycles.pop(0)

            if max_cycles is not None and cycle_count >= max_cycles:
                break

            if is_kill_switch_active(brain):
                _append_service_log(brain, "Emergency stop detected; terminating service loop.")
                break

            if not dry_run:
                _record_heartbeat(brain, interval_seconds=interval_seconds, active_loop=True)

            time.sleep(interval_seconds)

        if not dry_run:
            _record_heartbeat(brain, interval_seconds=interval_seconds, active_loop=False)
            _append_service_log(brain, f"Service loop stopped gracefully after {cycle_count} cycles.")

        return {
            "cycles_completed": cycle_count,
            "stopped": is_kill_switch_active(brain),
            "cycles": cycles,
        }
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            lock_fd.close()


def generate_service_config(
    project_path: Path,
    system_kind: str = "systemd",
) -> dict[str, Any]:
    """Generate (without installing) isolated service configuration files."""
    abs_project = project_path.resolve()
    raw_project_str = str(abs_project)
    escaped_project_xml = xml.sax.saxutils.escape(raw_project_str)
    # Systemd specifier escaping: '%' must be escaped as '%%' in unit files
    escaped_project_sysd = raw_project_str.replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")

    label_or_unit, filename = _service_unit_name(abs_project, system_kind=system_kind)

    # Resolve executable binary path accurately
    guardian_bin = shutil.which("guardian")
    if guardian_bin:
        exec_start_sysd = f'{guardian_bin} service run --project "{escaped_project_sysd}" --interval-seconds 600 --indefinite'
        launchd_args = [
            guardian_bin,
            "service",
            "run",
            "--project",
            raw_project_str,
            "--interval-seconds",
            "600",
            "--indefinite",
        ]
    else:
        python_bin = sys.executable
        exec_start_sysd = f'{python_bin} -m guardian_agent.cli service run --project "{escaped_project_sysd}" --interval-seconds 600 --indefinite'
        launchd_args = [
            python_bin,
            "-m",
            "guardian_agent.cli",
            "service",
            "run",
            "--project",
            raw_project_str,
            "--interval-seconds",
            "600",
            "--indefinite",
        ]

    if system_kind == "systemd":
        content = f"""[Unit]
Description=Guardian Agent Local Coordination Service ({label_or_unit})
After=network.target

[Service]
Type=simple
WorkingDirectory="{escaped_project_sysd}"
ExecStart={exec_start_sysd}
Restart=on-failure
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""
    elif system_kind == "launchd":
        launchd_strings = "\n".join(f"        <string>{xml.sax.saxutils.escape(str(arg))}</string>" for arg in launchd_args)
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label_or_unit}</string>
    <key>ProgramArguments</key>
    <array>
{launchd_strings}
    </array>
    <key>WorkingDirectory</key>
    <string>{escaped_project_xml}</string>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
    else:
        raise GuardianError(f"Unsupported service system kind {system_kind!r}. Supported: systemd, launchd")

    return {
        "system_kind": system_kind,
        "unit_name": label_or_unit,
        "filename": filename,
        "content": content,
        "instructions": f"Save content to system service directory (e.g. ~/.config/systemd/user/{filename} for systemd).",
    }



def install_service(project_path: Path, system_kind: str = "systemd") -> dict[str, Any]:
    """Install and enable the service daemon unit file into the user's system directory."""
    cfg = generate_service_config(project_path, system_kind=system_kind)
    content = cfg["content"]
    filename = cfg["filename"]
    unit_name = cfg["unit_name"]
    warnings: list[str] = []

    if system_kind == "systemd":
        target_dir = Path.home() / ".config" / "systemd" / "user"
        target_dir.mkdir(parents=True, exist_ok=True)
        unit_file = target_dir / filename
        unit_file.write_text(content, encoding="utf-8")

        # Reload systemd user daemon
        try:
            r1 = subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
            if r1.returncode != 0:
                warnings.append(f"systemctl daemon-reload returned code {r1.returncode}: {r1.stderr.strip()}")
            r2 = subprocess.run(["systemctl", "--user", "enable", filename], capture_output=True, text=True)
            if r2.returncode != 0:
                warnings.append(f"systemctl enable returned code {r2.returncode}: {r2.stderr.strip()}")
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            warnings.append(f"Systemctl execution warning: {err}")

        return {
            "installed": True,
            "system_kind": "systemd",
            "unit_name": unit_name,
            "unit_file": str(unit_file),
            "warnings": warnings,
            "status": f"Systemd user service {unit_name} installed at {unit_file}.",
        }

    elif system_kind == "launchd":
        target_dir = Path.home() / "Library" / "LaunchAgents"
        target_dir.mkdir(parents=True, exist_ok=True)
        plist_file = target_dir / filename
        plist_file.write_text(content, encoding="utf-8")

        return {
            "installed": True,
            "system_kind": "launchd",
            "unit_name": unit_name,
            "unit_file": str(plist_file),
            "warnings": warnings,
            "status": f"Launchd agent plist {unit_name} installed at {plist_file}.",
        }

    else:
        raise GuardianError(f"Unsupported system kind {system_kind!r}.")


def start_service(project_path: Path, system_kind: str = "systemd") -> dict[str, Any]:
    """Start the installed background service."""
    _, filename = _service_unit_name(project_path, system_kind=system_kind)
    if system_kind == "systemd":
        try:
            res = subprocess.run(
                ["systemctl", "--user", "start", filename],
                check=True,
                capture_output=True,
                text=True,
            )
            return {"started": True, "system_kind": "systemd", "output": res.stdout.strip()}
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            raise GuardianError(f"Failed to start systemd service {filename}: {err}") from err

    elif system_kind == "launchd":
        plist_file = Path.home() / "Library" / "LaunchAgents" / filename
        if not plist_file.is_file():
            install_service(project_path, "launchd")
        try:
            res = subprocess.run(
                ["launchctl", "load", str(plist_file)],
                check=True,
                capture_output=True,
                text=True,
            )
            return {"started": True, "system_kind": "launchd", "output": res.stdout.strip()}
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            raise GuardianError(f"Failed to start launchd service {filename}: {err}") from err
    else:
        raise GuardianError(f"Unsupported system kind {system_kind!r}.")


def stop_service(project_path: Path, system_kind: str = "systemd") -> dict[str, Any]:
    """Stop the running background service."""
    _, filename = _service_unit_name(project_path, system_kind=system_kind)
    if system_kind == "systemd":
        try:
            res = subprocess.run(
                ["systemctl", "--user", "stop", filename],
                check=True,
                capture_output=True,
                text=True,
            )
            return {"stopped": True, "system_kind": "systemd", "output": res.stdout.strip()}
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            raise GuardianError(f"Failed to stop systemd service {filename}: {err}") from err

    elif system_kind == "launchd":
        plist_file = Path.home() / "Library" / "LaunchAgents" / filename
        try:
            res = subprocess.run(
                ["launchctl", "unload", str(plist_file)],
                check=True,
                capture_output=True,
                text=True,
            )
            return {"stopped": True, "system_kind": "launchd", "output": res.stdout.strip()}
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            raise GuardianError(f"Failed to stop launchd service {filename}: {err}") from err
    else:
        raise GuardianError(f"Unsupported system kind {system_kind!r}.")


def uninstall_service(project_path: Path, system_kind: str = "systemd") -> dict[str, Any]:
    """Disable, stop, and uninstall the service unit file."""
    _, filename = _service_unit_name(project_path, system_kind=system_kind)
    errors: list[str] = []

    if system_kind == "systemd":
        try:
            r_dis = subprocess.run(["systemctl", "--user", "disable", filename], capture_output=True, text=True)
            if r_dis.returncode != 0 and "No such file" not in r_dis.stderr and "not loaded" not in r_dis.stderr:
                errors.append(f"systemctl disable failed ({r_dis.returncode}): {r_dis.stderr.strip()}")
            r_stp = subprocess.run(["systemctl", "--user", "stop", filename], capture_output=True, text=True)
            if r_stp.returncode != 0 and "not loaded" not in r_stp.stderr and "No such file" not in r_stp.stderr:
                errors.append(f"systemctl stop failed ({r_stp.returncode}): {r_stp.stderr.strip()}")
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            errors.append(str(err))

        unit_file = Path.home() / ".config" / "systemd" / "user" / filename
        if unit_file.exists():
            try:
                unit_file.unlink()
            except OSError as err:
                errors.append(f"Failed to remove unit file {unit_file}: {err}")

        try:
            r_dr = subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
            if r_dr.returncode != 0:
                errors.append(f"systemctl daemon-reload failed ({r_dr.returncode}): {r_dr.stderr.strip()}")
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            errors.append(str(err))

        uninstalled = len(errors) == 0
        return {"uninstalled": uninstalled, "system_kind": "systemd", "errors": errors}

    elif system_kind == "launchd":
        plist_file = Path.home() / "Library" / "LaunchAgents" / filename
        try:
            r_unl = subprocess.run(["launchctl", "unload", str(plist_file)], capture_output=True, text=True)
            if r_unl.returncode != 0 and "No such file" not in r_unl.stderr:
                errors.append(f"launchctl unload failed ({r_unl.returncode}): {r_unl.stderr.strip()}")
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            errors.append(str(err))

        if plist_file.exists():
            try:
                plist_file.unlink()
            except OSError as err:
                errors.append(f"Failed to remove plist file {plist_file}: {err}")

        uninstalled = len(errors) == 0
        return {"uninstalled": uninstalled, "system_kind": "launchd", "errors": errors}
    else:
        raise GuardianError(f"Unsupported system kind {system_kind!r}.")



def get_brain_schema_version(brain: ProjectBrain) -> int:
    """Return current brain schema version integer (defaulting to 1)."""
    vf = _schema_version_file(brain)
    if not vf.is_file():
        return 1
    try:
        data = json.loads(vf.read_text(encoding="utf-8"))
        return int(data.get("version", 1))
    except (json.JSONDecodeError, OSError, ValueError):
        return 1


def migrate_brain(brain: ProjectBrain, target_version: int = _CURRENT_BRAIN_SCHEMA_VERSION) -> dict[str, Any]:
    """Migrate brain schema to target version with automatic pre-upgrade snapshot and rollback."""
    current_ver = get_brain_schema_version(brain)
    if current_ver == target_version:
        return {
            "migrated": False,
            "version": current_ver,
            "status": f"Brain is already at version {current_ver}.",
        }

    if target_version > _CURRENT_BRAIN_SCHEMA_VERSION:
        raise GuardianError(
            f"Target version {target_version} exceeds current maximum supported schema version ({_CURRENT_BRAIN_SCHEMA_VERSION})."
        )

    if target_version < current_ver:
        raise GuardianError(f"Downgrade from version {current_ver} to {target_version} is not supported.")

    # Create pre-upgrade snapshot backup FIRST
    backup_info = backup_brain(brain, overwrite=False)
    backup_path = Path(backup_info["backup_path"])

    try:
        applied_versions: list[int] = []
        for ver in range(current_ver + 1, target_version + 1):
            _apply_schema_migration(brain, ver)
            applied_versions.append(ver)

        # Update schema_version.json
        vf = _schema_version_file(brain)
        vf.parent.mkdir(parents=True, exist_ok=True)
        vf.write_text(json.dumps({"version": target_version, "updated_at": now_utc()}, indent=2) + "\n", encoding="utf-8")

        append_journey(
            brain,
            f"Brain Schema Migrated to v{target_version}",
            [f"Previous version: {current_ver}", f"Pre-upgrade backup: {backup_path}"],
        )

        return {
            "migrated": True,
            "previous_version": current_ver,
            "current_version": target_version,
            "applied_versions": applied_versions,
            "backup_path": str(backup_path),
        }
    except Exception as err:
        # Automatic rollback on migration failure
        restore_brain(brain.root, backup_path)
        raise GuardianError(f"Brain migration failed: {err}. Rolled back to pre-upgrade state.") from err


def backup_brain(
    brain: ProjectBrain,
    destination: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Archive the project's .agent directory into a tar.gz backup file."""
    agent_dir = brain.directory.resolve()
    if not agent_dir.is_dir():
        raise GuardianError("No .agent brain directory found to backup.")

    # High-precision timestamp with UUID to avoid collision
    unique_suffix = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
    target_file = (destination.resolve() if destination else (brain.root / f"brain_backup_{unique_suffix}.tar.gz")).resolve()

    # Reject destination inside .agent directory to avoid archive recursion
    if target_file == agent_dir or agent_dir in target_file.parents:
        raise GuardianError("Backup destination cannot be inside the .agent directory.")

    # Overwrite protection
    if target_file.exists() and not overwrite:
        raise GuardianError(f"Backup file {target_file!r} already exists; overwrite refused.")

    target_file.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(target_file, "w:gz") as tar:
        tar.add(agent_dir, arcname=".agent")

    append_journey(brain, "Project Brain Backed Up", [f"Archive: {target_file}"])

    return {
        "backup_path": str(target_file),
        "size_bytes": target_file.stat().st_size,
        "created_at": now_utc(),
    }


def restore_brain(target_root: Path, archive_path: Path) -> dict[str, Any]:
    """Restore .agent brain directory from a tar.gz backup file with strict member validation and transactional rollback."""
    if not archive_path.is_file():
        raise GuardianError(f"Backup archive {archive_path!r} not found.")

    if not tarfile.is_tarfile(archive_path):
        raise GuardianError(f"File {archive_path!r} is not a valid tar archive.")

    # Pre-validate tarfile structure and member security
    try:
        with tarfile.open(archive_path, "r:gz") as test_tar:
            members = test_tar.getmembers()
            if not members:
                raise GuardianError("Archive is empty.")

            for m in members:
                # Security Check 1: Explicitly reject absolute paths
                if m.name.startswith("/") or m.name.startswith("\\"):
                    raise GuardianError(f"Archive contains prohibited absolute path member: {m.name!r}")

                # Security Check 2: No path traversal (..)
                clean_name = m.name.lstrip("/")
                parts = clean_name.split("/")
                if ".." in parts:
                    raise GuardianError(f"Archive contains path traversal member: {m.name!r}")

                # Security Check 3: Must reside strictly inside .agent tree
                if not (clean_name == ".agent" or clean_name.startswith(".agent/")):
                    raise GuardianError(
                        f"Archive contains member outside .agent tree: {m.name!r}"
                    )

                # Security Check 4: Reject symlinks, hardlinks, devices, FIFOs
                if m.issym() or m.islnk() or m.isdev() or m.isfifo() or m.ischr() or m.isblk():
                    raise GuardianError(
                        f"Archive contains prohibited link or special device member: {m.name!r}"
                    )
    except GuardianError:
        raise
    except Exception as err:
        raise GuardianError(f"Corrupted backup archive {archive_path!r}: {err}") from err

    target_agent = target_root / ".agent"
    tmp_extract_dir = target_root / f".agent_extract_tmp_{uuid.uuid4().hex[:8]}"
    old_backup = None

    try:
        # Step 1: Extract into temporary sibling directory FIRST
        tmp_extract_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(path=tmp_extract_dir, filter="data")

        # Step 2: Post-extraction validation — verify required brain file
        extracted_agent = tmp_extract_dir / ".agent"
        if not (extracted_agent / "PROJECT.md").is_file():
            raise GuardianError("Restored brain archive is missing required file .agent/PROJECT.md.")

        # Step 3: Transactional atomic swap with complete rollback guarantee
        if target_agent.exists():
            unique_old = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}"
            old_backup = target_root / f".agent_old_{unique_old}"
            shutil.move(str(target_agent), str(old_backup))

        try:
            shutil.move(str(extracted_agent), str(target_agent))
        except Exception as move_err:
            if old_backup and old_backup.exists() and not target_agent.exists():
                shutil.move(str(old_backup), str(target_agent))
            raise move_err

        if old_backup and old_backup.exists():
            shutil.rmtree(str(old_backup), ignore_errors=True)

    except Exception as extract_err:
        # Cleanup temporary extract directory and restore old_backup on failure
        if tmp_extract_dir.exists():
            shutil.rmtree(str(tmp_extract_dir), ignore_errors=True)
        if old_backup and old_backup.exists() and not target_agent.exists():
            shutil.move(str(old_backup), str(target_agent))
        raise GuardianError(f"Archive extraction failed: {extract_err}. Previous brain remains untouched.") from extract_err
    finally:
        if tmp_extract_dir.exists():
            shutil.rmtree(str(tmp_extract_dir), ignore_errors=True)

    return {
        "target_root": str(target_root),
        "restored_from": str(archive_path),
        "restored_at": now_utc(),
    }
