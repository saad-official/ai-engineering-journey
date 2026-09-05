"""Lab 01 - hello-llm.

One prompt, several providers, one client. Every provider here speaks the OpenAI
Chat Completions shape, so the only things that change are `base_url`, `api_key`,
and `model`. That is the abstraction `llm-kit` will formalise later.

Run:  uv run main.py            (from labs/01-hello-llm)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

WORKSPACE_ENV = Path(__file__).resolve().parents[2] / ".env"

PROMPT = "In two sentences, explain what a token is in the context of a language model."


class Settings(BaseSettings):
    """Secrets come from the workspace-level .env (gitignored). Never hardcode keys."""

    model_config = SettingsConfigDict(env_file=WORKSPACE_ENV, extra="ignore")

    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: str = "ollama"


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    price_in_per_m: float  # USD per 1M input tokens (0 for free/local)
    price_out_per_m: float


def openrouter_free_models(api_key: str) -> list[str]:
    """The :free list rotates weekly and individual free endpoints get rate-limited upstream,
    so discover candidates at runtime and let the caller fall through them on 429."""
    resp = httpx.get(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
    )
    resp.raise_for_status()
    free = [m for m in resp.json()["data"] if m["id"].endswith(":free")]
    if not free:
        raise RuntimeError("OpenRouter returned no :free models")
    # Prefer models that advertise JSON-schema structured outputs (needed in later labs),
    # and a rough size/quality ordering within those.
    prefs = ("gemma-4-31b", "glm-5.2", "minimax-m2.7", "nemotron-3-super", "gemma-4-26b")
    ordered: list[str] = []
    for pref in prefs:
        ordered += [m["id"] for m in free if pref in m["id"] and m["id"] not in ordered]
    ordered += [m["id"] for m in free if m["id"] not in ordered]
    return ordered


def build_providers(s: Settings) -> list[Provider]:
    providers: list[Provider] = []
    if s.gemini_api_key:
        providers.append(
            Provider(
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
                s.gemini_api_key.get_secret_value(),
                # 2.5-flash-lite is "no longer available to new users" (checked 2026-09-05);
                # 3.5-flash-lite is the cheapest current Flash-Lite with a free tier.
                "gemini-3.5-flash-lite",
                0.30,
                2.50,
            )
        )
    if s.groq_api_key:
        providers.append(
            Provider(
                "groq",
                "https://api.groq.com/openai/v1",
                s.groq_api_key.get_secret_value(),
                "openai/gpt-oss-20b",
                0.075,
                0.30,
            )
        )
    if s.openrouter_api_key:
        key = s.openrouter_api_key.get_secret_value()
        for model in openrouter_free_models(key)[:4]:
            providers.append(
                Provider("openrouter", "https://openrouter.ai/api/v1", key, model, 0, 0)
            )
    providers.append(Provider("ollama", s.ollama_base_url, s.ollama_api_key, "qwen3:1.7b", 0, 0))
    return providers


def run(p: Provider) -> bool:
    """Returns True on success so callers can stop after the first working fallback."""
    client = OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=60, max_retries=0)
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=p.model,
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=200,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001 - lab: show the failure, keep going
        print(f"[{p.name:<10}] {p.model}: FAILED ({type(exc).__name__}): {str(exc)[:140]}\n")
        return False
    dt = time.perf_counter() - t0
    u = resp.usage
    cost = 0.0
    if u:
        cost = (u.prompt_tokens * p.price_in_per_m + u.completion_tokens * p.price_out_per_m) / 1e6
    text = (resp.choices[0].message.content or "").strip().replace("\n", " ")
    print(f"[{p.name:<10}] model={resp.model or p.model}")
    print(
        f"             latency={dt:6.2f}s  tokens in/out={u.prompt_tokens if u else '?'}/"
        f"{u.completion_tokens if u else '?'}  cost=${cost:.6f}"
    )
    print(f"             {text[:220]}\n")
    return True


if __name__ == "__main__":
    settings = Settings()
    print(f"Prompt: {PROMPT}\n")
    succeeded: set[str] = set()
    for provider in build_providers(settings):
        if provider.name in succeeded:
            continue  # a fallback candidate for a provider that already worked
        if run(provider):
            succeeded.add(provider.name)
