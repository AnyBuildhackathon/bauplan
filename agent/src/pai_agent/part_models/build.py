"""Build every library part's 3D model from agent/data/models/sources.json and write the manifest.

    cd agent && uv run python -m pai_agent.part_models.build [--only id,id] [--step]

sources.json holds, per part id: the generator type (or an official STEP), the measured numbers with
the page or drawing each comes from (with the date it was checked, and `how` when a number was read
off a scaled drawing), styled numbers (drawn in proportion, not measured) and notes.
A part whose type needs a number that no real source gives is built anyway, marked `approximate`,
and lists what is missing. GLBs go to web/public/models/parts/, official STEPs (when small) to
agent/data/models/step/, and manifest.json records files, kind, source, license and bounding boxes.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from ..paths import DATA_DIR, REPO_ROOT
from . import drone, maker
from .official import official_model

MODELS_DIR = DATA_DIR / "models"
SOURCES_PATH = MODELS_DIR / "sources.json"
MANIFEST_PATH = MODELS_DIR / "manifest.json"
STEP_DIR = MODELS_DIR / "step"
OFFICIAL_DIR = MODELS_DIR / "official"
# Official STEPs too big to keep in the repository are downloaded here once (agent/runs/cache is ignored).
OFFICIAL_CACHE = DATA_DIR.parent / "runs" / "cache" / "part-models"
WEB_DIR = REPO_ROOT / "web" / "public" / "models" / "parts"
STEP_LIMIT_BYTES = 1_200_000

GENERATORS = {
    "brushless_motor": drone.brushless_motor,
    "propeller": drone.propeller,
    "lipo_pack": drone.lipo_pack,
    "fpv_camera": drone.fpv_camera,
    "vtx": drone.vtx,
    "whoop_frame": drone.whoop_frame,
    "carbon_frame": drone.carbon_frame,
    "canopy": drone.canopy,
    "board": maker.board,
    "servo": maker.servo,
    "micro_gearmotor": maker.micro_gearmotor,
    "round_gearmotor": maker.round_gearmotor,
    "can_motor": maker.can_motor,
    "tt_motor": maker.tt_motor,
    "stepper": maker.stepper,
    "can_stepper": maker.can_stepper,
    "wheel": maker.wheel,
    "ball_caster": maker.ball_caster,
    "bearing": maker.bearing,
    "screw": maker.screw,
    "insert": maker.nut_or_insert,
    "disc": maker.disc,
    "cell": maker.cell,
    "cell_pack": maker.cell_pack,
    "enclosure": maker.enclosure,
    "wall_adapter": maker.wall_adapter,
    "fan": maker.fan,
    "rocker_switch": maker.rocker_switch,
    "coil": maker.coil,
    "pad": maker.pad,
}

# The numbers each type must take from a real source before its model counts as measured.
KEY_DIMS = {
    "brushless_motor": ["diameter_mm", "height_mm", "shaft_mm", "bolt_circle_mm", "bolts"],
    "propeller": ["diameter_mm", "blades", "shaft_mm", "hub_h_mm"],
    "lipo_pack": ["length_mm", "width_mm", "height_mm", "connector"],
    "fpv_camera": ["length_mm", "width_mm", "height_mm"],
    "vtx": ["length_mm", "width_mm", "height_mm", "mount_mm"],
    "whoop_frame": ["wheelbase_mm", "size_mm", "mount_mm", "mount_diameter_mm"],
    "carbon_frame": ["wheelbase_mm", "mount_mm", "mount_diameter_mm", "arm_thickness_mm"],
    "canopy": ["length_mm", "width_mm", "height_mm"],
    "board": ["length_mm", "width_mm", "holes", "connector_positions"],
    "servo": ["length_mm", "width_mm", "overall_height_mm", "tab_bottom_mm", "tab_span_mm", "hole_spacing_mm"],
    "micro_gearmotor": ["width_mm", "height_mm", "length_mm", "shaft_mm", "shaft_len_mm"],
    "round_gearmotor": ["diameter_mm", "length_mm", "shaft_mm", "face_hole_circle_mm"],
    "can_motor": ["width_mm", "height_mm", "length_mm", "shaft_mm"],
    "tt_motor": ["length_mm", "width_mm", "height_mm", "holes"],
    "stepper": ["face_mm", "length_mm", "shaft_mm", "hole_spacing_mm"],
    "can_stepper": ["diameter_mm", "height_mm", "ear_spacing_mm", "shaft_mm"],
    "wheel": ["diameter_mm", "width_mm", "bore_mm"],
    "ball_caster": ["ball_mm", "height_mm", "hole_spacing_mm"],
    "bearing": ["bore_mm", "outer_mm", "width_mm"],
    "screw": ["thread_mm", "length_mm", "head_d_mm"],
    "insert": ["outer_mm", "length_mm", "bore_mm"],
    "disc": ["diameter_mm", "height_mm"],
    "cell": ["diameter_mm", "length_mm"],
    "cell_pack": ["length_mm", "width_mm", "height_mm"],
    "enclosure": ["length_mm", "width_mm", "height_mm"],
    "wall_adapter": ["length_mm", "width_mm", "height_mm"],
    "fan": ["size_mm", "thickness_mm", "hole_spacing_mm"],
    "rocker_switch": ["length_mm", "width_mm", "height_mm"],
    "coil": ["coil_d_mm", "cord_d_mm"],
    "pad": ["length_mm", "width_mm", "height_mm"],
}

# A key number a drawing may give in another form: the servo height to the spline top (no horn drawn).
ALTERNATIVES = {"servo": {"overall_height_mm": "spline_top_mm"}}

FRAME = "millimetres, Z up, centred on the part's footprint, bottom at z = 0, length along X"


def _checks(kind: str, d: dict) -> list[dict]:
    """What the test measures in the GLB against the recorded numbers, per type."""

    tol = lambda v: round(max(0.25, 0.02 * v), 3)  # noqa: E731
    out: list[dict] = []
    if kind == "brushless_motor":
        out.append({"check": "extent", "nodes": ["bell"], "axes": "xy", "expect": [d["diameter_mm"], d["diameter_mm"]], "tol": tol(d["diameter_mm"])})
        out.append({"check": "extent", "nodes": ["base", "bell", "shaft", "stator", "magnets", "mount_hole", "prop_nut", "prop_hole"], "axes": "z", "expect": [d["height_mm"]], "tol": tol(d["height_mm"])})
        out.append({"check": "bolt_circle", "nodes": ["mount_hole_"], "count": int(d["bolts"]), "diameter": d["bolt_circle_mm"], "tol": 0.1})
    elif kind == "propeller":
        out.append({"check": "rotor_diameter", "nodes": ["blade_"], "count": int(d["blades"]), "diameter": d["diameter_mm"], "tol": tol(d["diameter_mm"])})
        if "hub_h_mm" in d:
            out.append({"check": "extent", "nodes": ["hub"], "axes": "z", "expect": [d["hub_h_mm"]], "tol": 0.2})
    elif kind == "lipo_pack":
        nodes = ["body", "connector"] if d.get("length_includes_connector") or d.get("end_cap") else ["body"]
        out.append({"check": "extent", "nodes": nodes, "axes": "xyz", "expect": [d["length_mm"], d["width_mm"], max(d["height_mm"], 0)], "tol": tol(d["length_mm"])})
    elif kind == "board":
        out.append({"check": "extent", "nodes": ["board"], "axes": "xy", "expect": [d["length_mm"], d["width_mm"]], "tol": tol(d["length_mm"])})
        if d.get("holes"):
            out.append({"check": "holes", "nodes": ["hole_"], "expect": [[h[0], h[1]] for h in d["holes"]], "tol": 0.15})
        if d.get("height_mm"):
            out.append({"check": "extent", "nodes": None, "axes": "z", "expect": [d["height_mm"]], "tol": max(0.5, 0.08 * d["height_mm"])})
        if isinstance(d.get("connector_positions"), dict):
            # Each connector or pad named in the drawing sits where the drawing puts it.
            for name, (x, y) in d["connector_positions"].items():
                out.append({"check": "centre", "nodes": [name], "expect": [x, y], "tol": 0.2})
    elif kind == "servo":
        out.append({"check": "extent", "nodes": ["body", "body_top"], "axes": "xy", "expect": [d["length_mm"], d["width_mm"]], "tol": 0.3})
        if "overall_height_mm" in d:
            out.append({"check": "extent", "nodes": ["body", "tabs", "body_top", "gear_tower", "spline", "horn"], "axes": "z", "expect": [d["overall_height_mm"]], "tol": 0.3})
        else:
            out.append({"check": "extent", "nodes": ["body", "tabs", "body_top", "gear_tower", "spline"], "axes": "z", "expect": [d["spline_top_mm"]], "tol": 0.3})
        if "case_height_mm" in d:
            out.append({"check": "extent", "nodes": ["body", "tabs", "body_top"], "axes": "z", "expect": [d["case_height_mm"]], "tol": 0.3})
        out.append({"check": "extent", "nodes": ["tabs"], "axes": "x", "expect": [d["tab_span_mm"]], "tol": 0.3})
        out.append({"check": "min_z", "nodes": ["tabs"], "expect": d["tab_bottom_mm"], "tol": 0.2})
        if "hole_spacing_mm" in d:
            s = d["hole_spacing_mm"] / 2
            ys = [-d["hole_pitch_y_mm"] / 2, d["hole_pitch_y_mm"] / 2] if d.get("hole_pitch_y_mm") else [0]
            out.append({"check": "holes", "nodes": ["mount_hole_"], "expect": [[sx * s, y] for sx in (-1, 1) for y in ys], "tol": 0.15})
    elif kind == "vtx":
        out.append({"check": "extent", "nodes": ["board"], "axes": "xy", "expect": [d["length_mm"], d["width_mm"]], "tol": tol(d["length_mm"])})
        out.append({"check": "extent", "nodes": ["board", "rf_shield", "ufl", "led", "pad", "mount_hole"], "axes": "z", "expect": [d["height_mm"]], "tol": 0.3})
        if d.get("mount_mm"):
            s = d["mount_mm"] / 2
            out.append({"check": "holes", "nodes": ["mount_hole_"], "expect": [[s, s], [-s, s], [-s, -s], [s, -s]], "tol": 0.1})
    elif kind == "fpv_camera":
        out.append({"check": "extent", "nodes": ["body", "lens", "rear_board", "cable_socket"], "axes": "xyz", "expect": [d["length_mm"], d["width_mm"], d["height_mm"]], "tol": 0.3})
    elif kind == "ball_caster":
        out.append({"check": "extent", "nodes": None, "axes": "z", "expect": [d["height_mm"]], "tol": 0.3})
        out.append({"check": "extent", "nodes": ["ball"], "axes": "z", "expect": [d["ball_mm"]], "tol": 0.2})
        s = d["hole_spacing_mm"] / 2
        out.append({"check": "holes", "nodes": ["mount_hole_"], "expect": [[-s, 0], [s, 0]], "tol": 0.1})
        if "length_mm" in d and "width_mm" in d:
            out.append({"check": "extent", "nodes": ["body"], "axes": "xy", "expect": [d["length_mm"], d["width_mm"]], "tol": 0.3})
    elif kind == "tt_motor":
        out.append({"check": "extent", "nodes": ["body", "motor_can"], "axes": "xyz", "expect": [d["length_mm"], d["width_mm"], d["height_mm"]], "tol": 1.0})
    elif kind == "insert":
        out.append({"check": "extent", "nodes": ["body"], "axes": "xyz", "expect": [d["outer_mm"], d["outer_mm"], d["length_mm"]], "tol": 0.1})
    elif kind == "canopy":
        # The camera window opens the front, so its length is checked loosely.
        out.append({"check": "extent", "nodes": ["shell"], "axes": "yz", "expect": [d["width_mm"], d["height_mm"]], "tol": 0.3})
        out.append({"check": "extent", "nodes": ["shell"], "axes": "x", "expect": [d["length_mm"]], "tol": 1.5})
    elif kind == "coil":
        out.append({"check": "extent", "nodes": ["loop_"], "axes": "xy", "expect": [d["coil_d_mm"] + d["cord_d_mm"], d["coil_d_mm"] + d["cord_d_mm"]], "tol": 0.5})
    elif kind == "rocker_switch":
        out.append({"check": "extent", "nodes": ["bezel"], "axes": "xy", "expect": [d["length_mm"], d["width_mm"]], "tol": 0.2})
    elif kind == "cell_pack" and not d.get("shrink") and not d.get("holder"):
        out.append({"check": "extent", "nodes": ["cell_"], "axes": "xyz", "expect": [d["cell_len_mm"], d["cells"] * d["cell_d_mm"], d["cell_d_mm"]], "tol": 0.3})
    elif kind in ("whoop_frame",):
        out.append({"check": "extent", "nodes": ["frame_duct"], "axes": "xyz", "expect": d["size_mm"], "tol": 0.6})
        out.append({"check": "motor_spacing", "nodes": ["motor_mount_"], "wheelbase": d["wheelbase_mm"], "tol": 0.3})
    elif kind == "carbon_frame":
        out.append({"check": "motor_spacing", "nodes": ["motor_mount_"], "wheelbase": d["wheelbase_mm"], "tol": 0.3})
    elif kind == "stepper":
        out.append({"check": "extent", "nodes": ["body", "end_cap"], "axes": "xyz", "expect": [d["face_mm"], d["face_mm"], d["length_mm"]], "tol": 0.3})
        s = d["hole_spacing_mm"] / 2
        out.append({"check": "holes", "nodes": ["mount_hole_"], "expect": [[s, s], [-s, s], [-s, -s], [s, -s]], "tol": 0.1})
    elif kind == "wheel":
        out.append({"check": "extent", "nodes": ["tyre"], "axes": "xyz", "expect": [d["diameter_mm"], d["diameter_mm"], d["width_mm"]], "tol": tol(d["diameter_mm"])})
    elif kind == "bearing":
        out.append({"check": "extent", "nodes": ["outer_ring"], "axes": "xyz", "expect": [d["outer_mm"], d["outer_mm"], d["width_mm"]], "tol": 0.1})
        out.append({"check": "bore", "nodes": ["inner_ring"], "diameter": d["bore_mm"], "tol": 0.1})
    elif kind == "fan":
        out.append({"check": "extent", "nodes": ["body"], "axes": "xyz", "expect": [d["size_mm"], d["size_mm"], d["thickness_mm"]], "tol": 0.3})
        s = d["hole_spacing_mm"] / 2
        out.append({"check": "holes", "nodes": ["mount_hole_"], "expect": [[s, s], [-s, s], [-s, -s], [s, -s]], "tol": 0.1})
    elif kind == "cell":
        out.append({"check": "extent", "nodes": None, "axes": "xyz", "expect": [d["length_mm"], d["diameter_mm"], d["diameter_mm"]], "tol": 0.3})
    elif kind in ("round_gearmotor",):
        out.append({"check": "extent", "nodes": ["gearbox"], "axes": "xy", "expect": [d["diameter_mm"], d["diameter_mm"]], "tol": 0.3})
        out.append({"check": "extent", "nodes": ["body", "gearbox", "encoder"], "axes": "z", "expect": [d["length_mm"]], "tol": tol(d["length_mm"])})
        if "face_hole_circle_mm" in d:
            out.append({"check": "bolt_circle", "nodes": ["mount_hole_"], "count": int(d.get("face_holes", 2)), "diameter": d["face_hole_circle_mm"], "tol": 0.1})
    elif kind == "micro_gearmotor":
        out.append({"check": "extent", "nodes": ["body", "gearbox_plates"], "axes": "xyz", "expect": [d["length_mm"], d["width_mm"], d["height_mm"]], "tol": 0.3})
    elif kind in ("screw",):
        out.append({"check": "extent", "nodes": ["shank"], "axes": "xyz", "expect": [d["thread_mm"], d["thread_mm"], d["length_mm"]], "tol": 0.1})
        out.append({"check": "extent", "nodes": ["head"], "axes": "xy", "expect": [d["head_d_mm"], d["head_d_mm"]], "tol": 0.1})
    elif kind in ("disc",):
        out.append({"check": "extent", "nodes": ["body"], "axes": "xyz", "expect": [d["diameter_mm"], d["diameter_mm"], d["height_mm"]], "tol": tol(d["diameter_mm"])})
    elif kind in ("can_stepper",):
        out.append({"check": "extent", "nodes": ["body"], "axes": "xy", "expect": [d["diameter_mm"], d["diameter_mm"]], "tol": 0.3})
        out.append({"check": "holes", "nodes": ["mount_hole_"], "expect": [[-d["ear_spacing_mm"] / 2, 0], [d["ear_spacing_mm"] / 2, 0]], "tol": 0.1})
    elif all(k in d for k in ("length_mm", "width_mm", "height_mm")):
        out.append({"check": "extent", "nodes": ["body"], "axes": "xyz", "expect": [d["length_mm"], d["width_mm"], d["height_mm"]], "tol": tol(max(d["length_mm"], d["width_mm"]))})
        if kind == "enclosure" and "overall_height_mm" in d:
            out.append({"check": "extent", "nodes": None, "axes": "z", "expect": [d["overall_height_mm"]], "tol": 0.3})
        if kind == "wall_adapter" and d.get("plug_base_h_mm"):
            # Body, the plug's housing and the 19 mm Europlug pins, end to end.
            out.append({"check": "extent", "nodes": ["body", "plug_base", "plug_pin_"], "axes": "z", "expect": [d["height_mm"] + d["plug_base_h_mm"] + 19.0], "tol": 0.3})
    return out


def _official_step(official: dict) -> Path:
    """The official STEP: kept in the repository when small, else fetched once into the cache."""

    kept = OFFICIAL_DIR / official["file"]
    if kept.exists():
        return kept
    cached = OFFICIAL_CACHE / official["file"]
    if not cached.exists():
        from urllib.request import urlopen

        cached.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(official["download"], timeout=120) as response:
            cached.write_bytes(response.read())
    return cached


def _value(entry):
    return entry["value"] if isinstance(entry, dict) and "value" in entry else entry


def build_part(part_id: str, spec: dict, write_step: bool = False, glb_path: Path | None = None) -> dict:
    """Build one part's model and return its manifest entry (a web find's GLB goes to glb_path)."""

    kind = spec["type"]
    dims = {name: _value(v) for name, v in spec.get("dims", {}).items()}
    params = {"id": part_id, **spec.get("style", {}), **spec.get("estimate", {}), **dims}
    glb_path = glb_path or WEB_DIR / f"{part_id}.glb"
    entry: dict = {
        "id": part_id,
        "name": spec["name"],
        "catalogs": spec.get("catalogs", []),
        "category": spec.get("category"),
        "generator": kind,
        "glb": f"models/parts/{part_id}.glb" if glb_path.parent == WEB_DIR else str(glb_path),
        "step": None,
        "frame": FRAME,
        "source_url": spec.get("source"),
        "checked": spec.get("checked", date.today().isoformat()),
    }
    if kind == "official":
        official = spec["official"]
        step = Path(official["path"]) if official.get("path") else _official_step(official)
        model = official_model({"id": part_id, **official}, step)
        entry.update(kind="official", author=official["author"], license=official["license"], model_url=official["url"])
        if step.parent == OFFICIAL_DIR and glb_path.parent == WEB_DIR:
            entry["step"] = str(step.relative_to(REPO_ROOT))
        info = model.write(glb_path, tolerance=official.get("tolerance"))
        missing: list[str] = []
    else:
        model = GENERATORS[kind](params)
        model.rest_on_floor()
        step_path = STEP_DIR / f"{part_id}.step" if write_step else None
        info = model.write(glb_path, step_path)
        if step_path is not None:
            entry["step"] = str(step_path.relative_to(REPO_ROOT))
        required = KEY_DIMS.get(kind, [])
        alternative = ALTERNATIVES.get(kind, {})
        missing = [name for name in required if name not in dims and alternative.get(name) not in dims and name not in spec.get("not_applicable", [])]
        missing += [name for name in spec.get("missing", []) if name not in missing]
        entry.update(kind="approximate" if missing else "look-alike", author="AnyBuild look-alike generator", license="same as this repository")
    entry["dims"] = {
        name: (
            {"value": _value(v), "source": v.get("source", spec.get("source")), **{k: v[k] for k in ("checked", "how") if k in v}}
            if isinstance(v, dict)
            else {"value": v, "source": spec.get("source")}
        )
        for name, v in spec.get("dims", {}).items()
    }
    entry["missing"] = missing
    entry["estimated"] = sorted(spec.get("estimate", {}))
    entry["styled"] = sorted(k for k in spec.get("style", {}) if k not in ("color",))
    if kind == "official":
        entry["checks"] = spec.get("checks", [])
    else:
        try:
            # Measured numbers win; an approximate part is checked against its recorded estimates.
            entry["checks"] = _checks(kind, {**spec.get("style", {}), **spec.get("estimate", {}), **dims})
        except KeyError:
            entry["checks"] = []
    entry["bbox_mm"] = info["bbox_mm"]
    entry["bytes"] = info["bytes"]
    if spec.get("note"):
        entry["note"] = spec["note"]
    return entry


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="comma-separated part ids")
    parser.add_argument("--step", action="store_true", help="also write look-alike STEP files")
    args = parser.parse_args(argv)
    sources = json.loads(SOURCES_PATH.read_text())["parts"]
    manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {"parts": {}}
    only = set(args.only.split(",")) if args.only else None
    for part_id, spec in sources.items():
        if only and part_id not in only:
            continue
        try:
            entry = build_part(part_id, spec, args.step)
        except Exception as error:  # report and go on: one broken part must not stop the set
            print(f"FAILED {part_id}: {error!r}")
            continue
        manifest["parts"][part_id] = entry
        print(f"{entry['kind']:12} {part_id:40} {entry['bytes'] / 1024:7.1f} KB  bbox {entry['bbox_mm']}  missing {entry['missing']}")
    manifest["parts"] = {k: manifest["parts"][k] for k in sources if k in manifest["parts"]}
    manifest["frame"] = FRAME
    manifest["note"] = (
        "One entry per library part. kind is official (a manufacturer or library model, license given), "
        "look-alike (built from the measured numbers in dims, each with its source) or approximate "
        "(built, but the numbers in missing were not found in any real source)."
    )
    counts = {}
    for entry in manifest["parts"].values():
        counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
    manifest["counts"] = counts
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    total = sum(path.stat().st_size for path in WEB_DIR.glob("*.glb"))
    print(f"{len(manifest['parts'])} models {counts}, {total / 1e6:.1f} MB of GLB")


if __name__ == "__main__":
    main()
