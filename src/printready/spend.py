"""Spend guard: one price table, one ledger, one hard cap for every paid call (chat and images).

Every live call goes estimate -> check_cap -> call -> record:
- `estimate` is a worst case (no cached tokens, the full max_tokens out) so the cap is checked
  BEFORE the money is spent; `check_cap` raises BudgetExceeded when
  ledger_total + estimate > PRINTREADY_SPEND_CAP_USD (default 10.00).
- `record` appends what the call actually used, priced from the returned usage, to
  results/spend-ledger.jsonl. The ledger holds numbers only: no prompts, no keys.

Token convention: `tokens_in` is ALL prompt tokens, cached ones included; `tokens_cached` is the
cached subset (billed at the cached rate); `tokens_out` includes any reasoning tokens.
The ledger path can be moved with PRINTREADY_SPEND_LEDGER (tests do this) or a `path` argument.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CAP_USD = 10.00
CAP_ENV = "PRINTREADY_SPEND_CAP_USD"
LEDGER_ENV = "PRINTREADY_SPEND_LEDGER"
PER_M = 1_000_000


class BudgetExceeded(RuntimeError):
    """The next call would take the ledger past the spend cap. Raised before the call is made."""


class UnknownPrice(ValueError):
    """No price is known for this model; paid calls to it are refused unless a price is given."""


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens (input, cached input, output) and per generated image."""

    in_per_m: float = 0.0
    cached_per_m: float = 0.0
    out_per_m: float = 0.0
    per_image: float = 0.0

    @property
    def free(self) -> bool:
        return not (self.in_per_m or self.cached_per_m or self.out_per_m or self.per_image)


# Keyed by "<provider>:<model>" as passed to make_client / generate_image (xAI list prices, Oct 2026).
PRICES: dict[str, Price] = {
    "xai:grok-4.3": Price(in_per_m=1.25, cached_per_m=0.20, out_per_m=2.50),
    "xai:grok-4.7": Price(in_per_m=2.00, cached_per_m=0.50, out_per_m=6.00),
    "xai:grok-imagine-image": Price(per_image=0.02),
    "xai:grok-imagine-image-2.0": Price(per_image=0.04),
    "xai:grok-imagine-image-quality": Price(per_image=0.05),
}
FREE_PROVIDERS = ("fake",)  # scripted test responses cost nothing

_lock = threading.Lock()  # the workbench may run several images at once


def price_for(model: str, price: Price | None = None) -> Price:
    """The price for "<provider>:<model>". An explicit `price` wins; unknown paid models raise."""
    if price is not None:
        return price
    if model.split(":", 1)[0] in FREE_PROVIDERS:
        return Price()
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownPrice(f"no price known for {model!r}; add it to spend.PRICES or pass a price") from None


def cost(
    price: Price, tokens_in: int = 0, tokens_cached: int = 0, tokens_out: int = 0, images: int = 0
) -> float:
    """USD for one call's actual usage (`tokens_in` includes `tokens_cached`)."""
    cached = min(tokens_cached, tokens_in)
    return (
        (tokens_in - cached) * price.in_per_m / PER_M
        + cached * price.cached_per_m / PER_M
        + tokens_out * price.out_per_m / PER_M
        + images * price.per_image
    )


def estimate(price: Price, tokens_in: int = 0, tokens_out: int = 0, images: int = 0) -> float:
    """Worst-case USD before a call: no input assumed cached, `tokens_out` = the max allowed."""
    return cost(price, tokens_in=tokens_in, tokens_out=tokens_out, images=images)


def cap_usd() -> float:
    """The hard cap from PRINTREADY_SPEND_CAP_USD (default 10.00)."""
    raw = os.environ.get(CAP_ENV, "").strip()
    if not raw:
        return DEFAULT_CAP_USD
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{CAP_ENV} must be a number of US dollars, got {raw!r}") from None


def ledger_path(path: str | Path | None = None) -> Path:
    """`path`, else PRINTREADY_SPEND_LEDGER, else <repo>/results/spend-ledger.jsonl."""
    if path is not None:
        return Path(path)
    if os.environ.get(LEDGER_ENV):
        return Path(os.environ[LEDGER_ENV])
    return repo_root() / "results" / "spend-ledger.jsonl"


def repo_root() -> Path:
    """The source checkout this module runs from (has pyproject.toml), else the working directory."""
    root = Path(__file__).resolve().parents[2]
    return root if (root / "pyproject.toml").exists() else Path.cwd()


def ledger_total(path: str | Path | None = None) -> float:
    """Sum of `usd` over every ledger line (0 if the ledger does not exist yet)."""
    p = ledger_path(path)
    if not p.exists():
        return 0.0
    total = 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            total += float(json.loads(line)["usd"])
    return total


def check_cap(estimate_usd: float, path: str | Path | None = None, cap: float | None = None) -> None:
    """Raise BudgetExceeded if ledger_total + estimate_usd would pass the cap."""
    limit = cap_usd() if cap is None else cap
    spent = ledger_total(path)
    if spent + estimate_usd > limit:
        raise BudgetExceeded(
            f"spend cap reached: ledger ${spent:.4f} + this call up to ${estimate_usd:.4f} "
            f"would pass the ${limit:.2f} cap ({CAP_ENV})"
        )


def record(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_cached: int,
    tokens_out: int,
    images: int,
    usd: float,
    purpose: str,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Append one actual-usage line to the ledger and return it."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": provider,
        "model": model,
        "tokens_in": int(tokens_in),
        "tokens_cached": int(tokens_cached),
        "tokens_out": int(tokens_out),
        "images": int(images),
        "usd": round(float(usd), 6),
        "purpose": purpose,
    }
    p = ledger_path(path)
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    return entry
