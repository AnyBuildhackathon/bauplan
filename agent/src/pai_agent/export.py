"""Export: the bill of materials as CSV, the order grouped by shop, and one ZIP for the slicer and the bench.

The ZIP (anybuild-<product>-v<n>.zip, written into the session directory) holds the CAD files of
every built part (the drone frame, each spec part, the gripper part, the assembly), the FreeCAD
scripts, bom.csv, build-guide.md (the agent's guide when one was written, else an ordered list from
the bill of materials), the firmware file, the latest studio render and a README with the
requirements, the key numbers and print settings per material.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

CSV_COLUMNS = ["name", "qty", "unit_price_eur", "line_total_eur", "weight_g", "shop", "url", "price_source", "availability", "checked_at"]
CAD_SUFFIXES = (".stl", ".step", ".stp")
PRINT_SETTINGS = {
    "PLA": "0.2 mm layers, 20 % infill, 210 °C nozzle, 60 °C bed",
    "PETG": "0.2 mm layers, 25 % infill, 240 °C nozzle, 80 °C bed",
    "TPU": "0.2 mm layers, 15 % infill, 225 °C nozzle, slow (20 mm/s)",
    "ABS": "0.2 mm layers, 25 % infill, 250 °C nozzle, 100 °C bed, enclosure",
    "ASA": "0.2 mm layers, 25 % infill, 250 °C nozzle, 100 °C bed, enclosure",
    "PA": "0.2 mm layers, 30 % infill, 260 °C nozzle, dry filament",
}
METRIC_LABELS = {
    "weight_g": ("Weight", "g"),
    "thrust_to_weight": ("Thrust to weight", ""),
    "flight_time_min": ("Flight time", "min"),
    "price_eur": ("Cost", "€"),
}


def _last(events: list[dict], kind: str) -> dict | None:
    return next((event for event in reversed(events) if event.get("type") == kind), None)


def _printed(item: dict) -> bool:
    return item.get("shop") == "printed" or not str(item.get("url", "")).startswith(("http://", "https://"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "project"


def product_name(state) -> str:
    if state.product == "generic" and state.spec:
        return str(state.spec.get("name") or "product")
    return state.product


def version(state) -> int:
    return max(1, len(state.versions))


def bundle_name(state) -> str:
    return f"anybuild-{_slug(product_name(state))}-v{version(state)}.zip"


def bom_csv(bom: dict) -> str:
    """One row per line, then a total row; starts with a UTF-8 byte order mark so Excel reads it as UTF-8."""

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
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
                item.get("url", ""),
                item.get("price_source", "catalog"),
                item.get("availability", ""),
                item.get("checked_at", ""),
            ]
        )
    writer.writerow(["Total", "", "", f"{float(bom.get('total_eur', 0)):.2f}", "", "", "", "", "", ""])
    return "﻿" + out.getvalue()


def _material(state, item: dict) -> str:
    info = state.built.get(item.get("category", "")) if state.built else None
    if info and info.get("material"):
        return str(info["material"])
    found = re.search(r"printed (\w+)$", str(item.get("name", "")))
    return found.group(1) if found else "PLA"


def order(state) -> dict:
    """The bill of materials grouped by shop, most expensive shop first, printed parts in their own group."""

    shops: dict[str, dict] = {}
    printed = {"items": [], "filament_g": 0.0, "cost_eur": 0.0}
    for item in (state.bom or {}).get("items", []):
        if item.get("category") == "filament":
            continue
        qty = item.get("qty", 1)
        line = round(qty * float(item.get("unit_price_eur", 0)), 2)
        if _printed(item):
            mass = round(qty * float(item.get("weight_g", 0)), 1)
            printed["items"].append({"name": item["name"], "qty": qty, "material": _material(state, item), "mass_g": mass})
            printed["filament_g"] += mass
            printed["cost_eur"] += line
            continue
        shop = item.get("shop") or "Unknown shop"
        group = shops.setdefault(shop, {"shop": shop, "items": [], "total_eur": 0.0, "live": False})
        group["items"].append(
            {
                "name": item["name"],
                "qty": qty,
                "unit_price_eur": item.get("unit_price_eur", 0),
                "line_total_eur": line,
                "url": item.get("url", ""),
                "price_source": item.get("price_source", "catalog"),
            }
        )
        group["total_eur"] += line
        group["live"] = group["live"] or item.get("price_source") == "live"
    groups = sorted(shops.values(), key=lambda g: -g["total_eur"])
    for group in groups:
        group["total_eur"] = round(group["total_eur"], 2)
    printed["filament_g"] = round(printed["filament_g"], 1)
    printed["cost_eur"] = round(printed["cost_eur"], 2)
    return {"shops": groups, "print": printed, "total_eur": round(float((state.bom or {}).get("total_eur", 0)), 2)}


def _minutes(value: float) -> str:
    return f"{value:g} min"


def build_guide_md(guide: dict, title: str) -> str:
    lines = [f"# {title}: build guide", "", f"{len(guide['steps'])} steps, about {_minutes(guide['total_minutes'])}.", ""]
    for step in guide["steps"]:
        lines += [f"## Step {step['n']}: {step['title']}", ""]
        facts = [_minutes(step["minutes"])]
        if step.get("tools"):
            facts.append("Tools: " + ", ".join(step["tools"]))
        lines.append(" · ".join(facts))
        if step.get("items"):
            lines += ["", "Parts: " + ", ".join(step["items"])]
        lines += ["", step["instructions"], ""]
    return "\n".join(lines)


def simple_guide_md(state) -> str:
    """Without an agent-written guide: print the printed parts, fit the bought ones, then verify the checks."""

    plan = order(state)
    lines = [f"# {product_name(state)}: build guide", "", "Generated from the bill of materials; the agent wrote no step-by-step guide for this product.", ""]
    n = 0
    for item in plan["print"]["items"]:
        n += 1
        lines.append(f"{n}. Print {item['qty']} × {item['name']} in {item['material']} ({item['mass_g']:g} g). Settings in README.md.")
    for group in plan["shops"]:
        for item in group["items"]:
            n += 1
            lines.append(f"{n}. Fit {item['qty']} × {item['name']}.")
    checks = [r for r in state.requirements if r.get("_met") is not None]
    if checks:
        n += 1
        lines.append(f"{n}. Verify: " + "; ".join(str(r.get("text", r.get("id"))) for r in checks) + ".")
    return "\n".join(lines) + "\n"


def cad_files(directory: Path) -> list[Path]:
    """Each built part's STL and STEP and the assembly, not the per-body copies (asm-*) the assembly is made of."""

    found = [p for p in Path(directory).glob("*") if p.is_file() and not p.name.startswith("asm-")]
    return sorted(p for p in found if p.suffix.lower() in CAD_SUFFIXES or p.name == "assembly.glb")


