"""Portable USD assembly export. Blender handles meshes; the wrapper adds SI physics."""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
from pathlib import Path

from pai_agent.context import Ctx
from pai_agent.paths import AGENT_ROOT, REPO_ROOT
from pai_agent.state import BuildState
from pai_agent.tools.blender import _assembly, find_blender


def export_product(state: BuildState, directory: Path) -> dict:
    binary = find_blender()
    if not binary:
        raise RuntimeError("Blender is required for USD export. Install Blender on this Mac.")
    stl = REPO_ROOT / (state.stl_path or "")
    if not state.stl_path or not stl.is_file():
        raise ValueError("Build the CAD frame before exporting a product to USD.")
    spec = {"battery_mm": [68.0, 15.5, 6.7], **_assembly(state)}
    parts = []
    for category in ("frame", "motor", "propeller", "battery", "flight_controller"):
        selected = state.selected.get(category)
        if not selected:
            raise ValueError("Select a " + category + " before exporting the assembly.")
        mass = float(state.frame_mass_g if category == "frame" and state.frame_mass_g is not None else selected["mass_g"]) / 1000
        quantity = int(selected["bom_qty"])
        expected = 4 if category in ("motor", "propeller") else 1
        if quantity != expected or not math.isfinite(mass) or mass <= 0:
            raise ValueError("Invalid mass or quantity for " + category)
        for index in range(quantity):
            name = f"{category}_{index}"
            parts.append({"name": name, "usd_path": "/Product/Geometry/" + name,
                          "category": category, "index": index, "mass_kg": mass})
    mass = sum(p["mass_kg"] for p in parts)
    motor = state.selected["motor"]
    spec.update({
        "parts": parts,
        "mass_kg": mass,
        "max_thrust_n": float(motor["thrust_g"]) * int(motor["bom_qty"]) * 0.00980665,
        "units": "metres, kilograms, seconds; Z up",
    })
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "assembly.json"
    manifest.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    geometry = directory / "assembly.usdc"
    completed = subprocess.run(
        [binary, "-b", "--factory-startup", "-P", str(AGENT_ROOT / "blender/export_usd.py"), "--", str(stl), str(geometry), str(manifest)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if completed.returncode or not geometry.is_file():
        raise RuntimeError("Blender USD export failed. Check that this Blender build includes the USD exporter.")
    product = directory / "product.usda"
    product.write_text(f'''#usda 1.0
(
    defaultPrim = "Product"
    metersPerUnit = 1
    upAxis = "Z"
)
def Xform "Product" (
    prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
)
{{
    float physics:mass = {mass:.9f}
    bool physics:rigidBodyEnabled = true
    def Xform "Geometry" (prepend references = @assembly.usdc@</Geometry>) {{}}
}}
''', encoding="utf-8")
    return spec


async def product_usd(ctx: Ctx, args: dict) -> dict:
    del args
    # A unique subdirectory prevents an old referenced layer being reused by a USD cache.
    import uuid

    directory = ctx.state.directory / ("usd-" + uuid.uuid4().hex[:8])
    try:
        spec = await asyncio.to_thread(export_product, ctx.state, directory)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": str(exc), "detail": str(exc)}
    # HTTP /files intentionally serves one directory level; expose a portable zip.
    import zipfile

    bundle = ctx.state.directory / (directory.name + ".zip")
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("product.usda", "assembly.usdc", "assembly.json"):
            archive.write(directory / name, name)
    return {"ok": True, "detail": "USD assembly exported with per-part masses in SI units.",
            "usd_bundle_url": f"/files/{ctx.state.session_id}/{bundle.name}", "mass_kg": spec["mass_kg"]}
