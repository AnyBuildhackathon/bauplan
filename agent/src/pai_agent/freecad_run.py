"""FreeCAD builds: in the open FreeCAD window over freecad-mcp when it answers, else headless freecadcmd."""

from __future__ import annotations

import json
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
# The stages of frame_build.py, in order; the window shows each one as it lands.
_STAGES = ("Frame plate", "Prop ducts", "Motors", "Propellers", "Flight controller", "Battery and strap", "Antenna")


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
        raise FreeCADFailed("freecadcmd is missing")
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
        tail = (completed.stderr or completed.stdout or "no result").strip()[-400:]
        raise FreeCADFailed(tail)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("ok"):
        raise FreeCADFailed(str(result.get("error") or "FreeCAD script failed"))
    stl = directory / "frame.stl"
    step = directory / "frame.step"
    if not stl.is_file() or not step.is_file():
        raise FreeCADFailed("FreeCAD did not write STL or STEP")
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
    """Builds the drone stage by stage in the open FreeCAD window, so the room watches it grow.

    Every stage runs freecad/frame_build.py's own run_stage through the freecad-mcp add-on's
    execute_code on 127.0.0.1:9875, so the window builds exactly what the headless path builds.
    Any error or timeout raises FreeCADFailed, and the caller falls back to the headless build.
    """

    directory.mkdir(parents=True, exist_ok=True)
    result_path = directory / "freecad_result.json"
    result_path.unlink(missing_ok=True)
    doc = "AnyBuild_v" + str(version)
    load = (
        "import json\nimport runpy\nimport FreeCAD as App\nimport FreeCADGui as Gui\n"
        + "builder = runpy.run_path(" + repr(str(_SCRIPT)) + ", run_name='pai_gui')\n"
        + "params = json.loads(" + repr(json.dumps(params)) + ")\n"
        + "doc = App.getDocument(" + repr(doc) + ")\n"
    )
    view = "Gui.getDocument(doc.Name).ActiveView.fitAll()\n"
    steps: list[tuple[str, str]] = [
        (
            "New document",
            "import FreeCAD as App\nimport FreeCADGui as Gui\n"
            "for name in list(App.listDocuments()):\n"
            "    if name.startswith(('Bauplan', 'AnyBuild')):\n"
            "        App.closeDocument(name)\n"
            "doc = App.newDocument(" + repr(doc) + ")\n"
            "App.setActiveDocument(doc.Name)\n"
            "Gui.ActiveDocument = Gui.getDocument(doc.Name)\n"
            "Gui.getDocument(doc.Name).ActiveView.viewIsometric()\n",
        )
    ]
    for index, label in enumerate(_STAGES):
        steps.append((label, load + "builder['run_stage'](doc, params, " + str(index) + ")\n" + view))
    steps.append(
        (
            "save and export",
            load
            + "mass = builder['export'](doc, params, "
            + repr(str(directory))
            + ")\n"
            + "open("
            + repr(str(result_path))
            + ", 'w').write(json.dumps({'ok': True, 'mass_g': round(mass, 2)}))\n"
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
                raise FreeCADFailed("FreeCAD window: " + label + ": " + str(message)[:300])
            time.sleep(_GUI_STEP_S)
        try:
            shot = proxy.get_active_screenshot("Isometric", 1280, 720, "Frame")
            if shot:
                _store_image(directory / "view.png", shot)
        except Exception:
            pass
    except (OSError, xmlrpc.client.Error) as exc:
        raise FreeCADFailed("FreeCAD window does not answer: " + str(exc)) from exc
    if not result_path.is_file():
        raise FreeCADFailed("FreeCAD window wrote no result")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    for name in ("frame.stl", "frame.step", "frame.glb"):
        if not (directory / name).is_file():
            raise FreeCADFailed("FreeCAD window did not write " + name)
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
    raise FreeCADFailed("FreeCAD is not installed")


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
