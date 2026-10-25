"""The user's 3D printer and filaments: printer profiles, printing materials, and the choice of material per part.

The printer profiles hold each model's own numbers from its maker's spec page (`source_url`):
bed size, nozzle, hotend and bed limits, whether it has an enclosure, and the materials it
prints. ABS and ASA need an enclosure, so an open printer does not list them. The material
table holds what FEM, the thermal check and the material choice need, from the filament
makers' technical data sheets (`source_url`): printed tensile modulus and strength in the layer
plane, the interlayer (Z) strength, density, heat deflection temperature, elongation, impact,
UV and outdoor suitability, and a spool price.

The choice is process-wide, like the model settings (`settings.py`): POST /api/settings with
`printer` sets it, the dashboard keeps it in the browser and sends it again on load. Without a
printer set every caller behaves as before (`current()` is None).
"""

from __future__ import annotations

CHECKED = "2026-10-25"

# Volumetric flow (mm³/s) is an average for estimates on that printer class, not a maker figure.
PRINTERS: dict[str, dict] = {
    "bambu-a1": {
        "name": "Bambu Lab A1",
        "maker": "Bambu Lab",
        "bed_mm": [256, 256, 256],
        "nozzle_mm": 0.4,
        "max_hotend_c": 300,
        "max_bed_c": 100,
        "enclosure": False,
        "materials": ["PLA", "PETG", "TPU"],
        "flow_mm3_s": 15.0,
        "source_url": "https://bambulab.com/en/a1/tech-specs",
    },
    "bambu-a1-mini": {
        "name": "Bambu Lab A1 mini",
        "maker": "Bambu Lab",
        "bed_mm": [180, 180, 180],
        "nozzle_mm": 0.4,
        "max_hotend_c": 300,
        "max_bed_c": 80,
        "enclosure": False,
        "materials": ["PLA", "PETG", "TPU"],
        "flow_mm3_s": 12.0,
        "source_url": "https://bambulab.com/en/a1-mini/tech-specs",
    },
    "bambu-p1s": {
        "name": "Bambu Lab P1S",
        "maker": "Bambu Lab",
        "bed_mm": [256, 256, 256],
        "nozzle_mm": 0.4,
        "max_hotend_c": 300,
        "max_bed_c": 100,
        "enclosure": True,
        "materials": ["PLA", "PETG", "TPU", "ABS", "ASA"],
        "flow_mm3_s": 18.0,
        "source_url": "https://bambulab.com/en/p1/tech-specs",
    },
    "bambu-x1c": {
        "name": "Bambu Lab X1 Carbon",
        "maker": "Bambu Lab",
        "bed_mm": [256, 256, 256],
        "nozzle_mm": 0.4,
        "max_hotend_c": 300,
        "max_bed_c": 110,
        "enclosure": True,
        "materials": ["PLA", "PETG", "TPU", "ABS", "ASA", "NYLON"],
        "flow_mm3_s": 18.0,
        "source_url": "https://bambulab.com/en/x1/tech-specs",
    },
    "prusa-mk4s": {
        "name": "Original Prusa MK4S",
        "maker": "Prusa Research",
        "bed_mm": [250, 210, 220],
        "nozzle_mm": 0.4,
        "max_hotend_c": 290,
        "max_bed_c": 120,
        "enclosure": False,
        "materials": ["PLA", "PETG", "TPU", "NYLON"],
        "flow_mm3_s": 15.0,
        "source_url": "https://www.prusa3d.com/product/original-prusa-mk4s-3d-printer-5/",
    },
    "prusa-mini-plus": {
        "name": "Original Prusa MINI+",
        "maker": "Prusa Research",
        "bed_mm": [180, 180, 180],
        "nozzle_mm": 0.4,
        "max_hotend_c": 280,
        "max_bed_c": 100,
        "enclosure": False,
        "materials": ["PLA", "PETG", "TPU"],
        "flow_mm3_s": 8.0,
        "source_url": "https://www.prusa3d.com/product/original-prusa-mini-semi-assembled-3d-printer-4/",
    },
    "prusa-core-one": {
        "name": "Prusa CORE One",
        "maker": "Prusa Research",
        "bed_mm": [250, 220, 270],
        "nozzle_mm": 0.4,
        "max_hotend_c": 290,
        "max_bed_c": 120,
        "enclosure": True,
        "materials": ["PLA", "PETG", "TPU", "ABS", "ASA", "NYLON"],
        "flow_mm3_s": 18.0,
        "source_url": "https://www.prusa3d.com/product/prusa-core-one/",
    },
    "creality-ender-3-v3": {
        "name": "Creality Ender-3 V3",
        "maker": "Creality",
        "bed_mm": [220, 220, 250],
        "nozzle_mm": 0.4,
        "max_hotend_c": 300,
        "max_bed_c": 110,
        "enclosure": False,
        "materials": ["PLA", "PETG", "TPU"],
        "flow_mm3_s": 14.0,
        "source_url": "https://www.creality.com/products/creality-ender-3-v3",
    },
    "creality-k1": {
        "name": "Creality K1",
        "maker": "Creality",
        "bed_mm": [220, 220, 250],
        "nozzle_mm": 0.4,
        "max_hotend_c": 300,
        "max_bed_c": 100,
        "enclosure": True,
        "materials": ["PLA", "PETG", "TPU", "ABS", "ASA"],
        "flow_mm3_s": 18.0,
        "source_url": "https://www.creality.com/products/k1-flagship-3d-printer",
    },
    "elegoo-neptune-4": {
        "name": "Elegoo Neptune 4",
        "maker": "Elegoo",
        "bed_mm": [225, 225, 265],
        "nozzle_mm": 0.4,
        "max_hotend_c": 300,
        "max_bed_c": 110,
        "enclosure": False,
        "materials": ["PLA", "PETG", "TPU"],
        "flow_mm3_s": 12.0,
        "source_url": "https://www.elegoo.com/products/elegoo-neptune-4-fdm-3d-printer",
    },
}

