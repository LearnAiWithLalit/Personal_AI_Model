"""Allowlisted MCP stdio client with schema pinning and approval gates."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path

from guardian_agent.core import GuardianError, ProjectBrain, append_journey, markdown_escape, now_utc
from guardian_agent.operator import audit_log_action
from guardian_agent.policy import consume_action_approval


MCP_FILE = "mcp-servers.json"
PROTOCOL_VERSION = "2025-06-18"


def mcp_path(brain: ProjectBrain) -> Path:
    return brain.directory / MCP_FILE


def _default_registry() -> dict:
    return {"version": 1, "servers": []}


def load_mcp_registry(brain: ProjectBrain) -> dict:
    path = mcp_path(brain)
    if not path.exists():
        save_mcp_registry(brain, _default_registry())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GuardianError("MCP registry contains invalid JSON.") from error
    if payload.get("version") != 1 or not isinstance(payload.get("servers"), list):
        raise GuardianError("MCP registry has an unsupported format.")
    return payload


def save_mcp_registry(brain: ProjectBrain, payload: dict) -> None:
    mcp_path(brain).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _clean_server_id(server_id: str) -> str:
    clean = markdown_escape(server_id).lower()
    if not clean or not all(char.isalnum() or char in "-_" for char in clean):
        raise GuardianError("MCP server IDs may contain only letters, numbers, hyphens, and underscores.")
    return clean


def _server(brain: ProjectBrain, server_id: str) -> dict:
    clean = _clean_server_id(server_id)
    server = next((item for item in load_mcp_registry(brain)["servers"] if item.get("id") == clean), None)
    if not server:
        raise GuardianError(f"MCP server {clean!r} is not registered.")
    return server


def register_mcp_server(brain: ProjectBrain, server_id: str, command: str, arguments: list[str]) -> dict:
    clean = _clean_server_id(server_id)
    executable = markdown_escape(command)
    if not executable:
        raise GuardianError("An MCP server command is required.")
    payload = load_mcp_registry(brain)
    existing = next((item for item in payload["servers"] if item.get("id") == clean), None)
    record = {
        "id": clean,
        "transport": "stdio",
        "command": executable,
        "arguments": [str(item) for item in arguments],
        "trusted": False,
        "allowed_tools": {},
        "discovered_tools": {},
        "updated_at": now_utc(),
    }
    if existing:
        payload["servers"][payload["servers"].index(existing)] = record
    else:
        payload["servers"].append(record)
    save_mcp_registry(brain, payload)
    append_journey(
        brain,
        "MCP Server Registered",
        [f"Server: {clean}", "Status: untrusted", "Tool execution remains blocked until explicit trust and allowlisting."],
    )
    return record


def list_mcp_servers(brain: ProjectBrain) -> list[dict]:
    return load_mcp_registry(brain)["servers"]


def trust_mcp_server(brain: ProjectBrain, server_id: str, approval_id: str) -> dict:
    clean = _clean_server_id(server_id)
    payload = load_mcp_registry(brain)
    server = next((item for item in payload["servers"] if item.get("id") == clean), None)
    if not server:
        raise GuardianError(f"MCP server {clean!r} is not registered.")
    consume_action_approval(brain, approval_id, "mcp_trust_server", clean)
    server["trusted"] = True
    server["trusted_at"] = now_utc()
    save_mcp_registry(brain, payload)
    audit_log_action(brain, "mcp_trust_server", clean, "success", "Server command approved; tools remain separately allowlisted.")
    return server


def _schema_hash(tool: dict) -> str:
    material = {
        "name": tool.get("name"),
        "description": tool.get("description"),
        "inputSchema": tool.get("inputSchema", {}),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class StdioMcpSession:
    """Minimal MCP lifecycle client for one local stdio server process."""

    def __init__(self, brain: ProjectBrain, server: dict, timeout: float = 20.0):
        self.brain = brain
        self.server = server
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.request_id = 0

    def __enter__(self) -> "StdioMcpSession":
        executable = shutil.which(self.server["command"])
        if not executable:
            candidate = Path(self.server["command"])
            if candidate.is_absolute() and candidate.is_file():
                executable = str(candidate)
        if not executable:
            raise GuardianError(f"MCP executable {self.server['command']!r} was not found.")
        safe_env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"}
        }
        try:
            self.process = subprocess.Popen(
                [executable, *self.server.get("arguments", [])],
                cwd=str(self.brain.root),
                env=safe_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            initialized = self.request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "guardian-agent", "version": "0.1.0"},
                },
            )
            negotiated = initialized.get("protocolVersion")
            if negotiated != PROTOCOL_VERSION:
                raise GuardianError(
                    f"MCP server negotiated unsupported protocol version {negotiated!r}; expected {PROTOCOL_VERSION!r}."
                )
            self.notify("notifications/initialized")
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        if not self.process:
            return
        process = self.process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
        self.process = None

    def _write(self, payload: dict) -> None:
        if not self.process or not self.process.stdin:
            raise GuardianError("MCP server process is not running.")
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def _response(self, request_id: int) -> dict:
        if not self.process or not self.process.stdout:
            raise GuardianError("MCP server process is not running.")
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise GuardianError(f"MCP server exited unexpectedly with code {self.process.returncode}.")
                ready = selector.select(timeout=max(0.0, deadline - time.monotonic()))
                if not ready:
                    break
                line = self.process.stdout.readline()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    raise GuardianError("MCP server emitted invalid JSON on stdout.") from error
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    error = message["error"]
                    raise GuardianError(f"MCP error {error.get('code')}: {error.get('message')}")
                if "result" not in message:
                    raise GuardianError("MCP response is missing both result and error.")
                return message["result"]
        finally:
            selector.close()
        raise GuardianError(f"MCP request timed out after {self.timeout:g} seconds.")

    def request(self, method: str, params: dict | None = None) -> dict:
        self.request_id += 1
        payload = {"jsonrpc": "2.0", "id": self.request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)
        return self._response(self.request_id)

    def notify(self, method: str, params: dict | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)


def _discover(server: dict, brain: ProjectBrain) -> list[dict]:
    with StdioMcpSession(brain, server) as session:
        result = session.request("tools/list")
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise GuardianError("MCP tools/list response does not contain a tools array.")
    return tools


def discover_mcp_tools(brain: ProjectBrain, server_id: str) -> dict:
    server = _server(brain, server_id)
    if not server.get("trusted"):
        raise GuardianError("MCP server is not trusted. Approve and trust it before starting its command.")
    tools = _discover(server, brain)
    payload = load_mcp_registry(brain)
    stored = next(item for item in payload["servers"] if item["id"] == server["id"])
    stored["discovered_tools"] = {
        tool["name"]: {
            "description": tool.get("description", ""),
            "input_schema": tool.get("inputSchema", {}),
            "schema_sha256": _schema_hash(tool),
        }
        for tool in tools
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    stored["last_discovered_at"] = now_utc()
    save_mcp_registry(brain, payload)
    audit_log_action(brain, "mcp_discover_tools", server["id"], "success", f"Discovered {len(stored['discovered_tools'])} tools.")
    return {"server": server["id"], "tools": stored["discovered_tools"]}


def allow_mcp_tool(brain: ProjectBrain, server_id: str, tool_name: str, mode: str) -> dict:
    if mode not in {"read", "write"}:
        raise GuardianError("MCP tool mode must be read or write.")
    clean_tool = markdown_escape(tool_name)
    payload = load_mcp_registry(brain)
    server = next((item for item in payload["servers"] if item.get("id") == _clean_server_id(server_id)), None)
    if not server or not server.get("trusted"):
        raise GuardianError("MCP server must be registered and trusted before allowing tools.")
    discovered = server.get("discovered_tools", {}).get(clean_tool)
    if not discovered:
        raise GuardianError("Discover the server and select an exact discovered tool name before allowlisting it.")
    server.setdefault("allowed_tools", {})[clean_tool] = {
        "mode": mode,
        "schema_sha256": discovered["schema_sha256"],
        "allowed_at": now_utc(),
    }
    save_mcp_registry(brain, payload)
    audit_log_action(brain, "mcp_allow_tool", f"{server['id']}:{clean_tool}", "success", f"Mode: {mode}")
    return {"server": server["id"], "tool": clean_tool, **server["allowed_tools"][clean_tool]}


def call_mcp_tool(
    brain: ProjectBrain,
    server_id: str,
    tool_name: str,
    arguments: dict,
    approval_id: str | None = None,
) -> dict:
    server = _server(brain, server_id)
    if not server.get("trusted"):
        raise GuardianError("MCP server is not trusted.")
    clean_tool = markdown_escape(tool_name)
    permission = server.get("allowed_tools", {}).get(clean_tool)
    if not permission:
        raise GuardianError("MCP tool is not allowlisted.")
    tools = _discover(server, brain)
    live_tool = next((tool for tool in tools if tool.get("name") == clean_tool), None)
    if not live_tool:
        raise GuardianError("Allowlisted MCP tool is no longer advertised by the server.")
    if _schema_hash(live_tool) != permission.get("schema_sha256"):
        raise GuardianError("MCP tool schema changed after allowlisting; rediscover and approve the new schema.")
    target = f"{server['id']}:{clean_tool}"
    if permission.get("mode") == "write":
        if not approval_id:
            raise GuardianError(f"Write-capable MCP tool requires an approved mcp_write_tool request for {target}.")
        consume_action_approval(brain, approval_id, "mcp_write_tool", target)
    try:
        with StdioMcpSession(brain, server) as session:
            result = session.request("tools/call", {"name": clean_tool, "arguments": arguments})
        if result.get("isError"):
            raise GuardianError("MCP server reported a tool execution error.")
        audit_log_action(brain, "mcp_call_tool", target, "success", f"Mode: {permission['mode']}")
        return {"server": server["id"], "tool": clean_tool, "mode": permission["mode"], "result": result}
    except GuardianError as error:
        audit_log_action(brain, "mcp_call_tool", target, "failed", str(error))
        raise
