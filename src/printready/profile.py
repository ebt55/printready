"""Printer profile: load and validate a profile YAML (e.g. profiles/stickermule-diecut.yaml).

Each rule in the YAML has a `value`, a `source` (an https URL or the word `convention`) and a
one-line `why`. Every constant that decides a label boundary lives here; pure algorithm settings
stay in code.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

DEFAULT_PROFILE_NAME = "stickermule-diecut"
PT_PER_IN = 72.0
BYTES_PER_MB = 1_000_000  # decimal MB: 20 MB = 20,000,000 bytes (the conservative reading)


class ProfileError(ValueError):
    """The profile file is missing a rule, has a bad value, or has a bad source."""


@dataclass(frozen=True)
class Profile:
    name: str
    product: str
    ppi_target: float
    ppi_floor: float
    border_in: float
    border_min_in: float
    min_line_pt: float
    min_text_pt: float
    cap_height_ratio: float
    min_neck_in: float
    max_upload_mb: float
    soft_alpha_max_in: float
    max_bridge_border_in: float
    bg_delta_e: float
    bg_ring_uniform_frac: float
    edge_cut_min_run_in: float
    speck_max_in2: float
    damage_max_frac: float
    max_pieces: float
    max_specks: float
    bleed_in: float
    shape_corner_radius_in: float
    sources: dict[str, str] = field(default_factory=dict, compare=False, repr=False)  # key -> URL | "convention"
    whys: dict[str, str] = field(default_factory=dict, compare=False, repr=False)  # key -> one-line reason

    @staticmethod
    def pt_to_px(pt: float, ppi: float) -> float:
        """Points to pixels at `ppi` (72 pt per inch)."""
        return pt / PT_PER_IN * ppi

    @staticmethod
    def in_to_px(inches: float, ppi: float) -> float:
        """Inches to pixels at `ppi`."""
        return inches * ppi

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * BYTES_PER_MB)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Profile:
        """Build and validate a Profile from parsed YAML. Raises ProfileError."""
        if not isinstance(data, Mapping):
            raise ProfileError("profile must be a mapping")
        for key in ("name", "product", "rules"):
            if key not in data:
                raise ProfileError(f"profile is missing top-level key {key!r}")
        raw_rules = data["rules"]
        if not isinstance(raw_rules, Mapping):
            raise ProfileError("'rules' must be a mapping")

        missing = [k for k in RULE_KEYS if k not in raw_rules]
        if missing:
            raise ProfileError(f"profile is missing rules: {', '.join(missing)}")
        unknown = sorted(set(raw_rules) - set(RULE_KEYS))
        if unknown:
            raise ProfileError(f"profile has unknown rules: {', '.join(unknown)}")

        values: dict[str, float] = {}
        sources: dict[str, str] = {}
        whys: dict[str, str] = {}
        for key in RULE_KEYS:
            values[key], sources[key], whys[key] = _parse_rule(key, raw_rules[key])
        for key in ("cap_height_ratio", "bg_ring_uniform_frac", "damage_max_frac"):
            if values[key] > 1:
                raise ProfileError(f"rule {key!r} is a fraction and must be at most 1")
        if values["ppi_floor"] >= values["ppi_target"]:
            raise ProfileError("ppi_floor must be below ppi_target")
        if values["border_min_in"] > values["border_in"]:
            raise ProfileError("border_min_in must not exceed border_in")

        return cls(name=str(data["name"]), product=str(data["product"]), sources=sources, whys=whys, **values)


RULE_KEYS: tuple[str, ...] = tuple(
    f.name for f in fields(Profile) if f.name not in ("name", "product", "sources", "whys")
)


def _parse_rule(key: str, raw: Any) -> tuple[float, str, str]:
    if not isinstance(raw, Mapping):
        raise ProfileError(f"rule {key!r} must be a mapping with value, source, why")
    for part in ("value", "source", "why"):
        if part not in raw:
            raise ProfileError(f"rule {key!r} is missing {part!r}")
    value = raw["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"rule {key!r}: value must be a number, got {value!r}")
    if not (math.isfinite(value) and value > 0):
        raise ProfileError(f"rule {key!r}: value must be positive, got {value!r}")
    source = raw["source"]
    if not (source == "convention" or _is_https_url(source)):
        raise ProfileError(f"rule {key!r}: source must be an https URL or 'convention', got {source!r}")
    why = raw["why"]
    if not isinstance(why, str) or not why.strip():
        raise ProfileError(f"rule {key!r}: why must be a non-empty line")
    return float(value), source, why.strip()


def _is_https_url(text: Any) -> bool:
    if not isinstance(text, str) or any(c.isspace() for c in text):
        return False
    parsed = urlparse(text)
    return parsed.scheme == "https" and "." in parsed.netloc


def default_profile_path() -> Path:
    """The shipped profile: inside the installed package, else in the repo's profiles/ dir."""
    filename = f"{DEFAULT_PROFILE_NAME}.yaml"
    packaged = Path(__file__).resolve().parent / "profiles" / filename
    if packaged.exists():
        return packaged
    return Path(__file__).resolve().parents[2] / "profiles" / filename


def load_profile(path: str | Path | None = None) -> Profile:
    """Load and validate a profile YAML. `None` loads the shipped Sticker Mule die-cut profile."""
    path = Path(path) if path is not None else default_profile_path()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ProfileError(f"cannot read profile {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ProfileError(f"profile {path} is not valid YAML: {exc}") from exc
    return Profile.from_dict(data)
