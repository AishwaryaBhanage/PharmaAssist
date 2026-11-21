"""Cost of one completion, priced at the serving role's rates (config `llm.<role>.prices_per_mtok`).

Prices are USD per million tokens with the four keys the canonical `Usage` has. A missing key costs
nothing, so a provider that reports no cache tokens prices the same as one that does. gpt-5.5's
list (https://developers.openai.com/api/docs/pricing, read 2026-10-18): $5.00 input, $0.50 cached
input, $30.00 output per 1M tokens for prompts under 272K tokens; cache writes are not charged,
so `cache_write` is 0. Prompts past 272K tokens bill at the long-context rates ($10 / $1 / $45),
which the agent never reaches.
"""

from pharmassist.llm.base import Usage

KEYS = ("input", "output", "cache_read", "cache_write")


def cost_usd(usage: Usage | dict, prices: dict | None) -> float:
    """Dollars for one call, rounded to a millionth. `usage` may be a Usage or its dict form."""
    prices = prices or {}
    u = usage if isinstance(usage, dict) else {k: getattr(usage, k) for k in KEYS}
    return round(sum((u.get(k) or 0) * float(prices.get(k) or 0) for k in KEYS) / 1_000_000, 6)
