"""Config, providers, pacing and usage. Same house style as labs 03-05, plus one new limit.

New in this lab: a TOKENS-per-minute pacer next to the requests-per-minute one. Labs 03-05
made short calls (~500 tokens) and only RPM ever mattered. Extraction calls are big: the
document, a JSON Schema, and the reasoning model's hidden chain of thought add up to
~1,500 tokens per call. Groq's free tier allows 30 RPM but only 8,000 TPM on gpt-oss-20b
(TECHNOLOGY_STACK.md), so at 2 s per call the TOKEN limit is hit after ~5 calls. On this
workload TPM, not RPM, decides how fast the run can go.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKSPACE_ENV = Path(__file__).resolve().parents[2] / ".env"

# Groq free tier is 30 RPM on gpt-oss-20b: one call per 2 s. Gemini's free RPM is still
# UNVERIFIED (TECHNOLOGY_STACK.md), so the same pace is used for both. Unchanged from lab 05.
MIN_SECONDS_BETWEEN_CALLS = 2.0

# Generous for three reasons. gpt-oss-20b reasons before it answers (lab 03 lost a whole run
# at 256). An invoice JSON with four line items is ~250 visible tokens on its own. And here a
# budget that runs out does not give you a short answer - it gives you JSON with no closing
# brace, which is reported as "truncated" and never parsed (main.py, finish_reason check).
MAX_TOKENS = 2048

# Temperature 0 because the output is PARSED, not read (exp-003: choose temperature by
# whether a program or a person consumes the output). There is no upside to creative
# variation in an invoice total. It is still not deterministic (lab 03, exp-005), which is
# why every raw output is stored in the transcript instead of being re-derived.
TEMPERATURE = 0.0

# Used by the TPM pacer before the first call of a provider has reported real usage.
DEFAULT_CALL_TOKENS = 1500


class Settings(BaseSettings):
    """Secrets come from the workspace-level .env (gitignored). Never hardcode keys."""

    model_config = SettingsConfigDict(env_file=WORKSPACE_ENV, extra="ignore")

    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None


@dataclass(frozen=True)
class Provider:
    """No `supports` set of modes, on purpose. Which modes a provider supports is the thing
    this lab is measuring; a hard-coded set would just encode the assumption under test and
    skip the call that disproves it. llm-kit has `structured_mode` because by the time it
    was written, somebody had found out. Here, an unsupported mode is a recorded result."""

    name: str
    base_url: str
    api_key: str
    model: str
    price_in_per_m: float  # USD per 1M input tokens (paid tier; free tier costs $0)
    price_out_per_m: float  # USD per 1M output tokens
    tpm: int | None  # free-tier tokens per minute; None = unknown, pace by RPM only


def build_provider(s: Settings, name: str) -> Provider | None:
    """One client shape, only base_url / model / price change. Same as labs 01-05."""
    if name == "groq" and s.groq_api_key:
        return Provider(
            "groq",
            "https://api.groq.com/openai/v1",
            s.groq_api_key.get_secret_value(),
            "openai/gpt-oss-20b",
            0.075,
            0.30,
            8000,
        )
    if name == "gemini" and s.gemini_api_key:
        return Provider(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            s.gemini_api_key.get_secret_value(),
            "gemini-3.5-flash-lite",
            0.30,
            2.50,
            None,  # UNVERIFIED: read it in AI Studio (TECHNOLOGY_STACK.md open item)
        )
    return None


def call_cost(p: Provider, usage: dict[str, int | None] | None) -> float:
    if not usage:
        return 0.0
    cost = (usage["prompt_tokens"] or 0) * p.price_in_per_m / 1e6
    return cost + (usage["completion_tokens"] or 0) * p.price_out_per_m / 1e6


# ---------------------------------------------------------------- pacing

_last_call_started: float | None = None
_token_log: dict[str, deque[tuple[float, int]]] = {}  # provider -> (when, tokens) per call
_last_call_tokens: dict[str, int] = {}


def rate_limit(p: Provider) -> float:
    """Pace the *next* call; returns the seconds slept. Call immediately before every
    request, error path included. Two limits:

    RPM, unchanged from labs 03-05: sleep BEFORE the call, only for the time still owed
    since the previous call STARTED.

    TPM, new: keep a 60 s sliding window of the tokens each call actually used (from
    `usage`), and before the next call wait until the window has room for an estimate of
    it (the previous call's size). This is an estimate, not a guarantee: whether Groq
    counts `max_tokens` against TPM when the request ARRIVES, or the tokens actually used
    when it FINISHES, is UNVERIFIED. If it is the former, this pacer is too optimistic and
    a 429 still happens - which `send()` in extract.py handles once, visibly.
    """
    global _last_call_started
    slept = 0.0
    if _last_call_started is not None:
        owed = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_started)
        if owed > 0:
            time.sleep(owed)
            slept += owed
    if p.tpm:
        log = _token_log.setdefault(p.name, deque())
        need = _last_call_tokens.get(p.name, DEFAULT_CALL_TOKENS)
        while log:
            now = time.monotonic()
            while log and now - log[0][0] > 60:
                log.popleft()
            if not log or sum(t for _, t in log) + need <= p.tpm:
                break
            wait = 60 - (now - log[0][0]) + 0.25
            time.sleep(wait)
            slept += wait
    _last_call_started = time.monotonic()
    return slept


def record_tokens(p: Provider, usage: dict[str, int | None] | None) -> None:
    """Feed the TPM window. Called after every call that reported usage."""
    if not usage:
        return
    total = (usage["prompt_tokens"] or 0) + (usage["completion_tokens"] or 0)
    _token_log.setdefault(p.name, deque()).append((time.monotonic(), total))
    _last_call_tokens[p.name] = total


# ---------------------------------------------------------------- response fields


def field_of(obj: Any, name: str) -> Any:
    """getattr that also works on plain dicts. Provider extras (Groq's `reasoning`) are not
    in the SDK's typed models and can arrive as raw dicts. Same helper as lab 05."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def usage_dict(usage: Any) -> dict[str, int | None] | None:
    """Normalise a usage block to plain ints. None stays None: "no usage" is a finding."""
    if usage is None:
        return None
    details = field_of(usage, "completion_tokens_details")
    return {
        "prompt_tokens": field_of(usage, "prompt_tokens"),
        "completion_tokens": field_of(usage, "completion_tokens"),
        "reasoning_tokens": field_of(details, "reasoning_tokens"),
    }
