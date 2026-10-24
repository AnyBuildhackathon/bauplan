# Bottom shell of a Raspberry Pi 5 case: an open box with wall_mm walls, four M2.5
# standoffs on the Pi hole pattern (58 x 49 mm) and cut-outs for USB-C, the two
# micro HDMI ports and the USB/Ethernet end. Units are mm, Z is up, -Y is the front.
W = P.get("width_mm", 95.0)
D = P.get("depth_mm", 70.0)
H = P.get("height_mm", 27.0)
T = P.get("wall_mm", 2.0)

shell = Part.makeBox(W, D, H, Vector(-W / 2.0, -D / 2.0, 0))
shell = shell.cut(Part.makeBox(W - 2 * T, D - 2 * T, H, Vector(-W / 2.0 + T, -D / 2.0 + T, T)))
for x in (-29.0, 29.0):
    for y in (-24.5, 24.5):
        post = Part.makeCylinder(3.0, 4.0, Vector(x - 3.5, y, T))
        shell = shell.fuse(post.cut(Part.makeCylinder(1.25, 4.0, Vector(x - 3.5, y, T))))
# USB-C power and the two micro HDMI ports on the front wall.
for x, w in ((-30.0, 11.0), (-15.0, 9.0), (-1.5, 9.0)):
    shell = shell.cut(Part.makeBox(w, T + 2.0, 6.0, Vector(x - w / 2.0, -D / 2.0 - 1.0, T + 5.0)))
# USB and Ethernet end on the right wall.
shell = shell.cut(Part.makeBox(T + 2.0, 54.0, 16.0, Vector(W / 2.0 - T - 1.0, -27.0, T + 4.0)))
shape = shell.removeSplitter()
