"""Provider configuration: the one place that knows a base URL, a key, and model ids.

The bet this library makes is that *every* provider worth using speaks the OpenAI wire
format, so swapping vendors is a `base_url` and a model id, not a rewrite. That bet holds
today for Gemini (via its `/v1beta/openai/` compatibility endpoint), Groq, OpenRouter,
Ollama, DeepSeek, Together, and most of the rest.

Where the bet leaks - and it does - is documented per provider below in `quirks`. Knowing
precisely where portability ends is the actual skill; "it's all OpenAI-compatible" is what
people say right before a structured output silently stops validating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every lab and project in this workspace reads the same root .env, so one key rotation is
# one edit. Projects that later live in their own repo override this with their own path.
WORKSPACE_ENV = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    """Keys, loaded from the environment or the workspace .env. Never hardcoded.

    `SecretStr` so an accidental `print(settings)` or an exception rendering the settings
    object into a log emits `SecretStr('**********')` instead of an API key. Cheap habit,
    and the failure it prevents is a key in a public repo's CI log.
    """

    model_config = SettingsConfigDict(
        env_file=WORKSPACE_ENV, env_file_encoding="utf-8", extra="ignore"
    )

    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: str = "ollama"


@dataclass(frozen=True)
class Provider:
    """Everything needed to talk to one vendor, plus what it gets wrong."""

    name: str
    base_url: str
    api_key_field: str
    # The two-tier default. Routing cheap-vs-capable is a per-project decision, but having
    # a sane default pair on every provider makes `LLM(provider="groq")` immediately
    # useful without a model-id lookup.
    fast_model: str
    quality_model: str
    # How structured output is requested. Providers diverge here more than anywhere else.
    #   "json_schema"  - native schema enforcement (grammar-constrained). Trustworthy.
    #   "json_object"  - "emit valid JSON" with no schema. Shape is a hope, not a promise.
    structured_mode: str = "json_schema"
    supports_tools: bool = True
    # Free-tier requests per minute, where documented. Used to pace calls; None means
    # unverified, and the client then applies the most conservative pace it knows.
    free_rpm: int | None = None
    quirks: tuple[str, ...] = field(default_factory=tuple)


PROVIDERS: dict[str, Provider] = {
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_field="gemini_api_key",
        fast_model="gemini-3.5-flash-lite",
        quality_model="gemini-3.8-flash",
        structured_mode="json_schema",
        free_rpm=None,  # UNVERIFIED: read the live numbers in AI Studio, then record here
        quirks=(
            "Free-tier prompts are used to improve Google's products: never send private "
            "or company data through the free tier.",
            "Its JSON-Schema subset is narrower than OpenAI's; `$ref`, some unions and "
            "deeply nested optionals can be rejected. Run the schema test before trusting "
            "a Pydantic model here.",
        ),
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_field="groq_api_key",
        fast_model="openai/gpt-oss-20b",
        quality_model="openai/gpt-oss-120b",
        structured_mode="json_schema",
        free_rpm=30,
        quirks=(
            "8K tokens per minute on the free tier: tight for retrieval-heavy prompts. "
            "Use Gemini when the context is large.",
            "gpt-oss models are reasoning models - budget 250-500 completion tokens of "
            "hidden thinking before any visible output, and never set max_tokens low.",
        ),
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_field="openrouter_api_key",
        fast_model="openai/gpt-oss-20b:free",
        quality_model="openai/gpt-oss-120b:free",
        structured_mode="json_object",  # varies per underlying model; assume the weak one
        free_rpm=20,
        quirks=(
            "Free endpoints are low priority and may log or train on prompts. Model zoo "
            "for experiments only - never project traffic.",
        ),
    ),
    "ollama": Provider(
        name="ollama",
        base_url="",  # filled from settings.ollama_base_url at construction
        api_key_field="ollama_api_key",
        fast_model="qwen3:1.7b",
        quality_model="qwen3.5:4b",
        structured_mode="json_schema",
        free_rpm=None,
        quirks=(
            "`tool_choice` is unsupported: you cannot force a tool call, only suggest it.",
            "On this machine (i7-8650U, CPU-only) a 4B model decodes at 4-7 tok/s. Fine "
            "for batch classification, painful for anything interactive.",
        ),
    ),
}

DEFAULT_PROVIDER = "gemini"


def resolve(provider_name: str, settings: Settings | None = None) -> tuple[Provider, str]:
    """Return (provider, api_key), with a readable error when a key is missing.

    The missing-key error is worth its length: the single most common first-run failure in
    this workspace is a key that was never put in .env, and a bare 401 from the vendor
    does not tell a learner which of four keys to go and create.
    """
    settings = settings or Settings()
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"unknown provider {provider_name!r}. Known providers: {known}")

    raw_key = getattr(settings, provider.api_key_field, None)
    key = raw_key.get_secret_value() if isinstance(raw_key, SecretStr) else raw_key
    if not key:
        env_var = provider.api_key_field.upper()
        raise ValueError(
            f"no API key for provider {provider_name!r}. Set {env_var} in {WORKSPACE_ENV} "
            f"(copy .env.example) or in the environment."
        )

    if provider.name == "ollama":
        provider = Provider(**{**provider.__dict__, "base_url": settings.ollama_base_url})

    return provider, key
