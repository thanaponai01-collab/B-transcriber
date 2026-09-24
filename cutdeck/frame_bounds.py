"""Where a clip is actually drawn in a frame, measured from pixels.

Premiere gives plugins no size for a Graphic's text (docs/PREMIERE_FACTS.md, "Graphic Text
layer"), so the CutDeck Transform panel saves the frame under the playhead twice, with the clip
on and with it off, and asks the helper here for the box where the two differ. That box is the
clip's drawn pixels in sequence coordinates, whatever sits under or over it.

Proven live 2026-09-24 on a text Graphic: the difference was the text alone, 418 x 87 px.
"""

from pathlib import Path

from PIL import Image, ImageChops

# Two renders of the same frame are NOT always identical: other clips' video can differ by 1/255
# in a few pixels (live 2026-09-24: 3 pixels inside another clip, 1000 px from the text, made
# the box 0-1315 instead of 0-419 and every Align landed wrong). A single threshold can't
# separate that from the text's own faint anti-aliased edges (2 cut its top row). So the box
# is found from clear changes (> STRONG) and then grown only by faint changes (> 0) within
# MARGIN px of it: the text's soft edges count, a speck elsewhere in the frame does not.
STRONG = 16
MARGIN = 8


def drawn_bounds(on_path: str, off_path: str) -> dict | None:
    """Box of the pixels that differ between the two frames, as sequence pixels
    ``{left, top, right, bottom}`` (right/bottom exclusive), or None when nothing differs."""
    with Image.open(on_path) as on_image, Image.open(off_path) as off_image:
        # Premultiplied ("RGBa"): a fully transparent pixel is (0,0,0,0) whatever colour it
        # carries, so invisible leftovers don't count (live frames: 1 px too wide without it).
        on = on_image.convert("RGBA").convert("RGBa")
        off = off_image.convert("RGBA").convert("RGBa")
    if on.size != off.size:
        raise ValueError("The two frames differ in size")
    diff = ImageChops.difference(on, off)
    # Largest difference across R, G, B, A per pixel, then keep only real changes.
    channels = diff.split()
    strongest = channels[0]
    for channel in channels[1:]:
        strongest = ImageChops.lighter(strongest, channel)
    core = strongest.point(lambda v: 255 if v > STRONG else 0).getbbox()
    if core is None:
        return None
    width, height = strongest.size
    near = (max(core[0] - MARGIN, 0), max(core[1] - MARGIN, 0),
            min(core[2] + MARGIN, width), min(core[3] + MARGIN, height))
    box = strongest.crop(near).point(lambda v: 255 if v > 0 else 0).getbbox()
    left, top, right, bottom = box[0] + near[0], box[1] + near[1], box[2] + near[0], box[3] + near[1]
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def measure_request(req: dict, input_file) -> dict:
    """Handles the helper's ``frame_bounds`` request. The frames are temporary files the panel
    wrote only for this. The latest pair is kept, as ``cutdeck-bounds-last-on.png`` / ``-off.png``
    beside them (each request replaces the last), so a wrong measurement can be looked at;
    everything else is removed, whatever the outcome."""
    on_path = input_file(req.get("on"), ".png")
    off_path = input_file(req.get("off"), ".png")
    try:
        return {"bounds": drawn_bounds(on_path, off_path)}
    finally:
        for path, side in ((on_path, "on"), (off_path, "off")):
            Path(path).replace(Path(path).with_name(f"cutdeck-bounds-last-{side}.png"))
