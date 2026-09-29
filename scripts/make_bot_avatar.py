#!/usr/bin/env python3
"""Generate the Telegram profile photo for the bot.

The mark is a document with a checkmark inside it: this service reads
documents, and a checkmark is the thing a client wants to see next to a tax
document. Telegram shows the avatar as a circle at roughly 32-64 px in a chat
list, so the shape is kept to three elements and drawn at 4x then downsampled
to keep the edges clean.

The picture is set by hand, not through the API: `setMyProfilePhoto` rejected
every multipart encoding tried (bare bytes, named file, no extension, tuple
lists, both PNG and JPEG) with "photo isn't specified" while `getMe` on the
same token succeeded, so the file has to be sent through BotFather.

    python scripts/make_bot_avatar.py
    then: BotFather -> /setuserpic -> pick the bot -> send site/avatar.png
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "avatar.png"

SIZE = 640
SCALE = 4
CANVAS = SIZE * SCALE

# The landing page accent, so the avatar and the site read as one product.
GREEN_DARK = (15, 81, 50)
GREEN = (26, 107, 79)
GREEN_LIGHT = (46, 134, 102)
WHITE = (255, 255, 255)
MINT = (208, 240, 226)
SHADOW = (10, 60, 38)


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def vertical_gradient(height: int) -> Image.Image:
    """A soft top-lit gradient, so the mark does not look flat in a dark chat."""
    top, bottom = GREEN_LIGHT, GREEN_DARK
    image = Image.new("RGB", (1, height))
    pixels = image.load()
    for y in range(height):
        pixels[0, y] = lerp(top, bottom, y / max(height - 1, 1))
    return image.resize((CANVAS, CANVAS), Image.BILINEAR)


def rounded(draw: ImageDraw.ImageDraw, box, radius, fill) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def main() -> int:
    image = vertical_gradient(CANVAS)
    draw = ImageDraw.Draw(image)

    # Every measurement below is given in final-image pixels and scaled up here,
    # because the drawing happens on a 4x canvas for anti-aliasing. Getting this
    # wrong once produced a mark that was 102 px wide in a 640 px image and
    # vanished in a chat list.
    def s(value: float) -> float:
        return value * SCALE

    cx = CANVAS / 2

    # Telegram masks the avatar to a circle, so the sheet must stay inside the
    # circle while still filling it. A half-width of 205 with a half-height of
    # 220 keeps the corners just within the mask.
    half_w, half_h = s(205), s(220)
    left, right = cx - half_w, cx + half_w
    top, bottom = cx - half_h, cx + half_h
    fold = s(105)
    radius = s(30)

    for step in range(15, 0, -1):
        depth = (15 - step) / 15
        draw.rounded_rectangle(
            (left + s(step), top + s(step), right + s(step), bottom + s(step)),
            radius=radius,
            fill=lerp(GREEN, SHADOW, 0.10 + depth * 0.55),
        )

    rounded(draw, (left, top, right, bottom), radius, WHITE)

    # Folded top-right corner, the cue that this is a sheet of paper.
    draw.polygon(
        [(right - fold, top), (right, top + fold), (right - fold, top + fold)],
        fill=MINT,
    )
    draw.line(
        [(right - fold, top), (right - fold, top + fold), (right, top + fold)],
        fill=GREEN_LIGHT,
        width=s(5),
        joint="curve",
    )

    # Three rows of text, then the checkmark that says the document was read.
    line_left = left + s(52)
    for offset, width in ((0, 288), (60, 250), (120, 196)):
        rounded(
            draw,
            (line_left, top + s(66 + offset), line_left + s(width), top + s(86 + offset)),
            s(10),
            MINT,
        )

    tick = [
        (left + s(62), bottom - s(148)),
        (left + s(118), bottom - s(76)),
        (left + s(228), bottom - s(196)),
    ]
    draw.line(tick, fill=GREEN, width=s(42), joint="curve")
    for point in (tick[0], tick[2]):
        draw.ellipse(
            [point[0] - s(21), point[1] - s(21), point[0] + s(21), point[1] + s(21)],
            fill=GREEN,
        )

    image = image.resize((SIZE, SIZE), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT, "PNG", optimize=True)
    print(f"Wrote {OUT} ({SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
