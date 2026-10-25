"""Names shared with the 3D scene.

The wire list lives in docs/events.md. Keep this tuple identical to that list.
"""

PART_TARGETS = (
    "frame",
    "motor_front_left",
    "motor_front_right",
    "motor_rear_left",
    "motor_rear_right",
    "propeller_front_left",
    "propeller_front_right",
    "propeller_rear_left",
    "propeller_rear_right",
    "battery",
    "flight_controller",
)

UI_TARGETS = (
    "requirements",
    "metrics",
    "timeline",
    "viewport",
    "chat",
)

TARGETS = PART_TARGETS + UI_TARGETS

STEPS = (
    ("meeting", "Spec"),
    ("teile", "Parts"),
    ("cad", "CAD"),
    ("render", "Render"),
    ("simulation", "Simulation"),
    ("training", "Training"),
    ("stueckliste", "BOM"),
)

STEP_LABELS = dict(STEPS)

MASCOT_STATES = ("ruhig", "denkt", "erklaert", "freut_sich", "besorgt")
DRAW_KINDS = ("halo", "arrow", "circle", "note")

PART_CATEGORIES = (
    "motor",
    "propeller",
    "battery",
    "flight_controller",
    "frame",
    "camera",
    "canopy",
    "hardware",
    "vtx",
)

# Dashboard controls Mechanic can operate (tool ui_control, event `ui`). Each id is the
# `data-control` of the real on-screen control the pointer flies to before it acts.
# The wire list lives in docs/events.md; `library:{id}` opens one library item.
CONTROLS = {
    "tab:model": "Model tab, the live 3D model",
    "tab:cad": "CAD tab, the FreeCAD part with its feature tree and sliders",
    "tab:simulation": "Simulation tab, the MuJoCo test replays",
    "tab:omniverse": "Omniverse tab, the Isaac Sim results (drone only)",
    "view:workbench": "the Workbench, the main screen",
    "view:library": "the Library of reference builds",
    "view:training": "the Training view",
    "view:logbook": "the Logbook with every version",
    "panel:bom": "the bill of materials drawer (open true or false)",
    "panel:guide": "the step-by-step build guide (open true or false)",
    "panel:compare": "version compare, two versions side by side (versions [a, b])",
    "panel:settings": "the settings panel (open true or false)",
    "setting:agents": "setting: show agent steps and costs (value true or false)",
    "setting:tools": "setting: show tool details (value true or false)",
    "setting:all_metrics": "setting: show all metrics (value true or false)",
    "setting:push_to_talk": "setting: push-to-talk instead of hands-free (value true or false)",
    "setting:voice": "Mechanic's voice on or off (value true or false)",
    "explode": "the explode slider in the Model tab: value 0 (assembled) to 100 (every part pulled apart)",
    "focus": "turn the 3D camera to one part (part: a part name or id)",
    "run:test": "run the product's MuJoCo test again",
    "run:rebuild": "rebuild the CAD and rerun the checks",
}
