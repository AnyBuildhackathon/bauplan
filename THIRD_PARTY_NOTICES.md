# Third-Party Notices

AnyBuild ships 3D models of real drone parts made by other people.
They are used under the licenses below.
This file lists every third-party model in the repository, where it came from, who made it, and its license.

## Part models in `agent/freecad/parts/`

`agent/freecad/frame_build.py` loads these meshes and places them in the reference micro drone at real size.
The files in the repository are exactly what was downloaded.
For the browser GLB only, the build thins the canopy mesh (FreeCAD `Mesh.decimate`); the shape stays the same.

| File | Part | Author | Source | License |
| --- | --- | --- | --- | --- |
| `toothpick-canopy-14mm_271232.stl` | Toothpick canopy for a 14 mm nano camera, with antenna tube, on a 26 x 26 mm stack | DLQFPV | [Printables 271232](https://www.printables.com/model/271232-toothpick-whoop-14mm-camera-canopy-antenna-fpv) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `caddx-ant-lite-rough-model_721095.stl` | Caddx Ant Lite nano camera, 14 x 14 mm. It stands in for the Caddx Ant, which has the same body. | Youfu | [Printables 721095](https://www.printables.com/model/721095-caddx-ant-lite-rough-3d-model) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

The canopy model is attributed to DLQFPV as CC BY 4.0 requires.
In the generated `frame.glb` and the renders, it is thinned and placed in an assembly.
The camera model is in the public domain.

## Parts remodeled from published dimensions

No openly licensed model exists for the following parts, so `agent/freecad/frame_build.py` models them parametrically from the manufacturers' published dimensions and from product photos:

- Twiglet 2" carbon frame: 2 mm plate, 26 x 26 mm stack, 1103 motor pads with a 6.6 mm bolt circle, weighed at carbon-plate density (5.2 g against the 5.3 g listing).
- 1103 15000KV motor: 14 mm bell, 11 mm stator with 12 wound teeth, 1.5 mm shaft, three M1.4 bolts.
- Gemfan 2020 four-blade propeller: 51 mm, 2.0 inch pitch, 1.5 mm shaft.
- BetaFPV Matrix 1S 5IN1 V2 AIO board: 26 x 26 mm mount, standoffs, chips, passives and pads.
- The battery holder, the 1S pack, the strap, the wiring and the antenna.

We searched Printables, GitHub, the manufacturers' pages and the open web for these parts on 2026-10-24.
Thingiverse, GrabCAD and MakerWorld refused automated access, so we could not search them.
The candidates we found were the wrong part (a BetaFPV 0802SE motor, generic three-blade 2-inch props, printable plastic frames) or had a license that does not allow redistribution (CC BY-NC and CC BY-NC-SA).
