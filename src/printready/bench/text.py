"""Words, deliberate misspellings and the font used for badge text (DejaVu Sans Bold, shipped with
matplotlib). Cap height comes from the font's own glyph outline for "H", so a word can be set to
hit a target cap height in points at a sample's PPI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import matplotlib
from matplotlib import ft2font
from PIL import ImageFont

PT_PER_IN = 72.0

# Correctly spelled, generic sticker words (no brands). Badges and the text family draw from these.
WORDS: tuple[str, ...] = (
    "STICKER", "COFFEE", "ADVENTURE", "BAKERY", "GARDEN", "HELLO", "OCEAN", "MOUNTAIN", "PIZZA",
    "ROCKET", "SUNSHINE", "FOREST", "TACOS", "CAMPING", "BOOKS", "MUSIC", "DONUTS", "PLANTS",
    "COOKIES", "HONEY", "BICYCLE", "LIBRARY", "PICNIC", "SUMMER", "AUTUMN", "GALAXY", "DRAGON",
    "KITTEN", "PUPPY", "MARKET", "STUDIO", "GROCERY", "CANDLES", "WELCOME", "THANKS", "LEMONADE",
    "BREWERY", "WINTER",
)

# Deliberate misspellings, each checked by hand not to be an English word.
# (garbled, intended, method): swap = two adjacent letters exchanged, double = a letter doubled,
# drop = a letter left out.
GARBLES: tuple[tuple[str, str, str], ...] = (
    ("STIKCER", "STICKER", "swap"),
    ("ADVENTRUE", "ADVENTURE", "swap"),
    ("GRADEN", "GARDEN", "swap"),
    ("BAKREY", "BAKERY", "swap"),
    ("MOUNTIAN", "MOUNTAIN", "swap"),
    ("SUNHSINE", "SUNSHINE", "swap"),
    ("ROCEKT", "ROCKET", "swap"),
    ("COOKEIS", "COOKIES", "swap"),
    ("FOERST", "FOREST", "swap"),
    ("PICINC", "PICNIC", "swap"),
    ("CAMPIGN", "CAMPING", "swap"),
    ("GALXAY", "GALAXY", "swap"),
    ("OCCEAN", "OCEAN", "double"),
    ("MARKKET", "MARKET", "double"),
    ("STUDDIO", "STUDIO", "double"),
    ("DRAGGON", "DRAGON", "double"),
    ("TACCOS", "TACOS", "double"),
    ("MUSSIC", "MUSIC", "double"),
    ("DONNUTS", "DONUTS", "double"),
    ("PLANNTS", "PLANTS", "double"),
    ("HONNEY", "HONEY", "double"),
    ("WINNTER", "WINTER", "double"),
    ("CANDDLES", "CANDLES", "double"),
    ("BICYCCLE", "BICYCLE", "double"),
    ("COFEE", "COFFEE", "drop"),
    ("SUMMR", "SUMMER", "drop"),
    ("KITEN", "KITTEN", "drop"),
    ("PUPY", "PUPPY", "drop"),
    ("PIZA", "PIZZA", "drop"),
    ("WELCME", "WELCOME", "drop"),
    ("LEMONAE", "LEMONADE", "drop"),
    ("AUTUM", "AUTUMN", "drop"),
    ("BREWRY", "BREWERY", "drop"),
    ("GROCRY", "GROCERY", "drop"),
    ("LIBARY", "LIBRARY", "drop"),
    ("SUNSINE", "SUNSHINE", "drop"),
)


def font_path(bold: bool = True) -> Path:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name


@lru_cache(maxsize=1)
def cap_ratio() -> float:
    """Cap height over the em size, from the outline of "H" in font units."""
    face = ft2font.FT2Font(str(font_path()))
    flags = ft2font.LoadFlags.NO_SCALE if hasattr(ft2font, "LoadFlags") else ft2font.LOAD_NO_SCALE
    glyph = face.load_char(ord("H"), flags=flags)
    return glyph.bbox[3] / face.units_per_EM


@lru_cache(maxsize=256)
def font(size_px: float, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_path(bold)), size=size_px)


def font_size_for_cap(cap_px: float) -> float:
    """Em size in pixels whose cap height is `cap_px`. Rounded to 1/64 px (FreeType's unit)."""
    return round(cap_px / cap_ratio() * 64.0) / 64.0


def ink_width(word: str, size_px: float) -> float:
    """Width in pixels of the word's ink at `size_px`."""
    x0, _, x1, _ = font(size_px).getbbox(word, anchor="ls")
    return float(x1 - x0)


def pt_to_px(pt: float, ppi: float) -> float:
    return pt / PT_PER_IN * ppi


def px_to_pt(px: float, ppi: float) -> float:
    return px / ppi * PT_PER_IN
