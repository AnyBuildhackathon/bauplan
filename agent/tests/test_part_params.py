"""The parameter contract of a part script: PARAMS, the harness that holds a script to it, the sliders it gives the
CAD tab, and the user's values, which stay when Mechanic rebuilds or rewrites the part.

Run with: cd agent && uv run --with pytest pytest tests/test_part_params.py
No network and no keys. The FreeCAD tests skip without freecadcmd; the rest build with CadQuery standing in for it.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest

from pai_agent import part_params, versions
from pai_agent.bus import EventBus
from pai_agent.cad_script import PartBuild, ScriptFailed, density, run_script
from pai_agent.context import Ctx
from pai_agent.freecad_run import find_freecadcmd
from pai_agent.mesh_export import stls_to_glb
from pai_agent.part_params import ParamsError
from pai_agent.paths import SESSIONS_DIR
from pai_agent.session import Session
from pai_agent.state import BuildState
from pai_agent.tools import cad_part as cad_part_module
from pai_agent.tools.registry import call_tool

needs_freecad = pytest.mark.skipif(find_freecadcmd() is None, reason="freecadcmd is not installed")

BOX = '''PARAMS = {
    "width_mm": {"value": 60.0, "min": 30.0, "max": 120.0, "step": 1.0, "unit": "mm", "label": "Width", "group": "Body"},
    "depth_mm": {"value": 40.0, "min": 20.0, "max": 80.0, "step": 0.5, "label": "Depth", "group": "Body"},
    "height_mm": {"value": 20.0, "min": 10.0, "max": 40.0, "label": "Height", "group": "Body"},
    "holes": {"type": "integer", "value": 2, "min": 0, "max": 4, "label": "Holes", "group": "Holes"},
    "hole_mm": {"value": 4.0, "min": 2.0, "max": 8.0, "step": 0.5, "label": "Hole diameter", "group": "Holes"},
    "chamfer": {"value": False, "label": "Chamfered top", "group": "Finish"},
    "mount": {"value": "flat", "options": ["flat", "wall"], "label": "Mount", "group": "Finish"},
}
W, D, H = P["width_mm"], P["depth_mm"], P["height_mm"]
body = Part.makeBox(W, D, H, Vector(-W / 2, -D / 2, 0))
for i in range(P["holes"]):
    x = -W / 2 + W * (i + 1) / (P["holes"] + 1)
    body = body.cut(Part.makeCylinder(P["hole_mm"] / 2, H + 2, Vector(x, 0, -1)))
if P["chamfer"]:
    body = body.makeChamfer(1.0, [e for e in body.Edges if e.BoundBox.ZMin > H - 0.01])
if P["mount"] == "wall":
    body = body.fuse(Part.makeBox(W, 3, H + 20, Vector(-W / 2, D / 2, 0)))
shape = body
'''
SPEC = {
    "name": "Sensor box",
    "function": "A small box that holds a sensor on the desk.",
    "quote": "a sensor box under 20 euros",
    "requirements": [{"text": "Costs under 20 euros", "check": "cost", "max": 20, "unit": "eur", "quote": "under 20 euros"}],
    "parts": [
        {
            "id": "box", "name": "Box", "kind": "printed", "material": "PLA", "size_mm": [60, 40, 20],
            "description": "A box 60 x 40 x 20 mm with two holes through it, standing on Z = 0.",
            "params": {"width_mm": 60, "depth_mm": 40, "height_mm": 20},
        },
    ],
}


def _entry(**spec) -> dict:
    return part_params.check({"x_mm": spec})["x_mm"]


# The declaration


def test_a_declaration_fills_in_each_parameter_with_its_type_unit_step_and_label():
    entries, raw = part_params.declaration(BOX)
    assert list(entries) == ["width_mm", "depth_mm", "height_mm", "holes", "hole_mm", "chamfer", "mount"]
    assert entries["width_mm"] == {"type": "number", "value": 60.0, "min": 30.0, "max": 120.0, "step": 1.0, "unit": "mm", "label": "Width", "group": "Body"}
    # Unit from the name, the step the CAD tab would pick for a 30 mm span.
    assert (entries["height_mm"]["unit"], entries["height_mm"]["step"]) == ("mm", 0.5)
    assert entries["holes"] == {"type": "integer", "value": 2, "min": 0, "max": 4, "step": 1, "unit": "", "label": "Holes", "group": "Holes"}
    assert entries["chamfer"] == {"type": "switch", "value": False, "label": "Chamfered top", "group": "Finish"}
    assert entries["mount"] == {"type": "choice", "value": "flat", "options": ["flat", "wall"], "label": "Mount", "group": "Finish"}
    assert raw["depth_mm"]["step"] == 0.5
    # Without a label, the name is one; without a group, it has none.
    assert part_params.check({"lip_height_mm": {"value": 12, "min": 6, "max": 25}})["lip_height_mm"]["label"] == "Lip height"
    assert part_params.check({"angle_deg": {"value": 65, "min": 45, "max": 80}})["angle_deg"]["group"] is None


def test_every_problem_of_a_declaration_comes_back_at_once():
    with pytest.raises(ParamsError) as caught:
        part_params.check(
            {
                "Width": {"value": 1, "min": 0, "max": 2},
                "depth_mm": {"value": 90.0, "min": 20.0, "max": 80.0},
                "height_mm": {"value": 20.0},
                "wall_mm": {"value": 2.0, "min": 1.0, "max": 4.0, "steps": 0.2},
                "holes": {"type": "integer", "value": 2.5, "min": 0, "max": 4},
                "mount": {"value": "shelf", "options": ["flat", "wall"]},
                "vents": {"type": "switch", "value": 1},
                "slot_mm": {"value": 3.0, "min": 1.0, "max": 5.0, "step": 0.0},
            }
        )
    problems = caught.value.problems
    assert len(problems) == 8, problems
    assert "PARAMS['Width']: the name must be snake_case like width_mm." in problems
    assert "PARAMS['depth_mm']: value 90 must lie between min and max." in problems
    assert "PARAMS['height_mm']: give min and max, the range in which the part still builds and makes sense." in problems
    assert "PARAMS['wall_mm']: a number takes group, label, max, min, step, type, unit, value; not steps." in problems
    assert "PARAMS['holes']: value must be whole numbers." in problems
    assert "PARAMS['mount']: value must be one of its options." in problems
    assert "PARAMS['vents']: a switch's value is True or False." in problems
    assert "PARAMS['slot_mm']: step must be above 0 and at most max - min." in problems


def test_params_is_plain_data_assigned_once_and_every_parameter_is_read():
    with pytest.raises(ParamsError, match="PARAMS must be plain data"):
        part_params.declaration('W0 = 60.0\nPARAMS = {"width_mm": {"value": W0, "min": 30.0, "max": 120.0}}\nshape = P["width_mm"]\n')
    with pytest.raises(ParamsError, match="Assign PARAMS once, at the top level"):
        part_params.declaration('PARAMS = {}\nPARAMS["width_mm"] = {"value": 60.0}\n')
    with pytest.raises(ParamsError, match="Assign PARAMS once, at the top level"):
        part_params.declaration('if True:\n    PARAMS = {}\n')
    with pytest.raises(ParamsError) as caught:
        part_params.declaration('PARAMS = {"width_mm": {"value": 60.0, "min": 30.0, "max": 120.0}, "lip_mm": {"value": 5.0, "min": 1.0, "max": 9.0}}\nW = P["width_mm"]\n')
    assert caught.value.problems == ["PARAMS declares lip_mm, but the script never reads P['lip_mm']; read it with its name written out, or remove it."]
    # A script from before the contract declares nothing; a syntax error is the sandbox check's to report.
    assert part_params.declaration('W = P.get("width_mm", 60.0)\nshape = Part.makeBox(W, 10, 10)\n') is None
    assert part_params.declaration("PARAMS = {\n") is None


# Resolving the values


def test_values_come_from_the_default_then_mechanic_then_the_user():
    entries, _raw = part_params.declaration(BOX)
    resolved = part_params.resolve(entries, {"depth_mm": 50.0, "holes": 3.0, "width_mm": 140.0}, {"width_mm": 75, "mount": "wall"})
    assert resolved.values == {"width_mm": 75.0, "depth_mm": 50.0, "height_mm": 20.0, "holes": 3, "hole_mm": 4.0, "chamfer": False, "mount": "wall"}
    # A count is a whole number in P, so range() takes it.
    assert isinstance(resolved.values["holes"], int)
    # Mechanic's 140 mm widened the range for this build; the user's 75 mm won over it.
    assert (resolved.entries["width_mm"]["min"], resolved.entries["width_mm"]["max"]) == (30.0, 140.0)
    assert resolved.user == {"width_mm": 75.0, "mount": "wall"}
    assert resolved.overridden == {"width_mm": 140.0}
    assert resolved.dropped == {}


def test_a_user_value_that_no_longer_fits_is_dropped_with_the_reason():
    entries, _raw = part_params.declaration(BOX)
    resolved = part_params.resolve(entries, {}, {"width_mm": 150.0, "mount": "ceiling", "lip_mm": 4.0, "holes": 2.5, "chamfer": True})
    assert resolved.user == {"chamfer": True}
    assert resolved.dropped == {
        "width_mm": "width_mm must be between 30 and 120.",
        "mount": "mount must be one of flat, wall.",
        "lip_mm": "the part has no parameter lip_mm any more",
        "holes": "holes must be a whole number.",
    }
    assert resolved.values["width_mm"] == 60.0


def test_mechanics_values_must_have_their_parameters_type():
    entries, _raw = part_params.declaration(BOX)
    with pytest.raises(ParamsError) as caught:
        part_params.resolve(entries, {"chamfer": 1.0, "mount": "shelf", "holes": 1.5, "lid_mm": 2.0}, {})
    assert caught.value.problems == [
        "chamfer is a switch: true or false.",
        "mount must be one of flat, wall.",
        "holes must be a whole number.",
        "lid_mm is not declared in PARAMS; declare every parameter of the request (declared: width_mm, depth_mm, height_mm, holes, hole_mm, chamfer, mount).",
    ]


def test_the_payload_is_what_the_cad_tab_shows():
    entries, _raw = part_params.declaration(BOX)
    rows = part_params.payload(entries, {"width_mm": 75.0})
    assert rows["width_mm"] == {"type": "number", "value": 75.0, "label": "Width", "group": "Body", "min": 30.0, "max": 120.0, "step": 1.0, "unit": "mm"}
    assert rows["chamfer"] == {"type": "switch", "value": False, "label": "Chamfered top", "group": "Finish"}
    assert rows["mount"] == {"type": "choice", "value": "flat", "label": "Mount", "group": "Finish", "options": ["flat", "wall"]}
    assert part_params.coerce("depth_mm", rows["width_mm"], "52.5") == 52.5


def test_the_gripper_template_declares_its_parameters_with_labels_and_steps():
    entries = cad_part_module.template_params("gripper")
    assert entries["finger_length_mm"] == {
        "type": "number", "value": 70.0, "min": 45.0, "max": 110.0, "step": 1.0, "unit": "mm", "label": "Finger length", "group": "Fingers",
    }
    assert [entries[k]["step"] for k in ("finger_thickness_mm", "pad_thickness_mm")] == [0.5, 0.5]


# The flows, with CadQuery standing in for freecadcmd


class Bus:
    def __init__(self):
        self.events: list[dict] = []

    async def publish(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def session_dir():
    """A session folder inside the repository, where builds keep their files relative to it, removed afterwards."""

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="test-part-params-", dir=SESSIONS_DIR))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def builds(monkeypatch):
    """CadQuery builds a box of P's width, depth and height where freecadcmd would run the script; each call records P and the contract."""

    calls: list[dict] = []

    def build(source, params, out_dir, stem, material="PLA", expected_mm=None, fasteners=None, contract=None):
        import cadquery as cq

        calls.append({"params": dict(params), "contract": contract, "source": source})
        width, depth, height = (float(params.get(key, 10.0)) for key in ("width_mm", "depth_mm", "height_mm"))
        shape = cq.Workplane("XY").box(width, depth, height, centered=(True, True, False))
        solid = shape.val()
        box = solid.BoundingBox()
        bbox = [box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax]
        out_dir.mkdir(parents=True, exist_ok=True)
        stl, step, glb, piece = (out_dir / (stem + ext) for ext in (".stl", ".step", ".glb", "-0.stl"))
        for path in (stl, step, piece):
            cq.exporters.export(shape, str(path))
        stls_to_glb([(stem, piece, None)], glb)
        (out_dir / (stem + ".py")).write_text(source, encoding="utf-8")
        mass = round(solid.Volume() / 1000.0 * density(material), 2)
        row = {"name": "Part", "bbox_mm": bbox, "volume_mm3": solid.Volume(), "stl": piece.name, "material": material.upper(), "mass_g": mass, "reference": False}
        return PartBuild(parts=[row], bbox_mm=bbox, volume_mm3=solid.Volume(), mass_g=mass, stl=stl, step=step, glb=glb), False

    monkeypatch.setattr(cad_part_module, "run_script_cached", build)
    monkeypatch.setattr(cad_part_module, "freecad_unavailable", lambda error: False)
    return calls


