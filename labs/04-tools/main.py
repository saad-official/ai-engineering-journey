"""Lab 04 - tool calling, written by hand.

Labs 02 and 03 sent one message and read one answer. This lab is the first one with a
*loop*, and the loop is the entire thing an "AI agent" is. There is no other secret:

    messages = [system, user]
    while True:
        reply = model(messages, tools=schemas)
        if reply has no tool_calls:      -> done, that is the answer
        for each tool_call:              -> run it yourself, in your own process
            messages.append(the result)
        messages.append(reply) first     -> the order matters; see run_loop()

Everything a framework adds (LangChain's AgentExecutor, Pydantic AI, the OpenAI SDK's own
tool runner) is that while-loop plus retries, tracing and typing. CLAUDE.md rule 6 says
build the concept by hand once before adopting the framework, so this file has no
framework in it at all - just `openai`, `json`, and a `while`.

The three things a frontend engineer usually gets wrong on first contact:

  1. THE MODEL DOES NOT CALL ANYTHING. It emits a string naming a function and a string
     of JSON. Nothing executes until you decide to execute it. "Tool calling" is a
     structured-output feature with a convention bolted on.
  2. THE CONVERSATION IS THE STATE. There is no session on the provider's side. Every
     step re-sends the whole array - system prompt, tool schemas, every previous tool
     result - so the input bill grows on every turn. Section G puts numbers on that.
  3. THE LOOP MUST BE ABLE TO STOP. A model that keeps asking for a tool that keeps
     failing will keep asking forever. MAX_ITERATIONS is the circuit breaker, and it is
     the difference between a bug and a bill.

Sections:
  A. happy     one prompt, one tool, the full message array printed at every step
  B. both      one prompt needing get_weather AND calculate (often in one assistant turn)
  C. raises    a tool that fails; the error goes back to the model, which recovers
  D. unknown   the model asks for a tool that does not exist
  E. badjson   the model's `arguments` string is not valid JSON
  F. guard     the max-iteration circuit breaker actually tripping
  G. schemas   what a system message and each tool schema cost in prompt_tokens

Run:
    uv run main.py                      # everything on Groq: ~16 calls in practice,
                                        # 35 upper bound, ~2 min including pacing
    uv run main.py --dry-run            # print the plan; call nothing, measure nothing
    uv run main.py --only happy,both
    uv run main.py --only schemas       # just the token measurement (5 calls)
    uv run main.py --provider gemini    # slower; a cross-provider spot check

Why Groq: gpt-oss-20b answers in ~1 s (lab 02 section C) and supports tools. A loop makes
several sequential calls per prompt, so latency compounds in a way it did not in lab 02.

NO CACHE, same reason as lab 03. The loop *is* the experiment: a cached step hands back a
stored tool call and measures nothing about how the model behaves when it reads a real
error message. What is written to disk is a transcript under runs/ - full message arrays
and per-step usage, carrying the UTC timestamp and the resolved model id, so any number
quoted in NOTES.md can be traced to the run that produced it. Provenance, never replayed.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from tools import ALL_SCHEMAS, CALCULATE_SCHEMA, UNKNOWN_CITY, WEATHER_SCHEMA, dispatch

# Windows console default is cp1252, and model output is not. The first real run of this
# lab died on U+202F (narrow no-break space) inside a weather sentence: a UnicodeEncodeError
# from print(), after the tool loop had already completed successfully. Worth remembering -
# the model emits whatever Unicode it likes, and your terminal is a boundary like any other.
# errors="replace" keeps a stray glyph from killing a run that cost real API calls.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORKSPACE_ENV = Path(__file__).resolve().parents[2] / ".env"
RUNS_DIR = Path(__file__).parent / "runs"

# Groq free tier is 30 RPM on gpt-oss-20b (TECHNOLOGY_STACK.md section 1), i.e. one call
# every 2 s. Gemini's free RPM is still UNVERIFIED, so the same pace is used for both.
MIN_SECONDS_BETWEEN_CALLS = 2.0

# Generous, and lab 03 paid for this lesson in a whole voided run. gpt-oss-20b is a
# reasoning model: it spends completion tokens on a hidden chain of thought before it
# emits anything visible. Lab 03 measured 250-520 reasoning tokens for a ONE-LINE answer
# and its first run at max_tokens=256 produced finish_reason="length" on 22 of 45 calls,
# making every number in it void. Tool calling gives the model strictly more to think
# about (which tool, what arguments, is the result enough), so 2048 here rather than
# lab 03's 1024. If "length" shows up in the step table below, raise this before trusting
# a single row - and read the finish_reason discussion in run_loop(), because "length"
# during a tool call is worse than "length" in prose.
MAX_TOKENS = 2048

# Section G only reads usage.prompt_tokens, so the output is capped at one token: the
# input side is fully billed and reported regardless of how little is generated (lab 02
# used the same trick). finish_reason="length" there is expected and harmless precisely
# because nothing parses that output. That is the exception that proves the rule.
PROBE_MAX_TOKENS = 1

# Temperature 0 for tool selection, and this is a decision, not a default.
# exp-003's finding was: pick temperature by whether the output is PARSED or READ. Prose
# is read by a human who tolerates - and often prefers - variation. A tool call is parsed:
# `json.loads` on `arguments`, then a keyword bind onto a Python function, then the
# function's own validation. Every one of those is a hard edge where "a slightly different
# but equally good phrasing" is a crash, a wrong city, or a silently wrong number. There
# is no upside to sampling here; the greedy token is the one that matches the schema.
# It is still NOT determinism - lab 03 section B - so this reduces variance, and anything
# that must actually reproduce has to store the result rather than re-derive it.
TEMPERATURE = 0.0

# The circuit breaker. 6 model calls per prompt.
# Why 6 and not 3 or 30: the deepest LEGITIMATE path in this lab is section B - call the
# model, get two tool calls, return both, call again, possibly one follow-up call for the
# arithmetic, return it, call again for the final answer. That is 3 model calls, 4 if the
# model splits its tool calls across turns. 6 is double the deepest real path, which
# leaves room for one recovery from a failed tool (sections C-E each spend one extra turn
# reading an error) without leaving room for an infinite argue-with-the-tool loop.
# The number itself matters far less than the fact that it exists and that tripping it is
# reported loudly as a FAILURE rather than silently returning whatever the model last
# said. Section F sets it to 2 on purpose to watch it fire.
MAX_ITERATIONS = 6
GUARD_ITERATIONS = 2

SYSTEM_PROMPT = (
    "You are a precise assistant with access to tools. Use a tool whenever it can give "
    "you a fact or a calculation rather than guessing. Never invent a weather reading. "
    "When a tool returns an error, read it and adapt: either call the tool differently "
    "or tell the user plainly what could not be done. Keep the final answer to two "
    "sentences."
)

SECTIONS: tuple[str, ...] = ("happy", "both", "raises", "unknown", "badjson", "guard", "schemas")


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
    """One client shape, only base_url / model / price change. Same as labs 01-03."""
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


# ---------------------------------------------------------------- pacing


_last_call_started: float | None = None


def rate_limit() -> None:
    """Pace the *next* call. Call this immediately before every network request.

    Carried over unchanged from lab 03, where it replaced lab 02's sleep-after-the-call:
      1. the sleep was skipped on the error path, so a 429 storm - the one moment pacing
         actually matters - hammered the API as fast as it could refuse;
      2. it slept after the final call, paying 2 s for nothing;
      3. it slept a fixed 2 s on top of the call's own latency, so the real spacing was
         2 s + latency rather than the 2 s the rate limit needs.

    Sleeping *before* the call, for only the time still owed since the previous call
    started, fixes all three. The timestamp is taken before the attempt, so a call that
    raises still counts as a call and still paces the one after it.

    It matters more here than in lab 03. There the call count was knowable up front; a
    loop's is not - it depends on what the model decides to do - so the pacing has to be
    a property of the call site, not of a plan written in advance.
    """
    global _last_call_started
    if _last_call_started is not None:
        owed = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_started)
        if owed > 0:
            time.sleep(owed)
    _last_call_started = time.monotonic()


# ---------------------------------------------------------------- message plumbing


def assistant_message(msg: Any) -> dict[str, Any]:
    """Turn the SDK's response object back into a plain wire-format dict.

    Written out by hand rather than `msg.model_dump()` for two reasons: it is exactly
    what the next request will carry, so seeing the shape is the point; and model_dump()
    drags along provider extras (Groq returns a `reasoning` field) that some providers
    reject when you send them back.

    `content` is usually None on a tool-call turn. That is legal and it must be kept -
    dropping the assistant message and appending only the tool results produces a
    conversation where results answer nothing, and the API rejects it.
    """
    out: dict[str, Any] = {"role": "assistant", "content": msg.content}
    if getattr(msg, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return out


def tool_message(call_id: str, content: str) -> dict[str, Any]:
    """The result message.

    `tool_call_id` is the whole protocol: it is how the model knows which of several
    parallel calls this answers. There must be exactly one of these per id in the
    assistant turn's tool_calls, or the next request is a 400.

    No `name` field. Some providers accept it, it is deprecated in the OpenAI spec, and a
    field that is optional on one provider and rejected on another is not worth the
    readability. The id is the join key.
    """
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def synthetic_assistant(calls: list[tuple[str, str, str]]) -> dict[str, Any]:
    """Hand-build an assistant turn: [(call_id, tool_name, arguments_json_string)].

    Sections D and E need the model to do something it does correctly ~always: request a
    tool that does not exist, or emit malformed JSON. You cannot order a model to be
    unreliable on demand, and burning calls hoping for a rare failure is not an
    experiment. So those two turns are written by hand, injected into the array, and
    clearly marked SYNTHETIC in the output - and then the loop continues for real, so the
    *recovery* (the part that matters) is genuinely measured. The failure is staged; the
    model's reaction to it is not.

    This is honest rather than a shortcut: at scale these cases happen, they are rare
    enough that you will not see them in testing, and code that has never executed its
    error path does not have one.
    """
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}
            for cid, name, args in calls
        ],
    }


# ---------------------------------------------------------------- one step


@dataclass
class Step:
    """One iteration of the loop: either a model call or an injected synthetic turn."""

    index: int
    kind: str  # "model" | "synthetic"
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int | None
    latency_s: float
    tool_calls: int
    error: str | None = None
    outcomes: list[dict[str, object]] = field(default_factory=list)
    messages_after: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "kind": self.kind,
            "finish_reason": self.finish_reason,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "latency_s": round(self.latency_s, 3),
            "tool_calls": self.tool_calls,
            "error": self.error,
            "outcomes": self.outcomes,
            "messages_after": self.messages_after,
        }


@dataclass
class Loop:
    """One complete prompt-to-answer run of the while-loop."""

    label: str
    user_prompt: str
    max_iterations: int
    steps: list[Step]
    final_text: str | None
    stopped_because: str

    @property
    def billed_in(self) -> int:
        return sum(s.prompt_tokens for s in self.steps)

    @property
    def billed_out(self) -> int:
        return sum(s.completion_tokens for s in self.steps)

    def cost(self, p: Provider) -> float:
        return (self.billed_in * p.price_in_per_m + self.billed_out * p.price_out_per_m) / 1e6

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "user_prompt": self.user_prompt,
            "max_iterations": self.max_iterations,
            "stopped_because": self.stopped_because,
            "final_text": self.final_text,
            "billed_prompt_tokens": self.billed_in,
            "billed_completion_tokens": self.billed_out,
            "steps": [s.as_dict() for s in self.steps],
        }


# ---------------------------------------------------------------- printing


def flat(text: str, width: int = 68) -> str:
    """One line, truncated. The full text lives in the transcript under runs/."""
    s = (text or "").replace("\r", "").replace("\n", " | ").strip()
    return s if len(s) <= width else s[: width - 3] + "..."


def print_messages(messages: list[dict[str, Any]], caption: str) -> None:
    """Print the ENTIRE message array. This is the point of the lab.

    Watch it grow. Every line printed here is re-sent, and re-billed as input, on every
    remaining step - which is why the prompt_tokens column in the step table only ever
    goes up, and why "just add another tool" is a recurring cost rather than a one-off.
    """
    print(f"\n    messages[{len(messages)}]  {caption}")
    for i, m in enumerate(messages):
        role = str(m.get("role"))
        if role == "assistant" and m.get("tool_calls"):
            n = len(m["tool_calls"])
            content = m.get("content")
            shown = "content=None" if not content else f'content="{flat(content, 44)}"'
            print(f"      [{i}] assistant  {shown}  tool_calls={n}")
            for tc in m["tool_calls"]:
                fn = tc["function"]
                # The arguments are printed RAW, exactly as the model emitted them:
                # a JSON *string*, not a parsed object. Pretty-printing it here would
                # hide the one failure mode section E exists to show.
                print(f"            -> {fn['name']}  id={tc['id']}")
                print(f"               arguments={fn['arguments']!r}")
        elif role == "tool":
            print(f"      [{i}] tool       id={m.get('tool_call_id')}")
            print(f"               content={flat(str(m.get('content')), 62)}")
        else:
            print(f'      [{i}] {role:<9}  "{flat(str(m.get("content") or ""))}"')


def print_step_header(step: Step, previous_prompt_tokens: int | None, cumulative: int) -> None:
    """Per-step usage, with the delta that answers lab 02's open question."""
    if previous_prompt_tokens is None:
        delta = "  (first)"
    else:
        delta = f"{step.prompt_tokens - previous_prompt_tokens:+d} vs prev"
    think = "" if step.reasoning_tokens is None else f" ({step.reasoning_tokens} reasoning)"
    print(
        f"\n  -- step {step.index} [{step.kind}]  fr={str(step.finish_reason):<11} "
        f"in={step.prompt_tokens:<6} {delta:<14} out={step.completion_tokens}{think}  "
        f"{step.latency_s:.2f}s   cumulative billed in={cumulative}"
    )


