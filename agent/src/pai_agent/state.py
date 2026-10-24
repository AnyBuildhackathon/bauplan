"""Session state for one drone build."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BuildState:
    session_id: str
    directory: Path
    selected: dict[str, dict] = field(default_factory=dict)
    frame_mass_g: float | None = None
    metrics: dict = field(default_factory=dict)
    requirements: list[dict] = field(default_factory=list)
    sim_run: int = 0
    last_sim: dict | None = None
    stl_path: str | None = None
    cad_params: dict = field(default_factory=dict)
    cad_builds: int = 0
    bom: dict | None = None
    isaac_job_id: str | None = None
    training_video: str | None = None
    omniverse_result: dict | None = None
    started: bool = False
    finished: bool = False
    # Jamie: the meetings on the timeline, the versions built from them, and the order tasks.
    meetings: dict[str, dict] = field(default_factory=dict)
    meeting_cache: dict[str, dict] = field(default_factory=dict)
    versions: list[dict] = field(default_factory=list)
    reasons: dict[str, dict] = field(default_factory=dict)
    tasks: list[dict] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    templates_ready: bool = False
    last_read_live: bool = False
    complaints: list[dict] = field(default_factory=list)
    # Which product this session builds (drone or gripper), and the last generated CAD part.
    product: str = "drone"
    part: dict | None = None
    brief: dict = field(default_factory=dict)
