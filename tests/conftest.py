"""Shared test setup: every test gets a temporary spend ledger, so the committed
results/spend-ledger.jsonl only ever records real spend. Live tests (PRINTREADY_LIVE=1) keep the
real ledger on purpose: their calls are paid and must be counted against the cap."""

import os

import pytest

from printready import spend


@pytest.fixture(autouse=True)
def _temporary_spend_ledger(tmp_path, monkeypatch):
    if os.environ.get("PRINTREADY_LIVE") != "1":
        monkeypatch.setenv(spend.LEDGER_ENV, str(tmp_path / "spend-ledger.jsonl"))
