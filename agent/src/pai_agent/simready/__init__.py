"""NVIDIA SimReady objects in AnyBuild's scenes: real things to build around, measure and grasp.

NVIDIA publishes 2,575 SimReady packages (food, kitchenware, boxes, hand tools, ...) in the
Hugging Face dataset nvidia/simready-assets, each a USD asset with its mesh, textures, mass,
centre of mass, inertia, physics material and Wikidata semantics, under CC BY 4.0. AnyBuild
pins one revision of the dataset and uses an object as context in the scene, as the size a
design must fit, or as the thing a gripper picks up; objects never enter the bill of materials.

- `fetch.py` downloads one package into a cache outside the repository, refuses every license
  but CC-BY-4.0 and checks every file against the package's bill of materials (SHA-256).
- `convert.py` reads the USD and writes what AnyBuild runs: an MJCF body for MuJoCo (one convex
  hull, or a CoACD convex decomposition for a container such as a pan or a bowl, because a
  single hull would be a lid over the cavity), and a textured GLB for the 3D view.
- `index.py` searches the offline catalogue `agent/data/simready/index.json`, built once by
  `agent/scripts/build_simready_index.py`.

The Python packages behind it are the optional extra `simready` (`cd agent && uv sync --extra
simready`); without them the search still works and the tool says how to install them. Every
output carries the CC BY 4.0 attribution: NVIDIA as the author, the dataset link and the list
of changes AnyBuild made.
"""

from __future__ import annotations

import importlib.util

REPO_ID = "nvidia/simready-assets"
# The dataset revision AnyBuild is built and tested against; the index lists exactly its packages.
REVISION = "524747d9b5e1f21b5b18b56041788c01d745f1a1"
LICENSE = "CC-BY-4.0"
LICENSE_NAME = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
AUTHOR = "NVIDIA"

INSTALL_HINT = "Install the SimReady extra: cd agent && uv sync --extra simready"

# Import name and package name of each optional dependency, by what needs it. Downloads need none of
# them (huggingface_hub only finds a saved login token and lists the dataset for the index builder).
_NEEDS = {
    "convert": (("pxr", "usd-core"), ("trimesh", "trimesh")),
    "decompose": (("coacd", "coacd"),),
    "index": (("huggingface_hub", "huggingface_hub"),),
}


def source_tag(revision: str = REVISION) -> str:
    """`nvidia/simready-assets@524747d9b5e1`, the short form events and files carry."""

    return f"{REPO_ID}@{revision[:12]}"


def asset_url(asset_id: str, revision: str = REVISION) -> str:
    """The package's folder on Hugging Face at the pinned revision, the link the attribution names."""

    return f"https://huggingface.co/datasets/{REPO_ID}/tree/{revision}/{asset_id}"


def missing(*needs: str) -> list[str]:
    """The packages of the `simready` extra that are not installed, for the given needs (default: all)."""

    wanted = needs or tuple(_NEEDS)
    names = []
    for need in wanted:
        for module, package in _NEEDS[need]:
            if importlib.util.find_spec(module) is None and package not in names:
                names.append(package)
    return names
