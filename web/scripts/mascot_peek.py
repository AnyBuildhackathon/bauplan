"""Cut the access screen's peeking Mechanic out of the full figure.

Run from the repo root: uv run --with pillow python web/scripts/mascot_peek.py
Writes web/public/mascot-peek/head.webp and hand.webp. The boxes are in full-calm.webp
pixels (640 x 820); AccessScreen places the crops with the same numbers, so change both.
"""

from pathlib import Path

from PIL import Image

WEB = Path(__file__).resolve().parent.parent
SOURCE = WEB / "public/mascot/full-calm.webp"
OUT = WEB / "public/mascot-peek"

# Hair top to just below the shirt collar; the box hides everything under the collar.
HEAD = (196, 22, 444, 266)
# His right hand below the knuckles: the curled fingers and the thumb, cuff and jacket left out.
HAND = (176, 486, 228, 548)


def main() -> None:
    figure = Image.open(SOURCE).convert("RGBA")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, box in (("head", HEAD), ("hand", HAND)):
        figure.crop(box).save(OUT / f"{name}.webp", lossless=True)


if __name__ == "__main__":
    main()
