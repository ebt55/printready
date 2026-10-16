import json

import pytest

from printready import spend
from printready.spend import BudgetExceeded, Price, UnknownPrice


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv(spend.LEDGER_ENV, str(path))
    monkeypatch.delenv(spend.CAP_ENV, raising=False)
    return path


def test_price_table_matches_xai_list_prices():
    assert spend.price_for("xai:grok-4.3") == Price(1.25, 0.20, 2.50)
    assert spend.price_for("xai:grok-4.7") == Price(2.00, 0.50, 6.00)
    assert spend.price_for("xai:grok-imagine-image").per_image == 0.02
    assert spend.price_for("xai:grok-imagine-image-2.0").per_image == 0.04
    assert spend.price_for("xai:grok-imagine-image-quality").per_image == 0.05


def test_unknown_model_is_refused_unless_a_price_is_given():
    with pytest.raises(UnknownPrice, match="grok-9"):
        spend.price_for("xai:grok-9")
    with pytest.raises(UnknownPrice):
        spend.price_for("openrouter:x-ai/grok-4.3")
    given = Price(in_per_m=1.0)
    assert spend.price_for("xai:grok-9", given) is given
    assert spend.price_for("fake:script.json").free


def test_cost_bills_cached_tokens_at_the_cached_rate():
    p = spend.price_for("xai:grok-4.3")
    # 1M prompt tokens of which 200k cached, 100k out: 0.8 * 1.25 + 0.2 * 0.20 + 0.1 * 2.50
    assert spend.cost(p, tokens_in=1_000_000, tokens_cached=200_000, tokens_out=100_000) == pytest.approx(1.29)
    assert spend.cost(spend.price_for("xai:grok-imagine-image-2.0"), images=3) == pytest.approx(0.12)


def test_estimate_is_the_uncached_worst_case():
    p = spend.price_for("xai:grok-4.7")
    assert spend.estimate(p, tokens_in=10_000, tokens_out=4_096) == pytest.approx(0.02 + 4096 * 6 / 1e6)
    assert spend.estimate(p, tokens_in=10_000) > spend.cost(p, tokens_in=10_000, tokens_cached=10_000)


def test_record_appends_numbers_only_and_total_sums(ledger):
    assert spend.ledger_total() == 0.0
    e1 = spend.record("xai", "grok-4.3", 1200, 0, 300, 0, 0.00225, "agent")
    spend.record("xai", "grok-imagine-image", 0, 0, 0, 1, 0.02, "realset")
    lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2 and lines[0] == e1
    assert set(e1) == {"ts", "provider", "model", "tokens_in", "tokens_cached", "tokens_out", "images", "usd", "purpose"}
    assert spend.ledger_total() == pytest.approx(0.02225)


def test_check_cap_refuses_before_the_call(ledger, monkeypatch):
    spend.record("xai", "grok-4.3", 0, 0, 0, 0, 9.99, "earlier")
    spend.check_cap(0.01)  # exactly at the default 10.00 cap is allowed
    with pytest.raises(BudgetExceeded, match="10.00 cap"):
        spend.check_cap(0.02)
    monkeypatch.setenv(spend.CAP_ENV, "20")
    spend.check_cap(5.0)
    with pytest.raises(BudgetExceeded):
        spend.check_cap(0.5, cap=10.0)


def test_cap_and_ledger_path_come_from_the_environment(tmp_path, monkeypatch):
    assert spend.cap_usd() == 10.0
    monkeypatch.setenv(spend.CAP_ENV, "2.5")
    assert spend.cap_usd() == 2.5
    monkeypatch.setenv(spend.CAP_ENV, "lots")
    with pytest.raises(ValueError):
        spend.cap_usd()
    other = tmp_path / "other.jsonl"
    assert spend.ledger_path(other) == other
    monkeypatch.delenv(spend.LEDGER_ENV)
    assert spend.ledger_path().name == "spend-ledger.jsonl" and spend.ledger_path().parent.name == "results"
