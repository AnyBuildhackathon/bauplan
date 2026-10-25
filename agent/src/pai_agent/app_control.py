"""Spoken or typed dashboard commands: "show me the CAD", "pull it apart", "compare v1 and v2".

A short message that only asks to see or open something never needs the engineering
model: it becomes ui_control calls right away, also while a build runs. Anything that
changes the design ("make the arm longer") is left to the orchestrator, which has the
same tool for the requests these patterns miss.
"""

from __future__ import annotations

import re

from pai_agent.scene import PART_TARGETS
from pai_agent.state import BuildState

# A command is short; a longer message is a design conversation.
_MAX_WORDS = 16
# A question or an engineering verb means the person wants more than the screen: the orchestrator answers.
_CONVERSE = re.compile(
    r"\b(why|explain|what|which|how much|tell me|load|start from|create|design|build(?! guide)|make|change|increase|decrease|"
    r"swap|replace|add|remove|longer|shorter|lighter|heavier|bigger|smaller|stronger|cheaper|thicker|thinner|wider|narrower)\b",
    re.I,
)
# Product words and units: a design request, unless the command is about the model itself (a library item's name).
_DESIGN = re.compile(r"\b(mm|grams?|euros?|minutes?|stand|holder|mount|fan|robot|lamp)\b", re.I)
_OFF = re.compile(r"\b(close|hide|turn off|switch off|disable|stop showing|schlie(ss|ß)|aus\b|zu\b|weg\b)", re.I)

_PARTS = {
    "battery": r"batter(y|ie)|akku|lipo|pack",
    "frame": r"frame|rahmen|arms?",
    "motor_front_left": r"motors?|motoren",
    "propeller_front_left": r"propellers?|props?|rotors?",
    "flight_controller": r"flight controller|controller|fc\b|flugcontroller",
}
assert set(_PARTS) <= set(PART_TARGETS)


def _wants_off(text: str) -> bool:
    return bool(_OFF.search(text))


def _explode(text: str, match: re.Match) -> dict:
    if re.search(r"back together|reassembl|put it together|collapse|zusammen", match.group(0), re.I):
        return {"control": "explode", "value": 0}
    percent = re.search(r"(\d{1,3})\s*(%|percent|prozent)", text, re.I)
    value = 50 if re.search(r"\bhalf(way)?\b|halb", text, re.I) else 100
    if percent:
        value = min(100, int(percent[1]))
    return {"control": "explode", "value": value}


def _compare(text: str, _match: re.Match) -> dict:
    numbers = [int(n) for n in re.findall(r"\b(?:v|version\s*)(\d+)\b", text, re.I)]
    args: dict = {"control": "panel:compare"}
    if _wants_off(text):
        return {**args, "open": False}
    if len(numbers) >= 2:
        args["versions"] = numbers[:2]
    return args


def _setting(name: str):
    def build(text: str, _match: re.Match) -> dict:
        return {"control": "setting:" + name, "value": not _wants_off(text)}

    return build


def _voice(text: str, match: re.Match) -> dict:
    on = bool(re.search(r"unmute|speak again|talk again|voice on", match.group(0), re.I))
    return {"control": "setting:voice", "value": on}


def _panel(name: str):
    def build(text: str, _match: re.Match) -> dict:
        return {"control": "panel:" + name, "open": not _wants_off(text)}

    return build


def _fixed(control: str):
    return lambda _text, _match: {"control": control}


def _focus(_text: str, match: re.Match) -> dict:
    word = match.group("part")
    for target, pattern in _PARTS.items():
        if re.fullmatch(pattern, word, re.I):
            return {"control": "focus", "part": target}
    return {"control": "focus", "part": word}


_SHOW = r"(show|open|see|go to|switch to|bring up|zeig|öffne|oeffne)"

