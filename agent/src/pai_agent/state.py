"""`BuildState`: everything one bench knows about the build in progress.

One dataclass for all three flows: the drone (`selected` parts by category, `frame_mass_g`,
`last_sim`), the gripper (`brief`, `part`) and any product from a spec (`spec`, `built`
printed parts, `picked` bought parts, `assembly`, `checks`). Tools write their results here
and the requirement rows are recomputed from it after every successful tool call
(`requirements.py`), so the pass or fail the dashboard shows is always derived from measured
values, never from what the model said. The versions hang on the same state so a rebuild can
diff against the previous version. `requests` keeps what the user typed, so a requirement is only
attributed to the user when its words are really in a request (`requirements.attribute`).
"""

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
    # Mission tests (simulate_mission): the latest outcome per mission, without its replay data.
    missions: dict[str, dict] = field(default_factory=dict)
    mission_run: int = 0
    # The last `geometry` event, so it is only sent again when a part or the frame changed.
    geometry_shown: dict | None = None
    stl_path: str | None = None
    cad_params: dict = field(default_factory=dict)
    cad_builds: int = 0
    bom: dict | None = None
    isaac_job_id: str | None = None
    training_video: str | None = None
    omniverse_result: dict | None = None
    started: bool = False
    finished: bool = False
    # What the user typed or said, oldest first: the only source a requirement may quote as theirs.
    requests: list[str] = field(default_factory=list)
    versions: list[dict] = field(default_factory=list)
    # What restoring a version needs beyond its event (catalog ids, frame params, the saved build), by n.
    version_files: dict[int, dict] = field(default_factory=dict)
    reasons: dict[str, dict] = field(default_factory=dict)
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