# Printed test specimens from the makers' data sheets. modulus_mpa and strength_mpa are in the layer
# plane (horizontal print), z_strength_mpa the interlayer adhesion across layers. hdt_c is the heat
# deflection temperature at 0.45 MPa (1.8 MPa where only that is given). impact is a grade from the
# Charpy results (notched_kj_m2 where given); uv the outdoor rating from the maker's notes.
MATERIALS: dict[str, dict] = {
    "PLA": {
        "name": "PLA",
        "modulus_mpa": 2300.0,
        "strength_mpa": 51.0,
        "z_strength_mpa": 17.0,
        "density_g_cm3": 1.24,
        "hdt_c": 55.0,
        "elongation_pct": 2.9,
        "charpy_kj_m2": 13.0,
        "notched_kj_m2": None,
        "impact": 1,
        "uv": "poor",
        "flexible": False,
        "nozzle_c": 215,
        "bed_c": 60,
        "warp": 1,
        "eur_per_kg": 25.0,
        "source": "Prusament PLA technical data sheet v1.1 (2022)",
        "source_url": "https://prusament.com/materials/pla/",
    },
    "PETG": {
        "name": "PETG",
        "modulus_mpa": 1500.0,
        "strength_mpa": 47.0,
        "z_strength_mpa": 18.0,
        "density_g_cm3": 1.27,
        "hdt_c": 68.0,
        "elongation_pct": 5.1,
        "charpy_kj_m2": None,
        "notched_kj_m2": 6.0,
        "impact": 3,
        "uv": "fair",
        "flexible": False,
        "nozzle_c": 240,
        "bed_c": 85,
        "warp": 1,
        "eur_per_kg": 25.0,
        "source": "Prusament PETG technical data sheet (2023): unnotched Charpy no break",
        "source_url": "https://prusament.com/materials/prusament-petg/",
    },
    "ASA": {
        "name": "ASA",
        "modulus_mpa": 1600.0,
        "strength_mpa": 42.0,
        "z_strength_mpa": 11.0,
        "density_g_cm3": 1.07,
        "hdt_c": 93.0,
        "elongation_pct": 3.4,
        "charpy_kj_m2": 25.0,
        "notched_kj_m2": 12.0,
        "impact": 2,
        "uv": "excellent",
        "flexible": False,
        "nozzle_c": 260,
        "bed_c": 105,
        "warp": 3,
        "eur_per_kg": 30.0,
        "source": "Prusament ASA technical data sheet (2024)",
        "source_url": "https://prusament.com/materials/prusament-asa/",
    },
    "ABS": {
        "name": "ABS",
        "modulus_mpa": 2247.0,
        "strength_mpa": 33.4,
        "z_strength_mpa": 29.7,
        "density_g_cm3": 1.04,
        "hdt_c": 100.0,
        "elongation_pct": 17.9,
        "charpy_kj_m2": None,
        "notched_kj_m2": None,
        "impact": 2,
        "uv": "poor",
        "flexible": False,
        "nozzle_c": 255,
        "bed_c": 100,
        "warp": 3,
        "eur_per_kg": 25.0,
        "source": "Polymaker PolyLite ABS technical data sheet v5.5",
        "source_url": "https://polymaker.com/wp-content/uploads/lana-downloads/PolyLite-ABS_TDS_EN_V5.5.pdf",
    },
    "NYLON": {
        "name": "Nylon (PA6/66 copolymer)",
        "modulus_mpa": 2703.0,
        "strength_mpa": 78.0,
        "z_strength_mpa": 45.8,
        "density_g_cm3": 1.12,
        "hdt_c": 110.5,
        "elongation_pct": 12.7,
        "charpy_kj_m2": None,
        "notched_kj_m2": None,
        "impact": 3,
        "uv": "fair",
        "flexible": False,
        "nozzle_c": 260,
        "bed_c": 50,
        "warp": 2,
        "eur_per_kg": 50.0,
        "source": "Polymaker PolyMide CoPA technical data sheet v5.5 (dry, annealed)",
        "source_url": "https://polymaker.com/wp-content/uploads/lana-downloads/TDS_Polymaker_PolyMide-CoPA_V5.5_2026-01-06_EN.pdf",
    },
    "TPU": {
        "name": "TPU 95A",
        "modulus_mpa": 26.0,
        "strength_mpa": 41.4,
        "z_strength_mpa": 9.5,
        "density_g_cm3": 1.25,
        "hdt_c": 78.6,
        "elongation_pct": 563.0,
        "charpy_kj_m2": None,
        "notched_kj_m2": None,
        "impact": 4,
        "uv": "fair",
        "flexible": True,
        "nozzle_c": 230,
        "bed_c": 50,
        "warp": 0,
        "eur_per_kg": 40.0,
        "source": "Prusament TPU 95A technical data sheet (2025): modulus is the secant to 100 % (8.9 MPa) scaled to small strain",
        "source_url": "https://prusament.com/materials/prusament-tpu-95a/",
    },
}
NEEDS_ENCLOSURE = {"ABS", "ASA"}
POISSON = {"TPU": 0.45}
DEFAULT_POISSON = 0.35
IMPACT_WORDS = {0: "none", 1: "low", 2: "medium", 3: "high", 4: "very high"}
# A part's service temperature must stay this far under the heat deflection temperature.
HEAT_MARGIN_C = 5.0
# Printed defaults the FEM and the estimate both use.
PRINT = {"layer_height_mm": 0.2, "walls": 3, "infill_pct": 25}

