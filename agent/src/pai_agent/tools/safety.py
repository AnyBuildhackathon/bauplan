"""Safety and regulations check before anyone orders parts.

A fixed rule set reads the build (the drone parts and weight, the gripper's servo force, a
product spec's parts and words) and Claude adds its own findings over the same spec. Every
finding names its rule or source and a fix the agent can apply. The findings are hints for
the team, not legal advice: the rules change and a product still needs its own assessment.
"""

from __future__ import annotations

import re

from pai_agent.context import Ctx

SEVERITIES = ("danger", "warning", "info")
DISCLAIMER = "Hints from a fixed rule set and the agent, not legal advice. Check the current rules before you sell or fly it."

# EU drone classes by maximum take-off mass, Commission Delegated Regulation (EU) 2019/945, Annex Parts 1 to 3.
_C0_MAX_G = 250.0
_C1_MAX_G = 900.0
_C2_MAX_G = 4000.0

# Above this a lithium battery needs airline approval as a passenger spare, IATA DGR 2.3.
_PASSENGER_WH = 100.0
# Up to this per cell (and 100 Wh per pack) a battery ships under the lighter Section II of IATA PI 965 to 967.
_SECTION_II_CELL_WH = 20.0

# Contact with a closing gripper above this force starts to hurt a hand; ISO/TS 15066 Annex A gives 140 N transient for the hand.
_PINCH_INFO_N = 10.0
_HAND_TRANSIENT_N = 140.0
# Pitch radius of the gripper template's gears, where a finger can get between the teeth.
_GEAR_RADIUS_MM = 10.0

MAINS = re.compile(
    r"\b(230|240|220|120|110|100)\s*-?\s*v(olts?)?\b(?!\s*dc)|\bmains\b|\bwall (socket|outlet|plug)\b|\bschuko\b|\bE(27|14)\b|\b(110|230)\s*v\s*ac\b",
    re.IGNORECASE,
)
_CHILD = re.compile(r"\b(child|children|kids?|toddler|baby|babies|toy|toys|nursery)\b", re.IGNORECASE)
_COIN_CELL = re.compile(r"\b(coin|button) cell\b|\bCR ?20(32|25|16)\b", re.IGNORECASE)
_MECHANISM = re.compile(r"\b(gear|gears|hinge|linkage|jaw|jaws|gripper|claw|scissor|crank|lever arm)\b", re.IGNORECASE)
_ENCLOSURE = re.compile(r"\b(case|enclosure|housing|box|shade|lid)\b", re.IGNORECASE)
_HEAT_SOURCE = re.compile(r"\b(led|lamp|bulb|raspberry|pi ?5|motor|driver|heater|charger|power supply|battery)\b", re.IGNORECASE)


def _finding(fid: str, severity: str, title: str, reason: str, rule: str, fix: str, source: str = "rule") -> dict:
    return {"id": fid, "severity": severity, "title": title, "reason": reason, "rule": rule, "fix": fix, "source": source}


def _spec_text(spec: dict | None) -> str:
    if not spec:
        return ""
    words = [spec.get("name", ""), spec.get("function", ""), spec.get("quote", "")]
    for part in spec.get("parts", []):
        words += [part.get("name", ""), part.get("description", ""), part.get("query", "")]
    for requirement in spec.get("requirements", []):
        words.append(requirement.get("text", ""))
    return " ".join(str(w) for w in words if w)


def _battery_wh(battery: dict) -> float:
    if battery.get("energy_wh"):
        return float(battery["energy_wh"])
    volts = float(battery.get("voltage_v") or 3.7 * int(battery.get("cells") or 1))
    return volts * float(battery.get("capacity_mah") or 0) / 1000.0


