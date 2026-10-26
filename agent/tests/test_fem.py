"""The FEM checks itself: the cantilever against beam theory, a part that is not held named by its free
motion, the reactions balancing the loads, a peak that depends on the mesh, the watchdog on CalculiX,
and loads spread over the CAD faces by area. The tests marked needs_fem run gmsh and CalculiX (they
ship with FreeCAD); the rest run on a small structured mesh and need neither. No network, no keys."""

import time
from pathlib import Path

import numpy as np
import pytest

from pai_agent import fem
from pai_agent.tools import fem as fem_tool

needs_fem = pytest.mark.skipif(fem.find_tools() is None, reason="gmsh and CalculiX (FreeCAD's FEM tools) are not installed")
PROPS = {"modulus_mpa": 2000.0, "poisson": 0.35, "strength_mpa": 40.0, "z_strength_mpa": 20.0}


def box_mesh(size=(4.0, 2.0, 1.0), cells=(4, 2, 1), origin=(0.0, 0.0, 0.0)) -> fem.Mesh:
    """A structured C3D10 mesh of a box, each cell six tetrahedra round its diagonal, faces numbered 1 to 6 as x-, x+, y-, y+, z-, z+."""

    counts = [c + 1 for c in cells]
    axes = [np.linspace(o, o + s, n) for o, s, n in zip(origin, size, counts)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    cube = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    corners = []
    for i in range(cells[0]):
        for j in range(cells[1]):
            for k in range(cells[2]):
                v = [((i + a) * counts[1] + j + b) * counts[2] + k + c for a, b, c in cube]
                for split in [(0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6), (0, 5, 1, 6)]:
                    tet = [v[n] for n in split]
                    p = grid[tet]
                    if np.linalg.det(np.stack([p[1] - p[0], p[2] - p[0], p[3] - p[0]])) < 0:
                        tet[1], tet[2] = tet[2], tet[1]
                    corners.append(tet)
    nodes = list(grid)
    mids: dict[tuple[int, int], int] = {}

    def mid(a: int, b: int) -> int:
        key = (min(a, b), max(a, b))
        if key not in mids:
            mids[key] = len(nodes)
            nodes.append((grid[a] + grid[b]) / 2)
        return mids[key]

    tets = np.array([[a, b, c, d, mid(a, b), mid(b, c), mid(c, a), mid(a, d), mid(b, d), mid(c, d)] for a, b, c, d in corners])
    xyz = np.array(nodes)
    tris, _ = fem._boundary(tets, {})
    p = xyz[tris[:, :3]]
    normal = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    axis = np.argmax(np.abs(normal), axis=1)
    faces = 1 + 2 * axis + (normal[np.arange(len(axis)), axis] > 0)
    return fem.Mesh(xyz, tets, tris, faces.astype(np.int64), min(s / c for s, c in zip(size, cells)))


def _beam(tmp_path: Path, name: str = "beam.step", length: float = 100.0) -> Path:
    import cadquery as cq

    step = tmp_path / name
    cq.exporters.export(cq.Workplane().box(length, 10, 10, centered=False), str(step))
    return step


# --- on the structured mesh: no gmsh, no CalculiX ---


def test_a_force_spreads_over_the_face_by_area():
    mesh = box_mesh()
    top = fem.resolve(mesh, {"face_id": 6}, 1.0)
    assert top.where == "face 6 (8 mm²)"
    load = fem.force_load(mesh, top, [0, 0, -12.0])
    assert load.sum(axis=0) == pytest.approx([0, 0, -12.0])
    # Six-node triangles under an even traction: nothing on the corners, a third of each triangle's share on each mid-side node.
    corner_nodes = np.unique(mesh.tets[:, :4])
    assert np.abs(load[corner_nodes]).max() < 1e-12
    weights, _ = fem.surface_integrals(mesh, top.tris)
    assert weights[:, 3:] == pytest.approx(np.repeat(mesh.areas(top.tris)[:, None] / 3, 3, axis=1))
    # The resultant acts at the centre of the face: no moment about it.
    moment = np.cross(mesh.nodes - [2.0, 1.0, 1.0], load).sum(axis=0)
    assert np.abs(moment).max() < 1e-9


def test_pressure_pushes_along_the_normals_and_weight_loads_the_volume():
    mesh = box_mesh()
    side = fem.resolve(mesh, {"face": "x_max"}, 1.0)
    assert fem.pressure_load(mesh, side, 0.5).sum(axis=0) == pytest.approx([-0.5 * 2.0, 0, 0])
    every = fem.Region(np.arange(len(mesh.nodes)), np.arange(len(mesh.tris)), "all")
    # A closed surface under one pressure has no resultant.
    assert np.abs(fem.pressure_load(mesh, every, 2.0).sum(axis=0)).max() < 1e-9
    weight = fem.weight_load(mesh, 1.25, 2.0)
    assert weight.sum(axis=0) == pytest.approx([0, 0, -8.0 * 1.25 * fem.WEIGHT_N_MM3 * 2.0])
    # The consistent loads of a ten-node tetrahedron: corners push up, mid-side nodes carry the weight.
    assert (weight[np.unique(mesh.tets[:, :4]), 2] > 0).all() and (weight[np.unique(mesh.tets[:, 4:]), 2] < 0).all()


def test_regions_pick_cad_faces_sides_patches_and_boxes():
    mesh = box_mesh()
    assert set(mesh.face_ids[fem.resolve(mesh, {"face": "z_min"}, 1.0).tris]) == {5}
    patch = fem.resolve(mesh, {"near": [2.0, 1.0, 1.0], "radius_mm": 0.6}, 1.0)
    assert set(mesh.face_ids[patch.tris]) == {6} and patch.where.startswith("a 0.6 mm patch round (2.0, 1.0, 1.0) on face 6")
    # A point in the air above the part takes the patch round the nearest point of the surface.
    above = fem.resolve(mesh, {"near": [0.5, 0.5, 30.0], "radius_mm": 0.5}, 1.0)
    assert set(mesh.face_ids[above.tris]) <= {1, 3, 6} and 6 in set(mesh.face_ids[above.tris])
    boxed = fem.resolve(mesh, {"box": [-1, -1, -1, 1.01, 3, 2]}, 1.0)
    assert (mesh.nodes[boxed.nodes][:, 0] <= 1.01).all() and set(mesh.face_ids[boxed.tris]) == {1, 3, 4, 5, 6}
    with pytest.raises(ValueError, match="no outer face 9"):
        fem.resolve(mesh, {"face_id": 9}, 1.0)


def test_free_motions_name_what_the_supports_leave_free():
    square = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0]], dtype=float)
    every = np.ones((4, 3), dtype=bool)
    assert fem.free_motions(square, every) == []
    # The axis is named through its point nearest the middle of the held nodes.
    line = np.array([[0, 5, 2], [4, 5, 2], [11, 5, 2]], dtype=float)
    assert fem.free_motions(line, np.ones((3, 3), dtype=bool)) == ["turn about an axis along X through (5.0, 5.0, 2.0) mm"]
    assert fem.free_motions(np.array([[1.0, 2.0, 3.0]]), np.ones((1, 3), dtype=bool)) == ["turn in any direction about (1.0, 2.0, 3.0) mm"]
    # Resting on a table without friction: held only along Z.
    table = np.zeros((4, 3), dtype=bool)
    table[:, 2] = True
    assert fem.free_motions(square, table) == ["slide along X and Y", "turn about an axis along Z"]
    assert fem.free_motions(square, np.zeros((4, 3), dtype=bool)) == ["move and turn freely, since nothing holds it"]


