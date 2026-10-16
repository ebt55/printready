"""Procedural sample artwork for the workbench (examples/samples/*.png).

Every image is drawn here from shapes, so the repo ships no third-party or generated (Grok) art.
Each sample mimics one thing image models get wrong for die-cut stickers: a solid white
background, garbled text, too few pixels, separate parts, a soft glow, art cut off at the edge.
`palette` and `seed` make colour variants for the demo real-set gallery.

Run `python -m printready.web.samples` to redraw examples/samples/.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SS = 3  # supersampling factor: draw large, downsample with Lanczos for clean anti-aliased edges


@dataclass
class Sample:
    id: str
    title: str
    blurb: str
    draw: Callable[..., Image.Image]
    size_in: float = 3.0
    vision: dict = field(default_factory=lambda: {"text": [], "notes": "No text in the artwork."})
    agent: dict = field(default_factory=dict)  # demo agent behaviour, e.g. {"handoff": "..."}


# ------------------------------------------------------------------ drawing helpers

def _font(px: int) -> ImageFont.FreeTypeFont:
    """DejaVu Sans Bold from matplotlib's data dir (already a dependency), else Pillow's default."""
    try:
        import matplotlib

        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"
        return ImageFont.truetype(str(path), px)
    except Exception:  # pragma: no cover - fallback only
        return ImageFont.load_default(size=px)


class Pen:
    """Draws in supersampled coordinates while callers think in final pixels."""

    def __init__(self, w: int, h: int, bg=(0, 0, 0, 0)):
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w * SS, h * SS), bg)
        self.d = ImageDraw.Draw(self.img)

    def s(self, *vals):
        return [v * SS for v in vals]

    def ellipse(self, box, fill=None, outline=None, width=0):
        self.d.ellipse(self.s(*box), fill=fill, outline=outline, width=int(width * SS))

    def rect(self, box, fill=None, radius=0, outline=None, width=0):
        self.d.rounded_rectangle(self.s(*box), radius=radius * SS, fill=fill, outline=outline,
                                 width=int(width * SS))

    def poly(self, pts, fill=None):
        self.d.polygon([(x * SS, y * SS) for x, y in pts], fill=fill)

    def line(self, pts, fill, width):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=fill, width=int(width * SS), joint="curve")

    def arc(self, box, start, end, fill, width):
        self.d.arc(self.s(*box), start, end, fill=fill, width=int(width * SS))

    def text(self, xy, txt, px, fill):
        self.d.text((xy[0] * SS, xy[1] * SS), txt, font=_font(px * SS), fill=fill, anchor="mm")

    def done(self) -> Image.Image:
        return self.img.resize((self.w, self.h), Image.LANCZOS)


def _mask_canvas(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    m = Image.new("L", (w * SS, h * SS), 0)
    return m, ImageDraw.Draw(m)


def _grow(mask: Image.Image, radius_ss: float) -> Image.Image:
    """Dilate an L mask by a disc of `radius_ss` supersampled px (OpenCV; Pillow's MaxFilter is O(k^2))."""
    import cv2

    r = max(1, int(round(radius_ss)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return Image.fromarray(cv2.dilate(np.asarray(mask), kernel))


def _outlined(pen: Pen, mask: Image.Image, fill, outline, stroke: float) -> None:
    """Paint a filled shape with an outer outline: outline = dilated mask, fill = mask."""
    grown = _grow(mask, stroke * SS)
    pen.img.paste(Image.new("RGBA", pen.img.size, outline), (0, 0), grown)
    pen.img.paste(Image.new("RGBA", pen.img.size, fill), (0, 0), mask)


def _blob_pts(cx, cy, rx, ry, wobble, seed, n=180):
    rnd = random.Random(seed)
    phases = [rnd.uniform(0, math.tau) for _ in range(3)]
    pts = []
    for i in range(n):
        t = math.tau * i / n
        r = 1 + wobble * (0.6 * math.sin(2 * t + phases[0]) + 0.3 * math.sin(3 * t + phases[1])
                          + 0.1 * math.sin(5 * t + phases[2]))
        pts.append((cx + rx * r * math.cos(t), cy + ry * r * math.sin(t)))
    return pts


# ------------------------------------------------------------------ samples

PALETTES = {
    "mascot": [("#FFC83D", "#2A2420", "#FF8FA3"), ("#7FD1AE", "#1E2D2A", "#FF9E80")],
    "badge": [("#1F4E5A", "#F6E7C8", "#C9733B"), ("#5B2A86", "#FBEFD9", "#E07A5F")],
    "bolt": [("#FF6B35", "#FFD23F", "#2B2118"), ("#3A86FF", "#FFE066", "#14213D")],
    "cloud": [("#9AD1F5", "#3A86FF", "#1D3557"), ("#F7B2D9", "#B565D8", "#3C1642")],
    "ghost": [("#F4F1FF", "#3D348B", "#B8A9FF"), ("#EFFFF6", "#1B4332", "#74C69D")],
    "planet": [("#7B5CFF", "#FFB347", "#231942"), ("#FF5D73", "#7DE2D1", "#2D142C")],
    "cat": [("#8D99AE", "#2B2D42", "#FFF6E9"), ("#E9A178", "#3B1F0E", "#EAF4F4")],
    "scene": [(), ()],
}


def draw_mascot(w=1200, h=1200, palette=0, seed=1) -> Image.Image:
    """A blob mascot on a solid white background (opaque, like most image-model output)."""
    body, ink, cheek = PALETTES["mascot"][palette]
    pen = Pen(w, h, (255, 255, 255, 255))
    sx, sy = w / 1200, h / 1200
    m, md = _mask_canvas(w, h)
    pts = _blob_pts(600 * sx, 640 * sy, 360 * sx, 330 * sy, 0.05, seed)
    md.polygon([(x * SS, y * SS) for x, y in pts], fill=255)
    for cx in (330, 870):  # arms
        md.ellipse([v * SS for v in ((cx - 90) * sx, 600 * sy, (cx + 90) * sx, 760 * sy)], fill=255)
    for cx in (470, 730):  # feet
        md.ellipse([v * SS for v in ((cx - 110) * sx, 900 * sy, (cx + 110) * sx, 1040 * sy)], fill=255)
    md.ellipse([v * SS for v in (560 * sx, 170 * sy, 700 * sx, 330 * sy)], fill=255)  # sprout bulb
    _outlined(pen, m, body, ink, 14 * sx)
    pen.line([(630 * sx, 300 * sy), (600 * sx, 360 * sy)], ink, 14 * sx)
    for ex in (480, 720):  # eyes
        pen.ellipse((ex * sx - 62 * sx, 520 * sy, ex * sx + 62 * sx, 660 * sy), fill="#FFFFFF", outline=ink,
                    width=10 * sx)
        pen.ellipse((ex * sx - 30 * sx, 560 * sy, ex * sx + 30 * sx, 640 * sy), fill=ink)
        pen.ellipse((ex * sx - 6 * sx, 568 * sy, ex * sx + 12 * sx, 590 * sy), fill="#FFFFFF")
    for cx in (390, 810):
        pen.ellipse((cx * sx - 50 * sx, 680 * sy, cx * sx + 50 * sx, 730 * sy), fill=cheek)
    pen.arc((520 * sx, 640 * sy, 680 * sx, 780 * sy), 20, 160, ink, 12 * sx)
    return pen.done()


def draw_badge(w=1100, h=1100, palette=0, seed=1, words=("COFEE", "CLUBB")) -> Image.Image:
    """A round badge with a coffee cup and misspelled words (transparent background)."""
    ring, cream, accent = PALETTES["badge"][palette]
    pen = Pen(w, h)
    c, r = w / 2, w * 0.43
    pen.ellipse((c - r, c - r, c + r, c + r), fill=ring)
    r2 = r * 0.86
    pen.ellipse((c - r2, c - r2, c + r2, c + r2), fill=cream)
    r3 = r * 0.80
    pen.ellipse((c - r3, c - r3, c + r3, c + r3), outline=accent, width=w * 0.008)
    u = w / 1100
    pen.rect((c - 120 * u, c - 150 * u, c + 90 * u, c + 20 * u), fill="#6B3E26", radius=30 * u)
    pen.ellipse((c + 55 * u, c - 120 * u, c + 165 * u, c - 10 * u), outline="#6B3E26", width=24 * u)
    for dx in (-70, -15, 40):
        pen.arc((c + (dx - 20) * u, c - 260 * u, c + (dx + 20) * u, c - 170 * u), 100, 260, accent, 10 * u)
    pen.text((c, c + 120 * u), words[0], int(150 * u), ring)
    pen.text((c, c + 235 * u), words[1], int(78 * u), accent)
    pen.text((c, c - 320 * u), "EST 2026", int(40 * u), cream)
    return pen.done()


def draw_bolt(w=300, h=300, palette=0, seed=1) -> Image.Image:
    """A burst logo with a lightning bolt, drawn small (too few pixels for a 3 in sticker)."""
    burst, bolt, ink = PALETTES["bolt"][palette]
    pen = Pen(w, h)
    c = w / 2
    m, md = _mask_canvas(w, h)
    pts = []
    for i in range(32):
        rr = (0.46 if i % 2 == 0 else 0.36) * w
        t = math.tau * i / 32 - math.pi / 2
        pts.append((c + rr * math.cos(t), c + rr * math.sin(t)))
    md.polygon([(x * SS, y * SS) for x, y in pts], fill=255)
    _outlined(pen, m, burst, ink, w * 0.012)
    u = w / 300
    pen.poly([(c + 10 * u, c - 95 * u), (c - 55 * u, c + 12 * u), (c - 5 * u, c + 12 * u),
              (c - 22 * u, c + 95 * u), (c + 55 * u, c - 18 * u), (c + 5 * u, c - 18 * u)], fill=bolt)
    return pen.done()


def draw_cloud(w=1200, h=1160, palette=0, seed=1, gap_in=0.30) -> Image.Image:
    """A cloud and a raindrop as two separate parts (transparent), `gap_in` apart at a 3 in order."""
    cloud, drop, ink = PALETTES["cloud"][palette]
    pen = Pen(w, h)
    u = w / 1200
    m, md = _mask_canvas(w, h)
    for cx, cy, r in ((330, 430, 190), (560, 330, 240), (800, 420, 200), (470, 540, 170), (700, 560, 160)):
        md.ellipse([v * SS * u for v in (cx - r, cy - r, cx + r, cy + r)], fill=255)
    md.rounded_rectangle([v * SS * u for v in (180, 450, 960, 690)], radius=120 * SS * u, fill=255)
    _outlined(pen, m, cloud, ink, 12 * u)
    # Subject bbox is ~ 990 px tall, so a 3 in order prints at ~ 990 / 2.8 = 354 px per inch.
    px_per_in = 354 * u
    top = (690 + 12) * u + gap_in * px_per_in  # cloud bottom (with outline) + gap = drop tip
    dm, dd = _mask_canvas(w, h)
    cx, r = 800 * u, 88 * u
    cy = top + 1.75 * r
    dd.ellipse([v * SS for v in (cx - r, cy - r, cx + r, cy + r)], fill=255)
    dd.polygon([(v[0] * SS, v[1] * SS) for v in ((cx - r * 0.94, cy - r * 0.34), (cx, top + 12 * u),
                                                  (cx + r * 0.94, cy - r * 0.34))], fill=255)
    _outlined(pen, dm, drop, ink, 12 * u)
    pen.ellipse((cx - 44 * u, cy - 14 * u, cx - 16 * u, cy + 26 * u), fill="#FFFFFF")
    for ex in (480, 640):
        pen.ellipse((ex * u - 22 * u, 470 * u, ex * u + 22 * u, 520 * u), fill=ink)
    pen.arc((520 * u, 480 * u, 600 * u, 560 * u), 20, 160, ink, 10 * u)
    return pen.done()


def draw_ghost(w=1400, h=1400, palette=0, seed=1) -> Image.Image:
    """A ghost with a soft outer glow: a semi-transparent band makes the cut position ambiguous."""
    body, ink, glow = PALETTES["ghost"][palette]
    pen = Pen(w, h)
    u = w / 1100
    m, md = _mask_canvas(w, h)
    md.ellipse([v * SS * u for v in (300, 200, 800, 700)], fill=255)
    md.rectangle([v * SS * u for v in (300, 450, 800, 830)], fill=255)
    for i in range(5):
        x0 = 300 + i * 100
        md.ellipse([v * SS * u for v in (x0, 780, x0 + 100, 880)], fill=255)
    halo = _grow(m, 15 * u * SS).filter(ImageFilter.GaussianBlur(26 * u * SS))
    g = Image.new("RGBA", pen.img.size, glow)
    g.putalpha(halo.point(lambda v: int(v * 0.85)))
    pen.img.alpha_composite(g)
    _outlined(pen, m, body, ink, 12 * u)
    for ex in (470, 630):
        pen.ellipse((ex * u - 34 * u, 420 * u, ex * u + 34 * u, 510 * u), fill=ink)
    pen.ellipse((515 * u, 560 * u, 585 * u, 640 * u), fill=ink)
    return pen.done()


def draw_planet(w=1200, h=1200, palette=0, seed=1) -> Image.Image:
    """A ringed planet with a clean edge and real transparency: already fine for a die-cut."""
    planet, ring, ink = PALETTES["planet"][palette]
    pen = Pen(w, h)
    u = w / 1200
    c = 600 * u
    ring_box = (110 * u, 470 * u, 1090 * u, 730 * u)
    m, md = _mask_canvas(w, h)
    md.ellipse([v * SS for v in (c - 330 * u, c - 330 * u, c + 330 * u, c + 330 * u)], fill=255)
    md.ellipse([v * SS for v in ring_box], fill=255)
    pen.img.paste(Image.new("RGBA", pen.img.size, ink), (0, 0), _grow(m, 14 * u * SS))
    pen.ellipse(ring_box, fill=ring)
    pen.ellipse((ring_box[0] + 120 * u, ring_box[1] + 50 * u, ring_box[2] - 120 * u, ring_box[3] - 50 * u), fill=ink)
    # planet in front of the back half of the ring, then the front half of the ring on top
    pm, pd = _mask_canvas(w, h)
    pd.ellipse([v * SS for v in (c - 320 * u, c - 320 * u, c + 320 * u, c + 320 * u)], fill=255)
    pen.img.paste(Image.new("RGBA", pen.img.size, planet), (0, 0), pm)
    # Stripes and a highlight on their own layer, clipped to the planet and alpha-composited
    # (ImageDraw on an RGBA image replaces alpha instead of blending, which would punch holes).
    layer = Image.new("RGBA", pen.img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(layer)
    for i, y in enumerate((330, 420, 760, 850)):
        sd.rectangle([0, y * u * SS, w * SS, (y + 34 + 10 * (i % 3)) * u * SS], fill=(255, 255, 255, 56))
    sd.ellipse([v * SS for v in (c - 210 * u, c - 230 * u, c - 120 * u, c - 160 * u)], fill=(255, 255, 255, 120))
    la = np.asarray(layer).copy()
    la[..., 3] = np.minimum(la[..., 3], np.asarray(pm))
    pen.img.alpha_composite(Image.fromarray(la))
    front = Image.new("L", pen.img.size, 0)
    fd = ImageDraw.Draw(front)
    fd.rectangle([0, 600 * u * SS, w * SS, h * SS], fill=255)
    rm, rd = _mask_canvas(w, h)
    rd.ellipse([v * SS for v in ring_box], fill=255)
    rd.ellipse([v * SS for v in (ring_box[0] + 120 * u, ring_box[1] + 50 * u, ring_box[2] - 120 * u, ring_box[3] - 50 * u)], fill=0)
    front_ring = Image.fromarray(np.minimum(np.asarray(rm), np.asarray(front)))
    pen.img.paste(Image.new("RGBA", pen.img.size, ink), (0, 0), _grow(front_ring, 10 * u * SS))
    pen.img.paste(Image.new("RGBA", pen.img.size, ring), (0, 0), front_ring)
    return pen.done()


def draw_cat(w=1000, h=1000, palette=0, seed=1) -> Image.Image:
    """A sitting cat on a solid cream background whose tail runs off the right edge of the canvas."""
    fur, ink, bg = PALETTES["cat"][palette]
    pen = Pen(w, h, bg)
    u = w / 1000
    m, md = _mask_canvas(w, h)
    md.ellipse([v * SS * u for v in (250, 430, 690, 930)], fill=255)  # body
    md.ellipse([v * SS * u for v in (240, 160, 700, 560)], fill=255)  # head
    md.polygon([(v[0] * SS * u, v[1] * SS * u) for v in ((262, 330), (290, 70), (440, 220))], fill=255)
    md.polygon([(v[0] * SS * u, v[1] * SS * u) for v in ((678, 330), (650, 70), (500, 220))], fill=255)
    md.line([(v[0] * SS * u, v[1] * SS * u) for v in ((620, 850), (780, 840), (890, 780), (1060, 720))],
            fill=255, width=int(78 * SS * u), joint="curve")  # tail: off the canvas on the right
    _outlined(pen, m, fur, ink, 13 * u)
    for pts in (((290, 300), (305, 130), (400, 225)), ((650, 300), (635, 130), (540, 225))):
        pen.poly([(x * u, y * u) for x, y in pts], fill="#F4ACB7")
    for ex in (380, 560):
        pen.ellipse((ex * u - 42 * u, 330 * u, ex * u + 42 * u, 430 * u), fill="#F9F871")
        pen.ellipse((ex * u - 12 * u, 338 * u, ex * u + 12 * u, 422 * u), fill=ink)
    pen.poly([(440 * u, 455 * u), (500 * u, 455 * u), (470 * u, 490 * u)], fill="#F4ACB7")
    for side in (-1, 1):
        for dy in (0, 34):
            pen.line([(470 * u + side * 70 * u, (500 + dy) * u), (470 * u + side * 230 * u, (475 + dy * 1.6) * u)],
                     ink, 5 * u)
    pen.arc((330 * u, 760 * u, 450 * u, 900 * u), 200, 340, ink, 8 * u)  # paws
    pen.arc((490 * u, 760 * u, 610 * u, 900 * u), 200, 340, ink, 8 * u)
    return pen.done()


def draw_scene(w=1100, h=1100, palette=0, seed=1) -> Image.Image:
    """A full-bleed sunset landscape: a scene, not a cut-out. No edge to cut around."""
    skies = [((255, 158, 94), (232, 86, 128), (84, 52, 128)), ((255, 214, 140), (126, 196, 230), (40, 92, 160))]
    top, mid, low = skies[palette]
    y = np.linspace(0, 1, h * SS)[:, None]
    grad = np.where(y < 0.55, (1 - y / 0.55) * np.array(low) + (y / 0.55) * np.array(mid),
                    (1 - (y - 0.55) / 0.45) * np.array(mid) + ((y - 0.55) / 0.45) * np.array(top))
    sky = np.repeat(grad[:, None, :], w * SS, axis=1).reshape(h * SS, w * SS, 3).astype(np.uint8)
    pen = Pen(w, h)
    pen.img = Image.fromarray(np.dstack([sky, np.full(sky.shape[:2], 255, np.uint8)]), "RGBA")
    pen.d = ImageDraw.Draw(pen.img)
    u = w / 1100
    pen.ellipse((550 * u - 150 * u, 430 * u, 550 * u + 150 * u, 730 * u), fill=(255, 236, 170))
    rnd = random.Random(seed)
    for layer, (base, colour) in enumerate(((620, (92, 54, 110)), (700, (60, 36, 84)), (760, (38, 24, 58)))):
        pts = [(0, h)]
        x = 0.0
        while x <= w + 60:
            pts.append((x, (base - rnd.uniform(40, 170 - layer * 30)) * u))
            x += rnd.uniform(70, 150) * u
        pts += [(w, h)]
        pen.poly(pts, fill=colour)
    pen.rect((0, 820 * u, w, h), fill=(48, 40, 86))
    for i in range(9):
        yy = (840 + i * 26) * u
        pen.rect((550 * u - (120 - i * 10) * u, yy, 550 * u + (120 - i * 10) * u, yy + 8 * u), fill=(255, 214, 150))
    return pen.done()


SAMPLES: list[Sample] = [
    Sample("mascot", "Blob mascot", "Solid white background, like most image-model output.", draw_mascot),
    Sample("badge", "Coffee club badge", "Clean edge, but the words are misspelled.", draw_badge,
           # The scripted vision answer, in prompts/vision-text.md's format (box: fractions of the
           # art's own outline box, measured from draw_badge's layout).
           vision={"text": [
               {"letters": "C O F E E", "seen": "COFEE", "intended": "COFFEE", "misspelled": True,
                "broken": False, "box": [0.225, 0.569, 0.775, 0.685]},
               {"letters": "C L U B B", "seen": "CLUBB", "intended": "CLUB", "misspelled": True,
                "broken": False, "box": [0.373, 0.717, 0.627, 0.78]},
               {"letters": "E S T / 2 0 2 6", "seen": "EST 2026", "intended": "EST 2026", "misspelled": False,
                "broken": False, "box": [0.415, 0.146, 0.584, 0.178]}],
               "notes": "Two of three lines look misspelled; the small date line is legible."}),
    Sample("bolt", "Bolt logo, 300 px", "Too few pixels to print sharp at 3 in.", draw_bolt),
    Sample("cloud", "Cloud and raindrop", "Two parts with a gap; one die-cut needs one outline.", draw_cloud),
    Sample("ghost", "Glowing ghost", "A soft glow leaves the cut position ambiguous.", draw_ghost,
           agent={"look_note": "The glow fades over about 0.08 in, so any cut line either clips the glow or "
                               "leaves a hazy edge. That is a design decision for a person."}),
    Sample("planet", "Ringed planet", "Transparent, sharp, one part: ready as is.", draw_planet),
    Sample("cat", "Cat with cropped tail", "The tail runs off the edge of the canvas.", draw_cat),
    Sample("scene", "Sunset scene", "A full-bleed scene: no edge to cut around.", draw_scene),
]

SAMPLE_BY_ID = {s.id: s for s in SAMPLES}


def write_samples(out_dir: Path) -> list[dict]:
    """Draw every sample into `out_dir` and write samples.json (the manifest the server reads)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for s in SAMPLES:
        img = s.draw()
        if img.getchannel("A").getextrema()[0] == 255:  # opaque art ships as RGB, like a JPG export
            img = img.convert("RGB")
        img.save(out_dir / f"{s.id}.png", optimize=True)
        manifest.append({"id": s.id, "title": s.title, "blurb": s.blurb, "file": f"{s.id}.png",
                         "size_in": s.size_in, "width": img.width, "height": img.height,
                         "vision": s.vision, "agent": s.agent})
    (out_dir / "samples.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":  # pragma: no cover
    from printready.web.paths import samples_dir

    for item in write_samples(samples_dir()):
        print(item["file"], item["width"], "x", item["height"])