def drone_findings(state) -> list[dict]:
    findings = []
    selected = state.selected
    weight = float((state.metrics or {}).get("weight_g") or 0)
    if not weight:
        weight = sum(float(p.get("mass_g") or 0) * int(p.get("bom_qty") or 1) for p in selected.values()) + float(state.frame_mass_g or 0)
    if weight:
        rule = "EU drone classes, Delegated Regulation (EU) 2019/945 Annex; operating rules Implementing Regulation (EU) 2019/947"
        if weight < _C0_MAX_G:
            findings.append(
                _finding(
                    "drone-class",
                    "info",
                    f"EU class C0: {weight:.0f} g, under 250 g",
                    f"At {weight:.0f} g take-off mass it fits class C0 (under 250 g) in the Open category A1: no remote ID and no pilot exam. "
                    "The operator still registers (in Germany with the LBA) because the FPV camera can record people, and flies under 120 m, never over crowds.",
                    rule + ", Article 14(5) for registration",
                    "Register the operator before the first flight and put the e-ID label on the frame; keep the weight under 250 g in every revision.",
                )
            )
        elif weight < _C1_MAX_G:
            findings.append(
                _finding(
                    "drone-class",
                    "warning",
                    f"EU class C1: {weight:.0f} g, over 250 g",
                    f"At {weight:.0f} g it is over the 250 g C0 limit: class C1 needs a direct remote ID broadcast, operator registration and the online A1/A3 pilot test.",
                    rule,
                    "Get back under 250 g with a lighter battery or frame, or add a remote ID module and plan the A1/A3 test.",
                )
            )
        else:
            findings.append(
                _finding(
                    "drone-class",
                    "danger",
                    f"Over 900 g: class C2 or the Specific category",
                    f"At {weight:.0f} g it is past C1 (under 900 g): class C2 needs the A2 certificate and remote ID, over {_C2_MAX_G / 1000:.0f} kg it leaves the Open category.",
                    rule,
                    "Shrink the build below 900 g, ideally below 250 g, before ordering parts.",
                )
            )
    battery = selected.get("battery")
    if battery:
        findings.append(_battery_finding(battery))
    return findings


def _battery_finding(battery: dict) -> dict:
    wh = _battery_wh(battery)
    cells = int(battery.get("cells") or 1)
    section = "Section II (small cells)" if wh / cells <= _SECTION_II_CELL_WH and wh <= _PASSENGER_WH else "Section I (dangerous goods declaration)"
    carry = "fine as a passenger spare in hand luggage, never in checked bags" if wh <= _PASSENGER_WH else "over 100 Wh: airline approval needed even in hand luggage"
    return _finding(
        "lithium-battery",
        "warning",
        f"Lithium battery: {battery.get('name', 'LiPo')} is {wh:.1f} Wh",
        f"A {cells}S lithium polymer pack of {wh:.1f} Wh ships as dangerous goods: UN3480 alone or UN3481 packed with the drone, {section}, {carry}. "
        "A punctured or overcharged LiPo burns hot.",
        "UN 38.3 test summary; IATA Dangerous Goods Regulations PI 965 to 967; ADR special provision 188 for road",
        "Order from a shop that ships it as UN3480/UN3481 by road, charge in a LiPo bag at 1C, and store at 3.8 V per cell.",
    )


def gripper_findings(state) -> list[dict]:
    from pai_agent.tools.gripper import compute_grip

    try:
        grip = compute_grip(state)
    except ValueError:
        return []
    force = float(grip["grip_force_n"])
    opening = float(grip.get("opening_mm") or 0)
    servo = state.selected.get("servo", {})
    # Near the axis the same stall torque pinches much harder than at the fingertips.
    mesh = float(servo.get("stall_torque_kgcm") or 0) * 9.81 / 100.0 / (_GEAR_RADIUS_MM / 1000.0)
    severity = "warning" if max(force, mesh) >= _PINCH_INFO_N else "info"
    return [
        _finding(
            "pinch-point",
            severity,
            f"Pinch point: about {mesh:.0f} N at the gear mesh",
            f"{servo.get('name', 'The servo')} drives two meshing gears. The fingertips close with about {force:.0f} N on a {opening:.0f} mm opening, "
            f"but between the gear teeth, about {_GEAR_RADIUS_MM:.0f} mm from the axis, the stall torque pinches with about {mesh:.0f} N, enough to hurt a finger.",
            f"EN ISO 13857 and ISO 13854 minimum gaps (25 mm for fingers); ISO/TS 15066 Annex A hand contact limit {_HAND_TRANSIENT_N:.0f} N",
            "Print a cover over the gear mesh, limit the servo travel in the firmware so the jaws stop 4 mm apart when empty, and add a stop button on the arm.",
        )
    ]


