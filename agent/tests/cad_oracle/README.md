# CAD reference tests

Reference parts built through every CAD path AnyBuild has, whose exported files are measured on their own and compared with what they must measure.
Each part is built by the code a real build runs: the FreeCAD harness for the part scripts Mechanic writes, the library template and the reference builds' scripts, the standard parts from `pai_agent.fasteners`, headless FreeCAD's drone frame, the CadQuery fallbacks, and SolidCraft.
The STEP is read back with OpenCASCADE and measured on its exact geometry, the STL with numpy, the GLB from its binary chunk.
The idea and the form of the test come from SolidCraft's reference parts (`docs/oracle.md`, MIT); no code was taken.

## Running

```bash
cd agent && uv run --with pytest pytest tests/test_cad_oracle.py
cd agent && uv run python tests/cad_oracle/run.py                 # one line per part, then every failed check
cd agent && uv run python tests/cad_oracle/run.py spur-gear --all-rows
cd agent && uv run python tests/cad_oracle/run.py --record        # store measured values where a part has no formula
cd agent && uv run python tests/cad_oracle/run.py --keep /tmp/oracle   # keep the built files
```

Both need no network and no key.
Parts that need FreeCAD skip without `freecadcmd`, SolidCraft parts without `solidcraft-cli` 0.23.0 (`bash agent/scripts/setup_solidcraft.sh`); the standard parts and the CadQuery fallbacks run everywhere.
The parts build in worker processes, four at a time (`CAD_ORACLE_JOBS` or `--jobs` changes that), the drone frame's 16 s FreeCAD build first; the whole suite takes about 20 s, more on a busy machine.

## The parts

