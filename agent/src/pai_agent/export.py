"""Export and share: the bill of materials as CSV, one ZIP for the slicer and the bench, a library link.

The ZIP holds every STL and STEP file of the current build (the drone's frame, a spec product's
parts and assembly bodies), the bill of materials as CSV, the build guide as Markdown when one was
written, and the firmware file. Sharing saves a spec product to the library as a project; the drone
and the gripper are built by their own code, so their link reopens that code reference.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

CAD_SUFFIXES = (".stl", ".step", ".stp")
# Products built by their own flow: sharing one points at its code reference in the library.
CODE_REFERENCE_OF = {"drone": "micro-drone", "gripper": "robot-gripper"}


def _last(events: list[dict], kind: str) -> dict | None:
    return next((event for event in reversed(events) if event.get("type") == kind), None)


def bom_csv(bom: dict) -> str:
    """One row per line with its total, then a total row."""

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["name", "qty", "unit_price_eur", "line_eur", "weight_g", "shop", "price_source", "url"])
    for item in bom.get("items", []):
        qty = item.get("qty", 1)
        unit = float(item.get("unit_price_eur", 0))
        writer.writerow(
            [
                item.get("name", ""),
                qty,
                f"{unit:.2f}",
                f"{qty * unit:.2f}",
                f"{float(item.get('weight_g', 0)):g}",
                item.get("shop", ""),
                item.get("price_source", "catalog"),
                item.get("url", ""),
            ]
        )
    writer.writerow(["Total", "", "", f"{float(bom.get('total_eur', 0)):.2f}", "", "", "", ""])
    return out.getvalue()


def _minutes(value: float) -> str:
    return f"{value:g} min"


def build_guide_md(guide: dict, title: str) -> str:
    lines = [f"# {title}: build guide", "", f"{len(guide['steps'])} steps, about {_minutes(guide['total_minutes'])}.", ""]
    for step in guide["steps"]:
        lines.append(f"## Step {step['n']}: {step['title']}")
        lines.append("")
        facts = [_minutes(step["minutes"])]
        if step.get("tools"):
            facts.append("Tools: " + ", ".join(step["tools"]))
        lines.append(" · ".join(facts))
        if step.get("items"):
            lines.append("")
            lines.append("Parts: " + ", ".join(step["items"]))
        lines.append("")
        lines.append(step["instructions"])
        lines.append("")
    return "\n".join(lines)


def project_name(state) -> str:
    if state.product == "generic" and state.spec:
        return str(state.spec.get("name") or "product")
    return state.product


def zip_name(state) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", project_name(state).lower()).strip("-") or "project"
    return f"anybuild-{slug}-v{max(1, len(state.versions))}.zip"


def cad_files(directory: Path) -> list[Path]:
    return sorted(p for p in Path(directory).glob("*") if p.is_file() and p.suffix.lower() in CAD_SUFFIXES)


def project_zip(state, events: list[dict]) -> bytes:
    """Raises ValueError when there is nothing to export yet."""

    files = cad_files(state.directory)
    if not files and not state.bom:
        raise ValueError("Nothing to export yet: build something first.")
    folder = zip_name(state).removesuffix(".zip")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{folder}/cad/{path.name}")
        if state.bom:
            archive.writestr(f"{folder}/bom.csv", bom_csv(state.bom))
        guide = _last(events, "build_guide")
        if guide:
            archive.writestr(f"{folder}/build-guide.md", build_guide_md(guide, project_name(state)))
        firmware = _last(events, "firmware")
        if firmware:
            path = Path(state.directory) / str(firmware.get("filename", ""))
            if path.is_file() and path.parent == Path(state.directory):
                archive.write(path, f"{folder}/firmware/{path.name}")
    return buffer.getvalue()


def share(state) -> dict:
    """The library id a link reopens. Raises ValueError when the build cannot be saved yet."""

    code = CODE_REFERENCE_OF.get(state.product)
    if code is not None:
        if not state.bom:
            raise ValueError("Nothing to share yet: build something first.")
        return {"id": code, "saved": False}
    from pai_agent.references import save_reference

    row = save_reference(state)
    return {"id": row["id"], "saved": True}
