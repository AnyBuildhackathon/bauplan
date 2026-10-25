"""The public access gate: access code, sessions, rate limits, and the CORS origins."""

import os
import re
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pai_agent import access
from pai_agent.app import _cors_origins

CODE = "orange-falcon-42"
JSON = {"content-type": "application/json"}


def make_client() -> TestClient:
    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.post("/api/prompt")
    async def prompt():
        return {"ok": True}

    @app.post("/api/voice/speak")
    async def speak():
        return {"ok": True}

    @app.get("/api/events")
    async def events():
        return {"ok": True}

    @app.get("/files/{bucket}/{name}")
    async def files(bucket: str, name: str):
        return {"ok": True}

    app.add_middleware(access.AccessGate)
    # As behind Tailscale Funnel: the peer is loopback, the caller is in X-Forwarded-For.
    return TestClient(app, client=("127.0.0.1", 50000))


class AccessGateTest(unittest.TestCase):
    def setUp(self):
        env = {"ANYBUILD_ACCESS_CODE": CODE}
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.client = make_client()

    def tearDown(self):
        self.env.stop()

    def login(self, ip: str = "203.0.113.5") -> str:
        res = self.client.post("/api/access", json={"code": CODE}, headers={"x-forwarded-for": ip})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["token"]

    def test_open_without_code(self):
        with patch.dict(os.environ, {"ANYBUILD_ACCESS_CODE": ""}):
            self.assertEqual(self.client.post("/api/prompt").status_code, 200)

    def test_health_stays_open_everything_else_needs_a_session(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        for method, path in [("POST", "/api/prompt"), ("GET", "/api/events"), ("POST", "/api/voice/speak"), ("GET", "/files/s1/frame.stl"), ("GET", "/api/access")]:
            res = self.client.request(method, path)
            self.assertEqual(res.status_code, 401, path)
            self.assertEqual(res.json()["access"], "required")

    def test_code_gives_a_token_and_a_cookie(self):
        res = self.client.post("/api/access", json={"code": f"  {CODE} "})
        self.assertEqual(res.status_code, 200)
        cookie = res.headers["set-cookie"]
        for part in ("HttpOnly", "Secure", "SameSite=None"):
            self.assertIn(part, cookie)
        token = res.json()["token"]
        self.assertEqual(self.client.get("/api/access", headers={"authorization": f"Bearer {token}"}).status_code, 200)
        self.assertEqual(self.client.get(f"/api/events?access_token={token}").status_code, 200)
        self.assertEqual(self.client.get("/files/s1/frame.stl", headers={"cookie": f"{access.COOKIE}={token}"}).status_code, 200)

    def test_tampered_or_expired_tokens_fail(self):
        token = self.login()
        body, sig = token.split(".")
        forged = body[:-2] + ("AA" if body[-2:] != "AA" else "BB") + "." + sig
        self.assertEqual(self.client.get("/api/access", headers={"authorization": f"Bearer {forged}"}).status_code, 401)
        with patch.dict(os.environ, {"ANYBUILD_ACCESS_CODE": "new-code"}):
            self.assertEqual(self.client.get("/api/access", headers={"authorization": f"Bearer {token}"}).status_code, 401)
        self.assertIsNone(access.verify_token(CODE, token, now=10**12))

    def test_wrong_codes_are_rate_limited_per_ip(self):
        for _ in range(access.FAILS_PER_IP[0]):
            res = self.client.post("/api/access", json={"code": "guess"}, headers={"x-forwarded-for": "198.51.100.7"})
            self.assertEqual(res.status_code, 401)
        res = self.client.post("/api/access", json={"code": CODE}, headers={"x-forwarded-for": "198.51.100.7"})
        self.assertEqual(res.status_code, 429)
        self.assertIn("Retry-After", res.headers)
        # Another address is unaffected.
        self.login(ip="198.51.100.8")

    def test_access_needs_json(self):
        res = self.client.post("/api/access", data={"code": CODE})
        self.assertEqual(res.status_code, 415)

    def test_builds_are_limited_per_session(self):
        with patch.dict(os.environ, {"ANYBUILD_LIMIT_BUILDS": "3"}):
            auth = {"authorization": f"Bearer {self.login()}"}
            for _ in range(3):
                self.assertEqual(self.client.post("/api/prompt", headers=auth).status_code, 200)
            res = self.client.post("/api/prompt", headers=auth)
            self.assertEqual(res.status_code, 429)
            self.assertIn("3 builds", res.json()["detail"])
            # Speech has its own budget.
            self.assertEqual(self.client.post("/api/voice/speak", headers=auth).status_code, 200)
            # A fresh session from the same IP still has room until the per-IP cap (3x).
            auth2 = {"authorization": f"Bearer {self.login()}"}
            self.assertEqual(self.client.post("/api/prompt", headers=auth2).status_code, 200)

    def test_builds_are_limited_per_ip(self):
        with patch.dict(os.environ, {"ANYBUILD_LIMIT_BUILDS": "1"}):
            for _ in range(3):
                auth = {"authorization": f"Bearer {self.login()}", "x-forwarded-for": "203.0.113.9"}
                self.assertEqual(self.client.post("/api/prompt", headers=auth).status_code, 200)
            auth = {"authorization": f"Bearer {self.login()}", "x-forwarded-for": "203.0.113.9"}
            self.assertEqual(self.client.post("/api/prompt", headers=auth).status_code, 429)

    def test_buckets(self):
        self.assertEqual(access.bucket_of("POST", "/api/versions/2/restore"), "build")
        self.assertEqual(access.bucket_of("POST", "/api/control"), "build")
        self.assertEqual(access.bucket_of("POST", "/api/library/desk-fan/open"), "build")
        self.assertEqual(access.bucket_of("POST", "/api/explain"), "explain")
        self.assertIsNone(access.bucket_of("GET", "/api/versions"))
        self.assertIsNone(access.bucket_of("POST", "/api/answer"))

    def test_window_slides(self):
        window = access.Window()
        window.add("k", 0.0)
        self.assertGreater(window.retry_after("k", 1, 60, 30.0), 0)
        self.assertEqual(window.retry_after("k", 1, 60, 61.0), 0)

    def test_client_ip_trusts_forwarding_only_from_loopback(self):
        scope = {"client": ("127.0.0.1", 1), "headers": [(b"x-forwarded-for", b"1.1.1.1, 2.2.2.2")]}
        self.assertEqual(access.client_ip(scope), "2.2.2.2")
        scope["client"] = ("9.9.9.9", 1)
        self.assertEqual(access.client_ip(scope), "9.9.9.9")


class CorsTest(unittest.TestCase):
    def test_origins(self):
        with patch.dict(os.environ, {"ANYBUILD_CORS_ORIGINS": "https://anybuild.example.org"}):
            pattern = re.compile(_cors_origins())
        for ok in [
            "https://anybuild-demo.vercel.app",
            "https://anybuild-demo-git-main-anybuild.vercel.app",
            "http://localhost:5180",
            "http://127.0.0.1:5226",
            "tauri://localhost",
            "https://anybuild.example.org",
        ]:
            self.assertTrue(pattern.fullmatch(ok), ok)
        for bad in ["https://evil.vercel.app", "https://anybuild-demo.vercel.app.evil.com", "https://example.org", "http://anybuild-demo.vercel.app"]:
            self.assertFalse(pattern.fullmatch(bad), bad)


if __name__ == "__main__":
    unittest.main()
