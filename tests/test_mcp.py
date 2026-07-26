import sys
import tempfile
import unittest
from pathlib import Path

from guardian_agent.core import GuardianError, initialize
from guardian_agent.mcp import (
    allow_mcp_tool,
    call_mcp_tool,
    discover_mcp_tools,
    list_mcp_servers,
    register_mcp_server,
    trust_mcp_server,
)
from guardian_agent.policy import approve_action_request, request_action_approval


class McpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.brain = initialize(Path(self.tempdir.name) / "demo", "MCP Demo", "MCP integration test")
        fake_server = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
        register_mcp_server(self.brain, "test", sys.executable, [str(fake_server)])

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _trust(self) -> None:
        request = request_action_approval(
            self.brain, "mcp_trust_server", "test", "Trust the test fixture command."
        )
        approve_action_request(self.brain, request["id"])
        trust_mcp_server(self.brain, "test", request["id"])

    def test_registration_starts_untrusted(self) -> None:
        server = list_mcp_servers(self.brain)[0]
        self.assertFalse(server["trusted"])
        with self.assertRaises(GuardianError):
            discover_mcp_tools(self.brain, "test")

    def test_discover_allow_and_call_read_tool(self) -> None:
        self._trust()
        discovered = discover_mcp_tools(self.brain, "test")
        self.assertIn("echo", discovered["tools"])
        allow_mcp_tool(self.brain, "test", "echo", "read")
        result = call_mcp_tool(self.brain, "test", "echo", {"text": "hello"})
        self.assertEqual(result["mode"], "read")
        self.assertIn("hello", result["result"]["content"][0]["text"])

    def test_write_tool_requires_one_time_matching_approval(self) -> None:
        self._trust()
        discover_mcp_tools(self.brain, "test")
        allow_mcp_tool(self.brain, "test", "mutate", "write")
        with self.assertRaises(GuardianError):
            call_mcp_tool(self.brain, "test", "mutate", {"value": "x"})
        request = request_action_approval(
            self.brain, "mcp_write_tool", "test:mutate", "Run one approved write operation."
        )
        approve_action_request(self.brain, request["id"])
        result = call_mcp_tool(
            self.brain, "test", "mutate", {"value": "x"}, approval_id=request["id"]
        )
        self.assertEqual(result["mode"], "write")
        with self.assertRaises(GuardianError):
            call_mcp_tool(
                self.brain, "test", "mutate", {"value": "again"}, approval_id=request["id"]
            )


if __name__ == "__main__":
    unittest.main()
