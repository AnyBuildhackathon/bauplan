"""Session state for one build: the drone, the gripper, or any product from a spec."""

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
    # What restoring a version needs beyond its event (catalog ids, frame params, the saved build), by n.
    version_files: dict[int, dict] = field(default_factory=dict)
    reasons: dict[str, dict] = field(default_factory=dict)
    tasks: list[dict] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    templates_ready: bool = False
    last_read_live: bool = False
    complaints: list[dict] = field(default_factory=list)
    # Which product this session builds (drone, gripper or generic), and the last generated CAD part.
    product: str = "drone"
    part: dict | None = None
    brief: dict = field(default_factory=dict)
    # Any other product: its validated spec, the printed parts built per spec part id, the bought
    # parts picked per spec part id, the assembled model and the check results by check key.
    spec: dict | None = None
    built: dict[str, dict] = field(default_factory=dict)
    picked: dict[str, dict] = field(default_factory=dict)
    assembly: dict | None = None
    assembly_stale: bool = True
    checks: dict[str, dict] = field(default_factory=dict)
    # The community project this build was opened from: {"id", "title", "author"}, or None.
    remixed_from: dict | None = None
    # The last print plan from print_prep: per-part time, filament, cost, warnings and G-code.
    print_plan: dict | None = None
    # Design optimizer runs by id: the `optimize` event with its variants, and which one was built.
    optimize: dict[str, dict] = field(default_factory=dict)
