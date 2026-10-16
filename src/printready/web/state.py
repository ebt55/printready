"""Payload for GET /api/state: profile (values and sources), models with prices, spend ledger.

Prices: if the LLM chunk's `printready.spend` module exposes a PRICES table it wins; otherwise the
fallback below (from RESEARCH-FACTS.md, USD per 1M tokens) is used for estimates only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from printready import __version__

PROFILE_LABEL = "Sticker Mule die-cut rules (paraphrased from public FAQ)"
DEFAULT_CAP_USD = 10.00
STOP_AT_USD = 8.00  # 02-BUILD-CHUNKS: past $8, stop live work and ask

# model id -> (input, cached input, output) USD per 1M tokens
FALLBACK_PRICES: dict[str, tuple[float, float, float]] = {
    "xai:grok-4.3": (1.25, 0.20, 2.50),
    "xai:grok-4.7": (2.00, 0.50, 6.00),
}
MODELS = [
    {"id": "xai:grok-4.3", "label": "grok-4.3", "note": "default; cheapest Grok with vision and tools"},
    {"id": "xai:grok-4.7", "label": "grok-4.7", "note": "larger, about 2x the price"},
]
# Rough per-run token budgets used for the up-front estimate (8-turn cap, 768 px images).
AGENT_EST_TOKENS = {"in": 26_000, "cached": 12_000, "out": 1_400}
VISION_EST_TOKENS = {"in": 2_200, "cached": 0, "out": 220}

# How each profile value is shown: unit suffix and a short human name.
RULE_META: dict[str, tuple[str, str]] = {
    "ppi_target": ("PPI", "Resolution target"),
    "ppi_floor": ("PPI", "Resolution floor"),
    "border_in": ("in", "Standard border"),
    "border_min_in": ("in", "Minimum border"),
    "min_line_pt": ("pt", "Thinnest line"),
    "min_text_pt": ("pt", "Smallest text"),
    "cap_height_ratio": ("x", "Cap height / point size"),
    "min_neck_in": ("in", "Narrowest waist"),
    "max_upload_mb": ("MB", "Upload limit"),
    "soft_alpha_max_in": ("in", "Soft edge band"),
    "max_bridge_border_in": ("in", "Widest bridging border"),
    "bg_delta_e": ("dE", "Background colour tolerance"),
    "bg_ring_uniform_frac": ("", "Solid background share"),
    "edge_cut_min_run_in": ("in", "Cut-off edge run"),
    "speck_max_in2": ("in2", "Speck size"),
    "damage_max_frac": ("", "Background removal damage"),
    "max_pieces": ("", "Most separate pieces"),
    "max_specks": ("", "Most specks to drop"),
    "bleed_in": ("in", "Bleed past the cut"),
    "shape_corner_radius_in": ("in", "Rounded-rectangle corners"),
}


def prices() -> dict[str, tuple[float, float, float]]:
    try:  # the LLM chunk's spend module, once it exists, is the source of truth
        from printready import spend  # type: ignore[attr-defined]

        table = getattr(spend, "PRICES", None)
        if isinstance(table, dict) and table:
            merged = dict(FALLBACK_PRICES)
            for k, v in table.items():
                if hasattr(v, "in_per_m"):  # spend.Price
                    if v.in_per_m or v.out_per_m:
                        merged[k] = (float(v.in_per_m), float(v.cached_per_m), float(v.out_per_m))
                elif isinstance(v, (tuple, list)) and len(v) == 3:
                    merged[k] = tuple(float(x) for x in v)
            return merged
    except Exception:
        pass
    return FALLBACK_PRICES


def token_cost(model: str, tokens_in: int, tokens_cached: int, tokens_out: int) -> float:
    p_in, p_cached, p_out = prices().get(model, FALLBACK_PRICES["xai:grok-4.3"])
    fresh = max(0, tokens_in - tokens_cached)
    return (fresh * p_in + tokens_cached * p_cached + tokens_out * p_out) / 1_000_000


def estimate_usd(mode: str, model: str | None, vision: bool) -> float:
    """Up-front estimate shown before a paid run (an upper-end figure, not a promise)."""
    model = model or MODELS[0]["id"]
    if mode == "agent":
        t = AGENT_EST_TOKENS
    elif vision:
        t = VISION_EST_TOKENS
    else:
        return 0.0
    return round(token_cost(model, t["in"], t["cached"], t["out"]), 4)


def spend_cap() -> float:
    try:
        from printready import spend

        return float(spend.cap_usd())
    except Exception:
        pass
    try:
        return float(os.environ.get("PRINTREADY_SPEND_CAP_USD", DEFAULT_CAP_USD))
    except ValueError:
        return DEFAULT_CAP_USD


def ledger_total(path: Path) -> float:
    """Sum of `usd` over results/spend-ledger.jsonl; a missing file is $0.00, bad lines are skipped."""
    total = 0.0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0.0
    for line in lines:
        try:
            total += float(json.loads(line).get("usd", 0) or 0)
        except (ValueError, TypeError, AttributeError):
            continue
    return round(total, 4)


def profile_payload() -> dict[str, Any]:
    """The shipped profile as JSON: every rule with value, unit, source and why."""
    rules: list[dict[str, Any]] = []
    name, product = "stickermule-diecut", "die_cut"
    try:
        from printready.profile import RULE_KEYS, load_profile

        prof = load_profile()
        name, product = prof.name, prof.product
        for key in RULE_KEYS:
            unit, label = RULE_META.get(key, ("", key))
            rules.append({"key": key, "label": label, "value": getattr(prof, key), "unit": unit,
                          "source": prof.sources.get(key, "convention"), "why": prof.whys.get(key, "")})
    except Exception as exc:  # the UI still works with an empty rule list
        return {"name": name, "product": product, "label": PROFILE_LABEL, "rules": [], "error": str(exc)}
    return {"name": name, "product": product, "label": PROFILE_LABEL, "rules": rules}


def profile_values() -> dict[str, float]:
    return {r["key"]: float(r["value"]) for r in profile_payload()["rules"]}


def models_payload() -> list[dict[str, Any]]:
    out = []
    table = prices()
    for m in MODELS:
        p_in, p_cached, p_out = table.get(m["id"], FALLBACK_PRICES["xai:grok-4.3"])
        out.append({**m, "price_in": p_in, "price_cached": p_cached, "price_out": p_out,
                    "est_agent_usd": estimate_usd("agent", m["id"], False),
                    "est_vision_usd": estimate_usd("rules", m["id"], True)})
    return out


def spend_payload(root: Path) -> dict[str, Any]:
    from printready.web.paths import ledger_path

    path = ledger_path(root)
    return {"total_usd": ledger_total(path), "cap_usd": spend_cap(), "stop_at_usd": STOP_AT_USD,
            "ledger": "results/spend-ledger.jsonl", "ledger_exists": path.exists()}


def version() -> str:
    return __version__