def test_hold_check_stops_a_loaded_loose_body_and_leaves_out_an_idle_one():
    one = box_mesh()
    two = box_mesh(origin=(10.0, 0.0, 0.0))
    joined = fem.Mesh(
        np.concatenate([one.nodes, two.nodes]),
        np.concatenate([one.tets, two.tets + len(one.nodes)]),
        np.concatenate([one.tris, two.tris + len(one.nodes)]),
        np.concatenate([one.face_ids, two.face_ids + 6]),
        1.0,
    )
    cases = [{"name": "far end", "region": {"face_id": 8}, "force_n": [0, 0, -1.0]}]
    with pytest.raises(fem.FemUnheld) as unheld:
        fem.prepare(joined, [{"face_id": 1}], cases, PROPS, 1.0)
    assert str(unheld.value).startswith("Body 2 of 2, round (12.0, 1.0, 0.5) mm, is not held: it can move and turn freely")
    assert unheld.value.motions == ["move and turn freely, since nothing holds it"]
    model = fem.prepare(joined, [{"face_id": 1}], [{"name": "near end", "region": {"face_id": 2}, "force_n": [0, 0, -1.0]}], PROPS, 1.0)
    assert model.left_out == ["Body 2 of 2, round (12.0, 1.0, 0.5) mm, is not held and carries no load, so it is left out."]
    assert len(model.mesh.nodes) == len(one.nodes) and model.loads[0].shape == (len(one.nodes), 3)
    # Held along one edge only: the part turns about that edge.
    with pytest.raises(fem.FemUnheld, match="turn about an axis along Y through"):
        fem.prepare(one, [{"box": [-0.1, -1, -0.1, 0.1, 3, 0.1]}], [{"name": "top", "region": {"face_id": 6}, "force_n": [0, 0, -1.0]}], PROPS, 1.0)


