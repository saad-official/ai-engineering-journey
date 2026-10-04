"""What a call costs, in dollars, computed from the provider's own usage numbers.

Every price here is USD per 1,000,000 tokens and comes from TECHNOLOGY_STACK.md, which
was verified on 2026-09-05. Prices move. `PRICES_VERIFIED_ON` exists so a cost report can
print the date it is trusting, and so a stale table is visible rather than silent.

Why a library computes cost at all, when the current stack is entirely free tier:

  - "Free tier" is a quota, not an economics lesson. The number that matters for a project
    is cost *per user action* at paid rates, because that is the number that decides
    whether the product can exist. Measuring it from day one on free calls costs nothing.
  - Cost is the cheapest available proxy for prompt bloat. A prompt that quietly doubled
    in tokens shows up in this ledger before it shows up in a latency graph.
  - Model routing (cheap model to classify, better model for prose) is only justifiable
    with numbers on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass

PRICES_VERIFIED_ON = "2026-09-05"


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens. `free_tier` means a quota exists, NOT that the model is free."""

    input_per_m: float
    output_per_m: float
    free_tier: bool = False
    note: str = ""


# Keys are the model ids we actually send, so a typo in a model id shows up as a missing
# price rather than being silently charged at someone else's rate.
PRICES: dict[str, ModelPrice] = {
    # --- Google Gemini (primary) -------------------------------------------------
    "gemini-3.5-flash-lite": ModelPrice(0.30, 2.50, free_tier=True, note="workhorse"),
    "gemini-3.8-flash": ModelPrice(
        0.75, 3.75, free_tier=True, note="quality tier; promo price to 2026-12-31"
    ),
    "gemini-embedding-2": ModelPrice(0.20, 0.0, free_tier=True, note="embeddings"),
    # --- Groq (secondary; fast, good for agent loops) ----------------------------
    "openai/gpt-oss-20b": ModelPrice(0.075, 0.30, free_tier=True, note="fast tier"),
    "openai/gpt-oss-120b": ModelPrice(0.15, 0.60, free_tier=True, note="quality tier"),
    "qwen/qwen3.8-27b": ModelPrice(0.10, 0.40, free_tier=True),
    # --- Local (Ollama) ----------------------------------------------------------
    # Not actually zero - it is electricity and 100% of a CPU you wanted for other things -
    # but zero *marginal dollars*, which is what a budget guard cares about.
    "qwen3.5:4b": ModelPrice(0.0, 0.0, note="local"),
    "qwen3:1.7b": ModelPrice(0.0, 0.0, note="local"),
    "nomic-embed-text": ModelPrice(0.0, 0.0, note="local embeddings"),
}

# An unknown model must not silently cost $0.00 - that turns a missing price into a
# reassuring lie in every cost report. Charged at the most expensive rate we know so the
# error is conservative, and flagged so the caller can see it happened.
UNKNOWN_MODEL_PRICE = ModelPrice(
    max(p.input_per_m for p in PRICES.values()),
    max(p.output_per_m for p in PRICES.values()),
    note="UNKNOWN MODEL - priced at the worst known rate; add it to PRICES",
)


def price_for(model: str) -> tuple[ModelPrice, bool]:
    """Return (price, is_known). Never raises: a missing price must not break a call."""
    price = PRICES.get(model)
    if price is None:
        return UNKNOWN_MODEL_PRICE, False
    return price, True


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Dollar cost of one call at *paid* rates, whatever tier it actually ran on.

    Deliberately ignores the free tier. The question this answers is "what would this cost
    if it were real traffic", which is the only version of the number that is useful when
    deciding whether a feature can ship.
    """
    price, _ = price_for(model)
    return (prompt_tokens * price.input_per_m + completion_tokens * price.output_per_m) / 1_000_000