def product_findings(state, text: str) -> list[dict]:
    findings = []
    spec = state.spec or {}
    if MAINS.search(text):
        findings.append(
            _finding(
                "mains-voltage",
                "danger",
                "Mains voltage inside a printed part",
                "The request puts 230 V AC into the product. Mains in a 3D-printed housing needs double insulation (class II), strain relief on the cord, "
                "creepage distances and a CE declaration; PETG and PLA are not rated flame-retardant.",
                "EU Low Voltage Directive 2014/35/EU (50 to 1000 V AC); EN 60598-1 for luminaires; EN 62368-1 for electronics",
                "Keep mains outside: power it from a CE-marked USB-C wall adapter so only 5 V safety extra-low voltage (SELV) enters the printed parts.",
            )
        )
    if _CHILD.search(text):
        findings.append(
            _finding(
                "small-parts",
                "warning",
                "Children: small parts are a choking hazard",
                "The product is meant for children. Any part that fits the small-parts cylinder (31.7 mm wide, 25.4 to 57.1 mm deep) is a choking hazard under 3 years.",
                "Toy Safety Directive 2009/48/EC; EN 71-1 small parts cylinder",
                "Glue or screw small parts in place, make loose parts larger than the cylinder, and label it 0 to 3 years not suitable.",
            )
        )
    if _COIN_CELL.search(text):
        findings.append(
            _finding(
                "coin-cell",
                "danger",
                "Button cell must be locked away",
                "A swallowed coin cell burns through the oesophagus within two hours.",
                "EN IEC 60086-4; EN 62368-1 Annex M",
                "Put the cell behind a door that needs a screwdriver, and print the warning on the product.",
            )
        )
    checks = list((state.checks or {}).values())
    tip = next((c for c in checks if c.get("tool") == "check_tip_over"), None)
    if tip and tip.get("result") == "fail":
        findings.append(
            _finding(
                "tip-over",
                "warning",
                "Tall product tips over",
                str(tip.get("detail") or "The tip-over check failed: the centre of mass sits too high for the footprint."),
                "EN 14749 and ASTM F2057 stability practice; the AnyBuild tip-over check",
                "Widen or deepen the base, or move mass low, then run check_tip_over again.",
            )
        )
    elif not tip and state.assembly and state.assembly.get("bbox_mm"):
        box = state.assembly["bbox_mm"]
        size = [float(box[i + 3]) - float(box[i]) for i in range(3)] if len(box) == 6 else []
        if len(size) == 3 and min(size[0], size[1]) > 0 and size[2] / min(size[0], size[1]) > 3:
            findings.append(
                _finding(
                    "tip-over",
                    "info",
                    "Tall and narrow: check it does not tip",
                    f"It stands {size[2]:.0f} mm tall on a {min(size[0], size[1]):.0f} mm footprint, more than three times its width.",
                    "EN 14749 and ASTM F2057 stability practice",
                    "Run check_tip_over with a push at the top before ordering.",
                )
            )
    thermal = next((c for c in checks if c.get("tool") == "check_thermal"), None)
    printed = [p for p in spec.get("parts", []) if p.get("kind") == "printed"]
    closed = any(_ENCLOSURE.search(str(p.get("name", "")) + " " + str(p.get("description", ""))) for p in printed)
    if thermal and thermal.get("result") == "fail":
        findings.append(
            _finding(
                "heat",
                "danger",
                "Heat builds up in the closed enclosure",
                str(thermal.get("detail") or "The thermal check failed: the air inside gets too hot."),
                "EN 62368-1 touch temperature limits; PETG softens near 80 °C, PLA near 60 °C",
                "Add vents or a fan, or lower the power inside, then run check_thermal again.",
            )
        )
    elif not thermal and closed and _HEAT_SOURCE.search(text):
        findings.append(
            _finding(
                "heat",
                "info",
                "Heat source in a closed printed part",
                "A powered part sits in a closed printed enclosure; without vents the air inside heats up.",
                "EN 62368-1 touch temperature limits; PETG softens near 80 °C, PLA near 60 °C",
                "Run check_thermal with the power inside, and add vent slots if it runs hot.",
            )
        )
    if _MECHANISM.search(text):
        findings.append(
            _finding(
                "pinch-point",
                "info",
                "Moving parts can pinch fingers",
                "The product has a mechanism (gears, a hinge or jaws) that closes on itself.",
                "EN ISO 13857 and ISO 13854 minimum gaps (25 mm for fingers)",
                "Cover gear meshes and keep closing gaps either under 4 mm or over 25 mm.",
            )
        )
    return findings