def _ctx(directory: Path) -> Ctx:
    state = BuildState(session_id=directory.name, directory=directory)
    state.requests.append(SPEC["quote"])
    return Ctx(Bus(), state, auto_steps=False)


def _run(ctx: Ctx, name: str, args: dict) -> dict:
    return asyncio.run(call_tool(ctx, name, args))


def _session(ctx: Ctx) -> Session:
    """A bench around the context's state, so a slider goes through the same path as POST /api/cad/params."""

    session = Session()
    shutil.rmtree(session.state.directory, ignore_errors=True)
    session.state = ctx.state
    session.bus = ctx.bus
    return session


def _cad(ctx: Ctx, assembly: bool) -> dict:
    return [event for event in ctx.bus.events if event.get("type") == "cad" and bool(event.get("assembly")) == assembly][-1]


def test_a_script_with_params_builds_its_defaults_and_shows_its_sliders(builds, session_dir):
    ctx = _ctx(session_dir)
    result = _run(ctx, "cad_part", {"name": "Sensor box", "script": BOX})
    assert result["ok"], result
    assert result["params"] == {"width_mm": 60.0, "depth_mm": 40.0, "height_mm": 20.0, "holes": 2, "hole_mm": 4.0, "chamfer": False, "mount": "flat"}
    assert "user_values" not in result
    # The harness gets PARAMS as written, to hold the script to it.
    assert builds[-1]["contract"]["width_mm"]["label"] == "Width" and builds[-1]["params"] == result["params"]
    sliders = _cad(ctx, assembly=False)["params"]
    assert sliders["depth_mm"] == {"type": "number", "value": 40.0, "label": "Depth", "group": "Body", "min": 20.0, "max": 80.0, "step": 0.5, "unit": "mm"}
    assert sliders["mount"]["options"] == ["flat", "wall"]
    assert ctx.state.part["declared"] is True


