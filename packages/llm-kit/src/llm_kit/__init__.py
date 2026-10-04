"""llm-kit: a thin, fully-understood provider layer over any OpenAI-compatible LLM API.

Not a framework. About 700 lines, every one of which should be explainable on demand -
that is the acceptance criterion, per CLAUDE.md rule 6: build the concept by hand before
adopting the framework, and know exactly what the framework would have been doing.

    from llm_kit import LLM, Ledger, Tool

    ledger = Ledger(max_usd=0.05)
    llm = LLM(provider="groq", tier="fast", ledger=ledger)
    print(llm.complete("Say hello in five words.").text)
    print(ledger.summary())

What it deliberately does NOT do: prompt templating (projects own their prompts, versioned
as files), chains, memory, RAG, or anything that would make swapping it out expensive.
"""

from .client import LLM, AgentResult, Completion, Messages
from .errors import (
    LLMBudgetError,
    LLMError,
    LLMOutputError,
    LLMPermanentError,
    LLMTransientError,
)
from .pricing import PRICES, PRICES_VERIFIED_ON, cost_usd, price_for
from .providers import DEFAULT_PROVIDER, PROVIDERS, Provider, Settings, resolve
from .retry import RetryPolicy, classify, with_retries
from .tools import Tool, ToolError, ToolOutcome, dispatch
from .usage import CallRecord, Ledger, Usage

__all__ = [
    "AgentResult",
    "CallRecord",
    "Completion",
    "DEFAULT_PROVIDER",
    "LLM",
    "LLMBudgetError",
    "LLMError",
    "LLMOutputError",
    "LLMPermanentError",
    "LLMTransientError",
    "Ledger",
    "Messages",
    "PRICES",
    "PRICES_VERIFIED_ON",
    "PROVIDERS",
    "Provider",
    "RetryPolicy",
    "Settings",
    "Tool",
    "ToolError",
    "ToolOutcome",
    "Usage",
    "classify",
    "cost_usd",
    "dispatch",
    "price_for",
    "resolve",
    "with_retries",
]

__version__ = "0.1.0"