| Part | Built by | Values from |
| --- | --- | --- |
| `plate-holes` | a script as Mechanic writes it, with `PARAMS` | formulas |
| `plate-counterbore` | script: holes cut at two depths | formulas |
| `l-bracket` | script: two fused boxes, vertical and horizontal holes | formulas |
| `gusset` | script: an extruded polygon face with a hole | formulas |
| `stepped-shaft` | script: cylinders, a cone chamfer, a blind bore | formulas |
| `flanged-bushing` | script | formulas |
| `spur-gear` | script: an involute gear as a 324-point polygon | formulas (the polygon's own area and centroid) |
| `fillet-block` | script: `makeFillet` on four edges | formulas |
| `o-ring` | script: a torus in TPU | formulas |
| `enclosure-inserts` | script plus four M3 heat-set inserts the harness cuts in | formulas |
| `lid-screws` | script plus four ISO 4762 M3x8 screws in ISO 273 clearance holes | formulas |
| `gripper-template` | the FreeCAD library's gripper template | formulas for palm, gears, pads and servo; mirror symmetry and records for the fingers |
| `phone-stand-base` | the phone stand reference build's script | formulas |
| `phone-stand-back-rest` | the phone stand reference build's script | recorded |
| `screw-iso4762-m3x10`, `nut-iso4032-m3`, `washer-iso7089-m3`, `insert-m3x4` | `pai_agent.fasteners` | formulas from the standards' sizes; the nut's area recorded |
| `fallback-block` | `run_block`, the CadQuery stand-in without FreeCAD, with a screw's hole | formulas |
| `drone-frame` | `drone_assembly.write_frame`, the drone's carbon plate from the CadQuery fallback | formulas for box, centre, holes; volume and area recorded |
| `hero-frame` | `freecad_run.build_with_freecad`: headless FreeCAD builds the whole drone, `frame.step` and `frame.stl` are its plate | formulas for box and holes; volume, area and centre recorded |
| `solidcraft-plate` | SolidCraft: the same plate as `plate-holes` | the same formulas |
| `solidcraft-four-bar` | SolidCraft library: the Chebyshev four-bar | recorded |
| `solidcraft-gripper` | SolidCraft library: the two-finger gripper | formulas per body |

## What every part is checked for

- The STEP declares mm, its shape is valid (BRepCheck), every shell is closed (no free or badly oriented edge), and every solid belongs to a body of the build.
- Its solids, volume, surface area, centre of mass and bounding box, and the volume its bodies share, against the formulas or the record.
- The volume, bounding box, centre of mass and mass AnyBuild reports against the exact solid, and the mass against the material's density.
- The STL a slicer gets holds exactly the printed bodies' triangles, every body is watertight (no open, overused or flipped edge, no degenerate triangle, facing out) and the genus matches: one per through hole.
- Its bounding box, volume, area and centre of mass against the exact solid, within what the exporter's deflection allows; a mesh in metres or inches is far outside, which is the unit check.
- Per body the same against its own formula or record, its STL against its solid, its node in the GLB against its STL.
- Mirror pairs: one body is the other mirrored across x = 0.

## Tolerances

- Exact solids against a formula or a record: 1e-6 of the volume or area (plus 0.001), 0.1 um for a length, 0.01 mm3 of shared volume.
- AnyBuild's reported numbers: their rounding (0.01 mm3, 0.001 mm, 0.01 g); SolidCraft's own measure also 0.05 %, since it measures its triangulation and comes out about 0.012 % low on cylinders.
- An STL against its solid: the volume within the curved area times the linear deflection, the area within the curved area times 1 - cos(angular deflection), the bounding box inside the solid's and at most the linear deflection short of it, the centre of mass within the volume tolerance over the volume times the diagonal.
- The deflections are the writers' own: the FreeCAD harness meshes to max(0.02, diagonal / 800) mm and 0.35 rad, `frame_build.py` to 0.03 mm and 0.3 rad, CadQuery's exporter defaults to 0.1 mm and 0.1 rad, standard parts to 0.02 mm and 0.2 rad; SolidCraft does not say, comes out within 0.002 mm and is allowed 0.02.

## Adding a reference part

1. Write its build in `parts.py`: a part script (`PARAMS`, then `P[...]`, then `shape` or `parts`) for `build.freecad`, a standard part entry for `build.standard_part`, a SolidCraft command script for `build.solidcraft`; a new CAD path gets a builder in `build.py` that runs the real code and returns an `Output` with the files and the numbers AnyBuild reported.
2. Write what it must measure as an `Expect`: volume, area, centre of mass, bounding box, solids, genus, the shared volume (0 for parts that print and fit separately) and the mass with the material's density; per body in `bodies`, mirror pairs in `mirrored`.
   Leave out a value whose formula would only restate the script in a more error-prone way; it is recorded instead.
3. Add a `Reference` to `REFERENCES` with its name, what it covers and what it needs (`"freecad"`, `"solidcraft"` or `None`); `slow=True` starts a build of many seconds first.
4. Run `uv run python tests/cad_oracle/run.py <name> --all-rows` and read every row, then `--record` and review the diff of `recorded.json`.
5. A check that fails because of a real defect nobody fixes yet goes into the part's `known` with what is wrong; it then reports without failing, and fails once the defect is gone, so the entry goes with the fix.

`test_every_reference_part_has_its_values` fails when a part has neither a formula nor a record for one of its values.

## What it caught

Fixed with the suite:

- The FreeCAD harness reported each part's bounding box after meshing it, so `BoundBox` was the triangulation's and fell up to the deflection short of the part on curved faces: the flanged bushing at x = -9.979 instead of -10, the o-ring at 13.973 instead of 14, the gripper's fingers at y = -4.495 instead of -4.5.
  The error grows with the part, up to its diagonal / 800 (1.25 mm for a 1 m diagonal), and the box's centre is the point the assembly places a part by, MuJoCo's collision boxes and inertias come from it, and FEM places and orients the part with it.
  `part_harness.py` now takes `optimalBoundingBox(False, False)`, the exact one; before meshing `BoundBox` is no better (a torus of 14 mm came out 15.15).
- Standard parts reported CadQuery's `BoundingBox()`, which on a shape meshed for its STL is the triangulation's enlarged box: an M3x10 screw at [-2.8456, -2.8482, -10.0067, 2.8491, 2.8482, 3.0091] instead of [-2.84, -2.84, -10, 2.84, 2.84, 3].
  `hardware.row_of` now measures the exact box.

Open, listed as known defects:

- `agent/freecad/library/gripper.py` (locked): the two gears cut 6.8 mm3 into each other where they mesh, in four flank contacts of 1.7 mm3 next to the pitch point.
  Their teeth are rectangles 2.4 mm wide (1.6 modules) in gaps of 2.3 mm at the pitch circle, so the printed gears bind; Mechanic is shown this template as the example of a part script.
- `agent/solidcraft/library/two-finger-gripper.json`: 1184 mm3 of its bodies overlap.
  Each finger's root bar overlaps its gear (146 mm3) and its finger bar (320 mm3), and the axles run through the palm plate and through gears that have no bore; SolidCraft's measure, and with it the build's mass and the URDF link masses, counts that volume twice: 4.5 % of the gripper, 10 % of a finger.

Observed and accepted:

- SolidCraft's four-bar from its own examples draws its pins through the links they join (799 mm3 recorded); its links' masses are right, since no link's own bodies overlap.
- `frame_build.py` asks for a 0.45 mm fillet on the hero frame's 103 top edges, which FreeCAD 1.1.4 refuses (`BRep_API: command not done`); `_try_fillet` then keeps the plate unrounded, as recorded (its centre of mass sits at half the thickness). A fillet that works shows up as a changed record.