def _latest_render(directory: Path) -> Path | None:
    def number(path: Path) -> int:
        found = re.search(r"(\d+)", path.stem)
        return int(found.group(1)) if found else 0

    renders = sorted(Path(directory).glob("studio-v*.png"), key=number)
    return renders[-1] if renders else None


def _recorded_render(event: dict | None) -> Path | None:
    """Without Blender the render event points at the recorded still in the fallback folder."""

    from pai_agent.paths import FALLBACK_DIR

    url = str((event or {}).get("png_url") or "")
    if not url.startswith("/files/fallback/"):
        return None
    path = FALLBACK_DIR / Path(url.split("?")[0]).name
    return path if path.is_file() else None


def readme_md(state, missing: list[str]) -> str:
    lines = [f"# {product_name(state)}, version {version(state)}", "", "Exported from AnyBuild.", ""]
    if state.requirements:
        lines += ["## Requirements", ""]
        for requirement in state.requirements:
            met = requirement.get("_met")
            mark = "pass" if met is True else "fail" if met is False else "open"
            detail = requirement.get("_detail")
            lines.append(f"- {mark}: {requirement.get('text', requirement.get('id'))}" + (f" ({detail})" if detail else ""))
        lines.append("")
    numbers = [(METRIC_LABELS[k], state.metrics[k]) for k in METRIC_LABELS if isinstance(state.metrics.get(k), (int, float))]
    if numbers:
        lines += ["## Key numbers", ""]
        lines += [f"- {label}: {value:g}" + (f" {unit}" if unit else "") for (label, unit), value in numbers]
        lines.append("")
    plan = order(state)
    materials = sorted({item["material"] for item in plan["print"]["items"]})
    lines += ["## Print settings", ""]
    if materials:
        lines.append(f"{plan['print']['filament_g']:g} g of filament for the printed parts.")
        lines.append("")
    lines += [f"- {m}: {PRINT_SETTINGS.get(m.upper(), 'see the filament maker')}" for m in materials or ["PLA", "PETG", "TPU"]]
    lines += ["", "## Contents", "", "- cad/: STL for the slicer, STEP for CAD", "- bom.csv: the bill of materials", "- build-guide.md: the assembly steps"]
    lines += ["- firmware/: the flight controller or microcontroller file", "- render.png: the studio render", "- scripts/: the FreeCAD scripts", ""]
    if missing:
        lines += ["## Missing files", ""] + [f"- {name}" for name in missing] + [""]
    return "\n".join(lines)


def bundle(state, events: list[dict]) -> Path:
    """Writes the ZIP into the session directory, streaming each file from disk. Raises ValueError before the first bill of materials."""

    if not state.bom:
        raise ValueError("No bill of materials yet: build something first.")
    directory = Path(state.directory)
    path = directory / bundle_name(state)
    folder = path.stem
    files = cad_files(directory)
    names = {p.name for p in files}
    missing = [
        p.with_suffix(".step").name
        for p in files
        if p.suffix.lower() == ".stl" and p.stem != "assembly" and not {p.with_suffix(".step").name, p.with_suffix(".stp").name} & names
    ]
    tmp = path.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, f"{folder}/cad/{file.name}")
        for script in sorted(directory.glob("*.py")):
            archive.write(script, f"{folder}/scripts/{script.name}")
        archive.writestr(f"{folder}/bom.csv", bom_csv(state.bom))
        guide = _last(events, "build_guide")
        archive.writestr(f"{folder}/build-guide.md", build_guide_md(guide, product_name(state)) if guide else simple_guide_md(state))
        firmware = _last(events, "firmware")
        if firmware:
            file = directory / Path(str(firmware.get("filename", ""))).name
            if file.is_file():
                archive.write(file, f"{folder}/firmware/{file.name}")
        render = _latest_render(directory) or _recorded_render(_last(events, "render"))
        if render is not None:
            archive.write(render, f"{folder}/render.png")
        archive.writestr(f"{folder}/README.md", readme_md(state, missing))
    tmp.replace(path)
    return path
