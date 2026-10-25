"""Partner provenance and the read-only, bounded NVIDIA connection probe."""

import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from pai_agent import status
from pai_agent.app import app


class PartnerStatusTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.cad = patch.object(status, "find_freecadcmd", return_value=None)
        self.blender = patch.object(status, "find_blender", return_value=None)
        self.rpc = patch.object(status, "rpc_available", return_value=False)
        for mock in (self.cad, self.blender, self.rpc):
            mock.start()
            self.addCleanup(mock.stop)
        self.addCleanup(self.env.stop)

    def rows(self, events=None):
        return {row["id"]: row for row in status.partner_statuses(events or [])}

    def test_independent_fallbacks_without_credentials(self):
        rows = self.rows()
        self.assertEqual({key: row["state"] for key, row in rows.items()}, {
            "claude": "mock", "reson8": "offline",
            "gemini": "offline", "freecad": "offline", "blender": "offline",
        })

    def test_configured_apis_and_forced_mock_never_expose_secrets(self):
        keys = {name: "secret-status-test" for name in ("ANTHROPIC_API_KEY", "RESON8_API_KEY", "GEMINI_API_KEY")}
        with patch.dict(os.environ, keys):
            rows = self.rows()
            self.assertTrue(all(rows[key]["state"] == "live" for key in ("claude", "reson8", "gemini")))
            self.assertNotIn("secret-status-test", json.dumps(rows))
            self.assertIn("authentication and quota", rows["claude"]["detail"])
            with patch.dict(os.environ, {"PAI_FORCE_MOCK": "1"}):
                self.assertEqual(self.rows()["claude"]["state"], "mock")
                self.assertEqual(self.rows()["reson8"]["state"], "live")

    def test_runtime_fallback_overrides_installed_freecad_and_recovers(self):
        with patch.object(status, "find_freecadcmd", return_value="/bin/freecadcmd"):
            events = [{"type": "cad", "source": "cadquery"}, {"type": "tool", "name": "cad_frame", "status": "ok", "ms": 12}]
            self.assertEqual(self.rows(events)["freecad"]["state"], "offline")
            events.append({"type": "cad", "source": "freecad"})
            self.assertEqual(self.rows(events)["freecad"]["state"], "live")
            events.append({"type": "tool", "name": "cad_part", "status": "error", "ms": 2})
            self.assertEqual(self.rows(events)["freecad"]["state"], "offline")

    def test_status_http_contract_keeps_last_run_and_access_gate(self):
        session = SimpleNamespace(bus=SimpleNamespace(events=[]), state=SimpleNamespace(omniverse_result={
            "mode": "test", "status": "running", "source": "live", "stage": "execute", "detail": "Running physics.",
        }))
        connection = {"host": "gpu.example", "gpu": "NVIDIA A40", "state": "live", "detail": "SSH connected."}
        with patch.object(app.state, "session", session, create=True), patch.object(status, "isaac_connection", AsyncMock(return_value=connection)):
            client = TestClient(app)
            response = client.get("/api/status")
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(len(body["partners"]), 6)
            self.assertEqual(body["isaac"]["last_run"]["stage"], "execute")
            self.assertEqual(body["isaac"]["gpu"], "NVIDIA A40")
            with patch.dict(os.environ, {"ANYBUILD_ACCESS_CODE": "test-code"}):
                self.assertEqual(client.get("/api/status").status_code, 401)


class IsaacStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        status._gpu_cache = None
        status._gpu_lock = asyncio.Lock()
        env = patch.dict(os.environ, {"ISAAC_SSH_HOST": "gpu.example"}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    async def test_missing_host_never_starts_ssh(self):
        with patch.dict(os.environ, {"ISAAC_SSH_HOST": ""}), patch.object(asyncio, "create_subprocess_exec", AsyncMock()) as spawn:
            self.assertEqual((await status.isaac_connection())["state"], "offline")
            spawn.assert_not_called()

    async def test_success_reports_gpu_and_caches_without_writing_known_hosts(self):
        process = SimpleNamespace(returncode=0, communicate=AsyncMock(return_value=(b"NVIDIA A40\n", b"")))
        with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)) as spawn:
            first = await status.isaac_connection()
            second = await status.isaac_connection()
            self.assertEqual(first, second)
            self.assertEqual(first["state"], "live")
            self.assertEqual(first["gpu"], "NVIDIA A40")
            spawn.assert_awaited_once()
            self.assertIn("StrictHostKeyChecking=accept-new", spawn.call_args.args)
            self.assertIn("UserKnownHostsFile=/dev/null", spawn.call_args.args)
            self.assertEqual(spawn.call_args.args[-1], "nvidia-smi --query-gpu=name --format=csv,noheader")

    async def test_ssh_failure_is_offline(self):
        process = SimpleNamespace(returncode=255, communicate=AsyncMock(return_value=(b"", b"")))
        with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
            self.assertEqual((await status.isaac_connection())["state"], "offline")

    async def test_timeout_reaps_only_its_probe(self):
        process = SimpleNamespace(returncode=None, communicate=AsyncMock(side_effect=TimeoutError), kill=Mock(), wait=AsyncMock())
        with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)):
            self.assertEqual((await status.isaac_connection())["state"], "offline")
            process.kill.assert_called_once()
            process.wait.assert_awaited_once()
