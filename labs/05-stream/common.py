"""Shared by main.py (terminal) and server.py (FastAPI): config, providers, pacing, and the
one function that knows what a streamed chunk looks like.

Split out for one reason: both layers read the SAME chunk shape, and the chunk shape is the
lesson. If the parsing lived in two places, the terminal and the browser could disagree about
what "the first visible token" means, and every timing comparison between them would be
comparing two different definitions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKSPACE_ENV = Path(__file__).resolve().parents[2] / ".env"

# Groq free tier is 30 RPM on gpt-oss-20b (TECHNOLOGY_STACK.md section 1): one call per 2 s.
# Gemini's free RPM is still UNVERIFIED, so the same pace is used for both.
MIN_SECONDS_BETWEEN_CALLS = 2.0

# Generous, because lab 03 lost a whole run at 256: gpt-oss-20b spends completion tokens on
# hidden reasoning before anything visible. Here that matters twice over - a budget that runs
# out mid-reasoning gives you a stream that is ALL reasoning and no content, so the headline
# number of this lab ("time to first visible token") would simply never happen.
MAX_TOKENS = 1536

# Temperature 0 here is an EXPERIMENTAL CONTROL, not a product decision. exp-003 says prose
# that a human reads can have any temperature. But section C compares total time between
# streamed and non-streamed calls, and total time is mostly "how many tokens were decoded".
# Holding the output as steady as we can makes that comparison about the transport rather
# than about one run happening to write a longer answer. (Still not deterministic - lab 03.)
TEMPERATURE = 0.0

# Synthetic and public (free-tier prompts may train the provider's models). A few paragraphs
# long on purpose: a one-line answer arrives in one or two chunks and there is nothing to
# watch stream.
DEFAULT_PROMPT = (
    "Explain how a changelog generator could group commits into sections for release notes, "
    "in three short paragraphs."
)


class Settings(BaseSettings):
    """Secrets come from the workspace-level .env (gitignored). Never hardcode keys."""

    model_config = SettingsConfigDict(env_file=WORKSPACE_ENV, extra="ignore")

    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    price_in_per_m: float  # USD per 1M input tokens
    price_out_per_m: float  # USD per 1M output tokens


def build_provider(s: Settings, name: str) -> Provider | None:
    """One client shape, only base_url / model / price change. Same as labs 01-04."""
    if name == "groq" and s.groq_api_key:
        return Provider(
            "groq",
            "https://api.groq.com/openai/v1",
            s.groq_api_key.get_secret_value(),
            "openai/gpt-oss-20b",
            0.075,
            0.30,
        )
    if name == "gemini" and s.gemini_api_key:
        return Provider(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            s.gemini_api_key.get_secret_value(),
            "gemini-3.5-flash-lite",
            0.30,
            2.50,
        )
    return None


_last_call_started: float | None = None


def rate_limit() -> None:
    """Pace the *next* call. Call immediately before every network request. Unchanged from
    labs 03/04: sleep BEFORE the call, only for the time still owed since the previous call
    STARTED, so it also runs on the error path and never costs anything after the last call.

    Note what "started" means for a stream: the request opens, then the body trickles in for
    several seconds. The rate limit counts requests, not seconds of streaming, so pacing from
    the start is correct - a 6 s stream followed immediately by the next call is fine.
    """
    global _last_call_started
    if _last_call_started is not None:
        owed = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_started)
        if owed > 0:
            time.sleep(owed)
    _last_call_started = time.monotonic()


# ---------------------------------------------------------------- the chunk shape


def _field(obj: Any, name: str) -> Any:
    """getattr that also works on plain dicts. Provider-specific extras (Groq's `reasoning`,
    `x_groq`) are not in the SDK's typed models; pydantic keeps them as extra attributes, and
    nested ones can come back as raw dicts. Read defensively or crash on the other provider."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def usage_dict(usage: Any) -> dict[str, int | None] | None:
    """Normalise a usage block (SDK object or raw dict) to plain ints. None stays None -
    "the provider sent no usage" is a finding in this lab, not something to paper over."""
    if usage is None:
        return None
    details = _field(usage, "completion_tokens_details")
    return {
        "prompt_tokens": _field(usage, "prompt_tokens"),
        "completion_tokens": _field(usage, "completion_tokens"),
        # Hidden chain of thought, billed at the output rate. Lab 03: 84-95% of the output.
        "reasoning_tokens": _field(details, "reasoning_tokens"),
    }


@dataclass
class Delta:
    """Everything one streamed chunk can carry. Most chunks carry exactly one of these."""

    reasoning: str = ""  # hidden-thinking text, if the provider streams it at all
    content: str = ""  # the visible answer - the only part a product normally shows
    finish_reason: str | None = None  # only on the last choice-bearing chunk
    usage: dict[str, int | None] | None = None  # standard `chunk.usage`, if requested
    groq_usage: dict[str, int | None] | None = None  # Groq's non-standard `x_groq.usage`
    has_choices: bool = False


def read_chunk(chunk: Any) -> Delta:
    """Pull the useful fields out of one `ChatCompletionChunk`.

    What a stream actually looks like, chunk by chunk (gpt-oss-20b on Groq):

        {choices:[{delta:{role:"assistant"}}]}                  <- often empty; still a chunk
        {choices:[{delta:{reasoning:"The user wants"}}]}        <- hidden thinking, NOT content
        ... a few hundred more reasoning deltas ...
        {choices:[{delta:{content:"A changelog"}}]}             <- first VISIBLE token
        ... content deltas ...
        {choices:[{delta:{}, finish_reason:"stop"}]}            <- why it stopped
        {choices:[], usage:{...}}                               <- ONLY if include_usage

    The `reasoning` field is Groq's, not part of the OpenAI spec (OpenAI itself never streams
    reasoning text; DeepSeek-style hosts call it `reasoning_content`). Both are read, neither
    is assumed. Gemini's OpenAI layer does not stream its thinking unless asked, so on Gemini
    the reasoning happens but is invisible: the wait just moves in front of the first chunk.
    """
    d = Delta(usage=usage_dict(_field(chunk, "usage")))
    d.groq_usage = usage_dict(_field(_field(chunk, "x_groq"), "usage"))
    choices = _field(chunk, "choices") or []
    if not choices:
        return d
    d.has_choices = True
    choice = choices[0]
    delta = _field(choice, "delta")
    d.reasoning = _field(delta, "reasoning") or _field(delta, "reasoning_content") or ""
    d.content = _field(delta, "content") or ""
    d.finish_reason = _field(choice, "finish_reason")
    return d
