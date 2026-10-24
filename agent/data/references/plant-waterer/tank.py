import FreeCAD
import Part

V = FreeCAD.Vector

W = P.get("width_mm", 110.0)
D = P.get("depth_mm", 110.0)
H = P.get("height_mm", 100.0)
T = P.get("wall_mm", 2.0)
Z0 = 30.0

outer = Part.makeBox(W, D, H, V(-W / 2.0, -D / 2.0, Z0))
inner = Part.makeBox(W - 2 * T, D - 2 * T, H - T + 1.0, V(-W / 2.0 + T, -D / 2.0 + T, Z0 + T))
tank = outer.cut(inner)

# U-shaped notch in the top of the front wall (-Y): 10 wide, 5 deep, at X=-40
nw = 10.0
nd = 5.0
ztop = Z0 + H
nx = -40.0
notch = Part.makeBox(nw, T + 2.0, nd + 1.0, V(nx - nw / 2.0, -D / 2.0 - 1.0, ztop - nd + nw / 2.0))
# rounded bottom of the U
notch = Part.makeBox(nw, T + 2.0, nd - nw / 2.0 + 1.0, V(nx - nw / 2.0, -D / 2.0 - 1.0, ztop - nd + nw / 2.0))
cyl = Part.makeCylinder(nw / 2.0, T + 2.0, V(nx, -D / 2.0 - 1.0, ztop - nd + nw / 2.0), V(0, 1, 0))
notch = notch.fuse(cyl)
tank = tank.cut(notch)

shape = tank
