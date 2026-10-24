"""Mechanic's spoken lines without a network: milestones, fallbacks, and live-only events."""

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pai_agent import speech
from pai_agent.bus import EventBus
from pai_agent.state import BuildState


class FakeStream:
    def __init__(self, pieces):
        self.pieces = pieces

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    async def text_stream(self):
        for piece in self.pieces:
            yield piece


class FakeMessages:
    def __init__(self, pieces):
        self.pieces, self.calls = pieces, []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.pieces)


class FakeClient:
    def __init__(self, pieces):
        self.messages = FakeMessages(pieces)


class MilestoneTest(unittest.TestCase):
    def test_milestones_and_progress(self):
        self.assertEqual(speech.milestone({"type": "sim", "result": "fail", "summary": "It sank."})["result"], "fail")
        version = speech.milestone({"type": "version", "n": 2, "summary": "49.3 g · 15.6 min", "diff": [{"label": "Flight time", "before": 11.7, "after": 15.6, "unit": "min"}]})
        self.assertEqual(version["changes"], ["Flight time: 11.7 to 15.6 min"])
        self.assertIsNone(speech.milestone({"type": "tool", "name": "parts_search", "status": "ok"}))
        self.assertIsNone(speech.milestone({"type": "step", "id": "cad", "status": "done"}))
        self.assertEqual(speech.milestone({"type": "step", "label": "CAD", "status": "failed"})["step"], "CAD")

    def test_fresh_bench_names_no_product(self):
        state = BuildState(session_id="t", directory=Path("/tmp"))
        prompt = speech._reply_prompt("Design a phone stand", state, "started", None, [])
        self.assertNotIn("drone", prompt)
        state.started = True
        self.assertIn("Product: drone", speech._reply_prompt("Make it lighter", state, "started", None, []))

    def test_fallback_lines(self):
        self.assertEqual(speech.fallback_line([{"milestone": "simulation", "result": "pass"}]), "The simulation passed.")
        self.assertEqual(speech.fallback_line([{"milestone": "version finished", "version": 2, "summary": "49.3 g · 15.6 min"}]), "Version 2 is done: 49.3 g, 15.6 min.")


class VoiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"})
        self.env.start()
        self.bus = EventBus()
        self.seen = []
        self.busy = True
        self.voice = speech.Voice(self.bus, busy=lambda: self.busy)
        self.bus.observer = lambda event: (self.seen.append(event), self.voice.observe(event))

    async def asyncTearDown(self):
        self.voice.cancel()
        self.env.stop()

    async def test_reply_streams_live_and_lands_in_chat(self):
        self.voice._client = FakeClient(["On it, ", "building now."])
        state = BuildState(session_id="t", directory=Path("."))
        self.voice.reply("Build the drone.", state, "started")
        await asyncio.wait_for(self.voice._reply, 2)
        says = [e for e in self.seen if e["type"] == "say"]
        self.assertEqual([e.get("delta") for e in says[:-1]], ["On it, ", "building now."])
        self.assertEqual(says[-1]["text"], "On it, building now.")
        # Spoken pieces are live only; the finished reply is kept as a chat line.
        self.assertEqual([e["type"] for e in self.bus.events], ["chat"])
        self.assertEqual(self.bus.events[-1], {"type": "chat", "role": "agent", "text": "On it, building now.", "voice": True})
        self.assertEqual(self.voice._client.messages.calls[0]["thinking"], {"type": "disabled"})

    async def test_updates_only_while_building(self):
        self.voice._client = FakeClient(["The simulation passed."])
        self.busy = False
        await self.bus.publish({"type": "sim", "result": "pass", "summary": "ok"})
        self.assertIsNone(self.voice._update)
        self.busy = True
        await self.bus.publish({"type": "sim", "result": "pass", "summary": "ok"})
        await self.bus.publish({"type": "version", "n": 1, "summary": "36.7 g", "diff": []})
        await asyncio.wait_for(self.voice._update, 3)
        done = [e for e in self.seen if e["type"] == "say" and e["done"]]
        # Milestones that land together become one sentence.
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["kind"], "update")
        # The spoken update is also written into the chat, once.
        spoken = [e for e in self.bus.events if e["type"] == "chat" and e.get("voice")]
        self.assertEqual([e["text"] for e in spoken], ["The simulation passed."])

    async def test_model_failure_falls_back(self):
        class Broken:
            class messages:
                @staticmethod
                def stream(**kwargs):
                    raise RuntimeError("offline")

        self.voice._client = Broken()
        await self.bus.publish({"type": "sim", "result": "fail", "summary": "sank"})
        await asyncio.wait_for(self.voice._update, 3)
        done = [e for e in self.seen if e["type"] == "say" and e["done"]]
        self.assertEqual(done[0]["text"], "The simulation failed. Let me fix that.")


if __name__ == "__main__":
    unittest.main()
