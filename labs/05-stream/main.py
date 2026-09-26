"""Lab 05, layer 1 - streaming a completion to the terminal, and measuring what it buys.

Labs 01-04 called the model and waited for the whole answer. With `stream=True` the provider
keeps the HTTP response open and sends the answer as it is decoded, a few characters at a
time, as Server-Sent Events. The SDK hides the wire format (layer 2, server.py, re-emits it
by hand) and hands you an iterator of chunks.

The claim everyone repeats is "streaming makes it faster". This lab measures which "it":

    request sent
      |-- queue + PREFILL (read the prompt, parallel)  ...... time to first chunk
      |-- DECODE hidden reasoning (serial, 1 token/pass) .... still nothing to show a user
      |-- DECODE visible content (serial) ................... time to first VISIBLE token
      '-- last token, finish_reason, usage .................. total time

`notes/concepts/tokens-and-context-windows.md` says prefill drives time-to-first-token and
decode drives total latency. A reasoning model adds a middle band: gpt-oss-20b on Groq streams
its reasoning in a non-standard `delta.reasoning` field BEFORE any `delta.content`. So "the
first byte arrived" and "the user can read something" are different moments, and the gap
between them is the headline number of this lab.

Sections:
  A. live      one streamed call, deltas printed as they arrive, every timestamp reported
  B. usage     the same call WITHOUT stream_options.include_usage: is your cost ledger blind?
  C. compare   N streamed vs N non-streamed calls, interleaved, medians. Does streaming cut
               TOTAL latency, or only PERCEIVED latency?

Run:
    uv run main.py                     # Groq, 2 + 2*3 = 8 calls, ~30-60 s including pacing
    uv run main.py --dry-run           # the plan; calls nothing, MEASURES NOTHING
    uv run main.py --skip-compare      # sections A and B only (2 calls)
    uv run main.py --runs 5            # a less noisy section C
    uv run main.py --provider gemini   # hides its reasoning: watch where the wait moves to

NO CACHE, and here the reason is absolute: timing is the experiment. A cached response has a
time-to-first-token of zero and teaches nothing. What is written to runs/ is provenance only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from common import (
    DEFAULT_PROMPT,
    MAX_TOKENS,
    MIN_SECONDS_BETWEEN_CALLS,
    TEMPERATURE,
    WORKSPACE_ENV,
    Provider,
    Settings,
    build_provider,
    rate_limit,
    read_chunk,
    usage_dict,
)

# Windows console default is cp1252, and model output is not. Lab 04's first run died on
# U+202F inside print() after the API work had already succeeded. Streaming makes this worse,
# not better: print() runs once per chunk, so one bad glyph kills the run mid-answer.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUNS_DIR = Path(__file__).parent / "runs"

# A trap worth knowing: an HTTP "timeout" on a stream is NOT a deadline. httpx's read timeout
# is the maximum silence BETWEEN two bytes. A stream that sends one chunk every 50 s never
# times out, ever. So the per-read timeout guards against a dead connection, and a separate
# wall-clock deadline (checked inside the loop) guards against a slow one.
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
STREAM_DEADLINE_S = 120.0

# Every timestamp here uses time.perf_counter(), NOT time.monotonic(). On Windows with Python
# 3.12, monotonic() is GetTickCount64 and ticks every 15.625 ms - coarser than the gap between
# two stream chunks, so "first chunk" and "first reasoning chunk" would collapse into the same
# number. Check yours: python -c "import time; print(time.get_clock_info('monotonic'))".
# (rate_limit() keeps monotonic: a 2 s pacing sleep does not care about 15 ms.)


@dataclass
class StreamRun:
    """One streamed call. Every t_* is seconds since the request was sent (None = never)."""

    label: str
    include_usage: bool
    t_open: float | None = None  # create() returned: response headers are in, body is not
    t_first_chunk: float | None = None  # first chunk of ANY kind
    t_first_reasoning: float | None = None
    t_first_content: float | None = None  # first VISIBLE token - what a user experiences
    t_total: float | None = None
    chunks: int = 0
    reasoning_chunks: int = 0
    content_chunks: int = 0
    content_chunk_sizes: list[int] = field(default_factory=list)  # visible chars per chunk
    reasoning_chars: int = 0
    finish_reason: str | None = None
    usage: dict[str, int | None] | None = None  # standard chunk.usage
    usage_chunk_index: int | None = None  # which chunk (1-based) carried it
    usage_chunk_had_choices: bool | None = None
    groq_usage: dict[str, int | None] | None = None  # Groq's x_groq.usage extension
    content: str = ""
    error: str | None = None

    @property
    def reasoning_gap(self) -> float | None:
        """First byte -> first readable byte. Hidden reasoning being decoded, live."""
        if self.t_first_chunk is None or self.t_first_content is None:
            return None
        return self.t_first_content - self.t_first_chunk


@dataclass
class CallRun:
    """One non-streamed call. The whole body lands at once, so for the user time-to-first-
    visible-token IS the total time. That equality is the whole comparison in section C."""

    label: str
    t_total: float | None = None
    finish_reason: str | None = None
    usage: dict[str, int | None] | None = None
    content_chars: int = 0
    error: str | None = None


def stream_once(
    client: OpenAI, p: Provider, prompt: str, *, include_usage: bool, echo: bool, label: str
) -> StreamRun:
    run = StreamRun(label=label, include_usage=include_usage)
    kwargs: dict[str, Any] = {}
    if include_usage:
        # Without this, the OpenAI spec sends NO usage on a stream at all. With it, one extra
        # chunk arrives after finish_reason with `choices: []` and the usage block.
        kwargs["stream_options"] = {"include_usage": True}

    rate_limit()
    t0 = time.perf_counter()
    stream = None
    printing: str | None = None  # which kind of text is currently being echoed
    try:
        stream = client.chat.completions.create(
            model=p.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            stream=True,
            **kwargs,
        )
        # create() returns once the status line and headers are in - the body has not
        # started. On a non-streamed call this line would block for the whole generation.
        run.t_open = time.perf_counter() - t0
        for chunk in stream:
            now = time.perf_counter() - t0
            run.chunks += 1
            if run.t_first_chunk is None:
                run.t_first_chunk = now
            d = read_chunk(chunk)
            if d.reasoning:
                run.reasoning_chunks += 1
                run.reasoning_chars += len(d.reasoning)
                if run.t_first_reasoning is None:
                    run.t_first_reasoning = now
                if echo:
                    if printing != "reasoning":
                        print("\n  --- reasoning (a product would hide or collapse this) ---\n")
                        printing = "reasoning"
                    print(d.reasoning, end="", flush=True)
            if d.content:
                run.content_chunks += 1
                run.content_chunk_sizes.append(len(d.content))
                run.content += d.content
                if run.t_first_content is None:
                    run.t_first_content = now
                if echo:
                    if printing != "content":
                        print("\n\n  --- content (what the user reads) ---\n")
                        printing = "content"
                    # flush=True or the terminal buffers it and you are no longer streaming.
                    print(d.content, end="", flush=True)
            if d.finish_reason:
                run.finish_reason = d.finish_reason
            if d.usage:
                run.usage = d.usage
                run.usage_chunk_index = run.chunks
                run.usage_chunk_had_choices = d.has_choices
            if d.groq_usage:
                run.groq_usage = d.groq_usage
            if now > STREAM_DEADLINE_S:
                run.error = f"wall-clock deadline {STREAM_DEADLINE_S:.0f}s exceeded; closed"
                break
    except Exception as e:  # noqa: BLE001 - a lab reports every failure, it does not hide it
        run.error = f"{type(e).__name__}: {e}"
    finally:
        # Closing the stream closes the HTTP connection, which is how you tell the provider
        # to stop generating. Leaving the loop early without this keeps the socket (and,
        # possibly, the billing meter) running until garbage collection gets round to it.
        if stream is not None:
            stream.close()
        run.t_total = time.perf_counter() - t0
    if echo:
        print("\n")
    return run


def call_once(client: OpenAI, p: Provider, prompt: str, label: str) -> CallRun:
    run = CallRun(label=label)
    rate_limit()
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=p.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )
        run.finish_reason = resp.choices[0].finish_reason
        run.content_chars = len(resp.choices[0].message.content or "")
        run.usage = usage_dict(resp.usage)
    except Exception as e:  # noqa: BLE001
        run.error = f"{type(e).__name__}: {e}"
    run.t_total = time.perf_counter() - t0
    return run


# ---------------------------------------------------------------- reporting


def s(v: float | None) -> str:
    return "never" if v is None else f"{v:6.2f} s"


def fmt_usage(u: dict[str, int | None] | None) -> str:
    if u is None:
        return "ABSENT"
    out, think = u["completion_tokens"], u["reasoning_tokens"]
    return f"in {u['prompt_tokens']} / out {out} (reasoning {think})"


def check_finish(fr: str | None, error: str | None) -> None:
    """Same discipline as labs 02-04, with one streaming-only failure added."""
    if error:
        print(f"  !! ERROR: {error}")
    if fr == "length":
        print(
            "  !! finish_reason=length: the budget ran out. On a reasoning model that can mean\n"
            "     the whole stream was reasoning and the visible answer never started. Raise\n"
            "     MAX_TOKENS in common.py before trusting any timing on this run."
        )
    elif fr is None:
        print(
            "  !! no finish_reason: the stream ended without saying why. On a stream that means\n"
            "     the connection dropped mid-answer - and the user already read half of it."
        )


def report_stream(run: StreamRun, p: Provider) -> None:
    sizes = run.content_chunk_sizes
    other = run.chunks - run.reasoning_chunks - run.content_chunks
    print(f"  headers in (create returned)   {s(run.t_open)}")
    print(f"  first chunk, any kind          {s(run.t_first_chunk)}")
    print(f"  first reasoning chunk          {s(run.t_first_reasoning)}")
    print(f"  first VISIBLE content token    {s(run.t_first_content)}   <- the user's wait")
    print(f"  total                          {s(run.t_total)}")
    print(f"  gap: first chunk -> visible    {s(run.reasoning_gap)}   <- hidden reasoning")
    print(
        f"  chunks {run.chunks}  (reasoning {run.reasoning_chunks}, content "
        f"{run.content_chunks}, other {other})   reasoning chars {run.reasoning_chars}"
    )
    if sizes:
        print(
            f"  visible chars per content chunk   mean {statistics.mean(sizes):.1f}, "
            f"median {statistics.median(sizes):.0f}, max {max(sizes)}"
        )
    print(f"  finish_reason                  {run.finish_reason}")
    where = ""
    if run.usage is not None:
        shape = "choices=[]" if not run.usage_chunk_had_choices else "choices present"
        where = f"   on chunk {run.usage_chunk_index}/{run.chunks}, {shape}"
    print(f"  chunk.usage                    {fmt_usage(run.usage)}{where}")
    print(f"  x_groq.usage (Groq extension)  {fmt_usage(run.groq_usage)}")
    u = run.usage or run.groq_usage
    if u and u["completion_tokens"] and run.t_first_chunk is not None and run.t_total:
        rate = u["completion_tokens"] / max(run.t_total - run.t_first_chunk, 1e-6)
        print(f"  decode rate                    ~{rate:.0f} tok/s after the first chunk")
        cost = (u["prompt_tokens"] or 0) * p.price_in_per_m / 1e6
        cost += (u["completion_tokens"] or 0) * p.price_out_per_m / 1e6
        print(f"  cost at paid rates             ${cost:.6f}")
    check_finish(run.finish_reason, run.error)


def section_live(client: OpenAI, p: Provider, prompt: str) -> StreamRun:
    print("\n=== A. live: one streamed call, include_usage=True ===")
    print(f"  prompt: {prompt}")
    run = stream_once(client, p, prompt, include_usage=True, echo=True, label="A-live")
    report_stream(run, p)
    return run


def section_usage(client: OpenAI, p: Provider, prompt: str, with_usage: StreamRun) -> StreamRun:
    print("\n=== B. usage: the same call WITHOUT stream_options.include_usage ===")
    print("  (text not echoed this time - only what arrives at the end matters)")
    run = stream_once(client, p, prompt, include_usage=False, echo=False, label="B-no-usage")
    report_stream(run, p)
    print(f"\n  {'':<24} {'include_usage=True':<22} include_usage=False")
    for name, a, b in (
        ("chunk.usage", with_usage.usage, run.usage),
        ("x_groq.usage", with_usage.groq_usage, run.groq_usage),
    ):
        print(f"  {name:<24} {'present' if a else 'ABSENT':<22} {'present' if b else 'ABSENT'}")
    if run.usage is None and run.groq_usage is None:
        print(
            "\n  Without include_usage this provider told you NOTHING about what the call cost.\n"
            "  A ledger that reads `usage` records $0 for every streamed call - silently."
        )
    elif run.usage is None:
        print(
            "\n  No standard usage, but a provider-specific extension still carried it. Code\n"
            "  that relies on x_groq works on Groq and goes blind on every other provider."
        )
    return run


def section_compare(
    client: OpenAI, p: Provider, prompt: str, n: int
) -> tuple[list[StreamRun], list[CallRun]]:
    print(f"\n=== C. compare: {n} streamed vs {n} non-streamed, interleaved ===")
    # Interleaved S,N,S,N... rather than S,S,S,N,N,N so that a provider getting busier over
    # the minute this takes is spread across both groups instead of landing on one of them.
    streamed: list[StreamRun] = []
    plain: list[CallRun] = []
    for i in range(1, n + 1):
        sr = stream_once(client, p, prompt, include_usage=True, echo=False, label=f"C-stream-{i}")
        streamed.append(sr)
        print(f"  stream {i}: first visible {s(sr.t_first_content)}  total {s(sr.t_total)}")
        check_finish(sr.finish_reason, sr.error)
        cr = call_once(client, p, prompt, label=f"C-plain-{i}")
        plain.append(cr)
        print(f"  plain  {i}: first visible {s(cr.t_total)}  total {s(cr.t_total)}")
        check_finish(cr.finish_reason, cr.error)

    def stats(vals: list[float | None]) -> str:
        v = [x for x in vals if x is not None]
        if not v:
            return "n/a"
        return f"median {statistics.median(v):5.2f} s  (min {min(v):.2f}, max {max(v):.2f})"

    def out_tokens(runs: list[Any]) -> str:
        v = [r.usage["completion_tokens"] for r in runs if r.usage]
        return f"median {statistics.median(v):.0f}" if v else "n/a"

    ok_s = [r for r in streamed if r.error is None]
    ok_p = [r for r in plain if r.error is None]
    print(f"\n  {'':<22} streamed ({len(ok_s)} ok)")
    print(f"  {'first visible token':<22} {stats([r.t_first_content for r in ok_s])}")
    print(f"  {'total':<22} {stats([r.t_total for r in ok_s])}")
    print(f"  {'completion tokens':<22} {out_tokens(ok_s)}")
    print(f"\n  {'':<22} non-streamed ({len(ok_p)} ok)")
    print(f"  {'first visible token':<22} {stats([r.t_total for r in ok_p])}  (= total)")
    print(f"  {'total':<22} {stats([r.t_total for r in ok_p])}")
    print(f"  {'completion tokens':<22} {out_tokens(ok_p)}")
    print(
        "\n  Read it with N in mind. With N=3 a difference smaller than the min-max spread is\n"
        "  noise, not a finding. And check the completion-token medians match: if one group\n"
        "  happened to write longer answers, its total time is longer for that reason alone."
    )
    return streamed, plain


# ---------------------------------------------------------------- transcript + main


def write_transcript(p: Provider, started: str, prompt: str, runs: list[Any], n: int) -> Path:
    """Provenance, not a cache: never read back. Same contract as labs 03/04."""
    RUNS_DIR.mkdir(exist_ok=True)
    payload = {
        "lab": "05-stream",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "provider": p.name,
        "model": p.model,
        "prompt": prompt,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "compare_runs_per_group": n,
        "min_seconds_between_calls": MIN_SECONDS_BETWEEN_CALLS,
        "runs": [{"kind": type(r).__name__, **asdict(r)} for r in runs],
    }
    stamp = started.replace("-", "").replace(":", "").split(".")[0].replace("+0000", "")
    path = RUNS_DIR / f"{stamp}-{p.name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def dry_run(provider_name: str, have_key: bool, n: int, skip_compare: bool) -> None:
    """Print the plan. No network call, so it MEASURES NOTHING - and in a timing lab that
    means the dry run cannot tell you a single number worth writing down."""
    calls = 2 + (0 if skip_compare else 2 * n)
    print("\n=== --dry-run: the plan only. No network calls, no measurements. ===\n")
    print(f"  provider     {provider_name} (key in .env: {'yes' if have_key else 'NO'})")
    print("  A live       1 streamed call, include_usage=True, echoed")
    print("  B usage      1 streamed call, include_usage=False")
    if not skip_compare:
        print(f"  C compare    {n} streamed + {n} non-streamed, interleaved")
    print(f"  total        {calls} calls, max_tokens={MAX_TOKENS}, temperature={TEMPERATURE}")
    print(
        f"  pacing       >= {MIN_SECONDS_BETWEEN_CALLS}s between call starts -> at least "
        f"{max(calls - 1, 0) * MIN_SECONDS_BETWEEN_CALLS:.0f}s, plus the streams themselves"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Lab 05: streaming, measured.")
    ap.add_argument("--provider", choices=("groq", "gemini"), default="groq")
    ap.add_argument("--runs", type=int, default=3, help="per group in section C (default 3)")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--skip-compare", action="store_true", help="sections A and B only")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; measure nothing")
    args = ap.parse_args()
    if args.runs < 1:
        ap.error("--runs must be at least 1")

    provider = build_provider(Settings(), args.provider)
    if args.dry_run:
        dry_run(args.provider, provider is not None, args.runs, args.skip_compare)
        return
    if provider is None:
        print(f"No API key for '{args.provider}' in {WORKSPACE_ENV}. Nothing to run.")
        return

    started = datetime.now(UTC).isoformat()
    print(f"Lab 05 - streaming   provider={provider.name} model={provider.model}")
    print(f"started {started}   max_tokens={MAX_TOKENS}   temperature={TEMPERATURE}")
    print("no cache: every number below is a live call")

    # max_retries=0, same as labs 03/04, and streaming adds a reason: a retry after the
    # stream has STARTED would replay the answer from the top into a terminal (or a UI) that
    # has already shown half of it. Retrying a stream is only safe before the first chunk.
    client = OpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key,
        timeout=HTTP_TIMEOUT,
        max_retries=0,
    )

    live = section_live(client, provider, args.prompt)
    runs: list[Any] = [live, section_usage(client, provider, args.prompt, live)]
    if not args.skip_compare:
        streamed, plain = section_compare(client, provider, args.prompt, args.runs)
        runs += streamed + plain

    path = write_transcript(provider, started, args.prompt, runs, args.runs)
    print(f"\n  transcript -> {path}")
    print(
        "\n  Explain it back (CLAUDE.md rule 2):\n"
        "   1. Section A has a first chunk and a first VISIBLE token. What was the model doing\n"
        "      in between, and which of prefill / decode does each timestamp measure?\n"
        "   2. Section C: did streaming change the total time? Then what did it change?\n"
        "   3. Section B: where would a streamed call's cost come from if include_usage was\n"
        "      off - and what would your cost dashboard have shown?"
    )


if __name__ == "__main__":
    main()
