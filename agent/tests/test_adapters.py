"""Check adapters: lookups that never start a tool, a locked PATH, versions read from files, the
bounded Isaac probe, the run log fed by the live event stream, and GET /api/adapters."""

import asyncio
import json
import os
import plistlib
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from pai_agent import adapters, freecad_run, sparkbench, status
from pai_agent.app import app
from pai_agent.bus import EventBus
from pai_agent.tools import blender, print_prep

FIELDS = {"id", "name", "domain", "provides", "remote", "available", "version", "path", "detail", "install_hint", "last"}


def tool(path: Path) -> Path:
    """A fake executable that leaves `<path>.ran` behind if anything starts it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\ntouch "{path}.ran"\n')
    path.chmod(0o755)
    return path


def jdk(root: Path, version: str) -> Path:
    java = tool(root / "bin" / "java")
    (root / "release").write_text(f'JAVA_VERSION="{version}"\n')
    return java


class _Machine:
    """A machine with nothing installed: PATH, HOME, the app and bin folders and the repository are empty temp folders."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin, self.home, self.repo = self.root / "bin", self.root / "home", self.root / "repo"
        for folder in (self.bin, self.home, self.repo):
            folder.mkdir()
        self.log = adapters.RunLog(self.root / "adapters.json")

        def freecadcmd() -> str | None:
            # find_freecadcmd also walks /Applications/FreeCAD.app itself, which no patch can move: FreeCAD is on PATH or nowhere.
            return shutil.which("freecadcmd")

        slicers = tuple((name, commands, str(self.root / "none" / name)) for name, commands, _ in print_prep._SLICERS)
        for patcher in (
            patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home), "FREECAD_GUI": "off"}, clear=True),
            patch.object(adapters, "BIN_DIRS", ()),
            patch.object(adapters, "APP_DIRS", (self.root / "Applications",)),
            patch.object(adapters, "JAVA_PATHS", ()),
            patch.object(adapters, "REPO_ROOT", self.repo),
            patch.object(sparkbench, "_KNOWN_NODE", ()),
            patch.object(sparkbench, "_TSX", self.root / "bridge" / "node_modules" / "tsx" / "dist" / "cli.mjs"),
            patch.object(adapters, "LOG", self.log),
            patch.object(adapters, "find_freecadcmd", freecadcmd),
            patch.object(freecad_run, "find_freecadcmd", freecadcmd),
            patch.object(blender, "_KNOWN_BLENDER", self.root / "none" / "Blender"),
            patch.object(print_prep, "_SLICERS", slicers),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        adapters._isaac_seen = None

    def rows(self) -> dict[str, dict]:
        return {row["id"]: row for row in asyncio.run(adapters.report())}

    def checkout(self, *, installed: bool) -> Path:
        """SparkBench where setup_sparkbench.sh puts it, with its npm packages and the bridge's tsx when installed."""

        folder = self.home / ".cache" / "anybuild" / "sparkbench" / sparkbench.COMMIT
        (folder / "src" / "core").mkdir(parents=True)
        (folder / "src" / "core" / "planner.ts").write_text("")
        (folder / ".git").mkdir()
        (folder / ".git" / "HEAD").write_text(sparkbench.COMMIT + "\n")
        if installed:
            (folder / "node_modules").mkdir()
            sparkbench._TSX.parent.mkdir(parents=True)
            sparkbench._TSX.write_text("")
        return folder

    def kicad(self, version: str) -> None:
        app_dir = self.root / "Applications" / "KiCad" / "KiCad.app"
        tool(app_dir / "Contents" / "MacOS" / "kicad-cli")
        (app_dir / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))

    def jar(self) -> None:
        jar = self.home / ".cache" / "sparkbench" / "freerouting" / "freerouting-2.5.0.jar"
        jar.parent.mkdir(parents=True)
        jar.write_bytes(b"PK")