def test_balance_reports_load_that_lands_on_held_nodes():
    mesh = box_mesh()
    # The bottom face touches the clamped end, so part of an even load on it goes straight into the support.
    model = fem.prepare(mesh, [{"face_id": 1}], [{"name": "bottom", "region": {"face_id": 5}, "force_n": [0, 0, -8.0]}], PROPS, 1.0)
    carried = np.where(model.held, 0.0, model.loads[0]).sum(axis=0)
    balance = fem._balance(model, 0, -carried)
    assert balance["ok"] and balance["error_pct"] == 0.0
    assert 0 < balance["on_held_pct"] < 20 and balance["on_held_n"][2] < 0
    assert balance["reaction_n"][2] - balance["on_held_n"][2] == pytest.approx(8.0)
    assert not fem._balance(model, 0, -carried * 0.99)["ok"]
    # The part's own weight on its held face is expected there and does not count as load that misses the part.
    weighed = fem.prepare(mesh, [{"face_id": 5}], [{"name": "weight", "gravity_g": 1.0}], {**PROPS, "density_g_cm3": 1.0}, 1.0)
    assert weighed.held_shares == [0.0] and np.abs(np.where(weighed.held, weighed.loads[0], 0.0)).sum() > 0


def _fake_ccx(tmp_path: Path, body: str) -> str:
    script = tmp_path / "ccx"
    script.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def test_watchdog_stops_a_runaway_displacement_and_an_error_at_once(tmp_path):
    env = {"PATH": "/usr/bin:/bin"}
    runaway = _fake_ccx(tmp_path, 'echo " iteration 1"\necho " largest increment of disp= 1.000000e+00"\necho " largest increment of disp= 2.765642e+09"\nsleep 30')
    started = time.monotonic()
    with pytest.raises(fem.FemFailed, match="ran away past 10 times the part's size"):
        fem.run_ccx(runaway, tmp_path, env, 100.0)
    assert time.monotonic() - started < 10
    broken = _fake_ccx(tmp_path, 'echo " *ERROR in e_c3d: nonpositive jacobian"\nsleep 30')
    started = time.monotonic()
    with pytest.raises(fem.FemFailed, match="nonpositive jacobian"):
        fem.run_ccx(broken, tmp_path, env, 100.0)
    assert time.monotonic() - started < 10
    silent = _fake_ccx(tmp_path, "sleep 30")
    with pytest.raises(fem.FemFailed, match="ran past 1 s"):
        fem.run_ccx(silent, tmp_path, env, 100.0, timeout_s=1.0)
    calm = _fake_ccx(tmp_path, 'echo " largest increment of disp= 2.0e+00"\necho " Job finished"')
    assert fem.run_ccx(calm, tmp_path, env, 100.0) == (0, " largest increment of disp= 2.0e+00\n Job finished\n")