_selected: dict | None = None


def normalise_material(name: object) -> str:
    key = str(name or "").strip().upper()
    return {"PA": "NYLON", "PA6": "NYLON", "PA12": "NYLON", "PA-CF": "NYLON", "NYLON-CF": "NYLON", "PETG-CF": "PETG", "TPU95A": "TPU", "FLEX": "TPU"}.get(key, key)


def set_printer(raw: object) -> dict | None:
    """Sets or clears the user's printer. Raises ValueError with the allowed values."""

    global _selected
    if raw is None or raw is False or (isinstance(raw, dict) and not raw.get("model")):
        _selected = None
        return None
    if not isinstance(raw, dict):
        raise ValueError("printer must be {model, filaments} or null.")
    model = str(raw.get("model") or "").strip()
    if model not in PRINTERS:
        raise ValueError("printer.model must be one of " + ", ".join(PRINTERS) + ".")
    profile = PRINTERS[model]
    filaments = raw.get("filaments")
    if filaments is None:
        chosen = list(profile["materials"])
    else:
        if not isinstance(filaments, list):
            raise ValueError("printer.filaments must be a list such as [\"PLA\", \"PETG\"].")
        chosen = []
        for value in filaments:
            material = normalise_material(value)
            if material not in MATERIALS:
                raise ValueError("Unknown filament " + str(value) + ". Known: " + ", ".join(MATERIALS) + ".")
            if material not in chosen:
                chosen.append(material)
    _selected = {"model": model, "filaments": chosen}
    return current()


