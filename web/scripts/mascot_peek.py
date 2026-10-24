"""Cut the start screen's peeking Mechanic out of the full figures.

Run from the repo root: uv run --with pillow python web/scripts/mascot_peek.py
Writes web/public/mascot-peek/head.webp and fingers.webp. MechanicPeek.tsx places them
with the sizes printed here, so change both together.
"""

from pathlib import Path

from PIL import Image, ImageFilter

WEB = Path(__file__).resolve().parent.parent
MASCOT = WEB / "public/mascot"
OUT = WEB / "public/mascot-peek"

# full-calm.webp (640 x 820): hair top to just below the shirt collar.
HEAD = (196, 22, 444, 266)

# The art has no hand seen from the back, so the fingers are built from one digit: the
# thumb of the open hand in full-talking.webp, turned upright and flipped to point down.
OPEN_HAND = (90, 250, 170, 350)
UPRIGHT = -34
DIGIT = (85, 38, 102, 66)
# One hand's fingers left to right for the hand on the viewer's right
# (index, middle, ring, little): x, width, length, tilt in degrees.
FINGERS = [(0, 13, 21, -4), (11, 13, 24, -1), (22, 13, 22, 1), (33, 11, 17, 4)]


def finger_row() -> Image.Image:
    talking = Image.open(MASCOT / "full-talking.webp").convert("RGBA")
    upright = talking.crop(OPEN_HAND).rotate(UPRIGHT, resample=Image.BICUBIC, expand=True)
    digit = upright.crop(DIGIT).transpose(Image.FLIP_TOP_BOTTOM)
    row = Image.new("RGBA", (52, 30), (0, 0, 0, 0))
    for x, width, length, tilt in FINGERS:
        finger = digit.resize((width, length), Image.LANCZOS).rotate(
            tilt, resample=Image.BICUBIC, expand=True, center=(width / 2, 0)
        )
        # A soft shade where each finger lies over its neighbour keeps them apart.
        shade = Image.new("RGBA", finger.size, (26, 26, 24, 0))
        shade.putalpha(finger.getchannel("A").point(lambda a: a * 0.22).filter(ImageFilter.GaussianBlur(1)))
        row.alpha_composite(shade, (x + 1, 0))
        row.alpha_composite(finger, (x, 0))
    return row.crop(row.getchannel("A").getbbox())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    head = Image.open(MASCOT / "full-calm.webp").convert("RGBA").crop(HEAD)
    head.save(OUT / "head.webp", lossless=True)
    fingers = finger_row()
    fingers.save(OUT / "fingers.webp", lossless=True)
    print("head", head.size, "fingers", fingers.size)


if __name__ == "__main__":
    main()
