"""Lab 03 - generation parameters.

Lab 02 asked what a prompt *costs*. This lab asks what the sampling settings do to the
answer that comes back: the parameters every LLM API exposes and that most tutorials set
to a magic number without ever measuring the effect.

Mental model. A model does not emit text. Once per token it emits a score (a logit) for
every token in its vocabulary, and something downstream turns those scores into a choice:

    logits --> [ divide by temperature ] --> softmax --> [ top_p nucleus cut ] --> sample

  temperature  divides the logits before the softmax. t < 1 sharpens the distribution
               (the already-likely token becomes even likelier); t > 1 flattens it
               (unlikely tokens get a real chance). t = 0 is a special case: dividing by
               zero is undefined, so APIs map it to "skip sampling, take the argmax".
  top_p        does not reshape anything. It sorts tokens by probability, keeps adding
               them until the cumulative probability reaches p, discards the rest, and
               renormalises what is left. p = 1.0 discards nothing.

They are two knobs on the same step, which is why turning both at once makes results hard
to attribute - and why the frontend habit of "set temperature to 0.7 and top_p to 0.9
because the docs example did" is a guess, not a decision.

Sections:
  A. Variance      each prompt x each temperature x N runs; distinct count + similarity
  B. Determinism   is temperature 0 actually deterministic? (it is not guaranteed to be)
  C. Seed          does pinning the seed reproduce a *sampled* output?
  D. top_p         same temperature, two nucleus sizes
  E. Summary       one table, plus what the whole run cost

Run:
    uv run main.py                          # everything, on Groq (~40 calls, ~2 min)
    uv run main.py --dry-run                # print the call plan and estimate; call nothing
    uv run main.py --runs 3 --skip-topp     # cheaper
    uv run main.py --temps 0,0.5,1.0,1.5
    uv run main.py --skip-factual
    uv run main.py --provider gemini        # slower; see NOTES.md

Why Groq and not the workspace's primary provider: this is 40 sequential calls and Groq
answers in ~1 s (lab 02, section C). Gemini is available behind --provider for a
cross-provider spot check, not as the default.

WHY THERE IS NO CACHE HERE. Lab 02 cached provider responses under .cache/ so that
re-running to fix a formatting bug did not burn free-tier quota. That was right there and
would be wrong here: a cache keyed on (prompt, temperature) hands back the same stored
completion on every run and would *manufacture* the exact determinism this lab exists to
measure. Re-sampling is the experiment. What does get written to disk is a transcript
under runs/ carrying an ISO-8601 UTC timestamp, the provider and the resolved model id,
so any number quoted in NOTES.md can be traced back to the run that produced it. Every
value printed below is live; nothing here is ever replayed.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from prompts import CREATIVE, PROMPTS

WORKSPACE_ENV = Path(__file__).resolve().parents[2] / ".env"
RUNS_DIR = Path(__file__).parent / "runs"

DEFAULT_TEMPS: list[float] = [0.0, 0.7, 1.2]

# Groq free tier is 30 RPM on gpt-oss-20b (TECHNOLOGY_STACK.md section 1), i.e. one call
# every 2 s. Gemini's free RPM is still UNVERIFIED, so the same pace is used for both.
MIN_SECONDS_BETWEEN_CALLS = 2.0

# Generous on purpose. gpt-oss-20b is a reasoning model: it spends completion tokens on a
# hidden chain of thought *before* the visible answer, and those tokens are billed and
# counted. Set this too low and finish_reason comes back "length" with empty content -
# lab 02 section D, except harder to spot because the failure looks like a bad model.
# Measured 2026-09-17: at 256 this lab produced finish_reason="length" on 22 of 45 calls,
# because gpt-oss-20b spent 250-254 tokens on hidden reasoning for a one-line answer,
# leaving nothing for the visible text. The creative prompt was unmeasurable as a result.
# 1024 gives the chain of thought ~4x the room it actually used. If "length" shows up
# again, raise this before trusting any row - a truncated run is not a sample.
MAX_TOKENS = 1024

# Lab 02 measured Groq's chat-template overhead at a constant +71 tokens per request.
# Used only by --dry-run to estimate cost without making a call.
GROQ_WRAPPER_TOKENS = 71


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
    supports_seed: bool


def build_provider(s: Settings, name: str) -> Provider | None:
    """One client shape, only base_url / model / price change. Same as labs 01 and 02."""
    if name == "groq" and s.groq_api_key:
        return Provider(
            "groq",
            "https://api.groq.com/openai/v1",
            s.groq_api_key.get_secret_value(),
            "openai/gpt-oss-20b",
            0.075,
            0.30,
            # Groq accepts `seed` on the OpenAI-compatible endpoint and documents it as
            # best-effort, not a guarantee. Section C is what "best-effort" means in numbers.
            supports_seed=True,
        )
    if name == "gemini" and s.gemini_api_key:
        return Provider(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            s.gemini_api_key.get_secret_value(),
            "gemini-3.5-flash-lite",
            0.30,
            2.50,
            # The Gemini compatibility layer has no seed parameter. Sending one is at best
            # ignored and at worst a 400, so section C is skipped for Gemini.
            supports_seed=False,
        )
    return None


# ---------------------------------------------------------------- pacing


_last_call_started: float | None = None


def rate_limit() -> None:
    """Pace the *next* call. Call this immediately before every network request.

    Lab 02 slept *after* each call, which has three bugs this version fixes:
      1. the sleep was skipped on the error path, so a 429 storm - the one moment pacing
         actually matters - hammered the API as fast as it could refuse;
      2. it slept after the final call, paying 2 s for nothing;
      3. it slept a fixed 2 s on top of the call's own latency, so the real spacing was
         2 s + latency rather than the 2 s the rate limit needs.

    Sleeping *before* the call, for only the time still owed since the previous call
    started, fixes all three. The timestamp is taken before the attempt, so a call that
    raises still counts as a call and still paces the one after it.
    """
    global _last_call_started
    if _last_call_started is not None:
        owed = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_started)
        if owed > 0:
            time.sleep(owed)
    _last_call_started = time.monotonic()


# ---------------------------------------------------------------- one completion


@dataclass(frozen=True)
class Run:
    """One sampled completion, plus everything needed to decide whether to trust it."""

    index: int
    text: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None
    latency_s: float
    error: str | None = None

    @property
    def usable(self) -> bool:
        """Only a complete answer may be compared against another complete answer.

        A run that stopped on "length" was cut off by the token budget, not by the model
        deciding it was done. Counting it as "a different output" would measure
        MAX_TOKENS, not temperature. This is why finish_reason is checked before every
        single comparison in this file.
        """
        return self.error is None and self.finish_reason == "stop"

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "text": self.text,
            "finish_reason": self.finish_reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "latency_s": round(self.latency_s, 3),
            "error": self.error,
        }


def complete(
    client: OpenAI,
    p: Provider,
    prompt: str,
    *,
    index: int,
    temperature: float,
    top_p: float | None = None,
    seed: int | None = None,
) -> Run:
    """A single fresh sample. Never cached, never retried (a retry is another sample)."""
    kwargs: dict[str, object] = {
        "model": p.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS,
        "temperature": temperature,
    }
    # Only send a parameter that is actually being varied. Sending top_p=1.0 alongside a
    # temperature sweep is harmless but muddies "which knob produced this", and sending
    # seed to a provider that does not implement it is a silent no-op at best.
    if top_p is not None:
        kwargs["top_p"] = top_p
    if seed is not None and p.supports_seed:
        kwargs["seed"] = seed

    rate_limit()  # before the request, so it applies to the failure path too
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 - lab: report and keep going
        return Run(
            index=index,
            text="",
            finish_reason=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=None,
            latency_s=time.perf_counter() - t0,
            error=f"{type(exc).__name__}: {str(exc)[:110]}",
        )
    dt = time.perf_counter() - t0

    if not resp.choices:
        # Rare, but a 200 with no choices is not a sample. Say so instead of IndexError-ing.
        return Run(
            index=index,
            text="",
            finish_reason=None,
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            reasoning_tokens=None,
            latency_s=dt,
            error="empty choices in a 200 response",
        )
    choice = resp.choices[0]
    usage = resp.usage
    # Reasoning models report their hidden thinking under completion_tokens_details. It is
    # not in every provider's response, so read it defensively rather than assume it.
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    reasoning = getattr(details, "reasoning_tokens", None) if details is not None else None

    return Run(
        index=index,
        text=choice.message.content or "",
        finish_reason=choice.finish_reason,
        prompt_tokens=usage.prompt_tokens if usage else 0,
        completion_tokens=usage.completion_tokens if usage else 0,
        reasoning_tokens=reasoning,
        latency_s=dt,
    )


# ---------------------------------------------------------------- measuring variance


_WORD = re.compile(r"\w+", re.UNICODE)


def word_tokens(text: str) -> list[str]:
    """Lowercased words, punctuation and whitespace dropped.

    NOT the model's tokens - a deliberately different unit. The question here is "did the
    model make different word choices", and word-level comparison answers exactly that.
    """
    return _WORD.findall(text.lower())


def mean_pairwise_similarity(texts: list[str]) -> float | None:
    """Mean difflib ratio over all C(n,2) pairs. 1.0 = every pair identical.

    Why this metric:
      - Pairwise, not "compare everything to run 1". With an arbitrary reference, one
        outlier drags the whole score down and looks like uniform drift. All C(5,2) = 10
        pairs weight every output equally.
      - On words, not characters. Character-level ratios are inflated by shared spaces and
        incidental letter overlap: two completely different sentences in English still
        score around 0.5, which compresses the interesting range into the top half of the
        scale. Word-level answers the question that was actually asked.
      - difflib.SequenceMatcher, not a set overlap (Jaccard) and not an embedding cosine.
        SequenceMatcher respects order, so a reordered sentence scores below an identical
        one - and it is in the standard library, so the lab adds no dependency. An
        embedding model would measure *meaning*, which is a better question and a much
        more expensive one; that belongs in the eval lab, not here.
      - autojunk is off: difflib's default heuristic starts ignoring elements that appear
        in more than 1% of a sequence once it is 200+ items long, which would silently
        change the metric for longer outputs.

    The honest limit: this measures surface form. Two outputs that say the same thing in
    different words score low. Read it next to the distinct count and the raw text.
    """
    if len(texts) < 2:
        return None
    seqs = [word_tokens(t) for t in texts]
    ratios = [SequenceMatcher(None, a, b, autojunk=False).ratio() for a, b in combinations(seqs, 2)]
    return statistics.fmean(ratios)


@dataclass(frozen=True)
class Block:
    """One (prompt, temperature, top_p, seed) cell and every run inside it."""

    prompt_label: str
    prompt: str
    temperature: float
    top_p: float | None
    seed: int | None
    runs: list[Run]

    @property
    def usable_runs(self) -> list[Run]:
        return [r for r in self.runs if r.usable]

    @property
    def texts(self) -> list[str]:
        return [r.text for r in self.usable_runs]

    @property
    def distinct(self) -> int:
        """Byte-identical count, on the raw string exactly as returned. No stripping."""
        return len(set(self.texts))

    @property
    def similarity(self) -> float | None:
        return mean_pairwise_similarity(self.texts)

    @property
    def mean_out_tokens(self) -> float | None:
        usable = self.usable_runs
        return statistics.fmean(r.completion_tokens for r in usable) if usable else None

    @property
    def mean_reasoning_tokens(self) -> float | None:
        vals = [r.reasoning_tokens for r in self.usable_runs if r.reasoning_tokens is not None]
        return statistics.fmean(vals) if vals else None

    def cost(self, p: Provider) -> float:
        # Failed and truncated runs are excluded from the *comparison* but included here:
        # a truncated call is billed exactly like a complete one.
        tin = sum(r.prompt_tokens for r in self.runs)
        tout = sum(r.completion_tokens for r in self.runs)
        return (tin * p.price_in_per_m + tout * p.price_out_per_m) / 1e6

    def as_dict(self) -> dict[str, object]:
        return {
            "prompt_label": self.prompt_label,
            "prompt": self.prompt,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
            "runs": [r.as_dict() for r in self.runs],
        }


def run_block(
    client: OpenAI,
    p: Provider,
    prompt_label: str,
    prompt: str,
    *,
    n: int,
    temperature: float,
    top_p: float | None = None,
    seed: int | None = None,
) -> Block:
    runs = [
        complete(client, p, prompt, index=i, temperature=temperature, top_p=top_p, seed=seed)
        for i in range(1, n + 1)
    ]
    return Block(prompt_label, prompt, temperature, top_p, seed, runs)


# ---------------------------------------------------------------- printing


def show(text: str, width: int = 74) -> str:
    """One line, ASCII-safe for a Windows console. Full text lives in the transcript."""
    flat = text.replace("\r", "").replace("\n", " | ").strip()
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def print_block(b: Block) -> None:
    knobs = f"temp={b.temperature}"
    if b.top_p is not None:
        knobs += f" top_p={b.top_p}"
    if b.seed is not None:
        knobs += f" seed={b.seed}"
    print(f"\n  --- {b.prompt_label} @ {knobs} ---")
    for r in b.runs:
        if r.error is not None:
            print(f"  run {r.index:>2}  FAILED  {r.error}")
            continue
        extra = "" if r.reasoning_tokens is None else f" ({r.reasoning_tokens} reasoning)"
        marker = "" if r.usable else "   <- NOT comparable"
        print(
            f"  run {r.index:>2}  fr={str(r.finish_reason):<7} "
            f"{r.completion_tokens:>4} out{extra:<17} {r.latency_s:5.2f}s{marker}"
        )
        print(f"          {show(r.text)}")

    dropped = len(b.runs) - len(b.usable_runs)
    if dropped:
        print(
            f"  !! {dropped}/{len(b.runs)} run(s) dropped from the comparison "
            "(failed, or finish_reason != 'stop'). Fix that before trusting the row below."
        )
    sim = b.similarity
    sim_s = "n/a" if sim is None else f"{sim:.3f}"
    out_s = "n/a" if b.mean_out_tokens is None else f"{b.mean_out_tokens:.1f}"
    print(
        f"  => distinct {b.distinct}/{len(b.usable_runs)}   "
        f"mean pairwise similarity {sim_s}   mean out tokens {out_s}"
    )


SUMMARY_HEADER = (
    f"{'prompt':<10} {'temp':>5} {'top_p':>6} {'seed':>6} {'n':>3} "
    f"{'distinct':>8} {'mean sim':>9} {'out tok':>8} {'think':>6} {'dropped':>8} {'cost $':>9}"
)


def print_summary(blocks: list[Block], p: Provider) -> None:
    print("\n=== E. Summary (all values live; this lab has no cache) ===\n")
    print(SUMMARY_HEADER)
    print("-" * len(SUMMARY_HEADER))
    total = 0.0
    for b in blocks:
        total += b.cost(p)
        sim = b.similarity
        print(
            f"{b.prompt_label:<10} {b.temperature:>5} "
            f"{'-' if b.top_p is None else b.top_p:>6} "
            f"{'-' if b.seed is None else b.seed:>6} "
            f"{len(b.usable_runs):>3} "
            f"{b.distinct:>8} "
            f"{'n/a' if sim is None else f'{sim:.3f}':>9} "
            f"{'n/a' if b.mean_out_tokens is None else f'{b.mean_out_tokens:.1f}':>8} "
            f"{'-' if b.mean_reasoning_tokens is None else f'{b.mean_reasoning_tokens:.0f}':>6} "
            f"{len(b.runs) - len(b.usable_runs):>8} "
            f"{b.cost(p):>9.6f}"
        )
    print("-" * len(SUMMARY_HEADER))
    calls = sum(len(b.runs) for b in blocks)
    print(f"{'TOTAL':<10} {calls} calls, ${total:.6f} (free tier: $0 - this is the paid-rate cost)")
    print(
        "\n  distinct = byte-identical groups among the comparable runs (1 = all the same)\n"
        "  mean sim = mean difflib word-level similarity over every pair (1.000 = identical)\n"
        "  out tok  = mean completion tokens, hidden reasoning included; 'think' is that\n"
        "             reasoning share, which is billed at the output rate and is invisible\n"
        "             in the text you printed\n"
        f"  cost     = {p.model} at ${p.price_in_per_m}/1M in, ${p.price_out_per_m}/1M out"
    )


# ---------------------------------------------------------------- sections


def section_variance(
    client: OpenAI, p: Provider, temps: list[float], n: int, prompts: list[tuple[str, str]]
) -> list[Block]:
    print(f"\n=== A. Variance: {len(prompts)} prompt(s) x {len(temps)} temps x {n} runs ===")
    blocks: list[Block] = []
    for label, prompt in prompts:
        print(f"\n  prompt [{label}]: {prompt}")
        for t in temps:
            b = run_block(client, p, label, prompt, n=n, temperature=t)
            print_block(b)
            blocks.append(b)
    return blocks


def section_determinism(blocks: list[Block], n: int) -> None:
    """The claim to kill: "temperature 0 is deterministic"."""
    print("\n=== B. The determinism check ===\n")
    zero = [b for b in blocks if b.temperature == 0.0]
    if not zero:
        print("  (no temperature-0 block in this run; add 0 to --temps)")
        return
    for b in zero:
        comparable = len(b.usable_runs)
        if comparable < 2:
            print(f"  [{b.prompt_label}] not enough comparable runs to say anything.")
            continue
        if b.distinct == 1:
            print(
                f"  [{b.prompt_label}] temp 0: all {comparable} outputs were byte-identical.\n"
                f"      Read that as: NOT OBSERVED TO DIFFER IN {comparable} RUNS.\n"
                "      It is not proof of determinism, and it is not a guarantee you can build\n"
                "      on. Temperature 0 means greedy decoding - always take the argmax token -\n"
                "      and that is deterministic only if the logits are bit-for-bit identical\n"
                "      every time. On shared inference infrastructure they are not, because:\n"
                "        - floating-point addition is not associative, and GPU kernels sum in\n"
                "          whatever order the scheduler picks;\n"
                "        - batching is dynamic, so your request is computed alongside different\n"
                "          neighbours each time, which changes those reduction orders;\n"
                "        - mixture-of-experts routing (gpt-oss is an MoE) can send a token to a\n"
                "          different expert when the batch composition shifts;\n"
                "        - the provider can swap the serving stack, quantisation or the model\n"
                "          behind a stable name without telling you.\n"
                "      When two tokens are nearly tied, a 1e-7 wobble flips the argmax and the\n"
                "      completion diverges from there. Five identical runs at 14:00 is evidence,\n"
                "      not a contract. Anything that must be reproducible - a cached answer, a\n"
                "      regression test, an idempotent pipeline step - has to store the output,\n"
                "      not re-derive it from temperature=0."
            )
        else:
            print(
                f"  [{b.prompt_label}] temp 0 produced {b.distinct} DISTINCT outputs in "
                f"{comparable} runs.\n"
                "      There it is, first try: temperature 0 is greedy decoding, not a\n"
                "      determinism guarantee. Same prompt, same model name, same parameters,\n"
                "      different answer - because the logits themselves are not reproducible on\n"
                "      shared, dynamically batched inference hardware.\n"
                "      Never build a cache key, a test assertion, or an idempotency check on\n"
                "      the assumption that temperature 0 will repeat."
            )
        print()
    print(
        f"  Scope of this claim: one provider, one model, {n} runs, one afternoon.\n"
        "  It does not generalise across providers or across model versions, in either\n"
        "  direction. Re-measure when any of those change."
    )


def section_seed(client: OpenAI, p: Provider, temps: list[float], n: int, seed: int) -> list[Block]:
    """Does a fixed seed reproduce a sampled output?

    Deliberately run at the HIGHEST temperature, not at 0. A seed pins the pseudo-random
    draw, so at temperature 0 - where there is no draw to pin, only an argmax - it proves
    nothing. The seed only has something to do when sampling is genuinely random.
    """
    hot = max(temps)
    print(f"\n=== C. Seed at the highest temperature ({hot}) ===\n")
    if not p.supports_seed:
        print(f"  {p.name} does not expose `seed` on its OpenAI-compatible endpoint; skipping.")
        return []
    print(
        f"  A seed at temp 0 would prove nothing - there is no random draw to pin. Run it\n"
        f"  where sampling is at its loosest instead, and compare against the unseeded\n"
        f"  temp-{hot} block in section A."
    )
    b = run_block(client, p, "creative", CREATIVE, n=n, temperature=hot, seed=seed)
    print_block(b)
    if b.distinct == 1 and len(b.usable_runs) > 1:
        print(f"\n  seed={seed} repeated exactly across {len(b.usable_runs)} runs at temp {hot}.")
    else:
        print(
            f"\n  seed={seed} did NOT pin the output: {b.distinct} distinct results at temp "
            f"{hot}.\n"
            "  Which is the documented behaviour - every provider that offers `seed` calls it\n"
            "  best-effort. It fixes the sampler's RNG, and the sampler is only the last step;\n"
            "  it cannot fix the non-determinism upstream in the logits themselves."
        )
    return [b]


def section_topp(client: OpenAI, p: Provider, n: int) -> list[Block]:
    """Two knobs, same sampling step, opposite mechanisms."""
    print(f"\n=== D. top_p vs temperature (temp fixed at 1.0, {n} runs each) ===\n")
    print(
        "  temperature 1.0 means 'do not reshape the distribution at all' - the model's own\n"
        "  probabilities, untouched. So everything that changes between these two blocks is\n"
        "  top_p and only top_p.\n"
        "    top_p=1.0  keep the whole vocabulary; any token with non-zero probability can win\n"
        "    top_p=0.1  keep only the smallest set of tokens whose probabilities sum to 0.10,\n"
        "               then renormalise. On an open-ended prompt that is often a couple of\n"
        "               tokens, so it behaves like a low temperature - by a different mechanism.\n"
        "  Low temperature makes the tail unlikely. Low top_p makes the tail impossible.\n"
        "  That difference matters when the right answer is in the tail."
    )
    blocks: list[Block] = []
    for value in (1.0, 0.1):
        b = run_block(client, p, "creative", CREATIVE, n=n, temperature=1.0, top_p=value)
        print_block(b)
        blocks.append(b)
    return blocks


# ---------------------------------------------------------------- transcript


def write_transcript(p: Provider, blocks: list[Block], started: str, n: int) -> Path:
    """Provenance, not a cache: it is never read back to skip a call.

    Every entry carries the UTC timestamp and the exact model id, because "gpt-oss-20b on
    Groq" is not a fixed artefact - a provider can change the serving stack under a stable
    model name, and a result without a date and a model id cannot be compared to a later one.
    """
    RUNS_DIR.mkdir(exist_ok=True)
    payload = {
        "lab": "03-params",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "provider": p.name,
        "model": p.model,
        "runs_per_block": n,
        "max_tokens": MAX_TOKENS,
        "min_seconds_between_calls": MIN_SECONDS_BETWEEN_CALLS,
        "blocks": [b.as_dict() for b in blocks],
    }
    stamp = started.replace("-", "").replace(":", "").split(".")[0].replace("+0000", "")
    path = RUNS_DIR / f"{stamp}-{p.name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- dry run


def dry_run(
    p: Provider,
    temps: list[float],
    n: int,
    prompts: list[tuple[str, str]],
    topp: bool,
    seed: bool,
) -> None:
    """Print the plan. Makes no network call and therefore measures nothing.

    This is not `--local-only` from lab 02: there is no offline half of this lab. Every
    section needs fresh samples. All this does is show what a real run would cost first.
    """
    variance = len(prompts) * len(temps) * n
    seed_calls = n if seed else 0
    topp_calls = 2 * n if topp else 0
    calls = variance + seed_calls + topp_calls
    print("\n=== --dry-run: the plan only. No network calls, no measurements. ===\n")
    waiting = max(calls - 1, 0) * MIN_SECONDS_BETWEEN_CALLS
    print(f"  provider            {p.name} / {p.model}")
    print(
        f"  A. variance         {len(prompts)} prompt(s) x {len(temps)} temps x {n} runs"
        f" = {variance} calls"
    )
    print(f"  C. seed             {seed_calls} calls")
    print(f"  D. top_p            {topp_calls} calls")
    print(f"  total               {calls} calls")
    print(
        f"  pacing              >= {MIN_SECONDS_BETWEEN_CALLS}s apart -> "
        f">= {waiting:.0f}s of deliberate waiting"
    )
    est_in = sum(len(pr) // 4 + GROQ_WRAPPER_TOKENS for _, pr in prompts) / max(len(prompts), 1)
    worst = (est_in * calls * p.price_in_per_m + MAX_TOKENS * calls * p.price_out_per_m) / 1e6
    print(
        f"  cost (upper bound)  ${worst:.4f} - assumes every call generates the full "
        f"{MAX_TOKENS}\n"
        "                      output tokens, which none of them will. Input is estimated at\n"
        f"                      ~4 chars/token plus lab 02's measured +{GROQ_WRAPPER_TOKENS}"
        " chat-template constant.\n"
        "  On the Groq free tier the real cost is $0; the number is what it would cost if\n"
        "  this exact run were on the paid tier."
    )


# ---------------------------------------------------------------- main


def parse_temps(raw: str) -> list[float]:
    values = [float(part) for part in raw.split(",") if part.strip()]
    if not values:
        raise argparse.ArgumentTypeError("--temps needs at least one number, e.g. 0,0.7,1.2")
    return values


def main() -> None:
    ap = argparse.ArgumentParser(description="Lab 03: what temperature and top_p actually do.")
    ap.add_argument("--runs", type=int, default=5, help="samples per block (default 5)")
    ap.add_argument("--provider", choices=("groq", "gemini"), default="groq")
    ap.add_argument(
        "--temps", type=parse_temps, default=DEFAULT_TEMPS, help="comma-separated, e.g. 0,0.7,1.2"
    )
    ap.add_argument("--skip-topp", action="store_true", help="skip section D")
    ap.add_argument("--skip-seed", action="store_true", help="skip section C")
    ap.add_argument(
        "--skip-factual", action="store_true", help="creative prompt only (halves section A)"
    )
    ap.add_argument("--seed", type=int, default=42, help="seed used in section C (default 42)")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the call plan and a cost ceiling; make no calls, measure nothing",
    )
    args = ap.parse_args()

    if args.runs < 1:
        ap.error("--runs must be at least 1")

    provider = build_provider(Settings(), args.provider)
    if provider is None:
        print(f"No API key for '{args.provider}' in {WORKSPACE_ENV}. Nothing to run.")
        return

    prompts = [pr for pr in PROMPTS if not (args.skip_factual and pr[0] == "factual")]
    do_seed = not args.skip_seed and provider.supports_seed

    if args.dry_run:
        dry_run(provider, args.temps, args.runs, prompts, not args.skip_topp, do_seed)
        return

    started = datetime.now(UTC).isoformat()
    print(f"Lab 03 - generation parameters   provider={provider.name} model={provider.model}")
    print(f"started {started}   runs/block={args.runs}   temps={args.temps}")
    print("no cache: every number below is a fresh sample")

    client = OpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key,
        timeout=60,
        # 0 retries on purpose. The SDK's automatic retry would silently replace a failed
        # sample with a *different* sample and quietly break the pacing budget too.
        max_retries=0,
    )

    blocks = section_variance(client, provider, args.temps, args.runs, prompts)
    section_determinism(blocks, args.runs)
    if do_seed:
        blocks += section_seed(client, provider, args.temps, args.runs, args.seed)
    elif not args.skip_seed:
        print(f"\n=== C. Seed ===\n\n  {provider.name} has no `seed` parameter; skipped.")
    if not args.skip_topp:
        blocks += section_topp(client, provider, args.runs)

    print_summary(blocks, provider)
    path = write_transcript(provider, blocks, started, args.runs)
    print(f"\n  transcript -> {path}")


if __name__ == "__main__":
    main()