def _clean(raw: dict, index: int) -> dict | None:
    """One finding from Claude's own reasoning, in the same shape as the rule findings."""

    if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
        return None
    severity = str(raw.get("severity") or "info").lower()
    if severity not in SEVERITIES:
        severity = "info"
    return _finding(
        str(raw.get("id") or "claude-" + str(index + 1)),
        severity,
        str(raw["title"]).strip(),
        str(raw.get("reason") or "").strip(),
        str(raw.get("rule") or "Engineering judgement").strip(),
        str(raw.get("fix") or "").strip(),
        source="claude",
    )


async def safety_check(ctx: Ctx, args: dict) -> dict:
    state = ctx.state
    text = " ".join([_spec_text(state.spec), str(args.get("context") or "")])
    if state.product == "drone" and state.selected:
        findings = drone_findings(state)
    elif state.product == "gripper":
        findings = gripper_findings(state)
    else:
        findings = product_findings(state, text)
    known = {f["id"] for f in findings}
    for index, raw in enumerate(args.get("findings") or []):
        finding = _clean(raw, index)
        if finding and finding["id"] not in known:
            findings.append(finding)
            known.add(finding["id"])
    findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    label = (state.spec or {}).get("name") or {"drone": "the drone", "gripper": "the gripper"}.get(state.product, "the product")
    top = findings[0] if findings else None
    summary = (
        f"{len(findings)} safety note(s) for {label}: " + ", ".join(f"{n} {s}" for s, n in counts.items() if n)
        if findings
        else f"No safety rule fired for {label}."
    )
    await ctx.emit(
        {
            "type": "safety",
            "product": state.product,
            "label": label,
            "findings": findings,
            "summary": summary,
            "disclaimer": DISCLAIMER,
        }
    )
    return {
        "ok": True,
        "detail": summary,
        "findings": findings,
        "top": top,
        "disclaimer": DISCLAIMER,
        "next": "Tell the team the top finding honestly, worded as a hint, and apply its fix before ordering if it changes the design.",
    }


SCHEMA = {
    "name": "safety_check",
    "description": "Flags safety and regulatory issues before anyone orders parts: EU drone class (C0 under 250 g, registration, remote ID), lithium battery shipping, mains voltage, pinch points, tip-over, heat in closed enclosures and small parts for children. "
    "The rule set reads the current build; add your own findings over the spec and parts in findings. Pass the user's request or any power details in context. "
    "Call it before bom_build, then tell the team the top finding honestly as a hint, not legal advice, and apply its fix if it changes the design.",
    "input_schema": {
        "type": "object",
        "properties": {
            "context": {"type": "string", "description": "The request and power or use details the rules should read, e.g. 'runs on 230 V mains'."},
            "findings": {
                "type": "array",
                "description": "Your own findings beyond the rule set.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "severity": {"type": "string", "enum": list(SEVERITIES)},
                        "title": {"type": "string"},
                        "reason": {"type": "string"},
                        "rule": {"type": "string", "description": "The standard, regulation or source the finding rests on."},
                        "fix": {"type": "string", "description": "A concrete change the agent can apply."},
                    },
                    "required": ["severity", "title", "reason", "rule", "fix"],
                },
            },
        },
    },
}