# Order matters only for ties; commands run in the order they appear in the message.
_PATTERNS: list[tuple[re.Pattern, object]] = [
    (re.compile(r"\b(pull|take|break|blow|split|tear)\b[\w\s]{0,14}\bapart\b|\bexplod\w*|reverse.engineer\w*|auseinander\w*|zerleg\w*|"
                r"\bput it back together\b|\breassembl\w*|\bcollapse it\b|\bzusammen\w*", re.I), _explode),
    (re.compile(r"\bcompar(e|ison)\b|\bvergleich\w*|side by side|\bdiff(erence)? between\b", re.I), _compare),
    (re.compile(r"bill of materials|\bbom\b|parts list|shopping list|st(ü|ue)ckliste", re.I), _panel("bom")),
    (re.compile(r"build guide|assembly guide|assembly instructions|bauanleitung|how (do i|to) (build|assemble) it", re.I), _panel("guide")),
    (re.compile(r"\bagent (steps|costs?)\b", re.I), _setting("agents")),
    (re.compile(r"\btool (details|cards)\b", re.I), _setting("tools")),
    (re.compile(r"\ball (the )?(metrics|numbers|key numbers)\b", re.I), _setting("all_metrics")),
    (re.compile(r"push.to.talk", re.I), _setting("push_to_talk")),
    (re.compile(r"\b(unmute|mute|be quiet|stop talking|speak again|talk again|voice (on|off))\b", re.I), _voice),
    (re.compile(r"\bsettings\b|einstellungen", re.I), _panel("settings")),
    (re.compile(r"\blogbook\b|\blog book\b|logbuch", re.I), _fixed("view:logbook")),
    (re.compile(r"\blibrary\b|bibliothek|reference builds", re.I), _fixed("view:library")),
    (re.compile(r"\bworkbench\b|werkbank|main screen|\bgo back\b", re.I), _fixed("view:workbench")),
    (re.compile(_SHOW + r"\b[\w\s]{0,12}\btraining\b", re.I), _fixed("view:training")),
    (re.compile(r"\b(cad|freecad)\b", re.I), _fixed("tab:cad")),
    (re.compile(_SHOW + r"\b[\w\s]{0,12}\bomniverse\b|\bomniverse tab\b", re.I), _fixed("tab:omniverse")),
    (re.compile(r"\bsimulation\b|\bsim tab\b|\breplay\b", re.I), _fixed("tab:simulation")),
    (re.compile(r"\b(3d )?model\b|\bmodell\b", re.I), _fixed("tab:model")),
    (re.compile(r"\b(focus|zoom|look|point)\b (in )?(on|at) (the )?(?P<part>[a-z][a-z ]{1,24}?)\s*(\.|\?|!|$|please)", re.I), _focus),
    (re.compile(r"^\s*(please )?(re-?run|run|start|redo|repeat)( the)?( (hover|grip|push|mujoco))? (test|simulation)( again| now)?( please)?[.!]?\s*$", re.I), _fixed("run:test")),
    (re.compile(r"^\s*(please )?(rebuild|build it again|bau (es |ihn |sie )?neu)( it)?( again| now)?( please)?[.!]?\s*$", re.I), _fixed("run:rebuild")),
]

# A run or a test on Omniverse, a stress test or a training run is engineering, not navigation.
_ENGINEERING = re.compile(r"\b(stress|robust|wind|gusts?|payload|isaac|train(ing)? (it|the|a)|hover stability)\b", re.I)


def _library_item(text: str) -> dict | None:
    from pai_agent.references import list_references

    lowered = text.lower()
    for row in list_references():
        if row["name"].lower() in lowered or row["id"].replace("-", " ") in lowered:
            return {"control": "library:" + row["id"]}
    return None


def match_commands(text: str, state: BuildState) -> list[dict]:
    """The ui_control calls this message asks for, or [] when it is not a pure dashboard command."""

    words = text.split()
    if not words or len(words) > _MAX_WORDS or _ENGINEERING.search(text) or _CONVERSE.search(text):
        return []
    found: list[tuple[int, dict]] = []
    for pattern, build in _PATTERNS:
        match = pattern.search(text)
        if match:
            found.append((match.start(), build(text, match)))  # type: ignore[operator]
    if not found:
        return []
    controls = [args["control"] for _pos, args in found]
    # "Pull it apart" or "focus on the battery" already open the model; "compare" is not the CAD tab.
    if "explode" in controls or "focus" in controls:
        found = [(p, a) for p, a in found if a["control"] != "tab:model"]
    if "panel:guide" in controls:
        found = [(p, a) for p, a in found if a["control"] != "panel:bom"]
    if "view:library" in controls:
        item = _library_item(text)
        if item:
            found = [(p, item if a["control"] == "view:library" else a) for p, a in found]
    if any(a["control"].startswith("setting:") for _p, a in found):
        found = [(p, a) for p, a in found if a["control"] != "panel:settings"]
    # A design request that happens to name a tab ("make the CAD arm longer") goes to the orchestrator.
    if _DESIGN.search(text) and not any(a["control"] in {"explode", "panel:compare"} or a["control"].startswith("library:") for _p, a in found):
        return []
    found.sort(key=lambda item: item[0])
    seen: set[str] = set()
    out = []
    for _pos, args in found:
        if args["control"] in seen:
            continue
        seen.add(args["control"])
        out.append(args)
    return out


def describe(commands: list[dict]) -> str:
    """One line for the voice model: what is happening on screen."""

    parts = []
    for args in commands:
        control = args["control"]
        if control == "explode":
            parts.append("pulling the model apart" if args.get("value", 100) else "putting the model back together")
        elif control == "panel:compare":
            versions = args.get("versions")
            parts.append("comparing versions " + " and ".join(str(n) for n in versions) if versions else "comparing the last two versions")
        elif control == "focus":
            parts.append("turning the camera to the " + str(args.get("part", "")).replace("_", " "))
        elif control.startswith("setting:"):
            parts.append(("turning on " if args.get("value") else "turning off ") + control[8:].replace("_", " "))
        elif control.startswith("panel:"):
            parts.append(("opening the " if args.get("open", True) else "closing the ") + control[6:])
        else:
            parts.append("opening " + control.split(":", 1)[-1].replace("_", " "))
    return ", ".join(parts)
