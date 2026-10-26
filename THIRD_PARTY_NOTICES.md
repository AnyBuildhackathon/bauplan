# Third-Party Notices

AnyBuild's own code and assets are MIT licensed (see [LICENSE](LICENSE)).
This file lists everything in the repository that other people made, where it came from, who made it, and its license, plus how the generated media were made.
It was checked against every image, video, audio file and 3D model tracked in git on 2026-10-24.

## Adapted source code

Four chat components in `web/src/components/chat/` (`SidebarChat.tsx`, `SidebarChatInput.tsx`, `SidebarChatMessage.tsx`, `ContentPartsRenderer.tsx`) are adapted from [core-oss](https://github.com/10xapp/core-oss) under the Apache License 2.0.
Each file starts with a header naming its origin and stating that it was modified.
The changes and the full Apache License 2.0 text are in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES).

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

## NVIDIA SimReady objects

AnyBuild can put real objects from NVIDIA's SimReady assets into a scene (`scene_object`, see [docs/events.md](docs/events.md#object)).
They are the packages of the Hugging Face dataset [nvidia/simready-assets](https://huggingface.co/datasets/nvidia/simready-assets) at revision `524747d9b5e1f21b5b18b56041788c01d745f1a1`, made by NVIDIA and licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Each package declares that license in its `com.nvidia.simready.packaging.json` and ships the license text.
No package is stored in this repository: the backend downloads a package when it is first used, refuses any package whose license is not CC-BY-4.0, and keeps it in a cache outside the repository.
`agent/data/simready/index.json` lists every package of that revision with facts read from its metadata (name, Wikidata class, size, mass) and the hash of its thumbnail; it is derived from the dataset and carries the same attribution.

AnyBuild changes what it uses and says so with every object it shows, in the `attribution` and `changes` of the `object` event, the comment of the MJCF file, the header of every STL file and the `asset.copyright` of the GLB:

- the USD is converted to STL meshes and an MJCF body for MuJoCo;
- the collision meshes are replaced by their convex hulls, or a container's by a convex decomposition with CoACD;
- the object is converted to a glTF binary (GLB) with Blender, its textures scaled down to at most 1024 px, or without its textures when Blender is missing;
- the thumbnail is resized to a 256 px WebP.

NVIDIA's name identifies the source of the objects; it does not mean NVIDIA endorses AnyBuild.
Whoever passes converted objects on, for example in an exported project, passes the attribution and the list of changes with them and may not add restrictions.

## Generated media

These files were made for AnyBuild by the team with generative tools and are released with the project under the MIT License, subject to the terms of the tools that made them.

| Files | What | How it was made |
| --- | --- | --- |
| `web/public/mascot/*.webp` | Mechanic, the mascot, one still per expression | Google Gemini image generation (Nano Banana), original character |
| `web/public/logo-full.webp`, `web/public/logo-mark.webp`, `docs/assets/anybuild-logo.png`, `docs/assets/anybuild-social.png`, `web/public/og-image.png`, `web/public/apple-touch-icon.png`, `web/public/favicon*`, `desktop/src-tauri/icons/*.png` | AnyBuild logo: the workbench cube, cropped tight for the app icon, social image, favicons and desktop icons | Google Gemini image generation (Nano Banana), cube only, then cropped |
| `agent/data/sketches/phone-stand.png` | The sample hand sketch of a phone stand | Made by the team for the sketch-to-build demo |

The mascot is an original character; no photo of a real person is stored in the repository.

## Renders, CAD output and recordings made by AnyBuild

These files are output of AnyBuild's own pipeline and are MIT licensed with the project:

- `web/public/models/*`: FreeCAD assemblies (STEP, STL, GLB) and Blender studio renders of the reference drone and the robot gripper.
  The drone assemblies include the DLQFPV canopy and Youfu camera models above, under their licenses.
- `web/public/community/*.png` and `agent/data/references/*/thumbnail.png`: Blender renders of the reference builds.
- `agent/runs/fallback/render.png`: the recorded studio still used when Blender is missing.
- `agent/runs/fallback/omniverse.mp4`: the recorded Omniverse fallback, a browser replay with synthetic values, labelled as recorded in the app (see [docs/omniverse.md](docs/omniverse.md)).
- `agent/data/robouse/recorded/*` and `agent/tests/fixtures/robouse/*`: Robo Use trials of AnyBuild's gripper, recorded with `agent/scripts/record_robouse_trial.py`.
  The logs and the video are output of running [Robo Use](https://github.com/benchflow-ai/robouse) 0.6.1 (Apache-2.0 AND MIT AND CC-BY-4.0), which renders its own tabletop scene around AnyBuild's hand; they contain none of Robo Use's code or task text.
- `docs/assets/screenshots/*.jpg`: screenshots of the AnyBuild dashboard.

## SparkBench, installed separately

The `circuit_design` tool runs [SparkBench](https://github.com/dennisonbertram/sparkbench) by Dennison Bertram, under the MIT License ("Copyright (c) 2026 Dennison Bertram"), at commit `6dd92371aeb2ae6cc5c2dbe04a1fc84a448d315a`.
None of its code is in the repository: `agent/scripts/setup_sparkbench.sh` clones it into `~/.cache/anybuild/sparkbench/<commit>`, and `agent/sparkbench/bridge.ts`, AnyBuild's own code, imports its modules from there.
The circuit files it makes for a build (schematic, breadboard plan, KiCad project, netlist, SPICE deck, parts list, build guide and MicroPython firmware) come from its generators; the driver files in the firmware are copied from its parts library, whose driver code adapted from other projects keeps its own license, as SparkBench's README says.
Its optional native ESP32 helper (`native/esp32/helper`, GPL-2.0-or-later, it downloads QEMU) is never built, run or shipped: the setup installs SparkBench's npm packages without their install scripts, and the bridge does not touch it.

## Runtime dependencies

Libraries, fonts and external applications are not copied into the repository; they are installed by the package managers or separately.
Their versions and licenses are listed in [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md).
The web fonts Inter Tight, Chivo Mono and Caveat load from Google Fonts under the SIL Open Font License 1.1.
