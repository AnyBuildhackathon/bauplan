"""Manufacturer and library STEP models: read with their colours, turned into the part frame, as pieces.

The part frame is millimetres, Z up, centred on the footprint with the bottom at z = 0. Faces are
grouped by colour into one piece each, which keeps the GLB small and the real colours.
"""

from __future__ import annotations

from pathlib import Path

import cadquery as cq

from .glb import Finish
from .model import Model


def _colour_hex(colour) -> str:
    """A STEP colour (stored linear) as the sRGB #rrggbb a person would see."""

    from OCP.Quantity import Quantity_TOC_sRGB

    values = colour.Values(Quantity_TOC_sRGB)
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c * 255)))) for c in values)


def read_step_faces(path: Path) -> list[tuple[cq.Shape, str]]:
    """Every face of the STEP file in world position with its colour (#rrggbb, grey when unset)."""

    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Quantity import Quantity_Color, Quantity_TOC_sRGB
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_ColorCurv, XCAFDoc_ColorGen, XCAFDoc_ColorSurf, XCAFDoc_ColorTool, XCAFDoc_DocumentTool

    document = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError("Cannot read STEP: " + str(path))
    reader.Transfer(document)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    colours = XCAFDoc_DocumentTool.ColorTool_s(document.Main())
    result: list[tuple[cq.Shape, str]] = []

    def colour_of(label=None, shape=None) -> str | None:
        colour = Quantity_Color()
        for kind in (XCAFDoc_ColorSurf, XCAFDoc_ColorGen, XCAFDoc_ColorCurv):
            if label is not None and XCAFDoc_ColorTool.GetColor_s(label, kind, colour):
                return _colour_hex(colour)
            if shape is not None and colours.GetColor(shape, kind, colour):
                return _colour_hex(colour)
        return None

    def walk(label, location: TopLoc_Location, inherited: str | None) -> None:
        if shapes.IsReference_s(label):
            target = TDF_Label()
            shapes.GetReferredShape_s(label, target)
            walk(target, location.Multiplied(shapes.GetLocation_s(label)), colour_of(label) or inherited)
            return
        own = colour_of(label) or inherited
        if shapes.IsAssembly_s(label):
            children = TDF_LabelSequence()
            shapes.GetComponents_s(label, children)
            for i in range(1, children.Length() + 1):
                walk(children.Value(i), location, own)
            return
        shape = shapes.GetShape_s(label)
        subs = TDF_LabelSequence()
        shapes.GetSubShapes_s(label, subs)
        face_colours: list = []
        for i in range(1, subs.Length() + 1):
            sub = subs.Value(i)
            colour = colour_of(sub)
            if colour:
                sub_shape = shapes.GetShape_s(sub)
                explorer = TopExp_Explorer(sub_shape, TopAbs_FACE)
                while explorer.More():
                    face_colours.append((explorer.Current(), colour))
                    explorer.Next()
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            face = explorer.Current()
            colour = colour_of(shape=face) or own or "#9a9ca0"
            for candidate, sub_colour in face_colours:
                if candidate.IsSame(face):
                    colour = sub_colour
                    break
            result.append((cq.Shape.cast(face.Moved(location)), colour))
            explorer.Next()

    roots = TDF_LabelSequence()
    shapes.GetFreeShapes(roots)
    for i in range(1, roots.Length() + 1):
        walk(roots.Value(i), TopLoc_Location(), None)
    return result


def official_model(p: dict, step_path: Path) -> Model:
    """The official STEP as a part model in the part frame; `rotate` turns it first ([x, y, z] degrees)."""

    faces = read_step_faces(step_path)
    groups: dict[str, list[cq.Shape]] = {}
    for face, colour in faces:
        groups.setdefault(colour, []).append(face)
    compound = cq.Compound.makeCompound([face for face, _ in faces])
    rx, ry, rz = p.get("rotate", [0.0, 0.0, 0.0])

    def turned(shape: cq.Shape) -> cq.Shape:
        for axis, angle in (((1, 0, 0), rx), ((0, 1, 0), ry), ((0, 0, 1), rz)):
            if angle:
                shape = shape.rotate(cq.Vector(0, 0, 0), cq.Vector(*axis), angle)
        return shape

    box = turned(compound).BoundingBox()
    shift = cq.Vector(-(box.xmin + box.xmax) / 2, -(box.ymin + box.ymax) / 2, -box.zmin)
    m = Model(p["id"])
    overrides = p.get("colors", {})
    for index, (colour, members) in enumerate(sorted(groups.items(), key=lambda item: -len(item[1]))):
        shape = turned(cq.Compound.makeCompound(members)).translate(shift)
        shown = overrides.get(colour, colour)
        metallic = 0.9 if _is_metal(shown) else 0.0
        m.add(f"body_{index + 1}" if index else "body", shape, Finish(shown, metallic, 0.35 if metallic else 0.5))
    return m


def _is_metal(colour: str) -> bool:
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return abs(r - g) < 14 and abs(g - b) < 14 and 150 < r < 235 or (r > 180 and g > 140 and b < 90)