# ---------------------------------------------------------------- the loop


def run_loop(
    client: OpenAI,
    p: Provider,
    label: str,
    user_prompt: str,
    *,
    schemas: list[dict[str, Any]],
    max_iterations: int = MAX_ITERATIONS,
    queued: list[dict[str, Any]] | None = None,
) -> Loop:
    """The hand-written agent loop. Read this function top to bottom; it is the lab.

    `queued` holds pre-built assistant turns (see synthetic_assistant) that are consumed
    instead of a model call, one per iteration, before any real calls happen.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    pending = list(queued or [])
    steps: list[Step] = []
    final_text: str | None = None
    stopped = "max iterations"
    previous_in: int | None = None

    print(f"\n{'=' * 78}\n  [{label}]  max_iterations={max_iterations}")
    print(f"  user: {user_prompt}")
    print_messages(messages, "before the loop starts")

    iteration = 0
    while iteration < max_iterations:
        iteration += 1

        # ---- 1. get an assistant turn, either injected or from the model -------------
        if pending:
            msg_dict = pending.pop(0)
            step = Step(
                index=iteration,
                kind="synthetic",
                finish_reason="tool_calls",
                prompt_tokens=0,
                completion_tokens=0,
                reasoning_tokens=None,
                latency_s=0.0,
                tool_calls=len(msg_dict.get("tool_calls") or []),
            )
            print(
                f"\n  -- step {iteration} [synthetic]  no API call: this assistant turn is "
                "hand-written, see synthetic_assistant()"
            )
        else:
            rate_limit()  # before the request, so it applies to the failure path too
            t0 = time.perf_counter()
            try:
                resp = client.chat.completions.create(
                    model=p.model,
                    messages=messages,  # type: ignore[arg-type]
                    tools=schemas,  # type: ignore[arg-type]
                    # "auto" = the model decides. The alternatives are worth knowing:
                    # "none" forbids tools, "required" forces at least one call, and
                    # {"type":"function",...} pins one specific tool. "required" is a
                    # common fix for a model that will not call a tool - and a common way
                    # to create an infinite loop, because the model cannot ever finish.
                    tool_choice="auto",
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                )
            except Exception as exc:  # noqa: BLE001 - lab: report and stop this loop
                steps.append(
                    Step(
                        index=iteration,
                        kind="model",
                        finish_reason=None,
                        prompt_tokens=0,
                        completion_tokens=0,
                        reasoning_tokens=None,
                        latency_s=time.perf_counter() - t0,
                        tool_calls=0,
                        error=f"{type(exc).__name__}: {str(exc)[:140]}",
                        messages_after=copy.deepcopy(messages),
                    )
                )
                print(
                    f"\n  -- step {iteration} [model]  FAILED  {type(exc).__name__}: "
                    f"{str(exc)[:110]}"
                )
                stopped = "api error"
                break
            dt = time.perf_counter() - t0

            if not resp.choices:
                steps.append(
                    Step(
                        index=iteration,
                        kind="model",
                        finish_reason=None,
                        prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
                        completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
                        reasoning_tokens=None,
                        latency_s=dt,
                        tool_calls=0,
                        error="empty choices in a 200 response",
                        messages_after=copy.deepcopy(messages),
                    )
                )
                print(f"\n  -- step {iteration} [model]  200 with no choices; stopping")
                stopped = "empty choices"
                break

            choice = resp.choices[0]
            usage = resp.usage
            details = getattr(usage, "completion_tokens_details", None) if usage else None
            reasoning = getattr(details, "reasoning_tokens", None) if details is not None else None
            msg_dict = assistant_message(choice.message)
            step = Step(
                index=iteration,
                kind="model",
                finish_reason=choice.finish_reason,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                reasoning_tokens=reasoning,
                latency_s=dt,
                tool_calls=len(msg_dict.get("tool_calls") or []),
            )
            cumulative = sum(s.prompt_tokens for s in steps) + step.prompt_tokens
            print_step_header(step, previous_in, cumulative)
            previous_in = step.prompt_tokens

            # ---- 2. finish_reason discipline, the tool-loop version ------------------
            # Labs 02 and 03 checked finish_reason before comparing text. Here it is not a
            # measurement-quality question, it is a SAFETY question.
            #
            # "length" means the output hit max_tokens mid-stream. In prose that gives a
            # sentence that stops h. In a tool call it gives a truncated `arguments`
            # string - '{"city": "Kara' or '{"expression": "(1280 * 3) /' - and there are
            # two ways that ends:
            #   - json.loads raises, which is the lucky case; or
            #   - it happens to still parse, e.g. '{"city":"Kara"}' after a cut that
            #     landed on a quote, and you cheerfully execute a call the model never
            #     finished writing. With a real tool - a payment, a DELETE, an email -
            #     that is a truncated string turning into a wrong, irreversible action.
            # So a "length" finish with tool calls attached is NEVER executed. It is a
            # corrupt message, not a slightly short one. Raise max_tokens and re-run.
            if choice.finish_reason == "length" and msg_dict.get("tool_calls"):
                messages.append(msg_dict)
                step.error = "finish_reason='length' with pending tool_calls - NOT executed"
                step.messages_after = copy.deepcopy(messages)
                steps.append(step)
                print(
                    "     !! finish_reason='length' AND tool_calls present. The arguments\n"
                    "        JSON is truncated, so this tool call is discarded unexecuted.\n"
                    "        Raise MAX_TOKENS and re-run; do not 'fix up' the JSON."
                )
                stopped = "length with pending tool calls"
                break

        # ---- 3. append the assistant turn BEFORE the results ------------------------
        # Order is load-bearing. The protocol is assistant(tool_calls) then one tool
        # message per id, contiguously. Append the results first, or drop the assistant
        # turn because content was None, and the next request 400s.
        messages.append(msg_dict)

        calls = msg_dict.get("tool_calls") or []
        if not calls:
            # No tool calls -> this is the answer. The only exit that is not a failure.
            final_text = msg_dict.get("content") or ""
            step.messages_after = copy.deepcopy(messages)
            steps.append(step)
            print_messages(messages, f"after step {iteration} (final answer)")
            if step.finish_reason == "length":
                # Truncated prose. Not dangerous the way a truncated tool call is, but it
                # is not a complete answer either, so it is reported rather than returned
                # as if it were one.
                print("     !! the final answer itself was truncated (finish_reason='length')")
                stopped = "truncated final answer"
            else:
                stopped = "final answer"
            break

        # ---- 4. execute every requested call ----------------------------------------
        # A LIST, not a single call. Models batch independent calls into one turn - which
        # is exactly what section B is for - and code written around `tool_calls[0]`
        # silently drops the rest, leaving ids unanswered and the next request a 400.
        print(f"     executing {len(calls)} tool call(s):")
        for tc in calls:
            fn = tc["function"]
            outcome = dispatch(tc["id"], fn["name"], fn["arguments"])
            flag = "ok " if outcome.ok else "ERR"
            print(f"       [{flag}] {fn['name']}({flat(fn['arguments'], 46)})")
            print(f"             {outcome.detail}")
            messages.append(tool_message(outcome.call_id, outcome.content))
            step.outcomes.append(outcome.as_dict())

        step.messages_after = copy.deepcopy(messages)
        steps.append(step)
        print_messages(messages, f"after step {iteration} (tool results appended)")

    else:
        # The while loop ran out of iterations without ever hitting `break`. Python's
        # for/while-else is the tidy place for this: it only runs when the condition went
        # false, never after a break.
        print(
            f"\n  !! MAX ITERATIONS ({max_iterations}) REACHED with no final answer.\n"
            "     The circuit breaker fired. This is a FAILURE, reported as one - the\n"
            "     alternative is a loop that keeps paying for calls until the quota or\n"
            "     the credit card runs out. Whatever the model last said is not an\n"
            "     answer, so it is not returned as one."
        )

    total_in = sum(s.prompt_tokens for s in steps)
    total_out = sum(s.completion_tokens for s in steps)
    print(
        f"\n  => stopped: {stopped}   steps: {len(steps)}   billed {total_in} in / {total_out} out"
    )
    if final_text:
        print(f"  => answer: {final_text.strip()[:400]}")
    return Loop(label, user_prompt, max_iterations, steps, final_text, stopped)


# ---------------------------------------------------------------- sections


def section_happy(client: OpenAI, p: Provider, cap: int) -> Loop:
    print("\n\n### A. The loop, fully visible: one prompt, one tool ###")
    print(
        "  The smallest complete cycle. Expect: model -> tool_calls -> execute ->\n"
        "  result appended -> model again -> plain answer. Watch messages[] grow from 2\n"
        "  to 5 and watch prompt_tokens grow with it."
    )
    return run_loop(
        client,
        p,
        "A-happy",
        "What is the weather in Karachi right now?",
        schemas=ALL_SCHEMAS,
        max_iterations=cap,
    )


def section_both(client: OpenAI, p: Provider, cap: int) -> Loop:
    print("\n\n### B. Both tools, possibly in one assistant turn ###")
    print(
        "  This prompt cannot be answered without get_weather AND calculate. Two things\n"
        "  to watch: whether the model batches both weather lookups into ONE turn with\n"
        "  two tool_calls (parallel calling) or takes a turn each, and whether it uses\n"
        "  calculate for the arithmetic or quietly does it itself - a model doing mental\n"
        "  arithmetic while a calculator sits in its schema list is a tool-description\n"
        "  problem, which is exp-012 on the backlog."
    )
    return run_loop(
        client,
        p,
        "B-both",
        "Compare the temperature in Lahore and London, and tell me the exact difference "
        "in degrees Celsius. Use the calculator for the subtraction.",
        schemas=ALL_SCHEMAS,
        max_iterations=cap,
    )


def section_raises(client: OpenAI, p: Provider, cap: int) -> Loop:
    print("\n\n### C. A tool raises: the error goes back to the model ###")
    print(
        f"  {UNKNOWN_CITY} is not in the fixture, so get_weather raises ToolError. The\n"
        "  loop does NOT crash and does NOT swallow it: the error text becomes the tool\n"
        "  result, the model reads it, and its next move is the measurement. A tool error\n"
        "  is a prompt - tools.py lists the known cities inside the message for exactly\n"
        "  this reason, so a recovery is available rather than just an apology."
    )
    return run_loop(
        client,
        p,
        "C-raises",
        f"What is the weather in {UNKNOWN_CITY}? If you cannot get it, tell me which "
        "cities you can check instead.",
        schemas=ALL_SCHEMAS,
        max_iterations=cap,
    )


def section_unknown(client: OpenAI, p: Provider, cap: int) -> Loop:
    print("\n\n### D. A tool that does not exist ###")
    print(
        "  The first assistant turn is SYNTHETIC - hand-written, no API call - because a\n"
        "  model asks for a non-existent tool rarely enough that waiting for it is not an\n"
        "  experiment. It happens for real when a schema is removed in a deploy while a\n"
        "  conversation is in flight, when a name is misspelled under truncation, or when\n"
        "  a prompt describes a capability the schema list does not have. The dispatcher\n"
        "  refuses on the name alone, before any argument parsing: TOOL_FUNCTIONS is an\n"
        "  authorisation list, not a lookup convenience. Then the loop runs for real and\n"
        "  the recovery is genuine."
    )
    injected = synthetic_assistant(
        [("call_lab04_unknown_1", "get_stock_price", '{"ticker": "NVDA"}')]
    )
    return run_loop(
        client,
        p,
        "D-unknown-tool",
        "What is the NVDA share price, and what is 12 * 37?",
        schemas=ALL_SCHEMAS,
        max_iterations=cap,
        queued=[injected],
    )


def section_badjson(client: OpenAI, p: Provider, cap: int) -> Loop:
    print("\n\n### E. Malformed JSON in `arguments` ###")
    print(
        "  Also SYNTHETIC, same reason. The arguments string below is cut off mid-value,\n"
        "  which is precisely the shape a max_tokens truncation produces - the case the\n"
        "  finish_reason guard in run_loop() is designed to stop BEFORE it reaches the\n"
        "  dispatcher. This section is what happens when it slips past anyway: a\n"
        "  different provider that reports 'stop', a streamed response reassembled\n"
        "  wrongly, or simply a model that emitted bad JSON. json.loads raises, the\n"
        "  JSONDecodeError message (with its position) is handed back as the tool result,\n"
        "  and the model gets to reissue the call."
    )
    truncated = '{"expression": "(1280 * 3) / '
    injected = synthetic_assistant([("call_lab04_badjson_1", "calculate", truncated)])
    return run_loop(
        client,
        p,
        "E-malformed-json",
        "What is (1280 * 3) / 4?",
        schemas=ALL_SCHEMAS,
        max_iterations=cap,
        queued=[injected],
    )


def section_guard(client: OpenAI, p: Provider) -> Loop:
    print("\n\n### F. The max-iteration guard tripping ###")
    print(
        f"  Same loop, max_iterations lowered to {GUARD_ITERATIONS}, and a prompt that\n"
        "  needs six sequential weather lookups plus an average. It cannot finish in two\n"
        "  turns, so the guard fires - which is the point. In production the trip is not\n"
        "  a curiosity: it is the alarm. Log it, return a real failure to the caller, and\n"
        "  never return the model's last utterance as though it were an answer, because\n"
        "  mid-loop text ('let me check Tokyo next') reads like a response and is not one."
    )
    return run_loop(
        client,
        p,
        "F-max-iterations",
        "Get the weather for Karachi, Lahore, Islamabad, Tokyo, London and San Francisco, "
        "then give me the average temperature. Call get_weather for exactly one city per "
        "turn, never more than one tool call in a single turn, and use the calculator for "
        "the average.",
        schemas=ALL_SCHEMAS,
        max_iterations=GUARD_ITERATIONS,
    )


# ---------------------------------------------------------------- section G


PROBE_PROMPT = "What is the weather in Karachi right now?"


@dataclass(frozen=True)
class Probe:
    label: str
    explains: str
    prompt_tokens: int | None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "explains": self.explains,
            "prompt_tokens": self.prompt_tokens,
            "error": self.error,
        }


def probe(
    client: OpenAI,
    p: Provider,
    label: str,
    explains: str,
    *,
    system: bool,
    schemas: list[dict[str, Any]] | None,
) -> Probe:
    """One call, one number: usage.prompt_tokens. Everything else is held constant."""
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
    messages.append({"role": "user", "content": PROBE_PROMPT})

    kwargs: dict[str, Any] = {
        "model": p.model,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": PROBE_MAX_TOKENS,
    }
    if schemas is not None:
        kwargs["tools"] = schemas

    rate_limit()
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:  # noqa: BLE001 - lab: report and continue
        return Probe(label, explains, None, f"{type(exc).__name__}: {str(exc)[:110]}")
    return Probe(label, explains, resp.usage.prompt_tokens if resp.usage else None)


def section_schemas(client: OpenAI, p: Provider) -> list[Probe]:
    """Answers lab 02's open question: does the wrapper grow with a system message and
    with tool schemas?

    Lab 02 measured Groq's chat-template overhead at a constant +71 tokens with a single
    user message and no tools, on all six test texts. "Constant" was true within that
    experiment's scope - it varied nothing except the text. This varies the *envelope*
    instead, holding the user message byte-identical across all five calls, so every
    difference in prompt_tokens is the envelope and nothing else.
    """
    print("\n\n### G. What the envelope costs: system message and tool schemas ###")
    print(
        "  Same user message, five times, changing only what is wrapped around it.\n"
        "  max_tokens=1, because only usage.prompt_tokens is being read - finish_reason\n"
        "  will be 'length' on every one of these and that is fine here precisely because\n"
        "  nothing parses the output. Lab 02's +71 was measured with no system message\n"
        "  and no tools; this is the rest of that answer."
    )
    # One axis varies per row, and every row sends the byte-identical PROBE_PROMPT.
    # (label, explains, system, schemas)
    plan: list[tuple[str, str, bool, list[dict[str, Any]] | None]] = [
        ("bare", "user message only - lab 02's baseline shape", False, None),
        ("+system", "system message added, still no tools", True, None),
        ("+weather", "no system, one tool schema (get_weather)", False, [WEATHER_SCHEMA]),
        ("+calculate", "no system, one tool schema (calculate)", False, [CALCULATE_SCHEMA]),
        ("+both", "no system, both schemas - what every loop step above paid", False, ALL_SCHEMAS),
    ]
    probes = [
        probe(client, p, label, explains, system=system, schemas=schemas)
        for label, explains, system, schemas in plan
    ]

    base = probes[0].prompt_tokens
    header = f"{'variant':<12} {'prompt_tokens':>14} {'vs bare':>9}  what it isolates"
    print(f"\n{header}\n{'-' * len(header)}")
    for pr in probes:
        if pr.prompt_tokens is None:
            print(f"{pr.label:<12} {'FAILED':>14} {'-':>9}  {pr.error}")
            continue
        delta = "-" if base is None else f"{pr.prompt_tokens - base:+d}"
        print(f"{pr.label:<12} {pr.prompt_tokens:>14} {delta:>9}  {pr.explains}")

    weather = probes[2].prompt_tokens
    calc = probes[3].prompt_tokens
    both = probes[4].prompt_tokens
    if None not in (base, weather, calc, both):
        assert base is not None and weather is not None and calc is not None and both is not None
        print(
            f"\n  per-schema cost, measured rather than guessed:\n"
            f"    get_weather schema      {weather - base:+d} tokens\n"
            f"    calculate schema        {calc - base:+d} tokens\n"
            f"    both together           {both - base:+d} tokens\n"
            f"    sum of the two alone    {(weather - base) + (calc - base):+d} tokens\n"
            "  If 'both' is less than the sum, part of the cost is a one-off framing block\n"
            "  the provider emits once when ANY tool is present, and the rest is per-tool.\n"
            "  That split is the number you need to answer 'what does one more tool cost',\n"
            "  and it is paid on EVERY step of the loop, not once per conversation."
        )
    return probes


# ---------------------------------------------------------------- transcript


def write_transcript(
    p: Provider, loops: list[Loop], probes: list[Probe], started: str, sections: list[str]
) -> Path:
    """Provenance, not a cache: never read back to skip a call. Same contract as lab 03.

    It stores the full message array after every step, which is the artefact NOTES.md
    quotes from - a tool loop is not reconstructable from a summary.
    """
    RUNS_DIR.mkdir(exist_ok=True)
    payload = {
        "lab": "04-tools",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "provider": p.name,
        "model": p.model,
        "sections": sections,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "max_iterations": MAX_ITERATIONS,
        "guard_iterations": GUARD_ITERATIONS,
        "min_seconds_between_calls": MIN_SECONDS_BETWEEN_CALLS,
        "system_prompt": SYSTEM_PROMPT,
        "tool_schemas": ALL_SCHEMAS,
        "loops": [loop.as_dict() for loop in loops],
        "schema_probes": [pr.as_dict() for pr in probes],
    }
    stamp = started.replace("-", "").replace(":", "").split(".")[0].replace("+0000", "")
    path = RUNS_DIR / f"{stamp}-{p.name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------------------------------------------------------------- summary


def print_summary(loops: list[Loop], p: Provider) -> None:
    print("\n\n=== Summary (all values live; this lab has no cache) ===\n")
    header = (
        f"{'section':<17} {'steps':>5} {'in tok':>7} {'out tok':>8} {'cost $':>9}  stopped because"
    )
    print(header)
    print("-" * len(header))
    total = 0.0
    for loop in loops:
        total += loop.cost(p)
        print(
            f"{loop.label:<17} {len(loop.steps):>5} {loop.billed_in:>7} "
            f"{loop.billed_out:>8} {loop.cost(p):>9.6f}  {loop.stopped_because}"
        )
    print("-" * len(header))
    calls = sum(1 for loop in loops for s in loop.steps if s.kind == "model")
    print(f"{'TOTAL':<17} {calls} model calls, ${total:.6f} (free tier: $0 - paid-rate cost)")
    print(
        "\n  in tok = the SAME conversation billed again on every step. A 4-step loop pays\n"
        "           for its system prompt and its tool schemas four times. That is the\n"
        "           cost model of an agent, and it is why step count is a budget line.\n"
        f"  cost   = {p.model} at ${p.price_in_per_m}/1M in, ${p.price_out_per_m}/1M out"
    )


# ---------------------------------------------------------------- dry run


def dry_run(p: Provider, sections: list[str], cap: int) -> None:
    """Print the plan. Makes no network call and therefore MEASURES NOTHING.

    Said plainly because a dry run of a *loop* is weaker than lab 03's was. There the call
    count was fixed by the plan; here it is decided by the model at runtime, so the only
    honest figure is an upper bound. The real count is whatever the model does, and it is
    printed live as the loop runs.
    """
    print("\n=== --dry-run: the plan only. No network calls, no measurements. ===\n")
    print(f"  provider            {p.name} / {p.model}")
    print(f"  sections            {', '.join(sections)}")
    loop_sections = [s for s in sections if s != "schemas"]
    worst = 0
    for name in loop_sections:
        limit = GUARD_ITERATIONS if name == "guard" else cap
        # A queued synthetic turn consumes an iteration without making a call.
        synthetic = 1 if name in ("unknown", "badjson") else 0
        worst += max(limit - synthetic, 0)
        print(f"    {name:<16} <= {max(limit - synthetic, 0)} model calls (max_iterations {limit})")
    if "schemas" in sections:
        worst += 5
        print(f"    {'schemas':<16} == 5 model calls (fixed)")
    print(f"  upper bound         {worst} calls")
    print(
        f"  pacing              >= {MIN_SECONDS_BETWEEN_CALLS}s apart -> "
        f">= {max(worst - 1, 0) * MIN_SECONDS_BETWEEN_CALLS:.0f}s of deliberate waiting"
    )
    print(
        "\n  This is an UPPER bound and probably a loose one: a loop stops as soon as the\n"
        "  model answers, which is usually in 2-3 steps, not at the guard. There is no\n"
        "  cost estimate here - unlike lab 03, the input size is not knowable in advance\n"
        "  because it depends on how many tool results end up in the array. Run section G\n"
        "  (5 calls) if you want the input-side numbers before committing to a full run."
    )


# ---------------------------------------------------------------- main


def parse_sections(raw: str) -> list[str]:
    wanted = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [w for w in wanted if w not in SECTIONS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown section(s) {', '.join(unknown)}; choose from {', '.join(SECTIONS)}"
        )
    if not wanted:
        raise argparse.ArgumentTypeError(f"--only needs at least one of {', '.join(SECTIONS)}")
    # Keep the canonical order regardless of what order they were typed in.
    return [s for s in SECTIONS if s in wanted]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Lab 04: a two-tool agent loop written by hand, with the message "
        "array printed at every step."
    )
    ap.add_argument("--provider", choices=("groq", "gemini"), default="groq")
    ap.add_argument(
        "--only",
        type=parse_sections,
        default=list(SECTIONS),
        help=f"comma-separated subset of: {', '.join(SECTIONS)}",
    )
    ap.add_argument(
        "--max-iterations",
        type=int,
        default=MAX_ITERATIONS,
        help=f"circuit breaker for every section except 'guard' (default {MAX_ITERATIONS})",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the call plan; make no calls and measure nothing",
    )
    args = ap.parse_args()

    if args.max_iterations < 1:
        ap.error("--max-iterations must be at least 1")

    provider = build_provider(Settings(), args.provider)
    if provider is None:
        print(f"No API key for '{args.provider}' in {WORKSPACE_ENV}. Nothing to run.")
        return

    if args.dry_run:
        dry_run(provider, args.only, args.max_iterations)
        return

    started = datetime.now(UTC).isoformat()
    print(f"Lab 04 - tool calling   provider={provider.name} model={provider.model}")
    print(f"started {started}   sections={','.join(args.only)}   temperature={TEMPERATURE}")
    print(f"max_tokens={MAX_TOKENS}   max_iterations={args.max_iterations}")
    print("no cache: every step below is a fresh call")

    client = OpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key,
        timeout=90,
        # 0 retries on purpose, same as lab 03. In a loop it matters more: the SDK's
        # automatic retry would re-send an identical message array and could produce a
        # SECOND set of tool calls for work that already ran - a duplicate side effect,
        # which for a real tool means a double charge or a double email. Retries in an
        # agent belong at the loop level, where idempotency can be reasoned about.
        max_retries=0,
    )

    runners = {
        "happy": section_happy,
        "both": section_both,
        "raises": section_raises,
        "unknown": section_unknown,
        "badjson": section_badjson,
    }

    loops: list[Loop] = []
    probes: list[Probe] = []
    for name in args.only:
        if name in runners:
            # Every loop section takes the cap explicitly rather than reading a global,
            # so --max-iterations is honoured and section F keeps its own low value.
            loops.append(runners[name](client, provider, args.max_iterations))
        elif name == "guard":
            loops.append(section_guard(client, provider))
        elif name == "schemas":
            probes = section_schemas(client, provider)

    if loops:
        print_summary(loops, provider)
    path = write_transcript(provider, loops, probes, started, args.only)
    print(f"\n  transcript -> {path}")
    print(
        "\n  Explain it back (CLAUDE.md rule 2):\n"
        "   1. The provider stores nothing between steps. So what is 'the agent's memory',\n"
        "      literally, and what happens to the bill as the loop gets longer?\n"
        "   2. Why is finish_reason='length' more dangerous on a tool call than on prose?\n"
        "   3. A tool raised, and the loop kept going. Who decided what the model should\n"
        "      read about that failure, and why is that string a prompt?"
    )


if __name__ == "__main__":
    main()
