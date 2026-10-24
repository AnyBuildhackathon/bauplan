"""Exercise transport and artifact integrity without an NVIDIA GPU or credentials."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pai_agent.bus import EventBus
from pai_agent.context import Ctx
from pai_agent.state import BuildState
from pai_agent.tools import isaac


class FakeSSH:
    def __init__(self, mode="test", failure=None):
        self.mode, self.failure, self.calls = mode, failure, []

    async def run(self, command, timeout, script=None):
        self.calls.append((command, timeout, script))
        if self.failure == "upload" and command[0] == "scp":
            raise RuntimeError("scp failed (exit 1).")
        if script and "timeout --signal" in script and self.failure == "timeout":
            raise TimeoutError()
        if command[0] == "scp" and command[-1].endswith("/") and ":" not in command[-1]:
            directory = Path(command[-1])
            metrics = {"final_reward": 3, "iterations": 10, "parallel_envs": 64} if self.mode == "train" else {"hover_rmse_m": 0.02, "max_tilt_deg": 4, "max_drift_m": 0.02}
            payload = {"mode": self.mode, "source": "live", "status": "done", "metrics": metrics, "passed": True,
                       "curve": [[0, -2], [10, 3]] if self.mode == "train" else [], "detail": "Fake GPU result."}
            (directory / "result.json").write_text(json.dumps(payload))
            (directory / "result.mp4").write_bytes(b'\x00\x00\x00\x20ftypisom' + b'\x00' * 32 if self.failure != "video" else b'broken')


def fake_export(state, directory):
    for name in ("product.usda", "assembly.usdc", "assembly.json"):
        (directory / name).write_text("fake fixture")
    return {"mass_kg": 0.04, "parts": [{"mass_kg": 0.04}], "max_thrust_n": 1.6}


class IsaacTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.ctx = Ctx(EventBus(), BuildState("fakejob", self.directory), auto_steps=False)
        self.environment = patch.dict(os.environ, {"RUNPOD_SSH_HOST": "fake-pod.example", "RUNPOD_SSH_PORT": "2222",
                                                   "RUNPOD_SSH_USER": "root", "ISAAC_TIMEOUT_S": "30"}, clear=True)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    async def execute(self, mode="test", failure=None):
        runner = FakeSSH(mode, failure)
        with patch.object(isaac, "_command", runner.run), patch.object(isaac, "export_product", fake_export):
            result = await (isaac.isaac_train if mode == "train" else isaac.isaac_test)(self.ctx, {})
        return result, runner

    async def test_no_pod_is_recorded_with_fixed_conditions(self):
        os.environ.pop("RUNPOD_SSH_HOST")
        result = await isaac.isaac_test(self.ctx, {"scenario": "payload", "payload_g": 50})
        self.assertEqual(result["source"], "recorded")
        self.assertEqual(result["requested"]["payload_g"], 50)
        self.assertEqual(result["parameters"]["payload_g"], 10)
        self.assertFalse(result["product_tested"])
        self.assertIn("Waiting for pod", result["detail"])
        self.assertEqual(result["metrics"]["assembly_mass_g"], 36.7)
        self.assertAlmostEqual(result["metrics"]["total_mass_g"], result["metrics"]["assembly_mass_g"] + result["parameters"]["payload_g"])

    async def test_gripper_never_uploads_or_replays_drone_results(self):
        self.ctx.state.product = "gripper"
        with patch.object(isaac, "_command") as runner:
            for configured in (True, False):
                if not configured:
                    os.environ.pop("RUNPOD_SSH_HOST")
                for tool in (isaac.isaac_test, isaac.isaac_train):
                    result = await tool(self.ctx, {})
                    self.assertFalse(result["ok"])
                    self.assertIn("simulate_grip", result["detail"])
                    self.assertNotIn("video_url", result)
            runner.assert_not_called()
        self.assertIsNone(self.ctx.state.omniverse_result)

    async def test_product_switch_clears_drone_result(self):
        from pai_agent.tools.gripper import product_brief

        self.ctx.state.omniverse_result = {"source": "recorded"}
        self.ctx.state.training_video = "old-drone.mp4"
        result = await product_brief(self.ctx, {"product": "gripper"})
        self.assertTrue(result["ok"])
        self.assertIsNone(self.ctx.state.omniverse_result)
        self.assertIsNone(self.ctx.state.training_video)

    async def test_generic_cad_part_cannot_use_drone_controller(self):
        self.ctx.state.stl_path = "agent/runs/sessions/fakejob/part-bracket.stl"
        with patch.object(isaac, "_command") as runner:
            result = await isaac.isaac_test(self.ctx, {})
            self.assertFalse(result["ok"])
            runner.assert_not_called()

    async def test_upload_execution_and_download(self):
        result, runner = await self.execute()
        self.assertEqual(result["source"], "live")
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(runner.calls), 4)
        upload = runner.calls[1][0]
        self.assertTrue(any(p.endswith("product.usda") for p in upload))
        self.assertTrue(any(p.endswith("assembly.usdc") for p in upload))
        self.assertTrue(any(p.endswith("assembly.json") for p in upload))
        self.assertTrue(any(p.endswith("id_ed25519") for p in upload))
        self.assertIn("timeout --signal=TERM --kill-after=15s 30s", runner.calls[2][2])
        self.assertIn("/tmp/anybuild-", runner.calls[2][2])
        self.assertEqual(len(list(self.directory.glob("*.mp4"))), 1)
        self.assertEqual(len(list(self.directory.glob("*.json"))), 1)
        stages = [event["stage"] for event in self.ctx.bus.events if event.get("status") == "running"]
        self.assertEqual(stages, ["export", "upload", "execute", "download"])

    async def test_provider_neutral_configuration_takes_precedence(self):
        with patch.dict(os.environ, {"ISAAC_SSH_HOST": "brev.example", "ISAAC_SSH_PORT": "2200", "ISAAC_SSH_USER": "ubuntu"}):
            ssh, scp, target = isaac._connection()
            self.assertEqual(target, "ubuntu@brev.example")
            self.assertIn("2200", ssh)
            self.assertIn("2200", scp)

    async def test_training_has_curve_and_video(self):
        result, _ = await self.execute("train")
        self.assertEqual(result["curve"], [[0, -2], [10, 3]])
        self.assertTrue(result["video_url"].endswith(".mp4"))

    async def test_transport_timeout_and_corrupt_video_fall_back(self):
        for failure in ("upload", "timeout", "video"):
            with self.subTest(failure=failure):
                result, _ = await self.execute(failure=failure)
                self.assertEqual(result["source"], "recorded")
                self.assertIn("no new GPU measurement", result["detail"])

    async def test_invalid_arguments_do_not_start_ssh(self):
        with patch.object(isaac, "_command") as runner:
            for args in ({"wind_m_s": float("nan")}, {"payload_g": -10}, {"scenario": "unknown"}):
                result = await isaac.isaac_test(self.ctx, args)
                self.assertFalse(result["ok"])
            runner.assert_not_called()

    async def test_shell_injection_is_rejected(self):
        for field in ("RUNPOD_SSH_HOST", "RUNPOD_SSH_USER", "RUNPOD_SSH_PORT"):
            with patch.dict(os.environ, {field: "x;touch /tmp/unsafe"}):
                with self.assertRaises(ValueError):
                    isaac._connection()

    async def test_actual_process_timeout_is_bounded(self):
        with self.assertRaises(TimeoutError):
            await isaac._command(["/bin/sleep", "10"], 0.02)


if __name__ == "__main__":
    unittest.main()