def test_the_tool_takes_face_ids_pressure_and_its_own_weight():
    assert fem_tool._clean_region({"face_id": 7}) == {"face_id": [7]}
    with pytest.raises(ValueError, match="face_id is a face number"):
        fem_tool._clean_region({"face_id": [2.5]})
    with pytest.raises(ValueError, match="radius_mm must be more than 0"):
        fem_tool._clean_region({"near": [0, 0, 0], "radius_mm": -3})
    cases = fem_tool._clean_cases(
        [
            {"name": "shelf", "region": {"face_id": [3, 4]}, "force_n": [0, 0, -19.6]},
            {"name": "water", "loads": [{"region": {"face": "z_min"}, "pressure_mpa": 0.005}], "gravity_g": 1},
        ]
    )
    assert cases == [
        {"name": "shelf", "loads": [{"region": {"face_id": [3, 4]}, "force_n": [0.0, 0.0, -19.6]}]},
        {"name": "water", "loads": [{"region": {"face": "z_min"}, "pressure_mpa": 0.005}], "gravity_g": 1.0},
    ]
    with pytest.raises(ValueError, match="needs a force_n"):
        fem_tool._clean_cases([{"name": "nothing"}])


def test_a_peak_that_moves_with_the_mesh_is_told_only_near_the_limit():
    mesh = {"ok": False, "element_size_mm": 1.0, "change_pct": 17.0, "text": "Mesh check: the peak depends on the mesh."}
    result = {"safety": 2.6, "notes": [mesh["text"]], "checks": {"equilibrium": {"error_pct": 0.0}, "mesh": mesh}}
    notes, line = fem_tool._findings(result, 2.0)
    assert notes == [mesh["text"]] and line.endswith("the peak moves 17 % with 1 mm elements round it, so it depends on the mesh.")
    # 40x against 2x: no refinement turns that verdict, so the note stays in the checks only.
    notes, line = fem_tool._findings({**result, "safety": 40.0}, 2.0)
    assert notes == [] and line.endswith("but the part is far stronger than it needs either way.")
    settled = {**mesh, "ok": True, "change_pct": 3.0}
    assert fem_tool._findings({**result, "notes": [], "checks": {**result["checks"], "mesh": settled}}, 2.0)[1].endswith("round it.")


# --- gmsh and CalculiX ---


@needs_fem
def test_cantilever_matches_beam_theory_and_checks_itself(tmp_path):
    length, side, force = 100.0, 10.0, 10.0
    result = fem.analyse(_beam(tmp_path), None, PROPS, {"face": "x_min"}, [{"name": "tip", "region": {"face": "x_max"}, "force_n": [0, 0, -force]}], [0, 0, 1], tmp_path / "w", 3.0, tmp_path / "beam.glb")
    case = result["cases"][0]
    inertia = side**4 / 12
    # delta = F L^3 / (3 E I) and sigma = F L c / I at the root.
    assert case["max_deflection_mm"] == pytest.approx(force * length**3 / (3 * PROPS["modulus_mpa"] * inertia), rel=0.03)
    assert case["max_von_mises_mpa"] == pytest.approx(force * length * side / 2 / inertia, rel=0.05)
    assert case["safety_in_plane"] == pytest.approx(40.0 / case["max_von_mises_mpa"], rel=0.01)
    # Held on the root face, loaded on the tip face: the faces of the STEP, by area.
    assert result["held"] == "face 1 (100 mm²)" and case["loads"][0]["where"] == "10.0 N on face 2 (100 mm²)"
    assert case["equilibrium"]["error_pct"] < 0.1 and case["equilibrium"]["reaction_n"] == pytest.approx([0, 0, force], abs=1e-3)
    assert result["checks"]["mesh"]["ok"] is True and result["notes"] == []
    assert (tmp_path / "beam.glb").read_bytes()[:4] == b"glTF"


@needs_fem
def test_fem_judges_tension_across_layers_with_the_interlayer_strength(tmp_path):
    props = {**PROPS, "z_strength_mpa": 10.0}
    # Printed upright along X: the bending stress runs across the layers.
    upright = fem.analyse(_beam(tmp_path), None, props, {"face": "x_min"}, [{"name": "tip", "region": {"face": "x_max"}, "force_n": [0, 0, -10]}], [1, 0, 0], tmp_path / "w", 3.0, mesh_check=False)
    case = upright["cases"][0]
    assert case["governs"] == "layers"
    assert case["safety"] < case["safety_in_plane"]