def test_a_script_that_breaks_its_params_never_reaches_freecad(builds, session_dir):
    ctx = _ctx(session_dir)
    broken = BOX.replace('"min": 30.0, "max": 120.0', '"min": 130.0, "max": 120.0')
    result = _run(ctx, "cad_part", {"name": "Sensor box", "script": broken})
    assert result["ok"] is False
    assert result["problems"] == ["PARAMS['width_mm']: min must be below max."]
    assert builds == []


def test_a_slider_value_is_the_users_and_stays_when_mechanic_rewrites_the_part(builds, session_dir):
    ctx = _ctx(session_dir)
    assert _run(ctx, "product_spec", SPEC)["ok"]
    assert _run(ctx, "cad_part", {"part_id": "box", "script": BOX})["ok"]
    session = _session(ctx)

    # The user drags the width and flips the mount: both are theirs now, and the box is built with them.
    moved = asyncio.run(session.update_params({"box.width_mm": 75, "box.mount": "wall"}))
    assert moved["ok"] is not False, moved
    assert ctx.state.user_params == {"box": {"width_mm": 75.0, "mount": "wall"}}
    assert (builds[-1]["params"]["width_mm"], builds[-1]["params"]["mount"]) == (75.0, "wall")
    assembly = _cad(ctx, assembly=True)["params"]
    assert assembly["box.width_mm"]["label"] == "Box · Width" and assembly["box.width_mm"]["value"] == 75.0
    assert assembly["box.mount"] == {"type": "choice", "value": "wall", "label": "Box · Mount", "group": "Finish", "options": ["flat", "wall"]}

    # Mechanic rewrites the part with the spec's numbers: the user's width and mount stay, and the result says so.
    rewritten = _run(ctx, "cad_part", {"part_id": "box", "script": BOX.replace("Part.makeBox(W, D, H", "Part.makeBox(W, D, H + 0")})
    assert rewritten["ok"], rewritten
    assert builds[-1]["params"]["width_mm"] == 75.0
    assert rewritten["user_values"] == {"width_mm": 75.0, "mount": "wall"}
    assert rewritten["overridden_by_user"] == {"width_mm": 60.0}
    assert "replace_user_values" in rewritten["user_values_note"]
    assert ctx.state.built["box"]["params"]["width_mm"] == 75.0

    # A spec revision with the old numbers keeps them too, and lists what the user set.
    revised = _run(ctx, "product_spec", {**SPEC, "parts": [{**SPEC["parts"][0], "params": {**SPEC["parts"][0]["params"], "height_mm": 25}}]})
    assert revised["ok"], revised
    assert revised["rebuilt_with_new_params"] == ["box"]
    assert revised["user_values"] == {"box.width_mm": 75.0, "box.mount": "wall"}
    assert revised["overridden_by_user"] == {"box.width_mm": 60}
    assert (builds[-1]["params"]["width_mm"], builds[-1]["params"]["height_mm"]) == (75.0, 25.0)


