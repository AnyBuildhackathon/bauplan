import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from pai_agent.run_control import RunControl, RunStopped

_ENV = {"PAI_FORCE_MOCK": "1", "PAI_WARM": "0", "PAI_ASK_TIMEOUT_S": "0", "FREECAD_GUI": "off"}


async def _until(check, seconds: float = 30.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


class Gate(unittest.TestCase):
    def test_pause_holds_the_checkpoint_until_resume(self):
        async def flow():
            events = []

            async def publish(event):
                events.append(event["status"])

            run = RunControl(publish)
            await run.started()
            self.assertTrue(await run.pause())
            waiter = asyncio.create_task(run.checkpoint())
            await asyncio.sleep(0.05)
            held = not waiter.done()
            await run.resume()
            await asyncio.wait_for(waiter, 1)
            await run.finished()
            return held, events

        held, events = asyncio.run(flow())
        self.assertTrue(held)
        self.assertEqual(events, ["running", "pausing", "paused", "running", "idle"])

    def test_stop_wakes_a_paused_run_and_raises(self):
        async def flow():
            async def publish(_event):
                pass

            run = RunControl(publish)
            await run.started()
            await run.pause()
            waiter = asyncio.create_task(run.checkpoint())
            await asyncio.sleep(0.05)
            await run.stop()
            with self.assertRaises(RunStopped):
                await asyncio.wait_for(waiter, 1)
            await run.finished()
            return await run.pause()

        # Nothing runs any more, so there is nothing to pause.
        self.assertFalse(asyncio.run(flow()))


class ClosedConversation(unittest.TestCase):
    def test_stopped_tool_uses_get_results_and_the_stop_is_recorded(self):
        from pai_agent.orchestrator import _close_stopped, _results

        uses = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
        results = _results(uses, [{"ok": True, "mass_g": 40}])
        self.assertEqual([r["tool_use_id"] for r in results], ["a", "b"])
        self.assertFalse(results[0]["is_error"])
        self.assertTrue(results[1]["is_error"])

        messages = [
            {"role": "user", "content": "build a drone"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "cad_frame", "input": {}}]},
        ]
        _close_stopped(messages)
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user", "assistant"])
        self.assertEqual(messages[2]["content"][0]["tool_use_id"], "t1")


class SessionFlow(unittest.TestCase):
    def test_paused_build_runs_no_tool_and_resume_finishes_it(self):
        with mock.patch.dict(os.environ, _ENV):
            from pai_agent.session import Session

            async def flow():
                session = Session()
                await session.bootstrap()
                await session.start("Build me a racing drone")
                await _until(lambda: any(e.get("type") == "tool" and e.get("status") == "running" for e in session.bus.events))
                self.assertTrue((await session.pause())["ok"])
                await _until(lambda: session.run.status == "paused")
                count = len([e for e in session.bus.events if e.get("type") == "tool" and e.get("status") == "running"])
                await asyncio.sleep(0.3)
                after = len([e for e in session.bus.events if e.get("type") == "tool" and e.get("status") == "running"])
                self.assertTrue((await session.resume())["ok"])
                await asyncio.wait_for(session.task, 120)
                return count, after, session

            count, after, session = asyncio.run(flow())
        self.assertEqual(count, after)
        self.assertEqual(session.run.status, "idle")
        self.assertTrue(session.state.versions)

    def test_stop_keeps_the_bench_and_a_new_message_starts(self):
        with mock.patch.dict(os.environ, _ENV):
            from pai_agent.session import Session

            async def flow():
                session = Session()
                await session.bootstrap()
                await session.start("Build me a racing drone")
                await _until(lambda: any(e.get("type") == "tool" and e.get("status") == "running" for e in session.bus.events))
                self.assertTrue((await session.stop())["ok"])
                await asyncio.wait_for(session.task, 60)
                chat = [e["text"] for e in session.bus.events if e.get("type") == "chat"]
                stopped = (await session.stop())["ok"]
                again = await session.start("Build me a racing drone")
                await asyncio.wait_for(session.task, 120)
                return chat, stopped, again, session

            chat, stopped, again, session = asyncio.run(flow())
        self.assertTrue(any(text.startswith("Stopped.") for text in chat))
        self.assertFalse(stopped)
        self.assertEqual(again["status"], "started")
        self.assertEqual(session.run.status, "idle")

    def test_a_message_to_a_paused_run_stops_it_and_starts_the_message(self):
        with mock.patch.dict(os.environ, _ENV):
            from pai_agent.session import Session

            async def flow():
                session = Session()
                await session.bootstrap()
                await session.start("Build me a racing drone")
                await _until(lambda: any(e.get("type") == "tool" and e.get("status") == "running" for e in session.bus.events))
                await session.pause()
                await _until(lambda: session.run.status == "paused")
                result = await session.start("Make it lighter")
                await asyncio.wait_for(session.task, 120)
                chat = [(e["role"], e["text"]) for e in session.bus.events if e.get("type") == "chat"]
                return result, chat

            result, chat = asyncio.run(flow())
        self.assertEqual(result["status"], "started")
        stopped = next(i for i, (role, text) in enumerate(chat) if role == "agent" and text.startswith("Stopped."))
        self.assertIn(("user", "Make it lighter"), chat[stopped:])


if __name__ == "__main__":
    unittest.main()
