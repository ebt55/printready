"""Regenerate the small committed fixtures: `uv run python tests/fixtures/make_fixtures.py`.

badge.png          360x360 RGBA, transparent background, one anti-aliased badge (280 px across)
badge-on-white.jpg the same badge flattened onto white, JPEG q90 (opaque, solid background)
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).parent
SS = 4  # supersampling factor for anti-aliased edges


def badge_rgba(size: int = 360, radius: int = 140) -> np.ndarray:
    big = size * SS
    c = big // 2
    colour = np.zeros((big, big, 3), np.uint8)
    alpha = np.zeros((big, big), np.uint8)
    cv2.circle(alpha, (c, c), radius * SS, 255, -1)
    cv2.circle(colour, (c, c), radius * SS, (40, 60, 160), -1)  # navy ring
    cv2.circle(colour, (c, c), (radius - 18) * SS, (245, 170, 40), -1)  # orange face
    star = np.array([[c + int(r * np.cos(t)), c + int(r * np.sin(t))]
                     for i, t in enumerate(np.linspace(-np.pi / 2, 3 * np.pi / 2, 10, endpoint=False))
                     for r in [(70 if i % 2 == 0 else 30) * SS]], np.int32)
    cv2.fillPoly(colour, [star], (255, 255, 255))
    rgba = np.dstack([colour, alpha])
    return cv2.resize(rgba, (size, size), interpolation=cv2.INTER_AREA)


def main() -> None:
    rgba = badge_rgba()
    Image.fromarray(rgba).save(HERE / "badge.png", optimize=True)
    a = rgba[..., 3:4] / 255.0
    flat = (rgba[..., :3] * a + 255 * (1 - a)).round().astype(np.uint8)
    Image.fromarray(flat).save(HERE / "badge-on-white.jpg", quality=90)


if __name__ == "__main__":
    main()