def test_mechanic_changes_a_user_value_only_when_the_user_asked(builds, session_dir):
    ctx = _ctx(session_dir)
    assert _run(ctx, "product_spec", SPEC)["ok"]
    assert _run(ctx, "cad_part", {"part_id": "box", "script": BOX})["ok"]
    assert asyncio.run(_session(ctx).update_params({"name": "box.width_mm", "value": 75}))["ok"] is not False
    count = len(builds)

    refused = _run(ctx, "cad_update", {"part_id": "box", "params": {"width_mm": 90}})
    assert refused["ok"] is False
    assert refused["error"] == (
        "The user set width_mm 75 with the CAD sliders. Change it only when the user asks for a new value; "
        'then call cad_update again with replace_user_values ["width_mm"].'
    )
    assert len(builds) == count

    # Other parameters change as before; the user's width stays.
    deeper = _run(ctx, "cad_update", {"part_id": "box", "params": {"depth_mm": 50}})
    assert deeper["ok"], deeper
    assert (builds[-1]["params"]["width_mm"], builds[-1]["params"]["depth_mm"]) == (75.0, 50.0)
    assert deeper["user_values"] == {"width_mm": 75.0}

    # The user asked for 90 mm: Mechanic takes the width over, and it is Mechanic's from then on.
    taken = _run(ctx, "cad_update", {"part_id": "box", "params": {"width_mm": 90}, "replace_user_values": ["width_mm"]})
    assert taken["ok"], taken
    assert builds[-1]["params"]["width_mm"] == 90.0
    assert ctx.state.user_params == {}
    assert "user_values" not in taken

    # A switch takes true or false, a choice one of its options.
    wrong = _run(ctx, "cad_update", {"part_id": "box", "params": {"chamfer": "yes"}})
    assert (wrong["ok"], wrong["error"]) == (False, "chamfer is a switch: true or false.")
    assert _run(ctx, "cad_update", {"part_id": "box", "params": {"chamfer": True}})["detail"] == "Box: chamfer on"


