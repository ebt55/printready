import copy

import pytest
import yaml

from printready.profile import RULE_KEYS, Profile, ProfileError, default_profile_path, load_profile


@pytest.fixture
def raw():
    return yaml.safe_load(default_profile_path().read_text(encoding="utf-8"))


def test_loads_shipped_profile():
    p = load_profile()
    assert p.name == "stickermule-diecut"
    assert p.product == "die_cut"
    assert (p.ppi_target, p.ppi_floor) == (300, 150)
    assert (p.border_in, p.border_min_in) == (0.1, 0.0625)
    assert (p.min_line_pt, p.min_text_pt) == (1.0, 6.0)
    assert p.min_internal_cut_in == 0.25
    assert p.min_neck_in == 0.125
    assert p.max_upload_mb == 20
    assert p.soft_alpha_max_in == 0.03
    assert p.max_bridge_border_in == 0.25
    assert set(p.rules) == set(RULE_KEYS)
    assert p.rules["ppi_floor"].source == "convention"
    assert p.rules["ppi_target"].source.startswith("https://www.stickermule.com/")
    assert all(rule.why for rule in p.rules.values())


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


def test_rejects_bad_source(raw):
    bad = copy.deepcopy(raw)
    bad["rules"]["border_in"]["source"] = "http://example.com/rules"
    with pytest.raises(ProfileError, match="source"):
        Profile.from_dict(bad)


def test_rejects_missing_file(tmp_path):
    with pytest.raises(ProfileError):
        load_profile(tmp_path / "nope.yaml")
