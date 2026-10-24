"""FreeCAD builds: in the open FreeCAD window over freecad-mcp when it answers, else headless freecadcmd."""

from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import time
import xmlrpc.client
from pathlib import Path

from pai_agent.mesh_export import stl_to_glb
from pai_agent.paths import AGENT_ROOT

_SCRIPT = AGENT_ROOT / "freecad" / "frame_build.py"
def _rpc_url() -> str:
    # Read on use, so a value from agent/.env (loaded at startup) counts.
    return os.environ.get("FREECAD_MCP_URL", "").strip() or "http://127.0.0.1:9875"


class _TimeoutTransport(xmlrpc.client.Transport):
    """An XML-RPC transport with its own timeout, instead of changing the process-wide socket default."""

    def __init__(self, timeout: float) -> None:
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        connection = super().make_connection(host)
        connection.timeout = self._timeout
        return connection
_KNOWN_CMD = Path("/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd")
_DENSITY = 1.24 / 1000.0


class FreeCADFailed(Exception):
    pass


def find_freecadcmd() -> str | None:
    if _KNOWN_CMD.is_file() and os.access(_KNOWN_CMD, os.X_OK):
        return str(_KNOWN_CMD)
    for name in ("freecadcmd", "FreeCADCmd"):
        found = _which(name)
        if found:
            return found
    root = Path("/Applications/FreeCAD.app")
    if not root.is_dir():
        return None
    for name in ("freecadcmd", "FreeCADCmd"):
        for path in root.rglob(name):
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def _which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def build_with_freecad(directory: Path, params: dict) -> float:
    binary = find_freecadcmd()
    if binary is None:
        raise FreeCADFailed("freecadcmd fehlt")
    directory.mkdir(parents=True, exist_ok=True)
    params_path = directory / "cad_params.json"
    params_path.write_text(json.dumps(params), encoding="utf-8")
    env = os.environ.copy()
    env["PAI_FREECAD_PARAMS"] = str(params_path)
    env["PAI_FREECAD_OUT"] = str(directory)
    completed = subprocess.run(
        [binary, str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=env,
    )
    result_path = directory / "freecad_result.json"
    if not result_path.is_file():
        tail = (completed.stderr or completed.stdout or "kein Ergebnis").strip()[-400:]
        raise FreeCADFailed(tail)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("ok"):
        raise FreeCADFailed(str(result.get("error") or "FreeCAD-Skript fehlgeschlagen"))
    stl = directory / "frame.stl"
    step = directory / "frame.step"
    if not stl.is_file() or not step.is_file():
        raise FreeCADFailed("FreeCAD hat STL oder STEP nicht geschrieben")
    if not (directory / "frame.glb").is_file():
        stl_to_glb(stl, directory / "frame.glb")
    return float(result["mass_g"])


def gui_mode() -> str:
    """FREECAD_GUI: auto uses an open FreeCAD window, launch opens FreeCAD first, off stays headless."""

    mode = os.environ.get("FREECAD_GUI", "").strip().lower() or "auto"
    return mode if mode in {"auto", "launch", "off"} else "auto"


def rpc_available(wait_s: float = 0.0) -> bool:
    host, port = _rpc_host_port()
    deadline = time.monotonic() + wait_s
    while True:
        try:
            with socket.create_connection((host, port), 0.3):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)


def ensure_gui() -> bool:
    """True when the freecad-mcp RPC answers; with FREECAD_GUI=launch, opens FreeCAD and waits for it."""

    mode = gui_mode()
    if mode == "off":
        return False
    if rpc_available():
        return True
    if mode != "launch" or not Path("/Applications/FreeCAD.app").is_dir():
        return False
    subprocess.Popen(["open", "-g", "-a", "FreeCAD"])
    return rpc_available(wait_s=40)


_GUI_STEP_S = 0.35