def test_a_slider_outside_its_range_or_of_the_wrong_kind_is_refused(builds, session_dir):
    ctx = _ctx(session_dir)
    assert _run(ctx, "product_spec", SPEC)["ok"]
    assert _run(ctx, "cad_part", {"part_id": "box", "script": BOX})["ok"]
    session = _session(ctx)
    count = len(builds)
    assert asyncio.run(session.update_params({"box.width_mm": 200}))["error"] == "box.width_mm must be between 30 and 120."
    assert asyncio.run(session.update_params({"box.mount": "ceiling"}))["error"] == "box.mount must be one of flat, wall."
    assert asyncio.run(session.update_params({"box.holes": 1.5}))["error"] == "box.holes must be a whole number."
    assert (len(builds), ctx.state.user_params) == (count, {})


def test_a_rewrite_whose_range_leaves_out_the_users_value_drops_it_and_says_why(builds, session_dir):
    ctx = _ctx(session_dir)
    assert _run(ctx, "product_spec", SPEC)["ok"]
    assert _run(ctx, "cad_part", {"part_id": "box", "script": BOX})["ok"]
    assert asyncio.run(_session(ctx).update_params({"box.width_mm": 110, "box.depth_mm": 30}))["ok"] is not False
    narrower = BOX.replace('"min": 30.0, "max": 120.0', '"min": 30.0, "max": 90.0')
    result = _run(ctx, "cad_part", {"part_id": "box", "script": narrower})
    assert result["ok"], result
    assert result["dropped_user_values"] == {"width_mm": "width_mm must be between 30 and 90."}
    assert "tell the user" in result["dropped_note"]
    assert result["user_values"] == {"depth_mm": 30.0}
    assert ctx.state.user_params == {"box": {"depth_mm": 30.0}}
    assert builds[-1]["params"]["width_mm"] == 60.0


