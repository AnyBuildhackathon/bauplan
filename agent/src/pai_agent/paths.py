"""Directories the backend reads and writes."""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
AGENT_ROOT = PACKAGE_DIR.parents[1]
REPO_ROOT = AGENT_ROOT.parent
DATA_DIR = AGENT_ROOT / "data"
MEETINGS_DIR = DATA_DIR / "meetings"
PARTS_PATH = DATA_DIR / "parts.json"
RUNS_DIR = AGENT_ROOT / "runs"
SESSIONS_DIR = RUNS_DIR / "sessions"
FALLBACK_DIR = RUNS_DIR / "fallback"
FALLBACK_TRAINING = FALLBACK_DIR / "training.json"
ENV_PATH = AGENT_ROOT / ".env"
