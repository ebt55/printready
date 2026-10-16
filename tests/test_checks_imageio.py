from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from printready.imageio import ImageLoadError, artwork_from_rgba, load_artwork, save_png
from printready.profile import load_profile
from printready.types import Spec

P = load_profile()
SPEC = Spec("die_cut", 3.0)
FIXTURES = Path(__file__).parent / "fixtures"


def test_png_with_alpha_sets_subject_ppi_and_meta():
    art = load_artwork(FIXTURES / "badge.png", SPEC, P)
    assert art.rgba.shape == (360, 360, 4) and art.rgba.dtype == np.uint8
    assert art.subject is not None
    assert art.ppi == pytest.approx(280 / 2.8, rel=0.01)  # badge is 280 px across
    assert art.meta["format"] == "PNG" and art.meta["real_alpha"] is True
    assert art.meta["bytes"] == (FIXTURES / "badge.png").stat().st_size


def test_opaque_jpeg_uses_canvas_ppi():
    art = load_artwork(FIXTURES / "badge-on-white.jpg", SPEC, P)
    assert art.subject is None
    assert art.ppi == pytest.approx(360 / 2.8)
    assert art.meta["format"] == "JPEG" and art.meta["real_alpha"] is False


def test_real_alpha_threshold():
    rgba = np.full((100, 100, 4), 255, np.uint8)
    rgba[0, :50, 3] = 200  # 0.5 % of pixels: not real alpha
    assert artwork_from_rgba(rgba, SPEC, P).subject is None
    rgba[1:4, :, 3] = 200  # now 3.5 %
    assert artwork_from_rgba(rgba, SPEC, P).subject is not None


def test_exif_orientation_is_applied(tmp_path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees clockwise to display
    Image.new("RGB", (120, 80), (200, 0, 0)).save(path, exif=exif)
    assert load_artwork(path, SPEC, P).rgba.shape[:2] == (120, 80)


def test_webp_and_save_png_round_trip(tmp_path):
    rgba = np.array(Image.open(FIXTURES / "badge.png"))
    save_png(rgba, tmp_path / "sub" / "copy.png")
    assert np.array_equal(load_artwork(tmp_path / "sub" / "copy.png", SPEC, P).rgba, rgba)
    Image.fromarray(rgba).save(tmp_path / "badge.webp", lossless=True)
    assert load_artwork(tmp_path / "badge.webp", SPEC, P).meta["format"] == "WEBP"


def test_load_errors(tmp_path):
    garbage = tmp_path / "garbage.png"
    garbage.write_bytes(b"not an image at all")
    with pytest.raises(ImageLoadError, match="could not be decoded"):
        load_artwork(garbage, SPEC, P)
    gif = tmp_path / "anim.gif"
    Image.new("RGB", (80, 80)).save(gif)
    with pytest.raises(ImageLoadError, match="not PNG, JPG or WebP"):
        load_artwork(gif, SPEC, P)
    with pytest.raises(ImageLoadError):
        load_artwork(tmp_path / "missing.png", SPEC, P)