def test_a_new_product_starts_without_the_users_values_and_a_restore_brings_them_back(builds, session_dir, monkeypatch):
    ctx = _ctx(session_dir)
    assert _run(ctx, "product_spec", SPEC)["ok"]
    assert _run(ctx, "cad_part", {"part_id": "box", "script": BOX})["ok"]
    assert asyncio.run(_session(ctx).update_params({"box.width_mm": 75}))["ok"] is not False
    version = asyncio.run(versions.commit(ctx, label="Sensor box"))
    assert version["params"]["box.width_mm"] == 75.0 and version["params"]["box.mount"] == "flat"
    assert ctx.state.version_files[1]["user_params"] == {"box": {"width_mm": 75.0}}

    other = {**SPEC, "name": "Pen cup", "parts": [{**SPEC["parts"][0], "id": "cup", "name": "Cup"}]}
    assert _run(ctx, "product_spec", other)["ok"]
    assert ctx.state.user_params == {}

    # Restoring v1 makes the width the user's again; nothing renders or prices here.
    async def quiet(ctx, args):
        return {"ok": True}

    from pai_agent.tools import registry

    for name in ("blender_render", "bom_build"):
        monkeypatch.setitem(registry.TOOLS, name, quiet)
    asyncio.run(versions.restore(ctx, 1))
    assert ctx.state.user_params == {"box": {"width_mm": 75.0}}
    assert builds[-1]["params"]["width_mm"] == 75.0


def test_switches_and_choices_show_as_text_in_a_versions_difference():
    rows = versions.diff({"params": {"box.chamfer": False, "box.mount": "flat", "box.width_mm": 60.0}}, {"product": "generic", "params": {"box.chamfer": True, "box.mount": "wall", "box.width_mm": 75.0}})
    assert rows == [
        {"key": "param:box.chamfer", "label": "Box chamfer", "before": "off", "after": "on", "unit": ""},
        {"key": "param:box.mount", "label": "Box mount", "before": "flat", "after": "wall", "unit": ""},
        {"key": "param:box.width_mm", "label": "Box width", "before": 60.0, "after": 75.0, "unit": "mm"},
    ]


def test_the_gripper_template_keeps_a_finger_the_user_set_until_a_fix_they_picked_replaces_it(builds, session_dir):
    ctx = _ctx(session_dir)
    ctx.state.product = "gripper"
    gripper = {"name": "Robot gripper", "template": "gripper", "description": "Two-finger gear gripper", "material": "PLA", "params": {"jaw_opening_mm": 60}}
    assert _run(ctx, "cad_part", gripper)["ok"]
    sliders = _cad(ctx, assembly=False)["params"]
    assert sliders["finger_length_mm"]["label"] == "Finger length" and sliders["jaw_opening_mm"]["value"] == 60.0
    assert asyncio.run(_session(ctx).update_params({"finger_length_mm": 85}))["ok"] is not False
    assert ctx.state.user_params == {"robot-gripper": {"finger_length_mm": 85.0}}

    # Mechanic builds it again with its own numbers: the user's 85 mm stays.
    again = _run(ctx, "cad_part", {**gripper, "params": {"jaw_opening_mm": 60, "finger_length_mm": 70}})
    assert again["overridden_by_user"] == {"finger_length_mm": 70.0}
    assert builds[-1]["params"]["finger_length_mm"] == 85.0
    # The fix the user picked replaces it.
    fixed = _run(ctx, "cad_part", {**gripper, "params": {"jaw_opening_mm": 60, "finger_length_mm": 75}, "replace_user_values": ["finger_length_mm"]})
    assert fixed["ok"] and builds[-1]["params"]["finger_length_mm"] == 75.0
    assert ctx.state.user_params == {}