@needs_fem
def test_a_part_held_on_an_edge_is_named_by_its_free_motion(tmp_path):
    started = time.monotonic()
    with pytest.raises(fem.FemUnheld) as unheld:
        fem.analyse(_beam(tmp_path), None, PROPS, {"box": [-1, -1, -1, 0.1, 11, 0.1]}, [{"name": "tip", "region": {"face": "x_max"}, "force_n": [0, 0, -10]}], [0, 0, 1], tmp_path / "w", 3.0)
    assert str(unheld.value) == (
        "The part is not held: it can turn about an axis along Y through (0.0, 5.0, 0.0) mm. "
        "Hold it on a face with some area (a whole face, or a near patch with radius_mm), not along a line or at a point."
    )
    # Caught before CalculiX runs: no solve, no runaway displacement of 1e11 mm.
    assert not (tmp_path / "w" / "case0").exists() and time.monotonic() - started < 60


@needs_fem
def test_pressure_and_self_weight_balance_the_reactions(tmp_path):
    props = {**PROPS, "density_g_cm3": 1.25, "fill": 0.8}
    cases = [{"name": "water and weight", "loads": [{"region": {"face": "z_max"}, "pressure_mpa": 0.01}], "gravity_g": 1.0}]
    result = fem.analyse(_beam(tmp_path), None, props, {"face": "x_min"}, cases, [0, 0, 1], tmp_path / "w", 3.0, mesh_check=False)
    case = result["cases"][0]
    weight = 100 * 10 * 10 * 1.25 * 0.8 * fem.WEIGHT_N_MM3
    assert case["force_n"][2] == pytest.approx(-(0.01 * 1000 + weight), abs=0.01)
    assert [row["where"] for row in case["loads"]] == ["0.01 MPa on face 6 (1000 mm²)", "its own weight at 1 g"]
    # Whatever lands on the clamped face goes straight into the support; the rest the reactions balance.
    balance = case["equilibrium"]
    assert balance["error_pct"] < 0.1
    assert balance["on_held_n"][2] < 0
    assert balance["reaction_n"][2] - balance["on_held_n"][2] == pytest.approx(0.01 * 1000 + weight, rel=1e-3)


@needs_fem
def test_mesh_check_flags_a_sharp_inside_corner_but_not_a_rounded_one(tmp_path):
    import cadquery as cq

    def stepped(fillet: float) -> Path:
        shape = cq.Workplane().box(30, 10, 10, centered=False).union(cq.Workplane().box(70, 10, 5, centered=False).translate((30, 0, 0)))
        if fillet:
            shape = shape.edges("|Y").edges(cq.selectors.NearestToPointSelector((30, 5, 5))).fillet(fillet)
        step = tmp_path / f"stepped-{fillet:g}.step"
        cq.exporters.export(shape, str(step))
        return step

    cases = [{"name": "tip", "region": {"face": "x_max"}, "force_n": [0, 0, -5]}]
    sharp = fem.analyse(stepped(0), None, PROPS, {"face": "x_min"}, cases, [1, 0, 0], tmp_path / "w", 2.0)
    assert sharp["checks"]["mesh"]["ok"] is False and sharp["checks"]["mesh"]["change_pct"] > 15
    assert sharp["notes"] == [sharp["checks"]["mesh"]["text"]] and "sharp corner" in sharp["notes"][0]
    rounded = fem.analyse(stepped(3.0), None, PROPS, {"face": "x_min"}, cases, [1, 0, 0], tmp_path / "w", 2.0)
    assert rounded["checks"]["mesh"]["ok"] is True and rounded["notes"] == []


@needs_fem
def test_face_ids_follow_the_step(tmp_path):
    gmsh, _ccx = fem.find_tools()
    mesh = fem.mesh(_beam(tmp_path), tmp_path / "w", 3.0, gmsh)
    centres = {int(f): mesh.nodes[mesh.tris[mesh.face_ids == f, :3]].reshape(-1, 3).mean(axis=0) for f in np.unique(mesh.face_ids)}
    # OpenCASCADE numbers a box's faces x-, x+, y-, y+, z-, z+, as FreeCAD's Face1 to Face6.
    assert sorted(centres) == [1, 2, 3, 4, 5, 6]
    assert centres[1][0] == pytest.approx(0) and centres[2][0] == pytest.approx(100) and centres[6][2] == pytest.approx(10)
