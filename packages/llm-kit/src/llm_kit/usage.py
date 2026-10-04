"""Per-call accounting: what was sent, what came back, what it cost, how long it took.

The ledger is a large part of why this library exists rather than calling `openai`
directly at every call site. One object that every call passes through means a project can
answer "what did this request cost, and why" without instrumenting each call separately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .pricing import cost_usd, price_for


@dataclass(frozen=True)
class Usage:
    """Token counts as the provider reported them.

    `reasoning_tokens` matters more than it looks: lab 03 measured gpt-oss-20b spending
    250-520 completion tokens on hidden chain-of-thought for a one-line answer, i.e.
    84-95% of the output bill was text nobody ever sees. A completion-token count without
    it is not an explanation of the invoice.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.reasoning_tokens + other.reasoning_tokens,
        )

    @classmethod
    def from_response(cls, raw: Any) -> Usage:
        """Read usage off an OpenAI-shaped response, tolerating providers that omit it.

        Not every OpenAI-compatible endpoint fills every field (Ollama reports no
        reasoning tokens; some proxies report no usage at all). Missing usage must degrade
        to zeros, never crash a call that already succeeded and already cost money.
        """
        usage = getattr(raw, "usage", None)
        if usage is None:
            return cls()
        details = getattr(usage, "completion_tokens_details", None)
        reasoning = (getattr(details, "reasoning_tokens", 0) or 0) if details else 0
        return cls(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            reasoning_tokens=reasoning,
        )


@dataclass
class CallRecord:
    """One LLM call, after the fact.

    The unit of everything downstream: cost reports, traces, eval runs, and debugging a
    prompt that regressed last Tuesday.
    """

    provider: str
    model: str
    label: str
    usage: Usage
    latency_s: float
    finish_reason: str | None = None
    attempts: int = 1
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def cost_usd(self) -> float:
        return cost_usd(self.model, self.usage.prompt_tokens, self.usage.completion_tokens)

    @property
    def price_known(self) -> bool:
        return price_for(self.model)[1]

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "provider": self.provider,
            "model": self.model,
            "label": self.label,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "reasoning_tokens": self.usage.reasoning_tokens,
            "latency_s": round(self.latency_s, 3),
            "finish_reason": self.finish_reason,
            "attempts": self.attempts,
            "cost_usd": round(self.cost_usd, 8),
            "price_known": self.price_known,
            "error": self.error,
        }


class Ledger:
    """Accumulates CallRecords for one run, and enforces a hard spend ceiling.

    The ceiling is checked *before* each call rather than after, because an after-the-fact
    limit on an unbounded loop is a receipt, not a control.
    """

    def __init__(self, *, max_usd: float | None = None, max_calls: int | None = None):
        self.records: list[CallRecord] = []
        self.max_usd = max_usd
        self.max_calls = max_calls

    def add(self, record: CallRecord) -> CallRecord:
        self.records.append(record)
        return record

    @property
    def total_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def total_usage(self) -> Usage:
        total = Usage()
        for record in self.records:
            total = total + record.usage
        return total

    def would_exceed(self) -> str | None:
        """Return a human-readable reason if the NEXT call should not be made."""
        if self.max_calls is not None and len(self.records) >= self.max_calls:
            return f"call budget exhausted: {len(self.records)}/{self.max_calls} calls made"
        if self.max_usd is not None and self.total_usd >= self.max_usd:
            return f"cost budget exhausted: ${self.total_usd:.6f} of ${self.max_usd:.6f} spent"
        return None

    def summary(self) -> str:
        usage = self.total_usage
        unknown = sum(1 for r in self.records if not r.price_known)
        warn = f"  [!] {unknown} call(s) used an unpriced model" if unknown else ""
        return (
            f"{len(self.records)} calls  "
            f"{usage.prompt_tokens} in / {usage.completion_tokens} out "
            f"({usage.reasoning_tokens} hidden reasoning)  "
            f"${self.total_usd:.6f} at paid rates{warn}"
        )

    def write_jsonl(self, path: str | Path) -> Path:
        """One JSON object per line: greppable, appendable, and trivially loadable into a
        dataframe once a project starts asking cost questions across many runs."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for record in self.records:
                handle.write(json.dumps(record.as_dict()) + "\n")
        return target