# The harness, with freecadcmd


@needs_freecad
def test_the_harness_fails_a_script_that_reads_a_parameter_it_does_not_declare(tmp_path):
    script = 'PARAMS = {"width_mm": {"value": 20.0, "min": 10.0, "max": 40.0}}\nW = P["width_mm"]\nD = P.get("depth_mm", 10.0)\nshape = Part.makeBox(W, D, 5)\n'
    entries, raw = part_params.declaration(script)
    with pytest.raises(ScriptFailed) as caught:
        run_script(script, {"width_mm": 20.0}, tmp_path, "part-x", contract=raw)
    assert str(caught.value).startswith(
        "UndeclaredParameter: depth_mm is not declared in PARAMS; declare every parameter the script reads from P. (part_script.py line 3)"
    )
    # The same script without the contract reads P as before, with its default.
    assert run_script(script, {"width_mm": 20.0}, tmp_path, "part-y").bbox_mm[4] == pytest.approx(10.0)


@needs_freecad
def test_the_harness_fails_a_script_that_changes_params_while_it_runs(tmp_path):
    script = 'PARAMS = {"width_mm": {"value": 20.0, "min": 10.0, "max": 40.0}}\nPARAMS.update({"x": 1})\nshape = Part.makeBox(P["width_mm"], 5, 5)\n'
    _entries, raw = part_params.declaration(script)
    with pytest.raises(ScriptFailed, match="PARAMS changed while the script ran"):
        run_script(script, {"width_mm": 20.0}, tmp_path, "part-x", contract=raw)


@needs_freecad
def test_freecad_builds_a_switch_a_choice_and_a_count_from_params(monkeypatch, tmp_path, session_dir):
    monkeypatch.setattr("pai_agent.cache.CACHE_DIR", tmp_path / "cache")
    ctx = _ctx(session_dir)
    plain = _run(ctx, "cad_part", {"name": "Sensor box", "script": BOX})
    assert plain["ok"], plain
    session = _session(ctx)
    assert asyncio.run(session.update_params({"mount": "wall", "holes": 4}))["ok"] is not False
    walled = ctx.state.part
    assert (walled["params"]["mount"], walled["params"]["holes"]) == ("wall", 4)
    # The wall plate makes it 20 mm taller, and two more holes take material out.
    assert walled["bbox_mm"][5] == pytest.approx(plain["bbox_mm"][5] + 20.0)
    assert ctx.state.user_params == {"sensor-box": {"mount": "wall", "holes": 4}}


@needs_freecad
def test_freecad_keeps_the_users_width_when_mechanic_rewrites_the_part(monkeypatch, tmp_path, session_dir):
    """The whole story on the real harness: a slider, a rewritten script, a refused change and the one the user asked for."""

    monkeypatch.setattr("pai_agent.cache.CACHE_DIR", tmp_path / "cache")
    ctx = _ctx(session_dir)
    assert _run(ctx, "product_spec", SPEC)["ok"]
    assert _run(ctx, "cad_part", {"part_id": "box", "script": BOX})["ok"]
    assert asyncio.run(_session(ctx).update_params({"box.width_mm": 90}))["ok"] is not False

    def width() -> float:
        box = ctx.state.built["box"]["bbox_mm"]
        return box[3] - box[0]

    assert width() == pytest.approx(90.0)
    # Mechanic writes the part again, two holes more: the user's 90 mm stay.
    rewritten = _run(ctx, "cad_part", {"part_id": "box", "script": BOX.replace('"value": 2, "min": 0', '"value": 4, "min": 0')})
    assert rewritten["ok"], rewritten
    assert (width(), rewritten["params"]["holes"], rewritten["user_values"]) == (pytest.approx(90.0), 4, {"width_mm": 90.0})
    assert _run(ctx, "cad_update", {"part_id": "box", "params": {"width_mm": 70}})["ok"] is False
    assert _run(ctx, "cad_update", {"part_id": "box", "params": {"width_mm": 70}, "replace_user_values": ["width_mm"]})["ok"]
    assert width() == pytest.approx(70.0) and ctx.state.user_params == {}
