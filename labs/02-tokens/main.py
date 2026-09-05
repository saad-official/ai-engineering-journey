"""Lab 02 - tokens.

Three questions, all of them left open by lab 01:

1. How many tokens is a piece of text, really? Counted *locally*, before any network
   call, for six deliberately different kinds of text.
2. Why did the same prompt report 18 tokens on Gemini and 88 on Groq? Two suspects:
   different tokenizer vocabularies, and hidden chat-template tokens the provider
   wraps around your message. This lab separates them by measuring three numbers per
   text: a local count, Gemini's own `countTokens` (bare string, no chat wrapper),
   and each provider's `usage.prompt_tokens` (the real billed number, wrapper included).
3. Was Gemini's 32.5 s first call a cold start or the steady state? Ten sequential calls.

Plus a truncation demo, because `finish_reason == "length"` is the failure that looks
like a model-quality problem and is really a budget problem.

Run:
    uv run main.py                  # everything
    uv run main.py --local-only     # no network at all, no quota burned
    uv run main.py --skip-latency   # tables only
    uv run main.py --refresh        # ignore the on-disk cache

Provider responses are cached in .cache/ so re-running to fix a formatting bug does
not burn free-tier quota. Delete the folder or pass --refresh to re-measure.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import tiktoken
from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from samples import SAMPLES

WORKSPACE_ENV = Path(__file__).resolve().parents[2] / ".env"
CACHE_DIR = Path(__file__).parent / ".cache"

# o200k_base is OpenAI's tokenizer. It is NOT Gemini's and NOT gpt-oss's.
# That is deliberate and is half the lesson: there is no public local tokenizer for
# Gemini, so any local estimate is an approximation whose error you have to measure
# rather than assume. See NOTES.md.
LOCAL_ENCODING = "o200k_base"

# Kept short on purpose: the latency study measures the round trip, not generation length.
LATENCY_PROMPT = "Reply with exactly one word: ready"
SLEEP_BETWEEN_CALLS = 2.0  # free-tier RPM is unverified for Gemini; do not hammer it


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


def build_providers(s: Settings) -> list[Provider]:
    providers: list[Provider] = []
    if s.gemini_api_key:
        providers.append(
            Provider(
                "gemini",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
                s.gemini_api_key.get_secret_value(),
                "gemini-3.5-flash-lite",
            )
        )
    if s.groq_api_key:
        providers.append(
            Provider(
                "groq",
                "https://api.groq.com/openai/v1",
                s.groq_api_key.get_secret_value(),
                "openai/gpt-oss-20b",
            )
        )
    return providers


# ---------------------------------------------------------------- cache


def cache_get(key: str, refresh: bool) -> int | None:
    if refresh:
        return None
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return int(json.loads(path.read_text(encoding="utf-8"))["value"])
    return None


def cache_put(key: str, value: int) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(json.dumps({"value": value}), encoding="utf-8")


def cache_key(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------- counting


@functools.lru_cache(maxsize=1)
def encoder() -> tiktoken.Encoding:
    """Built once and reused.

    Note the asterisk on the word "local": tiktoken downloads the BPE vocabulary file
    on first use and caches it on disk. The *counting* is local, free and instant; the
    first call needs the network once. Set TIKTOKEN_CACHE_DIR to control where it lands.
    """
    return tiktoken.get_encoding(LOCAL_ENCODING)


def local_tokens(text: str) -> int:
    """Count with a local tokenizer. No cost, no rate limit, no per-call network."""
    return len(encoder().encode(text))


def gemini_count_tokens(api_key: str, model: str, text: str, refresh: bool) -> int | None:
    """Gemini's native countTokens: the true count for the *bare string*, no chat wrapper.

    This is the number to compare against the local estimate to isolate vocabulary
    differences. Comparing it against usage.prompt_tokens isolates the chat template.
    """
    key = cache_key("gemini-count", model, text)
    if (hit := cache_get(key, refresh)) is not None:
        return hit
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:countTokens"
    try:
        resp = httpx.post(
            url,
            headers={"x-goog-api-key": api_key},
            json={"contents": [{"parts": [{"text": text}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        total = int(resp.json()["totalTokens"])
    except Exception as exc:  # noqa: BLE001 - lab: report and continue
        print(f"  ! gemini countTokens failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None
    cache_put(key, total)
    return total


def prompt_tokens(p: Provider, text: str, refresh: bool) -> int | None:
    """The number you are actually billed for: your text plus the provider's chat template.

    max_tokens=1 keeps the output (the expensive half) to a single token. usage is
    reported regardless of how little is generated.
    """
    key = cache_key("usage", p.name, p.model, text)
    if (hit := cache_get(key, refresh)) is not None:
        return hit
    client = OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=60, max_retries=1)
    try:
        resp = client.chat.completions.create(
            model=p.model,
            messages=[{"role": "user", "content": text}],
            max_tokens=1,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 - lab: report and continue
        print(f"  ! {p.name} usage call failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None
    if resp.usage is None:
        return None
    value = resp.usage.prompt_tokens
    cache_put(key, value)
    time.sleep(SLEEP_BETWEEN_CALLS)
    return value


# ---------------------------------------------------------------- tables


def table_local() -> dict[str, int]:
    """Local counts only. Answers: how many tokens is this, and how dense is it?"""
    print(f"\n=== A. Local counts ({LOCAL_ENCODING}, no network) ===\n")
    header = f"{'text':<12} {'chars':>7} {'words':>7} {'tokens':>7} {'chars/tok':>10}"
    print(header)
    print("-" * len(header))
    counts: dict[str, int] = {}
    for label, text in SAMPLES:
        n = local_tokens(text)
        counts[label] = n
        chars, words = len(text), len(text.split())
        print(f"{label:<12} {chars:>7} {words:>7} {n:>7} {chars / n:>10.2f}")
    return counts


def table_providers(providers: list[Provider], local: dict[str, int], refresh: bool) -> None:
    """The two gaps that matter.

    vocab gap = Gemini countTokens - local count  -> different tokenizer vocabularies
    wrapper   = usage.prompt_tokens - countTokens -> the chat template you never wrote
    """
    gemini = next((p for p in providers if p.name == "gemini"), None)
    groq = next((p for p in providers if p.name == "groq"), None)
    print("\n=== B. Local vs provider-reported ===\n")
    header = (
        f"{'text':<12} {'local':>6} {'gem:count':>10} {'vocab':>7} "
        f"{'gem:usage':>10} {'wrapper':>8} {'groq:usage':>11} {'vs local':>9}"
    )
    print(header)
    print("-" * len(header))
    for label, text in SAMPLES:
        loc = local[label]
        g_count = (
            gemini_count_tokens(gemini.api_key, gemini.model, text, refresh) if gemini else None
        )
        g_usage = prompt_tokens(gemini, text, refresh) if gemini else None
        q_usage = prompt_tokens(groq, text, refresh) if groq else None

        def cell(v: int | None) -> str:
            return "-" if v is None else str(v)

        def delta(a: int | None, b: int | None) -> str:
            return "-" if a is None or b is None else f"{a - b:+d}"

        print(
            f"{label:<12} {loc:>6} {cell(g_count):>10} {delta(g_count, loc):>7} "
            f"{cell(g_usage):>10} {delta(g_usage, g_count):>8} "
            f"{cell(q_usage):>11} {delta(q_usage, loc):>9}"
        )
    print(
        "\n  vocab   = Gemini's own count minus the local o200k estimate (tokenizer difference)\n"
        "  wrapper = billed prompt_tokens minus the bare-string count (chat template overhead)\n"
        "  A near-constant wrapper column means it is fixed scaffolding, not proportional cost."
    )


# ---------------------------------------------------------------- latency


def latency_study(p: Provider, n: int) -> None:
    """Lab 01 saw one 32.5 s Gemini call and one 4.6 s call. One sample is not data."""
    print(f"\n=== C. Latency: {n} sequential calls to {p.name} ({p.model}) ===\n")
    client = OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=60, max_retries=0)
    times: list[float] = []
    for i in range(1, n + 1):
        t0 = time.perf_counter()
        try:
            client.chat.completions.create(
                model=p.model,
                messages=[{"role": "user", "content": LATENCY_PROMPT}],
                max_tokens=8,
                temperature=0,
            )
        except Exception as exc:  # noqa: BLE001 - lab: report and continue
            print(f"  call {i:>2}: FAILED ({type(exc).__name__}) {str(exc)[:90]}")
            time.sleep(SLEEP_BETWEEN_CALLS)
            continue
        dt = time.perf_counter() - t0
        times.append(dt)
        print(f"  call {i:>2}: {dt:6.2f}s{'   <- first call (cold?)' if i == 1 else ''}")
        time.sleep(SLEEP_BETWEEN_CALLS)

    if not times:
        print("  no successful calls")
        return
    ordered = sorted(times)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    print(
        f"\n  n={len(times)}  min={min(times):.2f}s  median={statistics.median(times):.2f}s  "
        f"mean={statistics.fmean(times):.2f}s  p90={p90:.2f}s  max={max(times):.2f}s"
    )
    if len(times) > 1:
        rest = statistics.median(times[1:])
        print(f"  first call {times[0]:.2f}s vs median of the rest {rest:.2f}s")


# ---------------------------------------------------------------- truncation


def truncation_demo(p: Provider) -> None:
    """max_tokens is a hard stop, not a hint. The model does not 'wrap up' when it runs out."""
    print(f"\n=== D. Truncation: finish_reason on {p.name} with max_tokens=16 ===\n")
    client = OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=60, max_retries=1)
    prompt = (
        "Return a JSON object with keys version, status and changes, where changes is an "
        "array of three objects each with id, category and title. JSON only."
    )
    try:
        resp = client.chat.completions.create(
            model=p.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=16,
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 - lab: report and continue
        print(f"  ! failed: {type(exc).__name__}: {str(exc)[:120]}")
        return
    choice = resp.choices[0]
    content = choice.message.content or ""
    print(f"  finish_reason = {choice.finish_reason!r}")
    print(f"  content       = {content!r}")
    if resp.usage:
        u = resp.usage
        print(f"  usage         = {u.prompt_tokens} in / {u.completion_tokens} out")
    try:
        json.loads(content)
        print("  json.loads    = parsed (unexpectedly complete)")
    except json.JSONDecodeError as exc:
        print(f"  json.loads    = JSONDecodeError: {exc.msg}")
        print("\n  The bug that looks like a model-quality problem and is really a budget one.")


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description="Lab 02: what a token actually costs.")
    ap.add_argument("--local-only", action="store_true", help="no network calls at all")
    ap.add_argument("--skip-latency", action="store_true", help="skip the 10-call latency study")
    ap.add_argument("--refresh", action="store_true", help="ignore the on-disk cache")
    ap.add_argument("--latency-n", type=int, default=10, help="how many latency calls (default 10)")
    args = ap.parse_args()

    local = table_local()
    if args.local_only:
        print("\n(--local-only: stopping before any network call)")
        return

    providers = build_providers(Settings())
    if not providers:
        print("\nNo API keys found in the workspace .env - local table only.")
        return

    table_providers(providers, local, args.refresh)

    gemini = next((p for p in providers if p.name == "gemini"), None)
    if gemini and not args.skip_latency:
        latency_study(gemini, args.latency_n)
    if gemini:
        truncation_demo(gemini)


if __name__ == "__main__":
    main()