class LookupTests(_Machine, unittest.TestCase):
    def test_locked_path_finds_only_the_backends_mujoco_and_hints_every_install(self):
        rows = self.rows()
        self.assertEqual(list(rows), [adapter.id for adapter in adapters.ADAPTERS])
        self.assertEqual({row["domain"] for row in rows.values()}, set(adapters.DOMAINS))
        self.assertEqual([key for key, row in rows.items() if row["remote"]], ["isaac"])
        self.assertIs(rows["mujoco"]["available"], True)
        for key, row in rows.items():
            self.assertEqual(set(row), FIELDS)
            if key != "mujoco":
                self.assertIs(row["available"], False, key)
                self.assertIsNone(row["path"], key)
            self.assertTrue(row["detail"], key)
            self.assertTrue(row["install_hint"], key)
            self.assertIsNone(row["last"], key)
        self.assertIn("CadQuery", rows["freecad"]["detail"])
        self.assertIn("recorded still", rows["blender"]["detail"])
        self.assertIn("beam estimate", rows["calculix"]["detail"])
        self.assertIn("No GPU host", rows["isaac"]["detail"])

    def test_installed_engines_are_found_with_versions_from_their_files_and_none_is_started(self):
        for name in ("freecadcmd", "ccx", "gmsh", "blender", "prusa-slicer", "ngspice", "node"):
            tool(self.bin / name)
        self.kicad("9.0.2")
        self.jar()
        java = jdk(self.root / "jdk", "21.0.2")
        self.checkout(installed=True)
        venv = self.repo / "anybuild-robouse" / ".venv"
        tool(venv / "bin" / "anybuild-robouse")
        (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        for dist in ("robouse-0.6.1", "mujoco-3.3.0"):
            (venv / "lib" / "python3.12" / "site-packages" / (dist + ".dist-info")).mkdir(parents=True)
        (self.repo / "anybuild-robouse" / "pyproject.toml").write_text("[project]\nname = 'anybuild-robouse'\n")

        with patch.dict(os.environ, {"JAVA": str(java)}):
            rows = self.rows()

        self.assertEqual([key for key, row in rows.items() if row["available"] is not True], ["isaac"])
        self.assertEqual(rows["kicad"]["version"], "9.0.2")
        self.assertEqual(rows["sparkbench"]["version"], sparkbench.COMMIT[:7])
        self.assertEqual(rows["sparkbench"]["path"], "~/.cache/anybuild/sparkbench/" + sparkbench.COMMIT)
        self.assertEqual(rows["freerouting"]["version"], "2.5.0")
        self.assertEqual(rows["freerouting"]["path"], "~/.cache/sparkbench/freerouting/freerouting-2.5.0.jar")
        self.assertIn("on Java 21", rows["freerouting"]["detail"])
        self.assertEqual(rows["robouse"]["version"], "0.6.1")
        self.assertIn("MuJoCo 3.3.0", rows["robouse"]["detail"])
        self.assertIn("`cd anybuild-robouse && uv sync`", rows["robouse"]["install_hint"])
        self.assertIn("PrusaSlicer", rows["slicer"]["detail"])
        self.assertEqual(rows["node"]["path"], str(self.bin / "node"))
        # The answer names the home folder ~, never the user.
        self.assertNotIn(str(self.home), json.dumps(rows))
        # Only files were read: no fake tool was started, not even for its version.
        self.assertEqual(sorted(path.name for path in self.root.rglob("*.ran")), [])

    def test_half_installs_say_what_is_missing(self):
        tool(self.bin / "node")
        self.checkout(installed=False)
        self.kicad("7.0.11")
        self.jar()
        java = jdk(self.root / "jdk", "17.0.9")
        tool(self.bin / "robouse")
        with patch.dict(os.environ, {"JAVA": str(java)}):
            rows = self.rows()
        self.assertIs(rows["sparkbench"]["available"], False)
        self.assertTrue(rows["sparkbench"]["detail"].startswith(f"SparkBench's npm packages are not installed in ~/.cache/anybuild/sparkbench/{sparkbench.COMMIT}"))
        self.assertIn("`bash agent/scripts/setup_sparkbench.sh`", rows["sparkbench"]["install_hint"])
        self.assertEqual(rows["sparkbench"]["version"], sparkbench.COMMIT[:7])
        self.assertIs(rows["kicad"]["available"], False)
        self.assertIn("KiCad 7.0.11 is too old", rows["kicad"]["detail"])
        self.assertIs(rows["freerouting"]["available"], False)
        self.assertIn("Java 17 is too old", rows["freerouting"]["detail"])
        self.assertIs(rows["robouse"]["available"], False)
        self.assertIn("not AnyBuild's gripper backend", rows["robouse"]["detail"])
        # Before the bridge is in the repository, the hint names the package to install.
        self.assertIn("robouse[sim]==0.6.1", rows["robouse"]["install_hint"])

    def test_sparkbench_without_node_says_so(self):
        self.checkout(installed=True)
        rows = self.rows()
        self.assertIs(rows["sparkbench"]["available"], False)
        self.assertTrue(rows["sparkbench"]["detail"].startswith("Node.js is not installed, so circuit_design gives no circuit"))
        self.assertIs(rows["node"]["available"], False)
        self.assertIn("Node.js 20 or newer", rows["node"]["install_hint"])

    def test_engines_turned_off_say_so(self):
        for name in ("ccx", "gmsh", "prusa-slicer"):
            tool(self.bin / name)
        with patch.dict(os.environ, {"PAI_CCX": "off", "PAI_SLICER": "off"}):
            rows = self.rows()
        self.assertIs(rows["calculix"]["available"], False)
        self.assertIn("PAI_CCX=off", rows["calculix"]["detail"])
        self.assertIs(rows["slicer"]["available"], False)
        self.assertIn("PAI_SLICER=off", rows["slicer"]["detail"])

    def test_the_open_freecad_window_shows_in_the_detail(self):
        with patch.dict(os.environ, {"FREECAD_GUI": "auto"}), patch.object(adapters, "rpc_available", return_value=True):
            only_window = self.rows()["freecad"]
            tool(self.bin / "freecadcmd")
            both = self.rows()["freecad"]
        self.assertIs(only_window["available"], True)
        self.assertIn("Only the drone frame builds in FreeCAD", only_window["detail"])
        self.assertIn("open FreeCAD window builds the drone frame visibly", both["detail"])

    def test_a_broken_lookup_answers_its_own_row_and_spares_the_rest(self):
        with patch.object(adapters, "find_blender", side_effect=RuntimeError("boom")), self.assertLogs("pai_agent.adapters", "WARNING"):
            rows = self.rows()
        self.assertIs(rows["blender"]["available"], False)
        self.assertEqual(rows["blender"]["detail"], "The lookup itself failed: RuntimeError: boom")
        self.assertIs(rows["mujoco"]["available"], True)


class IsaacProbeTests(_Machine, unittest.IsolatedAsyncioTestCase):
    async def rows_now(self) -> dict[str, dict]:
        return {row["id"]: row for row in await adapters.report()}

    async def test_a_live_gpu_is_available_and_a_failed_probe_is_not(self):
        live = {"host": "gpu.example", "gpu": "NVIDIA A40", "state": "live", "detail": "SSH connected."}
        offline = {"host": "gpu.example", "gpu": None, "state": "offline", "detail": "GPU SSH or nvidia-smi is unavailable."}
        with patch.dict(os.environ, {"RUNPOD_SSH_HOST": "gpu.example"}):
            with patch.object(status, "isaac_connection", AsyncMock(return_value=live)):
                row = (await self.rows_now())["isaac"]
            self.assertIs(row["available"], True)
            self.assertIn("NVIDIA A40", row["detail"])
            with patch.object(status, "isaac_connection", AsyncMock(return_value=offline)):
                row = (await self.rows_now())["isaac"]
            self.assertIs(row["available"], False)
            self.assertIn("SSH or nvidia-smi failed", row["detail"])

    async def test_a_hanging_probe_answers_within_the_budget_then_the_last_known_state(self):
        live = {"host": "gpu.example", "gpu": "NVIDIA A40", "state": "live", "detail": "SSH connected."}
        gates = [asyncio.Event(), asyncio.Event()]
        waiting = iter(gates)

        async def probe():
            await next(waiting).wait()
            return live

        with patch.dict(os.environ, {"RUNPOD_SSH_HOST": "gpu.example"}), patch.object(status, "isaac_connection", probe):
            started = time.perf_counter()
            first = (await self.rows_now())["isaac"]
            # The probe waits BUDGET_S (0.2 s); the rest of the second is room for a loaded machine.
            self.assertLess(time.perf_counter() - started, 1.5)
            self.assertIsNone(first["available"])
            self.assertEqual(first["detail"], "Checking SSH to gpu.example …")
            gates[0].set()
            for _ in range(100):
                if adapters._isaac_seen is not None:
                    break
                await asyncio.sleep(0.01)
            # The next probe hangs too, so the row answers what the first one found.
            second = (await self.rows_now())["isaac"]
            gates[1].set()
        self.assertIs(second["available"], True)
        self.assertIn("NVIDIA A40", second["detail"])


class RunLogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "runs" / "adapters.json"
        self.log = adapters.RunLog(self.path)

    def test_results_become_each_adapters_last_run_and_outlast_a_restart(self):
        events = [
            {"type": "sim", "run": 1, "result": "fail", "summary": "Thrust-to-weight 1.21. It barely hovers."},
            {"type": "mission", "mission": "speed_run", "label": "Speed run", "result": "pass", "summary": "61 km/h, min. 60 km/h."},
            {"type": "fem", "part_name": "Base plate", "result": "pass", "safety": 3.14, "limit": 2},
            {"type": "print", "source": "slicer", "slicer": "PrusaSlicer", "parts": [{"name": "Base plate"}], "totals": {"parts": 2, "time_min": 95.4, "filament_g": 41.2}},
            {"type": "render", "source": "blender", "png_url": "/files/s1/studio-v1.png", "label": "v1 · Studio"},
            {"type": "cad", "source": "freecad", "part": {"name": "Base plate"}},
            {"type": "omniverse", "source": "live", "status": "done", "mode": "test", "passed": True, "detail": "Held 0.5 m in the gust."},
            {"type": "circuit", "ok": False, "summary": "ESP32 DevKit V1 with 2 parts and 6 wires: 1 error and 0 warnings in the checks, 2 of 3 tests pass, 5 s simulated without an error."},
        ]
        self.assertEqual([self.log.record(event) for event in events], ["mujoco", "mujoco", "calculix", "slicer", "blender", "freecad", "isaac", "sparkbench"])
        last = adapters.RunLog(self.path).last()
        self.assertEqual(last["mujoco"], {"at": last["mujoco"]["at"], "pass": True, "summary": "Speed run passed: 61 km/h, min. 60 km/h."})
        self.assertLess(abs(last["mujoco"]["at"] - time.time()), 60)
        self.assertEqual(last["calculix"]["summary"], "FEM of Base plate passed: safety 3.1x, needs 2x")
        self.assertEqual(last["slicer"]["summary"], "PrusaSlicer sliced 2 parts: 95 min, 41 g of filament")
        self.assertEqual(last["blender"]["summary"], "Rendered v1 · Studio")
        self.assertEqual(last["freecad"]["summary"], "Built Base plate in FreeCAD")
        self.assertEqual(last["isaac"]["summary"], "Isaac Sim test passed: Held 0.5 m in the gust.")
        self.assertEqual(last["sparkbench"]["summary"], "Circuit failed: ESP32 DevKit V1 with 2 parts and 6 wires: 1 error and 0 warnings in the checks, 2 of 3 tests pass, 5 s simulated without an error.")
        self.assertIs(last["sparkbench"]["pass"], False)

    def test_each_test_kind_is_named(self):
        cases = [
            ({"type": "sim", "result": "fail", "summary": "Lagged 14 mm."}, "Hover test failed: Lagged 14 mm."),
            ({"type": "sim", "kind": "grip", "result": "pass", "summary": "Held."}, "Grip test passed: Held."),
            ({"type": "sim", "kind": "rigid", "mode": "drop", "result": "pass"}, "Drop test passed"),
            ({"type": "mission", "label": "Hard turn", "controller": "trained", "result": "pass", "summary": "131 °/s."}, "Hard turn with the trained controller passed: 131 °/s."),
            ({"type": "cad", "source": "freecad", "view_png_url": "/files/s1/view.png"}, "Built the drone in the open FreeCAD window"),
            ({"type": "omniverse", "source": "live", "status": "done", "mode": "train"}, "Isaac Lab training finished"),
        ]
        for event, summary in cases:
            self.assertEqual(adapters.run_of(event)[2], summary)

    def test_a_fallback_counts_only_when_the_engine_was_installed(self):
        still = {"type": "render", "source": "blender", "png_url": "/files/fallback/render.png", "label": "Recorded, Blender is offline"}
        block = {"type": "cad", "source": "cadquery", "part": {"name": "Hook"}}
        estimate = {"type": "print", "source": "estimate", "slicer": "", "parts": [{"name": "Hook"}], "totals": {}}
        with patch.object(adapters, "find_blender", return_value=None), patch.object(adapters, "find_freecadcmd", return_value=None):
            self.assertEqual([self.log.record(event) for event in (still, block, estimate)], [None, None, None])
        with patch.object(adapters, "find_blender", return_value="/x/blender"), patch.object(adapters, "find_freecadcmd", return_value="/x/freecadcmd"):
            self.assertEqual([self.log.record(event) for event in (still, block, estimate)], ["blender", "freecad", None])
        failed = {"type": "print", "source": "estimate", "slicer": "", "parts": [{"name": "Hook", "slicer_error": "PrusaSlicer exited with 1"}], "totals": {}}
        self.assertEqual(self.log.record(failed), "slicer")
        last = self.log.last()
        self.assertEqual(last["blender"]["summary"], "Blender failed or took too long, so the recorded still stands in")
        self.assertEqual(last["freecad"]["summary"], "FreeCAD failed or got stuck, so CadQuery built Hook")
        self.assertEqual(last["slicer"]["summary"], "Slicing Hook failed: PrusaSlicer exited with 1")
        self.assertFalse(any(row["pass"] for row in last.values()))

    def test_other_events_and_odd_shapes_are_no_runs(self):
        for event in (
            {"type": "chat", "role": "agent", "text": "Done."},
            {"type": "sim", "result": "running"},
            {"type": "cad", "source": "freecad", "assembly": True},
            {"type": "cad", "source": "freecad", "part": "not an object"},
            {"type": "print", "source": "slicer", "parts": "nope", "totals": []},
            {"type": "omniverse", "source": "recorded", "status": "recorded"},
            {"type": "omniverse", "source": "live", "status": "running"},
            {"type": "circuit", "ok": "yes", "summary": "Not a verdict."},
        ):
            self.assertIsNone(self.log.record(event), event)
        self.assertFalse(self.path.exists())

    def test_a_corrupt_file_reads_as_empty_and_is_replaced(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json")
        self.assertEqual(self.log.last(), {})
        self.log.record({"type": "fem", "part_name": "Arm", "result": "fail", "safety": 1.2, "limit": 2})
        self.assertEqual(list(json.loads(self.path.read_text())), ["calculix"])
        self.assertEqual(sorted(path.name for path in self.path.parent.iterdir()), ["adapters.json"])


class WatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_live_runs_are_recorded_never_a_backlog_or_a_reopened_chat(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log = adapters.RunLog(Path(temp.name) / "adapters.json")
        bus = EventBus()

        async def recorded(adapter: str) -> dict:
            for _ in range(500):
                if adapter in log.last():
                    return log.last()
                await asyncio.sleep(0.01)
            self.fail(adapter + " was never recorded")

        # Published before the watch subscribes: the session's backlog.
        await bus.publish({"type": "fem", "part_name": "Old", "result": "fail", "safety": 1.0, "limit": 2})
        with patch.object(adapters, "LOG", log):
            watcher = asyncio.create_task(adapters.watch(bus))
            for _ in range(500):
                if bus._subscribers:
                    break
                await asyncio.sleep(0.01)
            await bus.publish({"type": "sim", "result": "pass", "summary": "Live."})
            last = await recorded("mujoco")
            self.assertEqual(last["mujoco"]["summary"], "Hover test passed: Live.")
            self.assertNotIn("calculix", last)
            # A reopened chat replays its log: those runs happened before.
            await bus.load([{"type": "render", "png_url": "/files/s0/studio-v1.png", "label": "v1 · Studio"}])
            with self.assertLogs("pai_agent.adapters", "ERROR") as logged, patch.object(adapters.RunLog, "record", side_effect=OSError("disk full")):
                await bus.publish({"type": "cad", "source": "freecad", "part": {"name": "Lost"}})
                for _ in range(500):
                    if logged.records:
                        break
                    await asyncio.sleep(0.01)
            # A failed write is logged; the watch goes on.
            self.assertIn("Could not record an adapter run", logged.output[0])
            await bus.publish({"type": "fem", "part_name": "New", "result": "pass", "safety": 2.5, "limit": 2})
            last = await recorded("calculix")
            watcher.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await watcher
        self.assertEqual(last["calculix"]["summary"], "FEM of New passed: safety 2.5x, needs 2x")
        self.assertNotIn("blender", last)
        self.assertNotIn("freecad", last)
        self.assertEqual(bus._subscribers, [])


class EndpointTests(_Machine, unittest.TestCase):
    def test_get_adapters_answers_every_row_with_its_last_run_behind_the_access_gate(self):
        self.log.record({"type": "sim", "result": "pass", "summary": "It climbs to 50 cm."})
        client = TestClient(app)
        response = client.get("/api/adapters")
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual([row["id"] for row in rows], [adapter.id for adapter in adapters.ADAPTERS])
        self.assertTrue(all(set(row) == FIELDS for row in rows))
        mujoco = next(row for row in rows if row["id"] == "mujoco")
        self.assertEqual(mujoco["last"]["summary"], "Hover test passed: It climbs to 50 cm.")
        self.assertIs(mujoco["last"]["pass"], True)
        with patch.dict(os.environ, {"ANYBUILD_ACCESS_CODE": "test-code"}):
            self.assertEqual(client.get("/api/adapters").status_code, 401)


if __name__ == "__main__":
    unittest.main()