def build_in_gui(directory: Path, params: dict, version: int, progress=None) -> float:
    """Builds the frame feature by feature in the open FreeCAD window, so the room watches it grow.

    Uses the freecad-mcp add-on's execute_code on 127.0.0.1:9875. Any error or timeout raises
    FreeCADFailed, and the caller falls back to the headless build.
    """

    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "freecad_result.json"
    result_path.unlink(missing_ok=True)
    arm = float(params["arm_length_mm"])
    thick = float(params["thickness_mm"])
    bolt = float(params["motor_spacing_mm"]) / 2.0
    doc = "Bauplan_v" + str(version)
    head = "import FreeCAD as App\nimport FreeCADGui as Gui\nimport math\ndoc = App.getDocument(" + repr(doc) + ")\n"
    view = "Gui.getDocument(doc.Name).ActiveView.fitAll()\n"
    steps: list[tuple[str, str]] = [
        (
            "neues Dokument",
            "import FreeCAD as App\nimport FreeCADGui as Gui\n"
            "for name in list(App.listDocuments()):\n"
            "    if name.startswith('Bauplan'):\n"
            "        App.closeDocument(name)\n"
            "doc = App.newDocument(" + repr(doc) + ")\n"
            "App.setActiveDocument(doc.Name)\n"
            "Gui.ActiveDocument = Gui.getDocument(doc.Name)\n"
            "Gui.getDocument(doc.Name).ActiveView.viewIsometric()\n",
        ),
        (
            "Nabe",
            head
            + "hub = doc.addObject('Part::Cylinder', 'Nabe')\n"
            + f"hub.Radius = 20\nhub.Height = {thick}\n"
            + "doc.recompute()\n"
            + view,
        ),
    ]
    for index in range(4):
        angle = index * 90
        steps.append(
            (
                f"Arm {index + 1} von 4",
                head
                + f"a = math.radians({angle})\n"
                + f"arm = doc.addObject('Part::Box', 'Arm{index + 1}')\n"
                + f"arm.Length = {arm + 6}\narm.Width = 6\narm.Height = {thick}\n"
                + f"arm.Placement = App.Placement(App.Vector(3 * math.sin(a), -3 * math.cos(a), 0), App.Rotation(App.Vector(0, 0, 1), {angle}))\n"
                + f"pad = doc.addObject('Part::Cylinder', 'Motorauflage{index + 1}')\n"
                + f"pad.Radius = 6\npad.Height = {thick}\n"
                + f"pad.Placement.Base = App.Vector({arm} * math.cos(a), {arm} * math.sin(a), 0)\n"
                + "doc.recompute()\n"
                + view,
            )
        )
    holes = [(0.0, 0.0, 2.2)] + [(13.0 * sx, 13.0 * sy, 1.1) for sx in (-1, 1) for sy in (-1, 1)]
    for index in range(4):
        rad = math.radians(index * 90)
        cx, cy = arm * math.cos(rad), arm * math.sin(rad)
        holes.append((cx, cy, 1.0))
        for hole in range(3):
            angle = math.radians(index * 90 + hole * 120)
            holes.append((cx + bolt * math.cos(angle), cy + bolt * math.sin(angle), 0.8))
    steps.append(
        (
            "Bohrungen",
            head
            + "import Part\n"
            + "parts = [doc.getObject(n) for n in ['Nabe'] + ['Arm%d' % i for i in range(1, 5)] + ['Motorauflage%d' % i for i in range(1, 5)]]\n"
            + "base = doc.addObject('Part::MultiFuse', 'Grundform')\nbase.Shapes = parts\n"
            + "cutters = [Part.makeCylinder(r, "
            + str(thick + 2)
            + ", App.Vector(x, y, -1)) for x, y, r in "
            + repr(holes)
            + "]\n"
            + "tool = doc.addObject('Part::Feature', 'Bohrungen')\ntool.Shape = Part.makeCompound(cutters)\n"
            + "frame = doc.addObject('Part::Cut', 'Rahmen')\nframe.Base = base\nframe.Tool = tool\n"
            + "doc.recompute()\n"
            + "for obj in parts + [base, tool]:\n    obj.ViewObject.Visibility = False\n"
            + "frame.ViewObject.ShapeColor = (1.0, 0.54, 0.24)\n"
            + view,
        )
    )
    steps.append(
        (
            "Speichern und exportieren",
            head
            + "import json\nimport Mesh\nimport Part\n"
            + "frame = doc.getObject('Rahmen')\n"
            + f"doc.saveAs({str(directory / 'frame.FCStd')!r})\n"
            + f"Part.export([frame], {str(directory / 'frame.step')!r})\n"
            + f"Mesh.export([frame], {str(directory / 'frame.stl')!r})\n"
            + f"open({str(result_path)!r}, 'w').write(json.dumps({{'ok': True, 'mass_g': round(frame.Shape.Volume * {_DENSITY}, 2)}}))\n"
            + "Gui.getDocument(doc.Name).ActiveView.viewIsometric()\n"
            + view,
        )
    )

    try:
        proxy = xmlrpc.client.ServerProxy(_rpc_url(), allow_none=True, transport=_TimeoutTransport(15))
        for label, code in steps:
            if progress:
                progress("FreeCAD: " + label)
            answer = proxy.execute_code(code, 12)
            if not isinstance(answer, dict) or not answer.get("success"):
                message = answer.get("error") or answer.get("message") if isinstance(answer, dict) else str(answer)
                raise FreeCADFailed("FreeCAD-Fenster: " + label + ": " + str(message)[:300])
            time.sleep(_GUI_STEP_S)
        try:
            shot = proxy.get_active_screenshot("Isometric", 1280, 720, "Rahmen")
            if shot:
                _store_image(directory / "view.png", shot)
        except Exception:
            pass
    except (OSError, xmlrpc.client.Error) as exc:
        raise FreeCADFailed("FreeCAD-Fenster antwortet nicht: " + str(exc)) from exc
    if not result_path.is_file():
        raise FreeCADFailed("FreeCAD-Fenster hat kein Ergebnis geschrieben")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    stl = directory / "frame.stl"
    if not stl.is_file() or not (directory / "frame.step").is_file():
        raise FreeCADFailed("FreeCAD-Fenster hat STL oder STEP nicht geschrieben")
    stl_to_glb(stl, directory / "frame.glb")
    return float(result["mass_g"])


def open_in_freecad(path: Path) -> None:
    app = Path("/Applications/FreeCAD.app")
    if app.is_dir():
        subprocess.Popen(["open", "-a", "FreeCAD", str(path)])
        return
    binary = _which("freecad") or _which("FreeCAD")
    if binary:
        subprocess.Popen([binary, str(path)])
        return
    raise FreeCADFailed("FreeCAD ist nicht installiert")


def _rpc_host_port() -> tuple[str, int]:
    raw = _rpc_url().split("://", 1)[-1].split("/", 1)[0]
    if ":" in raw:
        host, port = raw.rsplit(":", 1)
        return host, int(port)
    return raw, 9875


def _store_image(dest: Path, payload: object) -> bool:
    data = payload
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("image") or payload.get("png")
        path = payload.get("path")
        if isinstance(path, str) and Path(path).is_file():
            dest.write_bytes(Path(path).read_bytes())
            return True
    if isinstance(data, str):
        import base64

        dest.write_bytes(base64.b64decode(data))
        return dest.stat().st_size > 32
    if isinstance(data, (bytes, bytearray)):
        dest.write_bytes(bytes(data))
        return dest.stat().st_size > 32
    return False