def current() -> dict | None:
    """The user's printer with its profile, the filaments they have and which of those it prints; None without one."""

    if _selected is None:
        return None
    profile = PRINTERS[_selected["model"]]
    printable = [m for m in _selected["filaments"] if m in profile["materials"]]
    return {
        "model": _selected["model"],
        **profile,
        "filaments": list(_selected["filaments"]),
        "printable": printable,
        "not_printable": [m for m in _selected["filaments"] if m not in profile["materials"]],
    }


def catalog() -> dict:
    return {
        "printers": [{"id": key, **{k: v for k, v in value.items() if k != "flow_mm3_s"}} for key, value in PRINTERS.items()],
        "filaments": [{"id": key, "name": value["name"], "eur_per_kg": value["eur_per_kg"], "needs_enclosure": key in NEEDS_ENCLOSURE} for key, value in MATERIALS.items()],
        "checked": CHECKED,
    }


def summary(printer: dict | None = None) -> str:
    """One line for the orchestrator: the printer, its bed and what it can print from the user's spools."""

    printer = printer or current()
    if not printer:
        return ""
    x, y, z = printer["bed_mm"]
    line = (
        f"The user has a 3D printer: {printer['name']}, {x:g} x {y:g} x {z:g} mm bed, {printer['nozzle_mm']:g} mm nozzle, "
        + ("enclosed" if printer["enclosure"] else "open frame, no enclosure")
        + ". Their filaments it prints: " + (", ".join(printer["printable"]) or "none")
    )
    if printer["not_printable"]:
        line += "; it cannot print their " + ", ".join(printer["not_printable"]) + (" (needs an enclosure)" if set(printer["not_printable"]) & NEEDS_ENCLOSURE else "")
    return line + "."


def density(material: str) -> float:
    return MATERIALS[normalise_material(material)]["density_g_cm3"]


def eur_per_g(material: str) -> float:
    entry = MATERIALS.get(normalise_material(material))
    return (entry["eur_per_kg"] if entry else 30.0) / 1000.0


def fill_fraction(min_wall_mm: float | None, walls: int | None = None, infill_pct: float | None = None, nozzle_mm: float = 0.4) -> float:
    """Share of a printed section that is plastic: the perimeter shell solid, the core at the infill density.

    For a wall of thickness t with n perimeters of one nozzle width on each side, the shell is
    2 n w of t (capped at t) and the rest prints at the infill; a thin wall is all perimeters.
    """

    walls = PRINT["walls"] if walls is None else walls
    infill = (PRINT["infill_pct"] if infill_pct is None else infill_pct) / 100.0
    if not min_wall_mm or min_wall_mm <= 0:
        return 1.0
    shell = min(1.0, 2.0 * walls * nozzle_mm * 1.05 / min_wall_mm)
    return round(shell + (1.0 - shell) * infill, 3)


def printed_properties(material: str, fill: float = 1.0) -> dict:
    """Modulus and strengths of the printed part: the data sheet values scaled by the plastic share of the section.

    The FEM solves on the solid shape with this homogenised modulus; strength in the layer plane and
    across the layers (Z) gets the same share, so a sparse core is never credited with solid strength.
    """

    entry = MATERIALS[normalise_material(material)]
    fill = min(max(fill, 0.05), 1.0)
    return {
        "material": normalise_material(material),
        "modulus_mpa": round(entry["modulus_mpa"] * fill, 1),
        "poisson": POISSON.get(normalise_material(material), DEFAULT_POISSON),
        "strength_mpa": round(entry["strength_mpa"] * fill, 2),
        "z_strength_mpa": round(entry["z_strength_mpa"] * fill, 2),
        "fill": fill,
        "density_g_cm3": entry["density_g_cm3"],
    }


