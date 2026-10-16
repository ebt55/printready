import copy

import pytest
import yaml

from printready.profile import RULE_KEYS, Profile, ProfileError, default_profile_path, load_profile

EXPECTED = {
    "ppi_target": 300, "ppi_floor": 150, "border_in": 0.1, "border_min_in": 0.0625,
    "min_line_pt": 1.0, "min_text_pt": 6.0, "cap_height_ratio": 0.7, "min_neck_in": 0.125,
    "max_upload_mb": 20, "soft_alpha_max_in": 0.03, "max_bridge_border_in": 0.25,
    "bg_delta_e": 8.0, "bg_ring_uniform_frac": 0.95, "edge_cut_min_run_in": 0.1,
    "speck_max_in2": 0.0004, "damage_max_frac": 0.02, "max_pieces": 8, "max_specks": 250,
}


@pytest.fixture
def raw():
    return yaml.safe_load(default_profile_path().read_text(encoding="utf-8"))


def test_loads_shipped_profile():
    p = load_profile()
    assert p.name == "stickermule-diecut"
    assert p.product == "die_cut"
    assert set(RULE_KEYS) == set(EXPECTED)
    for key, value in EXPECTED.items():
        assert getattr(p, key) == pytest.approx(value), key
        assert isinstance(getattr(p, key), float)
    assert set(p.sources) == set(p.whys) == set(EXPECTED)
    assert p.sources["ppi_floor"] == "convention"
    assert p.sources["ppi_target"].startswith("https://www.stickermule.com/")
    assert all(p.whys.values())
    assert p.max_upload_bytes == 20_000_000


def test_unit_helpers():
    assert Profile.pt_to_px(1.0, 300) == pytest.approx(300 / 72)
    assert Profile.in_to_px(0.1, 300) == pytest.approx(30)


def test_rejects_missing_key(raw):
    bad = copy.deepcopy(raw)
    del bad["rules"]["border_in"]
    with pytest.raises(ProfileError, match="border_in"):
        Profile.from_dict(bad)


def test_rejects_negative_value(raw):
    bad = copy.deepcopy(raw)
    bad["rules"]["min_neck_in"]["value"] = -0.125
    with pytest.raises(ProfileError, match="positive"):
        Profile.from_dict(bad)


def test_rejects_bad_source_and_fraction(raw):
    bad = copy.deepcopy(raw)
    bad["rules"]["border_in"]["source"] = "http://example.com/rules"
    with pytest.raises(ProfileError, match="source"):
        Profile.from_dict(bad)
    bad = copy.deepcopy(raw)
    bad["rules"]["bg_ring_uniform_frac"]["value"] = 95
    with pytest.raises(ProfileError, match="fraction"):
        Profile.from_dict(bad)


def test_rejects_unknown_rule_and_missing_file(raw, tmp_path):
    bad = copy.deepcopy(raw)
    bad["rules"]["min_internal_cut_in"] = {"value": 0.25, "source": "convention", "why": "old"}
    with pytest.raises(ProfileError, match="unknown"):
        Profile.from_dict(bad)
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "nope.yaml")
