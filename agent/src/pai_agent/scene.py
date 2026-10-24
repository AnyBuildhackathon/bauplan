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
    ("meeting", "Meeting"),
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
)