def choose_material(needs: dict, candidates: list[str] | None = None) -> dict:
    """The material for one printed part from what it must survive, among the candidates.

    needs: max_temp_c (service temperature), outdoor (sun and rain), impact (crashes, drops), flex
    (bends on purpose: a clip, a bumper, a gasket). Hard limits rule a material out (heat, flex);
    outdoor and impact rank the rest; then stiffness and strength; then the cheaper spool.
    Returns {material, reason, ok, rejected: {material: why}}; ok is False when no candidate meets the
    hard limits, and the best of the rest is returned with the reason why it falls short.
    """

    printer = current()
    pool = [normalise_material(m) for m in (candidates if candidates is not None else (printer["printable"] if printer else list(MATERIALS)))]
    pool = [m for m in dict.fromkeys(pool) if m in MATERIALS]
    if not pool:
        raise ValueError("No printable filament: add a filament this printer can print.")
    temp = needs.get("max_temp_c")
    temp = float(temp) if temp is not None else None
    outdoor = bool(needs.get("outdoor"))
    impact = bool(needs.get("impact"))
    flex = bool(needs.get("flex"))
    rejected: dict[str, str] = {}
    fitting = []
    for material in pool:
        entry = MATERIALS[material]
        if temp is not None and entry["hdt_c"] < temp + HEAT_MARGIN_C:
            rejected[material] = f"softens at {entry['hdt_c']:.0f} °C"
        elif flex and not entry["flexible"]:
            rejected[material] = "is rigid"
        elif not flex and entry["flexible"] and len(pool) > 1:
            rejected[material] = "is flexible, too soft to carry a load"
        else:
            fitting.append(material)
    ok = bool(fitting)
    # Nothing meets the hard limits: the best fallback is still rigid for a rigid part (flexible for a flexible one).
    ranked = fitting or [m for m in pool if MATERIALS[m]["flexible"] == flex] or pool

    def score(material: str) -> tuple:
        entry = MATERIALS[material]
        uv = {"poor": 0, "fair": 1, "good": 2, "excellent": 3}[entry["uv"]]
        return (
            -(uv if outdoor else 0),
            -(entry["impact"] if impact else 0),
            -(entry["hdt_c"] if temp is not None and not ok else 0),
            -min(entry["modulus_mpa"] * entry["strength_mpa"], 2500.0 * 60.0),
            entry["eur_per_kg"],
        )

    best = sorted(ranked, key=score)[0]
    entry = MATERIALS[best]
    reasons = []
    if temp is not None:
        reasons.append(f"it holds its shape to {entry['hdt_c']:.0f} °C, the part sees {temp:.0f} °C")
    if outdoor:
        reasons.append(f"its UV resistance is {entry['uv']}")
    if impact:
        reasons.append(f"its impact toughness is {IMPACT_WORDS[entry['impact']]}")
    if flex:
        reasons.append(f"it stretches {entry['elongation_pct']:.0f} % before it breaks")
    if not reasons:
        reasons.append(f"it is the stiffest and strongest of what you can print ({entry['modulus_mpa'] / 1000:.1f} GPa, {entry['strength_mpa']:.0f} MPa)")
    dropped = [f"{m} {why}" for m, why in rejected.items() if m != best]
    sentence = best + ", because " + " and ".join(reasons) + ("; " + ", ".join(dropped) if dropped else "") + "."
    if not ok:
        sentence = "None of your printable filaments meets it: " + ", ".join(f"{m} {why}" for m, why in rejected.items()) + f". Best of them: {best}."
    return {"material": best, "reason": sentence, "ok": ok, "rejected": rejected, "candidates": pool}


def warp_risk(material: str, printer: dict | None, footprint_mm: tuple[float, float]) -> dict:
    """Warping from the material's shrink, the enclosure and the part's longest side on the bed."""

    entry = MATERIALS[normalise_material(material)]
    longest = max(footprint_mm)
    score = entry["warp"]
    enclosed = bool(printer and printer.get("enclosure"))
    if not enclosed and normalise_material(material) in NEEDS_ENCLOSURE | {"NYLON"}:
        score += 2
    score += 2 if longest > 150 else 1 if longest > 80 else 0
    level = "high" if score >= 5 else "medium" if score >= 3 else "low"
    why = f"{normalise_material(material)} {'shrinks a lot' if entry['warp'] >= 3 else 'shrinks a little' if entry['warp'] >= 1 else 'barely shrinks'}"
    why += f", {'enclosed' if enclosed else 'open'} printer, {longest:.0f} mm long on the bed"
    return {"level": level, "score": score, "text": why}


def printed_frame(state) -> dict | None:
    """The drone's frame printed on the user's printer instead of bought: material, mass and filament price."""

    # The optimizer prices variants on a stand-in state without these fields.
    chosen = (getattr(state, "print_materials", None) or {}).get("frame")
    if current() is None or getattr(state, "product", "drone") != "drone" or not chosen or state.frame_mass_g is None:
        return None
    mass = float(state.frame_mass_g)
    return {"material": chosen["material"], "mass_g": mass, "price_eur": round(mass * eur_per_g(chosen["material"]), 2)}


def printed_line_name(name: str, material: str) -> str:
    printer = current()
    return f"{name}, printed on your {printer['name']} in {material}" if printer else f"{name}, printed {material}"
